"""
customs.py — Customs description / SAD-ready pipeline
=======================================================
Handles: HS classification → Polish description → SAD-ready JSON
Trigger sources: user (approve in dashboard), system (post-DHL)
Guard: Batch must exist
"""
from __future__ import annotations
from pathlib import Path
from ..core import timeline as tl
from ..core.guards import guard_sad_requires_batch, guard_trigger_declared


async def start_customs_description(
    audit: dict,
    audit_path: Path,
    trigger_source: str,
    actor: str,
) -> None:
    guard_sad_requires_batch(audit)
    guard_trigger_declared(trigger_source)
    tl.log_event(audit_path, tl.EV_DESCRIPTION_READY, trigger_source, actor,
                 detail={"phase": "customs_description_started"})
