"""Engine contract shared by the real LTX engine and the test engine."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

from ..editor.media import NO_WINDOW, require_ffmpeg
from ..jobs import JobContext


@dataclass
class GenRequest:
    mode: str  # t2v | i2v
    prompt: str
    negative_prompt: str
    width: int
    height: int
    frames: int
    fps: int
    steps: int
    guidance: float
    seed: int
    model_id: str
    image_path: Path | None = None
    end_image_path: Path | None = None


class VideoEngine(Protocol):
    def generate(self, req: GenRequest, out_path: Path, ctx: JobContext) -> dict:
        """Writes an MP4 to out_path. Returns extra metadata (e.g. strategy used)."""

    def unload(self) -> None: ...


def write_video(frames: Iterable, width: int, height: int, fps: int, out_path: Path) -> int:
    """Encodes uint8 RGB frames (H, W, 3) to H.264 by piping raw video into ffmpeg."""
    exe = require_ffmpeg()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        exe, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
        "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    count = 0
    try:
        assert proc.stdin is not None
        for frame in frames:
            proc.stdin.write(frame.tobytes())
            count += 1
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
    if proc.wait() != 0:
        raise RuntimeError(f"Could not encode the video: {err[-400:]}")
    return count
