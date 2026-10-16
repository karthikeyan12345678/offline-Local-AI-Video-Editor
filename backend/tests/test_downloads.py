"""Downloader against a local server that mimics the Hugging Face API."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ltxps.catalog import BASE_ID, MODELS
from ltxps.config import Paths, SettingsStore
from ltxps.downloads import DownloadManager

FILES = {
    "Lightricks/LTX-Video": {
        "model_index.json": b'{"x":1}',
        "scheduler/scheduler_config.json": b'{"s":1}',
        "tokenizer/spiece.model": b"T" * 3000,
        "text_encoder/model-00001-of-00002.safetensors": b"A" * 400_000,
        "text_encoder/model-00002-of-00002.safetensors": b"B" * 300_000,
        "transformer/diffusion_pytorch_model.safetensors": b"NOPE" * 1000,  # must NOT be downloaded
        "ltxv-2b-0.9.6-distilled-04-25.safetensors": b"C" * 500_000,
    },
    "Lightricks/LTX-Video-0.9.5": {"transformer/config.json": b'{"t":1}', "vae/config.json": b'{"v":1}', "README.md": b"hi"},
}


class Handler(BaseHTTPRequestHandler):
    slow = False
    requests: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        Handler.requests.append((self.path, self.headers.get("Range")))
        parts = self.path.split("?")[0].strip("/").split("/")
        if parts[:2] == ["api", "models"]:
            repo = "/".join(parts[2:4])
            if repo not in FILES:
                return self.send_error(404)
            body = json.dumps([{"type": "file", "path": p, "size": len(b)} for p, b in FILES[repo].items()]).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        repo = "/".join(parts[:2])
        path = "/".join(parts[4:])
        data = FILES.get(repo, {}).get(path)
        if data is None:
            return self.send_error(404)
        start = 0
        rng = self.headers.get("Range")
        if rng:
            start = int(rng.split("=")[1].split("-")[0])
            if start >= len(data):
                return self.send_error(416)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        else:
            self.send_response(200)
        chunk = data[start:]
        self.send_header("Content-Length", str(len(chunk)))
        self.end_headers()
        step = 50_000
        for i in range(0, len(chunk), step):
            try:
                self.wfile.write(chunk[i:i + step])
            except (BrokenPipeError, ConnectionResetError):
                return
            if Handler.slow:
                time.sleep(0.05)


@pytest.fixture()
def server():
    Handler.requests = []
    Handler.slow = False
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture()
def mgr(tmp_path, server):
    paths = Paths(tmp_path / "d").ensure()
    settings = SettingsStore(paths.settings_file)
    settings.update({"hf_endpoint": server})
    return DownloadManager(paths.models, settings)


def finish(mgr, item, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        st = mgr.state(item)
        if st.status in ("done", "error", "cancelled"):
            return st
        time.sleep(0.05)
    raise AssertionError("download hung")


def test_base_downloads_only_what_the_pipeline_needs(mgr):
    mgr.start(BASE_ID)
    st = finish(mgr, BASE_ID)
    assert st.status == "done" and st.done == st.total == 7 + 7 + 3000 + 400_000 + 300_000
    root = mgr.models_root / "ltx-video-base"
    assert (root / "text_encoder" / "model-00001-of-00002.safetensors").stat().st_size == 400_000
    assert not (root / "transformer").exists()  # 0.9.0 weights are skipped
    assert mgr.is_installed(BASE_ID)


def test_model_install_fetches_weights_and_its_offline_config(mgr):
    spec = MODELS["ltxv-2b-distilled"]
    mgr.start(spec.id)
    assert finish(mgr, spec.id).status == "done"
    assert spec.checkpoint_path(mgr.models_root).stat().st_size == 500_000
    assert (spec.config_dir(mgr.models_root) / "transformer" / "config.json").read_bytes() == b'{"t":1}'
    assert not (spec.config_dir(mgr.models_root) / "README.md").exists()
    assert mgr.is_installed(spec.id) and mgr.installed_bytes(spec.id) > 500_000


def test_probe_reports_total_size_without_downloading(mgr):
    assert mgr.probe_size("ltxv-2b-distilled") == 500_000 + 7 + 7
    assert not mgr.is_installed("ltxv-2b-distilled")


def test_interrupted_download_resumes_from_the_part_file(mgr, server):
    spec = MODELS["ltxv-2b-distilled"]
    dest = spec.checkpoint_path(mgr.models_root)
    dest.parent.mkdir(parents=True)
    part = dest.with_suffix(dest.suffix + ".part")
    part.write_bytes(b"C" * 200_000)
    mgr.start(spec.id)
    assert finish(mgr, spec.id).status == "done"
    assert dest.read_bytes() == b"C" * 500_000
    ranges = [r for p, r in Handler.requests if p.endswith("04-25.safetensors")]
    assert ranges == ["bytes=200000-"]  # only the missing tail was requested


def test_cancel_keeps_the_partial_file_for_later_and_never_marks_installed(mgr):
    Handler.slow = True
    mgr.start(BASE_ID)
    time.sleep(0.4)
    mgr.cancel(BASE_ID)
    st = finish(mgr, BASE_ID)
    assert st.status == "cancelled" and not mgr.is_installed(BASE_ID)
    Handler.slow = False
    mgr.start(BASE_ID)
    assert finish(mgr, BASE_ID).status == "done" and mgr.is_installed(BASE_ID)


def test_corrupted_install_is_detected_by_size(mgr):
    mgr.start(BASE_ID)
    finish(mgr, BASE_ID)
    victim = mgr.models_root / "ltx-video-base" / "text_encoder" / "model-00002-of-00002.safetensors"
    victim.write_bytes(b"short")
    assert not mgr.is_installed(BASE_ID)


def test_unreachable_server_gives_a_readable_error(tmp_path):
    paths = Paths(tmp_path / "d").ensure()
    s = SettingsStore(paths.settings_file)
    s.update({"hf_endpoint": "http://127.0.0.1:9"})
    m = DownloadManager(paths.models, s)
    m.start(BASE_ID)
    st = finish(m, BASE_ID)
    assert st.status == "error" and "connect" in st.error.lower()


def test_missing_repo_explains_the_mirror_setting(mgr):
    mgr.settings.update({"hf_endpoint": mgr.settings.get().hf_endpoint + "/nowhere"})
    mgr.start("ltxv-2b-091")
    st = finish(mgr, "ltxv-2b-091")
    assert st.status == "error" and "not found" in st.error.lower()


def test_delete_removes_files_and_state(mgr):
    mgr.start(BASE_ID)
    finish(mgr, BASE_ID)
    mgr.delete(BASE_ID)
    assert not mgr.is_installed(BASE_ID) and not (mgr.models_root / "ltx-video-base").exists()
