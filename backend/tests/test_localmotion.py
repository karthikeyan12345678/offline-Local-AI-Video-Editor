from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from ltxps.editor import localmotion


def _pose(dx=0.0, dy=0.0):
    # 13 normalised points of a standing figure; the arms move with dx/dy
    base = [(0.5, 0.15), (0.42, 0.28), (0.58, 0.28), (0.38, 0.42), (0.62, 0.42), (0.36, 0.55), (0.64, 0.55),
            (0.45, 0.55), (0.55, 0.55), (0.45, 0.75), (0.55, 0.75), (0.45, 0.95), (0.55, 0.95)]
    out = []
    for i, (x, y) in enumerate(base):
        arm = i in (5, 6)
        out.append((x + (dx if arm else 0), y + (dy if arm else 0)))
    return out


def _video(path, frames=12):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 12, (64, 64))
    for i in range(frames):
        vw.write(np.full((64, 64, 3), i * 10, np.uint8))
    vw.release()


def _image(path):
    img = np.zeros((96, 64, 3), np.uint8)
    img[:, :, 1] = 120
    cv2.rectangle(img, (28, 20), (36, 70), (255, 255, 255), -1)
    cv2.imwrite(str(path), img)


def test_arm_turns_instead_of_stretching():
    base = np.array([(x * 100, y * 200) for x, y in _pose()], np.float32)
    cur = base.copy()
    # in the video the right forearm (elbow 4 -> wrist 6) swings 90 degrees
    v = cur[6] - cur[4]
    cur[6] = cur[4] + np.array([-v[1], v[0]], np.float32)
    out = localmotion.pose_to(base, base, cur, 1.0)
    assert np.allclose(np.linalg.norm(out[6] - out[4]), np.linalg.norm(base[6] - base[4]), atol=0.5)  # same length
    assert np.allclose(out[6], cur[6], atol=0.5)  # and now points where the real forearm points
    assert np.allclose(out[4], base[4], atol=0.5)  # the elbow did not move
    still = localmotion.pose_to(base, base, base, 1.0)
    assert np.allclose(still, base, atol=1e-3)


def test_render_moves_the_person_but_not_the_background():
    h, w = 200, 100
    img = np.full((h, w, 3), (40, 120, 40), np.uint8)
    img[:, :60] = (200, 160, 60)  # a different background on the left, away from the body
    base = np.array([(x * w, y * h) for x, y in _pose()], np.float32)
    mask = np.zeros((h, w), np.float32)
    cv2.line(mask, tuple(int(v) for v in base[2]), tuple(int(v) for v in base[6]), 1.0, 7)  # the right arm only
    img2 = img.copy()
    img2[mask > 0] = (255, 255, 255)
    plate = localmotion._plate(img2, mask)
    cur = base.copy()
    v = cur[6] - cur[4]
    cur[6] = cur[4] + np.array([-v[1], v[0]], np.float32)
    dst = localmotion.pose_to(base, base, cur, 1.0)
    out = localmotion.render(img2, mask, plate, base, dst)
    assert out.shape == img2.shape
    assert not np.array_equal(out, localmotion.render(img2, mask, plate, base, base))  # the arm moved
    assert np.array_equal(out[:20, :20], img2[:20, :20])  # a corner far from the body is untouched


def test_run_makes_a_video_from_fake_poses(tmp_path):
    img, vid, dest = tmp_path / "c.png", tmp_path / "m.mp4", tmp_path / "out.mp4"
    _image(img)
    _video(vid)
    calls = {"n": 0}

    def detect(rgb):
        calls["n"] += 1
        return _pose(dx=0.01 * calls["n"], dy=-0.005 * calls["n"])

    seen = []
    r = localmotion.run(img, vid, dest, detect, on_progress=lambda p, m: seen.append(p))
    assert dest.exists() and dest.stat().st_size > 0 and r["frames"] >= 6
    cap = cv2.VideoCapture(str(dest))
    ok, frame = cap.read()
    assert ok and frame.shape[0] % 2 == 0 and seen[-1] == 1.0


def test_no_person_in_picture_or_video_is_explained(tmp_path):
    img, vid = tmp_path / "c.png", tmp_path / "m.mp4"
    _image(img)
    _video(vid)
    with pytest.raises(localmotion.LocalMotionError, match="character picture"):
        localmotion.run(img, vid, tmp_path / "o.mp4", lambda rgb: None)
    n = {"i": 0}

    def only_picture(rgb):
        n["i"] += 1
        return _pose() if n["i"] == 1 else None

    with pytest.raises(localmotion.LocalMotionError, match="motion video"):
        localmotion.run(img, vid, tmp_path / "o.mp4", only_picture)


def test_model_download_failure_gives_plain_steps(tmp_path):
    def boom(url, target):
        raise OSError("offline")

    with pytest.raises(localmotion.LocalMotionError, match="download"):
        localmotion.ensure_model(tmp_path / "pose", boom)

    def ok(url, target):
        target.write_bytes(b"x" * 200_000)

    assert localmotion.ensure_model(tmp_path / "pose", ok).exists()
    assert localmotion.ensure_model(tmp_path / "pose", boom).exists()  # already there: no download


class FakeInterpreter:
    """Stands in for TensorFlow Lite: returns MoveNet's (y, x, score) rows for a person standing in the left half of a 100x50 picture."""

    def __init__(self, score=0.9):
        self.score, self.fed = score, None

    def allocate_tensors(self): ...
    def get_input_details(self): return [{"index": 0, "shape": [1, 192, 192, 3], "dtype": np.uint8}]
    def get_output_details(self): return [{"index": 1}]
    def set_tensor(self, i, v): self.fed = v
    def invoke(self): ...

    def get_tensor(self, i):
        kp = np.zeros((1, 1, 17, 3), np.float32)
        kp[0, 0, :, 0], kp[0, 0, :, 1], kp[0, 0, :, 2] = 0.25, 0.25, self.score  # y, x in the padded 100x100 square
        return kp


def test_movenet_points_are_mapped_back_to_the_picture():
    it = FakeInterpreter()
    detect = localmotion.tensorflow_detector(Path("unused"), interpreter=it)
    pts = detect(np.zeros((50, 100, 3), np.uint8))  # wide picture: the square padding is 100x100
    assert len(pts) == 13 and it.fed.shape == (1, 192, 192, 3) and it.fed.dtype == np.uint8
    assert abs(pts[0][0] - 0.25) < 1e-6 and abs(pts[0][1] - 0.5) < 1e-6  # y 0.25 of 100 px = 25 px = 0.5 of the 50 px height
    assert localmotion.tensorflow_detector(Path("unused"), interpreter=FakeInterpreter(0.05))(np.zeros((50, 100, 3), np.uint8)) is None


def test_movenet_download_failure_gives_plain_steps(tmp_path):
    def boom(url, target):
        raise OSError("offline")

    with pytest.raises(localmotion.LocalMotionError, match="MoveNet"):
        localmotion.ensure_movenet(tmp_path / "pose", boom)
