import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from ltxps.editor import inpaint
from ltxps.editor.chat import apply_actions
from ltxps.editor.project import Project


class FakePipe:
    """Stands in for the real model: paints everything it is asked to repaint solid red."""

    def __init__(self):
        self.calls = []

    def __call__(self, **kw):
        self.calls.append(kw["prompt"])

        class R:
            images = [Image.new("RGB", kw["image"].size, (255, 0, 0))]

        return R()


def test_mask_from_rect_and_loop():
    m = inpaint.mask_from_shapes([{"type": "rect", "points": [[0.2, 0.2], [0.5, 0.5]]}], (200, 100))
    assert m.getpixel((70, 35)) == 255 and m.getpixel((190, 90)) == 0
    loop = [[0.2, 0.2], [0.6, 0.2], [0.6, 0.7], [0.2, 0.7], [0.2, 0.21]]
    m2 = inpaint.mask_from_shapes([{"type": "pen", "points": loop}], (200, 100))
    assert m2.getpixel((80, 45)) == 255  # a closed loop is filled


def test_empty_mask_is_explained():
    with pytest.raises(inpaint.InpaintError):
        inpaint.mask_from_shapes([], (100, 100))


def test_edit_frame_only_changes_the_marked_place():
    img = Image.new("RGB", (400, 300), (0, 120, 0))
    mask = inpaint.mask_from_shapes([{"type": "rect", "points": [[0.4, 0.4], [0.6, 0.6]]}], (400, 300))
    pipe = FakePipe()
    out = inpaint.edit_frame(pipe, img, mask, "empty field")
    assert out.getpixel((200, 150))[0] > 200  # repainted
    assert out.getpixel((5, 5)) == (0, 120, 0)  # untouched
    assert pipe.calls == ["empty field"]


def test_face_masks_sit_on_the_head():
    m = inpaint.mask_from_face({"x": 0.4, "y": 0.4, "w": 0.2, "h": 0.2}, (500, 500), "head")
    assert m.getpixel((250, 170)) == 255 and m.getpixel((250, 450)) == 0


def test_needs_a_place_and_a_prompt(tmp_path):
    with pytest.raises(inpaint.InpaintError):
        inpaint.edit_video("x.mp4", 0, 1, tmp_path / "o.mp4", prompt="a cap", shapes=[], part="")
    with pytest.raises(inpaint.InpaintError):
        inpaint.edit_video("x.mp4", 0, 1, tmp_path / "o.mp4", prompt="", shapes=[{"type": "rect", "points": [[0, 0], [1, 1]]}])


@pytest.mark.skipif(not shutil.which("ffmpeg") and not Path("/usr/bin/ffmpeg").exists(), reason="ffmpeg needed")
def test_edit_video_end_to_end_with_fake_model(tmp_path):
    from ltxps.editor.media import probe, require_ffmpeg

    src = tmp_path / "in.mp4"
    subprocess.run([require_ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=green:s=320x240:r=10:d=2", "-f", "lavfi", "-i", "sine=d=2", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)], check=True)
    out = tmp_path / "out.mp4"
    res = inpaint.edit_video(src, 0, 2, out, prompt="a red patch", shapes=[{"type": "rect", "points": [[0.3, 0.3], [0.7, 0.7]]}], pipe=FakePipe(), mode="patch")
    assert out.exists() and res["repainted"] == 1 and res["frames"] >= 15
    assert abs(probe(out).duration - 2) < 0.5
    import cv2

    cap = cv2.VideoCapture(str(out))
    ok, frame = cap.read()
    assert ok and frame[120, 160, 2] > 150 and frame[5, 5, 1] > 80  # red in the middle (BGR), still green at the corner


def test_chat_ai_edit_becomes_a_task_with_source_space_shapes():
    from ltxps.editor.render import AssetRef

    p = Project.model_validate({"canvas": {"width": 1280, "height": 720, "fps": 30},
                                "clips": [{"id": "c1", "asset_id": "a1", "trim_in": 0, "trim_out": 6}],
                                "drawings": [{"id": "d1", "start": 1, "duration": 3, "shapes": [{"type": "rect", "points": [[0.1, 0.1], [0.4, 0.5]], "color": "#ff0000", "width": 1}]}]})
    ctx = {"assets": {"a1": AssetRef(Path("x.mp4"), "video", 6.0, True, 1280, 720)}}
    r = apply_actions(p, [{"do": "task", "name": "ai_edit", "region": "drawing", "prompt": "flat grass field and sky"}], {"a1": "walk.mp4"}, ctx)
    assert r["tasks"] and r["tasks"][0]["name"] == "ai_edit" and not r["skipped"]
    t = r["tasks"][0]
    assert t["clips"] == ["c1"] and t["drawing_ids"] == ["d1"] and t["mode"] == "patch"
    assert abs(t["shapes"][0]["points"][1][0] - 0.4) < 0.01
    # the old wrong behaviour: the model says "remove" and has no drawing -> it must explain, not add a picture
    p2 = Project.model_validate({"clips": [{"id": "c1", "asset_id": "a1", "trim_in": 0, "trim_out": 6}]})
    r2 = apply_actions(p2, [{"do": "ai_edit", "region": "drawing", "prompt": "empty field"}], {"a1": "walk.mp4"}, ctx)
    assert not r2["tasks"] and "draw" in r2["skipped"][0]
    r3 = apply_actions(p2, [{"do": "ai_edit", "region": "head", "prompt": "a white baseball cap on the head"}], {"a1": "walk.mp4"}, ctx)
    assert r3["tasks"][0]["part"] == "head" and r3["tasks"][0]["mode"] == "track"


def test_a_picture_clip_can_be_repainted(tmp_path):
    src = tmp_path / "p.png"
    Image.new("RGB", (400, 300), (0, 120, 0)).save(src)
    out = tmp_path / "o.png"
    r = inpaint.edit_image(src, out, prompt="snowy mountain", shapes=[{"type": "rect", "points": [[0.3, 0.3], [0.7, 0.7]]}], pipe=FakePipe())
    im = Image.open(out)
    assert r["mode"] == "image" and im.getpixel((200, 150))[0] > 200 and im.getpixel((5, 5)) == (0, 120, 0)
    with pytest.raises(inpaint.InpaintError):
        inpaint.edit_image(src, out, prompt="snowy mountain", shapes=[], pipe=FakePipe())


def test_chat_accepts_a_picture_clip():
    from ltxps.editor.render import AssetRef

    p = Project.model_validate({"clips": [{"id": "c1", "asset_id": "a1"}],
                                "drawings": [{"id": "d1", "start": 0, "duration": 3, "shapes": [{"type": "pen", "points": [[0.2, 0.1], [0.5, 0.1], [0.5, 0.3], [0.2, 0.3], [0.2, 0.11]], "color": "#ff0000", "width": 1}]}]})
    ctx = {"assets": {"a1": AssetRef(Path("x.jpg"), "image", 0.0, False, 1086, 1448)}}
    r = apply_actions(p, [{"do": "ai_edit", "region": "drawing", "prompt": "snow covered rocky mountain"}], {"a1": "photo"}, ctx)
    assert r["tasks"] and not r["skipped"] and r["tasks"][0]["clips"] == ["c1"]


def test_new_diffusers_without_pipeline_vae_slicing_still_loads():
    class Vae:
        called = False

        def enable_slicing(self):
            Vae.called = True

    class Pipe:  # like diffusers 0.3x: no enable_vae_slicing on the pipeline itself
        vae = Vae()

    inpaint._vae_slicing(Pipe())
    assert Vae.called
    inpaint._vae_slicing(object())  # nothing available: no crash
