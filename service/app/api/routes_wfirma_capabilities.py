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

from dataclasses import asdict, is_dataclass
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Any, Optional

from ..core.security import require_api_key
from ..services import wfirma_capabilities as wfc
from ..services import wfirma_client
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


# ─────────────────────────────────────────────────────────────────────────────
# Read-only live search — operator-approved customer/product mapping helper.
# Wraps wfirma_client.search_customer / get_product_by_code.
# Pure read: no local DB writes, no upsert side-effects, never calls
# wfirma_client.create_customer or create_product.
# ─────────────────────────────────────────────────────────────────────────────

def _to_jsonable(obj: Any) -> Any:
    """Convert dataclass results to plain dicts for JSON serialisation."""
    if obj is None:
        return None
    if is_dataclass(obj):
        return asdict(obj)
    return obj


@router.get("/contractors/search", dependencies=[_auth])
def search_contractor(
    name: str         = Query(..., min_length=1),
    nip:  Optional[str] = Query(default=None),
) -> JSONResponse:
    """
    Live wFirma contractor lookup. Returns one match or null.

    Read-only: never writes to wfirma_customers, never calls create_customer.
    The operator uses the response to confirm a mapping via PUT /customers/{name}.
    """
    try:
        result = wfirma_client.search_customer(name, nip)
    except Exception as exc:
        # search_customer raises RuntimeError on wFirma error and ConnectionError
        # on network failure. Either is upstream-fatal; surface as 502 so the
        # operator sees it as "wFirma upstream issue", not a client mistake.
        raise HTTPException(
            status_code=502,
            detail={
                "ok":    False,
                "found": False,
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
    return JSONResponse({
        "ok":     True,
        "found":  result is not None,
        "result": _to_jsonable(result),
    })


@router.get("/goods/search", dependencies=[_auth])
def search_good(
    product_code: str = Query(..., min_length=1),
) -> JSONResponse:
    """
    Live wFirma goods lookup by product code. Returns one match or null.

    Read-only: never writes to wfirma_products, never calls create_product.
    The operator uses the response to confirm a mapping via PUT /products/{code}.
    """
    try:
        result = wfirma_client.get_product_by_code(product_code)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "ok":    False,
                "found": False,
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
    return JSONResponse({
        "ok":     True,
        "found":  result is not None,
        "result": _to_jsonable(result),
    })
