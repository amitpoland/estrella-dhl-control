"""routes_packing_advance.py — pre-shipment (advance) packing lists.

  POST   /api/v1/packing-advance/upload
         Upload a packing list the supplier sent BEFORE dispatch. Creates (or
         appends to) an ADVANCE_* batch. Parses design_no + quantity only.

  GET    /api/v1/packing-advance
         List advance documents. ?linked=false shows the ones still waiting
         for their shipment; ?include_withdrawn=true also shows retracted ones.

  POST   /api/v1/packing-advance/{document_id}/withdraw
         Body: {"reason": "..."} — the operator's repair for a wrong upload or
         a wrong link. Retracts, never deletes: the rows and the link stay put
         and the reason is recorded beside them.

  GET    /api/v1/packing-advance/{document_id}
         One advance document plus its lines.

  POST   /api/v1/packing-advance/{document_id}/link
         Body: {"batch_id": "SHIPMENT_..."} — record which real shipment
         fulfilled this advance list. Set once; never rewrites either document.

  GET    /api/v1/packing-advance/{document_id}/reconciliation
         Expected (advance) vs actual (final purchase packing) by design_no.

  GET    /api/v1/packing-advance/status
         Module status for the operator panel: last activity, document
         counts, and the documents actually needing attention.

Own prefix, NOT ``/api/v1/packing/...``: that router owns ``/{batch_id}`` as a
GET, so any literal sibling segment there would be a route-ordering trap.

Hard rules — enforced by the service layer, restated here because this is the
surface an operator can reach:
  * no inventory state is seeded (goods do not exist yet),
  * no product_code is minted (ADR-024 mints it from the purchase invoice),
  * no scan_code, no CPA/product_master write, no wFirma, no PZ, no proforma,
  * advance batches get NO storage/outputs/ directory, so the shipment list
    never shows a phantom shipment.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import (APIRouter, Body, Depends, HTTPException, Query,
                     UploadFile)

from ..core.config import settings
from ..core.logging import get_logger
from ..auth.dependencies import get_current_user
from ..services import advance_packing as adv
from ..services import packing_db as pdb

log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1/packing-advance", tags=["packing-advance"])
_auth  = Depends(get_current_user)

_ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls"}


def _operator_of(user: Dict[str, Any]) -> str:
    """Who is acting. The authenticated session is the ONLY authority.

    An earlier revision let an ``X-Operator-User`` header win whenever it was
    present, so any session holder could attribute an advance upload or link
    to somebody else with one extra curl flag -- and a link is deliberately
    hard to undo, so the false name stuck. Audit attribution must not be
    forgeable by whoever crafts the request. Nothing falls back to a header:
    the V2 shell never sent one.
    """
    return str(
        (user or {}).get("full_name") or (user or {}).get("email") or ""
    ).strip()


def _safe_name(filename: str) -> str:
    name = Path(filename or "advance_packing_list").name
    return "".join(c if c.isalnum() or c in "._- " else "_" for c in name)


@router.post("/upload")
async def upload_advance_packing_list(
    file:        UploadFile,
    supplier_id: Optional[int] = Query(default=None),
    batch_id:    Optional[str] = Query(default=None,
                                       description="Append to an existing ADVANCE_* batch"),
    user:        Dict[str, Any] = _auth,
) -> Dict[str, Any]:
    operator = _operator_of(user)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type {suffix!r}. Accepted: PDF, XLSX, XLS.",
        )

    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max {settings.max_upload_bytes // (1024 * 1024)} MB.",
        )

    bid = batch_id or adv.new_advance_id()
    if not adv.is_advance_batch(bid):
        raise HTTPException(status_code=400,
                            detail=f"Not an advance batch id: {bid!r}")

    dest_dir = adv.advance_source_dir(bid)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / _safe_name(file.filename or "")
    existed  = dest.exists()
    previous = dest.read_bytes() if existed else b""
    dest.write_bytes(content)

    def _undo() -> None:
        # A rejected upload must not leave the batch's source directory
        # holding a file that was never ingested.
        if existed:
            dest.write_bytes(previous)
        else:
            dest.unlink(missing_ok=True)

    try:
        return adv.ingest_advance(dest, supplier_id=supplier_id,
                                  batch_id=bid, operator=operator)
    except ValueError as exc:
        _undo()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _undo()
        log.warning("advance packing extraction failed for %s: %s", dest, exc)
        raise HTTPException(status_code=422,
                            detail=f"Advance packing list extraction failed: {exc}")


@router.get("", dependencies=[_auth])
def list_advance_packing_lists(
    linked:            Optional[bool] = Query(default=None),
    include_withdrawn: bool           = Query(default=False),
) -> Dict[str, Any]:
    docs = adv.list_advance_documents(linked=linked,
                                      include_withdrawn=include_withdrawn)
    return {"count": len(docs), "documents": docs}


@router.get("/status", dependencies=[_auth])
def advance_packing_status() -> Dict[str, Any]:
    """Operator status for the Advance Packing module.

    Registered BEFORE ``/{document_id}`` on purpose: that route would match the
    literal segment ``status`` and answer 404 for a document of that name --
    the same ordering trap this module's own prefix exists to avoid.

    Never raises. A status screen that 500s tells the operator nothing about
    the thing it is supposed to be reporting on, so an unreadable store comes
    back as ``healthy: false`` with the reason in ``last_error``.
    """
    return adv.advance_status()


@router.get("/{document_id}", dependencies=[_auth])
def get_advance_packing_list(document_id: str) -> Dict[str, Any]:
    doc = adv.get_advance_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404,
                            detail=f"No advance packing document {document_id!r}")
    lines: List[Dict[str, Any]] = pdb.get_packing_lines_for_document(document_id)
    return {"document": doc, "line_count": len(lines), "lines": lines}


@router.post("/{document_id}/link")
def link_advance_to_shipment(
    document_id: str,
    body:        Dict[str, Any] = Body(...),
    user:        Dict[str, Any] = _auth,
) -> Dict[str, Any]:
    operator = _operator_of(user)
    batch_id = str(body.get("batch_id") or "").strip()
    if not batch_id:
        raise HTTPException(status_code=400, detail="batch_id is required.")
    try:
        return adv.link_to_batch(document_id, batch_id, operator=operator)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{document_id}/withdraw")
def withdraw_advance_packing_list(
    document_id: str,
    body:        Dict[str, Any] = Body(...),
    user:        Dict[str, Any] = _auth,
) -> Dict[str, Any]:
    operator = _operator_of(user)
    reason   = str(body.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=400,
                            detail="A reason is required to withdraw this list.")
    try:
        return adv.withdraw(document_id, reason, operator=operator)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{document_id}/reconciliation", dependencies=[_auth])
def get_advance_reconciliation(document_id: str) -> Dict[str, Any]:
    try:
        return adv.reconcile(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
