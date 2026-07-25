"""Single source of truth for an operator/agent-supplied tracking update.

Two routes write the same `audit.tracking` patch:

  - ``routes_tracking.update_tracking_for_batch`` — operator / Cowork
    "Mark as Done" against a known batch.
  - ``routes_ai_bridge.import_bridge_result`` — a ``tracking_lookup`` result
    imported from an external AI tool.

They were maintained as two hand-written copies and drifted. When
``api_status``, ``updated_at`` and the top-level ``tracking_complete*`` keys
were added to the first, the second never got them, so a batch whose lookup was
closed through the AI bridge still rendered as "tracking required" and was
reverted by the next re-process. Both call this now, so the shape can only
change in one place.

The caller owns locking and persistence:

    with batch_write_lock(batch_id):
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        now = apply_tracking_update(audit, status=..., source=...)
        write_json_atomic(audit_path, audit)
"""
from __future__ import annotations

import time as _time
from typing import Any, Dict, Optional

# Legacy convention, kept deliberately: these stamps are recorded and displayed
# but never parsed (unlike pz_output.generated_at, whose false "Z" was corrected
# in 2026-07-21 because ordering depended on it). Changing the convention here
# would alter what BOTH write paths persist and belongs in its own change.
_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Statuses that mean the goods physically reached the warehouse.
_ARRIVED_STATUSES = ("delivered", "out_for_delivery")


def apply_tracking_update(
    audit:      Dict[str, Any],
    *,
    status:     str,
    source:     str,
    last_event: str = "",
    location:   str = "",
    event_time: Optional[str] = None,
    note:       Optional[str] = None,
    now:        Optional[str] = None,
    advance_workflow: bool = True,
) -> str:
    """Patch ``audit`` in place with a human/agent-supplied tracking update.

    Returns the timestamp used, so the caller can stamp related records (a
    closed proposal, a timeline event) with the same instant.

    Neither write path is ever the live carrier API, so ``api_status`` is
    ``"manual"`` regardless of ``source``. That is distinct from
    ``get_tracking_mode()``, which reports credential health
    (disabled / failed / active), and it is what ``shipment-detail.html``
    branches on to stop showing "DHL API disabled" over real tracking data.

    ``advance_workflow`` controls ONLY the three top-level ``tracking_complete*``
    keys — the workflow checkpoint. The tracking block itself is written either
    way, so evidence is never lost.

    It exists because the checkpoint is authorisation-sensitive and the callers
    are not equally privileged. ``/tracking/batch/{id}/update`` and
    ``/tracking/{awb}/cowork-result`` require ``require_role("admin",
    "logistics")``, but ``/ai-bridge/results/{task_id}`` requires only
    ``get_current_user`` — any authenticated account. Consolidating the three
    write paths (#973) inadvertently let the weakest of them set a checkpoint
    that previously needed an operator role. Callers that are not
    operator-authorised must pass ``advance_workflow=False``; they still record
    the tracking evidence, they just do not close the step.

    ``tracking_complete_source`` records who supplied it, so a consumer that
    needs to distinguish a human confirmation from an agent-inferred one can.
    """
    now = now or _time.strftime(_TS_FORMAT)

    tr = audit.setdefault("tracking", {})
    tr.update({
        "status":                   status,
        "status_label":             status.replace("_", " ").title(),
        "last_event":               last_event,
        "last_location":            location,
        "last_update":              event_time,
        "source":                   source,
        "api_status":               "manual",
        "updated_at":               now,
        "available":                True,
        "cowork_result_received":   True,
        "cowork_tracking_required": False,
        "cowork_result_at":         now,
    })
    if note:
        tr["cowork_result_note"] = note
    if status in _ARRIVED_STATUSES:
        tr["arrived_warehouse"] = True

    # Top level, not inside `tracking`: this is the workflow checkpoint the
    # dashboard reads, and audit_merge.PRESERVED_KEYS carries these three keys
    # so a re-process cannot drop the confirmation. Gated on advance_workflow
    # because setting it requires operator authority — see the docstring.
    if advance_workflow:
        audit["tracking_complete"]        = True
        audit["tracking_complete_source"] = source
        audit["tracking_complete_at"]     = now

    return now


def close_tracking_proposal(
    audit:       Dict[str, Any],
    proposal_id: str,
    source:      str,
    now:         str,
) -> bool:
    """Mark a linked ``tracking_lookup`` proposal done. True if one matched."""
    for prop in (audit.get("action_proposals") or []):
        if (prop.get("proposal_id") == proposal_id
                and prop.get("type") == "tracking_lookup"):
            prop["status"]      = "done"
            prop["done_at"]     = now
            prop["done_source"] = source
            return True
    return False
