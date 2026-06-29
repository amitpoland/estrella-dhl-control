"""
wFirma webhook event store.

Provides idempotent event insertion — insert_event returns False if the
event_id already exists (duplicate delivery), True if newly written.

Security: webhook_key is never stored here; the route layer strips it
before calling insert_event.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

_DDL = """
CREATE TABLE IF NOT EXISTS wfirma_webhook_events (
    event_id     TEXT PRIMARY KEY,
    event_type   TEXT,
    payload_json TEXT NOT NULL,
    received_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wfirma_webhook_type
    ON wfirma_webhook_events (event_type);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db(db_path: Path) -> None:
    """Create the wfirma_webhook_events table and indexes if they do not exist."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript(_DDL)


def insert_event(
    db_path: Path,
    event_id: str,
    event_type: Optional[str],
    payload: Dict[str, Any],
    received_at: str,
) -> bool:
    """
    Attempt to insert a new event. Returns True if inserted, False if duplicate.

    Uses INSERT OR IGNORE so concurrent duplicate deliveries are safe.
    """
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO wfirma_webhook_events
                (event_id, event_type, payload_json, received_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                event_id,
                event_type,
                json.dumps(payload, ensure_ascii=False),
                received_at,
            ),
        )
    return cur.rowcount == 1


def get_event(db_path: Path, event_id: str) -> Optional[dict]:
    """Return the event row as a plain dict, or None if not found."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM wfirma_webhook_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    return dict(row) if row else None
