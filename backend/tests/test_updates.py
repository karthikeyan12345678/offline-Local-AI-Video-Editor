import json
from pathlib import Path

import pytest

from ltxps import __version__, updates

ROOT = Path(__file__).resolve().parents[2]


def fake(app="9.9.9", mods=None):
    return lambda _url: {"app_version": app, "download_url": "https://x", "notes": "n", "modules": mods or [{"name": "faster-whisper", "version": "9.0.0"}, {"name": "pillow", "version": "0.0.1"}]}


def test_check_reports_app_and_module_updates():
    r = updates.check(fake(), installed=lambda n: {"faster-whisper": "1.2.1", "pillow": "12.0"}.get(n))
    assert r["app_update"] and r["latest"] == "9.9.9" and r["current"] == __version__
    byname = {m["name"]: m for m in r["modules"]}
    assert byname["faster-whisper"]["update"] and not byname["pillow"]["update"]
    assert r["modules_update"]


def test_missing_module_counts_as_update_and_same_version_does_not():
    r = updates.check(fake(app=__version__, mods=[{"name": "opencv-python-headless", "version": "5.0.0.93"}]), installed=lambda n: None)
    assert not r["app_update"] and r["modules"][0]["missing"] and r["modules_update"]
    r = updates.check(fake(app=__version__, mods=[{"name": "a", "version": "1.2.3"}]), installed=lambda n: "1.2.3")
    assert not r["modules_update"]


def test_update_installs_only_what_is_outdated():
    calls = []
    out = updates.update_modules(fake(), lambda n: {"faster-whisper": "1.0", "pillow": "99"}.get(n), lambda specs, on_line, cancel=None: calls.append(specs))
    assert calls == [["faster-whisper==9.0.0"]] and out["updated"] == ["faster-whisper"] and out["restart"]


def test_nothing_to_do_returns_quietly():
    out = updates.update_modules(fake(), lambda n: "999", lambda *a, **k: pytest.fail("should not install"))
    assert out == {"updated": [], "restart": False}


def test_manifest_in_repo_matches_version_and_requirements():
    """If this fails run: python scripts/make_update_manifest.py "what is new" and commit update-manifest.json"""
    m = json.loads((ROOT / "update-manifest.json").read_text(encoding="utf-8"))
    want = updates.manifest_from_requirements((ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8"), __version__, only=updates.UPDATABLE)
    assert m["app_version"] == __version__
    assert m["modules"] == want["modules"]


def test_version_compare():
    assert updates.vtuple("1.10.0") > updates.vtuple("1.9.9")
    assert updates.vtuple("5.0.0.93") > updates.vtuple("5.0.0")


def test_endpoint_reports_friendly_error_when_offline(monkeypatch):
    monkeypatch.setenv("LTXPS_UPDATE_URL", "http://127.0.0.1:9/none.json")
    with pytest.raises(updates.UpdateError):
        updates.check()


def test_history_and_table(tmp_path):
    h = tmp_path / "h.json"
    updates.remember_version(h, "pillow", "10.0.0")
    updates.remember_version(h, "pillow", "11.0.0")
    updates.remember_version(h, "pillow", "10.0.0")
    assert updates.read_history(h)["pillow"] == ["10.0.0", "11.0.0"]
    rows = {r["name"]: r for r in updates.module_table(updates.read_history(h), installed=lambda n: "11.0.0" if n == "pillow" else None, recommended={"pillow": "12.0.0"})}
    assert rows["pillow"]["previous"] == ["10.0.0"] and rows["pillow"]["recommended"] == "12.0.0" and rows["pillow"]["installed"] == "11.0.0"
    assert rows["httpx"]["installed"] is None


def test_only_known_modules_and_clean_versions_can_be_installed():
    assert updates.valid_install("pillow", "11.0.1") == "pillow==11.0.1"
    for bad in (("pillow", "1.0; rm -rf"), ("pillow", "1.0 --index-url x"), ("torch", "2.0"), ("evil-pkg", "1.0")):
        with pytest.raises(updates.UpdateError):
            updates.valid_install(*bad)
