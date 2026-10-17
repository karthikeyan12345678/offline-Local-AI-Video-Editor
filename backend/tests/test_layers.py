"""Layers (videos on top of or behind the main video), green-screen removal and keyframes, rendered through real ffmpeg."""

import subprocess
from pathlib import Path

import pytest
from PIL import Image

from conftest import FFMPEG, needs_ffmpeg
from ltxps.editor.media import probe, run_ffmpeg
from ltxps.editor.project import Canvas, Chroma, Clip, ExportOptions, Key, Layer, Project, TextOverlay
from ltxps.editor.render import AssetRef, build_plan, lerp_expr

pytestmark = needs_ffmpeg


@pytest.fixture(scope="module")
def green(tmp_path_factory) -> Path:
    """A green screen with a red square in the middle."""
    d = tmp_path_factory.mktemp("gs")
    out = d / "green.mp4"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x00FF00:s=320x240:d=3:r=24,drawbox=x=110:y=70:w=100:h=100:color=red:t=fill",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True)
    return out


@pytest.fixture()
def assets(media, green) -> dict[str, AssetRef]:
    out = {}
    for key, path in (("av", media["av"]), ("silent", media["silent"]), ("image", media["image"]), ("green", green)):
        info = probe(path)
        out[key] = AssetRef(path, info.kind, info.duration, info.has_audio, info.width, info.height)
    return out


def render(project: Project, assets, tmp_path: Path):
    out = tmp_path / "out.mp4"
    plan = build_plan(project, assets, ExportOptions(), out, tmp_path / "work")
    run_ffmpeg(plan.args, plan.total)
    return plan, out


def frame_at(video: Path, t: float, tmp_path: Path) -> Image.Image:
    png = tmp_path / f"f{t}.png"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1", str(png)], check=True)
    return Image.open(png).convert("RGB")


def canvas() -> Canvas:
    return Canvas(width=640, height=360, fps=24, background="#202020")


def is_green(px) -> bool:
    return px[1] > 150 and px[0] < 90 and px[2] < 90


def test_lerp_expression_holds_before_and_after_and_moves_between():
    e = lerp_expr([(1.0, 0.0, "linear"), (3.0, 1.0, "linear")])
    assert "lt(t,1)" in e and "lt(t,3)" in e
    assert lerp_expr([]) == "0" and lerp_expr([(2.0, 0.4, "smooth")]) == "0.4"
    assert "t-1" not in lerp_expr([(1.0, 0.0, "hold"), (3.0, 1.0, "hold")])  # a held key never blends


def test_layer_with_green_screen_removed_shows_the_video_behind_it(assets, tmp_path):
    p = Project(canvas=canvas(), clips=[Clip(id="1", asset_id="av")],
                layers=[Layer(id="l", asset_id="green", size=1.0, x=0.5, y=0.5, chroma=Chroma(enabled=True, similarity=0.35, blend=0.05))])
    plan, out = render(p, assets, tmp_path)
    info = probe(out)
    assert info.width == 640 and info.duration == pytest.approx(3.0, abs=0.2)
    f = frame_at(out, 1.0, tmp_path)
    assert not is_green(f.getpixel((60, 40)))  # the green is gone: the main video shows there
    r, g, b = f.getpixel((320, 180))
    assert r > 180 and g < 90  # the red square of the layer is still there


def test_same_layer_without_keying_covers_the_video_in_green(assets, tmp_path):
    p = Project(canvas=canvas(), clips=[Clip(id="1", asset_id="av")], layers=[Layer(id="l", asset_id="green", size=1.0)])
    _, out = render(p, assets, tmp_path)
    assert is_green(frame_at(out, 1.0, tmp_path).getpixel((20, 20)))


def test_layer_only_shows_between_its_start_and_end(assets, tmp_path):
    p = Project(canvas=canvas(), clips=[Clip(id="1", asset_id="av")], layers=[Layer(id="l", asset_id="green", size=1.0, start=1.0, trim_out=1.0)])
    _, out = render(p, assets, tmp_path)
    assert not is_green(frame_at(out, 0.4, tmp_path).getpixel((20, 20)))
    assert is_green(frame_at(out, 1.5, tmp_path).getpixel((20, 20)))
    assert not is_green(frame_at(out, 2.6, tmp_path).getpixel((20, 20)))


def test_keyframes_move_the_layer_over_time(assets, tmp_path):
    keys = [Key(t=0, x=0.2, y=0.5, size=0.3), Key(t=2, x=0.8, y=0.5, size=0.3, ease="linear")]
    p = Project(canvas=canvas(), clips=[Clip(id="1", asset_id="av")], layers=[Layer(id="l", asset_id="image", keys=keys, size=0.3)])
    _, out = render(p, assets, tmp_path)

    def blue_x(t: float) -> float:
        im = frame_at(out, t, tmp_path)
        xs = [x for x in range(0, 640, 4) if im.getpixel((x, 180))[2] > 200 and im.getpixel((x, 180))[0] < 60]
        assert xs, "the picture was not found"
        return sum(xs) / len(xs)

    assert blue_x(0.2) < blue_x(1.0) < blue_x(2.2)


def test_keyframed_size_and_opacity_render(assets, tmp_path):
    keys = [Key(t=0, x=0.5, y=0.5, size=0.2, opacity=1), Key(t=2, x=0.5, y=0.5, size=0.6, opacity=0.3, rotation=45)]
    p = Project(canvas=canvas(), clips=[Clip(id="1", asset_id="av")], layers=[Layer(id="l", asset_id="image", keys=keys)])
    _, out = render(p, assets, tmp_path)
    assert probe(out).duration == pytest.approx(3.0, abs=0.2)


def test_main_clip_green_screen_shows_a_layer_behind_it(assets, tmp_path):
    p = Project(canvas=canvas(), clips=[Clip(id="1", asset_id="green", chroma=Chroma(enabled=True, similarity=0.35, blend=0.05), fit="fill")],
                layers=[Layer(id="b", asset_id="av", behind=True, size=1.0)])
    plan, out = render(p, assets, tmp_path)
    f = frame_at(out, 1.0, tmp_path)
    assert not is_green(f.getpixel((20, 20)))
    r, g, b = f.getpixel((320, 180))
    assert r > 150 and g < 100


def test_behind_layer_without_keyed_video_warns(assets, tmp_path):
    p = Project(canvas=canvas(), clips=[Clip(id="1", asset_id="av")], layers=[Layer(id="b", asset_id="silent", behind=True)])
    plan, _ = render(p, assets, tmp_path)
    assert any("behind" in w for w in plan.warnings)


def test_layer_audio_is_mixed_and_can_be_muted(assets, tmp_path):
    p = Project(canvas=canvas(), clips=[Clip(id="1", asset_id="silent")], layers=[Layer(id="l", asset_id="av", size=0.3)])
    _, out = render(p, assets, tmp_path)
    assert probe(out).has_audio
    p2 = Project(canvas=canvas(), clips=[Clip(id="1", asset_id="silent")], layers=[Layer(id="l", asset_id="av", size=0.3, muted=True)])
    _, out2 = render(p2, assets, tmp_path / "m")
    # the silent main clip gets generated silence, so audio exists in both; the difference is the loudness
    def loud(path: Path) -> float:
        r = subprocess.run([FFMPEG, "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"], capture_output=True, text=True)
        import re
        m = re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr)
        return float(m.group(1)) if m else -91.0
    assert loud(out) > loud(out2) + 10


def test_text_follows_its_keyframes(assets, tmp_path):
    t = TextOverlay(id="t", text="WWWW", start=0, duration=3, x=0.2, y=0.5, size=12, box=False, color="#FFFFFF", fade_in=0, fade_out=0, anim_in="none", anim_out="none",
                    keys=[Key(t=0, x=0.1, y=0.5), Key(t=2.5, x=0.9, y=0.5, ease="linear")])
    p = Project(canvas=canvas(), clips=[Clip(id="1", asset_id="silent")], texts=[t])
    plan, out = render(p, assets, tmp_path)
    assert "lt(t," in " ".join(plan.args)


def test_old_projects_without_layers_still_load():
    p = Project.model_validate({"clips": [{"id": "1", "asset_id": "a"}], "texts": [{"id": "t", "text": "hi"}]})
    assert p.layers == [] and p.clips[0].chroma.enabled is False and p.texts[0].keys == []
