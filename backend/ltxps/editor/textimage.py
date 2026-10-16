"""Text overlays are drawn with Pillow into transparent PNGs.

This avoids depending on ffmpeg's optional `drawtext` filter (missing from many
static builds) and lets us pick a font that covers the script being typed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .project import TextOverlay


def _win_font(*names: str) -> str | None:
    win = os.environ.get("WINDIR", r"C:\Windows")
    for n in names:
        p = os.path.join(win, "Fonts", n)
        if os.path.exists(p):
            return p
    return None


def _script(text: str) -> str:
    for ch in text:
        o = ord(ch)
        if 0x0900 <= o <= 0x0DFF:
            return "indic"
        if 0x0600 <= o <= 0x06FF:
            return "arabic"
        if 0x3040 <= o <= 0x9FFF or 0xAC00 <= o <= 0xD7AF:
            return "cjk"
    return "latin"


def find_font(text: str, bold: bool) -> str | None:
    env = os.environ.get("LTXPS_FONT")
    if env and os.path.exists(env):
        return env
    script = _script(text)
    if sys.platform.startswith("win"):
        if script == "indic":
            return _win_font("nirmalab.ttf" if bold else "Nirmala.ttf", "Nirmala.ttf")
        if script == "cjk":
            return _win_font("msyhbd.ttc" if bold else "msyh.ttc", "YuGothB.ttc" if bold else "YuGothM.ttc", "malgun.ttf")
        return _win_font("segoeuib.ttf" if bold else "segoeui.ttf", "arialbd.ttf" if bold else "arial.ttf")
    if sys.platform == "darwin":
        return next((p for p in ("/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial.ttf") if os.path.exists(p)), None)
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    return next((p for p in candidates if os.path.exists(p)), None)


def _load_font(path: str | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow
        return ImageFont.load_default()


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def render_text_png(t: TextOverlay, canvas_height: int, canvas_width: int, dest: Path) -> tuple[int, int]:
    """Writes the overlay as a tight RGBA PNG and returns its size."""
    px = max(8, round(canvas_height * t.size / 100))
    path = find_font(t.text, t.bold)
    lines = t.text.replace("\r\n", "\n").split("\n")
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    has_box = t.box and t.box_opacity > 0

    # Shrink until the widest line fits inside the frame.
    while True:
        font = _load_font(path, px)
        bbox = probe.textbbox((0, 0), "Hg", font=font)
        widths = [max(1, round(probe.textlength(line, font=font))) for line in lines]
        pad = max(4, px // 3) if has_box else 2
        if max(widths) + pad * 2 <= canvas_width - 2 or px <= 8:
            break
        px -= 2

    glyph_h = bbox[3] - bbox[1]
    line_h = int(glyph_h * 1.3)
    w = min(max(widths) + pad * 2, canvas_width - 2)
    h = line_h * len(lines) + pad * 2
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if has_box:
        draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=max(3, px // 5), fill=(0, 0, 0, round(255 * t.box_opacity)))
    color = (*_rgb(t.color), 255)
    for i, line in enumerate(lines):
        x = (w - widths[i]) / 2
        top = pad + i * line_h + (line_h - glyph_h) / 2
        draw.text((x, top - bbox[1]), line, font=font, fill=color)
    if w % 2 or h % 2:  # keep even dimensions for yuv420p pipelines
        img = img.crop((0, 0, w - (w % 2), h - (h % 2)))
        w, h = img.size
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest)
    return w, h
