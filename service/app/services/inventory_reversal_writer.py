"""
inventory_reversal_writer.py — Inventory Reversal authority (Package B).

ONE writer for forward-correction reversals of transit states back to
WAREHOUSE_STOCK. Records the reversal (who / why / original event link) in
inventory_reversals and drives the state change through
inventory_state_engine.transition(). It never writes inventory_state directly,
never touches Product Master / Packing / Sales / wFirma / accounting, and never
mutates or deletes existing audit history — reversals are append-only forward
corrections.

Reversible states (transit only):
    SALES_TRANSIT or CLIENT_DISPATCHED → WAREHOUSE_STOCK

Terminal states (CLOSED, WRITTEN_OFF) have NO successors and are NOT reversible.

Operator identity is supplied by the route from the authenticated session.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

from . import inventory_state_engine as engine
from . import warehouse_db as wdb


REVERSIBLE_STATES = frozenset({"SALES_TRANSIT", "CLIENT_DISPATCHED"})


class ReversalError(Exception):
    """Structured reversal error. `code` maps to an HTTP status in the route."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def reverse_to_stock(
    *,
    scan_code:          str,
    operator:           str,
    reason:             str,
    idempotency_key:    str,
    expected_from:      str,
    original_event_id:  str = "",
    notes:              str = "",
) -> Dict[str, Any]:
    """Reverse a piece from a transit state back to WAREHOUSE_STOCK.

    expected_from must match the piece's current state (prevents race conditions
    and confirms the operator is reversing the correct state).

    Raises ReversalError(code) — INVALID_INPUT / DB_UNAVAILABLE /
    PIECE_NOT_FOUND / WRONG_STATE.
    """
    if not scan_code:
        raise ReversalError("INVALID_INPUT", "scan_code is required")
    if not operator:
        raise ReversalError("INVALID_INPUT", "operator is required (session-derived)")
    if not reason or not reason.strip():
        raise ReversalError("INVALID_INPUT", "reason is required")
    if not idempotency_key:
        raise ReversalError("INVALID_INPUT", "idempotency_key is required")
    if expected_from not in REVERSIBLE_STATES:
        raise ReversalError(
            "INVALID_INPUT",
            f"expected_from must be one of {sorted(REVERSIBLE_STATES)}, "
            f"got {expected_from!r}",
        )
    if wdb._db_path is None:
        raise ReversalError("DB_UNAVAILABLE", "warehouse_db not initialised")

    valid_reasons = wdb.REVERSAL_REASONS_TRANSIT
    if reason not in valid_reasons:
        raise ReversalError(
            "INVALID_INPUT",
            f"reason must be one of {sorted(valid_reasons)}, got {reason!r}",
        )

    prior = wdb.find_reversal_by_idempotency(scan_code, idempotency_key)
    if prior is not None:
        return _replay_result(prior)

    state_row = engine.get_state(scan_code)
    if state_row is None:
        raise ReversalError(
            "PIECE_NOT_FOUND",
            f"scan_code {scan_code!r} not in inventory_state",
        )

    current_state = state_row.get("state") or ""
    if current_state != expected_from:
        raise ReversalError(
            "WRONG_STATE",
            f"Piece {scan_code!r} is in {current_state!r}, "
            f"expected {expected_from!r}",
        )

    try:
        rev_row = wdb.record_reversal(
            scan_code=scan_code,
            from_state=current_state,
            to_state="WAREHOUSE_STOCK",
            reversal_type="transit",
            reason=reason,
            operator=operator,
            idempotency_key=idempotency_key,
            approval_reference="",
            original_event_id=original_event_id,
            notes=notes,
        )
    except sqlite3.IntegrityError:
        prior = wdb.find_reversal_by_idempotency(scan_code, idempotency_key)
        return _replay_result(prior or {})

    try:
        engine.transition(
            scan_code=scan_code,
            to_state=engine.WAREHOUSE_STOCK,
            operator=operator,
            note=f"Reversal from {current_state}: {reason}",
        )
    except ValueError as exc:
        raise ReversalError("INVALID_INPUT", str(exc)) from exc

    return {
        "status":          "reversed",
        "scan_code":       scan_code,
        "reversal_id":     rev_row.get("id"),
        "from_state":      current_state,
        "to_state":        "WAREHOUSE_STOCK",
        "idempotency_key": idempotency_key,
    }


def _replay_result(prior: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status":          "replayed",
        "scan_code":       prior.get("scan_code"),
        "reversal_id":     prior.get("id"),
        "from_state":      prior.get("from_state"),
        "to_state":        prior.get("to_state"),
        "idempotency_key": prior.get("idempotency_key"),
    }
