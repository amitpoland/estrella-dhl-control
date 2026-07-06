"""
Idempotency store and state tracker for carrier shipments.

Caller provides db_path — no global state, no app startup init required.
One row per idempotency_key. State transitions are the only allowed mutations.

tracking_ref: originally excluded by design ("labels live in the label
store"), but that invariant forced the coordinator to RE-INVOKE the adapter
on completed-key replay — which, for the live adapter, booked brand-new DHL
shipments (2026-07-06 duplicate-AWB incident, 3 duplicate live AWBs).
Superseded by operator decision 2026-07-06: tracking_ref IS persisted at
COMPLETE so replays return the stored result with zero adapter calls.
insert_shipment() still rejects LIVE-mode *inserts* — the pre-adapter
PENDING anchor row carries no AWB; the ref arrives only via update_state().
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

# Phase 5 — additive columns.  Separate from _DDL so older DBs can be
# migrated at init_db() time without recreating the table.
_ADDITIVE_COLUMNS = [
    ("service_product", "TEXT"),       # carrier service code (e.g. EXPRESS_WORLDWIDE)
    ("dimensions_json", "TEXT"),       # JSON snapshot of ShipmentRequest.dimensions
    ("tracking_ref", "TEXT"),          # AWB / tracking number, written at COMPLETE
                                       # (2026-07-06 duplicate-AWB incident fix)
    # AWB logistics visibility — Proforma V2 Logistics tab summary fields
    ("weight_kg", "REAL"),
    ("declared_value", "REAL"),
    ("currency", "TEXT"),
    ("box_type_code", "TEXT"),         # Box Master profile chosen in the AWB modal
]


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: Path) -> None:
    """Create the carrier_shipments table if it does not exist.

    Idempotent: additive ALTER TABLE for Phase-5 columns so existing DBs
    are migrated transparently.
    """
    with _connect(db_path) as conn:
        conn.executescript(_DDL)
        for col, ddl in _ADDITIVE_COLUMNS:
            try:
                conn.execute(
                    f"ALTER TABLE carrier_shipments ADD COLUMN {col} {ddl}"
                )
            except sqlite3.OperationalError as _exc:
                if "duplicate column" not in str(_exc).lower():
                    raise


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
                (idempotency_key, batch_id, mode, state, error, simulated,
                 service_product, dimensions_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.idempotency_key,
                batch_id,
                result.mode.value,
                result.state.value,
                result.error,
                int(result.simulated),
                result.service_product,
                result.dimensions_json,
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


def get_shipment_by_batch_id(db_path: Path, batch_id: str) -> Optional[dict]:
    """Return the most recent shipment row for the given batch_id, or None."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM carrier_shipments WHERE batch_id = ? ORDER BY created_at DESC LIMIT 1",
            (batch_id,),
        ).fetchone()
    return dict(row) if row else None


def update_state(
    db_path: Path,
    idempotency_key: str,
    state: ShipmentState,
    error: Optional[str] = None,
    *,
    tracking_ref: Optional[str] = None,
    mode: Optional[ShipmentMode] = None,
    simulated: Optional[bool] = None,
) -> None:
    """Advance the state of an existing shipment entry.

    At COMPLETE the coordinator also persists the adapter-truth fields
    (tracking_ref, mode, simulated) so a replay can return the stored
    result without re-invoking the adapter (2026-07-06 incident fix).
    Only non-None keyword fields are written.
    """
    sets = ["state = ?", "error = ?"]
    args: list = [state.value, error]
    if tracking_ref is not None:
        sets.append("tracking_ref = ?")
        args.append(tracking_ref)
    if mode is not None:
        sets.append("mode = ?")
        args.append(mode.value)
    if simulated is not None:
        sets.append("simulated = ?")
        args.append(int(simulated))
    sets.append("updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    args.append(idempotency_key)
    with _connect(db_path) as conn:
        conn.execute(
            f"UPDATE carrier_shipments SET {', '.join(sets)} WHERE idempotency_key = ?",
            tuple(args),
        )


def update_shipment_fields(
    db_path: Path,
    idempotency_key: str,
    *,
    service_product: Optional[str] = None,
    dimensions_json: Optional[str] = None,
    weight_kg: Optional[float] = None,
    declared_value: Optional[float] = None,
    currency: Optional[str] = None,
    box_type_code: Optional[str] = None,
) -> None:
    """Persist Phase-5 carrier API response fields on an existing row.

    Only writes non-None arguments.  A call with all None is a no-op.
    """
    sets, args = [], []
    if service_product is not None:
        sets.append("service_product = ?")
        args.append(service_product)
    if dimensions_json is not None:
        sets.append("dimensions_json = ?")
        args.append(dimensions_json)
    if weight_kg is not None:
        sets.append("weight_kg = ?")
        args.append(float(weight_kg))
    if declared_value is not None:
        sets.append("declared_value = ?")
        args.append(float(declared_value))
    if currency is not None:
        sets.append("currency = ?")
        args.append(currency)
    if box_type_code is not None:
        sets.append("box_type_code = ?")
        args.append(box_type_code)
    if not sets:
        return
    sets.append("updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    args.append(idempotency_key)
    with _connect(db_path) as conn:
        conn.execute(
            f"UPDATE carrier_shipments SET {', '.join(sets)} WHERE idempotency_key = ?",
            tuple(args),
        )
