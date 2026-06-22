"""
warehouse_receipt_db.py — Operator quantity-confirmation for warehouse receipt.

Authority: WAREHOUSE (goods receipt by quantity).

This module persists operator-confirmed *received quantities* by packing line or
batch. It is the authority that replaces the mandatory per-piece barcode scan as
the warehouse-receipt signal: warehouse receipt means an operator confirms the
quantity accepted against the expected (import packing) quantity — it does NOT
mean every physical piece has been scanned. Per-piece barcode scan remains
optional traceability evidence, except when a shipment is explicitly marked
``serial_controlled`` (see warehouse_receipt.py).

Tables
------
warehouse_receipt_confirmations   one row per (batch_id, line_key) — latest state
warehouse_receipt_events          append-only audit trail of every confirmation

Design rules
------------
- One DB file: storage_root/warehouse_receipt.db
- Movement is quantity only. Never touches invoice / PZ / wFirma values.
- Idempotent upsert by (batch_id, line_key); every write also appends an event.
- Thread-safe: per-call connection, WAL mode, threading.Lock.
- Public functions return None / [] on misses; callers decide error UX.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.logging import get_logger

log      = get_logger(__name__)
_lock    = threading.Lock()
_db_path: Optional[Path] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(_db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


# ── Init ────────────────────────────────────────────────────────────────────

def init_warehouse_receipt_db(db_path: Path) -> None:
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as con:
        con.executescript("""
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS warehouse_receipt_confirmations (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id       TEXT NOT NULL,
                line_key       TEXT NOT NULL,
                design_no      TEXT DEFAULT '',
                product_code   TEXT DEFAULT '',
                expected_qty   REAL DEFAULT 0,
                accepted_qty   REAL DEFAULT 0,
                shortage_qty   REAL DEFAULT 0,
                overage_qty    REAL DEFAULT 0,
                operator       TEXT DEFAULT '',
                source_documents TEXT DEFAULT '[]',
                note           TEXT DEFAULT '',
                confirmed_at   TEXT NOT NULL,
                UNIQUE(batch_id, line_key)
            );

            CREATE INDEX IF NOT EXISTS idx_wrc_batch
                ON warehouse_receipt_confirmations(batch_id);

            -- Append-only audit trail.
            CREATE TABLE IF NOT EXISTS warehouse_receipt_events (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id       TEXT NOT NULL,
                line_key       TEXT NOT NULL,
                expected_qty   REAL DEFAULT 0,
                accepted_qty   REAL DEFAULT 0,
                shortage_qty   REAL DEFAULT 0,
                overage_qty    REAL DEFAULT 0,
                operator       TEXT DEFAULT '',
                source_documents TEXT DEFAULT '[]',
                note           TEXT DEFAULT '',
                created_at     TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_wre_batch
                ON warehouse_receipt_events(batch_id);
        """)
    log.info("warehouse_receipt.db ready at %s", db_path)


def _ready() -> bool:
    return _db_path is not None


def _row_to_dict(r: sqlite3.Row) -> Dict[str, Any]:
    d = dict(r)
    try:
        d["source_documents"] = json.loads(d.get("source_documents") or "[]")
    except Exception:
        d["source_documents"] = []
    return d


# ── Writes ──────────────────────────────────────────────────────────────────

def upsert_confirmation(
    batch_id: str,
    line_key: str,
    *,
    expected_qty: float,
    accepted_qty: float,
    design_no: str = "",
    product_code: str = "",
    operator: str = "",
    source_documents: Optional[List[str]] = None,
    note: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Idempotently record an operator quantity confirmation for one line.

    shortage/overage are derived (never operator-supplied) so they cannot drift
    from expected vs accepted. Every call also appends an audit event.
    """
    if not _ready() or not batch_id or not line_key:
        return None

    exp = round(float(expected_qty or 0), 4)
    acc = round(float(accepted_qty or 0), 4)
    shortage = round(max(exp - acc, 0.0), 4)
    overage  = round(max(acc - exp, 0.0), 4)
    src_json = json.dumps(list(source_documents or []))
    ts = _now_iso()

    with _lock, _connect() as con:
        con.execute(
            """
            INSERT INTO warehouse_receipt_confirmations
                (batch_id, line_key, design_no, product_code, expected_qty,
                 accepted_qty, shortage_qty, overage_qty, operator,
                 source_documents, note, confirmed_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(batch_id, line_key) DO UPDATE SET
                design_no        = excluded.design_no,
                product_code     = excluded.product_code,
                expected_qty     = excluded.expected_qty,
                accepted_qty     = excluded.accepted_qty,
                shortage_qty     = excluded.shortage_qty,
                overage_qty      = excluded.overage_qty,
                operator         = excluded.operator,
                source_documents = excluded.source_documents,
                note             = excluded.note,
                confirmed_at     = excluded.confirmed_at
            """,
            (batch_id, line_key, design_no, product_code, exp, acc,
             shortage, overage, operator, src_json, note, ts),
        )
        con.execute(
            """
            INSERT INTO warehouse_receipt_events
                (batch_id, line_key, expected_qty, accepted_qty, shortage_qty,
                 overage_qty, operator, source_documents, note, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (batch_id, line_key, exp, acc, shortage, overage, operator,
             src_json, note, ts),
        )
        con.commit()
        row = con.execute(
            "SELECT * FROM warehouse_receipt_confirmations "
            "WHERE batch_id=? AND line_key=?",
            (batch_id, line_key),
        ).fetchone()
    return _row_to_dict(row) if row else None


# ── Reads ───────────────────────────────────────────────────────────────────

def get_confirmations(batch_id: str) -> List[Dict[str, Any]]:
    if not _ready() or not batch_id:
        return []
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM warehouse_receipt_confirmations "
            "WHERE batch_id=? ORDER BY line_key",
            (batch_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_confirmation(batch_id: str, line_key: str) -> Optional[Dict[str, Any]]:
    if not _ready() or not batch_id or not line_key:
        return None
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM warehouse_receipt_confirmations "
            "WHERE batch_id=? AND line_key=?",
            (batch_id, line_key),
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_events(batch_id: str) -> List[Dict[str, Any]]:
    if not _ready() or not batch_id:
        return []
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM warehouse_receipt_events "
            "WHERE batch_id=? ORDER BY id",
            (batch_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]
