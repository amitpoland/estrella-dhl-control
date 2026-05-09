"""
Idempotency store and state tracker for carrier shipments.

Caller provides db_path — no global state, no app startup init required.
One row per idempotency_key. State transitions are the only allowed mutations.

Structural invariant: tracking_ref (real AWB) is intentionally absent from
this table. Live AWBs must never be persisted here — they belong in the
secure label store (Phase D). Shadow simulated refs are also excluded for
the same schema reason: the idempotency store tracks *state*, not labels.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from ..models.shipment import ShipmentMode, ShipmentResult, ShipmentState

_DDL = """
CREATE TABLE IF NOT EXISTS carrier_shipments (
    idempotency_key TEXT PRIMARY KEY,
    batch_id        TEXT NOT NULL,
    mode            TEXT NOT NULL CHECK(mode IN ('shadow', 'live')),
    state           TEXT NOT NULL CHECK(state IN ('pending', 'submitted', 'complete', 'failed')),
    error           TEXT,
    simulated       INTEGER NOT NULL DEFAULT 0 CHECK(simulated IN (0, 1)),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: Path) -> None:
    """Create the carrier_shipments table if it does not exist."""
    with _connect(db_path) as conn:
        conn.executescript(_DDL)


def insert_shipment(db_path: Path, result: ShipmentResult, batch_id: str) -> None:
    """
    Record a new shipment idempotency entry.

    Live mode results are rejected — AWBs must never appear in this table.
    tracking_ref is also absent from the schema for the same structural reason.
    """
    if result.mode == ShipmentMode.LIVE:
        raise ValueError(
            "Live shipment results must not be inserted into carrier_shipments DB. "
            "AWB references are stored in the secure label store only."
        )
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO carrier_shipments
                (idempotency_key, batch_id, mode, state, error, simulated)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                result.idempotency_key,
                batch_id,
                result.mode.value,
                result.state.value,
                result.error,
                int(result.simulated),
            ),
        )


def exists(db_path: Path, idempotency_key: str) -> bool:
    """Return True if an entry exists for the given idempotency key."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM carrier_shipments WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
    return row is not None


def get_shipment(db_path: Path, idempotency_key: str) -> Optional[dict]:
    """Return the shipment row as a plain dict, or None if not found."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM carrier_shipments WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
    return dict(row) if row else None


def update_state(
    db_path: Path,
    idempotency_key: str,
    state: ShipmentState,
    error: Optional[str] = None,
) -> None:
    """Advance the state of an existing shipment entry."""
    with _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE carrier_shipments
            SET state      = ?,
                error      = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE idempotency_key = ?
            """,
            (state.value, error, idempotency_key),
        )
