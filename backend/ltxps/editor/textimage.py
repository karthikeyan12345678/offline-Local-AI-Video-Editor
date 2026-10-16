"""Text overlays are drawn with Pillow into transparent PNGs.

This avoids depending on ffmpeg's optional `drawtext` filter (missing from many
static builds) and gives full control over fonts, outlines, glow, shadows,
gradients and alignment. Pillow shapes Tamil, Hindi and other Indic scripts
correctly when it was built with Raqm (the official wheels are).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .fonts import LoadedFont, load_font, script_of
from .fonts import system_font as _system_font  # noqa: F401  (kept for older imports)
from .project import TextOverlay

SHEAR = 0.2  # italic slant


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def find_font(text: str, bold: bool) -> str | None:
    """Kept for callers/tests that only want a usable font file."""
    return load_font("", 40, bold, text).path


def _metrics(font: ImageFont.FreeTypeFont | ImageFont.ImageFont, size: int) -> tuple[int, int]:
    try:
        asc, desc = font.getmetrics()  # type: ignore[union-attr]
        return int(asc), int(desc)
    except (AttributeError, OSError):
        return int(size * 0.9), int(size * 0.25)


def _line_width(draw: ImageDraw.ImageDraw, line: str, lf: LoadedFont, spacing_px: float, manual: bool) -> int:
    if manual and len(line) > 1:
        return max(1, round(sum(draw.textlength(ch, font=lf.font) for ch in line) + spacing_px * (len(line) - 1)))
    return max(1, round(draw.textlength(line, font=lf.font)))


def _draw_line(draw: ImageDraw.ImageDraw, xy: tuple[float, float], line: str, lf: LoadedFont, fill, spacing_px: float, manual: bool, stroke: int = 0) -> None:
    x, y = xy
    kw = {"stroke_width": stroke, "stroke_fill": fill} if stroke > 0 else {}
    if manual and len(line) > 1:
        for ch in line:
            draw.text((x, y), ch, font=lf.font, fill=fill, **kw)
            x += draw.textlength(ch, font=lf.font) + spacing_px
    else:
        draw.text((x, y), line, font=lf.font, fill=fill, **kw)


def render_text_png(t: TextOverlay, canvas_height: int, canvas_width: int, dest: Path) -> tuple[int, int]:
    """Writes the overlay as a tight RGBA PNG and returns its size."""
    text = t.text.replace("\r\n", "\n")
    if t.uppercase:
        text = text.upper()
    lines = text.split("\n")
    px = max(8, round(canvas_height * t.size / 100))
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    has_box = t.box and t.box_opacity > 0
    indic = script_of(text) not in ("latin", "cjk", "hangul")  # spacing per letter would break shaping
    manual = abs(t.letter_spacing) > 1e-3 and not indic

    while True:
        lf = load_font(t.font, px, t.bold, text)
        spacing_px = t.letter_spacing * px
        widths = [_line_width(probe, line, lf, spacing_px, manual) for line in lines]
        pad = max(4, px // 3) if has_box else 2
        stroke_px = round(px * t.stroke / 100) + (max(1, px // 34) if lf.synth_bold else 0)
        glow_r = px * (0.12 + 0.3 * t.glow) if t.glow > 0 else 0
        sh_off = px * (0.04 + 0.06 * t.shadow) if t.shadow > 0 else 0
        sh_blur = px * (0.03 + 0.08 * t.shadow) if t.shadow > 0 else 0
        margin = int(stroke_px + glow_r * 2 + sh_off + sh_blur * 2 + 3 + (SHEAR * px if t.italic else 0))
        if max(widths) + pad * 2 + margin * 2 <= canvas_width - 2 or px <= 8:
            break
        px -= 2

    asc, desc = _metrics(lf.font, px)
    natural = asc + desc
    line_h = max(1, round(natural * t.line_spacing / 1.25))
    content_w = max(widths) + pad * 2
    content_h = line_h * len(lines) + pad * 2 - (line_h - natural if line_h > natural else 0)
    content_h = max(content_h, natural + pad * 2)
    W, H = content_w + margin * 2, content_h + margin * 2

    # ---- text masks
    text_mask = Image.new("L", (W, H), 0)
    sil_mask = Image.new("L", (W, H), 0)  # text plus its outline
    dm, ds = ImageDraw.Draw(text_mask), ImageDraw.Draw(sil_mask)
    for i, line in enumerate(lines):
        if t.align == "left":
            x = margin + pad
        elif t.align == "right":
            x = margin + content_w - pad - widths[i]
        else:
            x = margin + (content_w - widths[i]) / 2
        y = margin + pad + i * line_h + max(0, (line_h - natural) / 2)
        _draw_line(dm, (x, y), line, lf, 255, spacing_px, manual)
        _draw_line(ds, (x, y), line, lf, 255, spacing_px, manual, stroke=stroke_px)
    silhouette = sil_mask if stroke_px > 0 else text_mask

    # ---- layers
    fx = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if t.glow > 0:
        g = silhouette.filter(ImageFilter.GaussianBlur(glow_r)).point(lambda v: min(255, int(v * 2.2)))
        fx = Image.alpha_composite(fx, Image.composite(Image.new("RGBA", (W, H), (*_rgb(t.glow_color), 255)), fx, g))
    if t.shadow > 0:
        off = int(round(sh_off))
        sm = Image.new("L", (W, H), 0)
        sm.paste(silhouette, (off, off))
        sm = sm.filter(ImageFilter.GaussianBlur(max(0.1, sh_blur))).point(lambda v: min(255, int(v * 1.4)))
        fx = Image.alpha_composite(fx, Image.composite(Image.new("RGBA", (W, H), (*_rgb(t.shadow_color), 255)), Image.new("RGBA", (W, H), (0, 0, 0, 0)), sm))
    if stroke_px > 0:
        col = _rgb(t.stroke_color) if t.stroke > 0 else _rgb(t.color)
        fx = Image.alpha_composite(fx, Image.composite(Image.new("RGBA", (W, H), (*col, 255)), Image.new("RGBA", (W, H), (0, 0, 0, 0)), sil_mask))
    if t.color2:
        top = Image.new("RGBA", (W, H), (*_rgb(t.color), 255))
        bottom = Image.new("RGBA", (W, H), (*_rgb(t.color2), 255))
        ramp = Image.new("L", (W, H), 255)
        band_h = max(2, content_h - pad)
        ramp.paste(Image.new("L", (W, margin + pad), 0), (0, 0))
        ramp.paste(Image.linear_gradient("L").resize((W, band_h)), (0, margin + pad))
        fill = Image.composite(bottom, top, ramp)
    else:
        fill = Image.new("RGBA", (W, H), (*_rgb(t.color), 255))
    fx = Image.alpha_composite(fx, Image.composite(fill, Image.new("RGBA", (W, H), (0, 0, 0, 0)), text_mask))
    if t.italic:
        fx = fx.transform(fx.size, Image.AFFINE, (1, SHEAR, -SHEAR * H / 2, 0, 1, 0), resample=Image.BICUBIC)

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if has_box:
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((margin, margin, margin + content_w - 1, margin + content_h - 1), radius=max(3, px // 5), fill=(*_rgb(t.box_color), round(255 * t.box_opacity)))
    img = Image.alpha_composite(img, fx)

    if abs(t.rotation) > 0.01:
        img = img.rotate(-t.rotation, expand=True, resample=Image.BICUBIC)
    if t.opacity < 0.999:
        a = img.getchannel("A").point(lambda v: int(v * t.opacity))
        img.putalpha(a)

    bbox = img.getchannel("A").getbbox()  # trim the empty margin so the position box matches what you see
    if bbox:
        img = img.crop(bbox)
    w, h = img.size
    if w % 2 or h % 2:
        img = img.crop((0, 0, w - (w % 2), h - (h % 2)))
    if img.size[0] < 2 or img.size[1] < 2:
        img = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest)
    return img.size
