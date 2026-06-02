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

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from pydantic import BaseModel

from ..core.config import settings
from ..core.security import require_api_key
from ..config.email_routing import resolve_dhl_to, resolve_dhl_cc
from ..services.clearance_path_alias import (
    is_agency_clearance,
    is_dhl_self_clearance,
)
from ..services.polish_desc_validator import validate_polish_customs_description
from ..core import timeline as tl
from ..utils.io import write_json_atomic
from ..utils.proposal_lock import proposal_write_lock

# Router-level auth — every endpoint protected. Closes the pre-existing
# CRITICAL gap from the SECURITY review: previously /list, /approve,
# /reject, /queue, /refresh were all unauthenticated.
_auth = Depends(require_api_key)
router = APIRouter(
    prefix="/api/v1/action-proposals",
    tags=["action_proposals"],
    dependencies=[_auth],
)

_OUTPUTS = settings.storage_root / "outputs"

# ── Value guard constants (from clearance_decision.py) ───────────────────────
_THRESHOLD_USD = 2_500.0

# ── Proposal types created by operator action (not by cowork triggers) ───────
# Excluded from refresh_proposals auto-resolution because they have no
# trigger source that could "deactivate" them.
_OPERATOR_INITIATED_TYPES: frozenset = frozenset({"dhl_proactive_dispatch"})

# Phase 2.3 — auto-actor sentinels. These exact strings are used as both
# created_by and approved_by by Phase 2.3's auto-queue trigger; the G9
# self-approval guard recognises them and skips the equality check.
# New auto-flows must add their sentinels here explicitly.
AUTO_ACTOR_SENTINELS: frozenset = frozenset({"system:path_a_auto_queue"})


def _is_auto_actor(actor: str) -> bool:
    """True iff *actor* is a registered auto-flow sentinel that bypasses
    the G9 self-approval guard."""
    return actor in AUTO_ACTOR_SENTINELS

# Environments where the dhl_customs_email fallback to dev-null@localhost
# is acceptable. Any environment NOT in this set must fail loud at queue
# time when dhl_customs_email is empty.
_DEV_ENVIRONMENTS: frozenset = frozenset({"dev", "local", "test"})

# Environments that are explicitly production-class and must never accept
# the dev-null fallback.
_PROD_ENVIRONMENTS: frozenset = frozenset({"prod", "production", "staging"})


def _resolve_proactive_recipients() -> tuple[str, str, Optional[str]]:
    """
    Authoritative recipient + CC for proactive dispatch, resolved at queue time.

    Returns ``(to, cc, error)`` where *error* is None on success or a string
    explaining the fail-loud condition (production with empty
    dhl_customs_email).

    Resolution rules:
      * Recipient resolution delegates to ``email_routing.resolve_dhl_to`` /
        ``resolve_dhl_cc``: centralized ``DHL_TO`` / ``INTERNAL_CC`` constants
        win when non-empty; ``settings.dhl_customs_email`` /
        ``settings.dhl_customs_cc`` are consulted only as a fallback.
      * env in {dev, local, test} + empty resolved TO → ("dev-null@localhost", cc, None)
      * env in {prod, production, staging} + empty resolved TO → ("", cc, "config_missing")
      * any other env value + empty resolved TO → fail loud (treated as production-class)
      * any env + non-empty resolved TO → use it
    """
    env = (settings.environment or "").strip().lower()
    to_addr = resolve_dhl_to()
    cc_addr = resolve_dhl_cc()

    if not to_addr:
        if env in _DEV_ENVIRONMENTS:
            return "dev-null@localhost", cc_addr, None
        # Default to fail-loud for any non-dev environment value
        return "", cc_addr, "config_missing"

    return to_addr, cc_addr, None


def _record_proactive_failure(
    audit: Dict[str, Any],
    proposal: Dict[str, Any],
    exc: Exception,
) -> Dict[str, Any]:
    """Write the proactive-only failure side-effects into *audit* in-place."""
    reason = f"{type(exc).__name__}: {exc}"
    if len(reason) > 200:
        reason = reason[:197] + "..."
    audit["proactive_dispatch_failed_at"]      = _now()
    audit["proactive_dispatch_failure_reason"] = reason
    return {
        "batch_id":      audit.get("batch_id", ""),
        "proposal_id":   proposal.get("proposal_id", ""),
        "awb":           audit.get("awb") or audit.get("dhl_awb") or audit.get("tracking_no") or "",
        "error_class":   type(exc).__name__,
        "error_summary": reason,
    }


# ── Request models ─────────────────────────────────────────────────────────────

class DescriptionCorrection(BaseModel):
    """Correction values supplied by the operator when approving a
    ``customs_description_mismatch`` proposal.

    At least one of ``material_pl`` or ``description_pl`` must be non-empty.
    """
    material_pl:    Optional[str] = None   # e.g. "platyna próby 950"
    description_pl: Optional[str] = None   # full customs sentence (optional)


class ApproveBody(BaseModel):
    approved_by: str
    note: Optional[str] = None
    # Only consumed for customs_description_mismatch proposals.
    # Ignored for all other proposal types.
    correction: Optional[DescriptionCorrection] = None


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

    # G9 — proactive-only re-checks against LIVE audit
    if prop_type == "dhl_proactive_dispatch":
        _assert_proactive_dispatch_safe(proposal, audit)


def _gate_polish_desc_validation(
    audit: Dict[str, Any],
    batch_id: str,
    *,
    stage: str,
) -> None:
    """G-PC10 — mandatory format gate for the Polish customs description PDF.

    Runs the central validator (services.polish_desc_validator) and:
      • writes audit.polish_desc_validation = <result>
      • emits a timeline event (passed / failed)
      • raises HTTP 422 with the failed-rule list when invalid

    ``stage`` is one of {"approve", "queue"} and is recorded in the audit /
    timeline so a subsequent operator can see when the gate fired.
    """
    pdf_path = audit.get("polish_desc_path") or ""
    if not pdf_path and audit.get("polish_desc_filename"):
        pdf_path = str(
            settings.storage_root / "polish_descriptions"
            / audit["polish_desc_filename"]
        )

    batch_outputs_dir = _OUTPUTS / batch_id

    result = validate_polish_customs_description(
        pdf_path           = pdf_path,
        audit              = audit,
        batch_outputs_dir  = batch_outputs_dir if batch_outputs_dir.is_dir() else None,
    )
    result["stage"] = stage

    # Persist result + timeline event (best-effort; never block on write
    # failure — the gate decision below is what matters). The audit field
    # is saved before any HTTPException raise so the failure marker
    # survives the gate even when the operator only sees the 422.
    audit["polish_desc_validation"] = result
    try:
        _save_audit(batch_id, audit)
    except Exception:
        pass
    try:
        tl.log_event(
            _audit_path(batch_id),
            ("polish_desc_validation_passed" if result["valid"]
             else "polish_desc_validation_failed"),
            "admin",
            actor="system:polish_desc_validator",
            detail={
                "stage":         stage,
                "valid":         result["valid"],
                "failed_rules":  [f["rule"] for f in result["failed_rules"]],
                "summary":       result["summary"],
            },
        )
    except Exception:
        pass

    # tl.log_event writes the timeline event to disk via read-modify-write.
    # The caller's in-memory audit dict is now stale (missing the new
    # timeline entry). Refresh from disk so a subsequent _save_audit in
    # the calling handler does not overwrite the event we just persisted.
    try:
        fresh = json.loads(_audit_path(batch_id).read_text(encoding="utf-8"))
        audit.clear()
        audit.update(fresh)
    except Exception:
        pass

    if not result["valid"]:
        # Hard block — operator must regenerate / repair the PDF
        # before approve or queue can proceed.
        raise HTTPException(
            status_code=422,
            detail={
                "guard":         "polish_desc_validation_failed",
                "code":          "polish_desc_validation_failed",
                "error":         "Polish customs description PDF failed format validation. "
                                 "Regenerate the PDF; do not approve or queue until validation passes.",
                "stage":         stage,
                "summary":       result["summary"],
                "failed_rules":  result["failed_rules"],
                "expected":      result.get("expected", {}),
                "pdf_path":      result.get("pdf_path", ""),
            },
        )


def _assert_proactive_dispatch_safe(
    proposal: Dict[str, Any],
    audit: Dict[str, Any],
) -> None:
    """
    Re-validate proactive-dispatch preconditions at queue time.

    The proposal record is a snapshot from creation time. Audit state may
    have advanced (agency path activated, DSK generated, dispatch already
    sent in another window). All four conditions are re-checked against
    the LIVE audit before queue_email is invoked.

    Also enforces the self-approval block: the operator who created the
    proposal must not be the same person who approves it.
    """
    # G-PC1 / G-PC5 — clearance path must still be self-clearance, no agency
    cd = audit.get("clearance_decision") or {}
    clearance_path = (cd.get("clearance_path") or "").strip()
    if is_agency_clearance(clearance_path):
        raise HTTPException(
            status_code=409,
            detail={
                "guard": "agency_path_active",
                "error": "Clearance path advanced to agency clearance — "
                         "proactive dispatch no longer applicable.",
                "code":  "agency_path_active",
            },
        )
    if clearance_path and not is_dhl_self_clearance(clearance_path):
        raise HTTPException(
            status_code=409,
            detail={
                "guard": "not_self_clearance_path",
                "error": f"Clearance path is {clearance_path!r}; expected carrier_self_clearance.",
                "code":  "not_self_clearance_path",
            },
        )
    if audit.get("agency_name") or (audit.get("agency_reply_package") or {}).get("status"):
        raise HTTPException(
            status_code=409,
            detail={
                "guard": "agency_path_active",
                "error": "Agency forwarding active — proactive dispatch blocked.",
                "code":  "agency_path_active",
            },
        )

    # G-PC6 — DSK must not exist
    if audit.get("dsk_filename") or audit.get("dsk_reference"):
        raise HTTPException(
            status_code=409,
            detail={
                "guard": "dsk_already_created",
                "error": "DSK has been generated — proactive dispatch blocked.",
                "code":  "dsk_already_created",
            },
        )

    # G-PC3 — must not have been dispatched already
    if audit.get("proactive_dispatch_sent_at"):
        raise HTTPException(
            status_code=409,
            detail={
                "guard": "already_dispatched",
                "error": "Proactive dispatch already sent for this batch.",
                "code":  "already_dispatched",
            },
        )

    # Self-approval block — created_by != approved_by (SECURITY question 17 BLOCK)
    # Phase 2.3 exemption: registered auto-actor sentinels bypass the
    # equality check (auto-flows legitimately create + approve as one actor).
    # Phase 2.3.1 (Finding 1.1): keep .strip() for the equality check (operator
    # UX tolerates trailing whitespace) but invoke _is_auto_actor on the RAW
    # unstripped value. The exemption surface is byte-equal-to-sentinel only;
    # padded variants like " system:path_a_auto_queue " do NOT exempt.
    created_by_raw  = proposal.get("created_by")  or ""
    approved_by_raw = proposal.get("approved_by") or ""
    created_by  = created_by_raw.strip()
    approved_by = approved_by_raw.strip()
    if (created_by and approved_by and created_by == approved_by
            and not _is_auto_actor(created_by_raw)):
        raise HTTPException(
            status_code=409,
            detail={
                "guard": "self_approval_blocked",
                "error": "The operator who requested proactive dispatch cannot also "
                         "approve it. Please have a second admin approve the proposal.",
                "code":  "self_approval_blocked",
            },
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
        # Phase 2.2 — additive schema field for Phase 2.3's auto-queue
        # validation gate at Departed origin. When the auto-queue path
        # creates a proposal-fallback (rather than auto-queuing) because
        # one of the seven validation checks failed, this field carries
        # the human-readable failure reason. Operators see it as the
        # disabled_reason on the queue button (Phase 4.x renders it).
        # Default None for proposals not created via the validation gate.
        "validation_failure_reason": None,
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

    # Resolve pending_review proposals whose trigger is no longer detected.
    # Operator-initiated proposals (e.g. dhl_proactive_dispatch) have no
    # trigger source — they must NEVER be auto-resolved by trigger absence.
    for p in proposals:
        if (p.get("status") == "pending_review"
                and p.get("type") not in active_prop_types
                and p.get("type") not in _OPERATOR_INITIATED_TYPES):
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
    """Return all action proposals for a batch, annotated with can_approve."""
    audit = _load_audit(batch_id)
    proposals = [
        _annotate_can_approve(p, audit)
        for p in (audit.get("action_proposals") or [])
    ]
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

    # Phase 2.3.1 (Finding 1.2): operator-supplied approved_by must NOT be
    # in the auto-actor sentinel space. Otherwise an operator could approve
    # an auto-created proposal as the same auto actor and bypass the
    # implicit human-in-the-loop on auto-flow's self-approval exemption.
    if _is_auto_actor((body.approved_by or "").strip()):
        raise HTTPException(
            status_code=422,
            detail={
                "code":  "auto_actor_sentinel_reserved",
                "guard": "auto_actor_sentinel_reserved",
                "error": "approved_by is reserved for system actors and cannot be set by request.",
            },
        )

    # Find which batch owns this proposal
    batch_id, audit, proposal = _resolve_proposal(proposal_id)

    if proposal["status"] == "rejected":
        raise HTTPException(status_code=409, detail="Cannot approve a rejected proposal.")
    if proposal["status"] in ("queued", "sent"):
        raise HTTPException(
            status_code=409,
            detail=f"Proposal already in terminal status: {proposal['status']}",
        )

    # G-PC10 (approve stage) — Polish customs description format gate.
    # Only applies to dhl_proactive_dispatch proposals; non-DHL proposals
    # do not carry a Polish description PDF as a hard precondition.
    if proposal.get("type") == "dhl_proactive_dispatch":
        _gate_polish_desc_validation(audit, batch_id, stage="approve")
        # Gate refreshes audit in-place from disk to pick up the timeline
        # event it wrote. The caller's `proposal` variable now points to
        # an orphaned dict from the pre-refresh list — re-resolve it from
        # the new action_proposals list before mutating status below.
        proposal = _get_proposal(audit, proposal_id)

    proposal["status"]      = "approved"
    proposal["approved_by"] = body.approved_by.strip()
    proposal["approved_at"] = _now()
    if body.note:
        proposal["approval_note"] = body.note

    # ── customs_description_mismatch: apply correction to audit ──────────────
    # When the operator approves a description-mismatch proposal and supplies a
    # correction, store it in audit["description_corrections"][product_code].
    # The generate-description route reads this dict and applies overrides
    # before passing rows to the customs description engine.
    correction_applied: Optional[Dict[str, Any]] = None
    if proposal.get("type") == "customs_description_mismatch" and body.correction:
        product_code = proposal.get("product_code") or ""
        mat_pl  = (body.correction.material_pl    or "").strip()
        desc_pl = (body.correction.description_pl or "").strip()
        if product_code and (mat_pl or desc_pl):
            corr_entry: Dict[str, Any] = {
                "material_pl":     mat_pl,
                "description_pl":  desc_pl,
                "approved_by":     body.approved_by.strip(),
                "approved_at":     _now(),
                "source_proposal_id": proposal_id,
            }
            audit.setdefault("description_corrections", {})[product_code] = corr_entry
            # Record back on the proposal so the history is self-contained.
            proposal["correction"] = corr_entry
            correction_applied = corr_entry

    _save_audit(batch_id, audit)
    tl.log_event(
        _audit_path(batch_id),
        tl.EV_ACTION_PROPOSAL_APPROVED,
        "admin",
        actor=body.approved_by,
        detail={
            "proposal_id":    proposal_id,
            "proposal_type":  proposal["type"],
            "note":           body.note,
            "correction":     correction_applied,
        },
    )
    resp: Dict[str, Any] = {
        "status":      "approved",
        "proposal_id": proposal_id,
        "approved_by": body.approved_by,
    }
    if correction_applied:
        resp["correction_applied"] = correction_applied
    return resp


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
      - dhl_proactive_dispatch — additional G9 re-checks against live audit
        (clearance path, agency, DSK, already-dispatched, self-approval)

    Locking (P2 Slice A):
      The full critical section — fresh audit reload → guards →
      recipient re-resolution → queue_email → audit mutation → write — runs
      under proposal_write_lock(batch_id). Two concurrent calls for the
      same proposal serialise: one wins, the second observes the first's
      audit mutation and is blocked at G1/G-PC3.

    Recipient/CC for dhl_proactive_dispatch:
      Authoritative values are re-resolved at queue time from
      settings.dhl_customs_email / settings.dhl_customs_cc. The proposal's
      draft.to / draft.cc fields are demoted to operator preview and
      NEVER consulted as the queue recipient.

    Failure handling:
      Only dhl_proactive_dispatch wraps queue_email in try/except. On
      failure: proactive_dispatch_failed_at is recorded,
      EV_DHL_PROACTIVE_DISPATCH_FAILED is logged, proposal.status remains
      "approved" so the operator may retry, response is HTTP 500.
      All other proposal types preserve existing exception bubbling.

    On success: calls queue_email(), writes email_id to proposal, logs
    timeline. NO email is auto-sent — the queued email waits for MCP/admin
    delivery.
    """
    from ..services.email_service import queue_email
    from ..services.email_sender  import send_queued_email, _smtp_configured

    # Resolve initial batch_id (snapshot lookup); the live state is
    # re-fetched inside the lock below.
    batch_id, _audit_snapshot, _proposal_snapshot = _resolve_proposal(proposal_id)

    with proposal_write_lock(batch_id):
        # Re-load audit fresh inside the lock. The snapshot from
        # _resolve_proposal is staler than what's on disk; all guards must
        # run against the current state.
        audit = _load_audit(batch_id)
        proposal = _get_proposal(audit, proposal_id)
        prop_type = proposal.get("type", "")
        is_proactive = (prop_type == "dhl_proactive_dispatch")

        # ── Idempotency: already-delivered short-circuit (proactive) ──────
        # Re-calling /queue on a proactive proposal that has already been
        # SMTP-delivered must NOT re-send. Return the prior delivery state.
        if is_proactive and proposal.get("status") == "sent":
            return {
                "status":              "sent",
                "delivered":           True,
                "already_sent":        True,
                "proposal_id":         proposal_id,
                "email_id":            proposal.get("email_id"),
                "provider_message_id": proposal.get("provider_message_id"),
                "sent_at":             proposal.get("sent_at"),
                "to":                  (proposal.get("draft") or {}).get("to", ""),
            }

        # ── Proactive retry-send path: queue record exists, SMTP failed ──
        # When status="queued" + email_id present (set by an earlier call
        # that hit SMTP failure), skip queue_email and retry send only.
        # This avoids creating a duplicate queue record while the operator
        # retries via the same endpoint.
        proactive_retry = (
            is_proactive
            and proposal.get("status") == "queued"
            and bool(proposal.get("email_id"))
        )

        if proactive_retry:
            draft   = proposal.get("draft") or {}
            email_id = proposal["email_id"]
            to_addr  = draft.get("to", "")
            cc_addr  = draft.get("cc", "")
        else:
            # Run all safety guards (G1..G8 + G9 for proactive)
            _assert_can_queue(proposal, audit)

        # G-PC10 (queue stage) — Polish customs description format gate.
        # Re-runs the central validator at queue time so a stale audit
        # cannot let an invalid PDF through after a regenerate-without-revalidate.
        # Applies to both first-queue and retry-send paths so SMTP never
        # carries an invalid PDF.
        if is_proactive:
            _gate_polish_desc_validation(audit, batch_id, stage="queue")
            # Re-resolve proposal after the gate refreshes audit from disk.
            proposal = _get_proposal(audit, proposal_id)

        if not proactive_retry:
            draft     = proposal["draft"]

            # ── Resolve authoritative recipients ──────────────────────────
            # For proactive dispatch: read settings at queue time. Drafts
            # are not authoritative. For other types: pass draft through.
            if is_proactive:
                to_addr, cc_addr, env_error = _resolve_proactive_recipients()
                if env_error:
                    raise HTTPException(
                        status_code=500,
                        detail={
                            "error":  env_error,
                            "guard":  "config_missing",
                            "reason": "settings.dhl_customs_email is empty in a "
                                      "non-dev environment.",
                        },
                    )
            else:
                to_addr = draft.get("to", "")
                cc_addr = draft.get("cc", "")

        # ── queue_email — type-discriminated failure handling ─────────────
        if proactive_retry:
            # Skip queue_email entirely; the queue record already exists
            # and will be (re-)sent via SMTP below.
            pass
        elif is_proactive:
            try:
                email_id = queue_email(
                    to          = to_addr,
                    subject     = draft["subject"],
                    body_html   = draft.get("body_html") or f"<pre>{draft.get('body_text', '')}</pre>",
                    body_text   = draft.get("body_text", ""),
                    batch_id    = batch_id,
                    cc          = cc_addr,
                    attachments = draft.get("attachments", []),
                )
            except Exception as exc:
                # Proactive-only: capture failure into audit, log timeline,
                # leave proposal in "approved" so operator can retry.
                detail = _record_proactive_failure(audit, proposal, exc)
                _save_audit(batch_id, audit)
                tl.log_event(
                    _audit_path(batch_id),
                    tl.EV_DHL_PROACTIVE_DISPATCH_FAILED,
                    "admin",
                    actor=proposal.get("approved_by") or "system",
                    detail=detail,
                )
                raise HTTPException(
                    status_code=500,
                    detail={
                        "error":       "queue_failed",
                        "proposal_id": proposal_id,
                        "reason":      detail["error_summary"],
                    },
                ) from exc
        else:
            # Existing six types: exception bubbles up unchanged.
            email_id = queue_email(
                to          = to_addr,
                subject     = draft["subject"],
                body_html   = draft.get("body_html") or f"<pre>{draft.get('body_text', '')}</pre>",
                body_text   = draft.get("body_text", ""),
                batch_id    = batch_id,
                cc          = cc_addr,
                attachments = draft.get("attachments", []),
            )

        # ── Mutate proposal + audit + write (skip on proactive retry) ─────
        if not proactive_retry:
            proposal["status"]    = "queued"
            proposal["email_id"]  = email_id
            proposal["queued_at"] = _now()

            if is_proactive:
                now_iso = _now()
                audit["proactive_dispatch_sent_at"]      = now_iso
                audit["proactive_dispatch_email_id"]     = email_id
                audit["proactive_dispatch_recipient"]    = to_addr
                audit["proactive_dispatch_cc"]           = cc_addr
                audit["proactive_dispatch_attachments"]  = [
                    Path(a["path"]).name
                    for a in (draft.get("attachments") or [])
                    if a.get("path")
                ]

            _save_audit(batch_id, audit)

            # ── Timeline events ───────────────────────────────────────────
            tl.log_event(
                _audit_path(batch_id),
                tl.EV_EMAIL_QUEUED,
                "admin",
                actor=proposal["approved_by"],
                detail={
                    "proposal_id":   proposal_id,
                    "proposal_type": prop_type,
                    "email_id":      email_id,
                    "to":            to_addr,
                    "approved_by":   proposal["approved_by"],
                },
            )
            if is_proactive:
                tl.log_event(
                    _audit_path(batch_id),
                    tl.EV_DHL_PROACTIVE_DISPATCH_SENT,
                    "admin",
                    actor=proposal["approved_by"],
                    detail={
                        "batch_id":         batch_id,
                        "proposal_id":      proposal_id,
                        "awb":              audit.get("awb") or audit.get("dhl_awb") or audit.get("tracking_no") or "",
                        "approved_by":      proposal["approved_by"],
                        "email_id":         email_id,
                        "attachment_count": len(audit.get("proactive_dispatch_attachments") or []),
                        "recipient":        to_addr,
                    },
                )

        # ── Real SMTP send (proactive only, when SMTP is configured) ──────
        # The original implementation stopped after queue_email; the queue
        # record was never drained for `dhl_proactive_dispatch`. Trigger
        # the SMTP send in the same request so the operator-facing /queue
        # action actually delivers the email. Idempotent: send_queued_email
        # short-circuits when status=="sent" already; the proposal-level
        # short-circuit at the top of this handler covers re-calls of /queue.
        if is_proactive and _smtp_configured():
            try:
                send_result = send_queued_email(email_id, method="smtp")
            except Exception as exc:
                send_result = {
                    "ok":           False,
                    "error":        "send_exception",
                    "error_detail": f"{type(exc).__name__}: {exc}",
                }

            if send_result.get("ok") and send_result.get("status") == "sent":
                provider_id = send_result.get("provider_message_id")
                sent_at_iso = send_result.get("sent_at") or _now()
                proposal["status"]              = "sent"
                proposal["sent_at"]             = sent_at_iso
                proposal["provider_message_id"] = provider_id
                audit["proactive_dispatch_delivered_at"]        = sent_at_iso
                audit["proactive_dispatch_provider_message_id"] = provider_id
                # Clear any prior failure marker from a previous attempt
                audit.pop("proactive_dispatch_failed_at",      None)
                audit.pop("proactive_dispatch_failure_reason", None)
                audit.pop("proactive_dispatch_send_error",     None)
                _save_audit(batch_id, audit)

                tl.log_event(
                    _audit_path(batch_id),
                    "dhl_proactive_dispatch_delivered",
                    "admin",
                    actor=proposal.get("approved_by") or "system",
                    detail={
                        "proposal_id":         proposal_id,
                        "email_id":            email_id,
                        "provider_message_id": provider_id,
                        "sent_at":             sent_at_iso,
                        "recipient":           to_addr,
                    },
                )
                return {
                    "status":              "sent",
                    "delivered":           True,
                    "proposal_id":         proposal_id,
                    "email_id":            email_id,
                    "provider_message_id": provider_id,
                    "sent_at":             sent_at_iso,
                    "to":                  to_addr,
                }

            # SMTP failed — keep proposal at status="queued" so the same
            # endpoint retries SMTP (proactive_retry path) without
            # creating a duplicate queue record. Record failure markers.
            reason     = send_result.get("error") or "smtp_send_failed"
            err_detail = (send_result.get("error_detail") or "")[:200]
            failed_at  = _now()
            audit["proactive_dispatch_failed_at"]      = failed_at
            audit["proactive_dispatch_failure_reason"] = reason
            audit["proactive_dispatch_send_error"]     = {
                "reason":       reason,
                "error_detail": err_detail,
                "failed_at":    failed_at,
            }
            _save_audit(batch_id, audit)
            tl.log_event(
                _audit_path(batch_id),
                "dhl_proactive_dispatch_send_failed",
                "admin",
                actor=proposal.get("approved_by") or "system",
                detail={
                    "proposal_id":  proposal_id,
                    "email_id":     email_id,
                    "reason":       reason,
                    "error_detail": err_detail,
                    "failed_at":    failed_at,
                },
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "error":        "smtp_send_failed",
                    "proposal_id":  proposal_id,
                    "email_id":     email_id,
                    "reason":       reason,
                    "error_detail": err_detail,
                    "retryable":    True,
                },
            )

    # SMTP not configured (dev) or non-proactive proposal → existing
    # queued-only response unchanged.
    return {
        "status":      "queued",
        "proposal_id": proposal_id,
        "email_id":    email_id,
        "to":          to_addr,
    }


# ── can_approve projection — backend single authority ────────────────────────

def _annotate_can_approve(proposal: Dict[str, Any], audit: Dict[str, Any]) -> Dict[str, Any]:
    """
    Project can_approve + approve_blocked_reason onto a copy of the proposal.

    Backend is the single authority. Renderers must consume these fields and
    must never re-derive from raw audit fields (pz_pdf_filename, status, etc.).

    Rules (first match wins):
    1. Non-pending statuses (approved/queued/rejected/sent/resolved) → blocked
    2. Non-email types (tracking_lookup) → always approvable
    3. Completed batch → blocked regardless of PZ state
    4. PZ not generated (no pz_pdf_filename AND no pz_generated_at) → blocked
    5. Otherwise → approvable
    """
    p = dict(proposal)

    status = p.get("status", "")
    ptype  = p.get("type", "")

    if status != "pending_review":
        p["can_approve"]          = False
        p["approve_blocked_reason"] = f"Proposal is already {status}"
        return p

    if ptype in _NON_EMAIL_TYPES:
        p["can_approve"]          = True
        p["approve_blocked_reason"] = None
        return p

    if (audit.get("status") or "").lower() == "completed":
        p["can_approve"]          = False
        p["approve_blocked_reason"] = "Batch is completed — no further actions allowed"
        return p

    pz_ready = bool(audit.get("pz_pdf_filename") or audit.get("pz_generated_at"))
    if not pz_ready:
        p["can_approve"]          = False
        p["approve_blocked_reason"] = "PZ not yet generated — approve requires PZ to exist"
        return p

    p["can_approve"]          = True
    p["approve_blocked_reason"] = None
    return p


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


# ── wFirma action-proposal session helper ─────────────────────────────────────
# Mirror of routes_proforma._get_current_user_optional — operator is derived
# SERVER-SIDE from the session cookie, never from a client-supplied header.

def _get_resolve_operator(pz_session: Optional[str] = Cookie(default=None)) -> Optional[dict]:
    """Inject the session user for operator derivation in /resolve. None when API-key auth."""
    if not pz_session:
        return None
    try:
        from ..auth.service import decode_token, get_user_by_id
        payload = decode_token(pz_session)
        if not payload:
            return None
        return get_user_by_id(payload.get("sub"))
    except Exception:
        return None


# ── POST /{proposal_id}/resolve ───────────────────────────────────────────────

class ResolveBody(BaseModel):
    """Generic resolve body — type-specific fields live under resolution_data."""
    resolution_data: Dict[str, Any] = {}


@router.post("/{proposal_id}/resolve")
def resolve_proposal(
    proposal_id:  str,
    body:         ResolveBody,
    session_user: Optional[dict] = Depends(_get_resolve_operator),
) -> Dict[str, Any]:
    """
    Execute a wfirma_action recovery proposal.

    Guards:
      - proposal must have channel="wfirma_action"
      - proposal must be in status=pending_review
      - type-specific handler validates resolution_data (e.g., selected_series_id
        must be non-null and present in the proposal's available_series list)

    Operator identity is derived SERVER-SIDE from the session cookie — a client
    X-Operator header is never trusted. Falls back to "session-user" when
    authenticated via API key (no session cookie).

    On success: sets status=resolved, writes EV_WFIRMA_<TYPE>_RESOLVED.
    On type-handler error: re-raises (400/500) without mutating the proposal.
    """
    from ..services.wfirma_recovery import (
        WFIRMA_CHANNEL, STATUS_RESOLVED, STATUS_RESOLVING,
        dispatch_resolve,
    )

    batch_id, audit, proposal = _resolve_proposal(proposal_id)

    # ── Channel guard ─────────────────────────────────────────────────────────
    if proposal.get("channel") != WFIRMA_CHANNEL:
        raise HTTPException(
            status_code=400,
            detail=(
                f"proposal {proposal_id!r} has channel={proposal.get('channel')!r}; "
                f"/resolve only handles channel='{WFIRMA_CHANNEL}'"
            ),
        )

    # ── Status guard ──────────────────────────────────────────────────────────
    if proposal.get("status") != "pending_review":
        raise HTTPException(
            status_code=409,
            detail=(
                f"proposal {proposal_id!r} is in status={proposal.get('status')!r}; "
                f"only pending_review proposals can be resolved"
            ),
        )

    # ── Operator from session ─────────────────────────────────────────────────
    operator = (
        ((session_user or {}).get("full_name") or "").strip()
        or ((session_user or {}).get("email") or "").strip()
        or "session-user"
    )

    with proposal_write_lock(batch_id):
        # Re-load inside lock for freshness
        audit = _load_audit(batch_id)
        proposal = _get_proposal(audit, proposal_id)

        # Mark in-progress so concurrent calls see a terminal-ish status
        proposal["status"] = STATUS_RESOLVING
        _save_audit(batch_id, audit)

    # ── Dispatch to type handler ──────────────────────────────────────────────
    # Runs OUTSIDE the lock because it may make network calls (wFirma).
    # The STATUS_RESOLVING sentinel prevents double-execution.
    try:
        result = dispatch_resolve(proposal, body.resolution_data, operator)
    except HTTPException:
        # Restore to pending_review so operator can correct and retry
        with proposal_write_lock(batch_id):
            audit = _load_audit(batch_id)
            p = _get_proposal(audit, proposal_id)
            p["status"] = "pending_review"
            _save_audit(batch_id, audit)
        raise
    except Exception as exc:
        with proposal_write_lock(batch_id):
            audit = _load_audit(batch_id)
            p = _get_proposal(audit, proposal_id)
            p["status"] = "pending_review"
            _save_audit(batch_id, audit)
        raise HTTPException(
            status_code=500,
            detail=f"resolve handler failed: {type(exc).__name__}: {exc}",
        ) from exc

    # ── Mark resolved + audit ─────────────────────────────────────────────────
    with proposal_write_lock(batch_id):
        audit = _load_audit(batch_id)
        p = _get_proposal(audit, proposal_id)
        p["status"]           = STATUS_RESOLVED
        p["resolved_at"]      = _now()
        p["resolved_by"]      = operator
        p["resolution_result"] = result

        # Audit timeline event (tl.log_event writes directly to disk)
        ev_type = f"EV_WFIRMA_{proposal.get('type','').upper()}_RESOLVED"
        tl.log_event(
            _audit_path(batch_id), ev_type,
            trigger_source = "wfirma_recovery_resolve",
            actor          = operator,
            detail         = {
                "proposal_id": proposal_id,
                "type":        proposal.get("type"),
                "operator":    operator,
            },
        )
        _save_audit(batch_id, audit)

    return {
        "status":       STATUS_RESOLVED,
        "proposal_id":  proposal_id,
        "operator":     operator,
        "result":       result,
    }
