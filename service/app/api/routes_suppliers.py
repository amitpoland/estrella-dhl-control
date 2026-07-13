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

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from ..core.config import settings
from ..core.security import require_api_key
from ..core.logging import get_logger
from ..auth.dependencies import require_admin
from ..core.audit import audit_safe
from ..core.role_gate import require_role_or_apikey, MASTER_ADMIN, MASTER_EDITOR
from ..services.suppliers_db import (
    Supplier,
    init_db,
    validate_supplier,
    create_supplier,
    get_supplier,
    get_supplier_by_code,
    list_suppliers,
    update_supplier,
    delete_supplier,
    soft_delete_supplier,
    restore_supplier,
    hard_delete_supplier,
    sync_from_wfirma,
)

log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1/suppliers", tags=["suppliers"])
_auth       = Depends(require_api_key)
_write_auth = Depends(require_role_or_apikey(MASTER_ADMIN, MASTER_EDITOR))
_admin_auth = Depends(require_admin)

_DB_PATH = settings.storage_root / "suppliers.sqlite"


import hmac as _hmac


def _hard_delete_guard(request: Request) -> None:
    """Phase 4B Wave 3b-1 — gate for DELETE ...?hard=true. Flag must be on
    AND caller must hold master_admin (or admin X-API-Key). Same contract as
    the master-data / jewelry guards."""
    if not settings.master_hard_delete_enabled:
        raise HTTPException(
            status_code=409,
            detail=("Hard delete is disabled. Set master_hard_delete_enabled "
                    "to true (admin) to permit permanent removal."),
        )
    key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if settings.api_key and key and _hmac.compare_digest(key.encode("utf-8"), settings.api_key.encode("utf-8")):
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
    raise HTTPException(status_code=403,
                        detail="Hard delete requires master_admin role.")


def _resolve_list_active(v: Optional[str]) -> Optional[bool]:
    """Phase 4B Wave 3b-1 — default supplier list to active-only when the
    ``active`` query param is omitted."""
    parsed = _parse_active_query(v)
    return True if parsed is None else parsed


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
        # B0 supplier deep-enrichment 2026-05-17
        "street":              s.street,
        "city":                s.city,
        "postal_code":         s.postal_code,
        "contact_mobile":      s.contact_mobile,
        "bank_account":        s.bank_account,
        "last_wfirma_sync_at": s.last_wfirma_sync_at,
        "wfirma_sync_source":  s.wfirma_sync_source,
        "deleted_at":          s.deleted_at,
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
    active:  Optional[str] = Query(None,
        description="omit = active-only (default); 'false' = inactive only; 'true' = active only"),
    limit:   int           = Query(200, ge=1, le=1000),
) -> JSONResponse:
    """List suppliers, most-recently-updated first.

    Phase 4B Wave 3b-1: default to active-only when ``active`` is omitted.
    """
    try:
        init_db(_DB_PATH)
        records = list_suppliers(_DB_PATH,
                                 active=_resolve_list_active(active),
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


@router.post("/", dependencies=[_write_auth], summary="Create supplier", status_code=201)
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
    audit_safe("suppliers", "create", new_id,
               request=request, before=None, after=rec)
    return JSONResponse(status_code=201, content=_supplier_dict(rec))


@router.put("/{supplier_id}", dependencies=[_write_auth], summary="Update supplier")
async def update_supplier_endpoint(supplier_id: int, request: Request) -> JSONResponse:
    """Update a supplier. Partial payloads merge over existing fields."""
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")

    init_db(_DB_PATH)
    before = get_supplier(_DB_PATH, supplier_id)
    try:
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
    audit_safe("suppliers", "update", supplier_id,
               request=request, before=before, after=updated)
    return JSONResponse(_supplier_dict(updated))


@router.delete("/{supplier_id}", dependencies=[_write_auth],
               summary="Delete supplier (soft-delete by default; ?hard=true for permanent)",
               status_code=204)
def delete_supplier_endpoint(
    supplier_id: int, request: Request,
    hard: bool = Query(False, description="Permanent removal; requires master_admin + flag"),
) -> Response:
    init_db(_DB_PATH)
    before = get_supplier(_DB_PATH, supplier_id)
    if before is None:
        raise HTTPException(status_code=404, detail=f"Supplier not found: id={supplier_id}")
    if hard:
        _hard_delete_guard(request)
        try:
            removed = hard_delete_supplier(_DB_PATH, supplier_id)
        except Exception as exc:
            log.error("hard_delete_supplier failed id=%s: %s", supplier_id, exc, exc_info=True)
            raise HTTPException(status_code=500, detail=f"DB error: {exc}")
        if not removed:
            raise HTTPException(status_code=404, detail=f"Supplier not found: id={supplier_id}")
        log.info("supplier_hard_delete id=%d", supplier_id)
        audit_safe("suppliers", "hard_delete", supplier_id,
                   request=request, before=before, after=None)
        return Response(status_code=204)
    # Soft-delete (default).
    try:
        removed = soft_delete_supplier(_DB_PATH, supplier_id)
    except Exception as exc:
        log.error("soft_delete_supplier failed id=%s: %s", supplier_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    if not removed:
        raise HTTPException(status_code=404, detail=f"Supplier not found: id={supplier_id}")
    log.info("supplier_soft_delete id=%d", supplier_id)
    audit_safe("suppliers", "delete", supplier_id,
               request=request, before=before, after=None)
    return Response(status_code=204)


@router.post("/{supplier_id}/restore", dependencies=[_write_auth],
             summary="Restore a soft-deleted supplier")
def restore_supplier_endpoint(supplier_id: int, request: Request) -> JSONResponse:
    init_db(_DB_PATH)
    before = get_supplier(_DB_PATH, supplier_id)
    if before is None:
        raise HTTPException(status_code=404, detail=f"Supplier not found: id={supplier_id}")
    if not restore_supplier(_DB_PATH, supplier_id):
        raise HTTPException(status_code=404, detail=f"Supplier not found: id={supplier_id}")
    after = get_supplier(_DB_PATH, supplier_id)
    log.info("supplier_restore id=%d", supplier_id)
    audit_safe("suppliers", "restore", supplier_id,
               request=request, before=before, after=after)
    return JSONResponse(_supplier_dict(after))


# ── CSV import / export (Wave 5) ──────────────────────────────────────────────
_CSV_MAX_BYTES = 5 * 1024 * 1024  # 5 MB upload ceiling


@router.get("/export/csv", dependencies=[_auth],
            summary="Export suppliers as CSV (injection-safe, UTF-8 BOM)")
def suppliers_export_csv(
    active: Optional[bool] = Query(None, description="Filter; omit = active only"),
    country: Optional[str] = Query(None),
    limit: int = Query(10000, ge=1, le=100000),
) -> Response:
    from ..services import master_csv
    init_db(_DB_PATH)
    rows = [_supplier_dict(s) for s in
            list_suppliers(_DB_PATH, active=active, country=country, limit=limit)]
    body = master_csv.rows_to_csv(rows, master_csv.supplier_columns())
    from datetime import datetime, timezone
    fname = f"suppliers_export_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return Response(
        content=body, media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache", "Expires": "0",
        },
    )


@router.post("/import/csv", dependencies=[_write_auth],
             summary="Import suppliers from CSV (dry-run by default; ?commit=true to apply)")
async def suppliers_import_csv(
    request: Request,
    file: UploadFile = File(...),
    commit: bool = Query(False, description="false = preview only; true = apply upserts"),
) -> JSONResponse:
    """Upsert suppliers by ``supplier_code``. Preview (default) reports what
    WOULD happen; commit applies via the existing create/update writers. Rows
    are validated with ``validate_supplier``; unknown/system columns are ignored;
    empty cells never blank stored values."""
    fname = (file.filename or "").lower()
    ctype = (file.content_type or "").lower()
    if not (fname.endswith(".csv") or "csv" in ctype or ctype in
            ("application/vnd.ms-excel", "application/octet-stream", "text/plain")):
        raise HTTPException(status_code=422, detail="Upload must be a .csv file")
    raw = await file.read()
    if len(raw) > _CSV_MAX_BYTES:
        raise HTTPException(status_code=413, detail="CSV exceeds 5 MB limit")

    from ..services import master_csv
    init_db(_DB_PATH)
    writable = master_csv.supplier_import_writable()
    try:
        parsed = master_csv.parse_csv(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse CSV: {exc}")

    created = updated = 0
    rejected: list = []
    for line, row in parsed:
        data = master_csv.project_writable(row, writable)
        code = data.get("supplier_code")
        if not code:
            rejected.append({"row": line, "reason": "missing supplier_code"})
            continue
        existing = get_supplier_by_code(_DB_PATH, code)
        merged = {**({} if existing is None else _supplier_dict(existing)), **data}
        errs = validate_supplier(merged)
        if errs:
            rejected.append({"row": line, "reason": "; ".join(errs)})
            continue
        if not commit:
            if existing:
                updated += 1
            else:
                created += 1
            continue
        try:
            if existing is not None:
                update_supplier(_DB_PATH, int(existing.id), data)
                updated += 1
            else:
                create_supplier(_DB_PATH, data)
                created += 1
        except ValueError as exc:
            rejected.append({"row": line, "reason": str(exc)})
        except Exception as exc:
            log.error("supplier csv import row=%d failed: %s", line, exc, exc_info=True)
            rejected.append({"row": line, "reason": f"db error: {exc}"})

    result = {
        "mode": "commit" if commit else "preview",
        "committed": bool(commit),
        "total_rows": len(parsed),
        "created": created, "updated": updated, "skipped": len(rejected),
        "rejected": rejected,
    }
    if commit:
        audit_safe("suppliers", "csv_import", "-", request=request,
                   before=None, after={k: result[k] for k in
                                       ("total_rows", "created", "updated", "skipped")})
    return JSONResponse(result)


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


@router.post("/sync-from-wfirma/apply", dependencies=[_admin_auth],
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

    # B0 semantic fix (2026-05-16): Save/Assign writes to the LOCAL
    # suppliers master only. No wFirma write occurs here. The legacy
    # WFIRMA_SYNC_SUPPLIERS_ALLOWED flag protected an outbound wFirma
    # write path that this endpoint does NOT perform, so its gate is not
    # relevant — operator's authenticated click + X-API-Key are sufficient.
    # The flag remains in place for the bulk /api/v1/suppliers/sync-from-wfirma
    # endpoint (which is reserved for a future full-batch operator action).

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

    # B0 supplier deep-enrichment 2026-05-17 — for each successfully-applied
    # id, deep-fetch the wFirma contractor detail and fill empty
    # supplier_master enrichment columns (street/city/postal_code/
    # contact_mobile/bank_account). Fill-when-empty COALESCE protects
    # operator-set local values. Per-row failure is non-fatal — the
    # identity row already exists by this point.
    requested = set(wfirma_ids)
    deep_filled = 0
    deep_errors: List[Dict[str, Any]] = []
    try:
        from ..services.customer_master_db import (   # C-2b V7 reroute
            lookup_wfirma_contractor as _cmd_lookup_contractor,
        )
        from ..services.suppliers_db import upsert_supplier_identity_from_wfirma
        for p in result.get("proposals", []):
            wfid = p.get("wfirma_id")
            if not wfid or wfid not in requested:
                continue
            # Only enrich rows the apply actually wrote (skipped_invalid /
            # needs_operator_review never touch the DB).
            if p.get("status") in ("skipped_invalid", "needs_operator_review"):
                continue
            try:
                cd = _cmd_lookup_contractor(wfid)  # C-2b V7
                if not cd.ok:
                    continue
                # Compose a single-line address fallback from non-empty parts.
                addr_parts = [s for s in (cd.street, cd.zip, cd.city, cd.country) if s]
                upsert_supplier_identity_from_wfirma(
                    _DB_PATH,
                    wfirma_id=wfid,
                    name=cd.name or p.get("name", ""),
                    country=(cd.country or p.get("country", "")),
                    vat_id=(cd.nip or p.get("vat_id") or None),
                    street=cd.street or None,
                    city=cd.city or None,
                    postal_code=cd.zip or None,
                    contact_email=cd.email or None,
                    contact_phone=cd.phone or None,
                    contact_mobile=cd.mobile or None,
                    bank_account=cd.account_number or None,
                    address_fallback=", ".join(addr_parts) if addr_parts else None,
                )
                deep_filled += 1
            except Exception as exc:
                log.warning("supplier deep-fetch failed for wfid=%s: %s", wfid, exc)
                deep_errors.append({"wfirma_id": wfid, "error": str(exc)})
    except Exception as exc:
        # The deep-fetch layer is best-effort — never escalate to a 5xx.
        log.warning("supplier deep-fetch wrapper error: %s", exc)

    # Trim proposals to just the requested ids so the response is bounded.
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
        "deep_filled":   deep_filled,
        "deep_errors":   deep_errors,
        "proposals":     filtered,
    }
    log.info(
        "suppliers_sync_apply mode=write requested=%d inserted=%d updated=%d backfilled=%d skipped=%d deep_filled=%d",
        len(requested), body_out["inserted"], body_out["updated_match"],
        body_out["backfilled"], body_out["skipped"], deep_filled,
    )
    return JSONResponse(body_out)


@router.post("/sync-from-wfirma", dependencies=[_admin_auth],
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
