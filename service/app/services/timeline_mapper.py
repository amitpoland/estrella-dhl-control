"""
timeline_mapper.py — Email Type → Timeline Event Mapper
=========================================================
Maps email classification types to timeline event names.
Suggest-only mode: returns suggested events without writing to audit.json.

For actual writing, call timeline.log_event() from the audit update layer.
This module is READ-ONLY — it never writes anything.

Mapping table (from CLEARANCE_AUTOMATION_MASTER_BLUEPRINT.md):

  dhl_arrival       → carrier_arrived
  dhl_cesja_fwd     → dhl_cesja_forwarded
  zc429_notification→ sad_uploaded
  acs_pzc           → pzc_received
  ganther_duty      → duty_note_received
  ganther_payment   → payment_confirmed
  ganther_pzc       → pzc_received (Ganther relay)
  ganther_invoice   → ganther_invoice_received
  fedex_arrival     → carrier_arrived + fedex_cesja_pending
  fedex_cesja_ack   → cesja_submitted
  fedex_dsk         → dsk_received
  vat_deferment_gap → (alert — no direct timeline event, becomes warning)
  fca_complication  → (alert — becomes flag in audit)
  acs_vat_statement → acs_vat_statement_received (route to accounting)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ── Timeline event constants (mirrors core/timeline.py) ──────────────────────

EV_CARRIER_ARRIVED          = "carrier_arrived"
EV_DHL_CESJA_FORWARDED      = "dhl_cesja_forwarded"
EV_SAD_UPLOADED             = "sad_uploaded"
EV_PZC_RECEIVED             = "pzc_received"
EV_DUTY_NOTE_RECEIVED       = "duty_note_received"
EV_PAYMENT_CONFIRMED        = "payment_confirmed"
EV_GANTHER_INVOICE          = "ganther_invoice_received"
EV_CESJA_SUBMITTED          = "cesja_submitted"
EV_DSK_RECEIVED             = "dsk_received"
EV_FEDEX_CESJA_PENDING      = "fedex_cesja_pending"
EV_ACS_VAT_STATEMENT        = "acs_vat_statement_received"
EV_VAT_DEFERMENT_FLAGGED    = "vat_deferment_flagged"
EV_FCA_COMPLICATION         = "fca_complication_detected"
EV_CLEARANCE_STARTED        = "clearance_started"
EV_UNKNOWN_SENDER           = "unknown_sender_detected"


# ── Mapping table ─────────────────────────────────────────────────────────────

# Each entry:
#   email_type → list of (event_name, requires_fields, audit_field_updates)
#
# requires_fields: list of classification result fields that must be present
# audit_field_updates: dict of {audit_key: classification_result_key}

_MAPPING: Dict[str, Dict[str, Any]] = {
    "dhl_arrival": {
        "primary_event":        EV_CARRIER_ARRIVED,
        "carrier":              "DHL",
        "audit_updates": {
            "carrier":                    "carrier",         # "DHL"
            "tracking.arrived_warehouse": True,
            "dhl_ticket":                 "dhl_ticket",
        },
        "sub_event_map": {},
    },
    "dhl_cesja_fwd": {
        "primary_event":        EV_DHL_CESJA_FORWARDED,
        "carrier":              "DHL",
        "audit_updates":        {},
        "sub_event_map":        {},
    },
    "zc429_notification": {
        "primary_event":        EV_SAD_UPLOADED,
        "carrier":              "DHL",
        "audit_updates": {
            "zc429_mrn": "mrn",
        },
        "sub_event_map":        {},
    },
    "acs_pzc": {
        "primary_event":        EV_PZC_RECEIVED,
        "carrier":              "DHL",
        "audit_updates": {
            "duty_amount_pln":         "pln_amount",
            "duty_notice_received_at": "_current_time",
        },
        "sub_event_map": {
            "duty_amount_detected": EV_DUTY_NOTE_RECEIVED,
        },
    },
    "ganther_duty": {
        "primary_event":        EV_DUTY_NOTE_RECEIVED,
        "carrier":              "BOTH",
        "audit_updates": {
            "duty_amount_pln":         "pln_amount",
            "duty_notice_received_at": "_current_time",
        },
        "sub_event_map": {},
    },
    "ganther_payment": {
        "primary_event":        EV_PAYMENT_CONFIRMED,
        "carrier":              "BOTH",
        "audit_updates": {
            "duty_paid_signal_at": "_current_time",
        },
        "sub_event_map":        {},
    },
    "ganther_pzc": {
        "primary_event":        EV_PZC_RECEIVED,
        "carrier":              "BOTH",
        "audit_updates":        {},
        "sub_event_map": {
            "clearance_started": EV_CLEARANCE_STARTED,
        },
    },
    "ganther_invoice": {
        "primary_event":        EV_GANTHER_INVOICE,
        "carrier":              "BOTH",
        "audit_updates": {
            "ganther_invoice_amount_pln": "pln_amount",
        },
        "sub_event_map":        {},
    },
    "fedex_arrival": {
        "primary_event":        EV_CARRIER_ARRIVED,
        "carrier":              "FEDEX",
        "audit_updates": {
            "carrier":          "carrier",   # "FEDEX"
            "fedex_arrival_at": "_current_time",
        },
        "sub_event_map": {
            "cesja_form_attached": EV_FEDEX_CESJA_PENDING,
            "cesja_keyword":       EV_FEDEX_CESJA_PENDING,
        },
    },
    "fedex_cesja_ack": {
        "primary_event":        EV_CESJA_SUBMITTED,
        "carrier":              "FEDEX",
        "audit_updates": {
            "cesja_submitted_at": "_current_time",
        },
        "sub_event_map":        {},
    },
    "fedex_dsk": {
        "primary_event":        EV_DSK_RECEIVED,
        "carrier":              "FEDEX",
        "audit_updates":        {},
        "sub_event_map":        {},
    },
    "acs_vat_statement": {
        "primary_event":        EV_ACS_VAT_STATEMENT,
        "carrier":              "DHL",
        "audit_updates":        {},
        "sub_event_map":        {},
        "route_to_accounting":  True,
    },
    "vat_deferment_gap": {
        "primary_event":        EV_VAT_DEFERMENT_FLAGGED,
        "carrier":              "DHL",
        "audit_updates": {
            "vat_deferment_issue": True,
        },
        "sub_event_map":        {},
        "alert":                "CRITICAL: Contact account@ to renew VAT deferment permission",
    },
    "fca_complication": {
        "primary_event":        EV_FCA_COMPLICATION,
        "carrier":              "FEDEX",
        "audit_updates": {
            "fca_complication": True,
        },
        "sub_event_map":        {},
        "alert":                "Request transport invoice from shipper now",
    },
    "unknown_sender": {
        "primary_event":        EV_UNKNOWN_SENDER,
        "carrier":              "UNKNOWN",
        "audit_updates":        {},
        "sub_event_map":        {},
        "alert":                "Unknown sender — admin review required",
    },
}


# ── Mapper ────────────────────────────────────────────────────────────────────

class TimelineMapping:
    """Result of a timeline mapping operation."""

    def __init__(
        self,
        email_type: str,
        primary_event: str,
        carrier: str,
        suggested_audit_updates: Dict[str, Any],
        additional_events: List[str],
        alert: Optional[str],
        route_to_accounting: bool,
    ):
        self.email_type             = email_type
        self.primary_event          = primary_event
        self.carrier                = carrier
        self.suggested_audit_updates= suggested_audit_updates
        self.additional_events      = additional_events
        self.alert                  = alert
        self.route_to_accounting    = route_to_accounting

    def to_dict(self) -> Dict[str, Any]:
        return {
            "email_type":              self.email_type,
            "primary_event":           self.primary_event,
            "carrier":                 self.carrier,
            "suggested_audit_updates": self.suggested_audit_updates,
            "additional_events":       self.additional_events,
            "alert":                   self.alert,
            "route_to_accounting":     self.route_to_accounting,
        }


def map_email_to_events(
    classification: Dict[str, Any],
) -> Optional[TimelineMapping]:
    """
    Map an email classification result to timeline events.

    SAFE: Returns mapping suggestions only. Never writes to audit.json.

    Args:
        classification: Result dict from email_classifier.classify_email()

    Returns:
        TimelineMapping if actionable, None if do_not_trigger / internal.
    """
    email_type = classification.get("type", "unknown_sender")

    # Skip non-actionable types
    if email_type in ("do_not_trigger", "internal", "unknown_clearance"):
        return None

    mapping_def = _MAPPING.get(email_type)
    if not mapping_def:
        log.debug("timeline_mapper: no mapping for email_type=%s", email_type)
        return None

    # Build suggested audit updates
    audit_updates: Dict[str, Any] = {}
    for audit_key, source in mapping_def.get("audit_updates", {}).items():
        if source == "_current_time":
            from datetime import datetime, timezone
            audit_updates[audit_key] = datetime.now(timezone.utc).isoformat()
        elif source is True or source is False:
            audit_updates[audit_key] = source
        else:
            val = classification.get(source)
            if val is not None:
                audit_updates[audit_key] = val

    # Build additional events from sub_events
    additional_events: List[str] = []
    sub_event_map = mapping_def.get("sub_event_map", {})
    for sub_event in (classification.get("sub_events") or []):
        mapped = sub_event_map.get(sub_event)
        if mapped:
            additional_events.append(mapped)

    return TimelineMapping(
        email_type          = email_type,
        primary_event       = mapping_def["primary_event"],
        carrier             = mapping_def.get("carrier", classification.get("carrier", "UNKNOWN")),
        suggested_audit_updates = audit_updates,
        additional_events   = additional_events,
        alert               = mapping_def.get("alert"),
        route_to_accounting = mapping_def.get("route_to_accounting", False),
    )


def map_batch(classifications: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Map a list of email classifications to timeline events.

    Returns list of mapping dicts for all actionable classifications.
    """
    results = []
    for cls in classifications:
        mapping = map_email_to_events(cls)
        if mapping:
            results.append(mapping.to_dict())
    return results


def get_event_for_type(email_type: str) -> Optional[str]:
    """Return the primary timeline event name for an email type, or None."""
    m = _MAPPING.get(email_type)
    return m["primary_event"] if m else None


def list_all_mappings() -> Dict[str, str]:
    """Return {email_type: primary_event} for all known mappings."""
    return {k: v["primary_event"] for k, v in _MAPPING.items()}
