"""
test_active_shipment_monitor.py — periodic shipment sweeper.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))


def _settings(tmp_path: Path):
    class S:
        storage_root = tmp_path
    return S()


def _write_audit(tmp_path: Path, batch_id: str, **fields) -> Path:
    p = tmp_path / "outputs" / batch_id / "audit.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    base = {"batch_id": batch_id, "tracking_no": fields.get("awb", "1000000000"),
            "awb": fields.get("awb", "1000000000"),
            "clearance_status": "awaiting_dhl_customs_email"}
    base.update(fields)
    p.write_text(json.dumps(base), encoding="utf-8")
    return p


# ── Active vs terminal classification ────────────────────────────────────────

def test_skips_terminal_shipments(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m
    monkeypatch.setattr(m, "settings", _settings(tmp_path))
    # Terminal: agency sent + verified
    _write_audit(tmp_path, "B_TERM", awb="111",
                 clearance_status="agency_email_sent",
                 agency_reply_package={"send_verified": True})
    # Active: still awaiting DHL email
    _write_audit(tmp_path, "B_ACTIVE", awb="222",
                 clearance_status="awaiting_dhl_customs_email")
    out = m.scan_active_shipments()
    batch_ids = [a["batch_id"] for a in out["actions"]]
    assert "B_ACTIVE" in batch_ids
    assert "B_TERM" not in batch_ids


def test_force_includes_terminal(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m
    monkeypatch.setattr(m, "settings", _settings(tmp_path))
    _write_audit(tmp_path, "B_TERM", awb="111",
                 clearance_status="agency_email_sent",
                 agency_reply_package={"send_verified": True})
    out = m.scan_active_shipments(force=True)
    assert any(a["batch_id"] == "B_TERM" for a in out["actions"])


# ── Cache application: rank guard prevents downgrade ─────────────────────────

def test_cache_advance_from_awaiting_to_dhl_email_received(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m
    from app.services import email_intelligence_store as ei
    monkeypatch.setattr(m,  "settings", _settings(tmp_path))
    monkeypatch.setattr(ei, "settings", _settings(tmp_path))

    audit_path = _write_audit(tmp_path, "B_ADV", awb="888",
                              clearance_status="awaiting_dhl_customs_email")
    # Seed cache with verified DHL email evidence
    ei.save_email_scan_result({
        "awb":     "888",
        "matched": 1,
        "derived_events": [
            {"event": "dhl_customs_email_received",
             "source_email_from": "odprawacelna@dhl.com",
             "source_email_subject": "Agencja Celna DHL - przesyłka numer: 888",
             "ticket": "T#TESTONE",
             "timestamp": "2026-04-29T04:46:00Z",
             "confidence": "high"},
        ],
    }, audit={"batch_id": "B_ADV"})

    out = m.scan_active_shipments()
    audit_after = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit_after["clearance_status"] == "dhl_email_received"
    assert audit_after["dhl_email"]["ticket"] == "T#TESTONE"
    assert audit_after["dhl_ticket"] == "T#TESTONE"
    # Action summary reflects the apply
    a = next(a for a in out["actions"] if a["batch_id"] == "B_ADV")
    assert a["applied_cache"]["wrote_dhl_email"] is True


def test_cache_does_not_downgrade_advanced_status(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m
    from app.services import email_intelligence_store as ei
    monkeypatch.setattr(m,  "settings", _settings(tmp_path))
    monkeypatch.setattr(ei, "settings", _settings(tmp_path))

    audit_path = _write_audit(tmp_path, "B_NODOWN", awb="999",
                              clearance_status="polish_description_generated")
    ei.save_email_scan_result({
        "awb":     "999",
        "matched": 1,
        "derived_events": [
            {"event": "dhl_customs_email_received",
             "source_email_from": "odprawacelna@dhl.com",
             "ticket": "T#X", "timestamp": "2026-04-29T04:46:00Z"},
        ],
    }, audit={"batch_id": "B_NODOWN"})

    m.scan_active_shipments()
    audit_after = json.loads(audit_path.read_text(encoding="utf-8"))
    # Status MUST stay at polish_description_generated (rank 3 > dhl_email_received rank 2)
    assert audit_after["clearance_status"] == "polish_description_generated"


# ── Duplicate-task protection (cooldown) ─────────────────────────────────────

def test_cooldown_reuses_recent_task(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m
    from app.services import ai_bridge as ab
    monkeypatch.setattr(m,  "settings", _settings(tmp_path))
    monkeypatch.setattr(ab, "settings", _settings(tmp_path))

    _write_audit(tmp_path, "B_REUSE", awb="555",
                 clearance_status="awaiting_dhl_customs_email")
    # First sweep dispatches a task
    out1 = m.scan_active_shipments()
    a1 = next(a for a in out1["actions"] if a["batch_id"] == "B_REUSE")
    assert a1.get("dispatched_task")

    # Second sweep reuses (within cooldown)
    out2 = m.scan_active_shipments()
    a2 = next(a for a in out2["actions"] if a["batch_id"] == "B_REUSE")
    assert a2.get("reused_task") == a1["dispatched_task"]
    assert "dispatched_task" not in a2


# ── SLA rules ────────────────────────────────────────────────────────────────

def test_warsaw_dhl_email_overdue_after_6h(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m
    monkeypatch.setattr(m, "settings", _settings(tmp_path))
    long_ago = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
    _write_audit(tmp_path, "B_SLA", awb="333",
                 clearance_status="awaiting_dhl_customs_email",
                 tracking={"last_location": "WARSAW - PL", "last_update": long_ago})
    out = m.scan_active_shipments()
    a = next(a for a in out["actions"] if a["batch_id"] == "B_SLA")
    assert a["sla"]["dhl_email_overdue"] is True


def test_high_value_required_actions_after_dhl_email(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m
    monkeypatch.setattr(m, "settings", _settings(tmp_path))
    _write_audit(tmp_path, "B_HV", awb="444",
                 clearance_status="dhl_email_received",
                 clearance_decision={"total_value_usd": 10366,
                                     "clearance_path": "external_agency_clearance"},
                 dhl_email={"received": True, "received_at":
                            (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()})
    out = m.scan_active_shipments()
    a = next(a for a in out["actions"] if a["batch_id"] == "B_HV")
    assert a["sla"]["high_value"] is True
    assert "generate_polish_description" in a["sla"]["required_actions"]
    assert "build_agency_package"        in a["sla"]["required_actions"]


# ── No financial fields touched ──────────────────────────────────────────────

def test_monitor_does_not_modify_financial_fields(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m
    from app.services import email_intelligence_store as ei
    monkeypatch.setattr(m,  "settings", _settings(tmp_path))
    monkeypatch.setattr(ei, "settings", _settings(tmp_path))

    audit_path = _write_audit(tmp_path, "B_FIN", awb="666",
                              clearance_status="awaiting_dhl_customs_email",
                              invoice_totals={"total_cif_usd": 12345.67},
                              clearance_decision={"total_value_usd": 12345.67})
    ei.save_email_scan_result({
        "awb": "666", "matched": 1,
        "derived_events": [
            {"event": "dhl_customs_email_received",
             "source_email_from": "odprawacelna@dhl.com",
             "ticket": "T#FIN", "timestamp": "2026-04-29T04:46:00Z"},
        ],
    }, audit={"batch_id": "B_FIN"})

    m.scan_active_shipments()
    audit_after = json.loads(audit_path.read_text(encoding="utf-8"))
    # Financial fields untouched
    assert audit_after["invoice_totals"]["total_cif_usd"] == 12345.67
    assert audit_after["clearance_decision"]["total_value_usd"] == 12345.67
