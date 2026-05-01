"""
routes_lifecycle.py — Endpoints for the post-DHL → closure lifecycle layer.

  POST /api/v1/agency-documents/{batch_id}/received   — register agency SAD/PZC docs
  POST /api/v1/service-invoices/{batch_id}/received   — register DHL/agency invoices
  POST /api/v1/closure/{batch_id}/evaluate            — run closure engine
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.security import require_api_key

log    = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["lifecycle"])
_auth  = Depends(require_api_key)


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


# ── Closure evaluation ───────────────────────────────────────────────────────

@router.post("/closure/{batch_id}/evaluate", dependencies=[_auth])
def evaluate_closure_endpoint(batch_id: str) -> Dict[str, Any]:
    from ..services.shipment_closure import closure_for_batch
    return closure_for_batch(batch_id)
