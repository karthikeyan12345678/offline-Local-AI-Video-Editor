"""Video looks, effects, camera motions and transitions.

Everything here is data plus small ffmpeg-filter builders, so the project model
(validation), the renderer and the UI catalog all read from the same lists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# ------------------------------------------------------------------ transitions
# (id, label, group). Every id except "none"/"random" is an ffmpeg `xfade` transition.
_T = [
    ("fade", "Cross-fade", "Fade"), ("dissolve", "Dissolve", "Fade"), ("fadeblack", "Through black", "Fade"),
    ("fadewhite", "Through white", "Fade"), ("fadegrays", "Through grey", "Fade"), ("fadefast", "Fast fade", "Fade"),
    ("fadeslow", "Slow fade", "Fade"), ("hblur", "Blur", "Fade"), ("distance", "Distance", "Fade"),
    ("wipeleft", "Wipe left", "Wipe"), ("wiperight", "Wipe right", "Wipe"), ("wipeup", "Wipe up", "Wipe"), ("wipedown", "Wipe down", "Wipe"),
    ("wipetl", "Wipe top-left", "Wipe"), ("wipetr", "Wipe top-right", "Wipe"), ("wipebl", "Wipe bottom-left", "Wipe"), ("wipebr", "Wipe bottom-right", "Wipe"),
    ("slideleft", "Slide left", "Slide"), ("slideright", "Slide right", "Slide"), ("slideup", "Slide up", "Slide"), ("slidedown", "Slide down", "Slide"),
    ("smoothleft", "Smooth left", "Slide"), ("smoothright", "Smooth right", "Slide"), ("smoothup", "Smooth up", "Slide"), ("smoothdown", "Smooth down", "Slide"),
    ("coverleft", "Cover left", "Cover and reveal"), ("coverright", "Cover right", "Cover and reveal"), ("coverup", "Cover up", "Cover and reveal"), ("coverdown", "Cover down", "Cover and reveal"),
    ("revealleft", "Reveal left", "Cover and reveal"), ("revealright", "Reveal right", "Cover and reveal"), ("revealup", "Reveal up", "Cover and reveal"), ("revealdown", "Reveal down", "Cover and reveal"),
    ("circleopen", "Circle open", "Shape"), ("circleclose", "Circle close", "Shape"), ("circlecrop", "Circle crop", "Shape"), ("rectcrop", "Rectangle crop", "Shape"),
    ("vertopen", "Doors open (vertical)", "Shape"), ("vertclose", "Doors close (vertical)", "Shape"), ("horzopen", "Doors open (horizontal)", "Shape"), ("horzclose", "Doors close (horizontal)", "Shape"),
    ("radial", "Radial sweep", "Shape"),
    ("diagtl", "Diagonal top-left", "Slice"), ("diagtr", "Diagonal top-right", "Slice"), ("diagbl", "Diagonal bottom-left", "Slice"), ("diagbr", "Diagonal bottom-right", "Slice"),
    ("hlslice", "Slices left", "Slice"), ("hrslice", "Slices right", "Slice"), ("vuslice", "Slices up", "Slice"), ("vdslice", "Slices down", "Slice"),
    ("hlwind", "Wind left", "Wind"), ("hrwind", "Wind right", "Wind"), ("vuwind", "Wind up", "Wind"), ("vdwind", "Wind down", "Wind"),
    ("zoomin", "Zoom in", "Zoom"), ("squeezeh", "Squeeze sideways", "Zoom"), ("squeezev", "Squeeze up and down", "Zoom"), ("pixelize", "Pixelate", "Zoom"),
]
TRANSITION_INFO: list[tuple[str, str, str]] = [("none", "None (hard cut)", "Basic"), ("random", "Random (different each cut)", "Basic"), *_T]
XFADE_NAMES = tuple(t[0] for t in _T)
TRANSITIONS = tuple(t[0] for t in TRANSITION_INFO)


def pick_random_transition(seed: str, supported: set[str] | None = None) -> str:
    """A stable pseudo-random transition for a clip (same project always renders the same)."""
    pool = [n for n in XFADE_NAMES if n not in ("pixelize", "distance") and (supported is None or n in supported)] or ["fade"]
    h = 0
    for ch in seed:
        h = (h * 131 + ord(ch)) & 0xFFFFFFFF
    return pool[h % len(pool)]


# ------------------------------------------------------------------ colour looks
PRESET_FILTERS: dict[str, str] = {
    "bw": "hue=s=0",
    "sepia": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131:0",
    "vintage": "curves=preset=vintage",
    "cool": "colorbalance=rs=-.1:bs=.15:rm=-.05:bm=.1",
    "warm": "colorbalance=rs=.15:bs=-.15:rm=.08:bm=-.08",
    "faded": "curves=all='0/0.12 1/0.9',eq=saturation=0.8",
    "dramatic": "curves=preset=increase_contrast,eq=saturation=1.15",
    "negative": "negate",
    "cinematic": "colorbalance=rs=-.08:gs=-.02:bs=.1:rm=.04:bm=-.06:rh=.1:bh=-.1,eq=contrast=1.12:saturation=1.1",
    "noir": "hue=s=0,curves=all='0/0 0.25/0.14 0.75/0.9 1/1',eq=contrast=1.2",
    "cyberpunk": "colorbalance=rs=.2:gs=-.1:bs=.25:rm=.1:bm=.2:rh=.1:bh=.1,eq=saturation=1.4:contrast=1.15",
    "sunset": "colorbalance=rs=.2:gs=.02:bs=-.2:rm=.12:bm=-.12,eq=saturation=1.25:gamma=1.05",
    "golden": "colorbalance=rs=.12:gs=.04:bs=-.18:rm=.1:bm=-.1:rh=.08:bh=-.08,eq=saturation=1.1:brightness=0.03",
    "moody": "colorbalance=bs=.1:bm=.05:rh=-.05,eq=contrast=1.2:saturation=0.8:brightness=-0.05",
    "pastel": "eq=saturation=0.75:brightness=0.08:contrast=0.9,curves=all='0/0.1 1/1'",
    "vivid": "eq=saturation=1.6:contrast=1.1",
    "matte": "curves=all='0/0.1 1/0.92',eq=saturation=0.9",
    "bleach": "eq=saturation=0.55:contrast=1.35",
    "crossprocess": "curves=r='0/0 0.5/0.6 1/1':g='0/0 0.5/0.5 1/1':b='0/0.15 1/0.85'",
    "polaroid": "curves=all='0/0.06 1/0.94',colorbalance=rm=.06:bm=-.06,eq=saturation=1.15:contrast=0.95",
    "hdr": "eq=contrast=1.25:saturation=1.3,unsharp=7:7:1.0:7:7:0.0",
    "night": "colorbalance=bs=.2:bm=.15,eq=brightness=-0.12:saturation=0.85:contrast=1.15",
    "duotone_blue": "hue=s=0,curves=r='0/0.02 1/0.55':g='0/0.05 1/0.75':b='0/0.25 1/1'",
    "duotone_pink": "hue=s=0,curves=r='0/0.25 1/1':g='0/0.02 1/0.5':b='0/0.2 1/0.85'",
}
PRESET_LABELS = {
    "none": "None", "bw": "Black and white", "sepia": "Sepia", "vintage": "Vintage", "cool": "Cool", "warm": "Warm", "faded": "Faded",
    "dramatic": "Dramatic", "negative": "Negative", "cinematic": "Cinematic teal and orange", "noir": "Film noir", "cyberpunk": "Cyberpunk",
    "sunset": "Sunset", "golden": "Golden hour", "moody": "Moody", "pastel": "Pastel", "vivid": "Vivid", "matte": "Matte", "bleach": "Bleach bypass",
    "crossprocess": "Cross process", "polaroid": "Polaroid", "hdr": "HDR punch", "night": "Night", "duotone_blue": "Duotone blue", "duotone_pink": "Duotone pink",
}
FILTER_PRESETS = ("none", *PRESET_FILTERS)

# ------------------------------------------------------------------ camera motion
MOTION_INFO = [
    ("none", "None"), ("kenburns_in", "Slow zoom in"), ("kenburns_out", "Slow zoom out"), ("pan_left", "Pan left"), ("pan_right", "Pan right"),
    ("pan_up", "Pan up"), ("pan_down", "Pan down"), ("drift", "Gentle drift"), ("shake", "Handheld shake"), ("pulse", "Beat pulse (zoom)"), ("swing", "Swing (tilt)"),
]
MOTIONS = tuple(m[0] for m in MOTION_INFO)


def _f(x: float) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".") or "0"


def motion_filters(motion: str, strength: float, W: int, H: int, dur: float) -> list[str]:
    """Filters that move the camera over a clip that is already W x H. `t` is seconds since the clip started."""
    if motion == "none":
        return []
    s = max(0.05, min(1.0, strength))
    D = max(0.1, dur)
    prog = f"min(t/{_f(D)},1)"
    even = lambda e: f"trunc(({e})/2)*2"  # noqa: E731

    def zoom_scale(zexpr: str) -> str:
        return f"scale=w='{even(f'{W}*({zexpr})')}':h='{even(f'{H}*({zexpr})')}':eval=frame:flags=bicubic,crop={W}:{H}"

    if motion == "kenburns_in":
        return [zoom_scale(f"1+{_f(0.5 * s)}*{prog}")]
    if motion == "kenburns_out":
        return [zoom_scale(f"1+{_f(0.5 * s)}-{_f(0.5 * s)}*{prog}")]
    if motion in ("pan_left", "pan_right", "pan_up", "pan_down"):
        z = 1 + 0.12 + 0.28 * s
        pre = f"scale={even(f'{W}*{_f(z)}')}:{even(f'{H}*{_f(z)}')}:flags=bicubic"
        cx, cy = "(iw-ow)/2", "(ih-oh)/2"
        if motion == "pan_right":
            return [pre, f"crop={W}:{H}:x='(iw-ow)*{prog}':y='{cy}'"]
        if motion == "pan_left":
            return [pre, f"crop={W}:{H}:x='(iw-ow)*(1-{prog})':y='{cy}'"]
        if motion == "pan_down":
            return [pre, f"crop={W}:{H}:x='{cx}':y='(ih-oh)*{prog}'"]
        return [pre, f"crop={W}:{H}:x='{cx}':y='(ih-oh)*(1-{prog})'"]
    if motion == "drift":
        z = 1.1 + 0.15 * s
        return [
            f"scale={even(f'{W}*{_f(z)}')}:{even(f'{H}*{_f(z)}')}:flags=bicubic",
            f"crop={W}:{H}:x='(iw-ow)/2*(1+0.85*sin(t*0.7))':y='(ih-oh)/2*(1+0.85*cos(t*0.5))'",
        ]
    if motion == "shake":
        z = 1.05 + 0.1 * s
        return [
            f"scale={even(f'{W}*{_f(z)}')}:{even(f'{H}*{_f(z)}')}:flags=bicubic",
            f"crop={W}:{H}:x='(iw-ow)/2*(1+0.9*sin(t*41)*cos(t*7.3))':y='(ih-oh)/2*(1+0.9*sin(t*37)*cos(t*5.1))'",
        ]
    if motion == "pulse":
        return [zoom_scale(f"1+{_f(0.14 * s)}*pow(sin(PI*t*2),2)")]
    if motion == "swing":
        z = 1.14 + 0.1 * s
        return [
            f"scale={even(f'{W}*{_f(z)}')}:{even(f'{H}*{_f(z)}')}:flags=bicubic",
            f"rotate=a='{_f(0.05 * s)}*sin(t*1.7)':ow=iw:oh=ih:c=black",
            f"crop={W}:{H}",
        ]
    return []


# ------------------------------------------------------------------ effects
@dataclass(frozen=True)
class Fragment:
    """A piece of filter graph that needs its own labels (split/blend/stack)."""

    statements: list[str]  # use {in} for the input label, {out} for the output label and {p} as a private prefix


def _px(a: float, lo: float, hi: float) -> int:
    return int(round(lo + (hi - lo) * a))


def _fx_rgb_split(a: float, W: int, H: int) -> str:
    n = _px(a, 2, 16)
    return f"rgbashift=rh={-n}:bh={n}:gv={n // 2}"


def _fx_glitch(a: float, W: int, H: int) -> str:
    n = _px(a, 3, 22)
    return (
        f"rgbashift=rh={-n}:bh={n}:gv={n // 2},noise=alls={_px(a, 8, 30)}:allf=t,"
        f"eq=brightness='{_f(0.05 + 0.1 * a)}*gt(sin(t*37)*sin(t*11),0.92)':eval=frame"
    )


def _fx_vhs(a: float, W: int, H: int) -> str:
    n = _px(a, 2, 8)
    return (
        f"chromashift=crh={n}:cbh={-n},noise=alls={_px(a, 10, 34)}:allf=t+u,eq=saturation=1.25:contrast=1.08,"
        f"drawgrid=width=0:height=3:thickness=1:color=black@{_f(0.12 + 0.2 * a)}"
    )


def _fx_grain(a: float, W: int, H: int) -> str:
    return f"noise=alls={_px(a, 6, 40)}:allf=t+u"


def _fx_oldfilm(a: float, W: int, H: int) -> str:
    return f"curves=preset=vintage,noise=alls={_px(a, 8, 28)}:allf=t,eq=brightness='{_f(0.03 * a)}*sin(t*24)':eval=frame,vignette=PI/4"


def _fx_pixelate(a: float, W: int, H: int) -> str:
    n = _px(a, 4, 32)
    return f"scale=w=trunc(iw/{n}/2)*2:h=trunc(ih/{n}/2)*2:flags=neighbor,scale={W}:{H}:flags=neighbor"


def _fx_posterize(a: float, W: int, H: int) -> str:
    q = _px(1 - a, 16, 64)
    return f"lutrgb=r='trunc(val/{q})*{q}':g='trunc(val/{q})*{q}':b='trunc(val/{q})*{q}'"


def _fx_sketch(a: float, W: int, H: int) -> str:
    return "edgedetect=low=0.06:high=0.2:mode=wires,negate"


def _fx_neon(a: float, W: int, H: int) -> str:
    return "edgedetect=low=0.05:high=0.15:mode=colormix"


def _fx_emboss(a: float, W: int, H: int) -> str:
    k = "-2 -1 0 -1 1 1 0 1 2"
    return f"convolution='{k}:{k}:{k}:{k}'"


def _fx_strobe(a: float, W: int, H: int) -> str:
    period = _f(0.5 - 0.3 * a)
    return f"eq=brightness='{_f(0.25 + 0.3 * a)}*lt(mod(t,{period}),0.05)':eval=frame"


def _fx_letterbox(a: float, W: int, H: int) -> str:
    bar = _f(0.07 + 0.08 * a)
    return f"drawbox=x=0:y=0:w=iw:h=ih*{bar}:color=black:t=fill,drawbox=x=0:y=ih-ih*{bar}:w=iw:h=ih*{bar}:color=black:t=fill"


def _fx_fisheye(a: float, W: int, H: int) -> str:
    return f"lenscorrection=k1={_f(-0.25 - 0.45 * a)}:k2={_f(-0.1 - 0.2 * a)}"


def _fx_rainbow(a: float, W: int, H: int) -> str:
    return f"hue=h='t*{_px(a, 30, 180)}'"


def _fx_trail(a: float, W: int, H: int) -> str:
    return f"tmix=frames={_px(a, 2, 8)}"


def _fx_ghost(a: float, W: int, H: int) -> str:
    return f"lagfun=decay={_f(0.88 + 0.1 * a)}"


SIMPLE_EFFECTS: dict[str, tuple[str, Callable[[float, int, int], str]]] = {
    "rgb_split": ("RGB split", _fx_rgb_split), "glitch": ("Glitch", _fx_glitch), "vhs": ("VHS tape", _fx_vhs),
    "film_grain": ("Film grain", _fx_grain), "old_film": ("Old film", _fx_oldfilm), "pixelate": ("Pixelate", _fx_pixelate),
    "posterize": ("Posterize", _fx_posterize), "sketch": ("Pencil sketch", _fx_sketch), "neon_edges": ("Neon edges", _fx_neon),
    "emboss": ("Emboss", _fx_emboss), "strobe": ("Strobe flash", _fx_strobe), "letterbox": ("Cinema bars", _fx_letterbox),
    "fisheye": ("Fisheye", _fx_fisheye), "rainbow": ("Rainbow colours", _fx_rainbow), "trail": ("Motion trail", _fx_trail),
    "ghost": ("Ghost echo", _fx_ghost),
}


def _fx_mirror_h(a: float, W: int, H: int) -> Fragment:
    return Fragment([
        "[{in}]split=2[{p}a][{p}b]",
        "[{p}a]crop=iw/2:ih:0:0[{p}l]",
        "[{p}b]crop=iw/2:ih:0:0,hflip[{p}r]",
        "[{p}l][{p}r]hstack=inputs=2[{out}]",
    ])


def _fx_mirror_v(a: float, W: int, H: int) -> Fragment:
    return Fragment([
        "[{in}]split=2[{p}a][{p}b]",
        "[{p}a]crop=iw:ih/2:0:0[{p}t]",
        "[{p}b]crop=iw:ih/2:0:0,vflip[{p}u]",
        "[{p}t][{p}u]vstack=inputs=2[{out}]",
    ])


def _fx_bloom(a: float, W: int, H: int) -> Fragment:
    return Fragment([
        "[{in}]split=2[{p}a][{p}b]",
        f"[{{p}}b]gblur=sigma={_px(a, 8, 28)},eq=brightness=0.04[{{p}}g]",
        f"[{{p}}a][{{p}}g]blend=all_mode=screen:all_opacity={_f(0.25 + 0.5 * a)}[{{out}}]",
    ])


COMPLEX_EFFECTS: dict[str, tuple[str, Callable[[float, int, int], Fragment]]] = {
    "mirror_h": ("Mirror (left and right)", _fx_mirror_h), "mirror_v": ("Mirror (top and bottom)", _fx_mirror_v), "bloom": ("Dreamy glow", _fx_bloom),
}
EFFECT_INFO = [(k, v[0]) for k, v in {**SIMPLE_EFFECTS, **COMPLEX_EFFECTS}.items()]
EFFECTS = tuple(e[0] for e in EFFECT_INFO)


def effect_filter(effect: str, amount: float, W: int, H: int) -> str | Fragment:
    a = max(0.0, min(1.0, amount))
    if effect in SIMPLE_EFFECTS:
        return SIMPLE_EFFECTS[effect][1](a, W, H)
    return COMPLEX_EFFECTS[effect][1](a, W, H)
