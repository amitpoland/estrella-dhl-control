"""
Phase 4A -- payment_state.db schema and access layer.

Authority: wFirma payments API (read-only).
Database: C:\\PZ\\storage\\payment_state.db

Tables
------
wfirma_payment_snapshots  — append-only, keyed by payment_id UNIQUE. Rows are never
                            deleted; a payment withdrawn upstream is tombstoned via
                            source_deleted_at and drops out of the money path only.
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


def _connect(db_path: Path) -> sqlite3.Connection:
    """Tuned connection — WAL + busy_timeout per the dhl_thread_lock idiom
    (dhl_thread_lock.py:126-129; infra health pass d67d3722 finding #2):
    APScheduler-thread writer with no lock protection before this; every
    connection now waits out a competing writer (busy_timeout FIRST, so the
    WAL flip itself waits) instead of failing 'database is locked'."""
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_payment_db(db_path: Path) -> None:
    """Create payment_state.db and all Phase 4A tables if not already present."""
    with _connect(db_path) as conn:
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
        # Additive upgrades — never DROP. Keep INSERT OR IGNORE working
        # without requiring expense_id in the insert column list.
        _add_column_if_missing(conn, "wfirma_payment_snapshots", "expense_id", "TEXT")
        # Payment lifecycle. wFirma exposes NO deletion flag on <payment> (the only
        # ``*_del`` tags are compensation_del / interest_del, which are AMOUNTS).
        # Deletion is signalled by absence from a COMPLETE contractor fetch, so the
        # lifecycle has to live locally. Additive and reversible: rows are never
        # deleted, and a payment that reappears upstream is restored in place.
        #   source_deleted_at IS NULL      -> ACTIVE, participates in AR/AP
        #   source_deleted_at IS NOT NULL  -> historical, audit only, no money effect
        _add_column_if_missing(conn, "wfirma_payment_snapshots", "source_deleted_at", "TEXT")
        _add_column_if_missing(conn, "wfirma_payment_snapshots", "source_restored_at", "TEXT")
        # Stamped by reconcile_contractor_payments only. Distinct from
        # last_synced_at, which the scheduler stamps for snapshot ingestion:
        # a contractor can be synced without being reconciled (partial fetch),
        # and conflating the two would report a convergence that never ran.
        _add_column_if_missing(conn, "payment_sync_state", "last_reconciled_at", "TEXT")
        _add_column_if_missing(conn, "payment_sync_state", "last_error", "TEXT")
        _add_column_if_missing(conn, "payment_sync_state", "last_error_at", "TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wps_payment_date "
            "ON wfirma_payment_snapshots (payment_date)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wps_expense "
            "ON wfirma_payment_snapshots (expense_id)"
        )
        conn.commit()


def _add_column_if_missing(conn: sqlite3.Connection, table: str, col: str, decl: str) -> None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


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
    with _connect(db_path) as conn:
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


def _normalize_stored_doc_link(raw: Optional[str]) -> str:
    """Same sentinel rule as ledger_aggregator._normalize_doc_link_id.

    Live wFirma sends ``invoice/id=0`` and ``expense/id=0`` as no-link
    sentinels. Empty / whitespace / literal ``"0"`` → empty string.
    """
    s = (raw or "").strip()
    if not s or s == "0":
        return ""
    return s


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
    expense_id: Optional[str] = None,
    converge_expense_link: bool = False,
) -> bool:
    """
    INSERT OR IGNORE payment snapshot.
    Returns True when the row was newly inserted, False when already present.

    ``expense_id`` is the canonical wFirma ``<expense><id>`` relationship.
    When ``converge_expense_link`` is True (payment sync / backfill), an
    existing row's ``expense_id`` is updated to the fetched canonical value
    — including clearing a stale link when wFirma now sends the ``0``
    sentinel. Contractor identity and other snapshot columns are never
    overwritten on a duplicate payment_id.
    """
    link = _normalize_stored_doc_link(expense_id)
    with _connect(db_path) as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO wfirma_payment_snapshots
               (payment_id, contractor_id, invoice_id, expense_id, payment_date, value, value_pln,
                currency_label, payment_method, payment_type, type, notes, fetched_at, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (payment_id, contractor_id, invoice_id, link, payment_date, value, value_pln,
             currency_label, payment_method, payment_type, type_, notes, fetched_at, raw_json),
        )
        inserted = cur.rowcount > 0
        if converge_expense_link:
            old_row = conn.execute(
                "SELECT expense_id FROM wfirma_payment_snapshots WHERE payment_id = ?",
                (payment_id,),
            ).fetchone()
            old_link = _normalize_stored_doc_link(old_row[0] if old_row else None)
            if old_link and not link:
                log.warning(
                    "payment_snapshot: converge cleared expense_id payment_id=%s "
                    "old_expense_id=%s (wFirma sent no-link sentinel)",
                    payment_id,
                    old_link,
                )
            conn.execute(
                """UPDATE wfirma_payment_snapshots
                   SET expense_id = ?
                   WHERE payment_id = ?
                     AND COALESCE(expense_id, '') != ?""",
                (link, payment_id, link),
            )
        conn.commit()
        return inserted


def mark_contractor_synced(
    db_path: Path,
    contractor_id: str,
    now_iso: str,
    new_count: int,
) -> None:
    """Upsert last_synced_at and accumulate snapshot_count for a contractor."""
    with _connect(db_path) as conn:
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
    with _connect(db_path) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM wfirma_payment_snapshots"
        ).fetchone()[0]


def payment_expense_link_coverage(db_path: Path) -> dict:
    """Count snapshots with vs without a canonical expense relationship."""
    init_payment_db(db_path)
    with _connect(db_path) as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM wfirma_payment_snapshots"
        ).fetchone()[0]
        linked = conn.execute(
            """SELECT COUNT(*) FROM wfirma_payment_snapshots
               WHERE expense_id IS NOT NULL
                 AND TRIM(expense_id) NOT IN ('', '0')"""
        ).fetchone()[0]
    return {
        "payments_total": int(total),
        "with_expense_relationship": int(linked),
        "without_expense_relationship": int(total) - int(linked),
    }


def list_snapshot_contractor_ids(db_path: Path) -> List[str]:
    """Distinct contractor_id values already present in payment snapshots."""
    init_payment_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """SELECT DISTINCT contractor_id FROM wfirma_payment_snapshots
               WHERE contractor_id IS NOT NULL AND TRIM(contractor_id) != ''
               ORDER BY contractor_id"""
        ).fetchall()
    return [str(r[0]) for r in rows]


def reconcile_contractor_payments(
    db_path: Path,
    *,
    contractor_id: str,
    live_payment_ids: List[str],
    now_iso: str,
) -> dict:
    """Converge local payment EXISTENCE onto a COMPLETE upstream fetch.

    Set reconciliation, because wFirma signals payment deletion only by absence.
    For one contractor: local rows whose payment_id is not in *live_payment_ids*
    are tombstoned; rows that reappear upstream are restored. No row is deleted,
    no amount is touched, and identity is always ``payment_id`` — never a
    name/amount/date heuristic.

    THE CALLER OWNS THE SAFETY DECISION. Only call this when the fetch both
    succeeded AND was exhaustive; an empty *live_payment_ids* is then a valid
    result meaning "this contractor genuinely has no payments" and correctly
    tombstones the lot. A failed, truncated or partial fetch must never reach
    here — see ``sync_payments_for_contractor``.

    Idempotent: a replay against the same upstream set is a no-op.
    """
    cid = (contractor_id or "").strip()
    if not cid:
        raise ValueError("contractor_id is required")
    live = {str(p).strip() for p in live_payment_ids if str(p).strip()}

    init_payment_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT payment_id, source_deleted_at FROM wfirma_payment_snapshots "
            "WHERE contractor_id = ?",
            (cid,),
        ).fetchall()

        to_tombstone = [(r[0],) for r in rows if r[0] not in live and r[1] is None]
        to_restore = [(r[0],) for r in rows if r[0] in live and r[1] is not None]

        if to_tombstone:
            conn.executemany(
                "UPDATE wfirma_payment_snapshots SET source_deleted_at = ? "
                "WHERE payment_id = ?",
                [(now_iso, pid) for (pid,) in to_tombstone],
            )
            log.warning(
                "payment_reconcile: tombstoned %d payment(s) absent upstream "
                "contractor_id=%s payment_ids=%s",
                len(to_tombstone), cid, [p for (p,) in to_tombstone][:20],
            )
        if to_restore:
            conn.executemany(
                "UPDATE wfirma_payment_snapshots "
                "SET source_deleted_at = NULL, source_restored_at = ? "
                "WHERE payment_id = ?",
                [(now_iso, pid) for (pid,) in to_restore],
            )
            log.info(
                "payment_reconcile: restored %d payment(s) present again "
                "contractor_id=%s payment_ids=%s",
                len(to_restore), cid, [p for (p,) in to_restore][:20],
            )
        # Stamped on EVERY successful reconciliation, including a no-op one:
        # "nothing changed" is exactly the evidence that convergence ran and
        # found local state already correct.
        conn.execute(
            "INSERT OR IGNORE INTO payment_sync_state "
            "(contractor_id, last_synced_at, snapshot_count) VALUES (?, NULL, 0)",
            (cid,),
        )
        conn.execute(
            "UPDATE payment_sync_state SET last_reconciled_at = ?, "
            "last_error = NULL, last_error_at = NULL WHERE contractor_id = ?",
            (now_iso, cid),
        )
        conn.commit()

    return {
        "contractor_id": cid,
        "local_rows": len(rows),
        "upstream_rows": len(live),
        "tombstoned": len(to_tombstone),
        "restored": len(to_restore),
    }


def record_reconcile_failure(
    db_path: Path, *, contractor_id: str, error: str, now_iso: str
) -> None:
    """Record why convergence did NOT run for this contractor.

    Both a failed fetch and a fetch that came back incomplete land here — from
    the operator's side they are the same fact: local payment state for this
    contractor is not known to be current. Cleared by the next successful
    reconciliation.
    """
    cid = (contractor_id or "").strip()
    if not cid:
        return
    init_payment_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO payment_sync_state "
            "(contractor_id, last_synced_at, snapshot_count) VALUES (?, NULL, 0)",
            (cid,),
        )
        conn.execute(
            "UPDATE payment_sync_state SET last_error = ?, last_error_at = ? "
            "WHERE contractor_id = ?",
            (str(error)[:300], now_iso, cid),
        )
        conn.commit()


def list_tombstoned_payments(db_path: Path) -> List[dict]:
    """Audit view of payments withdrawn upstream. Never feeds a money path."""
    init_payment_db(db_path)
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            "SELECT payment_id, contractor_id, invoice_id, expense_id, payment_date, "
            "value, currency_label, source_deleted_at, source_restored_at "
            "FROM wfirma_payment_snapshots WHERE source_deleted_at IS NOT NULL "
            "ORDER BY source_deleted_at DESC, payment_id ASC"
        ).fetchall()]


def payment_lifecycle_stats(db_path: Path) -> dict:
    """Aggregate lifecycle counters. Aggregates only — no customer-identifying
    payment detail, so this is safe for a general status endpoint."""
    init_payment_db(db_path)
    with _connect(db_path) as conn:
        total, tombstoned, restored = conn.execute(
            "SELECT COUNT(*), "
            "       COUNT(source_deleted_at), "
            "       COUNT(source_restored_at) "
            "FROM wfirma_payment_snapshots"
        ).fetchone()
        last_sync = conn.execute(
            "SELECT MAX(last_reconciled_at) FROM payment_sync_state"
        ).fetchone()[0]
        contractors = conn.execute(
            "SELECT COUNT(*) FROM payment_sync_state WHERE last_reconciled_at IS NOT NULL"
        ).fetchone()[0]
        failing = conn.execute(
            "SELECT COUNT(*) FROM payment_sync_state WHERE last_error IS NOT NULL"
        ).fetchone()[0]
        # Message text only — no contractor_id — so this stays safe to render on
        # a general status panel.
        last_error, last_error_at = conn.execute(
            "SELECT last_error, last_error_at FROM payment_sync_state "
            "WHERE last_error IS NOT NULL ORDER BY last_error_at DESC LIMIT 1"
        ).fetchone() or (None, None)
    return {
        "payments_total": int(total),
        "payments_active": int(total) - int(tombstoned),
        "payments_tombstoned": int(tombstoned),
        "payments_restored_ever": int(restored),
        "contractors_reconciled": int(contractors),
        "contractors_failing": int(failing),
        "last_reconciled_at": last_sync,
        "last_error": last_error,
        "last_error_at": last_error_at,
    }


def get_sync_state(db_path: Path) -> List[dict]:
    """Per-contractor sync state (for diagnostics)."""
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            "SELECT contractor_id, last_synced_at, snapshot_count "
            "FROM payment_sync_state ORDER BY contractor_id"
        ).fetchall()]


def list_payments_as_of(
    db_path: Path,
    as_of: str,
    *,
    invoice_ids: Optional[List[str]] = None,
    contractor_id: Optional[str] = None,
) -> List[dict]:
    """POSITION settlements: payments with payment_date <= as_of.

    THE single shared financial read for payments. Both sides of the ledger reach
    money through here — ``match_payments_to_invoices`` (AR) and
    ``match_payments_to_expenses`` (AP) — so the lifecycle predicate belongs here
    and nowhere else. Do not re-implement it in matchers, routes, analytics or UI.

    Tombstoned payments (``source_deleted_at IS NOT NULL``) are excluded: a payment
    deleted upstream must stop reducing current AR/AP. The rows are retained for
    audit; read them with ``list_tombstoned_payments``.
    """
    ao = (as_of or "").strip()
    if not ao:
        raise ValueError("as_of is required")
    init_payment_db(db_path)
    sql = (
        "SELECT payment_id, contractor_id, invoice_id, expense_id, payment_date, "
        "value, value_pln, currency_label, payment_method, payment_type, type, notes, "
        "fetched_at "
        "FROM wfirma_payment_snapshots "
        "WHERE source_deleted_at IS NULL "
        "  AND (payment_date IS NULL OR payment_date = '' OR payment_date <= ?)"
    )
    params: list = [ao]
    if contractor_id:
        sql += " AND contractor_id = ?"
        params.append(contractor_id)
    if invoice_ids is not None:
        ids = [i for i in invoice_ids if i]
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        sql += f" AND invoice_id IN ({placeholders})"
        params.extend(ids)
    sql += " ORDER BY payment_date ASC, payment_id ASC"
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
