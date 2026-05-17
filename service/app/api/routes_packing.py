"""
routes_packing.py — Invoice + packing list DB endpoints.

POST /api/v1/packing/{batch_id}/upload
    Upload a packing list PDF or XLSX.
    Extracts rows, matches to invoice lines, stores in DB.
    Optional query param: force_reextract=true

POST /api/v1/packing/{batch_id}/reprocess-prices
    Re-read saved packing files and backfill unit_price_eur for rows where
    the current DB value is 0.  Used to recover prices after PR 2A migration
    (packing uploaded before the unit_price_eur column was added).

GET  /api/v1/packing/{batch_id}
    Return combined invoice lines + packing rows for a batch.

GET  /api/v1/packing/{batch_id}/lines
    Return only packing lines for a batch.
"""
from __future__ import annotations

import json
import re
import socket
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from ..auth.dependencies import get_current_user
from ..core.config import settings
from ..core import timeline as tl
from ..core.logging import get_logger
from ..services.batch_service import get_output_dir
from ..services import packing_db as pdb
from ..services import document_db as ddb
from ..services import inventory_state_engine as ise
from ..services.invoice_packing_extractor import process_packing_upload


def seed_purchase_transit(batch_id: str, line_records: List[Dict[str, Any]]) -> int:
    """
    Best-effort: ensure every freshly inserted/updated packing line has its
    inventory state initialised to PURCHASE_TRANSIT.

    Idempotent: a scan_code that already has any state is skipped, so re-uploads
    do not duplicate state events. Failures are logged and swallowed — they
    must never break the packing-upload flow.

    Returns the number of lines transitioned (0 on any failure).
    """
    seeded = 0
    try:
        for line in line_records:
            try:
                sc = pdb._compute_scan_code(line) or ""
                if not sc:
                    continue
                if ise.get_state(sc) is not None:
                    continue
                ise.transition(
                    scan_code    = sc,
                    to_state     = ise.PURCHASE_TRANSIT,
                    product_code = str(line.get("product_code") or ""),
                    design_no    = str(line.get("design_no") or ""),
                    batch_id     = batch_id,
                )
                seeded += 1
            except Exception as _row_exc:
                log.warning("[%s] inventory_state seed skipped for one line: %s",
                            batch_id, _row_exc)
                # Best-effort per-line failure mirror — never raises into the loop.
                # Bounded payload: error str truncated to 200 chars.
                try:
                    from ..services.batch_service import get_output_dir as _get_output_dir
                    _audit_path_fail = _get_output_dir(batch_id) / "audit.json"
                    tl.log_event(
                        _audit_path_fail,
                        tl.EV_INVENTORY_TRANSITION_FAILED,
                        trigger_source = "packing_upload",
                        actor          = "system",
                        detail = {
                            "batch_id":   batch_id,
                            "scan_code":  pdb._compute_scan_code(line) or "",
                            "to_state":   "purchase_transit",
                            "error":      str(_row_exc)[:200],
                        },
                    )
                except Exception as _tl_exc:
                    log.warning(
                        "[%s] inventory transition failure mirror failed (non-fatal): %s",
                        batch_id, _tl_exc,
                    )
    except Exception as _outer:
        log.warning("[%s] inventory_state seed best-effort failure: %s",
                    batch_id, _outer)

    # ── Best-effort timeline mirror — never breaks the upload flow ───────────
    # Emits one per-batch summary event regardless of seeded count, mirroring
    # the existing EV_PZ_GENERATED idiom.  log_event is itself non-fatal when
    # audit.json is missing; the outer try/except catches any unrelated failure
    # (e.g. settings or path resolution) so this can never raise into the route.
    try:
        from ..services.batch_service import get_output_dir as _get_output_dir
        _audit_path = _get_output_dir(batch_id) / "audit.json"
        tl.log_event(
            _audit_path,
            tl.EV_INVENTORY_PURCHASE_TRANSIT_SEEDED,
            trigger_source = "packing_upload",
            actor          = "system",
            detail = {
                "batch_id":    batch_id,
                "seeded":      seeded,
                "total_lines": len(line_records),
            },
        )
    except Exception as _tl_exc:
        log.warning("[%s] inventory_state seed mirror event failed (non-fatal): %s",
                    batch_id, _tl_exc)

    return seeded

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/packing", tags=["packing"])
_auth  = Depends(get_current_user)

_ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls"}
_MAX_BYTES: int     = settings.max_upload_bytes   # 20 MB

# ── Barcode helpers ───────────────────────────────────────────────────────────

_LABEL_SIZE_MM = (57, 32)    # width × height, 300 DPI
_ZPL_DPI       = 300
# 1 mm = 11.811 dots at 300 DPI → round to 12 for clean arithmetic
_DOT_PER_MM    = 11.811


def _fmt_qty(q: Any) -> str:
    """2.0 → '2'  |  1.5 → '1.5'"""
    try:
        f = float(q)
        return str(int(f)) if f == int(f) else str(f)
    except (TypeError, ValueError):
        return str(q)


def _zpl_safe(text: str) -> str:
    """
    Strip characters that corrupt ZPL II output.

    ^ starts a ZPL command — inside ^FD...^FS it terminates the field early.
    ~ triggers ZPL control sequences at any position.
    \\ can cause unexpected escaping on some firmware builds.
    All three must never appear in data fields.
    """
    if not text:
        return ""
    return text.replace("^", "").replace("~", "").replace("\\", "")


def _label_line(ln: Dict[str, Any]) -> str:
    """
    One human-readable summary string an operator can read aloud.
    Format: product_code · bag_id · design_no · metal karat · qty uom
    Empty tokens are omitted so the line stays clean.
    """
    parts = [
        ln.get("product_code", ""),
        ln.get("bag_id", ""),
        ln.get("design_no", ""),
        " ".join(filter(None, [ln.get("metal", ""), ln.get("karat", "")])),
        " ".join(filter(None, [_fmt_qty(ln.get("quantity", 0)), ln.get("uom", "")])),
    ]
    return " · ".join(p for p in parts if p)


def _barcode_value(ln: Dict[str, Any]) -> str:
    """
    Build the scannable barcode value for one physical packing line.

    Uniqueness contract — each physical piece must scan to a distinct value.
    Priority order:
      1. <product_code>|<bag_id>           — when packing list tracks bags
      2. <product_code>|sr<pack_sr>|<design_no> — when source-row Sr is known
                                              (handles aggregated invoices
                                              where many designs share one
                                              product_code)
      3. <product_code>|<design_no>        — fallback when no Sr/bag
      4. <product_code>                    — last resort
    """
    pc      = ln.get("product_code", "")
    bag     = ln.get("bag_id", "")
    sr      = ln.get("pack_sr")
    design  = ln.get("design_no", "")

    if bag:
        return f"{pc}|{bag}"
    if sr is not None:
        # Format Sr as integer when whole, else as-is
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


def _build_barcode_row(ln: Dict[str, Any]) -> Dict[str, Any]:
    bv = _barcode_value(ln)
    return {
        "product_code":           ln["product_code"],
        "invoice_no":             ln.get("invoice_no", ""),
        "design_no":              ln.get("design_no", ""),
        "batch_no":               ln.get("batch_no", ""),
        "bag_id":                 ln.get("bag_id", ""),
        "quantity":               _fmt_qty(ln.get("quantity", 0)),
        "uom":                    ln.get("uom", ""),
        "metal":                  ln.get("metal", ""),
        "karat":                  ln.get("karat", ""),
        "barcode_value":          bv,
        "scan_code":              bv,      # canonical search/entry key for all scan flows
        "pack_sr":                ln.get("pack_sr"),
        "unit_price":             ln.get("unit_price"),
        "label_line":             _label_line(ln),
        "requires_manual_review": bool(ln.get("requires_manual_review")),
    }


# ── ZPL II renderer ───────────────────────────────────────────────────────────
# Label: 57 × 32 mm at 300 DPI = 672 × 378 dots
# Margins: ~20 dots (≈1.7 mm) each side

def _render_zpl(row: Dict[str, Any]) -> str:
    """
    Render one barcode label as ZPL II for a Zebra 300 DPI printer.

    Layout (dots):
      y=15   Zone A: product_code (left)  |  bag_id (right)   — 22pt bold
      y=50   Zone B: design_no (left)     |  metal+karat (right) — 18pt
      y=80   Zone C: QTY: qty uom                              — 18pt
      y=105  Zone D: Code 128 barcode, height=80 dots
      (human-readable text printed by ^BC Y flag)
    """
    pc       = _zpl_safe(row.get("product_code", ""))
    bag      = _zpl_safe(row.get("bag_id", ""))
    design   = _zpl_safe(row.get("design_no", ""))
    metal_k  = _zpl_safe(" ".join(filter(None, [row.get("metal", ""), row.get("karat", "")])))
    qty_uom  = _zpl_safe(f"QTY: {row.get('quantity', '')} {row.get('uom', '')}".strip())
    bv       = _zpl_safe(row.get("barcode_value", row.get("product_code", "")))

    return (
        "^XA\n"
        "^CI28\n"                                            # UTF-8
        f"^FO20,15^A0N,22,22^FD{pc}^FS\n"                  # product_code
        f"^FO450,15^A0N,22,22^FD{bag}^FS\n"                # bag_id (right)
        f"^FO20,50^A0N,18,18^FD{design}^FS\n"              # design_no
        f"^FO450,50^A0N,18,18^FD{metal_k}^FS\n"            # metal karat
        f"^FO20,80^A0N,18,18^FD{qty_uom}^FS\n"             # quantity
        "^FO20,105^BY2,3,80\n"                              # barcode params
        "^BCN,80,Y,N,N\n"                                   # Code128, HR below
        f"^FD{bv}^FS\n"                                     # barcode data
        "^XZ\n"
    )


def _render_zpl_batch(rows: List[Dict[str, Any]]) -> str:
    """Concatenate ZPL for multiple labels — one print job."""
    return "".join(_render_zpl(r) for r in rows)


def _validate_batch(batch_id: str) -> Path:
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    output_dir = get_output_dir(batch_id)
    if not output_dir.exists():
        raise HTTPException(status_code=404, detail=f"Batch {batch_id!r} not found.")
    return output_dir


def _validate_file(file: UploadFile) -> None:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type {suffix!r}. Accepted: PDF, XLSX, XLS.",
        )


# ── POST /api/v1/packing/{batch_id}/upload ────────────────────────────────────

@router.post("/{batch_id}/upload", dependencies=[_auth])
async def upload_packing_list(
    batch_id: str,
    file:            UploadFile,
    force_reextract: bool = Query(default=False),
) -> Dict[str, Any]:
    """
    Upload a packing list (PDF or XLSX), extract rows, match to invoice lines,
    and store in DB.

    - Does not overwrite verified rows unless force_reextract=true.
    - Preserves original file in source/packing/ directory.
    - Logs PACKING_LIST_EXTRACTED and PACKING_MATCHED_TO_INVOICE events.
    """
    output_dir = _validate_batch(batch_id)
    _validate_file(file)

    content = await file.read()
    if len(content) > _MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max {_MAX_BYTES // (1024*1024)} MB.",
        )

    # Save original file to source/packing/
    packing_dir = output_dir / "source" / "packing"
    packing_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "packing_list").name
    safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in safe_name)
    dest_path = packing_dir / safe_name
    dest_path.write_bytes(content)

    # Run extraction + matching pipeline
    try:
        result = process_packing_upload(
            batch_id         = batch_id,
            batch_output_dir = output_dir,
            packing_file_path= dest_path,
            force_reextract  = force_reextract,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Packing list extraction failed: {exc}",
        )

    # Store packing document record
    doc_id = pdb.upsert_packing_document(**result["document"])

    # Build line records
    packing_rows = result["packing_rows"]
    line_records: List[Dict[str, Any]] = []
    for row in packing_rows:
        line_records.append({
            "packing_document_id":  doc_id,
            "batch_id":             batch_id,
            "invoice_no":           row.get("invoice_no", ""),
            "invoice_line_position":row.get("invoice_line_position"),
            "product_code":         row.get("product_code"),
            "design_no":            str(row.get("design_no", "") or ""),
            "batch_no":             str(row.get("batch_no", "") or ""),
            "bag_id":               str(row.get("bag_id", "") or ""),
            "tray_id":              str(row.get("tray_id", "") or ""),
            "item_type":            str(row.get("item_type", "") or ""),
            "uom":                  str(row.get("uom", "") or ""),
            "quantity":             float(row.get("quantity", 0) or 0),
            "gross_weight":         float(row.get("gross_weight", 0) or 0),
            "net_weight":           float(row.get("net_weight", 0) or 0),
            "metal":                str(row.get("metal", "") or ""),
            "karat":                str(row.get("karat", "") or ""),
            "stone_type":           str(row.get("stone_type", "") or ""),
            "remarks":              str(row.get("remarks", "") or ""),
            "extracted_confidence": float(row.get("extracted_confidence", 0) or 0),
            "requires_manual_review": bool(row.get("requires_manual_review", False)),
            # PR 2A — product identity enrichment from packing XLSX
            # unit_price_eur: client billing price (packing list Value column, EUR
            #   namespace) — distinct from unit_price which carries the supplier
            #   USD rate set at upsert from unit_price field above.
            "unit_price_eur":       float(row.get("unit_price", 0) or 0),
            # metal_color: standalone color code (W/Y/RG/R) — preserved from the
            #   "Col" column or parsed from combined "14KT/Y" tokens by extractor.
            "metal_color":          str(row.get("metal_color", "") or ""),
            # quality_string: full quality/grade string as-is from the packing
            #   list (may be compound, e.g. "G-VS LAB,E-VVS LAB"). Captures both
            #   the standard "Quality" column and the "Qualtity" typo variant.
            "quality_string":       str(row.get("quality_string", "") or ""),
        })

    inserted = pdb.upsert_packing_lines(line_records, force_reextract=force_reextract)

    # Seed inventory state → PURCHASE_TRANSIT for every line with a scan_code.
    # Idempotent on re-upload; failures must not break this route.
    seed_purchase_transit(batch_id, line_records)

    # Auto-create / sync proforma drafts from sales_packing_lines (non-blocking).
    # Uses sales_packing_lines (not packing_lines) as the source of truth for
    # client grouping and pricing. A no-op if no sales packing lines exist yet.
    try:
        from ..services.proforma_draft_sync import sync_draft_from_packing_upload
        _pf_db_path = settings.storage_root / "proforma_links.db"
        _sync_result = sync_draft_from_packing_upload(
            batch_id=batch_id,
            operator="packing_upload",
            db_path=_pf_db_path,
            audit_path=output_dir / "audit.json",
        )
        log.info("[%s] proforma draft sync: %s", batch_id, _sync_result)
    except Exception as _pf_exc:
        log.warning("[%s] proforma draft sync failed (non-fatal): %s", batch_id, _pf_exc)

    # Register packing file in unified document registry (non-blocking)
    try:
        import hashlib as _hl
        _h = _hl.sha256(content).hexdigest()
        _inv_no = result["document"].get("invoice_no", "")
        ddb.register_document(
            batch_id=batch_id, document_type="packing",
            file_name=safe_name, file_path=str(dest_path),
            file_hash=_h,
            related_invoice_no=_inv_no,
            extraction_status="extracted", source="upload",
        )
    except Exception as _e:
        log.warning("[%s] document_db packing register failed (non-fatal): %s", batch_id, _e)

    # Timeline events
    audit_path = output_dir / "audit.json"
    tl.log_event(
        audit_path,
        tl.EV_PACKING_LIST_EXTRACTED,
        "packing_upload",
        actor="operator",
        detail={
            "batch_id":     batch_id,
            "file":         safe_name,
            "total_rows":   result["total_rows"],
            "document_id":  doc_id,
        },
    )
    tl.log_event(
        audit_path,
        tl.EV_PACKING_MATCHED_TO_INVOICE,
        "packing_upload",
        actor="operator",
        detail={
            "batch_id":       batch_id,
            "matched":        result["matched_count"],
            "unmatched":      result["unmatched_count"],
            "total":          result["total_rows"],
            "force_reextract":force_reextract,
        },
    )

    return {
        "ok":               True,
        "batch_id":         batch_id,
        "document_id":      doc_id,
        "file":             safe_name,
        "total_rows":       result["total_rows"],
        "matched_count":    result["matched_count"],
        "unmatched_count":  result["unmatched_count"],
        "inserted_count":   inserted,
        "force_reextract":  force_reextract,
    }


# ── POST /api/v1/packing/{batch_id}/reprocess-prices ─────────────────────────

@router.post("/{batch_id}/reprocess-prices", dependencies=[_auth])
async def reprocess_packing_prices(batch_id: str) -> Dict[str, Any]:
    """
    Re-read saved packing XLSX files for this batch and backfill unit_price_eur
    in packing_lines where the current value is 0.

    Does NOT overwrite rows that already have unit_price_eur > 0.
    Does NOT re-run the full upload pipeline; only updates the price field.

    Use-case: recover prices after PR 2A migration when packing was uploaded
    before the unit_price_eur column was added (batch uploaded before 2026-05-14).

    Returns:
      { batch_id, diagnostic: { rows_with_price_before, rows_updated, rows_with_price_after },
        files: [{file, rows_extracted, rows_updated}] }
    """
    output_dir = _validate_batch(batch_id)

    packing_dir = output_dir / "source" / "packing"
    if not packing_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No packing source directory for batch {batch_id!r}",
        )

    xlsx_files = sorted(
        list(packing_dir.glob("*.xlsx")) + list(packing_dir.glob("*.xls")),
    )
    if not xlsx_files:
        raise HTTPException(
            status_code=404,
            detail=f"No packing XLSX files found in source directory for batch {batch_id!r}",
        )

    # Snapshot before
    all_lines_before = pdb.get_packing_lines_for_batch(batch_id)
    rows_with_price_before = sum(
        1 for r in all_lines_before if float(r.get("unit_price_eur", 0) or 0) > 0
    )

    file_results: List[Dict[str, Any]] = []
    total_updated = 0

    for pf in xlsx_files:
        file_entry: Dict[str, Any] = {"file": pf.name, "rows_extracted": 0,
                                      "rows_updated": 0, "error": None}
        try:
            result = process_packing_upload(
                batch_id         = batch_id,
                batch_output_dir = output_dir,
                packing_file_path= pf,
                force_reextract  = False,   # read-only extraction; no DB upsert here
            )
            packing_rows = result["packing_rows"]
            file_entry["rows_extracted"] = len(packing_rows)

            # Build line_records carrying unit_price_eur from the Value column
            line_records: List[Dict[str, Any]] = []
            for row in packing_rows:
                upe = float(row.get("unit_price", 0) or 0)
                if upe <= 0:
                    continue  # no Value column data for this row
                doc_id = ""  # we don't upsert documents here; matching is positional
                line_records.append({
                    "packing_document_id":  doc_id,
                    "batch_id":             batch_id,
                    "invoice_no":           row.get("invoice_no", ""),
                    "invoice_line_position":row.get("invoice_line_position"),
                    "product_code":         row.get("product_code"),
                    "design_no":            str(row.get("design_no", "") or ""),
                    "bag_id":               str(row.get("bag_id", "") or ""),
                    "pack_sr":              row.get("pack_sr"),
                    "unit_price_eur":       upe,
                })

            updated = pdb.backfill_unit_price_eur(batch_id, line_records)
            file_entry["rows_updated"] = updated
            total_updated += updated
        except Exception as exc:
            log.warning("[%s] reprocess-prices failed for %s: %s", batch_id, pf.name, exc)
            file_entry["error"] = str(exc)
        file_results.append(file_entry)

    # Snapshot after
    all_lines_after = pdb.get_packing_lines_for_batch(batch_id)
    rows_with_price_after = sum(
        1 for r in all_lines_after if float(r.get("unit_price_eur", 0) or 0) > 0
    )

    log.info(
        "[%s] reprocess-prices: %d rows updated, price coverage %d→%d/%d",
        batch_id, total_updated,
        rows_with_price_before, rows_with_price_after, len(all_lines_after),
    )
    return {
        "ok":      True,
        "batch_id": batch_id,
        "diagnostic": {
            "rows_with_price_before": rows_with_price_before,
            "rows_updated":           total_updated,
            "rows_with_price_after":  rows_with_price_after,
            "total_packing_rows":     len(all_lines_after),
        },
        "files": file_results,
    }


# ── GET /api/v1/packing/{batch_id} ────────────────────────────────────────────

@router.get("/{batch_id}", dependencies=[_auth])
def get_batch_packing(batch_id: str) -> Dict[str, Any]:
    """
    Return combined invoice lines (from pz_rows.json) and packing lines (from DB)
    for a batch.
    """
    output_dir = _validate_batch(batch_id)

    # Invoice lines from engine output
    try:
        from ..services.invoice_packing_extractor import load_invoice_lines
        invoice_lines = load_invoice_lines(output_dir)
    except Exception:
        invoice_lines = []

    # Packing lines from DB
    packing_lines = pdb.get_packing_lines_for_batch(batch_id)
    documents     = pdb.get_packing_documents_for_batch(batch_id)

    # ── Fallback visibility: 2026-05-17 hotfix ────────────────────────────
    # Atlas intake writes shipment_documents rows BEFORE running the
    # best-effort packing extractor. When extraction fails (unsupported
    # spreadsheet schema, corrupt PDF, etc.) packing_documents stays empty
    # and the Packing List card used to render "No packing list uploaded
    # yet" even though the file is on disk. Surface those uploaded-but-
    # unparsed files here so the card can show them honestly.
    fallback_docs: List[Dict[str, Any]] = []
    if not documents:
        try:
            from ..services import document_db as _ddb
            existing_hashes = {d.get("file_hash") for d in documents if d.get("file_hash")}
            for dtype in ("purchase_packing_list", "sales_packing_list"):
                rows = _ddb.get_documents_for_batch(batch_id, document_type=dtype) or []
                for r in rows:
                    if r.get("file_hash") and r["file_hash"] in existing_hashes:
                        continue   # already covered by parsed packing_documents
                    fallback_docs.append({
                        "id":                   r.get("id"),
                        "batch_id":             r.get("batch_id"),
                        "document_type":        r.get("document_type"),
                        "file_name":            r.get("file_name") or "",
                        "source_file_path":     r.get("file_path") or "",
                        "file_hash":            r.get("file_hash") or "",
                        # Mark as fallback so the UI can label it
                        # "Uploaded — extraction pending / failed" rather
                        # than claim parsed status.
                        "parser_status":        r.get("parser_status") or "pending",
                        "extraction_status":    r.get("extraction_status") or "pending",
                        "fallback_unparsed":    True,
                        "row_count":            0,
                        "created_at":           r.get("created_at"),
                        "updated_at":           r.get("updated_at"),
                    })
        except Exception as exc:
            log.warning("[%s] packing fallback enumeration failed (non-fatal): %s",
                        batch_id, exc)

    return {
        "batch_id":      batch_id,
        "invoice_lines": invoice_lines,
        "packing_lines": packing_lines,
        "documents":     documents + fallback_docs,
    }


# ── GET /api/v1/packing/{batch_id}/lines ─────────────────────────────────────

@router.get("/{batch_id}/lines", dependencies=[_auth])
def get_packing_lines(batch_id: str) -> Dict[str, Any]:
    """Return only packing lines for a batch."""
    _validate_batch(batch_id)
    lines = pdb.get_packing_lines_for_batch(batch_id)
    return {
        "batch_id": batch_id,
        "count":    len(lines),
        "lines":    lines,
    }


# ── Helpers for link-as-sales ────────────────────────────────────────────────

# Two filename patterns for client name extraction:
#   Short:  "148 Client SUOKKO.xlsx"      → leading number + space + Client + name
#   Long:   "148 EJL-26-27-148-PND-18KT-...-Client SUOKKO.xlsx"
#                                          → dash + Client + name anywhere in stem
# Handles both "Client" and the common "Cilent" typo.
# Requires either a numeric prefix OR a dash separator so bare "Client NAME.xlsx"
# (no invoice number, no dash) does not match — preserving prior behavior.
_CLIENT_NAME_RE = re.compile(
    r"(?:^\d+\s+|-)(?:client|cilent)\s+(.+)",
    re.IGNORECASE,
)

# Preamble-level label pattern for Excel header-row fallback.
_CLIENT_PREAMBLE_RE = re.compile(
    r"^(?:client|consignee|buyer|ship\s*to)\s*[:#\-]?\s*(.+)",
    re.IGNORECASE,
)


def _guess_client_from_filename(filename: str) -> str:
    """
    Parse the client name from filenames like:
      '148 Client SUOKKO.xlsx'                              (short format)
      '148 EJL-26-27-148-PND-18KT-...-Client SUOKKO.xlsx'  (long format)
    Also handles the 'Cilent' typo.  Returns '' if pattern not found.
    """
    stem = Path(filename).stem
    m = _CLIENT_NAME_RE.search(stem.strip())
    return m.group(1).strip() if m else ""


def _build_matched_sales_lines(
    packing_lines: List[Dict[str, Any]],
    client: str,
) -> tuple:
    """Filter *packing_lines* to invoiceable rows and build sales_packing_lines dicts.

    Returns (matched_list, skipped_count).  Excludes rows where product_code
    is absent/blank or requires_manual_review is set.
    """
    matched = [
        ln for ln in packing_lines
        if str(ln.get("product_code") or "").strip()
        and not ln.get("requires_manual_review")
    ]
    skipped = len(packing_lines) - len(matched)
    sales_lines = [
        {
            "client_name":  client,
            "client_ref":   str(ln.get("invoice_no", "") or ""),
            "product_code": str(ln.get("product_code", "") or ""),
            "design_no":    str(ln.get("design_no", "") or ""),
            "bag_id":       str(ln.get("bag_id", "") or ""),
            "quantity":     float(ln.get("quantity", 0) or 0),
            "remarks":      str(ln.get("remarks", "") or ""),
            "unit_price":   float(ln.get("unit_price_eur") or 0),
            "currency":     str(ln.get("currency") or "EUR"),
            "total_value":  float(ln.get("quantity") or 0) * float(ln.get("unit_price_eur") or 0),
            "price_source": "packing_xlsx_value" if float(ln.get("unit_price_eur") or 0) > 0 else "packing_promote",
        }
        for ln in matched
    ]
    return sales_lines, skipped


def _guess_client_from_preamble(file_path: str) -> str:
    """
    Fallback: scan the top rows of the Excel packing file for a 'Client:' /
    'Consignee:' / 'Buyer:' / 'Ship To:' label and return the value.
    Returns '' on any failure (missing file, unreadable format, no match).
    """
    if not file_path:
        return ""
    try:
        import openpyxl as _opx  # type: ignore
        wb = _opx.load_workbook(str(file_path), read_only=True, data_only=True)
        ws = wb.active
        for row in ws.iter_rows(min_row=1, max_row=12, values_only=True):
            for cell in row:
                raw = str(cell or "").strip()
                if not raw:
                    continue
                m = _CLIENT_PREAMBLE_RE.match(raw)
                if m:
                    val = m.group(1).strip().strip(":")
                    if val and len(val) < 80:
                        wb.close()
                        return val
        wb.close()
    except Exception:
        pass
    return ""


# ── GET /api/v1/packing/{batch_id}/packing-documents ─────────────────────────

@router.get("/{batch_id}/packing-documents", dependencies=[_auth])
def get_packing_documents(batch_id: str) -> Dict[str, Any]:
    """
    Return packing_documents rows for a batch, each annotated with:

    ``suggested_client_name``
        Client name parsed from the filename (``{N} Client {name}`` pattern).
        Empty string when the pattern does not match.

    ``line_count``
        Actual number of packing_lines rows linked to this document.
        Ghost rows from pre-dedup re-uploads will show 0.

    ``is_duplicate``
        True when another document in this batch has the same source_file_hash
        and this document is NOT the canonical one (i.e. it was created by a
        re-upload before hash-dedup was in place).

    ``canonical_id``
        The id of the preferred document in a duplicate hash group — the one
        with the highest line_count (ties broken by oldest created_at).
        None for non-duplicate documents.

    Used by the dashboard "Link packing files" flow so the operator can see
    which documents are real vs. ghost, edit client names, ignore duplicates,
    and then call ``POST /{batch_id}/link-as-sales``.
    """
    from collections import defaultdict as _dd

    _validate_batch(batch_id)
    docs = pdb.get_packing_documents_for_batch(batch_id)

    # ── Annotate each doc with suggested client name and real line count ──────
    line_counts = pdb.get_line_counts_for_batch(batch_id)
    for d in docs:
        raw_name = Path(d.get("source_file_path", "")).name
        d["suggested_client_name"] = (
            _guess_client_from_filename(raw_name)
            or _guess_client_from_preamble(d.get("source_file_path", ""))
        )
        d["line_count"] = line_counts.get(d["id"], 0)

    # ── Detect duplicates: group by non-empty source_file_hash ───────────────
    # Ghost rows share the same hash but were created before the hash-dedup
    # guard was in place.  Canonical = most lines; ties → oldest created_at.
    hash_groups: Dict[str, List[Dict[str, Any]]] = _dd(list)
    for d in docs:
        h = d.get("source_file_hash", "")
        if h:
            hash_groups[h].append(d)

    for group in hash_groups.values():
        if len(group) == 1:
            group[0]["is_duplicate"] = False
            group[0]["canonical_id"] = None
        else:
            # Sort: highest line_count first, then oldest created_at first
            sorted_grp = sorted(group, key=lambda x: (-x["line_count"], x["created_at"]))
            canonical_id = sorted_grp[0]["id"]
            for d in group:
                d["is_duplicate"] = (d["id"] != canonical_id)
                d["canonical_id"] = canonical_id

    # Docs with empty hash (very old rows with no hash) — never marked duplicate
    for d in docs:
        if "is_duplicate" not in d:
            d["is_duplicate"] = False
            d["canonical_id"] = None

    return {
        "batch_id":  batch_id,
        "count":     len(docs),
        "documents": docs,
    }


# ── POST /api/v1/packing/{batch_id}/link-as-sales ────────────────────────────


class _ClientMapping(BaseModel):
    packing_document_id: str
    client_name: str


class _LinkAsSalesBody(BaseModel):
    client_mappings: List[_ClientMapping]


@router.post("/{batch_id}/link-as-sales", dependencies=[_auth])
def link_packing_as_sales(
    batch_id: str,
    body: _LinkAsSalesBody,
) -> Dict[str, Any]:
    """
    Promote purchase packing lines into ``sales_packing_lines`` with operator-
    supplied client attribution, then auto-create/sync proforma drafts.

    This is the backfill path for batches where client packing files were
    uploaded via the purchase-packing route (``POST /{batch_id}/upload``) instead
    of the sales-intake route.

    **Idempotent**: uses ``replace_sales_packing_lines`` which atomically
    replaces lines scoped to (sales_document_id, batch_id) only.  Re-calling
    with the same mappings is safe.

    **Non-destructive**: rows in ``packing_lines`` (purchase side) are never
    touched.  Duplicate packing_document rows (ghost records from pre-dedup
    era) are safe to reference — they share lines with the canonical record.
    """
    output_dir = _validate_batch(batch_id)
    if not body.client_mappings:
        raise HTTPException(status_code=400, detail="client_mappings must not be empty.")

    results: List[Dict[str, Any]] = []
    for mapping in body.client_mappings:
        pdoc_id = (mapping.packing_document_id or "").strip()
        client  = (mapping.client_name or "").strip()
        if not pdoc_id or not client:
            results.append({
                "packing_document_id": pdoc_id,
                "client_name":         client,
                "ok":                  False,
                "reason":              "missing packing_document_id or client_name",
            })
            continue

        # Load existing purchase packing lines for this document
        packing_lines = pdb.get_packing_lines_for_document(pdoc_id)
        if not packing_lines:
            # Check if this might be a ghost duplicate doc with 0 lines.
            # Ghost docs share a hash with a canonical doc that has the real lines.
            # Tell the operator which doc to use instead.
            ghost_hint = ""
            pdoc_row = pdb.get_packing_document(pdoc_id)
            if pdoc_row:
                h = pdoc_row.get("source_file_hash", "")
                if h:
                    all_docs = pdb.get_packing_documents_for_batch(batch_id)
                    counts   = pdb.get_line_counts_for_batch(batch_id)
                    siblings = [d for d in all_docs
                                if d.get("source_file_hash") == h and d["id"] != pdoc_id]
                    canonical = next((d for d in siblings if counts.get(d["id"], 0) > 0), None)
                    if canonical:
                        ghost_hint = (
                            f" This appears to be a ghost duplicate — "
                            f"use canonical_id={canonical['id']!r} instead "
                            f"(has {counts[canonical['id']]} lines)."
                        )
            results.append({
                "packing_document_id": pdoc_id,
                "client_name":         client,
                "ok":                  False,
                "reason":              f"no packing lines found for document.{ghost_hint}",
            })
            continue

        # Get-or-create a stable sales_document record for this packing doc + client
        sales_doc_id = ddb.get_or_create_sales_document_for_packing(
            batch_id=batch_id,
            packing_document_id=pdoc_id,
            client_name=client,
        )

        # Map packing_lines → sales_packing_lines, excluding unmatched rows.
        sales_lines, unmatched_skipped = _build_matched_sales_lines(packing_lines, client)

        # Atomically replace (idempotent for this sales_document scope)
        repl = ddb.replace_sales_packing_lines(
            sales_document_id=sales_doc_id,
            batch_id=batch_id,
            lines=sales_lines,
        )
        results.append({
            "packing_document_id": pdoc_id,
            "client_name":         client,
            "ok":                  True,
            "packing_lines_read":  len(packing_lines),
            "sales_lines_written": repl["inserted"],
            "unmatched_skipped":   unmatched_skipped,
        })
        log.info(
            "[%s] link_as_sales: client=%s pdoc=%s lines=%d→%d (skipped=%d unmatched)",
            batch_id, client, pdoc_id, len(packing_lines), repl["inserted"],
            unmatched_skipped,
        )

    # Trigger proforma draft auto-sync (non-blocking; any error is logged, not raised)
    sync_summary: Dict[str, Any] = {}
    try:
        from ..services.proforma_draft_sync import sync_draft_from_packing_upload
        _pf_db_path = settings.storage_root / "proforma_links.db"
        sync_summary = sync_draft_from_packing_upload(
            batch_id=batch_id,
            operator="link_as_sales",
            db_path=_pf_db_path,
            audit_path=output_dir / "audit.json",
        )
        log.info("[%s] link_as_sales draft sync: %s", batch_id, sync_summary)
    except Exception as exc:
        log.warning("[%s] link_as_sales draft sync failed (non-fatal): %s", batch_id, exc)
        sync_summary = {"error": str(exc)}

    # Audit timeline
    try:
        tl.log_event(
            output_dir / "audit.json",
            "PACKING_LINKED_AS_SALES",
            "link_as_sales",
            actor="operator",
            detail={
                "batch_id": batch_id,
                "mappings": [
                    {"doc": m.packing_document_id, "client": m.client_name}
                    for m in body.client_mappings
                ],
                "results": results,
            },
        )
    except Exception:
        pass

    ok_count = sum(1 for r in results if r.get("ok"))
    return {
        "ok":        ok_count > 0,
        "batch_id":  batch_id,
        "processed": len(results),
        "linked":    ok_count,
        "failed":    len(results) - ok_count,
        "results":   results,
        "draft_sync": sync_summary,
    }


# ── GET /api/v1/packing/{batch_id}/barcode ───────────────────────────────────

@router.get("/{batch_id}/barcode", dependencies=[_auth])
def get_barcode_preview(batch_id: str) -> Dict[str, Any]:
    """
    Return barcode-ready rows for a batch.

    Each row joins the packing DB record with its product_code.
    Only matched rows (product_code IS NOT NULL) are included.
    Unmatched rows are reported in the summary but excluded from barcode rows
    because they have no stable identifier to encode.

    barcode_value = product_code  (e.g. "EJL/26-27/100-1")
    This is the canonical per-line identifier and is safe to encode as a
    1-D or 2-D barcode for warehouse scanning.

    Fields per row:
      product_code, invoice_no, design_no, batch_no, bag_id, barcode_value,
      requires_manual_review
    """
    _validate_batch(batch_id)
    all_lines = pdb.get_packing_lines_for_batch(batch_id)

    matched   = [ln for ln in all_lines if ln.get("product_code")]
    unmatched = [ln for ln in all_lines if not ln.get("product_code")]

    # One invoice line can span multiple bags.
    # Explode: one barcode row per physical bag, not per invoice line.
    rows = [_build_barcode_row(ln) for ln in matched]

    return {
        "batch_id":        batch_id,
        "count":           len(rows),
        "unmatched_count": len(unmatched),
        "rows":            rows,
    }


# ── GET /api/v1/packing/{batch_id}/barcode/zpl ───────────────────────────────

@router.get("/{batch_id}/barcode/zpl", dependencies=[_auth])
def get_barcode_zpl(batch_id: str) -> PlainTextResponse:
    """
    Return ZPL II label data for all matched bags in a batch.

    One ^XA...^XZ block per bag — safe to spool directly to a Zebra printer
    via TCP port 9100 or USB raw print queue.

    Label spec:
      57 × 32 mm at 300 DPI
      Zone A: product_code / bag_id
      Zone B: design_no / metal+karat
      Zone C: QTY: qty uom
      Zone D: Code 128 barcode (barcode_value = product_code|bag_id)
    """
    _validate_batch(batch_id)
    all_lines = pdb.get_packing_lines_for_batch(batch_id)
    matched   = [ln for ln in all_lines if ln.get("product_code")]
    if not matched:
        raise HTTPException(
            status_code=422,
            detail="No matched packing lines found. Upload and match a packing list first.",
        )
    rows = [_build_barcode_row(ln) for ln in matched]
    zpl  = _render_zpl_batch(rows)
    return PlainTextResponse(
        content=zpl,
        media_type="text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="labels_{batch_id}.zpl"',
            "X-Label-Count": str(len(rows)),
        },
    )


# ── POST /api/v1/packing/{batch_id}/barcode/print ────────────────────────────

@router.post("/{batch_id}/barcode/print", dependencies=[_auth])
def print_barcode_labels(
    batch_id:     str,
    printer_host: str   = Query(..., description="Zebra printer IP address"),
    printer_port: int   = Query(default=9100, description="Raw TCP port (default 9100)"),
    timeout_sec:  float = Query(default=5.0, description="TCP connect+send timeout"),
) -> Dict[str, Any]:
    """
    Send ZPL II labels directly to a Zebra printer via raw TCP (port 9100).

    The printer must be reachable from the server running this service.
    For USB-connected printers, use the /barcode/zpl endpoint and spool locally.

    Returns: ok, label_count, printer, port
    """
    _validate_batch(batch_id)
    all_lines = pdb.get_packing_lines_for_batch(batch_id)
    matched   = [ln for ln in all_lines if ln.get("product_code")]
    if not matched:
        raise HTTPException(
            status_code=422,
            detail="No matched packing lines. Upload and match a packing list first.",
        )

    rows    = [_build_barcode_row(ln) for ln in matched]
    zpl     = _render_zpl_batch(rows)
    payload = zpl.encode("utf-8")

    try:
        with socket.create_connection((printer_host, printer_port), timeout=timeout_sec) as sock:
            sock.sendall(payload)
        log.info(
            "[%s] Printed %d labels → %s:%d (%d bytes)",
            batch_id, len(rows), printer_host, printer_port, len(payload),
        )
    except OSError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Printer unreachable at {printer_host}:{printer_port} — {exc}",
        )

    return {
        "ok":           True,
        "batch_id":     batch_id,
        "label_count":  len(rows),
        "printer":      printer_host,
        "port":         printer_port,
        "bytes_sent":   len(payload),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Dev-only producer trigger
# ─────────────────────────────────────────────────────────────────────────────
# Reads existing packing_lines for *batch_id* and runs the same producer that
# fires after a real upload (seed_purchase_transit). Does NOT mutate
# packing_lines. Returns the count seeded into PURCHASE_TRANSIT.
#
# Gated by settings.environment == "dev" — returns 404 in prod. No auth so
# validation harnesses can hit it without a session. Should be removed (or
# kept disabled) before any non-dev deployment.

# Single dev router carries both packing trigger and inventory-state seeder.
# Mounted by main.py as packing_dev_router. Prefix is /api/v1/dev so
# sub-paths can name their domain explicitly.
dev_router = APIRouter(prefix="/api/v1/dev", tags=["dev"])


class _DevTriggerBody(BaseModel):
    batch_id: str


@dev_router.post("/packing/trigger")
def dev_trigger_packing_seeding(body: _DevTriggerBody) -> Dict[str, Any]:
    """
    Run seed_purchase_transit() against existing packing_lines for *batch_id*.

    Read-only against packing.db; only writes to inventory_state /
    inventory_state_events via the engine's idempotent transition path.
    """
    if settings.environment != "dev":
        raise HTTPException(status_code=404, detail="Not found.")

    batch_id = (body.batch_id or "").strip()
    if not batch_id or "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    try:
        lines = pdb.get_packing_lines_for_batch(batch_id)
        processed = seed_purchase_transit(batch_id, lines)
        return {
            "ok":        True,
            "batch_id":  batch_id,
            "lines":     len(lines),
            "processed": processed,
        }
    except Exception as exc:
        log.warning("[%s] dev trigger failed: %s", batch_id, exc)
        return {
            "ok":        False,
            "batch_id":  batch_id,
            "error":     str(exc),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Dev-only batch inventory_state seeder for legacy purchase packing lines
# ─────────────────────────────────────────────────────────────────────────────
# Per-batch, operator-triggered. Reads packing_lines + audit.json, walks
# each scan_code through legal transitions to a target state. Idempotent;
# never demotes; never touches sales_packing_lines, audit, warehouse scans,
# or proforma drafts.

_VALID_TARGETS = {"auto", ise.PURCHASE_TRANSIT, ise.WAREHOUSE_STOCK}


class _SeedBatchBody(BaseModel):
    batch_id:     str
    target_state: str  = "auto"
    dry_run:      bool = False


def _load_audit(batch_id: str) -> Dict[str, Any]:
    """Read audit.json from outputs/ or working/. Raises HTTPException(400) on miss."""
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / batch_id / "audit.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"audit.json for {batch_id} unreadable: {exc}",
                )
    raise HTTPException(
        status_code=400,
        detail=f"No audit.json found for {batch_id} — refusing to guess state.",
    )


def _pz_done(audit: Dict[str, Any]) -> bool:
    """
    Mirror of the inferred PZ-done logic used elsewhere in the app, plus the
    shared read-time evidence helper so a stale ``audit.status="failed"``
    doesn't block auto-target resolution when a legitimate PZ exists (e.g.
    only the timeline event ``wfirma_pz_created`` carried the proof). Strict
    rejection is preserved when no signal exists.
    """
    if (
        audit.get("pz_generated") is True
        or bool(audit.get("pz_pdf_filename"))
        or bool(audit.get("pz_generated_at"))
        or audit.get("status") in ("success", "partial")
    ):
        return True
    try:
        from ..services.audit_evidence import effective_pz_evidence
    except Exception:
        return False
    ev = effective_pz_evidence(audit)
    # Auto-target only flips to WAREHOUSE_STOCK when a *PZ-side* signal is
    # present — customs-only signals (DSK / SAD / clearance_status) prove
    # customs cleared but not that the wFirma PZ was issued, so they alone
    # must NOT promote inventory state. Business semantics preserved.
    pz_side = {
        "wfirma_export.wfirma_pz_doc_id",
        "timeline:wfirma_pz_created",
        "effective_pz_status_done",
    }
    return any(s in pz_side for s in ev["signals"])


@dev_router.post("/inventory-state/seed-batch")
def dev_seed_inventory_state(body: _SeedBatchBody) -> Dict[str, Any]:
    """
    Seed inventory_state for one legacy batch.

    No global backfill. Operator-triggered, batch-scoped, idempotent.
    Walks each scan_code through legal transitions only — never demotes,
    never overwrites a state row that's already at or beyond the target.
    """
    if settings.environment != "dev":
        raise HTTPException(status_code=404, detail="Not found.")

    batch_id = (body.batch_id or "").strip()
    if not batch_id or "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    requested = body.target_state or "auto"
    if requested not in _VALID_TARGETS:
        raise HTTPException(
            status_code=400,
            detail=f"target_state must be one of {sorted(_VALID_TARGETS)}; "
                   f"SALES_TRANSIT/CLOSED are not valid backfill targets.",
        )

    audit = _load_audit(batch_id)
    decided_target = (
        (ise.WAREHOUSE_STOCK if _pz_done(audit) else ise.PURCHASE_TRANSIT)
        if requested == "auto" else requested
    )

    lines = pdb.get_packing_lines_for_batch(batch_id)
    considered  = 0
    planned     = 0
    transitioned = 0
    skipped     = 0
    errors: List[Dict[str, Any]] = []

    for line in lines:
        considered += 1
        try:
            sc = line.get("scan_code") or pdb._compute_scan_code(line)
            if not sc:
                skipped += 1
                continue

            cur = ise.get_state(sc)
            cur_state = cur["state"] if cur else None

            # Plan the chain from cur_state to decided_target (legal hops only).
            chain = []
            if cur_state is None:
                chain.append(ise.PURCHASE_TRANSIT)
            if (decided_target == ise.WAREHOUSE_STOCK
                    and (cur_state == ise.PURCHASE_TRANSIT
                         or ise.PURCHASE_TRANSIT in chain)):
                chain.append(ise.WAREHOUSE_STOCK)

            if not chain:
                # Already at target or beyond — never demote.
                skipped += 1
                continue

            planned += len(chain)
            if body.dry_run:
                continue

            for next_state in chain:
                ise.transition(
                    scan_code    = sc,
                    to_state     = next_state,
                    product_code = str(line.get("product_code") or ""),
                    design_no    = str(line.get("design_no") or ""),
                    batch_id     = batch_id,
                )
                transitioned += 1
        except Exception as exc:
            errors.append({
                "scan_code": (line.get("scan_code") or "").strip(),
                "error":     f"{type(exc).__name__}: {exc}",
            })

    return {
        "ok":             True,
        "batch_id":       batch_id,
        "decided_target": decided_target,
        "requested_target": requested,
        "dry_run":        body.dry_run,
        "considered":     considered,
        "planned":        planned,
        "transitioned":   transitioned,
        "skipped":        skipped,
        "errors":         errors,
    }
