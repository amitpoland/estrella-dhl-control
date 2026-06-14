"""
dhl_followup_authority.py — Advisory 4-state follow-up authority.

Pure projection-of-projection: derives follow-up authority status from
projector row dicts. No new data sources, no side effects, advisory-only.

Four states (precedence: completed > blocked > eligible > waiting):
- completed: DSK received or terminal mode state
- blocked: waiting for customs docs or guard-suppressed
- eligible: actively monitored, next_due in past, not blocked
- waiting: actively monitored, next_due in future or not scheduled

Lesson E compliance: No email sends, no restricted imports, no SMTP.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now_utc() -> datetime:
    """Get current UTC time."""
    return datetime.now(timezone.utc)


def _parse_iso(s: Any) -> Optional[datetime]:
    """Parse ISO timestamp, return None on error."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def derive_followup_authority(row: dict) -> dict:
    """Advisory 4-state follow-up authority derived from a projector row.

    Args:
        row: Dict from project_shipment_rows() containing fields like:
             awb, batch_id, mode_state, status, next_due_at, waiting_for,
             dsk_received_at, sad_followup_reason

    Returns:
        {
            "followup_authority": "waiting" | "eligible" | "blocked" | "completed",
            "authority_reason": str,  # Human-readable explanation
            "authority_evidence": dict  # Row fields used in decision
        }
    """
    now = _now_utc()
    authority_evidence = {}

    # Extract key fields for decision logic
    dsk_received_at = row.get("dsk_received_at")
    mode_state = row.get("mode_state")
    waiting_for = row.get("waiting_for")
    sad_followup_reason = row.get("sad_followup_reason")
    next_due_at = row.get("next_due_at")
    status = row.get("status")

    # Track evidence used in decision
    authority_evidence["dsk_received_at"] = dsk_received_at
    authority_evidence["mode_state"] = mode_state
    authority_evidence["waiting_for"] = waiting_for
    authority_evidence["sad_followup_reason"] = sad_followup_reason
    authority_evidence["next_due_at"] = next_due_at
    authority_evidence["status"] = status

    # State precedence: completed > blocked > eligible > waiting

    # 1. COMPLETED - DSK received or terminal mode state
    if dsk_received_at:
        return {
            "followup_authority": "completed",
            "authority_reason": "DSK received",
            "authority_evidence": authority_evidence
        }

    # Check for terminal mode states (if mode_state indicates completion)
    if mode_state and "terminal" in str(mode_state).lower():
        return {
            "followup_authority": "completed",
            "authority_reason": f"Terminal mode state: {mode_state}",
            "authority_evidence": authority_evidence
        }

    # 2. BLOCKED - waiting for customs docs or guard suppression
    if waiting_for and "customs" in str(waiting_for).lower():
        return {
            "followup_authority": "blocked",
            "authority_reason": f"Waiting for customs docs: {waiting_for}",
            "authority_evidence": authority_evidence
        }

    if sad_followup_reason and ("suppress" in str(sad_followup_reason).lower() or
                               "guard" in str(sad_followup_reason).lower()):
        return {
            "followup_authority": "blocked",
            "authority_reason": f"Guard suppressed: {sad_followup_reason}",
            "authority_evidence": authority_evidence
        }

    # 3. ELIGIBLE - actively monitored, next_due in past, not blocked
    if next_due_at:
        next_due_dt = _parse_iso(next_due_at)
        if next_due_dt and next_due_dt <= now:
            # Check if actively monitored by status
            if status in ("Eligible", "Monitoring", "Waiting"):
                return {
                    "followup_authority": "eligible",
                    "authority_reason": f"Next due in past ({next_due_at}), actively monitored",
                    "authority_evidence": authority_evidence
                }

    # 4. WAITING - actively monitored with future next_due or not scheduled
    if status in ("Monitoring", "Waiting", "Eligible"):
        if next_due_at:
            next_due_dt = _parse_iso(next_due_at)
            if next_due_dt and next_due_dt > now:
                return {
                    "followup_authority": "waiting",
                    "authority_reason": f"Next due in future ({next_due_at})",
                    "authority_evidence": authority_evidence
                }
        else:
            return {
                "followup_authority": "waiting",
                "authority_reason": "Actively monitored but no schedule yet",
                "authority_evidence": authority_evidence
            }

    # Default fallback - any row not matching higher states falls to waiting
    return {
        "followup_authority": "waiting",
        "authority_reason": f"Default fallback (status: {status})",
        "authority_evidence": authority_evidence
    }


def summarize_followup_authority(rows: list) -> dict:
    """Counts by authority state.

    Args:
        rows: List of dicts from project_shipment_rows()

    Returns:
        {"waiting": int, "eligible": int, "blocked": int, "completed": int}
    """
    counts = {
        "waiting": 0,
        "eligible": 0,
        "blocked": 0,
        "completed": 0
    }

    for row in rows:
        if not isinstance(row, dict):
            continue
        authority = derive_followup_authority(row)
        state = authority.get("followup_authority", "waiting")
        if state in counts:
            counts[state] += 1

    return counts