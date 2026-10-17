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
    # --- added in 1.2.14: film stocks, moods, seasons, retro
    "blockbuster": "colorbalance=rs=-.12:gs=-.03:bs=.14:rm=-.05:bm=.08:rh=.14:gh=.04:bh=-.14,eq=contrast=1.18:saturation=1.2",
    "film_warm": "curves=all='0/0.04 0.5/0.52 1/0.96',colorbalance=rs=.08:bs=-.08:rm=.06:bm=-.05,eq=saturation=1.08:contrast=1.06",
    "film_cool": "curves=all='0/0.03 0.5/0.5 1/0.97',colorbalance=rs=-.06:bs=.1:gm=.03:bm=.05,eq=saturation=1.05:contrast=1.05",
    "film_fade": "curves=all='0/0.16 0.5/0.5 1/0.88',eq=saturation=0.85:contrast=1.04",
    "tungsten": "colorbalance=rs=.18:gs=.04:bs=-.22:rm=.1:bm=-.14,eq=saturation=1.1",
    "day_for_night": "colorbalance=rs=-.15:bs=.25:rm=-.1:bm=.2,eq=brightness=-0.18:contrast=1.2:saturation=0.7",
    "dreamy": "curves=all='0/0.08 1/1',eq=saturation=1.12:brightness=0.04:contrast=0.92,gblur=sigma=0.8",
    "romantic": "colorbalance=rs=.1:bs=.06:rm=.06:bm=.04,eq=saturation=1.1:brightness=0.04:contrast=0.95",
    "horror": "hue=s=0.35,colorbalance=gs=.08:gm=.1:rs=-.1,eq=contrast=1.3:brightness=-0.1,vignette=PI/3",
    "scifi": "colorbalance=rs=-.15:gs=.04:bs=.18:rm=-.08:bm=.14,eq=saturation=0.85:contrast=1.2",
    "autumn": "colorbalance=rs=.18:gs=.05:bs=-.2:rm=.12:bm=-.1,eq=saturation=1.2:contrast=1.06",
    "winter": "colorbalance=rs=-.1:bs=.14:rm=-.06:bm=.1,eq=saturation=0.8:brightness=0.03:contrast=1.05",
    "tropical": "colorbalance=rs=.06:gs=.06:bs=-.04,eq=saturation=1.45:contrast=1.08",
    "summer": "colorbalance=rs=.1:bs=-.08:rm=.05,eq=saturation=1.3:brightness=0.03:contrast=1.06",
    "retro_80s": "colorbalance=rs=.1:bs=.14:rm=.08:bm=.1,eq=saturation=1.35:contrast=1.12,curves=all='0/0.06 1/0.96'",
    "retro_90s": "curves=all='0/0.1 1/0.92',colorbalance=gm=.05:rm=.05:bm=-.04,eq=saturation=0.9:contrast=0.98",
    "anime": "eq=saturation=1.5:contrast=1.15:brightness=0.03,unsharp=5:5:0.8:5:5:0",
    "high_key": "curves=all='0/0.18 0.5/0.68 1/1',eq=saturation=0.9",
    "low_key": "curves=all='0/0 0.5/0.35 1/0.9',eq=contrast=1.2:saturation=0.9",
    "clean_bright": "eq=brightness=0.05:contrast=1.08:saturation=1.12,unsharp=3:3:0.5:3:3:0",
    "foodie": "colorbalance=rs=.08:gs=.03:bs=-.1:rm=.06,eq=saturation=1.35:contrast=1.1:brightness=0.02",
    "portrait_soft": "colorbalance=rs=.06:bs=-.03:rm=.03,eq=saturation=0.95:contrast=0.94:brightness=0.03,gblur=sigma=0.6",
    "sky_blue": "colorbalance=bs=.14:bm=.1:rh=-.06,eq=saturation=1.25:contrast=1.08",
    "forest_green": "colorbalance=gs=.1:gm=.08:rs=-.05:bs=-.05,eq=saturation=1.3:contrast=1.08",
    "moonlight": "hue=s=0.5,colorbalance=bs=.2:bm=.16:bh=.08,eq=brightness=-0.1:contrast=1.15",
    "grayscale_soft": "hue=s=0,curves=all='0/0.06 1/0.94'",
    "sin_red": "hue=s=0.2,colorbalance=rs=.2:rm=.15,eq=contrast=1.3",
}
PRESET_LABELS = {
    "none": "None", "bw": "Black and white", "sepia": "Sepia", "vintage": "Vintage", "cool": "Cool", "warm": "Warm", "faded": "Faded",
    "dramatic": "Dramatic", "negative": "Negative", "cinematic": "Cinematic teal and orange", "noir": "Film noir", "cyberpunk": "Cyberpunk",
    "sunset": "Sunset", "golden": "Golden hour", "moody": "Moody", "pastel": "Pastel", "vivid": "Vivid", "matte": "Matte", "bleach": "Bleach bypass",
    "crossprocess": "Cross process", "polaroid": "Polaroid", "hdr": "HDR punch", "night": "Night", "duotone_blue": "Duotone blue", "duotone_pink": "Duotone pink",
    "blockbuster": "Blockbuster", "film_warm": "Warm film stock", "film_cool": "Cool film stock", "film_fade": "Faded film", "tungsten": "Tungsten lamp",
    "day_for_night": "Day for night", "dreamy": "Dreamy soft", "romantic": "Romantic", "horror": "Horror", "scifi": "Sci-fi", "autumn": "Autumn",
    "winter": "Winter frost", "tropical": "Tropical", "summer": "Summer glow", "retro_80s": "Retro 80s", "retro_90s": "Retro 90s", "anime": "Anime bright",
    "high_key": "High key (airy)", "low_key": "Low key (dark)", "clean_bright": "Clean and bright", "foodie": "Food", "portrait_soft": "Soft portrait",
    "sky_blue": "Blue sky", "forest_green": "Forest green", "moonlight": "Moonlight", "grayscale_soft": "Soft grey", "sin_red": "Red accent noir",
}
LOOK_GROUPS = {
    "Basic": ["none", "bw", "sepia", "negative", "vivid", "matte", "faded", "pastel", "hdr", "clean_bright"],
    "Cinema": ["cinematic", "blockbuster", "film_warm", "film_cool", "film_fade", "tungsten", "day_for_night", "noir", "sin_red", "bleach", "crossprocess", "dramatic", "moody", "low_key", "high_key"],
    "Mood": ["warm", "cool", "dreamy", "romantic", "horror", "scifi", "cyberpunk", "night", "moonlight", "grayscale_soft"],
    "Season and place": ["sunset", "golden", "autumn", "winter", "tropical", "summer", "sky_blue", "forest_green"],
    "Retro": ["vintage", "polaroid", "retro_80s", "retro_90s", "anime"],
    "People and food": ["portrait_soft", "foodie"],
    "Duotone": ["duotone_blue", "duotone_pink"],
}
LOOK_GROUP = {i: g for g, ids in LOOK_GROUPS.items() for i in ids}
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


def _fx_vignette(a: float, W: int, H: int) -> str:
    return f"vignette=angle={_f(3.1416 / (2.2 + 3.2 * (1 - a)))}"


def _fx_crt(a: float, W: int, H: int) -> str:
    return f"drawgrid=width=0:height=3:thickness=1:color=black@{_f(0.2 + 0.4 * a)},eq=saturation=1.2:contrast=1.08,vignette=PI/4"


def _fx_crisp(a: float, W: int, H: int) -> str:
    return f"unsharp=5:5:{_f(0.6 + 1.6 * a)}:5:5:0"


def _fx_static(a: float, W: int, H: int) -> str:
    return f"noise=alls={_px(a, 30, 90)}:allf=t+u,eq=contrast=1.1"


def _fx_invert_flash(a: float, W: int, H: int) -> str:
    period = _f(0.9 - 0.6 * a)
    return f"negate=enable='lt(mod(t,{period}),0.09)'"


def _fx_pinch(a: float, W: int, H: int) -> str:
    return f"lenscorrection=k1={_f(0.2 + 0.5 * a)}:k2={_f(0.05 + 0.15 * a)}"


def _fx_popart(a: float, W: int, H: int) -> str:
    q = _px(1 - a, 32, 85)
    return f"lutrgb=r='trunc(val/{q})*{q}':g='trunc(val/{q})*{q}':b='trunc(val/{q})*{q}',eq=saturation=2.2:contrast=1.25"


def _fx_thermal(a: float, W: int, H: int) -> str:
    return "pseudocolor=preset=heat"


def _fx_nightvision(a: float, W: int, H: int) -> str:
    return f"colorchannelmixer=.0:.0:.0:0:.35:.6:.12:0:.0:.0:.0:0,noise=alls={_px(a, 10, 40)}:allf=t+u,eq=brightness=0.06:contrast=1.2,vignette=PI/3"


def _fx_xray(a: float, W: int, H: int) -> str:
    return "hue=s=0,negate,curves=all='0/0 0.5/0.62 1/1',colorchannelmixer=.7:0:0:0:0:.9:0:0:.1:.2:1:0"


SIMPLE_EFFECTS: dict[str, tuple[str, Callable[[float, int, int], str]]] = {
    "vignette_fx": ("Dark corners", _fx_vignette), "crt": ("Old TV scanlines", _fx_crt), "crisp": ("Crisp detail", _fx_crisp),
    "tv_static": ("TV static", _fx_static), "invert_flash": ("Invert flash", _fx_invert_flash), "pinch": ("Pinch (squeeze centre)", _fx_pinch),
    "pop_art": ("Pop art", _fx_popart), "thermal": ("Thermal camera", _fx_thermal), "night_vision": ("Night vision", _fx_nightvision),
    "xray": ("X-ray", _fx_xray),
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


def _fx_kaleido(a: float, W: int, H: int) -> Fragment:
    return Fragment([
        "[{in}]crop=trunc(iw/4)*2:trunc(ih/4)*2:0:0,split=4[{p}a][{p}b][{p}c][{p}d]",
        "[{p}b]hflip[{p}bh]",
        "[{p}c]vflip[{p}cv]",
        "[{p}d]hflip,vflip[{p}dd]",
        "[{p}a][{p}bh]hstack=inputs=2[{p}top]",
        "[{p}cv][{p}dd]hstack=inputs=2[{p}bot]",
        f"[{{p}}top][{{p}}bot]vstack=inputs=2,scale={W}:{H}:flags=bicubic[{{out}}]",
    ])


def _fx_cartoon(a: float, W: int, H: int) -> Fragment:
    q = _px(1 - a, 24, 60)
    return Fragment([
        "[{in}]split=2[{p}a][{p}b]",
        f"[{{p}}a]gblur=sigma=1.2,lutrgb=r='trunc(val/{q})*{q}':g='trunc(val/{q})*{q}':b='trunc(val/{q})*{q}',eq=saturation=1.5[{{p}}c]",
        "[{p}b]edgedetect=low=0.08:high=0.25:mode=wires,negate,format=rgb24[{p}e]",
        "[{p}c][{p}e]blend=all_mode=multiply[{out}]",
    ])


def _fx_light_leak(a: float, W: int, H: int) -> Fragment:
    return Fragment([
        "[{in}]split=2[{p}a][{p}b]",
        f"gradients=s={W}x{H}:r=24:c0=0xff7a18:c1=0xff2d6f:c2=0xffd36b:nb_colors=3:speed=0.015:type=linear,format=rgb24[{{p}}g]",
        f"[{{p}}b][{{p}}g]blend=all_mode=screen:all_opacity={_f(0.15 + 0.45 * a)}:shortest=1[{{p}}l]",
        "[{p}a][{p}l]blend=all_mode=normal:all_opacity=1[{out}]",
    ])


def _fx_focus_in(a: float, W: int, H: int) -> Fragment:
    return Fragment([
        "[{in}]split=2[{p}a][{p}b]",
        f"[{{p}}b]gblur=sigma={_px(a, 6, 22)}[{{p}}g]",
        "[{p}a][{p}g]blend=all_expr='A*min(1,T/1.2)+B*(1-min(1,T/1.2))'[{out}]",
    ])


def _fx_tilt_shift(a: float, W: int, H: int) -> Fragment:
    return Fragment([
        "[{in}]split=2[{p}a][{p}b]",
        f"[{{p}}b]gblur=sigma={_px(a, 4, 14)}[{{p}}g]",
        f"[{{p}}a][{{p}}g]blend=all_expr='A*if(between(Y,H*0.32,H*0.68),1,max(0,1-min(abs(Y-H*0.32),abs(Y-H*0.68))/(H*0.2)))+B*(1-if(between(Y,H*0.32,H*0.68),1,max(0,1-min(abs(Y-H*0.32),abs(Y-H*0.68))/(H*0.2))))'[{{out}}]",
    ])


COMPLEX_EFFECTS: dict[str, tuple[str, Callable[[float, int, int], Fragment]]] = {
    "kaleido": ("Kaleidoscope", _fx_kaleido), "focus_in": ("Blur-to-sharp opening", _fx_focus_in), "cartoon": ("Cartoon", _fx_cartoon), "light_leak": ("Light leak", _fx_light_leak), "tilt_shift": ("Tilt-shift (toy town)", _fx_tilt_shift),
    "mirror_h": ("Mirror (left and right)", _fx_mirror_h), "mirror_v": ("Mirror (top and bottom)", _fx_mirror_v), "bloom": ("Dreamy glow", _fx_bloom),
}
_ALL_EFFECTS = {**SIMPLE_EFFECTS, **COMPLEX_EFFECTS}
EFFECT_GROUPS = {
    "Glitch and retro": ["rgb_split", "glitch", "vhs", "tv_static", "crt", "old_film", "film_grain", "invert_flash", "strobe"],
    "Glow and light": ["bloom", "light_leak", "vignette_fx", "rainbow"],
    "Blur and focus": ["focus_in", "tilt_shift", "crisp", "trail", "ghost"],
    "Shape and mirror": ["mirror_h", "mirror_v", "kaleido", "fisheye", "pinch", "letterbox"],
    "Art and vision": ["cartoon", "sketch", "neon_edges", "pop_art", "posterize", "pixelate", "emboss", "thermal", "night_vision", "xray"],
}
EFFECT_GROUP = {i: g for g, ids in EFFECT_GROUPS.items() for i in ids}
EFFECT_INFO = [(i, _ALL_EFFECTS[i][0]) for ids in EFFECT_GROUPS.values() for i in ids] + [(k, v[0]) for k, v in _ALL_EFFECTS.items() if k not in EFFECT_GROUP]
EFFECTS = tuple(e[0] for e in EFFECT_INFO)


def effect_filter(effect: str, amount: float, W: int, H: int) -> str | Fragment:
    a = max(0.0, min(1.0, amount))
    if effect in SIMPLE_EFFECTS:
        return SIMPLE_EFFECTS[effect][1](a, W, H)
    return COMPLEX_EFFECTS[effect][1](a, W, H)


# ------------------------------------------------------------------ shape masks (layers)
MASK_INFO = [
    ("none", "No mask"), ("circle", "Circle"), ("ellipse", "Oval (fills the frame)"), ("rounded", "Rounded corners"), ("diamond", "Diamond"),
    ("heart", "Heart"), ("star", "Star"), ("hexagon", "Hexagon"), ("half_left", "Left half"), ("half_top", "Top half"), ("blinds", "Window blinds"),
]
MASKS = tuple(m[0] for m in MASK_INFO)


def mask_alpha_expr(mask: str, feather: float = 0.1, invert: bool = False) -> str:
    """A geq expression (0..1) that is 1 inside the shape and 0 outside; X, Y, W, H are the picture's own pixels."""
    m = "min(W,H)"
    U, V = "(2*X/W-1)", "(2*Y/H-1)"
    Uc, Vc = f"((2*X/W-1)*W/{m})", f"((2*Y/H-1)*H/{m})"
    if mask == "circle":
        d = f"(hypot({Uc},{Vc})-1)"
    elif mask == "ellipse":
        d = f"(hypot({U},{V})-1)"
    elif mask == "rounded":
        qx, qy = f"(abs({Uc})-(W/{m}-0.35))", f"(abs({Vc})-(H/{m}-0.35))"
        d = f"(hypot(max({qx},0),max({qy},0))+min(max({qx},{qy}),0)-0.35)"
    elif mask == "diamond":
        d = f"(abs({U})+abs({V})-1)"
    elif mask == "heart":
        x, y = f"({Uc}*1.25)", f"(-{Vc}*1.25+0.25)"
        d = f"((pow({x}*{x}+{y}*{y}-1,3)-{x}*{x}*pow({y},3))*0.35)"
    elif mask == "star":
        ang = f"(atan2({Vc},{Uc})+PI/2)"
        a2 = f"abs(mod({ang},2*PI/5)-PI/5)"
        d = f"(hypot({Uc},{Vc})-(0.42+0.58*{a2}/(PI/5)))"
    elif mask == "hexagon":
        d = f"(max(abs({Uc})*0.866+abs({Vc})*0.5,abs({Vc}))-1)"
    elif mask == "half_left":
        d = U
    elif mask == "half_top":
        d = V
    elif mask == "blinds":
        d = "((abs(mod(Y/H*8,1)-0.5)-0.25)*2)"
    else:
        return "1"
    soft = _f(0.015 + 0.45 * max(0.0, min(1.0, feather)))
    a = f"clip(0.5-{d}/{soft},0,1)"
    return f"(1-{a})" if invert else a
