"""
routes_client_carrier_accounts.py — Carrier account sub-resource REST API.

  GET    /api/v1/customer-master/{contractor_id}/carrier-accounts
  POST   /api/v1/customer-master/{contractor_id}/carrier-accounts
  PUT    /api/v1/customer-master/{contractor_id}/carrier-accounts/{acct_id}
  DELETE /api/v1/customer-master/{contractor_id}/carrier-accounts/{acct_id}

All endpoints are X-API-Key authenticated.
DB: settings.storage_root / "customer_master.sqlite"
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
from ..services.client_carrier_accounts_db import (
    validate_account, init_db,
    create_account, list_accounts, get_account,
    update_account, delete_account,
    soft_delete_account, restore_account, hard_delete_account,
    carrier_account_audit_pk,
)
from ..services.master_reference_checks import (
    ReferenceConflict, check_customer_exists, check_carrier_active,
)

log    = get_logger(__name__)
router = APIRouter(
    prefix="/api/v1/customer-master/{contractor_id}/carrier-accounts",
    tags=["customer-master"],
)
_auth    = Depends(require_api_key)
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
    parsed = _parse_active(v)
    return True if parsed is None else parsed


import hmac as _hmac


def _hard_delete_guard(request: Request) -> None:
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


def _acct_dict(a) -> dict:
    return {
        "id":             a.id,
        "contractor_id":  a.contractor_id,
        "carrier":        a.carrier,
        "account_number": a.account_number,
        "account_name":   a.account_name,
        "payment_type":   a.payment_type,
        "service_level":  a.service_level,
        "is_default":     a.is_default,
        "created_at":     a.created_at,
        "updated_at":     a.updated_at,
        "active":         a.active,
        "deleted_at":     a.deleted_at,
    }


@router.get("/", dependencies=[_auth], summary="List carrier accounts")
def list_accounts_endpoint(
    contractor_id: str,
    active: Optional[str] = Query(None,
        description="omit = active-only (default); 'false' = inactive only; 'true' = active only"),
) -> JSONResponse:
    try:
        init_db(_DB_PATH)
        accts = list_accounts(_DB_PATH, contractor_id,
                              active=_resolve_list_active(active))
    except HTTPException:
        raise
    except Exception as exc:
        log.error("list_accounts failed contractor_id=%s: %s", contractor_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse({"count": len(accts), "accounts": [_acct_dict(a) for a in accts]})


@router.post("/", dependencies=[_write_auth], summary="Create carrier account", status_code=201)
async def create_account_endpoint(contractor_id: str, request: Request) -> JSONResponse:
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    errs = validate_account(body)
    if errs:
        raise HTTPException(status_code=422, detail={"validation_errors": errs})
    init_db(_DB_PATH)
    # Phase 4C — parent customer must exist.
    try:
        check_customer_exists(_DB_PATH, field="contractor_id",
                              contractor_id=contractor_id)
    except ReferenceConflict as exc:
        raise HTTPException(status_code=409, detail=exc.to_detail())
    # Phase 4C-ext — referenced carrier must be active in carriers_config.
    # Match the lowercase normalisation that create_account performs.
    carrier_code = (body.get("carrier") or "").strip().lower()
    if carrier_code:
        try:
            check_carrier_active(settings.storage_root, carrier_code)
        except ReferenceConflict as exc:
            raise HTTPException(status_code=409, detail=exc.to_detail())
    try:
        acct_id = create_account(_DB_PATH, contractor_id, body)
    except ValueError as exc:
        if "DUPLICATE_ACCOUNT" in str(exc):
            raise HTTPException(
                status_code=409,
                detail=f"Carrier account already exists: carrier={body.get('carrier')!r} "
                       f"account_number={body.get('account_number')!r}",
            )
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("create_account failed contractor_id=%s: %s", contractor_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    stored = get_account(_DB_PATH, acct_id, contractor_id)
    if stored is None:
        raise HTTPException(status_code=500, detail="insert succeeded but record not found on re-read")
    log.info("carrier_account_created contractor_id=%s acct_id=%d", contractor_id, acct_id)
    audit_safe("client_carrier_accounts", "create",
               carrier_account_audit_pk(contractor_id, acct_id),
               request=request, before=None, after=stored)
    return JSONResponse(status_code=201, content=_acct_dict(stored))


@router.put("/{acct_id}", dependencies=[_write_auth], summary="Update carrier account")
async def update_account_endpoint(contractor_id: str, acct_id: int, request: Request) -> JSONResponse:
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    errs = validate_account(body)
    if errs:
        raise HTTPException(status_code=422, detail={"validation_errors": errs})
    init_db(_DB_PATH)
    before = get_account(_DB_PATH, acct_id, contractor_id)
    # Authority ordering: 422 (body) → 404 (account missing) → 409 (carrier
    # reference conflict) → write. Verify the account exists before checking
    # carrier authority so a missing-resource request is not turned into a
    # misleading master-data conflict.
    if before is None:
        raise HTTPException(
            status_code=404,
            detail=f"Carrier account not found: id={acct_id} contractor_id={contractor_id!r}",
        )
    # Phase 4C-ext Wave 2 — the carrier being set/preserved must still exist
    # and be active in carriers_config. Closes the update-path bypass.
    carrier_code = (body.get("carrier") or "").strip().lower()
    try:
        check_carrier_active(settings.storage_root, carrier_code)
    except ReferenceConflict as exc:
        raise HTTPException(status_code=409, detail=exc.to_detail())
    try:
        stored = update_account(_DB_PATH, acct_id, contractor_id, body)
    except ValueError as exc:
        if "DUPLICATE_ACCOUNT" in str(exc):
            raise HTTPException(
                status_code=409,
                detail=f"Carrier account already exists: carrier={body.get('carrier')!r} "
                       f"account_number={body.get('account_number')!r}",
            )
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("update_account failed acct_id=%d: %s", acct_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    if stored is None:
        raise HTTPException(
            status_code=404,
            detail=f"Carrier account not found: id={acct_id} contractor_id={contractor_id!r}",
        )
    log.info("carrier_account_updated contractor_id=%s acct_id=%d", contractor_id, acct_id)
    audit_safe("client_carrier_accounts", "update",
               carrier_account_audit_pk(contractor_id, acct_id),
               request=request, before=before, after=stored)
    return JSONResponse(_acct_dict(stored))


@router.delete("/{acct_id}", dependencies=[_write_auth],
               summary="Delete carrier account (soft-delete by default; ?hard=true for permanent)",
               status_code=204)
def delete_account_endpoint(
    contractor_id: str, acct_id: int, request: Request,
    hard: bool = Query(False, description="Permanent removal; requires master_admin + flag"),
) -> None:
    init_db(_DB_PATH)
    before = get_account(_DB_PATH, acct_id, contractor_id)
    if before is None:
        raise HTTPException(
            status_code=404,
            detail=f"Carrier account not found: id={acct_id} contractor_id={contractor_id!r}",
        )
    pk = carrier_account_audit_pk(contractor_id, acct_id)
    if hard:
        _hard_delete_guard(request)
        try:
            removed = hard_delete_account(_DB_PATH, acct_id, contractor_id)
        except Exception as exc:
            log.error("hard_delete_account failed acct_id=%d: %s", acct_id, exc, exc_info=True)
            raise HTTPException(status_code=500, detail=f"DB error: {exc}")
        if not removed:
            raise HTTPException(
                status_code=404,
                detail=f"Carrier account not found: id={acct_id} contractor_id={contractor_id!r}",
            )
        log.info("carrier_account_hard_deleted contractor_id=%s acct_id=%d",
                 contractor_id, acct_id)
        audit_safe("client_carrier_accounts", "hard_delete", pk,
                   request=request, before=before, after=None)
        return
    # Soft-delete (default).
    try:
        removed = soft_delete_account(_DB_PATH, acct_id, contractor_id)
    except Exception as exc:
        log.error("soft_delete_account failed acct_id=%d: %s", acct_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"Carrier account not found: id={acct_id} contractor_id={contractor_id!r}",
        )
    log.info("carrier_account_soft_deleted contractor_id=%s acct_id=%d",
             contractor_id, acct_id)
    audit_safe("client_carrier_accounts", "delete", pk,
               request=request, before=before, after=None)


@router.post("/{acct_id}/restore", dependencies=[_write_auth],
             summary="Restore a soft-deleted carrier account")
def restore_account_endpoint(contractor_id: str, acct_id: int, request: Request) -> JSONResponse:
    init_db(_DB_PATH)
    before = get_account(_DB_PATH, acct_id, contractor_id)
    if before is None:
        raise HTTPException(
            status_code=404,
            detail=f"Carrier account not found: id={acct_id} contractor_id={contractor_id!r}",
        )
    # Phase 4C — restoring a child whose parent contractor is missing
    # returns 409.
    try:
        check_customer_exists(_DB_PATH, field="contractor_id",
                              contractor_id=contractor_id)
    except ReferenceConflict as exc:
        raise HTTPException(status_code=409, detail=exc.to_detail())
    # Phase 4C-ext — referenced carrier must still be active. The carrier
    # code is taken from the row we're about to restore, normalised the
    # same way as create_account performs.
    carrier_code = (before.carrier or "").strip().lower()
    if carrier_code:
        try:
            check_carrier_active(settings.storage_root, carrier_code)
        except ReferenceConflict as exc:
            raise HTTPException(status_code=409, detail=exc.to_detail())
    if not restore_account(_DB_PATH, acct_id, contractor_id):
        raise HTTPException(
            status_code=404,
            detail=f"Carrier account not found: id={acct_id} contractor_id={contractor_id!r}",
        )
    after = get_account(_DB_PATH, acct_id, contractor_id)
    log.info("carrier_account_restored contractor_id=%s acct_id=%d", contractor_id, acct_id)
    audit_safe("client_carrier_accounts", "restore",
               carrier_account_audit_pk(contractor_id, acct_id),
               request=request, before=before, after=after)
    return JSONResponse(_acct_dict(after))
