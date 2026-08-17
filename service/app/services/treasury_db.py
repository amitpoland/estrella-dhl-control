"""
treasury_db.py — daily bank/cash closing balances + CFO close control.

NOT a wFirma authority. Local control-plane for Treasury / Daily CFO Close.

Rules:
  • Never destructively overwrite a historical close — corrections append a new
    row with correction_of_id lineage.
  • Sources: BANK_API | BANK_IMPORT | MANUAL
  • Additive schema only.

Database: <storage_root>/treasury.sqlite
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_NAME = "treasury.sqlite"

SOURCE_TYPES = ("BANK_API", "BANK_IMPORT", "MANUAL")
CLOSE_STATUSES = ("INCOMPLETE", "READY_TO_CLOSE", "CLOSED", "CORRECTED")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _dec_to_str(v: Optional[Decimal]) -> Optional[str]:
    if v is None:
        return None
    return format(v, "f")


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS treasury_balance_snapshots (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                effective_date    TEXT NOT NULL,
                account_location  TEXT NOT NULL,
                currency          TEXT NOT NULL,
                closing_balance   TEXT NOT NULL,
                source            TEXT NOT NULL,
                operator          TEXT,
                created_at        TEXT NOT NULL,
                reference_note    TEXT,
                correction_of_id  INTEGER,
                import_batch_id   TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_tbs_date_acct
                ON treasury_balance_snapshots (effective_date, account_location, currency);

            CREATE TABLE IF NOT EXISTS treasury_bank_import_batches (
                id                TEXT PRIMARY KEY,
                filename          TEXT NOT NULL,
                format            TEXT NOT NULL,
                uploaded_at       TEXT NOT NULL,
                uploaded_by       TEXT,
                status            TEXT NOT NULL,
                row_count         INTEGER NOT NULL DEFAULT 0,
                preview_json      TEXT,
                validation_json   TEXT,
                confirmed_at      TEXT,
                detail            TEXT
            );

            CREATE TABLE IF NOT EXISTS cfo_daily_close (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                close_date            TEXT NOT NULL,
                status                TEXT NOT NULL,
                bank_balances_ok      INTEGER NOT NULL DEFAULT 0,
                cash_captured_ok      INTEGER NOT NULL DEFAULT 0,
                ar_refreshed_ok       INTEGER NOT NULL DEFAULT 0,
                ap_refreshed_ok       INTEGER NOT NULL DEFAULT 0,
                statements_ok         INTEGER NOT NULL DEFAULT 0,
                exceptions_reviewed   INTEGER NOT NULL DEFAULT 0,
                closed_at             TEXT,
                closed_by             TEXT,
                correction_of_id      INTEGER,
                notes                 TEXT,
                created_at            TEXT NOT NULL,
                UNIQUE (close_date, created_at)
            );
            CREATE INDEX IF NOT EXISTS ix_cdc_date
                ON cfo_daily_close (close_date);
            """
        )
        conn.commit()


@dataclass(frozen=True)
class BalanceSnapshot:
    effective_date: str
    account_location: str
    currency: str
    closing_balance: Decimal
    source: str
    operator: Optional[str] = None
    reference_note: Optional[str] = None
    correction_of_id: Optional[int] = None
    import_batch_id: Optional[str] = None


def insert_balance_snapshot(
    db_path: Path,
    row: BalanceSnapshot,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Insert one balance snapshot.

    When ``conn`` is provided, the insert participates in the caller's
    transaction (no nested commit) — required for atomic bank-import confirm.
    """
    if row.source not in SOURCE_TYPES:
        raise ValueError(f"invalid source {row.source!r}")
    if not row.effective_date or not row.account_location or not row.currency:
        raise ValueError("effective_date, account_location, currency required")
    init_db(db_path)
    now = _now()
    params = (
        row.effective_date,
        row.account_location,
        row.currency.upper(),
        _dec_to_str(row.closing_balance),
        row.source,
        row.operator,
        now,
        row.reference_note,
        row.correction_of_id,
        row.import_batch_id,
    )
    sql = """
            INSERT INTO treasury_balance_snapshots (
                effective_date, account_location, currency, closing_balance,
                source, operator, created_at, reference_note, correction_of_id,
                import_batch_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """
    if conn is not None:
        cur = conn.execute(sql, params)
        return int(cur.lastrowid)
    with _connect(db_path) as own:
        cur = own.execute(sql, params)
        own.commit()
        return int(cur.lastrowid)


def latest_balances_as_of(db_path: Path, as_of: str) -> List[Dict[str, Any]]:
    """Latest snapshot per (account_location, currency) with effective_date <= as_of.

    Corrections append new rows. Winner = max(effective_date), then max(id).
    """
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT t.*
            FROM treasury_balance_snapshots t
            INNER JOIN (
                SELECT account_location, currency, MAX(effective_date) AS max_d
                FROM treasury_balance_snapshots
                WHERE effective_date <= ?
                GROUP BY account_location, currency
            ) d
              ON t.account_location = d.account_location
             AND t.currency = d.currency
             AND t.effective_date = d.max_d
            INNER JOIN (
                SELECT account_location, currency, effective_date, MAX(id) AS max_id
                FROM treasury_balance_snapshots
                GROUP BY account_location, currency, effective_date
            ) i
              ON t.id = i.max_id
            ORDER BY t.account_location, t.currency
            """,
            (as_of,),
        ).fetchall()
        return [dict(r) for r in rows]


def insert_daily_close(
    db_path: Path,
    *,
    close_date: str,
    status: str,
    bank_balances_ok: bool = False,
    cash_captured_ok: bool = False,
    ar_refreshed_ok: bool = False,
    ap_refreshed_ok: bool = False,
    statements_ok: bool = False,
    exceptions_reviewed: bool = False,
    closed_by: Optional[str] = None,
    correction_of_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> int:
    if status not in CLOSE_STATUSES:
        raise ValueError(f"invalid status {status!r}")
    init_db(db_path)
    now = _now()
    closed_at = now if status in ("CLOSED", "CORRECTED") else None
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO cfo_daily_close (
                close_date, status, bank_balances_ok, cash_captured_ok,
                ar_refreshed_ok, ap_refreshed_ok, statements_ok, exceptions_reviewed,
                closed_at, closed_by, correction_of_id, notes, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                close_date,
                status,
                1 if bank_balances_ok else 0,
                1 if cash_captured_ok else 0,
                1 if ar_refreshed_ok else 0,
                1 if ap_refreshed_ok else 0,
                1 if statements_ok else 0,
                1 if exceptions_reviewed else 0,
                closed_at,
                closed_by,
                correction_of_id,
                notes,
                now,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def treasury_db_path(storage_root: Path) -> Path:
    return Path(storage_root) / DB_NAME
