"""
document_db.py — Unified shipment document registry.

Tables
------
shipment_documents        every file, uploaded or generated
document_extraction_json  raw + normalized JSON per document
document_extracted_fields field-level storage with confidence + verified_status
customs_declarations      typed customs data from SAD/ZC429 XML
awb_documents             AWB structured data
pz_documents              PZ output records

Design rules
------------
- One DB file: storage_root/documents.db
- Dedup key for shipment_documents: (batch_id, document_type, file_hash)
  Same hash → return existing id, no duplicate row.
- verified fields cannot be overwritten unless force=True
- All public functions are non-throwing: callers wrap in try/except.
  documents.db failure must NEVER affect PZ processing or existing flows.
- Thread-safe: per-call connection, WAL mode, threading.Lock.

Read priority (implemented in read_field())
-------------------------------------------
1. document_extracted_fields (structured, field-level)
2. document_extraction_json  (normalized_json blob)
3. None — caller falls back to parser
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.logging import get_logger
from . import packing_db as _pdb

log      = get_logger(__name__)
_lock    = threading.Lock()
_db_path: Optional[Path] = None


# ── Init ───────────────────────────────────────────────────────────────────────

def init_document_db(db_path: Path) -> None:
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as con:
        con.executescript("""
            PRAGMA journal_mode=WAL;

            -- ── Unified file registry ─────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS shipment_documents (
                id                   TEXT PRIMARY KEY,
                batch_id             TEXT NOT NULL,
                awb                  TEXT NOT NULL DEFAULT '',
                document_type        TEXT NOT NULL,
                file_name            TEXT NOT NULL DEFAULT '',
                canonical_file_name  TEXT NOT NULL DEFAULT '',
                file_path            TEXT NOT NULL DEFAULT '',
                file_hash            TEXT NOT NULL DEFAULT '',
                parser_name          TEXT NOT NULL DEFAULT '',
                parser_version       TEXT NOT NULL DEFAULT '',
                parser_status        TEXT NOT NULL DEFAULT 'pending',
                extraction_status    TEXT NOT NULL DEFAULT 'pending',
                requires_manual_review INTEGER NOT NULL DEFAULT 0,
                related_invoice_no   TEXT NOT NULL DEFAULT '',
                related_mrn          TEXT NOT NULL DEFAULT '',
                related_pz_no        TEXT NOT NULL DEFAULT '',
                source               TEXT NOT NULL DEFAULT 'upload',
                client_contractor_id TEXT NOT NULL DEFAULT '',
                supplier_contractor_id TEXT NOT NULL DEFAULT '',
                created_at           TEXT NOT NULL,
                updated_at           TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sd_batch_id
                ON shipment_documents (batch_id);
            CREATE INDEX IF NOT EXISTS idx_sd_batch_type
                ON shipment_documents (batch_id, document_type);
            CREATE INDEX IF NOT EXISTS idx_sd_hash
                ON shipment_documents (file_hash);

            -- ── Raw + normalized extraction JSON ──────────────────────────────
            CREATE TABLE IF NOT EXISTS document_extraction_json (
                id              TEXT PRIMARY KEY,
                document_id     TEXT NOT NULL,
                batch_id        TEXT NOT NULL,
                document_type   TEXT NOT NULL,
                extracted_json  TEXT NOT NULL DEFAULT '{}',
                normalized_json TEXT NOT NULL DEFAULT '{}',
                schema_version  TEXT NOT NULL DEFAULT '1',
                created_at      TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES shipment_documents(id)
            );

            CREATE INDEX IF NOT EXISTS idx_dej_document_id
                ON document_extraction_json (document_id);
            CREATE INDEX IF NOT EXISTS idx_dej_batch_type
                ON document_extraction_json (batch_id, document_type);

            -- ── Field-level storage ───────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS document_extracted_fields (
                id               TEXT PRIMARY KEY,
                document_id      TEXT NOT NULL,
                batch_id         TEXT NOT NULL,
                field_name       TEXT NOT NULL,
                normalized_value TEXT NOT NULL DEFAULT '',
                confidence       REAL NOT NULL DEFAULT 0.0,
                verified_status  TEXT NOT NULL DEFAULT 'unverified',
                created_at       TEXT NOT NULL,
                updated_at       TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES shipment_documents(id)
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_def_doc_field
                ON document_extracted_fields (document_id, field_name);
            CREATE INDEX IF NOT EXISTS idx_def_batch_field
                ON document_extracted_fields (batch_id, field_name);

            -- ── Typed customs declarations ────────────────────────────────────
            CREATE TABLE IF NOT EXISTS customs_declarations (
                id                    TEXT PRIMARY KEY,
                document_id           TEXT NOT NULL,
                batch_id              TEXT NOT NULL,
                mrn                   TEXT NOT NULL DEFAULT '',
                lrn                   TEXT NOT NULL DEFAULT '',
                clearance_date        TEXT NOT NULL DEFAULT '',
                duty_pln              REAL NOT NULL DEFAULT 0.0,
                vat_pln               REAL NOT NULL DEFAULT 0.0,
                total_cif_usd         REAL NOT NULL DEFAULT 0.0,
                customs_rate_usd      REAL,
                statistical_value_pln REAL NOT NULL DEFAULT 0.0,
                agent                 TEXT NOT NULL DEFAULT '',
                importer_name         TEXT NOT NULL DEFAULT '',
                importer_nip          TEXT NOT NULL DEFAULT '',
                exporter_name         TEXT NOT NULL DEFAULT '',
                cn_code               TEXT NOT NULL DEFAULT '',
                goods_description     TEXT NOT NULL DEFAULT '',
                invoice_refs          TEXT NOT NULL DEFAULT '[]',
                raw_json              TEXT NOT NULL DEFAULT '{}',
                created_at            TEXT NOT NULL,
                updated_at            TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES shipment_documents(id)
            );

            CREATE INDEX IF NOT EXISTS idx_cd_batch_id
                ON customs_declarations (batch_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_cd_mrn
                ON customs_declarations (mrn) WHERE mrn != '';

            -- ── AWB structured data ───────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS awb_documents (
                id             TEXT PRIMARY KEY,
                document_id    TEXT NOT NULL,
                batch_id       TEXT NOT NULL,
                awb            TEXT NOT NULL DEFAULT '',
                carrier        TEXT NOT NULL DEFAULT '',
                shipper_name   TEXT NOT NULL DEFAULT '',
                consignee_name TEXT NOT NULL DEFAULT '',
                pieces         INTEGER NOT NULL DEFAULT 0,
                weight_kg      REAL NOT NULL DEFAULT 0.0,
                description    TEXT NOT NULL DEFAULT '',
                raw_json       TEXT NOT NULL DEFAULT '{}',
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES shipment_documents(id)
            );

            CREATE INDEX IF NOT EXISTS idx_awb_batch_id
                ON awb_documents (batch_id);

            -- ── PZ output records ─────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS pz_documents (
                id                  TEXT PRIMARY KEY,
                document_id         TEXT NOT NULL,
                batch_id            TEXT NOT NULL,
                doc_no              TEXT NOT NULL DEFAULT '',
                line_count          INTEGER NOT NULL DEFAULT 0,
                total_net_pln       REAL NOT NULL DEFAULT 0.0,
                total_gross_pln     REAL NOT NULL DEFAULT 0.0,
                duty_a00_pln        REAL NOT NULL DEFAULT 0.0,
                verification_status TEXT NOT NULL DEFAULT 'unknown',
                amendment_flags     TEXT NOT NULL DEFAULT '[]',
                workdrive_pdf_id    TEXT NOT NULL DEFAULT '',
                workdrive_xlsx_id   TEXT NOT NULL DEFAULT '',
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES shipment_documents(id)
            );

            CREATE INDEX IF NOT EXISTS idx_pz_batch_id
                ON pz_documents (batch_id);

            -- ── Invoice lines (purchase) ───────────────────────────────────
            CREATE TABLE IF NOT EXISTS invoice_lines (
                id                  TEXT PRIMARY KEY,
                document_id         TEXT NOT NULL,
                batch_id            TEXT NOT NULL,
                invoice_no          TEXT NOT NULL DEFAULT '',
                line_position       INTEGER NOT NULL DEFAULT 0,
                product_code        TEXT NOT NULL DEFAULT '',
                description         TEXT NOT NULL DEFAULT '',
                quantity            REAL NOT NULL DEFAULT 0.0,
                unit_price          REAL NOT NULL DEFAULT 0.0,
                total_value         REAL NOT NULL DEFAULT 0.0,
                currency            TEXT NOT NULL DEFAULT '',
                hs_code             TEXT NOT NULL DEFAULT '',
                gross_weight        REAL NOT NULL DEFAULT 0.0,
                net_weight          REAL NOT NULL DEFAULT 0.0,
                rate_usd            REAL NOT NULL DEFAULT 0.0,
                amount_usd          REAL NOT NULL DEFAULT 0.0,
                hsn_code            TEXT NOT NULL DEFAULT '',
                created_at          TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES shipment_documents(id)
            );

            CREATE INDEX IF NOT EXISTS idx_invoice_lines_batch
                ON invoice_lines (batch_id);
            CREATE INDEX IF NOT EXISTS idx_invoice_lines_invoice_no
                ON invoice_lines (invoice_no);

            -- ── Sales documents (outgoing chain) ──────────────────────────
            CREATE TABLE IF NOT EXISTS sales_documents (
                id                  TEXT PRIMARY KEY,
                batch_id            TEXT NOT NULL,
                document_id         TEXT NOT NULL DEFAULT '',
                client_name         TEXT NOT NULL DEFAULT '',
                client_ref          TEXT NOT NULL DEFAULT '',
                document_type       TEXT NOT NULL DEFAULT 'sales_invoice',
                sales_doc_no        TEXT NOT NULL DEFAULT '',
                sales_doc_date      TEXT NOT NULL DEFAULT '',
                source_file_path    TEXT NOT NULL DEFAULT '',
                extraction_status   TEXT NOT NULL DEFAULT 'pending',
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sales_docs_batch
                ON sales_documents (batch_id);

            -- ── Sales packing lines ────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS sales_packing_lines (
                id                  TEXT PRIMARY KEY,
                batch_id            TEXT NOT NULL,
                sales_document_id   TEXT NOT NULL,
                client_name         TEXT NOT NULL DEFAULT '',
                client_ref          TEXT NOT NULL DEFAULT '',
                product_code        TEXT NOT NULL DEFAULT '',
                design_no           TEXT NOT NULL DEFAULT '',
                bag_id              TEXT NOT NULL DEFAULT '',
                quantity            REAL NOT NULL DEFAULT 0.0,
                remarks             TEXT NOT NULL DEFAULT '',
                created_at          TEXT NOT NULL,
                FOREIGN KEY (sales_document_id) REFERENCES sales_documents(id)
            );

            CREATE INDEX IF NOT EXISTS idx_sales_lines_batch
                ON sales_packing_lines (batch_id);

            -- ── Product descriptions (locked bilingual block, per code) ────
            -- Single source of truth keyed by product_code.  See
            -- docs/wfirma.skill.md — generated once, reused everywhere
            -- (PZ description PDF, future wFirma product create, future
            -- proforma/invoice flows).
            CREATE TABLE IF NOT EXISTS product_descriptions (
                product_code        TEXT PRIMARY KEY,
                item_type           TEXT NOT NULL DEFAULT '',
                name_pl             TEXT NOT NULL DEFAULT '',
                description_pl      TEXT NOT NULL DEFAULT '',
                description_en      TEXT NOT NULL DEFAULT '',
                material_pl         TEXT NOT NULL DEFAULT '',
                purpose_pl          TEXT NOT NULL DEFAULT '',
                description_block   TEXT NOT NULL DEFAULT '',
                description_line    TEXT NOT NULL DEFAULT '',
                source              TEXT NOT NULL DEFAULT 'auto',
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_pd_item_type
                ON product_descriptions (item_type);
            CREATE INDEX IF NOT EXISTS idx_pd_source
                ON product_descriptions (source);
        """)

        # ── Forward-compat column migrations on invoice_lines ────────────
        # Older DBs were created before gross_weight/net_weight/rate_usd/
        # amount_usd/hsn_code were added. ALTER TABLE ADD COLUMN is a
        # no-op once the column exists.
        for col, ddl in (
            ("gross_weight", "REAL NOT NULL DEFAULT 0.0"),
            ("net_weight",   "REAL NOT NULL DEFAULT 0.0"),
            ("rate_usd",     "REAL NOT NULL DEFAULT 0.0"),
            ("amount_usd",   "REAL NOT NULL DEFAULT 0.0"),
            ("hsn_code",     "TEXT NOT NULL DEFAULT ''"),
        ):
            try:
                con.execute(f"ALTER TABLE invoice_lines ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                pass  # column already exists

        # ── Forward-compat: product_descriptions added description_en /
        # description_line later. Idempotent ALTER for older DBs.
        for col, ddl in (
            ("description_en",   "TEXT NOT NULL DEFAULT ''"),
            ("description_line", "TEXT NOT NULL DEFAULT ''"),
            # Phase 4 — name_sk: Slovak product name (nullable, operator-populated)
            ("name_sk",          "TEXT"),
        ):
            try:
                con.execute(
                    f"ALTER TABLE product_descriptions ADD COLUMN {col} {ddl}"
                )
            except sqlite3.OperationalError:
                pass  # column already exists

        # ── Contractor identity binding (New Shipment intake → real master
        # data). Idempotent ALTERs for installs that already have older
        # shipment_documents tables. Default '' = unbound (free-text legacy).
        for col, ddl in (
            ("client_contractor_id",   "TEXT NOT NULL DEFAULT ''"),
            ("supplier_contractor_id", "TEXT NOT NULL DEFAULT ''"),
        ):
            try:
                con.execute(
                    f"ALTER TABLE shipment_documents ADD COLUMN {col} {ddl}"
                )
            except sqlite3.OperationalError:
                pass  # column already exists

        # Indexes for the new contractor-id columns (created after ALTER so
        # legacy schemas without the columns are upgraded first).
        for idx_name, col in (
            ("idx_sd_client_cid",   "client_contractor_id"),
            ("idx_sd_supplier_cid", "supplier_contractor_id"),
        ):
            try:
                con.execute(
                    f"CREATE INDEX IF NOT EXISTS {idx_name} "
                    f"ON shipment_documents ({col})"
                )
            except sqlite3.OperationalError:
                pass

        # ── Parser-observability for sales side: mirror the
        # packing_documents.parser_diagnostic_json column on
        # sales_documents so successful sales-packing parses expose the
        # same Diagnostic toggle as purchase rows.  Default '{}' keeps
        # legacy rows JSON-decodable.  Idempotent on every boot.
        try:
            con.execute(
                "ALTER TABLE sales_documents ADD COLUMN "
                "parser_diagnostic_json TEXT NOT NULL DEFAULT '{}'"
            )
        except sqlite3.OperationalError:
            pass  # column already exists

        # ── Sales-side pricing: customer Proforma must use SALES prices,
        # not import/customs cost. Schema gap before this migration: only
        # quantity was captured; unit_price / currency were dropped at
        # intake. Idempotent ALTERs preserve existing data (default 0/'').
        for col, ddl in (
            ("unit_price",   "REAL NOT NULL DEFAULT 0.0"),
            ("currency",     "TEXT NOT NULL DEFAULT ''"),
            ("total_value",  "REAL NOT NULL DEFAULT 0.0"),
            ("price_source", "TEXT NOT NULL DEFAULT ''"),
        ):
            try:
                con.execute(
                    f"ALTER TABLE sales_packing_lines ADD COLUMN {col} {ddl}"
                )
            except sqlite3.OperationalError:
                pass  # column already exists

        # ── Contractor-at-birth projection (PR-2) ────────────────────────
        # Carry the Customer-Master contractor authority resolved at intake
        # (shipment_documents.client_contractor_id) onto the sales chain so
        # downstream grouping/reservation can use the authoritative identity
        # instead of fragile client_name string equality. Additive, idempotent,
        # default '' = unprojected (legacy / pre-fix rows; repaired by backfill).
        try:
            con.execute(
                "ALTER TABLE sales_documents ADD COLUMN "
                "client_contractor_id TEXT NOT NULL DEFAULT ''"
            )
        except sqlite3.OperationalError:
            pass  # column already exists
        try:
            con.execute(
                "ALTER TABLE sales_packing_lines ADD COLUMN "
                "client_contractor_id TEXT NOT NULL DEFAULT ''"
            )
        except sqlite3.OperationalError:
            pass  # column already exists
        for idx_name, table, col in (
            ("idx_sales_docs_client_cid",  "sales_documents",     "client_contractor_id"),
            ("idx_sales_lines_client_cid", "sales_packing_lines", "client_contractor_id"),
        ):
            try:
                con.execute(
                    f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({col})"
                )
            except sqlite3.OperationalError:
                pass

        # ── Product identity fields (PR: product-identity-engine-foundation)
        # Extends product_descriptions with packing-derived identity fields:
        #   karat / metal_color / quality_string / stone_type — from packing XLSX
        #   unit_price_eur — per-piece EUR price from packing XLSX Value column
        #   unit_price_usd — per-piece USD from invoice_lines
        #   confidence — HIGH / MEDIUM / LOW (assigned by product_identity_engine)
        #   supplier_prefix — "EJL" | "417G" | "UNKNOWN"
        #   is_globally_unique — 0 for 417G codes, 1 for EJL codes
        # All idempotent: safe to run against existing production DB.
        for col, ddl in (
            ("karat",              "TEXT NOT NULL DEFAULT ''"),
            ("metal_color",        "TEXT NOT NULL DEFAULT ''"),
            ("quality_string",     "TEXT NOT NULL DEFAULT ''"),
            ("stone_type",         "TEXT NOT NULL DEFAULT ''"),
            ("unit_price_eur",     "REAL NOT NULL DEFAULT 0.0"),
            ("unit_price_usd",     "REAL NOT NULL DEFAULT 0.0"),
            ("confidence",         "TEXT NOT NULL DEFAULT ''"),
            ("supplier_prefix",    "TEXT NOT NULL DEFAULT ''"),
            ("is_globally_unique", "INTEGER NOT NULL DEFAULT 1"),
        ):
            try:
                con.execute(
                    f"ALTER TABLE product_descriptions ADD COLUMN {col} {ddl}"
                )
            except sqlite3.OperationalError:
                pass  # column already exists


_V_SALES_TO_WFIRMA_DDL = """
CREATE TEMP VIEW IF NOT EXISTS v_sales_to_wfirma AS
SELECT
    spl.batch_id                AS batch_id,
    spl.sales_document_id       AS sales_document_id,
    sd.sales_doc_no             AS sales_doc_no,
    spl.client_name             AS client_name,
    spl.client_ref              AS client_ref,
    spl.design_no               AS sales_design_no,
    pl.product_code             AS wfirma_product_code,
    pl.design_no                AS purchase_design_no,
    SUM(spl.quantity)           AS qty,
    -- Sales-side pricing (preferred source for customer Proforma)
    spl.unit_price              AS sales_unit_price,
    spl.currency                AS sales_currency,
    SUM(spl.total_value)        AS sales_total_value,
    spl.price_source            AS sales_price_source
FROM sales_packing_lines spl
LEFT JOIN sales_documents sd
       ON sd.id = spl.sales_document_id
LEFT JOIN packing.packing_lines pl
       ON pl.batch_id = spl.batch_id
      AND (
              UPPER(TRIM(pl.design_no)) =
                  UPPER(TRIM(COALESCE(NULLIF(spl.product_code, ''), spl.design_no)))
           OR (
              NULLIF(TRIM(spl.product_code), '') IS NOT NULL
              AND NULLIF(TRIM(pl.product_code),  '') IS NOT NULL
              AND UPPER(TRIM(pl.product_code)) = UPPER(TRIM(spl.product_code))
           )
          )
GROUP BY spl.batch_id, spl.sales_document_id, sd.sales_doc_no,
         spl.client_name, spl.client_ref, spl.design_no, spl.product_code,
         spl.unit_price, spl.currency, spl.price_source,
         pl.product_code, pl.design_no
"""


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(_db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    # SQLite forbids persistent views from referencing attached schemas.
    # We attach the packing DB (when initialised) and recreate the view as
    # TEMP per-connection. The view is read-only and adds no documents.db
    # schema bloat.
    if _pdb._db_path is not None:
        try:
            con.execute(f"ATTACH DATABASE '{_pdb._db_path}' AS packing")
        except sqlite3.OperationalError:
            # Already attached on this connection (idempotent).
            pass
        try:
            con.executescript(_V_SALES_TO_WFIRMA_DDL)
        except sqlite3.OperationalError:
            # Best-effort: if attach failed (e.g. concurrent), skip view.
            pass
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """SHA-256 of a file on disk.  Returns '' if file missing."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


# ── Register document ──────────────────────────────────────────────────────────

def register_document(
    *,
    batch_id:             str,
    document_type:        str,
    file_name:            str          = "",
    file_path:            str          = "",
    file_hash:            str          = "",
    awb:                  str          = "",
    canonical_file_name:  str          = "",
    parser_name:          str          = "",
    parser_version:       str          = "",
    parser_status:        str          = "pending",
    extraction_status:    str          = "pending",
    related_invoice_no:   str          = "",
    related_mrn:          str          = "",
    related_pz_no:        str          = "",
    source:               str          = "upload",
    requires_manual_review: bool       = False,
    client_contractor_id:   str         = "",
    supplier_contractor_id: str         = "",
) -> Optional[str]:
    """
    Register a document in the unified registry.

    Returns the document id.  If a row with the same (batch_id, document_type,
    file_hash) already exists and file_hash is non-empty, returns the existing
    id without inserting a duplicate.

    Returns None if the DB is not initialised.
    """
    if _db_path is None:
        return None
    now = _now()
    with _lock:
        with _connect() as con:
            # Dedup by hash when hash is available
            if file_hash:
                existing = con.execute(
                    """SELECT id FROM shipment_documents
                       WHERE batch_id=? AND document_type=? AND file_hash=?
                       LIMIT 1""",
                    (batch_id, document_type, file_hash),
                ).fetchone()
                if existing:
                    return existing["id"]

            doc_id = str(uuid.uuid4())
            con.execute(
                """INSERT INTO shipment_documents
                       (id, batch_id, awb, document_type,
                        file_name, canonical_file_name, file_path, file_hash,
                        parser_name, parser_version, parser_status, extraction_status,
                        requires_manual_review,
                        related_invoice_no, related_mrn, related_pz_no,
                        source,
                        client_contractor_id, supplier_contractor_id,
                        created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    doc_id, batch_id, awb, document_type,
                    file_name, canonical_file_name, file_path, file_hash,
                    parser_name, parser_version, parser_status, extraction_status,
                    1 if requires_manual_review else 0,
                    related_invoice_no, related_mrn, related_pz_no,
                    source,
                    (client_contractor_id or "").strip(),
                    (supplier_contractor_id or "").strip(),
                    now, now,
                ),
            )
            return doc_id


def update_document_status(
    document_id:        str,
    extraction_status:  Optional[str] = None,
    parser_status:      Optional[str] = None,
    related_mrn:        Optional[str] = None,
    related_pz_no:      Optional[str] = None,
    related_invoice_no: Optional[str] = None,
    workdrive_id:       Optional[str] = None,
    requires_manual_review: Optional[bool] = None,
) -> None:
    """Patch status fields on an existing document row.

    ``requires_manual_review`` accepts True/False to flip the flag
    explicitly; passing None (default) leaves the column unchanged.
    """
    if _db_path is None:
        return
    sets: list[str] = ["updated_at=?"]
    vals: list[Any] = [_now()]
    if extraction_status is not None:
        sets.append("extraction_status=?");  vals.append(extraction_status)
    if parser_status is not None:
        sets.append("parser_status=?");      vals.append(parser_status)
    if related_mrn is not None:
        sets.append("related_mrn=?");        vals.append(related_mrn)
    if related_pz_no is not None:
        sets.append("related_pz_no=?");      vals.append(related_pz_no)
    if related_invoice_no is not None:
        sets.append("related_invoice_no=?"); vals.append(related_invoice_no)
    if requires_manual_review is not None:
        sets.append("requires_manual_review=?")
        vals.append(1 if requires_manual_review else 0)
    vals.append(document_id)
    with _lock:
        with _connect() as con:
            con.execute(
                f"UPDATE shipment_documents SET {', '.join(sets)} WHERE id=?",
                vals,
            )


def merge_document_normalized_json(
    document_id: str,
    batch_id:    str,
    blob:        Dict[str, Any],
    document_type: str = "purchase_invoice",
) -> None:
    """Merge ``blob`` into ``document_extraction_json.normalized_json``
    for the given document_id without touching ``extracted_json``.

    Idempotent: if no row exists, inserts a new one with ``extracted_json
    = '{}'`` and ``normalized_json = blob``.  If a row exists, the
    stored normalized JSON is parsed, the blob keys are merged on top
    (shallow merge), and the row is updated in place.

    Used by intake-time diagnostics surfaces (e.g.
    invoice_line_diagnostics) that need to append a structured
    diagnostics record to a document without clobbering any extraction
    payload other code might have written.

    No schema change.  Best-effort: returns silently if _db_path is
    None or any DB error occurs (the caller is expected to log)."""
    if _db_path is None:
        return
    now = _now()
    with _lock:
        with _connect() as con:
            row = con.execute(
                "SELECT id, normalized_json FROM document_extraction_json "
                "WHERE document_id=? LIMIT 1",
                (document_id,),
            ).fetchone()
            if row is None:
                con.execute(
                    """INSERT INTO document_extraction_json
                           (id, document_id, batch_id, document_type,
                            extracted_json, normalized_json,
                            schema_version, created_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (str(uuid.uuid4()), document_id, batch_id,
                     document_type, "{}",
                     json.dumps(blob, ensure_ascii=False),
                     "1", now),
                )
                return
            try:
                cur = json.loads(row["normalized_json"] or "{}")
                if not isinstance(cur, dict):
                    cur = {}
            except Exception:
                cur = {}
            cur.update(blob or {})
            con.execute(
                "UPDATE document_extraction_json "
                "SET normalized_json=? WHERE id=?",
                (json.dumps(cur, ensure_ascii=False), row["id"]),
            )


# ── Extraction JSON ────────────────────────────────────────────────────────────

def store_extraction_json(
    document_id:    str,
    batch_id:       str,
    document_type:  str,
    extracted_json: Any,
    normalized_json: Any,
    schema_version: str = "1",
) -> str:
    """
    Insert or replace the raw + normalized JSON for a document.
    Always replaces (one extraction row per document_id).
    Returns the row id.
    """
    if _db_path is None:
        return ""
    row_id = str(uuid.uuid4())
    now    = _now()
    ejson  = json.dumps(extracted_json,  ensure_ascii=False)
    njson  = json.dumps(normalized_json, ensure_ascii=False)
    with _lock:
        with _connect() as con:
            # Delete existing row for this document to maintain 1:1 relationship
            con.execute("DELETE FROM document_extraction_json WHERE document_id=?",
                        (document_id,))
            con.execute(
                """INSERT INTO document_extraction_json
                       (id, document_id, batch_id, document_type,
                        extracted_json, normalized_json, schema_version, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (row_id, document_id, batch_id, document_type,
                 ejson, njson, schema_version, now),
            )
    return row_id


# ── Field-level storage ────────────────────────────────────────────────────────

def upsert_field(
    document_id: str,
    batch_id:    str,
    field_name:  str,
    value:       Any,
    confidence:  float = 0.0,
    force:       bool  = False,
) -> bool:
    """
    Insert or update a single extracted field.

    If the existing row has verified_status='verified' and force=False,
    the write is skipped and False is returned.
    Returns True if written.
    """
    if _db_path is None:
        return False
    str_value = str(value) if value is not None else ""
    now = _now()
    with _lock:
        with _connect() as con:
            existing = con.execute(
                """SELECT id, verified_status FROM document_extracted_fields
                   WHERE document_id=? AND field_name=? LIMIT 1""",
                (document_id, field_name),
            ).fetchone()

            if existing:
                if existing["verified_status"] == "verified" and not force:
                    return False
                con.execute(
                    """UPDATE document_extracted_fields
                       SET normalized_value=?, confidence=?, updated_at=?
                       WHERE id=?""",
                    (str_value, confidence, now, existing["id"]),
                )
            else:
                con.execute(
                    """INSERT INTO document_extracted_fields
                           (id, document_id, batch_id, field_name,
                            normalized_value, confidence, verified_status,
                            created_at, updated_at)
                       VALUES (?,?,?,?,?,?,'unverified',?,?)""",
                    (str(uuid.uuid4()), document_id, batch_id, field_name,
                     str_value, confidence, now, now),
                )
    return True


def store_fields(
    document_id: str,
    batch_id:    str,
    fields:      Dict[str, Any],
    confidence:  float = 0.0,
    force:       bool  = False,
) -> int:
    """Bulk-store extracted fields.  Returns count of fields written."""
    written = 0
    for name, value in fields.items():
        if upsert_field(document_id, batch_id, name, value,
                        confidence=confidence, force=force):
            written += 1
    return written


# ── Read priority ──────────────────────────────────────────────────────────────

def get_fields_for_document(document_id: str) -> List[Dict[str, Any]]:
    """
    Return all extracted fields for one document, ordered by field_name.
    Read-only.  Returns [] if document has no fields or DB is not initialised.
    """
    if _db_path is None or not document_id:
        return []
    with _connect() as con:
        rows = con.execute(
            """SELECT field_name, normalized_value, confidence, verified_status,
                      created_at, updated_at
               FROM document_extracted_fields
               WHERE document_id=?
               ORDER BY field_name""",
            (document_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def read_field(
    batch_id:      str,
    document_type: str,
    field_name:    str,
) -> Optional[str]:
    """
    Return the best available value for a field, following read priority:

    1. document_extracted_fields — typed, verified
    2. document_extraction_json  — normalized_json blob (JSON key lookup)
    3. None — caller must fall back to parser

    Returns the most recently updated value across all documents of the
    given type in the batch.
    """
    if _db_path is None:
        return None
    with _connect() as con:
        # Priority 1 — field-level table
        row = con.execute(
            """SELECT def.normalized_value
               FROM document_extracted_fields def
               JOIN shipment_documents sd ON sd.id = def.document_id
               WHERE sd.batch_id=? AND sd.document_type=? AND def.field_name=?
               ORDER BY def.updated_at DESC LIMIT 1""",
            (batch_id, document_type, field_name),
        ).fetchone()
        if row:
            return row["normalized_value"]

        # Priority 2 — normalized_json blob
        row = con.execute(
            """SELECT dej.normalized_json
               FROM document_extraction_json dej
               WHERE dej.batch_id=? AND dej.document_type=?
               ORDER BY dej.created_at DESC LIMIT 1""",
            (batch_id, document_type),
        ).fetchone()
        if row:
            try:
                blob = json.loads(row["normalized_json"])
                if field_name in blob:
                    return str(blob[field_name])
            except (json.JSONDecodeError, TypeError):
                pass

    return None


# ── Customs declarations ───────────────────────────────────────────────────────

def store_customs_declaration(
    document_id: str,
    batch_id:    str,
    declaration: Dict[str, Any],
) -> str:
    """
    Store a parsed customs declaration (from ZC429 XML or PDF).
    Returns the row id.  Upserts on (batch_id, mrn) if mrn is present.
    """
    if _db_path is None:
        return ""
    mrn = str(declaration.get("mrn") or "")
    now = _now()

    with _lock:
        with _connect() as con:
            # Check existing by document_id or mrn
            existing = None
            if mrn:
                existing = con.execute(
                    "SELECT id FROM customs_declarations WHERE mrn=? LIMIT 1", (mrn,)
                ).fetchone()
            if existing is None:
                existing = con.execute(
                    "SELECT id FROM customs_declarations WHERE document_id=? LIMIT 1",
                    (document_id,)
                ).fetchone()

            row_id = existing["id"] if existing else str(uuid.uuid4())
            raw    = json.dumps(declaration, ensure_ascii=False)
            refs   = json.dumps(declaration.get("invoice_refs") or [], ensure_ascii=False)

            if existing:
                con.execute(
                    """UPDATE customs_declarations SET
                           document_id=?, batch_id=?, mrn=?, lrn=?,
                           clearance_date=?, duty_pln=?, vat_pln=?,
                           total_cif_usd=?, customs_rate_usd=?,
                           statistical_value_pln=?, agent=?,
                           importer_name=?, importer_nip=?, exporter_name=?,
                           cn_code=?, goods_description=?,
                           invoice_refs=?, raw_json=?, updated_at=?
                       WHERE id=?""",
                    (
                        document_id, batch_id,
                        mrn, str(declaration.get("lrn") or ""),
                        str(declaration.get("clearance_date") or ""),
                        float(declaration.get("duty_pln") or 0),
                        float(declaration.get("vat_pln") or 0),
                        float(declaration.get("total_cif_usd") or 0),
                        declaration.get("customs_rate_usd"),
                        float(declaration.get("statistical_value_pln") or 0),
                        str(declaration.get("agent") or ""),
                        str(declaration.get("importer_name") or ""),
                        str(declaration.get("importer_nip") or ""),
                        str(declaration.get("exporter_name") or ""),
                        str(declaration.get("cn_code") or ""),
                        str(declaration.get("goods_description") or ""),
                        refs, raw, now, row_id,
                    ),
                )
            else:
                con.execute(
                    """INSERT INTO customs_declarations
                           (id, document_id, batch_id, mrn, lrn,
                            clearance_date, duty_pln, vat_pln,
                            total_cif_usd, customs_rate_usd,
                            statistical_value_pln, agent,
                            importer_name, importer_nip, exporter_name,
                            cn_code, goods_description,
                            invoice_refs, raw_json, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        row_id, document_id, batch_id,
                        mrn, str(declaration.get("lrn") or ""),
                        str(declaration.get("clearance_date") or ""),
                        float(declaration.get("duty_pln") or 0),
                        float(declaration.get("vat_pln") or 0),
                        float(declaration.get("total_cif_usd") or 0),
                        declaration.get("customs_rate_usd"),
                        float(declaration.get("statistical_value_pln") or 0),
                        str(declaration.get("agent") or ""),
                        str(declaration.get("importer_name") or ""),
                        str(declaration.get("importer_nip") or ""),
                        str(declaration.get("exporter_name") or ""),
                        str(declaration.get("cn_code") or ""),
                        str(declaration.get("goods_description") or ""),
                        refs, raw, now, now,
                    ),
                )
    return row_id


def get_customs_declaration(batch_id: str) -> Optional[Dict[str, Any]]:
    """Return the most recent customs declaration for a batch, or None."""
    if _db_path is None:
        return None
    with _connect() as con:
        row = con.execute(
            """SELECT * FROM customs_declarations
               WHERE batch_id=? ORDER BY updated_at DESC LIMIT 1""",
            (batch_id,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["invoice_refs"] = json.loads(d["invoice_refs"])
    except (json.JSONDecodeError, TypeError):
        d["invoice_refs"] = []
    try:
        d["raw_json"] = json.loads(d["raw_json"])
    except (json.JSONDecodeError, TypeError):
        pass
    return d


# ── AWB documents ──────────────────────────────────────────────────────────────

def store_awb_document(
    document_id: str,
    batch_id:    str,
    awb_data:    Dict[str, Any],
) -> str:
    """Store structured AWB data.  Upserts on document_id."""
    if _db_path is None:
        return ""
    now = _now()
    with _lock:
        with _connect() as con:
            existing = con.execute(
                "SELECT id FROM awb_documents WHERE document_id=? LIMIT 1",
                (document_id,),
            ).fetchone()
            row_id = existing["id"] if existing else str(uuid.uuid4())
            raw    = json.dumps(awb_data, ensure_ascii=False)
            if existing:
                con.execute(
                    """UPDATE awb_documents SET
                           awb=?, carrier=?, shipper_name=?, consignee_name=?,
                           pieces=?, weight_kg=?, description=?,
                           raw_json=?, updated_at=?
                       WHERE id=?""",
                    (
                        str(awb_data.get("awb") or ""),
                        str(awb_data.get("carrier") or ""),
                        str(awb_data.get("shipper_name") or ""),
                        str(awb_data.get("consignee_name") or ""),
                        int(awb_data.get("pieces") or 0),
                        float(awb_data.get("weight_kg") or 0),
                        str(awb_data.get("description") or ""),
                        raw, now, row_id,
                    ),
                )
            else:
                con.execute(
                    """INSERT INTO awb_documents
                           (id, document_id, batch_id,
                            awb, carrier, shipper_name, consignee_name,
                            pieces, weight_kg, description,
                            raw_json, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        row_id, document_id, batch_id,
                        str(awb_data.get("awb") or ""),
                        str(awb_data.get("carrier") or ""),
                        str(awb_data.get("shipper_name") or ""),
                        str(awb_data.get("consignee_name") or ""),
                        int(awb_data.get("pieces") or 0),
                        float(awb_data.get("weight_kg") or 0),
                        str(awb_data.get("description") or ""),
                        raw, now, now,
                    ),
                )
    return row_id


def get_awb_document(batch_id: str) -> Optional[Dict[str, Any]]:
    """Return AWB structured fields for compliance_resolver consumption, or None.

    The stored raw_json column holds the awb_data dict (keyed consignee_name /
    shipper_name).  This function normalises the output to receiver_name /
    shipper_name so callers match the awb_parser.parse_awb_pdf() contract.
    """
    if _db_path is None:
        return None
    with _connect() as con:
        row = con.execute(
            """SELECT raw_json FROM awb_documents
               WHERE batch_id=? ORDER BY updated_at DESC LIMIT 1""",
            (batch_id,),
        ).fetchone()
    if not row:
        return None
    try:
        outer = json.loads(row["raw_json"])
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(outer, dict):
        return None
    result: Dict[str, Any] = {
        "receiver_name": outer.get("consignee_name", ""),
        "shipper_name":  outer.get("shipper_name", ""),
        "awb_number":    outer.get("awb", ""),
        "carrier":       outer.get("carrier", ""),
    }
    # Prefer inner awb_parser fields when the nested raw_json string is present
    inner_raw = outer.get("raw_json")
    if inner_raw:
        try:
            inner = json.loads(inner_raw)
            if isinstance(inner, dict):
                if inner.get("receiver_name"):
                    result["receiver_name"] = inner["receiver_name"]
                if inner.get("shipper_name"):
                    result["shipper_name"] = inner["shipper_name"]
        except (json.JSONDecodeError, TypeError):
            pass
    return result


# ── PZ documents ───────────────────────────────────────────────────────────────

def store_pz_document(
    document_id: str,
    batch_id:    str,
    pz_data:     Dict[str, Any],
) -> str:
    """
    Register a PZ output record.  Upserts on (batch_id, doc_no).
    Typical keys in pz_data: doc_no, line_count, total_net_pln,
    total_gross_pln, duty_a00_pln, verification_status, amendment_flags,
    workdrive_pdf_id, workdrive_xlsx_id.
    """
    if _db_path is None:
        return ""
    doc_no = str(pz_data.get("doc_no") or "")
    now    = _now()
    flags  = json.dumps(pz_data.get("amendment_flags") or [], ensure_ascii=False)
    with _lock:
        with _connect() as con:
            existing = None
            if doc_no:
                existing = con.execute(
                    "SELECT id FROM pz_documents WHERE batch_id=? AND doc_no=? LIMIT 1",
                    (batch_id, doc_no),
                ).fetchone()
            if existing is None:
                existing = con.execute(
                    "SELECT id FROM pz_documents WHERE document_id=? LIMIT 1",
                    (document_id,),
                ).fetchone()

            row_id = existing["id"] if existing else str(uuid.uuid4())
            if existing:
                con.execute(
                    """UPDATE pz_documents SET
                           document_id=?, doc_no=?, line_count=?,
                           total_net_pln=?, total_gross_pln=?, duty_a00_pln=?,
                           verification_status=?, amendment_flags=?,
                           workdrive_pdf_id=?, workdrive_xlsx_id=?,
                           updated_at=?
                       WHERE id=?""",
                    (
                        document_id,
                        doc_no,
                        int(pz_data.get("line_count") or 0),
                        float(pz_data.get("total_net_pln") or 0),
                        float(pz_data.get("total_gross_pln") or 0),
                        float(pz_data.get("duty_a00_pln") or 0),
                        str(pz_data.get("verification_status") or "unknown"),
                        flags,
                        str(pz_data.get("workdrive_pdf_id") or ""),
                        str(pz_data.get("workdrive_xlsx_id") or ""),
                        now, row_id,
                    ),
                )
            else:
                con.execute(
                    """INSERT INTO pz_documents
                           (id, document_id, batch_id, doc_no, line_count,
                            total_net_pln, total_gross_pln, duty_a00_pln,
                            verification_status, amendment_flags,
                            workdrive_pdf_id, workdrive_xlsx_id,
                            created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        row_id, document_id, batch_id,
                        doc_no,
                        int(pz_data.get("line_count") or 0),
                        float(pz_data.get("total_net_pln") or 0),
                        float(pz_data.get("total_gross_pln") or 0),
                        float(pz_data.get("duty_a00_pln") or 0),
                        str(pz_data.get("verification_status") or "unknown"),
                        flags,
                        str(pz_data.get("workdrive_pdf_id") or ""),
                        str(pz_data.get("workdrive_xlsx_id") or ""),
                        now, now,
                    ),
                )
    return row_id


def get_pz_document(batch_id: str) -> Optional[Dict[str, Any]]:
    """Return most recent PZ record for a batch, or None."""
    if _db_path is None:
        return None
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM pz_documents WHERE batch_id=? ORDER BY updated_at DESC LIMIT 1",
            (batch_id,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["amendment_flags"] = json.loads(d["amendment_flags"])
    except (json.JSONDecodeError, TypeError):
        d["amendment_flags"] = []
    return d


# ── Query helpers ──────────────────────────────────────────────────────────────

def get_documents_for_batch(
    batch_id:      str,
    document_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return all documents for a batch, optionally filtered by type."""
    if _db_path is None:
        return []
    with _connect() as con:
        if document_type:
            rows = con.execute(
                """SELECT * FROM shipment_documents
                   WHERE batch_id=? AND document_type=?
                   ORDER BY created_at""",
                (batch_id, document_type),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM shipment_documents WHERE batch_id=? ORDER BY created_at",
                (batch_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_document(document_id: str) -> Optional[Dict[str, Any]]:
    """Return a single shipment_documents row by id, or None. Read-only.

    Used by the status write-back paths to read the current extraction_status
    BEFORE downgrading it, so a transient re-parse failure cannot overwrite a
    previously-good 'extracted'/'complete' row with 'extraction_failed'.
    """
    if _db_path is None or not document_id:
        return None
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM shipment_documents WHERE id=? LIMIT 1",
            (document_id,),
        ).fetchone()
    return dict(row) if row else None


def get_documents_by_awb(
    awb:           str,
    document_type: Optional[str] = "purchase_invoice",
) -> List[Dict[str, Any]]:
    """Return documents sharing the given AWB across batches.

    Used by the DHL Polish description generator to union invoice_lines
    across batches that share the same AWB (e.g. one shipment uploaded
    twice under different batch_ids — AWB 4218922912 has both
    SHIPMENT_*_9040dd39 and SHIPMENT_*_bd18ec98).  Read-only.
    """
    awb_n = (awb or "").strip()
    if _db_path is None or not awb_n:
        return []
    with _connect() as con:
        if document_type:
            rows = con.execute(
                """SELECT * FROM shipment_documents
                   WHERE awb=? AND document_type=?
                   ORDER BY batch_id, created_at""",
                (awb_n, document_type),
            ).fetchall()
        else:
            rows = con.execute(
                """SELECT * FROM shipment_documents
                   WHERE awb=? ORDER BY batch_id, created_at""",
                (awb_n,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_document_by_hash(
    batch_id:      str,
    document_type: str,
    file_hash:     str,
) -> Optional[Dict[str, Any]]:
    """Return existing document row matching the hash, or None."""
    if _db_path is None or not file_hash:
        return None
    with _connect() as con:
        row = con.execute(
            """SELECT * FROM shipment_documents
               WHERE batch_id=? AND document_type=? AND file_hash=? LIMIT 1""",
            (batch_id, document_type, file_hash),
        ).fetchone()
    return dict(row) if row else None


# ── Invoice lines ──────────────────────────────────────────────────────────────

def store_invoice_lines(
    document_id: str,
    batch_id:    str,
    lines:       List[Dict[str, Any]],
) -> int:
    """
    Insert invoice line stubs for a purchase invoice document.
    product_code is generated as <invoice_no>-<line_position>.
    Returns count of rows inserted.
    """
    if _db_path is None or not lines:
        return 0
    now = _now()
    inserted = 0
    with _lock, _connect() as con:
        for i, ln in enumerate(lines, start=1):
            inv_no = str(ln.get("invoice_no", ""))
            pos    = int(ln.get("line_position", i) or i)
            pc     = ln.get("product_code") or f"{inv_no}-{pos}"

            # hsn_code / hs_code are aliases — keep both in sync
            hsn = str(ln.get("hsn_code") or ln.get("hs_code") or "")

            # rate_usd / unit_price aliases; amount_usd / total_value aliases
            rate   = float(ln.get("rate_usd",  ln.get("unit_price",  0)) or 0)
            amount = float(ln.get("amount_usd", ln.get("total_value", 0)) or 0)

            try:
                con.execute(
                    """INSERT OR IGNORE INTO invoice_lines
                       (id, document_id, batch_id, invoice_no, line_position,
                        product_code, description, quantity, unit_price,
                        total_value, currency, hs_code,
                        gross_weight, net_weight, rate_usd, amount_usd, hsn_code,
                        created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        str(uuid.uuid4()), document_id, batch_id,
                        inv_no, pos, pc,
                        str(ln.get("description", "")),
                        float(ln.get("quantity", 0) or 0),
                        rate,        # unit_price (legacy)
                        amount,      # total_value (legacy)
                        str(ln.get("currency", "")),
                        hsn,         # hs_code (legacy)
                        float(ln.get("gross_weight", 0) or 0),
                        float(ln.get("net_weight", 0) or 0),
                        rate,        # rate_usd (canonical)
                        amount,      # amount_usd (canonical)
                        hsn,         # hsn_code (canonical)
                        now,
                    ),
                )
                inserted += 1

                # ── Product Master canonical-identity projection (PR-1) ──
                # invoice_lines is the single canonical mint point for
                # product_code.  Project the freshly minted (or
                # re-confirmed) identity into product_master so every
                # downstream consumer can later link by product_code
                # without reaching into invoice_lines.
                #
                # Best-effort: failure here MUST NOT break invoice_lines
                # insert.  Idempotent via UNIQUE(product_code).  No
                # external API calls; reservation_db is local-DB only.
                try:
                    from . import reservation_db as _rdb
                    from ..core.config import settings as _settings
                    _rdb_path = _settings.storage_root / "reservation_queue.db"
                    _rdb.init_reservation_db(_rdb_path)
                    _rdb.upsert_product_master(
                        _rdb_path,
                        product_code       = pc,
                        design_no          = "",        # populated later by packing-side refresh
                        description        = str(ln.get("description", "")),
                        item_type          = "",        # populated later by description engine
                        hsn_code           = hsn,
                        unit_price_ref     = rate,
                        currency_ref       = str(ln.get("currency", "")),
                        confidence         = "high",
                        source_batch_id    = batch_id,
                        source_invoice_no  = inv_no,
                        source_document_id = document_id,
                        last_seen_batch_id = batch_id,
                    )
                except Exception as _master_exc:
                    log.warning(
                        "product_master upsert failed for pc=%r "
                        "(non-fatal): %s", pc, _master_exc,
                    )
            except Exception as exc:
                log.warning("invoice_lines insert failed: %s", exc)
    return inserted


def get_invoice_lines(
    batch_id:   str,
    invoice_no: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return invoice lines for a batch, optionally filtered by invoice_no."""
    if _db_path is None:
        return []
    with _connect() as con:
        if invoice_no:
            rows = con.execute(
                "SELECT * FROM invoice_lines WHERE batch_id=? AND invoice_no=? ORDER BY line_position",
                (batch_id, invoice_no),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM invoice_lines WHERE batch_id=? ORDER BY invoice_no, line_position",
                (batch_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_invoice_lines_for_batch(batch_id: str) -> List[Dict[str, Any]]:
    """Alias for get_invoice_lines(batch_id) — preferred name for matching pipelines."""
    return get_invoice_lines(batch_id)


def get_invoice_lines_for_document(
    document_id: str,
    limit:       int = 50,
) -> List[Dict[str, Any]]:
    """Return invoice_lines belonging to a single shipment_documents row.

    Used by the Document Registry to surface line counts + preview for
    purchase_invoice rows. Read-only; capped at `limit` rows for payload
    safety (matches the existing fields cap on the registry endpoint).
    """
    if _db_path is None or not document_id:
        return []
    with _connect() as con:
        rows = con.execute(
            """SELECT * FROM invoice_lines
               WHERE document_id=? ORDER BY line_position LIMIT ?""",
            (document_id, int(limit)),
        ).fetchall()
    return [dict(r) for r in rows]


def count_invoice_lines_for_document(document_id: str) -> int:
    """Count invoice_lines for a single document row (no preview)."""
    if _db_path is None or not document_id:
        return 0
    with _connect() as con:
        row = con.execute(
            "SELECT COUNT(*) AS n FROM invoice_lines WHERE document_id=?",
            (document_id,),
        ).fetchone()
    return int(row["n"] if row else 0)


def get_sales_packing_lines_for_document(
    document_id: str,
    limit:       int = 50,
) -> List[Dict[str, Any]]:
    """Return sales_packing_lines belonging to a single shipment_documents row.

    Sales packing extraction writes to sales_packing_lines (NOT to
    document_extracted_fields), so the Document Registry rendered
    "Lines/Fields: 0" for sales_packing_list rows. This mirrors
    ``get_invoice_lines_for_document``.

    The FK ``sales_document_id`` is keyed two ways across paths and BOTH must
    resolve for the registry to be correct:
      * reprocess  → ``sales_document_id == shipment_documents.id`` (this doc_id)
      * intake     → a freshly-minted ``sales_documents.id`` whose
                     ``document_id`` back-references this shipment_documents.id
    Read-only; capped at ``limit``. No FK / write changes.
    """
    if _db_path is None or not document_id:
        return []
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM sales_packing_lines "
            "WHERE sales_document_id = ? "
            "   OR sales_document_id IN "
            "      (SELECT id FROM sales_documents WHERE document_id = ?) "
            "ORDER BY created_at LIMIT ?",
            (document_id, document_id, int(limit)),
        ).fetchall()
    return [dict(r) for r in rows]


def count_sales_packing_lines_for_document(document_id: str) -> int:
    """Count sales_packing_lines for a single document row (no preview).

    Resolves both FK shapes (reprocess: ``sales_document_id`` == the
    shipment_documents.id; intake: a ``sales_documents.id`` whose
    ``document_id`` back-references it) — see
    ``get_sales_packing_lines_for_document``.
    """
    if _db_path is None or not document_id:
        return 0
    with _connect() as con:
        row = con.execute(
            "SELECT COUNT(*) AS n FROM sales_packing_lines "
            "WHERE sales_document_id = ? "
            "   OR sales_document_id IN "
            "      (SELECT id FROM sales_documents WHERE document_id = ?)",
            (document_id, document_id),
        ).fetchone()
    return int(row["n"] if row else 0)


# ── Sales documents ────────────────────────────────────────────────────────────

def _shipment_doc_contractor_id(con: sqlite3.Connection, document_id: str) -> str:
    """Read ``shipment_documents.client_contractor_id`` for *document_id*.

    This is the authoritative Customer-Master contractor identity bound at
    intake (``register_document``). Returns '' when the row or column is
    absent. Never raises — projection is best-effort.
    """
    if not (document_id or "").strip():
        return ""
    try:
        row = con.execute(
            "SELECT client_contractor_id FROM shipment_documents WHERE id=?",
            (str(document_id),),
        ).fetchone()
    except sqlite3.OperationalError:
        return ""
    if not row:
        return ""
    return (row["client_contractor_id"] or "").strip()


def _sales_doc_contractor_id(con: sqlite3.Connection, sales_document_id: str) -> str:
    """Read ``sales_documents.client_contractor_id`` for a sales_documents.id.

    Used to project the parent document's contractor authority onto its
    packing lines. Returns '' when absent. Never raises.
    """
    if not (sales_document_id or "").strip():
        return ""
    try:
        row = con.execute(
            "SELECT client_contractor_id FROM sales_documents WHERE id=?",
            (str(sales_document_id),),
        ).fetchone()
    except sqlite3.OperationalError:
        return ""
    if not row:
        return ""
    return (row["client_contractor_id"] or "").strip()


def store_sales_document(
    batch_id:    str,
    document_id: str,
    data:        Dict[str, Any],
) -> str:
    """
    Insert a sales document record. Returns the sales_document id.

    PR-2 (contractor-at-birth): ``client_contractor_id`` is projected onto the
    row. Precedence: explicit ``data["client_contractor_id"]`` → derived from
    the authoritative ``shipment_documents.client_contractor_id`` for
    *document_id*. This keeps the Customer-Master contractor authority resolved
    at intake from being dropped at the sales boundary (the silent-drop root
    cause). ``client_name`` is unchanged — contractor is an additive reference,
    never the identity key.
    """
    if _db_path is None:
        return ""
    now = _now()
    row_id = str(uuid.uuid4())
    with _lock, _connect() as con:
        cid = str(data.get("client_contractor_id", "") or "").strip()
        if not cid:
            cid = _shipment_doc_contractor_id(con, document_id)
        con.execute(
            """INSERT OR REPLACE INTO sales_documents
               (id, batch_id, document_id, client_name, client_ref,
                document_type, sales_doc_no, sales_doc_date,
                source_file_path, extraction_status,
                client_contractor_id, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row_id, batch_id, document_id,
                str(data.get("client_name", "")),
                str(data.get("client_ref", "")),
                str(data.get("document_type", "sales_invoice")),
                str(data.get("sales_doc_no", "")),
                str(data.get("sales_doc_date", "")),
                str(data.get("source_file_path", "")),
                str(data.get("extraction_status", "pending")),
                cid,
                now, now,
            ),
        )
    return row_id


def get_sales_documents(batch_id: str) -> List[Dict[str, Any]]:
    """Return all sales documents for a batch."""
    if _db_path is None:
        return []
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM sales_documents WHERE batch_id=? ORDER BY created_at",
            (batch_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def set_sales_client_name(
    batch_id: str, sales_document_id: str, client_name: str,
    *, old_client_name: Optional[str] = None,
) -> int:
    """PR-3: canonicalize the client_name on a sales_documents row AND its
    sales_packing_lines.

    Used when the operator's Customer-Master selection (client_contractor_id)
    is the authority and the display/grouping name must become the canonical
    ``bill_to_name`` consistently across the sales chain — so the draft, the
    v_sales_to_wfirma view, the reservation preview, and the next draft-sync all
    agree on one name (no split-brain).

    When *old_client_name* is supplied, the line update is SCOPED to lines that
    currently carry that name — so a multi-client packing document (distinct
    client_name values on different lines) never has unrelated lines clobbered.
    Returns the count of packing lines updated. Never raises beyond DB init.
    """
    if _db_path is None or not sales_document_id or not (client_name or "").strip():
        return 0
    now = _now()
    # Scope by old name whenever it is supplied (including "" for the
    # empty-name recovery case) so unrelated lines are never clobbered.
    old = old_client_name
    with _lock, _connect() as con:
        if old is not None:
            con.execute(
                "UPDATE sales_documents SET client_name=?, updated_at=? "
                "WHERE id=? AND batch_id=? AND client_name=?",
                (client_name, now, sales_document_id, batch_id, old),
            )
            cur = con.execute(
                "UPDATE sales_packing_lines SET client_name=? "
                "WHERE sales_document_id=? AND batch_id=? AND client_name=?",
                (client_name, sales_document_id, batch_id, old),
            )
        else:
            con.execute(
                "UPDATE sales_documents SET client_name=?, updated_at=? "
                "WHERE id=? AND batch_id=?",
                (client_name, now, sales_document_id, batch_id),
            )
            cur = con.execute(
                "UPDATE sales_packing_lines SET client_name=? "
                "WHERE sales_document_id=? AND batch_id=?",
                (client_name, sales_document_id, batch_id),
            )
        return cur.rowcount or 0


def set_sales_document_contractor(
    batch_id: str, sales_document_id: str, contractor_id: str,
) -> Dict[str, Any]:
    """Operator-driven direct assignment of the contractor authority onto ONE
    sales_documents row AND its sales_packing_lines.

    Used by the Sales-page blocked-record repair (Phase A — direct customer
    resolution). When a draft could not be born because no contractor was
    selected at intake (``contractor_missing``), the operator picks a
    Customer-Master customer and this writes its ``bill_to_contractor_id``
    (== sales chain ``client_contractor_id``) onto the blocked document's chain.
    The subsequent draft sync then reads the contractor, resolves the canonical
    name, births the draft, and resolves the open block — no re-intake.

    Scoped strictly to the one document (id + batch). This is a deliberate
    operator OVERRIDE: unlike ``backfill_contractor_ids`` (which only fills
    empties), it overwrites any existing ``client_contractor_id`` on the target
    document — so the prior value is read first and surfaced as
    ``previous_contractor_id`` for audit/disclosure (the caller can warn on an
    overwrite). It never changes ``client_name`` (the sync's canonical-rename
    step owns that) and never touches another document's rows. Returns
    ``{"sales_documents_updated", "sales_lines_updated", "previous_contractor_id"}``.
    Local-DB only; never raises beyond DB init.
    """
    if (_db_path is None
            or not (batch_id or "").strip()
            or not (sales_document_id or "").strip()
            or not (contractor_id or "").strip()):
        return {"sales_documents_updated": 0, "sales_lines_updated": 0,
                "previous_contractor_id": ""}
    now = _now()
    with _lock, _connect() as con:
        prev_row = con.execute(
            "SELECT client_contractor_id FROM sales_documents "
            "WHERE id=? AND batch_id=?",
            (sales_document_id, batch_id),
        ).fetchone()
        previous = (prev_row["client_contractor_id"] if prev_row else "") or ""
        cur_doc = con.execute(
            "UPDATE sales_documents SET client_contractor_id=?, updated_at=? "
            "WHERE id=? AND batch_id=?",
            (contractor_id, now, sales_document_id, batch_id),
        )
        cur_lines = con.execute(
            "UPDATE sales_packing_lines SET client_contractor_id=? "
            "WHERE sales_document_id=? AND batch_id=?",
            (contractor_id, sales_document_id, batch_id),
        )
    return {
        "sales_documents_updated": cur_doc.rowcount or 0,
        "sales_lines_updated":     cur_lines.rowcount or 0,
        "previous_contractor_id":  previous,
    }


def get_sales_documents_for_shipment_doc(
    document_id: str,
) -> List[Dict[str, Any]]:
    """Return sales_documents rows linked to a shipment_documents.id.

    Linkage: sales_documents.document_id == shipment_documents.id (the
    back-reference column populated by store_sales_document). Used by
    the sales reprocess resolver Pass 2 to scope client_name lookups
    to the *same* shipment document — preventing cross-document
    contamination (e.g. a stray link_as_sales row from another file in
    the same batch leaking its client_name into reprocessed rows).

    Local-DB read only. Returns [] when not initialised or no match.
    """
    if _db_path is None or not (document_id or "").strip():
        return []
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM sales_documents WHERE document_id=? "
            "ORDER BY created_at",
            (str(document_id),),
        ).fetchall()
    return [dict(r) for r in rows]


def update_sales_document_client_name(
    sales_document_id: str,
    client_name:       str,
) -> bool:
    """Local UPDATE: set sales_documents.client_name when non-empty.

    Used by the self-healing sales reprocess resolver to backfill
    client_name on sales_documents rows that were corrupted before
    PR #187 (empty client_name). No-op when client_name is empty or
    whitespace. NEVER raises — local-DB only, no external paths.

    Returns True on successful update, False otherwise.
    """
    if _db_path is None or not sales_document_id:
        return False
    cn = (client_name or "").strip()
    if not cn:
        return False
    try:
        now = _now()
        with _lock, _connect() as con:
            con.execute(
                "UPDATE sales_documents "
                "SET client_name=?, updated_at=? WHERE id=?",
                (cn, now, sales_document_id),
            )
        return True
    except Exception as exc:
        log.warning("update_sales_document_client_name failed: %s", exc)
        return False


def update_sales_document_parser_diagnostic(
    sales_document_id: str,
    parser_diagnostic: Dict[str, Any],
) -> bool:
    """Persist parser_diagnostic dict on sales_documents.

    Mirrors packing_documents.parser_diagnostic_json (purchase side).
    Returns True on success.  NEVER raises — diagnostic persistence is
    observability and must not break the parse path.
    """
    if _db_path is None or not sales_document_id:
        return False
    try:
        import json as _json
        payload = _json.dumps(parser_diagnostic or {}, ensure_ascii=False)
        now = _now()
        with _lock, _connect() as con:
            con.execute(
                "UPDATE sales_documents "
                "SET parser_diagnostic_json=?, updated_at=? WHERE id=?",
                (payload, now, sales_document_id),
            )
        return True
    except Exception as exc:
        log.warning("update_sales_document_parser_diagnostic failed: %s", exc)
        return False


def get_or_create_sales_document_for_packing(
    batch_id:            str,
    packing_document_id: str,
    client_name:         str,
    *,
    client_contractor_id: str = "",
) -> str:
    """
    Idempotent: return or create a sales_documents row that represents a purchase
    packing document being promoted to the sales side (via link-as-sales).

    Uses the synthetic document_id ``"packing:{packing_document_id}"`` as the
    stable lookup key — repeated calls for the same packing doc return the same
    row.  If the row already exists but the client_name differs (operator
    corrected a typo), the name is updated in-place.

    ``client_contractor_id`` — the operator's link-as-sales Customer-Master
    selection. When supplied it is the customer authority and is written onto
    ``sales_documents.client_contractor_id`` (which ``replace_sales_packing_lines``
    then projects onto the sales lines → the proforma draft). It OUTRANKS the
    best-effort projection and any parsed name (rules 1–2); the projection is
    used only when no contractor was selected (rule 3). When blank, behaviour is
    unchanged (existing fallback — rule 6).

    Returns the sales_document primary-key id.
    """
    if _db_path is None:
        return ""
    synthetic_doc_id = f"packing:{packing_document_id}"
    explicit_cid = (client_contractor_id or "").strip()
    now = _now()
    with _lock, _connect() as con:
        # Contractor (customer) authority precedence:
        #   1. explicit_cid  — operator's link-as-sales Customer-Master pick
        #                      (highest authority; contractor_id outranks name).
        #   2. projected_cid — best-effort projection from the packing
        #                      shipment_documents row; '' when unbound.
        # The operator selection WINS; fall back to the projection only when no
        # contractor was selected (rules 1–3).
        projected_cid = _shipment_doc_contractor_id(con, packing_document_id)
        existing = con.execute(
            "SELECT id, client_contractor_id FROM sales_documents "
            "WHERE batch_id=? AND document_id=?",
            (batch_id, synthetic_doc_id),
        ).fetchone()
        if existing:
            existing_cid = (existing["client_contractor_id"] or "").strip()
            # Explicit operator pick wins; else preserve a resolved authority
            # (never clobber with a projection — #570 class); else best-effort.
            cid_to_write = explicit_cid or existing_cid or projected_cid
            if client_name:
                con.execute(
                    "UPDATE sales_documents "
                    "SET client_name=?, client_contractor_id=?, updated_at=? WHERE id=?",
                    (client_name, cid_to_write, now, existing["id"]),
                )
            elif cid_to_write != existing_cid:
                con.execute(
                    "UPDATE sales_documents "
                    "SET client_contractor_id=?, updated_at=? WHERE id=?",
                    (cid_to_write, now, existing["id"]),
                )
            return existing["id"]
        row_id = str(uuid.uuid4())
        con.execute(
            """INSERT INTO sales_documents
               (id, batch_id, document_id, client_name, client_ref,
                document_type, sales_doc_no, sales_doc_date,
                source_file_path, extraction_status,
                client_contractor_id, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row_id, batch_id, synthetic_doc_id,
                client_name, "",
                "packing_list_promote", "", "",
                "", "extracted",
                explicit_cid or projected_cid,
                now, now,
            ),
        )
    return row_id


def ensure_sales_document_id(
    batch_id:             str,
    document_id:          str,
    *,
    client_name:          str = "",
    document_type:        str = "sales_packing_list",
    source_file_path:     str = "",
    client_contractor_id: str = "",
) -> str:
    """Idempotent: ensure a ``sales_documents`` row whose PRIMARY KEY ``id``
    equals *document_id*, and return that id.

    The reprocess sales path keys ``sales_packing_lines.sales_document_id`` to
    the sales packing list's ``shipment_documents.id`` (*document_id* here).
    ``wfirma_reservation`` and the ``v_sales_to_wfirma`` view join those lines
    on ``sales_documents.id`` — so the ``sales_documents`` row MUST carry that
    same id, otherwise every line is orphaned from those readers. The earlier
    ``store_sales_document`` behaviour minted a divergent random UUID, which is
    the root of that orphaning. Making ``id == document_id`` keeps the id-join
    aligned without rewiring the reprocess branch (``sales_doc_id`` stays
    ``document_id`` everywhere downstream).

    Idempotent on the id, so re-reprocess reuses the same row. Also removes
    line-less phantom siblings (same ``document_id`` under a stale random UUID)
    left by the pre-fix path. Returns *document_id* (== the row id).
    """
    if _db_path is None or not document_id:
        return ""
    now = _now()
    with _lock, _connect() as con:
        # PR-2: project contractor authority. Explicit arg wins; else derive
        # from the authoritative shipment_documents row (id == document_id on
        # the reprocess path). Best-effort '' when unbound.
        cid = (client_contractor_id or "").strip() or \
            _shipment_doc_contractor_id(con, document_id)
        existing = con.execute(
            "SELECT id, client_contractor_id FROM sales_documents WHERE id=?",
            (document_id,),
        ).fetchone()
        if existing:
            existing_cid = (existing["client_contractor_id"] or "").strip()
            # Merge-not-replace: fill the contractor reference only when empty.
            cid_to_write = existing_cid or cid
            if client_name and cid_to_write != existing_cid:
                con.execute(
                    "UPDATE sales_documents "
                    "SET client_name=?, client_contractor_id=?, updated_at=? WHERE id=?",
                    (client_name, cid_to_write, now, document_id),
                )
            elif client_name:
                con.execute(
                    "UPDATE sales_documents SET client_name=?, updated_at=? WHERE id=?",
                    (client_name, now, document_id),
                )
            elif cid_to_write != existing_cid:
                con.execute(
                    "UPDATE sales_documents "
                    "SET client_contractor_id=?, updated_at=? WHERE id=?",
                    (cid_to_write, now, document_id),
                )
        else:
            # Carry over operator-supplied identity from a pre-fix sibling
            # (same document_id under a stale random-UUID id) BEFORE it is
            # purged below — otherwise a prior backfill / operator edit of
            # client_name would be lost, and the reprocess client_name resolver
            # (Pass 2a, which reads sales_documents by document_id) would fall
            # through to the wFirma reverse-lookup.
            client_ref = ""
            if not client_name:
                sib = con.execute(
                    "SELECT client_name, client_ref FROM sales_documents "
                    "WHERE batch_id=? AND document_id=? AND id<>? "
                    "AND TRIM(COALESCE(client_name,''))<>'' "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (batch_id, document_id, document_id),
                ).fetchone()
                if sib:
                    client_name = sib[0] or ""
                    client_ref = sib[1] or ""
            # OR IGNORE: a concurrent reprocess of the same document may have
            # inserted the id==document_id row between the SELECT above and here
            # (the threading lock only serialises within this process). The
            # no-op-on-conflict keeps the helper safe under multi-worker /
            # concurrent-tab reprocess instead of raising a swallowed
            # UNIQUE-constraint error that would leave the lines orphaned.
            con.execute(
                """INSERT OR IGNORE INTO sales_documents
                   (id, batch_id, document_id, client_name, client_ref,
                    document_type, sales_doc_no, sales_doc_date,
                    source_file_path, extraction_status,
                    client_contractor_id, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    document_id, batch_id, document_id,
                    client_name, client_ref,
                    document_type, "", "",
                    source_file_path, "extracted",
                    cid,
                    now, now,
                ),
            )
        # Drop pre-fix phantom rows: older runs created a sales_documents row
        # with a random-UUID id + the same document_id. Once the canonical
        # id==document_id row exists, those siblings are empty phantoms — delete
        # only the ones that own NO sales_packing_lines, so real data is never
        # touched.
        con.execute(
            "DELETE FROM sales_documents "
            "WHERE batch_id=? AND document_id=? AND id<>? "
            "AND id NOT IN (SELECT DISTINCT sales_document_id "
            "               FROM sales_packing_lines WHERE batch_id=?)",
            (batch_id, document_id, document_id, batch_id),
        )
    return document_id


def store_sales_packing_lines(
    sales_document_id: str,
    batch_id:          str,
    lines:             List[Dict[str, Any]],
) -> int:
    """Insert sales packing lines. Returns inserted count.

    PR-2: each line carries ``client_contractor_id`` projected from the parent
    sales_document (which itself derives from the authoritative
    shipment_documents row). Per-line explicit value wins; else the parent's.
    """
    if _db_path is None or not lines:
        return 0
    now = _now()
    inserted = 0
    with _lock, _connect() as con:
        parent_cid = _sales_doc_contractor_id(con, sales_document_id)
        for ln in lines:
            try:
                line_cid = str(ln.get("client_contractor_id", "") or "").strip() \
                    or parent_cid
                con.execute(
                    """INSERT INTO sales_packing_lines
                       (id, batch_id, sales_document_id, client_name, client_ref,
                        product_code, design_no, bag_id, quantity, remarks,
                        unit_price, currency, total_value, price_source,
                        client_contractor_id, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        str(uuid.uuid4()), batch_id, sales_document_id,
                        str(ln.get("client_name", "")),
                        str(ln.get("client_ref", "")),
                        str(ln.get("product_code", "")),
                        str(ln.get("design_no", "")),
                        str(ln.get("bag_id", "")),
                        float(ln.get("quantity", 0) or 0),
                        str(ln.get("remarks", "")),
                        float(ln.get("unit_price", 0) or 0),
                        str(ln.get("currency", "") or "").upper(),
                        float(ln.get("total_value", 0) or 0),
                        str(ln.get("price_source", "") or ""),
                        line_cid,
                        now,
                    ),
                )
                inserted += 1
            except Exception as exc:
                log.warning("sales_packing_lines insert failed: %s", exc)
    return inserted


def replace_sales_packing_lines(
    sales_document_id: str,
    batch_id:          str,
    lines:             List[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Idempotent re-ingest: atomically DELETE all sales_packing_lines for
    *(sales_document_id, batch_id)* and re-INSERT the supplied *lines*.

    Use ONLY for operator-approved re-ingest (parser fix backfill, sales
    file correction). Normal first-time intake should keep using
    ``store_sales_packing_lines`` so concurrent runs don't accidentally
    wipe a fresh document.

    Scoping is strict on (sales_document_id, batch_id) — never touches
    rows for other clients or other batches.

    Returns ``{"deleted": int, "inserted": int}``.
    """
    if _db_path is None or not sales_document_id or not batch_id:
        return {"deleted": 0, "inserted": 0}
    now = _now()
    deleted = 0
    inserted = 0
    with _lock, _connect() as con:
        # Defensive: count first so the response is honest even if INSERT
        # fails midway.
        deleted = con.execute(
            "SELECT COUNT(*) FROM sales_packing_lines "
            "WHERE sales_document_id=? AND batch_id=?",
            (sales_document_id, batch_id),
        ).fetchone()[0]

        con.execute(
            "DELETE FROM sales_packing_lines "
            "WHERE sales_document_id=? AND batch_id=?",
            (sales_document_id, batch_id),
        )
        parent_cid = _sales_doc_contractor_id(con, sales_document_id)
        for ln in (lines or []):
            try:
                line_cid = str(ln.get("client_contractor_id", "") or "").strip() \
                    or parent_cid
                con.execute(
                    """INSERT INTO sales_packing_lines
                       (id, batch_id, sales_document_id, client_name, client_ref,
                        product_code, design_no, bag_id, quantity, remarks,
                        unit_price, currency, total_value, price_source,
                        client_contractor_id, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        str(uuid.uuid4()), batch_id, sales_document_id,
                        str(ln.get("client_name", "")),
                        str(ln.get("client_ref", "")),
                        str(ln.get("product_code", "")),
                        str(ln.get("design_no", "")),
                        str(ln.get("bag_id", "")),
                        float(ln.get("quantity", 0) or 0),
                        str(ln.get("remarks", "")),
                        float(ln.get("unit_price", 0) or 0),
                        str(ln.get("currency", "") or "").upper(),
                        float(ln.get("total_value", 0) or 0),
                        str(ln.get("price_source", "") or ""),
                        line_cid,
                        now,
                    ),
                )
                inserted += 1
            except Exception as exc:
                log.warning("replace_sales_packing_lines insert failed: %s",
                             exc)
    return {"deleted": int(deleted), "inserted": int(inserted)}


def backfill_contractor_ids(batch_id: str) -> Dict[str, int]:
    """PR-2 reconciliation: project ``client_contractor_id`` from the
    authoritative ``shipment_documents`` rows onto ``sales_documents`` and
    ``sales_packing_lines`` for *batch_id*.

    Pure projection — idempotent and additive:
      * only fills rows whose ``client_contractor_id`` is currently empty
        (never clobbers a resolved authority — #570 class),
      * never changes ``client_name`` (the draft identity key),
      * never creates drafts or blocked records (that is the sync layer's job).

    Repairs historical batches whose sales rows were born before PR-2 dropped
    the contractor authority. Safe to re-run. Returns update counts.
    """
    if _db_path is None or not (batch_id or "").strip():
        return {"sales_documents_updated": 0, "sales_lines_updated": 0}
    now = _now()
    sd_updated = 0
    sl_updated = 0
    with _lock, _connect() as con:
        sd_rows = con.execute(
            "SELECT id, document_id, client_contractor_id FROM sales_documents "
            "WHERE batch_id=?",
            (batch_id,),
        ).fetchall()
        for r in sd_rows:
            if (r["client_contractor_id"] or "").strip():
                continue  # already projected — idempotent skip
            ship_doc_id = str(r["document_id"] or "")
            # Synthetic link-as-sales rows back-reference the packing doc as
            # "packing:<real_shipment_documents.id>".
            if ship_doc_id.startswith("packing:"):
                ship_doc_id = ship_doc_id.split(":", 1)[1]
            cid = _shipment_doc_contractor_id(con, ship_doc_id)
            if not cid:
                continue
            con.execute(
                "UPDATE sales_documents "
                "SET client_contractor_id=?, updated_at=? WHERE id=?",
                (cid, now, r["id"]),
            )
            sd_updated += 1

        # Project parent → lines for any line still empty.
        line_rows = con.execute(
            "SELECT spl.id AS lid, sd.client_contractor_id AS cid "
            "FROM sales_packing_lines spl "
            "JOIN sales_documents sd ON sd.id = spl.sales_document_id "
            "WHERE spl.batch_id=? "
            "AND TRIM(COALESCE(spl.client_contractor_id,''))='' "
            "AND TRIM(COALESCE(sd.client_contractor_id,''))<>''",
            (batch_id,),
        ).fetchall()
        for lr in line_rows:
            con.execute(
                "UPDATE sales_packing_lines SET client_contractor_id=? WHERE id=?",
                (lr["cid"], lr["lid"]),
            )
            sl_updated += 1
    return {"sales_documents_updated": sd_updated, "sales_lines_updated": sl_updated}


def get_sales_packing_lines(
    batch_id: str,
    *,
    physical_only: bool = False,
) -> List[Dict[str, Any]]:
    """Return sales packing lines for a batch.

    Parameters
    ----------
    batch_id : str
    physical_only : bool (default False)
        When True, returns one row per physical item, scoped per
        ``sales_document``. Within a document, if any
        ``price_source='packing_xlsx_value'`` rows exist — the cost-authority
        rows written by the link-as-sales promotion path
        (``routes_packing.py`` ``_build_matched_sales_lines``) — only those are
        returned for that document; they are the de-duped one-per-item set. A
        document with no such row (a sales packing list parsed at intake or
        reprocess, whose rows carry ``price_source='excel_symbol'`` or ``''``)
        returns all of its rows, which are already one per item. Per-document
        scoping means a batch that mixes a promoted document and a parsed
        document never under-counts the parsed one nor double-counts the
        promoted one.

        (Note: the ``import-sales-prices`` endpoint does NOT insert rows here —
        it patches the proforma draft's ``editable_lines_json``. The
        ``excel_symbol`` label is applied by the sales packing parser at
        intake/reprocess time, not by import-sales-prices.)

        Leave ``physical_only=False`` (the default) when the caller needs all
        price-authority rows for pricing decisions — proforma draft sync,
        proforma reset, price-source audit, reporting.

        Pass ``physical_only=True`` when only physical item identity matters:
        ``sales_linkage`` and warehouse scan-count contexts, where returning
        all 292 rows for a 146-line batch would report 292/292 not-scanned
        and double the missing count.
    """
    if _db_path is None:
        return []

    with _connect() as con:
        all_rows = [dict(r) for r in con.execute(
            "SELECT * FROM sales_packing_lines WHERE batch_id=? ORDER BY created_at",
            (batch_id,),
        ).fetchall()]

    if not physical_only:
        return all_rows

    # One row per physical item, scoped per sales_document. A document that has
    # any canonical cost row (price_source='packing_xlsx_value') is de-duped to
    # just those; a document parsed without that pass (only 'excel_symbol' / ''
    # rows — already one per item) keeps all of its rows. Per-document scoping
    # so a mixed batch neither under-counts the parsed documents nor
    # double-counts the promoted ones.
    docs_with_canonical = {
        r["sales_document_id"] for r in all_rows
        if r.get("price_source") == "packing_xlsx_value"
    }
    return [
        r for r in all_rows
        if r.get("sales_document_id") not in docs_with_canonical
        or r.get("price_source") == "packing_xlsx_value"
    ]


def query_sales_to_wfirma(batch_id: str) -> List[Dict[str, Any]]:
    """
    Read-only resolution: every sales_packing_lines row for *batch_id*,
    annotated with the matched wFirma `product_code` from packing_lines.
    Unmatched sales designs come back with wfirma_product_code=None.

    Returned columns:
      batch_id, sales_document_id, sales_doc_no, client_name, client_ref,
      sales_design_no, wfirma_product_code, purchase_design_no, qty
    """
    if _db_path is None or not batch_id:
        return []
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM v_sales_to_wfirma WHERE batch_id=? "
            "ORDER BY sales_document_id, sales_design_no",
            (batch_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Product descriptions (locked-block store) ───────────────────────────────

def get_product_description(product_code: str) -> Optional[Dict[str, Any]]:
    """Return the persisted description row for *product_code*, or None."""
    if _db_path is None or not product_code:
        return None
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM product_descriptions WHERE product_code=?",
            (str(product_code),),
        ).fetchone()
    return dict(row) if row else None


def upsert_product_description(
    *,
    product_code:      str,
    item_type:         str,
    name_pl:           str,
    description_pl:    str,
    material_pl:       str,
    purpose_pl:        str,
    description_block: str,
    source:            str = "auto",
    description_en:    str = "",
    description_line:  str = "",
) -> None:
    """
    Insert or update a product description row.

    Idempotency rule: an existing row with source='manual' is NEVER
    overwritten by source='auto' callers — protects operator overrides
    from being clobbered by the default generator. Manual→manual updates
    are allowed; auto→manual upgrades are allowed; auto→auto is a no-op
    on second call (existing row returned by get_*).
    """
    if _db_path is None or not product_code:
        return
    now = _now()
    with _lock, _connect() as con:
        existing = con.execute(
            "SELECT source FROM product_descriptions WHERE product_code=?",
            (str(product_code),),
        ).fetchone()
        if existing is not None and existing["source"] == "manual" and source == "auto":
            # Manual override — do not touch.
            return
        if existing is not None:
            con.execute(
                """UPDATE product_descriptions
                   SET item_type=?, name_pl=?, description_pl=?, description_en=?,
                       material_pl=?, purpose_pl=?, description_block=?,
                       description_line=?, source=?, updated_at=?
                   WHERE product_code=?""",
                (item_type, name_pl, description_pl, description_en,
                 material_pl, purpose_pl, description_block, description_line,
                 source, now, str(product_code)),
            )
        else:
            con.execute(
                """INSERT INTO product_descriptions
                   (product_code, item_type, name_pl, description_pl,
                    description_en, material_pl, purpose_pl, description_block,
                    description_line, source, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (str(product_code), item_type, name_pl, description_pl,
                 description_en, material_pl, purpose_pl, description_block,
                 description_line, source, now, now),
            )


# ── Product identity backfill (write-mode, guarded) ──────────────────────────

_BACKFILL_SOURCE = "pz_rows_backfill"

#: Disposition strings returned by upsert_product_identity_from_backfill.
#: Dry-run variants are prefixed with "dry_run_".
BACKFILL_DISPOSITIONS = frozenset({
    "inserted",
    "updated",
    "skipped_manual",
    "skipped_417g",
    "skipped_generic",
    "dry_run_insert",
    "dry_run_update",
    "dry_run_skip_manual",
    "dry_run_skip_417g",
    "dry_run_skip_generic",
})


def upsert_product_identity_from_backfill(
    con,              # sqlite3.Connection — caller holds the connection
    product_code: str,
    identity,         # ProductIdentity from product_identity_engine
    *,
    dry_run: bool = True,
) -> str:
    """
    Insert or update a product_descriptions row from a ProductIdentity record.

    Guard order (evaluated before any write or dry-run check):
      1. supplier_prefix == "417G"  → skip (non-unique key, corruption risk)
      2. is_generic_description()   → skip
      3. product_code in FORBIDDEN_PRODUCT_CODE_KEYS → skip (legacy stubs)
      4. existing row source == 'manual' → skip (never overwrite manual rows)

    In dry-run mode (dry_run=True, the default):
      Returns a "dry_run_*" disposition string; NO writes are made.

    In write mode (dry_run=False):
      INSERT new row or UPDATE existing non-manual row with all 9 identity
      columns.  source is always set to 'pz_rows_backfill'.

    Returns one of the strings in BACKFILL_DISPOSITIONS.
    """
    # Lazy import — keeps document_db.py free of a hard dependency on
    # product_identity_engine at module load time.
    from app.services.product_identity_engine import (  # noqa: PLC0415
        is_generic_description,
        FORBIDDEN_PRODUCT_CODE_KEYS,
    )

    pc = str(product_code or "").strip()

    # ── Guard 1: 417G non-unique codes ──────────────────────────────────────
    if getattr(identity, "supplier_prefix", "") == "417G":
        return "dry_run_skip_417g" if dry_run else "skipped_417g"

    # ── Guard 2: generic description ────────────────────────────────────────
    desc_pl = str(getattr(identity, "description_pl", "") or "").strip()
    if is_generic_description(desc_pl):
        return "dry_run_skip_generic" if dry_run else "skipped_generic"

    # ── Guard 3: forbidden stub key ─────────────────────────────────────────
    if pc.upper() in FORBIDDEN_PRODUCT_CODE_KEYS:
        return "dry_run_skip_generic" if dry_run else "skipped_generic"

    # ── Guard 4: existing manual row ────────────────────────────────────────
    existing = con.execute(
        "SELECT source FROM product_descriptions WHERE product_code=?",
        (pc,),
    ).fetchone()
    if existing is not None and existing["source"] == "manual":
        return "dry_run_skip_manual" if dry_run else "skipped_manual"

    # ── Dry-run gate ────────────────────────────────────────────────────────
    if dry_run:
        return "dry_run_update" if existing is not None else "dry_run_insert"

    # ── Write ───────────────────────────────────────────────────────────────
    now = _now()
    # Map ProductIdentity fields to the product_descriptions schema.
    # For pz_rows backfill: name_pl and description_pl both take description_pl
    # (we have no separate short-name field from pz_rows).  material_pl and
    # purpose_pl are left empty — they may be enriched by future passes.
    row_values = (
        str(getattr(identity, "item_type",           "") or ""),
        desc_pl,                                          # name_pl
        desc_pl,                                          # description_pl
        str(getattr(identity, "description_en",      "") or ""),
        "",                                               # material_pl (not in pz_rows)
        "",                                               # purpose_pl  (not in pz_rows)
        str(getattr(identity, "description_bilingual","") or ""),  # description_block
        str(getattr(identity, "description_bilingual","") or ""),  # description_line
        _BACKFILL_SOURCE,                                 # source
        str(getattr(identity, "karat",               "") or ""),
        str(getattr(identity, "metal_color",         "") or ""),
        str(getattr(identity, "quality_string",      "") or ""),
        str(getattr(identity, "stone_type",          "") or ""),
        float(getattr(identity, "unit_price_eur",  0.0) or 0.0),
        float(getattr(identity, "unit_price_usd",  0.0) or 0.0),
        str(getattr(identity, "confidence",          "") or ""),
        str(getattr(identity, "supplier_prefix",     "") or ""),
        1 if getattr(identity, "is_globally_unique", False) else 0,
    )

    if existing is not None:
        # UPDATE — preserves created_at; the WHERE source != 'manual' is a
        # belt-and-suspenders guard on top of the pre-check above.
        con.execute(
            """UPDATE product_descriptions
               SET item_type=?, name_pl=?, description_pl=?, description_en=?,
                   material_pl=?, purpose_pl=?, description_block=?,
                   description_line=?, source=?,
                   karat=?, metal_color=?, quality_string=?, stone_type=?,
                   unit_price_eur=?, unit_price_usd=?, confidence=?,
                   supplier_prefix=?, is_globally_unique=?,
                   updated_at=?
               WHERE product_code=? AND source != 'manual'""",
            (*row_values, now, pc),
        )
        return "updated"
    else:
        con.execute(
            """INSERT INTO product_descriptions
               (product_code, item_type, name_pl, description_pl, description_en,
                material_pl, purpose_pl, description_block, description_line, source,
                karat, metal_color, quality_string, stone_type,
                unit_price_eur, unit_price_usd, confidence,
                supplier_prefix, is_globally_unique,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pc, *row_values, now, now),
        )
        return "inserted"


# ── Phase 6 MDI: Document Coverage Aggregate ─────────────────────────────────

def get_document_coverage_summary(db_path: Optional[Path] = None) -> Dict[str, Any]:
    """Platform-wide document coverage aggregation for MDI document domain.

    Read-only. Never raises — returns {} if the DB is missing or not
    initialised, so MDI scoring degrades gracefully.

    Returned keys:
        total_documents                  int
        document_type_counts             {type: int}
        extraction_status_counts         {status: int}
        parser_status_counts             {status: int}
        awb_linked_count                 int  (shipment_documents.awb != '')
        mrn_linked_count                 int  (related_mrn != '')
        pz_linked_count                  int  (related_pz_no != '')
        requires_manual_review_count     int
        customs_declaration_count        int
        customs_with_clearance_date      int  (clearance_date != '')
        pz_document_count                int
        pz_with_workdrive_count          int  (both pdf+xlsx WorkDrive IDs present)
        awb_document_count               int
        invoice_line_count               int
        invoice_lines_with_hs_code       int
    """
    path = db_path or _db_path
    if path is None or not Path(path).exists():
        return {}
    try:
        con = sqlite3.connect(str(path), check_same_thread=False, timeout=5)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only = ON")

        result: Dict[str, Any] = {}

        # ── shipment_documents totals ─────────────────────────────────────────
        row = con.execute("SELECT COUNT(*) AS n FROM shipment_documents").fetchone()
        result["total_documents"] = int(row["n"]) if row else 0

        # document_type breakdown
        rows = con.execute(
            "SELECT document_type, COUNT(*) AS n FROM shipment_documents "
            "GROUP BY document_type ORDER BY n DESC"
        ).fetchall()
        result["document_type_counts"] = {r["document_type"]: int(r["n"]) for r in rows}

        # extraction_status breakdown
        rows = con.execute(
            "SELECT extraction_status, COUNT(*) AS n FROM shipment_documents "
            "GROUP BY extraction_status"
        ).fetchall()
        result["extraction_status_counts"] = {r["extraction_status"]: int(r["n"]) for r in rows}

        # parser_status breakdown
        rows = con.execute(
            "SELECT parser_status, COUNT(*) AS n FROM shipment_documents "
            "GROUP BY parser_status"
        ).fetchall()
        result["parser_status_counts"] = {r["parser_status"]: int(r["n"]) for r in rows}

        # linkage counts
        row = con.execute(
            "SELECT "
            "  SUM(CASE WHEN TRIM(awb) != '' THEN 1 ELSE 0 END) AS awb_linked, "
            "  SUM(CASE WHEN TRIM(related_mrn) != '' THEN 1 ELSE 0 END) AS mrn_linked, "
            "  SUM(CASE WHEN TRIM(related_pz_no) != '' THEN 1 ELSE 0 END) AS pz_linked, "
            "  SUM(requires_manual_review) AS manual_review "
            "FROM shipment_documents"
        ).fetchone()
        result["awb_linked_count"]             = int(row["awb_linked"]    or 0) if row else 0
        result["mrn_linked_count"]             = int(row["mrn_linked"]    or 0) if row else 0
        result["pz_linked_count"]              = int(row["pz_linked"]     or 0) if row else 0
        result["requires_manual_review_count"] = int(row["manual_review"] or 0) if row else 0

        # ── customs_declarations ──────────────────────────────────────────────
        row = con.execute(
            "SELECT "
            "  COUNT(*) AS total, "
            "  SUM(CASE WHEN TRIM(clearance_date) != '' THEN 1 ELSE 0 END) AS with_date "
            "FROM customs_declarations"
        ).fetchone()
        result["customs_declaration_count"]    = int(row["total"]     or 0) if row else 0
        result["customs_with_clearance_date"]  = int(row["with_date"] or 0) if row else 0

        # ── pz_documents ──────────────────────────────────────────────────────
        row = con.execute(
            "SELECT "
            "  COUNT(*) AS total, "
            "  SUM(CASE WHEN TRIM(workdrive_pdf_id) != '' "
            "            AND TRIM(workdrive_xlsx_id) != '' THEN 1 ELSE 0 END) AS with_wdrive "
            "FROM pz_documents"
        ).fetchone()
        result["pz_document_count"]     = int(row["total"]      or 0) if row else 0
        result["pz_with_workdrive_count"] = int(row["with_wdrive"] or 0) if row else 0

        # ── awb_documents ─────────────────────────────────────────────────────
        row = con.execute("SELECT COUNT(*) AS n FROM awb_documents").fetchone()
        result["awb_document_count"] = int(row["n"]) if row else 0

        # ── invoice_lines ─────────────────────────────────────────────────────
        row = con.execute(
            "SELECT "
            "  COUNT(*) AS total, "
            "  SUM(CASE WHEN TRIM(COALESCE(hsn_code,'')) != '' OR "
            "           TRIM(COALESCE(hs_code,'')) != '' THEN 1 ELSE 0 END) AS with_hs "
            "FROM invoice_lines"
        ).fetchone()
        result["invoice_line_count"]          = int(row["total"]   or 0) if row else 0
        result["invoice_lines_with_hs_code"]  = int(row["with_hs"] or 0) if row else 0

        con.close()
        return result
    except Exception as exc:
        log.warning("[document_db] get_document_coverage_summary failed: %s", exc)
        return {}


def update_sales_packing_line_product_code(
    batch_id: str,
    row_id: str,
    product_code: str,
) -> bool:
    """Set ``product_code`` on one ``sales_packing_lines`` row.

    Used by POST /packing/{batch_id}/scored-pending/confirm when the operator
    explicitly assigns a product_code to a row that the spec scorer could not
    auto-resolve with HIGH confidence.

    Returns True when exactly one row was updated.  Never raises.
    """
    global _db_path
    if _db_path is None:
        log.warning("update_sales_packing_line_product_code: document_db not initialised")
        return False
    if not (batch_id or "").strip() or not (row_id or "").strip():
        return False
    try:
        with sqlite3.connect(str(_db_path)) as con:
            cur = con.execute(
                "UPDATE sales_packing_lines SET product_code=? WHERE id=? AND batch_id=?",
                ((product_code or "").strip(), row_id, batch_id),
            )
            return cur.rowcount == 1
    except Exception as exc:
        log.warning(
            "update_sales_packing_line_product_code row=%r batch=%r: %s",
            row_id, batch_id, exc,
        )
        return False
