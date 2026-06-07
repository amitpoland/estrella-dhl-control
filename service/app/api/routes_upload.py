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

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

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
    Attach a SAD/ZC429 PDF to an existing draft shipment.
    Transitions status from 'draft' → 'ready'.
    """
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    _validate_pdf(sad)

    output_dir = get_output_dir(batch_id)
    audit      = _read_audit(output_dir)

    current_status = audit.get("status", "")
    if current_status not in ("draft", "in_preparation"):
        raise HTTPException(
            status_code=409,
            detail=f"SAD can only be added to a draft shipment. Current status: {current_status}",
        )

    # Save SAD file
    sad_dir  = output_dir / "source" / "sad"
    sad_dir.mkdir(parents=True, exist_ok=True)
    sad_name = _safe_name(sad.filename or "sad.pdf")
    sad_path = sad_dir / sad_name
    await _save(sad, sad_path)
    log.info("[%s] SAD uploaded: %s", batch_id, sad_name)

    # Update audit.json
    audit["status"]           = "ready"
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

    return JSONResponse({
        "status":   "ready",
        "batch_id": batch_id,
        "sad":      sad_name,
        "message":  "SAD uploaded. Shipment is ready for processing.",
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
    # Non-destructive: only writes if absent or value=0/routing_pending with real CIF now available
    try:
        from ..services.clearance_decision import build_clearance_decision
        _audit_path = output_dir / "audit.json"
        _aud = json.loads(_audit_path.read_text(encoding="utf-8"))
        _dec = build_clearance_decision(_aud)
        if _dec.get("clearance_path") != "routing_pending" or not _aud.get("clearance_decision"):
            _aud["clearance_decision"] = _dec
            write_json_atomic(_audit_path, _aud)
            log.info("[%s] clearance_decision set after pipeline: path=%s cif=%.2f",
                     batch_id, _dec.get("clearance_path"), _dec.get("total_value_usd", 0))
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
    """
    promoted = 0
    try:
        from ..services import packing_db as _pdb
        from ..services import inventory_state_engine as _ise

        lines = _pdb.get_packing_lines_for_batch(batch_id)
        for line in lines:
            try:
                sc = line.get("scan_code") or _pdb._compute_scan_code(line)
                if not sc:
                    continue
                st = _ise.get_state(sc)
                if st is None or st.get("state") != _ise.PURCHASE_TRANSIT:
                    continue
                _ise.transition(scan_code=sc, to_state=_ise.WAREHOUSE_STOCK)
                promoted += 1
            except Exception as _row_exc:
                log.warning("[%s] WAREHOUSE_STOCK promote skipped for one line: %s",
                            batch_id, _row_exc)
                # Best-effort per-line failure mirror — never raises into the loop.
                # Bounded payload: error str truncated to 200 chars.
                try:
                    from ..services.batch_service import get_output_dir as _get_output_dir
                    _audit_path_fail = _get_output_dir(batch_id) / "audit.json"
                    tl.log_event(
                        _audit_path_fail,
                        tl.EV_INVENTORY_TRANSITION_FAILED,
                        trigger_source = "pz_pipeline",
                        actor          = "system",
                        detail = {
                            "batch_id":   batch_id,
                            "scan_code":  line.get("scan_code") or _pdb._compute_scan_code(line) or "",
                            "to_state":   "warehouse_stock",
                            "error":      str(_row_exc)[:200],
                        },
                    )
                except Exception as _tl_exc:
                    log.warning(
                        "[%s] inventory transition failure mirror failed (non-fatal): %s",
                        batch_id, _tl_exc,
                    )
    except Exception as _outer:
        log.warning("[%s] WAREHOUSE_STOCK promote best-effort failure: %s",
                    batch_id, _outer)

    # ── Best-effort timeline mirror — never breaks the PZ pipeline ───────────
    # One per-batch summary event regardless of promoted count, mirroring the
    # EV_PZ_GENERATED idiom that fires four lines above the call site.
    try:
        from ..services.batch_service import get_output_dir as _get_output_dir
        _audit_path = _get_output_dir(batch_id) / "audit.json"
        tl.log_event(
            _audit_path,
            tl.EV_INVENTORY_WAREHOUSE_STOCK_PROMOTED,
            trigger_source = "pz_pipeline",
            actor          = "system",
            detail = {
                "batch_id": batch_id,
                "promoted": promoted,
            },
        )
    except Exception as _tl_exc:
        log.warning("[%s] WAREHOUSE_STOCK promote mirror event failed (non-fatal): %s",
                    batch_id, _tl_exc)

    return promoted


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
        enriched.append(row)
    return JSONResponse({
        "batch_id": batch_id,
        "count":    len(enriched),
        "documents": enriched,
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
