"""Pen, arrows, circles and boxes drawn on the video are rendered by Pillow into one transparent picture
the size of the video, then laid over it for the time the drawing is on screen."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

from .project import Drawing, Shape

SS = 2  # draw at double size, shrink for smooth edges


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _px(pt: tuple[float, float], W: int, H: int) -> tuple[float, float]:
    return pt[0] * W, pt[1] * H


def _stroke(d: ImageDraw.ImageDraw, pts: list[tuple[float, float]], width: float, fill) -> None:
    if len(pts) == 1:
        x, y = pts[0]
        r = width / 2
        d.ellipse((x - r, y - r, x + r, y + r), fill=fill)
        return
    d.line(pts, fill=fill, width=max(1, round(width)), joint="curve")
    r = width / 2  # round caps
    for x, y in (pts[0], pts[-1]):
        d.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def _arrow_head(d: ImageDraw.ImageDraw, a: tuple[float, float], b: tuple[float, float], width: float, fill) -> None:
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    size = max(width * 3.2, 14 * SS)
    for s in (-1, 1):
        t = ang + math.pi + s * math.radians(28)
        d.line([b, (b[0] + size * math.cos(t), b[1] + size * math.sin(t))], fill=fill, width=max(1, round(width)))
    r = width / 2
    d.ellipse((b[0] - r, b[1] - r, b[0] + r, b[1] + r), fill=fill)


def _shape(layer: ImageDraw.ImageDraw, s: Shape, W: int, H: int, canvas_h: int) -> None:
    rgb = _rgb(s.color)
    alpha = round(255 * (0.4 if s.type == "highlight" else s.opacity))
    fill = (*rgb, alpha)
    width = max(1.0, canvas_h * SS * s.width / 100) * (3 if s.type == "highlight" else 1)
    pts = [_px(p, W, H) for p in s.points]
    if not pts:
        return
    if s.type in ("pen", "highlight"):
        _stroke(layer, pts, width, fill)
    elif s.type in ("line", "arrow") and len(pts) >= 2:
        a, b = pts[0], pts[-1]
        _stroke(layer, [a, b], width, fill)
        if s.type == "arrow":
            _arrow_head(layer, a, b, width, fill)
    elif s.type in ("rect", "ellipse") and len(pts) >= 2:
        x0, x1 = sorted((pts[0][0], pts[-1][0]))
        y0, y1 = sorted((pts[0][1], pts[-1][1]))
        if x1 - x0 < 2 or y1 - y0 < 2:
            return
        f = (*_rgb(s.fill_color or s.color), round(255 * s.fill_opacity)) if s.filled else None
        kw = {"fill": f, "outline": fill, "width": max(1, round(width))}
        if s.type == "rect":
            layer.rounded_rectangle((x0, y0, x1, y1), radius=min(width, (x1 - x0) / 4, (y1 - y0) / 4), **kw)
        else:
            layer.ellipse((x0, y0, x1, y1), **kw)


def render_drawing_png(d: Drawing, canvas_w: int, canvas_h: int, dest: Path) -> tuple[int, int]:
    """Writes one transparent canvas-sized PNG with every shape of the drawing. Returns its size."""
    W, H = canvas_w * SS, canvas_h * SS
    # every shape is drawn on its own layer so a see-through highlight does not darken where it overlaps itself
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for s in d.shapes:
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        _shape(ImageDraw.Draw(layer), s, W, H, canvas_h)
        img = Image.alpha_composite(img, layer)
    img = img.resize((canvas_w, canvas_h), Image.LANCZOS)
    if d.opacity < 0.999:
        img.putalpha(img.getchannel("A").point(lambda v: int(v * d.opacity)))
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest)
    return img.size


def render_image_overlay_png(ov, src, W: int, H: int, out) -> None:
    """Puts the picture at its place on a transparent canvas-sized sheet (scaled, turned, see-through)."""
    from pathlib import Path

    from PIL import Image

    sheet = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    with Image.open(Path(src)) as im:
        im = im.convert("RGBA")
        w = max(2, int(ov.size * W))
        h = max(2, int(im.height * w / max(1, im.width)))
        im = im.resize((w, h), Image.LANCZOS)
    if ov.rotation:
        im = im.rotate(-ov.rotation, expand=True, resample=Image.BICUBIC)
    if ov.opacity < 1:
        a = im.getchannel("A").point(lambda v: int(v * ov.opacity))
        im.putalpha(a)
    sheet.paste(im, (int(ov.x * W - im.width / 2), int(ov.y * H - im.height / 2)), im)
    sheet.save(out)
