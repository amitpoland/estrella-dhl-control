"""
test_dhl_selfclearance_p0_coordinator.py — coordinator skeleton entrypoints.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services.dhl_clearance_coordinator import (  # noqa: E402
    DhlClearanceCoordinator,
    DispatchInput,
    FollowupTickInput,
    InboundClarificationInput,
    NotImplementedYet,
    SadInboundInput,
    TrackingEventInput,
)


def _audit_path_a():
    return {"clearance_decision": {"clearance_path": "dhl_self_clearance"}}


def _audit_path_b():
    return {"clearance_decision": {"clearance_path": "agency_clearance"}}


def test_dispatch_proactive_raises_not_implemented_yet():
    c = DhlClearanceCoordinator()
    inp = DispatchInput(batch_id="B1", awb="AWB1", audit=_audit_path_a())
    # P2 wires dispatch_proactive (commit chore/dhl-selfclearance-p2-proactive).
    # On default flag state (shadow_mode=True, live_enabled=False, AWB
    # unstable in P0-only world) the coordinator returns a structured
    # result rather than raising NotImplementedYet. The "skipped" reason
    # is either "awb_unstable" (no carrier row present) or "dormant_state"
    # (shadow disabled). Specifically not NotImplementedYet anymore.
    result = c.dispatch_proactive(inp)
    assert isinstance(result, dict)
    assert result.get("status") in {"skipped", "shadow", "sent", "blocked"}


def test_on_tracking_event_raises_not_implemented_yet():
    c = DhlClearanceCoordinator()
    inp = TrackingEventInput(
        batch_id="B1", awb="AWB1", signal_token="poland_arrival",
        signal_at="2026-05-12T10:00:00Z", audit=_audit_path_a(),
    )
    with pytest.raises(NotImplementedYet):
        c.on_tracking_event(inp)


def test_tick_followup_raises_not_implemented_yet():
    c = DhlClearanceCoordinator()
    inp = FollowupTickInput(
        batch_id="B1", awb="AWB1", now_iso="2026-05-12T10:00:00Z",
        audit=_audit_path_a(),
    )
    with pytest.raises(NotImplementedYet):
        c.tick_followup(inp)


def test_on_inbound_clarification_raises_not_implemented_yet():
    c = DhlClearanceCoordinator()
    inp = InboundClarificationInput(
        batch_id="B1", awb="AWB1", thread_id="thr:x",
        message_id="m1", inbound_body="give me HS code", audit=_audit_path_a(),
    )
    with pytest.raises(NotImplementedYet):
        c.on_inbound_clarification(inp)


def test_on_sad_inbound_raises_not_implemented_yet():
    c = DhlClearanceCoordinator()
    inp = SadInboundInput(
        batch_id="B1", awb="AWB1", doc_id="d1", doc_sha256="e" * 64,
        doc_type="SAD", audit=_audit_path_a(),
    )
    with pytest.raises(NotImplementedYet):
        c.on_sad_inbound(inp)


def test_is_in_scope_for_path_a_returns_true():
    assert DhlClearanceCoordinator.is_in_scope(_audit_path_a()) is True


def test_is_in_scope_for_path_b_returns_false():
    assert DhlClearanceCoordinator.is_in_scope(_audit_path_b()) is False


def test_predecessor_p2_is_always_unblocked():
    assert DhlClearanceCoordinator.predecessor_live_enabled("p2") is True


def test_predecessor_unknown_phase_returns_false():
    assert DhlClearanceCoordinator.predecessor_live_enabled("p99") is False


def test_predecessor_p3_blocked_when_p2_off(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "dhl_selfclearance_p2_live_enabled", False)
    assert DhlClearanceCoordinator.predecessor_live_enabled("p3") is False


def test_predecessor_p3_unblocked_when_p2_on(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "dhl_selfclearance_p2_live_enabled", True)
    assert DhlClearanceCoordinator.predecessor_live_enabled("p3") is True


def test_initial_manifest_creates_block():
    audit = {}
    DhlClearanceCoordinator.initial_manifest(audit)
    assert "dhl_clearance" in audit
    assert audit["dhl_clearance"]["state"] is not None
