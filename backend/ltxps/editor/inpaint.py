"""AI object edits on video frames: remove something, change it, or add something (a cap, shoes…) inside a marked place.

How it works (all on this PC):
  1. The place comes from the person's drawing (rectangle, circle, scribble, arrow) or from a detected face (head / face).
  2. A Stable Diffusion *inpainting* model repaints only that place, using the rest of the picture as context.
  3. mode "patch": repaint ONE frame and blend it into every frame of the range. Fast. Right for a still camera (remove a hill, a sign, a person who stands still).
     mode "track": repaint a frame every few frames and blend each into the frames near it. Slower. Right when the person or camera moves.
The result is a new video file; the original is never touched.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

from .ai import AIError
from .media import NO_WINDOW, FfmpegError, probe, require_ffmpeg

Progress = Callable[[float, str], None]
MAX_SECONDS = 8.0
MAX_FRAMES = 240
NEGATIVE = "blurry, distorted, deformed, text, watermark, logo, frame, border, low quality"


class InpaintError(AIError):
    """Message is safe to show to the user."""


# ---------------------------------------------------------------- masks
def mask_from_shapes(shapes: list[dict[str, Any]], size: tuple[int, int], grow: float = 0.015):
    """White where the person marked. `points` are 0-1 of the picture. Open scribbles are thickened, closed ones are filled."""
    from PIL import Image, ImageDraw, ImageFilter

    w, h = size
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    thick = max(10, int(min(w, h) * 0.05))
    for sh in shapes:
        pts = [(float(p[0]) * w, float(p[1]) * h) for p in sh.get("points", [])]
        if len(pts) < 2 and sh.get("type") != "pen":
            continue
        kind = sh.get("type", "pen")
        if kind in ("rect", "highlight") and len(pts) >= 2 and kind == "rect":
            d.rectangle([min(pts[0][0], pts[-1][0]), min(pts[0][1], pts[-1][1]), max(pts[0][0], pts[-1][0]), max(pts[0][1], pts[-1][1])], fill=255)
        elif kind == "ellipse" and len(pts) >= 2:
            d.ellipse([min(pts[0][0], pts[-1][0]), min(pts[0][1], pts[-1][1]), max(pts[0][0], pts[-1][0]), max(pts[0][1], pts[-1][1])], fill=255)
        elif len(pts) >= 3 and ((pts[0][0] - pts[-1][0]) ** 2 + (pts[0][1] - pts[-1][1]) ** 2) ** 0.5 < 0.08 * max(w, h):
            d.polygon(pts, fill=255)  # a loop drawn around something
        else:
            for a, b in zip(pts, pts[1:]):
                d.line([a, b], fill=255, width=thick)
            for p in pts[:: max(1, len(pts) // 40)]:
                d.ellipse([p[0] - thick / 2, p[1] - thick / 2, p[0] + thick / 2, p[1] + thick / 2], fill=255)
    if m.getbbox() is None:
        raise InpaintError("The marked place is empty. Draw a box or circle around what should change, then ask again.")
    k = max(3, int(min(w, h) * grow) // 2 * 2 + 1)
    return m.filter(ImageFilter.MaxFilter(k))


def mask_from_face(face: dict[str, float], size: tuple[int, int], part: str = "head"):
    """`face` is {'x','y','w','h'} (0-1, top-left). 'head' = hair and the space above it (a cap, a hat); 'face' = the face itself."""
    from PIL import Image, ImageDraw

    w, h = size
    fx, fy, fw, fh = face["x"] * w, face["y"] * h, face["w"] * w, face["h"] * h
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    if part == "face":
        d.ellipse([fx - fw * 0.1, fy - fh * 0.1, fx + fw * 1.1, fy + fh * 1.15], fill=255)
    else:
        d.ellipse([fx - fw * 0.28, fy - fh * 0.85, fx + fw * 1.28, fy + fh * 0.32], fill=255)
    return m


# ---------------------------------------------------------------- one picture
def edit_frame(pipe: Any, img, mask, prompt: str, seed: int = 7, steps: int = 20, guidance: float = 7.5):
    """Repaints the white part of `mask` inside `img` (both PIL). Works on a crop around the mask so small things stay sharp."""
    from PIL import Image, ImageFilter

    w, h = img.size
    x0, y0, x1, y1 = mask.getbbox() or (0, 0, w, h)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    side = int(max(x1 - x0, y1 - y0) * 1.8)
    side = max(side, 256)
    side = min(side, min(w, h))
    left = int(min(max(0, cx - side / 2), w - side))
    top = int(min(max(0, cy - side / 2), h - side))
    box = (left, top, left + side, top + side)
    crop, mcrop = img.crop(box).convert("RGB"), mask.crop(box)
    res = 512
    ci, mi = crop.resize((res, res), Image.LANCZOS), mcrop.resize((res, res), Image.LANCZOS)
    try:
        import torch

        gen = torch.Generator("cpu").manual_seed(int(seed))
        out = pipe(prompt=prompt, negative_prompt=NEGATIVE, image=ci, mask_image=mi, num_inference_steps=steps, guidance_scale=guidance, strength=1.0, generator=gen,
                   width=res, height=res).images[0]
    except ImportError:
        out = pipe(prompt=prompt, negative_prompt=NEGATIVE, image=ci, mask_image=mi).images[0]
    out = out.convert("RGB").resize((side, side), Image.LANCZOS)
    soft = mcrop.filter(ImageFilter.GaussianBlur(max(2, side // 60)))
    merged = Image.composite(out, crop, soft)
    res_img = img.convert("RGB").copy()
    res_img.paste(merged, (left, top))
    return res_img


# ---------------------------------------------------------------- the model
_pipe: Any = None
_pipe_dir = ""


def _vae_slicing(pipe: Any) -> None:
    """Newer diffusers moved this to the VAE and removed it from the pipeline; older ones only have it on the pipeline."""
    for target, name in ((getattr(pipe, "vae", None), "enable_slicing"), (pipe, "enable_vae_slicing")):
        fn = getattr(target, name, None)
        if callable(fn):
            try:
                fn()
                return
            except Exception:  # noqa: BLE001 - slicing only saves memory; never worth failing for
                continue


def load_pipe(model_dir: str | Path):
    global _pipe, _pipe_dir
    if _pipe is not None and _pipe_dir == str(model_dir):
        return _pipe
    try:
        import torch
        from diffusers import StableDiffusionInpaintPipeline
    except ImportError as exc:
        raise InpaintError("AI object edits need PyTorch and diffusers, which the full VK Editor installs on the Welcome screen.") from exc
    cuda = torch.cuda.is_available()
    try:
        pipe = StableDiffusionInpaintPipeline.from_pretrained(str(model_dir), torch_dtype=torch.float16 if cuda else torch.float32, variant="fp16" if cuda else None,
                                                              safety_checker=None, requires_safety_checker=False, local_files_only=True)
    except Exception as exc:  # noqa: BLE001
        raise InpaintError("The object-edit model could not be loaded. Open the Models page and install “Object editor (AI inpainting)” again.") from exc
    if cuda:
        pipe.enable_model_cpu_offload()
        try:
            pipe.enable_attention_slicing()
        except Exception:  # noqa: BLE001
            pass
        _vae_slicing(pipe)
    pipe.set_progress_bar_config(disable=True)
    _pipe, _pipe_dir = pipe, str(model_dir)
    return pipe


# ---------------------------------------------------------------- a video range
def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise FfmpegError(r.stderr.decode("utf-8", "ignore")[-400:] or "ffmpeg failed")


def _face_boxes(frames: list[Path], every: int) -> dict[int, dict[str, float] | None]:
    from .ai import YUNET

    try:
        import cv2
    except ImportError:
        return {}
    if not YUNET.exists():
        return {}
    out: dict[int, dict[str, float] | None] = {}
    det = None
    for i in range(0, len(frames), every):
        im = cv2.imread(str(frames[i]))
        if im is None:
            continue
        h, w = im.shape[:2]
        if det is None:
            det = cv2.FaceDetectorYN.create(str(YUNET), "", (w, h), 0.5, 0.3, 50)
        det.setInputSize((w, h))
        _, faces = det.detect(im)
        out[i] = None if faces is None or not len(faces) else (lambda f: {"x": float(f[0]) / w, "y": float(f[1]) / h, "w": float(f[2]) / w, "h": float(f[3]) / h})(max(faces, key=lambda r: r[2] * r[3]))
    return out


def edit_video(src: str | Path, start: float, duration: float, out: Path, *, prompt: str, shapes: list[dict[str, Any]] | None = None, part: str = "",
               mode: str = "patch", pipe: Any = None, model_dir: str | Path | None = None, on_progress: Progress | None = None, cancel: threading.Event | None = None) -> dict[str, Any]:
    """Writes `out` (mp4): the range [start, start+duration] of `src` with the marked place repainted. Returns facts about the result."""
    from PIL import Image

    prompt = prompt.strip()
    if len(prompt) < 3:
        raise InpaintError("Say what should be there instead, for example “empty grass field” or “a white cap”.")
    if not shapes and part not in ("head", "face"):
        raise InpaintError("Mark the place first: draw a box or circle on the picture where the change should happen, then ask again.")
    info = probe(Path(src))
    if not info.width or not info.height:
        raise InpaintError("Could not read the picture of this video.")
    duration = min(max(0.2, duration), MAX_SECONDS)
    fps = min(30.0, info.fps or 25.0)
    if duration * fps > MAX_FRAMES:
        fps = MAX_FRAMES / duration
    scale = min(1.0, 1280 / max(info.width, info.height))
    ew, eh = max(2, round(info.width * scale / 2) * 2), max(2, round(info.height * scale / 2) * 2)
    tmp = Path(tempfile.mkdtemp(prefix="vk-inpaint-"))
    say = on_progress or (lambda p, m: None)

    def check() -> None:
        if cancel is not None and cancel.is_set():
            raise InpaintError("Cancelled.")

    try:
        say(0.02, "Reading the video")
        _run([require_ffmpeg(), "-v", "error", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(src), "-an", "-vf", f"fps={fps:.4f},scale={ew}:{eh}", str(tmp / "f_%05d.png")])
        frames = sorted(tmp.glob("f_*.png"))
        if not frames:
            raise InpaintError("No picture could be read from that part of the video.")
        n = len(frames)
        pipe = pipe or load_pipe(model_dir or "")
        faces = _face_boxes(frames, max(1, round(fps / 3))) if part in ("head", "face") else {}
        static_mask = mask_from_shapes(shapes, (ew, eh)) if shapes else None

        def mask_for(i: int):
            if static_mask is not None:
                return static_mask
            ks = [k for k in faces if faces[k]]
            if not ks:
                return None
            k = min(ks, key=lambda q: abs(q - i))
            return mask_from_face(faces[k], (ew, eh), part)  # type: ignore[arg-type]

        if mode == "track":
            step = max(1, round(fps / 6))
            keys = list(range(0, n, step))
        else:
            keys = [n // 2]
        if static_mask is None and not any(mask_for(i) is not None for i in keys):
            raise InpaintError("I could not find a face in that part of the video. Draw a box where the change should happen instead.")
        edited: dict[int, Any] = {}
        for j, i in enumerate(keys):
            check()
            m = mask_for(i)
            if m is None:
                continue
            say(0.08 + 0.7 * j / len(keys), f"Repainting picture {j + 1} of {len(keys)}")
            edited[i] = (edit_frame(pipe, Image.open(frames[i]).convert("RGB"), m, prompt), m)
        if not edited:
            raise InpaintError("Nothing could be repainted there.")
        ek = sorted(edited)
        from PIL import ImageFilter

        for i in range(n):
            check()
            k = min(ek, key=lambda q: abs(q - i)) if mode == "track" else ek[0]
            done_img, m = edited[k]
            cur = Image.open(frames[i]).convert("RGB")
            if mode == "track":
                m2 = mask_for(i) or m
                soft = m2.filter(ImageFilter.GaussianBlur(max(2, min(ew, eh) // 100)))
                Image.composite(done_img, cur, soft).save(frames[i])
            else:
                soft = m.filter(ImageFilter.GaussianBlur(max(2, min(ew, eh) // 100)))
                Image.composite(done_img, cur, soft).save(frames[i])
            if i % 10 == 0:
                say(0.8 + 0.12 * i / n, "Putting the new picture back into the video")
        say(0.93, "Saving the video")
        cmd = [require_ffmpeg(), "-y", "-v", "error", "-framerate", f"{fps:.4f}", "-i", str(tmp / "f_%05d.png"), "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(src),
               "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)]
        out.parent.mkdir(parents=True, exist_ok=True)
        _run(cmd)
        return {"frames": n, "repainted": len(edited), "mode": mode, "fps": fps, "duration": duration, "width": ew, "height": eh}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _face_in_picture(path: Path) -> dict[str, float] | None:
    from .ai import YUNET

    try:
        import cv2
    except ImportError:
        return None
    if not YUNET.exists():
        return None
    im = cv2.imread(str(path))
    if im is None:
        return None
    h, w = im.shape[:2]
    det = cv2.FaceDetectorYN.create(str(YUNET), "", (w, h), 0.5, 0.3, 50)
    _, faces = det.detect(im)
    if faces is None or not len(faces):
        return None
    f = max(faces, key=lambda r: r[2] * r[3])
    return {"x": float(f[0]) / w, "y": float(f[1]) / h, "w": float(f[2]) / w, "h": float(f[3]) / h}


def edit_image(src: str | Path, out: Path, *, prompt: str, shapes: list[dict[str, Any]] | None = None, part: str = "", pipe: Any = None,
               model_dir: str | Path | None = None, on_progress: Progress | None = None) -> dict[str, Any]:
    """The same repaint for a still picture (a photo on the timeline). Writes a PNG."""
    from PIL import Image

    prompt = prompt.strip()
    if len(prompt) < 3:
        raise InpaintError("Say what should be there instead, for example “empty grass field” or “a white cap”.")
    if not shapes and part not in ("head", "face"):
        raise InpaintError("Mark the place first: draw a box or circle on the picture where the change should happen, then ask again.")
    say = on_progress or (lambda p, m: None)
    img = Image.open(src).convert("RGB")
    if max(img.size) > 1600:
        k = 1600 / max(img.size)
        img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
    if shapes:
        mask = mask_from_shapes(shapes, img.size)
    else:
        box = _face_in_picture(Path(src))
        if not box:
            raise InpaintError("I could not find a face in this picture. Draw a box where the change should happen instead.")
        mask = mask_from_face(box, img.size, part)
    say(0.1, "Loading the AI model")
    pipe = pipe or load_pipe(model_dir or "")
    say(0.4, "Repainting")
    res = edit_frame(pipe, img, mask, prompt)
    out.parent.mkdir(parents=True, exist_ok=True)
    res.save(out, "PNG")
    say(1.0, "Done")
    return {"width": res.width, "height": res.height, "mode": "image"}
