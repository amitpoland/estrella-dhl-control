"""
Carrier shadow/status routes.

GET /api/v1/carrier/shadow/log
    Returns shadow log entries (metadata only — no request/response JSON blobs).
    Optional ?batch_id=<id> filter. Optional ?limit=<n> (1-500, default 100).

GET /api/v1/carrier/status
    Returns current carrier gate status values from settings.
    Does NOT require carrier to be active — always returns 200.

Auth: X-API-Key header via require_api_key.
No DB writes. No DHL API calls.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ..core.security import require_api_key
from ..services.carrier.persistence import shadow_log_db

router = APIRouter(prefix="/api/v1/carrier", tags=["carrier"])


# ── Dependencies ──────────────────────────────────────────────────────────────


def _get_shadow_log_db_path() -> Path:
    from ..core.config import settings
    root = settings.carrier_storage_root or (settings.storage_root / "carrier")
    root.mkdir(parents=True, exist_ok=True)
    return root / "shadow_log.db"


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/shadow/log")
def get_shadow_log(
    batch_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _auth: None = Depends(require_api_key),
    db_path: Path = Depends(_get_shadow_log_db_path),
) -> JSONResponse:
    shadow_log_db.init_db(db_path)
    entries = shadow_log_db.get_entries(db_path, batch_id=batch_id, limit=limit)
    return JSONResponse({"entries": entries, "count": len(entries)})


@router.get("/status")
def get_carrier_status(
    _auth: None = Depends(require_api_key),
) -> JSONResponse:
    from ..core.config import settings
    return JSONResponse({
        "carrier_api_status": settings.carrier_api_status,
        "carrier_plt_status": settings.carrier_plt_status,
    })


# ── CW-1: carrier webhook event processing (Run Now + status) ─────────────────


@router.post("/events/process")
def process_carrier_events(
    batch_id: Optional[str] = Query(default=None),
    _auth: None = Depends(require_api_key),
) -> JSONResponse:
    """Run Now — map stored carrier webhook events into the tracking authority
    (tracking_db). Idempotent (tracking dedup on source_ref); read-only against
    every other store; no booking / label / customs / finance side-effects."""
    from ..services.carrier.event_processor import run_carrier_event_processing
    return JSONResponse(run_carrier_event_processing(batch_id))


@router.get("/events/status")
def carrier_events_status(
    _auth: None = Depends(require_api_key),
) -> JSONResponse:
    """Four-questions status for the carrier event processor + live event counts."""
    from ..services.carrier.event_processor import get_status
    return JSONResponse(get_status())
