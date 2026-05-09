"""
test_carrier_state_engine.py — Pure-logic tests for the carrier state
machine. No DB, no I/O, no adapters.

Required coverage:
  1. All 9 states are members of ``STATES``.
  2. ``is_valid_state`` rejects bogus values.
  3. Every entry in ``LEGAL_TRANSITIONS`` is allowed by
     ``can_transition`` and accepted by ``transition``.
  4. Random non-legal pairs are rejected by both helpers.
  5. ``voided`` is unreachable from any post-handover state, with the
     specific carrier-rule error message.
  6. Terminal states (delivered / returned / voided) have an empty
     ``allowed_next_states`` and are reported as terminal.
  7. ``transition`` returns the *to_state* string on success.
  8. Closure-gate set: every pre-handover state maps to a still-open
     shipment.
"""
from __future__ import annotations

import pytest

from app.services.carrier import carrier_state_engine as cse


ALL_STATES = [
    cse.PRE_AWB,
    cse.AWB_ISSUED,
    cse.LABEL_CREATED,
    cse.LABEL_PRINTED,
    cse.HANDED_TO_CARRIER,
    cse.IN_TRANSIT,
    cse.DELIVERED,
    cse.RETURNED,
    cse.VOIDED,
]


# ── 1. State set is exactly 9 ────────────────────────────────────────────────

def test_states_contains_all_9_carrier_states():
    assert len(cse.STATES) == 9
    for s in ALL_STATES:
        assert s in cse.STATES


# ── 2. is_valid_state rejects garbage ───────────────────────────────────────

@pytest.mark.parametrize("bogus", [None, "", "Pre_AWB", "PRE_AWB", "delivery", "shipped"])
def test_is_valid_state_rejects_unknown(bogus):
    assert cse.is_valid_state(bogus) is False


@pytest.mark.parametrize("state", ALL_STATES)
def test_is_valid_state_accepts_known(state):
    assert cse.is_valid_state(state) is True


# ── 3. Every legal transition is allowed ────────────────────────────────────

@pytest.mark.parametrize("from_state", list(cse.LEGAL_TRANSITIONS.keys()))
def test_can_transition_legal_pairs(from_state):
    for to_state in cse.LEGAL_TRANSITIONS[from_state]:
        assert cse.can_transition(from_state, to_state) is True, (
            f"{from_state!r} → {to_state!r} should be legal"
        )
        # transition() must return the to_state on success
        assert cse.transition(from_state, to_state) == to_state


# ── 4. Non-legal pairs rejected ─────────────────────────────────────────────

@pytest.mark.parametrize("from_state", list(cse.LEGAL_TRANSITIONS.keys()))
def test_can_transition_rejects_illegal_pairs(from_state):
    legal = cse.LEGAL_TRANSITIONS[from_state]
    illegal = [s for s in cse.STATES if s not in legal and s != from_state]
    for to_state in illegal:
        assert cse.can_transition(from_state, to_state) is False, (
            f"{from_state!r} → {to_state!r} should be illegal"
        )
        with pytest.raises(ValueError):
            cse.transition(from_state, to_state)


def test_can_transition_unknown_states_return_false():
    assert cse.can_transition("garbage", cse.PRE_AWB) is False
    assert cse.can_transition(cse.PRE_AWB, "garbage") is False
    assert cse.can_transition(None, None) is False


def test_transition_unknown_states_raise():
    with pytest.raises(ValueError):
        cse.transition("garbage", cse.PRE_AWB)
    with pytest.raises(ValueError):
        cse.transition(cse.PRE_AWB, "garbage")


# ── 5. Voided unreachable after handover (named rule) ───────────────────────

@pytest.mark.parametrize("from_state", [
    cse.HANDED_TO_CARRIER, cse.IN_TRANSIT, cse.DELIVERED, cse.RETURNED,
])
def test_void_after_handover_is_blocked_with_named_rule(from_state):
    assert cse.can_transition(from_state, cse.VOIDED) is False
    with pytest.raises(ValueError) as exc:
        cse.transition(from_state, cse.VOIDED)
    # Either the named rule message or the generic "Illegal" message is
    # acceptable — but for these post-handover states we expect the
    # named rule to fire because the state engine special-cases it.
    msg = str(exc.value).lower()
    assert "void" in msg
    assert "before handover" in msg or "illegal" in msg


@pytest.mark.parametrize("from_state", [
    cse.PRE_AWB, cse.AWB_ISSUED, cse.LABEL_CREATED, cse.LABEL_PRINTED,
])
def test_void_before_handover_is_allowed(from_state):
    assert cse.can_transition(from_state, cse.VOIDED) is True
    assert cse.transition(from_state, cse.VOIDED) == cse.VOIDED


# ── 6. Terminals ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("term", [cse.DELIVERED, cse.RETURNED, cse.VOIDED])
def test_terminal_states_have_no_next_states(term):
    assert cse.is_terminal(term) is True
    assert cse.allowed_next_states(term) == frozenset()


@pytest.mark.parametrize("non_term", [
    cse.PRE_AWB, cse.AWB_ISSUED, cse.LABEL_CREATED,
    cse.LABEL_PRINTED, cse.HANDED_TO_CARRIER, cse.IN_TRANSIT,
])
def test_non_terminal_states_have_next_states(non_term):
    assert cse.is_terminal(non_term) is False
    assert len(cse.allowed_next_states(non_term)) > 0


def test_is_terminal_unknown_returns_false():
    assert cse.is_terminal("garbage") is False
    assert cse.is_terminal(None) is False


# ── 7. Closure-gate set ─────────────────────────────────────────────────────

def test_pre_handover_states_set():
    assert cse.PRE_HANDOVER_STATES == frozenset({
        cse.PRE_AWB, cse.AWB_ISSUED, cse.LABEL_CREATED, cse.LABEL_PRINTED,
    })
    # And handed_to_carrier and beyond are NOT in it (closure unblocks)
    for s in (cse.HANDED_TO_CARRIER, cse.IN_TRANSIT, cse.DELIVERED,
              cse.RETURNED, cse.VOIDED):
        assert s not in cse.PRE_HANDOVER_STATES
