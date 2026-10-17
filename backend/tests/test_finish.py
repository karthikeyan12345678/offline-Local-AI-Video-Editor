from pathlib import Path

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


def test_ai_upscale_pipeline_with_a_stand_in_tool(media, tmp_path):
    from PIL import Image

    clip = tmp_path / "c.mp4"
    clip.write_bytes(media["av"].read_bytes())
    before = probe(clip)
    exe = tmp_path / "tools" / "realesrgan" / "realesrgan-ncnn-vulkan.exe"

    def fake_runner(cmd, cwd, timeout, progress, cancel):  # plays the part of Real-ESRGAN: 4x every frame
        src, dst = cmd[cmd.index("-i") + 1], cmd[cmd.index("-o") + 1]
        assert "-n" in cmd and cmd[cmd.index("-n") + 1] == finish.ESRGAN_MODEL
        for f in sorted(Path(src).glob("*.png")):
            im = Image.open(f)
            im.resize((im.width * 4, im.height * 4)).save(Path(dst) / f.name)
        return 0

    seen = []
    r = finish.ai_upscale(clip, ffmpeg_path(), tmp_path / "tools", ensure=lambda t: exe, runner=fake_runner, on_status=seen.append)
    after = probe(clip)
    assert r["sharpened"] and r["method"] == "ai" and after.width == before.width * 2 and after.has_audio and abs(after.duration - before.duration) < 0.3


def test_ai_upscale_falls_back_without_touching_the_video(media, tmp_path):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(media["av"].read_bytes())
    original = clip.read_bytes()
    assert finish.ai_upscale(clip, ffmpeg_path(), tmp_path / "t", ensure=lambda t: None)["sharpened"] is False
    exe = tmp_path / "e.exe"
    r = finish.ai_upscale(clip, ffmpeg_path(), tmp_path / "t", ensure=lambda t: exe, runner=lambda *a: 1)
    assert r["sharpened"] is False and "graphics card" in r["reason"] and (tmp_path / "t" / "realesrgan.failed").exists()
    assert clip.read_bytes() == original


def test_downloaded_upscaler_is_unpacked_safely(tmp_path):
    import zipfile

    def fake_download(url, target):
        with zipfile.ZipFile(target, "w") as z:
            z.writestr("realesrgan-ncnn-vulkan.exe", b"x")
            z.writestr("models/realesrgan-x4plus.bin", b"y")
            z.writestr("../evil.txt", b"no")
            z.writestr("input.jpg", b"demo")

    exe = finish.ensure_esrgan(tmp_path / "tools", fake_download)
    assert exe and exe.exists() and (exe.parent / "models" / "realesrgan-x4plus.bin").exists()
    assert not (tmp_path / "evil.txt").exists() and not (exe.parent / "input.jpg").exists()
    assert finish.ensure_esrgan(tmp_path / "tools", lambda u, t: 1 / 0) == exe  # already installed: no download


def test_reference_audio_is_added_to_a_silent_result(media, tmp_path):
    silent, ref = tmp_path / "s.mp4", media["av"]
    silent.write_bytes(media["silent"].read_bytes())
    assert probe(silent).has_audio is False
    r = finish.attach_reference_audio(silent, ref, ffmpeg_path())
    assert r["audio"] is True and probe(silent).has_audio
    assert finish.attach_reference_audio(silent, media["silent"], ffmpeg_path())["reason"] == "already has sound"
    other = tmp_path / "o.mp4"
    other.write_bytes(media["silent"].read_bytes())
    assert finish.attach_reference_audio(other, media["silent"], ffmpeg_path())["audio"] is False  # the reference has no sound either
