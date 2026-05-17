"""routes_packing_resolution.py — B0.X R2 contractor-resolution endpoints.

  GET  /api/v1/packing/{batch_id}/contractor-resolution
       List all stored resolutions for a batch (client + supplier).

  GET  /api/v1/packing/{batch_id}/contractor-resolution/{role}
       Read one resolution by role.

  POST /api/v1/packing/{batch_id}/contractor-resolution
       Resolve + persist. Body: parsed-name / parsed-tax-id / parsed-country /
       parsed-wfirma-id / role. The resolver runs read-only against Client
       Master + Supplier Master, returns a verdict, and the route persists
       it with status='auto' or 'unresolved'.

  POST /api/v1/packing/{batch_id}/contractor-resolution/confirm
       Operator confirms the auto-suggested match. Body: role +
       optional matched_master_id (when operator overrides). Marks status
       as 'confirmed' (no override) or 'overridden' (operator picked a
       different master row from the candidates list).

Auth: X-API-Key (existing dependency).
Audit: optional ``X-Operator-User`` header is stored on confirm/override
operations. Defaults to 'anonymous' if absent.

Hard rules:
- No live wFirma call.
- No write to customer_master / suppliers (resolver is read-only;
  this route does not call any master upsert path).
- No proforma / PZ / DHL / customs / finance import.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from ..core.config import settings
from ..core.logging import get_logger
from ..core.security import require_api_key
from ..services import packing_contractor_resolver as pcr
from ..services import packing_resolution_db as prdb


log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1/packing", tags=["packing-resolution"])
_auth  = Depends(require_api_key)

_DB_PATH = settings.storage_root / "packing_resolutions.sqlite"


# ── GET /{batch_id}/contractor-resolution ────────────────────────────────────


@router.get("/{batch_id}/contractor-resolution",
            dependencies=[_auth],
            summary="List all resolutions for a packing batch")
def list_batch_resolutions(batch_id: str) -> JSONResponse:
    try:
        prdb.init_db(_DB_PATH)
        rows = prdb.list_resolutions_for_batch(_DB_PATH, batch_id)
    except Exception as exc:
        log.error("list_batch_resolutions failed batch=%s: %s", batch_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse({"batch_id": batch_id, "count": len(rows), "resolutions": rows})


@router.get("/{batch_id}/contractor-resolution/{role}",
            dependencies=[_auth],
            summary="Read one resolution by role (client or supplier)")
def get_one_resolution(batch_id: str, role: str) -> JSONResponse:
    if role not in ("client", "supplier"):
        raise HTTPException(status_code=422, detail="role must be 'client' or 'supplier'")
    try:
        prdb.init_db(_DB_PATH)
        row = prdb.get_resolution(_DB_PATH, batch_id=batch_id, role=role)
    except Exception as exc:
        log.error("get_one_resolution failed batch=%s role=%s: %s",
                  batch_id, role, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    if row is None:
        raise HTTPException(status_code=404,
                            detail=f"no resolution stored for batch={batch_id} role={role}")
    return JSONResponse(row)


# ── POST /{batch_id}/contractor-resolution ───────────────────────────────────


@router.post("/{batch_id}/contractor-resolution",
             dependencies=[_auth],
             summary="Resolve parsed contractor data and persist the verdict")
async def resolve_and_persist(
    batch_id: str,
    request: Request,
    x_operator_user: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Body:
        {
          "role": "client" | "supplier",
          "parsed_name": "...",
          "parsed_tax_id": "...",        (optional)
          "parsed_country": "PL",        (optional)
          "parsed_wfirma_id": "...",     (optional)
        }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Body must be a JSON object")

    role = (body.get("role") or "").strip()
    if role not in ("client", "supplier"):
        raise HTTPException(status_code=422, detail="role must be 'client' or 'supplier'")

    parsed_name = (body.get("parsed_name") or "").strip()
    if not parsed_name:
        raise HTTPException(status_code=422, detail="parsed_name is required")

    parsed = {
        "parsed_name":      parsed_name,
        "parsed_tax_id":    body.get("parsed_tax_id"),
        "parsed_country":   body.get("parsed_country"),
        "parsed_wfirma_id": body.get("parsed_wfirma_id"),
    }
    try:
        verdict = pcr.resolve_contractor(parsed, role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("resolver failed batch=%s role=%s: %s", batch_id, role, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"resolver error: {exc}")

    try:
        stored = prdb.upsert_resolution(
            _DB_PATH,
            batch_id=batch_id,
            role=role,
            verdict=verdict,
            operator_user=x_operator_user,
            operator_override=False,
        )
    except Exception as exc:
        log.error("upsert_resolution failed batch=%s role=%s: %s",
                  batch_id, role, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"persistence error: {exc}")

    log.info("packing_resolution stored batch=%s role=%s tier=%d status=%s",
             batch_id, role, stored.get("tier"), stored.get("status"))
    return JSONResponse(stored)


# ── POST /{batch_id}/contractor-resolution/confirm ───────────────────────────


@router.post("/{batch_id}/contractor-resolution/confirm",
             dependencies=[_auth],
             summary="Operator confirms or overrides the auto-suggested match")
async def confirm_or_override(
    batch_id: str,
    request: Request,
    x_operator_user: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Body:
        {
          "role": "client" | "supplier",
          "matched_master_type": "client_master" | "supplier_master" | null,
          "matched_master_id":   <int> | null,
          "matched_wfirma_id":   "<wfid>" | null,
        }

    When the operator passes a master_id different from the row's auto
    match, status flips to 'overridden' and ``operator_override=1`` is
    recorded. Otherwise the auto match is locked in as 'confirmed'.

    Hard rule: this route NEVER creates a customer_master / suppliers
    row. The (matched_master_type, matched_master_id) tuple must reference
    an EXISTING master row that came from the verdict's candidate list.
    Verification: we look up the candidate ids in the stored verdict.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Body must be a JSON object")

    role = (body.get("role") or "").strip()
    if role not in ("client", "supplier"):
        raise HTTPException(status_code=422, detail="role must be 'client' or 'supplier'")

    prdb.init_db(_DB_PATH)
    existing = prdb.get_resolution(_DB_PATH, batch_id=batch_id, role=role)
    if existing is None:
        raise HTTPException(status_code=404,
                            detail=f"no prior resolution for batch={batch_id} role={role}; "
                                   "POST /contractor-resolution first")

    chosen_type = body.get("matched_master_type")
    chosen_id   = body.get("matched_master_id")
    chosen_wfid = body.get("matched_wfirma_id")

    # If operator supplies a chosen_master_id, verify it appears in the
    # original candidate list (or matches the current auto match). This is
    # the no-auto-create guard: the operator can only pick from rows the
    # resolver already classified.
    is_override = False
    if chosen_id is not None:
        candidate_ids = [c.get("master_id") for c in (existing.get("candidates") or [])]
        if existing.get("matched_master_id") is not None:
            candidate_ids.append(existing.get("matched_master_id"))
        if chosen_id not in candidate_ids:
            raise HTTPException(
                status_code=422,
                detail=(f"matched_master_id {chosen_id} is not in the stored "
                        f"candidate list for batch={batch_id} role={role}. "
                        "Create the master row via the existing Client/Supplier "
                        "Master endpoints first, then re-run "
                        "POST /contractor-resolution to refresh candidates."),
            )
        is_override = (chosen_id != existing.get("matched_master_id"))

    # Build the verdict to persist: same evidence/candidates, but matched
    # fields reflect the operator pick. Tier/confidence/reason are preserved
    # so the audit trail keeps the original automatic-resolution metadata.
    verdict_to_store = dict(existing)
    if chosen_id is not None:
        verdict_to_store["matched_master_type"] = chosen_type or existing.get("matched_master_type")
        verdict_to_store["matched_master_id"]   = chosen_id
        verdict_to_store["matched_wfirma_id"]   = chosen_wfid or existing.get("matched_wfirma_id")

    status = "overridden" if is_override else "confirmed"
    try:
        stored = prdb.upsert_resolution(
            _DB_PATH,
            batch_id=batch_id,
            role=role,
            verdict=verdict_to_store,
            operator_user=x_operator_user,
            operator_override=is_override,
            status_override=status,
        )
    except Exception as exc:
        log.error("confirm/override failed batch=%s role=%s: %s",
                  batch_id, role, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"persistence error: {exc}")

    log.info("packing_resolution %s batch=%s role=%s master_id=%s user=%s",
             status, batch_id, role, chosen_id, (x_operator_user or "anonymous"))
    return JSONResponse(stored)
