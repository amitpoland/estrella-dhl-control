"""
routes_box_types.py — Box Types master CRUD (WF4.5 / Path-DOC).

Endpoints:
  GET  /api/v1/box-types/          — list active box types
  GET  /api/v1/box-types/{code}    — get one by code
  POST /api/v1/box-types/          — create (code + dims in body)
  PUT  /api/v1/box-types/{code}    — upsert by code (update dims)

No soft-delete in Phase D — inactive records are set via PUT with active=false.
Auth: X-API-Key read; MASTER_ADMIN or MASTER_EDITOR for writes.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ..core.config import settings
from ..core.security import require_api_key
from ..core.logging import get_logger
from ..core.audit import audit_safe
from ..core.role_gate import require_role_or_apikey, MASTER_ADMIN, MASTER_EDITOR
from ..services.master_data_db import (
    BoxType,
    init_db,
    list_box_types,
    get_box_type_by_code,
    upsert_box_type,
)

log = get_logger(__name__)

box_types_router = APIRouter(prefix="/api/v1/box-types", tags=["master-data"])

_auth = Depends(require_api_key)
_write_auth = Depends(require_role_or_apikey(MASTER_ADMIN, MASTER_EDITOR))

# Uses the same master_data.sqlite as all other master-data routers.
_DB_PATH = settings.storage_root / "master_data.sqlite"


def _box_type_dict(b: BoxType) -> dict:
    return {
        "id":             b.id,
        "code":           b.code,
        "name":           b.name,
        "length_cm":      b.length_cm,
        "width_cm":       b.width_cm,
        "height_cm":      b.height_cm,
        "tare_weight_kg": b.tare_weight_kg,
        "active":         b.active,
        "notes":          b.notes,
        "created_at":     b.created_at,
        "updated_at":     b.updated_at,
    }


def _resolve_list_active(v: Optional[str]) -> Optional[bool]:
    """Map query-param string → Optional[bool].

    omit / None  → True  (active-only, the common case)
    'false'      → False (inactive-only)
    'true'       → True
    'all'        → None  (all records)
    """
    if v is None:
        return True
    v = v.strip().lower()
    if v in ("false", "inactive"):
        return False
    if v in ("all",):
        return None
    return True


@box_types_router.get("/", dependencies=[_auth], summary="List box types")
def list_box_types_endpoint(
    active: Optional[str] = Query(
        None,
        description=(
            "omit = active-only (default); "
            "'false' = inactive only; "
            "'all' = all records"
        ),
    ),
    limit: int = Query(200, ge=1, le=1000),
) -> JSONResponse:
    try:
        init_db(_DB_PATH)
        recs = list_box_types(_DB_PATH, active=_resolve_list_active(active), limit=limit)
    except HTTPException:
        raise
    except Exception as exc:
        log.error("list_box_types failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse({
        "count":     len(recs),
        "box_types": [_box_type_dict(b) for b in recs],
    })


@box_types_router.get("/{code}", dependencies=[_auth], summary="Get box type by code")
def get_box_type_endpoint(code: str) -> JSONResponse:
    init_db(_DB_PATH)
    rec = get_box_type_by_code(_DB_PATH, code)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"BoxType not found: {code!r}")
    return JSONResponse(_box_type_dict(rec))


@box_types_router.post("/", dependencies=[_write_auth], summary="Create box type")
async def create_box_type_endpoint(request: Request) -> JSONResponse:
    """Create a new box type. ``code`` must be in the request body.

    Calls ``upsert_box_type`` — idempotent if the code already exists
    (acts as an update in that case, consistent with the PUT endpoint).
    """
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    code = (str(body.get("code") or "")).strip().upper()
    if not code:
        raise HTTPException(status_code=422, detail="'code' is required")
    body = dict(body); body["code"] = code
    init_db(_DB_PATH)
    before = get_box_type_by_code(_DB_PATH, code)
    try:
        rec = upsert_box_type(_DB_PATH, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("create_box_type failed code=%s: %s", code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    audit_safe("box_types", "create" if before is None else "update", code,
               request=request, before=before, after=rec)
    return JSONResponse(_box_type_dict(rec), status_code=201 if before is None else 200)


@box_types_router.put("/{code}", dependencies=[_write_auth], summary="Upsert box type by code")
async def upsert_box_type_endpoint(code: str, request: Request) -> JSONResponse:
    """Upsert a box type identified by ``code`` (path parameter).

    Body fields: name, length_cm, width_cm, height_cm, tare_weight_kg,
    active (bool), notes. ``code`` in body is overridden by the path param.
    """
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    body = dict(body); body["code"] = code.strip().upper()
    init_db(_DB_PATH)
    before = get_box_type_by_code(_DB_PATH, code)
    try:
        rec = upsert_box_type(_DB_PATH, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("upsert_box_type failed code=%s: %s", code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    audit_safe("box_types", "create" if before is None else "update", code,
               request=request, before=before, after=rec)
    return JSONResponse(_box_type_dict(rec))
