"""
Append-only shadow telemetry log.

Records every shadow-mode request/response pair for post-shadow analysis.
All response payloads MUST be passed through CarrierResponseRedactor before
being handed to append_entry — this module does not redact itself.

No UPDATE, no DELETE. Rows are immutable once written.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

_DDL = """
CREATE TABLE IF NOT EXISTS shadow_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id         TEXT NOT NULL,
    idempotency_key  TEXT NOT NULL,
    request_json     TEXT NOT NULL,
    response_json    TEXT NOT NULL,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS shadow_log_batch_idx ON shadow_log(batch_id);
CREATE INDEX IF NOT EXISTS shadow_log_key_idx   ON shadow_log(idempotency_key);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db(db_path: Path) -> None:
    """Create the shadow_log table and indexes if they do not exist."""
    with _connect(db_path) as conn:
        conn.executescript(_DDL)


def append_entry(
    db_path: Path,
    batch_id: str,
    idempotency_key: str,
    request_payload: Dict[str, Any],
    redacted_response: Dict[str, Any],
) -> int:
    """
    Append one shadow log entry. Returns the new row id.

    Caller is responsible for passing an already-redacted response.
    Both payloads are serialised to JSON strings before storage.
    """
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO shadow_log (batch_id, idempotency_key, request_json, response_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                batch_id,
                idempotency_key,
                json.dumps(request_payload, ensure_ascii=False),
                json.dumps(redacted_response, ensure_ascii=False),
            ),
        )
        return cur.lastrowid


def get_entries_for_batch(db_path: Path, batch_id: str) -> list:
    """Return all shadow log rows for a batch as a list of dicts."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM shadow_log WHERE batch_id = ? ORDER BY id ASC",
            (batch_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_entries(db_path: Path, batch_id: Optional[str] = None, limit: int = 100) -> list:
    """Return summary rows (no JSON blobs) ordered newest-first, up to limit.

    If batch_id is given, filters to that batch only.
    Intentionally excludes request_json and response_json — callers get
    id, batch_id, idempotency_key, created_at only.
    """
    with _connect(db_path) as conn:
        if batch_id is not None:
            rows = conn.execute(
                "SELECT id, batch_id, idempotency_key, created_at "
                "FROM shadow_log WHERE batch_id = ? ORDER BY id DESC LIMIT ?",
                (batch_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, batch_id, idempotency_key, created_at "
                "FROM shadow_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def count(db_path: Path) -> int:
    """Return total number of entries in the log."""
    with _connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM shadow_log").fetchone()[0]
