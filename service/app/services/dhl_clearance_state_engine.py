"""
dhl_clearance_state_engine.py — DHL self-clearance state machine (P0 scaffold).

Pure-logic state machine for the Path A (DHL self-clearance) workflow.
No I/O, no SQLite, no audit access. Callers persist state via
`dhl_clearance_manifest.py`.

States (ADR-012 base 9 + 4 added)
=================================
ADR-012 base ordered sequence:
    awaiting_preemptive_send
      → awaiting_poland_arrival
      → followup_active
      → dhl_requested_clarification
      → clarification_sent
      → awaiting_sad
      → sad_received
      → pz_unlocked
      → shipment_closed

Added in P0 (locked in dhl_selfclearance_program_2026-05-12 memory):
    dispatch_failed          — P2 dispatch error; recoverable to awaiting_preemptive_send
    scope_gate_violated      — AWB voided / threshold violated / agency engaged mid-flow
    operator_override_active — operator manual reply or force-unlock in progress
    pz_failed                — P5 PZ pipeline failed (non-retry; operator review)

Risk-R3 explicit edge:
    awaiting_poland_arrival → dhl_requested_clarification
(DHL responds to proactive dispatch before tracking shows Poland arrival.)

LEGAL_TRANSITIONS is a frozenset of (from_state, to_state) edges.
Any transition not in the set raises IllegalTransition.

State history is APPEND-ONLY. Use append_state_history() to record every
transition; never mutate prior history entries.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

# ── State name constants (single source of truth — callers must reference) ────

STATE_AWAITING_PREEMPTIVE_SEND:    str = "awaiting_preemptive_send"
STATE_AWAITING_POLAND_ARRIVAL:     str = "awaiting_poland_arrival"
STATE_FOLLOWUP_ACTIVE:             str = "followup_active"
STATE_DHL_REQUESTED_CLARIFICATION: str = "dhl_requested_clarification"
STATE_CLARIFICATION_SENT:          str = "clarification_sent"
STATE_AWAITING_SAD:                str = "awaiting_sad"
STATE_SAD_RECEIVED:                str = "sad_received"
STATE_PZ_UNLOCKED:                 str = "pz_unlocked"
STATE_SHIPMENT_CLOSED:             str = "shipment_closed"

# Added in P0 (4 extra)
STATE_DISPATCH_FAILED:             str = "dispatch_failed"
STATE_SCOPE_GATE_VIOLATED:         str = "scope_gate_violated"
STATE_OPERATOR_OVERRIDE_ACTIVE:    str = "operator_override_active"
STATE_PZ_FAILED:                   str = "pz_failed"

ALL_STATES: FrozenSet[str] = frozenset({
    STATE_AWAITING_PREEMPTIVE_SEND,
    STATE_AWAITING_POLAND_ARRIVAL,
    STATE_FOLLOWUP_ACTIVE,
    STATE_DHL_REQUESTED_CLARIFICATION,
    STATE_CLARIFICATION_SENT,
    STATE_AWAITING_SAD,
    STATE_SAD_RECEIVED,
    STATE_PZ_UNLOCKED,
    STATE_SHIPMENT_CLOSED,
    STATE_DISPATCH_FAILED,
    STATE_SCOPE_GATE_VIOLATED,
    STATE_OPERATOR_OVERRIDE_ACTIVE,
    STATE_PZ_FAILED,
})

INITIAL_STATE: str = STATE_AWAITING_PREEMPTIVE_SEND

TERMINAL_STATES: FrozenSet[str] = frozenset({
    STATE_SHIPMENT_CLOSED,
    STATE_SCOPE_GATE_VIOLATED,  # operator must hard-close out-of-band
})


# ── Legal transitions (frozenset of (from, to) edges) ────────────────────────
# Forward edges follow ADR-012 §"Automation state machine".
# Recovery / error edges added per dhl_selfclearance_program memory.

_BASE_FORWARD: List[Tuple[str, str]] = [
    (STATE_AWAITING_PREEMPTIVE_SEND,    STATE_AWAITING_POLAND_ARRIVAL),
    (STATE_AWAITING_POLAND_ARRIVAL,     STATE_FOLLOWUP_ACTIVE),
    (STATE_FOLLOWUP_ACTIVE,             STATE_DHL_REQUESTED_CLARIFICATION),
    (STATE_DHL_REQUESTED_CLARIFICATION, STATE_CLARIFICATION_SENT),
    (STATE_CLARIFICATION_SENT,          STATE_AWAITING_SAD),
    (STATE_AWAITING_SAD,                STATE_SAD_RECEIVED),
    (STATE_SAD_RECEIVED,                STATE_PZ_UNLOCKED),
    (STATE_PZ_UNLOCKED,                 STATE_SHIPMENT_CLOSED),
]

# Risk-R3 explicit edge: DHL responds before Poland arrival is observed.
_R3_EDGE: List[Tuple[str, str]] = [
    (STATE_AWAITING_POLAND_ARRIVAL, STATE_DHL_REQUESTED_CLARIFICATION),
]

# Path: no-clarification SAD (DHL doesn't ask, customs broker delivers SAD).
# Per master plan §4.1: "P5 can begin … EITHER live OR no-clarification SAD path".
_NO_CLARIFICATION_SAD: List[Tuple[str, str]] = [
    (STATE_AWAITING_POLAND_ARRIVAL, STATE_AWAITING_SAD),
    (STATE_FOLLOWUP_ACTIVE,         STATE_AWAITING_SAD),
]

# Error / failure edges
_FAILURE: List[Tuple[str, str]] = [
    # Dispatch failure
    (STATE_AWAITING_PREEMPTIVE_SEND,    STATE_DISPATCH_FAILED),
    (STATE_DISPATCH_FAILED,             STATE_AWAITING_PREEMPTIVE_SEND),  # recoverable
    # Scope-gate violation (AWB voided / threshold violated / agency mid-flow)
    (STATE_AWAITING_PREEMPTIVE_SEND,    STATE_SCOPE_GATE_VIOLATED),
    (STATE_AWAITING_POLAND_ARRIVAL,     STATE_SCOPE_GATE_VIOLATED),
    (STATE_FOLLOWUP_ACTIVE,             STATE_SCOPE_GATE_VIOLATED),
    (STATE_DHL_REQUESTED_CLARIFICATION, STATE_SCOPE_GATE_VIOLATED),
    (STATE_CLARIFICATION_SENT,          STATE_SCOPE_GATE_VIOLATED),
    (STATE_AWAITING_SAD,                STATE_SCOPE_GATE_VIOLATED),
    (STATE_SAD_RECEIVED,                STATE_SCOPE_GATE_VIOLATED),
    (STATE_PZ_UNLOCKED,                 STATE_SCOPE_GATE_VIOLATED),
    # PZ failure (terminal pending operator review)
    (STATE_PZ_UNLOCKED,                 STATE_PZ_FAILED),
    (STATE_PZ_FAILED,                   STATE_PZ_UNLOCKED),  # operator-acked retry
]

# Operator override (active manual reply or force-unlock) and return.
_OVERRIDE: List[Tuple[str, str]] = [
    (STATE_DHL_REQUESTED_CLARIFICATION, STATE_OPERATOR_OVERRIDE_ACTIVE),
    (STATE_FOLLOWUP_ACTIVE,             STATE_OPERATOR_OVERRIDE_ACTIVE),
    (STATE_AWAITING_SAD,                STATE_OPERATOR_OVERRIDE_ACTIVE),
    # Return paths — operator decides which state we resume in
    (STATE_OPERATOR_OVERRIDE_ACTIVE,    STATE_CLARIFICATION_SENT),
    (STATE_OPERATOR_OVERRIDE_ACTIVE,    STATE_AWAITING_SAD),
    (STATE_OPERATOR_OVERRIDE_ACTIVE,    STATE_FOLLOWUP_ACTIVE),
    (STATE_OPERATOR_OVERRIDE_ACTIVE,    STATE_SCOPE_GATE_VIOLATED),
]

LEGAL_TRANSITIONS: FrozenSet[Tuple[str, str]] = frozenset(
    _BASE_FORWARD + _R3_EDGE + _NO_CLARIFICATION_SAD + _FAILURE + _OVERRIDE
)


# ── Errors ───────────────────────────────────────────────────────────────────

class StateEngineError(Exception):
    """Base for state engine errors."""


class IllegalTransition(StateEngineError):
    """Raised when a from→to transition is not in LEGAL_TRANSITIONS."""


class UnknownState(StateEngineError):
    """Raised when a state name is not in ALL_STATES."""


# ── Pure predicates ──────────────────────────────────────────────────────────

def is_known_state(state: str) -> bool:
    return state in ALL_STATES


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def is_legal_transition(from_state: str, to_state: str) -> bool:
    return (from_state, to_state) in LEGAL_TRANSITIONS


def allowed_next_states(state: str) -> FrozenSet[str]:
    """Return the set of states reachable in one legal transition from *state*."""
    if not is_known_state(state):
        raise UnknownState(f"Unknown state: {state!r}")
    return frozenset(to for (frm, to) in LEGAL_TRANSITIONS if frm == state)


# ── Transition mechanics ─────────────────────────────────────────────────────

def transition(
    from_state: str,
    to_state: str,
    *,
    reason: str = "",
    actor:  str = "system",
    at:     Optional[str] = None,
    shadow: bool = False,
) -> Dict[str, Any]:
    """
    Validate a transition and return the new state-history entry.

    Does NOT mutate any external state — caller appends the returned record
    via append_state_history().

    The optional `shadow` kwarg places a `shadow: True` key on the entry
    record when the transition was produced under `shadow_mode=True` per
    ADR-018 Invariant 4. Audit consumers that filter via
    `entry.get("shadow") is True` can cleanly distinguish observation-mode
    transitions from live-mode transitions. When shadow=False (default),
    the key is omitted to keep live records compact.

    Raises:
        UnknownState      — if either state is not in ALL_STATES.
        IllegalTransition — if (from_state, to_state) is not in LEGAL_TRANSITIONS.
    """
    if not is_known_state(from_state):
        raise UnknownState(f"Unknown from_state: {from_state!r}")
    if not is_known_state(to_state):
        raise UnknownState(f"Unknown to_state: {to_state!r}")
    if not is_legal_transition(from_state, to_state):
        raise IllegalTransition(
            f"Illegal transition: {from_state!r} → {to_state!r}. "
            f"Allowed next states from {from_state!r}: "
            f"{sorted(allowed_next_states(from_state))}"
        )

    entry: Dict[str, Any] = {
        "from":   from_state,
        "to":     to_state,
        "at":     at or _now_utc(),
        "actor":  actor,
        "reason": reason or "",
    }
    if shadow:
        entry["shadow"] = True
    return entry


def append_state_history(
    history: List[Dict[str, Any]],
    entry: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Append-only state history. Returns a NEW list (does not mutate input).

    Caller is responsible for ensuring *entry* came from transition().
    """
    if not isinstance(history, list):
        raise TypeError("history must be a list")
    if not isinstance(entry, dict) or "from" not in entry or "to" not in entry:
        raise ValueError("entry must be a dict with at least 'from' and 'to' keys")
    return list(history) + [dict(entry)]


def current_state(history: List[Dict[str, Any]], default: str = INITIAL_STATE) -> str:
    """Return the latest 'to' state in *history*, or *default* if history empty."""
    if not history:
        return default
    last = history[-1]
    return last.get("to") or default


# ── Reachability helper (used by tests) ───────────────────────────────────────

def reachable_from(start: str) -> FrozenSet[str]:
    """BFS over LEGAL_TRANSITIONS — set of states reachable from *start*."""
    if not is_known_state(start):
        raise UnknownState(f"Unknown start state: {start!r}")
    seen = {start}
    frontier = [start]
    while frontier:
        s = frontier.pop()
        for nxt in allowed_next_states(s):
            if nxt not in seen:
                seen.add(nxt)
                frontier.append(nxt)
    return frozenset(seen)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
