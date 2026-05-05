"""
proposal_engine.py — Builds a unified proposal list for the decision engine.

Pulls from three sources, in priority order:
  1. audit["action_proposals"] where status="pending_review"
     → priority "high" (operator review needed)
  2. agency SLA follow-up — auto-generated when agency path is active,
     SAD/PZC not yet received, and >= 3 days have elapsed since forward
     → priority "high", source "agency_sla"
  3. batch_readiness.overall.next_step
     → priority "medium" (structural guidance from readiness layer)

Each proposal in the returned list has:
  action      : str       — human-readable action label
  reason      : str       — why this action is needed
  priority    : str       — "high" | "medium" | "low"
  next_step   : str | None
  source      : str       — "action_proposal" | "agency_sla" | "batch_readiness"
  type        : str | None — proposal type key (None for readiness-sourced)
  proposal_id : str | None — audit proposal ID (None for readiness-sourced)
"""
from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings

log = logging.getLogger(__name__)

# Map proposal type → readable action label
_TYPE_LABELS: Dict[str, str] = {
    "dhl_followup":              "Send DHL follow-up",
    "dhl_dsk_request":           "Send DSK reply to DHL",
    "dhl_dsk_transfer":          "Send DSK transfer to DHL",
    "agency_followup":           "Send agency follow-up",
    "agency_document_forward":   "Forward documents to agency",
    "duty_payment_followup":     "Follow up on duty payment",
    "missing_document_request":  "Request missing documents",
    "service_invoice_followup":  "Follow up on service invoice",
    "tracking_lookup":           "Run public tracking lookup",
    "carrier_description_reply": "Send carrier description reply",
}


_AGENCY_FORWARD_EVENTS = frozenset({"agency_email_sent", "agency_email_queued"})
_AGENCY_SLA_DAYS       = 3


def _agency_forwarded_ts(audit: Dict[str, Any]) -> Optional[str]:
    """Return the ISO timestamp when the agency email was first sent/queued.

    Checks (in order):
      1. audit["agency_reply_package"]["built_at"] or ["sent_at"]
      2. audit["timeline"] events with type in _AGENCY_FORWARD_EVENTS
    Returns None when agency forward cannot be confirmed from the audit.
    """
    pkg = audit.get("agency_reply_package") or {}
    ts  = pkg.get("built_at") or pkg.get("sent_at")
    if ts:
        return ts
    for ev in (audit.get("timeline") or []):
        if ev.get("event") in _AGENCY_FORWARD_EVENTS:
            return ev.get("ts")
    return None


def _has_pending_agency_followup(audit: Dict[str, Any]) -> bool:
    """True if a pending_review agency_followup proposal already exists."""
    for p in (audit.get("action_proposals") or []):
        if p.get("type") == "agency_followup" and p.get("status") == "pending_review":
            return True
    return False


def _sad_received(audit: Dict[str, Any]) -> bool:
    """True if SAD/PZC has already been received or imported."""
    return bool(
        audit.get("sad_imported_ts")
        or audit.get("sad_received_ts")
        or audit.get("sad_imported")
        or audit.get("customs_clearance_complete")
    )


def _add_agency_sla_proposal_if_needed(
    audit: Dict[str, Any],
    results: List[Dict[str, Any]],
) -> None:
    """Append an agency_followup high-priority proposal when SLA conditions are met.

    Conditions (all must hold):
      1. Agency forward timestamp exists in audit (agency path is active)
      2. SAD/PZC not yet received or imported
      3. At least _AGENCY_SLA_DAYS have elapsed since the agency forward
      4. No existing pending_review agency_followup proposal already queued
    """
    forwarded_ts = _agency_forwarded_ts(audit)
    if not forwarded_ts:
        return

    if _sad_received(audit):
        return

    try:
        sent_dt   = datetime.datetime.fromisoformat(forwarded_ts.replace("Z", "+00:00"))
        now       = datetime.datetime.now(datetime.timezone.utc)
        days_since = (now - sent_dt).total_seconds() / 86400.0
    except Exception as exc:
        log.debug("agency_sla ts parse error: %s", exc)
        return

    if days_since < _AGENCY_SLA_DAYS:
        return

    if _has_pending_agency_followup(audit):
        return

    results.append({
        "action":      _TYPE_LABELS["agency_followup"],
        "reason":      "Agency response overdue: SAD/PZC not received",
        "priority":    "high",
        "next_step":   "Send follow-up to Agencja Celna Spedycja for SAD/PZC",
        "source":      "agency_sla",
        "type":        "agency_followup",
        "proposal_id": None,
    })


def _load_audit(batch_id: str) -> Optional[Dict[str, Any]]:
    """Load audit.json for batch_id.  Returns None on any read error."""
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / batch_id / "audit.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception as exc:
                log.warning("proposal_engine audit read error batch=%s: %s", batch_id, exc)
    return None


def generate(batch_id: str) -> List[Dict[str, Any]]:
    """
    Build and return a priority-ordered proposal list for batch_id.

    Returns an empty list if no proposals are found.
    """
    results: List[Dict[str, Any]] = []

    # ── Source 1: pending action proposals ───────────────────────────────────
    audit = _load_audit(batch_id)
    if audit:
        for p in (audit.get("action_proposals") or []):
            if p.get("status") != "pending_review":
                continue
            prop_type = p.get("type", "")
            results.append({
                "action":     _TYPE_LABELS.get(prop_type, prop_type.replace("_", " ")),
                "reason":     p.get("reason", "Pending review"),
                "priority":   "high",
                "next_step":  None,
                "source":     "action_proposal",
                "proposal_id": p.get("proposal_id"),
                "type":       prop_type,
            })

    # ── Source 3: agency SLA follow-up ───────────────────────────────────────
    if audit:
        _add_agency_sla_proposal_if_needed(audit, results)

    # ── Source 2: batch readiness next_step ───────────────────────────────────
    try:
        from ..services.batch_readiness import get_batch_readiness
        br = get_batch_readiness(batch_id)
        overall = br.get("overall") or {}
        step = overall.get("next_step")
        if step:
            results.append({
                "action":      step,
                "reason":      "Readiness gate not met",
                "priority":    "medium",
                "next_step":   step,
                "source":      "batch_readiness",
                "type":        None,
                "proposal_id": None,
            })
    except Exception as exc:
        log.warning("proposal_engine batch_readiness error batch=%s: %s", batch_id, exc)

    return results
