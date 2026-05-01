"""
pz.py — PZ calculation pipeline
=================================
Handles: SAD verification → PZ calculation → output generation
Trigger sources: bot (/submit), dashboard (process button), system (auto-submit)
Guard: PZ requires SAD
"""
from __future__ import annotations
from pathlib import Path
from ..core import timeline as tl
from ..core.guards import guard_pz_requires_sad, guard_trigger_declared, guard_status_transition


async def start_pz(
    audit: dict,
    audit_path: Path,
    trigger_source: str,
    actor: str,
) -> None:
    """Validate preconditions before PZ engine runs. Non-destructive."""
    guard_pz_requires_sad(audit)
    guard_trigger_declared(trigger_source)
    guard_status_transition(audit.get("status", ""), "processing")
    tl.log_event(audit_path, tl.EV_PROCESSING_STARTED, trigger_source, actor,
                 detail={"trigger": trigger_source, "actor": actor})


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
