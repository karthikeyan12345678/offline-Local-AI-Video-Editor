"""Compiles an editor Project into a single ffmpeg invocation.

Every clip is normalised to the canvas (size, fps, pixel format, 48 kHz stereo)
so that concat/xfade never see mismatched streams. Clips with no audio get
generated silence of the exact length.
"""

from __future__ import annotations

import math
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .audiofx import fx_filters
from .effects import PRESET_FILTERS, XFADE_NAMES, Fragment, effect_filter, motion_filters, pick_random_transition
from .media import NO_WINDOW, require_ffmpeg
from .project import AudioClip, Clip, ExportOptions, Project, TextOverlay
from .textimage import render_text_png

SAMPLE_RATE = 48000
QUALITY_CRF = {"low": 28, "medium": 23, "high": 18}
VP9_CRF = {"low": 38, "medium": 32, "high": 25}

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


# ---------------------------------------------------------------- transitions support
_XFADE_SUPPORTED: set[str] | None = None


def xfade_supported() -> set[str]:
    """Transition names the installed ffmpeg knows (older builds lack the newest ones)."""
    global _XFADE_SUPPORTED
    if _XFADE_SUPPORTED is None:
        try:
            out = subprocess.run([require_ffmpeg(), "-hide_banner", "-h", "filter=xfade"], capture_output=True, text=True, creationflags=NO_WINDOW)
            names = set(re.findall(r"^\s+([a-z0-9]+)\s+-?\d+\s+\.\.FV", out.stdout + out.stderr, re.M))
            _XFADE_SUPPORTED = (names & set(XFADE_NAMES)) or set(XFADE_NAMES)
        except OSError:
            _XFADE_SUPPORTED = set(XFADE_NAMES)
    return _XFADE_SUPPORTED


def transition_name(clip: Clip, warnings: list[str] | None = None) -> str:
    """The xfade name to use after `clip` (random picks are stable, unsupported names fall back to a cross-fade)."""
    t = clip.transition.type
    supported = xfade_supported()
    if t == "random":
        return pick_random_transition(clip.id, supported)
    if t not in supported:
        if warnings is not None and "A transition is not available in this ffmpeg build; a cross-fade was used instead." not in warnings:
            warnings.append("A transition is not available in this ffmpeg build; a cross-fade was used instead.")
        return "fade"
    return t


# ---------------------------------------------------------------- per-clip chains
def _orient_point(clip: Clip, cx: float, cy: float) -> tuple[float, float]:
    """Move a point given in source-picture coordinates through the clip's rotate/flip."""
    if clip.rotate == 90:
        cx, cy = 1 - cy, cx
    elif clip.rotate == 180:
        cx, cy = 1 - cx, 1 - cy
    elif clip.rotate == 270:
        cx, cy = cy, 1 - cx
    if clip.flip_h:
        cx = 1 - cx
    if clip.flip_v:
        cy = 1 - cy
    return cx, cy


def _follow_stages(clip: Clip, asset: AssetRef, idx: int, project: Project, dur: float, warnings: list[str]) -> list[str] | None:
    """Crop window that follows a tracked subject. Returns None when it cannot be used."""
    fol = clip.follow
    if fol is None or not fol.keys or asset.kind == "image":
        return None
    c = project.canvas
    W, H = c.width, c.height
    sw, sh = (asset.height, asset.width) if clip.rotate in (90, 270) else (asset.width, asset.height)
    if sw <= 0 or sh <= 0:
        warnings.append("Follow-the-subject was skipped for a clip whose size is unknown.")
        return None
    target = W / H
    if sw / sh > target:
        ch, cw = float(sh), sh * target
    else:
        cw, ch = float(sw), sw / target
    cw, ch = max(16, int(cw / fol.zoom)) & ~1, max(16, int(ch / fol.zoom)) & ~1
    cw, ch = min(cw, sw & ~1), min(ch, sh & ~1)
    span_end = clip.trim_in + source_span(clip, asset)
    pts: list[tuple[float, float, float]] = []
    for t_src, cx, cy in fol.keys:
        t_out = ((span_end - t_src) if clip.reverse else (t_src - clip.trim_in)) / clip.speed
        ox, oy = _orient_point(clip, min(1.0, max(0.0, cx)), min(1.0, max(0.0, cy)))
        pts.append((t_out, ox, oy))
    pts.sort()
    if not pts:
        return None
    ts = [p[0] for p in pts]

    def at(t: float) -> tuple[float, float]:
        if t <= ts[0]:
            return pts[0][1], pts[0][2]
        if t >= ts[-1]:
            return pts[-1][1], pts[-1][2]
        lo, hi = 0, len(ts) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if ts[mid] <= t:
                lo = mid
            else:
                hi = mid
        span = ts[hi] - ts[lo]
        k = 0.0 if span <= 1e-9 else (t - ts[lo]) / span
        return pts[lo][1] + (pts[hi][1] - pts[lo][1]) * k, pts[lo][2] + (pts[hi][2] - pts[lo][2]) * k

    def xy(t: float) -> tuple[float, float]:
        cx, cy = at(t)
        return min(max(cx * sw - cw / 2, 0.0), float(sw - cw)), min(max(cy * sh - ch / 2, 0.0), float(sh - ch))

    x0, y0 = xy(0.0)
    moving = max(abs(p[1] - pts[0][1]) * sw for p in pts) > 1 or max(abs(p[2] - pts[0][2]) * sh for p in pts) > 1
    name = f"crop@fol{idx}"
    stages: list[str] = []
    if moving:
        n_frames = int(math.ceil(dur * c.fps)) + 1
        cmds = []
        for n in range(n_frames):
            t = n / c.fps
            x, y = xy(t)
            cmds.append(f"{t:.4f} {name} x {x:.1f}, {name} y {y:.1f}")
        stages.append("sendcmd=c='" + ";".join(cmds) + "'")
    stages.append(f"{name}={cw}:{ch}:{_f(x0)}:{_f(y0)}")
    stages.append(f"scale={W}:{H}:flags=bicubic")
    return stages


def _video_stages(clip: Clip, asset: AssetRef, idx: int, project: Project, dur: float, warnings: list[str]) -> list[str | Fragment]:
    c = project.canvas
    W, H = c.width, c.height
    f: list[str | Fragment] = []
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

    followed = _follow_stages(clip, asset, idx, project, dur, warnings)
    if followed is not None:
        f.extend(followed)
    else:
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

    f.extend(motion_filters(clip.motion, clip.motion_strength, W, H, dur))

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
    for e in clip.effects:
        f.append(effect_filter(e.type, e.amount, W, H))

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
    return f


def _assemble(stages: list[str | Fragment], src: str, out: str, prefix: str) -> list[str]:
    """Turn a stage list into graph statements; fragments (split/blend/stack) get their own labels."""
    stmts: list[str] = []
    cur, buf, n = src, [], 0
    for st in stages:
        if isinstance(st, str):
            buf.append(st)
            continue
        if buf:
            mid = f"{prefix}m{n}"
            stmts.append(f"[{cur}]" + ",".join(buf) + f"[{mid}]")
            cur, buf = mid, []
        nxt = f"{prefix}f{n}"
        for line in st.statements:
            stmts.append(line.replace("{in}", cur).replace("{out}", nxt).replace("{p}", f"{prefix}{n}_"))
        cur, n = nxt, n + 1
    stmts.append(f"[{cur}]" + ",".join(buf or ["null"]) + f"[{out}]")
    return stmts


def _video_chain(clip: Clip, asset: AssetRef, idx: int, project: Project, dur: float, warnings: list[str] | None = None) -> list[str]:
    return _assemble(_video_stages(clip, asset, idx, project, dur, warnings if warnings is not None else []), f"{idx}:v", f"v{idx}", f"c{idx}")


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
        f += fx_filters(clip.audio_fx, clip.pitch, clip.bass, clip.treble, clip.denoise_audio, clip.normalize_audio)
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


def _music_chain(ac: AudioClip, idx: int, span: float, total: float) -> str:
    """One audio-track block: effects, optional loop to the end of the video, fades, and its start offset."""
    f = [f"aresample={SAMPLE_RATE}", "aformat=channel_layouts=stereo:sample_fmts=fltp"]
    f += fx_filters(ac.fx, ac.pitch, ac.bass, ac.treble, ac.denoise, ac.normalize)
    if abs(ac.volume - 1) > 1e-6:
        f.append(f"volume={_f(ac.volume)}")
    length = span
    if ac.loop:
        length = max(0.05, total - ac.start)
        f += ["asetpts=PTS-STARTPTS", f"aloop=loop=-1:size={int(span * SAMPLE_RATE) + 1}", f"atrim=duration={_f(length)}"]
    if ac.fade_in > 0:
        f.append(f"afade=t=in:st=0:d={_f(min(ac.fade_in, length))}")
    if ac.fade_out > 0:
        d = min(ac.fade_out, length)
        f.append(f"afade=t=out:st={_f(max(0, length - d))}:d={_f(d)}")
    f.append("asetpts=PTS-STARTPTS")
    ms = int(round(ac.start * 1000))
    if ms > 0:
        f.append(f"adelay={ms}|{ms}")
    return f"[{idx}:a]" + ",".join(f) + f"[ax{idx}]"


def _text_animation(t: TextOverlay, W: int, H: int) -> tuple[list[str], str, str]:
    """Filters for the text picture plus the overlay x / y expressions that move it in and out."""
    st, end = t.start, t.start + t.duration
    di = min(t.fade_in, t.duration / 2) if t.anim_in != "none" else 0.0
    do = min(t.fade_out, t.duration / 2) if t.anim_out != "none" else 0.0
    chain = ["format=rgba"]
    p_in = f"clip((t-{_f(st)})/{_f(max(di, 0.001))},0,1)"
    q_out = f"clip((t-{_f(end - do)})/{_f(max(do, 0.001))},0,1)"
    e_in = f"(1-pow(1-{p_in},3))"
    e_out = f"pow({q_out},3)"
    dist_v, dist_h = 0.09 * H, 0.12 * W
    dx, dy = "0", "0"
    if di > 0:
        if t.anim_in in ("fade", "slide_up", "slide_down", "slide_left", "slide_right", "zoom"):
            chain.append(f"fade=t=in:st={_f(st)}:d={_f(di)}:alpha=1")
        if t.anim_in == "slide_up":
            dy += f"+{_f(dist_v)}*(1-{e_in})"
        elif t.anim_in == "slide_down":
            dy += f"-{_f(dist_v)}*(1-{e_in})"
        elif t.anim_in == "slide_left":
            dx += f"+{_f(dist_h)}*(1-{e_in})"
        elif t.anim_in == "slide_right":
            dx += f"-{_f(dist_h)}*(1-{e_in})"
    if do > 0:
        if t.anim_out in ("fade", "slide_up", "slide_down", "slide_left", "slide_right", "zoom"):
            chain.append(f"fade=t=out:st={_f(end - do)}:d={_f(do)}:alpha=1")
        if t.anim_out == "slide_up":
            dy += f"-{_f(dist_v)}*{e_out}"
        elif t.anim_out == "slide_down":
            dy += f"+{_f(dist_v)}*{e_out}"
        elif t.anim_out == "slide_left":
            dx += f"-{_f(dist_h)}*{e_out}"
        elif t.anim_out == "slide_right":
            dx += f"+{_f(dist_h)}*{e_out}"
    scale_terms: list[str] = []
    if di > 0 and t.anim_in == "zoom":
        scale_terms.append(f"(0.6+0.4*{e_in})")
    if di > 0 and t.anim_in == "pop":
        scale_terms.append(f"(1+2.70158*pow({p_in}-1,3)+1.70158*pow({p_in}-1,2))")
    if do > 0 and t.anim_out == "zoom":
        scale_terms.append(f"(1+0.35*{e_out})")
    if scale_terms:
        s = "*".join(scale_terms)
        chain.append(f"scale=w='max(2,trunc(iw*{s}/2)*2)':h='max(2,trunc(ih*{s}/2)*2)':eval=frame:flags=bicubic")
    if di > 0 and t.anim_in == "reveal":
        chain.append(f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(X,W*clip((T-{_f(st)})/{_f(di)},0,1)),alpha(X,Y),0)'")
    x = f"(W-w)*{_f(t.x)}+{dx}"
    y = f"(H-h)*{_f(t.y)}+{dy}"
    return chain, x, y


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
        graph.extend(_video_chain(clip, asset, i, project, dur, warnings))

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
                    f"[{v_run}][v{i}]xfade=transition={transition_name(prev, warnings)}:duration={_f(td)}:offset={_f(run - td)}[{nv}]"
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
        chain, x_expr, y_expr = _text_animation(t, canvas.width, canvas.height)
        graph.append(f"[{idx}:v]" + ",".join(chain) + f"[tx{k}]")
        nxt = f"vt{k}"
        graph.append(
            f"[{cur}][tx{k}]overlay=x='{x_expr}':y='{y_expr}':enable='between(t,{_f(t.start)},{_f(end)})':format=auto[{nxt}]"
        )
        cur = nxt
    v_last = cur

    # ---- audio: every clip is delayed to its start and mixed (skipped when not exporting audio)
    if want_audio:
        voice: list[str] = []  # the clips' own sound and any non-music audio blocks
        music: list[str] = []
        for i, clip in enumerate(project.clips):
            graph.append(_audio_chain(clip, assets[clip.asset_id], i, durations[i], overlap[i], overlap[i + 1], starts[i]))
            voice.append(f"[a{i}]")
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
            graph.append(_music_chain(ac, idx, span, total))
            (music if (ac.is_music and project.duck_music) else voice).append(f"[ax{idx}]")

        def mix_of(labels: list[str], out: str) -> str:
            if len(labels) == 1:
                graph.append(f"{labels[0]}anull[{out}]")
            else:
                graph.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0[{out}]")
            return out

        voice_bus = mix_of(voice, "avoice")
        if music:
            music_bus = mix_of(music, "amusic")
            graph.append(f"[{voice_bus}]asplit=2[avo1][avo2]")
            ratio = 2 + 10 * project.duck_amount
            graph.append(f"[{music_bus}][avo1]sidechaincompress=threshold=0.03:ratio={_f(ratio)}:attack=30:release=600:makeup=1[aduck]")
            graph.append("[avo2][aduck]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[amix]")
            a_final = "amix"
        else:
            a_final = voice_bus
        if abs(project.master_volume - 1) > 1e-6:
            graph.append(f"[{a_final}]volume={_f(project.master_volume)}[amaster]")
            a_final = "amaster"
        if project.master_normalize:
            graph.append(f"[{a_final}]loudnorm=I=-14:TP=-1.5:LRA=11,aresample={SAMPLE_RATE}[anorm]")
            a_final = "anorm"
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
