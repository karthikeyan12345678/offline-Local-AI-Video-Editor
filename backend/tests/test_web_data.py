"""The browser version loads static files made from the Python engine. They must never go stale."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT.parent / "frontend" / "public" / "data"

pytestmark = pytest.mark.skipif(not DATA.exists(), reason="the frontend folder is not here")


def tool():
    spec = importlib.util.spec_from_file_location("build_web_data", ROOT / "tools" / "build_web_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_catalog_file_matches_the_engine():
    mod = tool()
    assert json.loads((DATA / "catalog.json").read_text(encoding="utf-8")) == json.loads(json.dumps(mod.catalog())), "run: python tools/build_web_data.py"


def test_sound_list_and_files_match_the_engine():
    mod = tool()
    listed = json.loads((DATA / "sounds.json").read_text(encoding="utf-8"))
    assert listed == json.loads(json.dumps(mod.sound_list())), "run: python tools/build_web_data.py"
    for s in listed["sounds"]:
        f = DATA / "sounds" / f"{s['id']}.mp3"
        assert f.exists() and f.stat().st_size > 500, s["id"]


def test_every_font_in_the_catalog_ships_with_the_site():
    fonts = ROOT.parent / "frontend" / "public" / "fonts"
    rows = json.loads((fonts / "fonts.json").read_text(encoding="utf-8"))
    assert rows
    for r in rows:
        assert (fonts / r["regular"]).exists(), r["id"]
        if r.get("bold"):
            assert (fonts / r["bold"]).exists(), r["id"]


def test_the_browser_engine_modules_exist_and_do_not_need_a_server():
    editor = ROOT / "ltxps" / "editor"
    for name in ["effects", "audiofx", "soundfx", "fonts", "project", "textimage", "drawimage", "render", "chat"]:
        src = (editor / f"{name}.py").read_text(encoding="utf-8")
        for banned in ("import httpx", "import fastapi", "import torch", "import numpy", "import cv2"):
            assert banned not in src, f"{name}.py must stay free of `{banned}` so it runs in the browser"
