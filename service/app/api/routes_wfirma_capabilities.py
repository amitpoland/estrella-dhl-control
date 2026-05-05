"""
routes_wfirma_capabilities.py — wFirma capability/config check.

Endpoints
---------
  GET /api/v1/wfirma/capabilities
      Returns current wFirma integration state (config-only, no live API call).
      Tells the caller which operations are available before attempting creation.

  GET /api/v1/wfirma/customers
      List locally known customer mappings (client_name → wfirma_customer_id).

  GET /api/v1/wfirma/products
      List locally known product mappings (product_code → wfirma_product_id).

  PUT /api/v1/wfirma/customers/{client_name}
      Upsert a customer mapping (manual or post-sync registration).

  PUT /api/v1/wfirma/products/{product_code}
      Upsert a product mapping (manual or post-sync registration).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from ..core.security import require_api_key
from ..services import wfirma_capabilities as wfc
from ..services import wfirma_db as wfdb

router = APIRouter(prefix="/api/v1/wfirma", tags=["wfirma"])
_auth  = Depends(require_api_key)


# ── Capabilities ──────────────────────────────────────────────────────────────

@router.get("/capabilities", dependencies=[_auth])
def get_capabilities() -> JSONResponse:
    """
    Return wFirma integration capability state.

    Based on settings only — no live HTTP call to wFirma.
    Use this before attempting reservation/product/customer creation
    to understand what is currently supported.
    """
    return JSONResponse(wfc.get_capabilities())


# ── Customer mapping ──────────────────────────────────────────────────────────

class CustomerMappingRequest(BaseModel):
    wfirma_customer_id: Optional[str] = None
    vat_id:             str = ""
    country:            str = ""
    match_status:       str = "matched"


@router.get("/customers", dependencies=[_auth])
def list_customers(match_status: Optional[str] = None) -> JSONResponse:
    """List locally registered customer → wFirma customer_id mappings."""
    rows = wfdb.list_customers(match_status=match_status)
    return JSONResponse({"count": len(rows), "customers": rows})


@router.put("/customers/{client_name:path}", dependencies=[_auth])
def upsert_customer(client_name: str, req: CustomerMappingRequest) -> JSONResponse:
    """Register or update a customer mapping (manual or post-API-sync)."""
    row_id = wfdb.upsert_customer(
        client_name,
        wfirma_customer_id=req.wfirma_customer_id,
        vat_id=req.vat_id,
        country=req.country,
        match_status=req.match_status,
    )
    return JSONResponse({"ok": True, "id": row_id, "client_name": client_name})


# ── Product mapping ───────────────────────────────────────────────────────────

class ProductMappingRequest(BaseModel):
    wfirma_product_id: Optional[str] = None
    product_name_pl:   str = ""
    unit:              str = "szt."
    vat_rate:          str = "23"
    warehouse_id:      str = ""
    sync_status:       str = "matched"


@router.get("/products", dependencies=[_auth])
def list_products(sync_status: Optional[str] = None) -> JSONResponse:
    """List locally registered product_code → wFirma product_id mappings."""
    rows = wfdb.list_products(sync_status=sync_status)
    return JSONResponse({"count": len(rows), "products": rows})


@router.put("/products/{product_code:path}", dependencies=[_auth])
def upsert_product(product_code: str, req: ProductMappingRequest) -> JSONResponse:
    """Register or update a product mapping (manual or post-API-sync)."""
    row_id = wfdb.upsert_product(
        product_code,
        wfirma_product_id=req.wfirma_product_id,
        product_name_pl=req.product_name_pl,
        unit=req.unit,
        vat_rate=req.vat_rate,
        warehouse_id=req.warehouse_id,
        sync_status=req.sync_status,
    )
    return JSONResponse({"ok": True, "id": row_id, "product_code": product_code})
