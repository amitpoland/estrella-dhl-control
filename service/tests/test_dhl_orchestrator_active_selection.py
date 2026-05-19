"""test_dhl_orchestrator_active_selection.py — active shipment selection rules.

Covers is_active_shipment() — the gate that decides which audits the
orchestrator considers per tick.
"""
from __future__ import annotations

import json
import pathlib

import pytest


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    (tmp_path / "outputs").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _good_audit():
    return {
        "batch_id": "SHIPMENT_X",
        "awb": "AWB1",
        "tracking_no": "AWB1",
        "clearance_decision": {"clearance_path": "agency_clearance", "total_value_usd": 100},
        "clearance_status": "",
        "tracking": {"status": "in_transit"},
        "tracking_events": [],
    }


def test_active_when_all_fields_present(fresh):
    from app.services.dhl_orchestrator import is_active_shipment
    ok, why = is_active_shipment(_good_audit())
    assert ok is True
    assert why == "active"


def test_inactive_when_audit_not_a_dict(fresh):
    from app.services.dhl_orchestrator import is_active_shipment
    ok, why = is_active_shipment(None)
    assert ok is False
    assert why == "audit_malformed"


def test_inactive_when_batch_id_missing(fresh):
    from app.services.dhl_orchestrator import is_active_shipment
    a = _good_audit(); a["batch_id"] = ""
    ok, why = is_active_shipment(a)
    assert ok is False and why == "missing_batch_id"


def test_inactive_when_clearance_decision_missing(fresh):
    from app.services.dhl_orchestrator import is_active_shipment
    a = _good_audit(); a["clearance_decision"] = None
    ok, why = is_active_shipment(a)
    assert ok is False and why == "missing_clearance_decision"


def test_inactive_when_no_awb_or_tracking_no(fresh):
    from app.services.dhl_orchestrator import is_active_shipment
    a = _good_audit(); a["awb"] = ""; a["tracking_no"] = ""
    ok, why = is_active_shipment(a)
    assert ok is False and why == "missing_awb"


def test_inactive_when_delivered_via_tracking_status(fresh):
    from app.services.dhl_orchestrator import is_active_shipment
    a = _good_audit(); a["tracking"] = {"status": "delivered"}
    ok, why = is_active_shipment(a)
    assert ok is False and why == "delivered"


def test_inactive_when_clearance_terminal(fresh):
    from app.services.dhl_orchestrator import is_active_shipment
    a = _good_audit(); a["clearance_status"] = "agency_email_sent"
    ok, why = is_active_shipment(a)
    assert ok is False and why == "clearance_terminal"


def test_run_tick_excludes_delivered_shipments(fresh):
    """Integration: drop two audits on disk, one delivered, one active —
    only one ends up active in the tick result."""
    from app.services.dhl_orchestrator import run_tick

    active = _good_audit(); active["batch_id"] = "SHIPMENT_ACTIVE"
    delivered = _good_audit()
    delivered["batch_id"] = "SHIPMENT_DELIVERED"
    delivered["tracking"] = {"status": "delivered"}

    for a in (active, delivered):
        d = fresh / "outputs" / a["batch_id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "audit.json").write_text(json.dumps(a), encoding="utf-8")

    res = run_tick(persist=False)
    assert res.scanned == 2
    assert res.active == 1


def test_run_tick_survives_malformed_audit(fresh):
    """A corrupted audit.json must not crash the loop."""
    from app.services.dhl_orchestrator import run_tick

    good_d = fresh / "outputs" / "SHIPMENT_OK"
    good_d.mkdir(parents=True, exist_ok=True)
    (good_d / "audit.json").write_text(json.dumps(_good_audit()), encoding="utf-8")

    bad_d = fresh / "outputs" / "SHIPMENT_BROKEN"
    bad_d.mkdir(parents=True, exist_ok=True)
    (bad_d / "audit.json").write_text("{not valid json", encoding="utf-8")

    res = run_tick(persist=False)
    # Scanned counts both files; active counts only the good one.
    assert res.scanned == 2
    assert res.active == 1
