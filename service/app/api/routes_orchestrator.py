"""routes_orchestrator.py — DHL orchestrator read-only / dry-run / manual-tick API.

Phase 1 endpoints:

    GET  /api/v1/orchestrator/state/{batch_id}
        Read-only lifecycle resolution for one batch.

    POST /api/v1/orchestrator/dry-run
        Run a single tick that never persists telemetry and never executes.

    POST /api/v1/orchestrator/tick
        Run a single tick that respects flags.  Shadow mode is honoured.
        AUTO_* flags are honoured.  Used by operators or smoke tests.

All endpoints require the existing API-key auth gate (require_api_key).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from ..core.config import settings
from ..core.security import require_api_key
from ..services import dhl_orchestrator as orch

log    = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/orchestrator", tags=["orchestrator"])
_auth  = Depends(require_api_key)


def _monitor_state(audit: Dict[str, Any]) -> Dict[str, Any]:
    """
    F1/F5-FIX: Compute monitor block state for operator visibility.

    Surfaces why the monitor hasn't swept and what the safe remediation
    action is.  Read-only — no writes, no side effects.
    """
    auto_sweep    = bool(getattr(settings, "dhl_orch_auto_monitor_sweep", False))
    auto_followup = bool(getattr(settings, "dhl_orch_auto_send_dhl_followup", False))
    shadow        = bool(getattr(settings, "dhl_orch_shadow_mode", True))

    ei = audit.get("email_ingestion") or {}
    last_scan_at = ei.get("last_scan_at")

    blocked_reason: str | None = None
    if not auto_sweep:
        blocked_reason = "manual_monitor_required"

    return {
        "auto_monitor_sweep":     auto_sweep,
        "auto_send_dhl_followup": auto_followup,
        "shadow_mode":            shadow,
        "last_scan_at":           last_scan_at,
        "blocked_reason":         blocked_reason,
        "safe_operator_action":   (
            "POST /api/v1/monitor/active-shipments/run"
            if blocked_reason else None
        ),
    }


def _attachment_readiness(audit: Dict[str, Any]) -> Dict[str, Any]:
    """Read-only summary of what attachments would be available."""
    dsk          = (audit.get("dsk_path") or "").strip()
    polish_desc  = (audit.get("polish_desc_path") or "").strip()
    sad_ready    = (audit.get("sad_ready_path") or "").strip()
    inv_count    = 0
    inputs = audit.get("inputs") or {}
    if isinstance(inputs, dict):
        invs = inputs.get("invoices") or []
        if isinstance(invs, list):
            inv_count = len(invs)
    return {
        "dsk_path":          dsk,
        "dsk_present":       bool(dsk) and Path(dsk).exists() if dsk else False,
        "polish_desc_path":  polish_desc,
        "polish_desc_present": bool(polish_desc) and Path(polish_desc).exists() if polish_desc else False,
        "sad_ready_path":    sad_ready,
        "sad_ready_present": bool(sad_ready) and Path(sad_ready).exists() if sad_ready else False,
        "invoice_count":     inv_count,
    }


def _email_readiness(audit: Dict[str, Any]) -> Dict[str, Any]:
    de = audit.get("dhl_email") or {}
    cd = audit.get("clearance_decision") or {}
    return {
        "dhl_email_received":   bool(de.get("received")),
        "dhl_email_ticket":     de.get("ticket") or "",
        "agency_email_target":  cd.get("agency_email") or "",
        "clearance_path":       cd.get("clearance_path") or "",
        "clearance_status":     audit.get("clearance_status") or "",
        "agency_package_built": bool((audit.get("agency_reply_package") or {}).get("status")),
        "dhl_package_built":    bool((audit.get("dhl_reply_package") or {}).get("status")),
    }


def _find_audit_path(batch_id: str) -> Path:
    base = settings.storage_root / "outputs" / batch_id / "audit.json"
    if base.exists():
        return base
    alt = settings.storage_root / "working" / batch_id / "audit.json"
    if alt.exists():
        return alt
    raise HTTPException(status_code=404, detail=f"audit not found for batch_id={batch_id!r}")


@router.get("/state/{batch_id}", dependencies=[_auth])
async def get_orchestrator_state(batch_id: str) -> Dict[str, Any]:
    """Read-only orchestrator state for one batch.

    Returns the lifecycle resolution, next action that would fire, blocked
    reason if any, cooldown status, shadow-mode flag, attachment readiness
    snapshot, email readiness snapshot, and the current safety-flag
    snapshot.  No writes occur.
    """
    audit_path = _find_audit_path(batch_id)
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"audit unreadable: {exc!s}")

    active, why = orch.is_active_shipment(audit)
    lifecycle = orch.resolve_state(audit)
    flags = orch._flags_snapshot()
    # Decide what would happen on the next tick (no persistence).
    decision = orch.decide_for_audit(audit, flags=flags)

    return {
        "batch_id":             batch_id,
        "awb":                  str(audit.get("awb") or audit.get("tracking_no") or ""),
        "lifecycle_state":      lifecycle,
        "active":               active,
        "active_reason":        why,
        "next_action":          decision.action,
        "blocked_reason":       decision.blocked_reason,
        "shadow":               decision.shadow,
        "idempotency_key":      decision.idempotency_key,
        "last_recorded":        (audit.get("orchestrator") or {}),
        "attachment_readiness": _attachment_readiness(audit),
        "email_readiness":      _email_readiness(audit),
        "safety_flags":         flags,
        "monitor_state":        _monitor_state(audit),
    }


@router.post("/dry-run", dependencies=[_auth])
async def orchestrator_dry_run() -> Dict[str, Any]:
    """Compute decisions for all active shipments without persisting.

    No telemetry is written.  No actions are executed.  No external calls.
    Pure diagnostic.  Safe to call from any environment.
    """
    result = orch.run_tick(persist=False)
    return {
        **result.to_dict(),
        "persisted":   False,
        "dry_run":     True,
        "shadow_mode": bool(settings.dhl_orch_shadow_mode),
    }


@router.post("/tick", dependencies=[_auth])
async def orchestrator_tick() -> Dict[str, Any]:
    """Manual operator-triggered tick.

    Respects all flags.  In shadow mode (default) this writes telemetry
    only.  Out of shadow mode, individual AUTO_* flags gate each action.
    """
    if not settings.dhl_orch_enabled:
        return {
            "ok":          False,
            "error":       "dhl_orchestrator_disabled",
            "detail":      "Set DHL_ORCH_ENABLED=true to enable the orchestrator.",
            "safety_flags": orch._flags_snapshot(),
        }
    result = orch.run_tick(persist=True)
    return {
        **result.to_dict(),
        "persisted":    True,
        "dry_run":      False,
        "shadow_mode":  bool(settings.dhl_orch_shadow_mode),
        "safety_flags": orch._flags_snapshot(),
    }
