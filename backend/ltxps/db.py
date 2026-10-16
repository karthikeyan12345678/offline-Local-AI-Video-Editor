"""SQLite storage for library assets and editor projects."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  path TEXT NOT NULL,
  thumb TEXT,
  duration REAL NOT NULL DEFAULT 0,
  width INTEGER NOT NULL DEFAULT 0,
  height INTEGER NOT NULL DEFAULT 0,
  fps REAL NOT NULL DEFAULT 0,
  has_audio INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL,
  meta TEXT NOT NULL DEFAULT '{}',
  created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  data TEXT NOT NULL,
  updated REAL NOT NULL
);
"""


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Asset:
    id: str
    kind: str
    name: str
    path: str
    thumb: str | None
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    source: str
    meta: dict[str, Any]
    created: float

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "thumb": self.thumb is not None,
            "duration": self.duration,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "has_audio": self.has_audio,
            "source": self.source,
            "meta": self.meta,
            "created": self.created,
        }


def _row_to_asset(r: sqlite3.Row) -> Asset:
    return Asset(
        id=r["id"], kind=r["kind"], name=r["name"], path=r["path"], thumb=r["thumb"], duration=r["duration"],
        width=r["width"], height=r["height"], fps=r["fps"], has_audio=bool(r["has_audio"]), source=r["source"],
        meta=json.loads(r["meta"] or "{}"), created=r["created"],
    )


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- assets
    def add_asset(self, a: Asset) -> Asset:
        with self._lock:
            self._conn.execute(
                "INSERT INTO assets (id,kind,name,path,thumb,duration,width,height,fps,has_audio,source,meta,created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (a.id, a.kind, a.name, a.path, a.thumb, a.duration, a.width, a.height, a.fps, int(a.has_audio), a.source, json.dumps(a.meta), a.created),
            )
            self._conn.commit()
        return a

    def get_asset(self, asset_id: str) -> Asset | None:
        with self._lock:
            r = self._conn.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
        return _row_to_asset(r) if r else None

    def list_assets(self, kind: str | None = None, source: str | None = None) -> list[Asset]:
        q, args = "SELECT * FROM assets", []
        clauses = []
        if kind:
            clauses.append("kind=?")
            args.append(kind)
        if source:
            clauses.append("source=?")
            args.append(source)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY created DESC"
        with self._lock:
            rows = self._conn.execute(q, args).fetchall()
        return [_row_to_asset(r) for r in rows]

    def rename_asset(self, asset_id: str, name: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE assets SET name=? WHERE id=?", (name, asset_id))
            self._conn.commit()

    def delete_asset(self, asset_id: str) -> Asset | None:
        a = self.get_asset(asset_id)
        if a:
            with self._lock:
                self._conn.execute("DELETE FROM assets WHERE id=?", (asset_id,))
                self._conn.commit()
        return a

    # ---- projects
    def save_project(self, project_id: str, name: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO projects (id,name,data,updated) VALUES (?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, data=excluded.data, updated=excluded.updated",
                (project_id, name, json.dumps(data), time.time()),
            )
            self._conn.commit()

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            r = self._conn.execute("SELECT data FROM projects WHERE id=?", (project_id,)).fetchone()
        return json.loads(r["data"]) if r else None

    def list_projects(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT id,name,updated FROM projects ORDER BY updated DESC").fetchall()
        return [{"id": r["id"], "name": r["name"], "updated": r["updated"]} for r in rows]

    def delete_project(self, project_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
            self._conn.commit()
