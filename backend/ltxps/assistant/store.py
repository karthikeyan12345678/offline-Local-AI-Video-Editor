"""Assistant storage: conversations, messages (with result cards), registered files, and settings with protected API keys."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, conv TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL, content TEXT NOT NULL, cards TEXT NOT NULL DEFAULT '[]', files TEXT NOT NULL DEFAULT '[]', created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS messages_conv ON messages(conv, created);
CREATE TABLE IF NOT EXISTS files (
  id TEXT PRIMARY KEY, origin TEXT NOT NULL, name TEXT NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL, size INTEGER NOT NULL, created REAL NOT NULL);
"""


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class AssistantStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(sql, args)
            rows = cur.fetchall()
            self._conn.commit()
            return rows

    # conversations
    def create_conversation(self, title: str = "New chat") -> dict[str, Any]:
        cid, now = new_id(), time.time()
        self._q("INSERT INTO conversations VALUES (?,?,?,?)", (cid, title, now, now))
        return {"id": cid, "title": title, "created": now, "updated": now}

    def list_conversations(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._q("SELECT * FROM conversations ORDER BY updated DESC LIMIT 200")]

    def get_conversation(self, cid: str) -> dict[str, Any] | None:
        r = self._q("SELECT * FROM conversations WHERE id=?", (cid,))
        return dict(r[0]) if r else None

    def rename(self, cid: str, title: str) -> bool:
        self._q("UPDATE conversations SET title=? WHERE id=?", (title.strip()[:120] or "Chat", cid))
        return self.get_conversation(cid) is not None

    def delete_conversation(self, cid: str) -> bool:
        existed = self.get_conversation(cid) is not None
        self._q("DELETE FROM conversations WHERE id=?", (cid,))
        return existed

    # messages
    def add_message(self, cid: str, role: str, content: str, cards: list[dict] | None = None, files: list[str] | None = None) -> dict[str, Any]:
        mid, now = new_id(), time.time()
        self._q("INSERT INTO messages VALUES (?,?,?,?,?,?,?)", (mid, cid, role, content, json.dumps(cards or []), json.dumps(files or []), now))
        self._q("UPDATE conversations SET updated=? WHERE id=?", (now, cid))
        return {"id": mid, "role": role, "content": content, "cards": cards or [], "files": files or [], "created": now}

    def messages(self, cid: str) -> list[dict[str, Any]]:
        out = []
        for r in self._q("SELECT * FROM messages WHERE conv=? ORDER BY created, rowid", (cid,)):
            d = dict(r)
            d["cards"] = json.loads(d["cards"])
            d["files"] = json.loads(d["files"])
            out.append(d)
        return out

    # files
    def add_file(self, origin: str, name: str, path: Path, kind: str) -> dict[str, Any]:
        fid = new_id()
        size = path.stat().st_size if path.exists() else 0
        self._q("INSERT INTO files VALUES (?,?,?,?,?,?,?)", (fid, origin, name, str(path), kind, size, time.time()))
        return {"id": fid, "origin": origin, "name": name, "kind": kind, "size": size}

    def get_file(self, fid: str) -> dict[str, Any] | None:
        r = self._q("SELECT * FROM files WHERE id=?", (fid,))
        return dict(r[0]) if r else None

    def list_files(self, origin: str | None = None) -> list[dict[str, Any]]:
        rows = self._q("SELECT * FROM files WHERE origin=? ORDER BY created DESC LIMIT 300", (origin,)) if origin else self._q("SELECT * FROM files ORDER BY created DESC LIMIT 300")
        return [{k: r[k] for k in ("id", "origin", "name", "kind", "size", "created")} for r in rows]

    def delete_file(self, fid: str) -> bool:
        f = self.get_file(fid)
        if not f:
            return False
        try:
            Path(f["path"]).unlink(missing_ok=True)
        except OSError:
            pass
        self._q("DELETE FROM files WHERE id=?", (fid,))
        return True


class AssistantSettings:
    """JSON file. API keys are never sent back to the UI: only a masked hint is."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.data: dict[str, Any] = {"provider": "ollama", "providers": {}, "image": {"provider": "horde"}, "default_theme": "claude", "system_prompt": ""}
        if path.exists():
            try:
                self.data.update(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def raw(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self.data))

    @staticmethod
    def mask(key: str) -> str:
        return "" if not key else ("•" * 8 + key[-4:] if len(key) > 8 else "•" * len(key))

    def public(self) -> dict[str, Any]:
        d = self.raw()
        for sect in (d["providers"], {"image": d["image"]}):
            for v in sect.values():
                if isinstance(v, dict):
                    for k2, v2 in list(v.items()):
                        if isinstance(v2, dict) and "api_key" in v2:
                            v2["api_key_hint"] = self.mask(v2.pop("api_key"))
                    if "api_key" in v:
                        v["api_key_hint"] = self.mask(v.pop("api_key"))
        return d

    def update(self, patch: dict[str, Any]) -> None:
        with self._lock:
            d = self.data
            for k in ("provider", "default_theme", "system_prompt"):
                if isinstance(patch.get(k), str):
                    d[k] = patch[k]
            for pid, vals in (patch.get("providers") or {}).items():
                if not isinstance(vals, dict):
                    continue
                cur = d["providers"].setdefault(pid, {})
                for k in ("base_url", "model", "style"):
                    if isinstance(vals.get(k), str):
                        cur[k] = vals[k].strip()
                if "api_key" in vals and isinstance(vals["api_key"], str) and not vals["api_key"].startswith("•"):
                    cur["api_key"] = vals["api_key"].strip()  # an untouched masked value means "keep the old key"
            img = patch.get("image")
            if isinstance(img, dict):
                if isinstance(img.get("provider"), str):
                    d["image"]["provider"] = img["provider"]
                    d["image"]["chosen"] = True  # the person picked an engine on purpose
                for pid, vals in img.items():
                    if isinstance(vals, dict):
                        cur = d["image"].setdefault(pid, {})
                        for k in ("base_url", "model"):
                            if isinstance(vals.get(k), str):
                                cur[k] = vals[k].strip()
                        if isinstance(vals.get("api_key"), str) and not vals["api_key"].startswith("•"):
                            cur["api_key"] = vals["api_key"].strip()
            self._save()
