"""Compiles an editor Project into a single ffmpeg invocation.

Every clip is normalised to the canvas (size, fps, pixel format, 48 kHz stereo)
so that concat/xfade never see mismatched streams. Clips with no audio get
generated silence of the exact length.
"""

from __future__ import annotations

import math
import re
import subprocess
from typing import Any
from dataclasses import dataclass, field
from pathlib import Path

from .audiofx import fx_filters
from .effects import PRESET_FILTERS, XFADE_NAMES, Fragment, effect_filter, mask_alpha_expr, motion_filters, pick_random_transition
from .media import NO_WINDOW, require_ffmpeg
from .drawimage import render_drawing_png, render_image_overlay_png
from .project import AudioClip, Chroma, Clip, Drawing, ExportOptions, Layer, Project, TextOverlay
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

    alpha = any(c.chroma.enabled for c in project.clips)
    if clip.chroma.enabled:
        f.extend(chroma_stages(clip.chroma))
    elif alpha:
        f.append("format=yuva420p")

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
    f.append("format=yuva420p" if alpha else "format=yuv420p")
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


def _text_animation(t: Any, W: int, H: int) -> tuple[list[str], str, str]:
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
        elif t.anim_in == "bounce":
            chain.append(f"fade=t=in:st={_f(st)}:d={_f(min(di * 0.4, 0.25))}:alpha=1")
            p = p_in
            bounce = (f"if(lt({p},0.363636),7.5625*{p}*{p},if(lt({p},0.727273),7.5625*pow({p}-0.545455,2)+0.75,"
                      f"if(lt({p},0.909091),7.5625*pow({p}-0.818182,2)+0.9375,7.5625*pow({p}-0.954545,2)+0.984375)))")
            dy += f"-{_f(0.28 * H)}*(1-({bounce}))"
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
        elif t.anim_out == "drop":
            chain.append(f"fade=t=out:st={_f(end - do)}:d={_f(do)}:alpha=1")
            dy += f"+{_f(0.22 * H)}*pow({q_out},2)"
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
    if di > 0 and t.anim_in == "typewriter":
        n = max(1, max((len(line) for line in str(getattr(t, "text", "x")).split("\n")), default=1))
        chain.append(f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(X,W*floor(clip((T-{_f(st)})/{_f(di)},0,1)*{n})/{n}),alpha(X,Y),0)'")
    if di > 0 and t.anim_in == "flicker":
        p = f"clip((T-{_f(st)})/{_f(di)},0,1)"
        chain.append(f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*if(gte(T,{_f(st + di)}),1,gt(sin(T*113)*sin(T*37)+{p}*1.7-0.85,0))'")
    if do > 0 and t.anim_out == "flicker":
        p = f"clip((T-{_f(end - do)})/{_f(do)},0,1)"
        chain.append(f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*if(lt(T,{_f(end - do)}),1,gt(sin(T*113)*sin(T*37)+0.85-{p}*1.7,0))'")
    x = f"(W-w)*{_f(getattr(t, 'x', 0.5))}+{dx}"
    y = f"(H-h)*{_f(getattr(t, 'y', 0.5))}+{dy}"
    pos = _key_overlay_pos(t, W, H, getattr(t, "x", 0.5), getattr(t, "y", 0.5))
    if pos is not None:
        if hasattr(t, "asset_id"):  # a picture: its sheet already holds it at the resting spot, so shift by the difference
            x = f"W*(({pos[0]})-{_f(t.x)})+{dx}"
            y = f"H*(({pos[1]})-{_f(t.y)})+{dy}"
        else:  # text: x and y are fractions of the free room around it
            x = f"(W-w)*({pos[0]})+{dx}"
            y = f"(H-h)*({pos[1]})+{dy}"
    return chain, x, y



# ---------------------------------------------------------------- keyframes and layers
def _ease(p: str, mode: str) -> str:
    """Shape a 0..1 progress expression (smooth = slow in, slow out)."""
    if mode == "smooth":
        return f"({p}*{p}*(3-2*{p}))"
    return p


def lerp_expr(points: list[tuple[float, float, str]], var: str = "t") -> str:
    """One ffmpeg expression that moves through (time, value, ease) points: it holds the first value before the first point and the last after it."""
    pts = sorted(points, key=lambda q: q[0])
    if not pts:
        return "0"
    if len(pts) == 1:
        return _f(pts[0][1])
    e = _f(pts[-1][1])
    for i in range(len(pts) - 2, -1, -1):
        t0, v0, mode = pts[i]
        t1, v1, _ = pts[i + 1]
        if t1 - t0 < 1e-6:
            continue
        if mode == "hold":
            seg = _f(v0)
        else:
            p = f"clip(({var}-{_f(t0)})/{_f(t1 - t0)},0,1)"
            seg = f"({_f(v0)}+({_f(v1 - v0)})*{_ease(p, mode)})"
        e = f"if(lt({var},{_f(t1)}),{seg},{e})"
    return f"if(lt({var},{_f(pts[0][0])}),{_f(pts[0][1])},{e})"


def _key_points(keys: list[Any], start: float, field: str) -> list[tuple[float, float, str]]:
    return [(start + k.t, float(getattr(k, field)), getattr(k, "ease", "smooth")) for k in keys]


def _vary(keys: list[Any], field: str) -> bool:
    vals = [round(float(getattr(k, field)), 4) for k in keys]
    return len(set(vals)) > 1


def chroma_stages(ch: Chroma) -> list[str]:
    """Filters that make the screen colour transparent (output is yuva420p)."""
    f = ["format=yuva420p", f"chromakey=color={_hex(ch.color)}:similarity={_f(ch.similarity)}:blend={_f(ch.blend)}"]
    if ch.spill:
        r, g, b = (int(ch.color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        if g >= r and g >= b:
            f += ["format=gbrap", "despill=type=green", "format=yuva420p"]
        elif b > r and b > g:
            f += ["format=gbrap", "despill=type=blue", "format=yuva420p"]
    return f


def layer_duration(layer: Layer, asset: AssetRef) -> float:
    if asset.kind == "image":
        return layer.image_duration
    end = layer.trim_out if layer.trim_out > 0 else asset.duration
    if asset.duration > 0:
        end = min(end, asset.duration)
    return max(0.05, end - layer.trim_in) / layer.speed


def _layer_graph(layer: Layer, asset: AssetRef, idx: int, k: int, canvas_w: int, canvas_h: int, fps: int) -> tuple[list[str], str, str, str]:
    """Statements that turn input `idx` into a positioned, keyed, animated picture. Returns (statements, label, x_expr, y_expr)."""
    dur = layer_duration(layer, asset)
    st, end = layer.start, layer.start + dur
    keys = sorted(layer.keys, key=lambda q: q.t)
    nw = (min(asset.width, canvas_w * 2) if asset.width > 0 else canvas_w) & ~1
    nw = max(2, nw)
    stages: list[str | Fragment] = []
    if asset.kind != "image":
        stages.append(f"setpts=(PTS-STARTPTS)/{_f(layer.speed)}")
    else:
        stages.append("setpts=PTS-STARTPTS")
    stages.append(f"fps={fps}")
    stages.append(f"scale={nw}:-2:flags=bicubic")
    if layer.chroma.enabled:
        stages += chroma_stages(layer.chroma)
    else:
        stages.append("format=yuva420p")
    a = layer.adjust
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
        stages.append("eq=" + ":".join(eq_parts))
    if a.hue:
        stages.append(f"hue=h={_f(a.hue)}")
    if layer.preset != "none":
        stages.append(PRESET_FILTERS[layer.preset])
    if layer.blur > 0:
        stages.append(f"gblur=sigma={_f(layer.blur)}")
    for e in layer.effects:
        stages.append(effect_filter(e.type, e.amount, nw, max(2, int(nw * (asset.height / asset.width)) if asset.width else canvas_h)))
    stages.append("format=rgba")
    if layer.mask != "none":
        stages.append(f"format=gbrap,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*({mask_alpha_expr(layer.mask, layer.mask_feather, layer.mask_invert)})',format=rgba")
    # rotation first (into a square big enough for any angle), then size
    rot_varies = _vary(keys, "rotation") if len(keys) > 1 else False
    if rot_varies or abs(layer.rotation) > 1e-6 or (keys and abs(keys[0].rotation) > 1e-6):
        ang = lerp_expr([(st + q.t, q.rotation * math.pi / 180, q.ease) for q in keys]) if keys else _f(layer.rotation * math.pi / 180)
        stages.append(f"rotate=a='{ang}':ow='ceil(hypot(iw,ih)/2)*2':oh='ceil(hypot(iw,ih)/2)*2':c=none")
    if keys and _vary(keys, "size"):
        sz = lerp_expr([(st + q.t, q.size, q.ease) for q in keys])
        stages.append(f"scale=w='max(2,trunc(iw*({sz})*{canvas_w}/{nw}/2)*2)':h='max(2,trunc(ih*({sz})*{canvas_w}/{nw}/2)*2)':eval=frame:flags=bicubic")
    else:
        size = keys[0].size if keys else layer.size
        stages.append(f"scale=w='max(2,trunc(iw*{_f(size)}*{canvas_w}/{nw}/2)*2)':h='max(2,trunc(ih*{_f(size)}*{canvas_w}/{nw}/2)*2)':flags=bicubic")
    if keys and _vary(keys, "opacity"):
        op = lerp_expr([(st + q.t, q.opacity, q.ease) for q in keys], var="T")
        stages.append(f"format=gbrap,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*({op})',format=rgba")
    else:
        op = keys[0].opacity if keys else layer.opacity
        if abs(op - 1) > 1e-6:
            stages.append(f"colorchannelmixer=aa={_f(op)}")
    stages.append(f"setpts=PTS+{_f(st)}/TB")
    if layer.fade_in > 0:
        stages.append(f"fade=t=in:st={_f(st)}:d={_f(min(layer.fade_in, dur))}:alpha=1")
    if layer.fade_out > 0:
        d = min(layer.fade_out, dur)
        stages.append(f"fade=t=out:st={_f(max(st, end - d))}:d={_f(d)}:alpha=1")
    out = f"lay{k}"
    stmts = _assemble(stages, f"{idx}:v", out, f"l{k}_")
    if keys and _vary(keys, "x"):
        cx = lerp_expr([(st + q.t, q.x, q.ease) for q in keys])
    else:
        cx = _f(keys[0].x if keys else layer.x)
    if keys and _vary(keys, "y"):
        cy = lerp_expr([(st + q.t, q.y, q.ease) for q in keys])
    else:
        cy = _f(keys[0].y if keys else layer.y)
    return stmts, out, f"W*({cx})-w/2", f"H*({cy})-h/2"


def _layer_audio(layer: Layer, asset: AssetRef, idx: int, k: int) -> str | None:
    if asset.kind == "image" or not asset.has_audio or layer.muted:
        return None
    dur = layer_duration(layer, asset)
    f = [f"aresample={SAMPLE_RATE}", "aformat=channel_layouts=stereo:sample_fmts=fltp"]
    f += atempo_chain(layer.speed)
    if abs(layer.volume - 1) > 1e-6:
        f.append(f"volume={_f(layer.volume)}")
    f += ["asetpts=PTS-STARTPTS", f"atrim=duration={_f(dur)}"]
    ms = int(round(layer.start * 1000))
    if ms > 0:
        f.append(f"adelay={ms}|{ms}")
    return f"[{idx}:a]" + ",".join(f) + f"[lax{k}]"


def _key_overlay_pos(obj: Any, W: int, H: int, base_x: float, base_y: float) -> tuple[str, str] | None:
    """Replace a text/picture's resting position by one that follows its keyframes. Returns overlay x and y expressions, or None."""
    keys = sorted(getattr(obj, "keys", []) or [], key=lambda q: q.t)
    if len(keys) < 1:
        return None
    pts_x = [(obj.start + q.t, q.x, q.ease) for q in keys]
    pts_y = [(obj.start + q.t, q.y, q.ease) for q in keys]
    return lerp_expr(pts_x), lerp_expr(pts_y)


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
    for ly in project.layers:
        if ly.asset_id not in assets:
            raise PlanError("A layer refers to a media file that is no longer in the library.")
        if assets[ly.asset_id].kind == "audio":
            raise PlanError("Audio files belong on the audio track, not on a video layer.")

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

    # ---- layers: videos and pictures that play at the same time as the main video (behind it, or on top)
    cur = v_last
    next_input = n
    layer_audio: list[str] = []
    use_alpha = any(c.chroma.enabled for c in project.clips)
    ordered = sorted(enumerate(project.layers), key=lambda q: (q[1].track, q[0]))
    behind_layers = [q for q in ordered if q[1].behind]
    front_layers = [q for q in ordered if not q[1].behind]

    def put_layer(base: str, k: int, ly: Layer) -> str:
        nonlocal next_input
        asset = assets[ly.asset_id]
        idx = next_input
        next_input += 1
        ldur = layer_duration(ly, asset)
        if asset.kind == "image":
            args.extend(["-loop", "1", "-framerate", str(fps), "-t", _f(ldur), "-i", str(asset.path)])
        else:
            args.extend(["-ss", _f(ly.trim_in), "-t", _f(max(0.05, ldur * ly.speed)), "-i", str(asset.path)])
        stmts, lab, x_expr, y_expr = _layer_graph(ly, asset, idx, k, canvas.width, canvas.height, fps)
        graph.extend(stmts)
        nxt = f"vl{k}"
        graph.append(f"[{base}][{lab}]overlay=x='{x_expr}':y='{y_expr}':enable='between(t,{_f(ly.start)},{_f(ly.start + ldur)})':eof_action=pass:format=auto[{nxt}]")
        if want_audio:
            la = _layer_audio(ly, asset, idx, k)
            if la:
                graph.append(la)
                layer_audio.append(f"[lax{k}]")
        return nxt

    if behind_layers or use_alpha:
        graph.append(f"color=c={_hex(canvas.background)}:s={canvas.width}x{canvas.height}:r={fps}:d={_f(total)}[bgsheet]")
        base = "bgsheet"
        for k, ly in behind_layers:
            base = put_layer(base, k, ly)
        graph.append(f"[{base}][{cur}]overlay=format=auto[vmain]")
        cur = "vmain"
    for k, ly in front_layers:
        cur = put_layer(cur, k, ly)
    if behind_layers and not use_alpha:
        warnings.append("A layer is set to sit behind the main video, but the main video has no see-through part. Remove a green screen from it (Settings → Remove background) to show the layer.")

    # ---- drawings (pen, arrows, circles): one canvas-sized transparent PNG each, under the text
    for k, d in enumerate(project.drawings):
        if not d.shapes:
            continue
        png = workdir / f"draw{k}.png"
        render_drawing_png(d, canvas.width, canvas.height, png)
        args += ["-loop", "1", "-framerate", str(fps), "-t", _f(total), "-i", str(png)]
        idx = next_input
        next_input += 1
        chain, x_expr, y_expr = _text_animation(d, canvas.width, canvas.height)
        graph.append(f"[{idx}:v]" + ",".join(chain) + f"[dx{k}]")
        nxt = f"vd{k}"
        graph.append(f"[{cur}][dx{k}]overlay=x='{x_expr}':y='{y_expr}':enable='between(t,{_f(d.start)},{_f(d.start + d.duration)})':format=auto[{nxt}]")
        cur = nxt

    # ---- picture overlays (a cap, a logo…): placed on a transparent sheet, same fade/slide as drawings
    for k, ov in enumerate(project.images):
        src = assets.get(ov.asset_id)
        if src is None or src.kind != "image":
            warnings.append("A picture on the timeline was removed from the library and was skipped.")
            continue
        png = workdir / f"img{k}.png"
        render_image_overlay_png(ov, src.path, canvas.width, canvas.height, png)
        args += ["-loop", "1", "-framerate", str(fps), "-t", _f(total), "-i", str(png)]
        idx = next_input
        next_input += 1
        chain, x_expr, y_expr = _text_animation(ov, canvas.width, canvas.height)
        graph.append(f"[{idx}:v]" + ",".join(chain) + f"[ix{k}]")
        nxt = f"vi{k}"
        graph.append(f"[{cur}][ix{k}]overlay=x='{x_expr}':y='{y_expr}':enable='between(t,{_f(ov.start)},{_f(ov.start + ov.duration)})':format=auto[{nxt}]")
        cur = nxt

    # ---- text overlays: Pillow PNG per overlay, composited with `overlay`
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
        voice.extend(layer_audio)
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
