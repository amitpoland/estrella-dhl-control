"""Returns writer — Phase B.2.

Three public functions exposed via routes_inventory_returns:

  mark_returned_from_client()    — piece arrives back in warehouse RMA.
                                   Allowed predecessors:
                                     WAREHOUSE_STOCK, SAMPLE_OUT.
                                   (RETURNED_TO_PRODUCER → RFC is legal
                                   in the engine, but exposed only as
                                   an internal path — not a public route.)

  mark_returned_to_producer()    — piece is shipped back to producer.
                                   Allowed predecessors:
                                     WAREHOUSE_STOCK, RETURNED_FROM_CLIENT.

  return_from_producer_to_stock()— piece returns from producer rework
                                   into warehouse stock.
                                   Allowed predecessor:
                                     RETURNED_TO_PRODUCER.

ALL state changes route through `inventory_state_engine.transition()`
(single-writer discipline, same model as Sample-out — see
inventory_sample_writer.py:1-23). This writer:

  • validates inputs + evidence at the API boundary
  • checks DB precheck (warehouse_db.ensure_returns_schema)
  • delegates the state change to transition()
  • captures Returns-specific evidence via
    warehouse_db.record_returns_event()
  • catches sqlite3.IntegrityError from the partial UNIQUE index and
    returns the replay envelope with the SAME event_id

NEVER directly mutates inventory_state or inventory_state_events.

Idempotency contract:
  Caller supplies `idempotency_key`. The DB partial UNIQUE index on
  returns_events(scan_code, idempotency_key) WHERE key != '' enforces
  exactly-one-INSERT. On collision the writer returns status='replayed'
  with the prior event_id.

Migration:
  service/app/db/migrations/draft_20260512_175238_returns_events.py.draft
  must be applied before this writer can run in production.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict

from . import inventory_state_engine
from . import warehouse_db as wdb


WAREHOUSE_STOCK      = inventory_state_engine.WAREHOUSE_STOCK
SAMPLE_OUT           = inventory_state_engine.SAMPLE_OUT
RETURNED_FROM_CLIENT = inventory_state_engine.RETURNED_FROM_CLIENT
RETURNED_TO_PRODUCER = inventory_state_engine.RETURNED_TO_PRODUCER


class ReturnsError(Exception):
    """Raised for guard-rail failures. Mapped to HTTP 4xx/503 at the
    route layer. Never raised on replay (returns prior result instead)
    or on engine-level evidence rejection (those propagate as ValueError
    and are mapped separately)."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _is_returns_idempotency_violation(exc: sqlite3.IntegrityError) -> bool:
    """True iff the IntegrityError came from the partial UNIQUE index
    on (scan_code, idempotency_key) for returns_events."""
    msg = str(exc).lower()
    return (
        "idx_returns_idempotency" in msg
        or ("unique" in msg and "returns_events" in msg)
    )


def _common_preflight(
    *,
    scan_code:       str,
    operator:        str,
    idempotency_key: str,
) -> None:
    if not scan_code:
        raise ReturnsError("INVALID_INPUT", "scan_code is required")
    if not operator:
        raise ReturnsError("INVALID_INPUT", "operator is required")
    if not idempotency_key:
        raise ReturnsError("INVALID_INPUT", "idempotency_key is required")
    if wdb._db_path is None:
        raise ReturnsError("DB_UNAVAILABLE", "warehouse_db not initialised")
    if not wdb.ensure_returns_schema():
        raise ReturnsError(
            "MIGRATION_PENDING",
            "returns_events table/index missing — operator must run "
            "the draft_20260512_175238_returns_events migration",
        )


def mark_returned_from_client(
    *,
    scan_code:          str,
    operator:           str,
    return_reason:      str,
    origin_context:     str,
    received_at:        str,
    idempotency_key:    str,
    source_holder_name: str = "",
    notes:              str = "",
) -> Dict[str, Any]:
    """Move a piece WAREHOUSE_STOCK | SAMPLE_OUT → RETURNED_FROM_CLIENT.

    Raises ReturnsError for guard-rail failures:
      INVALID_INPUT, DB_UNAVAILABLE, MIGRATION_PENDING,
      PIECE_NOT_FOUND, WRONG_STATE.

    Engine-level evidence rejection (missing fields, bad reason, future
    received_at) propagates as ValueError from transition() — the route
    layer maps that to 400 INVALID_EVIDENCE.
    """
    _common_preflight(
        scan_code=scan_code,
        operator=operator,
        idempotency_key=idempotency_key,
    )

    state_row = inventory_state_engine.get_state(scan_code)
    if state_row is None:
        raise ReturnsError(
            "PIECE_NOT_FOUND",
            f"scan_code {scan_code!r} not in inventory_state",
        )
    current = state_row.get("state")
    if current not in (WAREHOUSE_STOCK, SAMPLE_OUT):
        raise ReturnsError(
            "WRONG_STATE",
            f"piece is in {current!r}; expected one of "
            f"{(WAREHOUSE_STOCK, SAMPLE_OUT)} to mark RETURNED_FROM_CLIENT",
        )

    # Write evidence first — partial UNIQUE serialises concurrent
    # writers; on collision we replay without touching the state engine.
    try:
        evt = wdb.record_returns_event(
            scan_code=scan_code,
            direction="from_client",
            operator=operator,
            source_holder_name=source_holder_name,
            return_reason=return_reason,
            received_at=received_at,
            notes=notes or origin_context,
            idempotency_key=idempotency_key,
        )
    except sqlite3.IntegrityError as exc:
        if _is_returns_idempotency_violation(exc):
            prior = wdb.find_returns_event_by_idempotency(
                scan_code, idempotency_key
            )
            return {
                "status":          "replayed",
                "scan_code":       scan_code,
                "direction":       "from_client",
                "event_id":        (prior or {}).get("id"),
                "idempotency_key": idempotency_key,
                "return_reason":   (prior or {}).get("return_reason", ""),
                "received_at":     (prior or {}).get("received_at", ""),
            }
        raise ReturnsError(
            "DB_CONSTRAINT",
            f"unexpected database constraint: {exc}",
        ) from exc

    # State transition — engine validates evidence again (defence in
    # depth). If transition rejects, the evidence row stays as part of
    # the audit trail; caller can investigate via event_id.
    inventory_state_engine.transition(
        scan_code=scan_code,
        to_state=RETURNED_FROM_CLIENT,
        operator=operator,
        return_reason=return_reason,
        origin_context=origin_context,
        received_at=received_at,
        source_holder_name=source_holder_name,
        note=notes,
    )

    return {
        "status":             "returned_from_client",
        "scan_code":          scan_code,
        "direction":          "from_client",
        "event_id":           evt.get("id"),
        "idempotency_key":    idempotency_key,
        "return_reason":      return_reason,
        "source_holder_name": source_holder_name,
        "received_at":        received_at,
    }


def mark_returned_to_producer(
    *,
    scan_code:                str,
    operator:                 str,
    producer_name:            str,
    idempotency_key:          str,
    return_reason:            str = "",
    dispatch_reference:       str = "",
    producer_id:              str = "",
    expected_resolution_date: str = "",
    notes:                    str = "",
) -> Dict[str, Any]:
    """Move a piece WAREHOUSE_STOCK | RETURNED_FROM_CLIENT
    → RETURNED_TO_PRODUCER.

    Requires producer_name, plus either return_reason or
    dispatch_reference (engine enforces this).
    """
    _common_preflight(
        scan_code=scan_code,
        operator=operator,
        idempotency_key=idempotency_key,
    )

    state_row = inventory_state_engine.get_state(scan_code)
    if state_row is None:
        raise ReturnsError(
            "PIECE_NOT_FOUND",
            f"scan_code {scan_code!r} not in inventory_state",
        )
    current = state_row.get("state")
    if current not in (WAREHOUSE_STOCK, RETURNED_FROM_CLIENT):
        raise ReturnsError(
            "WRONG_STATE",
            f"piece is in {current!r}; expected one of "
            f"{(WAREHOUSE_STOCK, RETURNED_FROM_CLIENT)} "
            f"to mark RETURNED_TO_PRODUCER",
        )

    try:
        evt = wdb.record_returns_event(
            scan_code=scan_code,
            direction="to_producer",
            operator=operator,
            producer_name=producer_name,
            producer_id=producer_id,
            return_reason=return_reason,
            expected_resolution_date=expected_resolution_date,
            dispatch_reference=dispatch_reference,
            notes=notes,
            idempotency_key=idempotency_key,
        )
    except sqlite3.IntegrityError as exc:
        if _is_returns_idempotency_violation(exc):
            prior = wdb.find_returns_event_by_idempotency(
                scan_code, idempotency_key
            )
            return {
                "status":          "replayed",
                "scan_code":       scan_code,
                "direction":       "to_producer",
                "event_id":        (prior or {}).get("id"),
                "idempotency_key": idempotency_key,
                "producer_name":   (prior or {}).get("producer_name", ""),
            }
        raise ReturnsError(
            "DB_CONSTRAINT",
            f"unexpected database constraint: {exc}",
        ) from exc

    inventory_state_engine.transition(
        scan_code=scan_code,
        to_state=RETURNED_TO_PRODUCER,
        operator=operator,
        producer_name=producer_name,
        return_reason=return_reason,
        dispatch_reference=dispatch_reference,
        expected_resolution_date=expected_resolution_date,
        note=notes,
    )

    return {
        "status":             "returned_to_producer",
        "scan_code":          scan_code,
        "direction":          "to_producer",
        "event_id":           evt.get("id"),
        "idempotency_key":    idempotency_key,
        "producer_name":      producer_name,
        "return_reason":      return_reason,
        "dispatch_reference": dispatch_reference,
    }


def return_from_producer_to_stock(
    *,
    scan_code:       str,
    operator:        str,
    idempotency_key: str,
    notes:           str = "",
) -> Dict[str, Any]:
    """Move a piece RETURNED_TO_PRODUCER → WAREHOUSE_STOCK.

    Producer has shipped the piece back (repaired / replaced); the
    operator restocks it. No additional evidence required beyond the
    transition itself — the audit-chain link to the originating
    `to_producer` event is captured in returns_events via the
    `direction='producer_restock'` row.
    """
    _common_preflight(
        scan_code=scan_code,
        operator=operator,
        idempotency_key=idempotency_key,
    )

    state_row = inventory_state_engine.get_state(scan_code)
    if state_row is None:
        raise ReturnsError(
            "PIECE_NOT_FOUND",
            f"scan_code {scan_code!r} not in inventory_state",
        )
    current = state_row.get("state")
    if current != RETURNED_TO_PRODUCER:
        raise ReturnsError(
            "WRONG_STATE",
            f"piece is in {current!r}, expected {RETURNED_TO_PRODUCER!r}",
        )

    try:
        evt = wdb.record_returns_event(
            scan_code=scan_code,
            direction="producer_restock",
            operator=operator,
            notes=notes,
            idempotency_key=idempotency_key,
        )
    except sqlite3.IntegrityError as exc:
        if _is_returns_idempotency_violation(exc):
            prior = wdb.find_returns_event_by_idempotency(
                scan_code, idempotency_key
            )
            return {
                "status":          "replayed",
                "scan_code":       scan_code,
                "direction":       "producer_restock",
                "event_id":        (prior or {}).get("id"),
                "idempotency_key": idempotency_key,
            }
        raise ReturnsError(
            "DB_CONSTRAINT",
            f"unexpected database constraint: {exc}",
        ) from exc

    inventory_state_engine.transition(
        scan_code=scan_code,
        to_state=WAREHOUSE_STOCK,
        operator=operator,
        note=notes,
    )

    return {
        "status":          "returned_from_producer_to_stock",
        "scan_code":       scan_code,
        "direction":       "producer_restock",
        "event_id":        evt.get("id"),
        "idempotency_key": idempotency_key,
    }
