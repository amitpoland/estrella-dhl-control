"""
wFirma webhook background scheduler (Phase 2A.1).

APScheduler BackgroundScheduler polls for RECEIVED / RETRY_PENDING processing
rows every 30 seconds, fetches XML from wFirma, and stores immutable snapshots.

Lifecycle
---------
start_wfirma_scheduler(storage_root) — call once in FastAPI lifespan startup.
stop_wfirma_scheduler()              — call in FastAPI lifespan shutdown.

Constraints
-----------
- No business-table writes.
- No wFirma writes.
- Idempotent: duplicate event_id never creates a duplicate snapshot.
- Max 1 concurrent instance (max_instances=1 on the job).
- Startup is non-fatal: if APScheduler is missing, logs an error and returns.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_scheduler = None          # module-level singleton (BackgroundScheduler)
_events_db_path: Optional[Path] = None
_proc_db_path: Optional[Path] = None


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_payload(event_id: str) -> str:
    """Read payload_json from the immutable events DB for a single event."""
    if _events_db_path is None:
        return "{}"
    try:
        with sqlite3.connect(str(_events_db_path)) as conn:
            row = conn.execute(
                "SELECT payload_json FROM wfirma_webhook_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return row[0] if row else "{}"
    except Exception:
        return "{}"


def _run_processing_tick() -> None:
    """
    Single scheduler tick.

    Step 1 — register: for every event in wfirma_webhook_events that has no
              processing row yet, create one (INSERT OR IGNORE, state=RECEIVED).

    Step 2 — process: find RECEIVED / RETRY_PENDING rows and attempt to fetch
              XML + store a snapshot for each. On success → COMPLETED.
              On failure → FAILED + retry_count++; after MAX_RETRIES → DEAD_LETTER.
    """
    if _events_db_path is None or _proc_db_path is None:
        return

    from .wfirma_processing_db import (
        ensure_processing_row,
        get_processable_events,
        set_state,
        increment_retry,
        mark_dead_letter,
        mark_retry_pending,
        MAX_RETRIES,
    )
    from .wfirma_snapshot_processor import InvoiceSnapshotProcessor, _extract_object_id

    now = _now_utc()

    # ── Step 1: register untracked events ─────────────────────────────────────
    try:
        with sqlite3.connect(str(_events_db_path)) as conn:
            event_rows = conn.execute(
                "SELECT event_id, payload_json, received_at FROM wfirma_webhook_events"
            ).fetchall()
    except Exception as exc:
        log.warning("wfirma_scheduler: cannot read events DB: %s", exc)
        return

    for event_id, payload_json, received_at in event_rows:
        object_id = _extract_object_id(payload_json or "{}")
        ensure_processing_row(
            _proc_db_path,
            event_id,
            object_id,
            received_at or now,
        )

    # ── Step 2: process pending rows ──────────────────────────────────────────
    pending = get_processable_events(_proc_db_path)
    if not pending:
        return

    processor = InvoiceSnapshotProcessor(_proc_db_path)

    for row in pending:
        event_id: str = row["event_id"]
        object_id: Optional[str] = row.get("object_id")
        current_retry: int = row.get("retry_count", 0)

        if not object_id:
            log.warning(
                "wfirma_scheduler: no object_id for event_id=%s (retry %d)",
                event_id, current_retry,
            )
            new_count = increment_retry(
                _proc_db_path, event_id, "no_object_id_in_payload", now
            )
            if new_count >= MAX_RETRIES:
                mark_dead_letter(_proc_db_path, event_id, now)
                log.error(
                    "wfirma_scheduler: dead_letter event_id=%s (no object_id after %d retries)",
                    event_id, MAX_RETRIES,
                )
            else:
                mark_retry_pending(_proc_db_path, event_id)
            continue

        payload_json = _read_payload(event_id)

        try:
            set_state(
                _proc_db_path, event_id, "FETCHING",
                extra={
                    "fetch_pending_at": now,
                    "fetching_at": now,
                    "last_attempted_at": now,
                },
            )

            processor.process(event_id, object_id, payload_json, now)

            set_state(
                _proc_db_path, event_id, "COMPLETED",
                extra={
                    "fetched_at": now,
                    "snapshotted_at": now,
                    "completed_at": now,
                },
            )
            log.info(
                "wfirma_scheduler: completed event_id=%s object_id=%s",
                event_id, object_id,
            )

        except Exception as exc:
            log.warning(
                "wfirma_scheduler: failed event_id=%s object_id=%s: %s",
                event_id, object_id, exc,
            )
            new_count = increment_retry(_proc_db_path, event_id, str(exc), now)
            if new_count >= MAX_RETRIES:
                mark_dead_letter(_proc_db_path, event_id, now)
                log.error(
                    "wfirma_scheduler: dead_letter event_id=%s after %d retries",
                    event_id, MAX_RETRIES,
                )
            else:
                mark_retry_pending(_proc_db_path, event_id)


def start_wfirma_scheduler(storage_root: Path) -> None:
    """
    Initialise the processing DB and start the APScheduler background job.
    Call once during FastAPI lifespan startup. Non-fatal if APScheduler is absent.
    """
    global _scheduler, _events_db_path, _proc_db_path

    _events_db_path = Path(storage_root) / "wfirma_webhook_events.db"
    _proc_db_path   = Path(storage_root) / "wfirma_processing.db"

    from .wfirma_processing_db import init_db
    init_db(_proc_db_path)

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        log.error(
            "wfirma_scheduler: apscheduler not installed — webhook processing disabled. "
            "Install with: pip install 'apscheduler>=3.10.0'"
        )
        return

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        _run_processing_tick,
        trigger="interval",
        seconds=30,
        id="wfirma_webhook_processor",
        max_instances=1,
    )
    _scheduler.start()
    log.info(
        "wfirma_scheduler: started (interval=30s) events_db=%s proc_db=%s",
        _events_db_path,
        _proc_db_path,
    )


def stop_wfirma_scheduler() -> None:
    """Gracefully shut down the scheduler. Non-fatal."""
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
            log.info("wfirma_scheduler: stopped")
        except Exception as exc:
            log.warning("wfirma_scheduler: stop failed: %s", exc)
        _scheduler = None
