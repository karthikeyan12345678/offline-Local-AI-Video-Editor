"""Sound and voice for generated videos: ambience choice, synthesis, mixing and the API."""

import subprocess

from ltxps.editor.ai import np
import pytest
from fastapi.testclient import TestClient

from conftest import needs_ffmpeg
from ltxps.app import create_app
from ltxps.editor import soundtrack
from ltxps.editor.media import probe
from ltxps.state import build_state
from ltxps.system import ffmpeg_path
from test_api import TOKEN, wait

pytestmark = needs_ffmpeg


def silent_video(path, seconds=2.0):
    subprocess.run([ffmpeg_path(), "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=blue:s=128x72:d={seconds}:r=12", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


@pytest.mark.parametrize("prompt,expected", [
    ("A lighthouse on a cliff at dawn, waves rolling in", "waves"), ("heavy rain on a window", "rain"), ("a campfire in the dark", "fire"),
    ("a busy city street at noon", "city"), ("astronaut floating in space", "space"), ("a smiling person", "calm"), ("walking through a misty forest", "wind"),
])
def test_ambience_is_chosen_from_the_prompt(prompt, expected):
    assert soundtrack.pick_ambience(prompt) == expected


@pytest.mark.parametrize("kind", soundtrack.AMBIENCES)
def test_every_ambience_is_audible_and_not_clipping(kind):
    sig = soundtrack.synth(kind, 1.5)
    assert len(sig) == int(1.5 * soundtrack.RATE) and 0.2 < np.max(np.abs(sig)) <= 0.9 + 1e-6 and np.isfinite(sig).all()


def test_build_adds_a_sound_track_and_keeps_the_picture(tmp_path):
    src = silent_video(tmp_path / "in.mp4")
    assert not probe(src).has_audio
    r = soundtrack.build(src, tmp_path / "out.mp4", prompt="ocean waves", work=tmp_path)
    out = probe(tmp_path / "out.mp4")
    assert out.has_audio and abs(out.duration - 2.0) < 0.3 and (out.width, out.height) == (128, 72)
    assert r["ambience"] == "waves" and r["voice"] is False and r["warnings"] == []


def fake_speak(seconds):
    def speak(text, dest, voice="", rate=0):
        soundtrack.write_wav(dest, soundtrack.synth("wind", seconds))
    return speak


def test_long_narration_is_sped_up_or_cut_with_a_warning(tmp_path, monkeypatch):
    src = silent_video(tmp_path / "in.mp4", 2.0)
    monkeypatch.setattr(soundtrack, "speak", fake_speak(4.0))
    r = soundtrack.build(src, tmp_path / "out.mp4", narration="a lot of words", ambience="none", work=tmp_path)
    assert r["voice"] is True and r["warnings"] and abs(probe(tmp_path / "out.mp4").duration - 2.0) < 0.3


def test_short_narration_needs_no_warning(tmp_path, monkeypatch):
    src = silent_video(tmp_path / "in.mp4", 3.0)
    monkeypatch.setattr(soundtrack, "speak", fake_speak(1.0))
    r = soundtrack.build(src, tmp_path / "out.mp4", narration="hi", ambience="rain", music=True, work=tmp_path)
    assert r["warnings"] == [] and r["voice"] and r["ambience"] == "rain" and probe(tmp_path / "out.mp4").has_audio


def test_nothing_to_add_is_a_clear_error(tmp_path):
    src = silent_video(tmp_path / "in.mp4")
    with pytest.raises(Exception, match="Choose"):
        soundtrack.build(src, tmp_path / "o.mp4", ambience="none", work=tmp_path)


@pytest.fixture()
def client(data_dir, monkeypatch):
    monkeypatch.setenv("LTXPS_ENGINE", "fake")
    monkeypatch.setenv("LTXPS_FAKE_VRAM_MB", "4096")
    monkeypatch.setattr(soundtrack, "speak", fake_speak(1.0))
    with TestClient(create_app(build_state(TOKEN)), headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        yield c


def test_generate_with_sound_returns_a_video_that_has_sound(client):
    j = client.post("/api/generate", json={"prompt": "waves on a beach", "width": 256, "height": 192, "frames": 17, "sound": {"narration": "Hello there", "ambience": "auto"}}).json()
    done = wait(client, j)
    assert done["status"] == "done", done
    a = next(x for x in client.get("/api/assets").json() if x["id"] == done["result"]["asset_id"])
    assert a["has_audio"] if "has_audio" in a else a["meta"]["sound"]["ambience"] == "waves"
    assert a["meta"]["sound"]["voice"] is True


def test_generate_without_sound_stays_silent_and_unchanged(client):
    done = wait(client, client.post("/api/generate", json={"prompt": "a dog", "width": 256, "height": 192, "frames": 17}).json())
    assert done["status"] == "done" and done["result"]["warnings"] == []


def test_soundtrack_route_makes_a_new_asset(client):
    g = wait(client, client.post("/api/generate", json={"prompt": "a quiet room", "width": 256, "height": 192, "frames": 17}).json())
    r = client.post("/api/editor/ai/soundtrack", json={"asset_id": g["result"]["asset_id"], "ambience": "rain", "music": True})
    assert r.status_code == 200, r.text
    d = wait(client, r.json())
    assert d["status"] == "done" and d["result"]["asset_id"] != g["result"]["asset_id"]
    assert client.get("/api/editor/ai/ambiences").json()["ambiences"][-1]["id"] == "none"


def test_soundtrack_route_rejects_non_video(client):
    assert client.post("/api/editor/ai/soundtrack", json={"asset_id": "nope"}).status_code == 422
