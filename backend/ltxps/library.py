"""Media library: importing files, registering outputs, thumbnails."""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path
from typing import Any

from .config import Paths
from .db import Asset, Database, new_id
from .editor.media import AUDIO_EXT, IMAGE_EXT, VIDEO_EXT, FfmpegError, probe, thumbnail
from .jobs import UserFacingError

SUPPORTED = (VIDEO_EXT | AUDIO_EXT | IMAGE_EXT) - {".gif_still"}


def safe_name(name: str) -> str:
    stem = re.sub(r"[^\w.\- ]+", "_", Path(name).stem).strip(" ._") or "media"
    return stem[:80]


class Library:
    def __init__(self, paths: Paths, db: Database):
        self.paths = paths
        self.db = db

    def register(self, file: Path, source: str, name: str | None = None, meta: dict[str, Any] | None = None) -> Asset:
        """Registers an existing file (already inside the data dir) as an asset."""
        try:
            info = probe(file)
        except FfmpegError as exc:
            raise UserFacingError(str(exc)) from exc
        asset_id = new_id()
        thumb_path = self.paths.thumbs / f"{asset_id}.jpg"
        thumb = str(thumb_path) if thumbnail(file, thumb_path, info) else None
        asset = Asset(
            id=asset_id, kind=info.kind, name=name or file.stem, path=str(file), thumb=thumb,
            duration=round(info.duration, 3), width=info.width, height=info.height, fps=info.fps,
            has_audio=info.has_audio, source=source, meta=meta or {}, created=time.time(),
        )
        return self.db.add_asset(asset)

    def import_file(self, src: Path, name: str | None = None) -> Asset:
        ext = src.suffix.lower()
        if ext not in SUPPORTED:
            raise UserFacingError(f"'{ext or 'this file type'}' is not a supported video, audio or image format.")
        if not src.exists():
            raise UserFacingError("That file no longer exists.")
        dest = self.paths.imports / f"{new_id()}_{safe_name(src.name)}{ext}"
        shutil.copy2(src, dest)
        try:
            return self.register(dest, "import", name or src.stem)
        except Exception:
            dest.unlink(missing_ok=True)
            raise

    def remove(self, asset_id: str) -> bool:
        a = self.db.delete_asset(asset_id)
        if not a:
            return False
        for p in (a.path, a.thumb):
            if p:
                Path(p).unlink(missing_ok=True)
        return True
