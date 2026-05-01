"""
email_sender.py — Real SMTP delivery for queued emails.

Honest contract:
  - Marks queue entry as 'sent' ONLY after the SMTP server returns success.
  - Idempotent: a second call on an already-sent entry returns the existing
    state without re-sending.
  - When SMTP credentials are missing, returns a clear `smtp_not_configured`
    error and leaves the queue entry at its current status.

Public API:
    send_queued_email(queue_id: str) -> dict
"""
from __future__ import annotations

import json
import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.config import settings
from ..core import timeline as tl
from ..utils.io import write_json_atomic

log = logging.getLogger(__name__)


# ── Errors ────────────────────────────────────────────────────────────────────

class EmailSendError(RuntimeError):
    """Raised when send fails — message is safe to surface to UI."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _queue_path() -> Path:
    return settings.storage_root / "email_queue.json"


def _load_queue() -> List[Dict[str, Any]]:
    p = _queue_path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_queue(queue: List[Dict[str, Any]]) -> None:
    write_json_atomic(_queue_path(), queue)


def _find_queue_entry(queue_id: str) -> Optional[Dict[str, Any]]:
    for e in _load_queue():
        if e.get("id") == queue_id:
            return e
    return None


def _split_recipients(value: str) -> List[str]:
    if not value:
        return []
    return [a.strip() for a in str(value).split(",") if a.strip()]


def _dedupe_addresses(addrs: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for a in addrs:
        key = a.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(a.strip())
    return out


def _attachments_for_queue(queue_entry: Dict[str, Any]) -> Tuple[List[Path], List[str]]:
    """
    Resolve attachment paths for this queue entry by reading the linked batch's
    audit.json (agency_reply_package or dhl_reply_package). Returns
    (existing_paths, missing_labels).
    """
    batch_id = queue_entry.get("batch_id", "")
    if not batch_id:
        return [], []
    audit_path = settings.storage_root / "outputs" / batch_id / "audit.json"
    if not audit_path.exists():
        audit_path = settings.storage_root / "working" / batch_id / "audit.json"
    if not audit_path.exists():
        return [], []
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception:
        return [], []

    # Prefer the package whose email_id matches this queue entry
    qid = queue_entry.get("id", "")
    candidates = []
    for key in ("agency_reply_package", "dhl_reply_package"):
        pkg = audit.get(key) or {}
        if pkg.get("email_id") == qid:
            candidates = pkg.get("attachments") or []
            break
    if not candidates:
        # Fallback: union of all packages
        for key in ("agency_reply_package", "dhl_reply_package"):
            pkg = audit.get(key) or {}
            for a in (pkg.get("attachments") or []):
                candidates.append(a)

    found: List[Path] = []
    missing: List[str] = []
    for a in candidates:
        path_str = a.get("path") if isinstance(a, dict) else ""
        if path_str:
            p = Path(path_str)
            if p.is_file():
                found.append(p)
            else:
                missing.append(a.get("label") or path_str)
    return found, missing


def _build_mime(
    sender:     str,
    to_list:    List[str],
    cc_list:    List[str],
    subject:    str,
    body_text:  str,
    body_html:  str,
    attachments: List[Path],
) -> MIMEMultipart:
    msg = MIMEMultipart("mixed")
    msg["From"]    = sender
    msg["To"]      = ", ".join(to_list)
    if cc_list:
        msg["Cc"]  = ", ".join(cc_list)
    msg["Subject"] = subject
    msg["Date"]    = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()

    # Read-receipt request: opt-in via settings.email_read_receipt_enabled.
    # Receipt mailbox defaults to the sender so notifications return to the
    # same identity. Non-fatal if either setting is absent.
    if getattr(settings, "email_read_receipt_enabled", False):
        rcpt = getattr(settings, "email_read_receipt_to", "") or sender
        if rcpt:
            msg["Disposition-Notification-To"] = rcpt
            msg["Return-Receipt-To"]           = rcpt
            msg["X-Confirm-Reading-To"]        = rcpt

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(body_text or "", "plain", "utf-8"))
    if body_html:
        alt.attach(MIMEText(body_html, "html", "utf-8"))
    msg.attach(alt)

    for p in attachments:
        with open(p, "rb") as f:
            part = MIMEApplication(f.read(), Name=p.name)
        part["Content-Disposition"] = f'attachment; filename="{p.name}"'
        msg.attach(part)
    return msg


def _smtp_configured() -> bool:
    return bool(settings.smtp_user and settings.smtp_password and settings.smtp_host)


# ── Public API ────────────────────────────────────────────────────────────────

def send_queued_email(
    queue_id:         str,
    method:           str = "smtp",
    confirm_mcp_send: bool = False,
    approved_by:      Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send one queued email via the requested method. Honest, idempotent.

    Methods:
      "smtp"           — primary; real SMTP delivery
      "zoho_mcp"       — fallback; requires confirm_mcp_send=True AND approved_by;
                         refused when total attachment size > MCP cap
                         (alias "mcp" accepted for back-compat)
      "manual_package" — emergency; returns the assembled package (no send)

    Returns include `available_methods` so the UI can show fallback options.
    """
    method = (method or "smtp").lower()
    # Back-compat alias
    if method == "mcp":
        method = "zoho_mcp"
    if method not in ("smtp", "zoho_mcp", "manual_package"):
        return {"ok": False, "queue_id": queue_id, "status": "unknown",
                "error": "unknown_method",
                "error_detail": f"method must be smtp|zoho_mcp|manual_package, got {method!r}"}

    entry = _find_queue_entry(queue_id)
    if not entry:
        return {
            "ok":       False,
            "queue_id": queue_id,
            "status":   "not_found",
            "error":    f"Queue entry {queue_id} not found.",
        }

    # ── Idempotency: don't re-send ─────────────────────────────────────────
    if entry.get("status") == "sent":
        return {
            "ok":                True,
            "queue_id":          queue_id,
            "status":            "sent",
            "provider_message_id": entry.get("provider_message_id"),
            "sent_at":           entry.get("sent_at"),
            "recipients":        {
                "to": _split_recipients(entry.get("to", "")),
                "cc": _split_recipients(entry.get("cc", "")),
            },
            "already_sent":      True,
        }

    # ── Method routing: manual_package / mcp / smtp ──────────────────────
    if method == "manual_package":
        return _build_manual_package(entry)

    if method == "zoho_mcp":
        # Email Evidence V2: MCP send is disabled. SMTP and manual_package are the
        # only supported production paths. The legacy `_send_via_mcp` handoff producer
        # is kept intact for now (do not delete) but unreachable from this entry point.
        return {
            "ok": False, "queue_id": queue_id,
            "status": entry.get("status", "pending"),
            "error": "mcp_send_disabled",
            "error_detail": (
                "Sending via Zoho MCP is disabled. Use SMTP (recommended) or "
                "manual_package fallback. Inbound MCP read paths are unaffected."
            ),
            "available_methods": ["smtp", "manual_package"],
        }

    # ── SMTP creds check ──────────────────────────────────────────────────
    if not _smtp_configured():
        return {
            "ok":       False,
            "queue_id": queue_id,
            "status":   entry.get("status", "pending"),
            "error":    "SMTP_NOT_CONFIGURED",
            "error_detail": (
                "SMTP credentials missing. Set SMTP_USER and SMTP_PASSWORD in .env "
                "(generate Zoho App Password at https://accounts.zoho.in/home#security/app_passwords). "
                "Use manual_package while waiting."
            ),
            "available_methods": ["manual_package"],
        }

    # ── Build recipients (deduplicate To/Cc) ──────────────────────────────
    to_list = _dedupe_addresses(_split_recipients(entry.get("to", "")))
    raw_cc  = _dedupe_addresses(_split_recipients(entry.get("cc", "")))
    to_norm = {a.lower() for a in to_list}
    cc_list = [a for a in raw_cc if a.lower() not in to_norm]

    if not to_list:
        return {
            "ok":       False,
            "queue_id": queue_id,
            "status":   entry.get("status", "pending"),
            "error":    "no_recipients",
            "error_detail": "Queue entry has no TO recipients.",
        }

    # ── Resolve attachments ───────────────────────────────────────────────
    attach_paths, missing = _attachments_for_queue(entry)
    if missing:
        return {
            "ok":       False,
            "queue_id": queue_id,
            "status":   entry.get("status", "pending"),
            "error":    "attachments_missing",
            "error_detail": f"Files not found on disk: {missing}",
        }

    # SMTP authenticates as smtp_user (amit@), but FROM may be an alias
    # configured on the same Zoho mailbox (import@, info@, account@).
    # Zoho permits this when the alias is in sendMailDetails for the account.
    auth_user   = settings.smtp_user or ""
    sender_addr = (entry.get("from_address") or "").strip() or auth_user

    # ── Build MIME ────────────────────────────────────────────────────────
    msg = _build_mime(
        sender=sender_addr,
        to_list=to_list,
        cc_list=cc_list,
        subject=entry.get("subject", ""),
        body_text=entry.get("body_text", ""),
        body_html=entry.get("body_html", ""),
        attachments=attach_paths,
    )

    # ── Connect + send ────────────────────────────────────────────────────
    all_recipients = to_list + cc_list
    log.info(
        "[email_sender] sending queue=%s subject=%r to=%d cc=%d attach=%d host=%s",
        queue_id, entry.get("subject", ""), len(to_list), len(cc_list),
        len(attach_paths), settings.smtp_host,
    )
    try:
        ctx = ssl.create_default_context()
        if settings.smtp_use_ssl:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port,
                                  context=ctx, timeout=30) as smtp:
                smtp.login(auth_user, settings.smtp_password)
                smtp.send_message(msg, from_addr=sender_addr, to_addrs=all_recipients)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
                smtp.starttls(context=ctx)
                smtp.login(auth_user, settings.smtp_password)
                smtp.send_message(msg, from_addr=sender_addr, to_addrs=all_recipients)
    except smtplib.SMTPAuthenticationError as exc:
        log.warning("[email_sender] auth failed for %s: %s", queue_id, exc)
        return {
            "ok":       False,
            "queue_id": queue_id,
            "status":   entry.get("status", "pending"),
            "error":    "smtp_auth_failed",
            "error_detail": "SMTP authentication failed — check SMTP_USER and SMTP_PASSWORD.",
        }
    except Exception as exc:
        log.warning("[email_sender] send failed for %s: %s", queue_id, exc)
        return {
            "ok":       False,
            "queue_id": queue_id,
            "status":   entry.get("status", "pending"),
            "error":    "smtp_send_failed",
            "error_detail": f"{type(exc).__name__}: {exc}",
        }

    # ── Mark sent (idempotent) ────────────────────────────────────────────
    now_iso     = datetime.now(timezone.utc).isoformat()
    provider_id = msg["Message-ID"]
    queue       = _load_queue()
    for e in queue:
        if e.get("id") == queue_id:
            e["status"]              = "sent"
            e["sent_at"]             = now_iso
            e["provider_message_id"] = provider_id
            e["sent_via"]            = "smtp_zoho"
            break
    _save_queue(queue)

    # ── Update audit.{agency,dhl}_reply_package + timeline ────────────────
    batch_id = entry.get("batch_id", "")
    pkg_kind = "unknown"
    if batch_id:
        audit_path = settings.storage_root / "outputs" / batch_id / "audit.json"
        if not audit_path.exists():
            audit_path = settings.storage_root / "working" / batch_id / "audit.json"
        if audit_path.exists():
            try:
                audit = json.loads(audit_path.read_text(encoding="utf-8"))
                for key in ("agency_reply_package", "dhl_reply_package"):
                    pkg = audit.get(key) or {}
                    if pkg.get("email_id") == queue_id:
                        pkg["status"]              = "sent"
                        pkg["sent_at"]             = now_iso
                        pkg["provider_message_id"] = provider_id
                        pkg["send_verified"]       = True
                        pkg["sent_via"]            = "smtp_zoho"
                        # Drop any prior risk_flag from inferred-confirmation flow
                        pkg["risk_flag"]           = False
                        audit[key] = pkg
                        pkg_kind = key
                        break
                write_json_atomic(audit_path, audit)
                event = ("agency_email_sent_verified" if pkg_kind == "agency_reply_package"
                         else "dhl_reply_sent_verified" if pkg_kind == "dhl_reply_package"
                         else "email_sent")
                tl.log_event(audit_path, event, "system", "email_sender", detail={
                    "queue_id":            queue_id,
                    "provider_message_id": provider_id,
                    "to_count":            len(to_list),
                    "cc_count":            len(cc_list),
                    "attachments_count":   len(attach_paths),
                })
            except Exception as exc:
                log.warning("[email_sender] audit update failed for %s: %s", queue_id, exc)

    return {
        "ok":                  True,
        "queue_id":            queue_id,
        "status":              "sent",
        "provider_message_id": provider_id,
        "sent_at":             now_iso,
        "recipients":          {"to": to_list, "cc": cc_list, "count": len(all_recipients)},
        "attachments_count":   len(attach_paths),
        "package_kind":        pkg_kind,
    }


# ── Manual package fallback ──────────────────────────────────────────────────

def _build_manual_package(entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Assemble a copy-paste-ready package for the operator to send via Zoho UI.
    Does NOT mark sent. Status stays 'pending' until mark_manually_sent() runs.
    """
    to_list = _dedupe_addresses(_split_recipients(entry.get("to", "")))
    raw_cc  = _dedupe_addresses(_split_recipients(entry.get("cc", "")))
    to_norm = {a.lower() for a in to_list}
    cc_list = [a for a in raw_cc if a.lower() not in to_norm]

    attach_paths, missing = _attachments_for_queue(entry)
    attachments = [
        {"filename": p.name, "path": str(p), "size_bytes": p.stat().st_size}
        for p in attach_paths
    ]

    return {
        "ok":       True,
        "queue_id": entry.get("id"),
        "status":   entry.get("status", "pending"),
        "method":   "manual_package",
        "package":  {
            "to":        to_list,
            "cc":        cc_list,
            "subject":   entry.get("subject", ""),
            "body_text": entry.get("body_text", ""),
            "body_html": entry.get("body_html", ""),
            "attachments":      attachments,
            "attachments_missing": missing,
        },
        "instructions": (
            "1. Open Zoho Mail compose. 2. Paste TO/CC/Subject/Body. "
            "3. Drag the listed attachment files in. 4. Send. "
            "5. POST /api/v1/admin/email-queue/<queue_id>/sent to mark verified."
        ),
    }


# ── MCP fallback (Zoho Mail MCP send + uploadAttachments) ────────────────────

def _send_via_mcp(entry: Dict[str, Any], approved_by: Optional[str] = None) -> Dict[str, Any]:
    """
    Validate a Zoho MCP send. Refuse when total attachment size exceeds the
    configured cap.

    The actual MCP call (uploadAttachments → sendEmail/sendReplyEmail) must
    happen in the orchestrator (Claude session). The backend can't invoke MCP
    tools. This function VALIDATES the request and returns a structured
    `ready_for_mcp` handoff for the orchestrator to act on. After the MCP
    relay completes, the orchestrator POSTs the provider message_id back via
    /api/v1/admin/email-queue/{id}/sent which marks status=sent + verified.

    Returns include `mode` = "send" | "reply" so the orchestrator picks
    sendEmail vs sendReplyEmail.
    """
    attach_paths, missing = _attachments_for_queue(entry)
    if missing:
        return {
            "ok": False, "queue_id": entry.get("id"),
            "status": entry.get("status", "pending"),
            "error": "attachments_missing",
            "error_detail": f"Files not on disk: {missing}",
        }
    total_bytes = sum(p.stat().st_size for p in attach_paths)
    cap = settings.mcp_send_max_attachment_bytes
    if total_bytes > cap:
        return {
            "ok":     False,
            "queue_id": entry.get("id"),
            "status": entry.get("status", "pending"),
            "error":  "mcp_attachments_too_large",
            "error_detail": (
                f"Total attachment size {total_bytes:,} bytes exceeds "
                f"MCP cap {cap:,} bytes. Use SMTP or manual_package instead."
            ),
            "total_bytes": total_bytes,
            "cap_bytes":   cap,
        }

    to_list = _dedupe_addresses(_split_recipients(entry.get("to", "")))
    raw_cc  = _dedupe_addresses(_split_recipients(entry.get("cc", "")))
    to_norm = {a.lower() for a in to_list}
    cc_list = [a for a in raw_cc if a.lower() not in to_norm]

    # Detect reply context — if the queue entry references a thread / parent
    # message, the orchestrator should use sendReplyEmail; otherwise sendEmail.
    reply_to_message_id = entry.get("reply_to_message_id") or ""
    reply_to_thread_id  = entry.get("reply_to_thread_id")  or ""
    mode = "reply" if (reply_to_message_id or reply_to_thread_id) else "send"

    return {
        "ok":          True,
        "queue_id":    entry.get("id"),
        "status":      entry.get("status", "pending"),
        "method":      "zoho_mcp",
        "approved_by": approved_by,
        "ready_for_mcp": {
            "mode":         mode,                 # "send" or "reply"
            "mcp_tool":     "ZohoMail_sendReplyEmail" if mode == "reply" else "ZohoMail_sendEmail",
            "account_id":   "2261204000000002002",
            "from_address": "amit@estrellajewels.eu",
            "to":           to_list,
            "cc":           cc_list,
            "subject":      entry.get("subject", ""),
            "body_text":    entry.get("body_text", ""),
            "body_html":    entry.get("body_html", ""),
            "reply_to_message_id": reply_to_message_id or None,
            "reply_to_thread_id":  reply_to_thread_id or None,
            "attachments": [{"filename": p.name, "path": str(p),
                              "size_bytes": p.stat().st_size}
                             for p in attach_paths],
            "total_bytes": total_bytes,
        },
        "next_step": (
            "Orchestrator (Claude session) uploads attachments via "
            "ZohoMail_uploadAttachments, then sends via the listed mcp_tool. "
            "After MCP confirms, POST /api/v1/admin/email-queue/<queue_id>/sent "
            "to mark queue + audit as sent_via=zoho_mcp + send_verified=true."
        ),
    }
