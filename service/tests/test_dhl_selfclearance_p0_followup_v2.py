"""
test_dhl_selfclearance_p0_followup_v2.py — ADR-014 cadence scheduler.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services import dhl_selfclearance_followup_v2 as fu  # noqa: E402


def _utc(year, month, day, hour=10, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_working_hours_window_default_parses():
    start, end, tz = fu._working_hours_window()
    assert start.hour == 8
    assert end.hour == 16


def test_is_working_hours_inside_window_returns_true():
    # Monday 2026-05-11 at 10:00 UTC
    monday_10 = _utc(2026, 5, 11, hour=10)
    assert fu.is_working_hours(monday_10) is True


def test_is_working_hours_weekend_returns_false():
    # Saturday 2026-05-09 at 12:00 UTC
    assert fu.is_working_hours(_utc(2026, 5, 9, hour=12)) is False


def test_is_working_hours_after_window_returns_false():
    assert fu.is_working_hours(_utc(2026, 5, 11, hour=23)) is False


def test_next_tick_working_hours_uses_short_interval():
    now = _utc(2026, 5, 11, hour=10)
    activated = _utc(2026, 5, 11, hour=8)
    d = fu.next_tick_time(now, activated)
    assert d.in_working_hours is True
    assert d.interval_sec == 7200  # 2h
    assert d.next_tick_at == now + timedelta(seconds=7200)


def test_next_tick_offhours_uses_long_interval():
    now = _utc(2026, 5, 9, hour=12)  # Saturday
    activated = _utc(2026, 5, 9, hour=11)
    d = fu.next_tick_time(now, activated)
    assert d.in_working_hours is False
    assert d.interval_sec == 21600  # 6h


def test_livelock_budget_exhausted_returns_no_tick():
    activated = _utc(2026, 5, 1, hour=10)
    # 1 week + 1 day after activation
    now = activated + timedelta(hours=200)
    d = fu.next_tick_time(now, activated)
    assert d.livelock_exhausted is True
    assert d.next_tick_at is None


def test_next_tick_caps_at_budget_end():
    activated = _utc(2026, 5, 1, hour=10)
    # Just before budget expires; interval would push past
    end = activated + timedelta(hours=fu._livelock_budget_hours())
    now = end - timedelta(minutes=30)
    d = fu.next_tick_time(now, activated)
    assert d.next_tick_at is not None
    assert d.next_tick_at <= end


def test_should_fire_is_true_when_not_exhausted():
    activated = _utc(2026, 5, 11, hour=8)
    now = _utc(2026, 5, 11, hour=10)
    d = fu.next_tick_time(now, activated)
    assert d.should_fire is True


def test_livelock_budget_end_computes_one_week_default():
    activated = _utc(2026, 5, 1, hour=10)
    end = fu.livelock_budget_end(activated)
    assert end - activated == timedelta(hours=168)


def test_is_holiday_default_stub_returns_false():
    assert fu.is_holiday(_utc(2026, 1, 1)) is False
