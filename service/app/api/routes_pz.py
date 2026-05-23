from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..core.config import settings
from ..core.logging import get_logger
from ..core.security import require_api_key
from ..schemas.response import (
    BatchSummary, CorrectionSummary, HealthResponse, OutputFiles,
    ProcessResponse, VerificationSummary,
)
from ..services import batch_service, cliq_service, export_service

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["pz"])

_auth = Depends(require_api_key)


def _has_hard_fail(v: dict) -> bool:
    """Return True if any verification key is explicitly False (confirmed mismatch)."""
    return any(val is False for val in v.values() if not isinstance(val, list))


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse, dependencies=[_auth])
async def health() -> HealthResponse:
    try:
        import pz_import_processor  # noqa: F401
        engine_status = "ok"
    except ImportError as e:
        engine_status = f"import error: {e}"

    overall = "ok" if engine_status == "ok" else "degraded"
    return HealthResponse(
        status      = overall,
        engine      = engine_status,
        environment = settings.environment,
        detail      = {"engine_dir": str(settings.engine_dir)},
    )


# ── Process ───────────────────────────────────────────────────────────────────

@router.post("/pz/process", dependencies=[_auth])
async def process_pz_deprecated() -> None:
    """
    DEPRECATED — standalone PZ processing endpoint.

    This endpoint bypasses the Shipment Batch model:
    - creates an isolated batch with no audit.json timeline
    - does not enforce the SAD guard on an existing shipment
    - results never appear in the dashboard

    Use the shipment-based flow instead:
      POST /api/v1/upload/shipment           → create shipment
      POST /api/v1/upload/shipment/{id}/sad  → upload SAD/ZC429
      POST /api/v1/upload/shipment/{id}/process → run PZ
    """
    raise HTTPException(
        status_code=410,
        detail={
            "error": "Deprecated endpoint. Use shipment-based PZ processing.",
            "use_instead": "POST /api/v1/upload/shipment/{batch_id}/process",
            "docs": (
                "1. Create shipment: POST /api/v1/upload/shipment\n"
                "2. Upload SAD:      POST /api/v1/upload/shipment/{id}/sad\n"
                "3. Run PZ:          POST /api/v1/upload/shipment/{id}/process"
            ),
        },
    )


@router.post("/pz/process/_legacy", response_model=ProcessResponse, dependencies=[_auth])
async def process_pz(
    invoices:        Annotated[List[UploadFile], File(description="Invoice PDFs (one or more)")],
    zc429:           Annotated[UploadFile,       File(description="ZC429 / SAD PDF")],
    doc_no:          Annotated[str,   Form()] = "",
    carrier:         Annotated[str,   Form()] = "",
    settlement_mode: Annotated[Literal["standard", "art33a"], Form()] = "standard",
    strict_match:    Annotated[Optional[bool], Form()] = None,
    nbp_rate:        Annotated[Optional[float], Form()] = None,
    post_to_cliq:    Annotated[bool,  Form()] = False,
    target_type:     Annotated[Literal["bot", "chat", "user"], Form()] = "bot",
    target_id:       Annotated[str,   Form()] = "",
) -> ProcessResponse:
    """Internal legacy path — hidden from production. Use /pz/process flow above."""

    # ── 1. Save uploads ───────────────────────────────────────────────────────
    try:
        batch_id, inv_dir, zc429_path = await batch_service.save_batch(invoices, zc429)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Failed to save uploaded files")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    output_dir = batch_service.get_output_dir(batch_id)
    errors: List[str] = []

    # ── 2. Run engine (strict_match handled at route level below) ─────────────
    result = None
    try:
        result = export_service.process_shipment(
            invoice_dir     = inv_dir,
            zc429_path      = zc429_path,
            output_dir      = output_dir,
            doc_no          = doc_no,
            settlement_mode = settlement_mode,
            carrier         = carrier,
            nbp_rate        = nbp_rate,
        )
    except Exception as exc:
        log.error("Engine error [batch=%s]: %s", batch_id, exc)
        errors.append(str(exc))

    # ── 3. Engine failure ─────────────────────────────────────────────────────
    if result is None:
        if post_to_cliq:
            await cliq_service.deliver_batch_result(
                result={}, doc_no=doc_no,
                target_type=target_type, target_id=target_id,
                errors=errors,
            )
        return ProcessResponse(
            status="failed", batch_id=batch_id,
            document_no=doc_no, errors=errors,
        )

    v           = result.get("verification", {})
    corrections = result.get("corrections_log", [])
    verify_gaps = [c for c in corrections if c.startswith("[VERIFY-GAP]")]
    amendment_flags = v.get("amendment_flags", [])

    # ── 4. Strict verification gate ───────────────────────────────────────────
    # per-request overrides global; None means "use config default"
    effective_strict = strict_match if strict_match is not None else settings.strict_match
    if effective_strict and (_has_hard_fail(v) or amendment_flags):
        failed_keys = [k for k, val in v.items()
                       if not isinstance(val, list) and val is False]
        reason = f"Hard verification failures: {failed_keys}" + (
            f"; amendment flags: {amendment_flags}" if amendment_flags else ""
        )
        log.warning("Batch BLOCKED [batch=%s]: %s", batch_id, reason)
        if post_to_cliq:
            failed_lines = "\n".join(f"- {k} = FALSE" for k in failed_keys)
            flag_lines   = "\n".join(f"- {f}" for f in amendment_flags)
            blocked_msg  = (
                f"⚠️ PZ BLOCKED — verification mismatch\n"
                f"Document: {doc_no or '—'}\n"
                f"Failed checks:\n{failed_lines}"
                + (f"\nAmendment flags:\n{flag_lines}" if amendment_flags else "")
                + "\nAction required: verify SAD vs invoices\nNo files posted."
            )
            await cliq_service.post_to_channel(blocked_msg)
        return ProcessResponse(
            status          = "blocked",
            batch_id        = batch_id,
            document_no     = doc_no,
            verification    = VerificationSummary(
                invoice_refs_match    = v.get("invoice_refs_match"),
                cif_match             = v.get("cif_match"),
                qty_match_by_type     = v.get("qty_match_by_type"),
                importer_match        = v.get("importer_match"),
                exporter_match        = v.get("exporter_match"),
                blocked_phrases_clean = v.get("blocked_phrases_clean"),
                duty_rate_ok          = v.get("duty_rate_ok"),
                amendment_flags       = amendment_flags,
            ),
            corrections_log = corrections,
            errors          = [reason],
        )

    # ── 5. Build response ─────────────────────────────────────────────────────
    resp_status: Literal["success", "partial", "failed", "blocked"] = (
        "partial" if verify_gaps else "success"
    )

    verification = VerificationSummary(
        invoice_refs_match    = v.get("invoice_refs_match"),
        cif_match             = v.get("cif_match"),
        qty_match_by_type     = v.get("qty_match_by_type"),
        importer_match        = v.get("importer_match"),
        exporter_match        = v.get("exporter_match"),
        blocked_phrases_clean = v.get("blocked_phrases_clean"),
        duty_rate_ok          = v.get("duty_rate_ok"),
        amendment_flags       = amendment_flags,
    )

    # Derive URLs from actual output filenames (batch_id-suffixed)
    pdf_name  = result["pdf_path"].name
    xlsx_name = result["xlsx_path"].name
    pdf_url   = f"/api/v1/files/{batch_id}/{pdf_name}"
    xlsx_url  = f"/api/v1/files/{batch_id}/{xlsx_name}"

    # ── 6. Post to Cliq ───────────────────────────────────────────────────────
    cliq_posted = False
    if post_to_cliq:
        result["batch_id"] = batch_id
        cliq_posted = await cliq_service.deliver_batch_result(
            result      = result,
            doc_no      = doc_no,
            target_type = target_type,
            target_id   = target_id,
        )

    batch_service.cleanup_working(batch_id)

    # ── Build correction summary for API response ─────────────────────────────
    corr_summary: Optional[CorrectionSummary] = None
    cr = result.get("correction_report")
    if cr:
        corr_summary = CorrectionSummary(
            has_critical  = cr.get("has_critical", False),
            has_warning   = cr.get("has_warning",  False),
            total_items   = len(cr.get("corrections", [])),
            critical_keys = [c["check_key"] for c in cr.get("corrections", []) if c["severity"] == "CRITICAL"],
            warning_keys  = [c["check_key"] for c in cr.get("corrections", []) if c["severity"] == "WARNING"],
        )

    return ProcessResponse(
        status           = resp_status,
        batch_id         = batch_id,
        document_no      = doc_no,
        summary          = BatchSummary(
            lines        = result["line_count"],
            total_net    = result["total_net"],
            total_gross  = result["total_gross"],
            duty_pln     = result["duty_pln"],
        ),
        verification     = verification,
        files            = OutputFiles(pdf_url=pdf_url, xlsx_url=xlsx_url),
        corrections_log  = corrections,
        errors           = errors,
        cliq_posted      = cliq_posted,
        audit_score      = result.get("audit_score"),
        audit_risk_level = result.get("audit_risk_level"),
        correction_summary = corr_summary,
    )


# ── Learning feedback endpoint ────────────────────────────────────────────────

# Idempotency set: (batch_id, confirmed_by, feedback)
# Prevents double-click spam and duplicate submissions within the same process.
# Resets on server restart (acceptable — persistent idempotency is in the
# learning store's feedback_log, which update_learning_store already deduplicates).
_feedback_seen: set = set()

_MAX_CONFIRMED_BY = 200
_MAX_REASON       = 1000


class FeedbackRequest(BaseModel):
    batch_id:     str
    doc_no:       str = ""
    feedback:     Literal["valid", "review", "incorrect"]
    confirmed_by: str = ""   # email or name of person confirming (audit trail)
    reason:       str = ""   # free-text justification for this feedback decision


class FeedbackResponse(BaseModel):
    status:   str
    batch_id: str
    feedback: str
    promoted: List[dict] = []
    skipped:  bool = False   # True when idempotency key matched


@router.post("/feedback", dependencies=[_auth], response_model=FeedbackResponse)
async def submit_feedback(req: FeedbackRequest) -> FeedbackResponse:
    """
    Record human feedback for a processed batch.

    - confirmed_by: email/name of person approving (stored in audit log)
    - reason: justification for this feedback decision (stored in audit log)
    - Promotes pattern memory when feedback is 'valid' (≥3 confirmations required).
    - Idempotent: duplicate (batch_id, confirmed_by, feedback) within same server
      process returns status='ok', skipped=True immediately.
    """
    # ── Validation ────────────────────────────────────────────────────────────
    if not req.batch_id or not req.batch_id.strip():
        raise HTTPException(status_code=422, detail="batch_id is required.")

    if len(req.confirmed_by) > _MAX_CONFIRMED_BY:
        raise HTTPException(
            status_code=422,
            detail=f"confirmed_by must be ≤ {_MAX_CONFIRMED_BY} characters.",
        )
    if len(req.reason) > _MAX_REASON:
        raise HTTPException(
            status_code=422,
            detail=f"reason must be ≤ {_MAX_REASON} characters.",
        )

    # ── Idempotency ───────────────────────────────────────────────────────────
    idem_key = (req.batch_id.strip(), req.confirmed_by.strip(), req.feedback)
    if idem_key in _feedback_seen:
        log.info(
            "Feedback duplicate skipped: batch=%s by='%s' feedback=%s",
            req.batch_id, req.confirmed_by, req.feedback,
        )
        return FeedbackResponse(
            status   = "ok",
            batch_id = req.batch_id,
            feedback = req.feedback,
            skipped  = True,
        )

    import sys
    engine_dir = str(settings.engine_dir)
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)

    try:
        from learning_agent import load_learning_store, update_learning_store, save_learning_store
        store = load_learning_store()
        store = update_learning_store(
            req.batch_id, req.doc_no, req.feedback, store,
            confirmed_by = req.confirmed_by,
            reason       = req.reason,
        )
        save_learning_store(store)

        # Register in idempotency set only after successful write
        _feedback_seen.add(idem_key)

        last_log = store["feedback_log"][-1] if store["feedback_log"] else {}
        promoted = last_log.get("promoted", [])
        log.info(
            "Feedback '%s' for batch %s by '%s' — promoted %d pattern(s)",
            req.feedback, req.batch_id, req.confirmed_by or "anonymous", len(promoted),
        )
        return FeedbackResponse(
            status   = "recorded",
            batch_id = req.batch_id,
            feedback = req.feedback,
            promoted = promoted,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("Feedback recording failed for %s: %s", req.batch_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Learning store inspection ─────────────────────────────────────────────────

@router.get("/learning/summary", dependencies=[_auth])
async def learning_summary() -> dict:
    """
    Full risk view of the current learning store.

    Per pattern:
      pattern_id, key, confirmed, confirmations, maturity, trusted,
      confidence (current effective confidence after decay),
      last_used, first_seen, applied_batches (count of valid promotions)

    Also returns: freeze_mode, feedback_log_count, last_updated.
    """
    import sys
    engine_dir = str(settings.engine_dir)
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)

    try:
        from learning_agent import (
            load_learning_store, maturity_level, _decayed_confidence,
            _MIN_CONFIRMATIONS, _LEARNING_FROZEN,
        )

        store = load_learning_store()

        # Build a lookup: pattern_id → count of valid promotions from feedback log
        applied_counts: dict = {}
        for entry in store.get("feedback_log", []):
            if entry.get("feedback") != "valid":
                continue
            for p in entry.get("promoted", []):
                pid = p.get("pattern_id", "")
                applied_counts[pid] = applied_counts.get(pid, 0) + 1

        def _confidence_for(p: dict, pat_type: str) -> Optional[float]:
            """Estimate current decayed confidence for a pattern."""
            n = p.get("confirmation_count", 0)
            if not p.get("confirmed") or n < _MIN_CONFIRMATIONS:
                return None
            n_capped = min(n, 20)
            if pat_type == "freight_patterns":
                base = min(0.95, 0.5 + (n_capped - _MIN_CONFIRMATIONS) * 0.03)
            elif pat_type == "exporter_aliases":
                base = min(0.90, 0.5 + (n_capped - _MIN_CONFIRMATIONS) * 0.05)
            else:
                base = min(0.95, 0.5 + (n_capped - _MIN_CONFIRMATIONS) * 0.05)
            last_seen = p.get("last_seen", "")
            return round(_decayed_confidence(base, last_seen), 4)

        def _pat_summary(patterns: dict, pat_type: str) -> list:
            rows = []
            for k, p in patterns.items():
                n     = p.get("confirmation_count", 0)
                pid   = p.get("pattern_id", k)
                conf  = _confidence_for(p, pat_type)
                mat   = maturity_level(n)

                row: dict = {
                    "pattern_id":      pid,
                    "key":             k,
                    "confirmed":       p.get("confirmed", False),
                    "confirmations":   n,
                    "maturity":        mat,
                    "trusted":         p.get("confirmed", False) and n >= _MIN_CONFIRMATIONS,
                    "confidence":      conf,
                    "last_used":       p.get("last_seen", ""),
                    "first_seen":      p.get("first_seen", ""),
                    "applied_batches": applied_counts.get(pid, 0),
                }

                # Type-specific fields
                if pat_type == "freight_patterns":
                    stats = p.get("stats", {})
                    row["supplier"]       = p.get("supplier", "")
                    row["sample_count"]   = stats.get("count", 0)
                    row["avg_freight_pct"] = round(stats.get("avg_freight_pct", 0) * 100, 3)
                    row["std_freight_pct"] = round(stats.get("std_freight_pct", 0) * 100, 3)
                    row["tol_freight_pct"] = round(stats.get("tol_freight_pct", 0) * 100, 3)
                elif pat_type == "address_patterns":
                    row["company"] = p.get("company", "")
                    row["nip"]     = p.get("nip", "")
                    row["address"] = p.get("address", "")
                elif pat_type == "exporter_aliases":
                    row["canonical"] = p.get("canonical", "")
                    row["aliases"]   = p.get("aliases", [])

                rows.append(row)
            return sorted(rows, key=lambda r: r["confirmations"], reverse=True)

        return {
            "freeze_mode":        _LEARNING_FROZEN,
            "freight_patterns":   _pat_summary(store.get("freight_patterns", {}),  "freight_patterns"),
            "address_patterns":   _pat_summary(store.get("address_patterns", {}),  "address_patterns"),
            "exporter_aliases":   _pat_summary(store.get("exporter_aliases", {}),  "exporter_aliases"),
            "feedback_log_count": len(store.get("feedback_log", [])),
            "last_updated":       store.get("last_updated", ""),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Global PZ Lineage (read-only authority surface) ──────────────────────────
#
# Exposes the invoice→packing→PZ relational authority built by
# global_pz_lineage.build_global_pz_lineage for Global Jewellery batches.
# Gate: Global supplier only (detected from source PDF content).
# No writes. No PZ mutation. No wFirma calls.
#
# Returns {is_global_supplier: false} for non-Global batches so the
# dashboard can suppress the panel cleanly without a 404 branch.


def _is_global_batch(batch_id: str) -> bool:
    """Detect Global Jewellery supplier by scanning the first 1k chars of any
    source PDF.  Pure read — no DB writes, no network calls."""
    try:
        from ..services.supplier_detect import detect_supplier  # noqa: PLC0415
        import pdfplumber  # noqa: PLC0415
    except Exception:
        return False
    for sub in ("outputs", "working"):
        base = settings.storage_root / sub / batch_id / "source"
        if not base.is_dir():
            continue
        for cat in ("invoices", "packing"):
            d = base / cat
            if not d.is_dir():
                continue
            for pdf in sorted(d.glob("*.pdf")):
                try:
                    with pdfplumber.open(str(pdf)) as p:
                        if not p.pages:
                            continue
                        head = (p.pages[0].extract_text() or "")[:1000]
                    if detect_supplier(head) == "global_jewellery":
                        return True
                except Exception:
                    continue
        break
    return False


def _find_source_pdf(batch_id: str, category: str) -> Optional[Path]:
    """Return the first PDF in source/{category}/ across outputs/ and working/."""
    for sub in ("outputs", "working"):
        d = settings.storage_root / sub / batch_id / "source" / category
        if d.is_dir():
            pdfs = sorted(d.glob("*.pdf"))
            if pdfs:
                return pdfs[0]
    return None


def _load_pz_rows_from_audit(batch_id: str) -> Optional[List[Dict[str, Any]]]:
    """Load audit.json rows[] for this batch. Returns None when absent."""
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / batch_id / "audit.json"
        if p.exists():
            try:
                audit = json.loads(p.read_text(encoding="utf-8"))
                rows = audit.get("rows") or []
                return rows or None
            except Exception:
                return None
    return None


def _extract_invoice_no(inv_pdf: Path) -> str:
    """Extract invoice number (NNN/YYYY-YYYY) from the invoice PDF using the
    engine parser; falls back to the file stem if the engine is unavailable."""
    engine_dir = str(settings.engine_dir)
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)
    try:
        from pz_import_processor import parse_invoice as _pi  # noqa: PLC0415
        inv = _pi(str(inv_pdf), [])
        if isinstance(inv, dict):
            raw = str(inv.get("_raw_text") or "")
            m = re.search(r"\b(\d{1,4}/\d{4}-\d{4})\b", raw)
            if m:
                return m.group(1)
            return str(inv.get("invoice_no") or "").strip()
    except Exception:
        pass
    return inv_pdf.stem


@router.get("/pz/lineage/{batch_id}", dependencies=[_auth])
def global_pz_lineage(batch_id: str) -> Dict[str, Any]:
    """Read-only invoice→packing→PZ relational authority for Global Jewellery.

    Returns the 4-dimensional match status, position links, and confidence
    reasons. Gated to Global Jewellery batches only. Returns
    ``{is_global_supplier: false}`` for all other batches so the dashboard
    can suppress the panel without raising a 404.

    No writes. No PZ mutation. No wFirma calls.
    """
    import dataclasses  # noqa: PLC0415

    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    # ── 1. Supplier gate ─────────────────────────────────────────────────────
    if not _is_global_batch(batch_id):
        return {"batch_id": batch_id, "is_global_supplier": False}

    # ── 2. Locate source files ───────────────────────────────────────────────
    inv_pdf  = _find_source_pdf(batch_id, "invoices")
    pack_pdf = _find_source_pdf(batch_id, "packing")

    if not inv_pdf:
        return {
            "batch_id":           batch_id,
            "is_global_supplier": True,
            "error":              "invoice PDF not found in source/invoices/",
            "match_status":       "UNMATCHED",
        }
    if not pack_pdf:
        return {
            "batch_id":           batch_id,
            "is_global_supplier": True,
            "error":              "packing PDF not found in source/packing/",
            "match_status":       "UNMATCHED",
        }

    # ── 3. Parse ─────────────────────────────────────────────────────────────
    try:
        from ..services.global_invoice_position_parser import (  # noqa: PLC0415
            parse_invoice_positions_from_pdf,
        )
        from ..services.global_packing_parser import (  # noqa: PLC0415
            parse_global_packing_pdf,
        )
        from ..services.global_pz_lineage import build_global_pz_lineage  # noqa: PLC0415
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"lineage parsers unavailable: {exc}")

    try:
        positions = parse_invoice_positions_from_pdf(inv_pdf)
    except Exception as exc:
        return {
            "batch_id":           batch_id,
            "is_global_supplier": True,
            "error":              f"invoice parse failed: {exc}",
            "match_status":       "UNMATCHED",
        }

    try:
        pack_rows, *_ = parse_global_packing_pdf(pack_pdf)
    except Exception as exc:
        return {
            "batch_id":           batch_id,
            "is_global_supplier": True,
            "error":              f"packing parse failed: {exc}",
            "match_status":       "UNMATCHED",
        }

    # ── 4. Load optional PZ rows from audit ─────────────────────────────────
    pz_rows = _load_pz_rows_from_audit(batch_id)

    # ── 5. Build lineage ─────────────────────────────────────────────────────
    invoice_no = _extract_invoice_no(inv_pdf)
    result = build_global_pz_lineage(positions, pack_rows, pz_rows, invoice_no)

    # ── 6. Serialize and annotate ─────────────────────────────────────────────
    d = dataclasses.asdict(result)
    d["batch_id"]           = batch_id
    d["is_global_supplier"] = True
    return d


def _load_pz_rows_from_file(batch_id: str) -> Optional[List[Dict[str, Any]]]:
    """Load pz_rows.json for this batch (posted PZ grouping). Returns None if absent."""
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / batch_id / "pz_rows.json"
        if p.exists():
            try:
                import json as _json  # noqa: PLC0415
                return _json.loads(p.read_text(encoding="utf-8")) or None
            except Exception:
                return None
    return None


def _load_authority_rows_from_audit(batch_id: str) -> Optional[List[Dict[str, Any]]]:
    """Load _pz_engine_authority_rows from audit.json. Returns None if absent."""
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / batch_id / "audit.json"
        if p.exists():
            try:
                import json as _json  # noqa: PLC0415
                audit = _json.loads(p.read_text(encoding="utf-8"))
                rows = audit.get("_pz_engine_authority_rows") or []
                return rows or None
            except Exception:
                return None
    return None


@router.get("/pz/lineage/{batch_id}/correction-proposal", dependencies=[_auth])
def global_pz_correction_proposal(batch_id: str) -> Dict[str, Any]:
    """Read-only correction proposal for the posted Global Jewellery PZ.

    Compares the posted PZ grouping (pz_rows.json), the engine authority
    (audit._pz_engine_authority_rows), and the live lineage result to produce
    a structured CorrectionProposal with zero-to-three correction options.

    Gate: Global Jewellery batches only.
    No writes. No wFirma calls. No PZ mutation.
    Operator approval is required before any corrective write can be issued.
    """
    import dataclasses  # noqa: PLC0415

    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    if not _is_global_batch(batch_id):
        return {"batch_id": batch_id, "is_global_supplier": False}

    inv_pdf  = _find_source_pdf(batch_id, "invoices")
    pack_pdf = _find_source_pdf(batch_id, "packing")

    if not inv_pdf or not pack_pdf:
        return {
            "batch_id":           batch_id,
            "is_global_supplier": True,
            "error":              "source PDFs not found; lineage unavailable",
        }

    try:
        from ..services.global_invoice_position_parser import (  # noqa: PLC0415
            parse_invoice_positions_from_pdf,
        )
        from ..services.global_packing_parser import parse_global_packing_pdf  # noqa: PLC0415
        from ..services.global_pz_lineage import build_global_pz_lineage  # noqa: PLC0415
        from ..services.global_pz_correction import build_correction_proposal  # noqa: PLC0415
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"correction modules unavailable: {exc}")

    try:
        positions = parse_invoice_positions_from_pdf(inv_pdf)
        pack_rows, *_ = parse_global_packing_pdf(pack_pdf)
    except Exception as exc:
        return {
            "batch_id":           batch_id,
            "is_global_supplier": True,
            "error":              f"parse failed: {exc}",
        }

    invoice_no     = _extract_invoice_no(inv_pdf)
    pz_rows        = _load_pz_rows_from_file(batch_id)
    authority_rows = _load_authority_rows_from_audit(batch_id)
    lineage_result = build_global_pz_lineage(positions, pack_rows, None, invoice_no)

    proposal = build_correction_proposal(
        batch_id=batch_id,
        invoice_no=invoice_no,
        lineage_result=lineage_result,
        pz_rows=pz_rows,
        authority_rows=authority_rows,
    )

    d = dataclasses.asdict(proposal)
    d["is_global_supplier"] = True
    return d


# ── Global PZ correction execution ───────────────────────────────────────────

class CorrectionExecuteRequest(BaseModel):
    option_id:       str
    operator_reason: str


@router.post("/pz/lineage/{batch_id}/correction-execute", dependencies=[_auth])
def global_pz_correction_execute(
    batch_id: str,
    body: CorrectionExecuteRequest,
) -> Dict[str, Any]:
    """Governed execution of a Global PZ correction option.

    Execution target: LOCAL pz_rows.json only.
    No wFirma API calls.  wFirma push is a separate, downstream operator step.

    Safety properties (Lesson E compliance):
      1. Execution-time validation  -- option_id and pz_rows validated here.
      2. Idempotency                -- correction_execution_record.json checked
                                       before any write.
      3. Terminal-state suppression -- is_global_supplier gate enforced here
                                       before calling the service.
      4. Replay safety              -- backup + record written atomically.
      5. No direct wFirma calls     -- only the existing PZ pipeline calls wFirma.
    """
    import dataclasses  # noqa: PLC0415

    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    # --- Terminal-state suppression: Global supplier gate ---
    if not _is_global_batch(batch_id):
        raise HTTPException(
            status_code=403,
            detail="Correction execution is only available for Global Jewellery batches.",
        )

    # --- Re-derive proposed_lines server-side ---
    inv_pdf  = _find_source_pdf(batch_id, "invoices")
    pack_pdf = _find_source_pdf(batch_id, "packing")
    if not inv_pdf or not pack_pdf:
        raise HTTPException(
            status_code=422,
            detail="Source PDFs not found; cannot re-derive correction proposal.",
        )

    try:
        from ..services.global_invoice_position_parser import (  # noqa: PLC0415
            parse_invoice_positions_from_pdf,
        )
        from ..services.global_packing_parser import parse_global_packing_pdf  # noqa: PLC0415
        from ..services.global_pz_lineage import build_global_pz_lineage  # noqa: PLC0415
        from ..services.global_pz_correction import build_correction_proposal  # noqa: PLC0415
        from ..services.global_pz_execution import execute_correction_option  # noqa: PLC0415
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"correction modules unavailable: {exc}")

    try:
        positions = parse_invoice_positions_from_pdf(inv_pdf)
        pack_rows, *_ = parse_global_packing_pdf(pack_pdf)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"parse failed: {exc}")

    invoice_no     = _extract_invoice_no(inv_pdf)
    pz_rows        = _load_pz_rows_from_file(batch_id)
    authority_rows = _load_authority_rows_from_audit(batch_id)
    lineage_result = build_global_pz_lineage(positions, pack_rows, None, invoice_no)

    proposal = build_correction_proposal(
        batch_id=batch_id,
        invoice_no=invoice_no,
        lineage_result=lineage_result,
        pz_rows=pz_rows,
        authority_rows=authority_rows,
    )

    # Extract ProposedLine list from the re-derived proposal
    proposed_lines = proposal.proposed_lines

    # --- Execute ---
    result = execute_correction_option(
        batch_id=batch_id,
        option_id=body.option_id,
        operator_reason=body.operator_reason,
        proposed_lines=proposed_lines,
        storage_root=settings.storage_root,
    )

    if not result.ok:
        raise HTTPException(status_code=422, detail=result.error or "Execution failed.")

    return dataclasses.asdict(result)


# ── File download ─────────────────────────────────────────────────────────────

@router.get("/files/{batch_id}/source/{category}/{filename}", dependencies=[_auth])
async def download_source_file(batch_id: str, category: str, filename: str) -> FileResponse:
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    if category not in ("invoices", "sad", "awb"):
        raise HTTPException(status_code=400, detail="Invalid category.")
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    file_path = settings.storage_root / "outputs" / batch_id / "source" / category / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Source file not found.")

    media = "application/pdf"  # all source files are PDFs
    return FileResponse(path=str(file_path), media_type=media, filename=filename)


@router.get("/files/{batch_id}/{filename}", dependencies=[_auth])
async def download_file(batch_id: str, filename: str) -> FileResponse:
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    file_path = settings.storage_root / "outputs" / batch_id / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")

    if filename.endswith(".pdf"):
        media = "application/pdf"
    elif filename.endswith(".xlsx"):
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        media = "text/plain; charset=utf-8"
    return FileResponse(path=str(file_path), media_type=media, filename=filename)
