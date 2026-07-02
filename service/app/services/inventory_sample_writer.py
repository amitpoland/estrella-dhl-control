"""Sample-out writer — Phase B.1.

First inventory write that mutates lifecycle truth. ALL state changes go
through `inventory_state_engine.transition()` (single-writer discipline,
per Doc 1 v2 + SAMPLE_OUT_DESIGN.md §1). This writer:

  • validates inputs + evidence at the API boundary
  • checks DB precheck (warehouse_db.ensure_sample_out_schema)
  • checks recipient-overdue block (30d rule per §8)
  • delegates the state change to inventory_state_engine.transition()
  • captures Sample-out-specific evidence via
    warehouse_db.record_sample_out_event()
  • catches sqlite3.IntegrityError from the partial UNIQUE index and
    returns the replay envelope with the SAME event_id

NEVER directly mutates inventory_state or inventory_state_events.

Idempotency contract:
  Caller supplies `idempotency_key`. The DB partial UNIQUE index on
  sample_out_events(scan_code, idempotency_key) WHERE key != '' enforces
  exactly-one-INSERT. On collision the writer returns status='replayed'
  with the prior event_id.

Migration:
  service/app/db/migrations/draft_20260512_122327_sample_out_events.py.draft
  must be applied before this writer can run in production.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from . import inventory_state_engine
from . import warehouse_db as wdb


WAREHOUSE_STOCK = inventory_state_engine.WAREHOUSE_STOCK
SAMPLE_OUT      = inventory_state_engine.SAMPLE_OUT
RECIPIENT_OVERDUE_DAYS = 30  # §8.3 — block new sample-outs after 30d overdue


class SampleOutError(Exception):
    """Raised for guard-rail failures. Mapped to HTTP 4xx/503 at the
    route layer. Never raised on replay (returns prior result instead)
    or on engine-level evidence rejection (those propagate as ValueError
    and are mapped separately)."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _is_sample_idempotency_violation(exc: sqlite3.IntegrityError) -> bool:
    """True iff the IntegrityError came from the partial UNIQUE index
    on (scan_code, idempotency_key) for sample_out_events."""
    msg = str(exc).lower()
    return (
        "idx_sample_out_idempotency" in msg
        or ("unique" in msg and "sample_out_events" in msg)
    )


def _common_preflight(
    *,
    scan_code:       str,
    operator:        str,
    idempotency_key: str,
) -> None:
    if not scan_code:
        raise SampleOutError("INVALID_INPUT", "scan_code is required")
    if not operator:
        raise SampleOutError("INVALID_INPUT", "operator is required")
    if not idempotency_key:
        raise SampleOutError("INVALID_INPUT", "idempotency_key is required")
    if wdb._db_path is None:
        raise SampleOutError("DB_UNAVAILABLE", "warehouse_db not initialised")
    if not wdb.ensure_sample_out_schema():
        raise SampleOutError(
            "MIGRATION_PENDING",
            "sample_out_events table/index missing — operator must run "
            "the draft_20260512_122327_sample_out_events migration",
        )


def sample_out(
    *,
    scan_code:             str,
    operator:              str,
    recipient_client_name: str,
    expected_return_date:  str,
    sample_reason:         str,
    idempotency_key:       str,
    recipient_client_id:   str = "",
    notes:                 str = "",
) -> Dict[str, Any]:
    """Move a piece WAREHOUSE_STOCK → SAMPLE_OUT.

    Raises SampleOutError for guard-rail failures:
      INVALID_INPUT, DB_UNAVAILABLE, MIGRATION_PENDING,
      PIECE_NOT_FOUND, WRONG_STATE, RECIPIENT_OVERDUE_BLOCK.

    Engine-level evidence rejection (missing recipient, bad reason,
    past expected_return_date) propagates as ValueError from
    transition() — the route layer maps that to 400 INVALID_EVIDENCE.
    """
    _common_preflight(
        scan_code=scan_code,
        operator=operator,
        idempotency_key=idempotency_key,
    )

    # State-gate — piece must be in WAREHOUSE_STOCK BEFORE we attempt
    # any write. This is also enforced by transition() via LEGAL_TRANSITIONS,
    # but checking here lets us return a clean 409 with no engine churn.
    state_row = inventory_state_engine.get_state(scan_code)
    if state_row is None:
        raise SampleOutError(
            "PIECE_NOT_FOUND",
            f"scan_code {scan_code!r} not in inventory_state",
        )
    current = state_row.get("state")
    if current != WAREHOUSE_STOCK:
        raise SampleOutError(
            "WRONG_STATE",
            f"piece is in {current!r}, expected {WAREHOUSE_STOCK!r}",
        )

    # Recipient-overdue block — §8.3, 30-day rule. If this recipient has
    # any open sample whose expected_return_date is 30+ days in the past,
    # reject new sample-outs to the same recipient.
    threshold = (
        datetime.now(timezone.utc) - timedelta(days=RECIPIENT_OVERDUE_DAYS)
    ).isoformat()
    overdue_count = wdb.count_open_overdue_samples_for_recipient(
        recipient_client_name, threshold
    )
    if overdue_count > 0:
        raise SampleOutError(
            "RECIPIENT_OVERDUE_BLOCK",
            f"recipient {recipient_client_name!r} has {overdue_count} "
            f"open sample(s) overdue by {RECIPIENT_OVERDUE_DAYS}+ days; "
            "return the overdue piece(s) before issuing new samples",
        )

    # Write attempt — capture evidence first via the DB UNIQUE on
    # (scan_code, idempotency_key). On collision we replay without
    # touching the state engine.
    try:
        evt = wdb.record_sample_out_event(
            scan_code=scan_code,
            direction="out",
            operator=operator,
            recipient_client_name=recipient_client_name,
            recipient_client_id=recipient_client_id,
            sample_reason=sample_reason,
            expected_return_date=expected_return_date,
            notes=notes,
            idempotency_key=idempotency_key,
        )
    except sqlite3.IntegrityError as exc:
        if _is_sample_idempotency_violation(exc):
            prior = wdb.find_sample_out_event_by_idempotency(
                scan_code, idempotency_key
            )
            return {
                "status": "replayed",
                "scan_code": scan_code,
                "direction": "out",
                "event_id": (prior or {}).get("id"),
                "idempotency_key": idempotency_key,
                "recipient_client_name": (prior or {}).get(
                    "recipient_client_name", ""
                ),
                "expected_return_date": (prior or {}).get(
                    "expected_return_date", ""
                ),
            }
        raise

    # State transition — delegated to the engine. Engine validates
    # evidence again (defence-in-depth: a future caller that bypasses
    # this writer still can't get into SAMPLE_OUT without evidence).
    try:
        inventory_state_engine.transition(
            scan_code=scan_code,
            to_state=SAMPLE_OUT,
            operator=operator,
            recipient_client_name=recipient_client_name,
            expected_return_date=expected_return_date,
            sample_reason=sample_reason,
            note=notes,
        )
    except ValueError:
        # Engine rejected the transition (evidence or legality). The
        # sample_out_events row was already written; route layer will
        # surface a 400 INVALID_EVIDENCE. We do NOT roll back the event
        # row — it's part of the audit trail showing the attempt.
        # Caller can investigate via the event_id.
        raise

    return {
        "status": "sampled_out",
        "scan_code": scan_code,
        "direction": "out",
        "event_id": evt.get("id"),
        "idempotency_key": idempotency_key,
        "recipient_client_name": recipient_client_name,
        "expected_return_date": expected_return_date,
        "sample_reason": sample_reason,
    }


def sample_return(
    *,
    scan_code:       str,
    operator:        str,
    idempotency_key: str,
    notes:           str = "",
) -> Dict[str, Any]:
    """Move a piece SAMPLE_OUT → WAREHOUSE_STOCK.

    Raises SampleOutError for guard-rail failures:
      INVALID_INPUT, DB_UNAVAILABLE, MIGRATION_PENDING,
      PIECE_NOT_FOUND, WRONG_STATE, NO_OPEN_SAMPLE_OUT.
    """
    _common_preflight(
        scan_code=scan_code,
        operator=operator,
        idempotency_key=idempotency_key,
    )

    state_row = inventory_state_engine.get_state(scan_code)
    if state_row is None:
        raise SampleOutError(
            "PIECE_NOT_FOUND",
            f"scan_code {scan_code!r} not in inventory_state",
        )
    current = state_row.get("state")
    if current != SAMPLE_OUT:
        raise SampleOutError(
            "WRONG_STATE",
            f"piece is in {current!r}, expected {SAMPLE_OUT!r}",
        )

    # Find originating 'out' event for audit chain continuity.
    origin = wdb.find_origin_sample_out_event(scan_code)
    if origin is None:
        # Piece is in SAMPLE_OUT but no matching 'out' event. This is a
        # data-integrity inconsistency — refuse to return without an
        # origin to link to. Operator-side triage required.
        raise SampleOutError(
            "NO_OPEN_SAMPLE_OUT",
            f"scan_code {scan_code!r} is in SAMPLE_OUT but no open "
            "sample_out_events row exists; data integrity check needed",
        )
    origin_id = origin.get("id", "")

    # Write attempt — same DB UNIQUE replay pattern as sample_out.
    try:
        evt = wdb.record_sample_out_event(
            scan_code=scan_code,
            direction="return",
            operator=operator,
            notes=notes,
            idempotency_key=idempotency_key,
            linked_origin_event_id=origin_id,
        )
    except sqlite3.IntegrityError as exc:
        if _is_sample_idempotency_violation(exc):
            prior = wdb.find_sample_out_event_by_idempotency(
                scan_code, idempotency_key
            )
            return {
                "status": "replayed",
                "scan_code": scan_code,
                "direction": "return",
                "event_id": (prior or {}).get("id"),
                "idempotency_key": idempotency_key,
                "linked_origin_event_id": (prior or {}).get(
                    "linked_origin_event_id", ""
                ),
            }
        raise

    # State transition — back to WAREHOUSE_STOCK. No evidence gate on
    # this side (transition rules allow SAMPLE_OUT → WAREHOUSE_STOCK
    # unconditionally; we just need operator + scan_code).
    # Direct transition BY DESIGN — a sample RETURN to stock is not a
    # Temp Warehouse → Final Stock promotion: no Stock Promotion Note
    # (PROJECT_STATE DECISIONS "BE-2b" boundary).
    inventory_state_engine.transition(
        scan_code=scan_code,
        to_state=WAREHOUSE_STOCK,
        operator=operator,
        note=notes,
    )

    return {
        "status": "returned",
        "scan_code": scan_code,
        "direction": "return",
        "event_id": evt.get("id"),
        "idempotency_key": idempotency_key,
        "linked_origin_event_id": origin_id,
    }
