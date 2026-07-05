"""
routes_supplier_invoice_ocr.py — Supplier invoice OCR extraction + review drafts.

  POST   /api/v1/supplier-invoice-ocr/upload
         Upload a foreign supplier invoice (PDF/PNG/JPG), run vision
         extraction, store a review draft. 201 with the draft.

  GET    /api/v1/supplier-invoice-ocr/drafts
         List drafts. Optional QS: status, limit (default 50), offset.

  GET    /api/v1/supplier-invoice-ocr/drafts/{draft_id}
         Read one draft in full (parsed JSON columns). 404 if absent.

  GET    /api/v1/supplier-invoice-ocr/drafts/{draft_id}/source-file
         Serve the original upload for the review-page preview pane.
         Cache-Control: no-store (Lesson G).

  POST   /api/v1/supplier-invoice-ocr/drafts/{draft_id}/confirm
         Operator confirms with corrected values. Session-role gated;
         operator identity derived SERVER-SIDE (never from the body).

  POST   /api/v1/supplier-invoice-ocr/drafts/{draft_id}/reject
         Operator rejects a pending draft. Session-role gated.

This module never writes to wFirma. Confirmed drafts are the operator's
reference for booking the expense manually (expenses/add is unverified —
docs/WFIRMA_API_VALIDATED_MAP.md).

Single extraction authority (2026-07-03): the DHL commercial invoice and the
supplier's purchase invoice are the SAME physical document (operator-confirmed
business fact), so this flow consumes ``vision_extractor.
extract_invoice_lineitems_via_vision`` — the same extractor the shipment-intake
path uses — rather than a second independent extraction of the same document.
The batch orchestrator ``run_image_only_invoice_extraction`` is NOT used here:
it assumes shipment-batch context (audit.json, batch dir layout, image-only
gating) that a standalone expense upload does not have.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from ..auth.dependencies import require_role
from ..core.config import settings
from ..core.logging import get_logger
from ..core.security import require_api_key
from ..services import supplier_invoice_db as sidb
from ..services.vision_extractor import extract_invoice_lineitems_via_vision

log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1/supplier-invoice-ocr", tags=["supplier_invoice_ocr"])
_auth    = Depends(require_api_key)
_op_auth = Depends(require_role("admin", "logistics", "accounts"))

_ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg"}
_MAGIC = {
    ".pdf":  b"%PDF",
    ".png":  b"\x89PNG",
    ".jpg":  b"\xff\xd8",
    ".jpeg": b"\xff\xd8",
}
_MEDIA_TYPES = {
    ".pdf":  "application/pdf",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
}
# Regenerable/confidential artifact serving — Lesson G headers, always.
_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _db_path() -> Path:
    # Resolved per-request (not module-level) so test fixtures that
    # monkeypatch settings.storage_root take effect.
    return settings.storage_root / "supplier_invoice_ocr.sqlite"


def _safe_name(filename: str) -> str:
    name = Path(filename or "").name
    name = "".join(c if c.isalnum() or c in "._- " else "_" for c in name)
    return name or "invoice"


def _parse_json_col(raw: Optional[str], default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _draft_scalar_dict(r: Any) -> Dict[str, Any]:
    return {
        "id":                    r["id"],
        "draft_uuid":            r["draft_uuid"],
        "source_filename":       r["source_filename"],
        "supplier_name":         r["supplier_name"],
        "supplier_gstin":        r["supplier_gstin"],
        "invoice_number":        r["invoice_number"],
        "invoice_date":          r["invoice_date"],
        "currency":              r["currency"],
        "total_amount":          r["total_amount"],
        "needs_review":          _parse_json_col(r["needs_review_json"], []),
        "status":                r["status"],
        "extraction_method":     r["extraction_method"],
        "extraction_confidence": r["extraction_confidence"],
        "created_at":            r["created_at"],
        "updated_at":            r["updated_at"],
        "confirmed_at":          r["confirmed_at"],
        "confirmed_by":          r["confirmed_by"],
    }


def _draft_full_dict(r: Any) -> Dict[str, Any]:
    d = _draft_scalar_dict(r)
    d["raw_extraction"]   = _parse_json_col(r["raw_extraction_json"], None)
    d["machine_original"] = _parse_json_col(r["machine_original_json"], None)
    d["confirmed_fields"] = _parse_json_col(r["confirmed_fields_json"], None)
    return d


def _operator_from_session(session_user: dict) -> str:
    operator = (
        (session_user.get("full_name") or "").strip()
        or (session_user.get("email") or "").strip()
        or str(session_user.get("id") or "").strip()
    )
    if not operator:
        # require_role guarantees an authenticated user; this only fires on a
        # malformed user record. Refuse rather than mint an unattributable write.
        raise HTTPException(status_code=401, detail="Operator identity required.")
    return operator


# ── Upload + extract ─────────────────────────────────────────────────────────

@router.post("/upload", dependencies=[_auth], status_code=201)
async def upload_supplier_invoice(file: UploadFile) -> JSONResponse:
    """Upload one supplier invoice, extract via vision LLM, store a draft.

    Extraction failures still persist the draft (file kept, method='failed')
    so the operator can retry or key the values manually — only invalid files
    are refused outright.
    """
    if not settings.supplier_invoice_ocr_enabled:
        raise HTTPException(
            status_code=503,
            detail="Supplier invoice OCR is not enabled (supplier_invoice_ocr_enabled).",
        )

    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type {ext or '(none)'} — allowed: {sorted(_ALLOWED_EXT)}",
        )

    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {settings.max_upload_bytes} bytes: {file.filename}",
        )
    if len(content) == 0:
        raise HTTPException(status_code=400, detail=f"Empty file: {file.filename}")
    if not content.startswith(_MAGIC[ext]):
        raise HTTPException(
            status_code=400,
            detail=f"File content does not match its {ext} extension: {file.filename}",
        )

    draft_uuid = str(uuid.uuid4())
    safe_name  = _safe_name(file.filename or f"invoice{ext}")
    dest_dir   = settings.storage_root / "supplier_invoice_ocr" / draft_uuid
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / safe_name
    dest.write_bytes(content)

    prov = extract_invoice_lineitems_via_vision(str(dest), object_id=draft_uuid)
    fields = prov.get("fields") or {}

    db = _db_path()
    sidb.init_db(db)
    row = sidb.create_draft(db, {
        "draft_uuid":            draft_uuid,
        "source_filename":       safe_name,
        "source_file_path":      str(dest),
        # Full provenance dict (fields + failed_layers + validation_errors) —
        # the machine output is never discarded.
        "raw_extraction_json":   json.dumps(prov, ensure_ascii=False),
        "machine_original_json": json.dumps(fields, ensure_ascii=False) if fields else None,
        # Column names are draft-store-local; the VALUES come from the shared
        # vision_extractor schema (supplier / invoice_no / …) — do not rename
        # the extraction keys themselves.
        "supplier_name":         fields.get("supplier"),
        "supplier_gstin":        fields.get("supplier_gstin"),
        "invoice_number":        fields.get("invoice_no"),
        "invoice_date":          fields.get("invoice_date"),
        "currency":              fields.get("currency"),
        "total_amount":          fields.get("total_amount"),
        "needs_review_json":     json.dumps(fields.get("needs_review") or []),
        "status":                sidb.STATUS_PENDING,
        "extraction_method":     prov.get("extraction_method"),
        "extraction_confidence": prov.get("extraction_confidence"),
    })

    body: Dict[str, Any] = {
        "ok": bool(prov.get("ok")),
        "draft_id": row["id"],
        "draft_uuid": draft_uuid,
        "status": row["status"],
        "extraction": _draft_full_dict(row),
        "failed_layers": prov.get("failed_layers") or [],
        "validation_errors": prov.get("validation_errors") or [],
    }

    if "ai_gateway_unavailable" in (prov.get("failed_layers") or []):
        body["error"] = "ai_extraction_unavailable"
        return JSONResponse(status_code=503, content=body)
    if not prov.get("ok"):
        body["error"] = "extraction_failed"
        return JSONResponse(status_code=422, content=body)
    return JSONResponse(status_code=201, content=body)


# ── Read ─────────────────────────────────────────────────────────────────────

@router.get("/drafts", dependencies=[_auth])
def list_supplier_invoice_drafts(
    status: Optional[str] = Query(None, description="pending_review | confirmed | rejected"),
    limit:  int           = Query(50, ge=1, le=200),
    offset: int           = Query(0, ge=0),
) -> Dict[str, Any]:
    if status and status not in sidb.STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {list(sidb.STATUSES)}")
    db = _db_path()
    sidb.init_db(db)
    rows = sidb.list_drafts(db, status=status, limit=limit, offset=offset)
    return {
        "ok": True,
        "drafts": [_draft_scalar_dict(r) for r in rows],
        "total": sidb.count_drafts(db, status=status),
        "limit": limit,
        "offset": offset,
    }


@router.get("/drafts/{draft_id}", dependencies=[_auth])
def get_supplier_invoice_draft(draft_id: int) -> Dict[str, Any]:
    db = _db_path()
    sidb.init_db(db)
    row = sidb.get_draft(db, draft_id)
    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"ok": True, "draft": _draft_full_dict(row)}


@router.get("/drafts/{draft_id}/source-file", dependencies=[_auth])
def get_supplier_invoice_source_file(draft_id: int) -> FileResponse:
    db = _db_path()
    sidb.init_db(db)
    row = sidb.get_draft(db, draft_id)
    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")
    path = Path(row["source_file_path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Source file missing on disk")
    media = _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media, headers=dict(_NO_STORE_HEADERS))


# ── Operator confirm / reject ────────────────────────────────────────────────

@router.post("/drafts/{draft_id}/confirm")
def confirm_supplier_invoice_draft(
    draft_id: int,
    payload: Dict[str, Any] = Body(...),
    session_user: dict = _op_auth,
) -> Dict[str, Any]:
    """Operator confirms the draft with reviewed/corrected values.

    ``confirmed_fields`` is what downstream humans use — never the raw
    extraction directly. Operator identity is the authenticated
    ``require_role`` user — derived SERVER-SIDE, never from the body.
    """
    confirmed_fields = payload.get("confirmed_fields")
    if not isinstance(confirmed_fields, dict) or not confirmed_fields:
        raise HTTPException(status_code=400, detail="confirmed_fields (object) is required")

    operator = _operator_from_session(session_user)
    db = _db_path()
    sidb.init_db(db)
    row = sidb.get_draft(db, draft_id)
    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")
    if row["status"] != sidb.STATUS_PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Draft is {row['status']} — only pending_review drafts can be confirmed.",
        )

    if not sidb.confirm_draft(db, draft_id, confirmed_by=operator,
                              confirmed_fields=confirmed_fields):
        raise HTTPException(status_code=409, detail="Draft is no longer pending_review.")

    fresh = sidb.get_draft(db, draft_id)
    log.info("[supplier_invoice_ocr] draft %s confirmed by %s", draft_id, operator)
    return {"ok": True, "draft_id": draft_id, "status": sidb.STATUS_CONFIRMED,
            "confirmed_by": operator,
            "confirmed_at": fresh["confirmed_at"] if fresh else None}


@router.post("/drafts/{draft_id}/reject")
def reject_supplier_invoice_draft(
    draft_id: int,
    session_user: dict = _op_auth,
) -> Dict[str, Any]:
    operator = _operator_from_session(session_user)
    db = _db_path()
    sidb.init_db(db)
    row = sidb.get_draft(db, draft_id)
    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")
    if row["status"] != sidb.STATUS_PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Draft is {row['status']} — only pending_review drafts can be rejected.",
        )

    if not sidb.reject_draft(db, draft_id, rejected_by=operator):
        raise HTTPException(status_code=409, detail="Draft is no longer pending_review.")

    log.info("[supplier_invoice_ocr] draft %s rejected by %s", draft_id, operator)
    return {"ok": True, "draft_id": draft_id, "status": sidb.STATUS_REJECTED}
