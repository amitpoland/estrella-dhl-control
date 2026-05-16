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
    HsCode, Unit, ProductLocal, Incoterm, VatConfig, FxRate, CarrierConfig, Design,
    init_db,
    validate_hs_code, upsert_hs_code, get_hs_code, list_hs_codes, delete_hs_code,
    validate_unit, upsert_unit, get_unit, list_units, delete_unit,
    validate_product_local, upsert_product_local, get_product_local,
    list_product_local, delete_product_local,
    validate_incoterm, upsert_incoterm, get_incoterm, list_incoterms, delete_incoterm,
    validate_vat_config, create_vat_config, get_vat_config, list_vat_config,
    update_vat_config, delete_vat_config,
    validate_fx_rate, create_fx_rate, get_fx_rate, list_fx_rates,
    update_fx_rate, delete_fx_rate,
    validate_carrier_config, upsert_carrier_config, get_carrier_config,
    list_carrier_configs, delete_carrier_config,
    validate_design, upsert_design, get_design, list_designs, delete_design,
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


# ══════════════════════════════════════════════════════════════════════════════
# B7 — Incoterms
# ══════════════════════════════════════════════════════════════════════════════

incoterms_router = APIRouter(prefix="/api/v1/incoterms", tags=["master-data"])


def _incoterm_dict(i: Incoterm) -> dict:
    return {
        "code": i.code, "name": i.name,
        "risk_transfer_point": i.risk_transfer_point,
        "freight_included": i.freight_included,
        "insurance_included": i.insurance_included,
        "customs_included": i.customs_included,
        "notes": i.notes, "active": i.active,
        "created_at": i.created_at, "updated_at": i.updated_at,
    }


@incoterms_router.get("/", dependencies=[_auth], summary="List incoterms")
def list_incoterms_endpoint(active: Optional[str] = Query(None),
                            limit: int = Query(100, ge=1, le=1000)) -> JSONResponse:
    try:
        init_db(_DB_PATH)
        recs = list_incoterms(_DB_PATH, active=_parse_active(active), limit=limit)
    except HTTPException:
        raise
    except Exception as exc:
        log.error("list_incoterms failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse({"count": len(recs), "incoterms": [_incoterm_dict(i) for i in recs]})


@incoterms_router.get("/{code}", dependencies=[_auth], summary="Get incoterm")
def get_incoterm_endpoint(code: str) -> JSONResponse:
    init_db(_DB_PATH)
    rec = get_incoterm(_DB_PATH, code)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Incoterm not found: {code}")
    return JSONResponse(_incoterm_dict(rec))


@incoterms_router.put("/{code}", dependencies=[_auth], summary="Upsert incoterm")
async def upsert_incoterm_endpoint(code: str, request: Request) -> JSONResponse:
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    body = dict(body); body["code"] = code
    errs = validate_incoterm(body)
    if errs:
        raise HTTPException(status_code=422, detail={"validation_errors": errs})
    try:
        rec = upsert_incoterm(_DB_PATH, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("upsert_incoterm failed code=%s: %s", code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse(_incoterm_dict(rec))


@incoterms_router.delete("/{code}", dependencies=[_auth], summary="Delete incoterm",
                         status_code=204)
def delete_incoterm_endpoint(code: str) -> Response:
    init_db(_DB_PATH)
    if not delete_incoterm(_DB_PATH, code):
        raise HTTPException(status_code=404, detail=f"Incoterm not found: {code}")
    return Response(status_code=204)


# ══════════════════════════════════════════════════════════════════════════════
# B7 — VAT Config  (READ-ONLY w.r.t. wFirma invoice path)
# ══════════════════════════════════════════════════════════════════════════════

vat_router = APIRouter(prefix="/api/v1/vat-config", tags=["master-data"])


def _vat_dict(v: VatConfig) -> dict:
    return {
        "id": v.id, "country": v.country, "product_type": v.product_type,
        "rate_pct": v.rate_pct, "rate_code": v.rate_code,
        "effective_from": v.effective_from, "effective_to": v.effective_to,
        "active": v.active, "notes": v.notes,
        "created_at": v.created_at, "updated_at": v.updated_at,
    }


@vat_router.get("/", dependencies=[_auth], summary="List VAT config entries")
def list_vat_endpoint(country: Optional[str] = Query(None),
                     active: Optional[str] = Query(None),
                     limit: int = Query(500, ge=1, le=2000)) -> JSONResponse:
    try:
        init_db(_DB_PATH)
        recs = list_vat_config(_DB_PATH, country=country,
                              active=_parse_active(active), limit=limit)
    except HTTPException:
        raise
    except Exception as exc:
        log.error("list_vat_config failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse({"count": len(recs), "vat_config": [_vat_dict(v) for v in recs]})


@vat_router.get("/{vat_id}", dependencies=[_auth], summary="Get VAT entry")
def get_vat_endpoint(vat_id: int) -> JSONResponse:
    init_db(_DB_PATH)
    rec = get_vat_config(_DB_PATH, vat_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"VAT config not found: {vat_id}")
    return JSONResponse(_vat_dict(rec))


@vat_router.post("/", dependencies=[_auth], summary="Create VAT entry", status_code=201)
async def create_vat_endpoint(request: Request) -> JSONResponse:
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    errs = validate_vat_config(body)
    if errs:
        raise HTTPException(status_code=422, detail={"validation_errors": errs})
    try:
        rec = create_vat_config(_DB_PATH, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("create_vat_config failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse(status_code=201, content=_vat_dict(rec))


@vat_router.put("/{vat_id}", dependencies=[_auth], summary="Update VAT entry")
async def update_vat_endpoint(vat_id: int, request: Request) -> JSONResponse:
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    try:
        rec = update_vat_config(_DB_PATH, vat_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("update_vat_config failed id=%s: %s", vat_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    if rec is None:
        raise HTTPException(status_code=404, detail=f"VAT config not found: {vat_id}")
    return JSONResponse(_vat_dict(rec))


@vat_router.delete("/{vat_id}", dependencies=[_auth], summary="Delete VAT entry",
                  status_code=204)
def delete_vat_endpoint(vat_id: int) -> Response:
    init_db(_DB_PATH)
    if not delete_vat_config(_DB_PATH, vat_id):
        raise HTTPException(status_code=404, detail=f"VAT config not found: {vat_id}")
    return Response(status_code=204)


# ══════════════════════════════════════════════════════════════════════════════
# B8 — FX Rates (REFERENCE-ONLY; not a PZ override path)
# ══════════════════════════════════════════════════════════════════════════════
#
# The PZ landed-cost / customs calculation engine consumes NBP rates live; this
# table is a pure reference / observation store for the operator. CRUD is local
# and additive. **No code in the PZ engine reads from this table** — write
# integration with the calculation path is explicitly FORBIDDEN by the campaign
# hard rules (see master-data-campaign.md MDC-071).

fx_router = APIRouter(prefix="/api/v1/fx-rates", tags=["master-data"])


def _fx_dict(f: FxRate) -> dict:
    return {
        "id": f.id, "rate_date": f.rate_date,
        "from_currency": f.from_currency, "to_currency": f.to_currency,
        "rate": f.rate, "source": f.source, "table_number": f.table_number,
        "notes": f.notes, "active": f.active,
        "created_at": f.created_at, "updated_at": f.updated_at,
    }


@fx_router.get("/", dependencies=[_auth], summary="List FX rate observations")
def list_fx_endpoint(from_currency: Optional[str] = Query(None),
                    to_currency: Optional[str] = Query(None),
                    rate_date: Optional[str] = Query(None),
                    active: Optional[str] = Query(None),
                    limit: int = Query(500, ge=1, le=2000)) -> JSONResponse:
    try:
        init_db(_DB_PATH)
        recs = list_fx_rates(_DB_PATH, from_currency=from_currency,
                             to_currency=to_currency, rate_date=rate_date,
                             active=_parse_active(active), limit=limit)
    except HTTPException:
        raise
    except Exception as exc:
        log.error("list_fx_rates failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse({"count": len(recs), "fx_rates": [_fx_dict(r) for r in recs]})


@fx_router.get("/{fx_id}", dependencies=[_auth], summary="Get FX rate entry")
def get_fx_endpoint(fx_id: int) -> JSONResponse:
    init_db(_DB_PATH)
    rec = get_fx_rate(_DB_PATH, fx_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"FX rate not found: {fx_id}")
    return JSONResponse(_fx_dict(rec))


@fx_router.post("/", dependencies=[_auth], summary="Create FX rate observation",
               status_code=201)
async def create_fx_endpoint(request: Request) -> JSONResponse:
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    errs = validate_fx_rate(body)
    if errs:
        raise HTTPException(status_code=422, detail={"validation_errors": errs})
    try:
        rec = create_fx_rate(_DB_PATH, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("create_fx_rate failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse(status_code=201, content=_fx_dict(rec))


@fx_router.put("/{fx_id}", dependencies=[_auth], summary="Update FX rate entry")
async def update_fx_endpoint(fx_id: int, request: Request) -> JSONResponse:
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    try:
        rec = update_fx_rate(_DB_PATH, fx_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("update_fx_rate failed id=%s: %s", fx_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    if rec is None:
        raise HTTPException(status_code=404, detail=f"FX rate not found: {fx_id}")
    return JSONResponse(_fx_dict(rec))


@fx_router.delete("/{fx_id}", dependencies=[_auth], summary="Delete FX rate entry",
                 status_code=204)
def delete_fx_endpoint(fx_id: int) -> Response:
    init_db(_DB_PATH)
    if not delete_fx_rate(_DB_PATH, fx_id):
        raise HTTPException(status_code=404, detail=f"FX rate not found: {fx_id}")
    return Response(status_code=204)


# ══════════════════════════════════════════════════════════════════════════════
# B9 — Carrier Configuration (LOCAL, NON-SECRET only)
# ══════════════════════════════════════════════════════════════════════════════
#
# Registers operator-facing carrier descriptions: code, name, parser, inbox,
# api_type, supported services. Does NOT store credentials — those stay in
# .env. Does NOT mutate any DHL/FedEx/UPS live integration. Does NOT touch
# the shipment carrier runtime. Pure local documentation table.

carriers_config_router = APIRouter(prefix="/api/v1/carriers-config", tags=["master-data"])


def _carrier_dict(c: CarrierConfig) -> dict:
    return {
        "carrier_code": c.carrier_code, "name": c.name,
        "parser_type": c.parser_type, "inbox_email": c.inbox_email,
        "api_type": c.api_type, "supported_services": c.supported_services,
        "notes": c.notes, "active": c.active,
        "created_at": c.created_at, "updated_at": c.updated_at,
    }


@carriers_config_router.get("/", dependencies=[_auth], summary="List carrier configs")
def list_carriers_endpoint(active: Optional[str] = Query(None),
                          limit: int = Query(100, ge=1, le=1000)) -> JSONResponse:
    try:
        init_db(_DB_PATH)
        recs = list_carrier_configs(_DB_PATH, active=_parse_active(active), limit=limit)
    except HTTPException:
        raise
    except Exception as exc:
        log.error("list_carrier_configs failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse({"count": len(recs),
                         "carriers": [_carrier_dict(c) for c in recs]})


@carriers_config_router.get("/{carrier_code}", dependencies=[_auth],
                            summary="Get carrier config")
def get_carrier_endpoint(carrier_code: str) -> JSONResponse:
    init_db(_DB_PATH)
    rec = get_carrier_config(_DB_PATH, carrier_code)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Carrier config not found: {carrier_code}")
    return JSONResponse(_carrier_dict(rec))


@carriers_config_router.put("/{carrier_code}", dependencies=[_auth],
                            summary="Upsert carrier config")
async def upsert_carrier_endpoint(carrier_code: str, request: Request) -> JSONResponse:
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    body = dict(body); body["carrier_code"] = carrier_code
    errs = validate_carrier_config(body)
    if errs:
        raise HTTPException(status_code=422, detail={"validation_errors": errs})
    try:
        rec = upsert_carrier_config(_DB_PATH, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("upsert_carrier_config failed code=%s: %s", carrier_code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse(_carrier_dict(rec))


@carriers_config_router.delete("/{carrier_code}", dependencies=[_auth],
                               summary="Delete carrier config", status_code=204)
def delete_carrier_endpoint(carrier_code: str) -> Response:
    init_db(_DB_PATH)
    if not delete_carrier_config(_DB_PATH, carrier_code):
        raise HTTPException(status_code=404, detail=f"Carrier config not found: {carrier_code}")
    return Response(status_code=204)


# ══════════════════════════════════════════════════════════════════════════════
# Designs — B-MD2 (MDOC-2026-05)
#
# Additive local master in master_data.sqlite. Soft references only — no SQL FK.
# product_identity_engine MUST NOT read this table. Pinned by a source-grep
# contract in test_master_data_hard_rules.py.
# ══════════════════════════════════════════════════════════════════════════════

designs_router = APIRouter(prefix="/api/v1/designs", tags=["master-data"])


def _design_dict(d: Design) -> dict:
    return {
        "design_code":   d.design_code,
        "display_name":  d.display_name,
        "product_ref":   d.product_ref,
        "design_family": d.design_family,
        "collection":    d.collection,
        "metal":         d.metal,
        "stone_summary": d.stone_summary,
        "hs_code":       d.hs_code,
        "unit":          d.unit,
        "active":        d.active,
        "notes":         d.notes,
        "created_at":    d.created_at,
        "updated_at":    d.updated_at,
    }


@designs_router.get("/", dependencies=[_auth], summary="List designs")
def list_designs_endpoint(active: Optional[str] = Query(None),
                          design_family: Optional[str] = Query(None),
                          collection: Optional[str] = Query(None),
                          limit: int = Query(500, ge=1, le=2000)) -> JSONResponse:
    init_db(_DB_PATH)
    try:
        recs = list_designs(_DB_PATH, active=_parse_active(active),
                            design_family=design_family, collection=collection,
                            limit=limit)
    except Exception as exc:
        log.error("list_designs failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse({"ok": True, "count": len(recs),
                         "designs": [_design_dict(d) for d in recs]})


@designs_router.get("/{design_code}", dependencies=[_auth], summary="Get design")
def get_design_endpoint(design_code: str) -> JSONResponse:
    init_db(_DB_PATH)
    rec = get_design(_DB_PATH, design_code)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Design not found: {design_code}")
    return JSONResponse(_design_dict(rec))


@designs_router.put("/{design_code}", dependencies=[_auth], summary="Upsert design")
async def upsert_design_endpoint(design_code: str, request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    body["design_code"] = design_code
    errs = validate_design(body)
    if errs:
        raise HTTPException(status_code=422, detail={"validation_errors": errs})
    try:
        rec = upsert_design(_DB_PATH, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("upsert_design failed code=%s: %s", design_code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse(_design_dict(rec))


@designs_router.delete("/{design_code}", dependencies=[_auth],
                        summary="Delete design", status_code=204)
def delete_design_endpoint(design_code: str) -> Response:
    init_db(_DB_PATH)
    if not delete_design(_DB_PATH, design_code):
        raise HTTPException(status_code=404, detail=f"Design not found: {design_code}")
    return Response(status_code=204)
