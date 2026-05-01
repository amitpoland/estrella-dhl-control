"""
routes_admin.py — Admin-only API endpoints.

GET  /api/v1/admin/email-queue          — list pending + recent emails
POST /api/v1/admin/email-queue/{id}/sent — mark an email as sent (for MCP relay)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from ..auth.dependencies import require_admin
from ..services.email_service import (
    get_all_emails,
    get_pending_emails,
    mark_sent,
)
from ..api.routes_dhl_clearance import _update_batch_reply_delivery

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
_auth = Depends(require_admin)


@router.get("/email-queue")
def list_email_queue(user: dict = Depends(require_admin)):
    """Return all emails (newest first). Pending emails are listed separately."""
    all_emails = get_all_emails(limit=100)
    pending    = [e for e in all_emails if e.get("status") == "pending"]
    return {
        "pending_count": len(pending),
        "emails": all_emails,
    }


class MarkSentRequest(BaseModel):
    error: Optional[str] = None


@router.post("/email-queue/{email_id}/sent")
def mark_email_sent(email_id: str, body: MarkSentRequest = MarkSentRequest(), user: dict = Depends(require_admin)):
    """Mark a queued email as sent or failed (called by MCP relay after sending)."""
    mark_sent(email_id, error=body.error or None)
    delivery_status = "failed" if body.error else "sent"

    # Propagate delivery confirmation back to the batch audit if linked
    all_emails = get_all_emails(limit=200)
    batch_id = next((e.get("batch_id", "") for e in all_emails if e.get("id") == email_id), "")
    propagated = False
    if batch_id:
        propagated = _update_batch_reply_delivery(batch_id, delivery_status, error=body.error or None)

    return {
        "ok":         True,
        "email_id":   email_id,
        "status":     delivery_status,
        "batch_id":   batch_id or None,
        "propagated": propagated,
    }


# ── Send fallback ladder (SMTP → MCP → manual_package) ───────────────────────

class SendQueuedRequest(BaseModel):
    method: Optional[str]   = "smtp"   # smtp | zoho_mcp | manual_package
    approved_by: Optional[str] = None  # required for zoho_mcp
    confirm_mcp_send: bool  = False    # required for zoho_mcp


@router.post("/email-queue/{queue_id}/send")
def send_queued_email_endpoint(
    queue_id: str,
    body:     SendQueuedRequest = SendQueuedRequest(),
    user:     dict = Depends(require_admin),
):
    """
    Send a queued email through the chosen method. Idempotent. Honest.

    method=smtp (default)
        Real SMTP delivery via SMTP_HOST/PORT/USER/PASSWORD in .env.
        Returns smtp_not_configured if creds missing.
        Marks status=sent ONLY after the SMTP server returns success.

    method=mcp
        Validates the request for MCP-relay send. Requires
        confirm_mcp_send=true. Refuses if attachment payload exceeds
        MCP_SEND_MAX_ATTACHMENT_BYTES. Returns ready_for_mcp payload —
        the orchestrator (Claude session) actually performs the MCP call,
        then POSTs back to /email-queue/{id}/sent to mark verified.

    method=manual_package
        Returns the copy-paste-ready package (TO/CC/Subject/Body/attachments).
        Does NOT mark sent. Operator sends from Zoho UI, then POSTs to
        /email-queue/{id}/sent to mark sent_via=manual.
    """
    from ..services.email_sender import send_queued_email
    return send_queued_email(
        queue_id,
        method=body.method or "smtp",
        confirm_mcp_send=body.confirm_mcp_send,
        approved_by=body.approved_by,
    )
