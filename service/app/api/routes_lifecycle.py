"""
routes_lifecycle.py — Endpoints for the post-DHL → closure lifecycle layer.

  POST /api/v1/agency-documents/{batch_id}/received   — register agency SAD/PZC docs (server paths)
  POST /api/v1/agency-documents/{batch_id}/upload     — browser-safe multipart upload
  POST /api/v1/service-invoices/{batch_id}/received   — register DHL/agency invoices
  POST /api/v1/closure/{batch_id}/evaluate            — run closure engine
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ..core.config   import settings
from ..core.security import require_api_key

log    = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["lifecycle"])
_auth  = Depends(require_api_key)

_ALLOWED_EXTENSIONS = {".pdf", ".xml", ".html", ".htm", ".jpg", ".jpeg", ".png"}
_MAX_UPLOAD_BYTES   = 50 * 1024 * 1024   # 50 MB per file


def _validate_upload(file: UploadFile) -> None:
    suffix = Path(file.filename or "").suffix.lower()
    if not suffix or suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type {suffix!r}. Allowed: "
                   + ", ".join(sorted(_ALLOWED_EXTENSIONS)),
        )


# ── Agency-document registration ─────────────────────────────────────────────

class AgencyDocsReq(BaseModel):
    file_paths: List[str]
    source:     Optional[str] = "operator"
    note:       Optional[str] = ""


@router.post("/agency-documents/{batch_id}/received", dependencies=[_auth])
def register_agency_docs_endpoint(batch_id: str, body: AgencyDocsReq) -> Dict[str, Any]:
    if not body.file_paths:
        raise HTTPException(status_code=422, detail="file_paths is empty")
    from ..services.agency_sad_monitor import register_agency_documents
    return register_agency_documents(
        batch_id, body.file_paths, source=body.source or "operator",
        note=body.note or "",
    )


@router.post("/agency-documents/{batch_id}/upload", dependencies=[_auth])
async def upload_agency_docs_endpoint(
    batch_id: str,
    files:  List[UploadFile],
    source: str = Form(default="operator"),
    note:   str = Form(default=""),
) -> Dict[str, Any]:
    """
    Browser-safe multipart upload for agency customs documents (SAD, PZC, ZC429, etc.).

    Accepts one or more files (.pdf, .xml, .html, .htm, .jpg, .jpeg, .png).
    Each file is saved to a controlled server-side temp path, then handed to
    register_agency_documents() which copies it into the structured shipment
    folder and updates the audit.

    Does not accept client-provided server paths.
    Does not use placeholder paths.
    """
    if not files:
        raise HTTPException(status_code=422, detail="No files provided.")
    for f in files:
        _validate_upload(f)

    from ..services.agency_sad_monitor import register_agency_documents

    saved_paths: List[str] = []
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"agency_upload_{batch_id}_"))
    try:
        for f in files:
            content = await f.read()
            if len(content) == 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"File '{f.filename}' is empty.",
                )
            if len(content) > _MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"File '{f.filename}' exceeds {_MAX_UPLOAD_BYTES // (1024*1024)} MB limit.",
                )
            safe_name = Path(f.filename or "document").name
            safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in safe_name)
            dest = tmp_dir / safe_name
            dest.write_bytes(content)
            saved_paths.append(str(dest))

        result = register_agency_documents(
            batch_id,
            saved_paths,
            source=source or "operator",
            note=note or "",
        )
    finally:
        # Clean up temp files that were NOT copied by register_agency_documents
        # (successfully imported files are already copied to the shipment folder;
        #  skipped files were never registered so safe to discard)
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result)
    return result


# ── Service-invoice registration ─────────────────────────────────────────────

class ServiceInvoiceReq(BaseModel):
    file_paths: List[str]
    source:     Optional[str] = "operator"


@router.post("/service-invoices/{batch_id}/received", dependencies=[_auth])
def register_service_invoices_endpoint(batch_id: str, body: ServiceInvoiceReq) -> Dict[str, Any]:
    if not body.file_paths:
        raise HTTPException(status_code=422, detail="file_paths is empty")
    from ..services.service_invoice_monitor import register_service_invoices
    return register_service_invoices(batch_id, body.file_paths, source=body.source or "operator")


@router.post("/service-invoices/{batch_id}/upload", dependencies=[_auth])
async def upload_service_invoices_endpoint(
    batch_id: str,
    files:    List[UploadFile],
    source:   str = Form(default="operator"),
) -> Dict[str, Any]:
    """
    Browser-safe multipart upload for service invoices (DHL, agency).

    Accepts one or more files (.pdf, .xml, .html, .htm, .jpg, .jpeg, .png).
    Each file is saved to a controlled server-side temp path, then handed to
    register_service_invoices() which copies it into the structured shipment
    folder and updates the audit.

    Does not accept client-provided server paths.
    Does not use placeholder paths.
    """
    if not files:
        raise HTTPException(status_code=422, detail="No files provided.")
    for f in files:
        _validate_upload(f)

    from ..services.service_invoice_monitor import register_service_invoices

    saved_paths: List[str] = []
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"svc_invoice_upload_{batch_id}_"))
    try:
        for f in files:
            content = await f.read()
            if len(content) == 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"File '{f.filename}' is empty.",
                )
            if len(content) > _MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"File '{f.filename}' exceeds {_MAX_UPLOAD_BYTES // (1024*1024)} MB limit.",
                )
            safe_name = Path(f.filename or "invoice").name
            safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in safe_name)
            dest = tmp_dir / safe_name
            dest.write_bytes(content)
            saved_paths.append(str(dest))

        result = register_service_invoices(
            batch_id,
            saved_paths,
            source=source or "operator",
        )
    finally:
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result)
    return result


# ── Closure evaluation ───────────────────────────────────────────────────────

@router.post("/closure/{batch_id}/evaluate", dependencies=[_auth])
def evaluate_closure_endpoint(batch_id: str):
    """Deprecated — use /api/v1/execute/closure_confirm instead."""
    from fastapi.responses import JSONResponse
    return JSONResponse(
        {
            "ok":      False,
            "error":   "deprecated",
            "message": "Closure confirmation must use /api/v1/execute/closure_confirm",
        },
        status_code=410,
    )


@router.get("/closure/{batch_id}/check", dependencies=[_auth])
def check_closure_endpoint(batch_id: str) -> Dict[str, Any]:
    """
    Read-only closure readiness check.

    Calls evaluate_closure() only — never writes to audit, never sets
    status=completed, never marks ready_for_accounting.
    Safe to call from the dashboard at any time.
    """
    from ..services.shipment_closure import evaluate_closure
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / batch_id / "audit.json"
        if p.exists():
            import json as _json
            audit = _json.loads(p.read_text(encoding="utf-8"))
            result = evaluate_closure(audit)
            result["batch_id"] = batch_id
            result["current_status"] = audit.get("status", "unknown")
            result["already_completed"] = audit.get("status") == "completed"
            return result
    raise HTTPException(status_code=404, detail=f"batch {batch_id!r} not found")


# ── Agency CN-mismatch follow-up ──────────────────────────────────────────────

_AF_FORBIDDEN = ("..", "/", "\\")


class AgencyFollowupReq(BaseModel):
    batch_id: str
    reason:   str = ""


@router.post("/lifecycle/agency-followup", dependencies=[_auth])
def agency_followup_endpoint(body: AgencyFollowupReq) -> Dict[str, Any]:
    """
    Queue an agency follow-up email for a CN-code mismatch.

    Operator-triggered from the dashboard CN-mismatch card.  The email is
    queued only — never sent directly.  Recipients come from email_routing /
    audit.clearance_decision.agency_email, never from the request payload.

    Guards
    ------
    - batch_id path-traversal check
    - 404 if audit.json not found
    - 409 if batch already completed
    - skipped (200) if agency_cn_followup.queued_at already set
    - audit written only after queue_email succeeds
    """
    import html as _html
    import json as _json
    from datetime import datetime, timezone

    from ..core import timeline as tl
    from ..services.action_email_builder import build_email_draft
    from ..services.email_service import queue_email

    batch_id = body.batch_id.strip()
    reason   = (body.reason or "").strip()

    # 1. Validate batch_id
    if not batch_id:
        raise HTTPException(status_code=400, detail="batch_id must not be empty")
    for frag in _AF_FORBIDDEN:
        if frag in batch_id:
            raise HTTPException(
                status_code=400,
                detail=f"batch_id contains forbidden character: {frag!r}",
            )

    # 2. Load audit
    audit: Optional[Dict[str, Any]] = None
    audit_path: Optional[Path] = None
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / batch_id / "audit.json"
        if p.exists():
            try:
                audit = _json.loads(p.read_text(encoding="utf-8"))
                audit_path = p
            except Exception as exc:
                log.error("agency_followup: audit parse error batch=%s: %s", batch_id, exc)
            break

    if audit is None or audit_path is None:
        raise HTTPException(status_code=404, detail=f"batch {batch_id!r} not found")

    # 3. Completed gate
    if audit.get("status") == "completed":
        raise HTTPException(
            status_code=409,
            detail="Cannot send agency follow-up: batch is already completed",
        )

    # 4. Idempotency — already queued
    existing = audit.get("agency_cn_followup") or {}
    if existing.get("queued_at"):
        return {"ok": True, "status": "skipped", "reason": "already_queued"}

    # 5. Build draft (recipients from email_routing, never from payload)
    draft = build_email_draft("agency_followup", audit)

    # 6. Append reason as plain text; rebuild HTML with escaping (never trust reason as HTML)
    if reason:
        body_with_reason = draft["body_text"] + f"\n\nReason: {reason}"
        draft["body_text"] = body_with_reason
        draft["body_html"] = (
            f"<pre style='font-family:sans-serif'>"
            f"{_html.escape(body_with_reason)}"
            f"</pre>"
        )

    # 7. Queue email (never send directly)
    try:
        email_id = queue_email(
            to           = draft["to"],
            subject      = draft["subject"],
            body_html    = draft["body_html"],
            body_text    = draft["body_text"],
            batch_id     = batch_id,
            cc           = draft.get("cc", ""),
            from_address = "import@estrellajewels.eu",
            email_type   = "agency_followup",
        )
    except Exception as exc:
        log.error("agency_followup: queue_email failed batch=%s: %s", batch_id, exc)
        raise HTTPException(status_code=502, detail=f"email queue failed: {exc}")

    # 8. Write audit (only after queue succeeds)
    now = datetime.now(timezone.utc).isoformat()
    try:
        audit["agency_cn_followup"] = {
            "queued_at": now,
            "email_id":  email_id,
            "reason":    reason,
            "to":        draft["to"],
        }
        tmp = audit_path.with_suffix(".json.tmp")
        tmp.write_text(_json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(audit_path)
        log.info("agency_followup: audit written batch=%s email_id=%s", batch_id, email_id)
    except Exception as exc:
        log.error(
            "agency_followup: audit write failed batch=%s (email already queued): %s",
            batch_id, exc,
        )

    # 9. Timeline event
    try:
        tl.log_event(
            audit_path,
            tl.EV_AGENCY_FOLLOWUP_SENT,
            trigger_source="lifecycle_endpoint",
            actor="operator",
            detail={"email_id": email_id, "to": draft["to"], "reason": reason},
        )
    except Exception as exc:
        log.warning("agency_followup: timeline event failed (non-fatal): %s", exc)

    return {
        "ok":       True,
        "queued":   True,
        "email_id": email_id,
        "to":       draft["to"],
        "batch_id": batch_id,
    }


# ── Direct-dispatch lifecycle promotion ──────────────────────────────────────
#
# Operator-explicit endpoint for goods that bypass the warehouse stock pool
# (DHL/agency-to-client direct delivery). Walks the supplied scan_codes
# through PURCHASE_TRANSIT → DIRECT_DISPATCH_READY via
# inventory_state_engine.transition() — never auto-promotes from RECEIVE
# alone, never touches wFirma / PZ / sales mappings.

class MarkDirectDispatchReq(BaseModel):
    batch_id:            str
    scan_codes:          List[str]
    operator:            str
    customer_allocation: str
    evidence_note:       Optional[str] = ""


def _customs_cleared_from_audit(batch_id: str) -> Dict[str, Any]:
    """
    Derive customs/PZ-clearance evidence from the on-disk audit, delegating
    to the shared read-time helper ``audit_evidence.effective_pz_evidence``.

    Returns ``{"cleared": bool, "signals": [...], "missing": [...]}``.
    Never accepts a caller-provided customs_cleared bool — the route owns
    this decision so the lifecycle gate cannot be bypassed by a forged body.

    The helper recognises stale-audit shapes (e.g. ``status="failed"`` on
    disk while a wfirma_pz_created timeline event proves PZ was issued) so
    a legitimate app-created PZ is never falsely rejected.
    """
    import json as _json
    from ..services.audit_evidence import effective_pz_evidence

    p = settings.storage_root / "outputs" / batch_id / "audit.json"
    if not p.exists():
        return {"cleared": False, "signals": [], "missing": ["audit.json"]}
    try:
        a = _json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"cleared": False, "signals": [],
                "missing": [f"audit.json unreadable: {exc}"]}

    ev = effective_pz_evidence(a)
    return {
        "cleared":          ev["has_evidence"],
        "signals":          ev["signals"],
        "wfirma_pz_doc_id": ev["wfirma_pz_doc_id"],
        "missing":          ev["missing"] if not ev["has_evidence"] else [],
    }


def _packing_scan_codes_for_batch(batch_id: str) -> set:
    """Set of legitimate scan_codes belonging to *batch_id* (from packing.db)."""
    from ..services import packing_db as _pdb
    out: set = set()
    try:
        for line in _pdb.get_packing_lines_for_batch(batch_id):
            sc = line.get("scan_code") or _pdb._compute_scan_code(line)
            if sc:
                out.add(sc)
    except Exception as exc:
        log.warning("packing scan-code load failed for %s: %s", batch_id, exc)
    return out


def _has_receive_event(scan_code: str, batch_id: str) -> bool:
    """True iff a RECEIVE movement event exists for *scan_code* in *batch_id*."""
    import sqlite3
    from ..services import warehouse_db as _wdb
    if _wdb._db_path is None:
        return False
    con = sqlite3.connect(str(_wdb._db_path))
    try:
        row = con.execute(
            "SELECT 1 FROM inventory_movement_events "
            "WHERE batch_id=? AND scan_code=? AND action='RECEIVE' LIMIT 1",
            (batch_id, scan_code),
        ).fetchone()
    finally:
        con.close()
    return row is not None


@router.post("/inventory-state/mark-direct-dispatch", dependencies=[_auth])
def mark_direct_dispatch(body: MarkDirectDispatchReq) -> Dict[str, Any]:
    """
    Mark each scan_code in *batch_id* as DIRECT_DISPATCH_READY.

    Idempotent: scan_codes already at DIRECT_DISPATCH_READY (or beyond on the
    direct-dispatch chain — i.e. CLIENT_DISPATCHED) are reported with
    outcome="already_ready" and no transition is attempted.

    Returns 400 on:
      - missing operator / customer_allocation
      - empty scan_codes
      - no customs/PZ clearance evidence in audit.json
    Returns 200 with per-line outcomes on success; lines that fail individual
    validation (not in batch, no RECEIVE, illegal current state) are reported
    with outcome="rejected" and a reason — they do NOT abort the batch.
    """
    from ..services import inventory_state_engine as _ise

    batch_id = (body.batch_id or "").strip()
    if not batch_id or "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    operator = (body.operator or "").strip()
    if not operator:
        raise HTTPException(status_code=400, detail="operator is required")
    customer = (body.customer_allocation or "").strip()
    if not customer:
        raise HTTPException(status_code=400,
                            detail="customer_allocation is required")
    if not body.scan_codes:
        raise HTTPException(status_code=400, detail="scan_codes is empty")

    # Customs/PZ clearance — route owns this; caller cannot supply it.
    customs = _customs_cleared_from_audit(batch_id)
    if not customs["cleared"]:
        raise HTTPException(
            status_code=400,
            detail={
                "error":   "customs/PZ clearance evidence missing",
                "batch_id": batch_id,
                "missing":  customs["missing"] or ["no clearance signals in audit.json"],
            },
        )

    legit = _packing_scan_codes_for_batch(batch_id)
    note  = (body.evidence_note or "").strip()

    results: List[Dict[str, Any]] = []
    for sc in body.scan_codes:
        sc = (sc or "").strip()
        if not sc:
            results.append({"scan_code": sc, "outcome": "rejected",
                            "reason": "empty scan_code"})
            continue
        if sc not in legit:
            results.append({"scan_code": sc, "outcome": "rejected",
                            "reason": "scan_code does not belong to batch"})
            continue

        cur = _ise.get_state(sc)
        cur_state = cur["state"] if cur else None
        if cur_state in (_ise.DIRECT_DISPATCH_READY, _ise.CLIENT_DISPATCHED):
            results.append({"scan_code": sc, "outcome": "already_ready",
                            "state": cur_state})
            continue

        if not _has_receive_event(sc, batch_id):
            results.append({"scan_code": sc, "outcome": "rejected",
                            "reason": "no RECEIVE movement event"})
            continue

        try:
            row = _ise.transition(
                scan_code=sc,
                to_state=_ise.DIRECT_DISPATCH_READY,
                operator=operator,
                customer_allocation=customer,
                customs_cleared=True,           # derived above; never from caller
                note=note,
                batch_id=batch_id,
            )
            results.append({"scan_code": sc, "outcome": "transitioned",
                            "state": row["state"]})
        except ValueError as exc:
            # Engine guard fired (illegal transition / residual evidence gap).
            results.append({"scan_code": sc, "outcome": "rejected",
                            "reason": str(exc)})

    transitioned = sum(1 for r in results if r["outcome"] == "transitioned")
    already      = sum(1 for r in results if r["outcome"] == "already_ready")
    rejected     = sum(1 for r in results if r["outcome"] == "rejected")

    # Append-only audit hardening: emit a timeline event so audit.json
    # carries proof of the operator's lifecycle decision. Best-effort.
    try:
        from ..services.audit_persist import record_inventory_direct_dispatch
        record_inventory_direct_dispatch(
            settings.storage_root / "outputs" / batch_id / "audit.json",
            batch_id            = batch_id,
            scan_codes          = [r["scan_code"] for r in results
                                    if r.get("outcome") in
                                    ("transitioned", "already_ready")],
            transitioned        = transitioned,
            already_ready       = already,
            operator            = operator,
            customer_allocation = customer,
            customs_signals     = customs["signals"],
            evidence_note       = note,
        )
    except Exception as exc:
        log.warning("mark-direct-dispatch audit append skipped: %s", exc)

    return {
        "ok":           True,
        "batch_id":     batch_id,
        "operator":     operator,
        "customer_allocation": customer,
        "customs_signals":    customs["signals"],
        "considered":   len(body.scan_codes),
        "transitioned": transitioned,
        "already_ready": already,
        "rejected":     rejected,
        "results":      results,
    }
