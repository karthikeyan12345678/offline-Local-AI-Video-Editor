"""Resumable model downloads straight from a Hugging Face compatible endpoint."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import httpx

from .catalog import AUX, BASE_ID, BASE_PATTERNS, BASE_REPO, CONFIG_PATTERNS, MODELS, base_dir
from .config import SettingsStore

MARKER = ".complete.json"


class DownloadCancelled(Exception):
    pass


@dataclass
class RemoteFile:
    path: str
    size: int


@dataclass
class DownloadState:
    id: str
    status: str = "idle"  # idle | probing | downloading | done | error | cancelled
    total: int = 0
    done: int = 0
    speed: float = 0.0
    current: str = ""
    error: str = ""
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)


def _headers() -> dict[str, str]:
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    h = {"User-Agent": "ltx-portable-studio/1.0"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def list_remote(endpoint: str, repo: str, patterns: tuple[str, ...] | list[str], client: httpx.Client | None = None) -> list[RemoteFile]:
    """List files in a repo matching glob patterns, with sizes."""
    own = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=True, headers=_headers())
    try:
        url: str | None = f"{endpoint.rstrip('/')}/api/models/{repo}/tree/main?recursive=true"
        files: list[RemoteFile] = []
        guard = 0
        while url and guard < 50:
            guard += 1
            resp = client.get(url)
            resp.raise_for_status()
            for entry in resp.json():
                if entry.get("type") != "file":
                    continue
                path = entry["path"]
                if any(fnmatch.fnmatch(path, pat) for pat in patterns):
                    size = entry.get("lfs", {}).get("size", entry.get("size", 0))
                    files.append(RemoteFile(path=path, size=int(size)))
            link = resp.headers.get("link", "")
            m = re.search(r'<([^>]+)>;\s*rel="next"', link)
            url = m.group(1) if m else None
        return files
    finally:
        if own:
            client.close()


def _fetch_file(
    client: httpx.Client,
    url: str,
    dest: Path,
    expected: int,
    on_bytes,
    cancel: threading.Event,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and expected and dest.stat().st_size == expected:
        on_bytes(expected)
        return
    part = dest.with_suffix(dest.suffix + ".part")
    have = part.stat().st_size if part.exists() else 0
    if expected and have > expected:
        part.unlink()
        have = 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    with client.stream("GET", url, headers=headers) as resp:
        if resp.status_code == 416:  # already complete
            have = expected
        else:
            resp.raise_for_status()
            if have and resp.status_code != 206:
                have = 0  # server ignored Range: restart
            mode = "ab" if have else "wb"
            on_bytes(have)
            with open(part, mode) as fh:
                for chunk in resp.iter_bytes(1024 * 1024):
                    if cancel.is_set():
                        raise DownloadCancelled()
                    fh.write(chunk)
                    on_bytes(len(chunk))
    if expected and part.stat().st_size != expected:
        raise IOError(f"Incomplete download for {dest.name}: got {part.stat().st_size} of {expected} bytes")
    part.replace(dest)


class DownloadManager:
    def __init__(self, models_root: Path, settings: SettingsStore):
        self.models_root = models_root
        self.settings = settings
        self._states: dict[str, DownloadState] = {}
        self._lock = threading.Lock()
        self._size_cache: dict[str, int] = {}

    # ---- layout --------------------------------------------------------------
    def _root(self, item_id: str) -> Path:
        if item_id in AUX:
            return self.models_root / item_id
        return base_dir(self.models_root) if item_id == BASE_ID else MODELS[item_id].root(self.models_root)

    def _marker(self, item_id: str) -> Path:
        return self._root(item_id) / MARKER

    def _plan(self, item_id: str) -> list[tuple[str, tuple[str, ...], str]]:
        """(repo, glob patterns, local sub-directory) for everything one item needs."""
        if item_id in AUX:
            return [(AUX[item_id].repo, AUX[item_id].patterns, "")]
        if item_id == BASE_ID:
            return [(BASE_REPO, BASE_PATTERNS, "")]
        spec = MODELS[item_id]
        return [(spec.repo, (spec.checkpoint,), ""), (spec.config_repo, CONFIG_PATTERNS, "config")]

    def is_installed(self, item_id: str) -> bool:
        marker = self._marker(item_id)
        if not marker.exists():
            return False
        try:
            meta = json.loads(marker.read_text(encoding="utf-8"))
            root = self._root(item_id)
            return bool(meta["files"]) and all(
                (root / f["path"]).exists() and (root / f["path"]).stat().st_size == f["size"] for f in meta["files"]
            )
        except (OSError, ValueError, KeyError):
            return False

    def installed_bytes(self, item_id: str) -> int:
        try:
            meta = json.loads(self._marker(item_id).read_text(encoding="utf-8"))
            return sum(f["size"] for f in meta["files"])
        except (OSError, ValueError, KeyError):
            return 0

    # ---- remote description ----------------------------------------------------
    def _remote_files(self, item_id: str, client: httpx.Client | None = None) -> list[tuple[RemoteFile, str, str]]:
        """(remote file, path relative to the item root, repo) for everything the item needs."""
        endpoint = self.settings.get().hf_endpoint
        out: list[tuple[RemoteFile, str, str]] = []
        for repo, patterns, sub in self._plan(item_id):
            files = list_remote(endpoint, repo, patterns, client)
            if not files:
                raise IOError(f"No files found in {repo}. Check the Hugging Face address in Settings.")
            for rf in files:
                out.append((rf, f"{sub}/{rf.path}" if sub else rf.path, repo))
        return out

    def probe_size(self, item_id: str) -> int:
        if item_id in self._size_cache:
            return self._size_cache[item_id]
        total = sum(rf.size for rf, _, _ in self._remote_files(item_id))
        self._size_cache[item_id] = total
        return total

    # ---- state -------------------------------------------------------------
    def state(self, item_id: str) -> DownloadState:
        with self._lock:
            st = self._states.get(item_id)
            if st is None:
                st = DownloadState(id=item_id)
                self._states[item_id] = st
            return st

    def start(self, item_id: str) -> DownloadState:
        if item_id != BASE_ID and item_id not in MODELS and item_id not in AUX:
            raise KeyError(item_id)
        st = self.state(item_id)
        with self._lock:
            if st.status in ("probing", "downloading"):
                return st
            st.status = "probing"
            st.error = ""
            st.done = 0
            st.total = 0
            st.speed = 0.0
            st.current = ""
            st.cancel = threading.Event()
        threading.Thread(target=self._run, args=(item_id, st), daemon=True, name=f"download-{item_id}").start()
        return st

    def cancel(self, item_id: str) -> None:
        st = self.state(item_id)
        st.cancel.set()

    def delete(self, item_id: str) -> None:
        import shutil

        shutil.rmtree(self._root(item_id), ignore_errors=True)
        self.state(item_id).status = "idle"

    # ---- worker ------------------------------------------------------------
    def _run(self, item_id: str, st: DownloadState) -> None:
        endpoint = self.settings.get().hf_endpoint.rstrip("/")
        root = self._root(item_id)
        try:
            with httpx.Client(timeout=httpx.Timeout(30, read=60), follow_redirects=True, headers=_headers()) as client:
                plan = self._remote_files(item_id, client)
                st.total = sum(rf.size for rf, _, _ in plan)
                self._size_cache[item_id] = st.total
                st.status = "downloading"

                base_done = 0
                window: list[tuple[float, int]] = []
                for rf, rel, repo in plan:
                    st.current = rel
                    file_done = 0

                    def on_bytes(n: int, _base=base_done) -> None:
                        nonlocal file_done
                        # First call carries the absolute resume offset, later calls are deltas.
                        file_done += n
                        st.done = _base + file_done
                        now = time.monotonic()
                        window.append((now, st.done))
                        while window and now - window[0][0] > 5:
                            window.pop(0)
                        if len(window) > 1 and window[-1][0] > window[0][0]:
                            st.speed = (window[-1][1] - window[0][1]) / (window[-1][0] - window[0][0])

                    url = f"{endpoint}/{repo}/resolve/main/{quote(rf.path)}"
                    _fetch_file(client, url, root / rel, rf.size, on_bytes, st.cancel)
                    base_done += rf.size
                    st.done = base_done

            self._marker(item_id).parent.mkdir(parents=True, exist_ok=True)
            self._marker(item_id).write_text(
                json.dumps({"files": [{"path": rel, "size": rf.size} for rf, rel, _ in plan]}), encoding="utf-8"
            )
            st.status = "done"
            st.speed = 0.0
        except DownloadCancelled:
            st.status = "cancelled"
        except (httpx.HTTPError, OSError) as exc:
            st.status = "error"
            st.error = _friendly(exc)


def _friendly(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return f"Access was refused ({code}). Check the Hugging Face address in Settings or your network."
        if code == 404:
            return "The file was not found at the configured Hugging Face address."
        return f"Server returned {code}."
    if isinstance(exc, httpx.ConnectError):
        return "Could not connect. Check your internet connection or the Hugging Face address in Settings."
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        return "The disk is full. Free some space and retry; the download will resume."
    return str(exc) or exc.__class__.__name__
