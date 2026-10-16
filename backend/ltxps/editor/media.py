"""ffmpeg helpers: probing, thumbnails and a progress-reporting runner.

Only the ffmpeg executable is required (the pip package imageio-ffmpeg bundles
it), so the app has no dependency on a system-wide install or on ffprobe.
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..system import ffmpeg_path

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif_still"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".gif", ".wmv", ".flv"}

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class FfmpegError(RuntimeError):
    pass


class RenderCancelled(Exception):
    pass


@dataclass
class MediaInfo:
    kind: str  # video | image | audio
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool


def require_ffmpeg() -> str:
    exe = ffmpeg_path()
    if not exe:
        raise FfmpegError("ffmpeg is not available. Reinstall the app runtime from Settings.")
    return exe


def _parse_duration(text: str) -> float:
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if not m:
        return 0.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def probe(path: Path) -> MediaInfo:
    exe = require_ffmpeg()
    proc = subprocess.run(
        [exe, "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=NO_WINDOW,
    )
    text = proc.stderr
    if "Invalid data found" in text or "No such file" in text or "Stream #" not in text:
        raise FfmpegError(f"Cannot read media file: {path.name}")
    duration = _parse_duration(text)
    video = re.search(r"Stream #\S+.*?Video:.*", text)
    has_audio = bool(re.search(r"Stream #\S+.*?Audio:", text))
    width = height = 0
    fps = 0.0
    if video:
        line = video.group(0)
        # Skip hex-like "0x31637661" tokens when matching WxH.
        dims = re.search(r"[\s,](\d{2,5})x(\d{2,5})(?=[\s,\[])", line)
        if dims:
            width, height = int(dims.group(1)), int(dims.group(2))
        f = re.search(r"([\d.]+)\s*fps", line)
        if f:
            fps = float(f.group(1))
        else:
            tbr = re.search(r"([\d.]+)\s*tbr", line)
            fps = float(tbr.group(1)) if tbr else 0.0

    ext = path.suffix.lower()
    if not video and has_audio:
        kind = "audio"
    elif ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp"} or (video and duration == 0.0):
        kind = "image"
    else:
        kind = "video"
    if kind == "image":
        duration = 0.0
        has_audio = False
    return MediaInfo(kind=kind, duration=duration, width=width, height=height, fps=fps, has_audio=has_audio)


def thumbnail(src: Path, dest: Path, info: MediaInfo, width: int = 320) -> bool:
    """Writes a JPEG poster frame. Audio files get no thumbnail."""
    if info.kind == "audio":
        return False
    exe = require_ffmpeg()
    dest.parent.mkdir(parents=True, exist_ok=True)
    seek = ["-ss", f"{min(0.5, info.duration / 2):.2f}"] if info.kind == "video" and info.duration > 0.2 else []
    proc = subprocess.run(
        [exe, "-y", "-hide_banner", "-loglevel", "error", *seek, "-i", str(src), "-frames:v", "1", "-vf", f"scale={width}:-2", str(dest)],
        capture_output=True,
        creationflags=NO_WINDOW,
    )
    return proc.returncode == 0 and dest.exists()


def run_ffmpeg(
    args: list[str],
    total_seconds: float = 0.0,
    on_progress: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
    stall_timeout: float = 180.0,
) -> None:
    """Runs ffmpeg, reporting 0..1 progress parsed from -progress output.

    A watchdog kills ffmpeg if it emits no progress for `stall_timeout` seconds,
    so a wedged filter graph becomes an error instead of a frozen app.
    """
    exe = require_ffmpeg()
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-progress", "pipe:1", "-nostats", *args]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=NO_WINDOW,
    )
    stderr_chunks: list[str] = []

    def drain_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_chunks.append(line)

    t = threading.Thread(target=drain_stderr, daemon=True)
    t.start()
    last_beat = time.monotonic()
    stalled = threading.Event()
    done = threading.Event()

    def watchdog() -> None:
        while not done.wait(1.0):
            if time.monotonic() - last_beat > stall_timeout and proc.poll() is None:
                stalled.set()
                proc.kill()
                return

    wd = threading.Thread(target=watchdog, daemon=True)
    wd.start()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            last_beat = time.monotonic()
            if cancel is not None and cancel.is_set():
                proc.kill()
                raise RenderCancelled()
            if on_progress and total_seconds > 0 and line.startswith("out_time_us="):
                try:
                    us = int(line.split("=", 1)[1])
                    on_progress(max(0.0, min(1.0, us / 1_000_000 / total_seconds)))
                except ValueError:
                    pass
        proc.wait()
    finally:
        done.set()
        if proc.poll() is None:
            proc.kill()
        t.join(timeout=2)
    if cancel is not None and cancel.is_set():
        raise RenderCancelled()
    if stalled.is_set():
        raise FfmpegError(f"ffmpeg stopped responding for {int(stall_timeout)}s and was cancelled.")
    if proc.returncode != 0:
        tail = "".join(stderr_chunks)[-1200:].strip()
        raise FfmpegError(tail or f"ffmpeg exited with code {proc.returncode}")
    if on_progress:
        on_progress(1.0)
