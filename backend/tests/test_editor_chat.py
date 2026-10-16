"""The chat editor: reading the model's answer, applying actions safely, and the endpoint with a fake model."""

import json

import pytest
from fastapi.testclient import TestClient

from conftest import needs_ffmpeg
from fakeserver import Fake
from ltxps.app import create_app
from ltxps.assistant.service import build_assistant_state
from ltxps.editor import chat
from ltxps.editor.project import Project
from ltxps.state import build_state
from test_api import upload

TOKEN = "test-token"


def proj(n=2):
    return Project.model_validate({"clips": [{"id": f"c{i}", "asset_id": f"a{i}"} for i in range(n)]})


NAMES = {"a0": "beach.mp4", "a1": "city.mp4"}


def test_parse_handles_fences_thinking_and_garbage():
    r = chat.parse_answer('<think>hmm</think>```json\n{"reply":"ok","actions":[{"do":"set_canvas","ratio":"9:16"}]}\n```')
    assert r["reply"] == "ok" and r["actions"][0]["do"] == "set_canvas"
    r = chat.parse_answer('Sure! {"reply":"hi","actions":[]} thanks')
    assert r["reply"] == "hi"
    assert chat.parse_answer("just words")["actions"] == []


def test_actions_change_the_project():
    out = chat.apply_actions(proj(), [
        {"do": "set_canvas", "ratio": "9:16"},
        {"do": "set_clip", "target": "all", "set": {"speed": 2, "preset": "cinematic" if "cinematic" in chat.FILTER_PRESETS else "none", "adjust": {"brightness": 20}}},
        {"do": "set_transition", "target": "all", "type": "fade", "duration": 0.8},
        {"do": "add_text", "text": "Hello", "start": 1, "style": "neon"},
        {"do": "add_drawing", "start": 0, "duration": 2, "shapes": [{"type": "arrow", "points": [[0.1, 0.1], [0.5, 0.5]]}]},
        {"do": "task", "name": "captions", "target": "first", "language": "en"},
    ], NAMES)
    p = out["project"]
    assert (p.canvas.width, p.canvas.height) == (720, 1280)
    assert all(c.speed == 2 and c.adjust.brightness == 20 for c in p.clips)
    assert p.clips[0].transition.type == "fade" and p.clips[1].transition.type == "none"  # nothing after the last clip
    assert p.texts[0].font == "orbitron" and p.texts[0].glow > 0
    assert len(p.drawings) == 1
    assert out["tasks"] == [{"name": "captions", "clips": ["c0"], "language": "en"}]
    assert not out["skipped"], out["skipped"]


def test_bad_actions_are_skipped_not_fatal():
    out = chat.apply_actions(proj(), [
        {"do": "set_clip", "target": 9, "set": {"speed": 2}},           # no such clip
        {"do": "set_clip", "target": 1, "set": {"preset": "nonsense"}},  # unknown look
        {"do": "set_clip", "target": 1, "set": {"evil": 1}},
        {"do": "format_disk"},
        {"do": "add_text", "text": "  "},
        {"do": "set_clip", "target": 1, "set": {"speed": 99}},           # clamped, not rejected
    ], NAMES)
    assert len(out["skipped"]) == 5
    assert out["project"].clips[0].speed == 4
    assert out["project"].clips[1].preset == "none"


def test_targets_by_name_and_number():
    out = chat.apply_actions(proj(), [{"do": "set_clip", "target": "city", "set": {"muted": True}}, {"do": "move_clip", "target": 2, "to": 1}], NAMES)
    assert [c.id for c in out["project"].clips] == ["c1", "c0"]
    assert out["project"].clips[0].muted and not out["project"].clips[1].muted


def test_system_prompt_lists_real_options():
    s = chat.system_prompt("Video: x", ["a.mp4"], True)
    for word in ("wipeleft" if "wipeleft" in chat.TRANSITIONS else "fade", "neon", "generate_video", "you can see them"):
        assert word in s


@pytest.fixture()
def client(data_dir, monkeypatch, tmp_path):
    monkeypatch.setenv("LTXPS_ENGINE", "fake")
    monkeypatch.setenv("LTXPS_FAKE_VRAM_MB", "4096")
    state = build_state(TOKEN)
    fake = Fake()
    a = build_assistant_state(tmp_path / "assistant", TOKEN)
    a.settings.update({"provider": "custom", "providers": {"custom": {"base_url": fake.url + "/v1", "model": "m-one", "api_key": ""}}})
    with TestClient(create_app(state, None, a), headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        c.fake = fake
        yield c
    fake.close()


@needs_ffmpeg
def test_chat_endpoint_edits_project_and_sends_picture(client, media):
    v = upload(client, media["av"])
    img = upload(client, media["image"])
    p = {"clips": [{"id": "c1", "asset_id": v["id"]}]}
    client.fake.reply = json.dumps({"reply": "Made it vertical.", "actions": [{"do": "set_canvas", "ratio": "9:16"}, {"do": "task", "name": "generate_video", "prompt": "a red car", "use_reference": True}]})
    st = client.get("/api/editor/chat/status").json()
    assert st["ready"] is True
    r = client.post("/api/editor/chat", json={"messages": [{"role": "user", "content": "make it vertical", "image_ids": [img["id"]]}], "project": p})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["reply"] == "Made it vertical." and j["changed"] is True
    assert j["project"]["canvas"]["height"] == 1280
    assert j["tasks"][0]["name"] == "generate_video" and j["tasks"][0]["use_reference"] is True
    sent = client.fake.requests[-1][2]
    user = sent["messages"][-1]["content"]
    assert any(part.get("type") == "image_url" for part in user)   # the reference picture reached the model
    assert "Clip 1" in sent["messages"][0]["content"]               # and so did the project summary


@needs_ffmpeg
def test_chat_reports_model_errors(client):
    client.fake.fail = 401
    r = client.post("/api/editor/chat", json={"messages": [{"role": "user", "content": "hi"}], "project": {}})
    assert r.status_code == 502 and r.json()
