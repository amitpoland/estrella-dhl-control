"""
routes_warehouse.py — Physical movement tracking API.

Endpoints
---------
  POST /api/v1/warehouse/scan
       Record a scan (RECEIVE / MOVE / PICK / PACK / DISPATCH / RETURN).
       Updates inventory_current_location and appends an event.

  GET  /api/v1/warehouse/inventory/{scan_code}
       Current location + full event history for one scannable item.

  POST /api/v1/warehouse/locations
       Declare or update a location (tray / bin / shelf).

  GET  /api/v1/warehouse/locations
       List declared locations.

  GET  /api/v1/warehouse/locations/{code}/inventory
       List every item currently at a location.

Movement is PHYSICAL ONLY. Never alters invoice / PZ / wFirma values.

Scanning (POST /scan) is OPTIONAL traceability — it is never a prerequisite for
receipt, location, inventory, sample/return, packing, dispatch, or manual workflows.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..core.logging import get_logger
from ..core.security import require_api_key, require_api_key_privileged
from ..auth.dependencies import require_permission
from ..services import warehouse_db as wdb

log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1/warehouse", tags=["warehouse"])
_auth       = Depends(require_api_key)             # reads: X-API-Key or any valid session
_auth_write = Depends(require_api_key_privileged)
_perm_wh_scan = Depends(require_permission("warehouse.scan"))


# ── Pydantic models ──────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    scan_code:   str = Field(..., min_length=1)
    action:      str = Field(..., min_length=1)
    to_location: str = ""
    operator:    str = ""
    note:        str = ""
    batch_id:    str = ""   # optional — scope lookup to a specific batch


class LocationRequest(BaseModel):
    location_code: str = Field(..., min_length=1)
    location_type: str = "tray"
    warehouse:     str = "MAIN"
    row_no:        str = ""
    tray_id:       str = ""
    description:   str = ""
    active:        bool = True


# NOTE: the former GET /config route (which returned the shared admin key to the
# browser) was REMOVED — it distributed an admin-equivalent shared secret to any
# authenticated session (SEC-WAREHOUSE-APIKEY-1). The scanner UI now authenticates
# by session cookie; warehouse writes require a write-capable role below.


# ── POST /scan ───────────────────────────────────────────────────────────────

@router.post("/scan", dependencies=[_auth_write, _perm_wh_scan])
def warehouse_scan(req: ScanRequest) -> JSONResponse:
    """
    OPTIONAL event-recording endpoint. A physical scan is *traceability only* and
    is NOT a prerequisite for receipt confirmation, location declaration, inventory,
    sample-out, return, packing, dispatch, or any manual workflow — those endpoints
    operate independently and never call record_scan.

    Records a scan event and returns the updated current-location row.
    404 if the scan_code is unknown to packing_lines.
    400 if the action verb isn't allowed.
    """
    action = (req.action or "").upper().strip()
    if action not in wdb.ALLOWED_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action {req.action!r}. Allowed: {sorted(wdb.ALLOWED_ACTIONS)}",
        )

    try:
        result = wdb.record_scan(
            scan_code   = req.scan_code,
            action      = action,
            to_location = req.to_location,
            operator    = req.operator,
            note        = req.note,
            batch_id    = req.batch_id or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"scan_code {req.scan_code!r} not found in packing_lines. "
                   f"Verify the barcode matches a packed inventory item.",
        )

    history = wdb.get_movement_history(req.scan_code)
    return JSONResponse({
        "ok":               True,
        "scan_code":        req.scan_code,
        "action":           action,
        "current_location": result.get("current_location"),
        "current_status":   result.get("current_status"),
        "unknown_location": result.get("unknown_location", False),
        "updated_at":       result.get("updated_at"),
        "event_count":      len(history),
        "inventory":        result,
    })


# ── GET /inventory/{scan_code} ───────────────────────────────────────────────

@router.get("/inventory/{scan_code:path}", dependencies=[_auth])
def get_inventory(scan_code: str) -> JSONResponse:
    """Return current location + full event history for one item."""
    current = wdb.get_current_location(scan_code)
    if not current:
        # Fall back: maybe the item exists in packing_lines but was never scanned
        pl = wdb.find_packing_line_by_scan_code(scan_code)
        if not pl:
            raise HTTPException(
                status_code=404,
                detail=f"scan_code {scan_code!r} not found in packing_lines.",
            )
        return JSONResponse({
            "scan_code":    scan_code,
            "current":      None,
            "history":      [],
            "packing_line": {
                "batch_id":     pl.get("batch_id"),
                "product_code": pl.get("product_code"),
                "design_no":    pl.get("design_no"),
                "quantity":     pl.get("quantity"),
                "invoice_no":   pl.get("invoice_no"),
            },
            "note": "Item known to packing_lines but never scanned yet.",
        })

    history = wdb.get_movement_history(scan_code)
    return JSONResponse({
        "scan_code": scan_code,
        "current":   current,
        "history":   history,
    })


# ── Locations ────────────────────────────────────────────────────────────────

@router.post("/locations", dependencies=[_auth_write, _perm_wh_scan])
def create_location(req: LocationRequest) -> JSONResponse:
    loc_id = wdb.upsert_location(
        location_code = req.location_code,
        location_type = req.location_type,
        warehouse     = req.warehouse,
        row_no        = req.row_no,
        tray_id       = req.tray_id,
        description   = req.description,
        active        = req.active,
    )
    return JSONResponse({
        "ok":            True,
        "id":            loc_id,
        "location_code": req.location_code,
    })


@router.get("/locations", dependencies=[_auth])
def list_locations(active_only: bool = True) -> JSONResponse:
    locs = wdb.list_locations(active=active_only if active_only else None)
    return JSONResponse({"count": len(locs), "locations": locs})


@router.get("/locations/{location_code:path}/inventory", dependencies=[_auth])
def location_inventory(location_code: str) -> JSONResponse:
    items = wdb.get_inventory_at_location(location_code)
    return JSONResponse({
        "location_code": location_code,
        "count":         len(items),
        "items":         items,
    })
