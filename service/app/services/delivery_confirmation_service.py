"""
Customer delivery-confirmation service.

Business flow (all customer-facing, zero fiscal side effects):
  1. An OUTBOUND shipment is delivered by DHL. The outbound-delivery hook calls
     :func:`maybe_notify_outbound_delivered`, which — behind a default-OFF
     feature flag and a strict activation boundary — queues ONE customer email
     containing an opaque "confirm receipt" link.
  2. The customer opens ``/receipt/{token}``, confirms good receipt or reports
     damage (with optional photos). :func:`submit_receipt` records the response.

Security / authority invariants (Lesson E, Lesson N):
  * Tokens are ``secrets.token_urlsafe(32)`` — opaque and unguessable. Only the
    SHA-256 hash is stored; no draft_id / db id is ever encoded in the token.
  * This module NEVER mutates accounting / invoice / stock / product / DHL
    state. It writes only to ``delivery_confirmations.db`` and the evidence
    store. Verified structurally by the test suite.
  * Idempotent per outbound AWB (``UNIQUE(awb)`` in delivery_confirmation_db).
  * Historical delivered shipments are NEVER mass-notified: the activation
    boundary requires the booking to have been created at/after the operator's
    activation timestamp.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import delivery_confirmation_db as dcdb

log = logging.getLogger(__name__)

# ── Public token / link ─────────────────────────────────────────────────────────

RECEIPT_TOKEN_TTL_DAYS = 30

# Allowed evidence MIME types + their canonical file extensions.
_ALLOWED_IMAGE_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_MAX_EVIDENCE_BYTES = 5 * 1024 * 1024   # 5 MB per file
_MAX_EVIDENCE_COUNT = 8

_ISSUE_CATEGORIES = {
    "package_box_damaged",
    "packing_damaged",
    "goods_damaged",
    "item_missing",
    "theft_tampering",
    "other",
}

_SAFE_AWB = re.compile(r"[^A-Za-z0-9_-]")


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%fZ")


def _storage_root() -> Path:
    from ..core.config import settings
    return Path(settings.storage_root)


def _db_path() -> Path:
    return _storage_root() / "delivery_confirmations.db"


def _evidence_root() -> Path:
    return _storage_root() / "delivery_evidence"


def _public_base() -> str:
    from ..core.config import settings
    base = (settings.public_base_url or "").strip() or (settings.fastapi_public_url or "").strip()
    return base.rstrip("/")


def _hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def build_receipt_link(token: str) -> str:
    """Absolute customer link for a receipt token."""
    return f"{_public_base()}/receipt/{token}"


def _safe_awb_dir_name(awb: str) -> str:
    return _SAFE_AWB.sub("_", (awb or "").strip()) or "unknown"


# ── Customer email resolution ────────────────────────────────────────────────────


def resolve_customer_email(draft: Any, storage_root: Path) -> str:
    """Resolve the customer email for a proforma draft, or "".

    Mirrors the authority chain used by ``routes_proforma._resolve_proforma_recipient``:
      draft.client_contractor_id → Customer Master → pick_email (bill_to first).
    Best-effort and never raises.
    """
    if draft is None:
        return ""
    try:
        cid = (getattr(draft, "client_contractor_id", "") or "").strip()
        if not cid:
            return ""
        from .customer_master_db import get_customer as _get_cm
        from .customer_master import pick_email as _pick_email
        cm_path = Path(storage_root) / "customer_master.sqlite"
        if not cm_path.exists():
            return ""
        cm = _get_cm(cm_path, int(cid))
        if cm is None:
            return ""
        return _pick_email(cm) or ""
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("resolve_customer_email failed: %s", exc)
        return ""


# ── Outbound delivered → notify ──────────────────────────────────────────────────


def _activation_ok(
    carrier_delivered_at: Optional[str],
    booking_created_at: Optional[str],
) -> bool:
    """Strict activation boundary — protects against mass-notifying history.

    Prefer carrier delivery time when present; fall back to booking created_at
    only when the delivery timestamp is missing. Requires a non-empty
    ``customer_delivery_confirmation_activated_at``. Empty activation or an
    unknown comparison timestamp → False (never mass-notify history).
    """
    from ..core.config import settings
    activated_at = (settings.customer_delivery_confirmation_activated_at or "").strip()
    if not activated_at:
        return False
    pivot = (carrier_delivered_at or "").strip() or (booking_created_at or "").strip()
    if not pivot:
        return False
    return pivot >= activated_at


def maybe_notify_outbound_delivered(
    awb: str,
    *,
    draft_id: Optional[int] = None,
    batch_id: Optional[str] = None,
    client_name: Optional[str] = None,
    delivered: bool = False,
    carrier_delivered_at: Optional[str] = None,
    booking_created_at: Optional[str] = None,
    customer_email: Optional[str] = None,
    customer_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Queue (at most one) customer delivery-confirmation email for an AWB.

    All gates below must pass; any failed gate returns a ``{"notified": False,
    "reason": ...}`` dict and never raises. The caller (the outbound-delivery
    hook) has already established the delivered signal for THIS outbound AWB via
    ``tracking_service`` — pass ``delivered=True`` / ``carrier_delivered_at`` so
    this function does not re-query tracking (which would recurse when invoked
    from inside ``get_tracking_status``).

    Idempotency: the notification row's ``UNIQUE(awb)`` means a repeated
    delivered event never queues a second email.
    """
    from ..core.config import settings

    awb = (awb or "").strip()
    if not awb:
        return {"notified": False, "reason": "no_awb"}

    if not settings.customer_delivery_confirmation_enabled:
        return {"notified": False, "reason": "feature_disabled"}

    if not delivered and not carrier_delivered_at:
        return {"notified": False, "reason": "not_delivered"}

    activation_cutoff_ok = _activation_ok(carrier_delivered_at, booking_created_at)
    if not activation_cutoff_ok:
        # Record intent is not created — never mass-notify historical deliveries.
        return {"notified": False, "reason": "activation_boundary", "awb": awb}

    storage_root = _storage_root()
    db = _db_path()

    # Resolve customer email if the caller did not supply it.
    email_to = (customer_email or "").strip()
    draft = None
    if not email_to and draft_id is not None:
        try:
            from . import proforma_invoice_link_db as pildb
            draft = pildb.get_draft_by_id(storage_root / "proforma_links.db", int(draft_id))
        except Exception:
            draft = None
        if draft is not None:
            email_to = resolve_customer_email(draft, storage_root)
            if not customer_name:
                customer_name = getattr(draft, "client_name", None)
    if not email_to:
        return {"notified": False, "reason": "no_customer_email", "awb": awb}

    # Idempotency anchor — first delivered event for this AWB inserts the row.
    # Failed status is sticky: do NOT auto-retry from tracking refresh / webhook
    # loops (that would mint a new token and re-spam the customer). Operator
    # resend can call reset_failed_notification_for_retry explicitly later.
    row, created = dcdb.create_notification_if_absent(
        db,
        awb=awb,
        draft_id=draft_id,
        batch_id=batch_id,
        client_name=client_name or customer_name,
        email_to=email_to,
        activation_cutoff_ok=activation_cutoff_ok,
    )
    if not created:
        status = (row or {}).get("status") or ""
        if status == "failed":
            return {"notified": False, "reason": "notification_failed", "awb": awb}
        return {"notified": False, "reason": "already_notified", "awb": awb}

    # Mint the opaque public token + persist its hash.
    token = secrets.token_urlsafe(32)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=RECEIPT_TOKEN_TTL_DAYS)
    ).strftime("%Y-%m-%dT%H:%M:%fZ")
    dcdb.create_receipt_token_row(
        db,
        token_hash=_hash_token(token),
        awb=awb,
        draft_id=draft_id,
        batch_id=batch_id,
        client_name=client_name or customer_name,
        customer_name=customer_name,
        expires_at=expires_at,
        carrier_delivered_at=carrier_delivered_at,
    )

    link = build_receipt_link(token)
    subject = "Your Estrella shipment has been delivered — confirm condition"
    html_body, text_body = _delivery_email_bodies(
        customer_name, awb, link, carrier_delivered_at=carrier_delivered_at,
    )

    email_id = ""
    try:
        from . import email_service
        email_id = email_service.queue_email(
            to=email_to,
            subject=subject,
            body_html=html_body,
            body_text=text_body,
            batch_id=batch_id or "",
            email_type="customer_delivery_confirmation",
        )
        dcdb.mark_notification_queued(
            db, awb, email_id=email_id, email_to=email_to, queued_at=_now_utc_iso(),
        )
    except Exception as exc:
        log.warning("delivery confirmation email queue failed for awb=%s: %s", awb, exc)
        dcdb.mark_notification_failed(db, awb, reason=str(exc))
        return {"notified": False, "reason": "email_queue_failed", "awb": awb}

    return {
        "notified": True,
        "awb": awb,
        "email_id": email_id,
        "email_to": email_to,
        "receipt_link": link,
    }


def _delivery_email_bodies(
    customer_name: Optional[str],
    awb: str,
    link: str,
    *,
    carrier_delivered_at: Optional[str] = None,
) -> tuple[str, str]:
    """Transactional Estrella delivery-confirmation email (HTML + plain text).

    Table-based, email-client-safe HTML — no JS. Distinct from DHL carrier
    notifications. CTA opens the secure /receipt/&#123;token&#125; page only.
    """
    from html import escape
    who = escape(customer_name or "Customer")
    awb_e = escape(awb)
    link_e = escape(link)
    when_raw = (carrier_delivered_at or "").strip()
    when_disp = ""
    if when_raw:
        try:
            when_disp = datetime.fromisoformat(
                when_raw.replace("Z", "+00:00")
            ).strftime("%d %b %Y %H:%M UTC")
        except Exception:
            when_disp = when_raw[:32]
    when = escape(when_disp)
    when_row = (
        f'<tr><td style="padding:4px 0;color:#6b655c;font-size:13px;">Delivered</td>'
        f'<td style="padding:4px 0;font-size:13px;font-weight:600;color:#1c1a17;">{when}</td></tr>'
        if when else ""
    )
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Delivery confirmation</title></head>
<body style="margin:0;padding:0;background:#f5f3ef;color:#1c1a17;
 font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f5f3ef;padding:24px 12px;">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;
 border:1px solid #e3ded5;border-radius:14px;">
<tr><td style="padding:28px 28px 8px;text-align:center;">
  <div style="font-size:12px;letter-spacing:3px;text-transform:uppercase;color:#6b655c;font-weight:600;">Estrella Jewels</div>
  <h1 style="margin:14px 0 0;font-size:22px;line-height:1.3;color:#1c1a17;font-weight:700;">
    Your Estrella shipment has been delivered
  </h1>
</td></tr>
<tr><td style="padding:8px 28px 0;font-size:15px;line-height:1.55;color:#1c1a17;">
  <p style="margin:0 0 14px;">Dear {who},</p>
  <p style="margin:0 0 18px;">DHL has marked your shipment as delivered. Please confirm everything arrived correctly,
  or report damage / missing items and attach photographs if needed.</p>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
   style="background:#f5f3ef;border-radius:10px;padding:12px 14px;margin:0 0 22px;">
    <tr><td style="padding:4px 0;color:#6b655c;font-size:13px;">Customer</td>
        <td style="padding:4px 0;font-size:13px;font-weight:600;">{who}</td></tr>
    <tr><td style="padding:4px 0;color:#6b655c;font-size:13px;">Carrier</td>
        <td style="padding:4px 0;font-size:13px;font-weight:600;">DHL</td></tr>
    <tr><td style="padding:4px 0;color:#6b655c;font-size:13px;">AWB</td>
        <td style="padding:4px 0;font-size:13px;font-weight:700;font-family:ui-monospace,monospace;">{awb_e}</td></tr>
    {when_row}
  </table>
  <table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 auto 18px;">
    <tr><td align="center" bgcolor="#8a6d3b" style="border-radius:12px;">
      <a href="{link_e}" style="display:inline-block;padding:14px 28px;font-size:16px;font-weight:700;
       color:#ffffff;text-decoration:none;border-radius:12px;">Confirm delivery condition</a>
    </td></tr>
  </table>
  <p style="margin:0 0 8px;font-size:13px;color:#6b655c;line-height:1.5;">
    You can confirm receipt in good condition, or report damaged packaging, damaged goods,
    missing items, suspected loss/theft, or another problem — and attach photos when reporting an issue.
  </p>
  <p style="margin:16px 0 0;font-size:12px;color:#6b655c;word-break:break-all;">
    If the button does not work, open this secure link:<br/>
    <a href="{link_e}" style="color:#8a6d3b;">{link_e}</a>
  </p>
</td></tr>
<tr><td style="padding:22px 28px 28px;font-size:13px;color:#6b655c;">
  Thank you,<br/><strong style="color:#1c1a17;">Estrella Jewels</strong>
</td></tr>
</table>
</td></tr></table>
</body></html>"""
    text = (
        f"Your Estrella shipment has been delivered\n\n"
        f"Dear {customer_name or 'Customer'},\n\n"
        f"DHL has marked your shipment as delivered.\n"
        f"Customer: {customer_name or 'Customer'}\n"
        f"Carrier: DHL\n"
        f"AWB: {awb}\n"
        + (f"Delivered: {carrier_delivered_at}\n" if carrier_delivered_at else "")
        + "\nConfirm delivery condition (or report damage / missing items):\n"
        f"{link}\n\n"
        "You can confirm good condition, or report damaged packaging, damaged goods,\n"
        "missing items, suspected loss/theft, or another problem, and attach photos.\n\n"
        "Thank you,\nEstrella Jewels\n"
    )
    return html, text


# ── Public receipt submission ────────────────────────────────────────────────────


class ReceiptError(Exception):
    """Raised for public-receipt validation failures. ``status`` maps to HTTP."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def get_public_receipt_metadata(token: str) -> Dict[str, Any]:
    """Read-only metadata for rendering the public page. Never leaks db ids."""
    row = dcdb.get_receipt_by_token_hash(_db_path(), _hash_token(token))
    if row is None:
        raise ReceiptError(404, "unknown_token", "This link is not valid.")
    now = _now_utc_iso()
    expired = bool(row.get("expires_at") and now > row["expires_at"])
    return {
        "customer_name": row.get("customer_name") or "Customer",
        "awb_masked": _mask_awb(row.get("awb")),
        "expires_at": row.get("expires_at"),
        "expired": expired,
        "used": bool(row.get("used_at")),
    }


def _mask_awb(awb: Optional[str]) -> str:
    a = (awb or "").strip()
    if len(a) <= 4:
        return a or ""
    return f"••••{a[-4:]}"


def _sniff_image(content: bytes) -> Optional[str]:
    """Return the detected image MIME by magic bytes, or None. Guards against a
    non-image (e.g. an executable) uploaded under an image content-type."""
    if content[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if content[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _validate_evidence_file(
    original_name: str, content_type: str, content: bytes,
) -> str:
    """Validate one uploaded evidence file. Returns the canonical extension.

    Rejects: disallowed MIME, oversized, empty, and content whose real magic
    bytes are not an allowed image (executables, archives, etc.).
    """
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared not in _ALLOWED_IMAGE_MIME:
        raise ReceiptError(
            422, "bad_file_type",
            f"Unsupported file type {declared or 'unknown'!r}. "
            "Only JPEG, PNG, WEBP or GIF images are allowed.",
        )
    if not content:
        raise ReceiptError(422, "empty_file", "Uploaded file is empty.")
    if len(content) > _MAX_EVIDENCE_BYTES:
        raise ReceiptError(
            413, "file_too_large",
            "Each photo must be 5 MB or smaller.",
        )
    sniffed = _sniff_image(content)
    if sniffed is None:
        raise ReceiptError(
            422, "not_an_image",
            "The uploaded file is not a valid image.",
        )
    return _ALLOWED_IMAGE_MIME[sniffed]


def submit_receipt(
    token: str,
    *,
    condition: str,
    categories: Optional[List[str]] = None,
    comments: str = "",
    files: Optional[List[Dict[str, Any]]] = None,
    response_ip: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a customer's receipt response. Public — no dashboard auth.

    ``files`` items are dicts: ``{"filename", "content_type", "content": bytes}``.

    Raises :class:`ReceiptError` (with an HTTP ``status``) on any validation
    failure: 404 unknown token, 409 replay (already used), 410 expired, 422
    invalid condition / category / file, 413 oversized file.
    """
    db = _db_path()
    token_hash = _hash_token(token)
    row = dcdb.get_receipt_by_token_hash(db, token_hash)
    if row is None:
        raise ReceiptError(404, "unknown_token", "This link is not valid.")

    now = _now_utc_iso()
    if row.get("used_at"):
        raise ReceiptError(409, "already_used", "This confirmation was already submitted.")
    if row.get("expires_at") and now > row["expires_at"]:
        raise ReceiptError(410, "expired", "This confirmation link has expired.")

    condition = (condition or "").strip().lower()
    if condition not in ("good", "issue"):
        raise ReceiptError(422, "bad_condition", "condition must be 'good' or 'issue'.")

    cats = [c.strip() for c in (categories or []) if (c or "").strip()]
    for c in cats:
        if c not in _ISSUE_CATEGORIES:
            raise ReceiptError(422, "bad_category", f"Unknown issue category {c!r}.")
    if condition == "good":
        cats = []  # a clean receipt carries no issue categories

    files = files or []
    if len(files) > _MAX_EVIDENCE_COUNT:
        raise ReceiptError(
            422, "too_many_files",
            f"At most {_MAX_EVIDENCE_COUNT} photos may be uploaded.",
        )

    # Validate every file BEFORE marking the receipt used, so a rejected file
    # does not consume the single-use token.
    validated: List[tuple] = []
    for f in files:
        ext = _validate_evidence_file(
            f.get("filename") or "", f.get("content_type") or "", f.get("content") or b"",
        )
        validated.append((f, ext))

    # Atomically claim the token (guards replay under concurrency).
    audit = {
        "response_ip": response_ip,
        "submitted_at": now,
        "file_count": len(validated),
    }
    try:
        updated = dcdb.mark_receipt_used(
            db,
            token_hash=token_hash,
            condition=condition,
            issue_categories=cats,
            comments=(comments or "").strip()[:4000],
            used_at=now,
            response_ip=response_ip,
            audit=audit,
        )
    except KeyError:
        raise ReceiptError(404, "unknown_token", "This link is not valid.")
    except ValueError as exc:
        msg = str(exc).lower()
        if "expired" in msg:
            raise ReceiptError(410, "expired", "This confirmation link has expired.")
        raise ReceiptError(409, "already_used", "This confirmation was already submitted.")

    # Persist evidence to disk under an AWB-scoped folder with random names.
    saved = 0
    if validated:
        awb_dir = (_evidence_root() / _safe_awb_dir_name(updated.get("awb"))).resolve()
        awb_dir.mkdir(parents=True, exist_ok=True)
        for f, ext in validated:
            stored_name = f"{uuid.uuid4().hex}{ext}"
            target = (awb_dir / stored_name).resolve()
            # Path-traversal defence: the random name cannot escape, but confirm.
            if target.parent != awb_dir:
                continue
            content = f.get("content") or b""
            target.write_bytes(content)
            dcdb.add_evidence(
                db,
                receipt_id=updated["id"],
                stored_name=stored_name,
                original_name=(f.get("filename") or "")[:255] or None,
                mime=(f.get("content_type") or "").split(";")[0].strip().lower() or None,
                size_bytes=len(content),
            )
            saved += 1

    return {
        "ok": True,
        "condition": condition,
        "issue_categories": cats,
        "evidence_saved": saved,
    }


def evidence_file_path(receipt_id: int, stored_name: str) -> Optional[Path]:
    """Resolve an evidence file on disk (operator stream). Path-confined."""
    receipt = dcdb.get_receipt_by_id(_db_path(), receipt_id)
    if receipt is None:
        return None
    awb_dir = (_evidence_root() / _safe_awb_dir_name(receipt.get("awb"))).resolve()
    candidate = (awb_dir / stored_name).resolve()
    if candidate.parent != awb_dir or not candidate.is_file():
        return None
    return candidate
