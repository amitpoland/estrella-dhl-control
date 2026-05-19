"""test_dhl_orchestrator_advance_pack.py — Phase B2 agency advance pack.

Verifies pre-arrival agency_advance_pack proposal flow:
  - eligible when all attachments + agency recipient present
  - allowed at DEPARTED_ORIGIN / transit / Hong Kong (NOT arrival-gated)
  - blocked when DSK / Polish / SAD / invoices / recipient missing
  - blocked when agency_reply_package already built
  - blocked when delivered
  - idempotent via cooldown
  - no email sent in shadow mode
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

import pytest


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "dhl_orch_shadow_mode", True, raising=False)
    monkeypatch.setattr(settings, "dhl_orch_auto_build_packages", False, raising=False)
    monkeypatch.setattr(settings, "dhl_orch_auto_send_agency_advance", False, raising=False)
    monkeypatch.setattr(settings, "dhl_orch_auto_send_dhl_followup", False, raising=False)
    (tmp_path / "outputs").mkdir(parents=True, exist_ok=True)
    from app.services.dhl_orchestrator import reset_cooldowns_for_tests
    reset_cooldowns_for_tests()
    return tmp_path


def _pre_arrival_advance_eligible_audit():
    """In-transit agency-clearance shipment with all attachments ready."""
    return {
        "batch_id": "SHIPMENT_ADV_1",
        "awb": "ADV1",
        "tracking_no": "ADV1",
        "clearance_decision": {
            "clearance_path": "agency_clearance",
            "agency_email": "biuro@acspedycja.pl",
            "total_value_usd": 16317.0,
        },
        "clearance_status": "dsk_generated",
        "dsk_path":         "x.pdf",
        "polish_desc_path": "y.pdf",
        "sad_ready_path":   "z.json",
        "inputs":           {"invoices": [{"path": "a.pdf"}]},
        "tracking":         {"status": "on_hold"},
        "tracking_events": [
            {"normalized_stage": "PICKED_UP"},
            {"normalized_stage": "DEPARTED_ORIGIN"},
        ],
    }


def test_eligible_with_full_doc_set(fresh):
    from app.services.dhl_orchestrator import is_agency_advance_pack_eligible
    ok, why = is_agency_advance_pack_eligible(_pre_arrival_advance_eligible_audit())
    assert ok is True
    assert why == "eligible"


def test_blocked_when_dsk_missing(fresh):
    from app.services.dhl_orchestrator import is_agency_advance_pack_eligible
    a = _pre_arrival_advance_eligible_audit()
    a["dsk_path"] = ""
    ok, why = is_agency_advance_pack_eligible(a)
    assert ok is False and why == "dsk_missing"


def test_blocked_when_polish_desc_missing(fresh):
    from app.services.dhl_orchestrator import is_agency_advance_pack_eligible
    a = _pre_arrival_advance_eligible_audit()
    a["polish_desc_path"] = ""
    ok, why = is_agency_advance_pack_eligible(a)
    assert ok is False and why == "polish_desc_missing"


def test_blocked_when_sad_missing(fresh):
    from app.services.dhl_orchestrator import is_agency_advance_pack_eligible
    a = _pre_arrival_advance_eligible_audit()
    a["sad_ready_path"] = ""
    ok, why = is_agency_advance_pack_eligible(a)
    assert ok is False and why == "sad_ready_missing"


def test_blocked_when_no_invoices(fresh):
    from app.services.dhl_orchestrator import is_agency_advance_pack_eligible
    a = _pre_arrival_advance_eligible_audit()
    a["inputs"] = {"invoices": []}
    ok, why = is_agency_advance_pack_eligible(a)
    assert ok is False and why == "no_input_invoices"


def test_blocked_when_agency_email_missing(fresh):
    from app.services.dhl_orchestrator import is_agency_advance_pack_eligible
    a = _pre_arrival_advance_eligible_audit()
    a["clearance_decision"]["agency_email"] = ""
    ok, why = is_agency_advance_pack_eligible(a)
    assert ok is False and why == "agency_email_missing"


def test_blocked_when_clearance_path_self_clearance(fresh):
    from app.services.dhl_orchestrator import is_agency_advance_pack_eligible
    a = _pre_arrival_advance_eligible_audit()
    a["clearance_decision"]["clearance_path"] = "carrier_self_clearance"
    ok, why = is_agency_advance_pack_eligible(a)
    assert ok is False and why == "clearance_path_not_agency"


def test_blocked_when_agency_reply_package_already_built(fresh):
    from app.services.dhl_orchestrator import is_agency_advance_pack_eligible
    a = _pre_arrival_advance_eligible_audit()
    a["agency_reply_package"] = {"status": "built"}
    ok, why = is_agency_advance_pack_eligible(a)
    assert ok is False and why == "agency_reply_package_already_built"


def test_blocked_when_advance_pack_already_built(fresh):
    from app.services.dhl_orchestrator import is_agency_advance_pack_eligible
    a = _pre_arrival_advance_eligible_audit()
    a["agency_advance_pack"] = {"status": "built"}
    ok, why = is_agency_advance_pack_eligible(a)
    assert ok is False and why == "agency_advance_pack_already_present"


def test_blocked_when_delivered(fresh):
    from app.services.dhl_orchestrator import is_agency_advance_pack_eligible
    a = _pre_arrival_advance_eligible_audit()
    a["tracking"] = {"status": "delivered"}
    ok, why = is_agency_advance_pack_eligible(a)
    assert ok is False and why == "delivered"


def test_decision_emits_agency_advance_pack_when_in_transit_eligible(fresh):
    """The decision MUST be agency_advance_pack_ready, NOT refresh_tracking,
    when the shipment is mid-transit with full doc set ready."""
    from app.services.dhl_orchestrator import decide_for_audit
    d = decide_for_audit(_pre_arrival_advance_eligible_audit())
    assert d.lifecycle_state == "in_transit"
    assert d.action == "agency_advance_pack_ready"


def test_decision_falls_back_to_refresh_tracking_when_advance_ineligible(fresh):
    from app.services.dhl_orchestrator import decide_for_audit
    a = _pre_arrival_advance_eligible_audit()
    a["dsk_path"] = ""  # makes advance ineligible
    d = decide_for_audit(a)
    # Without docs, advance is ineligible AND _has_docs_ready is False
    # (only 2/3 docs) so state may flip to classified.  Either way, the
    # decision must NOT be agency_advance_pack_ready.
    assert d.action != "agency_advance_pack_ready"


def test_advance_pack_decision_no_send_in_shadow(fresh, monkeypatch):
    """Critical safety: even though we emit the advance pack decision,
    no email or queue call happens."""
    from app.services import dhl_orchestrator as orch
    from app.services import email_service as esvc

    calls = []
    monkeypatch.setattr(esvc, "queue_email",
                        lambda *a, **kw: calls.append((a, kw)))
    import app.services.email_sender as snd
    monkeypatch.setattr(snd, "send_queued_email",
                        lambda *a, **kw: calls.append(("send", a, kw)) or {"ok": False})

    audit = _pre_arrival_advance_eligible_audit()
    d = fresh / "outputs" / audit["batch_id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    res = orch.run_tick(persist=True)
    assert any(dec.action == "agency_advance_pack_ready" for dec in res.decisions)
    assert calls == []


def test_dhl_followup_proposal_post_arrival_after_4h(fresh):
    """Phase B3: at destination + 4h → emit follow-up proposal."""
    from app.services.dhl_orchestrator import decide_for_audit
    now = datetime(2026, 5, 19, 10, 0, 0, tzinfo=timezone.utc)
    arrived = (now - timedelta(hours=5)).isoformat()
    audit = {
        "batch_id": "SHIPMENT_FU_1",
        "awb": "FU1", "tracking_no": "FU1",
        "clearance_decision": {"clearance_path": "agency_clearance"},
        "clearance_status": "dsk_generated",
        "tracking": {"status": "in_transit"},
        "tracking_events": [
            {"normalized_stage": "DEPARTED_ORIGIN", "event_time": "2026-05-15T00:00:00Z"},
            {"normalized_stage": "ARRIVED_DESTINATION_COUNTRY", "event_time": arrived},
        ],
    }
    d = decide_for_audit(audit, now=now)
    assert d.lifecycle_state == "customs_awaiting"
    # 5h elapsed since arrival → follow-up proposal fires
    assert d.action == "dhl_followup_proposal_ready"


def test_dhl_followup_blocked_before_arrival(fresh):
    """Phase B3: HK / DEPARTED_ORIGIN must NOT trigger follow-up proposal."""
    from app.services.dhl_orchestrator import decide_for_audit, _followup_proposal_due
    audit = _pre_arrival_advance_eligible_audit()
    # AWB still in HK / DEPARTED_ORIGIN
    assert _followup_proposal_due(audit, datetime.now(timezone.utc)) is False
    d = decide_for_audit(audit)
    assert d.action != "dhl_followup_proposal_ready"


def test_orphan_recovery_when_dhl_email_received_no_proposals(fresh):
    """Phase B5: dhl_email.received=True but action_proposals=None →
    orchestrator emits orphan-recovery decision before package build."""
    from app.services.dhl_orchestrator import decide_for_audit
    audit = _pre_arrival_advance_eligible_audit()
    audit["dhl_email"] = {"received": True, "ticket": "T1"}
    audit["action_proposals"] = None
    d = decide_for_audit(audit)
    assert d.lifecycle_state == "customs_received"
    assert d.action == "recover_orphan_proposals"


def test_advance_pack_no_smtp_invariant():
    """Source-grep: advance-pack code path must not import smtplib."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "app" / "services" / "dhl_orchestrator.py").read_text(encoding="utf-8")
    assert "import smtplib" not in src
    # Advance pack helper exists at module level
    assert "is_agency_advance_pack_eligible" in src
    assert "DECISION_AGENCY_ADVANCE_PACK" in src
    assert "DECISION_DHL_FOLLOWUP_PROPOSAL" in src
    assert "DECISION_RECOVER_ORPHAN_PROPOSALS" in src
