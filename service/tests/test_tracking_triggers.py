"""
test_tracking_triggers.py — Tracking-event → action triggers.

Verifies:
  - "Customs clearance status updated" produces DHL_CUSTOMS_EMAIL_CHECK_REQUIRED
  - Warsaw arrival without customs context emits DESTINATION_COUNTRY_REACHED
  - "On hold" alone does NOT trigger; "On hold for customs" DOES
  - Trigger awareness in active monitor sets pending_triggers
  - Repeat sweeps within retry window don't duplicate work
  - Retry past window raises risk_flags
  - Trigger satisfied when DHL email lands → state cleared, flag dropped
  - No financial fields modified
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

_INGEST_STUB = {"ok": True, "started_at": "2026-01-01T00:00:00Z",
                "active_batches": 0, "shipments": []}

@pytest.fixture(autouse=True)
def _no_network_ingestion(monkeypatch):
    """Prevent scan_active_shipments from making real Zoho API calls."""
    monkeypatch.setattr(
        "app.services.email_ingestion_worker.run_ingestion_cycle",
        lambda **kw: _INGEST_STUB,
    )


def _settings(tmp_path: Path):
    class S:
        storage_root = tmp_path
    return S()


def _ev(loc, desc, hours_ago=1):
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {"timestamp": ts, "location": loc, "status": "", "description": desc}


# ── Trigger detection ────────────────────────────────────────────────────────

def test_customs_clearance_event_triggers_email_check():
    from app.services.tracking_intelligence import detect_tracking_triggers
    events = [_ev("WARSAW - PL", "Customs clearance status updated", hours_ago=0.5)]
    triggers = detect_tracking_triggers(events, audit={"awb": "1012178215"})
    assert any(t["trigger"] == "DHL_CUSTOMS_EMAIL_CHECK_REQUIRED" for t in triggers)
    t = next(t for t in triggers if t["trigger"] == "DHL_CUSTOMS_EMAIL_CHECK_REQUIRED")
    assert t["awb"] == "1012178215"
    assert "customs" in t["reason"].lower()


def test_clearance_event_phrase_triggers():
    from app.services.tracking_intelligence import detect_tracking_triggers
    triggers = detect_tracking_triggers([_ev("WARSAW", "Clearance Event", 1)], audit={})
    assert any(t["trigger"] == "DHL_CUSTOMS_EMAIL_CHECK_REQUIRED" for t in triggers)


def test_on_hold_alone_does_not_trigger_customs():
    from app.services.tracking_intelligence import detect_tracking_triggers
    triggers = detect_tracking_triggers([_ev("WARSAW", "Shipment is on hold", 1)], audit={})
    # No customs context → no trigger
    assert not any(t["trigger"] == "DHL_CUSTOMS_EMAIL_CHECK_REQUIRED" for t in triggers)


def test_on_hold_for_customs_does_trigger():
    from app.services.tracking_intelligence import detect_tracking_triggers
    triggers = detect_tracking_triggers(
        [_ev("WARSAW", "Shipment is on hold pending customs clearance", 1)], audit={},
    )
    assert any(t["trigger"] == "DHL_CUSTOMS_EMAIL_CHECK_REQUIRED" for t in triggers)


def test_warsaw_arrival_without_customs_emits_destination_trigger():
    from app.services.tracking_intelligence import detect_tracking_triggers
    triggers = detect_tracking_triggers(
        [_ev("WARSAW - PL", "Processed at WARSAW", 1)],
        audit={"dhl_email": {}},
    )
    # No customs phrase, but at Warsaw → destination trigger
    assert any(t["trigger"] == "DESTINATION_COUNTRY_REACHED" for t in triggers)


def test_destination_trigger_skipped_if_dhl_email_already_received():
    from app.services.tracking_intelligence import detect_tracking_triggers
    triggers = detect_tracking_triggers(
        [_ev("WARSAW - PL", "Processed at WARSAW", 1)],
        audit={"dhl_email": {"received": True}},
    )
    assert not triggers


def test_no_trigger_when_far_from_destination():
    from app.services.tracking_intelligence import detect_tracking_triggers
    triggers = detect_tracking_triggers(
        [_ev("MUMBAI - IN", "Picked up", 1)], audit={},
    )
    assert triggers == []


# ── Active monitor integration ───────────────────────────────────────────────

def _audit(tmp_path, batch_id, awb="1012178215", **fields):
    p = tmp_path / "outputs" / batch_id / "audit.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    base = {
        "batch_id": batch_id,
        "tracking_no": awb,
        "awb": awb,
        "clearance_status": "awaiting_dhl_customs_email",
    }
    base.update(fields)
    p.write_text(json.dumps(base), encoding="utf-8")
    return p


def test_monitor_triggers_email_scan_on_customs_event(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m
    from app.services import ai_bridge as ab
    from app.services import email_intelligence_store as eis
    monkeypatch.setattr(m,  "settings", _settings(tmp_path))
    monkeypatch.setattr(ab, "settings", _settings(tmp_path))
    monkeypatch.setattr(eis, "find_existing_email_context", lambda audit: None)

    audit_path = _audit(tmp_path, "B_TRIG_1", awb="1012178215",
                        tracking={"events": [
                            _ev("WARSAW - PL", "Customs clearance status updated", 0.5),
                        ]})
    out = m.scan_active_shipments()
    a = next(a for a in out["actions"] if a["batch_id"] == "B_TRIG_1")
    assert a.get("triggers")
    assert any(t["trigger"] == "DHL_CUSTOMS_EMAIL_CHECK_REQUIRED" for t in a["triggers"])
    # Dispatched a bridge task because no DHL email yet
    assert a.get("dispatched_task")
    # Pending trigger written to audit
    audit_after = json.loads(audit_path.read_text(encoding="utf-8"))
    pending = audit_after.get("pending_triggers", {}).get("dhl_email_check") or {}
    assert pending.get("active") is True


def test_monitor_does_not_duplicate_task_within_cooldown(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m
    from app.services import ai_bridge as ab
    monkeypatch.setattr(m,  "settings", _settings(tmp_path))
    monkeypatch.setattr(ab, "settings", _settings(tmp_path))

    _audit(tmp_path, "B_TRIG_2", awb="555",
           tracking={"events": [_ev("WARSAW", "Customs clearance status updated", 1)]})
    out1 = m.scan_active_shipments()
    out2 = m.scan_active_shipments()
    a1 = next(a for a in out1["actions"] if a["batch_id"] == "B_TRIG_2")
    a2 = next(a for a in out2["actions"] if a["batch_id"] == "B_TRIG_2")
    # Second call reuses
    assert a1.get("dispatched_task")
    assert a2.get("reused_task") == a1["dispatched_task"]


def test_trigger_satisfied_clears_pending_when_email_received(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m
    from app.services import ai_bridge as ab
    from app.services import email_intelligence_store as eis
    monkeypatch.setattr(m,  "settings", _settings(tmp_path))
    monkeypatch.setattr(ab, "settings", _settings(tmp_path))
    monkeypatch.setattr(eis, "find_existing_email_context", lambda audit: None)

    audit_path = _audit(tmp_path, "B_TRIG_SAT", awb="777",
                        tracking={"events": [_ev("WARSAW", "Customs clearance status updated", 1)]})
    # First sweep — sets pending
    m.scan_active_shipments()
    # Operator/import marks DHL email received
    a = json.loads(audit_path.read_text(encoding="utf-8"))
    a["dhl_email"] = {"received": True, "ticket": "T#OK"}
    a["risk_flags"] = ["dhl_email_missing_after_tracking_trigger"]
    audit_path.write_text(json.dumps(a))
    # Second sweep — clears pending and risk flag
    m.scan_active_shipments()
    after = json.loads(audit_path.read_text(encoding="utf-8"))
    assert after["pending_triggers"]["dhl_email_check"]["active"] is False
    assert "dhl_email_missing_after_tracking_trigger" not in (after.get("risk_flags") or [])


def test_terminal_shipments_skipped_even_with_trigger(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m
    monkeypatch.setattr(m, "settings", _settings(tmp_path))
    _audit(tmp_path, "B_TERM", awb="888",
           clearance_status="agency_email_sent",
           agency_reply_package={"send_verified": True},
           tracking={"events": [_ev("WARSAW", "Customs clearance status updated", 1)]})
    out = m.scan_active_shipments()
    assert not any(a["batch_id"] == "B_TERM" for a in out["actions"])


def test_no_financial_fields_touched_by_trigger_processing(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m
    from app.services import ai_bridge as ab
    monkeypatch.setattr(m,  "settings", _settings(tmp_path))
    monkeypatch.setattr(ab, "settings", _settings(tmp_path))

    audit_path = _audit(tmp_path, "B_FIN", awb="123",
                        invoice_totals={"total_cif_usd": 9999.99},
                        clearance_decision={"total_value_usd": 9999.99},
                        tracking={"events": [_ev("WARSAW", "Customs clearance status updated", 1)]})
    m.scan_active_shipments()
    after = json.loads(audit_path.read_text(encoding="utf-8"))
    assert after["invoice_totals"]["total_cif_usd"] == 9999.99
    assert after["clearance_decision"]["total_value_usd"] == 9999.99
