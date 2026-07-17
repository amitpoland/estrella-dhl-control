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
    # Per-client shipment ownership.  One import batch is split into several
    # per-client proforma drafts (draft identity = (batch_id, client_name)); a
    # shipment belongs to exactly one client.  Nullable: legacy rows predate
    # this column and carry NULL — get_shipment_for_draft only attributes such
    # a row to a draft when the batch is unambiguously single-client.
    ("client_ref", "TEXT"),
    ("tracking_ref", "TEXT"),          # AWB / tracking number, written at COMPLETE
                                       # (2026-07-06 duplicate-AWB incident fix)
    # AWB logistics visibility — Proforma V2 Logistics tab summary fields
    ("weight_kg", "REAL"),
    ("declared_value", "REAL"),
    ("currency", "TEXT"),
    ("box_type_code", "TEXT"),         # Box Master profile chosen in the AWB modal
    # Local do-not-use control — an OPERATIONAL flag for duplicate/unused
    # labels. It is NOT a DHL cancellation/void (no DHL API call exists or is
    # made); the real AWB and its PDFs are preserved for audit.
    ("do_not_use", "INTEGER NOT NULL DEFAULT 0"),
    ("do_not_use_reason", "TEXT"),
    ("do_not_use_at", "TEXT"),
    ("do_not_use_by", "TEXT"),
    # Operator attribution (X-Operator) for the AWB booking. Written once at
    # the PENDING anchor insert and never mutated by a state transition, so the
    # audit trail always names the operator who initiated the real booking —
    # not whoever later replayed the idempotent request. NULL for legacy rows
    # booked before attribution existed (honest missing).
    ("booked_by", "TEXT"),
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


def insert_shipment(
    db_path: Path,
    result: ShipmentResult,
    batch_id: str,
    client_ref: Optional[str] = None,
    *,
    operator: Optional[str] = None,
) -> None:
    """
    Record a new shipment idempotency entry.

    Live mode results are rejected — AWBs must never appear in this table.
    tracking_ref is also absent from the schema for the same structural reason.

    client_ref (optional) scopes the row to a single client within the batch;
    None is stored for legacy/unscoped callers.

    operator (optional, keyword-only) is the X-Operator attribution for the
    booking, stored in booked_by. It is written ONLY at this PENDING anchor
    insert — state transitions never touch it — so the audit trail always names
    the operator who initiated the real booking, never a later replayer. None
    stores NULL (legacy/unattributed callers behave exactly as before).
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
                (idempotency_key, batch_id, client_ref, mode, state, error, simulated,
                 service_product, dimensions_json, booked_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.idempotency_key,
                batch_id,
                client_ref,
                result.mode.value,
                result.state.value,
                result.error,
                int(result.simulated),
                result.service_product,
                result.dimensions_json,
                operator,
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
    """Return the most recent shipment row for the given batch_id, or None.

    Batch-scoped — returns one row per batch regardless of client. Retained for
    internal/webhook correlation (batch_id ↔ tracking_ref) and legacy callers.
    For per-draft document resolution use get_shipment_for_draft, which never
    leaks one client's AWB onto another client's draft in the same batch.
    """
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM carrier_shipments WHERE batch_id = ? ORDER BY created_at DESC LIMIT 1",
            (batch_id,),
        ).fetchone()
    return dict(row) if row else None


def get_legacy_shipment(db_path: Path, batch_id: str) -> Optional[dict]:
    """Newest legacy (NULL client_ref) shipment row for the batch, or None.

    A legacy row predates client-scoped idempotency keys: a re-book of the
    same batch that now sends client_ref computes a NEW key, so the
    coordinator's completed-key replay will NOT match that row — a new
    shipment record (and, in live mode, a new carrier booking) would be
    created alongside it (ADR-proforma-cmr-short-number §Known limitation).

    Powers the booking-modal legacy-rebook warning ONLY. It is not a
    document-attribution path — that stays get_shipment_for_draft, which
    owns the per-client leak rules. 'failed' rows are excluded: a failed
    attempt is not a prior booking, and re-booking over one is the normal
    retry path. Read-only — never mutates state.
    """
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM carrier_shipments "
            "WHERE batch_id = ? AND client_ref IS NULL AND state != 'failed' "
            "ORDER BY created_at DESC LIMIT 1",
            (batch_id,),
        ).fetchone()
    return dict(row) if row else None


def get_client_shipment(
    db_path: Path, batch_id: str, client_ref: Optional[str]
) -> Optional[dict]:
    """Newest non-failed shipment row scoped to EXACTLY this client, or None.

    Companion to get_legacy_shipment: once a client-scoped row exists for the
    batch, a same-params re-book computes the SAME per-client idempotency key,
    so the coordinator replays (complete) or recovers (pending) that row — it
    does NOT create a new record alongside the legacy one. The booking-modal
    legacy-rebook warning is therefore suppressed when this returns a row
    (reviewer-challenge MEDIUM-2, 2026-07-16). The legacy row itself is
    deliberately never mutated — suppression is read-side only.

    'failed' rows are excluded for the opposite reason: a failed client-scoped
    attempt is NOT a prior booking (the coordinator refuses a same-key retry;
    a changed-params retry computes a new key and books for real), so the
    warning must still fire. Powers probe suppression ONLY — never a
    document-attribution path (that stays get_shipment_for_draft, which owns
    the per-client leak rules). Read-only — never mutates state.
    """
    if not (client_ref or "").strip():
        # An empty/blank ref must never match: '' != NULL in SQLite, and a
        # blank-scoped row would be a data bug, not a prior booking.
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM carrier_shipments "
            "WHERE batch_id = ? AND client_ref = ? AND state != 'failed' "
            "ORDER BY created_at DESC LIMIT 1",
            (batch_id, client_ref),
        ).fetchone()
    return dict(row) if row else None


def get_shipment_for_draft(
    db_path: Path,
    batch_id: str,
    client_ref: Optional[str] = None,
    *,
    allow_single_client_fallback: bool = False,
) -> Optional[dict]:
    """Resolve the carrier shipment that belongs to ONE client's draft.

    One import batch is split into several per-client proforma drafts. The
    carrier shipment belongs to exactly one client, so a draft must never be
    shown another client's AWB/CMR (2026-07-16 cross-client AWB contamination).

    Resolution order:
      1. Exact per-client match — the newest row with (batch_id, client_ref).
         This is the correct path for any shipment booked after client_ref was
         introduced.
      2. Legacy single-client fallback — only when *allow_single_client_fallback*
         is True (caller has proven the batch maps to exactly one client draft)
         AND exactly one shipment row exists for the batch. That single row is
         unambiguously this client's, even though it predates client_ref (NULL).
      3. Otherwise None (honest missing) — a multi-client batch with no exact
         per-client row must NOT fall back to "the latest batch row", which is
         precisely the contamination bug.

    Never mutates state — purely read-only.
    """
    with _connect(db_path) as conn:
        if client_ref:
            row = conn.execute(
                "SELECT * FROM carrier_shipments "
                "WHERE batch_id = ? AND client_ref = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (batch_id, client_ref),
            ).fetchone()
            if row:
                return dict(row)

        if allow_single_client_fallback:
            rows = conn.execute(
                "SELECT * FROM carrier_shipments WHERE batch_id = ? "
                "ORDER BY created_at DESC",
                (batch_id,),
            ).fetchall()
            if len(rows) == 1:
                row = dict(rows[0])
                # Defence-in-depth (independent of the caller's multi-client
                # gate): the fallback may attribute ONLY a legacy NULL-client_ref
                # row. A row scoped to a DIFFERENT client must never be returned
                # to this requestor — even if the outer gate misfires (e.g.
                # proforma_links.db path drift), the original cross-client leak
                # cannot recur (2026-07-16 independent-review POST-1).
                if (
                    row.get("client_ref")
                    and client_ref
                    and row["client_ref"] != client_ref
                ):
                    return None
                return row

    return None


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


def mark_do_not_use(
    db_path: Path,
    batch_id: str,
    tracking_ref: str,
    reason: str,
    operator: Optional[str] = None,
) -> int:
    """Mark every shipment row for (batch_id, tracking_ref) as do-not-use.

    Purely local operational status — never calls DHL, never changes the
    tracking_ref, state, or any booking field. Returns the number of rows
    marked (0 = no matching shipment).
    """
    if not (batch_id and tracking_ref and reason and reason.strip()):
        return 0
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE carrier_shipments
               SET do_not_use = 1,
                   do_not_use_reason = ?,
                   do_not_use_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                   do_not_use_by = ?,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
             WHERE batch_id = ? AND tracking_ref = ?
            """,
            (reason.strip(), operator, batch_id, tracking_ref),
        )
    return cur.rowcount


def get_do_not_use(db_path: Path, batch_id: str, tracking_ref: str) -> Optional[dict]:
    """Return the do-not-use flag fields for (batch_id, tracking_ref), or None.

    None means no shipment row exists for that pair (legacy rows without a
    stored tracking_ref are never matched — they cannot be marked).
    """
    if not (batch_id and tracking_ref):
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT do_not_use, do_not_use_reason, do_not_use_at, do_not_use_by
              FROM carrier_shipments
             WHERE batch_id = ? AND tracking_ref = ?
             ORDER BY do_not_use DESC LIMIT 1
            """,
            (batch_id, tracking_ref),
        ).fetchone()
    return dict(row) if row else None


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


def get_batch_by_tracking_ref(db_path: Path, tracking_ref: str) -> Optional[str]:
    """CW-1: resolve a DHL tracking number to its batch_id (read-only).

    Used by the carrier webhook at ingest time to correlate an inbound event
    with a shipment BEFORE log-safe stripping removes the tracking identifiers.
    Returns the most recent matching batch_id, or None.
    """
    ref = (tracking_ref or "").strip()
    if not ref or not Path(db_path).exists():
        return None
    try:
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute(
                "SELECT batch_id FROM carrier_shipments "
                "WHERE tracking_ref = ? ORDER BY rowid DESC LIMIT 1",
                (ref,),
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    return str(row[0]) if row and row[0] else None
