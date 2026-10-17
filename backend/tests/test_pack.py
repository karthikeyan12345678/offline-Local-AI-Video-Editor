"""The 1.2.14 effect pack: every look, effect, mask, text animation, voice style and built-in sound renders through real ffmpeg."""

import subprocess
from pathlib import Path

import pytest
from PIL import Image

from conftest import FFMPEG, needs_ffmpeg
from ltxps.editor import audiofx, soundfx
from ltxps.editor.effects import EFFECTS, FILTER_PRESETS, LOOK_GROUP, EFFECT_GROUP, MASKS, mask_alpha_expr
from ltxps.editor.media import probe, run_ffmpeg
from ltxps.editor.project import Canvas, Clip, Effect, ExportOptions, Layer, Project, TextOverlay, TEXT_ANIM_IN, TEXT_ANIM_OUT
from ltxps.editor.render import AssetRef, build_plan

pytestmark = needs_ffmpeg


@pytest.fixture()
def assets(media) -> dict[str, AssetRef]:
    out = {}
    for key, path in (("av", media["av"]), ("silent", media["silent"])):
        info = probe(path)
        out[key] = AssetRef(path, info.kind, info.duration, info.has_audio, info.width, info.height)
    return out


def render(project: Project, assets, tmp_path: Path) -> Path:
    out = tmp_path / "out.mp4"
    plan = build_plan(project, assets, ExportOptions(), out, tmp_path / "work")
    run_ffmpeg(plan.args, plan.total)
    return out


def frame_at(video: Path, t: float, tmp_path: Path) -> Image.Image:
    png = tmp_path / f"f{t}.png"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1", str(png)], check=True)
    return Image.open(png).convert("RGB")


def small() -> Canvas:
    return Canvas(width=320, height=180, fps=24, background="#202020")


def test_every_look_and_effect_has_a_group():
    assert all(k in LOOK_GROUP for k in FILTER_PRESETS)
    assert all(k in EFFECT_GROUP for k in EFFECTS)
    assert len(FILTER_PRESETS) >= 50 and len(EFFECTS) >= 30


@pytest.mark.parametrize("look", [k for k in FILTER_PRESETS if k != "none"])
def test_every_look_renders(look, assets, tmp_path):
    p = Project(canvas=small(), clips=[Clip(id="c", asset_id="av", trim_out=0.5, preset=look)])
    out = render(p, assets, tmp_path)
    assert probe(out).duration == pytest.approx(0.5, abs=0.2)


@pytest.mark.parametrize("fx", list(EFFECTS))
def test_every_effect_renders(fx, assets, tmp_path):
    p = Project(canvas=small(), clips=[Clip(id="c", asset_id="av", trim_out=0.6, effects=[Effect(type=fx, amount=0.6)])])
    out = render(p, assets, tmp_path)
    assert probe(out).duration == pytest.approx(0.6, abs=0.25)


@pytest.mark.parametrize("fx", list(audiofx.AUDIO_FX))
def test_every_voice_and_sound_style_renders(fx, assets, tmp_path):
    p = Project(canvas=small(), clips=[Clip(id="c", asset_id="av", trim_out=0.6, audio_fx=fx)])
    out = render(p, assets, tmp_path)
    assert probe(out).has_audio


def _far(a, b) -> bool:
    return sum(abs(x - y) for x, y in zip(a, b)) > 45


def _masked_frames(assets, tmp_path, **mask_args):
    base = dict(canvas=Canvas(width=320, height=180, fps=24, background="#202020"), clips=[Clip(id="c", asset_id="silent", trim_out=1.5, fit="fill", muted=True)])
    out = {}
    for name, extra in (("plain", {}), ("masked", mask_args)):
        d = tmp_path / name
        d.mkdir()
        p = Project(**base, layers=[Layer(id="l", asset_id="av", size=1.0, trim_out=1.5, muted=True, **extra)])
        out[name] = frame_at(render(p, assets, d), 0.5, d)
    return out["plain"], out["masked"]


SHAPES_WITH_CENTRE = ("circle", "ellipse", "rounded", "diamond", "heart", "star", "hexagon")
CORNER_CUT = SHAPES_WITH_CENTRE


@pytest.mark.parametrize("mask", [m for m in MASKS if m != "none"])
def test_masks_cut_the_layer_into_a_shape(mask, assets, tmp_path):
    plain, cut = _masked_frames(assets, tmp_path, mask=mask, mask_feather=0.0)
    if mask in SHAPES_WITH_CENTRE:
        assert not _far(cut.getpixel((160, 90)), plain.getpixel((160, 90))), "the middle keeps the layer"
        assert _far(cut.getpixel((6, 6)), plain.getpixel((6, 6))), "the corner shows what is underneath"
    elif mask == "half_left":
        assert not _far(cut.getpixel((30, 90)), plain.getpixel((30, 90)))
        assert _far(cut.getpixel((300, 90)), plain.getpixel((300, 90)))
    elif mask == "half_top":
        assert not _far(cut.getpixel((160, 20)), plain.getpixel((160, 20)))
        assert _far(cut.getpixel((160, 170)), plain.getpixel((160, 170)))
    elif mask == "blinds":
        assert _far(cut.getpixel((160, 18)), plain.getpixel((160, 18)))  # inside a gap between two slats


def test_invert_swaps_inside_and_outside(assets, tmp_path):
    plain, inv = _masked_frames(assets, tmp_path, mask="circle", mask_feather=0.0, mask_invert=True)
    assert _far(inv.getpixel((160, 90)), plain.getpixel((160, 90)))
    assert not _far(inv.getpixel((6, 6)), plain.getpixel((6, 6)))


def test_mask_expression_for_none_is_one_and_invert_wraps():
    assert mask_alpha_expr("none") == "1"
    assert mask_alpha_expr("circle", 0.1, True).startswith("(1-")


@pytest.mark.parametrize("anim_in", TEXT_ANIM_IN)
def test_every_text_animation_in_renders(anim_in, assets, tmp_path):
    p = Project(canvas=small(), clips=[Clip(id="c", asset_id="av", trim_out=1.5)],
                texts=[TextOverlay(id="t", text="Hello world", start=0.1, duration=1.2, fade_in=0.6, fade_out=0.3, anim_in=anim_in)])
    out = render(p, assets, tmp_path)
    assert out.exists()


@pytest.mark.parametrize("anim_out", TEXT_ANIM_OUT)
def test_every_text_animation_out_renders(anim_out, assets, tmp_path):
    p = Project(canvas=small(), clips=[Clip(id="c", asset_id="av", trim_out=1.5)],
                texts=[TextOverlay(id="t", text="Bye", start=0.1, duration=1.2, fade_in=0.2, fade_out=0.5, anim_out=anim_out)])
    assert render(p, assets, tmp_path).exists()


def test_typewriter_text_grows_letter_by_letter(assets, tmp_path):
    p = Project(canvas=Canvas(width=320, height=180, fps=24, background="#000000"), clips=[Clip(id="c", asset_id="av", trim_out=2.0, fit="fill", muted=True, adjust={"brightness": -100})],
                texts=[TextOverlay(id="t", text="TYPEWRITER TEXT", start=0, duration=2.0, size=14, color="#FFFFFF", box=False, fade_in=1.0, anim_in="typewriter", anim_out="none", x=0.5, y=0.5)])
    out = render(p, assets, tmp_path)

    def white(t: float) -> int:
        return sum(1 for px in frame_at(out, t, tmp_path).getdata() if min(px) > 200)

    assert white(0.3) < white(1.5)


# ---------------------------------------------------------------- built-in sound library
def test_sound_library_covers_the_basics_and_every_sound_is_made(tmp_path):
    ids = set(soundfx.SOUNDS)
    assert {"whoosh", "pop", "ding", "impact", "riser", "rain", "beat_hiphop", "shutter"} <= ids
    assert len(ids) >= 35
    for sid in ids:
        f = soundfx.ensure(sid, tmp_path)
        info = probe(f)
        assert info.kind == "audio" and info.duration == pytest.approx(soundfx.SOUNDS[sid][2], abs=0.15), sid
        vol = subprocess.run([FFMPEG, "-i", str(f), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
        assert "max_volume: -91" not in vol and "max_volume" in vol, sid  # not silent


def test_sound_lookup_understands_everyday_words():
    assert soundfx.find("add a whoosh") == "whoosh"
    assert soundfx.find("camera click") == "shutter"
    assert soundfx.find("rain") == "rain"
    assert soundfx.find("drum loop") == "beat_hiphop"
    assert soundfx.find("nothing like this") is None
