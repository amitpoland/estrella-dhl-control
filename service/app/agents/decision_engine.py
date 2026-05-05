"""
decision_engine.py — Centralized decision engine for batch action selection.

Single entry point: decide(batch_id)

Algorithm
---------
1. Call proposal_engine.generate(batch_id) to get all candidate actions.
2. If none → return idle state.
3. Sort by priority (high → medium → low).
4. Return the top action as primary_action plus full list for UI.

Output shape
------------
{
    "primary_action": str | None,   — Top-ranked action label
    "reason":         str | None,   — Why this action is recommended
    "next_step":      str | None,   — Extracted hint from the proposal
    "status":         str,          — "idle" | "action_required"
    "all_actions":    list,         — Full sorted list (for UI display)
    "batch_id":       str,
}
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from . import proposal_engine

log = logging.getLogger(__name__)

_PRIORITY_MAP: Dict[str, int] = {
    "high":   3,
    "medium": 2,
    "low":    1,
}


def decide(batch_id: str) -> Dict[str, Any]:
    """
    Evaluate all pending proposals for batch_id and return the single
    highest-priority action the operator should take next.

    Parameters
    ----------
    batch_id : str

    Returns
    -------
    dict with keys: primary_action, reason, next_step, status, all_actions, batch_id
    """
    proposals = proposal_engine.generate(batch_id)

    if not proposals:
        return {
            "primary_action": None,
            "reason":         None,
            "next_step":      None,
            "status":         "idle",
            "all_actions":    [],
            "batch_id":       batch_id,
        }

    for p in proposals:
        if p.get("priority", "low") not in _PRIORITY_MAP:
            log.warning(
                "decision_engine unknown priority %r for action %r batch=%s — sorted last",
                p.get("priority"), p.get("action"), batch_id,
            )

    sorted_p = sorted(
        proposals,
        key=lambda p: _PRIORITY_MAP.get(p.get("priority", "low"), 0),
        reverse=True,
    )

    top = sorted_p[0]

    return {
        "primary_action": top["action"],
        "reason":         top.get("reason"),
        "next_step":      top.get("next_step"),
        "status":         "action_required",
        "all_actions":    sorted_p,
        "batch_id":       batch_id,
    }
