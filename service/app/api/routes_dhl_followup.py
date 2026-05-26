"""
routes_dhl_followup.py — DHL follow-up control per batch (single-authority).

Endpoints:
  GET  /api/v1/dhl-followup/{batch_id}/mode          — read current follow-up mode + telemetry
  POST /api/v1/dhl-followup/{batch_id}/mode          — set follow-up mode {manual|automatic}
  GET  /api/v1/dhl-followup/{batch_id}/auto/preview  — preview gates + draft body (read-only)
  POST /api/v1/dhl-followup/{batch_id}/stop          — operator stops SLA
  POST /api/v1/dhl-followup/{batch_id}/send-now      — fire a follow-up now (operator-explicit)
  POST /api/v1/dhl-followup/{batch_id}/recalculate   — recompute next_followup_at
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.config import settings
from ..core.security import require_api_key
from ..core import timeline as tl
from ..utils.io import write_json_atomic

log    = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/dhl-followup", tags=["dhl-followup"])
_auth  = Depends(require_api_key)


def _audit_path(batch_id: str):
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / batch_id / "audit.json"
        if p.exists():
            return p
    raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found.")


# ── Stop ─────────────────────────────────────────────────────────────────────

class StopReq(BaseModel):
    reason:   str
    operator: Optional[str] = None


@router.post("/{batch_id}/stop", dependencies=[_auth])
def stop_followup_endpoint(batch_id: str, body: StopReq) -> Dict[str, Any]:
    """Manually stop follow-up SLA. Reason is required."""
    if not body.reason or not body.reason.strip():
        raise HTTPException(status_code=422, detail="reason is required")
    from ..services.dhl_followup_sla import stop_followup, STOP_MANUAL

    p = _audit_path(batch_id)
    audit = json.loads(p.read_text(encoding="utf-8"))
    state = audit.get("dhl_followup") or {}
    if not state.get("active"):
        return {"ok": True, "already_stopped": True, "state": state}

    full_reason = f"{STOP_MANUAL}: {body.reason.strip()}"
    if body.operator:
        full_reason += f" (by {body.operator})"
    stop_followup(audit, full_reason)
    write_json_atomic(p, audit)
    try:
        tl.log_event(p, "dhl_followup_stopped", "operator",
                     body.operator or "admin",
                     detail={"reason": body.reason, "type": "manual"})
    except Exception:
        pass
    return {"ok": True, "stopped": True, "state": audit["dhl_followup"]}


# ── Send-now ─────────────────────────────────────────────────────────────────

class SendNowReq(BaseModel):
    approved_by: str


@router.post("/{batch_id}/send-now", dependencies=[_auth])
def send_now_endpoint(batch_id: str, body: SendNowReq) -> Dict[str, Any]:
    """Fire one follow-up email immediately, regardless of next_followup_at."""
    if not body.approved_by or not body.approved_by.strip():
        raise HTTPException(status_code=422, detail="approved_by is required")

    from ..services.dhl_followup_email_builder import build_dhl_followup_email
    from ..services.email_service               import queue_email
    from ..services.email_sender                import send_queued_email, _smtp_configured
    from ..services.dhl_followup_sla            import record_followup_sent

    p = _audit_path(batch_id)
    audit = json.loads(p.read_text(encoding="utf-8"))
    state = audit.get("dhl_followup") or {}
    if not state.get("active"):
        raise HTTPException(status_code=422, detail="dhl_followup is not active")

    if (audit.get("customs_docs") or {}).get("received"):
        raise HTTPException(
            status_code=409,
            detail={
                "guard": "customs_docs_received",
                "error": "SAD already uploaded — DHL follow-up is no longer needed.",
            },
        )

    pkg = build_dhl_followup_email(audit, batch_id)
    email_id = queue_email(
        to=pkg["to"], subject=pkg["subject"],
        body_html=pkg["body_html"], body_text=pkg["body_text"],
        batch_id=batch_id, cc=pkg.get("cc", ""),
        from_address=pkg.get("from_address", ""),
        email_type=pkg.get("email_type", "dhl_followup"),
        attachments=pkg.get("attachments", []),
    )
    if not _smtp_configured():
        return {"ok": False, "queued": True, "email_id": email_id,
                "error": "smtp_not_configured"}

    out = send_queued_email(email_id, method="smtp")
    if out.get("ok") and out.get("status") == "sent":
        record_followup_sent(audit)
        write_json_atomic(p, audit)
        try:
            tl.log_event(p, "dhl_followup_sent", "operator", body.approved_by,
                         detail={"email_id": email_id,
                                 "provider_message_id": out.get("provider_message_id"),
                                 "manual": True})
        except Exception:
            pass
    return {"ok": out.get("ok"), "send_result": out, "state": audit.get("dhl_followup")}


# ── Mode authority (single-authority model, 2026-05-26) ─────────────────────
# Shipment-level follow-up mode is the sole switch between manual and
# automatic. The global DHL_ORCH_AUTO_SEND_DHL_FOLLOWUP env flag remains
# the emergency kill-all. When the global flag is OFF, no shipment auto-
# sends regardless of mode. When ON, only shipments with mode=automatic
# may auto-send (subject to all canonical guard gates). The Inbox toggles
# this state; the monitor reads it via dhl_followup_guard.

class SetModeReq(BaseModel):
    mode:     str
    operator: Optional[str] = None


@router.get("/{batch_id}/mode", dependencies=[_auth])
def get_mode_endpoint(batch_id: str) -> Dict[str, Any]:
    """Return current follow-up mode + UI telemetry (last scan, next due)."""
    from ..services.dhl_followup_mode import mode_telemetry
    p = _audit_path(batch_id)
    audit = json.loads(p.read_text(encoding="utf-8"))
    return mode_telemetry(audit)


@router.post("/{batch_id}/mode", dependencies=[_auth])
def set_mode_endpoint(batch_id: str, body: SetModeReq) -> Dict[str, Any]:
    """Persist a new follow-up mode on the shipment. Audited.

    Valid modes: 'manual', 'automatic'. Setting the same mode is a no-op.
    Operator name is recorded in the timeline event 'dhl_followup_mode_changed'.
    """
    from ..services.dhl_followup_mode import set_mode
    p = _audit_path(batch_id)
    audit = json.loads(p.read_text(encoding="utf-8"))
    op = (body.operator or "operator_inbox").strip() or "operator_inbox"
    try:
        result = set_mode(p, audit, body.mode, operator=op)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, **result}


# ── Preview (read-only — uses canonical guard + deterministic builder) ──────

@router.get("/{batch_id}/auto/preview", dependencies=[_auth])
def auto_preview_endpoint(batch_id: str) -> Dict[str, Any]:
    """Evaluate the canonical follow-up guard AND build the draft body
    without sending. Read-only — never sends, never writes.

    Single-authority guarantee: uses the SAME guard that the monitor
    sweep calls (``dhl_followup_guard.validate_followup_send_preconditions``).
    What you see in preview is exactly what the monitor would (or would
    not) send.

    AI polish is opportunistic — handled by
    ``ai_dhl_followup_drafter.enhance_email_body`` when available; falls
    back silently to the deterministic body on any error.
    """
    from ..services.dhl_followup_email_builder import build_dhl_followup_email
    from ..services.dhl_followup_guard         import validate_followup_send_preconditions
    from ..services.dhl_followup_mode          import get_mode, mode_telemetry

    p = _audit_path(batch_id)
    audit = json.loads(p.read_text(encoding="utf-8"))

    # Build deterministic package + optional AI polish (same code path as monitor)
    ai_used = False
    ai_model: Optional[str] = None
    pkg: Dict[str, Any]
    try:
        pkg = build_dhl_followup_email(audit, batch_id)
        try:
            from ..services.ai_dhl_followup_drafter import enhance_email_body
            draft = enhance_email_body(audit, batch_id, pkg)
            pkg = {**pkg, **draft.get("pkg_updates", {})}
            ai_used  = bool(draft.get("ai_used"))
            ai_model = draft.get("model_used")
        except Exception as exc:
            log.debug("[preview] ai_dhl_followup_drafter non-fatal: %s", exc)
    except Exception as exc:
        return {
            "ok":      False,
            "error":   f"build_failed: {exc}",
            "mode":    get_mode(audit),
            "telemetry": mode_telemetry(audit),
        }

    # Canonical guard — same call the monitor makes.
    guard = validate_followup_send_preconditions(audit, pkg)

    return {
        "ok":        True,
        "decision":  "preview",
        "mode":      get_mode(audit),
        "guard": {
            "ok":              guard.ok,
            "reason":          guard.reason,
            "idempotency_key": guard.idempotency_key,
            "primary_to":      guard.primary_to,
            "cc_count":        guard.cc_count,
            "attach_count":    guard.attach_count,
            "sla_age_min":     guard.sla_age_min,
            "ingest_age_min":  guard.ingest_age_min,
        },
        "package": {
            "to":           pkg.get("to"),
            "cc":           pkg.get("cc"),
            "subject":      pkg.get("subject"),
            "body_text":    pkg.get("body_text"),
            "followup_seq": pkg.get("followup_seq"),
            "ai_used":      ai_used,
            "ai_model":     ai_model,
        },
        "telemetry": mode_telemetry(audit),
    }


# ── Recalculate ──────────────────────────────────────────────────────────────

@router.post("/{batch_id}/recalculate", dependencies=[_auth])
def recalculate_endpoint(batch_id: str) -> Dict[str, Any]:
    """Recompute next_followup_at from last_followup_at (or trigger_time if none)."""
    from ..services.dhl_followup_sla import (
        calculate_next_followup_at, calculate_first_followup_at,
    )
    from datetime import datetime

    p = _audit_path(batch_id)
    audit = json.loads(p.read_text(encoding="utf-8"))
    state = audit.get("dhl_followup") or {}
    if not state.get("active"):
        raise HTTPException(status_code=422, detail="dhl_followup is not active")

    if state.get("last_followup_at"):
        anchor = datetime.fromisoformat(str(state["last_followup_at"]).replace("Z", "+00:00"))
        new_next = calculate_next_followup_at(anchor)
    else:
        anchor = datetime.fromisoformat(str(state["trigger_time"]).replace("Z", "+00:00"))
        new_next = calculate_first_followup_at(anchor)

    state["next_followup_at"] = new_next.isoformat()
    audit["dhl_followup"]     = state
    write_json_atomic(p, audit)
    return {"ok": True, "state": state}
