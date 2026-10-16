"""Design themes for generated files, plus the 'best design' recommender.

The catalog (themes.json) is distilled from Open Design's design-systems (Apache-2.0): palette, font names, category.
Every palette used in a file is passed through `document_palette`, which guarantees readable contrast.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOG = Path(__file__).with_name("themes.json")


# ------------------------------------------------------------------ colour maths (WCAG 2.x)
def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, round(c))) for c in rgb))


def luminance(h: str) -> float:
    def f(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = hex_to_rgb(h)
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def mix(a: str, b: str, t: float) -> str:
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return rgb_to_hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))  # type: ignore[arg-type]


def ensure_contrast(color: str, bg: str, ratio: float = 4.5) -> str:
    """Nudges `color` towards black or white (whichever is further from `bg`) until it reaches `ratio` against `bg`."""
    if contrast(color, bg) >= ratio:
        return color
    target = "#000000" if luminance(bg) > 0.4 else "#FFFFFF"
    for i in range(1, 21):
        c = mix(color, target, i / 20)
        if contrast(c, bg) >= ratio:
            return c
    return target


# ------------------------------------------------------------------ catalog
@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    category: str
    description: str
    colors: dict[str, str]
    fonts: dict[str, str]

    @property
    def dark(self) -> bool:
        return luminance(self.colors["bg"]) < 0.25

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "category": self.category, "description": self.description, "colors": self.colors, "fonts": self.fonts, "dark": self.dark}


@lru_cache(maxsize=1)
def catalog() -> dict[str, Theme]:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    return {t["id"]: Theme(t["id"], t["name"], t["category"], t["description"], t["colors"], t["fonts"]) for t in data["themes"]}


_EXTRA: dict[str, Theme] = {}


def register_theme(theme: Theme) -> None:
    """Adds a one-off theme (for example one copied from a reference file) so build_file can use it by id."""
    _EXTRA[theme.id] = theme


def get_theme(theme_id: str | None) -> Theme:
    if theme_id and theme_id in _EXTRA:
        return _EXTRA[theme_id]
    cat = catalog()
    if theme_id and theme_id in cat:
        return cat[theme_id]
    return cat.get("claude") or next(iter(cat.values()))


# ------------------------------------------------------------------ document palette and fonts
@dataclass(frozen=True)
class Palette:
    """Colours for one file. `paper` is the page background, `text`/`heading`/`accent` all pass WCAG AA on it."""

    theme_id: str
    paper: str
    text: str
    heading: str
    muted: str
    accent: str
    accent_on: str
    rule: str
    surface: str
    dark: bool
    font_display: str
    font_body: str
    font_kind: str  # serif | sans | mono: drives the fallback when a font is not installed


SAFE_FONTS = {
    "serif": ["Georgia", "Cambria", "Times New Roman"], "sans": ["Calibri", "Segoe UI", "Arial"], "mono": ["Consolas", "Courier New"],
}
KNOWN_SAFE = {f.lower(): f for fs in SAFE_FONTS.values() for f in fs} | {"verdana": "Verdana", "tahoma": "Tahoma", "trebuchet ms": "Trebuchet MS", "helvetica": "Arial", "inter": "Calibri"}


def safe_font(name: str, kind: str) -> str:
    """Brand fonts are rarely installed on the reader's PC, so use the brand font only if it is a common one."""
    return KNOWN_SAFE.get(name.lower().strip(), SAFE_FONTS.get(kind, SAFE_FONTS["sans"])[0])


def document_palette(theme: Theme, *, on_slides: bool = False) -> Palette:
    """`on_slides=True` keeps dark themes dark (slides are viewed on screens); printed documents get white paper."""
    c = theme.colors
    dark = theme.dark
    if dark and not on_slides:
        paper, text, base_head, surface = "#FFFFFF", "#1A1A1A", c["accent"], mix("#FFFFFF", c["bg"], 0.06)
    else:
        paper, text, base_head, surface = c["bg"], c["fg"], c.get("fg", c["accent"]), c.get("surface", c["bg"])
    accent = ensure_contrast(c["accent"], paper, 3.0)  # large shapes and rules only need 3:1
    heading = ensure_contrast(c["accent"] if (dark and not on_slides) else base_head, paper, 4.5)
    text = ensure_contrast(text, paper, 7.0)
    muted = ensure_contrast(c.get("muted", mix(text, paper, 0.4)), paper, 4.5)
    accent_on = c.get("accent-on", "#FFFFFF")
    if contrast(accent_on, accent) < 4.5:
        accent_on = "#000000" if contrast("#000000", accent) >= contrast("#FFFFFF", accent) else "#FFFFFF"
    f = theme.fonts
    return Palette(
        theme.id, paper, text, heading, muted, accent, accent_on, c.get("border-soft", mix(paper, text, 0.15)), surface, dark and on_slides,
        safe_font(f.get("display", ""), f.get("display_kind", "sans")), safe_font(f.get("body", ""), f.get("body_kind", "sans")), f.get("body_kind", "sans"),
    )


# ------------------------------------------------------------------ recommender
# purpose words -> categories (or theme ids) that tend to suit them
INTENT_MAP: list[tuple[set[str], list[str], str]] = [
    ({"resume", "cv", "curriculum", "cover", "letter", "job", "application"}, ["Professional & Corporate", "Modern & Minimal", "Editorial & Print"], "clean, conservative and easy for recruiters to scan"),
    ({"pitch", "investor", "startup", "funding", "fintech", "bank", "finance", "financial", "payment", "invoice"}, ["Fintech & Crypto", "Professional & Corporate", "Productivity & SaaS"], "credible and numbers-friendly"),
    ({"developer", "api", "code", "engineering", "technical", "docs", "documentation", "devops", "runbook"}, ["Developer Tools", "Backend & Data", "Modern & Minimal"], "built for technical readers"),
    ({"ai", "llm", "assistant", "chatbot", "model", "machine"}, ["AI & LLM", "Developer Tools", "Modern & Minimal"], "familiar from AI products"),
    ({"marketing", "campaign", "launch", "brand", "product", "promo", "sales"}, ["Bold & Expressive", "Media & Consumer", "E-Commerce & Retail"], "eye-catching and persuasive"),
    ({"report", "annual", "quarterly", "board", "executive", "summary", "proposal", "business", "consulting", "client"}, ["Professional & Corporate", "Productivity & SaaS", "Modern & Minimal"], "serious and well structured"),
    ({"magazine", "article", "blog", "essay", "newsletter", "story", "editorial", "portfolio", "book"}, ["Editorial & Print", "Creative & Artistic", "Editorial · Studio", "Editorial / Personal / Publication"], "made for reading"),
    ({"retail", "shop", "store", "ecommerce", "catalogue", "catalog", "menu", "restaurant", "cafe"}, ["E-Commerce & Retail", "Media & Consumer", "Bold & Expressive"], "warm and product-first"),
    ({"car", "automotive", "vehicle", "motor", "racing"}, ["Automotive", "Bold & Expressive"], "high-contrast and dynamic"),
    ({"creative", "art", "design", "studio", "agency", "poster", "event", "wedding"}, ["Creative & Artistic", "Design & Creative", "Bold & Expressive"], "expressive and visual"),
    ({"retro", "vintage", "classic", "nostalgic"}, ["Retro & Nostalgic"], "nostalgic"),
    ({"school", "education", "training", "course", "lesson", "student", "teaching", "workshop"}, ["Productivity & SaaS", "Modern & Minimal", "Media & Consumer"], "clear and friendly for learners"),
    ({"healthcare", "medical", "clinic", "hospital", "health", "patient"}, ["Professional & Corporate", "Modern & Minimal"], "calm and trustworthy"),
]
DARK_WORDS = {"dark", "night", "cinematic", "dramatic", "gaming", "neon"}
LIGHT_WORDS = {"light", "clean", "print", "printed", "minimal", "white", "paper"}


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def recommend(purpose: str, doc_type: str = "document", limit: int = 5, prefer: str | None = None) -> list[dict[str, Any]]:
    """Ranks themes for a purpose, e.g. 'investor pitch for a fintech startup'. Pure rules, so the result is explainable and works offline."""
    words = tokens(purpose) | tokens(doc_type)
    want_cats: dict[str, tuple[float, str]] = {}
    for keys, cats, why in INTENT_MAP:
        hit = keys & words
        if hit:
            for rank, cat in enumerate(cats):
                score = (3.0 - rank * 0.7) * (1 + 0.25 * (len(hit) - 1))
                if cat not in want_cats or want_cats[cat][0] < score:
                    want_cats[cat] = (score, why)
    wants_dark, wants_light = bool(DARK_WORDS & words), bool(LIGHT_WORDS & words) or doc_type in {"pdf", "docx", "doc", "resume"}
    print_doc = doc_type in {"pdf", "docx", "doc", "resume"}
    ranked = []
    for t in catalog().values():
        score, reasons = 0.0, []
        if t.category in want_cats:
            s, why = want_cats[t.category]
            score += s
            reasons.append(f"{t.category.lower()} look, {why}")
        desc = tokens(t.description + " " + t.name)
        overlap = (words & desc) - {"for", "the", "and", "a", "of", "to", "in", "with"}
        if overlap:
            score += 0.6 * min(len(overlap), 4)
            reasons.append("matches: " + ", ".join(sorted(overlap)[:4]))
        pal = document_palette(t, on_slides=not print_doc)
        ratio = contrast(pal.text, pal.paper)
        score += 0.5 if ratio >= 12 else 0.3 if ratio >= 7 else 0
        if t.dark and wants_dark:
            score += 1.0
            reasons.append("dark theme as asked")
        if not t.dark and wants_light:
            score += 0.4
        if t.dark and print_doc and not wants_dark:
            score -= 0.8  # dark pages waste ink and print badly
        if prefer and prefer.lower() in (t.id, t.name.lower()):
            score += 5
        ranked.append((score, t, reasons, ratio))
    ranked.sort(key=lambda r: (-r[0], r[1].name))
    out = []
    for score, t, reasons, ratio in ranked[:limit]:
        out.append({**t.to_json(), "score": round(score, 2), "reasons": reasons or ["balanced general-purpose palette"], "text_contrast": round(ratio, 1)})
    return out
