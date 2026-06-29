"""
wFirma webhook processing state and invoice snapshot store (Phase 2A.1).

Both tables live in wfirma_processing.db — completely separate from the
immutable Phase 1 event log (wfirma_webhook_events.db). Phase 1 table is
never touched here.

Tables
------
wfirma_webhook_processing
    Lazy-created per event (INSERT OR IGNORE) on first scheduler pick-up.
    Tracks processing state + one timestamp column per stage.

wfirma_invoice_snapshots
    Immutable, append-only. One row per event (event_id UNIQUE).
    Multiple snapshots per object_id are expected — versioned by COUNT.

Design rules
------------
- Never ALTER wfirma_webhook_events.
- INSERT OR IGNORE everywhere for idempotency.
- No writes to proforma_drafts, wfirma.db, or any other business table.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_RETRIES = 3

_DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS wfirma_webhook_processing (
    event_id          TEXT PRIMARY KEY,
    object_id         TEXT,
    processing_state  TEXT NOT NULL DEFAULT 'RECEIVED',
    retry_count       INTEGER NOT NULL DEFAULT 0,
    received_at       TEXT,
    fetch_pending_at  TEXT,
    fetching_at       TEXT,
    fetched_at        TEXT,
    snapshotted_at    TEXT,
    completed_at      TEXT,
    failed_at         TEXT,
    dead_letter_at    TEXT,
    last_error        TEXT,
    last_attempted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_proc_state
    ON wfirma_webhook_processing (processing_state);

CREATE TABLE IF NOT EXISTS wfirma_invoice_snapshots (
    snapshot_id    TEXT PRIMARY KEY,
    event_id       TEXT NOT NULL UNIQUE,
    object_id      TEXT NOT NULL,
    version        INTEGER NOT NULL DEFAULT 1,
    invoice_number TEXT,
    document_type  TEXT,
    currency       TEXT,
    net_amount     TEXT,
    gross_amount   TEXT,
    vat_amount     TEXT,
    issue_date     TEXT,
    sale_date      TEXT,
    payment_due    TEXT,
    payment_method TEXT,
    status         TEXT,
    fetched_at     TEXT NOT NULL,
    raw_xml        TEXT NOT NULL,
    parsed_json    TEXT NOT NULL,
    raw_payload    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snap_event  ON wfirma_invoice_snapshots (event_id);
CREATE INDEX IF NOT EXISTS idx_snap_object ON wfirma_invoice_snapshots (object_id);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _apply_phase2b_migration(conn: sqlite3.Connection) -> None:
    """
    Add Phase 2B enrichment timestamp columns to wfirma_webhook_processing.
    Idempotent — safe to call on an already-migrated database.
    """
    new_cols = [
        "matched_at   TEXT",
        "enriched_at  TEXT",
        "unmatched_at TEXT",
    ]
    for col_def in new_cols:
        col_name = col_def.split()[0]
        try:
            conn.execute(
                f"ALTER TABLE wfirma_webhook_processing ADD COLUMN {col_def}"
            )
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise


def init_db(db_path: Path) -> None:
    """Create both tables and indexes if they do not exist."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript(_DDL)
        _apply_phase2b_migration(conn)


# ── Processing table ───────────────────────────────────────────────────────────


def ensure_processing_row(
    db_path: Path,
    event_id: str,
    object_id: Optional[str],
    received_at: str,
) -> bool:
    """
    Create a processing row for event_id with state=RECEIVED if one does not exist.
    Returns True if inserted (new event), False if the row already existed.
    """
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO wfirma_webhook_processing
                (event_id, object_id, processing_state, received_at)
            VALUES (?, ?, 'RECEIVED', ?)
            """,
            (event_id, object_id, received_at),
        )
    return cur.rowcount == 1


def get_processable_events(db_path: Path, limit: int = 10) -> List[dict]:
    """
    Return up to `limit` rows in RECEIVED or RETRY_PENDING state
    whose retry_count is below MAX_RETRIES, ordered oldest-first.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT event_id, object_id, processing_state, retry_count
            FROM wfirma_webhook_processing
            WHERE processing_state IN ('RECEIVED', 'RETRY_PENDING')
              AND retry_count < ?
            ORDER BY received_at ASC
            LIMIT ?
            """,
            (MAX_RETRIES, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def set_state(
    db_path: Path,
    event_id: str,
    state: str,
    *,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Update processing_state and any additional columns supplied in `extra`.

    Example::
        set_state(db, eid, "COMPLETED", extra={"completed_at": now, "fetched_at": now})
    """
    assignments = ["processing_state = ?"]
    params: list = [state]
    if extra:
        for col, val in extra.items():
            assignments.append(f"{col} = ?")
            params.append(val)
    params.append(event_id)
    with _connect(db_path) as conn:
        conn.execute(
            f"UPDATE wfirma_webhook_processing SET {', '.join(assignments)} WHERE event_id = ?",
            params,
        )


def increment_retry(db_path: Path, event_id: str, error: str, now: str) -> int:
    """
    Increment retry_count, record last_error + timestamps, set state=FAILED.
    Returns the new retry_count.
    """
    with _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE wfirma_webhook_processing
            SET retry_count       = retry_count + 1,
                processing_state  = 'FAILED',
                last_error        = ?,
                last_attempted_at = ?,
                failed_at         = ?
            WHERE event_id = ?
            """,
            (error[:500], now, now, event_id),
        )
        row = conn.execute(
            "SELECT retry_count FROM wfirma_webhook_processing WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    return int(row["retry_count"]) if row else 0


def mark_dead_letter(db_path: Path, event_id: str, now: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE wfirma_webhook_processing
            SET processing_state = 'DEAD_LETTER', dead_letter_at = ?
            WHERE event_id = ?
            """,
            (now, event_id),
        )


def mark_retry_pending(db_path: Path, event_id: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE wfirma_webhook_processing SET processing_state = 'RETRY_PENDING' WHERE event_id = ?",
            (event_id,),
        )


# ── Snapshot table ─────────────────────────────────────────────────────────────


def _next_version(conn: sqlite3.Connection, object_id: str) -> int:
    """Count existing snapshots for this object_id and return the next version number."""
    row = conn.execute(
        "SELECT COUNT(*) FROM wfirma_invoice_snapshots WHERE object_id = ?",
        (object_id,),
    ).fetchone()
    return (row[0] if row else 0) + 1


def insert_snapshot(
    db_path: Path,
    *,
    snapshot_id: str,
    event_id: str,
    object_id: str,
    fetched_at: str,
    raw_xml: str,
    parsed: dict,
    raw_payload: str,
) -> bool:
    """
    Insert an immutable snapshot row.
    Returns True if inserted, False if a snapshot for this event_id already exists.
    Version is auto-incremented per object_id.
    """
    with _connect(db_path) as conn:
        version = _next_version(conn, object_id)
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO wfirma_invoice_snapshots (
                snapshot_id, event_id, object_id, version,
                invoice_number, document_type, currency,
                net_amount, gross_amount, vat_amount,
                issue_date, sale_date, payment_due, payment_method, status,
                fetched_at, raw_xml, parsed_json, raw_payload
            ) VALUES (
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?
            )
            """,
            (
                snapshot_id, event_id, object_id, version,
                parsed.get("invoice_number"), parsed.get("document_type"),
                parsed.get("currency"),
                parsed.get("net_amount"), parsed.get("gross_amount"),
                parsed.get("vat_amount"),
                parsed.get("issue_date"), parsed.get("sale_date"),
                parsed.get("payment_due"), parsed.get("payment_method"),
                parsed.get("status"),
                fetched_at, raw_xml,
                json.dumps(parsed, ensure_ascii=False),
                raw_payload,
            ),
        )
    return cur.rowcount == 1


def get_snapshotted_events(db_path: Path, limit: int = 20) -> List[dict]:
    """
    Return up to `limit` rows in SNAPSHOTTED state, ordered oldest-first.
    These are the Phase 2B enrichment candidates.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT event_id, object_id
            FROM wfirma_webhook_processing
            WHERE processing_state = 'SNAPSHOTTED'
            ORDER BY snapshotted_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_snapshot_by_event(db_path: Path, event_id: str) -> Optional[dict]:
    """Return the snapshot for a given event_id, or None."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM wfirma_invoice_snapshots WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    return dict(row) if row else None


def get_snapshots_by_object(db_path: Path, object_id: str) -> List[dict]:
    """Return all snapshots for a given object_id, ordered by version."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM wfirma_invoice_snapshots WHERE object_id = ? ORDER BY version ASC",
            (object_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_processing_stats(db_path: Path) -> dict:
    """Return per-state counts and total snapshot count (for observability)."""
    with _connect(db_path) as conn:
        state_rows = conn.execute(
            "SELECT processing_state, COUNT(*) AS cnt FROM wfirma_webhook_processing GROUP BY processing_state"
        ).fetchall()
        total_snapshots = conn.execute(
            "SELECT COUNT(*) FROM wfirma_invoice_snapshots"
        ).fetchone()[0]
    return {
        "by_state": {r["processing_state"]: r["cnt"] for r in state_rows},
        "total_snapshots": total_snapshots,
    }
