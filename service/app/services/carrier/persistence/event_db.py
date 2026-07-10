"""
Webhook event deduplication store.

Provides idempotent event insertion — insert_event returns False if the
event_id already exists, True if newly written. Callers must check the
return value before processing the event.

HMAC signature verification happens at the route layer before any DB
interaction. This module only handles dedup and retrieval.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

_DDL = """
CREATE TABLE IF NOT EXISTS carrier_events (
    event_id    TEXT PRIMARY KEY,
    batch_id    TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS carrier_events_batch_idx ON carrier_events(batch_id);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db(db_path: Path) -> None:
    """Create the carrier_events table and indexes if they do not exist."""
    with _connect(db_path) as conn:
        conn.executescript(_DDL)


def insert_event(
    db_path: Path,
    event_id: str,
    batch_id: str,
    event_type: str,
    payload: Dict[str, Any],
) -> bool:
    """
    Attempt to insert a new event. Returns True if inserted, False if duplicate.

    Uses INSERT OR IGNORE so concurrent duplicate deliveries are safe.
    """
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO carrier_events
                (event_id, batch_id, event_type, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                event_id,
                batch_id,
                event_type,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
    return cur.rowcount == 1


def get_event(db_path: Path, event_id: str) -> Optional[dict]:
    """Return the event row as a plain dict, or None if not found."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM carrier_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    return dict(row) if row else None


def get_events_for_batch(db_path: Path, batch_id: str) -> list:
    """Return all event rows for a batch ordered by received_at."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM carrier_events WHERE batch_id = ? ORDER BY received_at ASC",
            (batch_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_events(db_path: Path, limit: int = 500) -> list:
    """CW-1: newest-first event rows for the processor (read-only)."""
    if not Path(db_path).exists():
        return []
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM carrier_events ORDER BY received_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [dict(r) for r in rows]


def count_events(db_path: Path) -> Dict[str, int]:
    """CW-1: total vs correlated (non-empty batch_id) event counts."""
    if not Path(db_path).exists():
        return {"total": 0, "correlated": 0}
    with _connect(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM carrier_events").fetchone()[0]
        corr = conn.execute(
            "SELECT COUNT(*) FROM carrier_events WHERE batch_id != ''"
        ).fetchone()[0]
    return {"total": int(total), "correlated": int(corr)}
