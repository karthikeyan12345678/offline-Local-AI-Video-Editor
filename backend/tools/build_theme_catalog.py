"""Builds ltxps/assistant/themes.json from a checkout of Open Design (Apache-2.0).

    python tools/build_theme_catalog.py path/to/open-design-main/design-systems

Only small facts are kept (name, category, one-line description, palette, font names), not the design prose.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

KEYS = ["bg", "surface", "surface-warm", "fg", "fg-2", "muted", "meta", "border", "border-soft", "accent", "accent-on", "success", "warn", "danger"]
HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def parse_vars(css: str) -> dict[str, str]:
    root = css[css.index(":root"):]
    block = root[root.index("{") + 1:]
    out: dict[str, str] = {}
    for m in re.finditer(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", block):
        out.setdefault(m.group(1), re.sub(r"/\*.*?\*/", "", m.group(2)).strip())
    return out


def resolve(value: str, v: dict[str, str], depth: int = 0) -> str | None:
    m = re.fullmatch(r"var\((--[a-z0-9-]+)(?:,[^)]*)?\)", value)
    if m and depth < 5:
        return resolve(v.get(m.group(1), ""), v, depth + 1)
    if HEX.match(value):
        if len(value) == 4:
            value = "#" + "".join(c * 2 for c in value[1:])
        return value.upper()
    return None


def first_font(stack: str) -> str:
    m = re.match(r"\s*(?:\"([^\"]+)\"|'([^']+)'|([A-Za-z0-9 -]+))", stack)
    return next((g for g in (m.groups() if m else ()) if g), "").strip()


def kind_of(stack: str) -> str:
    s = stack.lower()
    if "mono" in s or "consolas" in s or "courier" in s:
        return "mono"
    if "serif" in s and "sans-serif" not in s.split("serif")[0][-6:]:
        return "serif" if re.search(r"(?<!sans-)serif", s) else "sans"
    return "sans"


def main(root: Path, out: Path) -> None:
    themes = []
    for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")):
        tokens, manifest = d / "tokens.css", d / "manifest.json"
        if not tokens.exists() or not manifest.exists():
            continue
        v = parse_vars(tokens.read_text(encoding="utf-8"))
        colors = {k: c for k in KEYS if (c := resolve(v.get(f"--{k}", ""), v))}
        if not all(k in colors for k in ("bg", "fg", "accent")):
            continue
        info = json.loads(manifest.read_text(encoding="utf-8"))
        design = (d / "DESIGN.md")
        blurb = ""
        if design.exists():
            lines = design.read_text(encoding="utf-8").splitlines()[:8]
            cat = [i for i, l in enumerate(lines) if l.startswith("> Category:")]
            if cat and cat[0] + 1 < len(lines):
                blurb = lines[cat[0] + 1].lstrip("> ").strip()
        disp, body = v.get("--font-display", ""), v.get("--font-body", "")
        themes.append({
            "id": info["id"], "name": info["name"], "category": info.get("category", ""), "description": blurb or info.get("description", ""),
            "colors": colors,
            "fonts": {"display": first_font(disp), "body": first_font(body), "display_kind": kind_of(disp), "body_kind": kind_of(body)},
        })
    out.write_text(json.dumps({"source": "Open Design design-systems (Apache-2.0)", "themes": themes}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(themes)} themes -> {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(__file__).resolve().parents[1] / "ltxps" / "assistant" / "themes.json")
