"""Quick local motion preview: a character picture is bent to follow the body movement of a reference video. Free, offline, no key.

MediaPipe finds the body points (shoulders, elbows, wrists, hips, knees, ankles) in the picture and in every video frame. The picture is then
warped so its points move the way the video's points moved. This is a rough puppet-style preview, NOT realistic video: the clothes and face are
stretched, not re-drawn. Use the online option for a realistic result.
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
MAX_SIDE = 768
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
    options = vision.PoseLandmarkerOptions(base_options=mpt.BaseOptions(model_asset_path=str(model_file)), num_poses=1, min_pose_detection_confidence=0.4, output_segmentation_masks=True)
    landmarker = vision.PoseLandmarker.create_from_options(options)

    def detect(rgb: Any) -> list[tuple[float, float]] | None:
        import numpy as np

        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        res = landmarker.detect(image)
        if not res.pose_landmarks:
            return None
        lm = res.pose_landmarks[0]
        try:
            detect.last_mask = np.array(res.segmentation_masks[0].numpy_view(), dtype=np.float32).squeeze() if res.segmentation_masks else None
        except Exception:  # noqa: BLE001 - the cut-out is a bonus; GrabCut takes over without it
            detect.last_mask = None
        return [(float(lm[i].x), float(lm[i].y)) for i in POINTS]

    detect.last_mask = None  # type: ignore[attr-defined]
    return detect


# ---- TensorFlow: MoveNet (a TensorFlow Lite model from Google). Needs the `tensorflow` package, which the app installs only on request.
MOVENET_URL = "https://tfhub.dev/google/lite-model/movenet/singlepose/lightning/tflite/float16/4?lite-format=tflite"
MOVENET_NAME = "movenet_lightning.tflite"
MOVENET_COCO = (0, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16)  # the same 13 body points, in MoveNet's 17-point order


def tensorflow_available() -> bool:
    import importlib.util

    return any(importlib.util.find_spec(n) is not None for n in ("tensorflow", "ai_edge_litert", "tflite_runtime"))


def ensure_movenet(folder: Path, download: Callable[[str, Path], None] | None = None) -> Path:
    target = folder / MOVENET_NAME
    if target.exists() and target.stat().st_size > 100_000:
        return target
    folder.mkdir(parents=True, exist_ok=True)
    try:
        (download or _download)(MOVENET_URL, target)
    except Exception as exc:  # noqa: BLE001
        raise LocalMotionError(f"The MoveNet file could not be downloaded ({type(exc).__name__}). Download it from {MOVENET_URL} and save it as {MOVENET_NAME} in: {folder}") from exc
    if not target.exists() or target.stat().st_size < 100_000:
        raise LocalMotionError(f"The MoveNet file did not download correctly. Save {MOVENET_URL} as {MOVENET_NAME} in {folder}")
    return target


def tensorflow_detector(model_file: Path, interpreter: Any = None) -> Detector:
    """MoveNet Lightning through TensorFlow Lite. `interpreter` is injected by the tests."""
    if interpreter is None:
        try:
            try:
                from ai_edge_litert.interpreter import Interpreter  # type: ignore
            except ImportError:
                try:
                    from tflite_runtime.interpreter import Interpreter  # type: ignore
                except ImportError:
                    import tensorflow as tf  # type: ignore

                    Interpreter = tf.lite.Interpreter  # noqa: N806
        except Exception as exc:  # noqa: BLE001
            raise LocalMotionError("TensorFlow is not installed. Press “Install TensorFlow” on the Motion control page (about 300 MB, once).") from exc
        interpreter = Interpreter(model_path=str(model_file))
    interpreter.allocate_tensors()
    inp, out = interpreter.get_input_details()[0], interpreter.get_output_details()[0]
    size = int(inp["shape"][1])

    def detect(rgb: Any) -> list[tuple[float, float]] | None:
        import cv2
        import numpy as np

        h, w = rgb.shape[:2]
        side = max(h, w)
        pad = np.zeros((side, side, 3), np.uint8)
        pad[:h, :w] = rgb
        small = cv2.resize(pad, (size, size), interpolation=cv2.INTER_AREA)
        interpreter.set_tensor(inp["index"], small[None].astype(inp["dtype"]))
        interpreter.invoke()
        kp = np.asarray(interpreter.get_tensor(out["index"])).reshape(-1, 3)  # (y, x, score) in 0..1 of the padded square
        picked = kp[list(MOVENET_COCO)]
        if float(picked[:, 2].mean()) < 0.2:
            return None
        return [(float(x * side / w), float(y * side / h)) for y, x, _ in picked]

    detect.last_mask = None  # type: ignore[attr-defined]
    return detect


def _fit(w: int, h: int, side: int = MAX_SIDE) -> tuple[int, int]:
    k = min(1.0, side / max(w, h))
    return max(2, int(round(w * k / 2)) * 2), max(2, int(round(h * k / 2)) * 2)


def _torso(pts: Any) -> float:
    import numpy as np

    sh, hip = (pts[1] + pts[2]) / 2, (pts[7] + pts[8]) / 2
    return float(max(np.linalg.norm(sh - hip), 1.0))


# local indices in POINTS: 0 nose, 1/2 shoulders, 3/4 elbows, 5/6 wrists, 7/8 hips, 9/10 knees, 11/12 ankles
LIMBS = ((1, 3), (3, 5), (2, 4), (4, 6), (7, 9), (9, 11), (8, 10), (10, 12))  # (from, to) in the order shoulder->elbow->wrist, hip->knee->ankle


def _rot(v: Any, a: float) -> Any:
    import numpy as np

    c, s = np.cos(a), np.sin(a)
    return np.array([c * v[0] - s * v[1], s * v[0] + c * v[1]], dtype=np.float32)


def _ang(v: Any) -> float:
    import math

    return math.atan2(float(v[1]), float(v[0]))


def _wrap(a: float) -> float:
    import math

    return (a + math.pi) % (2 * math.pi) - math.pi


def pose_to(base: Any, ref: Any, cur: Any, scale: float) -> Any:
    """Where the character's body points go when the person in the video moves from `ref` to `cur`.

    The character keeps its own limb lengths; each limb turns by the same angle the real limb turned (forward kinematics).
    """
    import numpy as np

    out = base.copy()
    hip_b, hip_r, hip_c = (base[7] + base[8]) / 2, (ref[7] + ref[8]) / 2, (cur[7] + cur[8]) / 2
    sh_b, sh_r, sh_c = (base[1] + base[2]) / 2, (ref[1] + ref[2]) / 2, (cur[1] + cur[2]) / 2
    hip_n = hip_b + (hip_c - hip_r) * scale
    d_torso = _wrap(_ang(sh_c - hip_c) - _ang(sh_r - hip_r))
    sh_n = hip_n + _rot(sh_b - hip_b, d_torso)
    for i in (7, 8):
        out[i] = hip_n + _rot(base[i] - hip_b, d_torso)
    for i in (1, 2):
        out[i] = sh_n + _rot(base[i] - sh_b, d_torso)
    d_head = _wrap(_ang(cur[0] - sh_c) - _ang(ref[0] - sh_r))
    out[0] = sh_n + _rot(base[0] - sh_b, d_head)
    for a, b in LIMBS:
        # shoulders/hips were placed above; each elbow/knee is placed by its upper bone before the lower bone hangs from it
        d = _wrap(_ang(cur[b] - cur[a]) - _ang(ref[b] - ref[a]))
        out[b] = out[a] + _rot(base[b] - base[a], d)
    return out


def bones(pts: Any) -> list[tuple[Any, Any]]:
    """The skeleton as line segments (torso, head, shoulder bar, hip bar and the eight limb bones)."""
    sh, hip = (pts[1] + pts[2]) / 2, (pts[7] + pts[8]) / 2
    out = [(hip, sh), (sh, pts[0]), (pts[1], pts[2]), (pts[7], pts[8])]
    out += [(pts[a], pts[b]) for a, b in LIMBS]
    return out


def _seg_dist(gx: Any, gy: Any, a: Any, b: Any) -> Any:
    import numpy as np

    ab = b - a
    L2 = float(ab @ ab) or 1.0
    t = np.clip(((gx - a[0]) * ab[0] + (gy - a[1]) * ab[1]) / L2, 0, 1)
    return np.hypot(gx - (a[0] + t * ab[0]), gy - (a[1] + t * ab[1]))


def _bone_matrix(a: Any, b: Any, a2: Any, b2: Any) -> tuple[Any, Any]:
    """Rotation (2x2) and translation that carry bone (a, b) onto (a2, b2). Length is kept, so limbs turn instead of stretching."""
    import numpy as np

    d = _wrap(_ang(b2 - a2) - _ang(b - a))
    c, s = np.cos(d), np.sin(d)
    R = np.array([[c, -s], [s, c]], dtype=np.float32)
    return R, a2 - R @ a


def skin(layer: Any, src: Any, dst: Any, grid: int = 4) -> Any:
    """Linear-blend skinning: every pixel follows the nearby bones, so an arm swings like an arm. `layer` is any HxWxC float image."""
    import cv2
    import numpy as np

    h, w = layer.shape[:2]
    gw, gh = max(8, w // grid), max(8, h // grid)
    gx, gy = np.meshgrid(np.linspace(0, w - 1, gw, dtype=np.float32), np.linspace(0, h - 1, gh, dtype=np.float32))
    sb, db = bones(src), bones(dst)
    acc_x, acc_y, tot = np.zeros_like(gx), np.zeros_like(gx), np.full_like(gx, 1e-4)
    for k, ((a, b), (a2, b2)) in enumerate(zip(sb, db)):
        length = float(np.linalg.norm(b2 - a2)) + float(np.linalg.norm(b - a))
        sigma = max(length * 0.11, 5.0)
        wgt = np.exp(-(_seg_dist(gx, gy, a2, b2) / sigma) ** 2) * (3.0 if k < 4 else 1.0)  # the trunk holds its shape against the limbs  # weight is measured around where the bone ends up (backward mapping)
        R, t = _bone_matrix(a2, b2, a, b)  # destination -> source
        sx = R[0, 0] * gx + R[0, 1] * gy + t[0]
        sy = R[1, 0] * gx + R[1, 1] * gy + t[1]
        acc_x += wgt * sx
        acc_y += wgt * sy
        tot += wgt
    # far from every bone the picture stays where it is
    near = np.exp(-(np.min([_seg_dist(gx, gy, a2, b2) for a2, b2 in db], axis=0) / 40.0) ** 2)
    mx = near * (acc_x / tot) + (1 - near) * gx
    my = near * (acc_y / tot) + (1 - near) * gy
    map_x = cv2.resize(mx.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
    map_y = cv2.resize(my.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
    return cv2.remap(layer, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def person_mask(img: Any, pts: Any, seg: Any = None) -> Any:
    """0..1 mask of the person. Uses MediaPipe's own cut-out when there is one, otherwise GrabCut seeded with the skeleton."""
    import cv2
    import numpy as np

    h, w = img.shape[:2]
    if seg is not None:
        m = cv2.resize(np.asarray(seg, dtype=np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
        if 0.02 < float((m > 0.5).mean()) < 0.9:
            return np.clip(m, 0, 1)
    gc = np.full((h, w), cv2.GC_BGD, np.uint8)
    x0, y0 = np.maximum(pts.min(axis=0) - 0.25 * _torso(pts), 0).astype(int)
    x1, y1 = np.minimum(pts.max(axis=0) + 0.35 * _torso(pts), [w - 1, h - 1]).astype(int)
    gc[y0:y1, x0:x1] = cv2.GC_PR_BGD
    thick = max(3, int(_torso(pts) * 0.22))
    prob = np.zeros((h, w), np.uint8)
    for a, b in bones(pts):
        cv2.line(prob, tuple(int(v) for v in a), tuple(int(v) for v in b), 255, thick * 3)
    gc[prob > 0] = cv2.GC_PR_FGD
    sure = np.zeros((h, w), np.uint8)
    for a, b in bones(pts):
        cv2.line(sure, tuple(int(v) for v in a), tuple(int(v) for v in b), 255, max(2, thick // 2))
    gc[sure > 0] = cv2.GC_FGD
    try:
        bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
        cv2.grabCut(img, gc, None, bgd, fgd, 4, cv2.GC_INIT_WITH_MASK)
        m = np.where((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD), 1.0, 0.0).astype(np.float32)
    except cv2.error:
        m = (prob > 0).astype(np.float32)
    if m.mean() < 0.01:
        m = (prob > 0).astype(np.float32)
    return m


def _plate(img: Any, mask: Any) -> Any:
    """The picture with the person removed (filled in from the surroundings) so the background stays still behind the moving person."""
    import cv2
    import numpy as np

    hard = cv2.dilate((mask > 0.4).astype(np.uint8) * 255, np.ones((9, 9), np.uint8))
    small = max(1, int(max(img.shape[:2]) / 384))
    if small > 1:
        im, mk = cv2.resize(img, None, fx=1 / small, fy=1 / small, interpolation=cv2.INTER_AREA), cv2.resize(hard, None, fx=1 / small, fy=1 / small, interpolation=cv2.INTER_NEAREST)
        filled = cv2.inpaint(im, mk, 6, cv2.INPAINT_TELEA)
        filled = cv2.resize(filled, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_CUBIC)
        keep = (hard == 0)[..., None]
        return np.where(keep, img, filled)
    return cv2.inpaint(img, hard, 6, cv2.INPAINT_TELEA)


def render(img: Any, mask: Any, plate: Any, src: Any, dst: Any) -> Any:
    """One frame: the person layer is skinned to the new pose and laid over the clean background."""
    import cv2
    import numpy as np

    soft = cv2.GaussianBlur(mask, (0, 0), 1.2)
    layer = np.dstack([img.astype(np.float32) * soft[..., None], soft]).astype(np.float32)
    moved = skin(layer, src, dst)
    alpha = np.clip(moved[..., 3:4], 0, 1)
    rgb = moved[..., :3] / np.maximum(alpha, 1e-3)
    out = rgb * alpha + plate.astype(np.float32) * (1 - alpha)
    return np.clip(out, 0, 255).astype(np.uint8)


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
    mask = person_mask(img, base, getattr(detect, "last_mask", None))
    plate = _plate(img, mask)

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
        cur = p if p is not None else last
        cur = cur if last is None else (0.65 * cur + 0.35 * last)  # a little smoothing removes the shaking of the detector
        track.append(cur)
        last = cur

    tmp = Path(tempfile.mkdtemp(prefix="vk-local-motion-"))
    raw = tmp / "raw.mp4"
    out = cv2.VideoWriter(str(raw), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    if not out.isOpened():
        raise LocalMotionError("The video could not be written.")
    try:
        for i, p in enumerate(track):
            if cancel is not None and cancel.is_set():
                raise LocalMotionError("Cancelled.")
            out.write(render(img, mask, plate, base, pose_to(base, ref, p, scale)))
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
