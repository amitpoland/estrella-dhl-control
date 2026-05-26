"""
test_dhl_followup_status_projector.py — Unit tests for the read-only
DHL follow-up automation status projector.

Pure-function module — no I/O at runtime: tests patch
``_audit_paths`` and ``_flag_on`` to inject synthetic state and never
touch real storage.

Coverage:
  1. flag-off → status_label = DISABLED
  2. flag-on, no audits → all counters zero
  3. inactive shipments excluded from counts
  4. monitoring vs eligible split by next_followup_at vs now
  5. next_due picks the earliest future timestamp
  6. last_sent / last_suppressed / last_failure resolve to the most recent
  7. today's counters scoped to start-of-UTC-day
  8. AI used vs fallback today counter from timeline details
  9. drill-down rows: status precedence (inactive excluded; eligible first)
 10. drill-down rows: mode = Manual when stopped_at present
 11. drill-down rows: stable sort by status then next_due_at
 12. humanise_age handles past, present, and future timestamps
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services import dhl_followup_status_projector as proj  # noqa: E402


_NOW = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)


def _audit(
    *,
    awb:           str = "12345",
    batch_id:      str = "SHIPMENT_12345_2026-05_aaaa",
    delivered:     bool = False,
    terminal:      bool = False,
    followup:      dict | None = None,
    timeline:      list | None = None,
    last_scan_at:  str | None = None,
) -> dict:
    """Build a synthetic audit dict that satisfies is_active_shipment when
    ``delivered=False`` and ``terminal=False``."""
    return {
        "batch_id":             batch_id,
        "awb":                  awb,
        "tracking_no":          awb,
        "clearance_decision":   {"clearance_path": "self_clearance"},
        "clearance_status":     "TERMINAL" if terminal else "in_progress",
        "_delivered_for_test":  delivered,
        "dhl_followup":         followup or {},
        "timeline":             timeline or [],
        "email_ingestion":      {"last_scan_at": last_scan_at} if last_scan_at else {},
    }


@pytest.fixture
def patch_storage(monkeypatch):
    """Inject synthetic audits and stub is_active_shipment to honour
    the ``_delivered_for_test`` test flag."""
    audits: list[dict] = []

    def _fake_paths():
        # Return synthetic path placeholders; _read_audit is also patched.
        return [Path(f"/synthetic/audit_{i}.json") for i, _ in enumerate(audits)]

    def _fake_read(p):
        idx = int(str(p).rsplit("_", 1)[-1].split(".")[0])
        return audits[idx]

    def _fake_active(audit):
        if not isinstance(audit, dict):
            return False, "audit_malformed"
        if audit.get("_delivered_for_test"):
            return False, "delivered"
        if audit.get("clearance_status") == "TERMINAL":
            return False, "clearance_terminal"
        if not (audit.get("awb") or audit.get("tracking_no") or "").strip():
            return False, "missing_awb"
        return True, "active"

    monkeypatch.setattr(proj, "_audit_paths", _fake_paths)
    monkeypatch.setattr(proj, "_read_audit", _fake_read)
    monkeypatch.setattr(proj, "_is_active", _fake_active)
    return audits


# ── 1. flag-off ──────────────────────────────────────────────────────────────

def test_flag_off_status_label_disabled(patch_storage, monkeypatch):
    monkeypatch.setattr(proj, "_flag_on", lambda: False)
    out = proj.project_automation_status(now=_NOW)
    assert out["flag_on"] is False
    assert out["status_label"] == "DISABLED"
    assert out["active_shipments"] == 0


# ── 2. flag-on, no audits ────────────────────────────────────────────────────

def test_flag_on_no_audits_all_zero(patch_storage, monkeypatch):
    monkeypatch.setattr(proj, "_flag_on", lambda: True)
    out = proj.project_automation_status(now=_NOW)
    assert out["flag_on"] is True
    assert out["status_label"] == "ACTIVE"
    assert out["active_shipments"] == 0
    assert out["monitoring"] == 0
    assert out["eligible_now"] == 0
    assert out["next_due"] is None
    assert out["last_sent"] is None
    assert out["traffic_light"] == {"ready": 0, "waiting": 0, "problems": 0}


# ── 3. inactive shipments excluded ───────────────────────────────────────────

def test_inactive_shipments_excluded_from_counts(patch_storage, monkeypatch):
    monkeypatch.setattr(proj, "_flag_on", lambda: True)
    patch_storage.append(_audit(awb="111", delivered=True))   # excluded
    patch_storage.append(_audit(awb="222", terminal=True))    # excluded
    patch_storage.append(_audit(awb="333"))                   # active
    out = proj.project_automation_status(now=_NOW)
    assert out["active_shipments"] == 1


# ── 4. monitoring vs eligible split ──────────────────────────────────────────

def test_monitoring_vs_eligible_split(patch_storage, monkeypatch):
    monkeypatch.setattr(proj, "_flag_on", lambda: True)
    future = (_NOW + timedelta(hours=2)).isoformat()
    past   = (_NOW - timedelta(minutes=5)).isoformat()
    patch_storage.append(_audit(awb="A", followup={"active": True, "next_followup_at": future}))
    patch_storage.append(_audit(awb="B", followup={"active": True, "next_followup_at": past}))
    patch_storage.append(_audit(awb="C", followup={"active": True, "next_followup_at": future}))
    out = proj.project_automation_status(now=_NOW)
    assert out["active_shipments"] == 3
    assert out["monitoring"] == 2
    assert out["eligible_now"] == 1
    assert out["traffic_light"]["ready"] == 1
    assert out["traffic_light"]["waiting"] == 2


# ── 5. next_due picks earliest future ────────────────────────────────────────

def test_next_due_picks_earliest_future(patch_storage, monkeypatch):
    monkeypatch.setattr(proj, "_flag_on", lambda: True)
    in_2h = (_NOW + timedelta(hours=2)).isoformat()
    in_5h = (_NOW + timedelta(hours=5)).isoformat()
    patch_storage.append(_audit(awb="LATER",   followup={"active": True, "next_followup_at": in_5h}))
    patch_storage.append(_audit(awb="SOONER",  followup={"active": True, "next_followup_at": in_2h}))
    out = proj.project_automation_status(now=_NOW)
    assert out["next_due"]["awb"] == "SOONER"
    assert "2h" in (out["next_due"]["due_in_human"] or "")
    assert out["next_due"]["due_in_human"].startswith("in ")


# ── 6. last_sent / last_suppressed / last_failure resolve to most recent ─────

def test_last_event_picks_most_recent(patch_storage, monkeypatch):
    monkeypatch.setattr(proj, "_flag_on", lambda: True)
    older = (_NOW - timedelta(hours=10)).isoformat()
    newer = (_NOW - timedelta(hours=2)).isoformat()
    patch_storage.append(_audit(
        awb="OLD",
        timeline=[
            {"event": "dhl_followup_sent",       "ts": older, "detail": {"ai_used": True}},
            {"event": "dhl_followup_suppressed", "ts": older, "detail": {"reason": "duplicate"}},
        ],
    ))
    patch_storage.append(_audit(
        awb="NEW",
        timeline=[
            {"event": "dhl_followup_sent",       "ts": newer, "detail": {"ai_used": False}},
        ],
    ))
    out = proj.project_automation_status(now=_NOW)
    assert out["last_sent"]["awb"] == "NEW"
    assert out["last_sent"]["ts"] == newer
    assert out["last_suppressed"]["awb"] == "OLD"
    assert out["last_failure"] is None


# ── 7. today's counters scoped to start-of-UTC-day ───────────────────────────

def test_today_counters_scoped_to_utc_day(patch_storage, monkeypatch):
    monkeypatch.setattr(proj, "_flag_on", lambda: True)
    today_morning = _NOW.replace(hour=8, minute=0).isoformat()
    yesterday     = (_NOW - timedelta(days=1)).isoformat()
    patch_storage.append(_audit(
        awb="X",
        timeline=[
            {"event": "dhl_followup_sent",       "ts": today_morning, "detail": {}},
            {"event": "dhl_followup_sent",       "ts": yesterday,     "detail": {}},
            {"event": "dhl_followup_suppressed", "ts": today_morning, "detail": {}},
            {"event": "dhl_followup_send_failed","ts": yesterday,     "detail": {}},
        ],
    ))
    out = proj.project_automation_status(now=_NOW)
    assert out["sent_today"] == 1
    assert out["suppressed_today"] == 1
    assert out["failed_today"] == 0


# ── 8. AI used vs fallback today counter ─────────────────────────────────────

def test_ai_used_vs_fallback_today(patch_storage, monkeypatch):
    monkeypatch.setattr(proj, "_flag_on", lambda: True)
    today = _NOW.replace(hour=10, minute=0).isoformat()
    patch_storage.append(_audit(
        awb="Y",
        timeline=[
            {"event": "dhl_followup_sent", "ts": today, "detail": {"ai_used": True}},
            {"event": "dhl_followup_sent", "ts": today, "detail": {"ai_used": False}},
            {"event": "dhl_followup_sent", "ts": today, "detail": {"ai_used": True}},
            {"event": "dhl_followup_sent", "ts": today, "detail": {}},  # neither
        ],
    ))
    out = proj.project_automation_status(now=_NOW)
    assert out["ai_used_today"] == 2
    assert out["ai_fallback_today"] == 1


# ── 9. drill-down rows: inactive excluded, eligible first ────────────────────

def test_shipment_rows_inactive_excluded_eligible_first(patch_storage, monkeypatch):
    monkeypatch.setattr(proj, "_flag_on", lambda: True)
    future = (_NOW + timedelta(hours=3)).isoformat()
    past   = (_NOW - timedelta(minutes=5)).isoformat()
    patch_storage.append(_audit(awb="A_DELIVERED", delivered=True))
    patch_storage.append(_audit(awb="B_MONITOR",  followup={"active": True, "next_followup_at": future}))
    patch_storage.append(_audit(awb="C_ELIGIBLE", followup={"active": True, "next_followup_at": past}))
    rows = proj.project_shipment_rows(now=_NOW)
    awbs = [r["awb"] for r in rows]
    assert "A_DELIVERED" not in awbs
    assert awbs[0] == "C_ELIGIBLE"
    assert rows[0]["status"] == proj.ST_ELIGIBLE
    assert rows[1]["status"] == proj.ST_MONITORING


# ── 10. drill-down rows: mode = Manual when stopped_at present ───────────────

def test_shipment_row_mode_manual_when_stopped(patch_storage, monkeypatch):
    monkeypatch.setattr(proj, "_flag_on", lambda: True)
    patch_storage.append(_audit(
        awb="STOPPED_AWB",
        followup={"active": True, "stopped_at": (_NOW - timedelta(hours=1)).isoformat()},
    ))
    rows = proj.project_shipment_rows(now=_NOW)
    assert len(rows) == 1
    assert rows[0]["mode"] == "Manual"
    assert rows[0]["status"] == proj.ST_STOPPED


# ── 11. drill-down rows: sort stable by status, then next_due_at ─────────────

def test_shipment_rows_sort_order(patch_storage, monkeypatch):
    monkeypatch.setattr(proj, "_flag_on", lambda: True)
    in_2h = (_NOW + timedelta(hours=2)).isoformat()
    in_5h = (_NOW + timedelta(hours=5)).isoformat()
    patch_storage.append(_audit(awb="MON_LATER",  followup={"active": True, "next_followup_at": in_5h}))
    patch_storage.append(_audit(awb="MON_SOONER", followup={"active": True, "next_followup_at": in_2h}))
    rows = proj.project_shipment_rows(now=_NOW)
    assert [r["awb"] for r in rows] == ["MON_SOONER", "MON_LATER"]


# ── 12. ST_FAILED row status when last followup event is a failure ──────────

def test_shipment_row_status_failed_when_last_event_is_failure(patch_storage, monkeypatch):
    monkeypatch.setattr(proj, "_flag_on", lambda: True)
    older = (_NOW - timedelta(hours=4)).isoformat()
    newer = (_NOW - timedelta(hours=1)).isoformat()
    patch_storage.append(_audit(
        awb="FAILED_AWB",
        followup={"active": True, "next_followup_at": (_NOW + timedelta(hours=2)).isoformat()},
        timeline=[
            {"event": "dhl_followup_sent",        "ts": older, "detail": {}},
            {"event": "dhl_followup_send_failed", "ts": newer, "detail": {"error": "smtp"}},
        ],
    ))
    rows = proj.project_shipment_rows(now=_NOW)
    assert len(rows) == 1
    assert rows[0]["status"] == proj.ST_FAILED


# ── 13. ST_SUPPRESSED row status when last followup event is a suppression ───

def test_shipment_row_status_suppressed_when_last_event_is_suppressed(patch_storage, monkeypatch):
    monkeypatch.setattr(proj, "_flag_on", lambda: True)
    patch_storage.append(_audit(
        awb="SUPP_AWB",
        followup={"active": True, "next_followup_at": (_NOW + timedelta(hours=2)).isoformat()},
        timeline=[
            {"event": "dhl_followup_suppressed", "ts": (_NOW - timedelta(minutes=10)).isoformat(),
             "detail": {"reason": "duplicate_idempotency_key"}},
        ],
    ))
    rows = proj.project_shipment_rows(now=_NOW)
    assert len(rows) == 1
    assert rows[0]["status"] == proj.ST_SUPPRESSED


# ── 14. Status precedence: failed beats suppressed when failed is more recent ─

def test_shipment_row_status_failed_beats_older_suppressed(patch_storage, monkeypatch):
    """When the same shipment has both events, the most recent wins."""
    monkeypatch.setattr(proj, "_flag_on", lambda: True)
    suppressed_old = (_NOW - timedelta(hours=8)).isoformat()
    failed_new     = (_NOW - timedelta(hours=1)).isoformat()
    patch_storage.append(_audit(
        awb="MIXED_AWB",
        followup={"active": True},
        timeline=[
            {"event": "dhl_followup_suppressed", "ts": suppressed_old, "detail": {}},
            {"event": "dhl_followup_send_failed", "ts": failed_new,    "detail": {}},
        ],
    ))
    rows = proj.project_shipment_rows(now=_NOW)
    assert rows[0]["status"] == proj.ST_FAILED


# ── 15. dhl_followup_stopped in timeline does NOT change status ─────────────

def test_shipment_row_status_ignores_stopped_event_when_state_not_stopped(patch_storage, monkeypatch):
    """A stopped-event in timeline without state.stopped_at means status is
    driven by next_followup_at, not the timeline event."""
    monkeypatch.setattr(proj, "_flag_on", lambda: True)
    patch_storage.append(_audit(
        awb="HISTORY_AWB",
        followup={"active": True, "next_followup_at": (_NOW + timedelta(hours=3)).isoformat()},
        timeline=[
            {"event": "dhl_followup_stopped", "ts": (_NOW - timedelta(hours=5)).isoformat(),
             "detail": {"reason": "manual"}},
        ],
    ))
    rows = proj.project_shipment_rows(now=_NOW)
    assert rows[0]["status"] == proj.ST_MONITORING


# ── 16. humanise_age handles past / present / future ─────────────────────────

def test_humanise_age_variants():
    now = _NOW
    assert proj._humanise_age(None, now) is None
    assert proj._humanise_age(now - timedelta(seconds=30), now).endswith("s ago")
    assert proj._humanise_age(now - timedelta(minutes=5), now) == "5 min ago"
    assert proj._humanise_age(now - timedelta(hours=2, minutes=14), now) == "2h 14m ago"
    assert proj._humanise_age(now + timedelta(hours=2, minutes=14), now) == "in 2h 14m"
    assert proj._humanise_age(now - timedelta(days=3), now).endswith("d ago")
