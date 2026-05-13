"""
routes_dhl_followup.py — Manual control over DHL follow-up SLA per batch.

Endpoints:
  POST /api/v1/dhl-followup/{batch_id}/stop          — operator stops SLA
  POST /api/v1/dhl-followup/{batch_id}/send-now      — fire a follow-up now
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
