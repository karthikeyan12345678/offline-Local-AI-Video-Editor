import json
from pathlib import Path

import httpx
import pytest

from ltxps.editor import motion


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _files(tmp_path):
    img, vid = tmp_path / "c.png", tmp_path / "m.mp4"
    img.write_bytes(b"\x89PNG fake")
    vid.write_bytes(b"fake video")
    return img, vid


def test_happy_path_polls_then_downloads(tmp_path):
    img, vid = _files(tmp_path)
    seen = {}
    states = iter(["IN_QUEUE", "IN_PROGRESS", "COMPLETED"])

    def h(req: httpx.Request):
        u = str(req.url)
        if req.method == "POST":
            seen["url"], seen["auth"], seen["body"] = u, req.headers["authorization"], json.loads(req.content)
            return httpx.Response(200, json={"request_id": "r1", "status_url": "https://queue.fal.run/s", "response_url": "https://queue.fal.run/r", "cancel_url": "https://queue.fal.run/c"})
        if u.endswith("/s"):
            return httpx.Response(200, json={"status": next(states)})
        if u.endswith("/r"):
            return httpx.Response(200, json={"video": {"url": "https://cdn.fal/out.mp4"}})
        return httpx.Response(200, content=b"MP4DATA")

    out = tmp_path / "o.mp4"
    prog = []
    r = motion.run("KEY", img, vid, out, orientation="image", mode="pro", prompt="dance", video_seconds=8, client=_client(h), poll=0, on_progress=lambda p, m: prog.append(m))
    assert out.read_bytes() == b"MP4DATA" and r["mode"] == "pro"
    assert seen["url"].endswith("/pro/motion-control") and seen["auth"] == "Key KEY"
    assert seen["body"]["character_orientation"] == "image" and seen["body"]["image_url"].startswith("data:image/png;base64,") and seen["body"]["video_url"].startswith("data:video/mp4")
    assert any("line" in m or "animating" in m for m in prog)


def test_bad_key_and_limits_are_explained(tmp_path):
    img, vid = _files(tmp_path)
    with pytest.raises(motion.MotionError, match="key"):
        motion.run("", img, vid, tmp_path / "o.mp4")
    with pytest.raises(motion.MotionError, match="10 s"):
        motion.run("K", img, vid, tmp_path / "o.mp4", orientation="image", video_seconds=20)
    with pytest.raises(motion.MotionError, match="3 seconds"):
        motion.run("K", img, vid, tmp_path / "o.mp4", video_seconds=1)
    with pytest.raises(motion.MotionError, match="did not accept"):
        motion.run("K", img, vid, tmp_path / "o.mp4", client=_client(lambda r: httpx.Response(401, json={"detail": "bad"})))


def test_failed_job(tmp_path):
    img, vid = _files(tmp_path)

    def h(req):
        if req.method == "POST":
            return httpx.Response(200, json={"request_id": "r", "status_url": "https://q/s", "response_url": "https://q/r"})
        return httpx.Response(200, json={"status": "FAILED", "error": "no person found"})

    with pytest.raises(motion.MotionError, match="no person found"):
        motion.run("K", img, vid, tmp_path / "o.mp4", client=_client(h), poll=0)


def test_key_is_stored_masked(tmp_path):
    s = motion.MotionSettings(tmp_path / "m.json")
    assert s.public()["has_key"] is False
    s.update("abcd1234efgh", "pro")
    p = s.public()
    assert p["has_key"] and p["key_hint"].endswith("efgh") and "abcd" not in p["key_hint"] and p["mode"] == "pro"
    s.update(p["key_hint"], None)  # an untouched masked box keeps the key
    assert s.get()["fal_key"] == "abcd1234efgh"
