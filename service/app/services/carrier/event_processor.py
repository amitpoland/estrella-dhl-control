"""
CW-1 (MASTER-EXEC-1 Phase 5) — carrier webhook event → tracking-events processor.

Maps stored, correlated ``carrier_events`` rows into the canonical tracking
authority (``tracking_db.shipment_tracking_events``) as one more WRITER through
the existing authority — exactly like the email pipeline. Idempotent by
construction: tracking_db's dedup key includes ``source_ref`` (= webhook
event_id), so replays and re-runs insert nothing new. No processed-marker
column is needed → NO schema change.

Authority boundaries (pinned by tests):
  * writes ONLY via tracking_db.record_events_batch — never carrier booking,
    doc printing, clearance state, finance, or reservation.
  * events with an empty batch_id (uncorrelated) are counted and skipped.
  * direction is "outbound" — carrier-webhook events describe OUR outbound
    client shipments booked through the carrier module.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

#: DHL Unified-Push style status → normalized tracking stage. Tolerant map;
#: unknown types fall through to the uppercased event_type (never a crash).
_STAGE_MAP: Dict[str, str] = {
    "pre-transit": "LABEL_CREATED",
    "pre_transit": "LABEL_CREATED",
    "transit":     "IN_TRANSIT",
    "in transit":  "IN_TRANSIT",
    "in_transit":  "IN_TRANSIT",
    "delivered":   "DELIVERED",
    "failure":     "EXCEPTION",
    "exception":   "EXCEPTION",
    "unknown":     "CARRIER_EVENT",
}

# Last-run summary for the status endpoint (in-memory; resets on restart —
# reported honestly via "since_restart": True). No schema change.
_LAST_RUN: Dict[str, Any] = {}
_LOCK = threading.Lock()


def _carrier_root() -> Path:
    from ...core.config import settings
    return settings.carrier_storage_root or (settings.storage_root / "carrier")


def _event_db_path() -> Path:
    return _carrier_root() / "carrier_events.db"


def _shipment_db_path() -> Path:
    return _carrier_root() / "carrier_shipments.db"


def map_stage(event_type: str) -> str:
    et = (event_type or "").strip().lower()
    return _STAGE_MAP.get(et) or ((event_type or "").strip().upper() or "CARRIER_EVENT")


def _awb_for_batch(batch_id: str) -> str:
    """Read-only: the batch's tracking_ref from the carrier shipment record."""
    sp = _shipment_db_path()
    if not Path(sp).exists():
        return ""
    try:
        with sqlite3.connect(str(sp)) as c:
            row = c.execute(
                "SELECT tracking_ref FROM carrier_shipments "
                "WHERE batch_id=? AND tracking_ref IS NOT NULL "
                "ORDER BY rowid DESC LIMIT 1",
                (batch_id,),
            ).fetchone()
        return str(row[0]) if row and row[0] else ""
    except sqlite3.OperationalError:
        return ""


def run_carrier_event_processing(batch_id: Optional[str] = None) -> Dict[str, Any]:
    """The ONE shared processing function (webhook trigger + Run-Now both call it).

    Reads stored webhook events (all, or one batch), maps them to normalized
    tracking events, and writes through tracking_db. Never raises.
    """
    started = time.time()
    summary: Dict[str, Any] = {
        "batch_id": batch_id or "", "processed": 0, "written": 0,
        "skipped_uncorrelated": 0, "errors": 0, "last_error": "",
    }
    try:
        from .persistence import event_db
        from .. import tracking_db as tdb

        db = _event_db_path()
        rows = (event_db.get_events_for_batch(db, batch_id) if batch_id
                else event_db.list_events(db, limit=1000))
        events = []
        for r in rows:
            summary["processed"] += 1
            bid = str(r.get("batch_id") or "").strip()
            if not bid:
                summary["skipped_uncorrelated"] += 1
                continue
            try:
                payload = json.loads(r.get("payload_json") or "{}")
            except Exception:
                payload = {}
            stage = map_stage(r.get("event_type") or "")
            events.append({
                "batch_id":         bid,
                "awb":              _awb_for_batch(bid),
                "stage":            stage,
                "normalized_stage": stage,
                "event_time":       str(payload.get("timestamp") or r.get("received_at") or ""),
                "source":           "carrier_webhook",
                "source_ref":       str(r.get("event_id") or ""),
                "direction":        "outbound",
                "confidence":       1.0,
                "description":      str(payload.get("description") or "")[:200],
            })
        if events:
            summary["written"] = int(tdb.record_events_batch(events) or 0)
    except Exception as exc:
        summary["errors"] += 1
        summary["last_error"] = f"{type(exc).__name__}: {exc}"
        log.warning("[cw1] carrier event processing failed: %s", exc)

    summary["duration_ms"] = int((time.time() - started) * 1000)
    with _LOCK:
        _LAST_RUN.clear()
        _LAST_RUN.update(summary)
        _LAST_RUN["last_completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return summary


def get_status() -> Dict[str, Any]:
    """Canonical four-questions status envelope (in-memory last run + live counts)."""
    from .persistence import event_db
    counts = {"total": 0, "correlated": 0}
    try:
        counts = event_db.count_events(_event_db_path())
    except Exception:
        pass
    with _LOCK:
        last = dict(_LAST_RUN)
    return {
        "healthy":              (last.get("errors", 0) == 0),
        "running":              False,
        "ever_run":             bool(last),
        "since_restart":        True,
        "last_completed_at":    last.get("last_completed_at"),
        "duration_ms":          last.get("duration_ms", 0),
        "processed":            last.get("processed", 0),
        "written":              last.get("written", 0),
        "skipped_uncorrelated": last.get("skipped_uncorrelated", 0),
        "errors":               last.get("errors", 0),
        "last_error":           last.get("last_error") or None,
        "events_total":         counts["total"],
        "events_correlated":    counts["correlated"],
    }
