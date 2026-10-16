from ltxps.setup_plan import build_plan


def plan(**kw):
    base = dict(ram_gb=16, vram_gb=6, gpu_ok=True, disk_free_gb=200, default_model="ltxv-2b-distilled", is_installed=lambda i: False)
    return build_plan(**{**base, **kw})


def test_plan_picks_one_of_each_kind_and_checks_disk():
    p = plan()
    ids = [i["id"] for i in p["items"]]
    assert ids == ["ltxv-base", "ltxv-2b-distilled", "whisper-small", "image-sd-turbo", "image-inpaint"]
    assert p["enough_disk"] and p["missing_bytes"] > 10e9
    assert not plan(disk_free_gb=5)["enough_disk"]


def test_small_memory_gets_lighter_captions_and_installed_items_are_not_counted():
    p = plan(ram_gb=8, is_installed=lambda i: i == "ltxv-base")
    assert [i["id"] for i in p["items"]][2] == "whisper-base"
    assert p["missing_bytes"] < 12e9
    assert "No graphics card" in plan(gpu_ok=False, vram_gb=0)["summary"]


from conftest import needs_ffmpeg  # noqa: E402
from test_api import client  # noqa: E402,F401


@needs_ffmpeg
def test_setup_endpoints(client, monkeypatch):
    p = client.get("/api/setup/plan").json()
    assert p["items"][0]["id"] == "ltxv-base" and p["items"][-1]["id"] == "image-inpaint"
    kinds = {m["id"]: m["kind"] for m in client.get("/api/models").json()["items"]}
    assert kinds["image-sd-turbo"] == "image" and kinds["whisper-base"] == "captions"
    monkeypatch.setattr("ltxps.updates.fetch_manifest", lambda url: {"modules": [{"name": "pillow", "version": "99.0.0"}]})
    t = client.get("/api/updates/modules").json()
    assert t["online"] and {r["name"]: r for r in t["modules"]}["pillow"]["recommended"] == "99.0.0"
    assert client.post("/api/updates/modules/install", json={"name": "torch", "version": "2.0"}).status_code == 422


def test_local_picture_model_is_used_once_installed(tmp_path):
    from ltxps.assistant.service import build_assistant_state

    a = build_assistant_state(tmp_path / "a", "t")
    a.models_root = tmp_path / "models"
    assert a.image_config().provider == "horde"
    (a.models_root / "image-sd-turbo").mkdir(parents=True)
    (a.models_root / "image-sd-turbo" / ".complete.json").write_text("{}")
    assert a.image_config().provider == "local" and a.image_config().local_dir
    a.settings.update({"image": {"provider": "pollinations"}})  # a deliberate choice wins
    assert a.image_config().provider == "pollinations"
