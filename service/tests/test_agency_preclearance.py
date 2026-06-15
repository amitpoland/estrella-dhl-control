"""
test_agency_preclearance.py — Outgoing Estrella→agency pre-clearance handling.

The bug being fixed: an outgoing email from Poland Import → Ganther/ACS asking
them to pre-arrange customs clearance is part of the workflow chain even though
no DHL email has arrived yet. The system must:
  - classify it as agency_preclearance_request (not 'unknown')
  - persist agency_preclearance into audit
  - NOT set dhl_email_received
  - NOT advance clearance_status
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))


# ── Template + allowed-writes ────────────────────────────────────────────────

def test_template_includes_agency_preclearance_classification():
    from app.services.ai_bridge import TASK_TEMPLATES
    instr = TASK_TEMPLATES["email_scan"]["instructions"]
    assert "agency_preclearance_request" in instr
    assert "agency_acknowledgement" in instr
    assert "ganther_forward" in instr
    assert "outgoing_clearance_request" in instr


def test_template_maps_classification_to_derived_events():
    from app.services.ai_bridge import TASK_TEMPLATES
    instr = TASK_TEMPLATES["email_scan"]["instructions"]
    assert "agency_preclearance_sent" in instr
    assert "agency_acknowledged" in instr


def test_template_includes_wait_for_arrival_action():
    from app.services.ai_bridge import TASK_TEMPLATES
    instr = TASK_TEMPLATES["email_scan"]["instructions"]
    assert "wait_for_arrival_and_dsk" in instr


def test_allowed_writes_includes_agency_preclearance():
    from app.services.ai_bridge import _ALLOWED_WRITES
    assert "agency_preclearance" in _ALLOWED_WRITES["email_scan"]


# ── Import behavior ──────────────────────────────────────────────────────────

def _setup_audit(tmp_path: Path, batch_id: str, status: str = "awaiting_dhl_customs_email"):
    audit_path = tmp_path / "outputs" / batch_id / "audit.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit = {"batch_id": batch_id, "tracking_no": "1012178215",
             "clearance_status": status}
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    return audit_path, audit


def test_import_with_agency_preclearance_writes_audit_field(tmp_path, monkeypatch):
    """Cowork result with agency_preclearance top-level dict must apply directly."""
    from app.services import ai_bridge as ab
    monkeypatch.setattr(ab, "settings",
        type("S", (), {"storage_root": tmp_path})())

    audit_path, audit = _setup_audit(tmp_path, "TEST_PRECLEAR_1")
    task = ab.create_task(batch_id="TEST_PRECLEAR_1", task_type="email_scan",
                          payload={"awb": "1012178215"})

    result_data = {
        "email_scan_results": {
            "awb":     "1012178215",
            "matched": 2,
            "derived_events": [
                {"event": "agency_preclearance_sent",
                 "source_email_from":    "import@estrellajewels.eu",
                 "source_email_subject": "Request for Custom Clearance Awb- 1012178215",
                 "timestamp": "2026-04-28T13:38:00Z",
                 "confidence": "high"},
            ],
            "recommended_next_action": "wait_for_arrival_and_dsk",
        },
        "agency_preclearance": {
            "source":  "ai_bridge_cowork",
            "sent_at": "2026-04-28T13:38:00Z",
            "subject": "Request for Custom Clearance Awb- 1012178215",
            "to":      "roman@acspedycja.pl, ciagarlak@ganther.com.pl",
            "cc":      "account@estrellajewels.eu",
        },
    }
    audit_now = json.loads(audit_path.read_text(encoding="utf-8"))
    outcome = ab.import_result(
        task_id=task["task_id"],
        result={"task_id": task["task_id"], "result_data": result_data},
        audit=audit_now, audit_path=audit_path,
    )
    assert outcome["ok"] is True
    after = json.loads(audit_path.read_text(encoding="utf-8"))
    assert after["agency_preclearance"]["source"] == "ai_bridge_cowork"
    assert "1012178215" in after["agency_preclearance"]["subject"]


def test_preclearance_does_NOT_advance_clearance_status(tmp_path, monkeypatch):
    """agency_preclearance_sent is NOT a DHL email — must NOT advance status."""
    from app.services import ai_bridge as ab
    monkeypatch.setattr(ab, "settings",
        type("S", (), {"storage_root": tmp_path})())

    audit_path, _ = _setup_audit(tmp_path, "TEST_PRECLEAR_2",
                                 status="awaiting_dhl_customs_email")
    task = ab.create_task(batch_id="TEST_PRECLEAR_2", task_type="email_scan",
                          payload={"awb": "1012178215"})

    result_data = {
        "email_scan_results": {
            "awb":     "1012178215",
            "matched": 1,
            "derived_events": [
                {"event": "agency_preclearance_sent",
                 "source_email_from": "import@estrellajewels.eu",
                 "timestamp": "2026-04-28T13:38:00Z"},
                # Critically: NO dhl_customs_email_received in this scan
            ],
            "recommended_next_action": "wait_for_arrival_and_dsk",
        },
    }
    audit_now = json.loads(audit_path.read_text(encoding="utf-8"))
    ab.import_result(
        task_id=task["task_id"],
        result={"task_id": task["task_id"], "result_data": result_data},
        audit=audit_now, audit_path=audit_path,
    )
    after = json.loads(audit_path.read_text(encoding="utf-8"))
    # Status MUST remain at awaiting_dhl_customs_email — pre-clearance is not
    # the same thing as the DHL customs email
    assert after["clearance_status"] == "awaiting_dhl_customs_email"
    # And dhl_email must NOT have been auto-applied
    assert "dhl_email" not in after or not after.get("dhl_email", {}).get("received")


# ── UI: pending state must not show "0 matched" as final ─────────────────────

def test_dashboard_pending_label_not_zero_matched():
    """Dashboard must render 'Cowork search pending' for ai_bridge_pending,
    not 'Scanned 0 · 0 matched' (which implies a completed zero-result scan)."""
    # Atlas-V2 relocated the Cowork-pending label into shipment-detail.html.
    src = (Path(__file__).resolve().parents[1] / "app" / "static" / "shipment-detail.html").read_text(encoding="utf-8")
    # The pending branch must reference both the Cowork-pending message and
    # be conditional on scan_method === 'ai_bridge_pending'
    assert "Cowork search pending" in src
    assert "ai_bridge_pending" in src
    # The conditional flag _isPending must drive the label switch
    assert "_isPending" in src
