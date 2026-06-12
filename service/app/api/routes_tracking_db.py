"""
routes_tracking_db.py — DB-backed tracking event endpoints.

GET  /api/v1/tracking/events/{batch_id}   → events for one batch
GET  /api/v1/tracking/events              → all events (paginated)
POST /api/v1/tracking/events/export       → regenerate master XLSX
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from ..core.config import settings
from ..core.security import require_api_key
from ..services import tracking_db as tdb
from ..services.tracking_master_export import export_master_xlsx, get_master_xlsx_path

router = APIRouter(
    prefix="/api/v1/tracking",
    tags=["tracking-db"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/events/{batch_id}")
def get_batch_events(batch_id: str):
    events = tdb.get_events_for_batch(batch_id)
    return {"batch_id": batch_id, "count": len(events), "events": events}


@router.get("/events")
def get_all_events(
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
):
    events = tdb.get_all_events(limit=limit, offset=offset)
    return {"count": len(events), "limit": limit, "offset": offset, "events": events}


@router.post("/events/export")
def export_events():
    path = get_master_xlsx_path(settings.storage_root)
    try:
        export_master_xlsx(path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"ok": True, "path": str(path), "size_bytes": path.stat().st_size}


@router.get("/events/export/download")
def download_master_xlsx():
    path = get_master_xlsx_path(settings.storage_root)
    if not path.exists():
        try:
            export_master_xlsx(path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
    # Lesson G: regenerable artifact — must never be served from browser cache.
    return FileResponse(
        path=str(path),
        filename="SHIPMENT_TRACKING_MASTER.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
