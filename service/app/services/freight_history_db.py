"""
freight_history_db.py — SQLite-backed customer-specific freight history.

Pure CRUD. Pure SQLite. No wFirma I/O lives here. The resolver layer in
freight_resolver.py orchestrates DB + wFirma; this module is purely the
storage surface so it can be tested in isolation with tmp_path fixtures.

Schema (locked):
    customer_freight_history
        id                  INTEGER PRIMARY KEY AUTOINCREMENT
        contractor_id       TEXT NOT NULL
        contractor_name     TEXT NOT NULL
        country             TEXT NOT NULL
        currency            TEXT NOT NULL
        freight_service_id  TEXT NOT NULL
        freight_amount      TEXT NOT NULL    (Decimal stored as string for exactness)
        source_type         TEXT NOT NULL    invoice | proforma | manual
        source_doc_id       TEXT
        source_doc_number   TEXT
        source_doc_date     TEXT
        created_at          TEXT NOT NULL
        updated_at          TEXT NOT NULL

Lookup is keyed by (contractor_id, currency) — the same customer in a
different currency is a separate freight history. Most-recent record per
key is what `get_latest_freight` returns.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional


_VALID_SOURCE_TYPES = {"invoice", "proforma", "manual"}


@dataclass(frozen=True)
class FreightRecord:
    contractor_id:      str
    contractor_name:    str
    country:            str
    currency:           str
    freight_service_id: str
    freight_amount:     Decimal
    source_type:        str
    source_doc_id:      Optional[str] = None
    source_doc_number:  Optional[str] = None
    source_doc_date:    Optional[str] = None
    id:                 Optional[int] = None
    created_at:         Optional[str] = None
    updated_at:         Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def init_db(db_path: Path) -> None:
    """Create the table if it doesn't exist. Idempotent."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_freight_history (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                contractor_id      TEXT NOT NULL,
                contractor_name    TEXT NOT NULL,
                country            TEXT NOT NULL,
                currency           TEXT NOT NULL,
                freight_service_id TEXT NOT NULL,
                freight_amount     TEXT NOT NULL,
                source_type        TEXT NOT NULL,
                source_doc_id      TEXT,
                source_doc_number  TEXT,
                source_doc_date    TEXT,
                created_at         TEXT NOT NULL,
                updated_at         TEXT NOT NULL
            )
        """)
        # One row per (contractor_id, currency, source_type) pair — keeps history
        # of changes; latest by updated_at wins on read.
        conn.execute("""
            CREATE INDEX IF NOT EXISTS ix_freight_lookup
            ON customer_freight_history (contractor_id, currency, updated_at DESC)
        """)


def _row_to_record(row: sqlite3.Row) -> FreightRecord:
    return FreightRecord(
        id                 = row["id"],
        contractor_id      = row["contractor_id"],
        contractor_name    = row["contractor_name"],
        country            = row["country"],
        currency           = row["currency"],
        freight_service_id = row["freight_service_id"],
        freight_amount     = Decimal(row["freight_amount"]),
        source_type        = row["source_type"],
        source_doc_id      = row["source_doc_id"],
        source_doc_number  = row["source_doc_number"],
        source_doc_date    = row["source_doc_date"],
        created_at         = row["created_at"],
        updated_at         = row["updated_at"],
    )


def save_freight_history(db_path: Path, rec: FreightRecord) -> int:
    """Insert a new row. Returns the inserted id.

    We always insert (never UPDATE) so the table is also a full audit trail.
    `get_latest_freight` returns the most recent row per (contractor_id, currency).
    """
    if rec.source_type not in _VALID_SOURCE_TYPES:
        raise ValueError(
            f"source_type must be one of {sorted(_VALID_SOURCE_TYPES)}, got {rec.source_type!r}"
        )
    if Decimal(rec.freight_amount) <= 0:
        raise ValueError(f"freight_amount must be > 0, got {rec.freight_amount}")
    if not rec.contractor_id or not rec.currency or not rec.freight_service_id:
        raise ValueError("contractor_id, currency, freight_service_id are required")

    now = _now_iso()
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute("""
            INSERT INTO customer_freight_history (
                contractor_id, contractor_name, country, currency,
                freight_service_id, freight_amount,
                source_type, source_doc_id, source_doc_number, source_doc_date,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rec.contractor_id, rec.contractor_name, rec.country, rec.currency,
            rec.freight_service_id, str(rec.freight_amount),
            rec.source_type, rec.source_doc_id, rec.source_doc_number,
            rec.source_doc_date,
            rec.created_at or now, now,
        ))
        return int(cur.lastrowid or 0)


def get_latest_freight(db_path: Path,
                       contractor_id: str,
                       currency:      str) -> Optional[FreightRecord]:
    """Return the most-recently-saved row for the given (contractor_id, currency).
    Returns None if no row exists. Read-only."""
    if not Path(db_path).is_file():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("""
            SELECT * FROM customer_freight_history
            WHERE contractor_id = ? AND currency = ?
            ORDER BY datetime(updated_at) DESC, id DESC
            LIMIT 1
        """, (contractor_id, currency)).fetchone()
    return _row_to_record(row) if row else None


def list_freight_history(db_path: Path,
                         contractor_id: Optional[str] = None,
                         currency:      Optional[str] = None,
                         limit:         int = 50) -> list:
    """Return up to `limit` records, newest first. Optional filters."""
    if not Path(db_path).is_file():
        return []
    sql = "SELECT * FROM customer_freight_history WHERE 1=1"
    params: list = []
    if contractor_id:
        sql += " AND contractor_id = ?"; params.append(contractor_id)
    if currency:
        sql += " AND currency = ?"; params.append(currency)
    sql += " ORDER BY datetime(updated_at) DESC, id DESC LIMIT ?"
    params.append(int(limit))
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(r) for r in rows]


__all__ = [
    "FreightRecord",
    "init_db",
    "save_freight_history",
    "get_latest_freight",
    "list_freight_history",
]
