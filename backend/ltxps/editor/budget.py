"""A spending guard for the online (paid) features, so the app stays free unless the person decides otherwise.

The default budget is $0, which keeps every online feature switched off: the local engines (LTX on this PC, free motion, the editor) never cost anything.
If the person has some online credit and wants to use it, they set a budget and a renewing period (6, 12 or 24 hours). The budget is a *limit the
app respects*, not money the app creates: the credit itself always comes from the person's own fal.ai account.

The period is a rolling window, like a daily quota: what was spent is counted for `window_hours` after it was spent, then it is available again.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

WINDOWS = (6, 12, 24)


class BudgetError(Exception):
    """The message is safe to show to the person."""


def _human(seconds: float) -> str:
    m = max(1, int(round(seconds / 60)))
    h, m = divmod(m, 60)
    return f"{h} h {m} min" if h else f"{m} min"


class Budget:
    def __init__(self, path: Path, clock=time.time):
        self.path = path
        self.clock = clock
        self._lock = threading.Lock()

    # -------------------------------------------------------------- storage
    def _load(self) -> dict[str, Any]:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            d = d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            d = {}
        d.setdefault("limit_usd", 0.0)
        d.setdefault("window_hours", 24)
        d.setdefault("ledger", [])
        return d

    def _save(self, d: dict[str, Any]) -> None:
        try:
            self.path.write_text(json.dumps(d), encoding="utf-8")
        except OSError:
            pass

    def _live(self, d: dict[str, Any]) -> list[dict[str, Any]]:
        horizon = self.clock() - float(d["window_hours"]) * 3600
        live = [e for e in d["ledger"] if float(e.get("t", 0)) > horizon]
        d["ledger"] = live  # old entries are forgotten: they no longer count
        return live

    # -------------------------------------------------------------- public
    def status(self) -> dict[str, Any]:
        with self._lock:
            d = self._load()
            live = self._live(d)
            limit = float(d["limit_usd"])
            spent = round(sum(float(e["usd"]) for e in live), 2)
            first = min((float(e["t"]) for e in live), default=None)
            renews = max(0.0, first + float(d["window_hours"]) * 3600 - self.clock()) if first is not None else 0.0
            return {"limit_usd": limit, "window_hours": int(d["window_hours"]), "spent_usd": spent, "left_usd": round(max(0.0, limit - spent), 2),
                    "enabled": limit > 0, "renews_in_seconds": int(renews), "renews_in": _human(renews) if first is not None else "", "windows": list(WINDOWS)}

    def set(self, limit_usd: float | None = None, window_hours: int | None = None) -> dict[str, Any]:
        with self._lock:
            d = self._load()
            if limit_usd is not None:
                if not (0 <= float(limit_usd) <= 1000):
                    raise BudgetError("Choose an amount between $0 and $1000.")
                d["limit_usd"] = round(float(limit_usd), 2)
            if window_hours is not None:
                if int(window_hours) not in WINDOWS:
                    raise BudgetError("Choose 6, 12 or 24 hours.")
                d["window_hours"] = int(window_hours)
            self._live(d)
            self._save(d)
        return self.status()

    def reserve(self, usd: float, what: str) -> str:
        """Checks the money is there and sets it aside. Returns a ticket for refund()."""
        with self._lock:
            d = self._load()
            live = self._live(d)
            limit = float(d["limit_usd"])
            if limit <= 0:
                raise BudgetError("Online video is switched off, so nothing can cost you money. To use it with your own fal.ai credit, set an online budget first "
                                  "(Settings → Online budget). The free video on this PC is always available.")
            spent = sum(float(e["usd"]) for e in live)
            if spent + usd > limit + 1e-9:
                first = min(float(e["t"]) for e in live) if live else self.clock()
                wait = first + float(d["window_hours"]) * 3600 - self.clock()
                raise BudgetError(f"This would cost about ${usd:.2f} but only ${max(0.0, limit - spent):.2f} is left of your ${limit:.2f} budget. "
                                  f"The budget renews in {_human(wait)}. You can also pick a cheaper size, or make the video free on this PC.")
            ticket = uuid.uuid4().hex[:10]
            d["ledger"].append({"id": ticket, "t": self.clock(), "usd": round(usd, 4), "what": what[:80]})
            self._save(d)
            return ticket

    def refund(self, ticket: str) -> None:
        with self._lock:
            d = self._load()
            d["ledger"] = [e for e in d["ledger"] if e.get("id") != ticket]
            self._save(d)
