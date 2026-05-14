"""
packing_db.py — SQLite store for invoice lines and packing list rows.

Tables:
  packing_documents — one row per uploaded packing list file
  packing_lines     — one row per packing list item, linked to invoice row

Dedup key for packing_lines:
  Primary (pack_sr known):  (packing_document_id, batch_id, invoice_no, pack_sr)
  Fallback:                 (batch_id, invoice_no, invoice_line_position, design_no, bag_id, unit_price)

scan_code column:
  Computed at write time from (product_code, bag_id, pack_sr, design_no) using the
  same algorithm as routes_packing._barcode_value() and warehouse_db.scan_code_for_packing_line().
  Indexed for O(1) lookup.

Thread-safe: connection per call, WAL mode, threading.Lock.
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


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
        _add_column_if_missing(con, "packing_lines", "unit_price_eur", "REAL NOT NULL DEFAULT 0.0")
        _add_column_if_missing(con, "packing_lines", "metal_color",    "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(con, "packing_lines", "quality_string", "TEXT NOT NULL DEFAULT ''")

        # Index for O(1) warehouse scan lookups (added lazily so existing DBs pick it up)
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_pl_scan_code ON packing_lines (scan_code)"
        )


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
    document_id: Optional[str] = None,
) -> str:
    """Insert or update a packing document record. Returns document id."""
    if _db_path is None:
        raise RuntimeError("packing_db not initialised — call init_packing_db() first")
    now = _now_iso()
    with _lock:
        with _connect() as con:
            # If document_id supplied → update existing
            if document_id:
                row = con.execute(
                    "SELECT id FROM packing_documents WHERE id=?", (document_id,)
                ).fetchone()
                if row:
                    con.execute(
                        """UPDATE packing_documents
                           SET invoice_no=?, source_file_path=?, source_file_hash=?,
                               parser_name=?, parser_version=?, extraction_status=?,
                               updated_at=?
                           WHERE id=?""",
                        (invoice_no, source_file_path, source_file_hash,
                         parser_name, parser_version, extraction_status,
                         now, document_id),
                    )
                    return document_id

            # Hash-based dedup: if another record for this batch already has the
            # same file hash, return it without creating a ghost duplicate.
            # This covers rapid re-uploads and retry scenarios where no
            # document_id was threaded through by the caller.
            if source_file_hash:
                dup = con.execute(
                    "SELECT id FROM packing_documents "
                    "WHERE batch_id=? AND source_file_hash=? LIMIT 1",
                    (batch_id, source_file_hash),
                ).fetchone()
                if dup:
                    return dup[0]

            # Otherwise insert new
            doc_id = document_id or str(uuid.uuid4())
            con.execute(
                """INSERT INTO packing_documents
                       (id, batch_id, invoice_no, source_file_path, source_file_hash,
                        parser_name, parser_version, extraction_status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (doc_id, batch_id, invoice_no, source_file_path, source_file_hash,
                 parser_name, parser_version, extraction_status, now, now),
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


# ── Packing lines ─────────────────────────────────────────────────────────────

def upsert_packing_lines(
    lines: List[Dict[str, Any]],
    force_reextract: bool = False,
) -> int:
    """
    Insert packing lines. Skip existing rows unless force_reextract=True.
    Dedup key: (batch_id, invoice_no, invoice_line_position, design_no, bag_id).
    packing_document_id is stored for traceability but is NOT part of the dedup key —
    a re-upload creates a new document but should update the same logical packing row.
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
                    existing = con.execute(
                        """SELECT id FROM packing_lines
                           WHERE batch_id=? AND invoice_no=?
                             AND packing_document_id=? AND pack_sr IS ?
                           LIMIT 1""",
                        (batch_id, inv_no,
                         line.get("packing_document_id", ""), pack_sr),
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
                            created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
