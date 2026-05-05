"""
routes_packing.py — Invoice + packing list DB endpoints.

POST /api/v1/packing/{batch_id}/upload
    Upload a packing list PDF or XLSX.
    Extracts rows, matches to invoice lines, stores in DB.
    Optional query param: force_reextract=true

GET  /api/v1/packing/{batch_id}
    Return combined invoice lines + packing rows for a batch.

GET  /api/v1/packing/{batch_id}/lines
    Return only packing lines for a batch.
"""
from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

from ..auth.dependencies import get_current_user
from ..core.config import settings
from ..core import timeline as tl
from ..core.logging import get_logger
from ..services.batch_service import get_output_dir
from ..services import packing_db as pdb
from ..services import document_db as ddb
from ..services.invoice_packing_extractor import process_packing_upload

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
        })

    inserted = pdb.upsert_packing_lines(line_records, force_reextract=force_reextract)

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

    return {
        "batch_id":      batch_id,
        "invoice_lines": invoice_lines,
        "packing_lines": packing_lines,
        "documents":     documents,
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
