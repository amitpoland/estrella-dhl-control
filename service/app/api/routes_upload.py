"""
routes_upload.py — Dashboard direct-upload shipment workflow
============================================================
Lifecycle:
  Step 1  POST /api/v1/upload/shipment
          AWB + carrier + invoices (+ optional AWB PDF)
          SAD is NOT required at creation → status = "draft"
          action = "draft" (only valid action) → save draft

  Step 2  POST /api/v1/upload/shipment/{batch_id}/sad
          Attach SAD/ZC429 to an existing draft → status = "ready"

  Step 3  POST /api/v1/upload/shipment/{batch_id}/process
          Run engine on a "ready" shipment

  Step 4  POST /api/v1/upload/shipment/{batch_id}/set_pz
          Set PZ number after processing (final stage)

  GET     /api/v1/upload/shipment/{batch_id}/status
          Poll status for dashboard polling
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from ..services import document_db as ddb
from ..services import packing_db as pdb
from ..services import document_readiness as docrev

import mimetypes

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from ..core.config import settings
from ..core.logging import get_logger
from ..core.security import require_api_key
from ..core.guards import guard_pz_requires_sad, guard_trigger_declared
from ..core import timeline as tl
from ..services import export_service
from ..services.batch_service import get_output_dir
from ..services.batch_state_normalizer import _compute_effective_blocked
from ..utils.io import write_json_atomic

_DHL_BROKER_THRESHOLD_USD: float = 2500.0

log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1/upload", tags=["upload"])
_auth  = Depends(require_api_key)

_ALLOWED_EXT    = {".pdf"}
_MAX_BYTES: int = settings.max_upload_bytes   # 20 MB

# Valid carrier values
_CARRIERS = {"DHL", "FedEx", "Other"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_name(filename: str) -> str:
    name = Path(filename).name
    name = "".join(c if c.isalnum() or c in "._- " else "_" for c in name)
    return name or "file.pdf"


_PDF_MAGIC = b"%PDF"


def _validate_pdf(file: UploadFile) -> None:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Only PDF files are accepted. Got: {file.filename!r}",
        )


async def _save(file: UploadFile, dest: Path) -> None:
    content = await file.read()
    if len(content) > _MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {file.filename} ({len(content):,} bytes, max {_MAX_BYTES:,})",
        )
    if len(content) == 0:
        raise HTTPException(status_code=400, detail=f"Empty file: {file.filename}")
    if dest.suffix.lower() == ".pdf" and not content[:4].startswith(_PDF_MAGIC):
        raise HTTPException(status_code=400, detail=f"File does not appear to be a valid PDF: {file.filename}")
    dest.write_bytes(content)


def _normalize_awb(raw: str) -> str:
    """
    Normalize a raw AWB / tracking number for use in batch IDs and the canonical
    awb field.  Removes all whitespace and non-digit separators so that user-entered
    values like "53 7881 9972" or "566 591-6826" become safe filesystem names.

    Rules:
      1. Strip leading/trailing whitespace.
      2. Remove all interior spaces.
      3. Remove interior hyphens that sit between digit groups (common DHL format).
      4. Preserve the result as-is if no digits are present (e.g. non-numeric codes).

    The original value is stored separately as raw_awb in the audit.
    """
    stripped = raw.strip()
    if not stripped:
        return ""
    # Remove interior spaces
    normalized = stripped.replace(" ", "")
    # Remove hyphens that are surrounded by digits on both sides
    import re as _re
    normalized = _re.sub(r"(?<=\d)-(?=\d)", "", normalized)
    return normalized


def _make_batch_id(tracking_no: str) -> str:
    ym  = datetime.now(timezone.utc).strftime("%Y-%m")
    uid = uuid.uuid4().hex[:8]
    tag = _normalize_awb(tracking_no) or "AUTO"
    return f"SHIPMENT_{tag}_{ym}_{uid}"


def _tracking_url(carrier: str, tracking_no: str) -> str:
    t = tracking_no.strip()
    if carrier == "DHL" and t:
        return f"https://www.dhl.com/pl-en/home/tracking.html?tracking-id={t}"
    if carrier == "FedEx" and t:
        return f"https://www.fedex.com/en-pl/tracking.html?trknbr={t}"
    return ""


def _write_draft_audit(
    output_dir:  Path,
    batch_id:    str,
    tracking_no: str,
    carrier:     str,
    note:        str,
    inv_names:   List[str],
    sad_name:    str,
    awb_name:    str,
    status:      str = "draft",
) -> None:
    """Write a stub audit.json representing the current draft state."""
    has_sad = bool(sad_name)
    if status == "draft" and has_sad:
        status = "ready"   # SAD present at creation → ready to process

    # ── Canonical AWB field (always normalised digits, separate from tracking_no) ──
    # For DHL: tracking_no IS the AWB.  Normalise via _normalize_awb (strips spaces,
    # removes intra-digit hyphens) so the canonical field is always a clean number.
    # raw_awb preserves what the operator originally typed.
    # If absent, set null and add warning so automation can reject the batch.
    awb_canonical: Optional[str] = None
    warnings: List[str] = []
    if tracking_no and tracking_no.strip():
        awb_canonical = _normalize_awb(tracking_no) or None
    else:
        warnings.append("awb_missing")
        log.warning("[%s] Batch created without AWB/tracking number — automation blocked", batch_id)

    audit = {
        "correction_schema_version": "v2",
        "timestamp":    time.strftime("%Y-%m-%dT%H:%M:%S"),
        "batch_id":     batch_id,
        "awb":          awb_canonical,          # canonical AWB — used by all automation
        "raw_awb":      tracking_no or None,    # original operator input, preserved for reference
        "tracking_no":  tracking_no,            # raw value as entered
        "carrier":      carrier,
        "tracking_url": _tracking_url(carrier, tracking_no),
        "doc_no":       note,
        "status":       status,
        "engine_version": None,
        "folder_path":  str(output_dir.resolve()),
        "source":       "dashboard_upload",
        "inputs": {
            "invoices": inv_names,
            "zc429":    sad_name or None,
            "awb":      awb_name or None,
        },
        "totals":          {},
        "verification":    {},
        "failed_checks":   [],
        "amendment_flags": [],
        "corrections_log": [],
        "correction_report": None,
        "files":           {},
        "delivery_log":    [],
        "warnings":        warnings,            # ["awb_missing"] blocks tracking + automation
        "timeline":        [],                  # initialise empty — log_event appends here
    }
    write_json_atomic(output_dir / "audit.json", audit)


def _read_audit(output_dir: Path) -> dict:
    p = output_dir / "audit.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="Shipment not found.")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(status_code=500, detail="Could not read shipment data.")


def _mark_agency_documents_received(
    audit_path: Path,
    batch_id:   str,
    sad_name:   str,
    sad_path:   Path,
) -> None:
    """
    Write agency_documents_received / agency_documents_received_state after a
    SAD/customs file is registered via the direct upload path.

    - Skips when existing source is email_ingestor or operator (trusted receipt preserved)
    - Merges without path-duplicates when called more than once
    - Non-fatal: all exceptions are logged and swallowed
    """
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        now_iso = datetime.now(timezone.utc).isoformat()

        existing_recv  = audit.get("agency_documents_received") or {}
        existing_state = audit.get("agency_documents_received_state") or {}
        existing_source = existing_state.get("source") or (
            existing_recv.get("source") if isinstance(existing_recv, dict) else None
        )
        if existing_source in ("email_ingestor", "operator"):
            log.debug(
                "[%s] agency_documents_received already set by %s — not overwriting",
                batch_id, existing_source,
            )
            return

        file_type = "customs_xml" if sad_path.suffix.lower() == ".xml" else "customs_pdf"
        abs_path  = str(sad_path.resolve())

        existing_files = existing_state.get("files") or []
        if not any(f.get("path") == abs_path for f in existing_files):
            existing_files = existing_files + [{"name": sad_name, "path": abs_path, "type": file_type}]

        if not existing_files:
            log.warning("[%s] _mark_agency_documents_received: no files present — not marking received", batch_id)
            return

        received_at = existing_state.get("received_at") or now_iso

        audit["agency_documents_received"] = {
            "received":    True,
            "source":      "direct_upload",
            "files":       [f["name"] for f in existing_files],
            "files_count": len(existing_files),
            "received_at": received_at,
        }
        audit["agency_documents_received_state"] = {
            "received":    True,
            "files":       existing_files,
            "source":      "direct_upload",
            "received_at": received_at,
        }
        write_json_atomic(audit_path, audit)
        log.info("[%s] agency_documents_received marked via direct_upload: %s", batch_id, sad_name)

    except Exception as exc:
        log.warning("[%s] _mark_agency_documents_received failed (non-fatal): %s", batch_id, exc)


# ── DHL pre-check (background) ───────────────────────────────────────────────

async def _run_dhl_precheck(
    batch_id:   str,
    output_dir: Path,
    inv_dir:    Path,
    carrier:    str,
) -> None:
    """
    Parse invoice CIF values and compute DHL routing hint.
    Runs as a background task after dashboard upload.
    Always non-fatal — swallows all exceptions.
    """
    audit_path   = output_dir / "audit.json"
    carrier_upper = carrier.upper()

    try:
        # ── 1. Parse invoice PDFs for CIF totals ─────────────────────────────
        invoice_cif_usd = freight_total = fob_total = insurance_total = 0.0
        cif_source      = "not_parsed"
        parsed_count    = 0

        try:
            import sys as _sys
            _engine = str(settings.engine_dir)
            if _engine not in _sys.path:
                _sys.path.insert(0, _engine)
            from pz_import_processor import parse_invoice as _pi, compute_invoice_totals as _ct  # noqa: PLC0415

            _corr: list = []
            _parsed: list = []
            for _pdf in sorted(inv_dir.glob("*.pdf")):
                try:
                    _inv = _pi(str(_pdf), _corr)
                    if _inv:
                        _parsed.append(_inv)
                except Exception as _ie:
                    log.debug("[%s] precheck: parse error %s: %s", batch_id, _pdf.name, _ie)

            if _parsed:
                _totals          = _ct(_parsed)
                fob_total        = _totals.get("total_fob_usd", 0.0)
                freight_total    = _totals.get("total_freight_usd", 0.0)
                insurance_total  = _totals.get("total_insurance_usd", 0.0)
                invoice_cif_usd  = _totals.get("total_cif_usd", 0.0)
                cif_source       = "invoice_parser"
                parsed_count     = len(_parsed)

            # ── Persist learning traces ───────────────────────────────────────
            # parse_invoice() already called learn_from_parse() internally.
            # We just capture the _learning_trace it attached to each result
            # and write them to audit.json so the dashboard can display them.
            if _parsed:
                try:
                    _learning_traces = [
                        inv["_learning_trace"]
                        for inv in _parsed
                        if isinstance(inv.get("_learning_trace"), dict)
                    ]
                    try:
                        _aud2 = json.loads(audit_path.read_text(encoding="utf-8"))
                        _aud2["learning_traces"] = _learning_traces
                        write_json_atomic(audit_path, _aud2)
                        log.info("[LEARNING] [%s] %d trace(s) written to audit",
                                 batch_id, len(_learning_traces))
                    except Exception as _awe:
                        log.warning("[LEARNING] [%s] audit write failed: %s", batch_id, _awe)
                except Exception as _le:
                    log.warning("[LEARNING] [%s] learning persist error: %s", batch_id, _le)

        except Exception as _pe:
            log.debug("[%s] precheck: invoice parsing unavailable: %s", batch_id, _pe)

        # ── 1b. AWB Custom Val fallback (tertiary CIF authority) ─────────────
        # When the invoice did not yield a CIF, the carrier-declared customs
        # value on the AWB/waybill is the last authority before UNKNOWN. We
        # parse it here and stash it on the audit so cif_resolver can use it as
        # the tertiary layer. Never overrides invoice CIF — invoice authority
        # always wins. Never fabricates 0.00; a parser miss stays a gap.
        awb_customs: dict = {}
        if invoice_cif_usd <= 0:
            try:
                from ..services.awb_parser import parse_awb_pdf as _parse_awb  # noqa: PLC0415
                awb_dir = output_dir / "source" / "awb"
                _awb_pdfs = sorted(awb_dir.glob("*.pdf")) if awb_dir.is_dir() else []
                for _awb_pdf in _awb_pdfs:
                    try:
                        _awb_res = _parse_awb(_awb_pdf)
                    except Exception as _ae:
                        log.debug("[%s] precheck: AWB parse error %s: %s", batch_id, _awb_pdf.name, _ae)
                        continue
                    _cv  = _awb_res.get("customs_value")
                    _ccy = (_awb_res.get("currency") or "").upper()
                    _gap = _awb_res.get("customs_value_gap")
                    if _cv is not None:
                        awb_customs = {
                            "value_usd": round(float(_cv), 2),
                            "currency":  _ccy or "USD",
                            "gap":       None,
                            "source_pdf": _awb_pdf.name,
                        }
                        log.info(
                            "[%s] precheck: AWB Custom Val fallback value=%.2f %s (from %s)",
                            batch_id, float(_cv), _ccy or "USD", _awb_pdf.name,
                        )
                        break
                    # No value — record the gap from the first AWB we tried.
                    if not awb_customs:
                        awb_customs = {
                            "value_usd": None,
                            "currency":  _ccy or "",
                            "gap":       _gap or "no_label",
                            "source_pdf": _awb_pdf.name,
                        }
                        log.warning(
                            "[%s] precheck: AWB Custom Val NOT extracted (gap=%s) from %s",
                            batch_id, _gap or "no_label", _awb_pdf.name,
                        )
            except Exception as _awe:
                log.debug("[%s] precheck: AWB fallback unavailable: %s", batch_id, _awe)

        # ── 2. Compute routing hint ──────────────────────────────────────────
        precheck: dict = {
            "completed_at":          datetime.now(timezone.utc).isoformat(),
            "carrier":               carrier_upper,
            "invoice_cif_total_usd": round(invoice_cif_usd, 2) if invoice_cif_usd > 0 else None,
            "fob_total_usd":         round(fob_total, 2) if fob_total > 0 else None,
            "freight_total_usd":     round(freight_total, 2) if freight_total > 0 else None,
            "insurance_total_usd":   round(insurance_total, 2) if insurance_total > 0 else None,
            "cif_source":            cif_source,
            "invoices_parsed":       parsed_count,
            "threshold_usd":         _DHL_BROKER_THRESHOLD_USD,
        }
        if awb_customs:
            precheck["awb_customs_value_usd"]  = awb_customs.get("value_usd")
            precheck["awb_customs_currency"]   = awb_customs.get("currency")
            precheck["awb_customs_value_gap"]  = awb_customs.get("gap")

        if carrier_upper == "DHL":
            if invoice_cif_usd > 0:
                if invoice_cif_usd > _DHL_BROKER_THRESHOLD_USD:
                    precheck["clearance_hint"]    = "Broker / DSK may be required"
                    precheck["dsk_required_hint"] = True
                    precheck["note"] = (
                        f"Invoice CIF ${invoice_cif_usd:,.2f} exceeds "
                        f"${_DHL_BROKER_THRESHOLD_USD:,.0f} threshold. "
                        "DSK may be required. Final decision requires DHL customs email or admin approval."
                    )
                else:
                    precheck["clearance_hint"]    = "DHL standard clearance likely"
                    precheck["dsk_required_hint"] = False
                    precheck["note"] = (
                        f"Invoice CIF ${invoice_cif_usd:,.2f} is within "
                        f"${_DHL_BROKER_THRESHOLD_USD:,.0f} threshold. "
                        "DHL self-clearance expected. Awaiting DHL customs email."
                    )
            else:
                precheck["clearance_hint"]    = "Invoice CIF not parsed — routing pending"
                precheck["dsk_required_hint"] = None
                precheck["note"] = (
                    "Invoice value could not be extracted. "
                    "DHL routing will be determined when DHL email arrives."
                )

        # ── 3. Write to audit.json ───────────────────────────────────────────
        try:
            _audit = json.loads(audit_path.read_text(encoding="utf-8"))
            _audit["dhl_precheck"] = precheck
            # Persist the AWB Custom Val authority block so cif_resolver can use
            # it as the tertiary layer. Merge-not-replace (authority-data rule):
            # spread the existing block and only update from this run when the new
            # read actually carries a value — a fresh run that parsed no AWB value
            # (gap) must NOT downgrade a previously-captured good value to None.
            if awb_customs:
                existing_awb = dict(_audit.get("awb_customs") or {})
                new_value = awb_customs.get("value_usd")
                if new_value is not None or not existing_awb.get("value_usd"):
                    # New read has a value, or there is nothing good to preserve.
                    _audit["awb_customs"] = {
                        **existing_awb,
                        "value_usd": new_value,
                        "currency":  awb_customs.get("currency"),
                        "gap":       awb_customs.get("gap"),
                    }
                else:
                    # Preserve the prior good value AND its usable state. The new
                    # read failed (gap), but the gating ``gap`` field MUST stay as
                    # the prior good value's (None) — cif_resolver treats any
                    # truthy ``gap`` as an unusable layer (cif_resolver.py:156),
                    # so overwriting ``gap`` here would silently downgrade a
                    # captured good value to UNKNOWN at resolution time, which is
                    # exactly the downgrade this branch exists to prevent. Record
                    # the failed re-read under a NON-gating diagnostic key instead.
                    existing_awb["last_reread_gap"] = awb_customs.get("gap")
                    _audit["awb_customs"] = existing_awb
            if carrier_upper == "DHL" and not _audit.get("clearance_status"):
                _audit["clearance_status"] = "awaiting_dhl_customs_email"
            write_json_atomic(audit_path, _audit)
        except Exception as _we:
            log.warning("[%s] precheck: audit write failed: %s", batch_id, _we)

        # ── 4. Log timeline event ────────────────────────────────────────────
        tl.log_event(
            audit_path, tl.EV_DHL_PRECHECK_COMPLETED, "system", "upload_pipeline",
            detail={
                "carrier":   carrier_upper,
                "cif_usd":   invoice_cif_usd if invoice_cif_usd > 0 else None,
                "dsk_hint":  precheck.get("dsk_required_hint"),
                "hint":      precheck.get("clearance_hint"),
            },
        )

        log.info("[%s] DHL pre-check done: carrier=%s cif=%.2f hint=%s dsk=%s",
                 batch_id, carrier_upper, invoice_cif_usd,
                 precheck.get("clearance_hint"), precheck.get("dsk_required_hint"))

        # ── 5. Image-only OCR/AI CIF fallback (LAST — self-contained) ─────────
        # When the text-based parsers above left CIF UNKNOWN because the AWB /
        # invoice is an image-only scan, escalate to the vision extractor. It
        # re-reads the fully-written audit, no-ops unless CIF is still UNKNOWN,
        # and does its own atomic merge-not-replace write. Non-fatal.
        try:
            from ..services.vision_extractor import run_image_only_cif_fallback
            _vres = run_image_only_cif_fallback(output_dir, batch_id)
            if _vres.get("ran"):
                log.info("[%s] vision CIF fallback: wrote=%s reason=%s",
                         batch_id, _vres.get("wrote"), _vres.get("reason"))
                if _vres.get("wrote"):
                    # Authority-chain evidence: a CIF/AWB value entered the audit
                    # via OCR/AI vision. Trace it on the timeline for the operator.
                    tl.log_event(
                        audit_path, tl.EV_VISION_CIF_WRITTEN, "system", "vision_fallback",
                        detail={
                            "source": "upload_precheck",
                            "documents": _vres.get("documents"),
                            "reason": _vres.get("reason"),
                        },
                    )
        except Exception as _ve:
            log.warning("[%s] vision CIF fallback failed (non-fatal): %s", batch_id, _ve)

        # ── 6. Advisory image-only invoice extraction (LAST — self-contained) ─
        # When the invoice is an image-only scan the engine cannot parse goods
        # lines / FOB / supplier, so PZ generation is impossible. Recover those
        # purchase-accounting inputs into the advisory `vision_invoice` block
        # (operator_confirmed=false — a proposal, never booked). Does NOT touch
        # CIF authority, invoice_totals, or rows. Non-fatal.
        try:
            from ..services.vision_extractor import run_image_only_invoice_extraction
            _ires = run_image_only_invoice_extraction(output_dir, batch_id)
            if _ires.get("ran"):
                log.info("[%s] vision invoice extraction: wrote=%s reason=%s",
                         batch_id, _ires.get("wrote"), _ires.get("reason"))
        except Exception as _ie:
            log.warning("[%s] vision invoice extraction failed (non-fatal): %s", batch_id, _ie)

    except Exception as exc:
        log.warning("[%s] DHL pre-check failed (non-fatal): %s", batch_id, exc)


# ── Step 1: Create shipment (always saves as draft) ──────────────────────────

@router.post("/shipment", dependencies=[_auth])
async def upload_shipment(
    background:  BackgroundTasks,
    invoices:    List[UploadFile],
    tracking_no: str                               = Form(default=""),
    carrier:     str                               = Form(default="Other"),
    note:        str                               = Form(default=""),
    sad:         Optional[UploadFile]              = None,
    awb:         Optional[UploadFile]              = None,
) -> JSONResponse:
    """
    Create a new shipment (always saves as draft).
    - SAD is optional: omit it to save a draft (shipment in transit, SAD not yet received).
    - Upload always stores only. Use POST /shipment/{batch_id}/process to trigger processing.
    - carrier must be DHL, FedEx, or Other.
    """
    # ── Validate ──────────────────────────────────────────────────────────────
    if not tracking_no.strip():
        raise HTTPException(status_code=400, detail="AWB / Tracking number is required.")
    if not invoices:
        raise HTTPException(status_code=400, detail="At least one invoice PDF is required.")
    if carrier not in _CARRIERS:
        carrier = "Other"

    for f in invoices:
        _validate_pdf(f)
    if sad and sad.filename:
        _validate_pdf(sad)
    else:
        sad = None   # treat missing/empty as not provided
    if awb and awb.filename:
        _validate_pdf(awb)
    else:
        awb = None

    # ── Build batch id and folder ─────────────────────────────────────────────
    batch_id   = _make_batch_id(tracking_no)
    output_dir = get_output_dir(batch_id)

    src_base = output_dir / "source"
    inv_dir  = src_base / "invoices"
    sad_dir  = src_base / "sad"
    awb_dir  = src_base / "awb"
    for d in (inv_dir, sad_dir, awb_dir):
        d.mkdir(parents=True, exist_ok=True)

    # ── Save invoices ─────────────────────────────────────────────────────────
    inv_names: List[str] = []
    for f in invoices:
        name = _safe_name(f.filename or "invoice.pdf")
        await _save(f, inv_dir / name)
        inv_names.append(name)
        log.info("[%s] Saved invoice: %s", batch_id, name)

    # ── Save SAD (optional) ───────────────────────────────────────────────────
    sad_name = ""
    sad_path: Optional[Path] = None
    if sad:
        sad_name = _safe_name(sad.filename or "sad.pdf")
        sad_path = sad_dir / sad_name
        await _save(sad, sad_path)
        log.info("[%s] Saved SAD: %s", batch_id, sad_name)

    # ── Save AWB PDF (optional) ───────────────────────────────────────────────
    awb_name = ""
    awb_path: Optional[Path] = None
    if awb:
        awb_name = _safe_name(awb.filename)
        awb_path = awb_dir / awb_name
        await _save(awb, awb_path)
        log.info("[%s] Saved AWB: %s", batch_id, awb_name)

    # ── Always write draft audit ──────────────────────────────────────────────
    _write_draft_audit(
        output_dir, batch_id, tracking_no, carrier, note,
        inv_names, sad_name, awb_name,
        status="draft",
    )
    audit_path   = output_dir / "audit.json"
    if sad_path:
        _mark_agency_documents_received(audit_path, batch_id, sad_name, sad_path)
    status_label = "ready" if sad_path else "draft"

    # ── Register documents in unified registry (non-blocking) ─────────────────
    _awb_canonical = _normalize_awb(tracking_no) if tracking_no.strip() else ""
    try:
        for _inv_name in inv_names:
            _inv_p = inv_dir / _inv_name
            ddb.register_document(
                batch_id=batch_id, document_type="invoice",
                file_name=_inv_name, file_path=str(_inv_p),
                file_hash=ddb.sha256_file(_inv_p),
                awb=_awb_canonical, source="upload",
            )
        if sad_path:
            ddb.register_document(
                batch_id=batch_id, document_type="sad_pdf",
                file_name=sad_name, file_path=str(sad_path),
                file_hash=ddb.sha256_file(sad_path),
                awb=_awb_canonical, source="upload",
            )
        if awb_path:
            ddb.register_document(
                batch_id=batch_id, document_type="awb",
                file_name=awb_name, file_path=str(awb_path),
                file_hash=ddb.sha256_file(awb_path),
                awb=_awb_canonical, source="upload",
            )
    except Exception as _e:
        log.warning("[%s] document_db register failed (non-fatal): %s", batch_id, _e)

    # ── Log timeline events ───────────────────────────────────────────────────
    tl.log_event(audit_path, tl.EV_BATCH_CREATED, "dashboard", "user",
                 detail={"tracking_no": tracking_no, "carrier": carrier,
                         "invoices": len(inv_names)})
    for _n in inv_names:
        tl.log_event(audit_path, tl.EV_INVOICE_UPLOADED, "dashboard", "user",
                     detail={"file": _n})
    if awb_name:
        tl.log_event(audit_path, tl.EV_AWB_UPLOADED, "dashboard", "user",
                     detail={"file": awb_name})
    if sad_name:
        tl.log_event(audit_path, tl.EV_SAD_UPLOADED, "dashboard", "user",
                     detail={"file": sad_name})

    # ── Schedule DHL pre-check (always runs; no-op for non-DHL) ──────────────
    background.add_task(_run_dhl_precheck, batch_id, output_dir, inv_dir, carrier)

    log.info("[%s] Draft saved (status=%s) — carrier=%s inv=%d sad=%s awb=%s",
             batch_id, status_label, carrier, len(inv_names), sad_name or "—", awb_name or "—")
    return JSONResponse({
        "status":      status_label,
        "batch_id":    batch_id,
        "tracking_no": tracking_no,
        "carrier":     carrier,
        "invoices":    len(inv_names),
        "has_sad":     bool(sad_path),
    })


# ── Step 2: Add SAD to existing draft → status becomes "ready" ───────────────

@router.post("/shipment/{batch_id}/sad", dependencies=[_auth])
async def upload_sad(
    batch_id: str,
    sad:      UploadFile,
) -> JSONResponse:
    """
    Attach or replace a SAD/ZC429 PDF for a shipment.
    Transitions status from 'draft'/'in_preparation' → 'ready'.
    Re-upload is also allowed for 'ready' and 'blocked' batches (file restore / SAD replacement).
    """
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    _validate_pdf(sad)

    output_dir = get_output_dir(batch_id)
    audit      = _read_audit(output_dir)

    current_status = audit.get("status", "")
    _TERMINAL = {"completed", "exported", "closed", "pz_generated", "wfirma_exported"}
    if current_status in _TERMINAL:
        raise HTTPException(
            status_code=409,
            detail=f"SAD cannot be changed on a closed shipment. Current status: {current_status}",
        )

    # Save SAD file
    sad_dir  = output_dir / "source" / "sad"
    sad_dir.mkdir(parents=True, exist_ok=True)
    sad_name = _safe_name(sad.filename or "sad.pdf")
    sad_path = sad_dir / sad_name
    await _save(sad, sad_path)
    log.info("[%s] SAD uploaded: %s (was status=%s)", batch_id, sad_name, current_status)

    # Update audit.json — only advance status for draft batches; keep existing status otherwise
    if current_status in ("draft", "in_preparation"):
        audit["status"] = "ready"
    audit["inputs"]["zc429"]  = sad_name
    audit["source"]           = "dashboard_upload"
    write_json_atomic(output_dir / "audit.json", audit)

    tl.log_event(output_dir / "audit.json", tl.EV_SAD_UPLOADED, "dashboard", "user",
                 detail={"file": sad_name})

    _mark_agency_documents_received(output_dir / "audit.json", batch_id, sad_name, sad_path)

    # Register SAD in document registry (non-blocking)
    try:
        _awb = str(audit.get("awb") or "")
        ddb.register_document(
            batch_id=batch_id, document_type="sad_pdf",
            file_name=sad_name, file_path=str(sad_path),
            file_hash=ddb.sha256_file(sad_path),
            awb=_awb, source="upload",
        )
    except Exception as _e:
        log.warning("[%s] document_db SAD register failed (non-fatal): %s", batch_id, _e)

    new_status = audit.get("status", current_status)
    return JSONResponse({
        "status":   new_status,
        "batch_id": batch_id,
        "sad":      sad_name,
        "message":  "SAD uploaded. Shipment is ready for processing."
                    if new_status == "ready"
                    else f"SAD replaced. Shipment status: {new_status}.",
    })


# ── Step 3: Process a ready shipment ─────────────────────────────────────────

@router.post("/shipment/{batch_id}/process", dependencies=[_auth])
async def process_shipment(
    batch_id:   str,
    background: BackgroundTasks,
) -> JSONResponse:
    """
    Start processing a shipment that has status 'ready'.
    Runs the full engine pipeline in the background.
    """
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    output_dir = get_output_dir(batch_id)
    audit      = _read_audit(output_dir)

    current_status = audit.get("status", "")
    # Allow re-run from:
    #   ready/partial/success  — normal re-run path
    #   failed                 — engine threw an exception on a previous attempt; operator retries
    #   processing             — background task crashed / server restarted mid-run; status stuck
    #   blocked                — engine wrote a blocked verdict (e.g. financial mismatch);
    #                            operator retries after fixing inputs OR engine code. The engine
    #                            re-evaluates failed_checks on each run and writes status=blocked
    #                            again if the mismatch persists — no silent override of any
    #                            financial gate. agency_sad_decision.safe_to_run_pz=False still
    #                            hard-rejects below (the explicit SAD-block gate).
    if current_status not in ("ready", "partial", "success", "failed", "processing", "blocked"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Shipment must be in 'ready', 'partial', 'success', 'failed', "
                f"'processing', or 'blocked' state to process. Current: {current_status}"
            ),
        )

    # Hard guard: reject if SAD decision engine has already blocked this batch.
    _sad_dec = audit.get("agency_sad_decision") or {}
    if _sad_dec and _sad_dec.get("safe_to_run_pz") is False:
        return JSONResponse(
            status_code=409,
            content={
                "ok":           False,
                "error":        "sad_validation_blocked",
                "reason":       _sad_dec.get("reason"),
                "mrn_parsed":   _sad_dec.get("mrn_parsed"),
                "mrn_declared": _sad_dec.get("mrn_declared"),
            },
        )

    # Fix 4: Allow Run PZ from XML/customs_declaration dict without requiring SAD PDF
    # if customs_declaration dict is already populated and zc429 parsed data is present.
    cd       = audit.get("customs_declaration") or {}
    zc429_d  = audit.get("zc429") or {}
    has_xml_customs = bool(cd.get("mrn") or zc429_d.get("mrn"))

    sad_name = audit.get("inputs", {}).get("zc429")
    sad_path: Optional[Path] = None

    if sad_name:
        _candidate = output_dir / "source" / "sad" / sad_name
        if _candidate.exists():
            sad_path = _candidate
        elif has_xml_customs:
            # Audit references a SAD by name but the file is gone — XML dict saves us
            log.info(
                "[%s] SAD PDF not on disk (%s) — using XML/customs_declaration dict as primary",
                batch_id, sad_name,
            )
            # Set customs_source for traceability
            audit.setdefault("customs_declaration", {})["customs_source"] = "xml_validated"
        else:
            raise HTTPException(status_code=404, detail=f"SAD file not found on disk: {sad_name}")
    elif has_xml_customs:
        # No SAD PDF at all, but we have parsed customs data — allow PZ
        log.info(
            "[%s] No SAD PDF — running PZ from XML/customs_declaration dict",
            batch_id,
        )
        audit["customs_source"] = "xml_validated"
        # Point sad_path to any ZC429 XML file if it exists
        _sad_dir = output_dir / "source" / "sad"
        if _sad_dir.exists():
            _xml_files = list(_sad_dir.glob("*.xml"))
            if _xml_files:
                sad_path = _xml_files[0]
                sad_name = sad_path.name
    else:
        # No SAD PDF and no XML customs data → block
        raise HTTPException(
            status_code=409,
            detail=(
                "No SAD/ZC429 found and no parsed customs data available. "
                "Upload SAD first or run Re-parse SAD."
            ),
        )

    # Stamp customs_source in audit
    _cs = "xml_validated" if has_xml_customs and not (sad_path and sad_path.suffix == ".pdf") else (
        "pdf_parse" if sad_path else "none"
    )
    audit.setdefault("customs_declaration", {})
    if not audit["customs_declaration"].get("customs_source"):
        audit["customs_declaration"]["customs_source"] = _cs
    audit["customs_source"] = _cs

    inv_dir = output_dir / "source" / "invoices"
    if not inv_dir.exists() or not list(inv_dir.glob("*.pdf")):
        raise HTTPException(status_code=404, detail="No invoice PDFs found for this shipment.")

    # Set status to processing
    audit["status"] = "processing"
    write_json_atomic(output_dir / "audit.json", audit)

    tracking_no = audit.get("tracking_no", "")
    carrier     = audit.get("carrier", "Other")
    doc_no      = audit.get("doc_no", "")
    inv_names   = audit.get("inputs", {}).get("invoices", [])
    awb_name    = audit.get("inputs", {}).get("awb", "")

    background.add_task(
        _run_pipeline,
        batch_id    = batch_id,
        output_dir  = output_dir,
        inv_dir     = inv_dir,
        sad_path    = sad_path,
        tracking_no = tracking_no,
        carrier     = carrier,
        doc_no      = doc_no,
        inv_names   = inv_names,
        sad_name    = sad_name or "",
        awb_name    = awb_name,
    )
    log.info("[%s] Processing started from ready state (customs_source=%s)", batch_id, _cs)
    return JSONResponse({
        "status":   "processing",
        "batch_id": batch_id,
        "message":  "Processing started. Check back in a moment.",
    })


# ── Step 4: Set PZ number after processing ───────────────────────────────────

@router.post("/shipment/{batch_id}/set_pz", dependencies=[_auth])
async def set_pz_number(
    batch_id: str,
    pz_number: str = Form(...),
) -> JSONResponse:
    """
    Set the PZ document number on a completed shipment (final stage).
    The PZ number is an output, not an input — it is confirmed after processing.
    """
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    if not pz_number.strip():
        raise HTTPException(status_code=400, detail="PZ number cannot be empty.")

    output_dir = get_output_dir(batch_id)
    audit      = _read_audit(output_dir)

    audit["doc_no"]    = pz_number.strip()
    audit["pz_confirmed"] = True
    audit["pz_confirmed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    write_json_atomic(output_dir / "audit.json", audit)

    log.info("[%s] PZ number set: %s", batch_id, pz_number.strip())
    return JSONResponse({
        "status":     "ok",
        "batch_id":   batch_id,
        "pz_number":  pz_number.strip(),
        "message":    "PZ number confirmed.",
    })


# ── Background pipeline ───────────────────────────────────────────────────────

async def _run_pipeline(
    batch_id:    str,
    output_dir:  Path,
    inv_dir:     Path,
    sad_path:    Path,
    tracking_no: str,
    carrier:     str,
    doc_no:      str,
    inv_names:   List[str],
    sad_name:    str,
    awb_name:    str,
) -> None:
    from fastapi import HTTPException as _HTTPException
    log.info("[%s] Background pipeline start", batch_id)

    # Guard check — block if SAD missing or already processed
    # In advisory mode, the guard returns an advisory dict instead of raising;
    # we log it and continue so the pipeline runs without SAD for testing.
    audit = _read_audit(output_dir) if (output_dir / "audit.json").exists() else {}
    try:
        _sad_advisory = guard_pz_requires_sad(audit)
        if _sad_advisory:
            log.info("[%s] PZ guard advisory (SAD absent, advisory mode ON): %s",
                     batch_id, _sad_advisory.get("code"))
    except _HTTPException as ge:
        log.error("[%s] PZ guard blocked pipeline: %s", batch_id, ge.detail)
        _patch_audit(output_dir, {
            "status":       "failed",
            "engine_error": ge.detail.get("error", str(ge.detail)) if isinstance(ge.detail, dict) else str(ge.detail),
        })
        tl.log_event(output_dir / "audit.json", tl.EV_ERROR, "system", "guard",
                     detail={"code": ge.detail.get("code") if isinstance(ge.detail, dict) else "GUARD",
                             "message": str(ge.detail)})
        return

    # ── AWB guard — block automation if AWB is missing ───────────────────────
    if not audit.get("awb"):
        if "awb_missing" not in audit.get("warnings", []):
            audit.setdefault("warnings", []).append("awb_missing")
            write_json_atomic(output_dir / "audit.json", audit)
        log.warning("[%s] AWB missing — tracking and cowork automation will be blocked", batch_id)
        # Not a hard block for PZ processing — PZ can still run; automation cannot

    tl.log_event(output_dir / "audit.json", tl.EV_PROCESSING_STARTED, "dashboard", "dashboard_user",
                 detail={"batch_id": batch_id, "doc_no": doc_no, "awb": audit.get("awb")})

    # Determine settlement_mode from customs_declaration (Art.33a)
    cd = audit.get("customs_declaration") or {}
    _settlement_mode = "art33a" if cd.get("art33a") else "standard"
    # Use pre-parsed ZC429 XML data if available (bypasses PDF parser)
    _zc429_dict = audit.get("zc429") if audit.get("zc429", {}).get("mrn") else None

    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: export_service.process_shipment(
                invoice_dir     = inv_dir,
                zc429_path      = sad_path,
                output_dir      = output_dir,
                doc_no          = doc_no,
                settlement_mode = _settlement_mode,
                zc429_dict      = _zc429_dict,
            ),
        )
    except Exception as exc:
        log.exception("[%s] Engine error during pipeline", batch_id)
        _patch_audit(output_dir, {"status": "failed", "engine_error": str(exc)})
        return

    # Patch carrier + source fields into the engine-written audit.json
    _patch_audit(output_dir, {
        "tracking_no": tracking_no or None,
        "carrier":     carrier,
        "tracking_url": _tracking_url(carrier, tracking_no),
        "source":      "dashboard_upload",
        "inputs.awb":  awb_name or None,
    })

    # ── Preserve operator_overrides and operator-confirmed fields ─────────────
    # process_shipment() writes a fresh audit.json that does not carry forward
    # operator_overrides, pz_confirmed, or pz_confirmed_at from before the run.
    # Restore them from the pre-run audit captured at pipeline start so the
    # audit trail and effective-blocked gate remain correct on subsequent reads.
    _pre_overrides = audit.get("operator_overrides")
    if _pre_overrides:  # non-empty list — restore unconditionally
        try:
            _audit_path = output_dir / "audit.json"
            _aud = json.loads(_audit_path.read_text(encoding="utf-8"))
            _aud["operator_overrides"] = _pre_overrides
            if audit.get("pz_confirmed"):
                _aud.setdefault("pz_confirmed", audit["pz_confirmed"])
            if audit.get("pz_confirmed_at"):
                _aud.setdefault("pz_confirmed_at", audit["pz_confirmed_at"])
            write_json_atomic(_audit_path, _aud)
            log.info("[%s] operator_overrides restored after engine write (%d entries)",
                     batch_id, len(_pre_overrides))
        except Exception as _ov_exc:
            log.warning("[%s] Could not restore operator_overrides (non-fatal): %s",
                        batch_id, _ov_exc)

    # ── Guarantee clearance_decision is populated after pipeline ────────────
    # Non-destructive: only writes if absent, or if we now have a real
    # (non-routing_pending) decision. Uses the carrier-aware + timeline-aware
    # builder so a FedEx shipment is not overwritten with DHL-rules output and
    # any prior timeline override (agency_email_sent / dhl_reply_sent) survives.
    try:
        from ..services.clearance_decision import build_clearance_decision_for_carrier
        _audit_path = output_dir / "audit.json"
        _aud = json.loads(_audit_path.read_text(encoding="utf-8"))
        _dec = build_clearance_decision_for_carrier(_aud)
        if _dec.get("clearance_path") != "routing_pending" or not _aud.get("clearance_decision"):
            _aud["clearance_decision"] = _dec
            write_json_atomic(_audit_path, _aud)
            log.info("[%s] clearance_decision set after pipeline: path=%s cif=%.2f state=%s",
                     batch_id, _dec.get("clearance_path"),
                     _dec.get("total_value_usd", 0), _dec.get("cif_state"))
    except Exception as _cd_exc:
        log.warning("[%s] clearance_decision post-pipeline (non-fatal): %s", batch_id, _cd_exc)

    log.info("[%s] Pipeline complete. status=%s net=%.2f",
             batch_id,
             result.get("status", "?"),
             result.get("total_net", 0))

    _r_status = result.get("status", "unknown")

    # ── Operator-override status reconciliation ───────────────────────────────
    # The engine sets status="blocked" based on failed_checks and amendment_flags
    # alone; it has no knowledge of operator overrides.  After the engine writes
    # its verdict, re-evaluate using _compute_effective_blocked so that a batch
    # whose only remaining issues are operator-accepted non-financial checks
    # transitions to "partial" rather than staying "blocked".
    #
    # Condition: engine said "blocked" AND all remaining issues are cleared by
    # operator overrides (effective_blocked=False) AND output files exist.
    # Result status: "partial" (operator-accepted — not a fully clean run).
    if _r_status == "blocked":
        try:
            from ..services.batch_state_normalizer import _compute_effective_blocked as _ceb
            _aud_path = output_dir / "audit.json"
            _aud_now = json.loads(_aud_path.read_text(encoding="utf-8"))
            if not _ceb(_aud_now):
                # All remaining issues are operator-accepted — promote to partial
                _aud_now["status"]      = "partial"
                _aud_now["pz_generated"] = True
                write_json_atomic(_aud_path, _aud_now)
                _r_status = "partial"
                log.info(
                    "[%s] operator-override reconciliation: promoted blocked→partial "
                    "(all remaining issues are operator-accepted)",
                    batch_id,
                )
        except Exception as _rec_exc:
            log.warning("[%s] override reconciliation (non-fatal): %s", batch_id, _rec_exc)

    # ── Stamp SAD import state + emit readiness-compatible event ─────────────
    # Bridges the gap between pz_generated (pipeline event) and the events
    # consumed by dhl_readiness (zc429_received / sad_uploaded) and
    # proposal_engine._sad_received() (sad_imported_ts).
    if _r_status in ("success", "partial"):
        _stamp_sad_imported(output_dir, sad_name)

    _ev = tl.EV_PZ_GENERATED if _r_status in ("success", "partial") else tl.EV_PZ_BLOCKED
    tl.log_event(output_dir / "audit.json", _ev, "dashboard", "dashboard_user",
                 detail={"status": _r_status, "doc_no": doc_no})

    # ── Inventory state promotion: PURCHASE_TRANSIT → WAREHOUSE_STOCK ────────
    # Only on success/partial. Idempotent: skip lines not in PURCHASE_TRANSIT.
    # Best-effort — must never break the PZ flow.
    if _r_status in ("success", "partial"):
        _promote_to_warehouse_stock(batch_id)


def _promote_to_warehouse_stock(batch_id: str) -> int:
    """
    Move every packing line for *batch_id* that is currently in
    PURCHASE_TRANSIT into WAREHOUSE_STOCK. Lines not yet seeded, or already at
    WAREHOUSE_STOCK or beyond, are skipped.

    Returns the number of lines promoted (0 on any failure).

    B×7-1b BE-1 (2026-07-02, PROJECT_STATE DECISIONS "slice B×7-1b BE-1"):
    the promotion loop that used to live here is now the shared authority
    services/stock_promotion.run_stock_promotion() — the same function the
    wFirma PZ writers call (Business Feature Completeness: ONE shared
    function, no Logic A / Logic B). This wrapper keeps the historical
    signature and int return for the PZ-generation call site and for the
    pre-existing test_warehouse_stock_promotion.py pins.
    """
    from ..services.stock_promotion import run_stock_promotion
    result = run_stock_promotion(
        batch_id,
        trigger  = "pz_generated",
        source   = "pz_pipeline",
        operator = "system",
    )
    return int(result.get("promoted", 0))


def _stamp_sad_imported(output_dir: Path, sad_name: str) -> None:
    """
    After successful PZ/customs processing, stamp SAD import state fields and
    emit a readiness-compatible timeline event so that:
      - proposal_engine._sad_received() returns True (checks sad_imported_ts)
      - dhl_readiness advances from agency_forwarded → sad_received (checks
        zc429_received / sad_uploaded timeline events)

    Event selection:
      ZC429 filename prefix → tl.EV_ZC429_RECEIVED
      anything else         → tl.EV_SAD_UPLOADED

    Idempotent: no-op if sad_imported_ts is already set.
    Non-fatal: any exception is logged at WARNING and swallowed.
    Does not modify financial or PZ calculation values.
    """
    audit_path = output_dir / "audit.json"
    if not audit_path.exists():
        return
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))

        # Idempotent guard — don't overwrite an already-stamped entry
        if audit.get("sad_imported_ts"):
            log.debug("[%s] _stamp_sad_imported: already set, skipping", output_dir.name)
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        audit["sad_imported"]    = True
        audit["sad_imported_ts"] = now_iso
        write_json_atomic(audit_path, audit)

        # Select readiness event by filename convention
        _ev_name = (
            tl.EV_ZC429_RECEIVED
            if (sad_name or "").upper().startswith("ZC429")
            else tl.EV_SAD_UPLOADED
        )

        # Dedup: only emit if this event type is not already in the timeline
        _existing_events = {e.get("event") for e in (audit.get("timeline") or [])}
        if _ev_name not in _existing_events:
            tl.log_event(audit_path, _ev_name, "system", "pz_pipeline",
                         detail={"sad_name": sad_name, "trigger": "pz_completed"})

        log.info("[%s] _stamp_sad_imported: sad_imported_ts=%s event=%s",
                 output_dir.name, now_iso, _ev_name)
    except Exception as exc:
        log.warning("[%s] _stamp_sad_imported failed (non-fatal): %s", output_dir.name, exc)


def _patch_audit(output_dir: Path, patches: dict) -> None:
    """Apply key→value patches to audit.json. Supports 'inputs.key' dot notation.

    Most keys only fill if absent/empty (preserves engine-written values).
    `status` and `engine_error` always overwrite — failure transitions must not be
    silently dropped just because the previous state was 'processing'.
    """
    audit_path = output_dir / "audit.json"
    _force_overwrite = {"status", "engine_error"}
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        for k, v in patches.items():
            if v is None:
                continue
            if "." in k:
                outer, inner = k.split(".", 1)
                audit.setdefault(outer, {})[inner] = v
            elif k in _force_overwrite:
                audit[k] = v
            else:
                if k not in audit or not audit[k]:
                    audit[k] = v
        # ── Ensure canonical awb is always set when tracking_no is present ──
        if not audit.get("awb") and audit.get("tracking_no"):
            audit["awb"] = _normalize_awb(audit["tracking_no"])
            audit.setdefault("warnings", [])
            if "awb_missing" in audit["warnings"]:
                audit["warnings"].remove("awb_missing")
        write_json_atomic(audit_path, audit)
    except Exception as e:
        log.error("[%s] Could not patch audit.json: %s", output_dir.name, e)


# ── Document Registry (read-only) ─────────────────────────────────────────────

# ── Document-identity contract (Wave 3) ─────────────────────────────────────
# Generated fiscal / customs-evidence documents are NEVER deletable from the
# registry (the operator regenerates or replaces them; deleting a booked PZ or a
# customs SAD would destroy the audit/compliance chain). Everything else — the
# operator-uploaded source docs — is deletable through the canonical
# delete-by-id route with confirmation + audit.
_GENERATED_TYPES = {
    "pz_pdf", "pz_xlsx", "pz_document", "audit_memo", "audit_en", "audit_pl",
    "calculation_xlsx", "corrections",
}
_CUSTOMS_EVIDENCE_TYPES = {"sad_pdf", "sad_xml"}
_NONDELETABLE_TYPES = _GENERATED_TYPES | _CUSTOMS_EVIDENCE_TYPES
# The document-row Replace button uses the GENERAL replace route, which rejects
# generated (regenerate instead) AND customs evidence (SAD is replaced via its
# dedicated /sad route on the SAD card, not the generic Replace button). So
# can_replace matches that route: uploaded source docs only.
_NONREPLACEABLE_TYPES = _GENERATED_TYPES | _CUSTOMS_EVIDENCE_TYPES


def _guess_mime(file_name: str) -> str:
    ext = (Path(file_name).suffix or "").lower()
    if ext == ".pdf":
        return "application/pdf"
    if ext in (".xlsx", ".xls"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if ext == ".xml":
        return "application/xml"
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".json":
        return "application/json"
    return mimetypes.guess_type(file_name)[0] or "application/octet-stream"


def _document_identity_contract(d: dict, batch_id: str) -> dict:
    """Derive the stable per-document identity contract the V2 Documents tab
    consumes. Serving is unified through ONE registry-keyed content route so
    view/download URLs never depend on per-type serving quirks."""
    doc_id  = d.get("id", "")
    dtype   = (d.get("document_type") or "")
    source  = (d.get("source") or "upload")
    fname   = d.get("file_name") or d.get("canonical_file_name") or ""
    is_generated = source == "generated" or dtype in _GENERATED_TYPES
    on_disk = bool((d.get("file_path") or "").strip())
    base = (f"/api/v1/upload/shipment/{batch_id}/documents/"
            f"{doc_id}/content")
    is_current = bool(d.get("is_current", 1))
    can_delete = (dtype not in _NONDELETABLE_TYPES) and not is_generated
    # Only the CURRENT version is replaceable (superseded rows are history).
    can_replace = (dtype not in _NONREPLACEABLE_TYPES) and not is_generated and is_current
    return {
        "document_id":       doc_id,
        "authority":         source,
        "is_generated":      is_generated,
        "is_current":        bool(d.get("is_current", 1)),
        "superseded_by":     d.get("superseded_by") or "",
        "original_filename": fname,
        "mime_type":         _guess_mime(fname),
        "can_view":          on_disk,
        "can_download":      on_disk,
        "can_replace":       can_replace and on_disk,
        "can_delete":        can_delete and on_disk,
        "view_url":          f"{base}?disposition=inline"     if on_disk else None,
        "download_url":      f"{base}?disposition=attachment" if on_disk else None,
    }


# Internal columns that must never leave the API boundary (absolute disk paths).
_MANIFEST_INTERNAL_FIELDS = ("file_path",)


@router.get("/shipment/{batch_id}/documents", dependencies=[_auth])
def list_batch_documents(batch_id: str) -> JSONResponse:
    """
    Return the per-batch document registry: every shipment_documents row for
    this batch, with its extracted fields embedded (capped at 50 fields per
    document for payload safety).

    Read-only. Wraps document_db.get_documents_for_batch() and
    document_db.get_fields_for_document().
    """
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    docs = ddb.get_documents_for_batch(batch_id)
    enriched = []
    for d in docs:
        doc_id = d.get("id", "")
        all_fields = ddb.get_fields_for_document(doc_id)
        row = {
            **d,
            "fields":            all_fields[:50],
            "fields_total":      len(all_fields),
            "fields_truncated":  len(all_fields) > 50,
        }
        # ── Invoice-side enrichment: 2026-05-17 hotfix ────────────────
        # Invoice extraction writes to invoice_lines, not
        # document_extracted_fields. The Document Registry used to read
        # only the latter and render "Fields: 0" for invoice rows even
        # when invoice_lines existed. Surface the line count + a small
        # preview so the UI can render "N lines" honestly.
        if (d.get("document_type") or "") in ("purchase_invoice", "sales_invoice"):
            try:
                lines_preview = ddb.get_invoice_lines_for_document(doc_id, limit=20)
                lines_total   = ddb.count_invoice_lines_for_document(doc_id)
                row["lines_preview"]   = lines_preview
                row["lines_count"]     = lines_total
                row["lines_truncated"] = lines_total > len(lines_preview)
            except Exception as exc:
                log.warning("[%s] invoice lines enrichment failed (non-fatal) doc=%s: %s",
                            batch_id, doc_id, exc)
        # ── Sales-packing enrichment ──────────────────────────────────
        # sales_packing_list extraction writes to sales_packing_lines
        # (keyed by sales_document_id == this shipment_documents.id), not
        # to document_extracted_fields — so without this branch the registry
        # rendered "Lines/Fields: 0" for sales rows even when 84 lines exist.
        # Mirror the invoice enrichment so the UI shows the real count.
        elif (d.get("document_type") or "") == "sales_packing_list":
            try:
                lines_preview = ddb.get_sales_packing_lines_for_document(doc_id, limit=20)
                lines_total   = ddb.count_sales_packing_lines_for_document(doc_id)
                row["lines_preview"]   = lines_preview
                row["lines_count"]     = lines_total
                row["lines_truncated"] = lines_total > len(lines_preview)
            except Exception as exc:
                log.warning("[%s] sales packing lines enrichment failed (non-fatal) doc=%s: %s",
                            batch_id, doc_id, exc)
        # ── Purchase-packing enrichment ───────────────────────────────
        # purchase_packing_list extraction writes to packing.db
        # (packing_lines, keyed by packing_document_id → packing_documents),
        # NOT to documents.db — so without this branch the registry rendered
        # "Lines/Fields: 0" for purchase rows even when lines existed. The
        # registry row is a shipment_documents row; bridge to its packing
        # document by (batch_id, file_hash) — equivalently (batch_id,
        # file_name) when a hash is absent. Mirror the invoice/sales branches.
        elif (d.get("document_type") or "") == "purchase_packing_list":
            try:
                _bid = d.get("batch_id") or batch_id
                _fh  = d.get("file_hash") or ""
                _fn  = d.get("file_name") or ""
                lines_preview = pdb.get_packing_lines_for_shipment_document(_bid, _fh, _fn, limit=20)
                lines_total   = pdb.count_packing_lines_for_shipment_document(_bid, _fh, _fn)
                row["lines_preview"]   = lines_preview
                row["lines_count"]     = lines_total
                row["lines_truncated"] = lines_total > len(lines_preview)
            except Exception as exc:
                log.warning("[%s] purchase packing lines enrichment failed (non-fatal) doc=%s: %s",
                            batch_id, doc_id, exc)

        # ── Review-state authority ─────────────────────────────────────
        # Attach the single backend review verdict (review_state /
        # review_reason / review_code) so the registry Review column is never
        # blank and never shows a stale 'pending'. The frontend renders this
        # verdict verbatim; it must not invent a state of its own.
        #
        # For purchase packing lists the authoritative extraction status lives
        # in packing.db / packing_documents (the shipment_documents column was
        # historically never written back) — reconcile from there so a complete
        # parse is reported as complete (RC-1).
        dtype = (d.get("document_type") or "")
        effective_status = None
        contractor_ctx = None
        try:
            if dtype == "purchase_packing_list":
                effective_status = pdb.get_packing_status_for_shipment_document(
                    d.get("batch_id") or batch_id,
                    d.get("file_hash") or "",
                    d.get("file_name") or "",
                ) or None
            elif dtype == "sales_packing_list":
                # Only apply the contractor gate when enrichment actually ran
                # (lines_preview present). If the sales-lines enrichment above
                # was swallowed, leave contractor_ctx None so the gate is
                # skipped — never a FALSE 'client_unresolved' block.
                if "lines_preview" in row:
                    _line_client = ""
                    for _ln in (row.get("lines_preview") or []):
                        _cn = str((_ln.get("client_name") or "")).strip()
                        if _cn:
                            _line_client = _cn
                            break
                    contractor_ctx = {
                        "client_contractor_id": d.get("client_contractor_id") or "",
                        "client_name": _line_client,
                    }
            _lc = row.get("lines_count")
            review = docrev.derive_document_review(
                d,
                line_count=_lc if isinstance(_lc, int) else None,
                contractor_context=contractor_ctx,
                effective_extraction_status=effective_status,
            )
            row.update(review.as_dict())
            row["extraction_status_effective"] = (
                effective_status or d.get("extraction_status") or ""
            )
        except Exception as exc:
            log.warning("[%s] review-state derivation failed (non-fatal) doc=%s: %s",
                        batch_id, doc_id, exc)
            # Never leave the row blank — the registry invariant is that every
            # row carries a concrete (non-empty) review_state. Surface the
            # derivation error honestly instead of inventing a verdict.
            row.setdefault("review_state", "needs_review")
            row.setdefault("review_reason", "Review state unavailable — check logs")
            row.setdefault("review_code", "review_derivation_error")
            row.setdefault("extraction_status_effective", d.get("extraction_status") or "")

        # ── Document-identity contract + internal-field scrub ──────────
        # Add the stable identity/capability/URL contract, then drop internal
        # columns (absolute file_path) that must never cross the API boundary.
        row.update(_document_identity_contract(d, batch_id))
        for _internal in _MANIFEST_INTERNAL_FIELDS:
            row.pop(_internal, None)

        enriched.append(row)
    return JSONResponse({
        "batch_id": batch_id,
        "count":    len(enriched),
        "documents": enriched,
    })


def _resolve_batch_document(batch_id: str, document_id: str) -> dict:
    """Fetch a registry row by id, enforce it belongs to batch_id, and confirm
    its file_path resolves under storage_root (path-traversal defence). Raises
    HTTPException on any failure. Returns the row dict."""
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    if not document_id or "/" in document_id or ".." in document_id:
        raise HTTPException(status_code=400, detail="Invalid document_id.")
    d = ddb.get_document(document_id)
    if not d or (d.get("batch_id") or "") != batch_id:
        raise HTTPException(status_code=404, detail="Document not found in this batch.")
    return d


def _safe_document_path(d: dict) -> Path:
    """Resolve + validate the on-disk file for a registry row: it must exist and
    live under storage_root (never let a poisoned file_path escape the root)."""
    raw = (d.get("file_path") or "").strip()
    if not raw:
        raise HTTPException(status_code=404, detail="Document has no stored file.")
    root = settings.storage_root.resolve()
    try:
        p = Path(raw).resolve()
        p.relative_to(root)
    except (ValueError, OSError):
        raise HTTPException(status_code=400, detail="Document path is outside storage root.")
    if not p.exists():
        raise HTTPException(status_code=404, detail="Stored file is missing on disk.")
    return p


def _safe_document_dir(d: dict, batch_id: str) -> Path:
    """Resolve + validate the directory a replacement file may be written to:
    the original document's parent dir, confirmed under storage_root (never let
    a poisoned file_path column redirect a write outside the root). Falls back to
    the batch's source/misc dir (under the root) when no original path exists."""
    root = settings.storage_root.resolve()
    raw = (d.get("file_path") or "").strip()
    if raw:
        try:
            parent = Path(raw).resolve().parent
            parent.relative_to(root)
            return parent
        except (ValueError, OSError):
            raise HTTPException(status_code=400, detail="Document path is outside storage root.")
    return (get_output_dir(batch_id) / "source" / "misc").resolve()


def _clean_operator(x_operator: Optional[str]) -> str:
    """Sanitise the X-Operator audit actor: printable only, capped length,
    defaulting to 'v2'. Prevents audit-log injection / unbounded values."""
    s = "".join(c for c in (x_operator or "").strip() if c.isprintable())[:120]
    return s or "v2"


@router.get("/shipment/{batch_id}/documents/{document_id}/content", dependencies=[_auth])
def serve_document_content(
    batch_id: str, document_id: str, disposition: str = "attachment",
) -> FileResponse:
    """Canonical registry-keyed content route. `disposition=inline` opens the
    document browser-safe (View); `disposition=attachment` (default) downloads
    it. One route for every document_type — the manifest's view_url/download_url
    both point here. no-store so a regenerated artifact is never served stale."""
    d = _resolve_batch_document(batch_id, document_id)
    path = _safe_document_path(d)
    fname = d.get("file_name") or path.name
    media = _guess_mime(fname)
    # XSS defence: only ever render browser-safe types INLINE from the app
    # origin. text/html and image/svg+xml can carry script; xlsx/xml/json etc.
    # have no reason to render inline — force those to attachment even when
    # inline is requested. nosniff blocks MIME-sniffing; a sandbox CSP neuters
    # any active content in a served file.
    _INLINE_SAFE = {"application/pdf", "image/png", "image/jpeg", "image/gif"}
    disp = "inline" if (disposition == "inline" and media in _INLINE_SAFE) else "attachment"
    return FileResponse(
        path=str(path),
        media_type=media,
        filename=fname,
        content_disposition_type=disp,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                 "Pragma": "no-cache", "Expires": "0",
                 "X-Content-Type-Options": "nosniff",
                 "Content-Security-Policy": "default-src 'none'; sandbox"},
    )


@router.delete("/shipment/{batch_id}/documents/{document_id}", dependencies=[_auth])
def delete_batch_document(
    batch_id: str, document_id: str,
    x_operator:  Optional[str] = Header(None, alias="X-Operator"),
    x_confirm:   Optional[str] = Header(None, alias="X-Confirm-Delete"),
) -> JSONResponse:
    """Canonical delete-by-id for an operator-UPLOADED document. Removes the
    registry row + its documents.db-side sales lines + the packing.db-side
    purchase-packing rows + the on-disk file, and writes a timeline audit event.
    Generated fiscal artifacts (pz/audit/calc) and customs evidence (sad) are
    NON-deletable → 409. Requires an explicit X-Confirm-Delete: true header
    (backend confirmation gate, in addition to the UI confirm)."""
    d = _resolve_batch_document(batch_id, document_id)
    dtype = (d.get("document_type") or "")
    if dtype in _NONDELETABLE_TYPES or (d.get("source") or "") == "generated":
        raise HTTPException(
            status_code=409,
            detail=(f"'{dtype}' is a generated/customs document and cannot be "
                    f"deleted. Regenerate or replace it instead."),
        )
    if str(x_confirm or "").strip().lower() != "true":
        raise HTTPException(status_code=428, detail="Delete requires confirmation (X-Confirm-Delete: true).")
    operator = _clean_operator(x_operator)

    # 1) packing.db purchase-packing rows FIRST — report whether it succeeded so
    #    the caller is never told ok:true while packing.db still holds orphans.
    packing_db_cleaned = True
    if dtype == "purchase_packing_list":
        try:
            pack_ids = pdb._resolve_packing_document_ids(
                d.get("batch_id") or batch_id,
                d.get("file_hash") or "",
                d.get("file_name") or "",
            )
            for _pid in pack_ids:
                pdb.delete_packing_document_and_lines(_pid)
        except Exception as exc:
            packing_db_cleaned = False
            log.warning("[%s] delete: packing.db cleanup FAILED doc=%s: %s",
                        batch_id, document_id, exc)
    # 2) registry row (+ documents.db sales lines cascade) — DB before disk so a
    #    crash never leaves a registry row pointing at a missing file.
    try:
        deleted = ddb.delete_document(document_id)
    except Exception as exc:
        log.warning("[%s] delete: registry delete failed doc=%s: %s", batch_id, document_id, exc)
        raise HTTPException(status_code=500, detail="Document registry delete failed — nothing was removed.")
    # 3) on-disk file (best-effort; registry row is already gone)
    file_removed = False
    try:
        raw = (d.get("file_path") or "").strip()
        if raw:
            p = Path(raw).resolve()
            p.relative_to(settings.storage_root.resolve())
            if p.exists():
                p.unlink()
                file_removed = True
    except Exception as exc:
        log.warning("[%s] delete: file unlink failed (non-fatal) doc=%s: %s",
                    batch_id, document_id, exc)
    # 4) audit event
    try:
        audit_path = get_output_dir(batch_id) / "audit.json"
        if audit_path.exists():
            tl.log_event(audit_path, "document_deleted", operator, "user", detail={
                "document_id": document_id, "document_type": dtype,
                "file_name": d.get("file_name") or "", "file_removed": file_removed,
                "packing_db_cleaned": packing_db_cleaned,
            })
    except Exception as exc:
        log.warning("[%s] delete: audit event failed (non-fatal) doc=%s: %s",
                    batch_id, document_id, exc)
    return JSONResponse({
        "ok": bool(deleted) and packing_db_cleaned,
        "batch_id": batch_id, "document_id": document_id,
        "document_type": dtype, "file_removed": file_removed,
        "packing_db_cleaned": packing_db_cleaned,
    })


@router.post("/shipment/{batch_id}/documents/{document_id}/replace", dependencies=[_auth])
async def replace_batch_document(
    batch_id: str, document_id: str,
    file: UploadFile,
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Replace the FILE of an uploaded document, PRESERVING provenance: the new
    file is written to a UNIQUE path (never overwriting the original) and the old
    registry row is SUPERSEDED (is_current=0, superseded_by=new id) with a
    timeline audit event. Only the CURRENT version of an uploaded doc is
    replaceable. Same document_type + extension. Does NOT re-parse — run recheck
    afterwards. Generated fiscal / customs-evidence docs are not replaceable
    here (SAD has its own /sad route) → 409."""
    d = _resolve_batch_document(batch_id, document_id)
    dtype = (d.get("document_type") or "")
    if dtype in _GENERATED_TYPES or (d.get("source") or "") == "generated":
        raise HTTPException(status_code=409, detail=f"'{dtype}' is a generated document and cannot be replaced (regenerate instead).")
    if dtype in _CUSTOMS_EVIDENCE_TYPES:
        raise HTTPException(status_code=409, detail="Replace SAD via POST /upload/shipment/{batch_id}/sad (customs authority).")
    # Only the current version may be replaced — replacing a superseded row would
    # create two is_current=1 rows for the same type.
    if not bool(d.get("is_current", 1)):
        raise HTTPException(status_code=409, detail="Cannot replace a superseded document — replace the current version instead.")
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No replacement file provided.")
    old_ext = (Path(d.get("file_name") or "").suffix or "").lower()
    new_ext = (Path(file.filename).suffix or "").lower()
    if new_ext != old_ext:  # unconditional — a no-extension original needs a no-extension replacement
        raise HTTPException(status_code=400, detail=f"Replacement must have the same extension as the original ({old_ext or 'none'}).")

    # UNIQUE destination — never overwrite the original file (provenance is the
    # preserved old file + superseded row). Directory is validated under root.
    dest_dir = _safe_document_dir(d, batch_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    base = "".join(c if c.isalnum() or c in "._- " else "_" for c in Path(file.filename).name)
    dest = dest_dir / f"repl_{uuid.uuid4().hex[:8]}_{base}"
    # _save enforces size (413) + 0-byte (400) + PDF magic-byte (for .pdf).
    await _save(file, dest)

    operator = _clean_operator(x_operator)
    new_id = ddb.register_document(
        batch_id=batch_id, document_type=dtype,
        file_name=file.filename, file_path=str(dest),
        file_hash=ddb.sha256_file(dest),
        awb=d.get("awb") or "", source="upload",
        client_contractor_id=d.get("client_contractor_id") or "",
        supplier_contractor_id=d.get("supplier_contractor_id") or "",
    ) or ""
    superseded = ddb.supersede_document(document_id, new_id) if new_id and new_id != document_id else False
    try:
        audit_path = get_output_dir(batch_id) / "audit.json"
        if audit_path.exists():
            tl.log_event(audit_path, "document_replaced", operator, "user", detail={
                "old_document_id": document_id, "new_document_id": new_id,
                "document_type": dtype, "file_name": file.filename,
            })
    except Exception as exc:
        log.warning("[%s] replace: audit event failed (non-fatal) doc=%s: %s",
                    batch_id, document_id, exc)
    return JSONResponse({
        "ok": True, "batch_id": batch_id, "document_type": dtype,
        "old_document_id": document_id, "new_document_id": new_id,
        "superseded": superseded, "next_step": "Run recheck to parse the replaced document.",
    })


# ── Status polling ────────────────────────────────────────────────────────────

@router.get("/shipment/{batch_id}/status", dependencies=[_auth])
def upload_status(batch_id: str) -> dict:
    """Poll processing status for a dashboard-uploaded shipment."""
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    audit_path = settings.storage_root / "outputs" / batch_id / "audit.json"
    if not audit_path.exists():
        raise HTTPException(status_code=404, detail="Shipment not found.")

    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(status_code=500, detail="Could not read shipment status.")

    # WorkDrive status block (from audit — set by export_service)
    _wd = audit.get("workdrive_upload", {})
    return {
        "batch_id":    batch_id,
        "status":      audit.get("status", "unknown"),
        "tracking_no": audit.get("tracking_no", ""),
        "carrier":     audit.get("carrier", ""),
        "doc_no":      audit.get("doc_no", ""),
        "timestamp":   audit.get("timestamp", ""),
        "engine_error": audit.get("engine_error"),
        # WorkDrive upload state (populated after export_service runs)
        "workdrive_upload_status":    _wd.get("status"),          # success|retry_queued|failed|None
        "workdrive_retry_required":   _wd.get("retry_required"),  # True = files queued for retry
        "workdrive_direct_upload":    audit.get("workdrive_direct_upload", False),
        "workdrive_pdf_resource_id":  audit.get("workdrive_pdf_resource_id"),
        "workdrive_xlsx_resource_id": audit.get("workdrive_xlsx_resource_id"),
        "workdrive_batch_folder_id":  audit.get("workdrive_batch_folder_id"),
    }


# ── DHL ZC429 completion-email intake ──────────────────────────────────────
#
# Accepts a structured representation of the DHL Agencja Celna WAW
# "Powiadomienie o odebranym komunikacie ZC429" notification (sender,
# subject, body, attachments) and routes it through dhl_zc429_intake.
#
# Read-only over financial/customs values. Sets only customs_declaration
# scalars + emits the existing ``zc429_received`` timeline event.
# Never touches PZ / wFirma / Proforma / SMTP. Does not interfere with
# the existing low-value (< 2500 USD) DHL self-clearance workflow,
# which operates upstream of this intake.

from pydantic import BaseModel as _ZC429BaseModel, Field as _ZC429Field   # noqa: E402
import base64 as _zc429_b64                                                # noqa: E402


class _ZC429Attachment(_ZC429BaseModel):
    filename:        str
    content_base64:  Optional[str] = None
    size:            Optional[int] = None


class _ZC429IntakeRequest(_ZC429BaseModel):
    sender:       str
    subject:      str
    body:         str
    received_at:  str = ""
    message_id:   str = ""
    batch_id:     Optional[str] = None
    attachments:  List[_ZC429Attachment] = _ZC429Field(default_factory=list)


@router.post("/dhl-zc429/intake", dependencies=[_auth])
def dhl_zc429_intake_endpoint(req: _ZC429IntakeRequest) -> JSONResponse:
    """Operator-/integration-triggered DHL ZC429 email intake.

    Decodes base64 attachment payloads, runs the detector + classifier,
    persists evidence + classified attachments into the matched
    shipment, and writes the ``customs_declaration`` audit block plus
    the ``zc429_received`` timeline event. Never executes PZ / wFirma /
    Proforma / SMTP actions and never alters the low-value self-
    clearance flow."""
    from ..services import dhl_zc429_intake as _zc429
    payload_atts: List[dict] = []
    for a in req.attachments:
        content = b""
        if a.content_base64:
            try:
                content = _zc429_b64.b64decode(a.content_base64, validate=False)
            except Exception:
                content = b""
        payload_atts.append({
            "filename": a.filename,
            "content":  content,
            "size":     a.size or len(content) or 0,
        })
    result = _zc429.ingest_zc429_email(
        sender       = req.sender,
        subject      = req.subject,
        body         = req.body,
        received_at  = req.received_at,
        message_id   = req.message_id,
        attachments  = payload_atts,
        batch_id     = req.batch_id,
    )
    status = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status)
