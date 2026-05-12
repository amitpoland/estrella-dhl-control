"""
test_dhl_selfclearance_p0_state_engine.py — State machine for DHL self-clearance.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services import dhl_clearance_state_engine as se  # noqa: E402


# ── State vocabulary ──────────────────────────────────────────────────────────

def test_thirteen_states_total():
    assert len(se.ALL_STATES) == 13


def test_all_nine_adr012_base_states_present():
    for s in [
        se.STATE_AWAITING_PREEMPTIVE_SEND,
        se.STATE_AWAITING_POLAND_ARRIVAL,
        se.STATE_FOLLOWUP_ACTIVE,
        se.STATE_DHL_REQUESTED_CLARIFICATION,
        se.STATE_CLARIFICATION_SENT,
        se.STATE_AWAITING_SAD,
        se.STATE_SAD_RECEIVED,
        se.STATE_PZ_UNLOCKED,
        se.STATE_SHIPMENT_CLOSED,
    ]:
        assert s in se.ALL_STATES


def test_four_added_states_present():
    for s in [
        se.STATE_DISPATCH_FAILED,
        se.STATE_SCOPE_GATE_VIOLATED,
        se.STATE_OPERATOR_OVERRIDE_ACTIVE,
        se.STATE_PZ_FAILED,
    ]:
        assert s in se.ALL_STATES


def test_initial_state_is_awaiting_preemptive_send():
    assert se.INITIAL_STATE == se.STATE_AWAITING_PREEMPTIVE_SEND


def test_terminal_states_include_closed_and_scope_violation():
    assert se.STATE_SHIPMENT_CLOSED in se.TERMINAL_STATES
    assert se.STATE_SCOPE_GATE_VIOLATED in se.TERMINAL_STATES


# ── Legal transitions ─────────────────────────────────────────────────────────

def test_base_forward_chain_is_legal():
    chain = [
        (se.STATE_AWAITING_PREEMPTIVE_SEND,    se.STATE_AWAITING_POLAND_ARRIVAL),
        (se.STATE_AWAITING_POLAND_ARRIVAL,     se.STATE_FOLLOWUP_ACTIVE),
        (se.STATE_FOLLOWUP_ACTIVE,             se.STATE_DHL_REQUESTED_CLARIFICATION),
        (se.STATE_DHL_REQUESTED_CLARIFICATION, se.STATE_CLARIFICATION_SENT),
        (se.STATE_CLARIFICATION_SENT,          se.STATE_AWAITING_SAD),
        (se.STATE_AWAITING_SAD,                se.STATE_SAD_RECEIVED),
        (se.STATE_SAD_RECEIVED,                se.STATE_PZ_UNLOCKED),
        (se.STATE_PZ_UNLOCKED,                 se.STATE_SHIPMENT_CLOSED),
    ]
    for frm, to in chain:
        assert se.is_legal_transition(frm, to), f"{frm} → {to} should be legal"


def test_risk_r3_edge_is_legal():
    # DHL responds before Poland-arrival shows on tracking.
    assert se.is_legal_transition(
        se.STATE_AWAITING_POLAND_ARRIVAL,
        se.STATE_DHL_REQUESTED_CLARIFICATION,
    )


def test_no_clarification_sad_paths_are_legal():
    assert se.is_legal_transition(
        se.STATE_AWAITING_POLAND_ARRIVAL, se.STATE_AWAITING_SAD,
    )
    assert se.is_legal_transition(
        se.STATE_FOLLOWUP_ACTIVE, se.STATE_AWAITING_SAD,
    )


def test_illegal_random_transition_raises():
    with pytest.raises(se.IllegalTransition):
        se.transition(
            se.STATE_AWAITING_PREEMPTIVE_SEND,
            se.STATE_SHIPMENT_CLOSED,
        )


def test_dispatch_failed_recovery_loop():
    assert se.is_legal_transition(
        se.STATE_AWAITING_PREEMPTIVE_SEND, se.STATE_DISPATCH_FAILED,
    )
    assert se.is_legal_transition(
        se.STATE_DISPATCH_FAILED, se.STATE_AWAITING_PREEMPTIVE_SEND,
    )


def test_pz_failed_recovery_to_unlocked():
    assert se.is_legal_transition(se.STATE_PZ_UNLOCKED, se.STATE_PZ_FAILED)
    assert se.is_legal_transition(se.STATE_PZ_FAILED, se.STATE_PZ_UNLOCKED)


def test_scope_gate_violated_reachable_from_every_active_state():
    # Scope-gate failure can fire at any non-terminal state.
    for s in [
        se.STATE_AWAITING_PREEMPTIVE_SEND,
        se.STATE_AWAITING_POLAND_ARRIVAL,
        se.STATE_FOLLOWUP_ACTIVE,
        se.STATE_DHL_REQUESTED_CLARIFICATION,
        se.STATE_CLARIFICATION_SENT,
        se.STATE_AWAITING_SAD,
        se.STATE_SAD_RECEIVED,
        se.STATE_PZ_UNLOCKED,
    ]:
        assert se.is_legal_transition(s, se.STATE_SCOPE_GATE_VIOLATED), \
            f"{s} → scope_gate_violated must be legal"


def test_operator_override_returns_to_workflow():
    assert se.is_legal_transition(
        se.STATE_FOLLOWUP_ACTIVE, se.STATE_OPERATOR_OVERRIDE_ACTIVE,
    )
    assert se.is_legal_transition(
        se.STATE_OPERATOR_OVERRIDE_ACTIVE, se.STATE_FOLLOWUP_ACTIVE,
    )


# ── transition() mechanics ────────────────────────────────────────────────────

def test_transition_returns_entry_with_required_fields():
    entry = se.transition(
        se.STATE_AWAITING_PREEMPTIVE_SEND,
        se.STATE_AWAITING_POLAND_ARRIVAL,
        reason="awb_stable", actor="system",
    )
    assert entry["from"] == se.STATE_AWAITING_PREEMPTIVE_SEND
    assert entry["to"] == se.STATE_AWAITING_POLAND_ARRIVAL
    assert entry["reason"] == "awb_stable"
    assert entry["actor"] == "system"
    assert "at" in entry and entry["at"]


def test_transition_unknown_state_raises():
    with pytest.raises(se.UnknownState):
        se.transition("bogus_state", se.STATE_AWAITING_POLAND_ARRIVAL)
    with pytest.raises(se.UnknownState):
        se.transition(se.STATE_AWAITING_POLAND_ARRIVAL, "bogus_state")


# ── state_history append-only ─────────────────────────────────────────────────

def test_append_state_history_returns_new_list():
    history = []
    entry = se.transition(
        se.STATE_AWAITING_PREEMPTIVE_SEND,
        se.STATE_AWAITING_POLAND_ARRIVAL,
    )
    new_history = se.append_state_history(history, entry)
    assert len(history) == 0  # original unchanged
    assert len(new_history) == 1


def test_state_history_idempotency_via_multiple_appends():
    history = []
    for frm, to in [
        (se.STATE_AWAITING_PREEMPTIVE_SEND, se.STATE_AWAITING_POLAND_ARRIVAL),
        (se.STATE_AWAITING_POLAND_ARRIVAL, se.STATE_FOLLOWUP_ACTIVE),
    ]:
        entry = se.transition(frm, to)
        history = se.append_state_history(history, entry)
    assert len(history) == 2
    assert history[0]["to"] == se.STATE_AWAITING_POLAND_ARRIVAL
    assert history[1]["to"] == se.STATE_FOLLOWUP_ACTIVE


def test_current_state_default_when_history_empty():
    assert se.current_state([]) == se.INITIAL_STATE


def test_current_state_returns_last_to():
    history = [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}]
    assert se.current_state(history) == "c"


# ── Reachability ──────────────────────────────────────────────────────────────

def test_reachable_from_initial_covers_all_states():
    reached = se.reachable_from(se.INITIAL_STATE)
    # All 13 states are reachable through some legal path from INITIAL_STATE.
    assert reached == se.ALL_STATES


def test_reachable_from_unknown_state_raises():
    with pytest.raises(se.UnknownState):
        se.reachable_from("nonexistent")


# ── allowed_next_states ───────────────────────────────────────────────────────

def test_allowed_next_states_from_initial():
    nxt = se.allowed_next_states(se.STATE_AWAITING_PREEMPTIVE_SEND)
    assert se.STATE_AWAITING_POLAND_ARRIVAL in nxt
    assert se.STATE_DISPATCH_FAILED in nxt
    assert se.STATE_SCOPE_GATE_VIOLATED in nxt


def test_shipment_closed_is_terminal_no_outgoing_edges():
    assert se.allowed_next_states(se.STATE_SHIPMENT_CLOSED) == frozenset()
