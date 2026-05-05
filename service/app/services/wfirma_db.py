"""
wfirma_db.py — Local mapping tables for wFirma integration.

Tables
------
wfirma_customers         client_name → wFirma customer_id mapping
wfirma_products          product_code → wFirma product_id mapping
wfirma_reservation_drafts  per-client draft (one per batch+client before creation)
wfirma_reservation_lines   per-product-code row within a draft

Design rules
------------
- One DB file: storage_root/wfirma.db
- wfirma_customer_id / wfirma_product_id = NULL until synced with wFirma API
- match_status / sync_status: pending | matched | not_found | error
- Drafts are local-only until POST /reservations/create is called
- Never mutates invoice / PZ / warehouse data
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.logging import get_logger

log      = get_logger(__name__)
_lock    = threading.Lock()
_db_path: Optional[Path] = None


# ── Init ──────────────────────────────────────────────────────────────────────

def init_wfirma_db(db_path: Path) -> None:
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as con:
        con.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            -- ── Client → wFirma customer mapping ──────────────────────────────
            CREATE TABLE IF NOT EXISTS wfirma_customers (
                id                  TEXT PRIMARY KEY,
                client_name         TEXT NOT NULL,
                wfirma_customer_id  TEXT DEFAULT NULL,
                vat_id              TEXT NOT NULL DEFAULT '',
                country             TEXT NOT NULL DEFAULT '',
                match_status        TEXT NOT NULL DEFAULT 'pending',
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_wfc_client_name
                ON wfirma_customers (client_name);
            CREATE INDEX IF NOT EXISTS idx_wfc_status
                ON wfirma_customers (match_status);

            -- ── product_code → wFirma product mapping ─────────────────────────
            CREATE TABLE IF NOT EXISTS wfirma_products (
                id                  TEXT PRIMARY KEY,
                product_code        TEXT NOT NULL,
                wfirma_product_id   TEXT DEFAULT NULL,
                product_name_pl     TEXT NOT NULL DEFAULT '',
                unit                TEXT NOT NULL DEFAULT 'szt.',
                vat_rate            TEXT NOT NULL DEFAULT '23',
                warehouse_id        TEXT NOT NULL DEFAULT '',
                sync_status         TEXT NOT NULL DEFAULT 'pending',
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_wfp_product_code
                ON wfirma_products (product_code);
            CREATE INDEX IF NOT EXISTS idx_wfp_status
                ON wfirma_products (sync_status);

            -- ── Per-client reservation draft ──────────────────────────────────
            CREATE TABLE IF NOT EXISTS wfirma_reservation_drafts (
                id              TEXT PRIMARY KEY,
                batch_id        TEXT NOT NULL,
                client_name     TEXT NOT NULL,
                client_ref      TEXT NOT NULL DEFAULT '',
                currency        TEXT NOT NULL DEFAULT 'USD',
                warehouse_id    TEXT NOT NULL DEFAULT '',
                ready_to_create INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_wfrd_batch
                ON wfirma_reservation_drafts (batch_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_wfrd_batch_client
                ON wfirma_reservation_drafts (batch_id, client_name);

            -- ── Per-product-code line within a draft ──────────────────────────
            CREATE TABLE IF NOT EXISTS wfirma_reservation_lines (
                id              TEXT PRIMARY KEY,
                draft_id        TEXT NOT NULL
                    REFERENCES wfirma_reservation_drafts(id) ON DELETE CASCADE,
                product_code    TEXT NOT NULL,
                product_name_pl TEXT NOT NULL DEFAULT '',
                qty             REAL NOT NULL DEFAULT 0,
                unit_price      REAL NOT NULL DEFAULT 0,
                currency        TEXT NOT NULL DEFAULT 'USD',
                stock_ok        INTEGER NOT NULL DEFAULT 0,
                product_ok      INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_wfrl_draft
                ON wfirma_reservation_lines (draft_id);
        """)

    # ── Migration: status / wfirma_reservation_id / submitted_at / last_error ─
    # Added for Phase 3.A live-create support. Run as ALTER TABLE per column,
    # tolerating "duplicate column" on existing databases.
    _add_columns_if_missing(
        db_path,
        "wfirma_reservation_drafts",
        [
            ("status",                "TEXT NOT NULL DEFAULT 'pending'"),
            ("wfirma_reservation_id", "TEXT NOT NULL DEFAULT ''"),
            ("submitted_at",          "TEXT NOT NULL DEFAULT ''"),
            ("last_error",            "TEXT NOT NULL DEFAULT ''"),
        ],
    )


def _add_columns_if_missing(
    db_path:    Path,
    table:      str,
    columns:    List[tuple[str, str]],
) -> None:
    """ALTER TABLE ADD COLUMN for each (name, definition) — silent on duplicates."""
    with sqlite3.connect(str(db_path)) as con:
        existing = {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
        for col_name, col_def in columns:
            if col_name in existing:
                continue
            try:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
            except sqlite3.OperationalError as exc:
                # "duplicate column name" race-safe — ignore
                if "duplicate column" not in str(exc).lower():
                    raise


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(_db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── wfirma_customers ──────────────────────────────────────────────────────────

def upsert_customer(
    client_name:        str,
    *,
    wfirma_customer_id: Optional[str] = None,
    vat_id:             str = "",
    country:            str = "",
    match_status:       str = "pending",
) -> str:
    """Insert or update a customer mapping. Returns local id."""
    if _db_path is None or not client_name:
        return ""
    now = _now()
    with _lock, _connect() as con:
        existing = con.execute(
            "SELECT id FROM wfirma_customers WHERE client_name=?",
            (client_name,),
        ).fetchone()
        if existing:
            con.execute(
                """UPDATE wfirma_customers
                   SET wfirma_customer_id=?, vat_id=?, country=?,
                       match_status=?, updated_at=?
                   WHERE id=?""",
                (wfirma_customer_id, vat_id, country, match_status, now, existing["id"]),
            )
            return existing["id"]
        row_id = str(uuid.uuid4())
        con.execute(
            """INSERT INTO wfirma_customers
               (id, client_name, wfirma_customer_id, vat_id, country,
                match_status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (row_id, client_name, wfirma_customer_id, vat_id, country,
             match_status, now, now),
        )
        return row_id


def get_customer(client_name: str) -> Optional[Dict[str, Any]]:
    if _db_path is None or not client_name:
        return None
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM wfirma_customers WHERE client_name=?",
            (client_name,),
        ).fetchone()
    return dict(row) if row else None


def list_customers(match_status: Optional[str] = None) -> List[Dict[str, Any]]:
    if _db_path is None:
        return []
    with _connect() as con:
        if match_status:
            rows = con.execute(
                "SELECT * FROM wfirma_customers WHERE match_status=? ORDER BY client_name",
                (match_status,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM wfirma_customers ORDER BY client_name"
            ).fetchall()
    return [dict(r) for r in rows]


# ── wfirma_products ───────────────────────────────────────────────────────────

def upsert_product(
    product_code:      str,
    *,
    wfirma_product_id: Optional[str] = None,
    product_name_pl:   str = "",
    unit:              str = "szt.",
    vat_rate:          str = "23",
    warehouse_id:      str = "",
    sync_status:       str = "pending",
) -> str:
    """Insert or update a product mapping. Returns local id."""
    if _db_path is None or not product_code:
        return ""
    now = _now()
    with _lock, _connect() as con:
        existing = con.execute(
            "SELECT id FROM wfirma_products WHERE product_code=?",
            (product_code,),
        ).fetchone()
        if existing:
            con.execute(
                """UPDATE wfirma_products
                   SET wfirma_product_id=?, product_name_pl=?, unit=?,
                       vat_rate=?, warehouse_id=?, sync_status=?, updated_at=?
                   WHERE id=?""",
                (wfirma_product_id, product_name_pl, unit, vat_rate,
                 warehouse_id, sync_status, now, existing["id"]),
            )
            return existing["id"]
        row_id = str(uuid.uuid4())
        con.execute(
            """INSERT INTO wfirma_products
               (id, product_code, wfirma_product_id, product_name_pl,
                unit, vat_rate, warehouse_id, sync_status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (row_id, product_code, wfirma_product_id, product_name_pl,
             unit, vat_rate, warehouse_id, sync_status, now, now),
        )
        return row_id


def get_product(product_code: str) -> Optional[Dict[str, Any]]:
    if _db_path is None or not product_code:
        return None
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM wfirma_products WHERE product_code=?",
            (product_code,),
        ).fetchone()
    return dict(row) if row else None


def list_products(sync_status: Optional[str] = None) -> List[Dict[str, Any]]:
    if _db_path is None:
        return []
    with _connect() as con:
        if sync_status:
            rows = con.execute(
                "SELECT * FROM wfirma_products WHERE sync_status=? ORDER BY product_code",
                (sync_status,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM wfirma_products ORDER BY product_code"
            ).fetchall()
    return [dict(r) for r in rows]


# ── wfirma_reservation_drafts ─────────────────────────────────────────────────

def upsert_reservation_draft(
    batch_id:       str,
    client_name:    str,
    *,
    client_ref:     str = "",
    currency:       str = "USD",
    warehouse_id:   str = "",
    ready_to_create: bool = False,
) -> str:
    """Insert or update a reservation draft. Returns draft id."""
    if _db_path is None or not batch_id or not client_name:
        return ""
    now = _now()
    with _lock, _connect() as con:
        existing = con.execute(
            "SELECT id FROM wfirma_reservation_drafts WHERE batch_id=? AND client_name=?",
            (batch_id, client_name),
        ).fetchone()
        if existing:
            con.execute(
                """UPDATE wfirma_reservation_drafts
                   SET client_ref=?, currency=?, warehouse_id=?,
                       ready_to_create=?, updated_at=?
                   WHERE id=?""",
                (client_ref, currency, warehouse_id,
                 1 if ready_to_create else 0, now, existing["id"]),
            )
            return existing["id"]
        draft_id = str(uuid.uuid4())
        con.execute(
            """INSERT INTO wfirma_reservation_drafts
               (id, batch_id, client_name, client_ref, currency,
                warehouse_id, ready_to_create, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (draft_id, batch_id, client_name, client_ref, currency,
             warehouse_id, 1 if ready_to_create else 0, now, now),
        )
        return draft_id


def get_reservation_draft(batch_id: str, client_name: str) -> Optional[Dict[str, Any]]:
    if _db_path is None:
        return None
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM wfirma_reservation_drafts WHERE batch_id=? AND client_name=?",
            (batch_id, client_name),
        ).fetchone()
    return dict(row) if row else None


def list_reservation_drafts(batch_id: str) -> List[Dict[str, Any]]:
    if _db_path is None:
        return []
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM wfirma_reservation_drafts WHERE batch_id=? ORDER BY client_name",
            (batch_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── wfirma_reservation_lines ──────────────────────────────────────────────────

def upsert_reservation_line(
    draft_id:       str,
    product_code:   str,
    *,
    product_name_pl: str = "",
    qty:            float = 0.0,
    unit_price:     float = 0.0,
    currency:       str = "USD",
    stock_ok:       bool = False,
    product_ok:     bool = False,
) -> str:
    """Insert or update a reservation line. Returns line id."""
    if _db_path is None or not draft_id or not product_code:
        return ""
    now = _now()
    with _lock, _connect() as con:
        existing = con.execute(
            "SELECT id FROM wfirma_reservation_lines WHERE draft_id=? AND product_code=?",
            (draft_id, product_code),
        ).fetchone()
        if existing:
            con.execute(
                """UPDATE wfirma_reservation_lines
                   SET product_name_pl=?, qty=?, unit_price=?, currency=?,
                       stock_ok=?, product_ok=?
                   WHERE id=?""",
                (product_name_pl, qty, unit_price, currency,
                 1 if stock_ok else 0, 1 if product_ok else 0, existing["id"]),
            )
            return existing["id"]
        line_id = str(uuid.uuid4())
        con.execute(
            """INSERT INTO wfirma_reservation_lines
               (id, draft_id, product_code, product_name_pl, qty, unit_price,
                currency, stock_ok, product_ok, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (line_id, draft_id, product_code, product_name_pl, qty, unit_price,
             currency, 1 if stock_ok else 0, 1 if product_ok else 0, now),
        )
        return line_id


def list_reservation_lines(draft_id: str) -> List[Dict[str, Any]]:
    if _db_path is None:
        return []
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM wfirma_reservation_lines WHERE draft_id=? ORDER BY product_code",
            (draft_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Phase 3.A: draft status transitions ───────────────────────────────────────
#
# Status state machine:
#   pending     — newly created, never submitted
#   submitting  — actively being POSTed to wFirma; rejects concurrent submit
#   created     — wFirma returned an ID; terminal (idempotent)
#   failed      — submission failed; eligible for retry
#
# All transitions go through the wfirma_db helpers below to keep the lock /
# atomicity rules consistent.

def get_reservation_draft_by_id(draft_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single draft by primary key."""
    if _db_path is None or not draft_id:
        return None
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM wfirma_reservation_drafts WHERE id=?",
            (draft_id,),
        ).fetchone()
    return dict(row) if row else None


def mark_draft_submitting(draft_id: str) -> bool:
    """
    Atomic transition pending|failed → submitting. Returns True if the
    transition happened (caller may proceed to POST), False if another
    worker already moved the draft (caller must NOT submit).
    """
    if _db_path is None or not draft_id:
        return False
    now = _now()
    with _lock, _connect() as con:
        cur = con.execute(
            """UPDATE wfirma_reservation_drafts
               SET status='submitting', submitted_at=?, last_error='', updated_at=?
               WHERE id=? AND status IN ('pending', 'failed')""",
            (now, now, draft_id),
        )
        return cur.rowcount > 0


def mark_draft_created(draft_id: str, wfirma_reservation_id: str) -> bool:
    """Transition submitting → created. Stores wFirma reservation ID."""
    if _db_path is None or not draft_id:
        return False
    now = _now()
    with _lock, _connect() as con:
        cur = con.execute(
            """UPDATE wfirma_reservation_drafts
               SET status='created', wfirma_reservation_id=?, last_error='', updated_at=?
               WHERE id=? AND status='submitting'""",
            (wfirma_reservation_id, now, draft_id),
        )
        return cur.rowcount > 0


def mark_draft_failed(draft_id: str, error_message: str) -> bool:
    """Transition submitting → failed. Stores error text for operator review."""
    if _db_path is None or not draft_id:
        return False
    now = _now()
    safe_err = (error_message or "")[:1000]   # cap to keep row size sane
    with _lock, _connect() as con:
        cur = con.execute(
            """UPDATE wfirma_reservation_drafts
               SET status='failed', last_error=?, updated_at=?
               WHERE id=? AND status='submitting'""",
            (safe_err, now, draft_id),
        )
        return cur.rowcount > 0


def reset_stuck_draft(draft_id: str, reason: str = "manual reset") -> bool:
    """
    Force submitting → failed for a draft that got stuck (e.g. process crashed
    mid-submit). Caller must check timestamp / authorise this — this helper
    only does the SQL transition.
    """
    if _db_path is None or not draft_id:
        return False
    now = _now()
    with _lock, _connect() as con:
        cur = con.execute(
            """UPDATE wfirma_reservation_drafts
               SET status='failed', last_error=?, updated_at=?
               WHERE id=? AND status='submitting'""",
            (f"reset: {reason}"[:1000], now, draft_id),
        )
        return cur.rowcount > 0
