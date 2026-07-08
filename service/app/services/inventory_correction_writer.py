"""
inventory_correction_writer.py — Inventory Correction authority (Package A).

ONE writer for identity corrections (product_code / design_no / batch_id) on an
existing inventory_state row. Records the correction (who / when / old value /
new value / reason) in inventory_corrections and drives the identity fix
through the single state writer inventory_state_engine.correct_identity(). It
never writes inventory_state directly, never touches Product Master / Packing /
Sales, and never changes the piece's lifecycle state or inventory_state_events
— identity corrections are NOT lifecycle transitions.

Priority correction cases handled here (Engineering OS v1.1 Inventory
Correction package, Package A + D-identity slice):
    1. blank product_code
    2. wrong product_code
    3. wrong batch_id
    4. wrong design_no
Cases 5 (wrong location) and 6 (over-scan/duplicate) are handled by other
authorities — see propose_archive() below for case 6 (archive proposal only,
never a physical delete or inventory_state mutation).

Operator identity is supplied by the route from the authenticated session —
this module never accepts an anonymous / caller-free-text operator (the route's
resolver rejects that before calling here).
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

from . import inventory_state_engine
from . import warehouse_db as wdb


class CorrectionError(Exception):
    """Structured correction error. `code` maps to an HTTP status in the route."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def apply_identity_correction(
    *,
    scan_code:       str,
    operator:        str,
    reason:          str,
    idempotency_key: str,
    product_code:    Optional[str] = None,
    design_no:       Optional[str] = None,
    batch_id:        Optional[str] = None,
) -> Dict[str, Any]:
    """Correct product_code / design_no / batch_id for scan_code. Idempotent on
    (scan_code, idempotency_key).

    Raises CorrectionError(code) — INVALID_INPUT / DB_UNAVAILABLE /
    PIECE_NOT_FOUND — mapped to HTTP status by the route.
    """
    if not scan_code:
        raise CorrectionError("INVALID_INPUT", "scan_code is required")
    if not operator:
        # Defence in depth: the route resolves operator from the session and
        # rejects anonymous BEFORE calling here.
        raise CorrectionError("INVALID_INPUT", "operator is required (session-derived)")
    if not reason or not reason.strip():
        raise CorrectionError("INVALID_INPUT", "reason is required")
    if not idempotency_key:
        raise CorrectionError("INVALID_INPUT", "idempotency_key is required")
    if product_code is None and design_no is None and batch_id is None:
        raise CorrectionError(
            "INVALID_INPUT",
            "at least one of product_code/design_no/batch_id is required",
        )
    if wdb._db_path is None:
        raise CorrectionError("DB_UNAVAILABLE", "warehouse_db not initialised")

    # Idempotency pre-check BEFORE the piece lookup — a genuine replay is safe
    # to short-circuit even if, hypothetically, the piece state has since
    # changed underneath it (mirrors the QC writer's replay-first pattern).
    prior = wdb.find_correction_by_idempotency(scan_code, idempotency_key)
    if prior is not None:
        return _replay_result(prior)

    state_row = inventory_state_engine.get_state(scan_code)
    if state_row is None:
        raise CorrectionError("PIECE_NOT_FOUND", f"scan_code {scan_code!r} not in inventory_state")

    old_product_code = state_row.get("product_code") or ""
    old_design_no     = state_row.get("design_no") or ""
    old_batch_id      = state_row.get("batch_id") or ""

    # 1) Persist the correction record FIRST — its UNIQUE(scan_code,
    #    idempotency_key) index is the idempotency gate. A duplicate returns
    #    'replayed' WITHOUT a second identity write (replay safety).
    try:
        corr_row = wdb.record_correction(
            scan_code=scan_code,
            correction_type="identity",
            old_product_code=old_product_code,
            new_product_code=(product_code if product_code is not None else old_product_code),
            old_design_no=old_design_no,
            new_design_no=(design_no if design_no is not None else old_design_no),
            old_batch_id=old_batch_id,
            new_batch_id=(batch_id if batch_id is not None else old_batch_id),
            reason=reason,
            operator=operator,
            idempotency_key=idempotency_key,
        )
    except sqlite3.IntegrityError:
        prior = wdb.find_correction_by_idempotency(scan_code, idempotency_key)
        return _replay_result(prior or {})

    # 2) Single-writer identity change. correct_identity() raises ValueError
    #    if scan_code disappears between the lookup above and this call —
    #    surfaced as INVALID_INPUT. No direct inventory_state write here.
    try:
        inventory_state_engine.correct_identity(
            scan_code=scan_code,
            operator=operator,
            product_code=product_code,
            design_no=design_no,
            batch_id=batch_id,
        )
    except ValueError as exc:
        raise CorrectionError("INVALID_INPUT", str(exc)) from exc

    return {
        "status":          "corrected",
        "scan_code":       scan_code,
        "correction_id":   corr_row.get("id"),
        "idempotency_key": idempotency_key,
    }


def _replay_result(prior: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status":          "replayed",
        "scan_code":       prior.get("scan_code"),
        "correction_id":   prior.get("id"),
        "idempotency_key": prior.get("idempotency_key"),
    }


def propose_archive(
    *,
    scan_code:       str,
    operator:        str,
    reason:          str,
    idempotency_key: str,
) -> Dict[str, Any]:
    """Record an archive PROPOSAL for an over-scan / duplicate piece. This is
    a proposal only — it never mutates inventory_state and never performs a
    physical delete of any audit history. A supervisor/operator reviews the
    proposal out-of-band; this package does not auto-apply it.

    Raises CorrectionError(code) — INVALID_INPUT / DB_UNAVAILABLE /
    PIECE_NOT_FOUND.
    """
    if not scan_code:
        raise CorrectionError("INVALID_INPUT", "scan_code is required")
    if not operator:
        raise CorrectionError("INVALID_INPUT", "operator is required (session-derived)")
    if not reason or not reason.strip():
        raise CorrectionError("INVALID_INPUT", "reason is required")
    if not idempotency_key:
        raise CorrectionError("INVALID_INPUT", "idempotency_key is required")
    if wdb._db_path is None:
        raise CorrectionError("DB_UNAVAILABLE", "warehouse_db not initialised")

    prior = wdb.find_correction_by_idempotency(scan_code, idempotency_key)
    if prior is not None:
        return _replay_result(prior)

    state_row = inventory_state_engine.get_state(scan_code)
    if state_row is None:
        raise CorrectionError("PIECE_NOT_FOUND", f"scan_code {scan_code!r} not in inventory_state")

    try:
        corr_row = wdb.record_correction(
            scan_code=scan_code,
            correction_type="archive_proposal",
            reason=reason,
            operator=operator,
            idempotency_key=idempotency_key,
            status="proposed",
        )
    except sqlite3.IntegrityError:
        prior = wdb.find_correction_by_idempotency(scan_code, idempotency_key)
        return _replay_result(prior or {})

    return {
        "status":          "archive_proposed",
        "scan_code":       scan_code,
        "correction_id":   corr_row.get("id"),
        "idempotency_key": idempotency_key,
    }
