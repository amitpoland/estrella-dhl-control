"""Move-stock service — location metadata writes only.

DOES NOT change inventory_state. Lifecycle state stays unchanged. The
piece must already be in WAREHOUSE_STOCK; transitions remain the
exclusive domain of inventory_state_engine (single-writer discipline,
per Doc 1 v2).

Idempotency strategy (Option A — Phase 4.5 remediation):
  - Database-level UNIQUE constraint on
    (scan_code, idempotency_key) WHERE idempotency_key != ''.
  - Writer INSERTs the event row; if the index catches a duplicate,
    sqlite3.IntegrityError fires inside record_scan_with_idempotency.
    We catch it, fetch the prior event by (scan_code, idempotency_key),
    and return the replay envelope.
  - NO app-level lock. The DB serialises concurrent writers via WAL +
    the UNIQUE constraint. Exactly one INSERT wins; the other gets
    the replay path.

Migration:
  service/app/db/migrations/draft_20260512_002516_idempotency_key.py.draft
  Must be applied to warehouse.db before this writer can run in
  production. The migration is idempotent and safe to re-run.

Side effects via record_scan_with_idempotency (action="MOVE"):
  • updates inventory_current_location (one row per scan_code)
  • appends inventory_movement_events with idempotency_key set
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict

from . import inventory_state_engine
from . import warehouse_db as wdb


WAREHOUSE_STOCK = inventory_state_engine.WAREHOUSE_STOCK


class MoveStockError(Exception):
    """Raised by move_piece() for guard-rail failures. Mapped to HTTP 4xx
    at the route layer. Never raised on missing piece (returns None
    instead) or on idempotent replay (returns prior result)."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _is_idempotency_violation(exc: sqlite3.IntegrityError) -> bool:
    """True iff the IntegrityError came from the partial UNIQUE index
    on (scan_code, idempotency_key). Other UNIQUE/NOT NULL violations
    on this table must surface as 500s (they would indicate corruption).
    """
    msg = str(exc).lower()
    return (
        "idx_movement_idempotency" in msg
        or ("unique" in msg and "idempotency_key" in msg)
    )


def move_piece(
    *,
    scan_code:        str,
    to_location:      str,
    operator:         str,
    idempotency_key:  str,
    note: str = "",
) -> Dict[str, Any]:
    """Move a piece to a new physical location.

    Raises MoveStockError on validation failure:
      - INVALID_INPUT       missing scan_code, to_location, operator, or key
      - PIECE_NOT_FOUND     scan_code unknown to inventory_state or packing_lines
      - WRONG_STATE         piece is not in WAREHOUSE_STOCK
      - DB_UNAVAILABLE      warehouse_db not initialised
    """
    if not scan_code:
        raise MoveStockError("INVALID_INPUT", "scan_code is required")
    if not to_location:
        raise MoveStockError("INVALID_INPUT", "to_location is required")
    if not operator:
        raise MoveStockError("INVALID_INPUT", "operator is required")
    if not idempotency_key:
        raise MoveStockError("INVALID_INPUT", "idempotency_key is required")

    if wdb._db_path is None:
        raise MoveStockError("DB_UNAVAILABLE", "warehouse_db not initialised")

    # 0. Migration precheck — column + index must exist BEFORE we issue
    #    the INSERT, otherwise SQLite raises OperationalError("no column
    #    named idempotency_key") which the writer's IntegrityError catch
    #    does NOT handle, propagating as a raw 500 with SQL text in the
    #    traceback. Fail fast and explicit instead.
    if not wdb.ensure_idempotency_schema():
        raise MoveStockError(
            "MIGRATION_PENDING",
            "idempotency_key migration not applied — endpoint disabled until "
            "operator runs the draft_20260512_002516_idempotency_key migration "
            "against warehouse.db",
        )

    # 1. State gate — piece must be in WAREHOUSE_STOCK (Doc 2 rule).
    #    Done BEFORE the write so we don't waste an insert+rollback
    #    on a piece that can't legally move.
    state_row = inventory_state_engine.get_state(scan_code)
    if state_row is None:
        raise MoveStockError(
            "PIECE_NOT_FOUND",
            f"scan_code {scan_code!r} not in inventory_state",
        )
    if state_row.get("state") != WAREHOUSE_STOCK:
        raise MoveStockError(
            "WRONG_STATE",
            f"piece is in {state_row.get('state')!r}, expected {WAREHOUSE_STOCK!r}",
        )

    # 2. Write attempt — UNIQUE constraint enforces idempotency.
    try:
        result = wdb.record_scan_with_idempotency(
            scan_code=scan_code,
            action="MOVE",
            to_location=to_location,
            operator=operator,
            idempotency_key=idempotency_key,
            note=note,
        )
    except sqlite3.IntegrityError as exc:
        if _is_idempotency_violation(exc):
            # Replay path: fetch the prior event and return the same
            # event_id so callers can dedupe deterministically.
            prior = wdb.find_movement_event_by_idempotency(
                scan_code, idempotency_key
            )
            current = wdb.get_current_location(scan_code) or {}
            return {
                "status": "replayed",
                "scan_code": scan_code,
                "to_location": to_location,
                "from_location": (prior or {}).get("from_location", ""),
                "event_id": (prior or {}).get("id"),
                "idempotency_key": idempotency_key,
                "current_location": current,
            }
        # Non-idempotency integrity error → not our domain; surface.
        raise

    if result is None:
        # record_scan_with_idempotency returns None when scan_code is
        # unknown to packing_lines (piece exists in inventory_state but
        # not in packing — data drift).
        raise MoveStockError(
            "PIECE_NOT_FOUND",
            f"scan_code {scan_code!r} not in packing_lines",
        )

    return {
        "status": "moved",
        "scan_code": scan_code,
        "to_location": to_location,
        "from_location": result.get("from_location", ""),
        "event_id": result.get("event_id"),
        "idempotency_key": idempotency_key,
        "current_location": result,
    }
