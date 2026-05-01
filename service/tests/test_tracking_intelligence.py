"""
test_tracking_intelligence.py — Time-based follow-up intelligence engine.

Verifies the stage classification, expected-next-event derivation, and delay
detection used by the dashboard's "Next Expected Action" panel.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from app.services.tracking_intelligence import evaluate_tracking_intelligence


def _ev(loc, status="", desc="", hours_ago=1):
    """Build a synthetic normalized event."""
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {"timestamp": ts, "location": loc, "status": status, "description": desc}


# ── Stage classification ─────────────────────────────────────────────────────

def test_leipzig_returns_warsaw_within_24h():
    out = evaluate_tracking_intelligence([_ev("LEIPZIG - DE", hours_ago=2)])
    assert out["stage"] == "transit_eu_hub"
    assert out["expected_next"] == "Arrival at Warsaw"
    assert out["expected_within_hours"] == 24
    assert out["delay_flag"] is False


def test_warsaw_arrival_expects_dhl_email_within_6h():
    out = evaluate_tracking_intelligence([_ev("WARSAW - PL", hours_ago=2)])
    assert out["stage"] == "at_warsaw"
    assert "DHL" in out["expected_next"]
    assert out["expected_within_hours"] == 6


def test_hong_kong_stage():
    out = evaluate_tracking_intelligence([_ev("HONG KONG - HK", hours_ago=4)])
    assert out["stage"] == "transit_asia_hub"


def test_mumbai_stage():
    out = evaluate_tracking_intelligence([_ev("MUMBAI - IN", hours_ago=2)])
    assert out["stage"] == "origin_dispatched"


def test_delivered_status_terminal_no_expected_next():
    out = evaluate_tracking_intelligence([_ev("WARSAW - PL", status="delivered", desc="Delivered", hours_ago=1)])
    assert out["stage"] == "delivered"
    assert out["expected_next"] is None
    assert out["delay_flag"] is False


def test_unknown_location_falls_back_to_in_transit():
    out = evaluate_tracking_intelligence([_ev("PARIS - FR", hours_ago=1)])
    assert out["stage"] == "in_transit"


# ── Delay detection ──────────────────────────────────────────────────────────

def test_leipzig_overdue_after_24h():
    """Last event in Leipzig 30h ago → delay_flag=true, delay_hours=6."""
    out = evaluate_tracking_intelligence([_ev("LEIPZIG - DE", hours_ago=30)])
    assert out["delay_flag"] is True
    assert out["delay_hours"] >= 5.5  # roughly 6h overdue


def test_warsaw_dhl_email_overdue_triggers_action_hint():
    """At Warsaw + 12h elapsed + no DHL email in audit → action mentions overdue."""
    audit = {"dhl_email": {}}
    out = evaluate_tracking_intelligence(
        [_ev("WARSAW - PL", hours_ago=12)], audit=audit,
    )
    assert out["delay_flag"] is True
    assert "overdue" in out["recommended_action"].lower()


def test_warsaw_with_dhl_email_received_changes_action():
    """If audit shows dhl_email.received=true, action reflects that."""
    audit = {"dhl_email": {"received": True}}
    out = evaluate_tracking_intelligence(
        [_ev("WARSAW - PL", hours_ago=2)], audit=audit,
    )
    assert "already received" in out["recommended_action"].lower()


# ── Edge cases ───────────────────────────────────────────────────────────────

def test_empty_events_returns_safe_default():
    out = evaluate_tracking_intelligence([])
    assert out["stage"] == "in_transit"
    assert out["delay_flag"] is False


def test_event_without_timestamp_no_delay():
    out = evaluate_tracking_intelligence([{"location": "WARSAW - PL", "status": "", "description": ""}])
    # No timestamp → can't compute delay
    assert out["delay_flag"] is False
    assert out["hours_since_last_event"] is None
