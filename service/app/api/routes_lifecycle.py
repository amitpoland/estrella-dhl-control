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
