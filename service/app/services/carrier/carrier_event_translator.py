"""
carrier_event_translator.py — Pure-logic mapping from carrier-emitted
status codes to (target carrier-state, coordinator-method) tuples.

DL-E1 scope
-----------
* No I/O. No DB. No HTTP. No web framework.
* No coordinator import. No adapter import.
* Translates a ``CarrierEvent`` (already parsed by an adapter) into
  a small ``Translation`` dataclass that the handler consumes.

The translation table is the canonical source of truth on which DHL
``statusCode`` values map to which carrier state. Anything outside
the table falls through to ``record_exception`` with the
``unknown=True`` flag — never a state change, never a crash.

Design guarantees
-----------------
1. ``translate(event)`` always returns a ``Translation`` — never None,
   never raises.
2. The output's ``coordinator_method`` is always the literal name of
   a method on ``the coordinator class`` so the handler can call
   ``getattr(coord, t.coordinator_method)`` safely.
3. ``unknown=True`` means the translator did not find a match. The
   handler must surface this in the manifest message and DB row.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .base import CarrierEvent


# ── Carrier coordinator method names (as literals) ─────────────────────────
#
# Kept as strings rather than imports so this module remains
# decoupled from the coordinator module. The handler resolves the
# attribute at call time.

_METHOD_IN_TRANSIT: str = "record_in_transit"
_METHOD_DELIVERED:  str = "record_delivered"
_METHOD_RETURNED:   str = "record_returned"
_METHOD_EXCEPTION:  str = "record_exception"


# ── Target state literals ──────────────────────────────────────────────────
#
# Mirror carrier_state_engine constants; kept as literals for the same
# decoupling reason as the method names. carrier_state_engine is the
# source of truth on legality at validation time.

_STATE_IN_TRANSIT: str = "in_transit"
_STATE_DELIVERED:  str = "delivered"
_STATE_RETURNED:   str = "returned"

# DHL-emitted statusCode → (target state | None, coordinator method).
# Codes are normalised to lowercase + dash-separated before lookup.
_TRANSLATION_TABLE = {
    # In-transit family — all collapse to in_transit; the original
    # statusCode is preserved in the manifest message via the raw payload.
    "transit":          (_STATE_IN_TRANSIT, _METHOD_IN_TRANSIT),
    "pre-transit":      (_STATE_IN_TRANSIT, _METHOD_IN_TRANSIT),
    "in-transit":       (_STATE_IN_TRANSIT, _METHOD_IN_TRANSIT),
    "in_transit":       (_STATE_IN_TRANSIT, _METHOD_IN_TRANSIT),
    "out-for-delivery": (_STATE_IN_TRANSIT, _METHOD_IN_TRANSIT),
    "out_for_delivery": (_STATE_IN_TRANSIT, _METHOD_IN_TRANSIT),
    "picked-up":        (_STATE_IN_TRANSIT, _METHOD_IN_TRANSIT),
    "picked_up":        (_STATE_IN_TRANSIT, _METHOD_IN_TRANSIT),

    # Delivered family.
    "delivered":        (_STATE_DELIVERED, _METHOD_DELIVERED),
    "success":          (_STATE_DELIVERED, _METHOD_DELIVERED),

    # Returned family. DHL emits "failure" for non-deliverable packages
    # that get returned to sender.
    "returned":         (_STATE_RETURNED, _METHOD_RETURNED),
    "return":           (_STATE_RETURNED, _METHOD_RETURNED),
    "return_in_progress": (_STATE_RETURNED, _METHOD_RETURNED),
    "return-in-progress": (_STATE_RETURNED, _METHOD_RETURNED),
    "failure":          (_STATE_RETURNED, _METHOD_RETURNED),
    "failure-rto":      (_STATE_RETURNED, _METHOD_RETURNED),

    # Exception family — informational, no state change.
    "exception":        (None,             _METHOD_EXCEPTION),
    "delay":            (None,             _METHOD_EXCEPTION),
    "customs_hold":     (None,             _METHOD_EXCEPTION),
    "customs-hold":     (None,             _METHOD_EXCEPTION),
    "address_issue":    (None,             _METHOD_EXCEPTION),
    "address-issue":    (None,             _METHOD_EXCEPTION),
}


# ── Public Translation type ────────────────────────────────────────────────

@dataclass(frozen=True)
class Translation:
    """Result of mapping a carrier event to a coordinator action.

    ``target_state`` is None when the event does not change carrier
    state (DHL ``exception`` codes and unknown statusCodes both land
    here). The handler still calls the coordinator (specifically
    ``record_exception``) so a manifest message is appended and the
    audit trail names the external signal.

    ``unknown`` is True iff the statusCode did not match any entry in
    the table — the handler surfaces this in the DB row and message
    so an operator dashboard can flag uncovered DHL codes.
    """
    target_state:        Optional[str]
    coordinator_method:  str
    unknown:             bool = False


# ── Public API ─────────────────────────────────────────────────────────────

def translate(event: CarrierEvent) -> Translation:
    """Map *event*'s ``event_code`` to a ``Translation``.

    Lookups are case-insensitive and tolerant of dash-vs-underscore
    variants (``out-for-delivery`` and ``out_for_delivery`` both land
    on the same row). Whitespace around the code is stripped.
    """
    code = (event.event_code or "").strip().lower()
    entry = _TRANSLATION_TABLE.get(code)
    if entry is None:
        return Translation(
            target_state       = None,
            coordinator_method = _METHOD_EXCEPTION,
            unknown            = True,
        )
    target_state, method = entry
    return Translation(
        target_state       = target_state,
        coordinator_method = method,
        unknown            = False,
    )
