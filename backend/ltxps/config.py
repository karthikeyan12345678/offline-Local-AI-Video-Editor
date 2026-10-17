"""Paths and persisted settings.

Everything the app writes lives under one data directory so the whole studio
(runtime, models, projects) can be copied to a USB drive and used on another PC.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path


def resolve_data_dir(product: str = "studio") -> Path:
    """The video studio and the separate AI Assistant keep their data in different folders (override with LTXPS_DATA_DIR)."""
    env = os.environ.get("LTXPS_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    folder = "LTXPortableStudio" if product == "studio" else "AIAssistantPortable"
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / folder
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg) / folder


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def models(self) -> Path:
        return self.root / "models"

    @property
    def outputs(self) -> Path:
        return self.root / "outputs"

    @property
    def imports(self) -> Path:
        return self.root / "imports"

    @property
    def thumbs(self) -> Path:
        return self.root / "thumbs"

    @property
    def renders(self) -> Path:
        return self.root / "renders"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def db(self) -> Path:
        return self.root / "studio.sqlite3"

    @property
    def settings_file(self) -> Path:
        return self.root / "settings.json"

    def ensure(self) -> "Paths":
        for p in (self.root, self.models, self.outputs, self.imports, self.thumbs, self.renders, self.cache, self.logs):
            p.mkdir(parents=True, exist_ok=True)
        return self


@dataclass
class Settings:
    # "auto" picks from detected VRAM. Otherwise lite | balanced | quality.
    profile: str = "auto"
    # "auto" | "model" | "group" | "sequential" | "none"
    memory_mode: str = "auto"
    # Where Hugging Face files come from. Lets users behind a mirror still download.
    hf_endpoint: str = "https://huggingface.co"
    default_model: str = "ltxv-2b-distilled"
    # Compute dtype override: "auto" | "bf16" | "fp16" | "fp32"
    compute_dtype: str = "auto"
    # Keep the DiT in memory between jobs (faster, uses RAM)
    keep_loaded: bool = False
    output_fps: int = 24
    # A video that runs longer than this many minutes is stopped with an explanation (0 = never stop)
    time_limit_min: int = 30
    # The first-run tour has been shown or skipped
    tour_done: bool = False
    auto_enhance: bool = True  # write a detailed prompt from a short idea before every video
    ai_upscale: bool = True  # Real-ESRGAN adds real fine detail (downloads about 45 MB once); falls back to plain sharpening
    sharpen_output: bool = True  # clean, enlarge and sharpen finished videos (they look soft at small sizes)


class SettingsStore:
    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._settings = self._load()

    def _load(self) -> Settings:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                known = {k: v for k, v in raw.items() if k in Settings.__dataclass_fields__}
                return Settings(**known)
            except (OSError, ValueError, TypeError):
                pass
        return Settings()

    def get(self) -> Settings:
        with self._lock:
            return Settings(**asdict(self._settings))

    def update(self, patch: dict) -> Settings:
        with self._lock:
            for key, value in patch.items():
                if key in Settings.__dataclass_fields__ and value is not None:
                    setattr(self._settings, key, value)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(self._settings), indent=2), encoding="utf-8")
            tmp.replace(self._path)
            return Settings(**asdict(self._settings))
