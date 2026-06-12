"""routes_master_jewelry.py — Phase 3 jewelry-domain master entities.

Three local-only entities, each in its OWN sqlite file:
  /api/v1/metals/      — metal codes + purity
  /api/v1/stones/      — gemstone catalog + certification (reference only)
  /api/v1/warehouses/  — stock-location catalog

Auth: read on _auth (require_api_key); write on _write_auth
(require_role_or_apikey(MASTER_ADMIN, MASTER_EDITOR)). DELETE is HARD delete —
soft-delete is Phase 4.

Audit: every write produces a master_audit row via audit_safe().

Authority isolation:
  - These tables are LOCAL. They do NOT mutate wFirma, PZ, DHL, proforma,
    customs, FX engine, or production env state.
  - Inventory engine MAY read warehouses as reference; writes stay here.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from ..core.config import settings
from ..core.security import require_api_key
from ..core.logging import get_logger
from ..core.audit import audit_safe
from ..core.role_gate import require_role_or_apikey, MASTER_ADMIN, MASTER_EDITOR

from ..services import metals_db as metals
from ..services import stones_db as stones
from ..services import warehouses_db as warehouses


log = get_logger(__name__)
_auth       = Depends(require_api_key)
_write_auth = Depends(require_role_or_apikey(MASTER_ADMIN, MASTER_EDITOR))
# Hard-delete is master_admin only — distinct from soft-delete authority.
_hard_delete_auth = Depends(require_role_or_apikey(MASTER_ADMIN))


def _resolve_list_active(active_param: Optional[str]) -> Optional[bool]:
    """Phase 4A list-default policy: when the ``active`` query param is
    omitted, default to active-only. Pass ``active=false`` to see soft-
    deleted records. Pass ``active=true`` for an explicit active filter
    (equivalent to omission)."""
    parsed = _parse_active(active_param)
    return True if parsed is None else parsed


import hmac as _hmac


def _hard_delete_guard(request: Request) -> None:
    """Phase 4A — guard for ``DELETE ...?hard=true``.

    Two gates must pass:
      1. ``settings.master_hard_delete_enabled`` is True → else 409.
      2. Caller holds master_admin authority:
           - direct admin X-API-Key, OR
           - session user with role == master_admin
         If ``master_role_enforcement`` is False, the API-key gate
         (handled by the route's ``_write_auth`` dependency) is the
         only requirement — but we still demand the admin key in
         that case (not an editor session) to keep hard delete
         intentional even with flag off. → else 403.

    The function returns silently when permitted, raises HTTPException
    otherwise.
    """
    if not settings.master_hard_delete_enabled:
        raise HTTPException(
            status_code=409,
            detail=("Hard delete is disabled. Set master_hard_delete_enabled "
                    "to true (admin) to permit permanent removal."),
        )
    # (a) admin X-API-Key bypass always wins.
    key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if settings.api_key and key and _hmac.compare_digest(key.encode("utf-8"), settings.api_key.encode("utf-8")):
        return
    # (b) session user must hold master_admin specifically.
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


def _metals_path()     -> Any: return settings.storage_root / "metals.sqlite"
def _stones_path()     -> Any: return settings.storage_root / "stones.sqlite"
def _warehouses_path() -> Any: return settings.storage_root / "warehouses.sqlite"


def _parse_active(v: Optional[str]) -> Optional[bool]:
    if v is None or v == "":
        return None
    s = str(v).strip().lower()
    if s in ("true", "1", "yes"):  return True
    if s in ("false", "0", "no"):  return False
    raise HTTPException(status_code=422,
                        detail=f"active must be true/false, got {v!r}")


def _read_body_dict(body: Any) -> dict:
    if not isinstance(body, dict):
        raise HTTPException(status_code=422,
                            detail="Request body must be a JSON object")
    return dict(body)


# ══════════════════════════════════════════════════════════════════════════════
# Metals
# ══════════════════════════════════════════════════════════════════════════════

metals_router = APIRouter(prefix="/api/v1/metals", tags=["master-data"])


@metals_router.get("/", dependencies=[_auth], summary="List metals")
def list_metals_endpoint(
    active:     Optional[str] = Query(None,
        description="omit = active-only (default); 'false' = inactive only; 'true' = active only"),
    metal_type: Optional[str] = Query(None),
    limit:      int           = Query(500, ge=1, le=2000),
) -> JSONResponse:
    try:
        metals.init_db(_metals_path())
        recs = metals.list_metals(_metals_path(),
                                  active=_resolve_list_active(active),
                                  metal_type=metal_type, limit=limit)
    except HTTPException:
        raise
    except Exception as exc:
        log.error("list_metals failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse({"count": len(recs),
                         "metals": [metals.metal_to_dict(m) for m in recs]})


@metals_router.get("/{code}", dependencies=[_auth], summary="Get metal")
def get_metal_endpoint(code: str) -> JSONResponse:
    metals.init_db(_metals_path())
    rec = metals.get_metal(_metals_path(), code)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Metal not found: {code}")
    return JSONResponse(metals.metal_to_dict(rec))


@metals_router.put("/{code}", dependencies=[_write_auth], summary="Upsert metal")
async def upsert_metal_endpoint(code: str, request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    body = _read_body_dict(body)
    body["code"] = code
    errs = metals.validate_metal(body)
    if errs:
        raise HTTPException(status_code=422, detail={"validation_errors": errs})
    metals.init_db(_metals_path())
    before = metals.get_metal(_metals_path(), code)
    try:
        rec = metals.upsert_metal(_metals_path(), body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("upsert_metal failed code=%s: %s", code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    audit_safe("metals", "create" if before is None else "update", code,
               request=request, before=before, after=rec)
    return JSONResponse(metals.metal_to_dict(rec))


@metals_router.delete("/{code}", dependencies=[_write_auth],
                       summary="Delete metal (soft-delete by default; ?hard=true for permanent)",
                       status_code=204)
def delete_metal_endpoint(
    code: str, request: Request,
    hard: bool = Query(False, description="Permanent removal; requires master_admin + flag"),
) -> Response:
    metals.init_db(_metals_path())
    before = metals.get_metal(_metals_path(), code)
    if before is None:
        raise HTTPException(status_code=404, detail=f"Metal not found: {code}")
    if hard:
        _hard_delete_guard(request)
        if not metals.hard_delete_metal(_metals_path(), code):
            raise HTTPException(status_code=404, detail=f"Metal not found: {code}")
        audit_safe("metals", "hard_delete", code,
                   request=request, before=before, after=None)
        return Response(status_code=204)
    # Soft delete (default).
    if not metals.soft_delete_metal(_metals_path(), code):
        raise HTTPException(status_code=404, detail=f"Metal not found: {code}")
    audit_safe("metals", "delete", code,
               request=request, before=before, after=None)
    return Response(status_code=204)


@metals_router.post("/{code}/restore", dependencies=[_write_auth],
                     summary="Restore a soft-deleted metal")
def restore_metal_endpoint(code: str, request: Request) -> JSONResponse:
    metals.init_db(_metals_path())
    before = metals.get_metal(_metals_path(), code)
    if before is None:
        raise HTTPException(status_code=404, detail=f"Metal not found: {code}")
    if not metals.restore_metal(_metals_path(), code):
        raise HTTPException(status_code=404, detail=f"Metal not found: {code}")
    after = metals.get_metal(_metals_path(), code)
    audit_safe("metals", "restore", code,
               request=request, before=before, after=after)
    return JSONResponse(metals.metal_to_dict(after))


# ══════════════════════════════════════════════════════════════════════════════
# Stones
# ══════════════════════════════════════════════════════════════════════════════

stones_router = APIRouter(prefix="/api/v1/stones", tags=["master-data"])


@stones_router.get("/", dependencies=[_auth], summary="List stones")
def list_stones_endpoint(
    active:     Optional[str] = Query(None,
        description="omit = active-only (default); 'false' = inactive only; 'true' = active only"),
    stone_type: Optional[str] = Query(None),
    limit:      int           = Query(500, ge=1, le=2000),
) -> JSONResponse:
    try:
        stones.init_db(_stones_path())
        recs = stones.list_stones(_stones_path(),
                                  active=_resolve_list_active(active),
                                  stone_type=stone_type, limit=limit)
    except HTTPException:
        raise
    except Exception as exc:
        log.error("list_stones failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse({"count": len(recs),
                         "stones": [stones.stone_to_dict(s) for s in recs]})


@stones_router.get("/{code}", dependencies=[_auth], summary="Get stone")
def get_stone_endpoint(code: str) -> JSONResponse:
    stones.init_db(_stones_path())
    rec = stones.get_stone(_stones_path(), code)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Stone not found: {code}")
    return JSONResponse(stones.stone_to_dict(rec))


@stones_router.put("/{code}", dependencies=[_write_auth], summary="Upsert stone")
async def upsert_stone_endpoint(code: str, request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    body = _read_body_dict(body)
    body["code"] = code
    errs = stones.validate_stone(body)
    if errs:
        raise HTTPException(status_code=422, detail={"validation_errors": errs})
    stones.init_db(_stones_path())
    before = stones.get_stone(_stones_path(), code)
    try:
        rec = stones.upsert_stone(_stones_path(), body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("upsert_stone failed code=%s: %s", code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    audit_safe("stones", "create" if before is None else "update", code,
               request=request, before=before, after=rec)
    return JSONResponse(stones.stone_to_dict(rec))


@stones_router.delete("/{code}", dependencies=[_write_auth],
                       summary="Delete stone (soft-delete by default; ?hard=true for permanent)",
                       status_code=204)
def delete_stone_endpoint(
    code: str, request: Request,
    hard: bool = Query(False, description="Permanent removal; requires master_admin + flag"),
) -> Response:
    stones.init_db(_stones_path())
    before = stones.get_stone(_stones_path(), code)
    if before is None:
        raise HTTPException(status_code=404, detail=f"Stone not found: {code}")
    if hard:
        _hard_delete_guard(request)
        if not stones.hard_delete_stone(_stones_path(), code):
            raise HTTPException(status_code=404, detail=f"Stone not found: {code}")
        audit_safe("stones", "hard_delete", code,
                   request=request, before=before, after=None)
        return Response(status_code=204)
    if not stones.soft_delete_stone(_stones_path(), code):
        raise HTTPException(status_code=404, detail=f"Stone not found: {code}")
    audit_safe("stones", "delete", code,
               request=request, before=before, after=None)
    return Response(status_code=204)


@stones_router.post("/{code}/restore", dependencies=[_write_auth],
                     summary="Restore a soft-deleted stone")
def restore_stone_endpoint(code: str, request: Request) -> JSONResponse:
    stones.init_db(_stones_path())
    before = stones.get_stone(_stones_path(), code)
    if before is None:
        raise HTTPException(status_code=404, detail=f"Stone not found: {code}")
    if not stones.restore_stone(_stones_path(), code):
        raise HTTPException(status_code=404, detail=f"Stone not found: {code}")
    after = stones.get_stone(_stones_path(), code)
    audit_safe("stones", "restore", code,
               request=request, before=before, after=after)
    return JSONResponse(stones.stone_to_dict(after))


# ══════════════════════════════════════════════════════════════════════════════
# Warehouses
# ══════════════════════════════════════════════════════════════════════════════

warehouses_router = APIRouter(prefix="/api/v1/warehouses", tags=["master-data"])


@warehouses_router.get("/", dependencies=[_auth], summary="List warehouses")
def list_warehouses_endpoint(
    active:   Optional[str] = Query(None,
        description="omit = active-only (default); 'false' = inactive only; 'true' = active only"),
    category: Optional[str] = Query(None),
    limit:    int           = Query(500, ge=1, le=2000),
) -> JSONResponse:
    try:
        warehouses.init_db(_warehouses_path())
        recs = warehouses.list_warehouses(_warehouses_path(),
                                          active=_resolve_list_active(active),
                                          category=category, limit=limit)
    except HTTPException:
        raise
    except Exception as exc:
        log.error("list_warehouses failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse({"count": len(recs),
                         "warehouses": [warehouses.warehouse_to_dict(w) for w in recs]})


@warehouses_router.get("/{code}", dependencies=[_auth], summary="Get warehouse")
def get_warehouse_endpoint(code: str) -> JSONResponse:
    warehouses.init_db(_warehouses_path())
    rec = warehouses.get_warehouse(_warehouses_path(), code)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Warehouse not found: {code}")
    return JSONResponse(warehouses.warehouse_to_dict(rec))


@warehouses_router.put("/{code}", dependencies=[_write_auth], summary="Upsert warehouse")
async def upsert_warehouse_endpoint(code: str, request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    body = _read_body_dict(body)
    body["code"] = code
    errs = warehouses.validate_warehouse(body)
    if errs:
        raise HTTPException(status_code=422, detail={"validation_errors": errs})
    warehouses.init_db(_warehouses_path())
    before = warehouses.get_warehouse(_warehouses_path(), code)
    try:
        rec = warehouses.upsert_warehouse(_warehouses_path(), body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("upsert_warehouse failed code=%s: %s", code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    audit_safe("warehouses", "create" if before is None else "update", code,
               request=request, before=before, after=rec)
    return JSONResponse(warehouses.warehouse_to_dict(rec))


@warehouses_router.delete("/{code}", dependencies=[_write_auth],
                           summary="Delete warehouse (soft-delete by default; ?hard=true for permanent)",
                           status_code=204)
def delete_warehouse_endpoint(
    code: str, request: Request,
    hard: bool = Query(False, description="Permanent removal; requires master_admin + flag"),
) -> Response:
    warehouses.init_db(_warehouses_path())
    before = warehouses.get_warehouse(_warehouses_path(), code)
    if before is None:
        raise HTTPException(status_code=404, detail=f"Warehouse not found: {code}")
    if hard:
        _hard_delete_guard(request)
        if not warehouses.hard_delete_warehouse(_warehouses_path(), code):
            raise HTTPException(status_code=404, detail=f"Warehouse not found: {code}")
        audit_safe("warehouses", "hard_delete", code,
                   request=request, before=before, after=None)
        return Response(status_code=204)
    if not warehouses.soft_delete_warehouse(_warehouses_path(), code):
        raise HTTPException(status_code=404, detail=f"Warehouse not found: {code}")
    audit_safe("warehouses", "delete", code,
               request=request, before=before, after=None)
    return Response(status_code=204)


@warehouses_router.post("/{code}/restore", dependencies=[_write_auth],
                         summary="Restore a soft-deleted warehouse")
def restore_warehouse_endpoint(code: str, request: Request) -> JSONResponse:
    warehouses.init_db(_warehouses_path())
    before = warehouses.get_warehouse(_warehouses_path(), code)
    if before is None:
        raise HTTPException(status_code=404, detail=f"Warehouse not found: {code}")
    if not warehouses.restore_warehouse(_warehouses_path(), code):
        raise HTTPException(status_code=404, detail=f"Warehouse not found: {code}")
    after = warehouses.get_warehouse(_warehouses_path(), code)
    audit_safe("warehouses", "restore", code,
               request=request, before=before, after=after)
    return JSONResponse(warehouses.warehouse_to_dict(after))
