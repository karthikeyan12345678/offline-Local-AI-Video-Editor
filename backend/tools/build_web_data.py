"""Writes the static data files the browser version loads (catalog, sound list, sound files, font list).

Run from the backend folder:  python tools/build_web_data.py
Output goes to ../frontend/public/data. The files are committed, so a static host
(GitHub Pages, Netlify) needs no Python at build time.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ltxps.assistant import llm  # noqa: E402
from ltxps.editor import audiofx, effects, fonts, soundfx  # noqa: E402
from ltxps.editor.project import TEXT_ANIM_IN, TEXT_ANIM_OUT  # noqa: E402

OUT = ROOT.parent / "frontend" / "public" / "data"


def catalog() -> dict:
    return {
        "transitions": [{"id": i, "label": l, "group": g} for i, l, g in effects.TRANSITION_INFO],
        "looks": [{"id": i, "label": effects.PRESET_LABELS.get(i, i), "group": effects.LOOK_GROUP.get(i, "Other")} for i in effects.FILTER_PRESETS],
        "effects": [{"id": i, "label": l, "group": effects.EFFECT_GROUP.get(i, "Other")} for i, l in effects.EFFECT_INFO],
        "masks": [{"id": i, "label": l} for i, l in effects.MASK_INFO],
        "motions": [{"id": i, "label": l} for i, l in effects.MOTION_INFO],
        "audio_fx": [{"id": i, "label": l, "group": g} for i, l, g in audiofx.AUDIO_FX_INFO],
        "fonts": [{"id": f.id, "label": f.label, "category": f.category, "scripts": list(f.scripts), "bold": bool(f.bold) or f.variable,
                   "file": f.regular, "file_bold": f.bold or f.regular} for f in fonts.catalog().values()],
        "text_anim_in": list(TEXT_ANIM_IN), "text_anim_out": list(TEXT_ANIM_OUT), "whisper": [],
    }


def sound_list() -> dict:
    return {"groups": soundfx.GROUP_ORDER, "sounds": soundfx.catalog()}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cat = catalog()
    (OUT / "catalog.json").write_text(json.dumps(cat, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    sounds_dir = OUT / "sounds"
    sounds_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for sid in soundfx.SOUNDS:
            wav = soundfx.ensure(sid, Path(tmp))
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "96k", str(sounds_dir / f"{sid}.mp3")], check=True)
    (OUT / "sounds.json").write_text(json.dumps(sound_list(), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    presets = {k: v for k, v in llm.PRESETS.items()}
    (OUT / "llm-presets.json").write_text(json.dumps(presets, ensure_ascii=False, indent=1), encoding="utf-8")

    fdir = ROOT.parent / "frontend" / "public" / "fonts"
    if fdir.exists():
        shutil.rmtree(fdir)
    shutil.copytree(fonts.FONT_DIR, fdir)
    print("web data written to", OUT)


if __name__ == "__main__":
    main()
