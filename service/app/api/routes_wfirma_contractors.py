"""
Phase 3B business API — wFirma contractor scan.

POST /api/v1/wfirma/contractors/scan
    Trigger a full wFirma contractor master scan immediately.
    Calls the same scan_contractors_into_master() used by the scheduler.
    Does NOT enforce the 6-hour cooldown — this is a manual "Run Now" trigger.
    Records scan state in contractor_poll.db (shared with the scheduler).

GET /api/v1/wfirma/contractors/scan/status
    Return canonical 11-field status shape from contractor_poll.db.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..core.config import settings
from ..core.logging import get_logger
from ..core.security import require_api_key

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/wfirma", tags=["wfirma"])
_auth  = Depends(require_api_key)

_POLL_DB = settings.storage_root / "contractor_poll.db"
_CM_DB   = settings.storage_root / "customer_master.sqlite"


def _canonical_status(state: dict) -> dict:
    """Map get_scan_state() dict to the canonical 11-field status shape."""
    started   = state.get("last_scan_started_at")
    completed = state.get("last_scan_completed_at")

    running = False
    if started:
        if not completed:
            running = True
        else:
            try:
                running = started > completed
            except Exception:
                pass

    duration_ms: Optional[int] = None
    if started and completed:
        try:
            s = datetime.fromisoformat(started)
            c = datetime.fromisoformat(completed)
            duration_ms = max(0, int((c - s).total_seconds() * 1000))
        except Exception:
            pass

    processed  = state.get("last_scan_contractor_count") or 0
    created    = state.get("last_scan_new_count") or 0
    updated    = state.get("last_scan_updated_count") or 0
    skipped    = max(0, processed - created - updated)
    last_error = state.get("last_scan_error")

    return {
        "healthy":           last_error is None,
        "running":           running,
        "last_started_at":   started,
        "last_completed_at": completed,
        "duration_ms":       duration_ms,
        "processed":         processed,
        "created":           created,
        "updated":           updated,
        "skipped":           skipped,
        "errors":            1 if last_error else 0,
        "last_error":        last_error,
    }


@router.post("/contractors/scan", dependencies=[_auth],
             summary="Trigger a full wFirma contractor master scan (Phase 3B)")
def trigger_contractor_scan() -> JSONResponse:
    """Run the full contractor scan immediately, bypassing the 6-hour cooldown.

    Calls the same scan_contractors_into_master() function used by the scheduler.
    Records scan state in contractor_poll.db so the scheduler sees the updated
    last_completed_at and honours its own cooldown correctly after a manual run.
    """
    from ..services.wfirma_contractor_poll_db import (
        init_contractor_poll_db,
        mark_scan_started,
        mark_scan_completed,
        get_scan_state,
    )
    from ..services.wfirma_contractor_poll_processor import scan_contractors_into_master

    init_contractor_poll_db(_POLL_DB)
    now = datetime.now(timezone.utc).isoformat()
    mark_scan_started(_POLL_DB, now)

    total, new_count, updated_count, error = scan_contractors_into_master(
        cm_db=_CM_DB, now=now
    )

    completed_at = datetime.now(timezone.utc).isoformat()
    mark_scan_completed(
        _POLL_DB, completed_at,
        contractor_count=total,
        new_count=new_count,
        updated_count=updated_count,
        error=error,
    )

    state = get_scan_state(_POLL_DB)
    return JSONResponse({"ok": True, "scan": _canonical_status(state)})


@router.get("/contractors/scan/status", dependencies=[_auth],
            summary="Return contractor scan status (Phase 3B)")
def get_contractor_scan_status() -> JSONResponse:
    """Return the canonical 11-field status shape from contractor_poll.db."""
    from ..services.wfirma_contractor_poll_db import (
        init_contractor_poll_db,
        get_scan_state,
    )

    init_contractor_poll_db(_POLL_DB)
    state = get_scan_state(_POLL_DB)
    return JSONResponse({"ok": True, "scan": _canonical_status(state)})
