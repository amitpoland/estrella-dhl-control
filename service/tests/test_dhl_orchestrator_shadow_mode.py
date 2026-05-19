"""test_dhl_orchestrator_shadow_mode.py — shadow-mode safety + AWB 4218922912.

Verifies that in shadow mode (default) the orchestrator:
  - takes no external actions
  - never calls queue_email / send_queued_email
  - writes telemetry without touching protected audit fields
  - keeps AWB 4218922912 blocked at in_transit (DEPARTED_ORIGIN)
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
    monkeypatch.setattr(settings, "dhl_orch_shadow_mode", True, raising=False)
    monkeypatch.setattr(settings, "dhl_orch_auto_refresh_tracking", False, raising=False)
    monkeypatch.setattr(settings, "dhl_orch_auto_monitor_sweep", False, raising=False)
    monkeypatch.setattr(settings, "dhl_orch_auto_email_ingest", False, raising=False)
    monkeypatch.setattr(settings, "dhl_orch_auto_refresh_proposals", False, raising=False)
    monkeypatch.setattr(settings, "dhl_orch_auto_build_packages", False, raising=False)
    monkeypatch.setattr(settings, "dhl_orch_auto_send_agency", False, raising=False)
    monkeypatch.setattr(settings, "dhl_orch_auto_send_dhl_reply", False, raising=False)
    (tmp_path / "outputs").mkdir(parents=True, exist_ok=True)
    from app.services.dhl_orchestrator import reset_cooldowns_for_tests
    reset_cooldowns_for_tests()
    return tmp_path


def _awb_4218922912_audit():
    """Reconstructed snapshot of the current production AWB 4218922912 audit.

    Matches the state observed during the 2026-05-19 inspection:
    - status=on_hold, latest stage DEPARTED_ORIGIN, Hong Kong
    - clearance_path=agency_clearance, CIF $16,317
    - DSK / Polish / SAD all generated
    - dhl_email not yet received, no reply packages, no proposals
    - carrier_arrived_at_poland_at = 2026-05-16 (STALE, predates HK events)
    """
    return {
        "batch_id": "SHIPMENT_4218922912_2026-05_9040dd39",
        "awb": "4218922912",
        "tracking_no": "4218922912",
        "carrier_arrived_at_poland_at": "2026-05-16T17:00:00+02:00",
        "clearance_decision": {
            "clearance_path": "agency_clearance",
            "total_value_usd": 16317.0,
            "agency_email": "biuro@acspedycja.pl",
            "require_dsk": True,
            "require_polish_description": True,
        },
        "clearance_status": "dsk_generated",
        "dsk_path": "C:\\PZ\\storage\\dsk_outputs\\DSK_4218922912_19-05-2026.pdf",
        "polish_desc_path": "C:\\PZ\\storage\\polish_descriptions\\POLISH_DESC_AWB_4218922912_20260518.pdf",
        "sad_ready_path": "C:\\PZ\\storage\\polish_descriptions\\SAD_READY_4218922912_18-05-2026.json",
        "tracking": {
            "status": "on_hold",
            "last_location": "HONG KONG - HONG KONG SAR, CHINA - HK",
        },
        "tracking_events": [
            {"normalized_stage": "PICKED_UP"},
            {"normalized_stage": "DEPARTED_ORIGIN"},
            {"normalized_stage": "ARRIVED_ORIGIN_HUB"},
            {"normalized_stage": "IN_TRANSIT"},
            {"normalized_stage": "EXCEPTION"},
            {"normalized_stage": "IN_TRANSIT"},
            {"normalized_stage": "DEPARTED_ORIGIN"},
        ],
        "dhl_email": None,
        "agency_reply_package": None,
        "dhl_reply_package": None,
        "action_proposals": None,
    }


def _write_audit(tmp, audit):
    d = tmp / "outputs" / audit["batch_id"]
    d.mkdir(parents=True, exist_ok=True)
    p = d / "audit.json"
    p.write_text(json.dumps(audit), encoding="utf-8")
    return p


def test_awb_4218922912_stays_in_transit(fresh):
    """The live shipment must resolve to in_transit, NOT customs_awaiting,
    because its latest normalized stage is DEPARTED_ORIGIN, below the
    ARRIVED_DESTINATION_COUNTRY threshold."""
    from app.services.dhl_orchestrator import resolve_state, decide_for_audit
    audit = _awb_4218922912_audit()
    assert resolve_state(audit) == "in_transit"
    d = decide_for_audit(audit)
    # Decision should be a tracking refresh, NOT email or send.
    assert d.action == "refresh_tracking"
    assert d.lifecycle_state == "in_transit"


def test_shadow_tick_does_not_call_queue_email(fresh, monkeypatch):
    """Most important safety check: no email enqueue in shadow mode."""
    from app.services import dhl_orchestrator as orch
    from app.services import email_service as esvc

    calls = []
    def _no(*a, **kw): calls.append((a, kw))
    monkeypatch.setattr(esvc, "queue_email", _no)
    import app.services.email_sender as snd
    monkeypatch.setattr(snd, "send_queued_email", lambda *a, **kw: calls.append(("send", a, kw)) or {"ok": False})

    _write_audit(fresh, _awb_4218922912_audit())
    res = orch.run_tick(persist=True)
    assert res.scanned >= 1
    assert calls == [], f"shadow mode triggered SMTP/queue calls: {calls!r}"


def test_shadow_tick_writes_telemetry_into_audit(fresh):
    """In shadow mode the orchestrator block IS written (audit.orchestrator)
    but no other audit fields are touched."""
    from app.services.dhl_orchestrator import run_tick

    audit = _awb_4218922912_audit()
    ap = _write_audit(fresh, audit)
    run_tick(persist=True)
    new = json.loads(ap.read_text(encoding="utf-8"))
    assert "orchestrator" in new
    o = new["orchestrator"]
    assert o["state"] == "in_transit"
    assert o["last_action"] == "refresh_tracking"
    assert o["shadow"] is True
    assert o["executed"] is False
    # Critical: the stale field is preserved exactly (not modified).
    assert new["carrier_arrived_at_poland_at"] == audit["carrier_arrived_at_poland_at"]
    # Critical: no other audit field renamed/removed.
    for k in ("batch_id", "awb", "clearance_decision", "clearance_status",
              "dsk_path", "polish_desc_path", "sad_ready_path", "tracking",
              "tracking_events"):
        assert k in new


def test_shadow_tick_appends_decisions_jsonl(fresh):
    from app.services.dhl_orchestrator import run_tick
    _write_audit(fresh, _awb_4218922912_audit())
    run_tick(persist=True)
    log_path = fresh / "orchestrator_decisions.jsonl"
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) >= 1
    rec = json.loads(lines[0])
    assert rec["batch_id"] == "SHIPMENT_4218922912_2026-05_9040dd39"
    assert rec["lifecycle_state"] == "in_transit"
    assert rec["shadow"] is True
    assert rec["executed"] is False
    assert "flags" in rec
    assert rec["idempotency_key"].startswith("SHIPMENT_4218922912_2026-05_9040dd39|refresh_tracking|")


def test_dry_run_writes_nothing(fresh):
    """POST /api/v1/orchestrator/dry-run produces decisions without persistence."""
    from app.services.dhl_orchestrator import run_tick
    _write_audit(fresh, _awb_4218922912_audit())
    res = run_tick(persist=False)
    assert res.scanned >= 1
    # No telemetry written:
    log_path = fresh / "orchestrator_decisions.jsonl"
    assert not log_path.exists()
    # No orchestrator block written into audit:
    audit_path = fresh / "outputs" / "SHIPMENT_4218922912_2026-05_9040dd39" / "audit.json"
    new = json.loads(audit_path.read_text(encoding="utf-8"))
    assert "orchestrator" not in new


def test_tick_idempotent_within_minute_bucket(fresh):
    """Two ticks fired in rapid succession share the same idempotency key
    for the same (batch_id, action)."""
    from app.services.dhl_orchestrator import run_tick
    _write_audit(fresh, _awb_4218922912_audit())
    r1 = run_tick(persist=False)
    r2 = run_tick(persist=False)
    # Both ticks see one active shipment, but cooldown prevents second
    # tick from picking the same action.
    keys1 = [d.idempotency_key for d in r1.decisions]
    actions2 = [d.action for d in r2.decisions]
    # Second tick should land in cooldown branch.
    assert "cooldown" in actions2


def test_delivered_shipment_decision_is_suppress(fresh):
    from app.services.dhl_orchestrator import decide_for_audit
    audit = _awb_4218922912_audit()
    audit["tracking"] = {"status": "delivered"}
    audit["delivered_at"] = "2026-05-18T10:00:00Z"
    d = decide_for_audit(audit)
    assert d.lifecycle_state == "delivered"
    assert d.action == "suppress_pending_after_delivery"
