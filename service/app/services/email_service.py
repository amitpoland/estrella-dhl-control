"""
email_service.py — Outbound email for Estrella PZ auth events.

Primary:  Zoho Mail REST API (needs ZOHO_MAIL_* env vars)
Fallback: JSON queue at storage_root/email_queue.json
          → Admin can view via GET /api/v1/admin/email-queue
          → Claude (MCP) can pick up and send via ZohoMail MCP connector
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional

from ..core.config import settings
from ..core.logging import get_logger
from ..utils.io import write_json_atomic

log = get_logger(__name__)

# ── Zoho Mail constants (from memory — Estrella Jewels account) ───────────────
ZOHO_ACCOUNT_ID  = "2261204000000002002"
ZOHO_FROM_EMAIL  = "info@estrellajewels.eu"
ZOHO_FROM_NAME   = "Estrella Jewels"
ZOHO_SEND_ID     = "2261204000001932001"   # "INFO" send address ID


# ── PR-211 extension: enqueue-time refusal exception ─────────────────────
#
# Raised by queue_email when the operator-rule guard determines that a
# follow-up must NOT enter the queue — i.e. the shipment is already
# delivered (= closed) or another pending entry for the same
# (batch_id, email_type, recipients) is already in flight.
#
# Callers should treat this as a non-fatal refusal: the email was never
# queued, no SMTP was attempted, no audit was mutated.  Catch + log;
# do not retry without re-checking the shipment state.

class FollowupSuppressedError(RuntimeError):
    """queue_email refused to enqueue because of a hard guard.

    The exception carries:
      - reason  : one of "shipment_delivered" / "duplicate_pending"
      - batch_id: the shipment that triggered the refusal
      - detail  : human-readable explanation safe to surface to UI / logs

    Catch by callers that want to surface the refusal to the operator
    without crashing the surrounding flow.
    """

    def __init__(self, reason: str, batch_id: str, detail: str = ""):
        self.reason   = reason
        self.batch_id = batch_id
        self.detail   = detail
        super().__init__(detail or f"queue_email refused ({reason}) for batch_id={batch_id!r}")


def _queue_file() -> Path:
    """Resolve queue path at runtime so test overrides of settings.storage_root are respected."""
    return settings.storage_root / "email_queue.json"


def _find_pending_duplicate(batch_id: str, email_type: str, to: str) -> Optional[dict]:
    """Return an existing pending queue entry matching the idempotency
    key (batch_id, email_type, recipients) or None.

    Read-only.  Uses :func:`shipment_delivered_guard.build_idempotency_key`
    so the key shape stays canonical across producers (UI, scheduler,
    cowork pipeline).

    Considers only entries with ``status='pending'`` — terminal entries
    (``sent``, ``suppressed_delivered``, ``expired_stale_queue``) are
    ignored because the spec says "prevent duplicate PENDING follow-ups
    for same key".
    """
    bid = (batch_id or "").strip()
    if not bid:
        return None
    try:
        from .shipment_delivered_guard import build_idempotency_key as _build_key
    except Exception:
        return None
    target_key = _build_key(bid, email_type, to)
    p = _queue_file()
    if not p.exists():
        return None
    try:
        queue = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(queue, list):
        return None
    for e in queue:
        if not isinstance(e, dict):
            continue
        if (e.get("status") or "") != "pending":
            continue
        cur_key = _build_key(
            e.get("batch_id") or "",
            e.get("email_type") or "",
            e.get("to") or "",
        )
        if cur_key == target_key:
            return e
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def queue_email(
    to:        str,
    subject:   str,
    body_html: str,
    body_text: str = "",
    batch_id:  str = "",
    cc:        str = "",   # comma-separated CC string; use email_routing.format_cc()
    from_address: str = "",   # override default sender (e.g. "import@estrellajewels.eu")
    email_type:   str = "",   # "agency" | "dhl_reply" | "" (default)
    attachments:  Optional[list] = None,  # list of {"label": str, "path": str} dicts
) -> str:
    """
    Add an email to the persistent queue.
    Returns the email ID.

    Parameters
    ----------
    to          : Primary recipient(s) — comma-separated string or single address.
    cc          : CC recipients — comma-separated string. Use email_routing.format_cc().
    attachments : Attachment metadata list — [{"label": "...", "path": "/abs/path"}].
                  Storing paths HERE (not just in audit.json) avoids a timing race:
                  queue_email() attempts immediate SMTP delivery synchronously, BEFORE
                  the caller has a chance to write audit["agency_reply_package"] to disk.
                  Without this, _attachments_for_queue() sees an empty audit and the
                  integrity guard cannot fire. Pass attachments= on every customs email.
    batch_id    : Optional — links queue entry back to a shipment batch for
                  delivery confirmation propagation (see mark_sent + routes_admin).
    """
    if not to or not to.strip():
        raise ValueError("queue_email: 'to' is required — cannot queue email without recipients")

    # ── PR-211 extension: enqueue-time delivered-shipment guard ─────────
    # Operator rule: if shipment is delivered, follow-up is closed.  The
    # send-time guard already exists inside email_sender.send_queued_email,
    # but queue_email triggers an IMMEDIATE synchronous SMTP attempt right
    # after writing the queue entry (see "Attempt immediate SMTP delivery"
    # block below).  The dev-instance incident (Mon 21:01) confirmed that
    # rogue uvicorn copies bypass the production-side guard entirely and
    # send via their own SMTP credentials.  Guarding at the enqueue boundary
    # closes the only remaining hole: refuse to write the queue entry at
    # all if the shipment is delivered.
    #
    # The guard is best-effort: if the audit cannot be loaded (missing
    # batch_id, file absent, parse error) it allows the enqueue.  This
    # matches the documented semantics of check_send_allowed and avoids
    # blocking legitimate queueing for batches whose metadata is missing.
    if batch_id:
        try:
            from .shipment_delivered_guard import check_send_allowed as _ssa
            _g = _ssa(batch_id)
            if not _g["allowed"]:
                log.error(
                    "queue_email REFUSED ENQUEUE — shipment delivered. "
                    "batch_id=%r reason=%r to=%r email_type=%r subject=%r. "
                    "No queue entry written, no SMTP attempted. "
                    "Re-open shipment to send a follow-up.",
                    batch_id, _g["reason"], to, email_type, subject,
                )
                raise FollowupSuppressedError(
                    reason="shipment_delivered",
                    batch_id=batch_id,
                    detail=(
                        f"Shipment {batch_id!r} is delivered "
                        f"({_g['reason']}); follow-up email "
                        f"({email_type or 'generic'}) refused at enqueue."
                    ),
                )
        except FollowupSuppressedError:
            raise
        except Exception as _g_exc:
            log.warning(
                "queue_email: delivered guard failed (non-fatal): %s — "
                "proceeding with enqueue",
                _g_exc,
            )

    # ── PR-211 extension: idempotency check ─────────────────────────────
    # Prevent duplicate pending follow-ups for the same
    # (batch_id, email_type, recipients) tuple.  Returns the existing
    # entry's id rather than creating a second queue entry.  Best-effort:
    # any failure during the duplicate scan logs and falls through to
    # normal enqueue (legitimate queueing must never be blocked by a
    # bookkeeping glitch).
    if batch_id:
        try:
            _dup = _find_pending_duplicate(batch_id, email_type, to)
            if _dup is not None:
                log.info(
                    "queue_email: duplicate pending entry detected — "
                    "returning existing id=%s without creating a second "
                    "queue entry. batch_id=%r email_type=%r to=%r",
                    _dup.get("id"), batch_id, email_type, to,
                )
                return str(_dup.get("id") or "")
        except Exception as _dup_exc:
            log.warning(
                "queue_email: idempotency dedup failed (non-fatal): %s — "
                "proceeding with enqueue",
                _dup_exc,
            )

    email_id = str(uuid.uuid4())
    entry = {
        "id":         email_id,
        "queued_at":  time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status":     "pending",
        "to":         to,
        "cc":         cc or "",
        "subject":    subject,
        "body_html":  body_html,
        "body_text":  body_text or _html_to_text(body_html),
        "sent_at":    None,
        "error":      None,
        "batch_id":   batch_id,     # links to shipment audit for delivery propagation
        # Zoho Mail fields (for direct API use)
        "from_address": from_address or ZOHO_FROM_EMAIL,
        "from_name":    ZOHO_FROM_NAME,
        "account_id":   ZOHO_ACCOUNT_ID,
        "email_type":   email_type or "",
        # Attachment metadata stored directly so _attachments_for_queue() can
        # validate them during the immediate synchronous SMTP attempt that fires
        # inside this function — before the caller has written audit.json.
        # IMPORTANT: None means "not provided — use audit.json fallback".
        # [] (empty list) means "caller explicitly declared no attachments".
        # Only pass attachments= when the caller owns the file list.
        "attachments":  list(attachments) if attachments is not None else None,
    }
    _append_to_queue(entry)
    log.info("Email queued id=%s to=%s cc=%s subject=%r", email_id, to, cc or "—", subject)

    # ── Attempt immediate SMTP delivery ───────────────────────────────────
    # Try to send the moment an email is queued so the queue doesn't
    # accumulate stale pending entries. Non-fatal: if SMTP is not configured
    # or the send fails, the entry stays 'pending' for manual retry via
    # POST /api/v1/admin/email-queue/{id}/send.
    try:
        from .email_sender import send_queued_email as _smtp_send, _smtp_configured
        if _smtp_configured():
            _result = _smtp_send(email_id, method="smtp")
            if _result.get("ok"):
                log.info("Email sent immediately id=%s to=%s", email_id, to)
            else:
                log.warning(
                    "Immediate SMTP send failed — email stays pending id=%s error=%s detail=%s",
                    email_id, _result.get("error"), _result.get("error_detail", ""),
                )
    except Exception as _send_exc:
        log.warning(
            "Immediate SMTP send attempt raised (non-fatal) id=%s: %s",
            email_id, _send_exc,
        )

    # ── Email Evidence V2 — record outbound at the moment of queueing ──────
    # Deterministic & cheap; avoids racy Sent-folder scrapes. Best-effort: a
    # failure here must NEVER block the queue write that already succeeded.
    try:
        from . import email_evidence_store as _evs
        from .email_thread_mapper import (
            classify_direction as _cd, classify_sender_role as _csr,
            classify_event_type as _cet, normalise_subject as _ns,
        )
        # Look up the AWB from the batch audit if present
        _awb = ""
        if batch_id:
            from pathlib import Path as _P
            _ap = settings.storage_root / "outputs" / batch_id / "audit.json"
            if _ap.exists():
                import json as _json
                try:
                    _au = _json.loads(_ap.read_text(encoding="utf-8"))
                    _awb = str(_au.get("awb") or _au.get("tracking_no") or "")
                except Exception:
                    _awb = ""
        if _awb:
            _to_list = [x.strip() for x in (to or "").split(",") if x.strip()]
            _direction   = _cd(entry["from_address"])
            _sender_role = _csr(entry["from_address"])
            _ev_type     = _cet(direction=_direction, sender_role=_sender_role,
                                subject=subject, body=entry["body_text"],
                                attachments=[], to_addresses=_to_list)
            _evs.save_message(_awb, {
                "message_id":   email_id,    # use queue id as deterministic message_id
                "thread_id":    "queue:" + (_ns(subject) or "outbound")[:80],
                "direction":    _direction,
                "sender":       entry["from_address"],
                "to":           _to_list,
                "cc":           [x.strip() for x in (cc or "").split(",") if x.strip()],
                "subject":      subject,
                "body_text":    entry["body_text"],
                "timestamp":    entry["queued_at"],
                "event_type":   _ev_type,
                "matched_identifiers": {"awb": True},
                "attachments":  [],
                # Queued = NOT yet sent. Promoted to "sent" by mark_sent below.
                "delivery_status": "queued",
                "queued_at":       entry["queued_at"],
            }, source="smtp_outbound")
            _evs.link_batch(_awb, batch_id)
    except Exception as _e:
        log.debug("Email Evidence outbound hook failed (non-fatal): %s", _e)

    return email_id


def mark_sent(email_id: str, error: Optional[str] = None) -> None:
    """Mark a queued email as sent (or failed)."""
    queue = _load_queue()
    matched: Optional[dict] = None
    for e in queue:
        if e["id"] == email_id:
            e["status"]  = "failed" if error else "sent"
            e["sent_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            e["error"]   = error
            matched = e
    _save_queue(queue)

    # ── Email Evidence V2 — flip queued → sent in the evidence store ───────
    # Best-effort. NEVER block the queue write that already succeeded.
    if matched and not error:
        try:
            from . import email_evidence_store as _evs
            _batch = matched.get("batch_id") or ""
            _awb = ""
            if _batch:
                _ap = settings.storage_root / "outputs" / _batch / "audit.json"
                if _ap.exists():
                    try:
                        _au = json.loads(_ap.read_text(encoding="utf-8"))
                        _awb = str(_au.get("awb") or _au.get("tracking_no") or "")
                    except Exception:
                        _awb = ""
            if _awb:
                _evs.update_message(_awb, email_id, {
                    "delivery_status":     "sent",
                    "sent_at":             matched["sent_at"],
                    "provider_message_id": matched.get("provider_message_id"),
                    "processed":           True,
                    "processed_at":        matched["sent_at"],
                })
        except Exception as _e:
            log.debug("Email Evidence mark_sent hook failed (non-fatal): %s", _e)


def get_pending_emails() -> list[dict]:
    """Return all emails with status='pending'."""
    return [e for e in _load_queue() if e.get("status") == "pending"]


def get_all_emails(limit: int = 50) -> list[dict]:
    """Return recent emails (newest first)."""
    queue = _load_queue()
    return list(reversed(queue[-limit:]))


# ── Email templates ───────────────────────────────────────────────────────────

def make_approval_email(user_full_name: str, login_url: str = "https://pz.estrellajewels.eu/login") -> tuple[str, str, str]:
    """Returns (subject, body_html, body_text)."""
    subject = "Your Estrella PZ account has been approved"
    html = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; color: #1e293b; max-width: 560px; margin: 40px auto; padding: 32px; background: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0;">
  <div style="text-align:center; margin-bottom: 28px;">
    <span style="font-size: 28px; color: #b8952a;">✦</span>
    <h2 style="font-family: Georgia, serif; color: #0f172a; margin: 8px 0 0;">Estrella Jewels</h2>
    <p style="color: #64748b; font-size: 13px; margin: 4px 0 0;">Customs Control System</p>
  </div>
  <p>Hello {user_full_name},</p>
  <p>Your account request has been <strong style="color: #16a34a;">approved</strong>.</p>
  <p>You can now log in to the Estrella Customs Control system.</p>
  <div style="text-align: center; margin: 28px 0;">
    <a href="{login_url}" style="display:inline-block; background: #0f172a; color: #fff; text-decoration: none; padding: 12px 32px; border-radius: 6px; font-weight: 600; font-size: 14px;">Log In Now</a>
  </div>
  <p style="font-size: 13px; color: #64748b; border-top: 1px solid #e2e8f0; padding-top: 16px; margin-top: 28px;">
    Regards,<br>
    <strong>Estrella Jewels</strong><br>
    <a href="https://estrellajewels.eu" style="color: #b8952a;">estrellajewels.eu</a>
  </p>
</body>
</html>"""
    text = f"""Hello {user_full_name},

Your account request has been approved.

You can now log in to the Estrella Customs Control system:
{login_url}

Regards,
Estrella Jewels
https://estrellajewels.eu"""
    return subject, html, text


def make_password_reset_email(
    user_full_name: str,
    code: str,
    reset_url: str = "https://pz.estrellajewels.eu/forgot-password",
    expires_minutes: int = 30,
) -> tuple[str, str, str]:
    """Password-reset email carrying the 6-digit code to the user directly.

    Returns (subject, body_html, body_text).

    Wired by `routes_auth.forgot_password` — the prior behaviour returned
    the code in the API response body as `_debug_code` only, requiring an
    admin to manually relay it. Production incident 2026-05-13 (Tejal
    login lockout) surfaced that no automated delivery path existed.
    """
    subject = "Estrella PZ — password reset code"
    safe_name = user_full_name or "there"
    html = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; color: #1e293b; max-width: 560px; margin: 40px auto; padding: 32px; background: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0;">
  <div style="text-align:center; margin-bottom: 28px;">
    <span style="font-size: 28px; color: #b8952a;">✦</span>
    <h2 style="font-family: Georgia, serif; color: #0f172a; margin: 8px 0 0;">Estrella Jewels</h2>
    <p style="color: #64748b; font-size: 13px; margin: 4px 0 0;">Customs Control System</p>
  </div>
  <p>Hello {safe_name},</p>
  <p>A password reset was requested for your Estrella PZ account.</p>
  <p>Your 6-digit reset code is:</p>
  <div style="text-align: center; margin: 24px 0;">
    <span style="display:inline-block; background:#0f172a; color:#fff; font-family: 'Courier New', monospace; font-size: 28px; letter-spacing: 8px; padding: 16px 32px; border-radius: 6px; font-weight: 700;">{code}</span>
  </div>
  <p>This code expires in {expires_minutes} minutes.</p>
  <div style="text-align: center; margin: 24px 0;">
    <a href="{reset_url}" style="display:inline-block; background: #b8952a; color: #fff; text-decoration: none; padding: 12px 28px; border-radius: 6px; font-weight: 600; font-size: 14px;">Enter code on reset page</a>
  </div>
  <p style="font-size: 12px; color: #94a3b8;">If you did not request this reset, ignore this email — your password will not change. Contact your administrator if you suspect unauthorised activity.</p>
  <p style="font-size: 13px; color: #64748b; border-top: 1px solid #e2e8f0; padding-top: 16px; margin-top: 28px;">
    Regards,<br>
    <strong>Estrella Jewels</strong><br>
    <a href="https://estrellajewels.eu" style="color: #b8952a;">estrellajewels.eu</a>
  </p>
</body>
</html>"""
    text = f"""Hello {safe_name},

A password reset was requested for your Estrella PZ account.

Your 6-digit reset code is: {code}

This code expires in {expires_minutes} minutes.

Enter the code on the reset page: {reset_url}

If you did not request this reset, ignore this email — your password
will not change. Contact your administrator if you suspect unauthorised
activity.

Regards,
Estrella Jewels
https://estrellajewels.eu"""
    return subject, html, text


def make_rejection_email(user_full_name: str) -> tuple[str, str, str]:
    """Returns (subject, body_html, body_text)."""
    subject = "Your Estrella PZ account request"
    html = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; color: #1e293b; max-width: 560px; margin: 40px auto; padding: 32px; background: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0;">
  <div style="text-align:center; margin-bottom: 28px;">
    <span style="font-size: 28px; color: #b8952a;">✦</span>
    <h2 style="font-family: Georgia, serif; color: #0f172a; margin: 8px 0 0;">Estrella Jewels</h2>
    <p style="color: #64748b; font-size: 13px; margin: 4px 0 0;">Customs Control System</p>
  </div>
  <p>Hello {user_full_name},</p>
  <p>Your account request was <strong style="color: #dc2626;">not approved</strong> at this time.</p>
  <p>Please contact your administrator for more details.</p>
  <p style="font-size: 13px; color: #64748b; border-top: 1px solid #e2e8f0; padding-top: 16px; margin-top: 28px;">
    Regards,<br>
    <strong>Estrella Jewels</strong><br>
    <a href="https://estrellajewels.eu" style="color: #b8952a;">estrellajewels.eu</a>
  </p>
</body>
</html>"""
    text = f"""Hello {user_full_name},

Your account request was not approved at this time.
Please contact your administrator for more details.

Regards,
Estrella Jewels
https://estrellajewels.eu"""
    return subject, html, text


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_queue() -> list[dict]:
    qf = _queue_file()
    if not qf.exists():
        return []
    try:
        return json.loads(qf.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_queue(queue: list[dict]) -> None:
    qf = _queue_file()
    qf.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(qf, queue)


def _append_to_queue(entry: dict) -> None:
    queue = _load_queue()
    queue.append(entry)
    _save_queue(queue)


def _html_to_text(html: str) -> str:
    """Very basic HTML → plain text strip."""
    import re
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()
