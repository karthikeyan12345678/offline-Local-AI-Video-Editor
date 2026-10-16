"""Every transition, look, effect, motion, sound effect and text animation really renders through ffmpeg."""

from pathlib import Path

import pytest

from conftest import needs_ffmpeg
from ltxps.editor import audiofx, effects
from ltxps.editor.media import probe, run_ffmpeg
from ltxps.editor.project import AudioClip, Canvas, Clip, Effect, ExportOptions, Follow, Project, TextOverlay, Transition
from ltxps.editor.render import AssetRef, build_plan

pytestmark = needs_ffmpeg


@pytest.fixture()
def assets(media):
    out = {}
    for key in ("av", "audio", "image"):
        i = probe(media[key])
        out[key] = AssetRef(media[key], i.kind, i.duration, i.has_audio, i.width, i.height)
    return out


def render(project, assets, tmp_path, **opts):
    o = ExportOptions(**opts)
    out = tmp_path / f"out.{o.format}"
    plan = build_plan(project, assets, o, out, tmp_path / "work")
    run_ffmpeg(plan.args, plan.total)
    return plan, probe(out)


def cv():
    return Canvas(width=320, height=180, fps=12)


@pytest.mark.parametrize("name", [t for t in effects.TRANSITIONS if t != "none"])
def test_transition(name, assets, tmp_path):
    p = Project(canvas=cv(), clips=[Clip(id="1", asset_id="av", trim_out=1.5, transition=Transition(type=name, duration=0.5)), Clip(id="2", asset_id="av", trim_in=1, trim_out=2.5)])
    _, info = render(p, assets, tmp_path)
    assert info.duration == pytest.approx(2.5, abs=0.3)


@pytest.mark.parametrize("name", [k for k in effects.FILTER_PRESETS if k != "none"])
def test_look(name, assets, tmp_path):
    render(Project(canvas=cv(), clips=[Clip(id="1", asset_id="av", trim_out=1, preset=name)]), assets, tmp_path)


@pytest.mark.parametrize("name", list(effects.EFFECTS))
def test_effect(name, assets, tmp_path):
    render(Project(canvas=cv(), clips=[Clip(id="1", asset_id="av", trim_out=1, effects=[Effect(type=name, amount=0.6)])]), assets, tmp_path)


@pytest.mark.parametrize("name", [m for m in effects.MOTIONS if m != "none"])
def test_motion(name, assets, tmp_path):
    render(Project(canvas=cv(), clips=[Clip(id="1", asset_id="av", trim_out=1, motion=name)]), assets, tmp_path)
    render(Project(canvas=cv(), clips=[Clip(id="1", asset_id="image", motion=name)]), assets, tmp_path / "img")


@pytest.mark.parametrize("name", list(audiofx.AUDIO_FX))
def test_audio_fx(name, assets, tmp_path):
    _, info = render(Project(canvas=cv(), clips=[Clip(id="1", asset_id="av", trim_out=1.5, audio_fx=name)]), assets, tmp_path)
    assert info.has_audio


@pytest.mark.parametrize("name", ["fade", "slide_up", "slide_down", "slide_left", "slide_right", "zoom", "pop", "reveal", "none"])
def test_text_in(name, assets, tmp_path):
    t = TextOverlay(id="t", text="Hello வணக்கம்", start=0.2, duration=1.5, anim_in=name, fade_in=0.4, fade_out=0.4, font="anton", stroke=6, glow=0.5)
    render(Project(canvas=cv(), clips=[Clip(id="1", asset_id="av", trim_out=2)], texts=[t]), assets, tmp_path)


@pytest.mark.parametrize("name", ["none", "fade", "slide_up", "slide_down", "slide_left", "slide_right", "zoom"])
def test_text_out(name, assets, tmp_path):
    t = TextOverlay(id="t", text="Bye", start=0.2, duration=1.5, anim_out=name, fade_in=0.3, fade_out=0.5)
    render(Project(canvas=cv(), clips=[Clip(id="1", asset_id="av", trim_out=2)], texts=[t]), assets, tmp_path)


def test_follow_crop(assets, tmp_path):
    keys = [(0.0, 0.2, 0.5), (1.0, 0.5, 0.4), (2.0, 0.8, 0.5)]
    p = Project(canvas=cv(), clips=[Clip(id="1", asset_id="av", trim_out=2, follow=Follow(keys=keys, zoom=1.5))])
    _, info = render(p, assets, tmp_path)
    assert info.width == 320 and info.duration == pytest.approx(2, abs=0.3)


def test_music_loop_duck_normalize(assets, tmp_path):
    p = Project(canvas=cv(), clips=[Clip(id="1", asset_id="av", trim_out=3)], duck_music=True, master_normalize=True,
                audio=[AudioClip(id="m", asset_id="audio", loop=True, fade_out=1, fx="warm", pitch=2, normalize=True)])
    plan, info = render(p, assets, tmp_path)
    assert info.has_audio and info.duration == pytest.approx(3, abs=0.3)


def test_drawings_render_over_the_video(assets, tmp_path):
    from ltxps.editor.project import Drawing, Shape

    shapes = [
        Shape(type="pen", points=[(0.1, 0.1), (0.3, 0.5), (0.5, 0.2)], color="#00FF00", width=1.5),
        Shape(type="arrow", points=[(0.2, 0.8), (0.8, 0.8)], color="#FF0000"),
        Shape(type="ellipse", points=[(0.4, 0.3), (0.7, 0.7)], color="#FFFF00", filled=True, fill_opacity=0.3),
        Shape(type="rect", points=[(0.05, 0.05), (0.95, 0.95)], color="#FFFFFF"),
        Shape(type="highlight", points=[(0.2, 0.4), (0.8, 0.4)], color="#FFEB3B"),
        Shape(type="line", points=[(0, 0), (1, 1)]),
    ]
    for anim in ("none", "fade", "pop", "reveal", "slide_up"):
        d = Drawing(id="d", start=0.2, duration=1.5, shapes=shapes, anim_in=anim, fade_in=0.4)
        p = Project(canvas=cv(), clips=[Clip(id="1", asset_id="av", trim_out=2)], drawings=[d])
        _, info = render(p, assets, tmp_path / anim)
        assert info.duration == pytest.approx(2, abs=0.3)


def test_drawing_png_has_ink_where_drawn(tmp_path):
    from PIL import Image

    from ltxps.editor.drawimage import render_drawing_png
    from ltxps.editor.project import Drawing, Shape

    out = tmp_path / "d.png"
    render_drawing_png(Drawing(id="d", shapes=[Shape(type="line", points=[(0.1, 0.5), (0.9, 0.5)], color="#FF0000", width=2)]), 200, 100, out)
    im = Image.open(out).convert("RGBA")
    assert im.size == (200, 100)
    assert im.getpixel((100, 50))[3] > 200 and im.getpixel((100, 5))[3] == 0


@pytest.mark.parametrize("anim", ["none", "fade", "pop", "slide_up"])
def test_picture_overlay_renders_and_shows_ink(anim, assets, tmp_path):
    from ltxps.editor.project import ImageOverlay

    ov = ImageOverlay(id="i", asset_id="image", start=0.2, duration=1.5, x=0.5, y=0.3, size=0.3, rotation=15, opacity=0.9, anim_in=anim, fade_in=0.3)
    p = Project(canvas=cv(), clips=[Clip(id="1", asset_id="av", trim_out=2)], images=[ov])
    _, info = render(p, assets, tmp_path / anim)
    assert info.duration == pytest.approx(2, abs=0.3)


def test_picture_overlay_png_is_placed_at_its_spot(assets, tmp_path):
    from PIL import Image

    from ltxps.editor.drawimage import render_image_overlay_png
    from ltxps.editor.project import ImageOverlay

    out = tmp_path / "i.png"
    render_image_overlay_png(ImageOverlay(id="i", asset_id="image", x=0.25, y=0.5, size=0.2), assets["image"].path, 400, 200, out)
    im = Image.open(out).convert("RGBA")
    assert im.size == (400, 200) and im.getpixel((100, 100))[3] > 0 and im.getpixel((350, 10))[3] == 0
