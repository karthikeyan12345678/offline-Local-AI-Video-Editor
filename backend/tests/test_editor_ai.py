"""AI helpers and their endpoints, run on synthetic media."""

import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from conftest import FFMPEG, needs_ffmpeg
from ltxps.editor import ai
from test_api import client, upload, wait  # noqa: F401  (fixtures)

pytestmark = needs_ffmpeg
YUNET = ai.YUNET


def clicks(path: Path, bpm=120, seconds=12, gap=(5, 8)) -> Path:
    sr = 22050
    y = np.zeros(sr * seconds, np.float32)
    for b in np.arange(0.2, seconds, 60 / bpm):
        i = int(b * sr)
        y[i:i + 400] = np.random.default_rng(1).standard_normal(400) * 0.8 * np.hanning(400)
    if gap:
        y[int(gap[0] * sr):int(gap[1] * sr)] = 0
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(sr)
        w.writeframes((y * 32000).astype(np.int16).tobytes())
    return path


def test_beats_tempo_and_grid(tmp_path):
    r = ai.beat_times(str(clicks(tmp_path / "c.wav", gap=None)))
    assert r["bpm"] == pytest.approx(120, abs=3)
    gaps = np.diff(r["beats"])
    assert np.median(gaps) == pytest.approx(0.5, abs=0.03)


def test_silence_cuts_remove_the_gap(tmp_path):
    r = ai.silence_cuts(str(clicks(tmp_path / "c.wav")), 12, -40, 0.6)
    assert len(r["keep"]) == 2 and r["removed"] > 2.5
    assert r["keep"][0][1] < 5.2 and r["keep"][1][0] > 7.8


def test_scene_cuts_find_the_change(tmp_path):
    out = tmp_path / "s.mp4"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=red:s=160x90:d=2:r=12", "-f", "lavfi", "-i", "color=blue:s=160x90:d=2:r=12",
                    "-filter_complex", "[0][1]concat=n=2:v=1:a=0", "-pix_fmt", "yuv420p", str(out)], check=True)
    assert ai.scene_cuts(str(out), 4)["cuts"] == [pytest.approx(2.0, abs=0.2)]


def test_auto_enhance_brightens_a_dark_frame(tmp_path):
    out = tmp_path / "d.mp4"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:d=1:r=12,eq=brightness=-0.35", "-pix_fmt", "yuv420p", str(out)], check=True)
    r = ai.auto_enhance(str(out), 0.5, 1)
    assert r["brightness"] > 0 or r["gamma"] > 1


def test_srt_format():
    assert ai.to_srt([{"start": 0.5, "end": 2.25, "text": "Hi"}]).startswith("1\n00:00:00,500 --> 00:00:02,250\nHi")


def test_follow_person_tracks_a_moving_face(tmp_path):
    astro = Path(__file__).parent / "data" / "face.png"
    if not astro.exists() or not YUNET.exists():
        pytest.skip("face sample not available")
    from PIL import Image

    face = Image.open(astro).convert("RGB")
    frames = tmp_path / "f"
    frames.mkdir()
    for i in range(30):
        bg = Image.new("RGB", (768, 256), (40, 60, 90))
        bg.paste(face.resize((256, 256)), (40 + i * 16, 0))
        bg.save(frames / f"f{i:03d}.png")
    mp4 = tmp_path / "m.mp4"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-framerate", "10", "-i", str(frames / "f%03d.png"), "-pix_fmt", "yuv420p", str(mp4)], check=True)
    r = ai.follow_person(str(mp4), 0, 3)
    assert r["found"] > 0.8
    assert r["keys"][-1][1] - r["keys"][0][1] > 0.3  # the camera path moves right with the face


def test_follow_without_any_person_still_returns_a_path(media):
    r = ai.follow_person(str(media["av"]), 0, 2)
    assert r["keys"] and all(0 <= k[1] <= 1 and 0 <= k[2] <= 1 for k in r["keys"])


def test_endpoints(client, media, tmp_path):
    cat = client.get("/api/editor/catalog").json()
    assert len(cat["transitions"]) >= 55 and len(cat["fonts"]) >= 60 and cat["audio_fx"] and cat["effects"]
    r = client.get("/api/editor/fonts/sample", params={"font": "anton", "text": "வணக்கம்"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert client.get("/api/editor/fonts/anton/file").status_code == 200
    assert client.get("/api/editor/fonts/nope/file").status_code == 404

    audio = upload(client, clicks(tmp_path / "c.wav"))
    j = wait(client, client.post("/api/editor/ai/beats", json={"asset_id": audio["id"]}).json())
    assert j["status"] == "done" and j["result"]["bpm"] > 60
    j = wait(client, client.post("/api/editor/ai/silence", json={"asset_id": audio["id"], "options": {"noise_db": -40}}).json())
    assert j["status"] == "done" and len(j["result"]["keep"]) == 2

    vid = upload(client, media["av"])
    j = wait(client, client.post("/api/editor/ai/follow", json={"asset_id": vid["id"]}).json())
    assert j["status"] == "done" and j["result"]["keys"]
    assert client.post("/api/editor/ai/enhance", json={"asset_id": vid["id"]}).status_code == 200
    # captions need the model first
    assert client.post("/api/editor/ai/captions", json={"asset_id": vid["id"], "options": {"model": "base"}}).status_code == 409
    assert client.post("/api/editor/ai/follow", json={"asset_id": audio["id"]}).status_code == 422
    models = client.get("/api/models").json()["items"]
    assert {"whisper-tiny", "whisper-base", "whisper-small"} <= {m["id"] for m in models}


def test_importing_the_api_works_without_numpy():
    """The separate AI Assistant app has no numpy; importing the server must not need it."""
    code = "import sys; sys.modules['numpy']=None; sys.modules['cv2']=None; import ltxps.app; from ltxps.editor import ai; print('ok')"
    r = subprocess.run([__import__('sys').executable, "-c", code], capture_output=True, text=True, cwd=Path(__file__).parents[1])
    assert r.stdout.strip() == "ok", r.stderr
