"""
stock_promotion_note_db.py — BE-2: Stock Promotion Note (Internal Stock
Movement document) storage + the platform's FIRST local document series.

OPERATOR CONTRACT (verbatim — PROJECT_STATE DECISIONS "BE-2 Stock Promotion
Note", 2026-07-02): "Stock Promotion Note created on every Temp Warehouse ->
Final Stock move, recording: source stage, destination stage, packing list /
import reference, design numbers, batch numbers, piece count, operator,
timestamp, reason/note, before/after inventory state."

Storage: warehouse.db (inventory domain — same file inventory_state_engine,
sample/returns events, and location writes live in), attached via
warehouse_db._db_path like inventory_state_engine (:345-349 idiom). Tables
are created idempotently on first touch (CREATE TABLE IF NOT EXISTS —
warehouse_receipt_db precedent); production picks the schema up at deploy
under deploy_persistence_storage_reviewer, no draft-migration file.

SERIES — SPN/NNN/YYYY. THIS IS THE LOCAL-SERIES PRECEDENT: future local
document series copy these semantics —
  * one writer transaction: BEGIN IMMEDIATE serialises cross-process writers
    at the SQLite level; the module _lock serialises in-process threads;
  * next number = MAX(series_seq)+1 scoped to series_year (no gaps on
    success, restarts each calendar year);
  * UNIQUE(note_no) + UNIQUE(series_year, series_seq) as the backstop; on
    IntegrityError the writer retries with the next number (bounded).

The Note is a DERIVATIVE document: inventory_state (single-writer:
inventory_state_engine.transition only) remains the truth. Note writes are
best-effort from the caller's perspective — see stock_promotion.py.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import warehouse_db as wdb

log = logging.getLogger(__name__)

_lock = threading.Lock()

_SERIES_PREFIX = "SPN"
_MAX_SERIES_RETRIES = 5


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    if wdb._db_path is None:
        raise RuntimeError(
            "warehouse_db not initialised — call init_warehouse_db() first"
        )
    con = sqlite3.connect(str(wdb._db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _ensure_tables(con: sqlite3.Connection) -> None:
    """Idempotent, first-touch table creation (warehouse_receipt_db idiom)."""
    con.executescript("""
        CREATE TABLE IF NOT EXISTS stock_promotion_notes (
            id                   TEXT PRIMARY KEY,
            note_no              TEXT NOT NULL UNIQUE,
            series_year          INTEGER NOT NULL,
            series_seq           INTEGER NOT NULL,
            batch_id             TEXT NOT NULL,
            source_stage         TEXT NOT NULL,
            dest_stage           TEXT NOT NULL,
            trigger              TEXT NOT NULL,
            source               TEXT NOT NULL DEFAULT '',
            operator             TEXT NOT NULL DEFAULT '',
            reason_note          TEXT NOT NULL DEFAULT '',
            packing_document_ids TEXT NOT NULL DEFAULT '',
            invoice_nos          TEXT NOT NULL DEFAULT '',
            wfirma_pz_doc_id     TEXT NOT NULL DEFAULT '',
            piece_count          INTEGER NOT NULL,
            created_at           TEXT NOT NULL,
            UNIQUE (series_year, series_seq)
        );
        CREATE INDEX IF NOT EXISTS idx_spn_batch
            ON stock_promotion_notes (batch_id);

        CREATE TABLE IF NOT EXISTS stock_promotion_note_lines (
            id                   TEXT PRIMARY KEY,
            note_id              TEXT NOT NULL,
            scan_code            TEXT NOT NULL,
            design_no            TEXT NOT NULL DEFAULT '',
            batch_no             TEXT NOT NULL DEFAULT '',
            invoice_no           TEXT NOT NULL DEFAULT '',
            packing_document_id  TEXT NOT NULL DEFAULT '',
            state_before         TEXT NOT NULL,
            state_after          TEXT NOT NULL,
            transition_event_id  TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (note_id) REFERENCES stock_promotion_notes(id)
        );
        CREATE INDEX IF NOT EXISTS idx_spn_lines_note
            ON stock_promotion_note_lines (note_id);
    """)


def _format_note_no(year: int, seq: int) -> str:
    return f"{_SERIES_PREFIX}/{seq:03d}/{year}"


def _distinct_joined(moved: List[Dict[str, Any]], key: str) -> str:
    """Distinct, order-preserving, comma-joined values for the header.

    A batch's pieces may span multiple invoices / packing documents (the
    golden batch covers invoices 039-044), so the header carries the joined
    distinct set while lines stay per-piece exact.
    """
    seen: List[str] = []
    for m in moved:
        v = str(m.get(key, "") or "").strip()
        if v and v not in seen:
            seen.append(v)
    return ", ".join(seen)


def _transition_event_id(con: sqlite3.Connection, scan_code: str,
                         dest_stage: str) -> str:
    """Latest engine event for this piece's promotion — the engine does not
    return its event id (inventory_state_engine.py:701-708), so the Note
    resolves it here, best-effort ('' on miss, never raises)."""
    try:
        row = con.execute(
            "SELECT id FROM inventory_state_events "
            "WHERE scan_code=? AND to_state=? "
            "ORDER BY occurred_at DESC LIMIT 1",
            (scan_code, dest_stage),
        ).fetchone()
        return row["id"] if row else ""
    except Exception:
        return ""


def write_promotion_note(
    *,
    batch_id: str,
    moved: List[Dict[str, Any]],
    trigger: str,
    source: str = "",
    operator: str = "",
    reason_note: str = "",
    source_stage: str = "PURCHASE_TRANSIT",
    dest_stage: str = "WAREHOUSE_STOCK",
    wfirma_pz_doc_id: str = "",
    now_iso: Optional[str] = None,
) -> str:
    """Write ONE Note covering exactly the *moved* subset. Returns note_no.

    Raises ValueError on an empty moved list (callers must not create
    zero-piece Notes — a no-op promotion produces NO Note). Series
    concurrency per the module docstring. *now_iso* is injectable for the
    year-rollover tests only; production callers omit it.
    """
    if not moved:
        raise ValueError("write_promotion_note: refusing a zero-piece Note")
    now = now_iso or _now()
    year = int(now[:4])

    with _lock, _connect() as con:
        _ensure_tables(con)
        last_exc: Optional[Exception] = None
        for _attempt in range(_MAX_SERIES_RETRIES):
            try:
                # LOCAL-SERIES PRECEDENT: BEGIN IMMEDIATE takes the write
                # lock BEFORE the MAX read, so no two writers can compute
                # the same next number from the same snapshot.
                con.execute("BEGIN IMMEDIATE")
                row = con.execute(
                    "SELECT COALESCE(MAX(series_seq), 0) AS m "
                    "FROM stock_promotion_notes WHERE series_year=?",
                    (year,),
                ).fetchone()
                seq = int(row["m"]) + 1
                note_no = _format_note_no(year, seq)
                note_id = str(uuid.uuid4())
                con.execute(
                    """INSERT INTO stock_promotion_notes
                       (id, note_no, series_year, series_seq, batch_id,
                        source_stage, dest_stage, trigger, source, operator,
                        reason_note, packing_document_ids, invoice_nos,
                        wfirma_pz_doc_id, piece_count, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (note_id, note_no, year, seq, batch_id,
                     source_stage, dest_stage, trigger, source, operator,
                     reason_note,
                     _distinct_joined(moved, "packing_document_id"),
                     _distinct_joined(moved, "invoice_no"),
                     wfirma_pz_doc_id, len(moved), now),
                )
                for m in moved:
                    sc = str(m.get("scan_code", "") or "")
                    con.execute(
                        """INSERT INTO stock_promotion_note_lines
                           (id, note_id, scan_code, design_no, batch_no,
                            invoice_no, packing_document_id,
                            state_before, state_after, transition_event_id)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (str(uuid.uuid4()), note_id, sc,
                         str(m.get("design_no", "") or ""),
                         str(m.get("batch_no", "") or ""),
                         str(m.get("invoice_no", "") or ""),
                         str(m.get("packing_document_id", "") or ""),
                         str(m.get("state_before", "") or ""),
                         str(m.get("state_after", "") or dest_stage),
                         _transition_event_id(con, sc, dest_stage)),
                    )
                con.commit()
                return note_no
            except sqlite3.IntegrityError as exc:
                # A racing writer won this number — retry with the next.
                con.rollback()
                last_exc = exc
            except Exception:
                con.rollback()
                raise
        raise RuntimeError(
            f"write_promotion_note: series allocation failed after "
            f"{_MAX_SERIES_RETRIES} retries: {last_exc}"
        )


def get_note(note_no: str) -> Optional[Dict[str, Any]]:
    """Header + lines for one Note, or None. Never raises on missing tables
    (fresh DB with no Notes yet = honest None)."""
    if not note_no:
        return None
    with _connect() as con:
        _ensure_tables(con)
        head = con.execute(
            "SELECT * FROM stock_promotion_notes WHERE note_no=?",
            (note_no,),
        ).fetchone()
        if head is None:
            return None
        lines = con.execute(
            "SELECT * FROM stock_promotion_note_lines WHERE note_id=? "
            "ORDER BY scan_code",
            (head["id"],),
        ).fetchall()
    out = dict(head)
    out["lines"] = [dict(r) for r in lines]
    return out


def list_notes(batch_id: str) -> List[Dict[str, Any]]:
    """Headers for a batch, newest first (lines via get_note)."""
    if not batch_id:
        return []
    with _connect() as con:
        _ensure_tables(con)
        rows = con.execute(
            "SELECT * FROM stock_promotion_notes WHERE batch_id=? "
            "ORDER BY created_at DESC",
            (batch_id,),
        ).fetchall()
    return [dict(r) for r in rows]
