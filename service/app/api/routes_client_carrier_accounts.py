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

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from ..core.config import settings
from ..core.security import require_api_key
from ..core.logging import get_logger
from ..services.client_carrier_accounts_db import (
    validate_account, init_db,
    create_account, list_accounts, get_account,
    update_account, delete_account,
)

log    = get_logger(__name__)
router = APIRouter(
    prefix="/api/v1/customer-master/{contractor_id}/carrier-accounts",
    tags=["customer-master"],
)
_auth    = Depends(require_api_key)
_DB_PATH = settings.storage_root / "customer_master.sqlite"


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
    }


@router.get("/", dependencies=[_auth], summary="List carrier accounts")
def list_accounts_endpoint(contractor_id: str) -> JSONResponse:
    try:
        accts = list_accounts(_DB_PATH, contractor_id)
    except Exception as exc:
        log.error("list_accounts failed contractor_id=%s: %s", contractor_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse({"count": len(accts), "accounts": [_acct_dict(a) for a in accts]})


@router.post("/", dependencies=[_auth], summary="Create carrier account", status_code=201)
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
    try:
        init_db(_DB_PATH)
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
    return JSONResponse(status_code=201, content=_acct_dict(stored))


@router.put("/{acct_id}", dependencies=[_auth], summary="Update carrier account")
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
    return JSONResponse(_acct_dict(stored))


@router.delete("/{acct_id}", dependencies=[_auth], summary="Delete carrier account",
               status_code=204)
def delete_account_endpoint(contractor_id: str, acct_id: int) -> None:
    try:
        removed = delete_account(_DB_PATH, acct_id, contractor_id)
    except Exception as exc:
        log.error("delete_account failed acct_id=%d: %s", acct_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"Carrier account not found: id={acct_id} contractor_id={contractor_id!r}",
        )
    log.info("carrier_account_deleted contractor_id=%s acct_id=%d", contractor_id, acct_id)
