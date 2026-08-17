"""
financial_reporting_db.py — local AR/AP reporting projection (not fiscal SoT).

wFirma remains the originating accounting authority. This SQLite store is the
canonical *fast reporting projection* for CFO/ledger UI:

  • backfill + incremental sync + reconciliation metadata
  • source timestamps + modified/source version for drift detection
  • due dates + open-relevant status so AR/AP aging does not require a cold
    wFirma portfolio waterfall on every page load

Database: <storage_root>/financial_reporting.sqlite

Additive / idempotent schema only — never destructive migrations.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


DB_NAME = "financial_reporting.sqlite"


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


def _add_column_if_missing(conn: sqlite3.Connection, table: str, col: str, decl: str) -> None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def init_db(db_path: Path) -> None:
    """Create reporting tables. Idempotent; additive column upgrades only."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ar_invoice_reporting (
                invoice_id            TEXT PRIMARY KEY,
                contractor_id         TEXT NOT NULL,
                contractor_name       TEXT,
                invoice_number        TEXT,
                document_type         TEXT NOT NULL,
                issue_date            TEXT,
                due_date              TEXT,
                currency              TEXT,
                net                   TEXT,
                tax                   TEXT,
                gross                 TEXT,
                payment_state         TEXT,
                document_status       TEXT,
                correction_of_id      TEXT,
                open_relevant         INTEGER NOT NULL DEFAULT 1,
                source_modified       TEXT,
                source_version        TEXT,
                synced_at             TEXT NOT NULL,
                raw_hash              TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_ar_contractor_due
                ON ar_invoice_reporting (contractor_id, due_date);
            CREATE INDEX IF NOT EXISTS ix_ar_issue
                ON ar_invoice_reporting (issue_date);
            CREATE INDEX IF NOT EXISTS ix_ar_open_ccy
                ON ar_invoice_reporting (open_relevant, currency);

            CREATE TABLE IF NOT EXISTS ap_expense_reporting (
                expense_id            TEXT PRIMARY KEY,
                supplier_id           TEXT NOT NULL,
                supplier_name         TEXT,
                document_number       TEXT,
                document_type         TEXT,
                issue_date            TEXT,
                due_date              TEXT,
                currency              TEXT,
                net                   TEXT,
                tax                   TEXT,
                gross                 TEXT,
                payment_state         TEXT,
                document_status       TEXT,
                correction_of_id      TEXT,
                open_relevant         INTEGER NOT NULL DEFAULT 1,
                source_modified       TEXT,
                source_version        TEXT,
                synced_at             TEXT NOT NULL,
                raw_hash              TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_ap_supplier_due
                ON ap_expense_reporting (supplier_id, due_date);
            CREATE INDEX IF NOT EXISTS ix_ap_issue
                ON ap_expense_reporting (issue_date);
            CREATE INDEX IF NOT EXISTS ix_ap_open_ccy
                ON ap_expense_reporting (open_relevant, currency);

            CREATE TABLE IF NOT EXISTS financial_reporting_sync_state (
                stream                TEXT PRIMARY KEY,
                last_full_sync_at     TEXT,
                last_incremental_at   TEXT,
                last_reconcile_at     TEXT,
                last_source_watermark TEXT,
                row_count             INTEGER NOT NULL DEFAULT 0,
                status                TEXT,
                detail                TEXT
            );
            """
        )
        # Additive upgrades (safe on existing DBs).
        for col, decl in (
            ("tax", "TEXT"),
            ("payment_state", "TEXT"),
            ("document_status", "TEXT"),
            ("correction_of_id", "TEXT"),
            ("open_relevant", "INTEGER NOT NULL DEFAULT 1"),
            ("source_modified", "TEXT"),
            ("source_version", "TEXT"),
            ("raw_hash", "TEXT"),
        ):
            _add_column_if_missing(conn, "ar_invoice_reporting", col, decl)
            _add_column_if_missing(conn, "ap_expense_reporting", col, decl)
        conn.commit()


@dataclass(frozen=True)
class ArInvoiceReportingRow:
    invoice_id: str
    contractor_id: str
    document_type: str
    contractor_name: Optional[str] = None
    invoice_number: Optional[str] = None
    issue_date: Optional[str] = None
    due_date: Optional[str] = None
    currency: Optional[str] = None
    net: Optional[Decimal] = None
    tax: Optional[Decimal] = None
    gross: Optional[Decimal] = None
    payment_state: Optional[str] = None
    document_status: Optional[str] = None
    correction_of_id: Optional[str] = None
    open_relevant: bool = True
    source_modified: Optional[str] = None
    source_version: Optional[str] = None
    raw_hash: Optional[str] = None


@dataclass(frozen=True)
class ApExpenseReportingRow:
    expense_id: str
    supplier_id: str
    document_type: Optional[str] = None
    supplier_name: Optional[str] = None
    document_number: Optional[str] = None
    issue_date: Optional[str] = None
    due_date: Optional[str] = None
    currency: Optional[str] = None
    net: Optional[Decimal] = None
    tax: Optional[Decimal] = None
    gross: Optional[Decimal] = None
    payment_state: Optional[str] = None
    document_status: Optional[str] = None
    correction_of_id: Optional[str] = None
    open_relevant: bool = True
    source_modified: Optional[str] = None
    source_version: Optional[str] = None
    raw_hash: Optional[str] = None


def upsert_ar_invoice(db_path: Path, row: ArInvoiceReportingRow) -> None:
    if not row.invoice_id or not row.contractor_id or not row.document_type:
        raise ValueError("invoice_id, contractor_id, document_type required")
    init_db(db_path)
    now = _now()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO ar_invoice_reporting (
                invoice_id, contractor_id, contractor_name, invoice_number,
                document_type, issue_date, due_date, currency, net, tax, gross,
                payment_state, document_status, correction_of_id, open_relevant,
                source_modified, source_version, synced_at, raw_hash
            ) VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )
            ON CONFLICT(invoice_id) DO UPDATE SET
                contractor_id=excluded.contractor_id,
                contractor_name=excluded.contractor_name,
                invoice_number=excluded.invoice_number,
                document_type=excluded.document_type,
                issue_date=excluded.issue_date,
                due_date=excluded.due_date,
                currency=excluded.currency,
                net=excluded.net,
                tax=excluded.tax,
                gross=excluded.gross,
                payment_state=excluded.payment_state,
                document_status=excluded.document_status,
                correction_of_id=excluded.correction_of_id,
                open_relevant=excluded.open_relevant,
                source_modified=excluded.source_modified,
                source_version=excluded.source_version,
                synced_at=excluded.synced_at,
                raw_hash=excluded.raw_hash
            """,
            (
                row.invoice_id,
                row.contractor_id,
                row.contractor_name,
                row.invoice_number,
                row.document_type,
                row.issue_date,
                row.due_date,
                row.currency,
                _dec_to_str(row.net),
                _dec_to_str(row.tax),
                _dec_to_str(row.gross),
                row.payment_state,
                row.document_status,
                row.correction_of_id,
                1 if row.open_relevant else 0,
                row.source_modified,
                row.source_version,
                now,
                row.raw_hash,
            ),
        )
        conn.commit()


def upsert_ap_expense(db_path: Path, row: ApExpenseReportingRow) -> None:
    if not row.expense_id or not row.supplier_id:
        raise ValueError("expense_id, supplier_id required")
    init_db(db_path)
    now = _now()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO ap_expense_reporting (
                expense_id, supplier_id, supplier_name, document_number,
                document_type, issue_date, due_date, currency, net, tax, gross,
                payment_state, document_status, correction_of_id, open_relevant,
                source_modified, source_version, synced_at, raw_hash
            ) VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )
            ON CONFLICT(expense_id) DO UPDATE SET
                supplier_id=excluded.supplier_id,
                supplier_name=excluded.supplier_name,
                document_number=excluded.document_number,
                document_type=excluded.document_type,
                issue_date=excluded.issue_date,
                due_date=excluded.due_date,
                currency=excluded.currency,
                net=excluded.net,
                tax=excluded.tax,
                gross=excluded.gross,
                payment_state=excluded.payment_state,
                document_status=excluded.document_status,
                correction_of_id=excluded.correction_of_id,
                open_relevant=excluded.open_relevant,
                source_modified=excluded.source_modified,
                source_version=excluded.source_version,
                synced_at=excluded.synced_at,
                raw_hash=excluded.raw_hash
            """,
            (
                row.expense_id,
                row.supplier_id,
                row.supplier_name,
                row.document_number,
                row.document_type,
                row.issue_date,
                row.due_date,
                row.currency,
                _dec_to_str(row.net),
                _dec_to_str(row.tax),
                _dec_to_str(row.gross),
                row.payment_state,
                row.document_status,
                row.correction_of_id,
                1 if row.open_relevant else 0,
                row.source_modified,
                row.source_version,
                now,
                row.raw_hash,
            ),
        )
        conn.commit()


def set_sync_state(
    db_path: Path,
    stream: str,
    *,
    last_full_sync_at: Optional[str] = None,
    last_incremental_at: Optional[str] = None,
    last_reconcile_at: Optional[str] = None,
    last_source_watermark: Optional[str] = None,
    row_count: Optional[int] = None,
    status: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    init_db(db_path)
    with _connect(db_path) as conn:
        existing = conn.execute(
            "SELECT * FROM financial_reporting_sync_state WHERE stream = ?",
            (stream,),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO financial_reporting_sync_state (
                    stream, last_full_sync_at, last_incremental_at, last_reconcile_at,
                    last_source_watermark, row_count, status, detail
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    stream,
                    last_full_sync_at,
                    last_incremental_at,
                    last_reconcile_at,
                    last_source_watermark,
                    int(row_count or 0),
                    status,
                    detail,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE financial_reporting_sync_state SET
                    last_full_sync_at=COALESCE(?, last_full_sync_at),
                    last_incremental_at=COALESCE(?, last_incremental_at),
                    last_reconcile_at=COALESCE(?, last_reconcile_at),
                    last_source_watermark=COALESCE(?, last_source_watermark),
                    row_count=COALESCE(?, row_count),
                    status=COALESCE(?, status),
                    detail=COALESCE(?, detail)
                WHERE stream=?
                """,
                (
                    last_full_sync_at,
                    last_incremental_at,
                    last_reconcile_at,
                    last_source_watermark,
                    row_count,
                    status,
                    detail,
                    stream,
                ),
            )
        conn.commit()


def get_sync_state(db_path: Path, stream: str) -> Optional[Dict[str, Any]]:
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM financial_reporting_sync_state WHERE stream = ?",
            (stream,),
        ).fetchone()
        return dict(row) if row else None


def count_ar(db_path: Path) -> int:
    init_db(db_path)
    with _connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM ar_invoice_reporting").fetchone()[0])


def count_ap(db_path: Path) -> int:
    init_db(db_path)
    with _connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM ap_expense_reporting").fetchone()[0])


def list_ar_invoices_as_of(
    db_path: Path,
    *,
    as_of: str,
    document_types: Sequence[str] = ("normal", "correction"),
    currency: str = "",
    contractor_id: str = "",
) -> List[Dict[str, Any]]:
    """Position-as-of invoice rows: issue_date <= as_of, fiscal types only."""
    init_db(db_path)
    types = [t for t in document_types if t]
    if not types:
        return []
    placeholders = ",".join("?" * len(types))
    sql = (
        f"SELECT * FROM ar_invoice_reporting "
        f"WHERE document_type IN ({placeholders}) "
        f"AND (issue_date IS NULL OR issue_date <= ?) "
        f"AND open_relevant = 1"
    )
    params: List[Any] = list(types) + [as_of]
    if currency:
        sql += " AND currency = ?"
        params.append(currency.upper())
    if contractor_id:
        sql += " AND contractor_id = ?"
        params.append(contractor_id)
    with _connect(db_path) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def list_ap_expenses_as_of(
    db_path: Path,
    *,
    as_of: str,
    currency: str = "",
    supplier_id: str = "",
) -> List[Dict[str, Any]]:
    init_db(db_path)
    sql = (
        "SELECT * FROM ap_expense_reporting "
        "WHERE (issue_date IS NULL OR issue_date <= ?) "
        "AND open_relevant = 1"
    )
    params: List[Any] = [as_of]
    if currency:
        sql += " AND currency = ?"
        params.append(currency.upper())
    if supplier_id:
        sql += " AND supplier_id = ?"
        params.append(supplier_id)
    with _connect(db_path) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def reporting_db_path(storage_root: Path) -> Path:
    return Path(storage_root) / DB_NAME
