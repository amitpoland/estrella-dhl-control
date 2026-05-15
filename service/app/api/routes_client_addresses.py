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

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from ..core.config import settings
from ..core.security import require_api_key
from ..core.logging import get_logger
from ..services.client_addresses_db import (
    validate_address, init_db,
    create_address, list_addresses, get_address,
    update_address, delete_address,
)

log    = get_logger(__name__)
router = APIRouter(
    prefix="/api/v1/customer-master/{contractor_id}/shipping-addresses",
    tags=["customer-master"],
)
_auth   = Depends(require_api_key)
_DB_PATH = settings.storage_root / "customer_master.sqlite"


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
    }


@router.get("/", dependencies=[_auth], summary="List shipping addresses")
def list_addresses_endpoint(contractor_id: str) -> JSONResponse:
    try:
        addrs = list_addresses(_DB_PATH, contractor_id)
    except Exception as exc:
        log.error("list_addresses failed contractor_id=%s: %s", contractor_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse({"count": len(addrs), "addresses": [_addr_dict(a) for a in addrs]})


@router.post("/", dependencies=[_auth], summary="Create shipping address", status_code=201)
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
    try:
        init_db(_DB_PATH)
        addr_id = create_address(_DB_PATH, contractor_id, body)
    except Exception as exc:
        log.error("create_address failed contractor_id=%s: %s", contractor_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    stored = get_address(_DB_PATH, addr_id, contractor_id)
    if stored is None:
        raise HTTPException(status_code=500, detail="insert succeeded but record not found on re-read")
    log.info("shipping_address_created contractor_id=%s addr_id=%d", contractor_id, addr_id)
    return JSONResponse(status_code=201, content=_addr_dict(stored))


@router.put("/{addr_id}", dependencies=[_auth], summary="Update shipping address")
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
    return JSONResponse(_addr_dict(stored))


@router.delete("/{addr_id}", dependencies=[_auth], summary="Delete shipping address",
               status_code=204)
def delete_address_endpoint(contractor_id: str, addr_id: int) -> None:
    try:
        removed = delete_address(_DB_PATH, addr_id, contractor_id)
    except Exception as exc:
        log.error("delete_address failed addr_id=%d: %s", addr_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"Shipping address not found: id={addr_id} contractor_id={contractor_id!r}",
        )
    log.info("shipping_address_deleted contractor_id=%s addr_id=%d", contractor_id, addr_id)
