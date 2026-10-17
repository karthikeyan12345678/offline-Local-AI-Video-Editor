"""Bundled font catalog and font loading for text overlays.

The fonts live in ./fonts (see fonts/README.txt for the licences). A text overlay
names a font id; if that font cannot draw the characters typed (for example a
Latin-only font with Tamil text) the matching script font is used instead so
the export never shows empty boxes.
"""

from __future__ import annotations

import json
import os
import sys
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(__file__).parent / "fonts"

SCRIPT_RANGES = [
    ("devanagari", 0x0900, 0x097F), ("bengali", 0x0980, 0x09FF), ("gurmukhi", 0x0A00, 0x0A7F), ("gujarati", 0x0A80, 0x0AFF),
    ("oriya", 0x0B00, 0x0B7F), ("tamil", 0x0B80, 0x0BFF), ("telugu", 0x0C00, 0x0C7F), ("kannada", 0x0C80, 0x0CFF),
    ("malayalam", 0x0D00, 0x0D7F), ("arabic", 0x0600, 0x06FF), ("cjk", 0x3040, 0x9FFF), ("hangul", 0xAC00, 0xD7AF),
]
# Script -> bundled font used when the chosen font has no glyphs for it.
SCRIPT_FALLBACK = {
    "tamil": "notosanstamil", "devanagari": "notosansdevanagari", "telugu": "notosanstelugu", "kannada": "notosanskannada",
    "malayalam": "notosansmalayalam", "bengali": "notosansbengali",
}
DEFAULT_FONT = "montserrat"


@dataclass(frozen=True)
class FontEntry:
    id: str
    label: str
    category: str
    regular: str
    bold: str | None
    variable: bool
    scripts: tuple[str, ...]
    license: str

    def path(self, bold: bool) -> Path:
        return FONT_DIR / (self.bold if bold and self.bold else self.regular)


@lru_cache(maxsize=1)
def catalog() -> dict[str, FontEntry]:
    try:
        rows = json.loads((FONT_DIR / "fonts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, FontEntry] = {}
    for r in rows:
        e = FontEntry(r["id"], r["label"], r["category"], r["regular"], r.get("bold"), bool(r.get("variable")), tuple(r.get("scripts", ["latin"])), r.get("license", ""))
        if e.path(False).exists():
            out[e.id] = e
    return out


def font_ids() -> tuple[str, ...]:
    return tuple(catalog())


def script_of(text: str) -> str:
    """The first non-Latin script found in `text`, else 'latin'."""
    for ch in text:
        o = ord(ch)
        if o < 0x0250:
            continue
        for name, lo, hi in SCRIPT_RANGES:
            if lo <= o <= hi:
                return name
    return "latin"


# ---------------------------------------------------------------- system fonts (last resort)
def _win_font(*names: str) -> str | None:
    win = os.environ.get("WINDIR", r"C:\Windows")
    for n in names:
        p = os.path.join(win, "Fonts", n)
        if os.path.exists(p):
            return p
    return None


def system_font(text: str, bold: bool) -> str | None:
    env = os.environ.get("LTXPS_FONT")
    if env and os.path.exists(env):
        return env
    script = script_of(text)
    if sys.platform.startswith("win"):
        if script not in ("latin", "cjk", "hangul", "arabic"):
            return _win_font("nirmalab.ttf" if bold else "Nirmala.ttf", "Nirmala.ttf")
        if script in ("cjk", "hangul"):
            return _win_font("msyhbd.ttc" if bold else "msyh.ttc", "YuGothB.ttc" if bold else "YuGothM.ttc", "malgun.ttf")
        return _win_font("segoeuib.ttf" if bold else "segoeui.ttf", "arialbd.ttf" if bold else "arial.ttf")
    if sys.platform == "darwin":
        return next((p for p in ("/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial.ttf") if os.path.exists(p)), None)
    cands = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    return next((p for p in cands if os.path.exists(p)), None)


# ---------------------------------------------------------------- loading
def _apply_variation(font: ImageFont.FreeTypeFont, bold: bool, size: int) -> bool:
    """Sets a variable font's weight. False when this Pillow cannot (the browser build has no variation support)."""
    try:
        axes = font.get_variation_axes()
    except (OSError, AttributeError, ValueError, NotImplementedError):
        return False
    values: list[float] = []
    for ax in axes:
        name = ax["name"].decode("latin-1").lower() if isinstance(ax["name"], bytes) else str(ax["name"]).lower()
        lo, hi, default = ax["minimum"], ax["maximum"], ax["default"]
        if "weight" in name:
            want = 700 if bold else 400
            values.append(max(lo, min(hi, want)))
        elif "width" in name:
            values.append(max(lo, min(hi, 100)))
        elif "optical" in name or "opsz" in name:
            values.append(max(lo, min(hi, size)))
        else:
            values.append(default)
    try:
        font.set_variation_by_axes(values)
    except (OSError, ValueError, NotImplementedError):
        return False
    return True


def _glyph_signature(font: ImageFont.FreeTypeFont, ch: str) -> bytes:
    size = getattr(font, "size", 32)
    box = int(size * 2) + 8
    img = Image.new("L", (box, box), 0)
    try:
        ImageDraw.Draw(img).text((4, 4), ch, font=font, fill=255)
    except (OSError, ValueError):
        return b""
    return img.tobytes()


def covers(font: ImageFont.FreeTypeFont, key: str, text: str) -> bool:
    """False if some letter in `text` is drawn as the font's 'missing glyph' box (or not at all)."""
    tofu = _glyph_signature(font, "\uFFFF")
    blank = Image.new("L", (int(getattr(font, "size", 32) * 2) + 8,) * 2, 0).tobytes()
    seen: set[str] = set()
    for ch in text:
        if ch in seen or ch.isspace() or unicodedata.category(ch)[0] not in ("L", "N"):
            continue
        seen.add(ch)
        sig = _glyph_signature(font, ch)
        if not sig or sig == tofu or sig == blank:
            return False
        if len(seen) > 40:
            break
    return True


@dataclass
class LoadedFont:
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    path: str | None
    id: str
    synth_bold: bool  # the family has no bold: draw a thin outline to fake it
    variable: bool


def _truetype(path: str | Path, size: int) -> ImageFont.FreeTypeFont | None:
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return None


def load_font(font_id: str, size: int, bold: bool, text: str) -> LoadedFont:
    """Best font for `text`: the requested one, else a script font, else a system font, else Pillow's default."""
    cat = catalog()
    script = script_of(text)
    order: list[str] = []
    if font_id and font_id in cat:
        order.append(font_id)
    fb = SCRIPT_FALLBACK.get(script)
    if fb and fb in cat and fb not in order:
        order.append(fb)
    if script == "latin" and DEFAULT_FONT in cat and DEFAULT_FONT not in order:
        order.append(DEFAULT_FONT)
    for fid in order:
        e = cat[fid]
        ft = _truetype(e.path(bold), size)
        if ft is None:
            continue
        varied = _apply_variation(ft, bold, size) if e.variable else False
        if not covers(ft, f"{fid}:{bold}", text):
            continue
        has_bold = varied or bool(e.bold)
        return LoadedFont(ft, str(e.path(bold)), fid, bold and not has_bold, e.variable)
    sys_path = system_font(text, bold)
    if sys_path:
        ft = _truetype(sys_path, size)
        if ft is not None:
            return LoadedFont(ft, sys_path, "", False, False)
    try:
        return LoadedFont(ImageFont.load_default(size=size), None, "", False, False)
    except TypeError:
        return LoadedFont(ImageFont.load_default(), None, "", False, False)


def sample_png(font_id: str, text: str, bold: bool, height: int = 44) -> Image.Image:
    """A small RGBA preview of `text` in the font (white on transparent) for the font picker."""
    lf = load_font(font_id, int(height * 0.62), bold, text)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    w = max(8, int(probe.textlength(text, font=lf.font)) + 12)
    img = Image.new("RGBA", (w, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((6, height / 2), text, font=lf.font, fill=(255, 255, 255, 255), anchor="lm")
    return img
