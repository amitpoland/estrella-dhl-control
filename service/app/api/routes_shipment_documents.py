"""
Shipment Document Hub API + public customer delivery-confirmation.

Operator surface (all ``require_api_key``):
  GET  /api/v1/shipment-documents/draft/{draft_id}/manifest
       Aggregated document manifest for a draft's shipment (read-only).
  GET  /api/v1/shipment-documents/draft/{draft_id}/complete-package
       One ZIP of authoritative bytes (wFirma PDFs + packing list + DHL files).
       422 {missing:[...]} when the package is not ready. Lesson-G no-store.
  GET  /api/v1/shipment-documents/draft/{draft_id}/delivery
       Operator view of the customer's delivery confirmation / damage report.
  GET  /api/v1/shipment-documents/draft/{draft_id}/delivery/evidence/{evidence_id}
       Stream one uploaded evidence image (scoped to this draft's receipt).

Public surface (NO dashboard auth — the customer follows an emailed opaque link):
  GET  /api/v1/shipment-documents/public/receipt/{token}   → page metadata JSON
  POST /api/v1/shipment-documents/public/receipt/{token}   → multipart submit

The public receipt path performs NO fiscal / accounting / inventory / DHL
mutation — it only records a customer acknowledgement + optional photos.

The HTML page itself is served at ``GET /receipt/{token}`` (registered in
main.py, app root) so the emailed link stays short and un-prefixed.
"""
from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi import File as _File
from fastapi.responses import JSONResponse, Response

from ..core.security import require_api_key

router = APIRouter(prefix="/api/v1/shipment-documents", tags=["shipment-documents"])

log = logging.getLogger(__name__)

_NO_STORE_HEADERS = {
    # Lesson G — regenerable downloads must never be cached.
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

_MAX_EVIDENCE_FILES = 8


def _storage_root() -> Path:
    from ..core.config import settings
    return Path(settings.storage_root)


def _proforma_db() -> Path:
    return _storage_root() / "proforma_links.db"


def _carrier_db() -> Path:
    from ..core.config import settings
    root = settings.carrier_storage_root or (settings.storage_root / "carrier")
    return Path(root) / "carrier_shipments.db"


# ── Operator: manifest ──────────────────────────────────────────────────────────


@router.get("/draft/{draft_id}/manifest")
def get_manifest(draft_id: int, _auth: None = Depends(require_api_key)) -> JSONResponse:
    """Aggregated document manifest for a draft's shipment (read-only)."""
    from ..services import shipment_document_manifest as sdm
    try:
        manifest = sdm.build_manifest(
            int(draft_id),
            storage_root=_storage_root(),
            proforma_db=_proforma_db(),
            carrier_db=_carrier_db(),
        )
    except sdm.DraftNotFound:
        raise HTTPException(status_code=404, detail=f"draft {draft_id} not found")
    return JSONResponse(manifest)


# ── Operator: complete package ZIP ───────────────────────────────────────────────


@router.get("/draft/{draft_id}/complete-package")
def get_complete_package(
    draft_id: int, _auth: None = Depends(require_api_key),
) -> Response:
    """Build a ZIP of the authoritative shipment documents.

    Bytes come only from authorities: wFirma PDFs (fetched read-only), the
    Commercial Packing List (``commercial_packing_list`` presentation adapter), and the
    DHL label/waybill files saved at booking. 422 with a ``missing`` list when
    the package is not ready.
    """
    from ..services import shipment_document_manifest as sdm
    from ..services import proforma_invoice_link_db as pildb
    from ..services import wfirma_client
    from ..services.carrier import doc_package
    from ..api.routes_carrier_actions import _shipment_doc_file

    storage_root = _storage_root()
    try:
        manifest = sdm.build_manifest(
            int(draft_id),
            storage_root=storage_root,
            proforma_db=_proforma_db(),
            carrier_db=_carrier_db(),
        )
    except sdm.DraftNotFound:
        raise HTTPException(status_code=404, detail=f"draft {draft_id} not found")

    cp = manifest["groups"]["complete_package"]
    if not cp.get("ready"):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Complete package is not ready.",
                "code": "COMPLETE_PACKAGE_NOT_READY",
                "missing": cp.get("missing", []),
            },
        )

    draft = pildb.get_draft_by_id(_proforma_db(), int(draft_id))
    if draft is None:
        raise HTTPException(status_code=404, detail=f"draft {draft_id} not found")

    batch_id = (draft.batch_id or "").strip()
    client_name = (draft.client_name or "").strip()
    awb = manifest.get("awb")

    buf = io.BytesIO()
    try:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. Fiscal document — invoice if converted, else posted proforma.
            invoice_id = (getattr(draft, "wfirma_invoice_id", None) or "").strip()
            proforma_id = (draft.wfirma_proforma_id or "").strip()
            fiscal_id = invoice_id or proforma_id
            fiscal_label = "invoice" if invoice_id else "proforma"
            if fiscal_id:
                pdf = wfirma_client.fetch_invoice_pdf(fiscal_id)
                if not pdf or len(pdf) < 10:
                    raise RuntimeError("wFirma returned an empty PDF")
                zf.writestr(f"{fiscal_label}-{fiscal_id}.pdf", pdf)

            # 2. Packing list — rendered by the EXISTING authority.
            company = doc_package._load_company_profile(storage_root)
            pdraft = doc_package._load_proforma_draft(batch_id, client_name, storage_root)
            customer = doc_package._resolve_customer_from_batch(
                batch_id, client_name, storage_root,
            )
            packing_pdf = doc_package.render_packing_list_pdf(
                batch_id, storage_root, company, customer, pdraft or draft,
            )
            if packing_pdf:
                zf.writestr("packing-list.pdf", packing_pdf)

            # 3. DHL files from disk (label/waybill/receipt at booking; ePOD
            # after delivery). ePOD is include-if-present — never required.
            if awb:
                for kind, name in (("label", "dhl-label.pdf"),
                                   ("waybill-doc", "dhl-waybill.pdf"),
                                   ("receipt", "dhl-receipt.pdf"),
                                   ("epod", "dhl-epod.pdf")):
                    doc = _shipment_doc_file(kind, batch_id, awb)
                    if doc is not None:
                        zf.writestr(name, doc.read_bytes())
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("complete-package build failed for draft %s: %s", draft_id, exc)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "Failed to assemble the complete package.",
                "code": "COMPLETE_PACKAGE_BUILD_FAILED",
                "detail": str(exc),
            },
        )

    safe_batch = batch_id.replace("/", "-") or "shipment"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="complete-package-{safe_batch}.zip"',
            **_NO_STORE_HEADERS,
        },
    )


# ── Operator: delivery confirmation view ─────────────────────────────────────────


@router.get("/draft/{draft_id}/delivery")
def get_delivery(draft_id: int, _auth: None = Depends(require_api_key)) -> JSONResponse:
    """Operator view of the customer's delivery confirmation / claim."""
    from ..services import delivery_confirmation_db as dcdb
    summary = dcdb.get_delivery_summary_for_draft(
        _storage_root() / "delivery_confirmations.db", int(draft_id),
    )
    return JSONResponse({"draft_id": draft_id, "delivery_confirmation": summary})


@router.get("/draft/{draft_id}/delivery/evidence/{evidence_id}")
def get_delivery_evidence(
    draft_id: int, evidence_id: int, _auth: None = Depends(require_api_key),
) -> Response:
    """Stream one uploaded evidence image, scoped to THIS draft's receipt.

    An evidence id belonging to a different draft's receipt returns 404 — an
    operator cannot read another draft's photos by guessing ids.
    """
    from ..services import delivery_confirmation_db as dcdb
    from ..services import delivery_confirmation_service as dcs

    db = _storage_root() / "delivery_confirmations.db"
    evidence = dcdb.get_evidence(db, int(evidence_id))
    if evidence is None:
        raise HTTPException(status_code=404, detail="evidence not found")
    receipt = dcdb.get_receipt_by_id(db, evidence["receipt_id"])
    if receipt is None or int(receipt.get("draft_id") or -1) != int(draft_id):
        # Scope guard: the evidence must belong to this draft's receipt.
        raise HTTPException(status_code=404, detail="evidence not found")

    path = dcs.evidence_file_path(evidence["receipt_id"], evidence["stored_name"])
    if path is None:
        raise HTTPException(status_code=404, detail="evidence file missing")
    mime = evidence.get("mime") or "application/octet-stream"
    return Response(
        content=path.read_bytes(),
        media_type=mime,
        headers=dict(_NO_STORE_HEADERS),
    )


# ── Public: customer receipt (NO dashboard auth) ─────────────────────────────────


@router.get("/public/receipt/{token}")
def public_receipt_metadata(token: str) -> JSONResponse:
    """Read-only metadata for the public receipt page (no auth)."""
    from ..services import delivery_confirmation_service as dcs
    try:
        meta = dcs.get_public_receipt_metadata(token)
    except dcs.ReceiptError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "error": exc.message})
    return JSONResponse(meta)


@router.post("/public/receipt/{token}")
async def public_receipt_submit(
    token: str,
    request: Request,
    condition: str = Form(...),
    categories: Optional[List[str]] = Form(None),
    comments: str = Form(""),
    photos: Optional[List[UploadFile]] = _File(None),
) -> JSONResponse:
    """Public multipart submit — records the customer's receipt response."""
    from ..services import delivery_confirmation_service as dcs

    files = []
    uploads = photos or []
    if len(uploads) > _MAX_EVIDENCE_FILES:
        raise HTTPException(
            status_code=422,
            detail={"code": "too_many_files",
                    "error": f"At most {_MAX_EVIDENCE_FILES} photos may be uploaded."},
        )
    for up in uploads:
        if up is None:
            continue
        content = await up.read()
        files.append({
            "filename": up.filename or "",
            "content_type": up.content_type or "",
            "content": content,
        })

    response_ip = request.client.host if request.client else None
    try:
        result = dcs.submit_receipt(
            token,
            condition=condition,
            categories=categories or [],
            comments=comments or "",
            files=files,
            response_ip=response_ip,
        )
    except dcs.ReceiptError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "error": exc.message})
    return JSONResponse(result)
