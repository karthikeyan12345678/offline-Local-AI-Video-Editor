"""Editor project document. This is exactly the JSON the frontend edits and saves."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

TRANSITIONS = (
    "none",
    "fade",
    "fadeblack",
    "fadewhite",
    "dissolve",
    "wipeleft",
    "wiperight",
    "wipeup",
    "wipedown",
    "slideleft",
    "slideright",
    "slideup",
    "slidedown",
    "circleopen",
    "circleclose",
    "radial",
    "pixelize",
)

FILTER_PRESETS = ("none", "bw", "sepia", "vintage", "cool", "warm", "faded", "dramatic", "negative")

HEX = r"^#[0-9a-fA-F]{6}$"


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

    @field_validator("preset")
    @classmethod
    def known_preset(cls, v: str) -> str:
        if v not in FILTER_PRESETS:
            raise ValueError(f"Unknown filter '{v}'")
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
    fade_in: float = Field(0, ge=0, le=5)
    fade_out: float = Field(0, ge=0, le=5)


class AudioClip(BaseModel):
    id: str
    asset_id: str
    start: float = Field(0, ge=0)
    trim_in: float = Field(0, ge=0)
    trim_out: float = Field(0, ge=0)  # 0 = until the end
    volume: float = Field(1, ge=0, le=2)
    fade_in: float = Field(0, ge=0, le=30)
    fade_out: float = Field(0, ge=0, le=30)


class Project(BaseModel):
    id: str = ""
    name: str = "Untitled project"
    canvas: Canvas = Field(default_factory=Canvas)
    clips: list[Clip] = Field(default_factory=list)
    texts: list[TextOverlay] = Field(default_factory=list)
    audio: list[AudioClip] = Field(default_factory=list)
    master_volume: float = Field(1, ge=0, le=2)


class ExportOptions(BaseModel):
    format: Literal["mp4", "webm", "gif"] = "mp4"
    width: int | None = Field(None, ge=64, le=3840)
    height: int | None = Field(None, ge=64, le=3840)
    fps: int | None = Field(None, ge=1, le=60)
    quality: Literal["low", "medium", "high"] = "medium"
    include_audio: bool = True
    preview: bool = False  # fast low-res proxy for in-app playback
