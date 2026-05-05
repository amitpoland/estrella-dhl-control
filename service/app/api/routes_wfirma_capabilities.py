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
from typing import Any, List, Optional

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


# ── Bulk goods search (read-only triage) ────────────────────────────────────

class BulkGoodsSearchRequest(BaseModel):
    product_codes: List[str]


@router.post("/goods/search-bulk", dependencies=[_auth])
def search_goods_bulk(req: BulkGoodsSearchRequest) -> JSONResponse:
    """
    Look up many product_codes in one call. Per-code result with
    `found` and `result` (or `error` on per-code failure). One bad
    lookup does not abort the batch.

    Read-only: never writes to wfirma_products, never calls
    create_product. Designed for operators triaging missing-mapping
    blockers from the proforma preview.
    """
    if not req.product_codes:
        raise HTTPException(
            status_code=422, detail="product_codes must be a non-empty list",
        )

    # Preserve input order; collapse exact duplicates so we don't hit wFirma
    # twice for the same code, but keep the input position for the caller's
    # readability.
    seen_index: dict = {}
    for i, raw in enumerate(req.product_codes):
        pc = (raw or "").strip()
        if pc and pc not in seen_index:
            seen_index[pc] = i

    looked_up: dict = {}
    for pc in seen_index:
        try:
            result = wfirma_client.get_product_by_code(pc)
            looked_up[pc] = {
                "product_code": pc,
                "found":        result is not None,
                "result":       _to_jsonable(result),
            }
        except Exception as exc:
            looked_up[pc] = {
                "product_code": pc,
                "found":        False,
                "result":       None,
                "error":        f"{type(exc).__name__}: {exc}",
            }

    # Emit results in input order; for duplicates, repeat the cached row
    # so the caller can map 1:1 with their submitted list.
    results: List[dict] = []
    for raw in req.product_codes:
        pc = (raw or "").strip()
        if not pc:
            results.append({
                "product_code": raw,
                "found":        False,
                "result":       None,
                "error":        "empty product_code",
            })
            continue
        results.append(looked_up[pc])

    found_count   = sum(1 for r in results if r.get("found"))
    missing_count = sum(1 for r in results if not r.get("found") and "error" not in r)
    error_count   = sum(1 for r in results if "error" in r)
    return JSONResponse({
        "ok":            True,
        "count":         len(results),
        "found_count":   found_count,
        "missing_count": missing_count,
        "error_count":   error_count,
        "results":       results,
    })
