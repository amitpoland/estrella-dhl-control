"""
test_dhl_clearance_state_engine_p2.py — P2 state transitions

Covers the state engine transitions exercised by P2:
  - awaiting_preemptive_send → awaiting_poland_arrival (success path)
  - awaiting_preemptive_send → dispatch_failed       (error path)
  - dispatch_failed → awaiting_preemptive_send       (recovery)

Plus the ADR-018 truth-table assertions for the (shadow_mode, live_enabled)
combinations relevant to P2's `dispatch_proactive` entrypoint.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services import dhl_clearance_state_engine as se  # noqa: E402
from app.services import dhl_clearance_coordinator as cc   # noqa: E402


# ── State machine transitions ────────────────────────────────────────────────

def test_p2_success_transition_awaiting_preemptive_to_arrival():
    assert se.is_legal_transition(
        se.STATE_AWAITING_PREEMPTIVE_SEND,
        se.STATE_AWAITING_POLAND_ARRIVAL,
    )


def test_p2_failure_transition_to_dispatch_failed():
    assert se.is_legal_transition(
        se.STATE_AWAITING_PREEMPTIVE_SEND,
        se.STATE_DISPATCH_FAILED,
    )


def test_p2_recovery_transition_back_from_dispatch_failed():
    assert se.is_legal_transition(
        se.STATE_DISPATCH_FAILED,
        se.STATE_AWAITING_PREEMPTIVE_SEND,
    )


def test_p2_illegal_transition_skip_awaiting_arrival():
    # Cannot leap from awaiting_preemptive_send straight to followup_active.
    with pytest.raises(se.IllegalTransition):
        se.transition(
            se.STATE_AWAITING_PREEMPTIVE_SEND,
            se.STATE_FOLLOWUP_ACTIVE,
        )


def test_p2_transition_metadata_captured():
    entry = se.transition(
        se.STATE_AWAITING_PREEMPTIVE_SEND,
        se.STATE_AWAITING_POLAND_ARRIVAL,
        reason="p2_dispatch_shadow",
        actor="system",
    )
    assert entry["from"] == se.STATE_AWAITING_PREEMPTIVE_SEND
    assert entry["to"] == se.STATE_AWAITING_POLAND_ARRIVAL
    assert entry["reason"] == "p2_dispatch_shadow"
    assert entry["actor"] == "system"
    assert entry["at"]


# ── ADR-018 truth table ──────────────────────────────────────────────────────

def test_adr018_dormant_state_allowed():
    cc._enforce_flag_combination("p2", shadow_mode=False, live_enabled=False)


def test_adr018_shadow_state_allowed():
    cc._enforce_flag_combination("p2", shadow_mode=True, live_enabled=False)


def test_adr018_live_state_allowed():
    cc._enforce_flag_combination("p2", shadow_mode=True, live_enabled=True)


def test_adr018_forbidden_state_rejected():
    with pytest.raises(cc.ForbiddenFlagCombination):
        cc._enforce_flag_combination("p2", shadow_mode=False, live_enabled=True)


def test_adr018_forbidden_message_cites_invariant_1():
    try:
        cc._enforce_flag_combination("p2", shadow_mode=False, live_enabled=True)
        assert False, "should have raised"
    except cc.ForbiddenFlagCombination as exc:
        msg = str(exc)
        assert "FORBIDDEN" in msg
        assert "ADR-018" in msg
