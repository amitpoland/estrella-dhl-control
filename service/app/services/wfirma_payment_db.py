"""
Phase 4A -- payment_state.db schema and access layer.

Authority: wFirma payments API (read-only).
Database: C:\\PZ\\storage\\payment_state.db

Tables
------
wfirma_payment_snapshots  — immutable, append-only, keyed by payment_id UNIQUE
payment_sync_state        — per-contractor sync control (last_synced_at, running count)

Track B constraint: this module does NOT import from or write to
wfirma_processing.db, wfirma_webhook_events.db, customer_master.sqlite,
or proforma_links.db.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)

SYNC_COOLDOWN_SECONDS = 3600  # re-sync per contractor at most once per hour


def init_payment_db(db_path: Path) -> None:
    """Create payment_state.db and all Phase 4A tables if not already present."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS wfirma_payment_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_id      TEXT NOT NULL UNIQUE,
            contractor_id   TEXT NOT NULL,
            invoice_id      TEXT,
            payment_date    TEXT,
            value           TEXT,
            value_pln       TEXT,
            currency_label  TEXT,
            payment_method  TEXT,
            payment_type    TEXT,
            type            TEXT,
            notes           TEXT,
            fetched_at      TEXT NOT NULL,
            raw_json        TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_wps_contractor
            ON wfirma_payment_snapshots (contractor_id);
        CREATE INDEX IF NOT EXISTS idx_wps_invoice
            ON wfirma_payment_snapshots (invoice_id);

        CREATE TABLE IF NOT EXISTS payment_sync_state (
            contractor_id   TEXT PRIMARY KEY,
            last_synced_at  TEXT,
            snapshot_count  INTEGER NOT NULL DEFAULT 0
        );
        """)
        conn.commit()


def get_contractors_due_for_sync(
    db_path: Path,
    all_contractor_ids: List[str],
    now_iso: str,
    cooldown_seconds: int = SYNC_COOLDOWN_SECONDS,
) -> List[str]:
    """
    Return the subset of contractor IDs that have not been synced within
    the cooldown window.  Contractors absent from payment_sync_state are
    always due (first-sync).
    """
    if not all_contractor_ids:
        return []

    placeholders = ",".join("?" * len(all_contractor_ids))
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT contractor_id, last_synced_at FROM payment_sync_state "
            f"WHERE contractor_id IN ({placeholders})",
            all_contractor_ids,
        ).fetchall()
    synced = {r["contractor_id"]: r["last_synced_at"] for r in rows}

    try:
        now_dt = datetime.fromisoformat(now_iso)
    except ValueError:
        return list(all_contractor_ids)

    due: List[str] = []
    cutoff = now_dt - timedelta(seconds=cooldown_seconds)

    for cid in all_contractor_ids:
        last_iso = synced.get(cid)
        if last_iso is None:
            due.append(cid)
            continue
        try:
            last_dt = datetime.fromisoformat(last_iso)
            if last_dt < cutoff:
                due.append(cid)
        except ValueError:
            due.append(cid)

    return due


def insert_payment_snapshot(
    db_path: Path,
    *,
    payment_id: str,
    contractor_id: str,
    invoice_id: Optional[str],
    payment_date: Optional[str],
    value: Optional[str],
    value_pln: Optional[str],
    currency_label: Optional[str],
    payment_method: Optional[str],
    payment_type: Optional[str],
    type_: Optional[str],
    notes: Optional[str],
    fetched_at: str,
    raw_json: str,
) -> bool:
    """
    INSERT OR IGNORE payment snapshot.
    Returns True when the row was newly inserted, False when already present.
    """
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO wfirma_payment_snapshots
               (payment_id, contractor_id, invoice_id, payment_date, value, value_pln,
                currency_label, payment_method, payment_type, type, notes, fetched_at, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (payment_id, contractor_id, invoice_id, payment_date, value, value_pln,
             currency_label, payment_method, payment_type, type_, notes, fetched_at, raw_json),
        )
        conn.commit()
        return cur.rowcount > 0


def mark_contractor_synced(
    db_path: Path,
    contractor_id: str,
    now_iso: str,
    new_count: int,
) -> None:
    """Upsert last_synced_at and accumulate snapshot_count for a contractor."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO payment_sync_state "
            "(contractor_id, last_synced_at, snapshot_count) VALUES (?, NULL, 0)",
            (contractor_id,),
        )
        conn.execute(
            "UPDATE payment_sync_state SET last_synced_at = ?, "
            "snapshot_count = snapshot_count + ? WHERE contractor_id = ?",
            (now_iso, new_count, contractor_id),
        )
        conn.commit()


def get_snapshot_count(db_path: Path) -> int:
    """Total payment snapshots (for diagnostics)."""
    with sqlite3.connect(str(db_path)) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM wfirma_payment_snapshots"
        ).fetchone()[0]


def get_sync_state(db_path: Path) -> List[dict]:
    """Per-contractor sync state (for diagnostics)."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            "SELECT contractor_id, last_synced_at, snapshot_count "
            "FROM payment_sync_state ORDER BY contractor_id"
        ).fetchall()]
