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
from ..core.audit import audit_safe, list_audit
from ..core.role_gate import (
    require_role_or_apikey, MASTER_ADMIN, MASTER_EDITOR,
)
from ..services.master_reference_checks import (
    ReferenceConflict, check_hs_code_active,
)
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
    # Phase 4B Wave 1 — soft-delete + restore primitives.
    soft_delete_hs_code,   restore_hs_code,   hard_delete_hs_code,
    soft_delete_unit,      restore_unit,      hard_delete_unit,
    soft_delete_incoterm,  restore_incoterm,  hard_delete_incoterm,
    soft_delete_vat_config, restore_vat_config, hard_delete_vat_config,
    soft_delete_fx_rate,   restore_fx_rate,   hard_delete_fx_rate,
    soft_delete_design,    restore_design,    hard_delete_design,
    # Phase 4B Wave 3a — carriers_config.
    soft_delete_carrier_config, restore_carrier_config, hard_delete_carrier_config,
    # Phase 4B Wave 4 — product_local.
    soft_delete_product_local, restore_product_local, hard_delete_product_local,
)

log    = get_logger(__name__)
_auth  = Depends(require_api_key)
# Phase 2 — role-gated write dependency. When master_role_enforcement is
# False (the default) this degrades to require_api_key, so attaching it
# to a route is a no-op until the flag flips.
_write_auth = Depends(require_role_or_apikey(MASTER_ADMIN, MASTER_EDITOR))
# Audit query gate — master_admin only when enforcement is enabled.
_audit_read_auth = Depends(require_role_or_apikey(MASTER_ADMIN))
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


def _resolve_list_active(v: Optional[str]) -> Optional[bool]:
    """Phase 4B Wave 1 — default list policy: omitted ``active`` → active-only.
    Explicit ``active=true`` or ``active=false`` overrides."""
    parsed = _parse_active(v)
    return True if parsed is None else parsed


import hmac as _hmac


def _hard_delete_guard(request: Request) -> None:
    """Phase 4B Wave 1 — guard for ``DELETE ...?hard=true`` on legacy
    Wave-1 entities. Identical contract to the jewelry guard in
    routes_master_jewelry.py — duplicated intentionally to avoid
    importing a private helper across route modules.

      1. ``settings.master_hard_delete_enabled`` must be True (else 409).
      2. Caller must hold master_admin authority:
           - direct admin X-API-Key, OR
           - session user with role == master_admin
         (else 403).
    """
    if not settings.master_hard_delete_enabled:
        raise HTTPException(
            status_code=409,
            detail=("Hard delete is disabled. Set master_hard_delete_enabled "
                    "to true (admin) to permit permanent removal."),
        )
    key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if settings.api_key and key and _hmac.compare_digest(key, settings.api_key):
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
        "deleted_at": h.deleted_at,
    }


@hs_router.get("/", dependencies=[_auth], summary="List HS codes")
def list_hs_endpoint(active: Optional[str] = Query(None,
        description="omit = active-only (default); 'false' = inactive only; 'true' = active only"),
                    limit: int = Query(500, ge=1, le=2000)) -> JSONResponse:
    try:
        init_db(_DB_PATH)
        recs = list_hs_codes(_DB_PATH, active=_resolve_list_active(active), limit=limit)
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


@hs_router.put("/{hs_code}", dependencies=[_write_auth], summary="Upsert HS code")
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
    init_db(_DB_PATH)
    before = get_hs_code(_DB_PATH, hs_code)
    try:
        rec = upsert_hs_code(_DB_PATH, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("upsert_hs_code failed code=%s: %s", hs_code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    audit_safe("hs_codes", "create" if before is None else "update", hs_code,
               request=request, before=before, after=rec)
    return JSONResponse(_hs_dict(rec))


@hs_router.delete("/{hs_code}", dependencies=[_write_auth],
                  summary="Delete HS code (soft-delete by default; ?hard=true for permanent)",
                  status_code=204)
def delete_hs_endpoint(
    hs_code: str, request: Request,
    hard: bool = Query(False, description="Permanent removal; requires master_admin + flag"),
) -> Response:
    init_db(_DB_PATH)
    before = get_hs_code(_DB_PATH, hs_code)
    if before is None:
        raise HTTPException(status_code=404, detail=f"HS code not found: {hs_code}")
    if hard:
        _hard_delete_guard(request)
        if not hard_delete_hs_code(_DB_PATH, hs_code):
            raise HTTPException(status_code=404, detail=f"HS code not found: {hs_code}")
        audit_safe("hs_codes", "hard_delete", hs_code,
                   request=request, before=before, after=None)
        return Response(status_code=204)
    if not soft_delete_hs_code(_DB_PATH, hs_code):
        raise HTTPException(status_code=404, detail=f"HS code not found: {hs_code}")
    audit_safe("hs_codes", "delete", hs_code,
               request=request, before=before, after=None)
    return Response(status_code=204)


@hs_router.post("/{hs_code}/restore", dependencies=[_write_auth],
                summary="Restore a soft-deleted HS code")
def restore_hs_endpoint(hs_code: str, request: Request) -> JSONResponse:
    init_db(_DB_PATH)
    before = get_hs_code(_DB_PATH, hs_code)
    if before is None:
        raise HTTPException(status_code=404, detail=f"HS code not found: {hs_code}")
    if not restore_hs_code(_DB_PATH, hs_code):
        raise HTTPException(status_code=404, detail=f"HS code not found: {hs_code}")
    after = get_hs_code(_DB_PATH, hs_code)
    audit_safe("hs_codes", "restore", hs_code,
               request=request, before=before, after=after)
    return JSONResponse(_hs_dict(after))


# ══════════════════════════════════════════════════════════════════════════════
# Units
# ══════════════════════════════════════════════════════════════════════════════

units_router = APIRouter(prefix="/api/v1/units", tags=["master-data"])


def _unit_dict(u: Unit) -> dict:
    return {
        "code": u.code, "name_pl": u.name_pl, "name_en": u.name_en,
        "unit_type": u.unit_type, "active": u.active,
        "created_at": u.created_at, "updated_at": u.updated_at,
        "deleted_at": u.deleted_at,
    }


@units_router.get("/", dependencies=[_auth], summary="List units")
def list_units_endpoint(active: Optional[str] = Query(None,
        description="omit = active-only (default); 'false' = inactive only; 'true' = active only"),
                       limit: int = Query(200, ge=1, le=1000)) -> JSONResponse:
    try:
        init_db(_DB_PATH)
        recs = list_units(_DB_PATH, active=_resolve_list_active(active), limit=limit)
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


@units_router.put("/{code}", dependencies=[_write_auth], summary="Upsert unit")
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
    init_db(_DB_PATH)
    before = get_unit(_DB_PATH, code)
    try:
        rec = upsert_unit(_DB_PATH, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("upsert_unit failed code=%s: %s", code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    audit_safe("units", "create" if before is None else "update", code,
               request=request, before=before, after=rec)
    return JSONResponse(_unit_dict(rec))


@units_router.delete("/{code}", dependencies=[_write_auth],
                     summary="Delete unit (soft-delete by default; ?hard=true for permanent)",
                     status_code=204)
def delete_unit_endpoint(
    code: str, request: Request,
    hard: bool = Query(False, description="Permanent removal; requires master_admin + flag"),
) -> Response:
    init_db(_DB_PATH)
    before = get_unit(_DB_PATH, code)
    if before is None:
        raise HTTPException(status_code=404, detail=f"Unit not found: {code}")
    if hard:
        _hard_delete_guard(request)
        if not hard_delete_unit(_DB_PATH, code):
            raise HTTPException(status_code=404, detail=f"Unit not found: {code}")
        audit_safe("units", "hard_delete", code,
                   request=request, before=before, after=None)
        return Response(status_code=204)
    if not soft_delete_unit(_DB_PATH, code):
        raise HTTPException(status_code=404, detail=f"Unit not found: {code}")
    audit_safe("units", "delete", code,
               request=request, before=before, after=None)
    return Response(status_code=204)


@units_router.post("/{code}/restore", dependencies=[_write_auth],
                   summary="Restore a soft-deleted unit")
def restore_unit_endpoint(code: str, request: Request) -> JSONResponse:
    init_db(_DB_PATH)
    before = get_unit(_DB_PATH, code)
    if before is None:
        raise HTTPException(status_code=404, detail=f"Unit not found: {code}")
    if not restore_unit(_DB_PATH, code):
        raise HTTPException(status_code=404, detail=f"Unit not found: {code}")
    after = get_unit(_DB_PATH, code)
    audit_safe("units", "restore", code,
               request=request, before=before, after=after)
    return JSONResponse(_unit_dict(after))


# ══════════════════════════════════════════════════════════════════════════════
# Product Local Augmentation
# ══════════════════════════════════════════════════════════════════════════════

pl_router = APIRouter(prefix="/api/v1/product-local", tags=["master-data"])


def _pl_dict(p: ProductLocal) -> dict:
    return {
        "product_code": p.product_code, "hs_code_override": p.hs_code_override,
        "unit_override": p.unit_override, "design_code_link": p.design_code_link,
        "notes": p.notes, "created_at": p.created_at, "updated_at": p.updated_at,
        "active": p.active, "deleted_at": p.deleted_at,
    }


@pl_router.get("/", dependencies=[_auth], summary="List product local augmentations")
def list_pl_endpoint(active: Optional[str] = Query(None,
        description="omit = active-only (default); 'false' = inactive only; 'true' = active only"),
                    limit: int = Query(500, ge=1, le=2000)) -> JSONResponse:
    try:
        init_db(_DB_PATH)
        recs = list_product_local(_DB_PATH, active=_resolve_list_active(active), limit=limit)
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


@pl_router.put("/{product_code}", dependencies=[_write_auth], summary="Upsert product augmentation")
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
    init_db(_DB_PATH)
    # Phase 4C — referential integrity: hs_code_override must reference an
    # ACTIVE row in hs_codes. Only validated on write; existing rows whose
    # parent has since gone inactive remain readable via GET.
    hs_override = (body.get("hs_code_override") or "").strip() or None
    if hs_override:
        try:
            check_hs_code_active(_DB_PATH, field="hs_code_override", code=hs_override)
        except ReferenceConflict as exc:
            raise HTTPException(status_code=409, detail=exc.to_detail())
    before = get_product_local(_DB_PATH, product_code)
    try:
        rec = upsert_product_local(_DB_PATH, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("upsert_product_local failed code=%s: %s", product_code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    audit_safe("product_local", "create" if before is None else "update", product_code,
               request=request, before=before, after=rec)
    return JSONResponse(_pl_dict(rec))


@pl_router.delete("/{product_code}", dependencies=[_write_auth],
                  summary="Delete product augmentation (soft-delete by default; ?hard=true for permanent)",
                  status_code=204)
def delete_pl_endpoint(
    product_code: str, request: Request,
    hard: bool = Query(False, description="Permanent removal; requires master_admin + flag"),
) -> Response:
    init_db(_DB_PATH)
    before = get_product_local(_DB_PATH, product_code)
    if before is None:
        raise HTTPException(status_code=404, detail=f"product-local not found: {product_code}")
    if hard:
        _hard_delete_guard(request)
        if not hard_delete_product_local(_DB_PATH, product_code):
            raise HTTPException(status_code=404, detail=f"product-local not found: {product_code}")
        audit_safe("product_local", "hard_delete", product_code,
                   request=request, before=before, after=None)
        return Response(status_code=204)
    if not soft_delete_product_local(_DB_PATH, product_code):
        raise HTTPException(status_code=404, detail=f"product-local not found: {product_code}")
    audit_safe("product_local", "delete", product_code,
               request=request, before=before, after=None)
    return Response(status_code=204)


@pl_router.post("/{product_code}/restore", dependencies=[_write_auth],
                summary="Restore a soft-deleted product overlay")
def restore_pl_endpoint(product_code: str, request: Request) -> JSONResponse:
    init_db(_DB_PATH)
    before = get_product_local(_DB_PATH, product_code)
    if before is None:
        raise HTTPException(status_code=404, detail=f"product-local not found: {product_code}")
    if not restore_product_local(_DB_PATH, product_code):
        raise HTTPException(status_code=404, detail=f"product-local not found: {product_code}")
    after = get_product_local(_DB_PATH, product_code)
    audit_safe("product_local", "restore", product_code,
               request=request, before=before, after=after)
    return JSONResponse(_pl_dict(after))


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
        "deleted_at": i.deleted_at,
    }


@incoterms_router.get("/", dependencies=[_auth], summary="List incoterms")
def list_incoterms_endpoint(active: Optional[str] = Query(None,
        description="omit = active-only (default); 'false' = inactive only; 'true' = active only"),
                            limit: int = Query(100, ge=1, le=1000)) -> JSONResponse:
    try:
        init_db(_DB_PATH)
        recs = list_incoterms(_DB_PATH, active=_resolve_list_active(active), limit=limit)
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


@incoterms_router.put("/{code}", dependencies=[_write_auth], summary="Upsert incoterm")
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
    init_db(_DB_PATH)
    before = get_incoterm(_DB_PATH, code)
    try:
        rec = upsert_incoterm(_DB_PATH, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("upsert_incoterm failed code=%s: %s", code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    audit_safe("incoterms", "create" if before is None else "update", code,
               request=request, before=before, after=rec)
    return JSONResponse(_incoterm_dict(rec))


@incoterms_router.delete("/{code}", dependencies=[_write_auth],
                         summary="Delete incoterm (soft-delete by default; ?hard=true for permanent)",
                         status_code=204)
def delete_incoterm_endpoint(
    code: str, request: Request,
    hard: bool = Query(False, description="Permanent removal; requires master_admin + flag"),
) -> Response:
    init_db(_DB_PATH)
    before = get_incoterm(_DB_PATH, code)
    if before is None:
        raise HTTPException(status_code=404, detail=f"Incoterm not found: {code}")
    if hard:
        _hard_delete_guard(request)
        if not hard_delete_incoterm(_DB_PATH, code):
            raise HTTPException(status_code=404, detail=f"Incoterm not found: {code}")
        audit_safe("incoterms", "hard_delete", code,
                   request=request, before=before, after=None)
        return Response(status_code=204)
    if not soft_delete_incoterm(_DB_PATH, code):
        raise HTTPException(status_code=404, detail=f"Incoterm not found: {code}")
    audit_safe("incoterms", "delete", code,
               request=request, before=before, after=None)
    return Response(status_code=204)


@incoterms_router.post("/{code}/restore", dependencies=[_write_auth],
                       summary="Restore a soft-deleted incoterm")
def restore_incoterm_endpoint(code: str, request: Request) -> JSONResponse:
    init_db(_DB_PATH)
    before = get_incoterm(_DB_PATH, code)
    if before is None:
        raise HTTPException(status_code=404, detail=f"Incoterm not found: {code}")
    if not restore_incoterm(_DB_PATH, code):
        raise HTTPException(status_code=404, detail=f"Incoterm not found: {code}")
    after = get_incoterm(_DB_PATH, code)
    audit_safe("incoterms", "restore", code,
               request=request, before=before, after=after)
    return JSONResponse(_incoterm_dict(after))


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
        "deleted_at": v.deleted_at,
    }


@vat_router.get("/", dependencies=[_auth], summary="List VAT config entries")
def list_vat_endpoint(country: Optional[str] = Query(None),
                     active: Optional[str] = Query(None,
        description="omit = active-only (default); 'false' = inactive only; 'true' = active only"),
                     limit: int = Query(500, ge=1, le=2000)) -> JSONResponse:
    try:
        init_db(_DB_PATH)
        recs = list_vat_config(_DB_PATH, country=country,
                              active=_resolve_list_active(active), limit=limit)
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


@vat_router.post("/", dependencies=[_write_auth], summary="Create VAT entry", status_code=201)
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
    audit_safe("vat_config", "create", rec.id,
               request=request, before=None, after=rec)
    return JSONResponse(status_code=201, content=_vat_dict(rec))


@vat_router.put("/{vat_id}", dependencies=[_write_auth], summary="Update VAT entry")
async def update_vat_endpoint(vat_id: int, request: Request) -> JSONResponse:
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    init_db(_DB_PATH)
    before = get_vat_config(_DB_PATH, vat_id)
    try:
        rec = update_vat_config(_DB_PATH, vat_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("update_vat_config failed id=%s: %s", vat_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    if rec is None:
        raise HTTPException(status_code=404, detail=f"VAT config not found: {vat_id}")
    audit_safe("vat_config", "update", vat_id,
               request=request, before=before, after=rec)
    return JSONResponse(_vat_dict(rec))


@vat_router.delete("/{vat_id}", dependencies=[_write_auth],
                  summary="Delete VAT entry (soft-delete by default; ?hard=true for permanent)",
                  status_code=204)
def delete_vat_endpoint(
    vat_id: int, request: Request,
    hard: bool = Query(False, description="Permanent removal; requires master_admin + flag"),
) -> Response:
    init_db(_DB_PATH)
    before = get_vat_config(_DB_PATH, vat_id)
    if before is None:
        raise HTTPException(status_code=404, detail=f"VAT config not found: {vat_id}")
    if hard:
        _hard_delete_guard(request)
        if not hard_delete_vat_config(_DB_PATH, vat_id):
            raise HTTPException(status_code=404, detail=f"VAT config not found: {vat_id}")
        audit_safe("vat_config", "hard_delete", vat_id,
                   request=request, before=before, after=None)
        return Response(status_code=204)
    if not soft_delete_vat_config(_DB_PATH, vat_id):
        raise HTTPException(status_code=404, detail=f"VAT config not found: {vat_id}")
    audit_safe("vat_config", "delete", vat_id,
               request=request, before=before, after=None)
    return Response(status_code=204)


@vat_router.post("/{vat_id}/restore", dependencies=[_write_auth],
                 summary="Restore a soft-deleted VAT entry")
def restore_vat_endpoint(vat_id: int, request: Request) -> JSONResponse:
    init_db(_DB_PATH)
    before = get_vat_config(_DB_PATH, vat_id)
    if before is None:
        raise HTTPException(status_code=404, detail=f"VAT config not found: {vat_id}")
    if not restore_vat_config(_DB_PATH, vat_id):
        raise HTTPException(status_code=404, detail=f"VAT config not found: {vat_id}")
    after = get_vat_config(_DB_PATH, vat_id)
    audit_safe("vat_config", "restore", vat_id,
               request=request, before=before, after=after)
    return JSONResponse(_vat_dict(after))


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
        "deleted_at": f.deleted_at,
    }


@fx_router.get("/", dependencies=[_auth], summary="List FX rate observations")
def list_fx_endpoint(from_currency: Optional[str] = Query(None),
                    to_currency: Optional[str] = Query(None),
                    rate_date: Optional[str] = Query(None),
                    active: Optional[str] = Query(None,
        description="omit = active-only (default); 'false' = inactive only; 'true' = active only"),
                    limit: int = Query(500, ge=1, le=2000)) -> JSONResponse:
    try:
        init_db(_DB_PATH)
        recs = list_fx_rates(_DB_PATH, from_currency=from_currency,
                             to_currency=to_currency, rate_date=rate_date,
                             active=_resolve_list_active(active), limit=limit)
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


@fx_router.post("/", dependencies=[_write_auth], summary="Create FX rate observation",
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
    audit_safe("fx_rates", "create", rec.id,
               request=request, before=None, after=rec)
    return JSONResponse(status_code=201, content=_fx_dict(rec))


@fx_router.put("/{fx_id}", dependencies=[_write_auth], summary="Update FX rate entry")
async def update_fx_endpoint(fx_id: int, request: Request) -> JSONResponse:
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    init_db(_DB_PATH)
    before = get_fx_rate(_DB_PATH, fx_id)
    try:
        rec = update_fx_rate(_DB_PATH, fx_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("update_fx_rate failed id=%s: %s", fx_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    if rec is None:
        raise HTTPException(status_code=404, detail=f"FX rate not found: {fx_id}")
    audit_safe("fx_rates", "update", fx_id,
               request=request, before=before, after=rec)
    return JSONResponse(_fx_dict(rec))


@fx_router.delete("/{fx_id}", dependencies=[_write_auth],
                 summary="Delete FX rate entry (soft-delete by default; ?hard=true for permanent)",
                 status_code=204)
def delete_fx_endpoint(
    fx_id: int, request: Request,
    hard: bool = Query(False, description="Permanent removal; requires master_admin + flag"),
) -> Response:
    init_db(_DB_PATH)
    before = get_fx_rate(_DB_PATH, fx_id)
    if before is None:
        raise HTTPException(status_code=404, detail=f"FX rate not found: {fx_id}")
    if hard:
        _hard_delete_guard(request)
        if not hard_delete_fx_rate(_DB_PATH, fx_id):
            raise HTTPException(status_code=404, detail=f"FX rate not found: {fx_id}")
        audit_safe("fx_rates", "hard_delete", fx_id,
                   request=request, before=before, after=None)
        return Response(status_code=204)
    if not soft_delete_fx_rate(_DB_PATH, fx_id):
        raise HTTPException(status_code=404, detail=f"FX rate not found: {fx_id}")
    audit_safe("fx_rates", "delete", fx_id,
               request=request, before=before, after=None)
    return Response(status_code=204)


@fx_router.post("/{fx_id}/restore", dependencies=[_write_auth],
                summary="Restore a soft-deleted FX rate entry")
def restore_fx_endpoint(fx_id: int, request: Request) -> JSONResponse:
    init_db(_DB_PATH)
    before = get_fx_rate(_DB_PATH, fx_id)
    if before is None:
        raise HTTPException(status_code=404, detail=f"FX rate not found: {fx_id}")
    if not restore_fx_rate(_DB_PATH, fx_id):
        raise HTTPException(status_code=404, detail=f"FX rate not found: {fx_id}")
    after = get_fx_rate(_DB_PATH, fx_id)
    audit_safe("fx_rates", "restore", fx_id,
               request=request, before=before, after=after)
    return JSONResponse(_fx_dict(after))


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
        "deleted_at": c.deleted_at,
    }


@carriers_config_router.get("/", dependencies=[_auth], summary="List carrier configs")
def list_carriers_endpoint(active: Optional[str] = Query(None,
        description="omit = active-only (default); 'false' = inactive only; 'true' = active only"),
                          limit: int = Query(100, ge=1, le=1000)) -> JSONResponse:
    try:
        init_db(_DB_PATH)
        recs = list_carrier_configs(_DB_PATH, active=_resolve_list_active(active), limit=limit)
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


@carriers_config_router.put("/{carrier_code}", dependencies=[_write_auth],
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
    init_db(_DB_PATH)
    before = get_carrier_config(_DB_PATH, carrier_code)
    try:
        rec = upsert_carrier_config(_DB_PATH, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("upsert_carrier_config failed code=%s: %s", carrier_code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    audit_safe("carriers_config", "create" if before is None else "update", carrier_code,
               request=request, before=before, after=rec)
    return JSONResponse(_carrier_dict(rec))


@carriers_config_router.delete("/{carrier_code}", dependencies=[_write_auth],
                               summary="Delete carrier config (soft-delete by default; ?hard=true for permanent)",
                               status_code=204)
def delete_carrier_endpoint(
    carrier_code: str, request: Request,
    hard: bool = Query(False, description="Permanent removal; requires master_admin + flag"),
) -> Response:
    init_db(_DB_PATH)
    before = get_carrier_config(_DB_PATH, carrier_code)
    if before is None:
        raise HTTPException(status_code=404, detail=f"Carrier config not found: {carrier_code}")
    if hard:
        _hard_delete_guard(request)
        if not hard_delete_carrier_config(_DB_PATH, carrier_code):
            raise HTTPException(status_code=404, detail=f"Carrier config not found: {carrier_code}")
        audit_safe("carriers_config", "hard_delete", carrier_code,
                   request=request, before=before, after=None)
        return Response(status_code=204)
    if not soft_delete_carrier_config(_DB_PATH, carrier_code):
        raise HTTPException(status_code=404, detail=f"Carrier config not found: {carrier_code}")
    audit_safe("carriers_config", "delete", carrier_code,
               request=request, before=before, after=None)
    return Response(status_code=204)


@carriers_config_router.post("/{carrier_code}/restore", dependencies=[_write_auth],
                              summary="Restore a soft-deleted carrier config")
def restore_carrier_endpoint(carrier_code: str, request: Request) -> JSONResponse:
    init_db(_DB_PATH)
    before = get_carrier_config(_DB_PATH, carrier_code)
    if before is None:
        raise HTTPException(status_code=404, detail=f"Carrier config not found: {carrier_code}")
    if not restore_carrier_config(_DB_PATH, carrier_code):
        raise HTTPException(status_code=404, detail=f"Carrier config not found: {carrier_code}")
    after = get_carrier_config(_DB_PATH, carrier_code)
    audit_safe("carriers_config", "restore", carrier_code,
               request=request, before=before, after=after)
    return JSONResponse(_carrier_dict(after))


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
        "deleted_at":    d.deleted_at,
    }


@designs_router.get("/", dependencies=[_auth], summary="List designs")
def list_designs_endpoint(active: Optional[str] = Query(None,
        description="omit = active-only (default); 'false' = inactive only; 'true' = active only"),
                          design_family: Optional[str] = Query(None),
                          collection: Optional[str] = Query(None),
                          limit: int = Query(500, ge=1, le=2000)) -> JSONResponse:
    init_db(_DB_PATH)
    try:
        recs = list_designs(_DB_PATH, active=_resolve_list_active(active),
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


@designs_router.put("/{design_code}", dependencies=[_write_auth], summary="Upsert design")
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
    init_db(_DB_PATH)
    # Phase 4C — referential integrity: design.hs_code (if supplied) must
    # reference an ACTIVE row in hs_codes.
    design_hs = (body.get("hs_code") or "").strip() or None
    if design_hs:
        try:
            check_hs_code_active(_DB_PATH, field="hs_code", code=design_hs)
        except ReferenceConflict as exc:
            raise HTTPException(status_code=409, detail=exc.to_detail())
    before = get_design(_DB_PATH, design_code)
    try:
        rec = upsert_design(_DB_PATH, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("upsert_design failed code=%s: %s", design_code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    audit_safe("designs", "create" if before is None else "update", design_code,
               request=request, before=before, after=rec)
    return JSONResponse(_design_dict(rec))


@designs_router.delete("/{design_code}", dependencies=[_write_auth],
                        summary="Delete design (soft-delete by default; ?hard=true for permanent)",
                        status_code=204)
def delete_design_endpoint(
    design_code: str, request: Request,
    hard: bool = Query(False, description="Permanent removal; requires master_admin + flag"),
) -> Response:
    init_db(_DB_PATH)
    before = get_design(_DB_PATH, design_code)
    if before is None:
        raise HTTPException(status_code=404, detail=f"Design not found: {design_code}")
    if hard:
        _hard_delete_guard(request)
        if not hard_delete_design(_DB_PATH, design_code):
            raise HTTPException(status_code=404, detail=f"Design not found: {design_code}")
        audit_safe("designs", "hard_delete", design_code,
                   request=request, before=before, after=None)
        return Response(status_code=204)
    if not soft_delete_design(_DB_PATH, design_code):
        raise HTTPException(status_code=404, detail=f"Design not found: {design_code}")
    audit_safe("designs", "delete", design_code,
               request=request, before=before, after=None)
    return Response(status_code=204)


@designs_router.post("/{design_code}/restore", dependencies=[_write_auth],
                     summary="Restore a soft-deleted design")
def restore_design_endpoint(design_code: str, request: Request) -> JSONResponse:
    init_db(_DB_PATH)
    before = get_design(_DB_PATH, design_code)
    if before is None:
        raise HTTPException(status_code=404, detail=f"Design not found: {design_code}")
    if not restore_design(_DB_PATH, design_code):
        raise HTTPException(status_code=404, detail=f"Design not found: {design_code}")
    after = get_design(_DB_PATH, design_code)
    audit_safe("designs", "restore", design_code,
               request=request, before=before, after=after)
    return JSONResponse(_design_dict(after))


# ══════════════════════════════════════════════════════════════════════════════
# Master Audit — Phase 1
# ══════════════════════════════════════════════════════════════════════════════
#
# Read-only query surface for the unified master_audit table. All writes are
# produced internally by audit_safe() calls inside the entity write handlers
# above. This endpoint never accepts writes.
#
# Auth is _auth in Phase 1 (same posture as the other master GETs). Phase 2
# will tighten this to require master_admin once role enforcement is enabled.

audit_router = APIRouter(prefix="/api/v1/master/audit", tags=["master-data"])


@audit_router.get("/", dependencies=[_audit_read_auth], summary="List master-data audit rows")
def list_master_audit_endpoint(
    entity: Optional[str] = Query(None, description="Filter by entity tag"),
    pk:     Optional[str] = Query(None, description="Filter by primary key"),
    actor:  Optional[str] = Query(None, description="Filter by actor"),
    op:     Optional[str] = Query(None, description="Filter by op"),
    since:  Optional[str] = Query(None, description="ISO-8601 inclusive lower bound"),
    until:  Optional[str] = Query(None, description="ISO-8601 exclusive upper bound"),
    limit:  int           = Query(200, ge=1, le=2000),
    offset: int           = Query(0,   ge=0),
) -> JSONResponse:
    try:
        rows = list_audit(
            entity=entity, pk=pk, actor=actor, op=op,
            since=since, until=until, limit=limit, offset=offset,
        )
    except Exception as exc:
        log.error("list_master_audit failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Audit query error: {exc}")
    return JSONResponse({"count": len(rows), "rows": rows})
