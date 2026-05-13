"""
timeline.py — Per-shipment event timeline
==========================================
Every action appends a structured event to audit.json["timeline"].
Event shape:
  {
    "ts":             ISO8601 string,
    "event":          str,
    "trigger_source": str,
    "actor":          str,
    "detail":         dict | None,
  }
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── Standard event names ──────────────────────────────────────────────────────
EV_BATCH_CREATED      = "batch_created"
EV_INVOICE_UPLOADED   = "invoice_uploaded"
EV_SAD_UPLOADED       = "sad_uploaded"
EV_AWB_UPLOADED       = "awb_uploaded"
EV_PROCESSING_STARTED = "processing_started"
EV_PZ_GENERATED       = "pz_generated"
EV_PZ_BLOCKED         = "pz_blocked"

# ── Inventory lifecycle mirror events ──────────────────────────────────────────
# Best-effort, per-batch summary events written to audit.json["timeline"] each
# time an existing inventory_state_engine producer runs.  They mirror the
# transitions the engine actually performed but live nowhere except the audit
# timeline — they do not gate, drive, or duplicate any production logic.
EV_INVENTORY_PURCHASE_TRANSIT_SEEDED   = "inventory_purchase_transit_seeded"
EV_INVENTORY_WAREHOUSE_STOCK_PROMOTED  = "inventory_warehouse_stock_promoted"
EV_INVENTORY_TRANSITION_FAILED         = "inventory_transition_failed"
EV_DHL_EMAIL_RECEIVED     = "dhl_email_received"
EV_DHL_INBOX_SCANNED      = "dhl_inbox_scanned"
EV_CLEARANCE_STARTED      = "clearance_started"
EV_DSK_GENERATED          = "dsk_generated"
EV_DESCRIPTION_READY      = "description_ready"
EV_REPLY_APPROVED         = "reply_approved"
EV_DHL_PRECHECK_COMPLETED = "dhl_precheck_completed"
EV_ERROR              = "error"
EV_STATUS_CHANGE      = "status_change"
EV_WFIRMA_CLIPBOARD   = "wfirma_clipboard_generated"
EV_WFIRMA_JSON        = "wfirma_json_generated"
EV_SHIPMENT_ARCHIVED             = "shipment_archived"
EV_SHIPMENT_RESTORED             = "shipment_restored"
EV_SHIPMENT_PERMANENTLY_DELETED  = "shipment_permanently_deleted"
EV_SHIPMENT_RECHECKED            = "shipment_rechecked"

# ── Clearance workflow events ──────────────────────────────────────────────────
EV_CLEARANCE_DECISION    = "clearance_decision_made"    # decision engine computed + stored
EV_DSK_TRANSFER_SENT     = "dsk_transfer_sent"          # DSK reply queued to DHL
EV_AGENCY_EMAIL_SENT     = "agency_email_sent"          # agency package queued
EV_DHL_FOLLOWUP_SENT     = "dhl_followup_sent"          # cowork: DHL follow-up queued
EV_AGENCY_FOLLOWUP_SENT  = "agency_followup_sent"       # cowork: agency follow-up queued
EV_SHIPMENT_ARRIVED      = "shipment_arrived_warsaw"    # cowork: tracking confirmed arrival

# ── Email-trigger clearance events (real-world flow) ──────────────────────────
# These fire when email_monitor classifies an inbound email as a clearance signal.
# Maps to TRIGGER_1..7 in AUTOMATION_TRIGGER_RULES.md
EV_CESJA_RECEIVED     = "cesja_received"          # T1: DHL cesja email ingested
EV_ZC429_RECEIVED     = "zc429_received"          # T2: AIS ZC429 customs clearance confirmed
EV_PZC_RECEIVED       = "pzc_received"            # T3: ACS PZC + duty notice email
EV_GANTHER_PZC_SENT   = "ganther_pzc_sent"        # T4: Ganther released shipment to DHL
EV_DSK_RECEIVED       = "dsk_received"            # DSK transfer confirmed received by DHL
EV_DUTY_NOTE_RECEIVED = "duty_note_received"      # T5: Ganther duty payment request (PLN amount)
EV_PAYMENT_CONFIRMED  = "payment_confirmed"       # T6: Ganther "dzieki, płaci się"
EV_GANTHER_INVOICE    = "ganther_invoice_received" # T7: Ganther service invoice

# ── Action proposal lifecycle events ──────────────────────────────────────────
EV_ACTION_PROPOSAL_CREATED  = "action_proposal_created"   # proposal written to audit
EV_ACTION_PROPOSAL_APPROVED = "action_proposal_approved"  # admin approved proposal
EV_ACTION_PROPOSAL_REJECTED = "action_proposal_rejected"  # admin rejected proposal
EV_EMAIL_QUEUED             = "email_queued"              # email added to queue after approval
EV_EMAIL_SENT               = "email_sent"                # queue worker confirmed delivery
EV_EMAIL_FAILED             = "email_failed"              # delivery attempt failed

# ── Proactive DHL customs dispatch (P2 Slice A) ──────────────────────────────
EV_DHL_PROACTIVE_DISPATCH_REQUESTED = "dhl_proactive_dispatch_requested"  # operator created proposal
EV_DHL_PROACTIVE_DISPATCH_SENT      = "dhl_proactive_dispatch_sent"       # email queued at queue time
EV_DHL_PROACTIVE_DISPATCH_FAILED    = "dhl_proactive_dispatch_failed"     # queue_email raised; proposal stays approved

# ── Tracking events ────────────────────────────────────────────────────────────
EV_TRACKING_PUBLIC_LOOKUP   = "tracking_public_lookup_completed"  # operator/cowork reported public result
EV_TRACKING_UPDATED         = "tracking_updated"                  # batch tracking block written (any source)

# ── AI Bridge events ───────────────────────────────────────────────────────────
EV_AI_BRIDGE_TASK_CREATED   = "ai_bridge_task_created"           # task file created for external AI
EV_AI_BRIDGE_RESULT_RECEIVED = "ai_bridge_result_received"       # result imported from external AI

# ── Packing list events ────────────────────────────────────────────────────────
EV_PACKING_LIST_EXTRACTED     = "packing_list_extracted"       # packing PDF/XLSX parsed + rows stored
EV_PACKING_MATCHED_TO_INVOICE = "packing_matched_to_invoice"   # packing rows matched to invoice lines

_MAX_EVENTS           = 200


def log_event(
    audit_path:     Path,
    event:          str,
    trigger_source: str,
    actor:          str = "system",
    detail:         Optional[dict] = None,
) -> None:
    """Append an event to audit.json["timeline"]. Non-fatal — swallows all errors."""
    try:
        if not audit_path.exists():
            log.warning("timeline.log_event: audit not found at %s", audit_path)
            return
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        timeline: list = audit.setdefault("timeline", [])

        # Build event and assert integrity before appending
        _ts = datetime.now(timezone.utc).isoformat()
        _entry: dict = {
            "ts":             _ts,
            "event":          event,
            "trigger_source": trigger_source,
            "actor":          actor or "system",
            "detail":         detail,
        }
        # Integrity guard — ts must always be present
        if "ts" not in _entry or not _entry["ts"]:
            raise ValueError(
                f"Timeline event integrity failure: 'ts' missing or empty "
                f"(event={event}, source={trigger_source})"
            )

        timeline.append(_entry)
        if len(timeline) > _MAX_EVENTS:
            audit["timeline"] = timeline[-_MAX_EVENTS:]
        tmp = audit_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(audit, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(audit_path)
    except Exception as exc:
        log.warning("timeline.log_event failed (non-fatal): %s", exc)


def get_timeline(audit_path: Path) -> list:
    """Return the timeline list from audit.json, or [] if missing."""
    try:
        if not audit_path.exists():
            return []
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        return audit.get("timeline", [])
    except Exception:
        return []
