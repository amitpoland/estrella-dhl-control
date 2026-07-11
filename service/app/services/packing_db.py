"""
packing_db.py — SQLite store for invoice lines and packing list rows.

Tables:
  packing_documents — one row per uploaded packing list file
  packing_lines     — one row per packing list item, linked to invoice row

Dedup key for packing_lines:
  Primary (pack_sr known):  (batch_id, invoice_no, pack_sr)
  Fallback:                 (batch_id, invoice_no, invoice_line_position, design_no, bag_id, unit_price)
  packing_document_id is stored for traceability but is NOT part of either key —
  a re-upload registers a new document but must update the same logical row.

scan_code column:
  Computed at write time from (product_code, bag_id, pack_sr, design_no) using the
  same algorithm as routes_packing._barcode_value() and warehouse_db.scan_code_for_packing_line().
  Indexed for O(1) lookup.

Thread-safe: connection per call, WAL mode, threading.Lock.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


_lock = threading.Lock()
_db_path: Optional[Path] = None


# ── scan_code computation (mirrors routes_packing._barcode_value) ─────────────
# Kept here so packing_db can populate the column at write time without
# importing warehouse_db (which imports packing_db — would be circular).

def _compute_scan_code(line: Dict[str, Any]) -> str:
    """
    Compute the canonical scan_code for a packing row.

    Priority:
      1. <product_code>|<bag_id>                 (bag tracking)
      2. <product_code>|sr<pack_sr>|<design_no>  (aggregated invoice)
      3. <product_code>|<design_no>              (no bag, no Sr)
      4. <product_code>                          (last resort)
    """
    pc     = str(line.get("product_code") or "")
    bag    = str(line.get("bag_id") or "")
    sr     = line.get("pack_sr")
    design = str(line.get("design_no") or "")

    if bag:
        return f"{pc}|{bag}"
    if sr is not None and sr != "":
        try:
            sr_str = str(int(sr)) if float(sr).is_integer() else str(sr)
        except (TypeError, ValueError):
            sr_str = str(sr)
        if design:
            return f"{pc}|sr{sr_str}|{design}"
        return f"{pc}|sr{sr_str}"
    if design:
        return f"{pc}|{design}"
    return pc


# ── Init ───────────────────────────────────────────────────────────────────────

def init_packing_db(db_path: Path) -> None:
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as con:
        con.executescript("""
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS packing_documents (
                id                  TEXT PRIMARY KEY,
                batch_id            TEXT NOT NULL,
                invoice_no          TEXT NOT NULL DEFAULT '',
                source_file_path    TEXT NOT NULL DEFAULT '',
                source_file_hash    TEXT NOT NULL DEFAULT '',
                parser_name         TEXT NOT NULL DEFAULT '',
                parser_version      TEXT NOT NULL DEFAULT '',
                extraction_status   TEXT NOT NULL DEFAULT 'pending',
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_pd_batch_id
                ON packing_documents (batch_id);

            CREATE TABLE IF NOT EXISTS packing_lines (
                id                      TEXT PRIMARY KEY,
                packing_document_id     TEXT NOT NULL,
                batch_id                TEXT NOT NULL,
                invoice_no              TEXT NOT NULL DEFAULT '',
                invoice_line_position   INTEGER DEFAULT NULL,
                product_code            TEXT DEFAULT NULL,
                design_no               TEXT NOT NULL DEFAULT '',
                batch_no                TEXT NOT NULL DEFAULT '',
                bag_id                  TEXT NOT NULL DEFAULT '',
                tray_id                 TEXT NOT NULL DEFAULT '',
                item_type               TEXT NOT NULL DEFAULT '',
                uom                     TEXT NOT NULL DEFAULT '',
                quantity                REAL NOT NULL DEFAULT 0.0,
                gross_weight            REAL NOT NULL DEFAULT 0.0,
                net_weight              REAL NOT NULL DEFAULT 0.0,
                metal                   TEXT NOT NULL DEFAULT '',
                karat                   TEXT NOT NULL DEFAULT '',
                stone_type              TEXT NOT NULL DEFAULT '',
                remarks                 TEXT NOT NULL DEFAULT '',
                extracted_confidence    REAL NOT NULL DEFAULT 0.0,
                requires_manual_review  INTEGER NOT NULL DEFAULT 0,
                created_at              TEXT NOT NULL,
                updated_at              TEXT NOT NULL,
                FOREIGN KEY (packing_document_id) REFERENCES packing_documents(id)
            );

            CREATE INDEX IF NOT EXISTS idx_pl_batch_id
                ON packing_lines (batch_id);
            CREATE INDEX IF NOT EXISTS idx_pl_product_code
                ON packing_lines (product_code);
            CREATE INDEX IF NOT EXISTS idx_pl_packing_document_id
                ON packing_lines (packing_document_id);
        """)

        # ── Forward-compat column migrations ────────────────────────────────
        # pack_sr  — packing list source serial (Sr / PkSr column).
        #            Distinguishes two same-design rows from one source list.
        # unit_price / total_value — captured for inventory/value verification.
        # scan_code — pre-computed barcode identity for O(1) warehouse lookup.
        _add_column_if_missing(con, "packing_lines",     "pack_sr",          "REAL DEFAULT NULL")
        _add_column_if_missing(con, "packing_lines",     "unit_price",       "REAL NOT NULL DEFAULT 0.0")
        _add_column_if_missing(con, "packing_lines",     "total_value",      "REAL NOT NULL DEFAULT 0.0")
        _add_column_if_missing(con, "packing_lines",     "scan_code",        "TEXT DEFAULT NULL")
        # source_file_hash — added to packing_documents after initial schema;
        # guard ensures existing DBs pick it up without a manual migration.
        _add_column_if_missing(con, "packing_documents", "source_file_hash", "TEXT NOT NULL DEFAULT ''")
        # PR 2A — product identity enrichment fields.
        # unit_price_eur: client billing price from packing XLSX Value column (EUR
        #   namespace, distinct from unit_price which carries USD supplier rate).
        # metal_color: standalone color code (W/Y/RG/R) from Col or Kt/Color split.
        # quality_string: raw quality/grade string from Quality column including
        #   compound values like "G-VS LAB,E-VVS LAB" and the "Qualtity" typo variant.
        _add_column_if_missing(con, "packing_lines", "unit_price_eur",  "REAL NOT NULL DEFAULT 0.0")
        _add_column_if_missing(con, "packing_lines", "metal_color",     "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(con, "packing_lines", "quality_string",  "TEXT NOT NULL DEFAULT ''")
        # Display fields — extracted by invoice_packing_extractor but previously
        # not stored (silently dropped at upload time). Added 2026-06-09.
        # Re-upload or force_reextract=True populates existing rows.
        _add_column_if_missing(con, "packing_lines", "size",            "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(con, "packing_lines", "diamond_weight",  "REAL NOT NULL DEFAULT 0.0")
        _add_column_if_missing(con, "packing_lines", "color_weight",    "REAL NOT NULL DEFAULT 0.0")

        # P1 parser observability: per-document parser_diagnostic_json column
        # carries the structured diagnostic dict captured by extract_packing.
        # Read-only by callers; writers serialise via json.dumps.
        _add_column_if_missing(con, "packing_documents", "parser_diagnostic_json",
                               "TEXT NOT NULL DEFAULT '{}'")

        # Index for O(1) warehouse scan lookups (added lazily so existing DBs pick it up)
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_pl_scan_code ON packing_lines (scan_code)"
        )

        # Supplier header templates — Tier 0 operator-approved column mappings.
        # Keyed by (supplier_id, doc_type, raw_header); UNIQUE prevents duplicates.
        con.executescript("""
            CREATE TABLE IF NOT EXISTS supplier_header_templates (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_id     INTEGER NOT NULL,
                doc_type        TEXT    NOT NULL DEFAULT 'purchase_packing_list',
                raw_header      TEXT    NOT NULL,
                canonical_field TEXT    NOT NULL,
                col_index       INTEGER,
                approved_by     TEXT    NOT NULL DEFAULT 'operator',
                approved_at     TEXT    NOT NULL,
                UNIQUE(supplier_id, doc_type, raw_header)
            );
            CREATE INDEX IF NOT EXISTS idx_sht_supplier
                ON supplier_header_templates (supplier_id, doc_type);
        """)

        # Audit columns added after initial release — safe via _add_column_if_missing.
        _add_column_if_missing(
            con, "supplier_header_templates", "source_method",
            "TEXT NOT NULL DEFAULT 'operator_approved'",
        )

        # supplier_id on packing_documents links the document to its Supplier Master row.
        _add_column_if_missing(con, "packing_documents", "supplier_id", "INTEGER")


def _add_column_if_missing(con: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(_db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Packing documents ─────────────────────────────────────────────────────────

def upsert_packing_document(
    *,
    batch_id: str,
    invoice_no: str = "",
    source_file_path: str = "",
    source_file_hash: str = "",
    parser_name: str = "",
    parser_version: str = "",
    extraction_status: str = "pending",
    parser_diagnostic: Optional[Dict[str, Any]] = None,
    document_id: Optional[str] = None,
    supplier_id: Optional[int] = None,
) -> str:
    """Insert or update a packing document record. Returns document id.

    `parser_diagnostic` (P1 observability) is JSON-serialised into the
    parser_diagnostic_json column. Passing None preserves any prior value
    on UPDATE and writes '{}' on INSERT.
    """
    if _db_path is None:
        raise RuntimeError("packing_db not initialised — call init_packing_db() first")
    now = _now_iso()
    diag_json: Optional[str]
    if parser_diagnostic is None:
        diag_json = None
    else:
        try:
            diag_json = json.dumps(parser_diagnostic, ensure_ascii=False)
        except Exception as exc:
            log.warning("parser_diagnostic JSON serialise failed (non-fatal): %s", exc)
            diag_json = "{}"
    with _lock:
        with _connect() as con:
            # If document_id supplied → update existing
            if document_id:
                row = con.execute(
                    "SELECT id FROM packing_documents WHERE id=?", (document_id,)
                ).fetchone()
                if row:
                    if diag_json is None:
                        con.execute(
                            """UPDATE packing_documents
                               SET invoice_no=?, source_file_path=?, source_file_hash=?,
                                   parser_name=?, parser_version=?, extraction_status=?,
                                   supplier_id=COALESCE(?, supplier_id),
                                   updated_at=?
                               WHERE id=?""",
                            (invoice_no, source_file_path, source_file_hash,
                             parser_name, parser_version, extraction_status,
                             supplier_id, now, document_id),
                        )
                    else:
                        con.execute(
                            """UPDATE packing_documents
                               SET invoice_no=?, source_file_path=?, source_file_hash=?,
                                   parser_name=?, parser_version=?, extraction_status=?,
                                   parser_diagnostic_json=?,
                                   supplier_id=COALESCE(?, supplier_id),
                                   updated_at=?
                               WHERE id=?""",
                            (invoice_no, source_file_path, source_file_hash,
                             parser_name, parser_version, extraction_status,
                             diag_json, supplier_id, now, document_id),
                        )
                    return document_id

            # Hash-based dedup: if another record for this batch already has the
            # same file hash, return it without creating a ghost duplicate.
            if source_file_hash:
                dup = con.execute(
                    "SELECT id FROM packing_documents "
                    "WHERE batch_id=? AND source_file_hash=? LIMIT 1",
                    (batch_id, source_file_hash),
                ).fetchone()
                if dup:
                    # Update diagnostic on the deduped row so the latest
                    # parser pass is visible to operators.
                    if diag_json is not None:
                        con.execute(
                            """UPDATE packing_documents
                               SET parser_diagnostic_json=?, updated_at=?
                               WHERE id=?""",
                            (diag_json, now, dup[0]),
                        )
                    return dup[0]

            # Otherwise insert new
            doc_id = document_id or str(uuid.uuid4())
            con.execute(
                """INSERT INTO packing_documents
                       (id, batch_id, invoice_no, source_file_path, source_file_hash,
                        parser_name, parser_version, extraction_status,
                        parser_diagnostic_json, supplier_id, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (doc_id, batch_id, invoice_no, source_file_path, source_file_hash,
                 parser_name, parser_version, extraction_status,
                 diag_json or "{}", supplier_id, now, now),
            )
            return doc_id


def get_packing_document(document_id: str) -> Optional[Dict[str, Any]]:
    if _db_path is None:
        return None
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM packing_documents WHERE id=?", (document_id,)
        ).fetchone()
    return dict(row) if row else None


def get_packing_documents_for_batch(batch_id: str) -> List[Dict[str, Any]]:
    if _db_path is None:
        return []
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM packing_documents WHERE batch_id=? ORDER BY created_at DESC",
            (batch_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _resolve_packing_document_ids(
    batch_id:         str,
    source_file_hash: str = "",
    file_name:        str = "",
) -> List[str]:
    """Resolve the packing_documents.id(s) for a shipment_documents row.

    A Document Registry row is a ``shipment_documents`` row (documents.db) — its
    packing list lines live in this DB (packing.db), keyed by
    ``packing_lines.packing_document_id`` → ``packing_documents.id``, a DIFFERENT
    id space. The bridge is the source file: a ``packing_documents`` row carries
    the same ``source_file_hash`` (== ``shipment_documents.file_hash``) and the
    same basename (== ``shipment_documents.file_name``) as its registry row.

    Resolution order (read-only):
      1. (batch_id, source_file_hash) — the canonical, content-addressed join.
      2. (batch_id, basename(source_file_path) == file_name) — fallback for any
         legacy row whose hash is absent or did not match.

    Returns every matching id (a re-upload can mint a second packing_documents
    row for the same file within a batch), so callers union their lines.
    """
    if _db_path is None or not batch_id:
        return []
    with _connect() as con:
        ids: List[str] = []
        if source_file_hash:
            ids = [
                r["id"] for r in con.execute(
                    "SELECT id FROM packing_documents "
                    "WHERE batch_id=? AND source_file_hash=?",
                    (batch_id, source_file_hash),
                ).fetchall()
            ]
        if not ids and file_name:
            rows = con.execute(
                "SELECT id, source_file_path FROM packing_documents WHERE batch_id=?",
                (batch_id,),
            ).fetchall()
            ids = [
                r["id"] for r in rows
                if Path(r["source_file_path"] or "").name == file_name
            ]
    return ids


def get_packing_lines_for_shipment_document(
    batch_id:         str,
    source_file_hash: str = "",
    file_name:        str = "",
    limit:            int = 50,
) -> List[Dict[str, Any]]:
    """Return packing_lines belonging to a single shipment_documents (registry) row.

    Distinct from ``get_packing_lines_for_document(packing_document_id)`` above:
    that one is keyed by a packing_documents.id (this DB's own id space); this one
    is keyed by a shipment_documents row's identity (batch_id + file_hash/file_name)
    and bridges documents.db → packing.db via ``_resolve_packing_document_ids``.

    purchase_packing_list extraction writes to packing_lines (packing.db, keyed
    by packing_document_id → packing_documents), NOT to documents.db
    invoice_lines / document_extracted_fields — so the Document Registry rendered
    "Lines/Fields: 0" for purchase_packing_list rows even when lines existed.
    Mirrors ``document_db.get_invoice_lines_for_document`` / the sales helper.

    Read-only; capped at ``limit`` rows for payload safety.
    """
    pdoc_ids = _resolve_packing_document_ids(batch_id, source_file_hash, file_name)
    if not pdoc_ids:
        return []
    placeholders = ",".join("?" * len(pdoc_ids))
    with _connect() as con:
        rows = con.execute(
            f"SELECT * FROM packing_lines "
            f"WHERE packing_document_id IN ({placeholders}) "
            f"ORDER BY invoice_line_position, created_at, id LIMIT ?",
            (*pdoc_ids, int(limit)),
        ).fetchall()
    return [dict(r) for r in rows]


def count_packing_lines_for_shipment_document(
    batch_id:         str,
    source_file_hash: str = "",
    file_name:        str = "",
) -> int:
    """Count packing_lines for a single shipment_documents (registry) row (no preview).

    Same two-DB bridge as ``get_packing_lines_for_shipment_document`` — see
    ``_resolve_packing_document_ids``. Read-only.
    """
    pdoc_ids = _resolve_packing_document_ids(batch_id, source_file_hash, file_name)
    if not pdoc_ids:
        return 0
    placeholders = ",".join("?" * len(pdoc_ids))
    with _connect() as con:
        row = con.execute(
            f"SELECT COUNT(*) AS n FROM packing_lines "
            f"WHERE packing_document_id IN ({placeholders})",
            tuple(pdoc_ids),
        ).fetchone()
    return int(row["n"] if row else 0)


def get_packing_status_for_shipment_document(
    batch_id:         str,
    source_file_hash: str = "",
    file_name:        str = "",
) -> str:
    """Return the authoritative packing extraction_status for a registry row.

    The Document Registry row is a ``shipment_documents`` row (documents.db),
    whose ``extraction_status`` for purchase packing lists was historically
    never written back from the packing pipeline. The real status lives here in
    packing.db / ``packing_documents``. This bridges the same way as
    ``count_packing_lines_for_shipment_document`` (via
    ``_resolve_packing_document_ids``) and returns the packing-side status so
    the registry can stop showing a stale 'pending'.

    Aggregation across re-uploaded duplicates: 'complete' if ANY resolved
    packing_documents row is complete; else 'empty' if all are empty; else the
    first non-empty status; '' when no packing_documents row exists. Read-only.
    """
    pdoc_ids = _resolve_packing_document_ids(batch_id, source_file_hash, file_name)
    if not pdoc_ids:
        return ""
    placeholders = ",".join("?" * len(pdoc_ids))
    with _connect() as con:
        rows = con.execute(
            f"SELECT extraction_status FROM packing_documents "
            f"WHERE id IN ({placeholders})",
            tuple(pdoc_ids),
        ).fetchall()
    statuses = [str((r["extraction_status"] or "")).strip().lower() for r in rows]
    if not statuses:
        return ""
    if "complete" in statuses:
        return "complete"
    non_empty = [s for s in statuses if s and s != "empty"]
    if non_empty:
        return non_empty[0]
    return "empty"


def update_packing_document_diagnostic(document_id: str, diagnostic: Dict[str, Any]) -> bool:
    """Update ONLY parser_diagnostic_json for one packing document.

    Returns True when a row was updated, False when document_id not found.
    Does NOT touch extraction_status, rows, or any other column.
    """
    if _db_path is None:
        return False
    now = _now_iso()
    try:
        diag_json = json.dumps(diagnostic, ensure_ascii=False)
    except Exception as exc:
        log.warning("update_packing_document_diagnostic JSON serialise failed: %s", exc)
        return False
    with _lock:
        with _connect() as con:
            cur = con.execute(
                """UPDATE packing_documents
                   SET parser_diagnostic_json=?, updated_at=?
                   WHERE id=?""",
                (diag_json, now, document_id),
            )
    return (cur.rowcount or 0) > 0


def delete_packing_document_and_lines(doc_id: str) -> Dict[str, Any]:
    """Atomically delete one packing document and all its extracted lines.

    Deletes packing_lines WHERE packing_document_id = doc_id, then deletes
    the packing_documents row itself.  Both deletes occur inside a single
    transaction so the DB is never left in a half-deleted state.

    Returns:
        {'doc_id': str, 'deleted_lines': int, 'source_file_path': str}

    Raises:
        RuntimeError  — packing_db not initialised
        KeyError      — doc_id does not exist in packing_documents
    """
    if _db_path is None:
        raise RuntimeError("packing_db not initialised — call init_packing_db() first")
    with _lock:
        with _connect() as con:
            row = con.execute(
                "SELECT source_file_path FROM packing_documents WHERE id=?",
                (doc_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"packing document {doc_id!r} not found")
            source_file_path: str = row["source_file_path"] or ""
            cur = con.execute(
                "DELETE FROM packing_lines WHERE packing_document_id=?",
                (doc_id,),
            )
            deleted_lines: int = cur.rowcount or 0
            con.execute("DELETE FROM packing_documents WHERE id=?", (doc_id,))
    return {
        "doc_id":           doc_id,
        "deleted_lines":    deleted_lines,
        "source_file_path": source_file_path,
    }


# ── Supplier header templates (Tier 0) ───────────────────────────────────────

def get_supplier_templates(
    supplier_id: int,
    doc_type: str = "purchase_packing_list",
) -> List[Dict[str, Any]]:
    """Return all operator-approved header templates for a supplier + doc_type.

    Returns a list of dicts with keys: id, supplier_id, doc_type, raw_header,
    canonical_field, col_index, approved_by, approved_at.
    Returns [] when the DB is uninitialised or no templates exist.
    """
    if _db_path is None:
        return []
    with _connect() as con:
        rows = con.execute(
            """SELECT * FROM supplier_header_templates
               WHERE supplier_id=? AND doc_type=?
               ORDER BY raw_header""",
            (supplier_id, doc_type),
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_supplier_template(
    *,
    supplier_id: int,
    doc_type: str = "purchase_packing_list",
    raw_header: str,
    canonical_field: str,
    col_index: Optional[int] = None,
    approved_by: str = "operator",
    source_method: str = "operator_approved",
) -> int:
    """Insert or replace a supplier header template.

    Uses INSERT OR REPLACE so re-approval of the same raw_header updates
    canonical_field, approved_by, approved_at, and source_method in place.
    source_method records which tier produced the original suggestion
    (alias / fuzzy / fuzzy_warning / llm / operator_approved).
    Returns the row id.
    """
    if _db_path is None:
        raise RuntimeError("packing_db not initialised")
    now = _now_iso()
    with _lock:
        with _connect() as con:
            cur = con.execute(
                """INSERT INTO supplier_header_templates
                       (supplier_id, doc_type, raw_header, canonical_field,
                        col_index, approved_by, approved_at, source_method)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(supplier_id, doc_type, raw_header)
                   DO UPDATE SET
                       canonical_field = excluded.canonical_field,
                       col_index       = excluded.col_index,
                       approved_by     = excluded.approved_by,
                       approved_at     = excluded.approved_at,
                       source_method   = excluded.source_method""",
                (supplier_id, doc_type, raw_header, canonical_field,
                 col_index, approved_by, now, source_method),
            )
            return cur.lastrowid or con.execute(
                """SELECT id FROM supplier_header_templates
                   WHERE supplier_id=? AND doc_type=? AND raw_header=?""",
                (supplier_id, doc_type, raw_header),
            ).fetchone()[0]


def delete_supplier_template(template_id: int) -> bool:
    """Delete a single supplier header template by id. Returns True if deleted."""
    if _db_path is None:
        return False
    with _lock:
        with _connect() as con:
            cur = con.execute(
                "DELETE FROM supplier_header_templates WHERE id=?", (template_id,)
            )
    return (cur.rowcount or 0) > 0


# ── Packing lines ─────────────────────────────────────────────────────────────

def upsert_packing_lines(
    lines: List[Dict[str, Any]],
    force_reextract: bool = False,
) -> int:
    """
    Insert packing lines. Skip existing rows unless force_reextract=True.
    Dedup key:
      Primary (pack_sr known):  (batch_id, invoice_no, pack_sr)
      Fallback (pack_sr None):  (batch_id, invoice_no, invoice_line_position, design_no, bag_id, unit_price)
    packing_document_id is stored for traceability but is NOT part of either key —
    a re-upload registers a new document but should update the same logical packing row.
    Returns count of rows inserted or updated.
    """
    if _db_path is None:
        return 0
    inserted = 0
    now = _now_iso()
    with _lock:
        with _connect() as con:
            for line in lines:
                batch_id  = line.get("batch_id", "")
                inv_no    = line.get("invoice_no", "")
                inv_pos   = line.get("invoice_line_position")
                design_no = line.get("design_no", "")
                bag_id    = line.get("bag_id", "")
                pack_sr   = line.get("pack_sr")           # source-list serial
                unit_price= float(line.get("unit_price", 0) or 0)

                # ── Primary dedup ────────────────────────────────────────
                # Each row in the source packing list is a DISTINCT physical
                # inventory line. The strongest unique signal is the source
                # serial (Sr / PkSr column). When that's available, use it.
                # Otherwise fall back to (design_no, bag_id, unit_price) so
                # two same-design rows priced differently aren't collapsed.
                if pack_sr is not None:
                    # packing_document_id is deliberately NOT in this key (see
                    # docstring): a re-upload registers a NEW document id, so
                    # filtering on it made the lookup miss and every pack_sr
                    # row duplicated on same-batch re-upload.
                    existing = con.execute(
                        """SELECT id FROM packing_lines
                           WHERE batch_id=? AND invoice_no=?
                             AND pack_sr IS ?
                           LIMIT 1""",
                        (batch_id, inv_no, pack_sr),
                    ).fetchone()
                else:
                    existing = con.execute(
                        """SELECT id FROM packing_lines
                           WHERE batch_id=? AND invoice_no=?
                             AND invoice_line_position IS ?
                             AND design_no=? AND bag_id=?
                             AND unit_price=?
                           LIMIT 1""",
                        (batch_id, inv_no, inv_pos, design_no, bag_id,
                         unit_price),
                    ).fetchone()

                # Secondary dedup: same position + same bag_id, design_no may differ.
                # Covers two cases:
                # 1. force_reextract=False: skip re-insertion when design_no was re-extracted
                #    differently but bag is identical (same physical item, OCR variance)
                # 2. force_reextract=True: find the row to update even when design_no changes
                # Different bag_id at the same position = distinct physical item → always insert.
                #
                # IMPORTANT: only fire this secondary check when bag_id is actually
                # populated. Empty bag_id means the packing list doesn't track physical
                # bags, so design_no IS the unique identifier. Without this guard,
                # aggregate (N:1) matches collapse to a single row per invoice line.
                if existing is None and bag_id:
                    existing = con.execute(
                        """SELECT id FROM packing_lines
                           WHERE batch_id=? AND invoice_no=?
                             AND invoice_line_position IS ?
                             AND bag_id=?
                           LIMIT 1""",
                        (batch_id, inv_no, inv_pos, bag_id),
                    ).fetchone()

                # force_reextract: if still no match (bag_id also changed), widen to position only
                if existing is None and force_reextract:
                    existing = con.execute(
                        """SELECT id FROM packing_lines
                           WHERE batch_id=? AND invoice_no=?
                             AND invoice_line_position IS ?
                           LIMIT 1""",
                        (batch_id, inv_no, inv_pos),
                    ).fetchone()

                if existing and not force_reextract:
                    continue

                scan_code = _compute_scan_code(line)

                if existing and force_reextract:
                    con.execute(
                        """UPDATE packing_lines SET
                               packing_document_id=?, design_no=?, bag_id=?,
                               product_code=?, batch_no=?, tray_id=?,
                               item_type=?, uom=?, quantity=?, gross_weight=?, net_weight=?,
                               metal=?, karat=?, stone_type=?, remarks=?,
                               extracted_confidence=?, requires_manual_review=?,
                               scan_code=?,
                               unit_price_eur=?, metal_color=?, quality_string=?,
                               size=?, diamond_weight=?, color_weight=?,
                               updated_at=?
                           WHERE id=?""",
                        (
                            line.get("packing_document_id", ""),
                            line.get("design_no", ""),
                            line.get("bag_id", ""),
                            line.get("product_code"),
                            line.get("batch_no", ""),
                            line.get("tray_id", ""),
                            line.get("item_type", ""),
                            line.get("uom", ""),
                            float(line.get("quantity", 0)),
                            float(line.get("gross_weight", 0)),
                            float(line.get("net_weight", 0)),
                            line.get("metal", ""),
                            line.get("karat", ""),
                            line.get("stone_type", ""),
                            line.get("remarks", ""),
                            float(line.get("extracted_confidence", 0)),
                            1 if line.get("requires_manual_review") else 0,
                            scan_code or None,
                            float(line.get("unit_price_eur", 0) or 0),
                            str(line.get("metal_color", "") or ""),
                            str(line.get("quality_string", "") or ""),
                            str(line.get("size", "") or ""),
                            float(line.get("diamond_weight", 0) or 0),
                            float(line.get("color_weight", 0) or 0),
                            now,
                            existing["id"],
                        ),
                    )
                    inserted += 1
                    continue

                line_id = str(uuid.uuid4())
                con.execute(
                    """INSERT INTO packing_lines
                           (id, packing_document_id, batch_id, invoice_no, invoice_line_position,
                            product_code, design_no, batch_no, bag_id, tray_id,
                            item_type, uom, quantity, gross_weight, net_weight,
                            metal, karat, stone_type, remarks,
                            extracted_confidence, requires_manual_review,
                            pack_sr, unit_price, total_value, scan_code,
                            unit_price_eur, metal_color, quality_string,
                            size, diamond_weight, color_weight,
                            created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        line_id, line.get("packing_document_id", ""),
                        batch_id,
                        inv_no, inv_pos,
                        line.get("product_code"),
                        design_no,
                        line.get("batch_no", ""),
                        bag_id,
                        line.get("tray_id", ""),
                        line.get("item_type", ""),
                        line.get("uom", ""),
                        float(line.get("quantity", 0)),
                        float(line.get("gross_weight", 0)),
                        float(line.get("net_weight", 0)),
                        line.get("metal", ""),
                        line.get("karat", ""),
                        line.get("stone_type", ""),
                        line.get("remarks", ""),
                        float(line.get("extracted_confidence", 0)),
                        1 if line.get("requires_manual_review") else 0,
                        pack_sr,
                        unit_price,
                        float(line.get("total_value", 0) or 0),
                        scan_code or None,
                        float(line.get("unit_price_eur", 0) or 0),
                        str(line.get("metal_color", "") or ""),
                        str(line.get("quality_string", "") or ""),
                        str(line.get("size", "") or ""),
                        float(line.get("diamond_weight", 0) or 0),
                        float(line.get("color_weight", 0) or 0),
                        now, now,
                    ),
                )
                inserted += 1
    return inserted


def get_line_counts_for_batch(batch_id: str) -> Dict[str, int]:
    """
    Return ``{packing_document_id: line_count}`` for all documents in *batch_id*.

    Documents with no lines are absent from the result — callers should use
    ``.get(doc_id, 0)``.  Used by the packing-documents endpoint to surface
    real extracted-line counts so operators can identify which document in a
    duplicate group has actual data.
    """
    if _db_path is None:
        return {}
    with _connect() as con:
        rows = con.execute(
            "SELECT packing_document_id, COUNT(*) AS cnt "
            "FROM packing_lines WHERE batch_id=? "
            "GROUP BY packing_document_id",
            (batch_id,),
        ).fetchall()
    return {r[0]: r[1] for r in rows}


def backfill_unit_price_eur(batch_id: str, line_records: List[Dict[str, Any]]) -> int:
    """
    Update unit_price_eur for packing_lines rows where the current value is 0
    and the supplied line_record has unit_price_eur > 0.

    Matching strategy:
      1. pack_sr  → (batch_id, invoice_no, pack_sr)
      2. fallback → (batch_id, invoice_no, invoice_line_position, design_no)

    packing_document_id is stored for traceability but is NOT part of either
    match key. The reprocess-prices caller does not upsert a document, so it
    passes an empty packing_document_id, while real stored rows carry a UUID.
    Scoping the pack_sr lookup by packing_document_id therefore never matched
    a stored row and silently backfilled nothing. The canonical key is
    (batch_id, invoice_no, pack_sr) — same contract as upsert_packing_lines.

    Returns the number of rows actually updated.
    Used to recover prices after PR 2A migration when packing was uploaded
    before the unit_price_eur column was added.
    """
    if _db_path is None:
        return 0
    updated = 0
    now = _now_iso()
    with _lock:
        with _connect() as con:
            for line in line_records:
                upe = float(line.get("unit_price_eur", 0) or 0)
                if upe <= 0:
                    continue  # nothing to backfill for this row
                batch     = line.get("batch_id", "")
                inv_no    = line.get("invoice_no", "")
                inv_pos   = line.get("invoice_line_position")
                design_no = line.get("design_no", "")
                pack_sr   = line.get("pack_sr")

                if pack_sr is not None:
                    # packing_document_id is deliberately NOT in this key: the
                    # reprocess-prices caller passes an empty doc id while stored
                    # rows carry a UUID, so filtering on it never matched and the
                    # backfill silently updated nothing.
                    row = con.execute(
                        """SELECT id, unit_price_eur FROM packing_lines
                           WHERE batch_id=? AND invoice_no=?
                             AND pack_sr IS ?
                           LIMIT 1""",
                        (batch, inv_no, pack_sr),
                    ).fetchone()
                else:
                    row = con.execute(
                        """SELECT id, unit_price_eur FROM packing_lines
                           WHERE batch_id=? AND invoice_no=?
                             AND invoice_line_position IS ?
                             AND design_no=?
                           LIMIT 1""",
                        (batch, inv_no, inv_pos, design_no),
                    ).fetchone()

                if row is None:
                    continue
                if float(row["unit_price_eur"] or 0) > 0:
                    continue  # already has a price — do not overwrite
                con.execute(
                    "UPDATE packing_lines SET unit_price_eur=?, updated_at=? WHERE id=?",
                    (upe, now, row["id"]),
                )
                updated += 1
    return updated


# ── Document-scoped price-reprocess resolver (canary-hardened) ──────────────
#
# The reprocess-prices route re-parses source packing files to recover
# unit_price_eur. Global-Jewellery parsed rows carry NO pack_sr — the parser
# emits a deterministic document-local ``line_position`` and pack_sr is stamped
# at INTAKE from that line_position (routes_intake.py / routes_packing.py
# upload: ``"pack_sr": r.get("line_position")``). Matching on
# (batch_id, invoice_no, pack_sr) therefore (a) missed every such row (pack_sr
# None → fallback) and (b) conflated the Client .xlsx and Poland .xls variants
# of one invoice, which are DIFFERENT registered packing_documents. A stopped
# 2026-07-11 canary proved the fallback (batch, invoice, invoice_line_position,
# design_no) is ambiguous (invoice 235: pack_sr 4 and 5 share ilp+design, prices
# 372 vs 458). The canonical, already-stored, unique reprocess identity is
# (packing_document_id, pack_sr := pack_sr or line_position). This resolver maps
# every positive-price source row to EXACTLY one stored row under that key,
# rejects 0/multi matches, and never uses LIMIT 1 to hide ambiguity. It writes
# nothing. ``backfill_unit_price_eur`` (the direct (batch,invoice,pack_sr)
# caller contract, PR #890) is intentionally left unchanged.

def _bridged_pack_sr(row: Dict[str, Any]):
    """Canonical serial for a parsed source row: pack_sr if the caller supplied
    one, else the parser's deterministic document-local ``line_position`` — the
    exact field INTAKE stamps into pack_sr. Returns a float or None."""
    ps = row.get("pack_sr")
    if ps is None:
        ps = row.get("line_position")
    try:
        return None if ps is None else float(ps)
    except (TypeError, ValueError):
        return None


def resolve_price_reprocess_targets(
    batch_id:     str,
    source_files: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Read-only preflight for the reprocess-prices route. Performs NO writes.

    ``source_files`` — one entry per re-parsed packing file (positive-price rows
    only)::

        { "file_name": str, "source_file_hash": str,
          "rows": [ {"pack_sr": ..., "line_position": ..., "unit_price": float}, ... ] }

    Each file is resolved to its packing_document via the existing
    content-addressed bridge (``_resolve_packing_document_ids`` →
    source_file_hash). A file whose hash resolves to 0 or >1 documents is
    rejected (invalid) — never guessed, never chosen by sort order. Each
    positive-price row is then resolved to the ONE stored packing row under the
    canonical identity (batch_id, packing_document_id, pack_sr:=pack_sr or
    line_position). Within a *serial* document (one that has stored pack_sr rows)
    every row must resolve to exactly one row; a *non-serial* document
    (invoice-total rows, no stored pack_sr) yields ``non_target`` rows that do
    not block. Returns a classification; ``blocking`` is True iff any invalid,
    ambiguous, or unmatched-within-a-serial-document row exists.
    """
    out: Dict[str, Any] = {
        "targets": [], "already_priced": [], "non_target": [],
        "unmatched": [], "ambiguous": [], "invalid": [],
        "files_scanned": len(source_files),
        "parsed_positive_price_records": 0,
    }
    if _db_path is None or not batch_id:
        out["invalid"].append({"reason": "packing_db_unavailable"})
        out["blocking"] = True
        return out
    with _connect() as con:
        for sf in source_files:
            fname = sf.get("file_name", "")
            fhash = sf.get("source_file_hash", "")
            rows  = sf.get("rows", []) or []
            out["parsed_positive_price_records"] += len(rows)
            doc_ids = _resolve_packing_document_ids(batch_id, fhash, fname)
            if len(doc_ids) != 1:
                reason = "unknown_document_hash" if not doc_ids else "multiply_registered_document"
                for _r in rows:
                    out["invalid"].append({"file": fname, "reason": reason,
                                           "doc_matches": len(doc_ids)})
                continue
            doc_id = doc_ids[0]
            doc_is_serial = con.execute(
                "SELECT 1 FROM packing_lines WHERE batch_id=? AND packing_document_id=? "
                "AND pack_sr IS NOT NULL LIMIT 1",
                (batch_id, doc_id),
            ).fetchone() is not None
            for r in rows:
                ps    = _bridged_pack_sr(r)
                price = float(r.get("unit_price", 0) or 0)
                base  = {"file": fname, "packing_document_id": doc_id,
                         "pack_sr": ps, "unit_price": price}
                if ps is None:
                    out["invalid"].append({**base, "reason": "no_pack_sr_or_line_position"})
                    continue
                matches = con.execute(
                    "SELECT id, unit_price_eur FROM packing_lines "
                    "WHERE batch_id=? AND packing_document_id=? AND pack_sr IS ?",
                    (batch_id, doc_id, ps),
                ).fetchall()
                if len(matches) > 1:
                    out["ambiguous"].append({**base, "match_count": len(matches)})
                elif not matches:
                    if doc_is_serial:
                        out["unmatched"].append({**base, "reason": "no_serial_row_in_serial_document"})
                    else:
                        out["non_target"].append({**base, "reason": "non_serial_document"})
                else:
                    m   = matches[0]
                    cur = float(m["unit_price_eur"] or 0)
                    tgt = {**base, "row_id": m["id"], "current_unit_price_eur": cur}
                    (out["already_priced"] if cur > 0 else out["targets"]).append(tgt)
    out["blocking"] = bool(out["invalid"] or out["ambiguous"] or out["unmatched"])
    return out


def apply_price_reprocess_targets(
    batch_id: str,
    targets:  List[Dict[str, Any]],
) -> int:
    """Transactionally set unit_price_eur (+updated_at) for the resolved targets.

    ALL-OR-NOTHING under one transaction: each target is updated by its stored
    row id, guarded so only rows whose current unit_price_eur is still <= 0 are
    written (idempotent, race-safe). ONLY unit_price_eur and updated_at change.
    Raises ValueError (rolling the whole transaction back) if the number of rows
    actually updated differs from the number of eligible targets, so a
    partial/racey result never commits. Callers MUST have confirmed
    ``resolve_price_reprocess_targets`` is not blocking first.
    """
    if _db_path is None or not targets:
        return 0
    now = _now_iso()
    eligible = [t for t in targets
                if float(t.get("unit_price", 0) or 0) > 0 and t.get("row_id")]
    with _lock:
        with _connect() as con:
            updated = 0
            for t in eligible:
                updated += con.execute(
                    "UPDATE packing_lines SET unit_price_eur=?, updated_at=? "
                    "WHERE id=? AND batch_id=? "
                    "AND (unit_price_eur IS NULL OR unit_price_eur<=0)",
                    (float(t["unit_price"]), now, t["row_id"], batch_id),
                ).rowcount
            if updated != len(eligible):
                # roll back the whole operation — never commit a partial recovery
                raise ValueError(
                    f"reprocess update-count mismatch: updated={updated} "
                    f"eligible={len(eligible)} (rolled back)"
                )
    return updated


def get_packing_lines_for_batch(batch_id: str) -> List[Dict[str, Any]]:
    if _db_path is None:
        return []
    with _connect() as con:
        rows = con.execute(
            """SELECT * FROM packing_lines WHERE batch_id=?
               ORDER BY invoice_no, invoice_line_position""",
            (batch_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_packing_lines_for_document(packing_document_id: str) -> List[Dict[str, Any]]:
    if _db_path is None:
        return []
    with _connect() as con:
        rows = con.execute(
            """SELECT * FROM packing_lines WHERE packing_document_id=?
               ORDER BY invoice_no, invoice_line_position""",
            (packing_document_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_packing_enrichment_for_batch(batch_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Return packing enrichment data keyed by product_code for a batch.

    Returns List[dict] per product_code to support multi-bag reality:
    one invoice line can span multiple bags (BAG-01 qty=2, BAG-02 qty=3).
    Returning only one row would silently drop bags and break barcode printing
    and warehouse traceability.

    Only includes rows that were matched (product_code IS NOT NULL).
    Unmatched rows are excluded — they have no stable key to join on.

    Shape:
      {
        "EJL/26-27/100-1": [
          {"design_no": "D-001", "batch_no": "LOT-A", "bag_id": "BAG-01",
           "tray_id": "", "quantity": 2.0, "gross_weight": 10.0,
           "net_weight": 9.5, "requires_manual_review": 0},
          {"design_no": "D-001", "batch_no": "LOT-A", "bag_id": "BAG-02",
           "tray_id": "", "quantity": 3.0, "gross_weight": 15.0,
           "net_weight": 14.0, "requires_manual_review": 0},
        ],
        "EJL/26-27/100-2": [
          {...}
        ],
        ...
      }

    Usage: bags = enrichment.get(product_code, [])  # [] if no packing data
    """
    if _db_path is None:
        return {}
    with _connect() as con:
        rows = con.execute(
            """SELECT product_code, design_no, batch_no, bag_id, tray_id,
                      quantity, gross_weight, net_weight, requires_manual_review
               FROM packing_lines
               WHERE batch_id=? AND product_code IS NOT NULL
               ORDER BY invoice_no, invoice_line_position, bag_id""",
            (batch_id,),
        ).fetchall()
    enrichment: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        pc = r["product_code"]
        enrichment.setdefault(pc, []).append({
            "design_no":              r["design_no"] or "",
            "batch_no":               r["batch_no"] or "",
            "bag_id":                 r["bag_id"] or "",
            "tray_id":                r["tray_id"] or "",
            "quantity":               r["quantity"],
            "gross_weight":           r["gross_weight"],
            "net_weight":             r["net_weight"],
            "requires_manual_review": r["requires_manual_review"],
        })
    return enrichment


def get_packing_line_by_product_code(product_code: str) -> Optional[Dict[str, Any]]:
    if _db_path is None:
        return None
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM packing_lines WHERE product_code=? LIMIT 1",
            (product_code,),
        ).fetchone()
    return dict(row) if row else None


def get_packing_line_by_scan_code(
    scan_code: str,
    batch_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    O(1) lookup by pre-computed scan_code column.

    If *batch_id* is provided the lookup is scoped to that batch — required
    when the same scan_code appears across multiple batches (e.g. test datasets
    or recurring shipment line references without pack_sr).  Falls back to the
    unscoped query when batch_id is absent so existing callers are unaffected.

    Returns None if:
    - DB not initialised
    - scan_code not found (unknown item)
    - scan_code column is NULL (legacy row — caller should fall back to candidate scan)
    """
    if _db_path is None or not scan_code:
        return None
    with _connect() as con:
        if batch_id:
            row = con.execute(
                "SELECT * FROM packing_lines WHERE scan_code=? AND batch_id=? LIMIT 1",
                (scan_code, batch_id),
            ).fetchone()
            # If not found in the requested batch, do NOT fall back to other batches
            return dict(row) if row else None
        row = con.execute(
            "SELECT * FROM packing_lines WHERE scan_code=? LIMIT 1",
            (scan_code,),
        ).fetchone()
    return dict(row) if row else None


def backfill_scan_codes() -> int:
    """
    Populate scan_code for any existing rows where it is NULL.
    Safe to call multiple times (idempotent). Returns count updated.
    """
    if _db_path is None:
        return 0
    updated = 0
    with _lock:
        with _connect() as con:
            rows = con.execute(
                "SELECT id, product_code, bag_id, pack_sr, design_no "
                "FROM packing_lines WHERE scan_code IS NULL"
            ).fetchall()
            for row in rows:
                sc = _compute_scan_code(dict(row))
                if sc:
                    con.execute(
                        "UPDATE packing_lines SET scan_code=? WHERE id=?",
                        (sc, row["id"]),
                    )
                    updated += 1
    return updated
