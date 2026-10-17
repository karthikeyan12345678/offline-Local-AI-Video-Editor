"""Editor project document. This is exactly the JSON the frontend edits and saves.

Every field added after the first release has a default, so projects saved by an
older version still open and render the same way.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .audiofx import AUDIO_FX_IDS
from .effects import EFFECTS, FILTER_PRESETS, MASKS, MOTIONS, TRANSITIONS

HEX = r"^#[0-9a-fA-F]{6}$"

TEXT_ANIM_IN = ("none", "fade", "slide_up", "slide_down", "slide_left", "slide_right", "zoom", "pop", "reveal", "bounce", "typewriter", "flicker")
TEXT_ANIM_OUT = ("none", "fade", "slide_up", "slide_down", "slide_left", "slide_right", "zoom", "drop", "flicker")


class Canvas(BaseModel):
    width: int = Field(1280, ge=64, le=3840)
    height: int = Field(720, ge=64, le=3840)
    fps: int = Field(24, ge=1, le=60)
    background: str = Field("#000000", pattern=HEX)

    @field_validator("width", "height")
    @classmethod
    def even(cls, v: int) -> int:
        return v - (v % 2)


class Adjust(BaseModel):
    brightness: float = Field(0, ge=-100, le=100)
    contrast: float = Field(0, ge=-100, le=100)
    saturation: float = Field(0, ge=-100, le=100)
    gamma: float = Field(1, ge=0.3, le=3)
    hue: float = Field(0, ge=-180, le=180)


class Transition(BaseModel):
    type: str = "none"
    duration: float = Field(0.5, ge=0.1, le=3)

    @field_validator("type")
    @classmethod
    def known(cls, v: str) -> str:
        if v not in TRANSITIONS:
            raise ValueError(f"Unknown transition '{v}'")
        return v


class Effect(BaseModel):
    type: str
    amount: float = Field(0.5, ge=0, le=1)

    @field_validator("type")
    @classmethod
    def known(cls, v: str) -> str:
        if v not in EFFECTS:
            raise ValueError(f"Unknown effect '{v}'")
        return v


class Follow(BaseModel):
    """Keep a person (or face) in frame. `keys` are [source seconds, centre x, centre y] with x and y as 0..1 of the picture."""

    keys: list[tuple[float, float, float]] = Field(default_factory=list, max_length=20000)
    zoom: float = Field(1, ge=1, le=3)  # 1 = widest window of the project's shape that fits; higher = tighter


class Chroma(BaseModel):
    """Remove a green or blue screen (or any single colour) so what is behind shows through."""

    enabled: bool = False
    color: str = Field("#00FF00", pattern=HEX)
    similarity: float = Field(0.3, ge=0.01, le=1)  # how far from the key colour still counts as background
    blend: float = Field(0.1, ge=0, le=1)  # soft edge
    spill: bool = True  # remove the green/blue tint left on hair and edges


class Key(BaseModel):
    """One keyframe: where a layer, picture or text is, and how it looks, `t` seconds after it starts. Values between keys are blended smoothly."""

    t: float = Field(0, ge=0, le=36000)
    x: float = Field(0.5, ge=-1, le=2)
    y: float = Field(0.5, ge=-1, le=2)
    size: float = Field(0.5, ge=0.01, le=3)
    rotation: float = Field(0, ge=-720, le=720)
    opacity: float = Field(1, ge=0, le=1)
    ease: Literal["smooth", "linear", "hold"] = "smooth"  # how to travel from this key to the next one


class Clip(BaseModel):
    id: str
    asset_id: str
    trim_in: float = Field(0, ge=0)
    trim_out: float = Field(0, ge=0)  # 0 = until the end of the source
    image_duration: float = Field(3, gt=0, le=600)  # only used for still images
    speed: float = Field(1, ge=0.25, le=4)
    reverse: bool = False
    volume: float = Field(1, ge=0, le=2)
    muted: bool = False
    fade_in: float = Field(0, ge=0, le=10)
    fade_out: float = Field(0, ge=0, le=10)
    fit: Literal["fit", "fill", "stretch"] = "fit"
    zoom: float = Field(1, ge=1, le=4)
    pan_x: float = Field(0, ge=-1, le=1)
    pan_y: float = Field(0, ge=-1, le=1)
    rotate: Literal[0, 90, 180, 270] = 0
    flip_h: bool = False
    flip_v: bool = False
    adjust: Adjust = Field(default_factory=Adjust)
    preset: str = "none"
    blur: float = Field(0, ge=0, le=30)
    sharpen: float = Field(0, ge=0, le=5)
    vignette: bool = False
    denoise: bool = False
    transition: Transition = Field(default_factory=Transition)
    # ---- added in the editor upgrade
    motion: str = "none"
    motion_strength: float = Field(0.5, ge=0, le=1)
    effects: list[Effect] = Field(default_factory=list, max_length=6)
    follow: Follow | None = None
    audio_fx: str = "none"
    pitch: float = Field(0, ge=-12, le=12)  # semitones
    bass: float = Field(0, ge=-12, le=12)  # dB
    treble: float = Field(0, ge=-12, le=12)  # dB
    denoise_audio: bool = False
    normalize_audio: bool = False
    chroma: Chroma = Field(default_factory=Chroma)

    @field_validator("preset")
    @classmethod
    def known_preset(cls, v: str) -> str:
        if v not in FILTER_PRESETS:
            raise ValueError(f"Unknown filter '{v}'")
        return v

    @field_validator("motion")
    @classmethod
    def known_motion(cls, v: str) -> str:
        if v not in MOTIONS:
            raise ValueError(f"Unknown motion '{v}'")
        return v

    @field_validator("audio_fx")
    @classmethod
    def known_audio_fx(cls, v: str) -> str:
        if v not in AUDIO_FX_IDS:
            raise ValueError(f"Unknown sound effect '{v}'")
        return v


class TextOverlay(BaseModel):
    id: str
    text: str = Field(min_length=1, max_length=500)
    start: float = Field(0, ge=0)
    duration: float = Field(3, gt=0, le=3600)
    x: float = Field(0.5, ge=0, le=1)
    y: float = Field(0.85, ge=0, le=1)
    size: float = Field(6, ge=1, le=30)  # percent of canvas height
    color: str = Field("#FFFFFF", pattern=HEX)
    bold: bool = False
    box: bool = True
    box_opacity: float = Field(0.5, ge=0, le=1)
    fade_in: float = Field(0, ge=0, le=5)  # length of the "in" animation
    fade_out: float = Field(0, ge=0, le=5)  # length of the "out" animation
    # ---- added in the editor upgrade
    font: str = Field("", max_length=40)  # bundled font id; "" = automatic
    italic: bool = False
    uppercase: bool = False
    align: Literal["left", "center", "right"] = "center"
    letter_spacing: float = Field(0, ge=-0.1, le=1)  # in ems
    line_spacing: float = Field(1.25, ge=0.8, le=2.5)
    color2: str | None = Field(None, pattern=HEX)  # set for a top-to-bottom colour gradient
    stroke: float = Field(0, ge=0, le=30)  # outline width, percent of the letter height
    stroke_color: str = Field("#000000", pattern=HEX)
    shadow: float = Field(0, ge=0, le=1)  # 0 = none
    shadow_color: str = Field("#000000", pattern=HEX)
    glow: float = Field(0, ge=0, le=1)  # 0 = none
    glow_color: str = Field("#FFFFFF", pattern=HEX)
    box_color: str = Field("#000000", pattern=HEX)
    rotation: float = Field(0, ge=-180, le=180)
    opacity: float = Field(1, ge=0, le=1)
    anim_in: str = "fade"
    anim_out: str = "fade"
    keys: list[Key] = Field(default_factory=list, max_length=200)  # moves the text between points (x, y only)

    @field_validator("anim_in")
    @classmethod
    def known_in(cls, v: str) -> str:
        if v not in TEXT_ANIM_IN:
            raise ValueError(f"Unknown text animation '{v}'")
        return v

    @field_validator("anim_out")
    @classmethod
    def known_out(cls, v: str) -> str:
        if v not in TEXT_ANIM_OUT:
            raise ValueError(f"Unknown text animation '{v}'")
        return v


SHAPE_TYPES = ("pen", "highlight", "line", "arrow", "rect", "ellipse")


class Shape(BaseModel):
    """One pen stroke or shape. Points are 0..1 of the picture, so it stays put at any export size."""

    type: Literal["pen", "highlight", "line", "arrow", "rect", "ellipse"] = "pen"
    points: list[tuple[float, float]] = Field(default_factory=list, max_length=4000)
    color: str = Field("#FF3B30", pattern=HEX)
    width: float = Field(0.8, ge=0.1, le=10)  # percent of the picture height
    opacity: float = Field(1, ge=0, le=1)
    filled: bool = False
    fill_color: str | None = Field(None, pattern=HEX)
    fill_opacity: float = Field(0.25, ge=0, le=1)

    @field_validator("points")
    @classmethod
    def in_frame(cls, v: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return [(min(1.5, max(-0.5, x)), min(1.5, max(-0.5, y))) for x, y in v]


class Drawing(BaseModel):
    """A set of shapes shown together for a while, with the same in/out animation options as text."""

    id: str
    start: float = Field(0, ge=0)
    duration: float = Field(3, gt=0, le=3600)
    shapes: list[Shape] = Field(default_factory=list, max_length=300)
    opacity: float = Field(1, ge=0, le=1)
    fade_in: float = Field(0.3, ge=0, le=5)
    fade_out: float = Field(0.3, ge=0, le=5)
    anim_in: str = "fade"
    anim_out: str = "fade"

    @field_validator("anim_in")
    @classmethod
    def known_in(cls, v: str) -> str:
        if v not in TEXT_ANIM_IN:
            raise ValueError(f"Unknown animation '{v}'")
        return v

    @field_validator("anim_out")
    @classmethod
    def known_out(cls, v: str) -> str:
        if v not in TEXT_ANIM_OUT:
            raise ValueError(f"Unknown animation '{v}'")
        return v


class ImageOverlay(BaseModel):
    """A picture (a cap, a logo, a sticker) shown on top of the video for a while. x and y are the CENTRE, 0..1 of the picture."""

    id: str
    asset_id: str
    start: float = Field(0, ge=0)
    duration: float = Field(3, gt=0, le=3600)
    x: float = Field(0.5, ge=-0.5, le=1.5)
    y: float = Field(0.5, ge=-0.5, le=1.5)
    size: float = Field(0.25, ge=0.01, le=2)  # width as a fraction of the video width
    rotation: float = Field(0, ge=-360, le=360)
    opacity: float = Field(1, ge=0, le=1)
    fade_in: float = Field(0.2, ge=0, le=5)
    fade_out: float = Field(0.2, ge=0, le=5)
    anim_in: str = "fade"
    anim_out: str = "fade"
    keys: list[Key] = Field(default_factory=list, max_length=200)  # moves the picture between points (x, y only)

    @field_validator("anim_in")
    @classmethod
    def known_in(cls, v: str) -> str:
        if v not in TEXT_ANIM_IN:
            raise ValueError(f"Unknown animation '{v}'")
        return v

    @field_validator("anim_out")
    @classmethod
    def known_out(cls, v: str) -> str:
        if v not in TEXT_ANIM_OUT:
            raise ValueError(f"Unknown animation '{v}'")
        return v


class Layer(BaseModel):
    """A video or picture playing on top of (or behind) the main video, at the same time. x and y are the CENTRE, 0..1 of the picture."""

    id: str
    asset_id: str
    track: int = Field(1, ge=1, le=8)  # 1 = lowest layer; a higher number is drawn on top
    behind: bool = False  # show it behind the main video (what a removed green screen reveals)
    start: float = Field(0, ge=0)
    trim_in: float = Field(0, ge=0)
    trim_out: float = Field(0, ge=0)  # 0 = until the end of the file
    image_duration: float = Field(4, gt=0, le=3600)  # for still pictures
    speed: float = Field(1, ge=0.25, le=4)
    volume: float = Field(1, ge=0, le=2)
    muted: bool = False
    x: float = Field(0.5, ge=-1, le=2)
    y: float = Field(0.5, ge=-1, le=2)
    size: float = Field(0.5, ge=0.01, le=3)  # width as a fraction of the video width
    rotation: float = Field(0, ge=-720, le=720)
    opacity: float = Field(1, ge=0, le=1)
    fade_in: float = Field(0, ge=0, le=10)
    fade_out: float = Field(0, ge=0, le=10)
    adjust: Adjust = Field(default_factory=Adjust)
    preset: str = "none"
    blur: float = Field(0, ge=0, le=30)
    effects: list[Effect] = Field(default_factory=list, max_length=4)
    chroma: Chroma = Field(default_factory=Chroma)
    mask: str = "none"  # cut the layer into a shape (circle, heart, star ...)
    mask_feather: float = Field(0.1, ge=0, le=1)
    mask_invert: bool = False
    keys: list[Key] = Field(default_factory=list, max_length=200)

    @field_validator("preset")
    @classmethod
    def known_preset(cls, v: str) -> str:
        if v not in FILTER_PRESETS:
            raise ValueError(f"Unknown filter '{v}'")
        return v

    @field_validator("mask")
    @classmethod
    def known_mask(cls, v: str) -> str:
        if v not in MASKS:
            raise ValueError(f"Unknown mask '{v}'")
        return v


class AudioClip(BaseModel):
    id: str
    asset_id: str
    start: float = Field(0, ge=0)
    trim_in: float = Field(0, ge=0)
    trim_out: float = Field(0, ge=0)  # 0 = until the end
    volume: float = Field(1, ge=0, le=2)
    fade_in: float = Field(0, ge=0, le=30)
    fade_out: float = Field(0, ge=0, le=30)
    # ---- added in the editor upgrade
    fx: str = "none"
    pitch: float = Field(0, ge=-12, le=12)
    bass: float = Field(0, ge=-12, le=12)
    treble: float = Field(0, ge=-12, le=12)
    denoise: bool = False
    normalize: bool = False
    loop: bool = False  # repeat until the end of the video
    is_music: bool = True  # music is lowered automatically when "duck music" is on

    @field_validator("fx")
    @classmethod
    def known_fx(cls, v: str) -> str:
        if v not in AUDIO_FX_IDS:
            raise ValueError(f"Unknown sound effect '{v}'")
        return v


class Project(BaseModel):
    id: str = ""
    name: str = "Untitled project"
    canvas: Canvas = Field(default_factory=Canvas)
    clips: list[Clip] = Field(default_factory=list)
    texts: list[TextOverlay] = Field(default_factory=list)
    audio: list[AudioClip] = Field(default_factory=list)
    drawings: list[Drawing] = Field(default_factory=list, max_length=200)
    images: list[ImageOverlay] = Field(default_factory=list, max_length=100)
    layers: list[Layer] = Field(default_factory=list, max_length=60)
    master_volume: float = Field(1, ge=0, le=2)
    duck_music: bool = False  # lower the audio track while the clips are speaking
    duck_amount: float = Field(0.6, ge=0, le=1)
    master_normalize: bool = False  # even out loudness of the whole export


class ExportOptions(BaseModel):
    format: Literal["mp4", "webm", "gif"] = "mp4"
    width: int | None = Field(None, ge=64, le=3840)
    height: int | None = Field(None, ge=64, le=3840)
    fps: int | None = Field(None, ge=1, le=60)
    quality: Literal["low", "medium", "high"] = "medium"
    include_audio: bool = True
    preview: bool = False  # fast low-res proxy for in-app playback
