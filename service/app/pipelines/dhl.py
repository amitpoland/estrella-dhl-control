"""
dhl.py — DHL customs clearance pipeline
=========================================
Handles: DHL email receipt → intent detection → DSK/description generation
Trigger sources: email (dhl_monitor), user (manual admin override)
Guard: DHL action requires email receipt
"""
from __future__ import annotations
from pathlib import Path
from ..core import timeline as tl
from ..core.guards import guard_dhl_requires_email, guard_trigger_declared


async def receive_dhl_email(
    audit: dict,
    audit_path: Path,
    ticket: str,
    awb: str,
    actor: str = "dhl_monitor",
) -> None:
    tl.log_event(audit_path, tl.EV_DHL_EMAIL_RECEIVED, "email", actor,
                 detail={"ticket": ticket or "", "awb": awb or ""})


async def start_clearance(
    audit: dict,
    audit_path: Path,
    trigger_source: str,
    actor: str,
    admin_override: bool = False,
) -> None:
    _dhl_adv = guard_dhl_requires_email(audit, admin_override)
    if _dhl_adv:
        # Advisory mode: persist to Inbox instead of silently swallowing
        from .pz import _advisory_to_action_proposal, _write_advisory_proposal
        _prop = _advisory_to_action_proposal(
            _dhl_adv, audit.get("batch_id", ""), trigger_source)
        _write_advisory_proposal(audit_path, _prop)
    guard_trigger_declared(trigger_source)
    tl.log_event(audit_path, tl.EV_CLEARANCE_STARTED, trigger_source, actor)
