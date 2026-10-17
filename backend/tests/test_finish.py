from ltxps import finish
from ltxps.editor.media import probe
from ltxps.system import ffmpeg_path


def test_target_size_is_even_and_capped():
    assert finish.target_size(512, 320) == (1024, 640)
    w, h = finish.target_size(1280, 704)
    assert max(w, h) <= 1920 and w % 2 == 0 and h % 2 == 0
    assert finish.target_size(1920, 1080) == (1920, 1080)  # already large: not enlarged


def test_sharpen_enlarges_the_clip_and_keeps_sound(media, tmp_path):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(media["av"].read_bytes())
    before = probe(clip)
    r = finish.sharpen(clip, ffmpeg_path())
    after = probe(clip)
    assert r["sharpened"] and after.width == before.width * 2 and after.has_audio and abs(after.duration - before.duration) < 0.3


def test_sharpen_never_raises(tmp_path):
    bad = tmp_path / "x.mp4"
    bad.write_bytes(b"not a video")
    assert finish.sharpen(bad, ffmpeg_path())["sharpened"] is False
    assert bad.read_bytes() == b"not a video"
    assert finish.sharpen(bad, None)["sharpened"] is False
