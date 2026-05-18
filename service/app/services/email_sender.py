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


def _mark_queue_error(queue_id: str, error: str, error_detail: str) -> None:
    """Write a non-blocking error marker onto the queue entry so retries can
    see why a prior send was refused. Does NOT change status — the entry
    stays 'pending' so it remains retryable after the underlying issue
    (missing file, unresolved attachment) is fixed."""
    try:
        queue = _load_queue()
        for e in queue:
            if e.get("id") == queue_id:
                e["error"]              = error
                e["error_detail"]       = (error_detail or "")[:500]
                e["last_send_attempt_at"] = datetime.now(timezone.utc).isoformat()
                break
        _save_queue(queue)
    except Exception:
        pass


def _mark_queue_terminal(queue_id: str, terminal_status: str,
                         reason: str, detail: str = "") -> None:
    """Flip a queue entry to a terminal status so subsequent retry
    replays skip it.  Used by the delivered-shipment guard and the
    stale-queue guard — both must prevent any future send for the
    given queue_id without manual operator action.

    Unlike _mark_queue_error, this sets ``status`` itself.  Valid
    terminal_status values are short tokens such as
    ``"suppressed_delivered"`` or ``"expired_stale_queue"``.  Writes
    are idempotent: subsequent invocations with the same terminal
    status overwrite the marker fields but do not reset to pending.
    """
    try:
        queue = _load_queue()
        now_iso = datetime.now(timezone.utc).isoformat()
        for e in queue:
            if e.get("id") == queue_id:
                e["status"]              = terminal_status
                e["suppression_reason"]  = reason
                e["suppression_detail"]  = (detail or "")[:500]
                e["suppressed_at"]       = now_iso
                # Keep the prior error fields for forensic trace.
                break
        _save_queue(queue)
    except Exception:
        pass


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
    Resolve attachment paths for this queue entry.

    Priority order:
      0. queue_entry["attachments"]  — stored at queue time via queue_email(attachments=...)
         Preferred path; avoids the audit.json timing race where the immediate SMTP
         attempt fires before the caller writes audit["agency_reply_package"] to disk.
      1. action_proposals[*].draft.attachments  (proposal-driven emails)
      2. agency_reply_package.attachments
      3. dhl_reply_package.attachments
      4. Last-resort union of all above (legacy fallback)

    Returns (existing_paths, missing_labels).
    """
    # ── Priority 0: attachments stored directly in queue entry ───────────────
    # This is the post-fix path for all callers that pass attachments= to queue_email().
    # It avoids the timing race: queue_email() calls send_queued_email() synchronously,
    # before the caller has had a chance to write audit.json. Without this fast path
    # the integrity guards cannot fire on the first send attempt.
    direct_attachments = queue_entry.get("attachments")
    if direct_attachments is not None:  # explicit empty list [] is also authoritative
        found: List[Path] = []
        missing: List[str] = []
        _storage_root = settings.storage_root.resolve()
        for a in direct_attachments:
            path_str = a.get("path") if isinstance(a, dict) else ""
            if path_str:
                p = Path(path_str)
                try:
                    resolved = p.resolve()
                    # Security: only serve files that live under storage_root
                    resolved.relative_to(_storage_root)
                except (ValueError, OSError):
                    log.warning(
                        "[email_sender] attachment path outside storage_root — skipped: %s", path_str
                    )
                    missing.append(a.get("label") or path_str)
                    continue
                if resolved.is_file():
                    found.append(resolved)
                else:
                    missing.append(a.get("label") or path_str)
        return found, missing

    # ── Fallback: look up from batch audit.json (legacy / backwards compat) ──
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

    qid = queue_entry.get("id", "")
    candidates: List[Any] = []

    # 1. Proposal-driven email — match by proposal.email_id
    for prop in (audit.get("action_proposals") or []):
        if prop.get("email_id") == qid:
            draft = prop.get("draft") or {}
            candidates = list(draft.get("attachments") or [])
            break

    # 2/3. Reply-package fallback — match by package.email_id
    if not candidates:
        for key in ("agency_reply_package", "dhl_reply_package"):
            pkg = audit.get(key) or {}
            if pkg.get("email_id") == qid:
                candidates = list(pkg.get("attachments") or [])
                break

    # Last-resort union (unchanged legacy behaviour)
    if not candidates:
        for prop in (audit.get("action_proposals") or []):
            for a in ((prop.get("draft") or {}).get("attachments") or []):
                candidates.append(a)
        for key in ("agency_reply_package", "dhl_reply_package"):
            pkg = audit.get(key) or {}
            for a in (pkg.get("attachments") or []):
                candidates.append(a)

    found_l: List[Path] = []
    missing_l: List[str] = []
    for a in candidates:
        path_str = a.get("path") if isinstance(a, dict) else ""
        if path_str:
            p = Path(path_str)
            if p.is_file():
                found_l.append(p)
            else:
                missing_l.append(a.get("label") or path_str)
    return found_l, missing_l


def _expected_attachment_count(queue_entry: Dict[str, Any]) -> int:
    """How many attachments SHOULD this queue entry carry, per the linked
    proposal/package? Used to detect the silent-send bug where attachments
    were declared upstream but the resolver returned an empty list. Returns
    0 when no proposal or package is found, in which case 'no attachments'
    is a valid send (e.g. plain admin notification).

    Priority: queue entry's own attachments list (set at queue time) first,
    then audit.json fallback for legacy entries."""
    # Fast path: attachments stored in queue entry (post-fix path)
    direct = queue_entry.get("attachments")
    if direct is not None:
        return len(direct)

    batch_id = queue_entry.get("batch_id", "")
    if not batch_id:
        return 0
    audit_path = settings.storage_root / "outputs" / batch_id / "audit.json"
    if not audit_path.exists():
        audit_path = settings.storage_root / "working" / batch_id / "audit.json"
    if not audit_path.exists():
        return 0
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    qid = queue_entry.get("id", "")
    for prop in (audit.get("action_proposals") or []):
        if prop.get("email_id") == qid:
            return len(((prop.get("draft") or {}).get("attachments")) or [])
    for key in ("agency_reply_package", "dhl_reply_package"):
        pkg = audit.get(key) or {}
        if pkg.get("email_id") == qid:
            return len(pkg.get("attachments") or [])
    return 0


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


# ── Attachment integrity constants ────────────────────────────────────────────

# Terminal queue status for attachment validation failures.
# Distinct from 'failed' (SMTP error) so UI can show the right recovery action.
_STATUS_ATTACHMENT_VALIDATION_FAILED = "FAILED_ATTACHMENT_VALIDATION"

# Body keywords that signal the email is supposed to carry attachments.
# When any of these appear in the combined body text but attach_paths is empty,
# the guard fires regardless of email_type.
_ATTACHMENT_BODY_KEYWORDS: Tuple[str, ...] = (
    "w załączeniu",
    "w zał.",
    "w zal.",
    "w załączniku",
    "załączam",
    "załącza",
    "prosimy o weryfikację dokumentów",
    "please find attached",
    "attached please find",
    "please find enclosed",
    "please see attached",
    "see attached",
    "herewith attached",
    "herewith enclosed",
    "enclosed please find",
    "in attachment",
    "as an attachment",
    "as attachment",
    "attached hereto",
    "attached herewith",
)

# Email types that unconditionally require ≥ 1 attachment before send.
# A customs or agency email without files is always an operational error.
_ATTACHMENT_REQUIRED_EMAIL_TYPES: frozenset = frozenset({
    "agency",
    "dhl_reply",
    "dhl_proactive_dispatch",
})


def _set_terminal_failure(
    queue_id: str,
    error_code: str,
    error_detail: str,
) -> None:
    """
    Set queue entry status to FAILED_ATTACHMENT_VALIDATION — a terminal state.

    Unlike _mark_queue_error (which keeps status='pending' so the entry is
    retryable), this marks a state that requires operator action: the
    attachment issue must be fixed and the email re-built before retry.
    """
    try:
        queue = _load_queue()
        for e in queue:
            if e.get("id") == queue_id:
                e["status"]                 = _STATUS_ATTACHMENT_VALIDATION_FAILED
                e["error"]                  = error_code
                e["error_detail"]           = (error_detail or "")[:500]
                e["last_send_attempt_at"]   = datetime.now(timezone.utc).isoformat()
                e["attachment_guard_fired"] = True
                break
        _save_queue(queue)
    except Exception:
        pass  # Never block the return path — the guard result already returned False


def _log_attachment_failure_to_audit(
    queue_id: str,
    entry: Dict[str, Any],
    error_code: str,
    error_detail: str,
) -> None:
    """Write an attachment_validation_failed timeline event to the batch audit.json."""
    batch_id = entry.get("batch_id", "")
    if not batch_id:
        return
    # Security: reject path-traversal patterns in batch_id before building FS path
    if any(c in batch_id for c in ("/", "\\", "..")):
        log.warning("[email_sender] _log_attachment_failure: rejected unsafe batch_id=%r", batch_id)
        return
    for sub in ("outputs", "working"):
        audit_path = settings.storage_root / sub / batch_id / "audit.json"
        if audit_path.exists():
            try:
                tl.log_event(
                    audit_path,
                    "attachment_validation_failed",
                    trigger_source="email_sender",
                    actor="system",
                    detail={
                        "queue_id":    queue_id,
                        "error_code":  error_code,
                        "error_detail": (error_detail or "")[:300],
                        "email_type":  entry.get("email_type", ""),
                        "subject":     (entry.get("subject") or "")[:120],
                        "to":          entry.get("to", ""),
                    },
                )
            except Exception:
                pass  # Non-fatal; don't mask the guard result
            return


def _validate_attachment_integrity(
    entry: Dict[str, Any],
    attach_paths: List[Path],
) -> Tuple[bool, str, str]:
    """
    Full attachment integrity check — called after _attachments_for_queue has
    confirmed declared paths exist on disk.

    Checks (in order):
      1. Zero-byte file guard — any 0-size attachment is invalid.
      2. Email-type requirement — customs/agency emails require ≥ 1 attachment.
      3. Body-keyword guard — body references attachments but list is empty.
      4. MIME packaging dry-run — catch encoding/IO failures before SMTP.

    Returns (ok, error_code, error_detail).
    ok=True means the email is safe to send.
    """
    email_type   = (entry.get("email_type") or "").strip().lower()
    body_text    = (entry.get("body_text") or "").lower()
    body_html    = (entry.get("body_html") or "").lower()
    combined_body = body_text + " " + body_html

    # ── Check 1: zero-byte files ──────────────────────────────────────────
    for p in attach_paths:
        try:
            if p.stat().st_size == 0:
                detail = (
                    "Outbound customs email blocked: required attachments missing or invalid. "
                    f"Attachment '{p.name}' is empty (0 bytes) — file was not generated correctly."
                )
                return False, "attachment_zero_bytes", detail
        except OSError as exc:
            detail = (
                "Outbound customs email blocked: required attachments missing or invalid. "
                f"Cannot stat attachment '{p.name}': {exc}"
            )
            return False, "attachment_stat_error", detail

    # ── Check 2: email type unconditionally requires ≥ 1 attachment ──────
    if email_type in _ATTACHMENT_REQUIRED_EMAIL_TYPES and len(attach_paths) == 0:
        detail = (
            "Outbound customs email blocked: required attachments missing or invalid. "
            f"Email type '{email_type}' requires at least 1 attachment "
            "but the resolver returned an empty list."
        )
        return False, "attachment_required_for_type", detail

    # ── Check 3: body keyword → attachment count mismatch ─────────────────
    if len(attach_paths) == 0:
        body_signals_attachment = any(kw in combined_body for kw in _ATTACHMENT_BODY_KEYWORDS)
        if body_signals_attachment:
            detail = (
                "Outbound customs email blocked: required attachments missing or invalid. "
                "Email body references attachments (attachment keyword found) "
                "but no attachment files were resolved."
            )
            return False, "body_references_missing_attachments", detail

    # ── Check 4: MIME packaging dry-run ───────────────────────────────────
    if attach_paths:
        try:
            to_list = _dedupe_addresses(_split_recipients(entry.get("to", "")))
            raw_cc  = _dedupe_addresses(_split_recipients(entry.get("cc", "")))
            to_norm = {a.lower() for a in to_list}
            cc_list = [a for a in raw_cc if a.lower() not in to_norm]
            _build_mime(
                sender      = entry.get("from_address", "test@localhost"),
                to_list     = to_list or ["test@localhost"],
                cc_list     = cc_list,
                subject     = entry.get("subject", ""),
                body_text   = entry.get("body_text", ""),
                body_html   = entry.get("body_html", ""),
                attachments = attach_paths,
            )
        except Exception as exc:
            filenames = [p.name for p in attach_paths]
            detail = (
                "Outbound customs email blocked: required attachments missing or invalid. "
                f"MIME packaging failed for {filenames}: {exc}"
            )
            return False, "mime_packaging_failed", detail

    return True, "", ""


def _smtp_configured() -> bool:
    return bool(settings.smtp_user and settings.smtp_password and settings.smtp_host)


def _assert_production_env_for_smtp() -> None:
    """Lesson E Property 5 — environment isolation guard.

    Raises RuntimeError if SMTP credentials are set but environment is NOT prod.
    A dev/local process with credentials must never connect to the live SMTP server.
    Call this once before any SMTP connect attempt.
    """
    if _smtp_configured() and settings.environment != "prod":
        raise RuntimeError(
            f"email_sender: SMTP credentials are configured but environment="
            f"{settings.environment!r} (expected 'prod'). "
            "Set ENVIRONMENT=prod in .env to enable real outbound email, "
            "or unset SMTP_USER/SMTP_PASSWORD/SMTP_HOST in dev."
        )


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

    # ── Already-suppressed terminal states: don't re-attempt ─────────────
    # If a prior call already flipped this entry to a delivered-suppress
    # or stale-expire terminal status, return the suppression result
    # verbatim so retry replays observe the same outcome.
    if entry.get("status") in ("suppressed_delivered", "expired_stale_queue"):
        return {
            "ok":                  False,
            "queue_id":            queue_id,
            "status":              entry.get("status"),
            "guard":               entry.get("status"),
            "guard_reason":        entry.get("suppression_reason") or "",
            "suppressed_at":       entry.get("suppressed_at"),
            "error":               entry.get("status"),
            "error_detail":        entry.get("suppression_detail") or "",
            "already_suppressed":  True,
        }

    # ── Hard guard: shipment delivered → suppress send ──────────────────
    # Re-checks the shipment's live audit state at EXECUTION TIME, not
    # only at enqueue time. Required by the operator rule:
    #   "If shipment status is delivered, the shipment is closed.
    #    Don't follow up."
    # The guard flips the queue entry to a terminal `suppressed_delivered`
    # status so any subsequent retry replay also skips it without trying
    # to send again. Re-opening a delivered shipment requires explicit
    # operator action outside this guard.
    try:
        from .shipment_delivered_guard import (
            check_send_allowed as _ssa_check_send_allowed,
            is_queue_entry_stale as _ssa_is_stale,
            STALE_QUEUE_DAYS    as _ssa_stale_days,
        )
        _bid = str(entry.get("batch_id") or "").strip()
        _g   = _ssa_check_send_allowed(_bid)
        if not _g["allowed"]:
            _mark_queue_terminal(
                queue_id,
                terminal_status="suppressed_delivered",
                reason=_g["reason"],
                detail=(
                    f"shipment for batch_id={_bid!r} is delivered; "
                    "follow-up email suppressed per operator policy."
                ),
            )
            return {
                "ok":            False,
                "queue_id":      queue_id,
                "status":        "suppressed_delivered",
                "guard":         "shipment_delivered",
                "guard_reason":  _g["reason"],
                "audit_found":   _g["audit_found"],
                "batch_id":      _bid,
                "error":         "shipment_delivered",
                "error_detail":  (
                    "Shipment is delivered — follow-up email "
                    "suppressed. Re-open the shipment to send."
                ),
            }
        # ── Stale-queue expiry ─────────────────────────────────────
        # An entry older than STALE_QUEUE_DAYS that has never sent
        # is almost certainly stale.  Refuse with a terminal
        # `expired_stale_queue` status so replays don't fire it.
        if _ssa_is_stale(entry):
            _mark_queue_terminal(
                queue_id,
                terminal_status="expired_stale_queue",
                reason="stale_queue_entry",
                detail=(
                    f"queued_at={entry.get('queued_at')!r} is older than "
                    f"{_ssa_stale_days} days; entry expired."
                ),
            )
            return {
                "ok":           False,
                "queue_id":     queue_id,
                "status":       "expired_stale_queue",
                "guard":        "stale_queue",
                "guard_reason": "stale_queue_entry",
                "queued_at":    entry.get("queued_at"),
                "max_age_days": _ssa_stale_days,
                "error":        "stale_queue_entry",
                "error_detail": (
                    f"Queue entry older than {_ssa_stale_days} days. "
                    "Manually re-queue if a fresh send is needed."
                ),
            }
    except Exception as _guard_exc:
        # Guards are non-fatal: log and continue.  A guard failure must
        # NOT block legitimate sends.  Operator can observe the warn.
        try:
            from ..core.logging import get_logger as _get_logger
            _get_logger(__name__).warning(
                "send_queued_email: delivered/stale guard failed (non-fatal) "
                "for queue_id=%r: %s", queue_id, _guard_exc,
            )
        except Exception:
            pass

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

    # ── SMTP creds check + Lesson E Property 5 environment isolation ─────
    _assert_production_env_for_smtp()
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
        # Persist failure marker on the queue entry so a retry doesn't
        # silently send body-only.
        _mark_queue_error(queue_id, "attachments_missing",
                          f"Files not found on disk: {missing}")
        return {
            "ok":       False,
            "queue_id": queue_id,
            "status":   entry.get("status", "pending"),
            "error":    "attachments_missing",
            "error_detail": f"Files not found on disk: {missing}",
        }

    # Silent-send guard: if upstream declared attachments but the resolver
    # returned zero (e.g. proposal-draft attachments not visible to the
    # resolver), abort. Body-only delivery for an attachment-bearing email
    # is the bug this gate prevents.
    expected_count = _expected_attachment_count(entry)
    if expected_count > 0 and len(attach_paths) == 0:
        reason = (
            f"resolver returned 0 attachments but batch declares "
            f"{expected_count} — refusing to send body-only."
        )
        _mark_queue_error(queue_id, "attachments_unresolved", reason)
        log.warning("[email_sender] %s queue=%s", reason, queue_id)
        return {
            "ok":           False,
            "queue_id":     queue_id,
            "status":       entry.get("status", "pending"),
            "error":        "attachments_unresolved",
            "error_detail": reason,
        }

    # ── Full attachment integrity validation ──────────────────────────────
    # Covers: zero-byte files, email-type attachment requirement,
    # body-keyword vs attachment-count mismatch, MIME packaging dry-run.
    # Sets terminal status FAILED_ATTACHMENT_VALIDATION and logs to audit
    # on failure — no retry until operator fixes the underlying issue.
    att_ok, att_error, att_detail = _validate_attachment_integrity(entry, attach_paths)
    if not att_ok:
        _set_terminal_failure(queue_id, att_error, att_detail)
        _log_attachment_failure_to_audit(queue_id, entry, att_error, att_detail)
        log.error(
            "[email_sender] attachment integrity blocked send: queue=%s error=%s detail=%s",
            queue_id, att_error, (att_detail or "")[:200],
        )
        return {
            "ok":       False,
            "queue_id": queue_id,
            "status":   _STATUS_ATTACHMENT_VALIDATION_FAILED,
            "error":    att_error,
            "error_detail": att_detail,
        }

    # SMTP authenticates as smtp_user (amit@), but FROM may be an alias
    # configured on the same Zoho mailbox (import@, info@, account@).
    # Zoho permits this when the alias is in sendMailDetails for the account.
    auth_user   = settings.smtp_user or ""
    sender_addr = (entry.get("from_address") or "").strip() or auth_user

    # ── Build MIME ────────────────────────────────────────────────────────
    try:
        msg = _build_mime(
            sender=sender_addr,
            to_list=to_list,
            cc_list=cc_list,
            subject=entry.get("subject", ""),
            body_text=entry.get("body_text", ""),
            body_html=entry.get("body_html", ""),
            attachments=attach_paths,
        )
    except Exception as exc:
        log.error("[email_sender] MIME build failed queue=%s: %s", queue_id, exc)
        _mark_queue_error(queue_id, "mime_build_failed", str(exc)[:300])
        return {
            "ok":           False,
            "queue_id":     queue_id,
            "status":       entry.get("status", "pending"),
            "error":        "mime_build_failed",
            "error_detail": f"MIME assembly failed: {exc}",
        }

    # ── Connect + send ────────────────────────────────────────────────────
    all_recipients = to_list + cc_list
    log.info(
        "[email_sender] sending queue=%s subject=%r to=%d cc=%d attach=%d host=%s files=%s",
        queue_id, entry.get("subject", ""), len(to_list), len(cc_list),
        len(attach_paths), settings.smtp_host,
        [p.name for p in attach_paths],
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
