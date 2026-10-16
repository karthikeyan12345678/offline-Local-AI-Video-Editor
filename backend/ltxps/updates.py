"""Update check: a small manifest on GitHub lists the newest app version and the tested versions of the AI modules.

The person never touches pip or Node. When they press "Update AI modules" the listed versions are installed into
the app's own Python. The manifest is written by the maintainer (scripts/make_update_manifest.py), so only
versions that were tested together are ever offered.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from importlib import metadata
from typing import Any, Callable

import httpx

from . import __version__

DEFAULT_URL = "https://raw.githubusercontent.com/karthikeyan12345678/ai-assistant-studio/main/update-manifest.json"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
Fetch = Callable[[str], dict[str, Any]]


class UpdateError(RuntimeError):
    """Message is safe to show to the user."""


def manifest_url() -> str:
    return os.environ.get("LTXPS_UPDATE_URL") or DEFAULT_URL


def fetch_manifest(url: str) -> dict[str, Any]:
    try:
        r = httpx.get(url, timeout=httpx.Timeout(12.0, connect=6.0), follow_redirects=True, headers={"User-Agent": "vk-editor"})
    except httpx.HTTPError as exc:
        raise UpdateError("Could not reach the update server. Check your internet connection.") from exc
    if r.status_code == 404:
        raise UpdateError("No update information has been published yet.")
    if r.status_code >= 400:
        raise UpdateError(f"The update server answered {r.status_code}. Try again later.")
    try:
        data = r.json()
    except ValueError as exc:
        raise UpdateError("The update information could not be read.") from exc
    if not isinstance(data, dict):
        raise UpdateError("The update information could not be read.")
    return data


def vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v.split("+")[0].split("-")[0])[:4]) or (0,)


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def installed_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def check(fetch: Fetch = fetch_manifest, installed: Callable[[str], str | None] = installed_version) -> dict[str, Any]:
    m = fetch(manifest_url())
    latest = str(m.get("app_version", "")).strip()
    modules = []
    for item in m.get("modules", []):
        if not isinstance(item, dict) or "name" not in item or "version" not in item:
            continue
        name, want = str(item["name"]), str(item["version"])
        have = installed(name)
        modules.append({"name": name, "label": item.get("label", name), "installed": have, "latest": want,
                        "update": have is None or vtuple(have) < vtuple(want), "missing": have is None})
    return {
        "current": __version__, "latest": latest or __version__,
        "app_update": bool(latest) and vtuple(latest) > vtuple(__version__),
        "download_url": m.get("download_url", ""), "notes": m.get("notes", ""),
        "modules": modules, "modules_update": any(x["update"] for x in modules),
    }


def pip_install(specs: list[str], on_line: Callable[[str], None], cancel: Any = None) -> None:
    cmd = [sys.executable, "-m", "pip", "install", "--no-warn-script-location", "--progress-bar", "raw", *specs]
    env = {**os.environ, "PYTHONUTF8": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", env=env, creationflags=NO_WINDOW)
    tail: list[str] = []
    assert p.stdout is not None
    for raw in p.stdout:
        for line in re.split(r"[\r\n]+", raw):
            line = line.strip()
            if not line:
                continue
            tail = (tail + [line])[-8:]
            on_line(line)
        if cancel is not None and cancel.is_set():
            p.kill()
            raise UpdateError("Cancelled.")
    if p.wait() != 0:
        raise UpdateError("The update could not be installed:\n" + "\n".join(tail[-4:]))


def update_modules(fetch: Fetch = fetch_manifest, installed: Callable[[str], str | None] = installed_version, installer: Callable[..., None] = pip_install, on_line: Callable[[str], None] = lambda _l: None, cancel: Any = None) -> dict[str, Any]:
    info = check(fetch, installed)
    todo = [m for m in info["modules"] if m["update"]]
    if not todo:
        return {"updated": [], "restart": False}
    installer([f"{m['name']}=={m['latest']}" for m in todo], on_line, cancel)
    return {"updated": [m["name"] for m in todo], "restart": True}


def manifest_from_requirements(requirements_text: str, app_version: str, notes: str = "", download_url: str = "", only: tuple[str, ...] = ()) -> dict[str, Any]:
    """Used by scripts/make_update_manifest.py and the tests: every pinned package becomes an updatable module."""
    mods = []
    for line in requirements_text.splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+)==([\w.\-+]+)", line.strip())
        if m and (not only or _norm(m.group(1)) in only):
            mods.append({"name": m.group(1), "version": m.group(2)})
    return {"app_version": app_version, "notes": notes, "download_url": download_url, "modules": mods}


# Packages the person can refresh without reinstalling the app. PyTorch is left out on purpose: it is tied to the graphics card.
UPDATABLE = ("faster-whisper", "opencv-python-headless", "imageio-ffmpeg", "pillow", "httpx", "pypdf", "python-docx", "python-pptx", "openpyxl", "reportlab")


def json_text(m: dict[str, Any]) -> str:
    return json.dumps(m, indent=2, ensure_ascii=False) + "\n"
