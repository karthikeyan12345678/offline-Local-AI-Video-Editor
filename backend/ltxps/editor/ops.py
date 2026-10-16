"""One-click tools that turn a library item into a new library item."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..db import Asset
from .media import run_ffmpeg

Progress = Callable[[float], None]


class ToolError(ValueError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    id: str
    label: str
    description: str
    accepts: tuple[str, ...]  # asset kinds
    ext: str
    out_kind: str


TOOLS: dict[str, ToolSpec] = {
    t.id: t
    for t in (
        ToolSpec("interpolate", "Smooth motion", "Create in-between frames to raise the frame rate (slow on long clips).", ("video",), "mp4", "video"),
        ToolSpec("upscale", "Upscale", "Enlarge 2x or 3x with Lanczos scaling and light sharpening.", ("video", "image"), "mp4", "video"),
        ToolSpec("stabilize", "Stabilize", "Reduce camera shake.", ("video",), "mp4", "video"),
        ToolSpec("loop", "Loop", "Repeat a clip several times.", ("video",), "mp4", "video"),
        ToolSpec("boomerang", "Boomerang", "Play forward, then backward (audio is dropped).", ("video",), "mp4", "video"),
        ToolSpec("extract_frame", "Extract frame", "Save a still image from the clip.", ("video",), "png", "image"),
        ToolSpec("extract_audio", "Extract audio", "Save the sound as an audio file.", ("video",), "mp3", "audio"),
        ToolSpec("remove_audio", "Remove audio", "Make a silent copy.", ("video",), "mp4", "video"),
        ToolSpec("to_gif", "Make GIF", "Convert to an animated GIF.", ("video",), "gif", "video"),
        ToolSpec("convert", "Convert", "Re-encode as MP4 or WebM.", ("video",), "mp4", "video"),
    )
}

H264 = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]


def _num(params: dict[str, Any], key: str, default: float, lo: float, hi: float) -> float:
    try:
        v = float(params.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ToolError(f"'{key}' must be a number.") from exc
    if not lo <= v <= hi:
        raise ToolError(f"'{key}' must be between {lo:g} and {hi:g}.")
    return v


def output_ext(tool: str, params: dict[str, Any]) -> str:
    if tool == "extract_audio":
        return "wav" if params.get("format") == "wav" else "mp3"
    if tool == "convert":
        return "webm" if params.get("format") == "webm" else "mp4"
    return TOOLS[tool].ext


def run_tool(
    tool: str,
    asset: Asset,
    params: dict[str, Any],
    dest: Path,
    on_progress: Progress | None = None,
    cancel: threading.Event | None = None,
) -> None:
    spec = TOOLS.get(tool)
    if spec is None:
        raise ToolError(f"Unknown tool '{tool}'.")
    if asset.kind not in spec.accepts:
        raise ToolError(f"'{spec.label}' works on {' or '.join(spec.accepts)} files, not {asset.kind}.")
    src = str(asset.path)
    dur = asset.duration
    run = lambda args, total=dur: run_ffmpeg(args, total, on_progress, cancel)  # noqa: E731

    if tool == "interpolate":
        fps = int(_num(params, "fps", 48, 24, 120))
        vf = f"minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
        run(["-i", src, "-vf", vf, *H264, *(["-c:a", "copy"] if asset.has_audio else ["-an"]), str(dest)])

    elif tool == "upscale":
        factor = _num(params, "factor", 2, 1.5, 3)
        if max(asset.width, asset.height) * factor > 3840:
            raise ToolError("The result would be wider than 3840 px. Pick a smaller factor.")
        vf = f"scale=trunc(iw*{factor}/2)*2:trunc(ih*{factor}/2)*2:flags=lanczos,unsharp=5:5:0.6:5:5:0"
        if asset.kind == "image":
            run(["-loop", "1", "-t", "3", "-i", src, "-vf", vf, "-r", "24", *H264, "-an", str(dest)], 3)
        else:
            run(["-i", src, "-vf", vf, *H264, *(["-c:a", "copy"] if asset.has_audio else ["-an"]), str(dest)])

    elif tool == "stabilize":
        run(["-i", src, "-vf", "deshake=rx=32:ry=32:edge=mirror", *H264, *(["-c:a", "copy"] if asset.has_audio else ["-an"]), str(dest)])

    elif tool == "loop":
        times = int(_num(params, "times", 3, 2, 20))
        run(["-stream_loop", str(times - 1), "-i", src, *H264, *(["-c:a", "aac", "-b:a", "192k"] if asset.has_audio else ["-an"]), str(dest)], dur * times)

    elif tool == "boomerang":
        if dur > 60:
            raise ToolError("Boomerang needs the whole clip in memory. Use a clip under a minute.")
        graph = "[0:v]split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1:a=0[v]"
        run(["-i", src, "-filter_complex", graph, "-map", "[v]", *H264, str(dest)], dur * 2)

    elif tool == "extract_frame":
        at = params.get("time", "last")
        if at == "last":
            run(["-sseof", "-0.5", "-i", src, "-update", "1", "-q:v", "1", str(dest)], 0)
        else:
            t = _num(params, "time", 0, 0, max(dur, 0.0))
            run(["-ss", f"{t:.3f}", "-i", src, "-frames:v", "1", "-q:v", "1", str(dest)], 0)

    elif tool == "extract_audio":
        if not asset.has_audio:
            raise ToolError("This clip has no audio.")
        codec = ["-c:a", "pcm_s16le"] if dest.suffix == ".wav" else ["-c:a", "libmp3lame", "-q:a", "2"]
        run(["-i", src, "-vn", *codec, str(dest)])

    elif tool == "remove_audio":
        run(["-i", src, "-c:v", "copy", "-an", str(dest)])

    elif tool == "to_gif":
        width = int(_num(params, "width", 480, 120, 960))
        fps = int(_num(params, "fps", 12, 4, 20))
        graph = f"fps={fps},scale={width}:-2:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4"
        run(["-i", src, "-vf", graph, "-loop", "0", str(dest)])

    elif tool == "convert":
        if dest.suffix == ".webm":
            run(["-i", src, "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "30", "-row-mt", "1", "-c:a", "libopus", "-b:a", "128k", str(dest)])
        else:
            run(["-i", src, *H264, "-c:a", "aac", "-b:a", "192k", str(dest)])
