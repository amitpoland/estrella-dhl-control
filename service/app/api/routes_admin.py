"""
routes_admin.py — Admin-only API endpoints.

GET  /api/v1/admin/email-queue          — list pending + recent emails
POST /api/v1/admin/email-queue/{id}/sent — mark an email as sent (for MCP relay)
GET  /api/v1/admin/authority-drift      — check authority module drift (R2)

Description authority endpoints (post-PR #741 campaign):
GET  /api/v1/admin/description-authority/status        — live compliance metrics
GET  /api/v1/admin/description-authority/review-queue  — manual rows needing review
PATCH /api/v1/admin/description-authority/{code}/description-en — operator update
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


# ── Description Authority Compliance (post-PR #741 campaign) ─────────────────

_NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma":        "no-cache",
    "Expires":       "0",
}

import re as _re

_PL_TYPE_RE = [
    ("ring",      _re.compile(r"\bPierścionek\b",            _re.IGNORECASE)),
    ("earrings",  _re.compile(r"\bKolczyki\b",               _re.IGNORECASE)),
    ("pendant",   _re.compile(r"\bWisiorek\b|\bZawieszka\b", _re.IGNORECASE)),
    ("bracelet",  _re.compile(r"\bBransoletka\b",            _re.IGNORECASE)),
    ("necklace",  _re.compile(r"\bNaszyjnik\b",              _re.IGNORECASE)),
]


def _classify_product_type(description_pl: str) -> str:
    for typ, pat in _PL_TYPE_RE:
        if pat.search(description_pl or ""):
            return typ
    return "other"


@router.get("/description-authority/status")
def description_authority_status(user: dict = Depends(require_admin)) -> JSONResponse:
    """Live compliance metrics for all product_descriptions rows."""
    import sqlite3 as _sql
    from collections import Counter
    from ..core.config import settings
    from ..services.description_length_policy import validate_description_line

    db_path = settings.storage_root / "documents.db"
    if not db_path.exists():
        return JSONResponse(status_code=503, content={"error": "documents.db not found"},
                            headers=_NO_CACHE)

    conn = _sql.connect(str(db_path))
    conn.row_factory = _sql.Row
    try:
        rows = conn.execute(
            "SELECT product_code, description_pl, description_en, source, updated_at "
            "FROM product_descriptions ORDER BY product_code"
        ).fetchall()
    finally:
        conn.close()

    blocked_rows, warn_rows, ok_rows = [], [], []
    for row in rows:
        result = validate_description_line(row["description_pl"] or "", row["description_en"] or "")
        entry = {
            "product_code":       row["product_code"],
            "description_pl":     (row["description_pl"] or "")[:80],
            "description_en":     row["description_en"] or "",
            "source":             row["source"] or "",
            "updated_at":         row["updated_at"] or "",
            "shorthand_detected": result.shorthand_detected,
            "advisory":           (result.advisory or "")[:200],
            "product_type":       _classify_product_type(row["description_pl"] or ""),
        }
        if result.blocked:
            blocked_rows.append(entry)
        elif result.warnings:
            warn_rows.append(entry)
        else:
            ok_rows.append(entry)

    total = len(rows)
    return JSONResponse(
        content={
            "total":              total,
            "ok":                 len(ok_rows),
            "blocked":            len(blocked_rows),
            "warnings":           len(warn_rows),
            "shorthand_detected": sum(1 for e in blocked_rows if e["shorthand_detected"]),
            "missing_pl":         sum(1 for row in rows if not (row["description_pl"] or "").strip()),
            "missing_en_count":   sum(1 for row in rows if not (row["description_en"] or "").strip()),
            "blocked_by_source":  dict(Counter(e["source"] for e in blocked_rows)),
            "blocked_by_type":    dict(Counter(e["product_type"] for e in blocked_rows)),
            "top_blocked":        blocked_rows[:20],
        },
        headers=_NO_CACHE,
    )


@router.get("/description-authority/review-queue")
def description_authority_review_queue(user: dict = Depends(require_admin)) -> JSONResponse:
    """Return all source='manual' rows where validate_description_line().blocked=True."""
    import sqlite3 as _sql
    from ..core.config import settings
    from ..services.description_length_policy import validate_description_line

    db_path = settings.storage_root / "documents.db"
    if not db_path.exists():
        return JSONResponse(status_code=503, content={"error": "documents.db not found"},
                            headers=_NO_CACHE)

    conn = _sql.connect(str(db_path))
    conn.row_factory = _sql.Row
    try:
        rows = conn.execute(
            "SELECT product_code, description_pl, description_en, source, updated_at, "
            "       description_en_updated_by, description_en_updated_at, description_en_update_reason "
            "FROM product_descriptions WHERE source='manual' ORDER BY product_code"
        ).fetchall()
    finally:
        conn.close()

    queue = []
    for row in rows:
        result = validate_description_line(row["description_pl"] or "", row["description_en"] or "")
        if result.blocked:
            queue.append({
                "product_code":                row["product_code"],
                "description_pl":              row["description_pl"] or "",
                "description_en":              row["description_en"] or "",
                "source":                      row["source"] or "",
                "updated_at":                  row["updated_at"] or "",
                "description_en_updated_by":   row["description_en_updated_by"] or "",
                "description_en_updated_at":   row["description_en_updated_at"] or "",
                "description_en_update_reason": row["description_en_update_reason"] or "",
                "shorthand_detected":          result.shorthand_detected,
                "advisory":                    result.advisory,
                "product_type":                _classify_product_type(row["description_pl"] or ""),
            })

    return JSONResponse(content={"count": len(queue), "queue": queue}, headers=_NO_CACHE)


class _DescriptionEnUpdate(BaseModel):
    description_en: str
    reason:         str   # mandatory — stored in description_en_update_reason
    operator:       str   # legacy label echoed from UI; actor comes from session


@router.patch("/description-authority/{product_code:path}/description-en")
def update_description_en(
    product_code: str,
    body:         _DescriptionEnUpdate,
    user:         dict = Depends(require_admin),
) -> JSONResponse:
    """Operator update of description_en for one product_code.

    Validates via validate_description_line() before writing.
    Returns 422 if the proposed value still fails — no write occurs.
    On success writes description_en_updated_by (session email),
    description_en_updated_at (UTC), description_en_update_reason.
    """
    import sqlite3 as _sql
    import logging as _log
    from ..core.config import settings
    from ..services.description_length_policy import validate_description_line

    proposed_en = (body.description_en or "").strip()
    reason      = (body.reason or "").strip()
    actor       = user.get("email") or user.get("username") or "?"

    if not reason:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "detail": "reason is required and must not be blank."},
            headers=_NO_CACHE,
        )

    db_path = settings.storage_root / "documents.db"
    if not db_path.exists():
        raise HTTPException(status_code=503, detail="documents.db not found")

    conn = _sql.connect(str(db_path))
    conn.row_factory = _sql.Row
    try:
        row = conn.execute(
            "SELECT description_pl FROM product_descriptions WHERE product_code=?",
            (product_code,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail=f"product_code {product_code!r} not found")

    result = validate_description_line(row["description_pl"] or "", proposed_en)
    if result.blocked:
        return JSONResponse(
            status_code=422,
            content={
                "ok":      False,
                "blocked": True,
                "advisory": result.advisory,
                "detail":  "Proposed description_en still fails validate_description_line().",
            },
            headers=_NO_CACHE,
        )

    conn = _sql.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE product_descriptions "
            "SET description_en=?, source='manual', updated_at=datetime('now'), "
            "    description_en_updated_by=?, "
            "    description_en_updated_at=datetime('now'), "
            "    description_en_update_reason=? "
            "WHERE product_code=?",
            (proposed_en, actor, reason, product_code),
        )
        conn.commit()
    finally:
        conn.close()

    _log.getLogger(__name__).info(
        "description-authority: %s updated description_en for %r reason=%r",
        actor, product_code, reason,
    )

    return JSONResponse(
        content={
            "ok":                          True,
            "product_code":                product_code,
            "description_en":              proposed_en,
            "source":                      "manual",
            "description_en_updated_by":   actor,
            "description_en_update_reason": reason,
            "warnings":                    result.warnings,
        },
        headers=_NO_CACHE,
    )
