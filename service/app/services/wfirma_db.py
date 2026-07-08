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
        # C6 T8 — lightweight corruption check on every startup.
        # PRAGMA quick_check is fast (seconds on a <100 MB DB) and catches
        # most corruption. Logs a WARNING rather than crashing the service —
        # a corrupt wfirma.db is a recoverable error; operator should restore
        # from backup and restart.
        try:
            qc_result = con.execute("PRAGMA quick_check").fetchone()
            if qc_result and qc_result[0] != "ok":
                import logging as _logging
                _logging.getLogger(__name__).error(
                    "wfirma.db PRAGMA quick_check FAILED: %s — consider restoring from backup",
                    qc_result[0],
                )
        except Exception:
            pass  # never block startup
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
            # PR-2 contractor-at-birth: authoritative contractor reference
            # carried into reservation readiness. Reference only — the unique
            # key stays (batch_id, client_name); no gating/booking change.
            ("client_contractor_id",  "TEXT NOT NULL DEFAULT ''"),
        ],
    )
    _add_columns_if_missing(
        db_path,
        "wfirma_products",
        [
            ("product_name",    "TEXT NOT NULL DEFAULT ''"),
            ("description_block", "TEXT NOT NULL DEFAULT ''"),
        ],
    )
    # Per-customer default currency for sales-side Proforma pricing fallback.
    # Used only when neither the Excel nor the operator supplied a currency.
    # Plus ship-to receiver mapping (Step 1 of Nabywca/Odbiorca support).
    # ``ship_to_mode`` selects the wFirma rendering shape; defaults to the
    # safe "no separate receiver" value so existing customers keep their
    # current Proforma behaviour until an operator opts them in.
    _add_columns_if_missing(
        db_path,
        "wfirma_customers",
        [
            ("default_currency",            "TEXT NOT NULL DEFAULT ''"),
            ("ship_to_mode",                "TEXT NOT NULL DEFAULT 'same_as_bill_to'"),
            ("ship_to_wfirma_customer_id",  "TEXT NOT NULL DEFAULT ''"),
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


def backfill_contractor_id(row_id: str, contractor_id: str) -> bool:
    """WF-3 non-destructive migration helper. Fill ``wfirma_customer_id`` on a
    legacy ``wfirma_customers`` row ONLY when it is currently empty. The write is
    keyed by the row id (never by name) and never overwrites an existing id, so
    it is rollback-safe (original data preserved) and idempotent (a second run
    fills nothing). Returns True iff a row was newly filled.
    """
    cid = (contractor_id or "").strip()
    if _db_path is None or not row_id or not cid:
        return False
    with _lock, _connect() as con:
        cur = con.execute(
            "UPDATE wfirma_customers SET wfirma_customer_id=?, updated_at=? "
            "WHERE id=? AND (wfirma_customer_id IS NULL OR wfirma_customer_id='')",
            (cid, _now(), row_id),
        )
        return cur.rowcount == 1


_ALLOWED_CURRENCIES: frozenset = frozenset({
    "EUR", "USD", "PLN", "GBP", "CHF", "JPY",
})


def set_customer_default_currency(
    client_name: str,
    currency:    str,
) -> Optional[Dict[str, Any]]:
    """
    Update ONLY ``default_currency`` (and ``updated_at``) for an existing
    mapped customer. Never creates a new customer; never touches identity
    fields (``wfirma_customer_id``, ``vat_id``, ``country``, ``match_status``).

    Returns
    -------
    None
        If *client_name* has no row in wfirma_customers (caller → HTTP 404).
    dict
        ``{"client_name", "before_currency", "after_currency", "id"}`` on
        success.

    Raises
    ------
    ValueError
        If *currency* is not in the allowed ISO set
        (``EUR | USD | PLN | GBP | CHF | JPY``).
    """
    if _db_path is None or not client_name:
        return None
    cur = (currency or "").strip().upper()
    if cur not in _ALLOWED_CURRENCIES:
        raise ValueError(
            f"currency {currency!r} not allowed; must be one of "
            f"{sorted(_ALLOWED_CURRENCIES)}"
        )
    now = _now()
    with _lock, _connect() as con:
        row = con.execute(
            "SELECT id, default_currency FROM wfirma_customers "
            "WHERE client_name=?",
            (client_name,),
        ).fetchone()
        if not row:
            return None
        before = (row["default_currency"] or "").upper()
        con.execute(
            """UPDATE wfirma_customers
               SET default_currency=?, updated_at=?
               WHERE id=?""",
            (cur, now, row["id"]),
        )
        return {
            "id":               row["id"],
            "client_name":      client_name,
            "before_currency":  before,
            "after_currency":   cur,
        }


_ALLOWED_SHIP_TO_MODES: frozenset = frozenset({
    "same_as_bill_to",      # no separate receiver — wFirma uses bill-to address
    "bill_to_alt",          # bill-to contractor's own alt-address (different_contact_address=1)
    "separate_contractor",  # ship-to is a SEPARATE wFirma contractor record
})


def set_customer_ship_to(
    client_name:                str,
    mode:                       str,
    ship_to_wfirma_customer_id: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Update ONLY ``ship_to_mode`` and ``ship_to_wfirma_customer_id`` (plus
    ``updated_at``) for an existing mapped customer. Never creates a new
    customer; never touches identity fields (``wfirma_customer_id``,
    ``vat_id``, ``country``, ``match_status``, ``default_currency``).

    Mode contract
    -------------
    same_as_bill_to        → ``ship_to_wfirma_customer_id`` is forced empty.
    bill_to_alt            → ``ship_to_wfirma_customer_id`` is forced empty.
                              wFirma renders ship-to from the bill-to
                              contractor's own alt-address fields
                              (different_contact_address=1 + contact_*).
    separate_contractor    → ``ship_to_wfirma_customer_id`` is REQUIRED
                              (non-empty, no leading/trailing whitespace).
                              The Proforma builder (Step 2) will emit
                              ``<contractor_receiver><id>...</id></contractor_receiver>``
                              against this id. The receiver MUST already
                              exist in wFirma master; this helper does NOT
                              verify existence (no fetch_contractor_by_id
                              helper exists in wfirma_client today — Step 3
                              will add the live preflight).

    Returns
    -------
    None
        If *client_name* has no row in wfirma_customers.
    dict
        ``{"id", "client_name",
            "before_mode", "before_ship_to_wfirma_customer_id",
            "after_mode",  "after_ship_to_wfirma_customer_id"}``

    Raises
    ------
    ValueError
        If *mode* is not in the allowed set, or
        ``mode == "separate_contractor"`` with an empty
        ``ship_to_wfirma_customer_id``, or the receiver id equals the
        bill-to ``wfirma_customer_id`` (silly self-reference).
    """
    if _db_path is None or not client_name:
        return None
    m = (mode or "").strip().lower()
    if m not in _ALLOWED_SHIP_TO_MODES:
        raise ValueError(
            f"ship_to_mode {mode!r} not allowed; must be one of "
            f"{sorted(_ALLOWED_SHIP_TO_MODES)}"
        )
    receiver = (ship_to_wfirma_customer_id or "").strip()
    if m == "separate_contractor":
        if not receiver:
            raise ValueError(
                "ship_to_wfirma_customer_id is required when "
                "mode='separate_contractor'"
            )
    else:
        # The two non-receiver modes always clear any stale receiver id.
        receiver = ""

    now = _now()
    with _lock, _connect() as con:
        row = con.execute(
            "SELECT id, wfirma_customer_id, ship_to_mode, "
            "ship_to_wfirma_customer_id "
            "FROM wfirma_customers WHERE client_name=?",
            (client_name,),
        ).fetchone()
        if not row:
            return None

        # Defensive: refuse self-reference for separate_contractor mode.
        if (m == "separate_contractor"
                and receiver == (row["wfirma_customer_id"] or "").strip()):
            raise ValueError(
                "ship_to_wfirma_customer_id equals the bill-to "
                "wfirma_customer_id — separate_contractor requires a "
                "DIFFERENT receiver"
            )

        before_mode     = (row["ship_to_mode"] or "same_as_bill_to")
        before_receiver = (row["ship_to_wfirma_customer_id"] or "")
        con.execute(
            """UPDATE wfirma_customers
               SET ship_to_mode=?, ship_to_wfirma_customer_id=?,
                   updated_at=?
               WHERE id=?""",
            (m, receiver, now, row["id"]),
        )
        return {
            "id":                                  row["id"],
            "client_name":                         client_name,
            "before_mode":                         before_mode,
            "before_ship_to_wfirma_customer_id":   before_receiver,
            "after_mode":                          m,
            "after_ship_to_wfirma_customer_id":    receiver,
        }


def get_customer(client_name: str) -> Optional[Dict[str, Any]]:
    if _db_path is None or not client_name:
        return None
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM wfirma_customers WHERE UPPER(client_name)=UPPER(?)",
            (client_name,),
        ).fetchone()
    return dict(row) if row else None


def get_customer_by_wfirma_id(wfirma_id: str) -> Optional[Dict[str, Any]]:
    """Reverse lookup: wfirma_customer_id → wfirma_customers row.

    Read-only local DB query.  Returns None when the contractor id is
    not present in the local cache.  **Never calls the wFirma API** —
    used by self-healing sales reprocess to recover client_name from
    operator-supplied client_contractor_id when sales_packing_lines
    rows have been corrupted (empty client_name).
    """
    if _db_path is None or not (wfirma_id or "").strip():
        return None
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM wfirma_customers WHERE wfirma_customer_id=?",
            (str(wfirma_id),),
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
    product_name:      Optional[str] = None,
    description_block: Optional[str] = None,
    unit:              str = "szt.",
    vat_rate:          str = "23",
    warehouse_id:      str = "",
    sync_status:       str = "pending",
) -> str:
    """Insert or update a product mapping. Returns local id.

    product_name and description_block use never-erase semantics: a None or empty
    incoming value never overwrites an existing non-empty stored value.
    """
    if _db_path is None or not product_code:
        return ""
    now = _now()
    with _lock, _connect() as con:
        existing = con.execute(
            "SELECT id, product_name, description_block FROM wfirma_products WHERE product_code=?",
            (product_code,),
        ).fetchone()
        if existing:
            eff_pname  = (product_name or "").strip() or (existing["product_name"] or "")
            eff_dblock = (description_block or "").strip() or (existing["description_block"] or "")
            con.execute(
                """UPDATE wfirma_products
                   SET wfirma_product_id=?, product_name_pl=?, product_name=?,
                       description_block=?, unit=?,
                       vat_rate=?, warehouse_id=?, sync_status=?, updated_at=?
                   WHERE id=?""",
                (wfirma_product_id, product_name_pl, eff_pname, eff_dblock,
                 unit, vat_rate, warehouse_id, sync_status, now, existing["id"]),
            )
            return existing["id"]
        eff_pname  = (product_name or "").strip()
        eff_dblock = (description_block or "").strip()
        row_id = str(uuid.uuid4())
        con.execute(
            """INSERT INTO wfirma_products
               (id, product_code, wfirma_product_id, product_name_pl, product_name,
                description_block, unit, vat_rate, warehouse_id, sync_status,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (row_id, product_code, wfirma_product_id, product_name_pl, eff_pname,
             eff_dblock, unit, vat_rate, warehouse_id, sync_status, now, now),
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


def get_products_batch(product_codes: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch multiple products in a single query. Returns {product_code: row_dict}.

    Performance: O(1) round-trips vs O(N) individual get_product() calls.
    Use in ensure_products_for_batch() loops instead of per-code get_product().
    """
    if _db_path is None or not product_codes:
        return {}
    placeholders = ",".join("?" for _ in product_codes)
    with _connect() as con:
        rows = con.execute(
            f"SELECT * FROM wfirma_products WHERE product_code IN ({placeholders})",
            product_codes,
        ).fetchall()
    return {row["product_code"]: dict(row) for row in rows}


def adopt_pending_product(product_code: str) -> bool:
    """Adopt a found-in-wFirma product into local 'matched' authority.

    LOCAL ONLY — never calls wFirma, never creates/edits a good. Flips ONLY a
    row that already carries a wfirma_product_id AND sync_status=='pending_adoption'
    (i.e. the product was discovered in wFirma and is awaiting an explicit
    operator decision). All other columns are preserved. Returns True iff a row
    was adopted; False for missing / already-matched / non-pending / unlinked
    rows. Idempotent — re-running after adoption is a no-op (returns False).
    """
    if _db_path is None or not (product_code or "").strip():
        return False
    now = _now()
    with _lock, _connect() as con:
        cur = con.execute(
            """UPDATE wfirma_products
                  SET sync_status='matched', updated_at=?
                WHERE product_code=?
                  AND sync_status='pending_adoption'
                  AND wfirma_product_id IS NOT NULL
                  AND TRIM(wfirma_product_id) <> ''""",
            (now, product_code.strip()),
        )
        return cur.rowcount > 0


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
    client_contractor_id: str = "",
) -> str:
    """Insert or update a reservation draft. Returns draft id.

    PR-2: ``client_contractor_id`` is the authoritative contractor reference
    carried into reservation readiness. Reference only — the unique key stays
    (batch_id, client_name) and readiness/booking logic is unchanged. Merge-
    not-replace: an empty incoming value never clears a stored reference.
    """
    if _db_path is None or not batch_id or not client_name:
        return ""
    now = _now()
    cid = str(client_contractor_id or "").strip()
    with _lock, _connect() as con:
        existing = con.execute(
            "SELECT id, client_contractor_id FROM wfirma_reservation_drafts "
            "WHERE batch_id=? AND client_name=?",
            (batch_id, client_name),
        ).fetchone()
        if existing:
            existing_cid = (existing["client_contractor_id"] or "").strip()
            cid_to_write = cid or existing_cid
            con.execute(
                """UPDATE wfirma_reservation_drafts
                   SET client_ref=?, currency=?, warehouse_id=?,
                       ready_to_create=?, client_contractor_id=?, updated_at=?
                   WHERE id=?""",
                (client_ref, currency, warehouse_id,
                 1 if ready_to_create else 0, cid_to_write, now, existing["id"]),
            )
            return existing["id"]
        draft_id = str(uuid.uuid4())
        con.execute(
            """INSERT INTO wfirma_reservation_drafts
               (id, batch_id, client_name, client_ref, currency,
                warehouse_id, ready_to_create, client_contractor_id,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (draft_id, batch_id, client_name, client_ref, currency,
             warehouse_id, 1 if ready_to_create else 0, cid, now, now),
        )
        return draft_id


def rename_reservation_draft_client(
    batch_id: str, old_client_name: str, new_client_name: str,
) -> Dict[str, Any]:
    """PR-3: move a reservation draft from old_client_name → new_client_name.

    Canonical-wins on collision: if a reservation draft already exists under
    new_client_name, the OLD draft (and its lines) is removed and the canonical
    one kept; otherwise the old draft is renamed in place (keeping its lines).
    Lines are deleted explicitly (not relying on the per-connection CASCADE
    pragma). Never raises on a missing old draft. Returns an action summary.
    """
    if _db_path is None or not batch_id or not old_client_name:
        return {"action": "noop"}
    if old_client_name == new_client_name:
        return {"action": "noop"}
    now = _now()
    with _lock, _connect() as con:
        old_row = con.execute(
            "SELECT id FROM wfirma_reservation_drafts "
            "WHERE batch_id=? AND client_name=?",
            (batch_id, old_client_name),
        ).fetchone()
        if not old_row:
            return {"action": "noop"}
        new_row = con.execute(
            "SELECT id FROM wfirma_reservation_drafts "
            "WHERE batch_id=? AND client_name=?",
            (batch_id, new_client_name),
        ).fetchone()
        if new_row:
            line_n = con.execute(
                "SELECT COUNT(*) FROM wfirma_reservation_lines WHERE draft_id=?",
                (old_row["id"],),
            ).fetchone()[0]
            con.execute("DELETE FROM wfirma_reservation_lines WHERE draft_id=?",
                        (old_row["id"],))
            con.execute("DELETE FROM wfirma_reservation_drafts WHERE id=?",
                        (old_row["id"],))
            return {"action": "dropped_old", "old_id": old_row["id"],
                    "dropped_lines": int(line_n)}
        con.execute(
            "UPDATE wfirma_reservation_drafts SET client_name=?, updated_at=? WHERE id=?",
            (new_client_name, now, old_row["id"]),
        )
        return {"action": "renamed", "id": old_row["id"]}


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
