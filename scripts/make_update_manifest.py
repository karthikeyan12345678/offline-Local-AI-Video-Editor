"""Writes update-manifest.json at the repository root. Run it whenever you raise the version or change requirements.txt:

    python scripts/make_update_manifest.py "Short note about what is new"
"""
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
from ltxps import __version__  # noqa: E402
from ltxps.updates import UPDATABLE, json_text, manifest_from_requirements  # noqa: E402

notes = sys.argv[1] if len(sys.argv) > 1 else ""
text = (root / "backend" / "requirements.txt").read_text(encoding="utf-8")
m = manifest_from_requirements(text, __version__, notes, "https://github.com/karthikeyan12345678/offline-Local-AI-Video-Editor/releases/latest", UPDATABLE)
(root / "update-manifest.json").write_text(json_text(m), encoding="utf-8")
print("wrote", root / "update-manifest.json")
