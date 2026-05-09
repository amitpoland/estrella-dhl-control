"""
carrier_state_engine.py — Pure-logic carrier shipment state machine.

This module is deliberately stateless. It validates transitions and
nothing else. No SQLite, no file system, no HTTP, no audit hooks.
That separation lets the same legality rules be applied:

  * by the shipment DB (carrier_shipment_db) before persisting a
    transition,
  * by the coordinator (DL-D) before requesting a state change from an
    adapter,
  * by tests that need to enumerate legal transitions without a
    database.

States
------
  pre_awb            Coordinator has all inputs but has not yet asked
                     the carrier to issue an AWB.
  awb_issued         Carrier returned an AWB. Label may not be ready
                     yet (DHL sometimes returns label asynchronously).
  label_created      Adapter has the label artefact. Operator has not
                     printed it.
  label_printed      Operator confirmed the label printed cleanly.
  handed_to_carrier  Carrier picked up / dropoff scanned. After this
                     point, ``voided`` is no longer reachable per DHL
                     contract-of-carriage rules.
  in_transit         Carrier acknowledged movement.
  delivered          Terminal — proof of delivery received.
  returned           Terminal — RTO / non-deliverable.
  voided             Terminal — cancellation accepted by carrier
                     before handover. Unreachable after
                     handed_to_carrier.

Transitions (only these are legal; everything else raises)
----------
  pre_awb            → awb_issued, voided
  awb_issued         → label_created, voided
  label_created      → label_printed, voided
  label_printed      → handed_to_carrier, voided
  handed_to_carrier  → in_transit, delivered, returned
  in_transit         → delivered, returned
  delivered          → (terminal)
  returned           → (terminal)
  voided             → (terminal)

Public API
----------
  is_valid_state(state)                     -> bool
  is_terminal(state)                        -> bool
  allowed_next_states(state)                -> frozenset[str]
  can_transition(from_state, to_state)      -> bool
  transition(from_state, to_state)          -> str        (raises on illegal)
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Optional

# ── State constants ──────────────────────────────────────────────────────────
#
# Strings are lowercase with underscores. They are part of the database
# schema (carrier_shipments.state) and a JSON wire contract (future
# routes / dashboard), so any rename is a migration.

PRE_AWB:           str = "pre_awb"
AWB_ISSUED:        str = "awb_issued"
LABEL_CREATED:     str = "label_created"
LABEL_PRINTED:     str = "label_printed"
HANDED_TO_CARRIER: str = "handed_to_carrier"
IN_TRANSIT:        str = "in_transit"
DELIVERED:         str = "delivered"
RETURNED:          str = "returned"
VOIDED:            str = "voided"

STATES: FrozenSet[str] = frozenset({
    PRE_AWB,
    AWB_ISSUED,
    LABEL_CREATED,
    LABEL_PRINTED,
    HANDED_TO_CARRIER,
    IN_TRANSIT,
    DELIVERED,
    RETURNED,
    VOIDED,
})

TERMINAL_STATES: FrozenSet[str] = frozenset({
    DELIVERED,
    RETURNED,
    VOIDED,
})

# Closure-gate helpers. The lifecycle closure check (DL-C / routes_lifecycle)
# treats any shipment in PRE_HANDOVER_STATES as still-open work — closure of
# the parent batch is blocked while one or more of its carrier shipments are
# in this set. Once the package is HANDED_TO_CARRIER (and therefore on the
# carrier's responsibility), the closure gate releases.
PRE_HANDOVER_STATES: FrozenSet[str] = frozenset({
    PRE_AWB, AWB_ISSUED, LABEL_CREATED, LABEL_PRINTED,
})

# Map: from_state → set of legal to_states. Terminal states map to an
# empty frozenset, so ``allowed_next_states`` and ``can_transition``
# behave correctly without a special case.
LEGAL_TRANSITIONS: Dict[str, FrozenSet[str]] = {
    PRE_AWB:           frozenset({AWB_ISSUED, VOIDED}),
    AWB_ISSUED:        frozenset({LABEL_CREATED, VOIDED}),
    LABEL_CREATED:     frozenset({LABEL_PRINTED, VOIDED}),
    LABEL_PRINTED:     frozenset({HANDED_TO_CARRIER, VOIDED}),
    HANDED_TO_CARRIER: frozenset({IN_TRANSIT, DELIVERED, RETURNED}),
    IN_TRANSIT:        frozenset({DELIVERED, RETURNED}),
    DELIVERED:         frozenset(),
    RETURNED:          frozenset(),
    VOIDED:            frozenset(),
}


# ── Public helpers ──────────────────────────────────────────────────────────

def is_valid_state(state: Optional[str]) -> bool:
    """True iff *state* is one of the 9 known carrier states."""
    return bool(state) and state in STATES


def is_terminal(state: Optional[str]) -> bool:
    """True iff *state* is delivered/returned/voided.

    Unknown states return False rather than raising — callers that care
    about validity should call :func:`is_valid_state` first.
    """
    return bool(state) and state in TERMINAL_STATES


def allowed_next_states(state: Optional[str]) -> FrozenSet[str]:
    """Set of states that can legally follow *state*.

    Returns an empty frozenset for any unknown state and for terminals
    (delivered/returned/voided).
    """
    if not is_valid_state(state):
        return frozenset()
    return LEGAL_TRANSITIONS[state]


def can_transition(from_state: Optional[str], to_state: Optional[str]) -> bool:
    """True iff (from_state → to_state) is a legal carrier transition.

    Both arguments are validated; an unknown state on either side is
    always False (never raises). Use :func:`transition` when an illegal
    move should fail loudly.
    """
    if not is_valid_state(from_state) or not is_valid_state(to_state):
        return False
    return to_state in LEGAL_TRANSITIONS[from_state]


# ── Strict transition (raises on illegal) ────────────────────────────────────

def transition(from_state: str, to_state: str) -> str:
    """Validate the carrier transition (*from_state* → *to_state*).

    On success returns *to_state* unchanged so callers can write
    ``new_state = transition(prev, to_state)``.

    Raises
    ------
    ValueError
      - *from_state* or *to_state* is not a known carrier state
      - the move is not in :data:`LEGAL_TRANSITIONS`
      - the implicit "voided after handover" rule is violated
        (this is just a clearer message for an already-illegal move,
        included because the state engine is the canonical place to
        explain it)
    """
    if not is_valid_state(from_state):
        raise ValueError(
            f"Unknown carrier from_state {from_state!r}. "
            f"Allowed: {sorted(STATES)}"
        )
    if not is_valid_state(to_state):
        raise ValueError(
            f"Unknown carrier to_state {to_state!r}. "
            f"Allowed: {sorted(STATES)}"
        )

    if to_state == VOIDED and from_state in (
        HANDED_TO_CARRIER, IN_TRANSIT, DELIVERED, RETURNED,
    ):
        # Same outcome as the generic illegal-transition raise below,
        # but the error message names the actual carrier rule so the
        # operator UI can show why ``Void`` is grayed out.
        raise ValueError(
            f"Illegal carrier transition {from_state!r} → {VOIDED!r}: "
            f"voiding is only permitted before handover to the carrier."
        )

    legal = LEGAL_TRANSITIONS[from_state]
    if to_state not in legal:
        raise ValueError(
            f"Illegal carrier transition {from_state!r} → {to_state!r}. "
            f"Legal next states from {from_state!r}: {sorted(legal)}"
        )
    return to_state
