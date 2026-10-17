"""The online spending guard: off by default, a renewing budget when the person turns it on."""

import pytest

from ltxps.editor.budget import Budget, BudgetError


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def make(tmp_path):
    c = Clock()
    return Budget(tmp_path / "b.json", clock=c), c


def test_default_is_free_online_is_switched_off(tmp_path):
    b, _ = make(tmp_path)
    s = b.status()
    assert s["limit_usd"] == 0 and not s["enabled"]
    with pytest.raises(BudgetError, match="switched off"):
        b.reserve(0.5, "video")


def test_spending_is_limited_and_renews_after_the_window(tmp_path):
    b, c = make(tmp_path)
    b.set(1.00, 6)
    b.reserve(0.60, "a")
    with pytest.raises(BudgetError, match="renews in"):
        b.reserve(0.60, "b")
    assert b.status()["left_usd"] == 0.40
    c.now += 5 * 3600 + 59 * 60
    with pytest.raises(BudgetError):
        b.reserve(0.60, "still too early")
    c.now += 120  # now more than 6 hours since the first spend
    assert b.status()["left_usd"] == 1.00 and b.status()["renews_in"] == ""
    b.reserve(0.60, "after renewal")


def test_a_failed_job_is_refunded(tmp_path):
    b, _ = make(tmp_path)
    b.set(1.0, 12)
    t = b.reserve(0.9, "x")
    b.refund(t)
    assert b.status()["spent_usd"] == 0
    b.reserve(0.9, "again")


def test_settings_are_checked_and_survive_a_restart(tmp_path):
    b, c = make(tmp_path)
    with pytest.raises(BudgetError):
        b.set(window_hours=5)
    with pytest.raises(BudgetError):
        b.set(limit_usd=-1)
    b.set(2.5, 12)
    again = Budget(tmp_path / "b.json", clock=c)
    assert again.status()["limit_usd"] == 2.5 and again.status()["window_hours"] == 12
