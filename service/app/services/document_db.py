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
) -> None:
    """Patch status fields on an existing document row."""
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
    vals.append(document_id)
    with _lock:
        with _connect() as con:
            con.execute(
                f"UPDATE shipment_documents SET {', '.join(sets)} WHERE id=?",
                vals,
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


# ── Sales documents ────────────────────────────────────────────────────────────

def store_sales_document(
    batch_id:    str,
    document_id: str,
    data:        Dict[str, Any],
) -> str:
    """
    Insert or update a sales document record.
    Returns the sales_document id.
    """
    if _db_path is None:
        return ""
    now = _now()
    row_id = str(uuid.uuid4())
    with _lock, _connect() as con:
        con.execute(
            """INSERT OR REPLACE INTO sales_documents
               (id, batch_id, document_id, client_name, client_ref,
                document_type, sales_doc_no, sales_doc_date,
                source_file_path, extraction_status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row_id, batch_id, document_id,
                str(data.get("client_name", "")),
                str(data.get("client_ref", "")),
                str(data.get("document_type", "sales_invoice")),
                str(data.get("sales_doc_no", "")),
                str(data.get("sales_doc_date", "")),
                str(data.get("source_file_path", "")),
                str(data.get("extraction_status", "pending")),
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
) -> str:
    """
    Idempotent: return or create a sales_documents row that represents a purchase
    packing document being promoted to the sales side (via link-as-sales).

    Uses the synthetic document_id ``"packing:{packing_document_id}"`` as the
    stable lookup key — repeated calls for the same packing doc return the same
    row.  If the row already exists but the client_name differs (operator
    corrected a typo), the name is updated in-place.

    Returns the sales_document primary-key id.
    """
    if _db_path is None:
        return ""
    synthetic_doc_id = f"packing:{packing_document_id}"
    now = _now()
    with _lock, _connect() as con:
        existing = con.execute(
            "SELECT id FROM sales_documents WHERE batch_id=? AND document_id=?",
            (batch_id, synthetic_doc_id),
        ).fetchone()
        if existing:
            if client_name:
                con.execute(
                    "UPDATE sales_documents SET client_name=?, updated_at=? WHERE id=?",
                    (client_name, now, existing[0]),
                )
            return existing[0]
        row_id = str(uuid.uuid4())
        con.execute(
            """INSERT INTO sales_documents
               (id, batch_id, document_id, client_name, client_ref,
                document_type, sales_doc_no, sales_doc_date,
                source_file_path, extraction_status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row_id, batch_id, synthetic_doc_id,
                client_name, "",
                "packing_list_promote", "", "",
                "", "extracted",
                now, now,
            ),
        )
    return row_id


def store_sales_packing_lines(
    sales_document_id: str,
    batch_id:          str,
    lines:             List[Dict[str, Any]],
) -> int:
    """Insert sales packing lines. Returns inserted count."""
    if _db_path is None or not lines:
        return 0
    now = _now()
    inserted = 0
    with _lock, _connect() as con:
        for ln in lines:
            try:
                con.execute(
                    """INSERT INTO sales_packing_lines
                       (id, batch_id, sales_document_id, client_name, client_ref,
                        product_code, design_no, bag_id, quantity, remarks,
                        unit_price, currency, total_value, price_source,
                        created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
        for ln in (lines or []):
            try:
                con.execute(
                    """INSERT INTO sales_packing_lines
                       (id, batch_id, sales_document_id, client_name, client_ref,
                        product_code, design_no, bag_id, quantity, remarks,
                        unit_price, currency, total_value, price_source,
                        created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                        now,
                    ),
                )
                inserted += 1
            except Exception as exc:
                log.warning("replace_sales_packing_lines insert failed: %s",
                             exc)
    return {"deleted": int(deleted), "inserted": int(inserted)}


def get_sales_packing_lines(batch_id: str) -> List[Dict[str, Any]]:
    """Return all sales packing lines for a batch."""
    if _db_path is None:
        return []
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM sales_packing_lines WHERE batch_id=? ORDER BY created_at",
            (batch_id,),
        ).fetchall()
    return [dict(r) for r in rows]


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
