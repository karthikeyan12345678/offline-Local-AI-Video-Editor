"""Renders real timelines through ffmpeg and checks what comes out."""

from pathlib import Path

import pytest

from conftest import needs_ffmpeg
from ltxps.editor.media import probe, run_ffmpeg
from ltxps.editor.project import Adjust, AudioClip, Canvas, Clip, ExportOptions, Project, TextOverlay, Transition
from ltxps.editor.render import AssetRef, PlanError, build_plan, clip_duration, timeline_duration

pytestmark = needs_ffmpeg


@pytest.fixture()
def assets(media) -> dict[str, AssetRef]:
    out = {}
    for key, kind in (("av", "video"), ("silent", "video"), ("audio", "audio"), ("image", "image")):
        info = probe(media[key])
        out[key] = AssetRef(media[key], info.kind, info.duration, info.has_audio, info.width, info.height)
        assert info.kind == kind
    return out


def render(project: Project, assets, tmp_path: Path, **opts):
    options = ExportOptions(**opts)
    out = tmp_path / f"out.{options.format}"
    plan = build_plan(project, assets, options, out, tmp_path / "work")
    run_ffmpeg(plan.args, plan.total)
    return plan, probe(out)


def canvas(**kw) -> Canvas:
    return Canvas(width=kw.get("width", 640), height=kw.get("height", 360), fps=kw.get("fps", 24))


def test_two_clips_with_different_size_fps_are_joined_to_canvas(assets, tmp_path):
    p = Project(canvas=canvas(), clips=[Clip(id="1", asset_id="av"), Clip(id="2", asset_id="silent")])
    plan, info = render(p, assets, tmp_path)
    assert info.width == 640 and info.height == 360
    assert info.has_audio  # silence is generated for the silent clip
    assert info.duration == pytest.approx(5.0, abs=0.15)
    assert plan.total == pytest.approx(5.0)


def test_trim_and_speed_change_duration(assets, tmp_path):
    clip = Clip(id="1", asset_id="av", trim_in=1.0, trim_out=3.0, speed=2.0)  # 2s of source at 2x = 1s
    assert clip_duration(clip, assets["av"]) == pytest.approx(1.0)
    _, info = render(Project(canvas=canvas(), clips=[clip]), assets, tmp_path)
    assert info.duration == pytest.approx(1.0, abs=0.15)


def test_slow_motion_with_audio_tempo_chain(assets, tmp_path):
    clip = Clip(id="1", asset_id="av", speed=0.25)  # needs two atempo stages
    _, info = render(Project(canvas=canvas(), clips=[clip]), assets, tmp_path)
    assert info.duration == pytest.approx(12.0, abs=0.3)
    assert info.has_audio


def test_reverse_keeps_length(assets, tmp_path):
    clip = Clip(id="1", asset_id="av", reverse=True)
    _, info = render(Project(canvas=canvas(), clips=[clip]), assets, tmp_path)
    assert info.duration == pytest.approx(3.0, abs=0.15)


def test_transition_overlaps_clips(assets, tmp_path):
    a = Clip(id="1", asset_id="av", transition=Transition(type="dissolve", duration=1.0))
    b = Clip(id="2", asset_id="silent")
    p = Project(canvas=canvas(), clips=[a, b])
    assert timeline_duration(p, assets) == pytest.approx(4.0)
    _, info = render(p, assets, tmp_path)
    assert info.duration == pytest.approx(4.0, abs=0.2)


def test_mixed_cuts_and_transitions(assets, tmp_path):
    clips = [
        Clip(id="1", asset_id="av", transition=Transition(type="wipeleft", duration=0.5)),
        Clip(id="2", asset_id="silent"),  # hard cut after this one
        Clip(id="3", asset_id="av", trim_out=1.5),
    ]
    p = Project(canvas=canvas(), clips=clips)
    _, info = render(p, assets, tmp_path)
    assert info.duration == pytest.approx(3 + 2 + 1.5 - 0.5, abs=0.25)


def test_transition_is_clamped_to_half_of_the_shorter_clip(assets):
    a = Clip(id="1", asset_id="av", transition=Transition(type="fade", duration=3.0))
    b = Clip(id="2", asset_id="silent")  # 2s
    assert timeline_duration(Project(canvas=canvas(), clips=[a, b]), assets) == pytest.approx(3 + 2 - 1.0)


def test_image_clip_uses_requested_duration(assets, tmp_path):
    p = Project(canvas=canvas(), clips=[Clip(id="1", asset_id="image", image_duration=2.5)])
    _, info = render(p, assets, tmp_path)
    assert info.duration == pytest.approx(2.5, abs=0.15)


def test_every_visual_control_produces_a_valid_render(assets, tmp_path):
    clip = Clip(
        id="1", asset_id="av", fit="fill", zoom=1.5, pan_x=0.4, pan_y=-0.4, rotate=90, flip_h=True, flip_v=True,
        adjust=Adjust(brightness=10, contrast=20, saturation=-30, gamma=1.2, hue=15),
        preset="sepia", blur=2, sharpen=1.5, vignette=True, denoise=True, fade_in=0.5, fade_out=0.5, volume=0.5,
    )
    _, info = render(Project(canvas=canvas(), clips=[clip]), assets, tmp_path)
    assert (info.width, info.height) == (640, 360)


@pytest.mark.parametrize("preset", ["bw", "sepia", "vintage", "cool", "warm", "faded", "dramatic", "negative"])
def test_each_filter_preset_renders(preset, assets, tmp_path):
    clip = Clip(id="1", asset_id="silent", trim_out=0.5, preset=preset)
    _, info = render(Project(canvas=canvas(), clips=[clip]), assets, tmp_path)
    assert info.duration > 0.3


@pytest.mark.parametrize("name", ["fade", "fadeblack", "slideleft", "circleopen", "pixelize", "radial", "wipeup"])
def test_transition_types_render(name, assets, tmp_path):
    a = Clip(id="1", asset_id="silent", transition=Transition(type=name, duration=0.5))
    b = Clip(id="2", asset_id="silent")
    _, info = render(Project(canvas=canvas(), clips=[a, b]), assets, tmp_path)
    assert info.duration == pytest.approx(3.5, abs=0.25)


def test_text_overlay_with_special_characters_and_fades(assets, tmp_path):
    t = TextOverlay(id="t", text="It's 50% off: don't miss\nsecond line", start=0.5, duration=1.5, fade_in=0.3, fade_out=0.3, bold=True)
    plan, info = render(Project(canvas=canvas(), clips=[Clip(id="1", asset_id="av")], texts=[t]), assets, tmp_path)
    assert info.duration == pytest.approx(3.0, abs=0.15)
    assert not plan.warnings


def test_audio_track_is_mixed_and_never_extends_the_video(assets, tmp_path):
    p = Project(
        canvas=canvas(),
        clips=[Clip(id="1", asset_id="silent")],  # 2s, silent
        audio=[AudioClip(id="a", asset_id="audio", start=0.5, trim_in=1.0, volume=0.7, fade_in=0.2, fade_out=0.2)],
    )
    _, info = render(p, assets, tmp_path)
    assert info.has_audio
    assert info.duration == pytest.approx(2.0, abs=0.15)


def test_export_without_audio_has_no_audio_stream(assets, tmp_path):
    _, info = render(Project(canvas=canvas(), clips=[Clip(id="1", asset_id="av")]), assets, tmp_path, include_audio=False)
    assert not info.has_audio


def test_webm_and_gif_exports(assets, tmp_path):
    p = Project(canvas=canvas(), clips=[Clip(id="1", asset_id="silent", trim_out=1.0)])
    _, webm = render(p, assets, tmp_path, format="webm", quality="low")
    assert webm.duration == pytest.approx(1.0, abs=0.2)
    _, gif = render(p, assets, tmp_path, format="gif")
    assert gif.width <= 640 and gif.duration > 0.5


def test_export_resolution_and_fps_override(assets, tmp_path):
    p = Project(canvas=canvas(), clips=[Clip(id="1", asset_id="av", trim_out=1.0)])
    _, info = render(p, assets, tmp_path, width=320, height=180, fps=12)
    assert (info.width, info.height) == (320, 180)
    assert info.fps == pytest.approx(12, abs=0.5)


def test_preview_proxy_is_small_and_fast_format(assets, tmp_path):
    p = Project(canvas=Canvas(width=1280, height=720, fps=30), clips=[Clip(id="1", asset_id="av", trim_out=1.0)])
    _, info = render(p, assets, tmp_path, preview=True)
    assert info.width == 640 and info.height == 360


def test_vertical_canvas_pads_landscape_source(assets, tmp_path):
    p = Project(canvas=Canvas(width=360, height=640, fps=24), clips=[Clip(id="1", asset_id="av", trim_out=1.0)])
    _, info = render(p, assets, tmp_path)
    assert (info.width, info.height) == (360, 640)


def test_long_timeline_uses_filter_script_file(assets, tmp_path):
    clips = [Clip(id=str(i), asset_id="silent", trim_out=0.2) for i in range(40)]
    plan, info = render(Project(canvas=canvas(width=320, height=180), clips=clips), assets, tmp_path)
    assert any(a in ("-/filter_complex", "-filter_complex_script") for a in plan.args)
    assert info.duration == pytest.approx(8.0, abs=0.5)


def test_empty_timeline_is_rejected(assets, tmp_path):
    with pytest.raises(PlanError):
        build_plan(Project(), assets, ExportOptions(), tmp_path / "x.mp4", tmp_path)


def test_audio_file_on_video_track_is_rejected(assets, tmp_path):
    with pytest.raises(PlanError):
        build_plan(Project(clips=[Clip(id="1", asset_id="audio")]), assets, ExportOptions(), tmp_path / "x.mp4", tmp_path)


def test_sixty_clip_timeline_with_audio_and_transitions_finishes(assets, tmp_path):
    """Regression: ffmpeg's audio concat deadlocked on long timelines (about 1 run in 4)."""
    clips = [
        Clip(id=str(i), asset_id="av", trim_out=0.4, transition=Transition(type="fade", duration=0.1) if i % 3 == 0 else Transition())
        for i in range(60)
    ]
    p = Project(canvas=canvas(width=320, height=180), clips=clips)
    out = tmp_path / "long.mp4"
    plan = build_plan(p, assets, ExportOptions(), out, tmp_path / "work")
    run_ffmpeg(plan.args, plan.total, stall_timeout=30)
    info = probe(out)
    assert info.has_audio
    assert info.duration == pytest.approx(plan.total, abs=0.4)


def test_stalled_ffmpeg_is_killed_with_a_clear_error(tmp_path):
    from ltxps.editor.media import FfmpegError

    # An endless lavfi source with output to the null muxer at real-time speed stalls progress output.
    with pytest.raises(FfmpegError, match="stopped responding"):
        run_ffmpeg(["-re", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=1", "-progress", "pipe:2", "-f", "null", "-"], 0, stall_timeout=2)
