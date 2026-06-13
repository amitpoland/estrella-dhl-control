"""
routes_admin.py — Admin-only API endpoints.

GET  /api/v1/admin/email-queue          — list pending + recent emails
POST /api/v1/admin/email-queue/{id}/sent — mark an email as sent (for MCP relay)
GET  /api/v1/admin/authority-drift      — check authority module drift (R2)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from ..auth.dependencies import require_admin
from ..core.config import settings
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


# ── Product Master backfill (PR-4) ────────────────────────────────────────────

class _ProductMasterBackfillRequest(BaseModel):
    """Default dry_run=True — operator must explicitly opt into writes.
    Mirrors the safe-by-default pattern of other admin endpoints."""
    dry_run:         bool          = True
    batch_id_filter: Optional[str] = None


@router.post("/product-master/backfill")
def trigger_product_master_backfill(
    body: _ProductMasterBackfillRequest = _ProductMasterBackfillRequest(),
    user: dict                          = Depends(require_admin),
):
    """Admin-only.  Idempotent projection of historical invoice_lines.
    product_code values into product_master.

    Behaviour:
      * default dry_run=True (returns preview, writes nothing).
      * dry_run=False executes idempotent UPSERT via PR #193's
        reservation_db.upsert_product_master helper — existing rows'
        non-empty source_* identity is preserved.
      * batch_id_filter restricts the scan to a single batch.
      * Local-DB only.  No external calls.  No schema changes.

    Returns the backfill summary directly (see
    product_master_backfill.backfill_from_invoice_lines docstring).
    """
    from ..core.config import settings
    from ..services.product_master_backfill import (
        backfill_from_invoice_lines,
    )
    result = backfill_from_invoice_lines(
        settings.storage_root,
        dry_run         = bool(body.dry_run),
        batch_id_filter = (body.batch_id_filter or "").strip() or None,
    )
    # Operator-facing audit trail.
    import logging as _logging
    _logging.getLogger(__name__).info(
        "product-master backfill triggered by user=%s dry_run=%s "
        "filter=%r → scanned_codes=%d inserted=%d updated=%d errors=%d",
        user.get("email", "?"),
        result.get("dry_run"),
        body.batch_id_filter,
        result.get("scanned_codes", 0),
        result.get("inserted", 0),
        result.get("updated", 0),
        len(result.get("errors", []) or []),
    )
    return result


# ── Authority Drift Detection (R2 — Campaign 02.5 Phase 4) ──────────────────


@router.get("/authority-drift")
def get_authority_drift(user: dict = Depends(require_admin)) -> JSONResponse:
    """R2: Authority drift detection endpoint.

    Compare live authority module hashes vs pinned manifest.
    Flag-gated: returns 503 when authority_drift_detection=False.

    Auth: admin-guarded (same pattern as other admin endpoints).
    Headers: Cache-Control: no-store per Lesson G.
    """
    # R3: Config flag check - explicit disabled reason per Lesson M
    if not settings.authority_drift_detection:
        return JSONResponse(
            status_code=503,
            content={
                "error": "Authority drift detection disabled",
                "reason": "authority_drift_detection=False in configuration",
                "action": "Set AUTHORITY_DRIFT_DETECTION=true to enable monitoring"
            },
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )

    # Import authority drift service
    try:
        from ..services.authority_drift_service import check_authority_drift

        drift_report = check_authority_drift()

        # Phase 4 alerting: emit structured alert if drift detected
        if drift_report.get("drift_detected", False):
            try:
                from ..services.authority_drift_service import emit_drift_alert
                emit_drift_alert(drift_report, user.get("email", "admin"))
            except Exception as alert_exc:
                # Don't fail the request if alerting fails
                import logging
                logging.getLogger(__name__).warning(
                    "Authority drift alert emission failed: %s", alert_exc
                )

        return JSONResponse(
            content=drift_report,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Authority drift check failed",
                "detail": str(e)
            },
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
