"""
reservation_db.py — Reservation queue DB layer (new schema).

Tables
------
product_master            design_no + product_code canonical registry
design_product_mapping    design_no → product_code resolution
wfirma_product_mapping    product_code → wFirma product_id sync state
wfirma_customer_mapping   client_name → wFirma customer_id sync state
reservation_queue         per-line queue rows (pending → ready → created)

Design rules
------------
- All functions take db_path: Path and open their own connection (no globals).
- row_factory = sqlite3.Row for dict-like access.
- product_code is the ONLY bridge to wFirma goods — no name-only matching.
- reservation_queue FK to product_master uses DEFERRABLE INITIALLY DEFERRED
  so blocked rows (product_code='UNMAPPED') can be inserted without a master.
- Old wfirma_db.py tables are untouched — this module is additive only.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("reservation_db")

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS product_master (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_code TEXT NOT NULL UNIQUE,
    design_no TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    metal TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    source_invoice_no TEXT NOT NULL DEFAULT '',
    source_batch_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_product_master_product_code ON product_master(product_code);
CREATE INDEX IF NOT EXISTS idx_product_master_design_no ON product_master(design_no);

CREATE TABLE IF NOT EXISTS design_product_mapping (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    design_no TEXT NOT NULL,
    product_code TEXT NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'locked',
    source TEXT NOT NULL DEFAULT 'purchase_packing',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(design_no, product_code),
    FOREIGN KEY(product_code) REFERENCES product_master(product_code)
);
CREATE INDEX IF NOT EXISTS idx_design_product_mapping_design_no ON design_product_mapping(design_no);

CREATE TABLE IF NOT EXISTS wfirma_product_mapping (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_code TEXT NOT NULL UNIQUE,
    wfirma_product_id TEXT NOT NULL DEFAULT '',
    wfirma_code TEXT NOT NULL DEFAULT '',
    wfirma_name TEXT NOT NULL DEFAULT '',
    warehouse_id TEXT NOT NULL DEFAULT '',
    sync_status TEXT NOT NULL DEFAULT 'pending',
    last_checked_at TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(product_code) REFERENCES product_master(product_code)
);
CREATE INDEX IF NOT EXISTS idx_wfirma_product_mapping_status ON wfirma_product_mapping(sync_status);

-- ── C-1a: canonical Product MIRROR (sync layer ONLY; PROJECT_STATE DECISIONS
-- "C-1 RATIFIED" LAYER RESPONSIBILITIES). EXACTLY six columns — wfirma_id,
-- product_code, sync_version, last_sync, hash, deleted_flag — never business
-- logic. Consolidates the two split mirrors (wfirma_products in wfirma.db +
-- wfirma_product_mapping above) which deprecate in place (readers redirected
-- in C-1c, tables retained). Pinned by test_master_consumption_rule.py.
CREATE TABLE IF NOT EXISTS wfirma_product_mirror (
    wfirma_id    TEXT NOT NULL DEFAULT '',
    product_code TEXT NOT NULL,
    sync_version INTEGER NOT NULL DEFAULT 1,
    last_sync    TEXT NOT NULL DEFAULT '',
    hash         TEXT NOT NULL DEFAULT '',
    deleted_flag INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_wpm_product_code ON wfirma_product_mirror(product_code);
CREATE UNIQUE INDEX IF NOT EXISTS idx_wpm_wfirma_id ON wfirma_product_mirror(wfirma_id) WHERE wfirma_id != '';

CREATE TABLE IF NOT EXISTS wfirma_customer_mapping (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_name TEXT NOT NULL UNIQUE,
    wfirma_customer_id TEXT NOT NULL DEFAULT '',
    vat_id TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT '',
    match_status TEXT NOT NULL DEFAULT 'pending',
    last_checked_at TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reservation_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_key TEXT NOT NULL UNIQUE,
    batch_id TEXT NOT NULL,
    client_name TEXT NOT NULL,
    client_ref TEXT NOT NULL DEFAULT '',
    sales_doc_no TEXT NOT NULL DEFAULT '',
    design_no TEXT NOT NULL,
    product_code TEXT NOT NULL,
    qty REAL NOT NULL,
    unit_price REAL NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'USD',
    status TEXT NOT NULL DEFAULT 'pending',
    wfirma_product_id TEXT NOT NULL DEFAULT '',
    wfirma_customer_id TEXT NOT NULL DEFAULT '',
    wfirma_reservation_id TEXT NOT NULL DEFAULT '',
    blocking_reason TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ready_at TEXT NOT NULL DEFAULT '',
    submitted_at TEXT NOT NULL DEFAULT '',
    completed_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(product_code) REFERENCES product_master(product_code)
        DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX IF NOT EXISTS idx_reservation_queue_batch ON reservation_queue(batch_id);
CREATE INDEX IF NOT EXISTS idx_reservation_queue_status ON reservation_queue(status);
CREATE INDEX IF NOT EXISTS idx_reservation_queue_product_code ON reservation_queue(product_code);
CREATE INDEX IF NOT EXISTS idx_reservation_queue_client ON reservation_queue(client_name);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Additive migration helper ──────────────────────────────────────────────────

def _add_column_if_missing(
    con:        sqlite3.Connection,
    table:      str,
    column:     str,
    definition: str,
) -> None:
    """Add *column* to *table* if it does not already exist. Additive only —
    never drops or alters existing columns.  Mirrors the pattern used in
    packing_db._add_column_if_missing and tracking_db._add_column_if_missing.
    Safe to call repeatedly (idempotent)."""
    cols = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
    if column in cols:
        return
    con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


# product_master forward-compat columns added by PR-1 Product Master Foundation.
# Additive only.  Existing rows acquire the default for each new column.
_PRODUCT_MASTER_ADDITIVE_COLUMNS = (
    ("item_type",          "TEXT NOT NULL DEFAULT ''"),
    ("hsn_code",           "TEXT NOT NULL DEFAULT ''"),
    ("unit_price_ref",     "REAL NOT NULL DEFAULT 0.0"),
    ("currency_ref",       "TEXT NOT NULL DEFAULT ''"),
    ("confidence",         "TEXT NOT NULL DEFAULT 'high'"),
    ("source_document_id", "TEXT NOT NULL DEFAULT ''"),
    ("last_seen_batch_id", "TEXT NOT NULL DEFAULT ''"),
)

# Phase 4 — Composite identity columns (Atlas Campaign).
# Composite identity = supplier_id + supplier_product_code + normalized_design_attributes.
# Additive: existing rows keep '' defaults; EJL codes remain globally unique.
# 417G codes: supplier_id populated → (supplier_id, product_code) is the
# effective composite key (not SQL-enforced cross-row, but logically unique).
# is_globally_unique mirrors the same field in product_descriptions; 0 = 417G-class.
_PRODUCT_MASTER_PHASE4_COLUMNS = (
    ("supplier_id",                   "TEXT NOT NULL DEFAULT ''"),
    ("supplier_product_code",         "TEXT NOT NULL DEFAULT ''"),
    ("normalized_design_attributes",  "TEXT NOT NULL DEFAULT ''"),
    ("is_globally_unique",            "INTEGER NOT NULL DEFAULT 1"),
)

# C-1a — product_master promoted to the EJ Dashboard Product MASTER authority
# (PROJECT_STATE DECISIONS "C-1 RATIFIED"). Adds the business authority fields
# (status incl. 'mapping_required', is_active) plus the fields folded from the
# deprecating product_local overlay (unit, origin_country, notes,
# design_code_link). hs_code_override folds into the existing hsn_code column
# at backfill (no new column). Additive, idempotent.
_PRODUCT_MASTER_C1A_AUTHORITY_COLUMNS = (
    ("status",           "TEXT NOT NULL DEFAULT 'mapping_required'"),
    ("is_active",        "INTEGER NOT NULL DEFAULT 1"),
    ("unit",             "TEXT NOT NULL DEFAULT ''"),
    ("origin_country",   "TEXT NOT NULL DEFAULT 'IN'"),
    ("notes",            "TEXT NOT NULL DEFAULT ''"),
    ("design_code_link", "TEXT NOT NULL DEFAULT ''"),
)


# ── Init ───────────────────────────────────────────────────────────────────────

def init_reservation_db(db_path: Path) -> None:
    """Create all 5 reservation tables if they don't exist and apply any
    forward-compat additive column migrations (idempotent)."""
    with _connect(db_path) as con:
        con.executescript(_DDL)
        for col, ddl in _PRODUCT_MASTER_ADDITIVE_COLUMNS:
            _add_column_if_missing(con, "product_master", col, ddl)
        # Phase 4 composite identity columns
        for col, ddl in _PRODUCT_MASTER_PHASE4_COLUMNS:
            _add_column_if_missing(con, "product_master", col, ddl)
        # C-1a — Product Master authority columns (business layer)
        for col, ddl in _PRODUCT_MASTER_C1A_AUTHORITY_COLUMNS:
            _add_column_if_missing(con, "product_master", col, ddl)
        # Phase 4 — partial unique index on (supplier_id, product_code) for 417G rows.
        # Only applies when supplier_id is non-empty (EJL rows keep the existing
        # UNIQUE(product_code) constraint; 417G rows need the composite constraint).
        try:
            con.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_pm_supplier_composite "
                "ON product_master(supplier_id, product_code) "
                "WHERE supplier_id != ''"
            )
        except Exception:
            pass  # index may already exist


# ── C-1a Product Authority backfill ─────────────────────────────────────────────

def backfill_product_authority(
    reservation_db_path: Path,
    wfirma_db_path:      Path,
    master_data_db_path: Path,
    *,
    now_iso: str,
) -> dict:
    """C-1a data backfill (PROJECT_STATE DECISIONS "C-1 RATIFIED").

    Idempotent. Populates wfirma_product_mirror from the two deprecating split
    mirrors (wfirma_products in wfirma.db + wfirma_product_mapping in the
    reservation DB), folds product_local business fields into product_master,
    and sets product_master.status from mirror presence. Reads the sibling DBs
    read-only; writes only the reservation DB. Never raises on a missing
    sibling table — degrades and reports.

    Returns {mirror_rows, status_set, local_folded}.
    """
    import hashlib

    result = {"mirror_rows": 0, "status_set": 0, "local_folded": 0,
              "wfirma_id_collisions": 0}
    init_reservation_db(reservation_db_path)

    # 1. Collect wFirma product identities from the two split sources.
    #    prefer a confirmed wfirma_product_id; carry code/name for the hash.
    ids: dict = {}   # product_code -> (wfirma_id, wfirma_code, wfirma_name)

    def _merge(pc, wid, code, name):
        pc = (pc or "").strip()
        if not pc:
            return
        wid = (wid or "").strip()
        prev = ids.get(pc)
        # a non-empty wfirma_id always wins over an empty one
        if prev is None or (not prev[0] and wid):
            ids[pc] = (wid, (code or "").strip(), (name or "").strip())

    # wfirma.db / wfirma_products (read-only)
    try:
        with sqlite3.connect(f"file:{wfirma_db_path}?mode=ro", uri=True) as wcon:
            wcon.row_factory = sqlite3.Row
            for r in wcon.execute(
                "SELECT product_code, wfirma_product_id, product_name FROM wfirma_products"
            ):
                _merge(r["product_code"], r["wfirma_product_id"], r["product_code"], r["product_name"])
    except Exception:
        pass  # table/file may be absent in a fresh tree

    # reservation.db / wfirma_product_mapping (same file)
    with _connect(reservation_db_path) as con:
        try:
            for r in con.execute(
                "SELECT product_code, wfirma_product_id, wfirma_code, wfirma_name "
                "FROM wfirma_product_mapping"
            ):
                _merge(r["product_code"], r["wfirma_product_id"], r["wfirma_code"], r["wfirma_name"])
        except Exception:
            pass

        # 2. Upsert the canonical mirror (idempotent on product_code).
        #    COLLISION-SAFE: the UNIQUE wfirma_id invariant is enforced. If two
        #    product_codes claim the SAME non-empty wfirma_id (a real
        #    data-integrity condition — one wFirma product should map to one
        #    code), the second is stored with an EMPTY mirror wfirma_id and
        #    counted as a collision, so the invariant holds and the problem is
        #    surfaced (reported) rather than crashing the migration. The
        #    already-claimed wfirma_id set is seeded from rows already present.
        # wfirma_id -> owning product_code (ownership-aware so a re-run does NOT
        # collide a row with its OWN prior entry).
        claimed = {
            r["wfirma_id"]: r["product_code"] for r in con.execute(
                "SELECT wfirma_id, product_code FROM wfirma_product_mirror WHERE wfirma_id!=''"
            )
        }
        for pc, (wid, code, name) in ids.items():
            eff_wid = wid
            owner = claimed.get(wid) if wid else None
            if wid and owner is not None and owner != pc:
                eff_wid = ""            # collision (different code) — hold UNIQUE, surface it
                result["wfirma_id_collisions"] += 1
            elif wid:
                claimed[wid] = pc
            h = hashlib.sha256(f"{eff_wid}|{code}|{name}".encode("utf-8")).hexdigest()[:32]
            existing = con.execute(
                "SELECT product_code FROM wfirma_product_mirror WHERE product_code=?", (pc,)
            ).fetchone()
            if existing:
                con.execute(
                    "UPDATE wfirma_product_mirror SET wfirma_id=?, last_sync=?, hash=?, "
                    "sync_version=sync_version+1 WHERE product_code=?",
                    (eff_wid, now_iso, h, pc),
                )
            else:
                con.execute(
                    "INSERT INTO wfirma_product_mirror "
                    "(wfirma_id, product_code, sync_version, last_sync, hash, deleted_flag) "
                    "VALUES (?,?,?,?,?,0)",
                    (eff_wid, pc, 1, now_iso, h),
                )
                result["mirror_rows"] += 1

        # 3. Master status from mirror presence (only for product_codes that
        #    have a product_master row — the master is the business authority).
        for pc, (wid, _c, _n) in ids.items():
            new_status = "mapped" if wid else "mapping_required"
            cur = con.execute(
                "UPDATE product_master SET status=?, updated_at=? "
                "WHERE product_code=? AND status!=?",
                (new_status, now_iso, pc, new_status),
            )
            result["status_set"] += cur.rowcount

        # 4. Fold product_local business fields into the master (override wins).
        try:
            with sqlite3.connect(f"file:{master_data_db_path}?mode=ro", uri=True) as mcon:
                mcon.row_factory = sqlite3.Row
                local_rows = mcon.execute(
                    "SELECT product_code, hs_code_override, unit_override, "
                    "design_code_link, notes, origin_country, active "
                    "FROM product_local"
                ).fetchall()
        except Exception:
            local_rows = []
        for lr in local_rows:
            pc = (lr["product_code"] or "").strip()
            if not pc:
                continue
            cur = con.execute(
                """UPDATE product_master SET
                       hsn_code        = CASE WHEN ?!='' THEN ? ELSE hsn_code END,
                       unit            = CASE WHEN ?!='' THEN ? ELSE unit END,
                       design_code_link= CASE WHEN ?!='' THEN ? ELSE design_code_link END,
                       notes           = CASE WHEN ?!='' THEN ? ELSE notes END,
                       origin_country  = COALESCE(NULLIF(?, ''), origin_country),
                       is_active       = ?,
                       updated_at      = ?
                   WHERE product_code=?""",
                (
                    (lr["hs_code_override"] or ""), (lr["hs_code_override"] or ""),
                    (lr["unit_override"] or ""), (lr["unit_override"] or ""),
                    (lr["design_code_link"] or ""), (lr["design_code_link"] or ""),
                    (lr["notes"] or ""), (lr["notes"] or ""),
                    (lr["origin_country"] or ""),
                    int(lr["active"]) if lr["active"] is not None else 1,
                    now_iso, pc,
                ),
            )
            result["local_folded"] += cur.rowcount

    return result


# ── C-1b — Master-first product write path (sync-layer helpers) ─────────────────
# These are the ONLY entry points a BUSINESS module uses to touch wFirma product
# data (MASTER CONSUMPTION RULE / LAYER RESPONSIBILITIES). Business routes call
# these instead of importing wfirma_client or reading the mirror tables directly.
# The write GATE (settings.wfirma_create_product_allowed) stays in the CALLING
# route — these helpers assume the caller has already decided the push is allowed
# ("unchanged in gating"). reservation_db is the whitelisted sync layer; the
# wfirma_client imports are function-local to keep import-time coupling minimal.

def lookup_wfirma_product(product_code: str):
    """Read-only wFirma goods lookup by code, via the sync layer. Returns the
    WFirmaProduct (or None). Business routes call THIS instead of importing
    wfirma_client.get_product_by_code directly (V6 + batch-resolve read)."""
    from .wfirma_client import get_product_by_code
    return get_product_by_code(product_code)


def wfirma_product_sync_client():
    """Return a thin client exposing get_product_by_code(code) for
    reservation_worker.sync_wfirma_products_by_codes, so business routes never
    import wfirma_client themselves (V6). The forbidden identifier lives here in
    the whitelisted sync layer, not in the business route."""
    from .wfirma_client import get_product_by_code as _get

    class _ProductSyncClient:
        @staticmethod
        def get_product_by_code(code):
            return _get(code)

    return _ProductSyncClient()


def set_product_master_status(
    db_path: Path,
    product_code: str,
    status: str,
    *,
    is_active: Optional[int] = None,
) -> int:
    """Set product_master.status (and optionally is_active) for an already-minted
    code. Returns rows updated. Reflects sync state: 'mapping_required' before the
    wFirma push, 'mapped' after a confirmed wfirma_id is mirrored."""
    now = _now()
    with _connect(db_path) as con:
        if is_active is None:
            cur = con.execute(
                "UPDATE product_master SET status=?, updated_at=? WHERE product_code=?",
                (status, now, product_code),
            )
        else:
            cur = con.execute(
                "UPDATE product_master SET status=?, is_active=?, updated_at=? "
                "WHERE product_code=?",
                (status, int(is_active), now, product_code),
            )
        return cur.rowcount


def upsert_product_mirror(
    db_path: Path,
    *,
    wfirma_id: str,
    product_code: str,
    name: str = "",
    also_set_master_status: Optional[str] = None,
) -> Dict[str, Any]:
    """Write the code→wfirma_id sync identity into wfirma_product_mirror — the
    ONLY place sync identity is written (LAYER RESPONSIBILITIES). Collision-safe
    on the UNIQUE(wfirma_id) invariant: if a DIFFERENT product_code already owns
    this non-empty wfirma_id (a one-good-two-codes data problem), the linkage is
    REFUSED (returned collision=True, owner=<code>) rather than breaking the
    invariant — the caller surfaces it. The UNIQUE constraint is the true
    enforcement boundary: a TOCTOU race that slips past the pre-check is caught
    as an IntegrityError and reported as a collision, so a mirror write never
    raises for a duplicate wfirma_id. Bumps sync_version + refreshes last_sync +
    hash on an existing row; inserts otherwise. When ``also_set_master_status``
    is given, the product_master.status flip runs in the SAME transaction as the
    mirror write, so the mirror and the master status can never diverge."""
    import hashlib

    now = _now()
    wfirma_id = (wfirma_id or "").strip()
    with _connect(db_path) as con:
        if wfirma_id:
            owner = con.execute(
                "SELECT product_code FROM wfirma_product_mirror "
                "WHERE wfirma_id=? AND wfirma_id!=''",
                (wfirma_id,),
            ).fetchone()
            if owner is not None and owner["product_code"] != product_code:
                return {"written": False, "collision": True, "owner": owner["product_code"]}
        h = hashlib.sha256(
            f"{wfirma_id}|{product_code}|{name}".encode("utf-8")
        ).hexdigest()[:32]
        existing = con.execute(
            "SELECT product_code FROM wfirma_product_mirror WHERE product_code=?",
            (product_code,),
        ).fetchone()
        try:
            if existing:
                con.execute(
                    "UPDATE wfirma_product_mirror SET wfirma_id=?, last_sync=?, hash=?, "
                    "sync_version=sync_version+1 WHERE product_code=?",
                    (wfirma_id, now, h, product_code),
                )
            else:
                con.execute(
                    "INSERT INTO wfirma_product_mirror "
                    "(wfirma_id, product_code, sync_version, last_sync, hash, deleted_flag) "
                    "VALUES (?,?,?,?,?,0)",
                    (wfirma_id, product_code, 1, now, h),
                )
        except sqlite3.IntegrityError:
            # Lost the UNIQUE(wfirma_id) race to a concurrent writer — the
            # constraint is the real boundary; report the actual current owner.
            owner_row = con.execute(
                "SELECT product_code FROM wfirma_product_mirror "
                "WHERE wfirma_id=? AND wfirma_id!=''",
                (wfirma_id,),
            ).fetchone()
            owner = owner_row["product_code"] if owner_row else product_code
            return {"written": False, "collision": True, "owner": owner}
        if also_set_master_status:
            con.execute(
                "UPDATE product_master SET status=?, updated_at=? WHERE product_code=?",
                (also_set_master_status, now, product_code),
            )
    return {"written": True, "collision": False, "owner": product_code}


def create_wfirma_product_via_master(
    db_path: Path,
    *,
    product_code: str,
    name: str,
    unit: str = "szt.",
    netto: float = 0.0,
    vat_code_id: Optional[str] = None,
    description: str = "",
):
    """Master-first product CREATE (write-sequence steps 2+3). The caller has
    ALREADY written the product_master row and confirmed the write gate is ON.
    This performs the wFirma push via the existing client call and, on a
    CONFIRMED wfirma_id, writes the MIRROR (sync identity) + flips
    product_master.status to 'mapped'. Returns (WFirmaProduct, mirror_result).
    On an id-less result the caller keeps the Master (sync-pending)."""
    from .wfirma_client import create_product
    result = create_product(
        product_code=product_code,
        name=name,
        unit=unit,
        netto=netto,
        vat_code_id=vat_code_id,
        description=description,
    )
    mirror = {"written": False, "collision": False, "owner": product_code}
    if result is not None and (getattr(result, "wfirma_id", "") or "").strip():
        try:
            # Mirror write + master.status='mapped' happen atomically in one
            # transaction (also_set_master_status) so they never diverge.
            mirror = upsert_product_mirror(
                db_path,
                wfirma_id=result.wfirma_id,
                product_code=product_code,
                name=name,
                also_set_master_status="mapped",
            )
        except Exception as exc:  # pragma: no cover - defensive
            # wFirma good was created but the local mirror write failed; keep the
            # successful create signal and report the mirror problem for repair.
            log.warning(
                "create_wfirma_product_via_master: wFirma good %s created but "
                "mirror write failed for %s: %s", result.wfirma_id, product_code, exc,
            )
            mirror = {"written": False, "collision": False,
                      "owner": product_code, "error": str(exc)}
    return result, mirror


def edit_wfirma_product_via_master(
    db_path: Path,
    *,
    product_code: str,
    wfirma_product_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
):
    """Master-first product EDIT: pushes the name/description change via the
    existing gated client call (gate checked by caller) and, on success, bumps
    the MIRROR sync fields for this code — PRESERVING the existing
    code→wfirma_id mapping. Returns (edit_result_dict, mirror_result)."""
    from .wfirma_client import edit_product
    result = edit_product(
        wfirma_product_id=wfirma_product_id,
        name=name,
        description=description,
    )
    try:
        mirror = upsert_product_mirror(
            db_path, wfirma_id=wfirma_product_id, product_code=product_code, name=name or ""
        )
    except Exception as exc:  # pragma: no cover - defensive
        # The wFirma edit already committed remotely; a mirror-write failure must
        # not masquerade as an edit failure. Preserve the edit result + report.
        log.warning(
            "edit_wfirma_product_via_master: wFirma good %s edited but mirror "
            "write failed for %s: %s — manual reconciliation needed",
            wfirma_product_id, product_code, exc,
        )
        mirror = {"written": False, "collision": False,
                  "owner": product_code, "error": str(exc)}
    return result, mirror


# ── product_master ─────────────────────────────────────────────────────────────

def upsert_product_master(
    db_path: Path,
    product_code: str,
    design_no: str,
    description: str = "",
    metal: str = "",
    category: str = "",
    source_invoice_no: str = "",
    source_batch_id: str = "",
    *,
    item_type:                   str   = "",
    hsn_code:                    str   = "",
    unit_price_ref:              float = 0.0,
    currency_ref:                str   = "",
    confidence:                  str   = "high",
    source_document_id:          str   = "",
    last_seen_batch_id:          str   = "",
    # Phase 4 — composite identity fields
    supplier_id:                 str   = "",
    supplier_product_code:       str   = "",
    normalized_design_attributes: str  = "",
    is_globally_unique:          int   = 1,
) -> int:
    """Insert or update a product_master row. Returns the row id.

    Idempotency key: UNIQUE(product_code) for EJL-class (globally unique) codes.
    For 417G-class codes (is_globally_unique=0), the effective composite key is
    (supplier_id, product_code) — enforced by a partial unique index.

    Re-running with the same product_code UPDATEs the existing row and
    refreshes ``updated_at`` — no duplicate row is ever created.

    Preserve-on-blank semantics: when an existing row has a non-empty
    ``design_no`` and the caller passes ``design_no=""`` (e.g. at invoice
    intake before packing is parsed), the existing value is preserved.
    This mirrors the self-heal pattern from PR #190 and prevents later
    invoice-only refreshes from wiping a packing-resolved design_no.

    ``last_seen_batch_id`` is refreshed on every call so observability
    can answer "when was this code last referenced?"; ``source_batch_id``
    stays at the originating batch.

    Never invents product_code — caller must pass an already-minted code
    (the single canonical generator is store_invoice_lines in
    document_db.py)."""
    now = _now()
    with _connect(db_path) as con:
        con.execute("PRAGMA foreign_keys=ON")
        # Phase 4: 417G codes use composite (supplier_id, product_code) as key.
        # EJL codes (supplier_id='') continue to use product_code alone.
        if supplier_id:
            existing = con.execute(
                "SELECT * FROM product_master WHERE supplier_id=? AND product_code=?",
                (supplier_id, product_code),
            ).fetchone()
        else:
            existing = con.execute(
                "SELECT * FROM product_master WHERE product_code=?",
                (product_code,),
            ).fetchone()
        if existing:
            # Preserve-on-blank semantics for the originating identity:
            #   - design_no:          keep existing when new is blank
            #   - source_batch_id:    NEVER overwrite — first batch wins
            #   - source_invoice_no:  NEVER overwrite — first invoice wins
            #   - source_document_id: NEVER overwrite — first document wins
            # last_seen_batch_id always advances to the latest referencing
            # batch (observability of recent activity).
            def _keep(new_v: Any, existing_key: str) -> Any:
                exv = existing[existing_key]
                if isinstance(new_v, str):
                    return new_v if new_v.strip() else (exv or "")
                return new_v if new_v else (exv or new_v)

            new_design_no         = _keep(design_no,         "design_no")
            keep_source_batch_id  = (existing["source_batch_id"]   or source_batch_id)
            keep_source_invoice   = (existing["source_invoice_no"] or source_invoice_no)
            keep_source_doc_id    = (existing["source_document_id"] or source_document_id)
            new_last_seen         = (last_seen_batch_id or source_batch_id
                                     or existing["last_seen_batch_id"] or "")
            # Phase 4: preserve-on-blank for composite identity fields too
            new_supplier_id    = _keep(supplier_id, "supplier_id") if "supplier_id" in existing.keys() else supplier_id
            new_sup_prod_code  = _keep(supplier_product_code, "supplier_product_code") if "supplier_product_code" in existing.keys() else supplier_product_code
            new_norm_attrs     = _keep(normalized_design_attributes, "normalized_design_attributes") if "normalized_design_attributes" in existing.keys() else normalized_design_attributes
            con.execute(
                """UPDATE product_master
                   SET design_no=?, description=?, metal=?, category=?,
                       source_invoice_no=?, source_batch_id=?,
                       item_type=?, hsn_code=?, unit_price_ref=?,
                       currency_ref=?, confidence=?,
                       source_document_id=?, last_seen_batch_id=?,
                       supplier_id=?, supplier_product_code=?,
                       normalized_design_attributes=?, is_globally_unique=?,
                       updated_at=?
                   WHERE product_code=?""",
                (new_design_no, description, metal, category,
                 keep_source_invoice, keep_source_batch_id,
                 item_type, hsn_code, unit_price_ref,
                 currency_ref, confidence,
                 keep_source_doc_id, new_last_seen,
                 new_supplier_id, new_sup_prod_code,
                 new_norm_attrs, is_globally_unique,
                 now, product_code),
            )
            return existing["id"]
        cur = con.execute(
            """INSERT INTO product_master
               (product_code, design_no, description, metal, category,
                source_invoice_no, source_batch_id,
                item_type, hsn_code, unit_price_ref,
                currency_ref, confidence,
                source_document_id, last_seen_batch_id,
                supplier_id, supplier_product_code,
                normalized_design_attributes, is_globally_unique,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (product_code, design_no, description, metal, category,
             source_invoice_no, source_batch_id,
             item_type, hsn_code, unit_price_ref,
             currency_ref, confidence,
             source_document_id,
             (last_seen_batch_id or source_batch_id),
             supplier_id, supplier_product_code,
             normalized_design_attributes, is_globally_unique,
             now, now),
        )
        return cur.lastrowid


def get_product_master(db_path: Path, product_code: str) -> Optional[Dict[str, Any]]:
    with _connect(db_path) as con:
        row = con.execute(
            "SELECT * FROM product_master WHERE product_code=?",
            (product_code,),
        ).fetchone()
    return dict(row) if row else None


def get_product_master_by_composite(
    db_path: Path,
    supplier_id: str,
    product_code: str,
) -> Optional[Dict[str, Any]]:
    """Phase 4 — look up a product_master row by (supplier_id, product_code).

    For 417G-class codes (is_globally_unique=0), the same product_code string
    may appear under different suppliers. This function resolves by the
    composite key (supplier_id, product_code) to disambiguate.

    Falls back to get_product_master(product_code) when supplier_id is empty
    or when no composite match is found (preserves backward compatibility with
    EJL-class codes that have supplier_id='').
    """
    if not supplier_id:
        return get_product_master(db_path, product_code)
    with _connect(db_path) as con:
        row = con.execute(
            "SELECT * FROM product_master WHERE supplier_id=? AND product_code=?",
            (supplier_id, product_code),
        ).fetchone()
    if row:
        return dict(row)
    # Fallback: try without supplier constraint (EJL codes)
    return get_product_master(db_path, product_code)


def validate_product_code_in_master(
    db_path: Path,
    product_code: str,
    supplier_id: str = "",
) -> bool:
    """Phase 4 — GAP 17 logical link: verify product_code exists in product_master.

    Used at write time by inventory, proforma, and sales surfaces to assert that
    every product_code references a known master row. This is a logical (not SQL FK)
    check because the line tables live in different DB files.

    Returns True when the product_code is found. Returns False (not raises) when
    absent — callers decide whether to block or emit an advisory.
    """
    row = get_product_master_by_composite(db_path, supplier_id, product_code)
    return row is not None


def list_product_masters(
    db_path: Path,
    source_batch_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    with _connect(db_path) as con:
        if source_batch_id is not None:
            rows = con.execute(
                "SELECT * FROM product_master WHERE source_batch_id=? ORDER BY product_code",
                (source_batch_id,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM product_master ORDER BY product_code"
            ).fetchall()
    return [dict(r) for r in rows]


def get_product_master_statuses(db_path: Path, product_codes) -> Dict[str, str]:
    """Batch read of product_master.status for a set of codes → {code: status}.
    Additive read accessor (C-1c) so business modules do readiness checks against
    the Product Master authority instead of the wfirma_db split cache. Missing
    codes are simply absent from the returned map."""
    codes = [c for c in {(pc or "").strip() for pc in product_codes} if c]
    # Read-only + side-effect-free: never create the DB file; tolerate a missing
    # product_master table (returns {} → callers treat those codes as unmapped).
    if not codes or not Path(db_path).exists():
        return {}
    out: Dict[str, str] = {}
    try:
        with _connect(db_path) as con:
            ph = ",".join("?" * len(codes))
            for row in con.execute(
                f"SELECT product_code, status FROM product_master WHERE product_code IN ({ph})",
                codes,
            ):
                out[row["product_code"]] = row["status"]
    except sqlite3.OperationalError:
        return {}
    return out


# ── design_product_mapping ────────────────────────────────────────────────────

def upsert_design_mapping(
    db_path: Path,
    design_no: str,
    product_code: str,
    confidence: str = "locked",
    source: str = "purchase_packing",
) -> int:
    """Insert or update a design → product_code mapping. Returns row id."""
    now = _now()
    with _connect(db_path) as con:
        existing = con.execute(
            "SELECT id FROM design_product_mapping WHERE design_no=? AND product_code=?",
            (design_no, product_code),
        ).fetchone()
        if existing:
            con.execute(
                """UPDATE design_product_mapping
                   SET confidence=?, source=?, updated_at=?
                   WHERE design_no=? AND product_code=?""",
                (confidence, source, now, design_no, product_code),
            )
            return existing["id"]
        cur = con.execute(
            """INSERT INTO design_product_mapping
               (design_no, product_code, confidence, source, created_at, updated_at)
               VALUES (?,?,?,?,?,?)""",
            (design_no, product_code, confidence, source, now, now),
        )
        return cur.lastrowid


def get_product_code_by_design_no(
    db_path: Path,
    design_no: str,
) -> Optional[Dict[str, Any]]:
    """Return the most recently updated mapping for design_no, or None."""
    with _connect(db_path) as con:
        row = con.execute(
            """SELECT * FROM design_product_mapping
               WHERE design_no=?
               ORDER BY updated_at DESC LIMIT 1""",
            (design_no,),
        ).fetchone()
    return dict(row) if row else None


# ── wfirma_product_mapping ────────────────────────────────────────────────────

def upsert_wfirma_product_mapping(
    db_path: Path,
    product_code: str,
    wfirma_product_id: str = "",
    wfirma_code: str = "",
    wfirma_name: str = "",
    warehouse_id: str = "",
    sync_status: str = "pending",
    last_checked_at: str = "",
    last_error: str = "",
) -> int:
    """Insert or update wFirma product sync state. Returns row id."""
    now = _now()
    with _connect(db_path) as con:
        existing = con.execute(
            "SELECT id FROM wfirma_product_mapping WHERE product_code=?",
            (product_code,),
        ).fetchone()
        if existing:
            con.execute(
                """UPDATE wfirma_product_mapping
                   SET wfirma_product_id=?, wfirma_code=?, wfirma_name=?,
                       warehouse_id=?, sync_status=?, last_checked_at=?,
                       last_error=?, updated_at=?
                   WHERE product_code=?""",
                (wfirma_product_id, wfirma_code, wfirma_name,
                 warehouse_id, sync_status, last_checked_at,
                 last_error, now, product_code),
            )
            return existing["id"]
        cur = con.execute(
            """INSERT INTO wfirma_product_mapping
               (product_code, wfirma_product_id, wfirma_code, wfirma_name,
                warehouse_id, sync_status, last_checked_at, last_error,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (product_code, wfirma_product_id, wfirma_code, wfirma_name,
             warehouse_id, sync_status, last_checked_at, last_error,
             now, now),
        )
        return cur.lastrowid


def get_wfirma_product_mapping(
    db_path: Path,
    product_code: str,
) -> Optional[Dict[str, Any]]:
    with _connect(db_path) as con:
        row = con.execute(
            "SELECT * FROM wfirma_product_mapping WHERE product_code=?",
            (product_code,),
        ).fetchone()
    return dict(row) if row else None


def list_wfirma_product_mappings(
    db_path: Path,
    sync_status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    with _connect(db_path) as con:
        if sync_status is not None:
            rows = con.execute(
                "SELECT * FROM wfirma_product_mapping WHERE sync_status=? ORDER BY product_code",
                (sync_status,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM wfirma_product_mapping ORDER BY product_code"
            ).fetchall()
    return [dict(r) for r in rows]


# ── wfirma_customer_mapping ───────────────────────────────────────────────────

def upsert_wfirma_customer_mapping(
    db_path: Path,
    client_name: str,
    wfirma_customer_id: str = "",
    vat_id: str = "",
    country: str = "",
    match_status: str = "pending",
    last_checked_at: str = "",
    last_error: str = "",
) -> int:
    """Insert or update wFirma customer sync state. Returns row id."""
    now = _now()
    with _connect(db_path) as con:
        existing = con.execute(
            "SELECT id FROM wfirma_customer_mapping WHERE client_name=?",
            (client_name,),
        ).fetchone()
        if existing:
            con.execute(
                """UPDATE wfirma_customer_mapping
                   SET wfirma_customer_id=?, vat_id=?, country=?,
                       match_status=?, last_checked_at=?, last_error=?, updated_at=?
                   WHERE client_name=?""",
                (wfirma_customer_id, vat_id, country,
                 match_status, last_checked_at, last_error, now,
                 client_name),
            )
            return existing["id"]
        cur = con.execute(
            """INSERT INTO wfirma_customer_mapping
               (client_name, wfirma_customer_id, vat_id, country,
                match_status, last_checked_at, last_error, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (client_name, wfirma_customer_id, vat_id, country,
             match_status, last_checked_at, last_error, now, now),
        )
        return cur.lastrowid


def get_wfirma_customer_mapping(
    db_path: Path,
    client_name: str,
) -> Optional[Dict[str, Any]]:
    with _connect(db_path) as con:
        row = con.execute(
            "SELECT * FROM wfirma_customer_mapping WHERE client_name=?",
            (client_name,),
        ).fetchone()
    return dict(row) if row else None


def list_wfirma_customer_mappings(
    db_path: Path,
    match_status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    with _connect(db_path) as con:
        if match_status is not None:
            rows = con.execute(
                "SELECT * FROM wfirma_customer_mapping WHERE match_status=? ORDER BY client_name",
                (match_status,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM wfirma_customer_mapping ORDER BY client_name"
            ).fetchall()
    return [dict(r) for r in rows]


# ── reservation_queue ─────────────────────────────────────────────────────────

def upsert_reservation_queue(
    db_path: Path,
    queue_key: str,
    batch_id: str,
    client_name: str,
    client_ref: str = "",
    sales_doc_no: str = "",
    design_no: str = "",
    product_code: str = "",
    qty: float = 0.0,
    unit_price: float = 0.0,
    currency: str = "USD",
    status: str = "pending",
    blocking_reason: str = "",
    wfirma_product_id: str = "",
    wfirma_customer_id: str = "",
) -> int:
    """Insert or update a reservation queue row. Returns row id."""
    now = _now()
    with _connect(db_path) as con:
        # Use PRAGMA deferred FK so UNMAPPED product_code rows can be inserted
        con.execute("PRAGMA foreign_keys=OFF")
        existing = con.execute(
            "SELECT id FROM reservation_queue WHERE queue_key=?",
            (queue_key,),
        ).fetchone()
        if existing:
            con.execute(
                """UPDATE reservation_queue
                   SET batch_id=?, client_name=?, client_ref=?, sales_doc_no=?,
                       design_no=?, product_code=?, qty=?, unit_price=?,
                       currency=?, status=?, blocking_reason=?,
                       wfirma_product_id=?, wfirma_customer_id=?, updated_at=?
                   WHERE queue_key=?""",
                (batch_id, client_name, client_ref, sales_doc_no,
                 design_no, product_code, qty, unit_price,
                 currency, status, blocking_reason,
                 wfirma_product_id, wfirma_customer_id, now,
                 queue_key),
            )
            return existing["id"]
        cur = con.execute(
            """INSERT INTO reservation_queue
               (queue_key, batch_id, client_name, client_ref, sales_doc_no,
                design_no, product_code, qty, unit_price, currency,
                status, blocking_reason, wfirma_product_id, wfirma_customer_id,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (queue_key, batch_id, client_name, client_ref, sales_doc_no,
             design_no, product_code, qty, unit_price, currency,
             status, blocking_reason, wfirma_product_id, wfirma_customer_id,
             now, now),
        )
        return cur.lastrowid


def get_reservation_queue_row(
    db_path: Path,
    queue_id: int,
) -> Optional[Dict[str, Any]]:
    with _connect(db_path) as con:
        row = con.execute(
            "SELECT * FROM reservation_queue WHERE id=?",
            (queue_id,),
        ).fetchone()
    return dict(row) if row else None


def list_reservation_queue(
    db_path: Path,
    status: Optional[str] = None,
    batch_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    with _connect(db_path) as con:
        if status and batch_id:
            rows = con.execute(
                """SELECT * FROM reservation_queue
                   WHERE status=? AND batch_id=?
                   ORDER BY id""",
                (status, batch_id),
            ).fetchall()
        elif status:
            rows = con.execute(
                "SELECT * FROM reservation_queue WHERE status=? ORDER BY id",
                (status,),
            ).fetchall()
        elif batch_id:
            rows = con.execute(
                "SELECT * FROM reservation_queue WHERE batch_id=? ORDER BY id",
                (batch_id,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM reservation_queue ORDER BY id"
            ).fetchall()
    return [dict(r) for r in rows]


def update_queue_status(
    db_path: Path,
    row_id: int,
    status: str,
    blocking_reason: str = "",
    last_error: str = "",
    updated_at: str = "",
) -> None:
    now = updated_at or _now()
    with _connect(db_path) as con:
        con.execute(
            """UPDATE reservation_queue
               SET status=?, blocking_reason=?, last_error=?, updated_at=?
               WHERE id=?""",
            (status, blocking_reason, last_error, now, row_id),
        )


def update_queue_ready(
    db_path: Path,
    row_id: int,
    wfirma_product_id: str,
    wfirma_customer_id: str,
    ready_at: str,
    updated_at: str,
) -> None:
    with _connect(db_path) as con:
        con.execute(
            """UPDATE reservation_queue
               SET status='ready', wfirma_product_id=?, wfirma_customer_id=?,
                   ready_at=?, updated_at=?
               WHERE id=?""",
            (wfirma_product_id, wfirma_customer_id, ready_at, updated_at, row_id),
        )


def mark_queue_group_submitting(
    db_path: Path,
    batch_id: str,
    client_name: str,
    sales_doc_no: str,
    updated_at: str,
) -> bool:
    """
    Atomic transition ready → submitting for all rows in the group.
    Returns True if at least one row was transitioned (caller may proceed).
    Returns False if no ready rows found (concurrent worker already locked them).
    """
    with _connect(db_path) as con:
        cur = con.execute(
            """UPDATE reservation_queue
               SET status='submitting', updated_at=?
               WHERE batch_id=? AND client_name=? AND sales_doc_no=?
               AND status='ready'""",
            (updated_at, batch_id, client_name, sales_doc_no),
        )
        return cur.rowcount > 0


def mark_queue_group_created(
    db_path: Path,
    batch_id: str,
    client_name: str,
    sales_doc_no: str,
    wfirma_reservation_id: str,
    completed_at: str,
    updated_at: str,
) -> None:
    with _connect(db_path) as con:
        con.execute(
            """UPDATE reservation_queue
               SET status='created', wfirma_reservation_id=?,
                   completed_at=?, updated_at=?
               WHERE batch_id=? AND client_name=? AND sales_doc_no=?
               AND status='submitting'""",
            (wfirma_reservation_id, completed_at, updated_at,
             batch_id, client_name, sales_doc_no),
        )


def mark_queue_group_failed(
    db_path: Path,
    batch_id: str,
    client_name: str,
    sales_doc_no: str,
    error: str,
    updated_at: str,
) -> None:
    with _connect(db_path) as con:
        con.execute(
            """UPDATE reservation_queue
               SET status='failed', last_error=?, updated_at=?
               WHERE batch_id=? AND client_name=? AND sales_doc_no=?
               AND status='submitting'""",
            (error[:1000], updated_at, batch_id, client_name, sales_doc_no),
        )


def list_product_codes_from_queue(
    db_path: Path,
    status: Optional[str] = None,
) -> List[str]:
    """Return distinct non-empty product_codes from the queue."""
    with _connect(db_path) as con:
        if status is not None:
            rows = con.execute(
                """SELECT DISTINCT product_code FROM reservation_queue
                   WHERE status=? AND product_code != '' AND product_code != 'UNMAPPED'
                   ORDER BY product_code""",
                (status,),
            ).fetchall()
        else:
            rows = con.execute(
                """SELECT DISTINCT product_code FROM reservation_queue
                   WHERE product_code != '' AND product_code != 'UNMAPPED'
                   ORDER BY product_code"""
            ).fetchall()
    return [r["product_code"] for r in rows]
