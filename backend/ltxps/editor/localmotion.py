"""Quick local motion preview: a character picture is bent to follow the body movement of a reference video. Free, offline, no key.

MediaPipe finds the body points (shoulders, elbows, wrists, hips, knees, ankles) in the picture and in every video frame. The picture is then
warped so its points move the way the video's points moved. This is a rough puppet-style preview, NOT Kling quality: the clothes and face are
stretched, not re-drawn. Use the cloud option (Kling) for a realistic result.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from .ai import AIError

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
MODEL_NAME = "pose_landmarker_lite.task"
# MediaPipe pose indices: nose, shoulders, elbows, wrists, hips, knees, ankles
POINTS = (0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)
MAX_SIDE = 512
MAX_SECONDS = 12
Detector = Callable[[Any], "list[tuple[float, float]] | None"]  # RGB image -> normalised (x, y) for POINTS, or None when nobody is found
Progress = Callable[[float, str], None]


class LocalMotionError(AIError):
    """Message is safe to show to the user."""


def model_path(folder: Path) -> Path:
    return folder / MODEL_NAME


def ensure_model(folder: Path, download: Callable[[str, Path], None] | None = None) -> Path:
    target = model_path(folder)
    if target.exists() and target.stat().st_size > 100_000:
        return target
    folder.mkdir(parents=True, exist_ok=True)
    try:
        (download or _download)(MODEL_URL, target)
    except Exception as exc:  # noqa: BLE001 - any network problem gets the same plain instruction
        raise LocalMotionError(f"The small body-finder file could not be downloaded ({type(exc).__name__}). Check the internet once, or download it from {MODEL_URL} "
                               f"and put it in this folder: {folder}") from exc
    if not target.exists() or target.stat().st_size < 100_000:
        raise LocalMotionError(f"The body-finder file did not download correctly. Download {MODEL_URL} and put it in {folder}")
    return target


def _download(url: str, target: Path) -> None:
    import httpx

    tmp = target.with_suffix(".part")
    with httpx.stream("GET", url, timeout=httpx.Timeout(60, connect=20), follow_redirects=True) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    tmp.replace(target)


def mediapipe_detector(model_file: Path) -> Detector:
    try:
        import mediapipe as mp  # type: ignore
        from mediapipe.tasks import python as mpt  # type: ignore
        from mediapipe.tasks.python import vision  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise LocalMotionError("MediaPipe is not installed. Open Settings > Modules and update, or run: pip install mediapipe") from exc
    options = vision.PoseLandmarkerOptions(base_options=mpt.BaseOptions(model_asset_path=str(model_file)), num_poses=1, min_pose_detection_confidence=0.4)
    landmarker = vision.PoseLandmarker.create_from_options(options)

    def detect(rgb: Any) -> list[tuple[float, float]] | None:
        import numpy as np

        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        res = landmarker.detect(image)
        if not res.pose_landmarks:
            return None
        lm = res.pose_landmarks[0]
        return [(float(lm[i].x), float(lm[i].y)) for i in POINTS]

    return detect


def _fit(w: int, h: int, side: int = MAX_SIDE) -> tuple[int, int]:
    k = min(1.0, side / max(w, h))
    return max(2, int(round(w * k / 2)) * 2), max(2, int(round(h * k / 2)) * 2)


def _torso(pts: Any) -> float:
    import numpy as np

    sh, hip = (pts[1] + pts[2]) / 2, (pts[7] + pts[8]) / 2
    return float(max(np.linalg.norm(sh - hip), 1.0))


def warp(image: Any, src: Any, dst: Any) -> Any:
    """Moves the picture so the body points `src` end up at `dst` (pixel coordinates). Everything far from the body stays put."""
    import cv2
    import numpy as np

    h, w = image.shape[:2]
    gh, gw = 48, 48
    ys, xs = np.mgrid[0:gh, 0:gw]
    gx, gy = xs * (w - 1) / (gw - 1), ys * (h - 1) / (gh - 1)
    sigma = max(_torso(src) * 0.45, 8.0)
    num_x, num_y, den = np.zeros_like(gx, dtype=np.float32), np.zeros_like(gx, dtype=np.float32), np.full_like(gx, 0.12, dtype=np.float32)
    for (sx, sy), (tx, ty) in zip(src, dst):
        wgt = np.exp(-(((gx - sx) ** 2 + (gy - sy) ** 2) / (2 * sigma ** 2))).astype(np.float32)
        num_x += wgt * (tx - sx)
        num_y += wgt * (ty - sy)
        den += wgt
    # backward mapping: the pixel that lands at (x, y) came from (x - shift)
    map_x = cv2.resize((gx - num_x / den).astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
    map_y = cv2.resize((gy - num_y / den).astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
    return cv2.remap(image, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def run(image_path: Path, video_path: Path, dest: Path, detect: Detector, *, strength: float = 1.0, on_progress: Progress = lambda _p, _m: None,
        cancel: Any = None) -> dict[str, Any]:
    import cv2
    import numpy as np

    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if img is None:
        raise LocalMotionError("The character picture could not be read.")
    w, h = _fit(img.shape[1], img.shape[0])
    img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    on_progress(0.05, "Finding the body in the picture")
    found = detect(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    if not found:
        raise LocalMotionError("No person was found in the character picture. Use a clear picture of one person, head to toe.")
    base = np.array([(x * w, y * h) for x, y in found], dtype=np.float32)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise LocalMotionError("The motion video could not be opened.")
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    fps = min(max(fps, 8.0), 30.0)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, int(round((cap.get(cv2.CAP_PROP_FPS) or fps) / fps)))
    max_frames = int(MAX_SECONDS * fps)
    poses: list[Any] = []
    vw = vh = 0
    idx = 0
    try:
        while len(poses) < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % step == 0:
                if cancel is not None and cancel.is_set():
                    raise LocalMotionError("Cancelled.")
                fw, fh = _fit(frame.shape[1], frame.shape[0])
                vw, vh = fw, fh
                small = cv2.resize(frame, (fw, fh), interpolation=cv2.INTER_AREA)
                p = detect(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
                poses.append(np.array([(x * fw, y * fh) for x, y in p], dtype=np.float32) if p else None)
                if total:
                    on_progress(0.1 + 0.5 * min(1.0, idx / total), f"Reading the movement ({len(poses)} frames)")
            idx += 1
    finally:
        cap.release()
    good = [p for p in poses if p is not None]
    if len(good) < max(3, len(poses) // 4):
        raise LocalMotionError("A person could not be followed in the motion video. Use a video where one person is fully visible.")
    ref = good[0]
    scale = _torso(base) / _torso(ref) * strength
    last = ref
    track = []
    for p in poses:
        last = p if p is not None else last
        track.append(last)

    tmp = Path(tempfile.mkdtemp(prefix="vk-local-motion-"))
    raw = tmp / "raw.mp4"
    out = cv2.VideoWriter(str(raw), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    if not out.isOpened():
        raise LocalMotionError("The video could not be written.")
    try:
        for i, p in enumerate(track):
            if cancel is not None and cancel.is_set():
                raise LocalMotionError("Cancelled.")
            target = base + (p - ref) * scale
            out.write(warp(img, base, target))
            on_progress(0.6 + 0.35 * (i + 1) / len(track), f"Drawing frame {i + 1} of {len(track)}")
    finally:
        out.release()
    dest.parent.mkdir(parents=True, exist_ok=True)
    _to_h264(raw, dest)
    on_progress(1.0, "Done")
    return {"frames": len(track), "fps": fps, "engine": "mediapipe"}


def _to_h264(raw: Path, dest: Path) -> None:
    """OpenCV writes MPEG-4 part 2, which many players and browsers cannot show. Re-encode to H.264 when ffmpeg exists."""
    try:
        from ..system import ffmpeg_path

        ff = ffmpeg_path()
        if ff:
            subprocess.run([ff, "-y", "-i", str(raw), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", str(dest)],
                           capture_output=True, timeout=300, check=True)
            if dest.exists() and dest.stat().st_size > 0:
                return
    except (OSError, subprocess.SubprocessError):
        pass
    dest.write_bytes(raw.read_bytes())
