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
