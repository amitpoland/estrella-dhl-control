"""
routes_intake.py — Full document-chain intake endpoint.
========================================================

POST /api/v1/shipment/intake

Accepts the complete intake payload in a single multipart request:
  - AWB number + carrier
  - AWB PDF (optional)
  - Purchase invoice PDFs (1+)
  - Purchase packing lists (PDF/XLS, one per invoice, indexed)
  - Sales documents (optional)
  - Sales packing lists (optional)
  - metadata JSON mapping blocks to files

All files are saved as evidence.
All files are registered in shipment_documents.
AWB PDF is parsed and stored in awb_documents.
Packing lists are extracted via existing invoice_packing_extractor pipeline.
Sales documents are saved and registered.

POST /api/v1/shipment/{batch_id}/packing_list
  Backfill: attach a packing list to an existing batch (any status).
  Works for old batches that were created before the intake screen.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from ..core.config import settings
from ..core.logging import get_logger
from ..core.security import require_api_key
from ..services.proforma_draft_governance import check_creation_lines
from ..core import timeline as tl
from ..services import document_db as ddb
from ..services import packing_db as pdb
from ..services import proforma_invoice_link_db as pildb
from .routes_packing import seed_purchase_transit
from ..services.awb_parser import parse_awb_pdf
from ..services.batch_service import get_output_dir
from ..services.invoice_intake_parser import parse_invoice_pdf
from ..services.invoice_packing_extractor import process_packing_upload, _safe_float
from ..services.global_invoice_parser import parse_global_invoice_pdf
from ..services.supplier_detect import detect_supplier
from ..utils.io import write_json_atomic
from .routes_upload import _mark_agency_documents_received

log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1/shipment", tags=["intake"])
_auth  = Depends(require_api_key)


def _read_pdf_text_preview(path: Path) -> str:
    """Return first ~800 characters of a PDF's first page. Returns '' on error."""
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            if not pdf.pages:
                return ""
            return (pdf.pages[0].extract_text() or "")[:800]
    except Exception:
        return ""

_CARRIERS            = {"DHL", "FedEx", "Other"}
_ALLOWED_INVOICE_EXT = {".pdf"}
_ALLOWED_PACKING_EXT = {".pdf", ".xlsx", ".xls"}
_ALLOWED_SAD_EXT     = {".pdf", ".xml"}
# Per-doc-type extension policy for the New Shipment Atlas local-only
# slots. Central source of truth so the frontend `<input accept>` can
# mirror it exactly (see _NS_DOC_TYPES in dashboard.html). Tightened
# 2026-05-17 hotfix after a user dropped an xlsx packing list into the
# default first (purchase_invoice) slot and saw "Allowed: ['.pdf']".
_ALLOWED_SERVICE_EXT = {".pdf", ".xlsx", ".xls"}
_ALLOWED_CARNET_EXT  = {".pdf"}
# `other_document` keeps the historical generic-safe rule (PDF +
# spreadsheets + images); we explicitly avoid widening to anything
# executable / archive.
_ALLOWED_OTHER_EXT   = {".pdf", ".xlsx", ".xls", ".jpg", ".jpeg", ".png"}
_MAX_BYTES: int      = settings.max_upload_bytes   # 20 MB


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "._- " else "_" for c in Path(name).name)


def _make_batch_id(tracking_no: str) -> str:
    slug  = "".join(c if c.isalnum() else "" for c in tracking_no)[:20]
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    uid   = uuid.uuid4().hex[:8]
    return f"SHIPMENT_{slug}_{month}_{uid}"


def _proforma_db_path() -> Path:
    """Storage location for proforma_invoice_link_db (Phase 2 drafts)."""
    return settings.storage_root / "proforma_links.db"


def _auto_create_draft_for_client(
    *,
    batch_id:    str,
    client:      str,
    client_ref:  str,
    currency:    str,
    line_records: List[Dict[str, Any]],
    operator:    str = "intake",
) -> None:
    """Best-effort: auto-create a Phase-2 editable Proforma Draft from
    sales_packing line_records. Idempotent. Failure is logged and
    swallowed — never block intake on draft creation.
    """
    if not (client or "").strip():
        return
    if not line_records:
        return
    try:
        # Reshape line_records (sales_packing_lines schema) into the
        # auto-create's `lines` shape. Keep client_ref alongside each
        # line so per-line client refs aren't lost.
        editable_input = []
        for r in line_records:
            editable_input.append({
                "product_code": r.get("product_code") or "",
                "design_no":    r.get("design_no") or "",
                "qty":          r.get("quantity") or 0,
                "unit_price":   r.get("unit_price") or 0,
                "currency":     (r.get("currency") or currency or "").upper(),
                "price_source": r.get("price_source") or "",
                "client_ref":   r.get("client_ref") or client_ref or "",
                # Carry sales-packing attributes through for the generated
                # name_pl fallback (used only on a product_descriptions miss).
                # Generally absent on sales_packing_lines rows; passed through
                # defensively so the fallback fires when they ARE present.
                "ctg":            r.get("ctg") or r.get("category") or "",
                "kt":             r.get("kt") or r.get("karat") or "",
                "col":            r.get("col") or r.get("metal_color") or "",
                "quality":        r.get("quality") or r.get("quality_string") or "",
            })
        # Governance check — no-op when proforma_draft_governance_enabled=False
        check_creation_lines(editable_input)
        # Lazy imports to avoid import cycles (service layer stays free of
        # route/parser imports; we inject these as callables instead).
        from ..api.sales_packing_parser import generate_name_pl_if_sufficient
        from ..services import wfirma_db as _wfdb
        draft, was_created = pildb.auto_create_draft_from_sales_packing(
            _proforma_db_path(),
            batch_id      = batch_id,
            client_name   = client,
            currency      = (currency or "").upper(),
            lines         = editable_input,
            operator      = operator,
            # Fill blank name_pl from the product_descriptions authority at
            # birth so drafts are not born with a missing commercial
            # description. Never fabricates; never touches price.
            name_pl_lookup = ddb.get_product_description,
            # Second-choice name_pl: generate from attributes ONLY when the
            # category is recognised (declines None otherwise). Never fabricates.
            desc_generate  = generate_name_pl_if_sufficient,
            # Birth advisory: surface missing wFirma product mapping (read-only;
            # never writes wFirma). Visibility only — does not block creation.
            product_mapping_lookup = _wfdb.get_product,
        )
        log.info(
            "[%s] proforma draft %s for client=%r (id=%s, state=%s, lines=%d)",
            batch_id,
            "auto-created" if was_created else "already exists",
            client, draft.id, draft.draft_state, len(editable_input),
        )
    except Exception as exc:
        log.warning("[%s] proforma draft auto-create failed for %r: %s",
                    batch_id, client, exc)


def _validate_file(file: UploadFile, allowed_exts: set) -> None:
    if not file.filename:
        raise HTTPException(status_code=400, detail="File has no name.")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in allowed_exts:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{suffix}' not allowed. Allowed: {sorted(allowed_exts)}",
        )


async def _save(file: UploadFile, dest: Path) -> bytes:
    content = await file.read()
    if len(content) > _MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max {_MAX_BYTES // (1024 * 1024)} MB.",
        )
    dest.write_bytes(content)
    return content


def _write_draft_audit(
    output_dir:  Path,
    batch_id:    str,
    tracking_no: str,
    carrier:     str,
    inv_names:   List[str],
    awb_name:    str,
) -> None:
    audit = {
        "batch_id":    batch_id,
        "tracking_no": tracking_no,
        "awb":         tracking_no.strip().replace(" ", ""),
        "carrier":     carrier,
        "status":      "draft",
        "source":      "intake_upload",
        "timestamp":   _now_iso(),
        "inputs":      {
            "invoices":  inv_names,
            "awb":       awb_name,
        },
        "invoice_names": inv_names,
        "awb_name":      awb_name,
        "folder_path":   str(output_dir),
        "timeline":      [],
    }
    write_json_atomic(output_dir / "audit.json", audit)


# ── Main intake endpoint ──────────────────────────────────────────────────────

@router.post("/intake", dependencies=[_auth])
async def shipment_intake(
    background:         BackgroundTasks,
    tracking_no:        str                    = Form(default=""),
    carrier:            str                    = Form(default="DHL"),
    metadata:           str                    = Form(default="{}"),
    invoices:           List[UploadFile]       = [],
    packing_lists:      List[UploadFile]       = [],
    awb:                Optional[UploadFile]   = None,
    sad:                Optional[UploadFile]   = None,    # SAD/ZC429 PDF or XML
    sales_documents:    List[UploadFile]       = [],
    sales_packing_lists: List[UploadFile]      = [],
    # Atlas-aligned local-only document types. These are saved + registered
    # in shipment_documents but NEVER parsed and NEVER trigger
    # DHL/PZ/SAD/wFirma/proforma. Contractor IDs come from per-slot metadata.
    service_invoices:   List[UploadFile]       = [],
    carnet_docs:        List[UploadFile]       = [],
    other_docs:         List[UploadFile]       = [],
) -> JSONResponse:
    """
    Full document-chain intake.

    Body (multipart/form-data):
      tracking_no           — AWB/tracking number (required)
      carrier               — DHL | FedEx | Other
      invoices[]            — purchase invoice PDFs (1+)
      packing_lists[]       — packing list per invoice (PDF/XLS, optional, indexed)
      awb                   — AWB tracking PDF (optional)
      sales_documents[]     — sales invoice/order PDFs (optional)
      sales_packing_lists[] — sales packing lists (optional)
      metadata              — JSON string:
                              {
                                "purchase_blocks": [
                                  {"invoice_index":0,"packing_index":0,"supplier_name":"..."}
                                ],
                                "sales_blocks": [
                                  {"document_index":0,"packing_index":0,
                                   "client_name":"...","client_ref":"..."}
                                ]
                              }
    """
    if not tracking_no.strip():
        raise HTTPException(status_code=400, detail="AWB / Tracking number is required.")
    if not invoices:
        raise HTTPException(status_code=400, detail="At least one purchase invoice is required.")
    if carrier not in _CARRIERS:
        carrier = "Other"

    # Parse metadata JSON (best-effort)
    try:
        meta: Dict[str, Any] = json.loads(metadata) if metadata.strip() else {}
    except Exception:
        meta = {}

    purchase_blocks: List[Dict[str, Any]] = meta.get("purchase_blocks", [])
    sales_blocks:    List[Dict[str, Any]] = meta.get("sales_blocks",    [])
    # Per-slot metadata for the local-only Atlas document types. Each
    # block entry corresponds to a file in the matching UploadFile list
    # by position. Missing/short metadata is tolerated (contractor IDs
    # default to "").
    service_blocks: List[Dict[str, Any]] = meta.get("service_blocks", [])
    carnet_blocks:  List[Dict[str, Any]] = meta.get("carnet_blocks",  [])
    other_blocks:   List[Dict[str, Any]] = meta.get("other_blocks",   [])
    # Operator-supplied free-text note. Persisted to audit.json only;
    # no downstream consumer reads it yet.
    operator_note: str = str(meta.get("note") or "").strip()

    # ── Resolve shipment-level contractor identity (best-effort, optional).
    # Each purchase block may carry ``supplier_contractor_id`` and each sales
    # block ``client_contractor_id``. The shipment-level ids are inherited
    # by the AWB document only; per-document records use their own block id.
    _shipment_supplier_cid = next(
        (str(b.get("supplier_contractor_id") or "").strip()
         for b in purchase_blocks
         if str(b.get("supplier_contractor_id") or "").strip()),
        "",
    )
    _shipment_client_cid = next(
        (str(b.get("client_contractor_id") or "").strip()
         for b in sales_blocks
         if str(b.get("client_contractor_id") or "").strip()),
        "",
    )

    def _supplier_cid_for_purchase(block_idx: int) -> str:
        if 0 <= block_idx < len(purchase_blocks):
            return str(purchase_blocks[block_idx].get("supplier_contractor_id") or "").strip()
        return ""

    def _client_cid_for_sales(block_idx: int) -> str:
        if 0 <= block_idx < len(sales_blocks):
            return str(sales_blocks[block_idx].get("client_contractor_id") or "").strip()
        return ""

    # ── Validate file types ──────────────────────────────────────────────────
    for f in invoices:
        _validate_file(f, _ALLOWED_INVOICE_EXT)
    for f in packing_lists:
        _validate_file(f, _ALLOWED_PACKING_EXT)
    for f in sales_documents:
        _validate_file(f, _ALLOWED_INVOICE_EXT)
    for f in sales_packing_lists:
        _validate_file(f, _ALLOWED_PACKING_EXT)
    # Per-doc-type allow-lists (hotfix 2026-05-17). Each slot type honors
    # its own extension policy mirroring the frontend `<input accept>`.
    for f in service_invoices:
        _validate_file(f, _ALLOWED_SERVICE_EXT)
    for f in carnet_docs:
        _validate_file(f, _ALLOWED_CARNET_EXT)
    for f in other_docs:
        _validate_file(f, _ALLOWED_OTHER_EXT)
    if awb and awb.filename:
        _validate_file(awb, _ALLOWED_INVOICE_EXT)
    else:
        awb = None
    if sad and sad.filename:
        _validate_file(sad, _ALLOWED_SAD_EXT)
    else:
        sad = None

    # ── Build batch folder ───────────────────────────────────────────────────
    batch_id   = _make_batch_id(tracking_no)
    output_dir = get_output_dir(batch_id)

    src_base  = output_dir / "source"
    inv_dir   = src_base / "invoices"
    awb_dir   = src_base / "awb"
    sad_dir   = src_base / "sad"
    pack_dir  = src_base / "packing"
    sales_dir = src_base / "sales"
    service_dir = src_base / "service"
    carnet_dir  = src_base / "carnet"
    misc_dir    = src_base / "misc"
    for d in (inv_dir, awb_dir, sad_dir, pack_dir, sales_dir,
              service_dir, carnet_dir, misc_dir):
        d.mkdir(parents=True, exist_ok=True)

    awb_canonical = tracking_no.strip().replace(" ", "")

    # ── A. Save AWB PDF + parse ──────────────────────────────────────────────
    awb_name     = ""
    awb_path     = None
    awb_fields:  Dict[str, Any] = {}
    awb_doc_id   = ""

    if awb:
        awb_name = _safe_name(awb.filename)
        awb_path = awb_dir / awb_name
        await _save(awb, awb_path)
        log.info("[%s] AWB saved: %s", batch_id, awb_name)

        # Register in document_db
        awb_doc_id = ddb.register_document(
            batch_id=batch_id, document_type="awb",
            file_name=awb_name, file_path=str(awb_path),
            file_hash=ddb.sha256_file(awb_path),
            awb=awb_canonical, source="intake",
            client_contractor_id=_shipment_client_cid,
            supplier_contractor_id=_shipment_supplier_cid,
        ) or ""

        # Parse AWB fields
        awb_fields = parse_awb_pdf(awb_path)
        if awb_doc_id:
            try:
                ddb.store_awb_document(
                    document_id=awb_doc_id, batch_id=batch_id,
                    awb_data={
                        "awb":           awb_fields.get("awb_number") or awb_canonical,
                        "carrier":       awb_fields.get("carrier") or carrier,
                        "shipper_name":  awb_fields.get("shipper_name", ""),
                        "consignee_name": awb_fields.get("receiver_name", ""),
                        "pieces":        awb_fields.get("piece_count") or 0,
                        "weight_kg":     awb_fields.get("declared_weight") or 0.0,
                        "description":   awb_fields.get("contents", ""),
                        "raw_json":      json.dumps(awb_fields),
                    },
                )
                # Store extracted fields for read_field() priority
                field_map = {
                    "awb_number":         awb_fields.get("awb_number", ""),
                    "carrier":            awb_fields.get("carrier", ""),
                    "shipper_name":       awb_fields.get("shipper_name", ""),
                    "shipper_address":    awb_fields.get("shipper_address", ""),
                    "receiver_name":      awb_fields.get("receiver_name", ""),
                    "receiver_address":   awb_fields.get("receiver_address", ""),
                    "shipment_reference": awb_fields.get("shipment_reference", ""),
                    "customs_value":      str(awb_fields.get("customs_value") or ""),
                    "customs_value_gap":  awb_fields.get("customs_value_gap", ""),
                    "currency":           awb_fields.get("currency", ""),
                    "declared_weight":    str(awb_fields.get("declared_weight") or ""),
                    "piece_count":        str(awb_fields.get("piece_count") or ""),
                    "ship_date":          awb_fields.get("ship_date", ""),
                    "contents":           awb_fields.get("contents", ""),
                    "origin":             awb_fields.get("origin", ""),
                    "destination":        awb_fields.get("destination", ""),
                    "duty_account":       awb_fields.get("duty_account", ""),
                    "tax_account":        awb_fields.get("tax_account", ""),
                }
                ddb.store_fields(
                    document_id=awb_doc_id, batch_id=batch_id,
                    fields={k: v for k, v in field_map.items() if v},
                    confidence=awb_fields.get("confidence", 0.5),
                )
            except Exception as exc:
                log.warning("[%s] AWB document_db store failed (non-fatal): %s", batch_id, exc)

    # ── A2. Save SAD / ZC429 (optional) ──────────────────────────────────────
    sad_name     = ""
    sad_doc_id   = ""
    sad_summary: Dict[str, Any] = {}
    if sad:
        sad_name = _safe_name(sad.filename or "sad.pdf")
        sad_path = sad_dir / sad_name
        await _save(sad, sad_path)
        log.info("[%s] SAD saved: %s", batch_id, sad_name)
        sad_doc_type = "sad_xml" if sad_path.suffix.lower() == ".xml" else "sad_pdf"
        sad_doc_id = ddb.register_document(
            batch_id=batch_id, document_type=sad_doc_type,
            file_name=sad_name, file_path=str(sad_path),
            file_hash=ddb.sha256_file(sad_path),
            awb=awb_canonical, source="intake",
        ) or ""
        sad_summary = {"file": sad_name, "type": sad_doc_type, "doc_id": sad_doc_id}

    # ── B. Save purchase invoices + parse → invoice_lines ────────────────────
    inv_names: List[str] = []
    inv_doc_ids: List[str] = []
    inv_nos: List[str] = []           # parsed invoice numbers, parallel to inv_names
    inv_summaries: List[Dict[str, Any]] = []

    for idx, f in enumerate(invoices):
        name = _safe_name(f.filename or "invoice.pdf")
        path = inv_dir / name
        await _save(f, path)
        inv_names.append(name)
        # Map this invoice to its purchase block (block where invoice_index
        # falls within the block's contiguous invoice range).
        _supplier_cid = ""
        running = 0
        for _b_idx, _b in enumerate(purchase_blocks):
            # purchase_blocks metadata is built per-block; we walk it in
            # order. invoice_index in metadata = the first invoice index
            # of that block. Match the running counter.
            _b_inv_start = int(_b.get("invoice_index", running) or running)
            if idx >= _b_inv_start:
                _supplier_cid = _supplier_cid_for_purchase(_b_idx)
        doc_id = ddb.register_document(
            batch_id=batch_id, document_type="purchase_invoice",
            file_name=name, file_path=str(path),
            file_hash=ddb.sha256_file(path),
            awb=awb_canonical, source="intake",
            supplier_contractor_id=_supplier_cid,
        ) or ""
        inv_doc_ids.append(doc_id)
        log.info("[%s] Invoice saved: %s doc_id=%s", batch_id, name, doc_id)

        # Parse the invoice into invoice_lines so packing-list matching works
        # without waiting for PZ to run.
        inv_no_parsed = ""
        try:
            parsed = parse_invoice_pdf(path, name)
            inv_no_parsed = parsed.get("invoice_no", "")
            lines = parsed.get("lines", [])
            method = parsed.get("extraction_method", "")
            n_stored = ddb.store_invoice_lines(doc_id, batch_id, lines) if doc_id else 0
            inv_summaries.append({
                "file":         name,
                "invoice_no":   inv_no_parsed,
                "lines_parsed": len(lines),
                "lines_stored": n_stored,
                "method":       method,
                "is_real":      method != "filename_only",
            })
            # Write related_invoice_no on the document row for back-reference
            if doc_id and inv_no_parsed:
                try:
                    ddb.update_document_status(
                        document_id=doc_id,
                        related_invoice_no=inv_no_parsed,
                        extraction_status="extracted" if method != "filename_only" else "placeholder",
                    )
                except Exception:
                    pass
            # PR-205: per-line description diagnostics.  Pure, deterministic
            # check that emits warning codes when invoice_lines.description
            # looks like the overall header / customs goods description
            # instead of the per-position line text.  Never blocks intake.
            # Diagnostic blob lands in document_extraction_json.normalized_json
            # (no schema change).  Sets requires_manual_review when warn/error
            # codes fire.
            if doc_id and method != "filename_only" and lines:
                try:
                    from app.services import invoice_line_diagnostics as ild
                    diag = ild.evaluate_invoice_lines(lines)
                    if diag.get("any_warning"):
                        try:
                            ddb.merge_document_normalized_json(
                                document_id=doc_id, batch_id=batch_id,
                                blob=diag, document_type="purchase_invoice",
                            )
                        except Exception as _diag_store_exc:
                            log.warning(
                                "[%s] invoice-line diagnostics store failed "
                                "(non-fatal): %s", batch_id, _diag_store_exc,
                            )
                        if diag.get("requires_manual_review"):
                            try:
                                ddb.update_document_status(
                                    document_id=doc_id,
                                    requires_manual_review=True,
                                )
                            except Exception as _diag_flag_exc:
                                log.warning(
                                    "[%s] requires_manual_review flip failed "
                                    "(non-fatal): %s", batch_id, _diag_flag_exc,
                                )
                except Exception as _diag_exc:
                    log.warning(
                        "[%s] invoice-line diagnostics failed "
                        "(non-fatal): %s", batch_id, _diag_exc,
                    )
        except Exception as exc:
            log.warning("[%s] Invoice parse failed (non-fatal): %s — %s", batch_id, name, exc)
            inv_summaries.append({"file": name, "error": str(exc), "lines_stored": 0})

        inv_nos.append(inv_no_parsed)

    # ── C. Save + process purchase packing lists ──────────────────────────────
    packing_results: List[Dict[str, Any]] = []

    for idx, f in enumerate(packing_lists):
        # Find supplier name from metadata block
        block       = next((b for b in purchase_blocks if b.get("packing_index") == idx), {})
        supplier    = block.get("supplier_name", "")
        supplier_cid = str(block.get("supplier_contractor_id") or "").strip()
        inv_idx     = block.get("invoice_index", idx)
        inv_doc_id  = inv_doc_ids[inv_idx] if inv_idx < len(inv_doc_ids) else ""

        name = _safe_name(f.filename or f"packing_{idx}.xlsx")
        path = pack_dir / name
        content = await f.read()
        if len(content) > _MAX_BYTES:
            raise HTTPException(status_code=413, detail=f"Packing list too large.")
        path.write_bytes(content)

        # related_invoice_no must be the parsed EJL invoice number, not the
        # PDF filename. Falls back to filename only if parser failed.
        related_inv_no = (inv_nos[inv_idx] if inv_idx < len(inv_nos) else "") or \
                         (inv_names[inv_idx] if inv_idx < len(inv_names) else "")
        pack_doc_id = ddb.register_document(
            batch_id=batch_id, document_type="purchase_packing_list",
            file_name=name, file_path=str(path),
            file_hash=ddb.sha256_file(path),
            awb=awb_canonical, source="intake",
            related_invoice_no=related_inv_no,
            supplier_contractor_id=supplier_cid,
        ) or ""

        # Parse supplier_cid as int supplier_id (suppliers.id PK stored as string).
        _supplier_id: Optional[int] = None
        if supplier_cid and supplier_cid.isdigit():
            try:
                _supplier_id = int(supplier_cid)
            except ValueError:
                pass

        # Run packing extraction pipeline
        pack_summary: Dict[str, Any] = {"file": name, "status": "skipped", "rows": 0}
        try:
            result = process_packing_upload(
                batch_id=batch_id,
                batch_output_dir=output_dir,
                packing_file_path=path,
                force_reextract=False,
                supplier_id=_supplier_id,
            )
            inv_lines_source = result.get("invoice_lines_source", "unknown")
            doc_id_pdb = pdb.upsert_packing_document(**result["document"])
            rows = result.get("packing_rows", [])
            # P1: capture raw-header fingerprint artifact on failure (zero rows).
            try:
                _diag = (result.get("parser_diagnostic") or {})
                if not rows or _diag.get("failure_reason"):
                    from ..services.parser_diagnostic_writer import write_packing_diagnostic_artifact
                    write_packing_diagnostic_artifact(
                        storage_root=settings.storage_root,
                        batch_id=batch_id,
                        document_id=pack_doc_id,
                        filename=name,
                        document_type="purchase_packing_list",
                        source_path=path,
                        parser_diagnostic=_diag,
                    )
            except Exception as _exc:
                log.warning("[%s] purchase packing diagnostic artifact failed (non-fatal): %s",
                            batch_id, _exc)
            line_records = [
                {
                    "packing_document_id":   doc_id_pdb,
                    "batch_id":              batch_id,
                    "invoice_no":            r.get("invoice_no", ""),
                    "invoice_line_position": r.get("invoice_line_position"),
                    "product_code":          r.get("product_code"),
                    "design_no":             str(r.get("design_no", "") or ""),
                    "batch_no":              str(r.get("batch_no", "") or ""),
                    "bag_id":                str(r.get("bag_id", "") or ""),
                    "tray_id":               str(r.get("tray_id", "") or ""),
                    "item_type":             str(r.get("item_type", "") or ""),
                    "uom":                   str(r.get("uom", "") or ""),
                    "quantity":              _safe_float(r.get("quantity", 0)),
                    "gross_weight":          _safe_float(r.get("gross_weight", 0)),
                    "net_weight":            _safe_float(r.get("net_weight", 0)),
                    "metal":                 str(r.get("metal", "") or ""),
                    "karat":                 str(r.get("karat", "") or ""),
                    "stone_type":            str(r.get("stone_type", "") or ""),
                    "remarks":               str(r.get("remarks", "") or ""),
                    "extracted_confidence":  _safe_float(r.get("extracted_confidence", 0)),
                    "requires_manual_review": bool(r.get("requires_manual_review", False)),
                    "invoice_no_raw":        str(r.get("invoice_no", "") or ""),
                    "supplier_name":         supplier,
                    # Source-list serial (Sr / PkSr) — primary uniqueness key
                    # so two same-design rows from one source list aren't
                    # collapsed by the dedup logic.
                    "pack_sr":               r.get("line_position"),
                    "unit_price":            _safe_float(r.get("unit_price", 0)),
                    "total_value":           _safe_float(r.get("total_value", 0)),
                }
                for r in rows
            ]
            if line_records:
                pdb.upsert_packing_lines(line_records)
                seed_purchase_transit(batch_id, line_records)

            # Global Jewellery: generate Polish descriptions from packing lines
            if result.get("supplier") == "global_jewellery":
                try:
                    from ..services.description_engine import regenerate_descriptions_for_packing_lines
                    _desc = regenerate_descriptions_for_packing_lines(
                        batch_id=batch_id, dry_run=False
                    )
                    log.info("[%s] Global packing descriptions (intake): %s", batch_id, _desc)
                except Exception as _desc_exc:
                    log.warning("[%s] Global description regen failed (non-fatal): %s",
                                batch_id, _desc_exc)

            pack_summary = {
                "file":   name,
                "status": "extracted",
                "rows":   len(rows),
                "matched":   result.get("matched_count", 0),
                "unmatched": result.get("unmatched_count", 0),
                "invoice_lines_source": inv_lines_source,
            }
        except Exception as exc:
            log.warning("[%s] Packing list extraction failed (non-fatal): %s — %s", batch_id, name, exc)
            pack_summary = {"file": name, "status": "extraction_failed", "rows": 0, "error": str(exc)}

        packing_results.append(pack_summary)

    # ── D. Save sales documents ───────────────────────────────────────────────
    sales_names: List[str] = []
    sales_doc_ids: List[str] = []

    for idx, f in enumerate(sales_documents):
        block      = next((b for b in sales_blocks if b.get("document_index") == idx), {})
        client     = block.get("client_name", "")
        client_ref = block.get("client_ref", "")
        client_cid = str(block.get("client_contractor_id") or "").strip()

        name = _safe_name(f.filename or f"sales_{idx}.pdf")
        path = sales_dir / name
        await _save(f, path)
        sales_names.append(name)

        doc_id = ddb.register_document(
            batch_id=batch_id, document_type="sales_invoice",
            file_name=name, file_path=str(path),
            file_hash=ddb.sha256_file(path),
            awb=awb_canonical, source="intake",
            client_contractor_id=client_cid,
        ) or ""
        sales_doc_ids.append(doc_id)

        if doc_id:
            try:
                ddb.store_sales_document(
                    batch_id=batch_id, document_id=doc_id,
                    data={
                        "client_name":      client,
                        "client_ref":       client_ref,
                        "document_type":    "sales_invoice",
                        "source_file_path": str(path),
                        "extraction_status": "pending",
                    },
                )
            except Exception as exc:
                log.warning("[%s] sales_document store failed (non-fatal): %s", batch_id, exc)

        log.info("[%s] Sales doc saved: %s client=%s", batch_id, name, client)

    # ── E. Save sales packing lists + parse + link to client ─────────────────
    sales_pack_summaries: List[Dict[str, Any]] = []
    for idx, f in enumerate(sales_packing_lists):
        block      = next((b for b in sales_blocks if b.get("packing_index") == idx), {})
        client     = block.get("client_name", "")
        client_ref = block.get("client_ref", "")
        client_cid = str(block.get("client_contractor_id") or "").strip()
        # Operator-supplied per-document currency override (optional).
        operator_currency = (block.get("currency", "") or "").strip().upper()
        sales_idx    = block.get("document_index", idx)
        sales_doc_id = (sales_doc_ids[sales_idx]
                        if isinstance(sales_idx, int) and 0 <= sales_idx < len(sales_doc_ids)
                        else "")

        name = _safe_name(f.filename or f"sales_packing_{idx}.xlsx")
        path = sales_dir / name
        content = await f.read()
        path.write_bytes(content)

        sp_doc_id = ddb.register_document(
            batch_id=batch_id, document_type="sales_packing_list",
            file_name=name, file_path=str(path),
            file_hash=ddb.sha256_file(path),
            awb=awb_canonical, source="intake",
            client_contractor_id=client_cid,
        ) or ""

        # If no sales_documents block was uploaded, create a sales_documents
        # record from the packing-list metadata so the client/ref still gets
        # tracked in the registry.
        if not sales_doc_id and (client or client_ref):
            try:
                sales_doc_id = ddb.store_sales_document(
                    batch_id=batch_id, document_id=sp_doc_id,
                    data={
                        "client_name":      client,
                        "client_ref":       client_ref,
                        "document_type":    "sales_packing_list",
                        "source_file_path": str(path),
                        "extraction_status": "pending",
                    },
                )
            except Exception as exc:
                log.warning("[%s] sales_document auto-create failed: %s", batch_id, exc)
                sales_doc_id = ""

        # Parse the sales packing list and store rows in sales_packing_lines.
        # Uses the same EJL excel reader as the purchase side.
        n_rows = 0
        export_inv_no = ""
        currency_for_doc = ""
        currency_source = "missing"
        has_pnd = False
        pnd_summary: Dict[str, Any] = {
            "applied": False, "reason": "no PND rows",
            "pairs": [], "warnings": [],
        }
        try:
            from ..services.invoice_packing_extractor import extract_packing
            sp_rows, _, _, _sp_diag = extract_packing(path)
            # P1: write artifact on failure for sales packing too.
            try:
                if not sp_rows or (_sp_diag or {}).get("failure_reason"):
                    from ..services.parser_diagnostic_writer import write_packing_diagnostic_artifact
                    write_packing_diagnostic_artifact(
                        storage_root=settings.storage_root,
                        batch_id=batch_id,
                        document_id=sp_doc_id,
                        filename=name,
                        document_type="sales_packing_list",
                        source_path=path,
                        parser_diagnostic=_sp_diag or {},
                    )
            except Exception as _exc:
                log.warning("[%s] sales packing diagnostic artifact failed (non-fatal): %s",
                            batch_id, _exc)
            export_invs = [r.get("invoice_no", "") for r in sp_rows if r.get("invoice_no")]
            if export_invs:
                from collections import Counter
                export_inv_no = Counter(export_invs).most_common(1)[0][0]

            # ── Currency resolution ladder (per-document) ──────────────
            # 1. Excel — sheet/header detection (already on each row's
            #    "currency" field by the parser).
            # 2. Operator override — `currency` field on the sales block.
            # 3. Customer default — wfirma_customers.default_currency.
            # 4. Blank — Proforma preview will block, never silent guess.
            customer_default = ""
            try:
                from ..services import wfirma_db as _wfdb
                _cust = _wfdb.get_customer(client) if client else None
                customer_default = ((_cust or {}).get("default_currency") or "").strip().upper()
            except Exception as exc:
                log.warning("[%s] customer default-currency lookup failed: %s",
                            batch_id, exc)

            currency_source = "missing"
            currency_for_doc = ""
            # Determine the document-level currency source by looking at the
            # FIRST parsed row. The parser already labels the source per-row:
            #   excel_symbol  — cell number_format ($/€/zł) — authoritative
            #   excel_token   — header / preamble ISO token
            #   excel_row     — per-row currency cell
            # Anything Excel-supplied wins over operator and customer default.
            first_excel_currency = ""
            first_excel_source   = ""
            for _r in sp_rows:
                _ec = (str(_r.get("currency", "") or "")).strip().upper()
                if _ec:
                    first_excel_currency = _ec
                    first_excel_source   = (_r.get("currency_source")
                                              or "excel")
                    break
            # Multi-currency conflict in one file → never silently use
            # the dominant value. Operator must clarify.
            mixed_currency = any(
                _r.get("currency_conflict") for _r in sp_rows
            )
            if mixed_currency:
                currency_for_doc = ""
                currency_source  = "mixed_excel_currencies_block"
            elif first_excel_currency:
                currency_for_doc = first_excel_currency
                currency_source  = first_excel_source or "excel"
            elif operator_currency:
                currency_for_doc = operator_currency
                currency_source  = "operator"
            elif customer_default:
                currency_for_doc = customer_default
                currency_source  = "customer_default"

            # ── PND disambiguation (deterministic, gated) ──────────────
            # Build supplier candidates for the same invoice from packing.db
            # joined to invoice_lines (for unit_price). Run only when the
            # parser produced PND rows.
            from ..services.sales_pnd_disambiguator import disambiguate_pnd
            pnd_summary: Dict[str, Any] = {
                "applied": False, "reason": "no PND rows",
                "pairs": [], "warnings": [],
            }
            inv_no_for_pnd = export_inv_no
            has_pnd = any(
                str(r.get("design_no", "") or "").strip().upper() == "PND"
                for r in sp_rows
            )
            if has_pnd and inv_no_for_pnd:
                # Pull supplier-side pendants for this invoice. We use
                # invoice_lines (cost rows) joined to packing.db product_code
                # → product_code. invoice_lines item_type isn't projected,
                # but packing.packing_lines.item_type is. Build from packing
                # then attach unit_price from invoice_lines by product_code.
                supplier_candidates: List[Dict[str, Any]] = []
                try:
                    from ..services import packing_db as _pdb
                    p_rows = _pdb.get_packing_lines_for_batch(batch_id)
                    inv_price_index: Dict[str, float] = {}
                    for il in ddb.get_invoice_lines_for_batch(batch_id) or []:
                        ipc = (il.get("product_code") or "").strip()
                        if ipc and ipc not in inv_price_index:
                            inv_price_index[ipc] = float(
                                il.get("rate_usd") or il.get("unit_price") or 0
                            )
                    for pl in p_rows:
                        if (pl.get("invoice_no") or "") != inv_no_for_pnd:
                            continue
                        item_type = (pl.get("item_type") or "").strip().upper()
                        if not (item_type.startswith("PEND") or item_type == "PND"):
                            continue
                        pc = (pl.get("product_code") or "").strip()
                        supplier_candidates.append({
                            "product_code": pc,
                            "design_no":    pl.get("design_no") or "",
                            "item_type":    item_type,
                            "unit_price":   inv_price_index.get(pc, 0.0),
                        })
                except Exception as exc:
                    log.warning("[%s] supplier PND candidate load failed: %s",
                                batch_id, exc)
                # Apply disambiguator. Mutates sp_rows in-place when it fires.
                sp_rows, pnd_summary = disambiguate_pnd(
                    sp_rows, supplier_candidates, invoice_no=inv_no_for_pnd,
                )

            # ── PR-3b: Sales packing matcher (canonical pc projection) ──
            # Copy canonical product_code from same-batch purchase
            # packing_lines into sp_rows BEFORE persistence.  The PND
            # disambiguator's choice (if it fired) is preserved by the
            # matcher's existing-wins branch.  The legacy
            # "design_no as product_code" fallback below is removed —
            # rows that can't be resolved persist product_code=''.
            from ..services.sales_packing_matcher import (
                match_sales_lines_to_packing as _match_sales,
            )
            sp_rows, sales_matcher_summary = _match_sales(batch_id, sp_rows)
            if (sales_matcher_summary.get("designs_resolved")
                    or sales_matcher_summary.get("designs_ambiguous")
                    or sales_matcher_summary.get("designs_unresolved")):
                log.info("[%s] intake sales matcher: %s",
                         batch_id, sales_matcher_summary)

            if sp_rows and sales_doc_id:
                line_records = []
                for r in sp_rows:
                    row_currency = str(r.get("currency", "") or "").strip().upper()
                    final_currency = row_currency or currency_for_doc
                    line_records.append({
                        "client_name":  client,
                        "client_ref":   client_ref,
                        # Canonical product_code only.  Sources (in order
                        # of precedence, all canonical EJL/...-N codes):
                        #   1. parser-emitted pc (rare for sales)
                        #   2. PND disambiguator's choice
                        #   3. sales_packing_matcher resolution
                        # Empty when none of the above resolved — DB
                        # layer accepts empty.  design_no is NEVER used
                        # as a product_code fallback.
                        "product_code": str(r.get("product_code") or ""),
                        "design_no":    str(r.get("design_no", "") or ""),
                        "bag_id":       str(r.get("bag_id", "") or ""),
                        "quantity":     float(r.get("quantity", 0) or 0),
                        "remarks":      str(r.get("client_po", "") or r.get("remarks", "") or ""),
                        # Sales pricing (canonical — never substituted by import cost)
                        "unit_price":   float(r.get("unit_price",  0) or 0),
                        "total_value":  float(r.get("total_value", 0) or 0),
                        "currency":     final_currency,
                        "price_source": "packing_list" if (
                            float(r.get("unit_price", 0) or 0) > 0
                        ) else "",
                    })
                ddb.store_sales_packing_lines(sales_doc_id, batch_id, line_records)
                n_rows = len(line_records)
                # Phase 2 — auto-create local editable Proforma Draft.
                # Idempotent; never blocks intake on failure.
                _auto_create_draft_for_client(
                    batch_id     = batch_id,
                    client       = client,
                    client_ref   = client_ref,
                    currency     = currency_for_doc,
                    line_records = line_records,
                    operator     = "intake",
                )
        except Exception as exc:
            log.warning("[%s] sales packing parse failed (non-fatal): %s — %s",
                        batch_id, name, exc)

        sales_pack_summaries.append({
            "file":              name,
            "client_name":       client,
            "client_ref":        client_ref,
            "rows":              n_rows,
            "export_invoice_no": export_inv_no,
            # Operator-visible provenance: where the persisted currency came
            # from, and whether PND product_codes were resolved by the
            # deterministic price tiebreak (or left ambiguous).
            "currency":           currency_for_doc,
            "currency_source":    currency_source,    # excel | operator | customer_default | missing
            "pnd_mapping_source": (
                "price_tiebreak" if pnd_summary.get("applied") else
                ("ambiguous" if has_pnd else "n/a")
            ),
            "pnd_summary":        pnd_summary,
            "sales_matcher_summary": sales_matcher_summary,
            "warnings": (
                (["currency missing — Proforma will block until set"]
                 if currency_source == "missing" else [])
                + (["multiple Excel currency symbols detected — operator "
                    "must clarify before Proforma can issue"]
                   if currency_source == "mixed_excel_currencies_block"
                   else [])
                + list(pnd_summary.get("warnings") or [])
            ),
        })
        log.info("[%s] Sales packing saved: %s client=%s rows=%d",
                 batch_id, name, client or "?", n_rows)

    # ── E2. Local-only Atlas document types (service / carnet / other) ──────
    # File save + register_document only. No parser, no extractor, no
    # external workflow trigger. Contractor IDs come from per-slot metadata
    # (service → supplier; carnet/other → shipment-level inherit unless
    # overridden in the block).
    service_doc_ids: List[str] = []
    carnet_doc_ids:  List[str] = []
    other_doc_ids:   List[str] = []

    async def _persist_local_async(
        files: List[UploadFile],
        dest_dir: Path,
        document_type: str,
        blocks: List[Dict[str, Any]],
        *,
        is_supplier_side: bool,
    ) -> List[str]:
        out_ids: List[str] = []
        for idx, f in enumerate(files):
            if not (f and f.filename):
                continue
            name = _safe_name(f.filename)
            path = dest_dir / name
            await _save(f, path)
            block = blocks[idx] if 0 <= idx < len(blocks) else {}
            sup_cid = str(block.get("supplier_contractor_id") or "").strip()
            cli_cid = str(block.get("client_contractor_id")   or "").strip()
            # Neutral docs (carnet / other) inherit shipment-level IDs from
            # both sides when the per-slot block did not specify one.
            if not sup_cid and not is_supplier_side:
                sup_cid = _shipment_supplier_cid
            if not cli_cid and not is_supplier_side:
                cli_cid = _shipment_client_cid
            if is_supplier_side and not sup_cid:
                sup_cid = _shipment_supplier_cid
            doc_id = ddb.register_document(
                batch_id=batch_id, document_type=document_type,
                file_name=name, file_path=str(path),
                file_hash=ddb.sha256_file(path),
                awb=awb_canonical, source="intake",
                client_contractor_id=cli_cid,
                supplier_contractor_id=sup_cid,
            ) or ""
            if doc_id:
                out_ids.append(doc_id)
                log.info("[%s] %s saved: %s doc_id=%s",
                         batch_id, document_type, name, doc_id)
        return out_ids

    service_doc_ids = await _persist_local_async(
        service_invoices, service_dir, "service_invoice", service_blocks,
        is_supplier_side=True,
    )
    carnet_doc_ids = await _persist_local_async(
        carnet_docs, carnet_dir, "carnet", carnet_blocks,
        is_supplier_side=False,
    )
    other_doc_ids = await _persist_local_async(
        other_docs, misc_dir, "other_document", other_blocks,
        is_supplier_side=False,
    )

    # ── E3. Seed packing_contractor_resolution from operator's dropdown picks
    # The ContractorResolutionPanel reads packing_contractor_resolution (the
    # R2 resolver's output table). Atlas intake captures contractor IDs from
    # master-data dropdowns directly — treat that as an explicit operator
    # confirmation so the panel shows the picked identities without forcing
    # a redundant "Resolve" click. No resolver algorithm runs here; no
    # wFirma call; no contractor record is created. Failure is non-fatal.
    try:
        from ..services import packing_resolution_db as prdb
        _pr_db_path = settings.storage_root / "packing_resolutions.sqlite"

        def _resolve_master_row(contractor_id: str, role: str) -> Dict[str, Any]:
            """Look up the operator-picked master-data row for this role.
            Returns a dict with at least {name, country, vat_id} or empty
            on miss. Read-only against existing master tables; no writes."""
            if not contractor_id:
                return {}
            try:
                if role == "client":
                    from ..services.customer_master_db import get_customer
                    _cm_path = settings.storage_root / "customer_master.sqlite"
                    rec = get_customer(_cm_path, contractor_id)
                    if rec is None:
                        return {}
                    return {
                        "name":     getattr(rec, "bill_to_name", "") or "",
                        "country":  getattr(rec, "country", "") or "",
                        "vat_id":   getattr(rec, "nip", "") or getattr(rec, "vat_eu_number", "") or "",
                    }
                # supplier — main canonical MasterData-B4 store
                from ..services.suppliers_db import get_supplier
                _sup_path = settings.storage_root / "suppliers.sqlite"
                # contractor_id may be the str(id); accept int conversion
                try:
                    sup_id = int(contractor_id)
                except (TypeError, ValueError):
                    return {}
                rec = get_supplier(_sup_path, sup_id)
                if rec is None:
                    return {}
                return {
                    "name":    getattr(rec, "name", "") or "",
                    "country": getattr(rec, "country", "") or "",
                    "vat_id":  getattr(rec, "vat_id", "") or "",
                }
            except Exception as exc:
                log.warning("[%s] master-data lookup failed for %s=%r: %s",
                            batch_id, role, contractor_id, exc)
                return {}

        # Supplier: prefer the shipment-level id, else first non-empty
        # per-block id (already resolved at the top of the route).
        sup_cid = _shipment_supplier_cid or next(
            (str(b.get("supplier_contractor_id") or "").strip()
             for b in purchase_blocks
             if str(b.get("supplier_contractor_id") or "").strip()),
            "",
        )
        cli_cid = _shipment_client_cid or next(
            (str(b.get("client_contractor_id") or "").strip()
             for b in sales_blocks
             if str(b.get("client_contractor_id") or "").strip()),
            "",
        )

        def _seed(role: str, contractor_id: str) -> None:
            if not contractor_id:
                return
            master = _resolve_master_row(contractor_id, role)
            parsed_name = master.get("name") or contractor_id   # fallback so
            # upsert_resolution's required parsed_name is satisfied even when
            # master-data lookup missed (operator can still see the id).
            verdict = {
                "parsed_name":         parsed_name,
                "parsed_tax_id":       master.get("vat_id") or None,
                "parsed_country":      master.get("country") or None,
                "matched_master_type": "customer_master" if role == "client" else "suppliers",
                "matched_master_id":   contractor_id,
                "tier":                1,        # exact-id match
                "confidence":          1.0,      # operator-confirmed
                "reason":              "atlas_intake_dropdown_pick",
                "evidence":            {"source": "intake_dropdown"},
                "candidates":          [],
                "status":              "confirmed",
            }
            prdb.upsert_resolution(
                _pr_db_path,
                batch_id          = batch_id,
                role              = role,
                verdict           = verdict,
                operator_user     = "intake",
                operator_override = False,
                status_override   = "confirmed",
            )
            log.info("[%s] contractor-resolution seeded: role=%s id=%s name=%s",
                     batch_id, role, contractor_id, parsed_name)

        _seed("supplier", sup_cid)
        _seed("client",   cli_cid)
    except Exception as exc:
        log.warning("[%s] contractor-resolution seed failed (non-fatal): %s",
                    batch_id, exc)

    # ── F. Write draft audit + timeline ──────────────────────────────────────
    _write_draft_audit(output_dir, batch_id, tracking_no, carrier, inv_names, awb_name)
    audit_path = output_dir / "audit.json"
    if sad_name:
        _mark_agency_documents_received(audit_path, batch_id, sad_name, sad_dir / sad_name)
    tl.log_event(audit_path, tl.EV_BATCH_CREATED, "intake", "user",
                 detail={
                     "tracking_no": tracking_no, "carrier": carrier,
                     "invoices": len(inv_names), "packing_lists": len(packing_lists),
                     "sales_docs": len(sales_names),
                 })
    for n in inv_names:
        tl.log_event(audit_path, tl.EV_INVOICE_UPLOADED, "intake", "user", detail={"file": n})
    if awb_name:
        tl.log_event(audit_path, tl.EV_AWB_UPLOADED, "intake", "user", detail={"file": awb_name})

    # Persist operator note + local-only doc counts into audit.json so the
    # information survives without requiring a new column on any DB table.
    try:
        if operator_note or service_doc_ids or carnet_doc_ids or other_doc_ids:
            audit_obj: Dict[str, Any] = {}
            if audit_path.exists():
                try:
                    audit_obj = json.loads(audit_path.read_text(encoding="utf-8"))
                except Exception:
                    audit_obj = {}
            if operator_note:
                audit_obj["operator_note"] = operator_note
            local_summary = audit_obj.get("local_documents") or {}
            if service_doc_ids:
                local_summary["service_invoice"] = service_doc_ids
            if carnet_doc_ids:
                local_summary["carnet"] = carnet_doc_ids
            if other_doc_ids:
                local_summary["other_document"] = other_doc_ids
            if local_summary:
                audit_obj["local_documents"] = local_summary
            write_json_atomic(audit_path, audit_obj)
    except Exception as exc:
        log.warning("[%s] audit metadata update failed (non-fatal): %s",
                    batch_id, exc)

    # ── G. Return intake summary ──────────────────────────────────────────────
    # ── F2. Rule-based reverification (WF1.3) — post-parse advisory check
    # Runs rule_based_reverification against the freshly-parsed batch.
    # Proposals written to audit.json so they appear in the Inbox.
    # Best-effort: never blocks the intake response.
    try:
        from ..services.rule_based_reverification import (
            reverify_purchase_batch,
            write_reverification_proposals_to_audit,
        )
        if audit_path.exists():
            _rev_audit = json.loads(audit_path.read_text(encoding="utf-8"))
            _proposals = reverify_purchase_batch(batch_id, _rev_audit, settings.storage_root)
            if _proposals:
                added = write_reverification_proposals_to_audit(_rev_audit, _proposals)
                if added:
                    write_json_atomic(audit_path, _rev_audit)
    except Exception as _rev_exc:
        log.warning("[%s] rule_based_reverification failed (non-fatal): %s",
                    batch_id, _rev_exc)

    return JSONResponse({
        "ok":            True,
        "batch_id":      batch_id,
        "tracking_no":   tracking_no,
        "carrier":       carrier,
        "awb": {
            "file":       awb_name,
            "awb_number": awb_fields.get("awb_number", awb_canonical),
            "carrier":    awb_fields.get("carrier", carrier),
            "shipper":    awb_fields.get("shipper_name", ""),
            "receiver":   awb_fields.get("receiver_name", ""),
            "value_usd":  awb_fields.get("customs_value"),
            "weight_kg":  awb_fields.get("declared_weight"),
            "confidence": awb_fields.get("confidence", 0.0),
        } if awb_name else None,
        "sad": sad_summary or None,
        "purchase": {
            "invoices":         inv_names,
            "invoice_parsed":   inv_summaries,
            "packing_lists":    packing_results,
        },
        "sales": {
            "documents":     sales_names,
            "packing_lists": sales_pack_summaries,
        },
        "local_documents": {
            "service_invoice": len(service_doc_ids),
            "carnet":          len(carnet_doc_ids),
            "other_document":  len(other_doc_ids),
        },
        "operator_note": operator_note,
        "documents_registered": (
            (1 if awb_name else 0) +
            len(inv_names) +
            len(packing_lists) +
            len(sales_names) +
            len(sales_packing_lists) +
            len(service_doc_ids) +
            len(carnet_doc_ids) +
            len(other_doc_ids)
        ),
        "status": "draft",
        "next_step": "Upload SAD when customs clearance documents are received.",
    })


# ── Backfill: add packing list to an existing batch ──────────────────────────

@router.post("/{batch_id}/packing_list", dependencies=[_auth])
async def add_packing_list(
    batch_id:       str,
    file:           UploadFile,
    supplier_name:  str = Form(default=""),
    invoice_index:  int = Form(default=0),
) -> JSONResponse:
    """
    Attach a packing list to an existing batch (backfill).
    Works for batches in any status — does not block or alter PZ.

    invoice_index: 0-based index into the batch's invoice list (informational only).
    """
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    _validate_file(file, _ALLOWED_PACKING_EXT)

    output_dir = get_output_dir(batch_id)
    if not output_dir.exists():
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found.")

    # Load audit to get AWB
    audit_path = output_dir / "audit.json"
    awb_canonical = ""
    if audit_path.exists():
        try:
            import json as _json
            audit = _json.loads(audit_path.read_text(encoding="utf-8"))
            awb_canonical = str(audit.get("awb") or "")
        except Exception:
            pass

    pack_dir = output_dir / "source" / "packing"
    pack_dir.mkdir(parents=True, exist_ok=True)

    name = _safe_name(file.filename or "packing_list.xlsx")
    path = pack_dir / name
    content = await file.read()
    if len(content) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large.")
    path.write_bytes(content)

    # Register in document_db
    doc_id = ddb.register_document(
        batch_id=batch_id, document_type="purchase_packing_list",
        file_name=name, file_path=str(path),
        file_hash=ddb.sha256_file(path),
        awb=awb_canonical, source="backfill",
    ) or ""

    # Run packing extraction (DB-first match, pz_rows.json fallback for legacy)
    result_summary: Dict[str, Any] = {"status": "skipped", "rows": 0}
    try:
        result = process_packing_upload(
            batch_id=batch_id,
            batch_output_dir=output_dir,
            packing_file_path=path,
            force_reextract=False,
        )
        inv_lines_source = result.get("invoice_lines_source", "unknown")
        doc_id_pdb = pdb.upsert_packing_document(**result["document"])
        rows = result.get("packing_rows", [])
        if rows:
            line_records = [
                {
                    "packing_document_id":   doc_id_pdb,
                    "batch_id":              batch_id,
                    "invoice_no":            r.get("invoice_no", ""),
                    "invoice_line_position": r.get("invoice_line_position"),
                    "product_code":          r.get("product_code"),
                    "design_no":             str(r.get("design_no", "") or ""),
                    "batch_no":              str(r.get("batch_no", "") or ""),
                    "bag_id":                str(r.get("bag_id", "") or ""),
                    "tray_id":               str(r.get("tray_id", "") or ""),
                    "item_type":             str(r.get("item_type", "") or ""),
                    "uom":                   str(r.get("uom", "") or ""),
                    "quantity":              _safe_float(r.get("quantity", 0)),
                    "gross_weight":          _safe_float(r.get("gross_weight", 0)),
                    "net_weight":            _safe_float(r.get("net_weight", 0)),
                    "metal":                 str(r.get("metal", "") or ""),
                    "karat":                 str(r.get("karat", "") or ""),
                    "stone_type":            str(r.get("stone_type", "") or ""),
                    "remarks":               str(r.get("remarks", "") or ""),
                    "extracted_confidence":  _safe_float(r.get("extracted_confidence", 0)),
                    "requires_manual_review": bool(r.get("requires_manual_review", False)),
                    "invoice_no_raw":        str(r.get("invoice_no", "") or ""),
                    "supplier_name":         supplier_name,
                }
                for r in rows
            ]
            pdb.upsert_packing_lines(line_records)
            seed_purchase_transit(batch_id, line_records)

            # Global Jewellery: generate descriptions from packing lines (non-blocking)
            if result.get("supplier") == "global_jewellery":
                try:
                    from ..services.description_engine import regenerate_descriptions_for_packing_lines
                    _desc = regenerate_descriptions_for_packing_lines(
                        batch_id=batch_id, dry_run=False
                    )
                    log.info("[%s] Global packing descriptions (backfill): %s", batch_id, _desc)
                except Exception as _desc_exc:
                    log.warning("[%s] Global description regen failed (non-fatal): %s",
                                batch_id, _desc_exc)
        result_summary = {
            "status":               "extracted",
            "rows":                 len(rows),
            "matched":              result.get("matched_count", 0),
            "unmatched":            result.get("unmatched_count", 0),
            "invoice_lines_source": inv_lines_source,
        }
    except Exception as exc:
        log.warning("[%s] Backfill packing extraction failed: %s — %s", batch_id, name, exc)
        result_summary = {"status": "extraction_failed", "rows": 0, "error": str(exc)}

    # Timeline event
    if audit_path.exists():
        try:
            tl.log_event(
                audit_path, "packing_list_backfilled", "dashboard", "user",
                detail={"file": name, "rows": result_summary.get("rows", 0)},
            )
        except Exception:
            pass

    return JSONResponse({
        "ok":       True,
        "batch_id": batch_id,
        "file":     name,
        "doc_id":   doc_id,
        "extraction": result_summary,
    })


# ── Generic add-document endpoint (post-draft) ────────────────────────────────
#
# Single endpoint that adds ONE source document to an existing batch.
# Reuses the same persistence + parser code paths the New Shipment intake
# already uses (_validate_file, _safe_name, _save, ddb.register_document,
# process_packing_upload, parse_invoice_pdf, ddb.store_invoice_lines,
# parse_awb_pdf, ddb.store_awb_document, ddb.store_sales_document). No new
# external integrations. Parser failure is non-fatal.

# Per-doc-type config table. Each entry declares the canonical save dir,
# the extension allow-list (reuses module-level constants), which contractor
# side(s) inherit when the form omits an explicit id, and which parser hook
# fires.
_ADD_DOC_POLICY: Dict[str, Dict[str, Any]] = {
    "purchase_invoice": {
        "subdir": "invoices", "exts": _ALLOWED_INVOICE_EXT,
        "supplier_side": True,  "client_side": False,  "parser": "invoice",
    },
    "purchase_packing_list": {
        "subdir": "packing",  "exts": _ALLOWED_PACKING_EXT,
        "supplier_side": True,  "client_side": False,  "parser": "packing",
    },
    "sales_invoice": {
        "subdir": "sales",    "exts": _ALLOWED_INVOICE_EXT,
        "supplier_side": False, "client_side": True,   "parser": "sales_document",
    },
    "sales_proforma": {
        "subdir": "sales",    "exts": _ALLOWED_INVOICE_EXT,
        "supplier_side": False, "client_side": True,   "parser": "sales_document",
    },
    "sales_packing_list": {
        "subdir": "sales",    "exts": _ALLOWED_PACKING_EXT,
        "supplier_side": False, "client_side": True,   "parser": "packing",
    },
    "awb": {
        "subdir": "awb",      "exts": _ALLOWED_INVOICE_EXT,
        "supplier_side": True,  "client_side": True,   "parser": "awb",
    },
    "service_invoice": {
        "subdir": "service",  "exts": _ALLOWED_SERVICE_EXT,
        "supplier_side": True,  "client_side": False,  "parser": None,
    },
    "carnet": {
        "subdir": "carnet",   "exts": _ALLOWED_CARNET_EXT,
        "supplier_side": True,  "client_side": True,   "parser": None,
    },
    "other_document": {
        "subdir": "misc",     "exts": _ALLOWED_OTHER_EXT,
        "supplier_side": True,  "client_side": True,   "parser": None,
    },
}


def _inherit_contractor_ids(
    batch_id:                str,
    document_type:           str,
    explicit_supplier_cid:   str,
    explicit_client_cid:     str,
) -> tuple[str, str]:
    """Resolve final supplier/client contractor IDs for a per-document
    add-document call.

    Order (matches the inspection report §5):
      1. Explicit form-supplied id wins (empty string treated as
         "not provided" and falls through).
      2. Inherit confirmed id from packing_contractor_resolution per
         the document_type's policy side(s).
      3. Empty string.
    """
    policy = _ADD_DOC_POLICY[document_type]
    sup_out = (explicit_supplier_cid or "").strip()
    cli_out = (explicit_client_cid   or "").strip()
    if sup_out and cli_out:
        return sup_out, cli_out

    try:
        from ..services import packing_resolution_db as prdb
        _pr_db = settings.storage_root / "packing_resolutions.sqlite"
        if not sup_out and policy["supplier_side"]:
            row = prdb.get_resolution(_pr_db, batch_id=batch_id, role="supplier")
            if row and row.get("matched_master_id"):
                sup_out = str(row["matched_master_id"])
        if not cli_out and policy["client_side"]:
            row = prdb.get_resolution(_pr_db, batch_id=batch_id, role="client")
            if row and row.get("matched_master_id"):
                cli_out = str(row["matched_master_id"])
    except Exception as exc:
        log.warning("[%s] contractor-id inheritance failed (non-fatal): %s",
                    batch_id, exc)
    return sup_out, cli_out


@router.post("/{batch_id}/add-document", dependencies=[_auth])
async def add_document_to_batch(
    batch_id:                str,
    file:                    UploadFile,
    document_type:           str = Form(...),
    supplier_contractor_id:  str = Form(default=""),
    client_contractor_id:    str = Form(default=""),
    invoice_index:           int = Form(default=0),
) -> JSONResponse:
    """Attach a single source document to an existing batch.

    Display-side button lands in a separate PR. This endpoint is the
    canonical write surface for post-draft document additions.

    Validation:
      * batch_id format / existence
      * document_type is in _ADD_DOC_POLICY (NOT 'sad' — use SAD route)
      * file extension matches the doc-type allow-list

    Returns 200 with shipment_documents id + parser_status + lines_count
    when applicable. Parser failure is non-fatal (extraction_failed +
    log). No DHL / wFirma / proforma / PZ / SAD trigger from this path.
    """
    # ── Validate batch_id ────────────────────────────────────────────────
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    # ── Validate document_type ───────────────────────────────────────────
    if document_type == "sad":
        raise HTTPException(
            status_code=422,
            detail="SAD documents must be uploaded via the SAD-specific "
                   "route, not /add-document.",
        )
    if document_type not in _ADD_DOC_POLICY:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown document_type {document_type!r}. Allowed: "
                   + ", ".join(sorted(_ADD_DOC_POLICY.keys())),
        )

    policy = _ADD_DOC_POLICY[document_type]

    # ── Validate file ────────────────────────────────────────────────────
    if not (file and file.filename):
        raise HTTPException(status_code=400, detail="File has no name.")
    _validate_file(file, policy["exts"])

    # ── Resolve batch dir ────────────────────────────────────────────────
    # Canonical "batch exists" marker is audit.json; the output dir alone
    # is auto-created by get_output_dir, so checking dir.exists() is not
    # a real existence test.
    audit_path = settings.storage_root / "outputs" / batch_id / "audit.json"
    if not audit_path.exists():
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found.")
    output_dir = get_output_dir(batch_id)

    # Pull AWB from audit for register_document (best-effort).
    awb_canonical = ""
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        awb_canonical = str(audit.get("awb") or "")
    except Exception:
        pass

    # ── Save file to disk ────────────────────────────────────────────────
    dest_dir = output_dir / "source" / policy["subdir"]
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = _safe_name(file.filename)
    path = dest_dir / name
    await _save(file, path)

    # ── Resolve contractor IDs ───────────────────────────────────────────
    sup_cid, cli_cid = _inherit_contractor_ids(
        batch_id=batch_id, document_type=document_type,
        explicit_supplier_cid=supplier_contractor_id,
        explicit_client_cid=client_contractor_id,
    )

    # ── Register in shipment_documents ───────────────────────────────────
    doc_id = ddb.register_document(
        batch_id=batch_id, document_type=document_type,
        file_name=name, file_path=str(path),
        file_hash=ddb.sha256_file(path),
        awb=awb_canonical, source="add_document",
        client_contractor_id=cli_cid,
        supplier_contractor_id=sup_cid,
    ) or ""
    log.info("[%s] add-document registered: type=%s file=%s doc_id=%s",
             batch_id, document_type, name, doc_id)

    # ── Optional parser hook (non-fatal) ─────────────────────────────────
    parser_status: str = "skipped"
    lines_count:   Optional[int] = None
    extraction_summary: Dict[str, Any] = {}

    if policy["parser"] == "invoice":
        try:
            # Supplier detection: route Global invoices to dedicated parser
            _pdf_preview = _read_pdf_text_preview(path)
            _supplier = detect_supplier(_pdf_preview)
            if _supplier == "global_jewellery":
                parsed = parse_global_invoice_pdf(path, name)
            else:
                parsed = parse_invoice_pdf(path, name)  # EJL default — unchanged
            lines = parsed.get("lines", [])
            method = parsed.get("extraction_method", "")
            n_stored = ddb.store_invoice_lines(doc_id, batch_id, lines) if doc_id else 0
            lines_count = n_stored
            parser_status = "extracted" if method and method != "filename_only" else "placeholder"
            extraction_summary = {
                "invoice_no": parsed.get("invoice_no", ""),
                "lines":      n_stored,
                "method":     method,
            }
            if doc_id and parsed.get("invoice_no"):
                try:
                    ddb.update_document_status(
                        document_id=doc_id,
                        related_invoice_no=parsed["invoice_no"],
                        extraction_status=parser_status,
                    )
                except Exception:
                    pass
            # PR-205: per-line description diagnostics — mirror of the
            # batch-upload path above.  Pure / additive / never blocks.
            if doc_id and method != "filename_only" and lines:
                try:
                    from app.services import invoice_line_diagnostics as ild
                    diag = ild.evaluate_invoice_lines(lines)
                    if diag.get("any_warning"):
                        try:
                            ddb.merge_document_normalized_json(
                                document_id=doc_id, batch_id=batch_id,
                                blob=diag, document_type="purchase_invoice",
                            )
                        except Exception as _diag_store_exc:
                            log.warning(
                                "[%s] invoice-line diagnostics store failed "
                                "(non-fatal): %s", batch_id, _diag_store_exc,
                            )
                        if diag.get("requires_manual_review"):
                            try:
                                ddb.update_document_status(
                                    document_id=doc_id,
                                    requires_manual_review=True,
                                )
                            except Exception as _diag_flag_exc:
                                log.warning(
                                    "[%s] requires_manual_review flip failed "
                                    "(non-fatal): %s", batch_id, _diag_flag_exc,
                                )
                except Exception as _diag_exc:
                    log.warning(
                        "[%s] invoice-line diagnostics failed "
                        "(non-fatal): %s", batch_id, _diag_exc,
                    )
        except Exception as exc:
            log.warning("[%s] invoice parse failed (non-fatal): %s — %s",
                        batch_id, name, exc)
            parser_status = "extraction_failed"
            extraction_summary = {"error": str(exc)}

    elif policy["parser"] == "packing":
        try:
            result = process_packing_upload(
                batch_id=batch_id,
                batch_output_dir=output_dir,
                packing_file_path=path,
            )
            lines_count = int(result.get("packing_rows_count") or
                              len(result.get("packing_rows") or []))
            parser_status = "extracted" if lines_count > 0 else "placeholder"
            extraction_summary = {
                "matched":   result.get("matched_count", 0),
                "unmatched": result.get("unmatched_count", 0),
                "rows":      lines_count,
            }
        except Exception as exc:
            log.warning("[%s] packing parse failed (non-fatal): %s — %s",
                        batch_id, name, exc)
            parser_status = "extraction_failed"
            extraction_summary = {"error": str(exc)}

    elif policy["parser"] == "sales_document":
        try:
            if doc_id:
                ddb.store_sales_document(
                    batch_id=batch_id, document_id=doc_id,
                    data={
                        "client_name":      "",
                        "client_ref":       "",
                        "document_type":    document_type,
                        "source_file_path": str(path),
                        "extraction_status": "pending",
                    },
                )
            parser_status = "stored"
        except Exception as exc:
            log.warning("[%s] sales_document store failed (non-fatal): %s",
                        batch_id, exc)
            parser_status = "extraction_failed"
            extraction_summary = {"error": str(exc)}

    elif policy["parser"] == "awb":
        try:
            awb_fields = parse_awb_pdf(path)
            if doc_id:
                ddb.store_awb_document(
                    document_id=doc_id, batch_id=batch_id,
                    awb_data={
                        "awb":            awb_fields.get("awb_number") or awb_canonical,
                        "carrier":        awb_fields.get("carrier") or "",
                        "shipper_name":   awb_fields.get("shipper_name", ""),
                        "consignee_name": awb_fields.get("receiver_name", ""),
                        "pieces":         awb_fields.get("piece_count") or 0,
                        "weight_kg":      awb_fields.get("declared_weight") or 0.0,
                        "description":    awb_fields.get("contents", ""),
                        "raw_json":       json.dumps(awb_fields),
                    },
                )
            parser_status = "stored"
            extraction_summary = {
                "awb_number": awb_fields.get("awb_number", ""),
                "shipper":    awb_fields.get("shipper_name", ""),
            }
        except Exception as exc:
            log.warning("[%s] awb parse failed (non-fatal): %s — %s",
                        batch_id, name, exc)
            parser_status = "extraction_failed"
            extraction_summary = {"error": str(exc)}

    else:
        # Local-only types (service_invoice / carnet / other_document):
        # file is saved + registered, no parser runs.
        parser_status = "local_only"

    # ── Append timeline event (non-fatal) ────────────────────────────────
    try:
        if audit_path.exists():
            tl.log_event(
                audit_path, "document_uploaded", "add_document", "user",
                detail={
                    "file":           name,
                    "document_type":  document_type,
                    "document_id":    doc_id,
                    "parser_status":  parser_status,
                    "lines_count":    lines_count,
                },
            )
    except Exception as exc:
        log.warning("[%s] timeline log failed (non-fatal): %s", batch_id, exc)

    return JSONResponse({
        "ok":             True,
        "batch_id":       batch_id,
        "document_id":    doc_id,
        "document_type":  document_type,
        "file_name":      name,
        "parser_status":  parser_status,
        "lines_count":    lines_count,
        "extraction":     extraction_summary,
        "contractor": {
            "supplier_contractor_id": sup_cid,
            "client_contractor_id":   cli_cid,
        },
    })



# ── Sales-packing re-ingest ────────────────────────────────────────────────
#
# Idempotent backfill / correction path. Replaces sales_packing_lines for
# (batch_id, sales_document_id) using the SAME parser + currency ladder +
# PND tiebreak the main intake route uses. Never creates a new batch;
# never touches unrelated clients or unrelated batches.

@router.post("/sales-packing/reingest", dependencies=[_auth])
async def sales_packing_reingest(
    batch_id:           str                = Form(...),
    metadata:           str                = Form(default="{}"),
    files:              List[UploadFile]   = [],
    override_currency:  str                = Form(default=""),
    x_operator:         Optional[str]      = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """
    Re-parse and atomically replace sales_packing_lines for an EXISTING
    batch. Each file is matched to a sales_document via metadata blocks
    (``client_name`` + optional ``client_ref``).

    Body (multipart/form-data):
      batch_id           — existing SHIPMENT_… batch id (required)
      files[]            — sales packing list spreadsheets (.xlsx / .xls)
      metadata           — JSON: {"sales_blocks":[{"packing_index":0,
                                                    "client_name":"...",
                                                    "client_ref":"...",
                                                    "currency":"EUR"}]}
      override_currency  — optional 3-letter ISO; only honoured when Excel
                           detection produced a multi-currency conflict.

    Returns per-file: deleted_count, inserted_count, before_count,
    currency, currency_source, currency_conflict, warnings, pnd_summary.

    Mixed-currency files (parser flagged conflict) are SKIPPED unless the
    operator supplied ``override_currency``.
    """
    if not (batch_id or "").strip():
        raise HTTPException(status_code=400, detail="batch_id is required")
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="invalid batch_id")
    if not files:
        raise HTTPException(status_code=400, detail="no files provided")
    for f in files:
        _validate_file(f, _ALLOWED_PACKING_EXT)

    try:
        meta: Dict[str, Any] = json.loads(metadata) if metadata.strip() else {}
    except Exception:
        meta = {}
    sales_blocks: List[Dict[str, Any]] = meta.get("sales_blocks", [])

    output_dir = get_output_dir(batch_id)
    sales_dir  = output_dir / "source" / "sales"
    sales_dir.mkdir(parents=True, exist_ok=True)

    # Index existing sales_documents by client_name (case- and
    # whitespace-tolerant) so the operator doesn't need to supply
    # the exact stored key.
    existing_docs = ddb.get_sales_documents(batch_id)
    by_client: Dict[str, List[Dict[str, Any]]] = {}
    for d in existing_docs:
        key = (d.get("client_name") or "").strip().upper()
        if not key:
            continue
        by_client.setdefault(key, []).append(d)

    override_ccy = (override_currency or "").strip().upper()
    if override_ccy and override_ccy not in {"EUR", "USD", "PLN", "GBP",
                                              "CHF", "JPY"}:
        raise HTTPException(
            status_code=400,
            detail=f"override_currency {override_currency!r} not in allowed set",
        )

    operator = (x_operator or "").strip()

    results: List[Dict[str, Any]] = []
    for idx, f in enumerate(files):
        block      = next((b for b in sales_blocks
                            if b.get("packing_index") == idx), {})
        client     = (block.get("client_name", "") or "").strip()
        client_ref = (block.get("client_ref",  "") or "").strip()
        operator_ccy = (block.get("currency", "") or "").strip().upper()

        per_file: Dict[str, Any] = {
            "file":              f.filename,
            "client_name":       client,
            "client_ref":        client_ref,
            "deleted_count":     0,
            "inserted_count":    0,
            "before_count":      0,
            "currency":          "",
            "currency_source":   "missing",
            "currency_conflict": False,
            "warnings":          [],
            "pnd_summary":       {"applied": False, "reason": "not run"},
        }

        if not client:
            per_file["warnings"].append("client_name missing in metadata")
            results.append(per_file); continue

        # Resolve sales_document_id by client_name. Refuse if multiple match.
        candidates = by_client.get(client.upper(), [])
        if not candidates:
            # ── Orphan-repair: operator may supply sales_document_id to fix
            # a row whose client_name was never set at initial upload time
            # (e.g. metadata block omitted client_name during intake).
            # When provided, update client_name on the existing document and
            # proceed — this is the reconciliation path for empty-client rows.
            supplied_doc_id = (block.get("sales_document_id") or "").strip()
            if supplied_doc_id:
                orphan = next(
                    (d for d in existing_docs if d.get("id") == supplied_doc_id),
                    None,
                )
                if orphan is not None:
                    # Defense-in-depth: existing_docs is already batch-scoped
                    # but verify explicitly before any write.
                    if orphan.get("batch_id") != batch_id:
                        per_file["warnings"].append(
                            f"sales_document_id {supplied_doc_id!r} "
                            "does not belong to this batch")
                        results.append(per_file); continue
                    _updated = ddb.update_sales_document_client_name(
                        supplied_doc_id, client,
                    )
                    candidates = [orphan]
                    per_file["client_name_repaired"] = _updated
                    per_file["repaired_from_doc_id"] = supplied_doc_id
                    if not _updated:
                        per_file["warnings"].append(
                            "orphan client_name DB update returned False "
                            "— lines will still be inserted but "
                            "sales_documents.client_name may remain empty")
                    log.info(
                        "[%s] reingest orphan-repair: doc_id=%s client=%s "
                        "db_updated=%s",
                        batch_id, supplied_doc_id, client, _updated,
                    )
                else:
                    per_file["warnings"].append(
                        f"sales_document_id {supplied_doc_id!r} not found in batch")
                    results.append(per_file); continue
            else:
                per_file["warnings"].append(
                    f"no sales_document found for client {client!r} in batch")
                results.append(per_file); continue
        if len(candidates) > 1:
            per_file["warnings"].append(
                f"multiple sales_documents for client {client!r} — "
                "refusing to auto-pick")
            results.append(per_file); continue
        sales_doc = candidates[0]
        sales_doc_id = sales_doc.get("id") or ""
        if not sales_doc_id:
            per_file["warnings"].append("resolved sales_document has no id")
            results.append(per_file); continue

        # Save the file under the existing batch's sales folder so the
        # source-of-truth is preserved. Overwrite is intentional.
        name = _safe_name(f.filename or f"sales_packing_reingest_{idx}.xlsx")
        path = sales_dir / name
        path.write_bytes(await f.read())

        # Parse via the same extractor — this picks up the cell-format
        # currency symbol fix that landed earlier.
        try:
            from ..services.invoice_packing_extractor import extract_packing
            sp_rows, _, _, _sp_diag = extract_packing(path)
        except Exception as exc:
            per_file["warnings"].append(f"parse failed: {exc}")
            results.append(per_file); continue

        # Currency ladder (Excel symbol > Excel token > operator > default
        # > blank). Pre-existing route logic is the source-of-truth for
        # this; we mirror it here so the re-ingest path stays consistent.
        from ..services import wfirma_db as _wfdb
        customer_default = ""
        try:
            _cust = _wfdb.get_customer(client) if client else None
            customer_default = ((_cust or {}).get("default_currency") or "").strip().upper()
        except Exception:
            pass

        first_excel_currency = ""
        first_excel_source   = ""
        for _r in sp_rows:
            _ec = (str(_r.get("currency", "") or "")).strip().upper()
            if _ec:
                first_excel_currency = _ec
                first_excel_source   = (_r.get("currency_source") or "excel")
                break
        mixed = any(_r.get("currency_conflict") for _r in sp_rows)

        if mixed and not override_ccy:
            per_file["currency_conflict"] = True
            per_file["currency_source"]   = "mixed_excel_currencies_block"
            per_file["warnings"].append(
                "multiple Excel currency symbols detected — supply "
                "override_currency or fix the source file")
            results.append(per_file); continue

        if override_ccy and (mixed or not first_excel_currency):
            currency_for_doc = override_ccy
            currency_source  = "operator_override"
        elif first_excel_currency:
            currency_for_doc = first_excel_currency
            currency_source  = first_excel_source or "excel"
        elif operator_ccy:
            currency_for_doc = operator_ccy
            currency_source  = "operator"
        elif customer_default:
            currency_for_doc = customer_default
            currency_source  = "customer_default"
        else:
            currency_for_doc = ""
            currency_source  = "missing"

        # PND tiebreak — same builder as intake.
        from ..services.sales_pnd_disambiguator import disambiguate_pnd
        inv_no_for_pnd = ""
        export_invs = [r.get("invoice_no", "") for r in sp_rows
                        if r.get("invoice_no")]
        if export_invs:
            from collections import Counter as _C
            inv_no_for_pnd = _C(export_invs).most_common(1)[0][0]

        pnd_summary = {"applied": False, "reason": "no PND rows",
                        "pairs": [], "warnings": []}
        has_pnd = any(
            str(r.get("design_no", "") or "").strip().upper() == "PND"
            for r in sp_rows
        )
        if has_pnd and inv_no_for_pnd:
            try:
                p_rows = pdb.get_packing_lines_for_batch(batch_id)
                inv_price_index: Dict[str, float] = {}
                for il in ddb.get_invoice_lines_for_batch(batch_id) or []:
                    ipc = (il.get("product_code") or "").strip()
                    if ipc and ipc not in inv_price_index:
                        inv_price_index[ipc] = float(
                            il.get("rate_usd") or il.get("unit_price") or 0
                        )
                supplier_candidates: List[Dict[str, Any]] = []
                for pl in p_rows:
                    if (pl.get("invoice_no") or "") != inv_no_for_pnd:
                        continue
                    item_type = (pl.get("item_type") or "").strip().upper()
                    if not (item_type.startswith("PEND")
                            or item_type == "PND"):
                        continue
                    supplier_candidates.append({
                        "product_code": pl.get("product_code") or "",
                        "design_no":    pl.get("design_no") or "",
                        "item_type":    item_type,
                        "unit_price":   inv_price_index.get(
                            pl.get("product_code") or "", 0.0,
                        ),
                    })
                sp_rows, pnd_summary = disambiguate_pnd(
                    sp_rows, supplier_candidates, invoice_no=inv_no_for_pnd,
                )
            except Exception as exc:
                log.warning("[%s] reingest PND tiebreak failed: %s",
                             batch_id, exc)

        # ── PR-3b: Sales packing matcher (canonical pc projection) ──
        # Mirrors the shipment_intake wiring. Runs AFTER the PND
        # disambiguator so its choices are preserved by the matcher's
        # existing-wins branch. The legacy "design_no as product_code"
        # fallback below is removed — unresolved rows persist
        # product_code=''.
        from ..services.sales_packing_matcher import (
            match_sales_lines_to_packing as _match_sales,
        )
        sp_rows, sales_matcher_summary = _match_sales(batch_id, sp_rows)
        if (sales_matcher_summary.get("designs_resolved")
                or sales_matcher_summary.get("designs_ambiguous")
                or sales_matcher_summary.get("designs_unresolved")):
            log.info("[%s] reingest sales matcher: %s",
                     batch_id, sales_matcher_summary)

        # Build line records with the ladder-resolved currency.
        line_records: List[Dict[str, Any]] = []
        for r in sp_rows:
            row_currency = str(r.get("currency", "") or "").strip().upper()
            final_currency = row_currency or currency_for_doc
            line_records.append({
                "client_name":  client,
                "client_ref":   client_ref,
                # Canonical product_code only — no design_no fallback.
                # See shipment_intake comment block for source order.
                "product_code": str(r.get("product_code") or ""),
                "design_no":    str(r.get("design_no", "") or ""),
                "bag_id":       str(r.get("bag_id", "") or ""),
                "quantity":     float(r.get("quantity", 0) or 0),
                "remarks":      str(r.get("client_po", "") or
                                     r.get("remarks", "") or ""),
                "unit_price":   float(r.get("unit_price",  0) or 0),
                "total_value":  float(r.get("total_value", 0) or 0),
                "currency":     final_currency,
                "price_source": "packing_list" if (
                    float(r.get("unit_price", 0) or 0) > 0
                ) else "",
            })

        # Atomic replace, scoped to (sales_doc_id, batch_id) only.
        repl = ddb.replace_sales_packing_lines(
            sales_document_id=sales_doc_id,
            batch_id=batch_id,
            lines=line_records,
        )
        per_file["before_count"]      = repl["deleted"]
        per_file["deleted_count"]     = repl["deleted"]
        per_file["inserted_count"]    = repl["inserted"]
        per_file["currency"]          = currency_for_doc
        per_file["currency_source"]   = currency_source
        per_file["currency_conflict"] = mixed
        per_file["pnd_summary"]       = pnd_summary
        per_file["sales_matcher_summary"] = sales_matcher_summary
        # Phase 2 — auto-create / surface local editable Proforma Draft.
        # Idempotent: re-ingest does NOT replace draft lines on a live
        # draft (only first-time creation populates editable_lines_json).
        _auto_create_draft_for_client(
            batch_id     = batch_id,
            client       = client,
            client_ref   = client_ref,
            currency     = currency_for_doc,
            line_records = line_records,
            operator     = operator or "reingest",
        )
        if currency_source == "missing":
            per_file["warnings"].append(
                "currency missing — Proforma will block until set")
        per_file["warnings"].extend(pnd_summary.get("warnings") or [])
        results.append(per_file)

    return JSONResponse({
        "ok":        True,
        "batch_id":  batch_id,
        "operator":  operator,
        "files":     results,
    })
