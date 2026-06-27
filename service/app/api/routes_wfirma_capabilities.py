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
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
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
from ..services import wfirma_product_auto_register as _wfar
from ..services import wfirma_customer_auto_resolve as _wfcar

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/wfirma", tags=["wfirma"])
_auth  = Depends(require_api_key)


def _operator_from_header(x_operator: Optional[str]) -> str:
    """Extract operator id from the X-Operator header, fallback 'operator'.
    Used for correction-registry attribution on operator-approved actions."""
    return (x_operator or "").strip() or "operator"


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


# ── Ship-to receiver endpoint (Step 1 of Nabywca/Odbiorca support) ─────────
#
# Registered BEFORE the catch-all PUT /customers/{client_name:path} so the
# path-converter doesn't greedily swallow the /ship-to suffix. Mirrors the
# default-currency endpoint pattern: data-only operator action, never
# creates wFirma contractors, never touches bill-to identity fields.

class _ShipToRequest(BaseModel):
    mode: str
    ship_to_wfirma_customer_id: Optional[str] = ""


@router.put(
    "/customers/{client_name:path}/ship-to",
    dependencies=[_auth],
)
def set_customer_ship_to_endpoint(
    client_name: str,
    req:         _ShipToRequest,
    x_operator:  Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """
    Update ONLY ``ship_to_mode`` and ``ship_to_wfirma_customer_id`` for an
    existing mapped customer. Never creates customers; never touches
    ``wfirma_customer_id``, ``vat_id``, ``country``, ``match_status``,
    ``default_currency``.

    Body: ``{"mode": "separate_contractor", "ship_to_wfirma_customer_id": "..."}``

    Modes:
      - ``same_as_bill_to`` (default): no separate receiver — wFirma
        renders ship-to from the bill-to contractor's primary address.
      - ``bill_to_alt``: wFirma renders ship-to from the bill-to
        contractor's own alt-address fields (must be configured in
        wFirma master with ``different_contact_address=1``). No
        receiver id needed.
      - ``separate_contractor``: ship-to is a SEPARATE wFirma contractor.
        ``ship_to_wfirma_customer_id`` is required and must already exist
        in wFirma master (live existence check is deferred to Step 3 —
        see Risks).

    Unknown mode → 400.
    Missing receiver id when mode=separate_contractor → 400.
    Unknown customer → 404.
    """
    try:
        result = wfdb.set_customer_ship_to(
            client_name                = client_name,
            mode                       = req.mode,
            ship_to_wfirma_customer_id = (req.ship_to_wfirma_customer_id or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"customer {client_name!r} not registered in "
                   "wfirma_customers — register the mapping first",
        )
    return JSONResponse({
        "ok":          True,
        "client_name": result["client_name"],
        "id":          result["id"],
        "before": {
            "mode":                       result["before_mode"],
            "ship_to_wfirma_customer_id": result["before_ship_to_wfirma_customer_id"],
        },
        "after": {
            "mode":                       result["after_mode"],
            "ship_to_wfirma_customer_id": result["after_ship_to_wfirma_customer_id"],
        },
        "operator":    (x_operator or "").strip(),
    })


# ── Default-currency endpoint (Proforma pricing fallback) ──────────────────
#
# Registered BEFORE the catch-all PUT /customers/{client_name:path} so the
# path-converter doesn't greedily swallow the /default-currency suffix.

class _DefaultCurrencyRequest(BaseModel):
    currency: str


@router.put(
    "/customers/{client_name:path}/default-currency",
    dependencies=[_auth],
)
def set_customer_default_currency(
    client_name: str,
    req:         _DefaultCurrencyRequest,
    x_operator:  Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """
    Update ONLY ``default_currency`` for an existing mapped customer.
    Never creates customers; never touches ``wfirma_customer_id``,
    ``vat_id``, ``country``, or ``match_status``.

    Body: ``{"currency": "EUR"}``. Allowed values: EUR, USD, PLN, GBP,
    CHF, JPY. Unknown currency → 400. Unknown customer → 404.
    """
    try:
        result = wfdb.set_customer_default_currency(
            client_name=client_name, currency=req.currency,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"customer {client_name!r} not registered in "
                   "wfirma_customers — register the mapping first",
        )
    return JSONResponse({
        "ok":              True,
        "client_name":     result["client_name"],
        "id":              result["id"],
        "before_currency": result["before_currency"],
        "after_currency":  result["after_currency"],
        "operator":        (x_operator or "").strip(),
    })


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


# ── Search-first PRODUCT AUTHORITY: search-and-compare (PR 1 foundation) ────
#
# Operator-stated workflow (2026-05-23):
#   Search wFirma → Found? Yes → compare metadata → ask before update/overwrite
# This endpoint is the read-only "compare metadata" surface. Future PRs
# wire the interactive /adopt, /update-and-adopt, /create write paths that
# act on operator confirmation. This endpoint NEVER writes — operators can
# preview the comparison freely without risking unintended adoption.


@router.get("/goods/search-and-compare", dependencies=[_auth])
def search_and_compare_good(
    product_code: str = Query(..., min_length=1),
    name_pl:      Optional[str] = Query(default=None),
    unit:         Optional[str] = Query(default=None),
    vat_rate:     Optional[str] = Query(default=None),
) -> JSONResponse:
    """
    Search wFirma for ``product_code`` AND compare the live response against
    the operator-supplied local expectation. Read-only; never writes.

    Surfaces the metadata-comparison foundation of the search-first product
    authority workflow. Future endpoints (``/adopt``, ``/update-and-adopt``,
    ``/create``) will consume the same comparison output and act on operator
    confirmation. This endpoint allows preview without write risk.

    Response payload::

        {
          "ok":           True | False,
          "wfirma_error": <str>  # populated only when wFirma side raised
          "comparison":   { ... output of compare_product_metadata ... }
        }

    Use cases:
      * Operator triages a missing-mapping blocker in the proforma preview
        and wants to see what wFirma already has under that code.
      * Dashboard "Verify" button shows the diff inline before any write.
      * Pre-flight check before bulk auto-register: which codes would
        trigger operator-review status?
    """
    from ..services.wfirma_product_compare import compare_product_metadata

    # 1. Live wFirma search (read-only)
    wfirma_error = ""
    try:
        wf_product = wfirma_client.get_product_by_code(product_code)
    except Exception as exc:
        wf_product = None
        wfirma_error = f"{type(exc).__name__}: {exc}"

    # 2. Build local expectation from optional query params. Empty / None
    #    fields are dropped so the comparator treats them as "no expectation".
    local_expected = {
        k: v for k, v in {
            "product_code": product_code,
            "name_pl":      name_pl,
            "unit":         unit,
            "vat_rate":     vat_rate,
        }.items() if v not in (None, "")
    }
    if list(local_expected.keys()) == ["product_code"]:
        # Only the code echo — no real local expectation supplied.
        local_expected = None  # type: ignore[assignment]

    # 3. Pure compare — no writes.
    comparison = compare_product_metadata(
        wfirma_product = wf_product,
        local_expected = local_expected,
        product_code   = product_code,
    )

    return JSONResponse({
        "ok":           wfirma_error == "",
        "wfirma_error": wfirma_error,
        "comparison":   comparison,
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


# ── Search-first product authority — operator-choice write endpoints ───────
#
# These 3 endpoints implement the operator-stated 2026-05-23 workflow:
#
#    Product required → Search wFirma → Found?
#      ├─ Yes → adopt → compare metadata → ask before update
#      │        a) No overwrite  → /goods/adopt           (this section)
#      │        b) Yes overwrite → /goods/update-and-adopt
#      └─ No                     → /goods/create-and-adopt
#
# Each endpoint asserts an explicit operator decision. They REFUSE to
# silently cross paths: /adopt errors 409 if wFirma doesn't have the
# product (operator should call /create-and-adopt); /create-and-adopt
# errors 409 if wFirma already has the product (operator should call
# /adopt or /update-and-adopt). This prevents duplicate creation and
# accidental overwrite even under operator-UI race conditions.
#
# Reuses existing infrastructure (no new dependencies, no new flags):
#   - wfirma_client.get_product_by_code() for search
#   - wfirma_client.edit_product()        gated on wfirma_edit_product_allowed
#   - wfirma_client.create_product()      gated on wfirma_create_product_allowed
#   - wfdb.upsert_product()               for local mirror (sync_status=matched)
#   - wfirma_product_compare.compare_product_metadata() for diff in responses
#
# design_code is NEVER used as identity in any of these endpoints. The
# product_code is the sole authority key. design_code may appear in
# request bodies (passed to deng.get_description_block as metadata only).


class AdoptProductRequest(BaseModel):
    """Optional local expectation supplied by the caller; used ONLY for
    building the response advisory + comparison payload. No effect on
    the wFirma side (nothing is written there)."""
    name_pl: Optional[str] = None
    unit:    Optional[str] = None


class UpdateAndAdoptProductRequest(BaseModel):
    """Operator-supplied new values to push to wFirma's existing product
    via wfirma_client.edit_product (name + description only — identity
    fields like code/unit/vat are NEVER mutated)."""
    name:        Optional[str] = None
    description: Optional[str] = None
    # Local expectation for the comparison payload (optional, informational)
    name_pl:     Optional[str] = None
    unit:        Optional[str] = None


class CreateAndAdoptProductRequest(BaseModel):
    """Operator-confirmed create. Same shape as CreateFromCodeRequest;
    we route through deng.get_description_block to lock the Polish
    description identical to the legacy create endpoint."""
    item_type:      str
    description_en: str = ""


@router.post("/goods/adopt/{product_code:path}", dependencies=[_auth])
def adopt_existing_product(
    product_code: str,
    req: Optional[AdoptProductRequest] = None,
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """
    Operator's "No overwrite" path: search wFirma, MUST find the product,
    mirror the mapping locally. wFirma side is NEVER mutated by this
    endpoint — no create, no edit. Idempotent.

    Errors:
      409  product not in wFirma — operator should call /create-and-adopt
      502  wFirma search failed
      500  local mirror write failed
    """
    from ..services.wfirma_product_compare import compare_product_metadata

    if not (product_code or "").strip():
        raise HTTPException(status_code=400, detail="product_code is required")
    pc = product_code.strip()
    op = _operator_from_header(x_operator)

    # 1. Search wFirma — MUST find for /adopt to apply
    try:
        existing = wfirma_client.get_product_by_code(pc)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"ok": False, "status": "search_failed",
                    "error": f"{type(exc).__name__}: {exc}"},
        )

    if existing is None:
        # Refuse to cross paths — operator must call the explicit create
        # endpoint. This prevents duplicate creation under UI races.
        raise HTTPException(
            status_code=409,
            detail={
                "ok":           False,
                "status":       "not_in_wfirma",
                "product_code": pc,
                "hint":         "wFirma has no product for this code — "
                                "call POST /goods/create-and-adopt to create.",
            },
        )

    # 2. Build comparison for the response advisory (informational only;
    #    /adopt always proceeds since operator already chose this path).
    local_expected = None
    if req is not None:
        local_expected = {
            k: v for k, v in {
                "product_code": pc,
                "name_pl":      req.name_pl,
                "unit":         req.unit,
            }.items() if v not in (None, "")
        } or None
    comparison = compare_product_metadata(
        wfirma_product = existing,
        local_expected = local_expected,
        product_code   = pc,
    )

    # 3. Persist the local mirror (wFirma side untouched).
    try:
        wfdb.upsert_product(
            product_code      = pc,
            wfirma_product_id = existing.wfirma_id,
            product_name_pl   = existing.name or "",
            unit              = existing.unit or "szt.",
            vat_rate          = "23",
            sync_status       = "matched",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "status": "local_mirror_failed",
                    "error": f"{type(exc).__name__}: {exc}"},
        )

    return JSONResponse({
        "ok":                True,
        "action":            "adopted",
        "product_code":      pc,
        "wfirma_product_id": existing.wfirma_id,
        "wfirma_untouched":  True,
        "operator":          op,
        "comparison":        comparison,
    })


@router.post("/goods/update-and-adopt/{product_code:path}",
             dependencies=[_auth])
def update_and_adopt_product(
    product_code: str,
    req: UpdateAndAdoptProductRequest,
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """
    Operator's "Yes overwrite" path: search wFirma, MUST find the product,
    call goods/edit with operator-supplied name/description, then mirror.
    Only name + description fields are sent to wFirma — code, unit, vat,
    price are identity-preserved by wfirma_client.edit_product().

    Gated on settings.wfirma_edit_product_allowed (existing flag — does
    NOT introduce a new flag).

    Errors:
      400  no fields to update (both name and description empty)
      403  wfirma_edit_product_allowed is false
      409  product not in wFirma — operator should call /create-and-adopt
      502  wFirma edit failed
      500  local mirror write failed
    """
    from ..services.wfirma_product_compare import compare_product_metadata

    if not (product_code or "").strip():
        raise HTTPException(status_code=400, detail="product_code is required")
    pc = product_code.strip()
    op = _operator_from_header(x_operator)

    new_name = (req.name or "").strip()
    new_desc = (req.description or "").strip()
    if not new_name and not new_desc:
        raise HTTPException(
            status_code=400,
            detail="at least one of name or description must be non-empty",
        )

    # Gate
    if not getattr(settings, "wfirma_edit_product_allowed", False):
        return JSONResponse(
            status_code=403,
            content={
                "ok":               False,
                "status":           "blocked",
                "product_code":     pc,
                "blocking_reasons": [
                    "wfirma_edit_product_allowed is false — "
                    "operator must enable WFIRMA_EDIT_PRODUCT_ALLOWED to update",
                ],
            },
        )

    # 1. Search wFirma — MUST find for /update-and-adopt to apply
    try:
        existing = wfirma_client.get_product_by_code(pc)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"ok": False, "status": "search_failed",
                    "error": f"{type(exc).__name__}: {exc}"},
        )
    if existing is None:
        raise HTTPException(
            status_code=409,
            detail={
                "ok":           False,
                "status":       "not_in_wfirma",
                "product_code": pc,
                "hint":         "wFirma has no product for this code — "
                                "call POST /goods/create-and-adopt to create.",
            },
        )

    # 2. Push the edit to wFirma (identity-preserving — code/unit/vat
    #    are never mutated by wfirma_client.edit_product).
    edit_kwargs = {}
    if new_name:
        edit_kwargs["name"] = new_name
    if new_desc:
        edit_kwargs["description"] = new_desc
    try:
        edit_result = wfirma_client.edit_product(
            existing.wfirma_id, **edit_kwargs,
        )
    except Exception as exc:
        log.warning("[%s] goods/edit failed: %s", pc, exc)
        return JSONResponse(
            status_code=502,
            content={"ok": False, "status": "edit_failed",
                     "product_code": pc,
                     "error": f"{type(exc).__name__}: {exc}"},
        )

    # 3. Persist local mirror with the updated name.
    try:
        wfdb.upsert_product(
            product_code      = pc,
            wfirma_product_id = existing.wfirma_id,
            product_name_pl   = edit_result.get("name") or new_name or existing.name or "",
            unit              = edit_result.get("unit") or existing.unit or "szt.",
            vat_rate          = "23",
            sync_status       = "matched",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "status": "local_mirror_failed",
                    "error": f"{type(exc).__name__}: {exc}"},
        )

    # 4. Build post-edit comparison for response payload.
    #    The local_expected is what the operator just pushed (name +
    #    optional unit), so an adopt_as_is result confirms the edit
    #    landed correctly on the wFirma side.
    local_expected = {
        k: v for k, v in {
            "product_code": pc,
            "name_pl":      new_name or req.name_pl,
            "unit":         req.unit,
        }.items() if v not in (None, "")
    } or None
    # Synth post-edit wFirma view from edit_result for the diff.
    class _EditedView:
        wfirma_id = existing.wfirma_id
        name = edit_result.get("name") or new_name
        code = edit_result.get("code") or pc
        unit = edit_result.get("unit") or existing.unit
        count = 0.0
        reserved = 0.0
    comparison = compare_product_metadata(
        wfirma_product = _EditedView,
        local_expected = local_expected,
        product_code   = pc,
    )

    return JSONResponse({
        "ok":                 True,
        "action":             "updated_and_adopted",
        "product_code":       pc,
        "wfirma_product_id":  existing.wfirma_id,
        "updated_fields":     sorted(edit_kwargs.keys()),
        "wfirma_post_state":  {
            "name": edit_result.get("name"),
            "code": edit_result.get("code"),
            "unit": edit_result.get("unit"),
        },
        "operator":           op,
        "comparison":         comparison,
    })


@router.post("/goods/create-and-adopt/{product_code:path}",
             dependencies=[_auth])
def create_and_adopt_product(
    product_code: str,
    req: CreateAndAdoptProductRequest,
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """
    Operator's "missing → create" path: search wFirma, MUST NOT find the
    product (409 if it exists — operator should call /adopt instead),
    call goods/add via the locked description_block, mirror locally.

    Gated on settings.wfirma_create_product_allowed (existing flag).

    Errors:
      403  wfirma_create_product_allowed is false
      409  product ALREADY in wFirma — operator should call /adopt
      502  wFirma search OR create failed
      500  local mirror write failed
    """
    if not (product_code or "").strip():
        raise HTTPException(status_code=400, detail="product_code is required")
    pc = product_code.strip()
    op = _operator_from_header(x_operator)

    # Gate
    if not settings.wfirma_create_product_allowed:
        return JSONResponse(
            status_code=403,
            content={
                "ok":               False,
                "status":           "blocked",
                "product_code":     pc,
                "blocking_reasons": [
                    "wfirma_create_product_allowed is false — "
                    "operator must enable WFIRMA_CREATE_PRODUCT_ALLOWED to create",
                ],
            },
        )

    # 1. Search wFirma — MUST NOT find for /create-and-adopt to apply.
    #    Prevents duplicate creation under UI races.
    try:
        existing = wfirma_client.get_product_by_code(pc)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"ok": False, "status": "search_failed",
                    "error": f"{type(exc).__name__}: {exc}"},
        )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "ok":           False,
                "status":       "already_in_wfirma",
                "product_code": pc,
                "wfirma_product_id": existing.wfirma_id,
                "hint":         "wFirma already has this product — "
                                "call POST /goods/adopt (or "
                                "/goods/update-and-adopt) instead. "
                                "Refusing to create a duplicate.",
            },
        )

    # 2. Build the locked description_block via deng (same as the legacy
    #    /create-from-product-code endpoint — keeps Polish name formatting
    #    canonical).
    block = deng.get_description_block(
        product_code   = pc,
        item_type      = req.item_type,
        description_en = req.description_en,
    )
    wf_name = (
        (block.get("description_line") or "").strip()
        or (block.get("name_pl") or "").strip()
        or pc
    )

    # 3. Create via goods/add.
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
        return JSONResponse(
            status_code=502,
            content={"ok": False, "status": "create_failed",
                     "product_code": pc,
                     "error": f"{type(exc).__name__}: {exc}"},
        )
    if not result.wfirma_id:
        return JSONResponse(
            status_code=502,
            content={"ok": False, "status": "create_failed",
                     "product_code": pc,
                     "error": "goods/add returned no wfirma_id — refusing fake mapping"},
        )

    # 4. Persist local mirror only on confirmed wFirma success.
    try:
        wfdb.upsert_product(
            product_code      = pc,
            wfirma_product_id = result.wfirma_id,
            product_name_pl   = block.get("name_pl") or "",
            unit              = "szt.",
            vat_rate          = "23",
            sync_status       = "matched",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "status": "local_mirror_failed",
                    "error": f"{type(exc).__name__}: {exc}"},
        )

    return JSONResponse({
        "ok":                True,
        "action":            "created_and_adopted",
        "product_code":      pc,
        "wfirma_product_id": result.wfirma_id,
        "name":              result.name,
        "unit":              result.unit,
        "description_used":  block.get("description_line"),
        "operator":          op,
    })


@router.post("/shipment/{batch_id:path}/adopt-pending-found",
             dependencies=[_auth])
def adopt_pending_found_for_batch(
    batch_id: str,
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Batch adopt every product_code in THIS batch that was found in wFirma and
    is awaiting an operator decision (sync_status=='pending_adoption' with a
    wfirma_product_id) — flip it to 'matched'.

    LOCAL AUTHORITY ONLY. This is NOT a wFirma write: it neither creates nor
    edits a wFirma good — it only adopts already-existing wFirma products into
    local 'matched' authority. No feature flag gates it (adoption of an
    existing product is not a write); create/register stays gated by
    WFIRMA_CREATE_PRODUCT_ALLOWED on the per-row create-and-adopt path.

    Batch-scoped: only the codes present in this batch's invoice_lines are
    considered. Note that wfirma_products maps product_code → wFirma good
    GLOBALLY (one unique row per code — there is no per-batch product mapping),
    so adopting code X is by design a global authority decision: it asserts
    "code X maps to wFirma good Y" everywhere, which is correct because the code
    is the global identity. Batch scoping bounds WHICH codes this call may adopt;
    it does not (and need not) create per-batch product rows. Operators wanting
    to eyeball each wFirma name before committing use the per-row Compare +
    Adopt in the pending modal; batch adopt trusts the discovery (goods/find by
    code) mapping. Rows that are missing, unlinked, already-matched, or in any
    other status are SKIPPED with an explicit reason. Idempotent.

    Response: { ok, batch_id, considered, adopted_count, adopted[], skipped[] }
    """
    if ".." in batch_id or batch_id.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    op = _operator_from_header(x_operator)

    from ..services import document_db as _ddb
    try:
        invoice_rows = _ddb.get_invoice_lines_for_batch(batch_id) or []
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"ok": False, "error": "invoice_lines read failed: " + str(exc)},
        )

    codes = sorted({
        (r.get("product_code") or "").strip()
        for r in invoice_rows
        if (r.get("product_code") or "").strip()
    })
    cache = wfdb.get_products_batch(codes) if codes else {}

    adopted: List[str] = []
    skipped: List[dict] = []
    for pc in codes:
        row    = cache.get(pc) or {}
        status = (row.get("sync_status") or "").strip()
        wfid   = (row.get("wfirma_product_id") or "").strip()
        if status == "matched" and wfid:
            skipped.append({"product_code": pc, "reason": "already_matched"})
        elif status == "pending_adoption" and wfid:
            if wfdb.adopt_pending_product(pc):
                adopted.append(pc)
            else:                       # lost a race / row changed under us
                skipped.append({"product_code": pc, "reason": "adopt_no_op"})
        elif not row:
            skipped.append({"product_code": pc, "reason": "not_resolved_yet"})
        elif not wfid:
            skipped.append({"product_code": pc, "reason": "missing_in_wfirma"})
        else:
            skipped.append({"product_code": pc, "reason": "status_" + (status or "unknown")})

    log.info(
        "[%s] adopt-pending-found: adopted=%d skipped=%d (operator=%s)",
        batch_id, len(adopted), len(skipped), op,
    )
    return JSONResponse({
        "ok":               True,
        "batch_id":         batch_id,
        "operator":         op,
        "considered":       len(codes),
        "adopted_count":    len(adopted),
        "adopted":          adopted,
        "skipped":          skipped,
        "wfirma_untouched": True,
    })


# ── Batch wFirma product auto-registration (dry-run + write) ───────────────
#
# Compose the existing single-product create flow over an entire batch's
# invoice_lines. The dry-run endpoint NEVER calls goods/add — it only
# searches wFirma for each code and reports missing ones. The write
# endpoint honors the existing wfirma_create_product_allowed flag.
# No service-actor bypass; no observer (those are deliberately deferred).


@router.post("/goods/auto-register-preview/{batch_id:path}",
             dependencies=[_auth])
def auto_register_preview(
    batch_id: str,
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """
    Read-only preview of what auto-registration would do for *batch_id*.

    Searches wFirma for each unique invoice-line product_code, mirrors
    any existing matches into the local wfirma_products table, and
    reports the rest as ``missing``. NEVER calls goods/add. Safe to
    invoke at any time, including before the operator flips
    WFIRMA_CREATE_PRODUCT_ALLOWED.

    Mirrored existing matches log a `product_mapping_override`
    correction (operator-approved, append-only) — pure missing rows
    do not log.
    """
    if not (batch_id or "").strip() or "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    return JSONResponse(_wfar.ensure_products_for_batch(
        batch_id, dry_run=True,
        operator=_operator_from_header(x_operator),
    ))


@router.post("/goods/auto-register/{batch_id:path}", dependencies=[_auth])
def auto_register_write(
    batch_id: str,
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """
    Write-mode batch auto-registration. Honors
    ``settings.wfirma_create_product_allowed`` — when the flag is off,
    every missing product is reported as ``blocked`` and no goods/add
    is called. Idempotent: existing products short-circuit to
    ``existing_mapped`` via the search-first step.

    Each ``existing_mapped`` and ``created`` row records an
    operator-approved `product_mapping_override` in the correction
    registry. ``blocked`` / ``failed`` / ``missing`` rows do not log.
    """
    if not (batch_id or "").strip() or "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    return JSONResponse(_wfar.ensure_products_for_batch(
        batch_id, dry_run=False,
        operator=_operator_from_header(x_operator),
    ))


# ── Batch wFirma customer auto-resolve (read-only preview) ────────────────
#
# Walk distinct sales-side client names for the batch, normalize them,
# search wFirma's local mirror first, then fall back to a live
# contractors/find search (read-only). Successful matches are mirrored
# into both wfirma_customers (master) and wfirma_customer_mapping
# (parallel registry). NEVER calls create_customer; the single-customer
# create path remains operator-only.


class CustomerAutoCreateRequest(BaseModel):
    """Body for the operator-triggered customer auto-create endpoint."""
    client_name:  str
    vat_id:       str = ""
    country_code: str = ""


@router.post("/customers/auto-create-from-name", dependencies=[_auth])
def customer_auto_create_from_name(
    req: CustomerAutoCreateRequest,
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """
    Operator-triggered single-customer create with mandatory
    resolver-gate. Pre-create gate:

      • Re-runs the VAT-first ambiguity-safe resolver.
      • REFUSES create when the resolver returns any of:
          exact_match, normalized_match, prefix_match,
          reverse_prefix_match, ambiguous, ambiguous_vat
        (resolver already mirrored the safe match into the local
        registries, or there's enough uncertainty to require operator
        review).
      • Only ``status="missing"`` proceeds to wFirma.

    Honors ``settings.wfirma_create_customer_allowed`` (default False);
    no service-actor bypass. On wFirma confirmed success, mirrors into
    both ``wfirma_customers`` (master) and
    ``reservation_queue.wfirma_customer_mapping`` (parallel registry).
    """
    return JSONResponse(_wfcar.create_one(
        client_name  = req.client_name,
        vat_id       = req.vat_id,
        country_code = req.country_code,
        operator     = _operator_from_header(x_operator),
    ))


@router.post("/customers/auto-resolve-preview/{batch_id:path}",
             dependencies=[_auth])
def customer_auto_resolve_preview(
    batch_id: str,
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """
    Read-only customer resolution for *batch_id*.

    For every distinct client_name found in sales_documents (with a
    fallback to sales_packing_lines), the resolver tries: exact local
    match, normalized exact, prefix tolerance ("Clear-Diamonds" →
    "Clear-Diamonds Ltd"), reverse-prefix, then a live wFirma
    contractors/find search. Matches are mirrored into local registries
    so subsequent Proforma previews resolve them automatically. NEVER
    creates a customer in wFirma.
    """
    if not (batch_id or "").strip() or "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    return JSONResponse(_wfcar.ensure_customers_for_batch(
        batch_id, dry_run=True,
        operator=_operator_from_header(x_operator),
    ))


# ── Operator-approved goods/edit refresh from locked block ─────────────────

@router.post("/goods/refresh-name-from-block/{product_code:path}",
             dependencies=[_auth])
def refresh_good_name_from_block(product_code: str) -> JSONResponse:
    """
    Refresh an EXISTING wFirma product's name + description in place,
    sourced from the locked description_engine block.

    Operator-approved only. Per-product per call. No bulk endpoint.

    Status values:
      blocked  — gate off (WFIRMA_EDIT_PRODUCT_ALLOWED=false), or local
                 mapping missing/empty wfirma_product_id, or
                 description_engine has no usable block for this code.
      updated  — goods/edit succeeded; local product_name_pl refreshed.
      failed   — wFirma returned an error or refused; no local update.
    """
    if not (product_code or "").strip():
        raise HTTPException(status_code=400, detail="product_code is required")
    pc = product_code.strip()

    # ── 1. Settings gate ──────────────────────────────────────────────────
    if not settings.wfirma_edit_product_allowed:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "product_code":     pc,
            "blocking_reasons": [
                "wfirma_edit_product_allowed is false — operator must enable "
                "WFIRMA_EDIT_PRODUCT_ALLOWED to edit",
            ],
        })

    # ── 2. Local mapping must exist with non-empty wfirma_product_id ──────
    local = wfdb.get_product(pc)
    wfirma_product_id = (local or {}).get("wfirma_product_id") or ""
    if not local or not wfirma_product_id:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "product_code":     pc,
            "blocking_reasons": [
                f"wfirma_products has no wfirma_product_id for {pc!r} — "
                "register the mapping first",
            ],
        })

    # ── 3. Locked block must exist with usable line + block ───────────────
    block = deng.get_description_block(
        product_code = pc,
        item_type    = (local or {}).get("product_name_pl") or "",
    )
    description_line  = (block.get("description_line")  or "").strip()
    description_block = (block.get("description_block") or "").strip()
    if not description_line or not description_block:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "product_code":     pc,
            "blocking_reasons": [
                f"description_engine has no locked block for {pc!r} — "
                "generate one before refreshing the wFirma name",
            ],
        })

    # ── 4. Live wFirma edit (only path with external write) ───────────────
    try:
        result = wfirma_client.edit_product(
            wfirma_product_id = wfirma_product_id,
            name              = description_line,
            description       = description_block,
        )
    except Exception as exc:
        log.warning("[%s] goods/edit failed: %s", pc, exc)
        return JSONResponse({
            "ok":          False,
            "status":      "failed",
            "product_code": pc,
            "wfirma_product_id": wfirma_product_id,
            "error":       f"{type(exc).__name__}: {exc}",
        })

    # ── 5. Refresh local mapping only on confirmed success ────────────────
    # Local product_name_pl carries the SHORT polish name (matches what
    # description_engine.name_pl returns). The full description_line stays
    # reconstructible via description_engine — no need to cache it locally.
    name_pl = (block.get("name_pl") or "").strip()
    wfdb.upsert_product(
        product_code      = pc,
        wfirma_product_id = wfirma_product_id,
        product_name_pl   = name_pl,
        unit              = (local or {}).get("unit") or "szt.",
        vat_rate          = (local or {}).get("vat_rate") or "23",
        warehouse_id      = (local or {}).get("warehouse_id") or "",
        sync_status       = "matched",
    )

    return JSONResponse({
        "ok":                True,
        "status":            "updated",
        "product_code":      pc,
        "wfirma_product_id": wfirma_product_id,
        "wfirma_name":       result.get("name"),
        "name_used":         description_line,
        "description_used":  description_block,
    })


# ── Internal-test contractor (locked-name, narrow-scope create) ─────────────
#
# This endpoint is the ONLY backdoor for live contractors/add. It exists
# solely to spawn a single ESTRELLA INTERNAL TEST contractor used as the
# safe target for wFirma write diagnostics (12-line proforma persistence
# probe, etc.). It does NOT expose generic customer creation:
#   - name/country/city/zip/nip are HARD-CODED here, not request-derived
#   - the only customer name accepted is "ESTRELLA INTERNAL TEST"
#   - search-first; if the contractor already exists, just save the local
#     mapping and return existing_mapped (no goods/add call)
#   - settings gate WFIRMA_CREATE_CUSTOMER_ALLOWED must be true to create
#   - on create failure, no local mapping is written

_INTERNAL_TEST_NAME    = "ESTRELLA INTERNAL TEST"
_INTERNAL_TEST_COUNTRY = "PL"
_INTERNAL_TEST_CITY    = "Warszawa"
_INTERNAL_TEST_ZIP     = "00-001"
_INTERNAL_TEST_NIP     = ""   # blank — wFirma allows non-VAT contractors


@router.post("/customers/create-internal-test", dependencies=[_auth])
def create_internal_test_customer() -> JSONResponse:
    """
    Create or register the internal-test contractor for wFirma diagnostics.

    Status values:
      existing_mapped — contractor already in wFirma; local mapping saved
      blocked         — missing in wFirma AND create flag is off
      created         — created via contractors/add; local mapping saved
      failed          — contractors/add returned an error; no local mapping
    """
    name = _INTERNAL_TEST_NAME

    # ── 1. Search wFirma first (read-only) ─────────────────────────────────
    try:
        existing = wfirma_client.search_customer(name)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"ok": False, "status": "search_failed",
                    "error": f"{type(exc).__name__}: {exc}"},
        )

    if existing is not None and (existing.wfirma_id or "").strip():
        wfdb.upsert_customer(
            client_name        = name,
            wfirma_customer_id = existing.wfirma_id,
            country            = existing.country or _INTERNAL_TEST_COUNTRY,
            match_status       = "matched",
        )
        return JSONResponse({
            "ok":                  True,
            "status":              "existing_mapped",
            "client_name":         name,
            "wfirma_customer_id":  existing.wfirma_id,
            "country":             existing.country,
            "city":                existing.city,
            "zip":                 existing.zip,
        })

    # ── 2. Missing — gate on settings flag ─────────────────────────────────
    if not settings.wfirma_create_customer_allowed:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "client_name":      name,
            "blocking_reasons": [
                "wfirma_create_customer_allowed is false — operator must "
                "enable WFIRMA_CREATE_CUSTOMER_ALLOWED to create",
            ],
        })

    # ── 3. Create via contractors/add (locked field set) ────────────────────
    try:
        created = wfirma_client.create_customer(
            name     = _INTERNAL_TEST_NAME,
            nip      = _INTERNAL_TEST_NIP,
            country  = _INTERNAL_TEST_COUNTRY,
            zip_code = _INTERNAL_TEST_ZIP,
            city     = _INTERNAL_TEST_CITY,
        )
    except Exception as exc:
        log.warning("contractors/add internal-test failed: %s", exc)
        return JSONResponse({
            "ok":          False,
            "status":      "failed",
            "client_name": name,
            "error":       f"{type(exc).__name__}: {exc}",
        })

    if not (created.wfirma_id or "").strip():
        return JSONResponse({
            "ok":          False,
            "status":      "failed",
            "client_name": name,
            "error":       "contractors/add returned no wfirma_id — refusing fake mapping",
        })

    wfdb.upsert_customer(
        client_name        = name,
        wfirma_customer_id = created.wfirma_id,
        country            = _INTERNAL_TEST_COUNTRY,
        match_status       = "matched",
    )

    return JSONResponse({
        "ok":                  True,
        "status":              "created",
        "client_name":         name,
        "wfirma_customer_id":  created.wfirma_id,
        "country":             _INTERNAL_TEST_COUNTRY,
        "city":                _INTERNAL_TEST_CITY,
        "zip":                 _INTERNAL_TEST_ZIP,
    })


# ── Customer sync from wFirma (read-only by default) ─────────────────────────

from ..services import wfirma_customer_sync as wfsync   # noqa: E402


@router.get("/customers/sync-preview", dependencies=[_auth])
def sync_customers_preview() -> JSONResponse:
    """
    Read-only sync plan. Pulls all wFirma contractors and classifies them
    against local wfirma_customers without writing. Always safe to call.
    """
    try:
        plan = wfsync.plan_sync()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"ok": False, "status": "fetch_failed",
                    "error": f"{type(exc).__name__}: {exc}"},
        )
    return JSONResponse({
        "ok":             True,
        "mode":           "preview",
        "total_remote":   plan["total_remote"],
        "insert":         plan["insert"],
        "update_fill":    plan["update_fill"],
        "update_match":   plan["update_match"],
        "conflict":       plan["conflict"],
        "skip_count":      plan["skip_count"],
        "skipped_invalid": plan.get("skipped_invalid", 0),
        "incomplete":      plan.get("incomplete", False),
        "applied_count":   0,
        "conflicts":       plan["conflict"],
    })


@router.post("/customers/sync", dependencies=[_auth])
def sync_customers(write: bool = False) -> JSONResponse:
    """
    Sync wFirma contractors into local wfirma_customers.

    Default (write=false): same shape as sync-preview, no writes.
    write=true requires settings.wfirma_sync_customers_allowed; only
    insert / update_fill / update_match rows are applied. Conflicts
    are returned but never auto-resolved.
    """
    try:
        plan = wfsync.plan_sync()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"ok": False, "status": "fetch_failed",
                    "error": f"{type(exc).__name__}: {exc}"},
        )

    response = {
        "ok":             True,
        "mode":           "preview" if not write else "write",
        "total_remote":   plan["total_remote"],
        "insert":         plan["insert"],
        "update_fill":    plan["update_fill"],
        "update_match":   plan["update_match"],
        "conflict":       plan["conflict"],
        "skip_count":      plan["skip_count"],
        "skipped_invalid": plan.get("skipped_invalid", 0),
        "incomplete":      plan.get("incomplete", False),
        "applied_count":   0,
        "conflicts":       plan["conflict"],
    }

    if not write:
        return JSONResponse(response)

    if not settings.wfirma_sync_customers_allowed:
        return JSONResponse({
            **response,
            "ok":               False,
            "mode":             "blocked",
            "blocking_reasons": [
                "wfirma_sync_customers_allowed is false — operator must "
                "enable WFIRMA_SYNC_CUSTOMERS_ALLOWED to apply",
            ],
        })

    apply_result = wfsync.apply_plan(plan)
    response["applied_count"] = apply_result["applied_count"]
    response["rejected_blank"] = apply_result["rejected_blank"]
    return JSONResponse(response)


# ── B0 (MDOC-cache) — review-and-assign layer for customers ───────────────────
#
# Mirrors the suppliers/sync-from-wfirma/{preview,apply} pair so the dashboard
# can render a per-row review table for Customer Master too. The underlying
# data model (wfirma_customers) is unchanged; only KYC-free identity fields
# (client_name, wfirma_customer_id, vat_id, country) are touched. No shipping,
# carrier, or invoice data is mutated.

_CM_STATUS_MATCHED_EXISTING      = "matched_existing"
_CM_STATUS_NEW_CANDIDATE         = "new_candidate"
_CM_STATUS_NEEDS_OPERATOR_REVIEW = "needs_operator_review"
_CM_STATUS_SKIPPED_INVALID       = "skipped_invalid"


def _plan_to_customer_proposals(plan: dict) -> List[dict]:
    """Flatten plan_sync() output into a stable proposal list for the UI.

    Returned items always contain:
      wfirma_id, name, vat_id, country, email, status, proposed_action,
      reason, local_name, local_wfirma_id.

    No DB writes; no wFirma call. Pure projection."""
    out: List[dict] = []
    def _row(entry, status, action, reason):
        return {
            "wfirma_id":       (entry.get("wfirma_customer_id") or "").strip(),
            "name":            entry.get("client_name") or "",
            "vat_id":          entry.get("vat_id") or "",
            "country":         entry.get("country") or "",
            "email":           None,  # wFirma client does not surface email yet
            "status":          status,
            "proposed_action": action,
            "reason":          reason,
            "local_name":      entry.get("local_client_name"),
            "local_wfirma_id": entry.get("local_wfirma_id"),
        }
    for e in plan.get("update_match", []) or []:
        out.append(_row(e, _CM_STATUS_MATCHED_EXISTING, "update", "wfirma_id_match"))
    for e in plan.get("update_fill", []) or []:
        out.append(_row(e, _CM_STATUS_NEEDS_OPERATOR_REVIEW, "backfill", "name_match_missing_wfirma_id"))
    for e in plan.get("conflict", []) or []:
        out.append(_row(e, _CM_STATUS_NEEDS_OPERATOR_REVIEW, "manual", e.get("reason") or "conflict"))
    for e in plan.get("insert", []) or []:
        out.append(_row(e, _CM_STATUS_NEW_CANDIDATE, "insert", "no_local_match"))
    # plan.get('skip_count') / plan.get('skipped_invalid') are counts, not rows
    return out


@router.get("/customers/sync-from-wfirma/preview", dependencies=[_auth],
            summary="Per-row review proposals for wFirma → Customer Master (no write)")
def customer_master_sync_preview() -> JSONResponse:
    """Read wFirma contractors and surface per-row proposals for the
    Customer Master review table. No write. Same status enum as suppliers."""
    try:
        plan = wfsync.plan_sync()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"ok": False, "status": "fetch_failed",
                    "error": f"{type(exc).__name__}: {exc}"},
        )
    proposals = _plan_to_customer_proposals(plan)
    return JSONResponse({
        "ok":         True,
        "mode":       "preview",
        "fetched":    plan["total_remote"],
        "proposals":  proposals,
    })


@router.post("/customers/sync-from-wfirma/apply", dependencies=[_auth],
             summary="Apply only the wFirma customer rows the operator selected")
async def customer_master_sync_apply(request: Request) -> JSONResponse:
    """Per-row apply for Customer Master. Body: ``{"wfirma_ids": [...]}``.

    Only the requested ids are written. Flag-gated by
    ``WFIRMA_SYNC_CUSTOMERS_ALLOWED``. Writes only identity fields
    (client_name, wfirma_customer_id, vat_id, country, match_status); KYC,
    shipping addresses, carrier accounts, and invoice settings are NEVER
    touched here."""
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Body must be a JSON object")
    wfirma_ids = body.get("wfirma_ids")
    if not isinstance(wfirma_ids, list) or not wfirma_ids:
        raise HTTPException(status_code=422,
                            detail="wfirma_ids must be a non-empty list of strings")
    if not all(isinstance(x, str) for x in wfirma_ids):
        raise HTTPException(status_code=422, detail="wfirma_ids must be a list of strings")

    if not settings.wfirma_sync_customers_allowed:
        return JSONResponse({
            "ok":               False,
            "mode":             "blocked",
            "dry_run":          True,
            "applied_count":    0,
            "blocking_reasons": [
                "wfirma_sync_customers_allowed is false — operator must "
                "enable WFIRMA_SYNC_CUSTOMERS_ALLOWED to apply"
            ],
        })

    try:
        plan = wfsync.plan_sync()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"ok": False, "status": "fetch_failed",
                    "error": f"{type(exc).__name__}: {exc}"},
        )

    requested = set(wfirma_ids)

    def _filter(entries):
        return [e for e in (entries or [])
                if (e.get("wfirma_customer_id") or "").strip() in requested]

    filtered_plan = {
        "insert":       _filter(plan.get("insert")),
        "update_fill":  _filter(plan.get("update_fill")),
        "update_match": _filter(plan.get("update_match")),
        "conflict":     [],  # conflicts are never auto-applied
    }
    apply_result = wfsync.apply_plan(filtered_plan)

    # Proposals returned to caller are the filtered subset for transparency.
    all_proposals = _plan_to_customer_proposals(plan)
    filtered_proposals = [p for p in all_proposals if p["wfirma_id"] in requested]

    return JSONResponse({
        "ok":             True,
        "mode":           "write",
        "fetched":        plan["total_remote"],
        "applied_count":  apply_result["applied_count"],
        "rejected_blank": apply_result["rejected_blank"],
        "proposals":      filtered_proposals,
    })


# ── C25A — Setup-detail endpoint (read-only) ─────────────────────────────────
#
# Operator-facing setup detail for a shipment batch.  Combines:
#   * Per-product detail of missing wFirma product registrations.
#   * Per-customer detail of mapping status against wFirma + Customer Master.
#   * Readiness split: "can prepare proforma" vs "can post to wFirma".
#
# Authority rules:
#   * READ-ONLY.  Calls no wFirma write paths.  Never inserts/updates DB rows.
#   * Mirrors the existing dashboard `proforma-readiness` payload but adds
#     per-row detail so the operator can see exactly which products and
#     customers need setup before posting.
#   * `create_flag_on` fields reflect WFIRMA_CREATE_PRODUCT_ALLOWED /
#     WFIRMA_CREATE_CUSTOMER_ALLOWED config defaults (both False by default).
#     The frontend MUST hide write buttons when these flags are False.


def split_import_vs_sales_blockers(
    *,
    client_names: list,
    unresolved_customers: list,
    products_missing_count: int,
    wfirma_create_pz_allowed: bool,
    batch_lifecycle: str,
) -> dict:
    """Authority split for the setup-detail readiness panel.

    IMPORT PZ / wFirma goods receipt is governed by IMPORT authority ONLY:
    mapped products, warehouse receipt (stock authority), and the
    ``WFIRMA_CREATE_PZ_ALLOWED`` fiscal gate. SALES preparation prerequisites
    (proforma drafts, customer/contractor mapping) are DOWNSTREAM sales
    authority — they gate proforma *preparation*, never the import PZ.

    Prior behaviour folded the sales prep blockers into the posting list, which
    wrongly blocked the import PZ on AWB 9158478722 whenever a proforma draft or
    customer mapping was missing. Imported goods may sit in inventory before
    being sold, so sales linkage must be advisory (visible, never blocking) for
    the import PZ.

    Returns the readiness sub-dict (prep/post/advisory lists + the two
    derived booleans). Pure function — no I/O — so the authority contract is
    unit-testable without seeding every backing DB.
    """
    prep_blockers: list = []          # SALES (proforma) preparation authority
    if not client_names:
        prep_blockers.append("no proforma drafts exist for this batch")
    if unresolved_customers:
        prep_blockers.append(
            "{0} customer(s) unmapped: ".format(len(unresolved_customers))
            + ", ".join(d["client_name"] for d in unresolved_customers[:3])
            + ("..." if len(unresolved_customers) > 3 else "")
        )

    # IMPORT PZ posting prerequisites — fiscal/customs gates ONLY. Sales prep is
    # intentionally NOT folded in here (that fold was the AWB 9158478722 bug).
    post_blockers: list = []          # IMPORT PZ / wFirma goods-receipt authority
    if products_missing_count > 0:
        post_blockers.append(
            "{0} product code(s) unmapped in wFirma".format(products_missing_count)
        )
    if not wfirma_create_pz_allowed:
        post_blockers.append("WFIRMA_CREATE_PZ_ALLOWED is False (admin flag)")
    if batch_lifecycle in ("DHL_TRANSIT", "PRE_IMPORT"):
        post_blockers.append("warehouse scan-in not yet performed (transit)")
    elif batch_lifecycle == "UNKNOWN":
        # Fail closed: lifecycle defaults to "UNKNOWN" in the response skeleton
        # and stays there when inventory_batch_state cannot determine the batch
        # (exception or no rows). Warehouse receipt is unconfirmed, so do NOT
        # report import-PZ posting readiness — this is a warehouse/stock
        # authority gate, not a sales gate.
        post_blockers.append("warehouse receipt not confirmed (inventory state unknown)")

    return {
        "blockers_for_preparation": prep_blockers,
        "blockers_for_posting":     post_blockers,
        # Sales linkage is advisory for the import PZ: visible, never blocking.
        "sales_linkage_advisory":   list(prep_blockers),
        "can_prepare_proforma":     not prep_blockers,
        "can_post_to_wfirma":       not post_blockers,
    }


@router.get("/shipment/{batch_id:path}/setup-detail", dependencies=[_auth])
def shipment_setup_detail(batch_id: str) -> JSONResponse:
    """READ-ONLY operator setup detail for products + customers + readiness."""
    if ".." in batch_id or batch_id.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    from ..core.config import settings as _s
    from ..services import wfirma_db as _wfdb
    from ..services import document_db as _ddb
    from ..services import customer_master_db as _cmdb
    from ..services import proforma_invoice_link_db as _pildb
    from pathlib import Path as _Path

    out: dict = {
        "batch_id": batch_id,
        "products": {
            "missing":        [],
            "mapped_count":   0,
            "missing_count":  0,
            "create_flag_on": bool(getattr(_s, "wfirma_create_product_allowed", False)),
        },
        "customers": {
            "details":        [],
            "create_flag_on": bool(getattr(_s, "wfirma_create_customer_allowed", False)),
        },
        "readiness": {
            "can_prepare_proforma":       False,
            "can_post_to_wfirma":         False,
            "blockers_for_preparation":   [],
            "blockers_for_posting":       [],
            "sales_linkage_advisory":     [],
            "purchase_transit_count":     0,
            "batch_lifecycle":            "UNKNOWN",
        },
        "errors": [],
    }

    # Products: missing rows with line context.
    #
    # C25A-DATA-FIX (2026-05-20): switched from query_sales_to_wfirma to
    # get_invoice_lines_for_batch as the authoritative product source.
    # Reason: query_sales_to_wfirma reads a TEMP VIEW (v_sales_to_wfirma)
    # whose left-join on packing.packing_lines returns 0 rows for batches
    # where the sales-side and purchase-side design_no patterns differ.
    # invoice_lines is the canonical product authority for the batch — it
    # is what the existing /dashboard/batches/{batch}/proforma-readiness
    # endpoint uses, and the two endpoints must agree on product counts.
    try:
        invoice_rows = _ddb.get_invoice_lines_for_batch(batch_id) or []
    except Exception as exc:
        invoice_rows = []
        out["errors"].append("invoice_lines read failed: " + str(exc))

    # Best-effort design_no + item_type enrichment from packing_lines
    # (per-product first-match within the batch).  Same batch_id scope; no
    # cross-batch leakage.  If packing_db is unavailable, fall back to
    # invoice-line description as the descriptive label.
    pl_by_code: dict = {}
    try:
        from ..services import packing_db as _pdb
        if _pdb._db_path is not None:
            pl_rows = _pdb.get_packing_lines_for_batch(batch_id) or []
            for pl in pl_rows:
                pc = (pl.get("product_code") or "").strip()
                if pc and pc not in pl_by_code:
                    pl_by_code[pc] = pl
    except Exception as exc:
        out["errors"].append("packing_lines enrichment failed: " + str(exc))

    # Best-effort client_name attribution per product_code from
    # sales_packing_lines (same batch).  Allows the panel to show which
    # operator-owned client is waiting on each product registration.
    spl_client_by_code: dict = {}
    try:
        if _ddb._db_path is not None:
            import sqlite3 as _sql
            with _sql.connect(str(_ddb._db_path)) as con:
                con.row_factory = _sql.Row
                spl_rows = con.execute(
                    "SELECT product_code, client_name FROM sales_packing_lines "
                    "WHERE batch_id=? AND product_code <> ''",
                    (batch_id,),
                ).fetchall()
                for r in spl_rows:
                    pc = (r["product_code"] or "").strip()
                    cn = (r["client_name"] or "").strip()
                    if pc and cn and pc not in spl_client_by_code:
                        spl_client_by_code[pc] = cn
    except Exception as exc:
        out["errors"].append("sales_packing_lines client lookup failed: " + str(exc))

    # Distinct product_codes from invoice_lines (authoritative).
    all_codes = sorted({
        (r.get("product_code") or "").strip()
        for r in invoice_rows
        if (r.get("product_code") or "").strip()
    })
    mapped_map = {}
    try:
        if all_codes:
            mapped_map = _wfdb.get_products_batch(all_codes) or {}
    except Exception as exc:
        out["errors"].append("wfirma_products lookup failed: " + str(exc))

    # Aggregate per product_code from invoice_lines (one entry per code).
    missing_acc: dict = {}
    mapped_count = 0
    seen_codes: set = set()
    for r in invoice_rows:
        pc = (r.get("product_code") or "").strip()
        if not pc:
            continue
        if pc in seen_codes:
            # Aggregate qty/value into existing entry (same code, multiple lines).
            if pc in missing_acc:
                try:
                    missing_acc[pc]["qty"] += float(r.get("quantity") or 0)
                except Exception:
                    pass
                try:
                    missing_acc[pc]["total_value"] += float(r.get("total_value") or 0)
                except Exception:
                    pass
            continue
        seen_codes.add(pc)
        prod = mapped_map.get(pc) or {}
        is_mapped = bool(prod.get("wfirma_product_id")) and (prod.get("sync_status") == "matched")
        if is_mapped:
            mapped_count += 1
            continue
        pl = pl_by_code.get(pc) or {}
        missing_acc[pc] = {
            "product_code":  pc,
            "design_no":     (pl.get("design_no") or "").strip() or None,
            "item_type":     (pl.get("item_type") or "").strip() or None,
            "qty":           float(r.get("quantity") or 0),
            "total_value":   float(r.get("total_value") or 0),
            "currency":      (r.get("currency") or "").strip() or None,
            "draft_id":      None,  # not derivable from invoice_lines
            "client_name":   spl_client_by_code.get(pc) or None,
            "description":   (r.get("description") or "").strip() or None,
        }

    out["products"]["mapped_count"]  = mapped_count
    out["products"]["missing_count"] = len(missing_acc)
    out["products"]["missing"]       = sorted(missing_acc.values(), key=lambda x: x["product_code"])

    # Customers: per-client status + action_needed
    try:
        cm_db_path = _Path(_s.storage_root) / "customer_master.sqlite"
        cm_rows = _cmdb.list_customers(cm_db_path, limit=10000)
    except Exception as exc:
        cm_rows = []
        out["errors"].append("customer_master read failed: " + str(exc))
    cm_by_name_lower = {(c.bill_to_name or "").strip().lower(): c for c in cm_rows if c.bill_to_name}

    client_names: list = []
    try:
        pildb_path = _Path(_s.storage_root) / "proforma_links.db"
        drafts = _pildb.list_drafts_for_batch(pildb_path, batch_id) or []
        seen = set()
        for d in drafts:
            cn = getattr(d, "client_name", None) or (d.get("client_name") if isinstance(d, dict) else None)
            if cn and cn not in seen:
                client_names.append(cn)
                seen.add(cn)
    except Exception as exc:
        out["errors"].append("proforma_drafts read failed: " + str(exc))

    for cn in client_names:
        try:
            wf = _wfdb.get_customer_by_name(cn) if hasattr(_wfdb, "get_customer_by_name") else None
        except Exception:
            wf = None
        wfirma_id = (wf or {}).get("wfirma_customer_id") if isinstance(wf, dict) else None

        cm_rec = cm_by_name_lower.get(cn.lower())
        cm_present = bool(cm_rec)
        cm_bill_to_name = cm_rec.bill_to_name if cm_rec else None

        if wfirma_id:
            status = "matched"
            action = "none"
        elif cm_present and getattr(cm_rec, "bill_to_contractor_id", None):
            status = "matched"
            action = "refresh_resolver_cache"
        elif not cm_present:
            status = "unmapped"
            action = "add_to_cm"
        else:
            cm_has_wfid = bool(getattr(cm_rec, "bill_to_contractor_id", None))
            if cm_has_wfid:
                status = "matched"
                action = "fix_name_alias"
            else:
                status = "unmapped"
                action = "create_in_wfirma"

        out["customers"]["details"].append({
            "client_name":          cn,
            "status":               status,
            "wfirma_customer_id":   wfirma_id or (getattr(cm_rec, "bill_to_contractor_id", None) if cm_rec else None),
            "cm_record_present":    cm_present,
            "cm_bill_to_name":      cm_bill_to_name,
            "action_needed":        action,
        })

    # Readiness split
    try:
        from ..services import inventory_batch_state as _ibs
        inv = _ibs.get_batch_state(batch_id) or {}
        out["readiness"]["purchase_transit_count"] = int(
            (inv.get("counts") or {}).get("PURCHASE_TRANSIT", 0)
        )
        if inv.get("synthetic"):
            out["readiness"]["batch_lifecycle"] = "DHL_TRANSIT"
        elif out["readiness"]["purchase_transit_count"] > 0:
            out["readiness"]["batch_lifecycle"] = "PRE_IMPORT"
        else:
            wh = sum(v for k, v in (inv.get("counts") or {}).items() if k == "WAREHOUSE_STOCK")
            if wh > 0:
                out["readiness"]["batch_lifecycle"] = "WAREHOUSE_STOCK"
    except Exception as exc:
        out["errors"].append("inventory_batch_state read failed: " + str(exc))

    # Authority split (Lesson I — workflow-class fix): IMPORT PZ readiness is
    # governed by import authority only (products + warehouse receipt + fiscal
    # gate); SALES prep (proforma drafts + customer mapping) is downstream and
    # advisory. See split_import_vs_sales_blockers() for the full rationale.
    unresolved_customers = [d for d in out["customers"]["details"] if d["status"] == "unmapped"]
    out["readiness"].update(
        split_import_vs_sales_blockers(
            client_names             = client_names,
            unresolved_customers     = unresolved_customers,
            products_missing_count   = out["products"]["missing_count"],
            wfirma_create_pz_allowed = bool(getattr(_s, "wfirma_create_pz_allowed", False)),
            batch_lifecycle          = out["readiness"]["batch_lifecycle"],
        )
    )

    return JSONResponse(out)
