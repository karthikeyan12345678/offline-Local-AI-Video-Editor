"""Composition root: builds every service once and shares it with the API."""

from __future__ import annotations

import os
import shutil
import threading
import time
from dataclasses import dataclass, field

from .config import Paths, SettingsStore, resolve_data_dir
from .db import Database
from .downloads import DownloadManager
from .engine.base import VideoEngine
from .jobs import JobManager
from .library import Library
from .system import SystemInfo, detect_system


@dataclass
class AppState:
    paths: Paths
    settings: SettingsStore
    db: Database
    library: Library
    jobs: JobManager
    downloads: DownloadManager
    engine: VideoEngine
    token: str
    _system: SystemInfo | None = None
    _system_at: float = 0.0
    requires_models: bool = True
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def system(self, refresh: bool = False) -> SystemInfo:
        with self._lock:
            if refresh or self._system is None or time.time() - self._system_at > 30:
                self._system = detect_system()
                self._system_at = time.time()
            return self._system

    def disk_free_gb(self) -> float:
        try:
            return round(shutil.disk_usage(self.paths.root).free / 1024**3, 1)
        except OSError:
            return 0.0


def build_state(token: str, engine: VideoEngine | None = None) -> AppState:
    paths = Paths(resolve_data_dir()).ensure()
    settings = SettingsStore(paths.settings_file)
    db = Database(paths.db)
    downloads = DownloadManager(paths.models, settings)
    state = AppState(
        paths=paths,
        settings=settings,
        db=db,
        library=Library(paths, db),
        jobs=JobManager(),
        downloads=downloads,
        engine=None,  # type: ignore[arg-type]  # set just below; the real engine needs `state.system`
        token=token,
    )
    if engine is not None:
        state.engine = engine
    elif os.environ.get("LTXPS_ENGINE") == "fake":
        from .engine.fake import FakeEngine

        state.engine = FakeEngine()
        state.requires_models = False
    else:
        from .engine.ltxv import LtxvEngine

        state.engine = LtxvEngine(paths, settings, downloads, state.system)
    return state
