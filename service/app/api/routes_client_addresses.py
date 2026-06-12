"""
routes_client_addresses.py — Shipping address sub-resource REST API.

  GET    /api/v1/customer-master/{contractor_id}/shipping-addresses
  POST   /api/v1/customer-master/{contractor_id}/shipping-addresses
  PUT    /api/v1/customer-master/{contractor_id}/shipping-addresses/{addr_id}
  DELETE /api/v1/customer-master/{contractor_id}/shipping-addresses/{addr_id}

All endpoints are X-API-Key authenticated.
DB: settings.storage_root / "customer_master.sqlite"  (shared with customer_master table)
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ..core.config import settings
from ..core.security import require_api_key
from ..core.logging import get_logger
from ..core.audit import audit_safe
from ..core.role_gate import require_role_or_apikey, MASTER_ADMIN, MASTER_EDITOR
from ..services.client_addresses_db import (
    validate_address, init_db,
    create_address, list_addresses, get_address,
    update_address, delete_address,
    soft_delete_address, restore_address, hard_delete_address,
    address_audit_pk,
)
from ..services.master_reference_checks import (
    ReferenceConflict, check_customer_exists,
)

log    = get_logger(__name__)
router = APIRouter(
    prefix="/api/v1/customer-master/{contractor_id}/shipping-addresses",
    tags=["customer-master"],
)
_auth   = Depends(require_api_key)
_write_auth = Depends(require_role_or_apikey(MASTER_ADMIN, MASTER_EDITOR))
_DB_PATH = settings.storage_root / "customer_master.sqlite"


# ── Phase 4B Wave 2 — list-policy + hard-delete guard ───────────────────────

def _parse_active(v):
    if v is None or v == "":
        return None
    s = str(v).strip().lower()
    if s in ("true", "1", "yes"):  return True
    if s in ("false", "0", "no"):  return False
    raise HTTPException(status_code=422,
                        detail=f"active must be true/false, got {v!r}")


def _resolve_list_active(v):
    """Default to active-only when ``active`` query param is omitted."""
    parsed = _parse_active(v)
    return True if parsed is None else parsed


import hmac as _hmac


def _hard_delete_guard(request: Request) -> None:
    """Same contract as Phase 4A/Wave 1: flag must be enabled AND caller must
    hold master_admin (or admin X-API-Key). Soft-delete remains the default
    for the DELETE verb."""
    if not settings.master_hard_delete_enabled:
        raise HTTPException(
            status_code=409,
            detail=("Hard delete is disabled. Set master_hard_delete_enabled "
                    "to true (admin) to permit permanent removal."),
        )
    key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if settings.api_key and key and _hmac.compare_digest(key.encode("utf-8"), settings.api_key.encode("utf-8")):
        return
    cookie = request.cookies.get("pz_session")
    if cookie:
        try:
            from ..auth.dependencies import get_current_user_optional  # noqa: PLC0415
            user = get_current_user_optional(pz_session=cookie)
        except Exception:
            user = None
        if user and (user.get("role") or "") == MASTER_ADMIN:
            return
    raise HTTPException(
        status_code=403,
        detail="Hard delete requires master_admin role.",
    )


def _addr_dict(a) -> dict:
    return {
        "id":            a.id,
        "contractor_id": a.contractor_id,
        "label":         a.label,
        "name":          a.name,
        "person":        a.person,
        "street":        a.street,
        "city":          a.city,
        "zip":           a.zip,
        "country":       a.country,
        "phone":         a.phone,
        "email":         a.email,
        "is_default":    a.is_default,
        "created_at":    a.created_at,
        "updated_at":    a.updated_at,
        "active":        a.active,
        "deleted_at":    a.deleted_at,
    }


@router.get("/", dependencies=[_auth], summary="List shipping addresses")
def list_addresses_endpoint(
    contractor_id: str,
    active: Optional[str] = Query(None,
        description="omit = active-only (default); 'false' = inactive only; 'true' = active only"),
) -> JSONResponse:
    try:
        init_db(_DB_PATH)
        addrs = list_addresses(_DB_PATH, contractor_id,
                               active=_resolve_list_active(active))
    except HTTPException:
        raise
    except Exception as exc:
        log.error("list_addresses failed contractor_id=%s: %s", contractor_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse({"count": len(addrs), "addresses": [_addr_dict(a) for a in addrs]})


@router.post("/", dependencies=[_write_auth], summary="Create shipping address", status_code=201)
async def create_address_endpoint(contractor_id: str, request: Request) -> JSONResponse:
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    errs = validate_address(body)
    if errs:
        raise HTTPException(status_code=422, detail={"validation_errors": errs})
    init_db(_DB_PATH)
    # Phase 4C — referential integrity: contractor must exist in
    # customer_master before a child address can be attached. Both
    # tables share the same SQLite file, so a single _DB_PATH suffices.
    try:
        check_customer_exists(_DB_PATH, field="contractor_id",
                              contractor_id=contractor_id)
    except ReferenceConflict as exc:
        raise HTTPException(status_code=409, detail=exc.to_detail())
    try:
        addr_id = create_address(_DB_PATH, contractor_id, body)
    except Exception as exc:
        log.error("create_address failed contractor_id=%s: %s", contractor_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    stored = get_address(_DB_PATH, addr_id, contractor_id)
    if stored is None:
        raise HTTPException(status_code=500, detail="insert succeeded but record not found on re-read")
    log.info("shipping_address_created contractor_id=%s addr_id=%d", contractor_id, addr_id)
    audit_safe("client_addresses", "create",
               address_audit_pk(contractor_id, addr_id),
               request=request, before=None, after=stored)
    return JSONResponse(status_code=201, content=_addr_dict(stored))


@router.put("/{addr_id}", dependencies=[_write_auth], summary="Update shipping address")
async def update_address_endpoint(contractor_id: str, addr_id: int, request: Request) -> JSONResponse:
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    errs = validate_address(body)
    if errs:
        raise HTTPException(status_code=422, detail={"validation_errors": errs})
    init_db(_DB_PATH)
    before = get_address(_DB_PATH, addr_id, contractor_id)
    try:
        stored = update_address(_DB_PATH, addr_id, contractor_id, body)
    except Exception as exc:
        log.error("update_address failed addr_id=%d: %s", addr_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    if stored is None:
        raise HTTPException(
            status_code=404,
            detail=f"Shipping address not found: id={addr_id} contractor_id={contractor_id!r}",
        )
    log.info("shipping_address_updated contractor_id=%s addr_id=%d", contractor_id, addr_id)
    audit_safe("client_addresses", "update",
               address_audit_pk(contractor_id, addr_id),
               request=request, before=before, after=stored)
    return JSONResponse(_addr_dict(stored))


@router.delete("/{addr_id}", dependencies=[_write_auth],
               summary="Delete shipping address (soft-delete by default; ?hard=true for permanent)",
               status_code=204)
def delete_address_endpoint(
    contractor_id: str, addr_id: int, request: Request,
    hard: bool = Query(False, description="Permanent removal; requires master_admin + flag"),
) -> None:
    init_db(_DB_PATH)
    before = get_address(_DB_PATH, addr_id, contractor_id)
    if before is None:
        raise HTTPException(
            status_code=404,
            detail=f"Shipping address not found: id={addr_id} contractor_id={contractor_id!r}",
        )
    pk = address_audit_pk(contractor_id, addr_id)
    if hard:
        _hard_delete_guard(request)
        try:
            removed = hard_delete_address(_DB_PATH, addr_id, contractor_id)
        except Exception as exc:
            log.error("hard_delete_address failed addr_id=%d: %s", addr_id, exc, exc_info=True)
            raise HTTPException(status_code=500, detail=f"DB error: {exc}")
        if not removed:
            raise HTTPException(
                status_code=404,
                detail=f"Shipping address not found: id={addr_id} contractor_id={contractor_id!r}",
            )
        log.info("shipping_address_hard_deleted contractor_id=%s addr_id=%d",
                 contractor_id, addr_id)
        audit_safe("client_addresses", "hard_delete", pk,
                   request=request, before=before, after=None)
        return
    # Soft-delete (default).
    try:
        removed = soft_delete_address(_DB_PATH, addr_id, contractor_id)
    except Exception as exc:
        log.error("soft_delete_address failed addr_id=%d: %s", addr_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"Shipping address not found: id={addr_id} contractor_id={contractor_id!r}",
        )
    log.info("shipping_address_soft_deleted contractor_id=%s addr_id=%d",
             contractor_id, addr_id)
    audit_safe("client_addresses", "delete", pk,
               request=request, before=before, after=None)


@router.post("/{addr_id}/restore", dependencies=[_write_auth],
             summary="Restore a soft-deleted shipping address")
def restore_address_endpoint(contractor_id: str, addr_id: int, request: Request) -> JSONResponse:
    init_db(_DB_PATH)
    before = get_address(_DB_PATH, addr_id, contractor_id)
    if before is None:
        raise HTTPException(
            status_code=404,
            detail=f"Shipping address not found: id={addr_id} contractor_id={contractor_id!r}",
        )
    # Phase 4C — restoring a child whose parent contractor is missing
    # (or eventually inactive) returns 409. Phase 4C does NOT auto-restore
    # parents.
    try:
        check_customer_exists(_DB_PATH, field="contractor_id",
                              contractor_id=contractor_id)
    except ReferenceConflict as exc:
        raise HTTPException(status_code=409, detail=exc.to_detail())
    if not restore_address(_DB_PATH, addr_id, contractor_id):
        raise HTTPException(
            status_code=404,
            detail=f"Shipping address not found: id={addr_id} contractor_id={contractor_id!r}",
        )
    after = get_address(_DB_PATH, addr_id, contractor_id)
    log.info("shipping_address_restored contractor_id=%s addr_id=%d", contractor_id, addr_id)
    audit_safe("client_addresses", "restore",
               address_audit_pk(contractor_id, addr_id),
               request=request, before=before, after=after)
    return JSONResponse(_addr_dict(after))
