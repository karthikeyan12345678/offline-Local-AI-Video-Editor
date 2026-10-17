import time

import pytest
from fastapi.testclient import TestClient

from conftest import needs_ffmpeg
from ltxps.app import create_app
from ltxps.state import build_state

pytestmark = needs_ffmpeg
TOKEN = "test-token"


@pytest.fixture()
def client(data_dir, monkeypatch):
    monkeypatch.setenv("LTXPS_ENGINE", "fake")
    monkeypatch.setenv("LTXPS_FAKE_VRAM_MB", "4096")
    state = build_state(TOKEN)
    with TestClient(create_app(state), headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        c.state = state  # type: ignore[attr-defined]
        yield c


def wait(client, job, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{job['id']}").json()
        if j["status"] in ("done", "error", "cancelled"):
            return j
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def upload(client, path, name=None):
    with open(path, "rb") as fh:
        r = client.post("/api/assets/upload", files={"file": (name or path.name, fh)})
    assert r.status_code == 200, r.text
    return r.json()


def test_every_route_requires_the_token(data_dir, monkeypatch):
    monkeypatch.setenv("LTXPS_ENGINE", "fake")
    with TestClient(create_app(build_state(TOKEN))) as c:
        assert c.get("/api/system").status_code == 401
        assert c.get("/api/assets", headers={"Authorization": "Bearer nope"}).status_code == 401
        assert c.get("/api/health?t=" + TOKEN).status_code == 200  # media elements pass the token in the URL


def test_requests_from_other_hostnames_are_rejected(data_dir, monkeypatch):
    monkeypatch.setenv("LTXPS_ENGINE", "fake")
    with TestClient(create_app(build_state(TOKEN)), base_url="http://evil.example") as c:
        assert c.get("/api/health", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 400


def test_four_gb_gpu_is_reported_as_lite_profile(client):
    s = client.get("/api/system").json()
    assert s["profile"] == "lite" and s["gpu"]["vram_gb"] == 4.0
    lim = client.get("/api/limits").json()
    assert lim["profile"]["id"] == "lite" and lim["profile"]["max_frames"] == 97
    assert any(r["width"] == 512 and r["height"] == 320 for r in lim["profile"]["resolutions"])


def test_generation_end_to_end_adds_a_playable_clip_to_the_library(client):
    r = client.post("/api/generate", json={"prompt": "a lighthouse at dawn", "width": 384, "height": 256, "frames": 25, "seed": 5})
    assert r.status_code == 200, r.text
    job = wait(client, r.json())
    assert job["status"] == "done", job
    a = next(x for x in client.get("/api/assets").json() if x["id"] == job["result"]["asset_id"])
    assert a["kind"] == "video" and a["source"] == "generated" and a["meta"]["seed"] == 5 and a["width"] == 384
    f = client.get(f"/api/assets/{a['id']}/file", headers={"Range": "bytes=0-99"})
    assert f.status_code == 206 and len(f.content) == 100  # seeking works in <video>
    assert client.get(f"/api/assets/{a['id']}/thumb").status_code == 200


def test_request_beyond_the_4gb_budget_is_refused_with_a_reason(client):
    r = client.post("/api/generate", json={"prompt": "x", "width": 1216, "height": 704, "frames": 121})
    assert r.status_code == 422 and "Lite" in r.json()["detail"]
    r = client.post("/api/generate", json={"prompt": "x", "width": 512, "height": 320, "frames": 200})
    assert r.status_code == 422 and "frames" in r.json()["detail"]


def test_sizes_snap_to_what_the_model_accepts(client):
    job = wait(client, client.post("/api/generate", json={"prompt": "x", "width": 500, "height": 330, "frames": 30}).json())
    a = client.get("/api/assets").json()[0]
    assert (a["width"], a["height"]) == (480, 320) and a["meta"]["frames"] == 25


def test_unlock_limits_allows_large_requests(client):
    r = client.post("/api/generate", json={"prompt": "x", "width": 1216, "height": 704, "frames": 121, "unlock_limits": True})
    assert r.status_code == 200
    client.post(f"/api/jobs/{r.json()['id']}/cancel")


def test_random_seed_is_recorded_so_a_result_can_be_reproduced(client):
    job = wait(client, client.post("/api/generate", json={"prompt": "x", "width": 384, "height": 256, "frames": 9}).json())
    seed = client.get("/api/assets").json()[0]["meta"]["seed"]
    assert isinstance(seed, int) and seed >= 0


def test_image_to_video_needs_an_image_from_the_library(client, media):
    assert client.post("/api/generate", json={"prompt": "x", "mode": "i2v"}).status_code == 422
    img = upload(client, media["image"])
    assert img["kind"] == "image"
    r = client.post("/api/generate", json={"prompt": "pan across", "mode": "i2v", "image_asset_id": img["id"], "width": 384, "height": 256, "frames": 9})
    assert wait(client, r.json())["status"] == "done"


def test_start_and_end_pictures(client, media):
    img = upload(client, media["image"])
    vid = upload(client, media["av"])
    base = {"prompt": "walk", "mode": "i2v", "image_asset_id": img["id"], "width": 384, "height": 256, "frames": 9}
    r = client.post("/api/generate", json={**base, "end_image_asset_id": vid["id"]})
    assert r.status_code == 422
    r = client.post("/api/generate", json={**base, "end_image_asset_id": img["id"]})
    job = wait(client, r.json())
    assert job["status"] == "done"
    made = next(x for x in client.get("/api/assets").json() if x["id"] == job["result"]["asset_id"])
    assert made["meta"]["end_image_asset_id"] == img["id"] and made["meta"]["end_image"] is True


def test_continue_a_clip_from_its_last_frame(client, media):
    clip = upload(client, media["av"])
    r = client.post("/api/generate/extend", json={"prompt": "the camera keeps moving", "source_asset_id": clip["id"], "width": 384, "height": 256, "frames": 9})
    assert r.status_code == 200, r.text
    job = wait(client, r.json())
    assert job["status"] == "done"
    made = next(x for x in client.get("/api/assets").json() if x["id"] == job["result"]["asset_id"])
    assert made["meta"]["continues"] == clip["id"]


def test_cancelling_a_running_generation(client):
    r = client.post("/api/generate", json={"prompt": "x", "width": 384, "height": 256, "frames": 9})
    time.sleep(0.2)
    assert client.post(f"/api/jobs/{r.json()['id']}/cancel").json()["ok"]
    assert wait(client, r.json())["status"] == "cancelled"
    assert client.get("/api/assets").json() == []


def test_upload_rejects_unsupported_and_unreadable_files(client, tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hi")
    with open(bad, "rb") as fh:
        assert client.post("/api/assets/upload", files={"file": ("notes.txt", fh)}).status_code == 422
    fake = tmp_path / "broken.mp4"
    fake.write_bytes(b"not a video at all")
    with open(fake, "rb") as fh:
        r = client.post("/api/assets/upload", files={"file": ("broken.mp4", fh)})
    assert r.status_code == 422 and client.get("/api/assets").json() == []  # nothing left behind


def test_upload_reads_media_properties(client, media):
    a = upload(client, media["av"])
    assert (a["width"], a["height"], a["has_audio"]) == (640, 360, True) and a["duration"] == pytest.approx(3.0, abs=0.1)
    assert upload(client, media["audio"])["kind"] == "audio"


def test_quick_tool_makes_a_new_library_item(client, media):
    clip = upload(client, media["silent"])
    job = wait(client, client.post("/api/editor/tools/boomerang", json={"asset_id": clip["id"]}).json())
    assert job["status"] == "done"
    made = next(x for x in client.get("/api/assets").json() if x["id"] == job["result"]["asset_id"])
    assert made["duration"] == pytest.approx(4.0, abs=0.2) and made["source"] == "edit"


def test_quick_tool_errors_are_readable(client, media):
    clip = upload(client, media["silent"])
    job = wait(client, client.post("/api/editor/tools/extract_audio", json={"asset_id": clip["id"]}).json())
    assert job["status"] == "error" and "no audio" in job["error"]
    assert client.post("/api/editor/tools/stabilize", json={"asset_id": upload(client, media["audio"])["id"]}).status_code == 422


def test_export_project_to_library_and_hide_previews(client, media):
    a, b = upload(client, media["av"]), upload(client, media["silent"])
    project = {
        "name": "My film", "canvas": {"width": 640, "height": 360, "fps": 24},
        "clips": [
            {"id": "c1", "asset_id": a["id"], "transition": {"type": "fade", "duration": 0.5}},
            {"id": "c2", "asset_id": b["id"]},
        ],
        "texts": [{"id": "t1", "text": "Hello", "start": 0, "duration": 2}],
    }
    job = wait(client, client.post("/api/editor/export", json={"project": project, "options": {"format": "mp4"}}).json())
    assert job["status"] == "done", job
    out = next(x for x in client.get("/api/assets").json() if x["id"] == job["result"]["asset_id"])
    assert out["source"] == "export" and out["duration"] == pytest.approx(4.5, abs=0.25)

    prev = wait(client, client.post("/api/editor/export", json={"project": project, "options": {"preview": True}}).json())
    assert prev["status"] == "done"
    assert prev["result"]["asset_id"] not in [x["id"] for x in client.get("/api/assets").json()]
    assert client.get(f"/api/assets/{prev['result']['asset_id']}/file").status_code == 200


def test_export_with_empty_timeline_explains_what_to_do(client):
    job = wait(client, client.post("/api/editor/export", json={"project": {"name": "x", "clips": []}}).json())
    assert job["status"] == "error" and "at least one clip" in job["error"]


def test_export_with_a_deleted_media_file_is_refused_early(client, media):
    a = upload(client, media["av"])
    client.delete(f"/api/assets/{a['id']}")
    r = client.post("/api/editor/export", json={"project": {"name": "x", "clips": [{"id": "c", "asset_id": a["id"]}]}})
    assert r.status_code == 422


def test_invalid_project_values_are_rejected(client, media):
    a = upload(client, media["av"])
    bad = {"name": "x", "clips": [{"id": "c", "asset_id": a["id"], "speed": 50}]}
    assert client.post("/api/editor/export", json={"project": bad}).status_code == 422
    bad = {"name": "x", "clips": [{"id": "c", "asset_id": a["id"], "transition": {"type": "explode"}}]}
    assert client.post("/api/editor/export", json={"project": bad}).status_code == 422


def test_project_save_load_roundtrip(client):
    p = {"name": "Draft", "clips": [{"id": "c", "asset_id": "zzz", "speed": 2}]}
    assert client.put("/api/projects/p1", json=p).status_code == 200
    got = client.get("/api/projects/p1").json()
    assert got["name"] == "Draft" and got["clips"][0]["speed"] == 2 and got["id"] == "p1"
    assert [x["id"] for x in client.get("/api/projects").json()] == ["p1"]
    client.delete("/api/projects/p1")
    assert client.get("/api/projects/p1").status_code == 404


def test_delete_asset_removes_the_files(client, media):
    a = upload(client, media["av"])
    path = client.state.db.get_asset(a["id"]).path  # type: ignore[attr-defined]
    from pathlib import Path
    assert Path(path).exists()
    client.delete(f"/api/assets/{a['id']}")
    assert not Path(path).exists() and client.get(f"/api/assets/{a['id']}/file").status_code == 404


def test_settings_validation_and_persistence(client):
    assert client.put("/api/settings", json={"profile": "huge"}).status_code == 422
    assert client.put("/api/settings", json={"default_model": "nope"}).status_code == 422
    r = client.put("/api/settings", json={"profile": "balanced", "hf_endpoint": "https://hf-mirror.example/"}).json()
    assert r["profile"] == "balanced" and r["hf_endpoint"] == "https://hf-mirror.example"
    assert client.get("/api/limits").json()["profile"]["id"] == "balanced"


# ------------------------------------------------------------------ 1.2.11: key cleanup, estimate, usage, limits
def test_fal_key_is_cleaned_and_validated(tmp_path):
    from ltxps.editor import motion

    assert motion.clean_key('abc123:secret_value') == "abc123:secret_value"
    assert motion.clean_key('Key abc123:secret_value') == "abc123:secret_value"
    assert motion.clean_key('{"fal_key": "abc123:secret_value", "mode": "std"}') == "abc123:secret_value"
    assert motion.clean_key('"abc123:secret_value"}') == "abc123:secret_value"
    assert motion.clean_key("FAL_KEY=abc123:secret_value\n") == "abc123:secret_value"
    assert motion.key_problem("hello world") is not None
    st = motion.MotionSettings(tmp_path / "motion.json")
    (tmp_path / "motion.json").write_text('{"fal_key": "{\\"fal_key\\": \\"abc123:secret_value\\"}"}')  # the broken file the app used to save
    assert st.get()["fal_key"] == "abc123:secret_value"
    import pytest

    with pytest.raises(motion.MotionError):
        st.update("not a key at all", None)


def test_motion_settings_route_rejects_garbage(client):
    r = client.post("/api/motion/settings", json={"fal_key": "this is not a key"})
    assert r.status_code == 422 and "fal.ai key" in r.json()["detail"]
    ok = client.post("/api/motion/settings", json={"fal_key": '{"fal_key": "abc123:secret_value"}'})
    assert ok.status_code == 200 and ok.json()["has_key"] and ok.json()["key_hint"].endswith("alue")


def test_estimate_and_usage_routes(client):
    e = client.get("/api/estimate", params={"width": 512, "height": 320, "frames": 49}).json()
    assert e["seconds"] > 0 and e["band"] in ("fast", "ok", "slow", "too_long") and e["limit_seconds"] == 1800
    u = client.get("/api/usage").json()
    assert "cpu" in u and "vram_used_gb" in u
    s = client.put("/api/settings", json={"time_limit_min": 10, "tour_done": True}).json()
    assert s["time_limit_min"] == 10 and s["tour_done"] is True
    assert client.get("/api/estimate", params={"width": 512, "height": 320, "frames": 49}).json()["limit_seconds"] == 600


def test_prompt_enhance_route(client):
    r = client.post("/api/prompt/enhance", json={"prompt": "a car on a mountain road", "kind": "video"})
    assert r.status_code == 200 and "car" in r.json()["prompt"]
    assert client.get("/api/ai/advice").status_code in (200, 503)
