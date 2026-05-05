"""
tracking_db.py — SQLite store for shipment tracking events.

One row per event. Dedup key: (batch_id, awb, stage, event_time, source_ref, email_message_id).
Thread-safe: connection per call, WAL mode, threading.Lock.
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


_lock = threading.Lock()
_db_path: Optional[Path] = None


# ── Init ───────────────────────────────────────────────────────────────────────

def init_tracking_db(db_path: Path) -> None:
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as con:
        con.executescript("""
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS shipment_tracking_events (
                id                     TEXT PRIMARY KEY,
                batch_id               TEXT NOT NULL,
                awb                    TEXT NOT NULL,
                carrier                TEXT NOT NULL DEFAULT 'DHL',
                stage                  TEXT NOT NULL,
                status                 TEXT NOT NULL DEFAULT '',
                event_time             TEXT NOT NULL,
                captured_at            TEXT NOT NULL,
                source                 TEXT NOT NULL,
                source_ref             TEXT DEFAULT '',
                email_message_id       TEXT DEFAULT '',
                raw_subject            TEXT DEFAULT '',
                raw_sender             TEXT DEFAULT '',
                location               TEXT DEFAULT '',
                description            TEXT DEFAULT '',
                normalized_stage       TEXT NOT NULL DEFAULT '',
                confidence             REAL NOT NULL DEFAULT 0.0,
                requires_manual_review INTEGER NOT NULL DEFAULT 0,
                created_at             TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_te_batch_id
                ON shipment_tracking_events (batch_id);
            CREATE INDEX IF NOT EXISTS idx_te_awb
                ON shipment_tracking_events (awb);
            CREATE INDEX IF NOT EXISTS idx_te_event_time
                ON shipment_tracking_events (event_time);
        """)
        _add_column_if_missing(con, "shipment_tracking_events", "status", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(con, "shipment_tracking_events", "source_ref", "TEXT DEFAULT ''")
        _add_column_if_missing(con, "shipment_tracking_events", "email_message_id", "TEXT DEFAULT ''")
        _add_column_if_missing(con, "shipment_tracking_events", "raw_subject", "TEXT DEFAULT ''")
        _add_column_if_missing(con, "shipment_tracking_events", "raw_sender", "TEXT DEFAULT ''")
        _add_column_if_missing(con, "shipment_tracking_events", "normalized_stage", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(con, "shipment_tracking_events", "confidence", "REAL NOT NULL DEFAULT 0.0")
        _add_column_if_missing(con, "shipment_tracking_events", "requires_manual_review", "INTEGER NOT NULL DEFAULT 0")


def _add_column_if_missing(con: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(_db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Write ──────────────────────────────────────────────────────────────────────

def record_event(
    *,
    batch_id: str,
    awb: str,
    stage: str,
    event_time: str,
    source: str,
    carrier: str = "DHL",
    status: str = "",
    source_ref: str = "",
    email_message_id: str = "",
    raw_subject: str = "",
    raw_sender: str = "",
    location: str = "",
    description: str = "",
    normalized_stage: str = "",
    confidence: float = 0.0,
    requires_manual_review: bool = False,
) -> bool:
    """Insert event; skip silently if dedup key already exists. Returns True if inserted."""
    if _db_path is None:
        return False
    now = _now_iso()
    event_id = str(uuid.uuid4())
    with _lock:
        with _connect() as con:
            existing = con.execute(
                """
                SELECT id FROM shipment_tracking_events
                WHERE batch_id=? AND awb=? AND stage=? AND event_time=?
                  AND source_ref=? AND email_message_id=?
                LIMIT 1
                """,
                (batch_id, awb, stage, event_time, source_ref, email_message_id),
            ).fetchone()
            if existing:
                return False
            con.execute(
                """
                INSERT INTO shipment_tracking_events
                    (id, batch_id, awb, carrier, stage, status, event_time, captured_at,
                     source, source_ref, email_message_id, raw_subject, raw_sender,
                     location, description, normalized_stage, confidence,
                     requires_manual_review, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event_id, batch_id, awb, carrier, stage, status, event_time, now,
                    source, source_ref, email_message_id, raw_subject, raw_sender,
                    location, description, normalized_stage, confidence,
                    1 if requires_manual_review else 0, now,
                ),
            )
    return True


def record_events_batch(events: List[Dict[str, Any]]) -> int:
    """Insert multiple events; skip duplicates. Returns count inserted."""
    inserted = 0
    for ev in events:
        ok = record_event(
            batch_id=ev.get("batch_id", ""),
            awb=ev.get("awb", ""),
            stage=ev.get("stage", ev.get("normalized_stage", "")),
            event_time=ev.get("event_time", _now_iso()),
            source=ev.get("source", ""),
            carrier=ev.get("carrier", "DHL"),
            status=ev.get("status", ""),
            source_ref=ev.get("source_ref", ""),
            email_message_id=ev.get("email_message_id", ""),
            raw_subject=ev.get("raw_subject", ""),
            raw_sender=ev.get("raw_sender", ""),
            location=ev.get("location", ""),
            description=ev.get("description", ev.get("raw_description", "")),
            normalized_stage=ev.get("normalized_stage", ""),
            confidence=ev.get("confidence", 0.0),
            requires_manual_review=bool(ev.get("requires_manual_review", False)),
        )
        if ok:
            inserted += 1
    return inserted


# ── Read ───────────────────────────────────────────────────────────────────────

def get_events_for_batch(batch_id: str) -> List[Dict[str, Any]]:
    if _db_path is None:
        return []
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM shipment_tracking_events WHERE batch_id=? ORDER BY event_time ASC",
            (batch_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_events_for_awb(awb: str) -> List[Dict[str, Any]]:
    if _db_path is None:
        return []
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM shipment_tracking_events WHERE awb=? ORDER BY event_time ASC",
            (awb,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_events(limit: int = 5000, offset: int = 0) -> List[Dict[str, Any]]:
    if _db_path is None:
        return []
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM shipment_tracking_events ORDER BY event_time DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return [dict(r) for r in rows]


def get_latest_stage_for_batch(batch_id: str) -> Optional[str]:
    if _db_path is None:
        return None
    with _connect() as con:
        row = con.execute(
            "SELECT stage FROM shipment_tracking_events WHERE batch_id=? ORDER BY event_time DESC LIMIT 1",
            (batch_id,),
        ).fetchone()
    return row["stage"] if row else None
