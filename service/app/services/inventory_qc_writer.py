"""
inventory_qc_writer.py — Returns QC Disposition authority (Phase 2).

ONE writer for the QC disposition of a client-returned piece. It records the
inspection outcome (condition / inspector / decision) in returns_qc_disposition
and drives the piece's lifecycle transition — through the single state writer
inventory_state_engine.transition(). It never writes inventory_state directly,
never touches Product Master / Packing / Sales, and NEVER performs an accounting
or wFirma side effect (a write-off is an inventory disposition only).

Decision → transition (only legal from RETURNED_FROM_CLIENT):
    restock   → WAREHOUSE_STOCK
    repair    → RETURNED_TO_PRODUCER
    write_off → WRITTEN_OFF   (terminal, never reopens)

Operator identity is supplied by the route from the authenticated session —
this module never accepts an anonymous / caller-free-text operator (the route's
resolver rejects that before calling here).
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict

from . import inventory_state_engine
from . import warehouse_db as wdb

RETURNED_FROM_CLIENT = inventory_state_engine.RETURNED_FROM_CLIENT
WAREHOUSE_STOCK      = inventory_state_engine.WAREHOUSE_STOCK
RETURNED_TO_PRODUCER = inventory_state_engine.RETURNED_TO_PRODUCER
WRITTEN_OFF          = inventory_state_engine.WRITTEN_OFF

# decision → target lifecycle state
_DECISION_TO_STATE: Dict[str, str] = {
    "restock":   WAREHOUSE_STOCK,
    "repair":    RETURNED_TO_PRODUCER,
    "write_off": WRITTEN_OFF,
}


class QCError(Exception):
    """Structured QC-disposition error. `code` maps to an HTTP status in the route."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


# QC 'repair' routes to RETURNED_TO_PRODUCER, whose engine evidence contract
# requires a structured reason. A QC repair IS a post-inspection reject.
_REPAIR_RETURN_REASON = "post_inspection_reject"


def apply_qc_disposition(
    *,
    scan_code:          str,
    decision:           str,
    operator:           str,
    idempotency_key:    str,
    condition:          str = "",
    inspector:          str = "",
    notes:              str = "",
    producer_name:      str = "",
    dispatch_reference: str = "",
) -> Dict[str, Any]:
    """Record a QC disposition for a RETURNED_FROM_CLIENT piece and drive its
    lifecycle transition. Idempotent on (scan_code, idempotency_key).

    Raises QCError(code) — INVALID_INPUT / DB_UNAVAILABLE / PIECE_NOT_FOUND /
    WRONG_STATE — mapped to HTTP status by the route.
    """
    if not scan_code:
        raise QCError("INVALID_INPUT", "scan_code is required")
    if not operator:
        # Defence in depth: the route resolves operator from the session and
        # rejects anonymous BEFORE calling here. This guard makes the writer
        # itself refuse an empty operator — no anonymous QC writes, ever.
        raise QCError("INVALID_INPUT", "operator is required (session-derived)")
    if not idempotency_key:
        raise QCError("INVALID_INPUT", "idempotency_key is required")
    if decision not in _DECISION_TO_STATE:
        raise QCError(
            "INVALID_INPUT",
            f"decision must be one of {sorted(_DECISION_TO_STATE)}, got {decision!r}",
        )
    if decision == "repair" and not (producer_name or "").strip():
        # RETURNED_TO_PRODUCER cannot be reached without a producer to send to —
        # surfaced honestly rather than faking a producer.
        raise QCError(
            "INVALID_INPUT",
            "producer_name is required for a 'repair' disposition "
            "(the piece is routed to that producer)",
        )
    if wdb._db_path is None:
        raise QCError("DB_UNAVAILABLE", "warehouse_db not initialised")

    # Idempotency pre-check BEFORE the state gate: a genuine replay arrives after
    # the piece has already left RETURNED_FROM_CLIENT, so the state check would
    # wrongly reject it. If this (piece, key) was already disposed, replay now.
    prior = wdb.find_qc_disposition_by_idempotency(scan_code, idempotency_key)
    if prior is not None:
        return {
            "status":          "replayed",
            "scan_code":       scan_code,
            "decision":        prior.get("decision", decision),
            "to_state":        _DECISION_TO_STATE.get(prior.get("decision", decision)),
            "qc_id":           prior.get("id"),
            "idempotency_key": idempotency_key,
        }

    state_row = inventory_state_engine.get_state(scan_code)
    if state_row is None:
        raise QCError("PIECE_NOT_FOUND", f"scan_code {scan_code!r} not in inventory_state")
    current = state_row.get("state")
    if current != RETURNED_FROM_CLIENT:
        raise QCError(
            "WRONG_STATE",
            f"QC disposition requires state {RETURNED_FROM_CLIENT!r}; "
            f"piece is in {current!r}",
        )

    to_state = _DECISION_TO_STATE[decision]

    # 1) Persist the QC record FIRST — its UNIQUE(piece_id, idempotency_key)
    #    index is the idempotency gate. A duplicate returns 'replayed' WITHOUT
    #    a second state transition (replay safety).
    try:
        qc_row = wdb.record_qc_disposition(
            piece_id=scan_code,
            decision=decision,
            operator=operator,
            idempotency_key=idempotency_key,
            condition=condition,
            inspector=inspector,
            notes=notes,
            producer_name=producer_name,
            dispatch_reference=dispatch_reference,
        )
    except sqlite3.IntegrityError:
        prior = wdb.find_qc_disposition_by_idempotency(scan_code, idempotency_key)
        return {
            "status":          "replayed",
            "scan_code":       scan_code,
            "decision":        (prior or {}).get("decision", decision),
            "to_state":        _DECISION_TO_STATE.get((prior or {}).get("decision", decision)),
            "qc_id":           (prior or {}).get("id"),
            "idempotency_key": idempotency_key,
        }

    # 2) Single-writer lifecycle change. transition() validates legality
    #    (RETURNED_FROM_CLIENT → to_state) and raises ValueError if illegal —
    #    that surfaces as WRONG_STATE. No direct inventory_state write here.
    _extra = {}
    if to_state == RETURNED_TO_PRODUCER:
        # Satisfy the engine's RETURNED_TO_PRODUCER evidence contract from QC
        # context (a repair is a post-inspection reject to a named producer).
        _extra = {
            "producer_name":  producer_name,
            "return_reason":  _REPAIR_RETURN_REASON,
            "dispatch_reference": dispatch_reference,
        }
    try:
        inventory_state_engine.transition(
            scan_code=scan_code,
            to_state=to_state,
            operator=operator,
            note=notes or f"QC {decision}",
            **_extra,
        )
    except ValueError as exc:
        raise QCError("WRONG_STATE", str(exc)) from exc

    return {
        "status":          "qc_disposed",
        "scan_code":       scan_code,
        "decision":        decision,
        "to_state":        to_state,
        "qc_id":           qc_row.get("id"),
        "idempotency_key": idempotency_key,
    }
