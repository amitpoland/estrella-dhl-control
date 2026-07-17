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
_links_db_path: Optional[Path] = None   # proforma_links.db — Phase 2B enrichment target
_cm_db_path: Optional[Path] = None      # customer_master.sqlite — Phase 3 customer sync
_payment_db_path: Optional[Path] = None           # payment_state.db — Phase 4A payment sync
_contractor_poll_db_path: Optional[Path] = None   # contractor_poll.db — Phase 3B contractor scan
_last_tick_at: Optional[str] = None     # set at the start of every tick
_started_at: Optional[str] = None       # set once when the scheduler starts


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_scheduler_status() -> dict:
    """
    Return a snapshot of scheduler state for the diagnostics endpoint.
    Safe to call from any thread; never raises.
    """
    running = _scheduler is not None and getattr(_scheduler, "running", False)
    next_tick: Optional[str] = None
    if running:
        try:
            job = _scheduler.get_job("wfirma_webhook_processor")
            if job and job.next_run_time:
                next_tick = job.next_run_time.isoformat()
        except Exception:
            pass
    return {
        "running":    running,
        "started_at": _started_at,
        "last_tick":  _last_tick_at,
        "next_tick":  next_tick,
    }


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
              XML + store a snapshot for each. On success → SNAPSHOTTED.
              On failure → FAILED + retry_count++; after MAX_RETRIES → DEAD_LETTER.
    """
    global _last_tick_at
    _last_tick_at = _now_utc()

    # ── Step 0: series dictionary refresh (stale-triggered, cooldown-gated) ──
    # Runs BEFORE the events-DB guard so a webhook-storage problem can never
    # starve the dictionary refresh. Internally failure-isolated and cheap:
    # the staleness/cooldown pre-check is in-memory only.
    _run_series_refresh_tick()

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
    # NOTE: Steps 3 and 4 must run even when pending is empty — terminal-state
    # events (COMPLETED / UNMATCHED / ENRICHMENT_FAILED) have nothing left for
    # Step 2 but still need enrichment (Phase 2B) and customer sync (Phase 3).
    pending = get_processable_events(_proc_db_path)

    if pending:
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
                    _proc_db_path, event_id, "SNAPSHOTTED",
                    extra={
                        "fetched_at": now,
                        "snapshotted_at": now,
                    },
                )
                log.info(
                    "wfirma_scheduler: snapshotted event_id=%s object_id=%s",
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

    # ── Step 3: enrich SNAPSHOTTED events (Phase 2B) ──────────────────────────
    _run_enrichment_tick()

    # ── Step 4: sync customer from terminal events (Phase 3) ──────────────────
    _run_customer_sync_tick()

    # ── Step 5: snapshot payments per contractor (Phase 4A) ───────────────────
    _run_payment_sync_tick()

    # ── Step 6: proactive contractor master sync from wFirma list (Phase 3B) ──
    _run_contractor_poll_tick()

    # ── Step 7: goods stock-change webhook sync (Wave 4 C-8a) ─────────────────
    _run_stock_sync_tick()


def _run_series_refresh_tick() -> None:
    """
    Series dictionary refresh step — called at the start of every tick.

    Re-fetches the wFirma series catalog (read-only ``series/find``) through
    the ONE shared refresh function
    ``wfirma_dictionary_cache.refresh_from_wfirma`` (also used by the startup
    bootstrap and the operator Run-Now endpoint) whenever the cache is stale
    (>24 h TTL, or baseline/error state after an NSSM restart) and the retry
    cooldown has elapsed.

    - Gated by SERIES_BOOTSTRAP_ENABLED — the same flag that gates the
      startup live fetch, so one flag governs all autonomous wFirma fetches.
    - Failure-isolated: never raises into the scheduler tick.
    - No wFirma writes. No DB writes — in-memory cache + series_cache.json only.
    """
    try:
        from ..core.config import settings
        if not settings.series_bootstrap_enabled:
            return
        from . import wfirma_dictionary_cache as wdc
        if not wdc.should_attempt_scheduled_refresh():
            return
        result = wdc.refresh_from_wfirma(trigger="scheduler")
        src = result.get("source_state", {})
        # Count only live entries (the baseline "— Default series" placeholder
        # has id="" and would otherwise inflate the count by one).
        inv_count = len([e for e in result.get("invoice_series", []) if e.get("id")])
        pro_count = len([e for e in result.get("proforma_series", []) if e.get("id")])
        log.info(
            "wfirma_scheduler: series_refresh invoice=%s proforma=%s "
            "invoice_count=%d proforma_count=%d",
            src.get("invoice_series"), src.get("proforma_series"),
            inv_count, pro_count,
        )
    except Exception as exc:
        log.warning("wfirma_scheduler: series refresh failed (non-fatal): %s", exc)


def _run_enrichment_tick() -> None:
    """
    Phase 2B enrichment step — called at the end of every processing tick.

    Picks up SNAPSHOTTED events and attempts to enrich each one by matching
    snapshot.object_id to proforma_drafts.wfirma_proforma_id and writing
    the three approved fields via write_postposting_enrichment().

    State transitions (MATCHED / ENRICHED / COMPLETED / UNMATCHED) are
    written to wfirma_processing.db by enrich_snapshot().
    """
    if _proc_db_path is None or _links_db_path is None:
        return

    from .wfirma_processing_db import get_snapshotted_events
    from .wfirma_enrichment_processor import enrich_snapshot

    pending = get_snapshotted_events(_proc_db_path)
    if not pending:
        return

    now = _now_utc()
    for row in pending:
        event_id:  str           = row["event_id"]
        object_id: Optional[str] = row.get("object_id") or ""

        result = enrich_snapshot(
            event_id=event_id,
            object_id=object_id,
            proc_db=_proc_db_path,
            links_db=_links_db_path,
            now=now,
        )
        log.info(
            "wfirma_scheduler: enrichment=%s event_id=%s object_id=%s",
            result, event_id, object_id,
        )


def _run_customer_sync_tick() -> None:
    """
    Phase 3 customer sync step — called at the end of every processing tick.

    Picks up terminal events (COMPLETED / UNMATCHED / ENRICHMENT_FAILED) whose
    invoice snapshot exists but customer sync hasn't run yet, fetches the
    contractor profile from wFirma, and upserts approved fields into
    customer_master (fill-when-empty semantics via upsert_identity_only).

    customer_synced_at is set on success or intentional skip.
    customer_sync_attempts is incremented on failure; events that hit
    MAX_CUSTOMER_SYNC_ATTEMPTS are excluded from future ticks.
    """
    if _proc_db_path is None or _cm_db_path is None:
        return

    from .wfirma_processing_db import get_customer_sync_pending_events
    from .wfirma_customer_sync_processor import sync_customer_from_snapshot

    pending = get_customer_sync_pending_events(_proc_db_path)
    if not pending:
        return

    now = _now_utc()
    for row in pending:
        event_id: str = row["event_id"]

        result = sync_customer_from_snapshot(
            event_id=event_id,
            proc_db=_proc_db_path,
            cm_db=_cm_db_path,
            now=now,
        )
        log.info(
            "wfirma_scheduler: customer_sync=%s event_id=%s",
            result, event_id,
        )


def _run_payment_sync_tick() -> None:
    """
    Phase 4A payment snapshot step — called at the end of every processing tick.

    Reads known contractor_ids from customer_master, determines which are due
    for sync (cooldown: 1 hour per contractor), fetches wFirma payments for
    each, and stores immutable snapshots in payment_state.db.

    No writes to business tables. No modifications to existing Track B stages.
    """
    if _payment_db_path is None or _cm_db_path is None:
        return

    try:
        with sqlite3.connect(str(_cm_db_path)) as conn:
            rows = conn.execute(
                "SELECT bill_to_contractor_id FROM customer_master "
                "WHERE bill_to_contractor_id IS NOT NULL AND bill_to_contractor_id != ''"
            ).fetchall()
    except Exception as exc:
        log.warning("wfirma_scheduler: cannot read customer_master for payment sync: %s", exc)
        return

    contractor_ids = [r[0] for r in rows]
    if not contractor_ids:
        return

    from .wfirma_payment_db import get_contractors_due_for_sync, mark_contractor_synced
    from .wfirma_payment_sync_processor import sync_payments_for_contractor

    now = _now_utc()
    due = get_contractors_due_for_sync(_payment_db_path, contractor_ids, now)
    if not due:
        return

    for cid in due:
        new_count, existing_count, error = sync_payments_for_contractor(
            contractor_id=cid,
            payment_db=_payment_db_path,
            now=now,
        )
        mark_contractor_synced(_payment_db_path, cid, now, new_count)
        log.info(
            "wfirma_scheduler: payment_sync contractor_id=%s new=%d existing=%d error=%s",
            cid, new_count, existing_count, error,
        )


def _run_contractor_poll_tick() -> None:
    """
    Phase 3B contractor scan step — called at the end of every processing tick.

    Paginates through the full wFirma contractor list and upserts every
    contractor into customer_master (fill-when-empty semantics).  Only
    runs when the 6-hour cooldown has elapsed since the last completed scan.

    No writes to wfirma_processing.db or any Track B stage.
    No modifications to existing webhook pipeline stages.
    """
    if _contractor_poll_db_path is None or _cm_db_path is None:
        return

    from .wfirma_contractor_poll_db import (
        is_scan_due, mark_scan_started, mark_scan_completed
    )
    from .wfirma_contractor_poll_processor import scan_contractors_into_master

    now = _now_utc()
    if not is_scan_due(_contractor_poll_db_path, now):
        return

    mark_scan_started(_contractor_poll_db_path, now)
    total, new_count, updated_count, error = scan_contractors_into_master(
        cm_db=_cm_db_path,
        now=now,
    )
    mark_scan_completed(
        _contractor_poll_db_path, now,
        contractor_count=total,
        new_count=new_count,
        updated_count=updated_count,
        error=error,
    )
    log.info(
        "wfirma_scheduler: contractor_poll total=%d new=%d updated=%d error=%s",
        total, new_count, updated_count, error,
    )


def _run_stock_sync_tick() -> None:
    """
    Wave 4 C-8a goods stock-change sync step — called at the end of every tick.

    Routes stored webhook events through wfirma_stock_sync_processor. Inert until
    OI-10 supplies the stock-change payload contract (see the processor): today no
    event is recognized as a stock-change and no reads/writes occur. Wired here so
    that only the processor's BLOCKED-BY-OI-10 sections need filling later.

    Idempotency relies on the existing wfirma_webhook_events.event_id PRIMARY KEY
    (storage-level). No new state table, no schema change, no wFirma writes.
    """
    if _events_db_path is None:
        return

    from .wfirma_stock_sync_processor import sync_stock_from_event

    try:
        with sqlite3.connect(str(_events_db_path)) as conn:
            rows = conn.execute(
                "SELECT event_id, event_type, payload_json FROM wfirma_webhook_events"
            ).fetchall()
    except Exception as exc:
        log.warning("wfirma_scheduler: cannot read events DB for stock sync: %s", exc)
        return

    now = _now_utc()
    recognized = 0
    for event_id, event_type, payload_json in rows:
        result = sync_stock_from_event(
            event_id=event_id,
            event_type=event_type,
            payload_json=payload_json or "{}",
            now=now,
        )
        if result != "skipped_not_stock_change":
            recognized += 1

    if recognized:
        log.info(
            "wfirma_scheduler: stock_sync recognized=%d (deferred — BLOCKED BY OI-10)",
            recognized,
        )


def start_wfirma_scheduler(storage_root: Path) -> None:
    """
    Initialise the processing DB and start the APScheduler background job.
    Call once during FastAPI lifespan startup. Non-fatal if APScheduler is absent.
    """
    global _scheduler, _events_db_path, _proc_db_path, _links_db_path, _cm_db_path, _payment_db_path, _contractor_poll_db_path

    _events_db_path  = Path(storage_root) / "wfirma_webhook_events.db"
    _proc_db_path    = Path(storage_root) / "wfirma_processing.db"
    _links_db_path   = Path(storage_root) / "proforma_links.db"
    _cm_db_path      = Path(storage_root) / "customer_master.sqlite"
    _payment_db_path          = Path(storage_root) / "payment_state.db"
    _contractor_poll_db_path  = Path(storage_root) / "contractor_poll.db"

    from .wfirma_processing_db import init_db
    init_db(_proc_db_path)

    from .wfirma_payment_db import init_payment_db
    init_payment_db(_payment_db_path)

    from .wfirma_contractor_poll_db import init_contractor_poll_db
    init_contractor_poll_db(_contractor_poll_db_path)

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        log.error(
            "wfirma_scheduler: apscheduler not installed — webhook processing disabled. "
            "Install with: pip install 'apscheduler>=3.10.0'"
        )
        return

    global _started_at
    _started_at = _now_utc()

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
