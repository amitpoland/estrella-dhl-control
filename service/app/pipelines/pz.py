"""
pz.py — PZ calculation pipeline
=================================
Handles: SAD verification → PZ calculation → output generation
Trigger sources: bot (/submit), dashboard (process button), system (auto-submit)
Guard: PZ requires SAD
"""
from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from ..core import timeline as tl
from ..core.guards import guard_pz_requires_sad, guard_trigger_declared, guard_status_transition


def _advisory_to_action_proposal(advisory: dict, batch_id: str, trigger_source: str) -> dict:
    """Convert a guard advisory dict to an action_proposal entry for the Inbox."""
    return {
        "proposal_id":   str(uuid.uuid4()),
        "type":          advisory.get("code", "advisory_gate"),
        "channel":       "advisory_gate",
        "batch_id":      batch_id,
        "status":        "pending_review",
        "reason":        advisory.get("message", "Advisory gate bypassed"),
        "confidence":    "high",
        "advisory":      True,
        "created_at":    datetime.now(timezone.utc).isoformat(),
        "approved_by":   None,
        "approved_at":   None,
        "rejected_by":   None,
        "rejected_at":   None,
        "reject_reason": None,
        "draft":         {},
        "email_id":      None,
        "queued_at":     None,
        "action":        advisory.get("action", ""),
        "trigger":       trigger_source,
    }


def _write_advisory_proposal(audit_path: Path, proposal: dict) -> None:
    """Append an advisory proposal to audit.json action_proposals (dedup by type+channel)."""
    try:
        if not audit_path.exists():
            return
        with audit_path.open(encoding="utf-8") as f:
            audit = json.load(f)
        proposals = audit.setdefault("action_proposals", [])
        # Dedup: skip if an active advisory of this type+channel already exists
        _active = {"pending_review"}
        for p in proposals:
            if (p.get("type") == proposal["type"]
                    and p.get("channel") == "advisory_gate"
                    and p.get("status") in _active):
                return  # already present
        proposals.append(proposal)
        with audit_path.open("w", encoding="utf-8") as f:
            json.dump(audit, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # never block the pipeline on proposal write failure


async def start_pz(
    audit: dict,
    audit_path: Path,
    trigger_source: str,
    actor: str,
) -> None:
    """Validate preconditions before PZ engine runs. Non-destructive.

    In advisory mode (settings.advisory_gates_enabled=True) the SAD guard
    returns an advisory dict instead of raising; we persist it as an
    action_proposal so it is visible in the Inbox, then continue.
    The wFirma write flags remain hard-gated separately.
    """
    advisory = guard_pz_requires_sad(audit)
    if advisory:
        # Persist advisory as an Inbox action_proposal (not just a log line)
        batch_id = audit.get("batch_id", "")
        proposal = _advisory_to_action_proposal(advisory, batch_id, trigger_source)
        _write_advisory_proposal(audit_path, proposal)
        tl.log_event(audit_path, "advisory_gate_bypassed", trigger_source, actor,
                     detail={"advisory": advisory, "proposal_id": proposal["proposal_id"]})
    guard_trigger_declared(trigger_source)
    guard_status_transition(audit.get("status", ""), "processing")
    tl.log_event(audit_path, tl.EV_PROCESSING_STARTED, trigger_source, actor,
                 detail={"trigger": trigger_source, "actor": actor,
                         "advisory": advisory})


async def record_pz_result(
    audit_path: Path,
    status: str,
    trigger_source: str,
    actor: str,
    detail: dict | None = None,
) -> None:
    """Record the PZ result event after the engine completes."""
    event = tl.EV_PZ_GENERATED if status in ("success", "partial") else tl.EV_PZ_BLOCKED
    tl.log_event(audit_path, event, trigger_source, actor, detail=detail)
