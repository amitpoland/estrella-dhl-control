"""
routes_suppliers.py — Suppliers Master Data REST API.

  GET    /api/v1/suppliers/
         List suppliers. Optional QS: country, active, limit (default 200).

  GET    /api/v1/suppliers/{supplier_id}
         Read one supplier by id. 404 if absent.

  POST   /api/v1/suppliers/
         Create a new supplier. 201 with stored record. Body is a JSON object.

  PUT    /api/v1/suppliers/{supplier_id}
         Update a supplier. Partial updates merge over existing record.

  DELETE /api/v1/suppliers/{supplier_id}
         Hard delete. 204 on success, 404 if missing.

All endpoints are X-API-Key authenticated. This module is local-only — it
does NOT call wFirma and is NOT part of any PZ/customs calculation path.

DB path: settings.storage_root / "suppliers.sqlite"
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from ..core.config import settings
from ..core.security import require_api_key
from ..core.logging import get_logger
from ..services.suppliers_db import (
    Supplier,
    init_db,
    validate_supplier,
    create_supplier,
    get_supplier,
    list_suppliers,
    update_supplier,
    delete_supplier,
    sync_from_wfirma,
)

log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1/suppliers", tags=["suppliers"])
_auth  = Depends(require_api_key)

_DB_PATH = settings.storage_root / "suppliers.sqlite"


def _supplier_dict(s: Supplier) -> dict:
    return {
        "id":            s.id,
        "supplier_code": s.supplier_code,
        "name":          s.name,
        "country":       s.country,
        "vat_id":        s.vat_id,
        "eori":          s.eori,
        "address":       s.address,
        "contact_email": s.contact_email,
        "contact_phone": s.contact_phone,
        "active":        s.active,
        "notes":         s.notes,
        "wfirma_id":     s.wfirma_id,
        "created_at":    s.created_at,
        "updated_at":    s.updated_at,
    }


def _parse_active_query(v: Optional[str]) -> Optional[bool]:
    if v is None or v == "":
        return None
    s = str(v).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    raise HTTPException(status_code=422, detail=f"active must be true/false, got {v!r}")


@router.get("/", dependencies=[_auth], summary="List suppliers")
def list_suppliers_endpoint(
    country: Optional[str] = Query(None, description="ISO alpha-2 filter"),
    active:  Optional[str] = Query(None, description="true|false"),
    limit:   int           = Query(200, ge=1, le=1000),
) -> JSONResponse:
    """List suppliers, most-recently-updated first."""
    try:
        init_db(_DB_PATH)
        records = list_suppliers(_DB_PATH,
                                 active=_parse_active_query(active),
                                 country=country, limit=limit)
    except HTTPException:
        raise
    except Exception as exc:
        log.error("list_suppliers failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return JSONResponse({"count": len(records),
                         "suppliers": [_supplier_dict(s) for s in records]})


@router.get("/{supplier_id}", dependencies=[_auth], summary="Get one supplier")
def get_supplier_endpoint(supplier_id: int) -> JSONResponse:
    """Read a supplier by id. 404 if not found."""
    try:
        init_db(_DB_PATH)
        rec = get_supplier(_DB_PATH, supplier_id)
    except Exception as exc:
        log.error("get_supplier failed id=%s: %s", supplier_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Supplier not found: id={supplier_id}")
    return JSONResponse(_supplier_dict(rec))


@router.post("/", dependencies=[_auth], summary="Create supplier", status_code=201)
async def create_supplier_endpoint(request: Request) -> JSONResponse:
    """Create a new supplier. Body must be a JSON object with at least
    supplier_code, name, and country."""
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")

    errs = validate_supplier(body)
    if errs:
        raise HTTPException(status_code=422, detail={"validation_errors": errs})

    try:
        init_db(_DB_PATH)
        new_id = create_supplier(_DB_PATH, body)
    except ValueError as exc:
        msg = str(exc)
        status = 409 if msg.startswith("DUPLICATE_CODE") else 422
        raise HTTPException(status_code=status, detail=msg)
    except Exception as exc:
        log.error("create_supplier failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")

    rec = get_supplier(_DB_PATH, new_id)
    if rec is None:
        raise HTTPException(status_code=500,
                            detail="create succeeded but record not found on re-read")
    log.info("supplier_create id=%d code=%s", new_id, rec.supplier_code)
    return JSONResponse(status_code=201, content=_supplier_dict(rec))


@router.put("/{supplier_id}", dependencies=[_auth], summary="Update supplier")
async def update_supplier_endpoint(supplier_id: int, request: Request) -> JSONResponse:
    """Update a supplier. Partial payloads merge over existing fields."""
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")

    try:
        init_db(_DB_PATH)
        updated = update_supplier(_DB_PATH, supplier_id, body)
    except ValueError as exc:
        msg = str(exc)
        status = 409 if msg.startswith("DUPLICATE_CODE") else 422
        raise HTTPException(status_code=status, detail=msg)
    except Exception as exc:
        log.error("update_supplier failed id=%s: %s", supplier_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Supplier not found: id={supplier_id}")
    log.info("supplier_update id=%d code=%s", supplier_id, updated.supplier_code)
    return JSONResponse(_supplier_dict(updated))


@router.delete("/{supplier_id}", dependencies=[_auth], summary="Delete supplier",
               status_code=204)
def delete_supplier_endpoint(supplier_id: int) -> Response:
    """Hard delete. 204 on success, 404 if missing."""
    try:
        init_db(_DB_PATH)
        removed = delete_supplier(_DB_PATH, supplier_id)
    except Exception as exc:
        log.error("delete_supplier failed id=%s: %s", supplier_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    if not removed:
        raise HTTPException(status_code=404, detail=f"Supplier not found: id={supplier_id}")
    log.info("supplier_delete id=%d", supplier_id)
    return Response(status_code=204)


# ── B0 (MDOC-cache) — sync from wFirma ────────────────────────────────────────
@router.get("/sync-from-wfirma/preview", dependencies=[_auth],
            summary="Per-row review proposals for wFirma → local suppliers (no write)")
def suppliers_sync_preview_endpoint() -> JSONResponse:
    """Read wFirma contractors and classify per-row proposals.

    No write. Status enum:
      - matched_existing      → safe update on apply
      - new_candidate         → insert on apply
      - needs_operator_review → vat+name match, wfirma_id backfill on confirm
      - skipped_invalid       → cannot be applied

    Each proposal carries the local match (if any) so the dashboard can
    render a review table with View / Edit / Assign / Skip actions.
    """
    try:
        init_db(_DB_PATH)
        from ..services.suppliers_db import compute_proposals
        proposals = compute_proposals(_DB_PATH)
    except Exception as exc:
        log.error("suppliers preview failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail={"ok": False, "status": "fetch_failed",
                    "error": f"{type(exc).__name__}: {exc}"},
        )
    return JSONResponse({
        "ok":        True,
        "mode":      "preview",
        "fetched":   len(proposals),
        "proposals": proposals,
    })


@router.post("/sync-from-wfirma/apply", dependencies=[_auth],
             summary="Apply only the wFirma rows the operator selected")
async def suppliers_sync_apply_endpoint(request: Request) -> JSONResponse:
    """Per-row apply. Body: ``{"wfirma_ids": ["123", "456"]}``.

    Each requested id is reclassified against the live wFirma fetch and
    the local DB, then only that row is written. Flag-gated by
    ``WFIRMA_SYNC_SUPPLIERS_ALLOWED``.

    Skipped-invalid proposals are never applied — the response surfaces
    them in ``proposals`` so the operator sees why.

    Returns the same counts shape as the bulk sync endpoint plus a
    filtered proposals list scoped to the requested ids.
    """
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

    if not settings.wfirma_sync_suppliers_allowed:
        return JSONResponse({
            "ok":               False,
            "mode":             "blocked",
            "dry_run":          True,
            "applied_count":    0,
            "blocking_reasons": [
                "wfirma_sync_suppliers_allowed is false — operator must "
                "enable WFIRMA_SYNC_SUPPLIERS_ALLOWED to apply"
            ],
        })

    try:
        init_db(_DB_PATH)
        result = sync_from_wfirma(_DB_PATH, dry_run=False, wfirma_ids=wfirma_ids)
    except Exception as exc:
        log.error("suppliers apply failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail={"ok": False, "status": "apply_failed",
                    "error": f"{type(exc).__name__}: {exc}"},
        )

    # Trim proposals to just the requested ids so the response is bounded.
    requested = set(wfirma_ids)
    filtered = [p for p in result.get("proposals", []) if p["wfirma_id"] in requested]
    body_out = {
        "ok":            True,
        "mode":          "write",
        "fetched":       result["fetched"],
        "inserted":      result["inserted"],
        "updated_match": result["updated_match"],
        "backfilled":    result["backfilled"],
        "skipped":       result["skipped"],
        "conflicts":     result["conflicts"],
        "dry_run":       result["dry_run"],
        "applied_count": result["inserted"] + result["updated_match"] + result["backfilled"],
        "proposals":     filtered,
    }
    log.info(
        "suppliers_sync_apply mode=write requested=%d inserted=%d updated=%d backfilled=%d skipped=%d",
        len(requested), body_out["inserted"], body_out["updated_match"],
        body_out["backfilled"], body_out["skipped"],
    )
    return JSONResponse(body_out)


@router.post("/sync-from-wfirma", dependencies=[_auth],
             summary="Pull wFirma contractors into local suppliers (read wFirma only)")
def suppliers_sync_from_wfirma_endpoint(
    write: bool = Query(False, description="true → apply; false → dry-run preview"),
) -> JSONResponse:
    """Read-only against wFirma. Pulls contractors via wfirma_client and
    upserts them into the local suppliers table. No wFirma write.

    - Dedup rules: by wfirma_id (primary); by (vat_id+name) fallback for
      legacy rows; new rows inserted with deterministic supplier_code.
    - Default (write=false): dry-run preview, no local mutation.
    - write=true requires settings.wfirma_sync_suppliers_allowed.
    - Returns {fetched, inserted, updated_match, backfilled, skipped,
      conflicts, dry_run, blocked?, examples}.
    """
    try:
        init_db(_DB_PATH)
    except Exception as exc:
        log.error("suppliers init_db failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB init error: {exc}")

    # Force dry-run unless explicitly enabled by settings.
    effective_dry_run = True
    blocking_reasons = []
    if write:
        if settings.wfirma_sync_suppliers_allowed:
            effective_dry_run = False
        else:
            blocking_reasons.append(
                "wfirma_sync_suppliers_allowed is false — operator must "
                "enable WFIRMA_SYNC_SUPPLIERS_ALLOWED to apply"
            )

    try:
        result = sync_from_wfirma(_DB_PATH, dry_run=effective_dry_run)
    except Exception as exc:
        log.error("sync_from_wfirma failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail={"ok": False, "status": "fetch_failed",
                    "error": f"{type(exc).__name__}: {exc}"},
        )

    body = {
        "ok":               True,
        "mode":             "write" if (write and not blocking_reasons) else "preview",
        "fetched":          result["fetched"],
        "inserted":         result["inserted"],
        "updated_match":    result["updated_match"],
        "backfilled":       result["backfilled"],
        "skipped":          result["skipped"],
        "conflicts":        result["conflicts"],
        "dry_run":          result["dry_run"],
        "examples":         result.get("examples", []),
        "proposals":        result.get("proposals", []),  # B0 review layer
    }
    if blocking_reasons:
        body["ok"] = False
        body["mode"] = "blocked"
        body["blocking_reasons"] = blocking_reasons
    log.info(
        "suppliers_sync_from_wfirma mode=%s fetched=%d inserted=%d updated=%d backfilled=%d skipped=%d",
        body["mode"], body["fetched"], body["inserted"], body["updated_match"],
        body["backfilled"], body["skipped"],
    )
    return JSONResponse(body)
