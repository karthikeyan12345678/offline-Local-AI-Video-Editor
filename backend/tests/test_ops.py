import pytest

from conftest import needs_ffmpeg
from ltxps.db import Asset
from ltxps.editor.media import probe
from ltxps.editor.ops import TOOLS, ToolError, output_ext, run_tool

pytestmark = needs_ffmpeg


def asset_for(path, kind=None) -> Asset:
    i = probe(path)
    return Asset("a1", kind or i.kind, path.stem, str(path), None, i.duration, i.width, i.height, i.fps, i.has_audio, "import", {}, 0.0)


def go(tool, media_key, media, tmp_path, **params):
    a = asset_for(media[media_key])
    dest = tmp_path / f"out.{output_ext(tool, params)}"
    run_tool(tool, a, params, dest)
    return probe(dest)


def test_interpolate_raises_frame_rate(media, tmp_path):
    info = go("interpolate", "silent", media, tmp_path, fps=60)
    assert info.fps == pytest.approx(60, abs=1)
    assert info.duration == pytest.approx(2.0, abs=0.2)


def test_upscale_doubles_dimensions(media, tmp_path):
    info = go("upscale", "silent", media, tmp_path, factor=2)
    assert (info.width, info.height) == (640, 480)


def test_upscale_refuses_results_over_4k(media, tmp_path):
    a = asset_for(media["av"])
    a.width = 3000
    with pytest.raises(ToolError, match="3840"):
        run_tool("upscale", a, {"factor": 2}, tmp_path / "x.mp4")


def test_upscale_a_still_image_produces_a_short_video(media, tmp_path):
    info = go("upscale", "image", media, tmp_path, factor=2)
    assert info.kind == "video" and info.width == 400


def test_stabilize_keeps_duration(media, tmp_path):
    assert go("stabilize", "av", media, tmp_path).duration == pytest.approx(3.0, abs=0.2)


def test_loop_repeats(media, tmp_path):
    assert go("loop", "av", media, tmp_path, times=3).duration == pytest.approx(9.0, abs=0.4)


def test_boomerang_doubles_length_and_drops_audio(media, tmp_path):
    info = go("boomerang", "silent", media, tmp_path)
    assert info.duration == pytest.approx(4.0, abs=0.2) and not info.has_audio


def test_extract_last_frame_is_a_png(media, tmp_path):
    info = go("extract_frame", "av", media, tmp_path, time="last")
    assert info.kind == "image" and (info.width, info.height) == (640, 360)


def test_extract_frame_at_time(media, tmp_path):
    assert go("extract_frame", "av", media, tmp_path, time=1.5).kind == "image"


def test_extract_audio_requires_audio(media, tmp_path):
    with pytest.raises(ToolError, match="no audio"):
        run_tool("extract_audio", asset_for(media["silent"]), {}, tmp_path / "x.mp3")


def test_extract_audio_wav(media, tmp_path):
    info = go("extract_audio", "av", media, tmp_path, format="wav")
    assert info.kind == "audio" and info.duration == pytest.approx(3.0, abs=0.2)


def test_remove_audio(media, tmp_path):
    assert not go("remove_audio", "av", media, tmp_path).has_audio


def test_to_gif(media, tmp_path):
    info = go("to_gif", "av", media, tmp_path, width=240, fps=10)
    assert info.width == 240


def test_convert_to_webm(media, tmp_path):
    assert go("convert", "av", media, tmp_path, format="webm").has_audio


def test_wrong_kind_is_rejected(media, tmp_path):
    with pytest.raises(ToolError, match="works on"):
        run_tool("stabilize", asset_for(media["audio"]), {}, tmp_path / "x.mp4")


def test_out_of_range_parameter_is_rejected(media, tmp_path):
    with pytest.raises(ToolError, match="between"):
        run_tool("loop", asset_for(media["av"]), {"times": 500}, tmp_path / "x.mp4")


def test_every_tool_has_a_spec():
    assert set(TOOLS) == {"interpolate", "upscale", "stabilize", "loop", "boomerang", "extract_frame", "extract_audio", "remove_audio", "to_gif", "convert"}
