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

from ..core.config import settings
from ..core.logging import get_logger
from ..core.security import require_api_key
from ..services import description_engine as deng
from ..services import wfirma_capabilities as wfc
from ..services import wfirma_client
from ..services import wfirma_db as wfdb

log = get_logger(__name__)

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


# ── Operator-approved product create (search-first, locked block) ──────────

class CreateFromCodeRequest(BaseModel):
    item_type:      str
    description_en: str = ""


@router.post("/goods/create-from-product-code/{product_code:path}",
             dependencies=[_auth])
def create_good_from_product_code(
    product_code: str,
    req:          CreateFromCodeRequest,
) -> JSONResponse:
    """
    Operator-approved product create.

    Always search wFirma first. If found, persist the local mapping and
    return existing_mapped. If missing AND wfirma_create_product_allowed
    is true, build the payload from the locked description_block and call
    goods/add. Caller cannot override unit / vat_rate / type / code.

    Status values:
      existing_mapped — product already in wFirma; local mapping saved
      blocked         — missing in wFirma AND create flag is off
      created         — created via goods/add; local mapping + description saved
      failed          — goods/add returned an error; no local mapping written
    """
    if not (product_code or "").strip():
        raise HTTPException(status_code=400, detail="product_code is required")
    pc = product_code.strip()

    # ── 1. Search wFirma first (read-only) ─────────────────────────────────
    try:
        existing = wfirma_client.get_product_by_code(pc)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"ok": False, "status": "search_failed",
                    "error": f"{type(exc).__name__}: {exc}"},
        )

    if existing is not None:
        # Persist mapping locally; do NOT call create_product.
        wfdb.upsert_product(
            product_code      = pc,
            wfirma_product_id = existing.wfirma_id,
            product_name_pl   = existing.name or "",
            unit              = existing.unit or "szt.",
            vat_rate          = "23",
            sync_status       = "matched",
        )
        return JSONResponse({
            "ok":                True,
            "status":            "existing_mapped",
            "product_code":      pc,
            "wfirma_product_id": existing.wfirma_id,
            "name":              existing.name,
            "unit":              existing.unit,
        })

    # ── 2. Missing — gate on settings flag ─────────────────────────────────
    if not settings.wfirma_create_product_allowed:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "product_code":     pc,
            "blocking_reasons": [
                "wfirma_create_product_allowed is false — "
                "operator must enable WFIRMA_CREATE_PRODUCT_ALLOWED to create",
            ],
        })

    # ── 3. Create via goods/add using the locked description_block ─────────
    block = deng.get_description_block(
        product_code   = pc,
        item_type      = req.item_type,
        description_en = req.description_en,
    )

    # Master-data name per docs/wfirma.skill.md §5 (revised after live
    # wFirma review): the wFirma <code> field already holds the product_code
    # — repeating it in <name> is noise. The visible product name uses the
    # locked Polish-first / English-after-slash description_line.
    # Fallback chain: description_line → name_pl → product_code.
    wf_name = (
        (block.get("description_line") or "").strip()
        or (block.get("name_pl") or "").strip()
        or pc
    )

    try:
        result = wfirma_client.create_product(
            product_code = pc,
            name         = wf_name,
            unit         = "szt.",
            netto        = 0.0,
            vat_code_id  = wfirma_client.find_vat_code_id(23),
            description  = block.get("description_block") or "",
        )
    except Exception as exc:
        log.warning("[%s] goods/add failed: %s", pc, exc)
        return JSONResponse({
            "ok":          False,
            "status":      "failed",
            "product_code": pc,
            "error":       f"{type(exc).__name__}: {exc}",
        })

    # ── 4. Persist mapping locally only on confirmed success ───────────────
    if not result.wfirma_id:
        return JSONResponse({
            "ok":           False,
            "status":       "failed",
            "product_code": pc,
            "error":        "goods/add returned no wfirma_id — refusing fake mapping",
        })

    wfdb.upsert_product(
        product_code      = pc,
        wfirma_product_id = result.wfirma_id,
        product_name_pl   = block.get("name_pl") or "",
        unit              = "szt.",
        vat_rate          = "23",
        sync_status       = "matched",
    )

    return JSONResponse({
        "ok":                True,
        "status":            "created",
        "product_code":      pc,
        "wfirma_product_id": result.wfirma_id,
        "name":              result.name,
        "unit":              result.unit,
        "description_used":  block.get("description_line"),
    })
