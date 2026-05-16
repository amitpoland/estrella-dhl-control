"""
routes_master_data.py — Master Data B5 REST API.

Three local-only entities sharing one SQLite file:
  /api/v1/hs-codes/        — HS code registry (PK = hs_code)
  /api/v1/units/           — Unit of measure registry (PK = code)
  /api/v1/product-local/   — Local augmentation of wFirma products (PK = product_code)

All endpoints X-API-Key authenticated. Pure local CRUD — does NOT call wFirma,
does NOT participate in PZ/customs/landed-cost calculation, does NOT modify
any pre-existing schema.

Note: PUT is the upsert verb for natural-keyed entities (hs-codes, units,
product-local). This mirrors customer-master semantics and avoids a separate
"create vs update" decision at the UI layer.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from ..core.config import settings
from ..core.security import require_api_key
from ..core.logging import get_logger
from ..services.master_data_db import (
    HsCode, Unit, ProductLocal,
    init_db,
    validate_hs_code, upsert_hs_code, get_hs_code, list_hs_codes, delete_hs_code,
    validate_unit, upsert_unit, get_unit, list_units, delete_unit,
    validate_product_local, upsert_product_local, get_product_local,
    list_product_local, delete_product_local,
)

log    = get_logger(__name__)
_auth  = Depends(require_api_key)
_DB_PATH = settings.storage_root / "master_data.sqlite"


def _parse_active(v: Optional[str]) -> Optional[bool]:
    if v is None or v == "":
        return None
    s = str(v).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    raise HTTPException(status_code=422, detail=f"active must be true/false, got {v!r}")


# ══════════════════════════════════════════════════════════════════════════════
# HS Codes
# ══════════════════════════════════════════════════════════════════════════════

hs_router = APIRouter(prefix="/api/v1/hs-codes", tags=["master-data"])


def _hs_dict(h: HsCode) -> dict:
    return {
        "hs_code": h.hs_code, "description_pl": h.description_pl,
        "description_en": h.description_en, "duty_rate_pct": h.duty_rate_pct,
        "vat_rate_pct": h.vat_rate_pct, "active": h.active, "notes": h.notes,
        "created_at": h.created_at, "updated_at": h.updated_at,
    }


@hs_router.get("/", dependencies=[_auth], summary="List HS codes")
def list_hs_endpoint(active: Optional[str] = Query(None),
                    limit: int = Query(500, ge=1, le=2000)) -> JSONResponse:
    try:
        init_db(_DB_PATH)
        recs = list_hs_codes(_DB_PATH, active=_parse_active(active), limit=limit)
    except HTTPException:
        raise
    except Exception as exc:
        log.error("list_hs_codes failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse({"count": len(recs), "hs_codes": [_hs_dict(h) for h in recs]})


@hs_router.get("/{hs_code}", dependencies=[_auth], summary="Get HS code")
def get_hs_endpoint(hs_code: str) -> JSONResponse:
    init_db(_DB_PATH)
    rec = get_hs_code(_DB_PATH, hs_code)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"HS code not found: {hs_code}")
    return JSONResponse(_hs_dict(rec))


@hs_router.put("/{hs_code}", dependencies=[_auth], summary="Upsert HS code")
async def upsert_hs_endpoint(hs_code: str, request: Request) -> JSONResponse:
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    body = dict(body)
    body["hs_code"] = hs_code
    errs = validate_hs_code(body)
    if errs:
        raise HTTPException(status_code=422, detail={"validation_errors": errs})
    try:
        rec = upsert_hs_code(_DB_PATH, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("upsert_hs_code failed code=%s: %s", hs_code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse(_hs_dict(rec))


@hs_router.delete("/{hs_code}", dependencies=[_auth], summary="Delete HS code",
                  status_code=204)
def delete_hs_endpoint(hs_code: str) -> Response:
    init_db(_DB_PATH)
    if not delete_hs_code(_DB_PATH, hs_code):
        raise HTTPException(status_code=404, detail=f"HS code not found: {hs_code}")
    return Response(status_code=204)


# ══════════════════════════════════════════════════════════════════════════════
# Units
# ══════════════════════════════════════════════════════════════════════════════

units_router = APIRouter(prefix="/api/v1/units", tags=["master-data"])


def _unit_dict(u: Unit) -> dict:
    return {
        "code": u.code, "name_pl": u.name_pl, "name_en": u.name_en,
        "unit_type": u.unit_type, "active": u.active,
        "created_at": u.created_at, "updated_at": u.updated_at,
    }


@units_router.get("/", dependencies=[_auth], summary="List units")
def list_units_endpoint(active: Optional[str] = Query(None),
                       limit: int = Query(200, ge=1, le=1000)) -> JSONResponse:
    try:
        init_db(_DB_PATH)
        recs = list_units(_DB_PATH, active=_parse_active(active), limit=limit)
    except HTTPException:
        raise
    except Exception as exc:
        log.error("list_units failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse({"count": len(recs), "units": [_unit_dict(u) for u in recs]})


@units_router.get("/{code}", dependencies=[_auth], summary="Get unit")
def get_unit_endpoint(code: str) -> JSONResponse:
    init_db(_DB_PATH)
    rec = get_unit(_DB_PATH, code)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Unit not found: {code}")
    return JSONResponse(_unit_dict(rec))


@units_router.put("/{code}", dependencies=[_auth], summary="Upsert unit")
async def upsert_unit_endpoint(code: str, request: Request) -> JSONResponse:
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    body = dict(body)
    body["code"] = code
    errs = validate_unit(body)
    if errs:
        raise HTTPException(status_code=422, detail={"validation_errors": errs})
    try:
        rec = upsert_unit(_DB_PATH, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("upsert_unit failed code=%s: %s", code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse(_unit_dict(rec))


@units_router.delete("/{code}", dependencies=[_auth], summary="Delete unit",
                     status_code=204)
def delete_unit_endpoint(code: str) -> Response:
    init_db(_DB_PATH)
    if not delete_unit(_DB_PATH, code):
        raise HTTPException(status_code=404, detail=f"Unit not found: {code}")
    return Response(status_code=204)


# ══════════════════════════════════════════════════════════════════════════════
# Product Local Augmentation
# ══════════════════════════════════════════════════════════════════════════════

pl_router = APIRouter(prefix="/api/v1/product-local", tags=["master-data"])


def _pl_dict(p: ProductLocal) -> dict:
    return {
        "product_code": p.product_code, "hs_code_override": p.hs_code_override,
        "unit_override": p.unit_override, "design_code_link": p.design_code_link,
        "notes": p.notes, "created_at": p.created_at, "updated_at": p.updated_at,
    }


@pl_router.get("/", dependencies=[_auth], summary="List product local augmentations")
def list_pl_endpoint(limit: int = Query(500, ge=1, le=2000)) -> JSONResponse:
    try:
        init_db(_DB_PATH)
        recs = list_product_local(_DB_PATH, limit=limit)
    except Exception as exc:
        log.error("list_product_local failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse({"count": len(recs), "items": [_pl_dict(p) for p in recs]})


@pl_router.get("/{product_code}", dependencies=[_auth], summary="Get product augmentation")
def get_pl_endpoint(product_code: str) -> JSONResponse:
    init_db(_DB_PATH)
    rec = get_product_local(_DB_PATH, product_code)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"product-local not found: {product_code}")
    return JSONResponse(_pl_dict(rec))


@pl_router.put("/{product_code}", dependencies=[_auth], summary="Upsert product augmentation")
async def upsert_pl_endpoint(product_code: str, request: Request) -> JSONResponse:
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    body = dict(body)
    body["product_code"] = product_code
    errs = validate_product_local(body)
    if errs:
        raise HTTPException(status_code=422, detail={"validation_errors": errs})
    try:
        rec = upsert_product_local(_DB_PATH, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("upsert_product_local failed code=%s: %s", product_code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse(_pl_dict(rec))


@pl_router.delete("/{product_code}", dependencies=[_auth], summary="Delete product augmentation",
                  status_code=204)
def delete_pl_endpoint(product_code: str) -> Response:
    init_db(_DB_PATH)
    if not delete_product_local(_DB_PATH, product_code):
        raise HTTPException(status_code=404, detail=f"product-local not found: {product_code}")
    return Response(status_code=204)
