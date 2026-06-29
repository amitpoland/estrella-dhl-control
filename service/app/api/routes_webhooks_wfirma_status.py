"""
wFirma webhook diagnostics endpoint (Phase 2A.2).

Endpoint
--------
  GET /api/v1/webhooks/wfirma/status
      Read-only operational view of the wFirma webhook pipeline.
      Returns scheduler heartbeat, queue state, snapshot totals,
      and recent dead-letter events.

Security
--------
  Session-cookie auth (get_current_user). Admin or any authenticated user
  can access; this is internal operational data, not customer data.

Constraints
-----------
  - Read-only: zero writes to any table.
  - No business-table reads (proforma_drafts, wfirma.db, customer master).
  - No schema changes.
  - No scheduler logic changes.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..auth.dependencies import get_current_user

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks-wfirma"])


# ── helpers ────────────────────────────────────────────────────────────────────


def _get_proc_db_path() -> Optional[Path]:
    try:
        from ..services.wfirma_webhook_scheduler import _proc_db_path
        return _proc_db_path
    except Exception:
        return None


def _query_status(db_path: Path) -> dict:
    """
    Run all read queries against wfirma_processing.db.
    Returns structured status data; never raises (returns {} on error).
    """
    try:
        from ..services.wfirma_processing_db import get_processing_stats
        stats = get_processing_stats(db_path)
    except Exception:
        stats = {"by_state": {}, "total_snapshots": 0}

    by_state = stats.get("by_state", {})

    latest_snapshot_at: Optional[str] = None
    recent_dead_letters: list = []

    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row

            row = conn.execute(
                "SELECT fetched_at FROM wfirma_invoice_snapshots "
                "ORDER BY fetched_at DESC LIMIT 1"
            ).fetchone()
            if row:
                latest_snapshot_at = row["fetched_at"]

            dl_rows = conn.execute(
                """
                SELECT event_id, object_id, retry_count, last_error
                FROM wfirma_webhook_processing
                WHERE processing_state = 'DEAD_LETTER'
                ORDER BY dead_letter_at DESC
                LIMIT 5
                """
            ).fetchall()
            recent_dead_letters = [dict(r) for r in dl_rows]
    except Exception:
        pass

    return {
        "queue": {
            "received":      by_state.get("RECEIVED", 0),
            "fetching":      by_state.get("FETCHING", 0),
            "retry_pending": by_state.get("RETRY_PENDING", 0),
            "snapshotted":   by_state.get("SNAPSHOTTED", 0),
            "dead_letter":   by_state.get("DEAD_LETTER", 0),
        },
        "snapshots": {
            "total":              stats.get("total_snapshots", 0),
            "latest_snapshot_at": latest_snapshot_at,
        },
        "recent_dead_letters": recent_dead_letters,
    }


# ── route ──────────────────────────────────────────────────────────────────────


@router.get("/wfirma/status")
def wfirma_webhook_status(
    _user: dict = Depends(get_current_user),
) -> JSONResponse:
    """
    Read-only diagnostics for the wFirma webhook pipeline.

    Returns scheduler heartbeat, processing queue state counts,
    snapshot totals, and the five most recent dead-letter events.
    """
    try:
        from ..services.wfirma_webhook_scheduler import get_scheduler_status
        scheduler = get_scheduler_status()
    except Exception:
        scheduler = {"running": False, "last_tick": None, "next_tick": None}

    db_path = _get_proc_db_path()

    if db_path is None or not db_path.exists():
        return JSONResponse({
            "scheduler": scheduler,
            "queue": {
                "received": 0, "fetching": 0, "retry_pending": 0,
                "snapshotted": 0, "dead_letter": 0,
            },
            "snapshots": {"total": 0, "latest_snapshot_at": None},
            "recent_dead_letters": [],
        })

    status = _query_status(db_path)
    status["scheduler"] = scheduler
    return JSONResponse(status)
