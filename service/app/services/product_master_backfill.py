"""product_master_backfill.py — One-shot historical projection of
invoice_lines.product_code into reservation_db.product_master.

Activates the canonical product identity registry (PR #193) for
historical batches whose invoice intake happened before the projection
hook was deployed.  All future intakes already write product_master
inline via store_invoice_lines; this module covers the legacy gap.

Architecture rules:
  * invoice_lines is the ONLY source.  product_code is never invented.
  * Reuses reservation_db.upsert_product_master (PR #193 helper).
    Preserve-on-blank semantics protect existing master rows from
    being overwritten with empties.
  * Idempotent: UNIQUE(product_code) makes second run produce
    inserted=0 (only updated_at refreshes).
  * Local-DB only.  No external HTTP / wFirma / SMTP / DHL calls.
  * Per-row try/except — one bad row never aborts the job.
  * dry_run=True writes nothing and returns a preview list.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def backfill_from_invoice_lines(
    storage_root:    Path,
    *,
    dry_run:         bool          = False,
    batch_id_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Project invoice_lines.product_code into product_master.

    Read-only on documents.db; UPSERT on reservation_queue.db's
    product_master table when ``dry_run`` is False.

    Args:
      storage_root:    settings.storage_root (locates both DB files).
      dry_run:         when True, performs the scan + preview without
                       writing.  Default False per execute-plan brief
                       (admin endpoint defaults dry_run=True).
      batch_id_filter: optional — restrict scan to one batch_id.

    Returns:
      {
        "dry_run":            bool,
        "scanned_rows":       int,    # invoice_lines rows examined
        "scanned_codes":      int,    # distinct product_codes seen
        "skipped_empty_code": int,
        "inserted":           int,    # PM rows newly created
        "updated":            int,    # existing PM rows refreshed
        "errors":             [str],
        "preview":            [       # populated only in dry_run mode
          {"product_code": str, "action": "insert"|"update",
           "source_batch_id": str, "source_invoice_no": str},
          ...
        ],
      }
    """
    out: Dict[str, Any] = {
        "dry_run":            bool(dry_run),
        "scanned_rows":       0,
        "scanned_codes":      0,
        "skipped_empty_code": 0,
        "inserted":           0,
        "updated":            0,
        "errors":             [],
        "preview":            [],
    }

    docs_db = Path(storage_root) / "documents.db"
    rdb_db  = Path(storage_root) / "reservation_queue.db"
    if not docs_db.exists():
        out["errors"].append(f"documents.db not found at {docs_db}")
        return out

    # ── Lazy import; reservation_db requires init before upsert ─────────
    from . import reservation_db as _rdb
    try:
        _rdb.init_reservation_db(rdb_db)
    except Exception as exc:
        out["errors"].append(f"reservation_db init failed: {exc}")
        return out

    # ── Aggregate invoice_lines by product_code ─────────────────────────
    # OLDEST row (by created_at ASC) wins for source_* identity.
    # NEWEST row wins for last_seen_batch_id.
    by_code: Dict[str, Dict[str, Any]] = {}
    try:
        with sqlite3.connect(str(docs_db)) as con:
            con.row_factory = sqlite3.Row
            sql = ("SELECT product_code, description, hsn_code, hs_code, "
                   "       currency, unit_price, rate_usd, "
                   "       batch_id, invoice_no, document_id, created_at "
                   "FROM invoice_lines "
                   "WHERE active=1 ")
            params: List[Any] = []
            if batch_id_filter:
                sql += " AND batch_id=? "
                params.append(batch_id_filter)
            sql += " ORDER BY created_at ASC"
            for r in con.execute(sql, params).fetchall():
                out["scanned_rows"] += 1
                pc = (r["product_code"] or "").strip()
                if not pc:
                    out["skipped_empty_code"] += 1
                    continue
                entry = by_code.get(pc)
                if entry is None:
                    by_code[pc] = {
                        "product_code":      pc,
                        "description":       r["description"] or "",
                        "hsn_code":          (r["hsn_code"] or r["hs_code"]
                                              or ""),
                        "unit_price_ref":    float(r["rate_usd"]
                                                   or r["unit_price"]
                                                   or 0.0),
                        "currency_ref":      r["currency"] or "",
                        "source_batch_id":   r["batch_id"] or "",
                        "source_invoice_no": r["invoice_no"] or "",
                        "source_document_id": r["document_id"] or "",
                        "last_seen_batch_id": r["batch_id"] or "",
                    }
                else:
                    # Already have the oldest row's identity; refresh
                    # last_seen_batch_id to the latest referencing batch.
                    entry["last_seen_batch_id"] = r["batch_id"] or entry["last_seen_batch_id"]
    except Exception as exc:
        out["errors"].append(f"invoice_lines scan failed: {exc}")
        return out

    out["scanned_codes"] = len(by_code)

    # ── Determine existing PM rows for dry-run accounting ───────────────
    existing_pcs: set = set()
    try:
        with sqlite3.connect(str(rdb_db)) as con:
            con.row_factory = sqlite3.Row
            for r in con.execute(
                "SELECT product_code FROM product_master"
            ).fetchall():
                existing_pcs.add(r["product_code"])
    except Exception as exc:
        out["errors"].append(f"product_master read failed: {exc}")
        # do not abort — caller may still want the planning preview

    # ── Plan / execute per product_code ─────────────────────────────────
    for pc, fields in by_code.items():
        action = "update" if pc in existing_pcs else "insert"
        if dry_run:
            out["preview"].append({
                "product_code":      pc,
                "action":            action,
                "source_batch_id":   fields["source_batch_id"],
                "source_invoice_no": fields["source_invoice_no"],
            })
            continue
        try:
            _rdb.upsert_product_master(
                rdb_db,
                product_code       = pc,
                design_no          = "",       # PR #193 preserve-on-blank
                description        = fields["description"],
                metal              = "",
                category           = "",
                source_invoice_no  = fields["source_invoice_no"],
                source_batch_id    = fields["source_batch_id"],
                item_type          = "",
                hsn_code           = fields["hsn_code"],
                unit_price_ref     = fields["unit_price_ref"],
                currency_ref       = fields["currency_ref"],
                confidence         = "high",
                source_document_id = fields["source_document_id"],
                last_seen_batch_id = fields["last_seen_batch_id"],
            )
            if action == "insert":
                out["inserted"] += 1
            else:
                out["updated"] += 1
        except Exception as exc:
            out["errors"].append(
                f"upsert failed for {pc!r}: {exc}"
            )

    log.info(
        "product_master backfill: dry_run=%s scanned_rows=%d "
        "scanned_codes=%d inserted=%d updated=%d skipped_empty=%d "
        "errors=%d filter=%r",
        out["dry_run"], out["scanned_rows"], out["scanned_codes"],
        out["inserted"], out["updated"], out["skipped_empty_code"],
        len(out["errors"]), batch_id_filter,
    )
    return out
