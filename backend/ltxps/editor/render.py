"""Compiles an editor Project into a single ffmpeg invocation.

Every clip is normalised to the canvas (size, fps, pixel format, 48 kHz stereo)
so that concat/xfade never see mismatched streams. Clips with no audio get
generated silence of the exact length.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .media import NO_WINDOW, require_ffmpeg
from .project import Clip, ExportOptions, Project
from .textimage import render_text_png

SAMPLE_RATE = 48000
QUALITY_CRF = {"low": 28, "medium": 23, "high": 18}
VP9_CRF = {"low": 38, "medium": 32, "high": 25}

PRESET_FILTERS = {
    "bw": "hue=s=0",
    "sepia": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131:0",
    "vintage": "curves=preset=vintage",
    "cool": "colorbalance=rs=-.1:bs=.15:rm=-.05:bm=.1",
    "warm": "colorbalance=rs=.15:bs=-.15:rm=.08:bm=-.08",
    "faded": "curves=all='0/0.12 1/0.9',eq=saturation=0.8",
    "dramatic": "curves=preset=increase_contrast,eq=saturation=1.15",
    "negative": "negate",
}


@dataclass
class AssetRef:
    path: Path
    kind: str  # video | image | audio
    duration: float
    has_audio: bool
    width: int = 0
    height: int = 0


@dataclass
class RenderPlan:
    args: list[str]
    total: float
    output: Path
    warnings: list[str] = field(default_factory=list)


class PlanError(ValueError):
    pass


# ---------------------------------------------------------------- durations
def source_span(clip: Clip, asset: AssetRef) -> float:
    """Seconds of source media the clip consumes."""
    if asset.kind == "image":
        return clip.image_duration
    end = clip.trim_out if clip.trim_out > 0 else asset.duration
    if asset.duration > 0:
        end = min(end, asset.duration)
    return max(0.05, end - clip.trim_in)


def clip_duration(clip: Clip, asset: AssetRef) -> float:
    if asset.kind == "image":
        return clip.image_duration
    return source_span(clip, asset) / clip.speed


def effective_transition(prev: Clip, prev_dur: float, cur_dur: float) -> float:
    if prev.transition.type == "none":
        return 0.0
    return max(0.0, min(prev.transition.duration, prev_dur * 0.5, cur_dur * 0.5))


def timeline_duration(project: Project, assets: dict[str, AssetRef]) -> float:
    total = 0.0
    prev: Clip | None = None
    prev_dur = 0.0
    for clip in project.clips:
        d = clip_duration(clip, assets[clip.asset_id])
        if prev is not None:
            total -= effective_transition(prev, prev_dur, d)
        total += d
        prev, prev_dur = clip, d
    return total


# ---------------------------------------------------------------- helpers
def _f(x: float) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".") or "0"


def _hex(color: str) -> str:
    return "0x" + color.lstrip("#").upper()


def atempo_chain(speed: float) -> list[str]:
    out: list[str] = []
    s = speed
    while s > 2.0:
        out.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        out.append("atempo=0.5")
        s /= 0.5
    if abs(s - 1.0) > 1e-6:
        out.append(f"atempo={_f(s)}")
    return out


_FFMPEG_MAJOR: int | None = None


def ffmpeg_major() -> int:
    global _FFMPEG_MAJOR
    if _FFMPEG_MAJOR is None:
        try:
            out = subprocess.run([require_ffmpeg(), "-version"], capture_output=True, text=True, creationflags=NO_WINDOW).stdout
            m = re.search(r"version\s+[nN]?(\d+)", out)
            _FFMPEG_MAJOR = int(m.group(1)) if m else 6
        except OSError:
            _FFMPEG_MAJOR = 6
    return _FFMPEG_MAJOR


# ---------------------------------------------------------------- per-clip chains
def _video_chain(clip: Clip, asset: AssetRef, idx: int, project: Project, dur: float) -> str:
    c = project.canvas
    W, H = c.width, c.height
    f: list[str] = []
    is_image = asset.kind == "image"
    if clip.reverse and not is_image:
        f.append("reverse")
    speed = 1.0 if is_image else clip.speed
    f.append(f"setpts=(PTS-STARTPTS)/{_f(speed)}")
    f.append(f"fps={c.fps}")

    if clip.rotate == 90:
        f.append("transpose=1")
    elif clip.rotate == 180:
        f.append("hflip,vflip")
    elif clip.rotate == 270:
        f.append("transpose=2")
    if clip.flip_h:
        f.append("hflip")
    if clip.flip_v:
        f.append("vflip")

    bg = _hex(c.background)
    if clip.fit == "fit":
        f.append(f"scale={W}:{H}:force_original_aspect_ratio=decrease:flags=bicubic")
        f.append(f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={bg}")
    elif clip.fit == "fill":
        f.append(f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=bicubic")
        f.append(f"crop={W}:{H}")
    else:
        f.append(f"scale={W}:{H}:flags=bicubic")
    if clip.zoom > 1.0001:
        z = _f(clip.zoom)
        f.append(f"scale=iw*{z}:ih*{z}:flags=bicubic")
        f.append(f"crop={W}:{H}:(iw-{W})*{_f(0.5 + clip.pan_x * 0.5)}:(ih-{H})*{_f(0.5 + clip.pan_y * 0.5)}")

    a = clip.adjust
    eq_parts = []
    if a.brightness:
        eq_parts.append(f"brightness={_f(a.brightness / 100)}")
    if a.contrast:
        eq_parts.append(f"contrast={_f(1 + a.contrast / 100)}")
    if a.saturation:
        eq_parts.append(f"saturation={_f(1 + a.saturation / 100)}")
    if abs(a.gamma - 1) > 1e-6:
        eq_parts.append(f"gamma={_f(a.gamma)}")
    if eq_parts:
        f.append("eq=" + ":".join(eq_parts))
    if a.hue:
        f.append(f"hue=h={_f(a.hue)}")
    if clip.preset != "none":
        f.append(PRESET_FILTERS[clip.preset])
    if clip.denoise:
        f.append("hqdn3d=3:3:6:6")
    if clip.blur > 0:
        f.append(f"gblur=sigma={_f(clip.blur)}")
    if clip.sharpen > 0:
        f.append(f"unsharp=5:5:{_f(clip.sharpen)}:5:5:0")
    if clip.vignette:
        f.append("vignette=PI/4")

    f.append("setsar=1")
    f.append("format=yuv420p")
    if clip.fade_in > 0:
        f.append(f"fade=t=in:st=0:d={_f(min(clip.fade_in, dur))}")
    if clip.fade_out > 0:
        d = min(clip.fade_out, dur)
        f.append(f"fade=t=out:st={_f(max(0, dur - d))}:d={_f(d)}")
    f.append(f"trim=duration={_f(dur)}")
    f.append("setpts=PTS-STARTPTS")
    f.append(f"fps={c.fps}")  # constant frame rate on the output link (xfade requires it)
    return f"[{idx}:v]" + ",".join(f) + f"[v{idx}]"


def _audio_chain(clip: Clip, asset: AssetRef, idx: int, dur: float, head: float, tail: float, start: float) -> str:
    """Audio for one clip, already positioned at its absolute timeline start.

    Clips are mixed (not concatenated): ffmpeg's audio `concat` can deadlock on
    long timelines. `head`/`tail` are the overlaps shared with neighbouring
    clips; linear fades over those overlaps sum to a constant-level crossfade.
    """
    use_source = asset.kind != "image" and asset.has_audio and not clip.muted
    if not use_source:
        f = [f"anullsrc=r={SAMPLE_RATE}:cl=stereo", f"atrim=duration={_f(dur)}", "asetpts=PTS-STARTPTS"]
        src = ""
    else:
        f = [f"aresample={SAMPLE_RATE}", "aformat=channel_layouts=stereo:sample_fmts=fltp"]
        if clip.reverse:
            f.append("areverse")
        f += atempo_chain(clip.speed)
        if abs(clip.volume - 1) > 1e-6:
            f.append(f"volume={_f(clip.volume)}")
        f.append("asetpts=PTS-STARTPTS")
        # Pad (silence) or cut so audio length matches the video exactly.
        f.append(f"apad=whole_dur={_f(dur)}")
        f.append(f"atrim=duration={_f(dur)}")
        src = f"[{idx}:a]"
    fi = max(clip.fade_in, head)
    fo = max(clip.fade_out, tail)
    if fi > 0:
        f.append(f"afade=t=in:st=0:d={_f(min(fi, dur))}")
    if fo > 0:
        d = min(fo, dur)
        f.append(f"afade=t=out:st={_f(max(0, dur - d))}:d={_f(d)}")
    f.append("asetpts=PTS-STARTPTS")
    ms = int(round(start * 1000))
    if ms > 0:
        f.append(f"adelay={ms}|{ms}")
    return src + ",".join(f) + f"[a{idx}]"


# ---------------------------------------------------------------- main entry
def build_plan(project: Project, assets: dict[str, AssetRef], opts: ExportOptions, output: Path, workdir: Path) -> RenderPlan:
    if not project.clips:
        raise PlanError("Add at least one clip to the timeline before exporting.")
    for clip in project.clips:
        if clip.asset_id not in assets:
            raise PlanError("A clip refers to a media file that is no longer in the library.")
        if assets[clip.asset_id].kind == "audio":
            raise PlanError("Audio files belong on the audio track, not the video track.")
    for ac in project.audio:
        if ac.asset_id not in assets:
            raise PlanError("An audio clip refers to a media file that is no longer in the library.")

    workdir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    canvas = project.canvas
    fps = canvas.fps
    out_w = opts.width or canvas.width
    out_h = opts.height or canvas.height
    out_fps = opts.fps or fps
    if opts.preview:
        out_w = min(out_w, 640)
        out_h = max(2, round(out_w * canvas.height / canvas.width))
        out_fps = min(out_fps, 24)
    if opts.format == "gif":
        out_w = min(out_w, 640)
        out_h = max(2, round(out_w * canvas.height / canvas.width))
        out_fps = min(out_fps, 15)
    out_w -= out_w % 2
    out_h -= out_h % 2

    args: list[str] = []
    graph: list[str] = []
    durations: list[float] = []
    want_audio = opts.include_audio and opts.format != "gif"

    n = len(project.clips)

    # ---- timeline geometry
    for clip in project.clips:
        durations.append(clip_duration(clip, assets[clip.asset_id]))
    overlap = [0.0] * (n + 1)  # overlap[i] = shared with the previous clip; overlap[n] = 0
    starts = [0.0] * n
    for i in range(1, n):
        overlap[i] = effective_transition(project.clips[i - 1], durations[i - 1], durations[i])
        starts[i] = starts[i - 1] + durations[i - 1] - overlap[i]
    total = starts[-1] + durations[-1]

    # ---- inputs: one per clip, then text images, then audio-track clips
    for i, clip in enumerate(project.clips):
        asset = assets[clip.asset_id]
        dur = durations[i]
        if asset.kind == "image":
            args += ["-loop", "1", "-framerate", str(fps), "-t", _f(dur), "-i", str(asset.path)]
        else:
            span = source_span(clip, asset)
            if clip.reverse and span > 60:
                warnings.append("Reversing clips longer than a minute uses a lot of memory.")
            args += ["-ss", _f(clip.trim_in), "-t", _f(span), "-i", str(asset.path)]
        graph.append(_video_chain(clip, asset, i, project, dur))

    # ---- join video
    any_transition = any(c.transition.type != "none" for c in project.clips[:-1])
    if n == 1:
        v_last = "v0"
    elif not any_transition:
        graph.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vcat]")
        v_last = "vcat"
    else:
        v_run, run = "v0", durations[0]
        for i in range(1, n):
            prev = project.clips[i - 1]
            td = overlap[i]
            nv = f"vj{i}"
            if td > 0:
                graph.append(
                    f"[{v_run}][v{i}]xfade=transition={prev.transition.type}:duration={_f(td)}:offset={_f(run - td)}[{nv}]"
                )
                run = run + durations[i] - td
            else:
                graph.append(f"[{v_run}][v{i}]concat=n=2:v=1:a=0,fps={fps}[{nv}]")  # fps resets the timebase xfade needs
                run = run + durations[i]
            v_run = nv
        v_last = v_run

    # ---- text overlays: Pillow PNG per overlay, composited with `overlay`
    cur = v_last
    next_input = n
    for k, t in enumerate(project.texts):
        png = workdir / f"text{k}.png"
        render_text_png(t, canvas.height, canvas.width, png)
        args += ["-loop", "1", "-framerate", str(fps), "-t", _f(total), "-i", str(png)]
        idx = next_input
        next_input += 1
        end = t.start + t.duration
        chain = ["format=rgba"]
        if t.fade_in > 0:
            chain.append(f"fade=t=in:st={_f(t.start)}:d={_f(min(t.fade_in, t.duration))}:alpha=1")
        if t.fade_out > 0:
            d = min(t.fade_out, t.duration)
            chain.append(f"fade=t=out:st={_f(max(t.start, end - d))}:d={_f(d)}:alpha=1")
        graph.append(f"[{idx}:v]" + ",".join(chain) + f"[tx{k}]")
        nxt = f"vt{k}"
        graph.append(
            f"[{cur}][tx{k}]overlay=x=(W-w)*{_f(t.x)}:y=(H-h)*{_f(t.y)}:enable='between(t,{_f(t.start)},{_f(end)})':format=auto[{nxt}]"
        )
        cur = nxt
    v_last = cur

    # ---- audio: every clip is delayed to its start and mixed (skipped when not exporting audio)
    if want_audio:
        mix: list[str] = []
        for i, clip in enumerate(project.clips):
            graph.append(_audio_chain(clip, assets[clip.asset_id], i, durations[i], overlap[i], overlap[i + 1], starts[i]))
            mix.append(f"[a{i}]")
        for ac in project.audio:
            asset = assets[ac.asset_id]
            if not asset.has_audio and asset.kind != "audio":
                warnings.append("An audio-track clip has no audio and was skipped.")
                continue
            idx = next_input
            next_input += 1
            end = ac.trim_out if ac.trim_out > 0 else asset.duration
            span = max(0.05, (min(end, asset.duration) if asset.duration > 0 else end) - ac.trim_in)
            args += ["-ss", _f(ac.trim_in), "-t", _f(span), "-i", str(asset.path)]
            f = [f"aresample={SAMPLE_RATE}", "aformat=channel_layouts=stereo:sample_fmts=fltp"]
            if abs(ac.volume - 1) > 1e-6:
                f.append(f"volume={_f(ac.volume)}")
            if ac.fade_in > 0:
                f.append(f"afade=t=in:st=0:d={_f(min(ac.fade_in, span))}")
            if ac.fade_out > 0:
                d = min(ac.fade_out, span)
                f.append(f"afade=t=out:st={_f(max(0, span - d))}:d={_f(d)}")
            ms = int(round(ac.start * 1000))
            if ms > 0:
                f.append(f"adelay={ms}|{ms}")
            graph.append(f"[{idx}:a]" + ",".join(f) + f"[ax{idx}]")
            mix.append(f"[ax{idx}]")
        if len(mix) > 1:
            graph.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=longest:dropout_transition=0:normalize=0[amix]")
            a_final = "amix"
        else:
            a_final = "a0"
        if abs(project.master_volume - 1) > 1e-6:
            graph.append(f"[{a_final}]volume={_f(project.master_volume)}[amaster]")
            a_final = "amaster"
        graph.append(f"[{a_final}]alimiter=limit=0.97[aout]")

    # ---- final video shaping
    final: list[str] = []
    if (out_w, out_h) != (canvas.width, canvas.height):
        final.append(f"scale={out_w}:{out_h}:flags=bicubic")
    if out_fps != fps:
        final.append(f"fps={out_fps}")
    if opts.format == "gif":
        final.append("split[g1][g2];[g1]palettegen=stats_mode=diff[pal];[g2][pal]paletteuse=dither=bayer:bayer_scale=4")
    if final:
        graph.append(f"[{v_last}]" + ",".join(final) + "[vout]")
    else:
        graph.append(f"[{v_last}]null[vout]")

    graph_text = ";".join(graph)
    if len(graph_text) > 6000:
        script = workdir / "graph.txt"
        script.write_text(graph_text, encoding="utf-8")
        args += ["-/filter_complex", str(script)] if ffmpeg_major() >= 7 else ["-filter_complex_script", str(script)]
    else:
        args += ["-filter_complex", graph_text]

    args += ["-map", "[vout]"]
    if want_audio:
        args += ["-map", "[aout]"]
    args += ["-t", _f(total)]

    if opts.format == "mp4":
        crf = QUALITY_CRF[opts.quality] if not opts.preview else 32
        preset = "ultrafast" if opts.preview else "medium"
        args += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        if want_audio:
            args += ["-c:a", "aac", "-b:a", "192k" if not opts.preview else "96k"]
    elif opts.format == "webm":
        args += ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(VP9_CRF[opts.quality]), "-row-mt", "1", "-pix_fmt", "yuv420p"]
        if want_audio:
            args += ["-c:a", "libopus", "-b:a", "128k"]
    else:  # gif
        args += ["-loop", "0"]
    args.append(str(output))
    return RenderPlan(args=args, total=total, output=output, warnings=warnings)
