"""Learns the look and structure of a file the person shares, so a new PDF/Word/PowerPoint can follow it.

Only facts that can be read reliably are used: heading outline, section order, length, fonts, the main colour, and how long the paragraphs are.
"""

from __future__ import annotations

import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from .extract import ExtractError, extract
from .themes import Theme, catalog, contrast, hex_to_rgb, luminance, register_theme

_HEX = re.compile(r'(?:srgbClr val|w:color w:val|w:fill)="([0-9A-Fa-f]{6})"')
_FONT = re.compile(r'(?:w:ascii|typeface)="([^"]{2,40})"')


def _sat(h: str) -> float:
    r, g, b = (c / 255 for c in hex_to_rgb(h))
    mx, mn = max(r, g, b), min(r, g, b)
    return 0.0 if mx == 0 else (mx - mn) / mx


def _xml_style(path: Path) -> tuple[list[str], list[str]]:
    colors: Counter[str] = Counter()  # weights are floats
    fonts: Counter[str] = Counter()
    try:
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if n.endswith(".xml") and (n.startswith("word/") or n.startswith("ppt/slides/") or n.startswith("ppt/theme/")):
                    x = z.read(n).decode("utf-8", "ignore")
                    if n.startswith("word/theme/"):
                        continue  # the stock Office palette, not what the author chose
                    weight = 10 if n in ("word/document.xml",) or n.startswith("ppt/slides/") else 0.1  # colours used in the body count more than style defaults
                    for c in _HEX.findall(x):
                        colors[c.upper()] += weight
                    for f in _FONT.findall(x):
                        if not f.startswith(("+", "Symbol", "Wingdings")):
                            fonts[f] += weight
    except (zipfile.BadZipFile, OSError):
        return [], []
    return [c for c, _ in colors.most_common(12)], [f for f, _ in fonts.most_common(3)]


def _headings(ex: Any) -> list[str]:
    if ex.kind == "docx" and ex.facts.get("headings"):
        return ex.facts["headings"][:30]
    if ex.kind == "pptx":
        return [(u.split("\n", 1)[0]).strip()[:80] for u in ex.units if u.strip()][:30]
    out = []  # PDF / text: short, title-like lines that are not sentences
    for line in ex.text.splitlines():
        t = line.strip()
        if 3 <= len(t) <= 70 and not t.endswith((".", ",", ";")) and len(t.split()) <= 9 and (t.isupper() or t.istitle() or re.match(r"^\d+(\.\d+)*\s+\S", t)):
            out.append(t)
    return out[:30]


def profile(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    ex = extract(p)
    if ex.kind not in {"pdf", "docx", "pptx", "md", "txt"}:
        raise ExtractError("Use a PDF, Word, PowerPoint, Markdown or text file as the reference.")
    colors, fonts = _xml_style(p) if ex.kind in {"docx", "pptx"} else ([], [])
    paras = [u for u in ex.units if len(u.split()) > 12]
    avg_words = round(sum(len(u.split()) for u in paras) / len(paras)) if paras else 0
    bullets = len(re.findall(r"(?m)^\s*[•\-•●*]\s", ex.text))
    return {
        "name": ex.name, "kind": ex.kind, "outline": _headings(ex), "length": ex.facts.get("pages") or ex.facts.get("slides") or max(1, len(ex.text.split()) // 450),
        "words": len(ex.text.split()), "tables": len(ex.tables), "fonts": fonts, "colors": colors, "avg_paragraph_words": avg_words, "uses_bullets": bullets >= 4,
        "sample": ex.text[:1200],
    }


def theme_from(prof: dict[str, Any]) -> Theme | None:
    """A theme with the reference file's main colour and font, or None when it had none worth copying."""
    cols = ["#" + c.lstrip("#") for c in prof.get("colors", []) if _sat("#" + c.lstrip("#")) > 0.25 and 0.03 < luminance("#" + c.lstrip("#")) < 0.8]
    base = catalog().get("claude")
    if not cols or base is None:
        return None
    accent = cols[0]
    c = dict(base.colors)
    c.update({"bg": "#FFFFFF", "fg": "#1A1A1A", "surface": "#F5F6F8", "accent": accent, "meta": accent, "muted": "#5F6673", "border-soft": "#E3E6EB",
              "accent-on": "#FFFFFF" if contrast("#FFFFFF", accent) >= 4.5 else "#000000"})
    f = dict(base.fonts)
    if prof.get("fonts"):
        f.update({"display": prof["fonts"][0], "body": prof["fonts"][-1] if len(prof["fonts"]) > 1 else prof["fonts"][0]})
    th = Theme("reference", f"Like {prof['name']}", "Reference", "Copied from the file you shared.", c, f)
    register_theme(th)
    return th


def instructions(prof: dict[str, Any], fmt: str) -> str:
    """Words for the writing model: follow this file's structure and voice, but not its facts."""
    parts = [f"A reference file was shared (“{prof['name']}”). Match its STRUCTURE and VOICE for the new {fmt.upper()}; do not copy its facts or sentences."]
    if prof["outline"]:
        parts.append("Its sections, in order: " + " → ".join(prof["outline"][:18]) + ". Use the same kinds of sections in the same order, adapted to the new topic.")
    unit = "slides" if prof["kind"] == "pptx" else "pages"
    parts.append(f"It is about {prof['length']} {unit} / {prof['words']} words long; aim for a similar size.")
    if prof["avg_paragraph_words"]:
        parts.append(f"Its paragraphs average about {prof['avg_paragraph_words']} words: keep yours similar.")
    parts.append("It uses bullet lists a lot; do the same." if prof["uses_bullets"] else "It is mostly running prose; use bullets sparingly.")
    if prof["tables"]:
        parts.append(f"It contains {prof['tables']} table(s); include tables where this one did.")
    parts.append("Tone sample from the reference (imitate the register, not the content):\n" + re.sub(r"\s+", " ", prof["sample"])[:500])
    return "\n".join(parts)
