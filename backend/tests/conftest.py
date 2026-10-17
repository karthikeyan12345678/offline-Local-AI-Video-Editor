import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ltxps.system import ffmpeg_path  # noqa: E402

FFMPEG = ffmpeg_path()
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not available")


def _run(*args: str) -> None:
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", *args], check=True)


@pytest.fixture(scope="session")
def media(tmp_path_factory) -> dict[str, Path]:
    """Small synthetic media: a/v clip, silent clip, audio, still image."""
    if FFMPEG is None:
        pytest.skip("ffmpeg not available")
    d = tmp_path_factory.mktemp("media")
    files = {
        "av": d / "av.mp4",  # 640x360 @24, 3s, with audio
        "silent": d / "silent.mp4",  # 320x240 @30, 2s, no audio, different size/fps on purpose
        "audio": d / "music.wav",  # 6s
        "image": d / "still.png",
    }
    _run("-f", "lavfi", "-i", "testsrc=size=640x360:rate=24:duration=3", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(files["av"]))
    _run("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(files["silent"]))
    _run("-f", "lavfi", "-i", "sine=frequency=300:duration=6", str(files["audio"]))
    _run("-f", "lavfi", "-i", "color=c=blue:size=200x100", "-frames:v", "1", str(files["image"]))
    return files


@pytest.fixture()
def data_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("LTXPS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def has_cmd(name: str) -> bool:
    return shutil.which(name) is not None


@pytest.fixture(autouse=True)
def _no_real_fal_calls(monkeypatch):
    """Tests must never contact fal.ai (a fake key would be refused there)."""
    from ltxps.editor import motion

    monkeypatch.setattr(motion, "check_key", lambda key, client=None: None)
