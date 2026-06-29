"""
Phase 2B — wFirma snapshot → proforma enrichment.

Matches SNAPSHOTTED events to proforma_drafts by wfirma_proforma_id,
reads three fields from snapshot dedicated columns (not parsed_json),
and writes via the single approved write path: write_postposting_enrichment().

State transitions written to wfirma_processing.db:
    SNAPSHOTTED → MATCHED → ENRICHED → COMPLETED    (happy path)
    SNAPSHOTTED → MATCHED → ENRICHMENT_FAILED        (write/read failure)
    SNAPSHOTTED → UNMATCHED                          (no draft found — valid terminal)

Called exclusively from wfirma_webhook_scheduler._run_enrichment_tick().
Never raises — all exceptions produce ENRICHMENT_FAILED.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def _find_draft_id(links_db: Path, object_id: str) -> Optional[int]:
    """
    Return proforma_drafts.id where wfirma_proforma_id = object_id, or None.
    Never raises.
    """
    try:
        with sqlite3.connect(str(links_db)) as conn:
            row = conn.execute(
                "SELECT id FROM proforma_drafts WHERE wfirma_proforma_id = ?",
                (str(object_id),),
            ).fetchone()
        return int(row[0]) if row else None
    except Exception as exc:
        log.warning("enrichment: draft lookup error object_id=%s: %s", object_id, exc)
        return None


def _read_snapshot_fields(proc_db: Path, event_id: str) -> Optional[dict]:
    """
    Read the three enrichment fields from dedicated snapshot columns.

    Uses issue_date / payment_due / payment_method columns directly —
    not parsed_json — so the values are the same ones the snapshot processor
    already validated and stored.  Returns None only if the snapshot row
    is missing entirely.
    """
    try:
        with sqlite3.connect(str(proc_db)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT issue_date, payment_due, payment_method "
                "FROM wfirma_invoice_snapshots WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "wfirma_issue_date":     row["issue_date"],
            "wfirma_payment_due":    row["payment_due"],
            "wfirma_payment_method": row["payment_method"],
        }
    except Exception as exc:
        log.warning("enrichment: snapshot read error event_id=%s: %s", event_id, exc)
        return None


def enrich_snapshot(
    *,
    event_id: str,
    object_id: str,
    proc_db: Path,
    links_db: Path,
    now: str,
) -> str:
    """
    Attempt to enrich a single SNAPSHOTTED event.

    Writes the processing-state machine transitions to proc_db and the
    three enrichment fields to links_db (via write_postposting_enrichment).

    Returns the terminal state string — one of:
      "COMPLETED"          matched + three fields written
      "UNMATCHED"          no proforma draft found (valid terminal, no retry)
      "ENRICHMENT_FAILED"  read or write failure after a match was found
    """
    from .wfirma_processing_db import set_state

    # ── Match ─────────────────────────────────────────────────────────────────
    draft_id = _find_draft_id(links_db, object_id)

    if draft_id is None:
        set_state(proc_db, event_id, "UNMATCHED", extra={"unmatched_at": now})
        log.info(
            "enrichment: UNMATCHED event_id=%s object_id=%s (no proforma draft)",
            event_id, object_id,
        )
        return "UNMATCHED"

    set_state(proc_db, event_id, "MATCHED", extra={"matched_at": now})

    # ── Read snapshot ─────────────────────────────────────────────────────────
    fields = _read_snapshot_fields(proc_db, event_id)
    if fields is None:
        set_state(
            proc_db, event_id, "ENRICHMENT_FAILED",
            extra={"last_error": "snapshot_fields_missing", "failed_at": now},
        )
        log.error(
            "enrichment: ENRICHMENT_FAILED event_id=%s — snapshot row missing",
            event_id,
        )
        return "ENRICHMENT_FAILED"

    # ── Write (only approved path) ────────────────────────────────────────────
    try:
        from .proforma_invoice_link_db import write_postposting_enrichment
        write_postposting_enrichment(
            links_db,
            draft_id,
            wfirma_issue_date=fields["wfirma_issue_date"],
            wfirma_payment_due=fields["wfirma_payment_due"],
            wfirma_payment_method=fields["wfirma_payment_method"],
        )
    except Exception as exc:
        set_state(
            proc_db, event_id, "ENRICHMENT_FAILED",
            extra={"last_error": str(exc)[:500], "failed_at": now},
        )
        log.error(
            "enrichment: ENRICHMENT_FAILED event_id=%s object_id=%s draft_id=%s: %s",
            event_id, object_id, draft_id, exc,
        )
        return "ENRICHMENT_FAILED"

    # ── Complete ──────────────────────────────────────────────────────────────
    set_state(proc_db, event_id, "ENRICHED",   extra={"enriched_at":  now})
    set_state(proc_db, event_id, "COMPLETED",  extra={"completed_at": now})
    log.info(
        "enrichment: COMPLETED event_id=%s object_id=%s draft_id=%s",
        event_id, object_id, draft_id,
    )
    return "COMPLETED"
