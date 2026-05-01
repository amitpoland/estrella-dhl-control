"""
routes_action_proposals.py — Admin-approval pipeline for cowork action proposals.

Every outbound email in the clearance workflow goes through this pipeline:
    1. Cowork detects a trigger → creates proposal (status=pending_review)
    2. Admin reviews proposal in dashboard
    3. Admin approves → status=approved, approved_by recorded
    4. Admin clicks Queue → email added to queue (status=queued), email_id written
    5. Timeline records every state transition

HARD CONSTRAINTS (never relax):
  - NO auto-send.  queue_email() is NEVER called without an approved + approved_by record.
  - NO proposal can queue without approved status.
  - NO email can be queued without at least one recipient.
  - Attachment paths are validated before queuing.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core.config import settings
from ..core import timeline as tl
from ..utils.io import write_json_atomic

router = APIRouter(prefix="/api/v1/action-proposals", tags=["action_proposals"])

_OUTPUTS = settings.storage_root / "outputs"

# ── Value guard constants (from clearance_decision.py) ───────────────────────
_THRESHOLD_USD = 2_500.0


# ── Request models ─────────────────────────────────────────────────────────────

class ApproveBody(BaseModel):
    approved_by: str
    note: Optional[str] = None


class RejectBody(BaseModel):
    rejected_by: str
    reason: str


# ── Internal helpers ──────────────────────────────────────────────────────────

def _audit_path(batch_id: str) -> Path:
    return _OUTPUTS / batch_id / "audit.json"


def _load_audit(batch_id: str) -> Dict[str, Any]:
    p = _audit_path(batch_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"Batch {batch_id!r} not found")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not read audit: {exc}")


def _save_audit(batch_id: str, audit: Dict[str, Any]) -> None:
    p = _audit_path(batch_id)
    write_json_atomic(p, audit)


def _get_proposal(audit: Dict[str, Any], proposal_id: str) -> Dict[str, Any]:
    for p in (audit.get("action_proposals") or []):
        if p.get("proposal_id") == proposal_id:
            return p
    raise HTTPException(status_code=404, detail=f"Proposal {proposal_id!r} not found")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Safety guards ─────────────────────────────────────────────────────────────

def _assert_can_queue(proposal: Dict[str, Any], audit: Dict[str, Any]) -> None:
    """
    Raise HTTPException if the proposal cannot safely be queued.

    Guards:
      G1  status must be "approved"
      G2  approved_by must be present and non-empty
      G3  draft.to must contain at least one recipient
      G4  all declared attachment paths must exist on disk
      G5  batch_id in proposal must match audit batch_id
      G6  high-value shipments must not queue carrier_description_reply
      G7  low-value shipments must not queue dhl_dsk_transfer (without override)
      G8  rejected proposals cannot be queued
    """
    status       = proposal.get("status", "")
    approved_by  = (proposal.get("approved_by") or "").strip()
    draft        = proposal.get("draft") or {}
    prop_type    = proposal.get("type", "")
    prop_batch   = proposal.get("batch_id", "")
    audit_batch  = audit.get("batch_id", "")

    # G0 — non-email types (cowork/manual tasks) can never queue an email
    if prop_type in _NON_EMAIL_TYPES:
        raise HTTPException(
            status_code=422,
            detail={
                "code":    "invalid_action",
                "message": (
                    f"Proposal type '{prop_type}' is a cowork/manual task — "
                    "queue_email is not applicable. "
                    "Use POST /api/v1/tracking/{batch_id}/update to record the result."
                ),
            },
        )

    # G8 — rejected proposals are terminal
    if status == "rejected":
        raise HTTPException(
            status_code=409,
            detail="Proposal has been rejected and cannot be queued.",
        )

    # G1 — must be approved
    if status != "approved":
        raise HTTPException(
            status_code=409,
            detail=f"Proposal status is '{status}' — must be 'approved' before queuing.",
        )

    # G2 — approved_by required
    if not approved_by:
        raise HTTPException(
            status_code=422,
            detail="Cannot queue: approved_by is missing from proposal.",
        )

    # G3 — must have recipient
    recipients = (draft.get("to") or "").strip()
    if not recipients:
        raise HTTPException(
            status_code=422,
            detail="Cannot queue: email draft has no recipients (draft.to is empty).",
        )

    # G4 — attachments must exist
    for att in (draft.get("attachments") or []):
        path_str = att.get("path") or ""
        if path_str and not Path(path_str).exists():
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Cannot queue: attachment '{att.get('label', path_str)}' "
                    f"not found on disk: {path_str}"
                ),
            )

    # G5 — batch_id match
    if prop_batch and audit_batch and prop_batch != audit_batch:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot queue: proposal batch_id '{prop_batch}' does not match "
                f"audit batch_id '{audit_batch}'."
            ),
        )

    # G6 — high-value: block carrier_description_reply
    dec = audit.get("clearance_decision") or {}
    cif = float(dec.get("total_value_usd") or 0)
    if prop_type == "carrier_description_reply" and cif > _THRESHOLD_USD:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot queue carrier_description_reply: shipment value ${cif:.2f} "
                f"exceeds ${_THRESHOLD_USD:.0f} threshold — use dhl_dsk_transfer instead."
            ),
        )

    # G7 — low-value: block dhl_dsk_transfer without override
    if prop_type == "dhl_dsk_transfer" and 0 < cif <= _THRESHOLD_USD:
        if not proposal.get("override_value_check"):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot queue dhl_dsk_transfer: shipment value ${cif:.2f} "
                    f"is below ${_THRESHOLD_USD:.0f} threshold — "
                    "carrier description reply is the correct path. "
                    "Set override_value_check=true to force."
                ),
            )


# ── Proposal creation (called by cowork) ──────────────────────────────────────

def create_proposal(
    audit:         Dict[str, Any],
    batch_id:      str,
    proposal_type: str,
    reason:        str,
    confidence:    str,
) -> Dict[str, Any]:
    """
    Create an action proposal and write it into audit["action_proposals"].

    Deduplication: if a proposal with the same type is already active
    (status in {pending_review, approved, queued}), return the existing one.

    Returns the proposal dict (new or existing).
    """
    from ..services.action_email_builder import build_email_draft

    proposals: List[Dict[str, Any]] = audit.setdefault("action_proposals", [])

    # Dedup: one active proposal per type
    _active_statuses = {"pending_review", "approved", "queued"}
    for existing in proposals:
        if (existing.get("type") == proposal_type
                and existing.get("status") in _active_statuses):
            return existing

    # Build email draft (pure, no side effects)
    try:
        draft = build_email_draft(proposal_type, audit)
    except Exception as exc:
        draft = {"error": str(exc)}

    proposal: Dict[str, Any] = {
        "proposal_id":  str(uuid.uuid4()),
        "type":         proposal_type,
        "batch_id":     batch_id,
        "status":       "pending_review",
        "reason":       reason,
        "confidence":   confidence,
        "draft":        draft,
        "created_at":   _now(),
        "approved_by":  None,
        "approved_at":  None,
        "rejected_by":  None,
        "rejected_at":  None,
        "reject_reason": None,
        "email_id":     None,
        "queued_at":    None,
        "override_value_check": False,
    }
    proposals.append(proposal)
    return proposal


# ── Trigger → proposal type mapping ──────────────────────────────────────────

_TRIGGER_TO_TYPE: Dict[str, str] = {
    "DSK_MISSING":                      "dhl_followup",
    "DSK_MISSING_FEDEX":                "dhl_followup",
    "SAD_DELAY":                        "agency_followup",
    "DUTY_PAYMENT_PENDING":             "duty_payment_followup",
    "CLEARANCE_OVERDUE":                "agency_followup",
    "GANTHER_RELAY_OVERDUE":            "agency_followup",
    "SLA_DHL_BREACH":                   "dhl_followup",
    "SLA_FEDEX_BREACH":                 "dhl_followup",
    "SLA_GANTHER_BREACH":               "agency_followup",
    "SLA_PAYMENT_BREACH":               "duty_payment_followup",
    # Tracking lookup — cowork/manual task, never an email
    "PUBLIC_TRACKING_LOOKUP_REQUIRED":  "tracking_lookup",
    "TRACKING_LOOKUP_REQUIRED":         "tracking_lookup",
}

# Proposal types that are NEVER email-sendable (cowork/manual tasks only)
_NON_EMAIL_TYPES: frozenset = frozenset({"tracking_lookup"})


def generate_action_proposals(
    audit:       Dict[str, Any],
    batch_id:    str,
    suggestions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Convert cowork suggestions into action proposals in audit["action_proposals"].

    Called in execute mode after detect_triggers(). Each suggestion with a known
    trigger→type mapping gets one proposal (deduplication prevents duplicates).

    Returns list of new proposals created (may be empty if all deduped).
    """
    created: List[Dict[str, Any]] = []
    for sug in suggestions:
        trigger    = sug.get("trigger", "")
        prop_type  = _TRIGGER_TO_TYPE.get(trigger)
        if not prop_type:
            continue
        proposal = create_proposal(
            audit         = audit,
            batch_id      = batch_id,
            proposal_type = prop_type,
            reason        = sug.get("reason", ""),
            confidence    = sug.get("confidence", "medium"),
        )
        # Only count as "created" if it's new (fresh created_at within last 2 seconds)
        if proposal.get("status") == "pending_review":
            from datetime import timezone as _tz
            try:
                age = (datetime.now(timezone.utc) -
                       datetime.fromisoformat(proposal["created_at"])).total_seconds()
                if age < 5:
                    created.append(proposal)
            except Exception:
                created.append(proposal)
    return created


def refresh_proposals(
    audit_path: Path,
    audit:      Dict[str, Any],
    batch_id:   str,
) -> Dict[str, Any]:
    """
    Idempotent proposal refresh driven by detect_triggers.

    For every monitor sweep (and the manual /refresh endpoint):
      - Detect current triggers
      - For each trigger with a known mapping:
          • If pending/approved/queued proposal of that type exists → update last_seen_at
          • Otherwise → create new proposal (pending_review)
      - For each pending_review proposal whose trigger is no longer detected → resolve it
      - Write audit only if something changed
      - Log a timeline event only when the proposal set changes (create or resolve)

    Returns summary dict: {created, updated, resolved, active_trigger_types}

    HARD CONSTRAINTS:
      - Only pending_review proposals are auto-resolved (approved/queued are never auto-resolved)
      - No financial fields are touched
      - approved_by / approved_at / email_id / queued_at are never modified
    """
    from ..agents.cowork_coordinator import detect_triggers

    now_str = _now()
    _active_statuses = {"pending_review", "approved", "queued"}

    suggestions = detect_triggers(audit, batch_id)

    # Map of currently-active trigger codes → proposal types
    active_prop_types: set = set()
    sug_by_type: Dict[str, Dict] = {}
    for sug in suggestions:
        pt = _TRIGGER_TO_TYPE.get(sug.get("trigger", ""))
        if pt:
            active_prop_types.add(pt)
            sug_by_type.setdefault(pt, sug)

    proposals: List[Dict[str, Any]] = audit.setdefault("action_proposals", [])

    created_ids: List[str] = []
    updated_ids: List[str] = []
    resolved_ids: List[str] = []

    # Upsert: update last_seen_at or create new proposal
    for pt, sug in sug_by_type.items():
        existing = next(
            (p for p in proposals
             if p.get("type") == pt and p.get("status") in _active_statuses),
            None,
        )
        if existing:
            existing["last_seen_at"] = now_str
            existing["last_trigger_reason"] = sug.get("reason", "")
            updated_ids.append(existing["proposal_id"])
        else:
            new_p = create_proposal(
                audit         = audit,
                batch_id      = batch_id,
                proposal_type = pt,
                reason        = sug.get("reason", ""),
                confidence    = sug.get("confidence", "medium"),
            )
            new_p["last_seen_at"] = now_str
            created_ids.append(new_p["proposal_id"])

    # Resolve pending_review proposals whose trigger is no longer detected
    for p in proposals:
        if (p.get("status") == "pending_review"
                and p.get("type") not in active_prop_types):
            p["status"] = "resolved"
            p["resolved_at"] = now_str
            p["resolution_reason"] = "trigger_no_longer_detected"
            resolved_ids.append(p["proposal_id"])

    changed = bool(created_ids or resolved_ids)

    if changed or updated_ids:
        write_json_atomic(audit_path, audit)

    if changed:
        try:
            tl.log_event(
                audit_path,
                "action_proposals_refreshed",
                "monitor",
                "active_shipment_monitor",
                detail={
                    "created":  len(created_ids),
                    "resolved": len(resolved_ids),
                },
            )
        except Exception:
            pass

    return {
        "created":              len(created_ids),
        "updated":              len(updated_ids),
        "resolved":             len(resolved_ids),
        "active_trigger_types": sorted(active_prop_types),
    }


# ── Manual refresh endpoint ──────────────────────────────────────────────────

@router.post("/{batch_id}/refresh")
def refresh_proposals_endpoint(batch_id: str) -> Dict[str, Any]:
    """
    Immediately refresh action proposals for one batch.

    Calls detect_triggers → upserts/resolves proposals → returns summary.
    Safe to call repeatedly — fully idempotent.
    """
    audit_p = _audit_path(batch_id)
    if not audit_p.exists():
        raise HTTPException(status_code=404, detail=f"Batch {batch_id!r} not found")
    try:
        audit = json.loads(audit_p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not read audit: {exc}")

    result = refresh_proposals(audit_p, audit, batch_id)
    return {"batch_id": batch_id, **result}


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/{batch_id}")
def list_proposals(batch_id: str) -> Dict[str, Any]:
    """Return all action proposals for a batch."""
    audit = _load_audit(batch_id)
    proposals = audit.get("action_proposals") or []
    return {
        "batch_id":  batch_id,
        "count":     len(proposals),
        "proposals": proposals,
    }


@router.post("/{proposal_id}/approve")
def approve_proposal(proposal_id: str, body: ApproveBody) -> Dict[str, Any]:
    """
    Approve an action proposal.

    Requires: approved_by (non-empty).
    Sets status=approved and logs EV_ACTION_PROPOSAL_APPROVED to timeline.
    """
    if not (body.approved_by or "").strip():
        raise HTTPException(status_code=422, detail="approved_by is required.")

    # Find which batch owns this proposal
    batch_id, audit, proposal = _resolve_proposal(proposal_id)

    if proposal["status"] == "rejected":
        raise HTTPException(status_code=409, detail="Cannot approve a rejected proposal.")
    if proposal["status"] in ("queued", "sent"):
        raise HTTPException(
            status_code=409,
            detail=f"Proposal already in terminal status: {proposal['status']}",
        )

    proposal["status"]      = "approved"
    proposal["approved_by"] = body.approved_by.strip()
    proposal["approved_at"] = _now()
    if body.note:
        proposal["approval_note"] = body.note

    _save_audit(batch_id, audit)
    tl.log_event(
        _audit_path(batch_id),
        tl.EV_ACTION_PROPOSAL_APPROVED,
        "admin",
        actor=body.approved_by,
        detail={
            "proposal_id":   proposal_id,
            "proposal_type": proposal["type"],
            "note":          body.note,
        },
    )
    return {"status": "approved", "proposal_id": proposal_id, "approved_by": body.approved_by}


@router.post("/{proposal_id}/reject")
def reject_proposal(proposal_id: str, body: RejectBody) -> Dict[str, Any]:
    """
    Reject an action proposal.

    Requires: rejected_by + reason.
    Sets status=rejected (terminal — cannot be re-queued).
    """
    if not (body.rejected_by or "").strip():
        raise HTTPException(status_code=422, detail="rejected_by is required.")
    if not (body.reason or "").strip():
        raise HTTPException(status_code=422, detail="reason is required.")

    batch_id, audit, proposal = _resolve_proposal(proposal_id)

    if proposal["status"] in ("queued", "sent"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot reject proposal in terminal status: {proposal['status']}",
        )

    proposal["status"]       = "rejected"
    proposal["rejected_by"]  = body.rejected_by.strip()
    proposal["rejected_at"]  = _now()
    proposal["reject_reason"] = body.reason.strip()

    _save_audit(batch_id, audit)
    tl.log_event(
        _audit_path(batch_id),
        tl.EV_ACTION_PROPOSAL_REJECTED,
        "admin",
        actor=body.rejected_by,
        detail={
            "proposal_id":   proposal_id,
            "proposal_type": proposal["type"],
            "reason":        body.reason,
        },
    )
    return {"status": "rejected", "proposal_id": proposal_id}


@router.post("/{proposal_id}/queue")
def queue_proposal(proposal_id: str) -> Dict[str, Any]:
    """
    Queue the email for an approved proposal.

    Guards:
      - Proposal must be approved (not just pending)
      - approved_by must be present
      - Recipients must be non-empty
      - Attachment files must exist on disk
      - High-value blocks carrier_description_reply
      - Low-value blocks dhl_dsk_transfer (without override)

    On success: calls queue_email(), writes email_id to proposal, logs timeline.
    NO email is auto-sent — the queued email waits for MCP/admin delivery.
    """
    from ..services.email_service import queue_email

    batch_id, audit, proposal = _resolve_proposal(proposal_id)

    # Run all safety guards before touching any state
    _assert_can_queue(proposal, audit)

    draft    = proposal["draft"]
    email_id = queue_email(
        to        = draft["to"],
        subject   = draft["subject"],
        body_html = draft.get("body_html") or f"<pre>{draft.get('body_text', '')}</pre>",
        body_text = draft.get("body_text", ""),
        batch_id  = batch_id,
        cc        = draft.get("cc", ""),
    )

    proposal["status"]    = "queued"
    proposal["email_id"]  = email_id
    proposal["queued_at"] = _now()

    _save_audit(batch_id, audit)
    tl.log_event(
        _audit_path(batch_id),
        tl.EV_EMAIL_QUEUED,
        "admin",
        actor=proposal["approved_by"],
        detail={
            "proposal_id":   proposal_id,
            "proposal_type": proposal["type"],
            "email_id":      email_id,
            "to":            draft["to"],
            "approved_by":   proposal["approved_by"],
        },
    )
    return {
        "status":      "queued",
        "proposal_id": proposal_id,
        "email_id":    email_id,
        "to":          draft["to"],
    }


# ── Batch-scoped proposal resolver ────────────────────────────────────────────

def _resolve_proposal(
    proposal_id: str,
) -> tuple[str, Dict[str, Any], Dict[str, Any]]:
    """
    Find the (batch_id, audit, proposal) tuple for a given proposal_id.

    Searches all active batch audits.  Raises 404 if not found.
    """
    if not _OUTPUTS.is_dir():
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id!r} not found.")

    for batch_dir in _OUTPUTS.iterdir():
        if not batch_dir.is_dir():
            continue
        ap = batch_dir / "audit.json"
        if not ap.exists():
            continue
        try:
            audit = json.loads(ap.read_text(encoding="utf-8"))
        except Exception:
            continue
        for prop in (audit.get("action_proposals") or []):
            if prop.get("proposal_id") == proposal_id:
                return batch_dir.name, audit, prop

    raise HTTPException(status_code=404, detail=f"Proposal {proposal_id!r} not found.")
