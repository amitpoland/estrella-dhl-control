"""
wFirma webhook diagnostics endpoint (Phase 2A.2).

Endpoint
--------
  GET /api/v1/webhooks/wfirma/status
      Read-only operational view of the wFirma webhook pipeline.
      Returns service version, scheduler heartbeat, queue state,
      snapshot totals, and recent dead-letter events.

Security
--------
  Session-cookie auth (get_current_user).

Constraints
-----------
  - Read-only: zero writes to any table.
  - No business-table reads (proforma_drafts, wfirma.db, customer master).
  - No schema changes.
  - No scheduler logic changes.

Version
-------
  Set PZ_VERSION environment variable to the deployed git SHA (e.g. "c3f1229a")
  so the endpoint reflects the running code version. Falls back to "unknown".
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..auth.dependencies import get_current_user

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks-wfirma"])

TICK_INTERVAL_SECONDS = 30

# Written by .claude/deploy/Deploy-PZ.ps1 — the sole writer, from the config key
# `version_file`. Pinned by service/tests/test_deploy_authority.py. Two levels above app/:
#   production: C:\PZ\version.txt  (parents[2] of C:\PZ\app\api\<file>)
_SHA_FILE = Path(__file__).parents[2] / "version.txt"


# ── helpers ────────────────────────────────────────────────────────────────────


def _get_service_version() -> str:
    """Return deployed SHA via priority chain: PZ_VERSION env → git_sha.txt → 'unknown'."""
    v = os.environ.get("PZ_VERSION")
    if v:
        return v
    try:
        sha = _SHA_FILE.read_text(encoding="utf-8").strip()
        if sha:
            return sha
    except Exception:
        pass
    return "unknown"


def _get_proc_db_path() -> Optional[Path]:
    try:
        from ..services.wfirma_webhook_scheduler import _proc_db_path
        return _proc_db_path
    except Exception:
        return None


def _scheduler_health(running: bool, last_tick_at: Optional[str], interval_seconds: int) -> str:
    if not running:
        return "stopped"
    if last_tick_at is None:
        return "late"
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last_tick_at)).total_seconds()
        return "healthy" if age <= interval_seconds * 2 else "late"
    except Exception:
        return "late"


def _uptime_seconds(started_at: Optional[str]) -> Optional[int]:
    if not started_at:
        return None
    try:
        dt = datetime.fromisoformat(started_at)
        return int((datetime.now(timezone.utc) - dt).total_seconds())
    except Exception:
        return None


def _build_service_block() -> dict:
    """Merge version + scheduler state into a single 'service' section."""
    try:
        from ..services.wfirma_webhook_scheduler import get_scheduler_status
        sched = get_scheduler_status()
    except Exception:
        sched = {"running": False, "started_at": None, "last_tick": None, "next_tick": None}

    started_at   = sched.get("started_at")
    running      = sched.get("running", False)
    last_tick_at = sched.get("last_tick")
    return {
        "version":               _get_service_version(),
        "started_at":            started_at,
        "uptime_seconds":        _uptime_seconds(started_at),
        "scheduler_running":     running,
        "scheduler_health":      _scheduler_health(running, last_tick_at, TICK_INTERVAL_SECONDS),
        "last_tick_at":          last_tick_at,
        "next_tick_at":          sched.get("next_tick"),
        "tick_interval_seconds": TICK_INTERVAL_SECONDS,
    }


def _query_status(db_path: Path) -> dict:
    """
    Run all read queries against wfirma_processing.db.
    Never raises; returns safe defaults on error.
    """
    try:
        from ..services.wfirma_processing_db import get_processing_stats
        stats = get_processing_stats(db_path)
    except Exception:
        stats = {"by_state": {}, "total_snapshots": 0}

    by_state        = stats.get("by_state", {})
    total_snapshots = stats.get("total_snapshots", 0)

    latest_snapshot_at: Optional[str] = None
    recent_dead_letters: list = []
    duplicates = 0

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

            dup_row = conn.execute(
                "SELECT COUNT(*) FROM wfirma_invoice_snapshots WHERE version > 1"
            ).fetchone()
            duplicates = dup_row[0] if dup_row else 0
    except Exception:
        pass

    received      = by_state.get("RECEIVED", 0)
    fetching      = by_state.get("FETCHING", 0)
    retry_pending = by_state.get("RETRY_PENDING", 0)
    snapshotted   = by_state.get("SNAPSHOTTED", 0)
    dead_letter   = by_state.get("DEAD_LETTER", 0)
    matched       = by_state.get("MATCHED", 0)
    enriched      = by_state.get("ENRICHED", 0)
    unmatched     = by_state.get("UNMATCHED", 0)
    completed     = by_state.get("COMPLETED", 0)
    enrichment_failed = by_state.get("ENRICHMENT_FAILED", 0)

    return {
        "queue": {
            "total":              sum(by_state.values()),
            "received":           received,
            "fetching":           fetching,
            "retry_pending":      retry_pending,
            "snapshotted":        snapshotted,
            "matched":            matched,
            "enriched":           enriched,
            "unmatched":          unmatched,
            "completed":          completed,
            "dead_letter":        dead_letter,
            "enrichment_failed":  enrichment_failed,
        },
        "snapshots": {
            "total":              total_snapshots,
            "latest_snapshot_at": latest_snapshot_at,
        },
        "metrics": {
            "webhooks_received":  sum(by_state.values()),
            "snapshots_created":  total_snapshots,
            "duplicates":         duplicates,
            "fetch_failures":     dead_letter,
            "matched":            matched,
            "unmatched":          unmatched,
            "enrichment_success": completed,
            "enrichment_failed":  enrichment_failed,
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

    Returns service version, scheduler heartbeat, processing queue state counts,
    snapshot totals, and the five most recent dead-letter events.
    """
    service = _build_service_block()
    db_path = _get_proc_db_path()

    if db_path is None or not db_path.exists():
        return JSONResponse({
            "service": service,
            "queue": {
                "total": 0, "received": 0, "fetching": 0,
                "retry_pending": 0, "snapshotted": 0,
                "matched": 0, "enriched": 0, "unmatched": 0,
                "completed": 0, "dead_letter": 0, "enrichment_failed": 0,
            },
            "snapshots": {"total": 0, "latest_snapshot_at": None},
            "metrics": {
                "webhooks_received": 0, "snapshots_created": 0, "duplicates": 0,
                "fetch_failures": 0, "matched": 0, "unmatched": 0,
                "enrichment_success": 0, "enrichment_failed": 0,
            },
            "recent_dead_letters": [],
        })

    status = _query_status(db_path)
    status["service"] = service
    return JSONResponse(status)
