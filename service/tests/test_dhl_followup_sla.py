"""
test_dhl_followup_sla.py — Working-hour-aware DHL follow-up scheduler.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services.dhl_followup_sla import (   # noqa: E402
    POLAND_TZ, WORK_START, WORK_END,
    is_working_time, next_working_time,
    calculate_first_followup_at, calculate_next_followup_at,
    start_followup, stop_followup, record_followup_sent, is_due,
)

_INGEST_STUB = {"ok": True, "started_at": "2026-01-01T00:00:00Z",
                "active_batches": 0, "shipments": []}

@pytest.fixture(autouse=True)
def _no_network_ingestion(monkeypatch):
    """Prevent scan_active_shipments from making real Zoho API calls."""
    monkeypatch.setattr(
        "app.services.email_ingestion_worker.run_ingestion_cycle",
        lambda **kw: _INGEST_STUB,
    )


def _pl(year=2026, month=4, day=29, hour=10, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=POLAND_TZ)


# ── Schedule math ────────────────────────────────────────────────────────────

def test_first_followup_06_30_in_work_hours_after_4h():
    """06:30 trigger → 06:30 + 4h = 10:30 → still in work window."""
    out = calculate_first_followup_at(_pl(hour=6, minute=30))
    assert out.hour == 10 and out.minute == 30
    assert out.day  == 29


def test_first_followup_12_30_pushes_to_next_day():
    """12:30 + 4h = 16:30 → after 16:00 → next day 08:00."""
    out = calculate_first_followup_at(_pl(hour=12, minute=30))
    assert out.day == 30
    assert out.hour == WORK_START.hour and out.minute == WORK_START.minute


def test_first_followup_14_30_pushes_to_next_day():
    """14:30 + 4h = 18:30 → after 16:00 → next day 08:00."""
    out = calculate_first_followup_at(_pl(hour=14, minute=30))
    assert out.day == 30
    assert out.hour == WORK_START.hour


def test_first_followup_09_00_lands_at_13_00():
    """09:00 + 4h = 13:00 → in window."""
    out = calculate_first_followup_at(_pl(hour=9, minute=0))
    assert out.day == 29 and out.hour == 13 and out.minute == 0


def test_weekends_are_active_not_skipped():
    """Saturday trigger should NOT skip to Monday — weekends are active."""
    sat = datetime(2026, 5, 2, 10, 0, tzinfo=POLAND_TZ)   # Saturday
    out = calculate_first_followup_at(sat)
    # 10:00 Sat + 4h = 14:00 Sat → still Saturday in work window
    assert out.weekday() == 5   # Saturday
    assert out.hour == 14


def test_repeat_every_hour_within_window():
    """Sent at 10:00 → next at 11:00."""
    out = calculate_next_followup_at(_pl(hour=10, minute=0))
    assert out.day == 29 and out.hour == 11


def test_repeat_jumps_window_at_end_of_day():
    """Sent at 15:30 → +1h = 16:30 → next day 08:00."""
    out = calculate_next_followup_at(_pl(hour=15, minute=30))
    assert out.day == 30 and out.hour == WORK_START.hour


# ── Lifecycle ────────────────────────────────────────────────────────────────

def test_start_followup_writes_audit_state():
    audit = {}
    state = start_followup(audit, _pl(hour=9), "customs trigger")
    assert state["active"] is True
    assert state["followup_count"] == 0
    assert state["trigger_reason"] == "customs trigger"
    assert audit["dhl_followup"] is state


def test_start_is_idempotent_when_already_active():
    audit = {"dhl_followup": {"active": True, "followup_count": 3}}
    state = start_followup(audit, _pl(), "later")
    assert state["followup_count"] == 3   # unchanged


def test_stop_followup_marks_inactive_with_reason():
    audit = {}
    start_followup(audit, _pl(), "trig")
    stop_followup(audit, "dhl_email_received")
    assert audit["dhl_followup"]["active"] is False
    assert audit["dhl_followup"]["stop_reason"] == "dhl_email_received"
    assert audit["dhl_followup"]["stopped_at"]


def test_record_followup_sent_increments_and_advances():
    audit = {}
    start_followup(audit, _pl(hour=9), "trig")
    record_followup_sent(audit, when=_pl(hour=13))
    state = audit["dhl_followup"]
    assert state["followup_count"]  == 1
    assert state["last_followup_at"]
    # Next = last + 1h working = 14:00
    assert state["next_followup_at"].startswith("2026-04-29T14:00")


def test_is_due_when_now_past_next_followup_at():
    state = {"active": True, "next_followup_at": _pl(hour=10).isoformat()}
    assert is_due(state, now=_pl(hour=11)) is True
    assert is_due(state, now=_pl(hour=9))  is False


def test_is_due_false_when_inactive():
    state = {"active": False, "next_followup_at": _pl(hour=10).isoformat()}
    assert is_due(state, now=_pl(hour=11)) is False


# ── Monitor integration ──────────────────────────────────────────────────────

def _settings(tmp_path: Path):
    class S:
        storage_root = tmp_path
        smtp_host = "smtppro.zoho.in"
        smtp_port = 465
        smtp_user = None
        smtp_password = None
        smtp_use_ssl = True
        mcp_send_max_attachment_bytes = 200_000
    return S()


def _seed_active_batch(tmp_path: Path, batch_id: str, awb: str = "1234567890"):
    batch_dir = tmp_path / "outputs" / batch_id
    inv_dir   = batch_dir / "source" / "invoices"
    awb_dir   = batch_dir / "source" / "awb"
    for d in (inv_dir, awb_dir):
        d.mkdir(parents=True, exist_ok=True)
    (inv_dir / "INV.pdf").write_bytes(b"%PDF inv")
    awb_pdf = awb_dir / f"{awb} AWB.pdf"
    awb_pdf.write_bytes(b"%PDF awb")

    audit = {
        "batch_id":             batch_id,
        "awb":                  awb,
        "tracking_no":          awb,
        "inputs":               {"awb": awb_pdf.name},
        "clearance_status":     "awaiting_dhl_customs_email",
        "clearance_decision":   {"total_value_usd": 5000,
                                 "clearance_path":  "agency_clearance"},
        "tracking": {
            "events": [{
                "timestamp":   datetime.now(POLAND_TZ).isoformat(),
                "location":    "WARSAW - PL",
                "description": "Customs clearance status updated",
                "status":      "",
            }],
        },
    }
    (batch_dir / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return batch_dir


def test_monitor_starts_followup_on_customs_trigger(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m, ai_bridge as ab
    monkeypatch.setattr(m,  "settings", _settings(tmp_path))
    monkeypatch.setattr(ab, "settings", _settings(tmp_path))
    batch_dir = _seed_active_batch(tmp_path, "B_FU_START")
    out = m.scan_active_shipments()
    a = next(a for a in out["actions"] if a["batch_id"] == "B_FU_START")
    assert a.get("dhl_followup", {}).get("started") is True

    audit_after = json.loads((batch_dir / "audit.json").read_text())
    f = audit_after["dhl_followup"]
    assert f["active"] is True
    assert f["trigger_reason"]
    assert f["first_followup_at"]
    assert f["followup_count"] == 0


def test_monitor_stops_followup_when_dhl_email_received(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m, ai_bridge as ab
    monkeypatch.setattr(m,  "settings", _settings(tmp_path))
    monkeypatch.setattr(ab, "settings", _settings(tmp_path))
    batch_dir = _seed_active_batch(tmp_path, "B_FU_STOP")
    # First sweep starts the SLA
    m.scan_active_shipments()
    # DHL email arrives between sweeps
    audit = json.loads((batch_dir / "audit.json").read_text())
    audit["dhl_email"] = {"received": True, "ticket": "T#X"}
    (batch_dir / "audit.json").write_text(json.dumps(audit))
    # Second sweep stops the SLA
    out = m.scan_active_shipments()
    a = next(a for a in out["actions"] if a["batch_id"] == "B_FU_STOP")
    assert a.get("dhl_followup", {}).get("stopped") is True
    audit_after = json.loads((batch_dir / "audit.json").read_text())
    f = audit_after["dhl_followup"]
    assert f["active"] is False
    assert f["stop_reason"] == "dhl_email_received"


def test_terminal_shipment_does_not_start_followup(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m, ai_bridge as ab
    monkeypatch.setattr(m,  "settings", _settings(tmp_path))
    monkeypatch.setattr(ab, "settings", _settings(tmp_path))
    # Terminal shipment is skipped from sweep entirely → no follow-up state
    batch_dir = _seed_active_batch(tmp_path, "B_FU_TERM")
    audit = json.loads((batch_dir / "audit.json").read_text())
    audit["clearance_status"] = "agency_email_sent"
    audit["agency_reply_package"] = {"send_verified": True}
    (batch_dir / "audit.json").write_text(json.dumps(audit))
    m.scan_active_shipments()
    audit_after = json.loads((batch_dir / "audit.json").read_text())
    assert "dhl_followup" not in audit_after


def test_no_financial_fields_modified(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m, ai_bridge as ab
    monkeypatch.setattr(m,  "settings", _settings(tmp_path))
    monkeypatch.setattr(ab, "settings", _settings(tmp_path))
    batch_dir = _seed_active_batch(tmp_path, "B_FU_FIN")
    audit = json.loads((batch_dir / "audit.json").read_text())
    audit["invoice_totals"] = {"total_cif_usd": 5000}
    (batch_dir / "audit.json").write_text(json.dumps(audit))
    m.scan_active_shipments()
    after = json.loads((batch_dir / "audit.json").read_text())
    assert after["invoice_totals"]["total_cif_usd"] == 5000
    assert after["clearance_decision"]["total_value_usd"] == 5000


# ── customs_docs_received stop condition ─────────────────────────────────────

def test_followup_stops_when_customs_docs_received(tmp_path, monkeypatch):
    """Active SLA is stopped the sweep after SAD is uploaded (customs_docs.received=True)."""
    from app.services import active_shipment_monitor as m, ai_bridge as ab
    monkeypatch.setattr(m,  "settings", _settings(tmp_path))
    monkeypatch.setattr(ab, "settings", _settings(tmp_path))

    batch_dir = _seed_active_batch(tmp_path, "B_FU_SAD_STOP")
    # Seed: active SLA already running, customs_docs not yet uploaded
    audit = json.loads((batch_dir / "audit.json").read_text())
    audit["dhl_followup"] = {
        "active": True,
        "trigger_reason": "customs_trigger",
        "trigger_time": datetime.now(POLAND_TZ).isoformat(),
        "first_followup_at": datetime.now(POLAND_TZ).isoformat(),
        "next_followup_at": (datetime.now(POLAND_TZ)).isoformat(),
        "followup_count": 1,
        "last_followup_at": None,
        "stopped_at": None,
        "stop_reason": None,
    }
    (batch_dir / "audit.json").write_text(json.dumps(audit))
    # First sweep: SLA active, no customs docs → should send
    # (we're not testing the send here — we're testing the stop)

    # Now upload SAD
    audit = json.loads((batch_dir / "audit.json").read_text())
    audit["customs_docs"] = {"received": True, "received_at": datetime.now(POLAND_TZ).isoformat()}
    (batch_dir / "audit.json").write_text(json.dumps(audit))

    out = m.scan_active_shipments()
    a = next(a for a in out["actions"] if a["batch_id"] == "B_FU_SAD_STOP")
    assert a.get("dhl_followup", {}).get("stopped") is True

    audit_after = json.loads((batch_dir / "audit.json").read_text())
    f = audit_after["dhl_followup"]
    assert f["active"] is False
    assert f["stop_reason"] == "customs_docs_received"


def test_followup_does_not_start_when_customs_docs_received(tmp_path, monkeypatch):
    """SLA must not start when customs_docs.received is already True at trigger time."""
    from app.services import active_shipment_monitor as m, ai_bridge as ab
    monkeypatch.setattr(m,  "settings", _settings(tmp_path))
    monkeypatch.setattr(ab, "settings", _settings(tmp_path))

    batch_dir = _seed_active_batch(tmp_path, "B_FU_SAD_NOSTART")
    audit = json.loads((batch_dir / "audit.json").read_text())
    audit["customs_docs"] = {"received": True, "received_at": datetime.now(POLAND_TZ).isoformat()}
    (batch_dir / "audit.json").write_text(json.dumps(audit))

    m.scan_active_shipments()
    audit_after = json.loads((batch_dir / "audit.json").read_text())
    assert not (audit_after.get("dhl_followup") or {}).get("active")
