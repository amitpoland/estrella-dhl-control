"""
Phase 3B -- contractor_poll.db schema and scan-state layer.

Tracks the last time a full wFirma contractor scan completed so the
scheduler can apply a cooldown and avoid re-scanning every 30 seconds.

Database: C:\\PZ\\storage\\contractor_poll.db
Table:    contractor_poll_state (single-row control record)

Authority: scan state only.  The actual contractor data lives in
customer_master.sqlite (written via upsert_identity_only).  This module
never touches customer_master.sqlite directly.

Track B constraint: does NOT import from or write to wfirma_processing.db,
wfirma_webhook_events.db, or payment_state.db.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

SCAN_COOLDOWN_SECONDS = 21600   # full scan at most once every 6 hours
PAGE_SIZE             = 50      # contractors per wFirma API page


def _connect(db_path: Path) -> sqlite3.Connection:
    """Tuned connection — WAL + busy_timeout per the dhl_thread_lock idiom
    (dhl_thread_lock.py:126-129; infra health pass d67d3722 finding #2):
    this DB has a FastAPI 'Run Now' writer AND the APScheduler tick writer;
    every connection now waits out a competing writer (busy_timeout FIRST,
    so the WAL flip itself waits) instead of failing 'database is locked'."""
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_contractor_poll_db(db_path: Path) -> None:
    """Create contractor_poll.db and the scan-state table if not present."""
    with _connect(db_path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS contractor_poll_state (
            id                      INTEGER PRIMARY KEY CHECK (id = 1),
            last_scan_started_at    TEXT,
            last_scan_completed_at  TEXT,
            last_scan_contractor_count INTEGER NOT NULL DEFAULT 0,
            last_scan_new_count     INTEGER NOT NULL DEFAULT 0,
            last_scan_updated_count INTEGER NOT NULL DEFAULT 0,
            last_scan_error         TEXT
        );
        """)
        conn.commit()


def get_last_scan_completed_at(db_path: Path) -> Optional[str]:
    """Return ISO timestamp of the last completed full scan, or None."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT last_scan_completed_at FROM contractor_poll_state WHERE id = 1"
        ).fetchone()
    return row[0] if row else None


def is_scan_due(db_path: Path, now_iso: str, cooldown_seconds: int = SCAN_COOLDOWN_SECONDS) -> bool:
    """Return True if a full scan should run (never scanned, or cooldown elapsed)."""
    last = get_last_scan_completed_at(db_path)
    if last is None:
        return True
    try:
        now_dt  = datetime.fromisoformat(now_iso)
        last_dt = datetime.fromisoformat(last)
        return now_dt - last_dt >= timedelta(seconds=cooldown_seconds)
    except ValueError:
        return True


def mark_scan_started(db_path: Path, now_iso: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO contractor_poll_state
               (id, last_scan_started_at, last_scan_completed_at,
                last_scan_contractor_count, last_scan_new_count,
                last_scan_updated_count, last_scan_error)
               VALUES (1, ?, NULL, 0, 0, 0, NULL)
               ON CONFLICT(id) DO UPDATE SET
                   last_scan_started_at = excluded.last_scan_started_at,
                   last_scan_error = NULL""",
            (now_iso,),
        )
        conn.commit()


def mark_scan_completed(
    db_path: Path,
    now_iso: str,
    contractor_count: int,
    new_count: int,
    updated_count: int,
    error: Optional[str] = None,
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO contractor_poll_state
               (id, last_scan_started_at, last_scan_completed_at,
                last_scan_contractor_count, last_scan_new_count,
                last_scan_updated_count, last_scan_error)
               VALUES (1, NULL, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   last_scan_completed_at      = excluded.last_scan_completed_at,
                   last_scan_contractor_count  = excluded.last_scan_contractor_count,
                   last_scan_new_count         = excluded.last_scan_new_count,
                   last_scan_updated_count     = excluded.last_scan_updated_count,
                   last_scan_error             = excluded.last_scan_error""",
            (now_iso, contractor_count, new_count, updated_count, error),
        )
        conn.commit()


def get_scan_state(db_path: Path) -> dict:
    """Return full scan-state row as dict (for diagnostics)."""
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM contractor_poll_state WHERE id = 1"
        ).fetchone()
    return dict(row) if row else {}
