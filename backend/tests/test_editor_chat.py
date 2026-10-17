"""The chat editor: reading the model's answer, applying actions safely, and the endpoint with a fake model."""

import json

import pytest
from fastapi.testclient import TestClient

from conftest import needs_ffmpeg
from fakeserver import Fake
from ltxps.app import create_app
from ltxps.assistant.service import build_assistant_state
from ltxps.editor import chat
from ltxps.editor.chat import apply_actions, parse_answer
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
    for word in ("wipeleft" if "wipeleft" in chat.TRANSITIONS else "fade", "neon", "generate_video", "You can see them"):
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


# ---------------------------------------------------------------- picture overlays (1.2.1)
def _img_ctx(face=None):
    from types import SimpleNamespace as NS
    assets = {"cap": NS(id="cap", kind="image", name="cap.png", path="/x/cap.png", duration=0, width=400, height=200),
              "v1": NS(id="v1", kind="video", name="a.mp4", path="/x/a.mp4", duration=10.0, width=1280, height=720)}
    return {"attached": ["cap"], "assets": assets, "face": face}


def _proj_one_clip():
    from ltxps.editor.project import Project
    return Project.model_validate({"clips": [{"id": "c1", "asset_id": "v1"}]})


def test_add_image_on_head_uses_the_face():
    names = {"cap": "cap.png", "v1": "a.mp4"}
    ctx = _img_ctx(face=lambda path, t: {"x": 0.4, "y": 0.3, "w": 0.2, "h": 0.3})
    out = apply_actions(_proj_one_clip(), [{"do": "add_image", "image": "attached", "anchor": "head"}], names, ctx)
    assert not out["skipped"], out["skipped"]
    im = out["project"].images[0]
    assert im.asset_id == "cap" and abs(im.x - 0.5) < 1e-6 and im.size > 0.2
    assert im.y < 0.3  # above the face top
    assert "head" in out["applied"][0]
    assert out["focus"] is not None


def test_add_image_without_face_still_places_and_says_so():
    out = apply_actions(_proj_one_clip(), [{"do": "add_image", "image": "attached", "anchor": "head", "x": 0.5, "y": 0.2, "size": 0.2}], {"cap": "cap.png", "v1": "a.mp4"}, _img_ctx(face=lambda p, t: None))
    assert out["project"].images and "could not find a face" in out["applied"][0]


def test_add_image_needs_an_attached_picture():
    out = apply_actions(_proj_one_clip(), [{"do": "add_image", "image": "attached"}], {"v1": "a.mp4"}, {"attached": [], "assets": {}})
    assert not out["project"].images and "attach" in out["skipped"][0]


def test_action_without_do_is_skipped_politely():
    out = apply_actions(_proj_one_clip(), [{"target": "head"}, {"do": "draw", "shapes": [{"type": "arrow", "points": [[0.1, 0.1], [0.4, 0.4]]}]}], {"v1": "a.mp4"})
    assert len(out["project"].drawings) == 1 and len(out["skipped"]) == 1 and "without a clear action" in out["skipped"][0]


def test_parse_flags_unreadable_answers():
    assert parse_answer("sure, here you go")["ok"] is False
    assert parse_answer('{"reply":"ok","actions":{"do":"set_canvas","ratio":"1:1"}}')["actions"] == [{"do": "set_canvas", "ratio": "1:1"}]


@needs_ffmpeg
def test_chat_endpoint_puts_attached_picture_on_the_video_and_retries_bad_answers(client, media):
    v = upload(client, media["av"])
    img = upload(client, media["image"])
    p = {"clips": [{"id": "c1", "asset_id": v["id"]}]}
    client.fake.reply = json.dumps({"reply": "Cap added.", "actions": [{"do": "add_image", "image": "attached", "x": 0.5, "y": 0.2, "size": 0.2, "start": 0, "duration": 2}]})
    r = client.post("/api/editor/chat", json={"messages": [{"role": "user", "content": "put this cap on his head", "image_ids": [img["id"]]}], "project": p}).json()
    assert r["changed"] is True and r["project"]["images"][0]["asset_id"] == img["id"] and r["focus"] == 0
    assert r["understood"] is True
    # an answer that is not JSON is asked for again once
    n = len(client.fake.requests)
    client.fake.reply = "sure! I would add a cap"
    r2 = client.post("/api/editor/chat", json={"messages": [{"role": "user", "content": "add a cap"}], "project": p}).json()
    assert r2["changed"] is False and r2["understood"] is False and len(client.fake.requests) - n == 2


@pytest.mark.parametrize("word,size", [("youtube", (1920, 1080)), ("Shorts", (1080, 1920)), ("instagram reels", (1080, 1920)), ("Instagram-Feed", (1080, 1350)), ("tiktok", (1080, 1920))])
def test_set_canvas_platform_presets(word, size):
    out = chat.apply_actions(proj(), [{"do": "set_canvas", "preset": word}], NAMES)
    c = out["project"].canvas
    assert (c.width, c.height) == size and c.fps == 30


def test_set_canvas_unknown_preset_is_reported_not_crashing():
    out = chat.apply_actions(proj(), [{"do": "set_canvas", "preset": "myspace"}], NAMES)
    assert out["project"].canvas.width == 1280


def test_soundtrack_and_sound_on_new_video_tasks():
    out = chat.apply_actions(proj(), [
        {"do": "task", "name": "soundtrack", "target": "first", "narration": "Welcome", "ambience": "rain", "music": True},
        {"do": "task", "name": "generate_video", "prompt": "a calm sea", "narration": "Hello sea", "ambience": "bogus"},
        {"do": "task", "name": "soundtrack", "target": "all", "ambience": "none"},
    ], NAMES)
    t = out["tasks"]
    assert t[0]["name"] == "soundtrack" and t[0]["ambience"] == "rain" and t[0]["music"] and len(t[0]["clips"]) == 1
    assert t[1]["name"] == "generate_video" and t[1]["narration"] == "Hello sea" and t[1]["ambience"] == "auto"
    assert len(t) == 2  # the empty soundtrack request was refused


# ---------------------------------------------------------------- layers, green screen, keyframes
class _A:
    def __init__(self, kind="video", duration=6.0):
        self.kind, self.duration, self.width, self.height = kind, duration, 640, 360


def _ctx():
    return {"assets": {"a0": _A(), "a1": _A(), "a2": _A("video", 8.0), "a3": _A("image", 0)}}


NAMES2 = {"a0": "beach.mp4", "a1": "city.mp4", "a2": "actor_greenscreen.mp4", "a3": "logo.png"}


def test_add_layer_remove_green_and_put_a_background_behind():
    out = chat.apply_actions(proj(), [
        {"do": "remove_background", "on": "clip", "target": 1, "color": "green"},
        {"do": "add_layer", "video": "beach", "behind": True},
        {"do": "add_layer", "video": "logo", "x": 0.9, "y": 0.1, "size": 0.15, "start": 1, "duration": 3},
        {"do": "add_layer", "video": "greenscreen", "remove_color": "green", "track": 2},
    ], NAMES2, _ctx())
    p = out["project"]
    assert not out["skipped"], out["skipped"]
    assert p.clips[0].chroma.enabled and not p.clips[1].chroma.enabled
    bg, logo, actor = p.layers
    assert bg.behind and bg.size == 1.0 and (bg.x, bg.y) == (0.5, 0.5)
    assert logo.image_duration == 3 and logo.start == 1 and logo.size == 0.15
    assert actor.chroma.enabled and actor.track == 2 and actor.size == 1.0


def test_set_and_delete_layer_are_checked():
    base = chat.apply_actions(proj(), [{"do": "add_layer", "video": "city"}], NAMES2, _ctx())["project"]
    out = chat.apply_actions(base, [{"do": "set_layer", "target": 1, "set": {"opacity": 0.4, "x": 0.2, "adjust": {"brightness": 10}}},
                                    {"do": "set_layer", "target": 5, "set": {"x": 1}}, {"do": "set_layer", "target": 1, "set": {"evil": 1}}], NAMES2, _ctx())
    assert out["project"].layers[0].opacity == 0.4 and out["project"].layers[0].adjust.brightness == 10
    assert len(out["skipped"]) == 2
    gone = chat.apply_actions(out["project"], [{"do": "delete_layer", "target": "all"}], NAMES2, _ctx())["project"]
    assert gone.layers == []


def test_keyframes_by_chat_start_from_the_current_look():
    base = chat.apply_actions(proj(), [{"do": "add_layer", "video": "city", "x": 0.2, "y": 0.5, "size": 0.3, "start": 2}], NAMES2, _ctx())["project"]
    out = chat.apply_actions(base, [{"do": "keyframe", "on": "layer", "target": 1, "at": 2, "ease": "linear"}, {"do": "keyframe", "on": "layer", "target": 1, "at": 5, "x": 0.8, "opacity": 0.5}], NAMES2, _ctx())["project"]
    k = out.layers[0].keys
    assert [round(q.t, 2) for q in k] == [0, 3] and k[0].x == 0.2 and k[1].x == 0.8 and k[1].size == 0.3 and k[1].opacity == 0.5 and k[0].ease == "linear"
    again = chat.apply_actions(out, [{"do": "keyframe", "on": "layer", "target": 1, "at": 5, "x": 0.9}], NAMES2, _ctx())["project"]
    assert len(again.layers[0].keys) == 2 and again.layers[0].keys[1].x == 0.9  # same moment = replaced, not doubled
    assert chat.apply_actions(again, [{"do": "clear_keyframes", "on": "layer", "target": 1}], NAMES2, _ctx())["project"].layers[0].keys == []


def test_move_along_makes_text_fly_across():
    base = chat.apply_actions(proj(), [{"do": "add_text", "text": "Hi", "start": 1, "duration": 4}], NAMES2, _ctx())["project"]
    out = chat.apply_actions(base, [{"do": "move_along", "on": "text", "target": 1, "from": [0.1, 0.5], "to": [0.9, 0.5]}], NAMES2, _ctx())
    k = out["project"].texts[0].keys
    assert not out["skipped"] and len(k) == 2 and k[0].x == 0.1 and k[1].x == 0.9 and k[1].t == 4


def test_prompt_and_summary_know_layers():
    base = chat.apply_actions(proj(), [{"do": "add_layer", "video": "beach", "behind": True}], NAMES2, _ctx())["project"]
    assert "Layer 1" in chat.describe(base, NAMES2, {"a0": 6.0}) and "behind" in chat.describe(base, NAMES2, {})
    sp = chat.system_prompt("x", [], False)
    for word in ("add_layer", "remove_background", "keyframe", "move_along"):
        assert word in sp
    assert chat.looks_like_edit_request("remove the green screen")


# ---------------------------------------------------------------- 1.2.14 pack: sounds, masks, layer effects
class _Snd:
    def __init__(self, i, n):
        self.id, self.name = i, n


def _with_sound():
    made = []

    def make(sid):
        made.append(sid)
        return _Snd("snd_" + sid, sid.replace("_", " ").title())

    ctx = _ctx()
    ctx["sound"] = make
    return ctx, made


def test_add_sound_finds_the_sound_from_everyday_words():
    ctx, made = _with_sound()
    out = chat.apply_actions(proj(), [{"do": "add_sound", "sound": "a whoosh", "start": 3}, {"do": "add_sound", "sound": "rain"}, {"do": "add_sound", "sound": "xyzzy"}], NAMES2, ctx)
    a = out["project"].audio
    assert made == ["whoosh", "rain"] and len(out["skipped"]) == 1
    assert a[0].start == 3 and not a[0].loop and a[0].volume == 1
    assert a[1].loop and a[1].is_music and a[1].volume == 0.5  # ambience repeats under the video, quietly


def test_set_layer_takes_a_mask_and_one_effect():
    base = chat.apply_actions(proj(), [{"do": "add_layer", "video": "city"}], NAMES2, _ctx())["project"]
    out = chat.apply_actions(base, [{"do": "set_layer", "target": 1, "set": {"mask": "heart", "mask_feather": 0.3, "effect": "glitch", "effect_amount": 0.8}},
                                    {"do": "set_layer", "target": 1, "set": {"mask": "dragon"}}, {"do": "set_layer", "target": 1, "set": {"effect": "nope"}}], NAMES2, _ctx())
    ly = out["project"].layers[0]
    assert ly.mask == "heart" and ly.mask_feather == 0.3 and ly.effects[0].type == "glitch" and ly.effects[0].amount == 0.8
    assert len(out["skipped"]) == 2
    off = chat.apply_actions(out["project"], [{"do": "set_layer", "target": 1, "set": {"mask": "off"}}], NAMES2, _ctx())["project"]
    assert off.layers[0].mask == "none"


def test_prompt_lists_the_new_catalog():
    sp = chat.system_prompt("x", [], False)
    for word in ("add_sound", "whoosh", "blockbuster", "kaleido", "heart", "typewriter", "helium"):
        assert word in sp
    assert chat.looks_like_edit_request("add a whoosh sound at 3 seconds")
