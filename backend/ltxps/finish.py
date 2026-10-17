"""Finishing touch for videos made on this PC: a small model at a small size looks soft, so the clip is cleaned, enlarged and sharpened.

This makes the picture look crisper and bigger. It cannot invent detail that the model never drew; for truly sharp video use the cloud option.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .editor.media import probe


def target_size(width: int, height: int, factor: float = 2.0, max_side: int = 1920) -> tuple[int, int]:
    k = min(factor, max_side / max(width, height))
    k = max(k, 1.0)
    return int(round(width * k / 2)) * 2, int(round(height * k / 2)) * 2


def sharpen(path: Path, ffmpeg: str | None, factor: float = 2.0) -> dict[str, Any]:
    """Re-encodes `path` in place. Returns what was done; never raises (a failed finish leaves the original video untouched)."""
    if not ffmpeg:
        return {"sharpened": False, "reason": "ffmpeg not found"}
    try:
        info = probe(path)
        w, h = int(info.width or 0), int(info.height or 0)
        if not w or not h:
            return {"sharpened": False, "reason": "no picture"}
        tw, th = target_size(w, h, factor)
        out = Path(tempfile.mkdtemp(prefix="vk-sharp-")) / "sharp.mp4"
        vf = f"hqdn3d=1.2:1.2:3:3,scale={tw}:{th}:flags=lanczos,unsharp=5:5:0.9:5:5:0.0,unsharp=3:3:0.5:3:3:0.0"
        cmd = [ffmpeg, "-y", "-i", str(path), "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(out)]
        subprocess.run(cmd, capture_output=True, timeout=600, check=True)
        if out.exists() and out.stat().st_size > 0:
            os.replace(out, path)
            return {"sharpened": True, "from": f"{w}x{h}", "to": f"{tw}x{th}"}
    except Exception:  # noqa: BLE001 - a finishing touch must never lose the video that was just made
        pass
    return {"sharpened": False, "reason": "could not re-encode"}


def attach_reference_audio(video: Path, reference: Path, ffmpeg: str | None) -> dict[str, Any]:
    """Takes the sound of the reference video and puts it on the finished video (in place). Does nothing when the reference has no sound or the
    finished video already has some. Never raises."""
    if not ffmpeg:
        return {"audio": False, "reason": "ffmpeg not found"}
    try:
        if probe(video).has_audio:
            return {"audio": True, "reason": "already has sound"}
        if not probe(reference).has_audio:
            return {"audio": False, "reason": "the reference video has no sound"}
        out = Path(tempfile.mkdtemp(prefix="vk-audio-")) / "with_audio.mp4"
        cmd = [ffmpeg, "-y", "-i", str(video), "-i", str(reference), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest",
               "-movflags", "+faststart", str(out)]
        subprocess.run(cmd, capture_output=True, timeout=300, check=True)
        if out.exists() and out.stat().st_size > 0:
            os.replace(out, video)
            return {"audio": True, "reason": "added from the reference video"}
    except Exception:  # noqa: BLE001 - the video must survive a sound problem
        pass
    return {"audio": False, "reason": "could not add the sound"}


# ---- AI upscaler: Real-ESRGAN (ncnn build). It redraws each frame at 4x size, which adds real fine detail (fur, skin, leaves) instead of only sharpening.
ESRGAN_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip"
ESRGAN_EXE = "realesrgan-ncnn-vulkan.exe"
ESRGAN_MODEL = "realesrgan-x4plus"
ESRGAN_TIMEOUT = 15 * 60
FAIL_HOURS = 12


def _download_zip(url: str, target: Path) -> None:
    import httpx

    tmp = target.with_suffix(".part")
    with httpx.stream("GET", url, timeout=httpx.Timeout(120, connect=20), follow_redirects=True) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    tmp.replace(target)


def ensure_esrgan(tools: Path, download: Any = None) -> Path | None:
    """Path of the upscaler program, downloading it (about 45 MB, once) when it is not there yet. None when it cannot be had (not Windows, offline...)."""
    import sys
    import time
    import zipfile

    folder = tools / "realesrgan"
    exe = folder / ESRGAN_EXE
    if exe.exists():
        return exe
    if download is None and not sys.platform.startswith("win"):
        return None
    marker = tools / "realesrgan.failed"
    try:
        if marker.exists() and time.time() - marker.stat().st_mtime < FAIL_HOURS * 3600:
            return None
        tools.mkdir(parents=True, exist_ok=True)
        archive = tools / "realesrgan.zip"
        (download or _download_zip)(ESRGAN_URL, archive)
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                if name.startswith(("/", "..")) or ".." in Path(name).parts or name.lower().endswith((".jpg", ".mp4")):
                    continue  # never write outside the folder; skip the demo pictures
                z.extract(name, folder)
        archive.unlink(missing_ok=True)
        return exe if exe.exists() else None
    except Exception:  # noqa: BLE001 - offline or blocked: plain sharpening takes over
        try:
            (tools / "realesrgan.failed").write_text("download failed")
        except OSError:
            pass
        return None


def _run_tool(cmd: list[str], cwd: Path, timeout: float, progress: Any, cancel: Any) -> int:
    import time

    p = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    started = time.time()
    while True:
        try:
            return p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            progress()
            if (cancel is not None and cancel.is_set()) or time.time() - started > timeout:
                p.kill()
                return -9


def ai_upscale(path: Path, ffmpeg: str | None, tools: Path, *, on_status: Any = None, cancel: Any = None, ensure: Any = None, runner: Any = None) -> dict[str, Any]:
    """Re-draws every frame with Real-ESRGAN, scales to 2x the original size (at most 1920), and replaces `path`. Never raises; on any problem the
    original video stays and the reason is returned so plain sharpening can take over."""
    say = on_status or (lambda _m: None)
    if not ffmpeg:
        return {"sharpened": False, "reason": "ffmpeg not found"}
    work = Path(tempfile.mkdtemp(prefix="vk-esrgan-"))
    try:
        say("Getting the AI upscaler ready")
        exe = (ensure or ensure_esrgan)(tools)
        if exe is None:
            return {"sharpened": False, "reason": "the AI upscaler is not available on this PC"}
        info = probe(path)
        w, h, fps = int(info.width or 0), int(info.height or 0), float(info.fps or 24)
        if not w or not h:
            return {"sharpened": False, "reason": "no picture"}
        src, dst = work / "in", work / "out"
        src.mkdir()
        dst.mkdir()
        subprocess.run([ffmpeg, "-y", "-i", str(path), "-vsync", "0", str(src / "%05d.png")], capture_output=True, timeout=300, check=True)
        total = len(list(src.glob("*.png")))
        if not total:
            return {"sharpened": False, "reason": "no frames"}
        cmd = [str(exe), "-i", str(src), "-o", str(dst), "-n", ESRGAN_MODEL, "-s", "4", "-f", "png", "-m", str(Path(exe).parent / "models")]
        code = (runner or _run_tool)(cmd, Path(exe).parent, ESRGAN_TIMEOUT, lambda: say(f"Adding detail: frame {len(list(dst.glob('*.png')))} of {total}"), cancel)
        done = len(list(dst.glob("*.png")))
        if code != 0 or done < total:
            if code not in (-9,):
                try:
                    tools.mkdir(parents=True, exist_ok=True)
                    (tools / "realesrgan.failed").write_text(f"exit {code}")
                except OSError:
                    pass
            return {"sharpened": False, "reason": "the AI upscaler stopped" if code == -9 else "the AI upscaler did not run on this graphics card"}
        tw, th = target_size(w, h, 2.0)
        out = work / "final.mp4"
        say("Putting the detailed frames back into a video")
        cmd2 = [ffmpeg, "-y", "-framerate", f"{fps:.3f}", "-i", str(dst / "%05d.png"), "-i", str(path), "-map", "0:v:0", "-map", "1:a?",
                "-vf", f"scale={tw}:{th}:flags=lanczos,unsharp=3:3:0.35:3:3:0.0", "-c:v", "libx264", "-preset", "medium", "-crf", "15", "-pix_fmt", "yuv420p",
                "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(out)]
        subprocess.run(cmd2, capture_output=True, timeout=900, check=True)
        if out.exists() and out.stat().st_size > 0:
            os.replace(out, path)
            return {"sharpened": True, "method": "ai", "from": f"{w}x{h}", "to": f"{tw}x{th}"}
        return {"sharpened": False, "reason": "could not re-encode"}
    except Exception:  # noqa: BLE001 - the finished video must never be lost to a finishing touch
        return {"sharpened": False, "reason": "the AI upscaler could not finish"}
    finally:
        import shutil

        shutil.rmtree(work, ignore_errors=True)
