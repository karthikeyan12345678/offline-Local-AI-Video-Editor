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


def test_warp_moves_points_and_keeps_far_pixels():
    img = np.zeros((100, 100, 3), np.uint8)
    img[40:50, 60:70] = 255
    src = np.array([[65, 45]] * 13, np.float32)
    dst = src + np.array([-20, 0], np.float32)
    out = localmotion.warp(img, src, dst)
    assert out[45, 45].sum() > out[45, 65].sum()  # the white patch moved left
    assert out[2, 2].sum() == 0 and out[97, 97].sum() == 0  # corners untouched


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
