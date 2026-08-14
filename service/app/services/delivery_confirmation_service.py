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
    origin_batch_id: Optional[str] = None,
    client_name: Optional[str] = None,
    delivered: bool = False,
    carrier_delivered_at: Optional[str] = None,
    delivery_location: Optional[str] = None,
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

    Identity: outbound ``awb`` + ``client_name`` own customer communication.
    ``origin_batch_id`` (or legacy ``batch_id`` when only that is passed) is
    import/sales provenance — never the email-queue / customs-audit namespace.
    ``queue_email`` always uses ``batch_id=""`` for this email type.

    ``delivery_location`` is read-only presentation metadata (the carrier's own
    normalised city + country for the delivered event). It gates nothing, is
    never persisted, and is omitted from the email when absent.
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

    # Provenance only — never operative customer-email batch authority.
    origin = (origin_batch_id or batch_id or "").strip() or None

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
        batch_id=None,  # operative communication key is awb, not import batch
        origin_batch_id=origin,
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
        batch_id=None,
        origin_batch_id=origin,
        client_name=client_name or customer_name,
        customer_name=customer_name,
        expires_at=expires_at,
        carrier_delivered_at=carrier_delivered_at,
    )

    link = build_receipt_link(token)
    subject = "Your Estrella shipment has been delivered — confirm condition"
    html_body, text_body = _delivery_email_bodies(
        customer_name,
        awb,
        link,
        carrier_delivered_at=carrier_delivered_at,
        delivery_location=delivery_location,
    )

    from ..config.email_routing import resolve_customer_delivery_confirmation_cc
    email_cc = resolve_customer_delivery_confirmation_cc(email_to)
    if not email_cc:
        log.warning(
            "delivery confirmation CC empty (CUSTOMER_DELIVERY_CONFIRMATION_CC) "
            "for awb=%s — sending To=%s without internal CC",
            awb, email_to,
        )

    email_id = ""
    try:
        from . import email_service
        email_id = email_service.queue_email(
            to=email_to,
            cc=email_cc,
            subject=subject,
            body_html=html_body,
            body_text=text_body,
            # Empty: never bind customer MIME to import/customs audit namespace.
            batch_id="",
            email_type="customer_delivery_confirmation",
            # Explicit list only: CMR when canonical export exists, else [].
            # Never omit attachments (None → audit/customs/DHL package fallback).
            attachments=_cmr_attachment_for_draft(draft_id),
        )
        dcdb.mark_notification_queued(
            db,
            awb,
            email_id=email_id,
            email_to=email_to,
            email_cc=email_cc,
            queued_at=_now_utc_iso(),
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
        "email_cc": email_cc,
        "receipt_link": link,
        "origin_batch_id": origin,
    }


def _cmr_attachment_for_draft(draft_id: Optional[int]) -> list:
    """Explicit CMR attachment list for customer_delivery_confirmation.

    Fail closed: returns [] when CMR unavailable. Never omits the attachments
    argument (None would allow audit-package fallback).
    """
    if draft_id is None:
        return []
    try:
        from . import commercial_cmr as ccmr
        from ..core.config import settings
        exported = ccmr.export_cmr_pdf_for_draft(
            draft_id=int(draft_id),
            storage_root=Path(settings.storage_root),
            proforma_db=Path(settings.storage_root) / "proforma_links.db",
            carrier_db=(
                Path(settings.carrier_storage_root or (Path(settings.storage_root) / "carrier"))
                / "carrier_shipments.db"
            ),
        )
    except Exception as exc:
        log.warning("CMR export for confirmation failed draft=%s: %s", draft_id, exc)
        return []
    if not exported:
        return []
    pdf_bytes, filename = exported
    out_dir = _storage_root() / "delivery_confirmation_pdfs"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in filename)
    path = out_dir / f"{int(draft_id)}_{safe}"
    path.write_bytes(pdf_bytes)
    return [{"label": safe, "path": str(path)}]


def retry_failed_confirmation_for_draft(draft_id: int) -> Dict[str, Any]:
    """Operator manual confirmation send for a *failed* notification only.

    Clears the failed row via ``reset_failed_notification_for_retry``, then
    re-enters :func:`maybe_notify_outbound_delivered` with ``delivered=True``.
    Does not invent delivery — requires an existing failed notification row.
    """
    db = _db_path()
    notification = dcdb.get_notification_for_draft(db, int(draft_id))
    if notification is None:
        return {"notified": False, "reason": "no_notification"}
    if (notification.get("status") or "") != "failed":
        return {
            "notified": False,
            "reason": "not_failed",
            "status": notification.get("status"),
        }
    awb = (notification.get("awb") or "").strip()
    if not awb:
        return {"notified": False, "reason": "no_awb"}
    if not dcdb.reset_failed_notification_for_retry(db, awb):
        return {"notified": False, "reason": "reset_failed"}
    return maybe_notify_outbound_delivered(
        awb,
        draft_id=int(draft_id),
        origin_batch_id=notification.get("origin_batch_id"),
        client_name=notification.get("client_name"),
        delivered=True,
        customer_email=notification.get("email_to"),
        customer_name=notification.get("client_name"),
    )


def _prove_outbound_delivered(awb: str) -> Dict[str, Any]:
    """Read-only proof that an outbound AWB is delivered. Never invents delivery.

    Uses carrier booking recognition + tracking terminal cache (no live refresh)
    so this path cannot recurse into the outbound delivery hook.
    """
    awb = (awb or "").strip()
    if not awb:
        return {"ok": False, "reason": "no_awb"}
    try:
        from ..core.config import settings
        from .carrier.persistence import shipment_db
        carrier_root = Path(
            settings.carrier_storage_root or (Path(settings.storage_root) / "carrier")
        )
        carrier_db = carrier_root / "carrier_shipments.db"
        row = shipment_db.get_shipment_by_tracking_ref(carrier_db, awb)
        if row is None:
            return {"ok": False, "reason": "awb_not_recognised"}
        batch_id = (row.get("batch_id") or "").strip()
        cache_dir = Path(settings.storage_root) / "outputs" / batch_id if batch_id else None
        if cache_dir is None or not cache_dir.is_dir():
            # Fall back to carrier storage batch folder if present.
            alt = carrier_root / "shipments" / batch_id if batch_id else None
            cache_dir = alt if alt and alt.is_dir() else Path(settings.storage_root)
        from . import tracking_service as ts
        cached = ts._load_cache(cache_dir)
        hit = ts.select_cached_tracking_record(cached, awb) or {}
        if (hit.get("status") or "").strip().lower() == "delivered":
            return {
                "ok": True,
                "awb": awb,
                "origin_batch_id": batch_id or None,
                "client_name": (row.get("client_ref") or "").strip() or None,
                "carrier_delivered_at": hit.get("last_update"),
                "booking_created_at": row.get("created_at"),
            }
        if ts._delivery_proof_present(cache_dir):
            return {
                "ok": True,
                "awb": awb,
                "origin_batch_id": batch_id or None,
                "client_name": (row.get("client_ref") or "").strip() or None,
                "carrier_delivered_at": hit.get("last_update"),
                "booking_created_at": row.get("created_at"),
            }
        return {"ok": False, "reason": "not_delivered"}
    except Exception as exc:
        log.debug("delivered proof failed awb=%s: %s", awb, exc)
        return {"ok": False, "reason": "proof_error"}


def send_confirmation_for_draft(draft_id: int) -> Dict[str, Any]:
    """Operator Send Confirmation — reuse existing delivery-confirmation authority.

    Paths:
      * failed notification → retry_failed_confirmation_for_draft
      * no notification yet → maybe_notify only when outbound AWB is proven delivered
      * awaiting / confirmed / issue → refuse (reminder or already done)

    Never fabricates delivery. CMR attaches when canonical CMR export is available.
    """
    db = _db_path()
    summary = dcdb.get_delivery_summary_for_draft(db, int(draft_id))
    notification = dcdb.get_notification_for_draft(db, int(draft_id))
    op = (summary or {}).get("operator_status") if summary else None
    if op in ("confirmed_good", "issue_reported"):
        return {"notified": False, "reason": f"already_{op}"}
    if op == "awaiting_customer":
        return {"notified": False, "reason": "awaiting_customer"}
    if notification and (notification.get("status") or "") == "failed":
        return retry_failed_confirmation_for_draft(int(draft_id))

    awb = (
        ((summary or {}).get("awb") if summary else None)
        or ((notification or {}).get("awb") if notification else None)
        or ""
    ).strip()
    if not awb:
        # Resolve AWB from carrier shipment linked to the draft.
        try:
            from ..core.config import settings
            from . import proforma_invoice_link_db as pildb
            from .carrier.persistence import shipment_db
            from .shipment_document_manifest import _batch_client_count

            draft = pildb.get_draft_by_id(
                Path(settings.storage_root) / "proforma_links.db", int(draft_id),
            )
            if draft is not None:
                batch_id = (draft.batch_id or "").strip()
                client_name = (draft.client_name or "").strip() or None
                proforma_db = Path(settings.storage_root) / "proforma_links.db"
                single_client = _batch_client_count(proforma_db, batch_id) <= 1
                row = shipment_db.get_shipment_for_draft(
                    (
                        Path(settings.carrier_storage_root or (Path(settings.storage_root) / "carrier"))
                        / "carrier_shipments.db"
                    ),
                    batch_id,
                    client_name,
                    allow_single_client_fallback=single_client,
                )
                if row:
                    awb = (row.get("tracking_ref") or "").strip()
        except Exception as exc:
            log.debug("confirmation AWB resolve failed: %s", exc)
    if not awb:
        return {"notified": False, "reason": "no_awb"}

    # If already queued/sent successfully, do not re-spam — operator uses reminder.
    if notification and (notification.get("status") or "") in ("queued", "sent"):
        return {
            "notified": False,
            "reason": "already_notified",
            "status": notification.get("status"),
        }

    proof = _prove_outbound_delivered(awb)
    if not proof.get("ok"):
        return {
            "notified": False,
            "reason": proof.get("reason") or "not_delivered",
            "awb": awb,
        }

    return maybe_notify_outbound_delivered(
        awb,
        draft_id=int(draft_id),
        origin_batch_id=proof.get("origin_batch_id"),
        client_name=proof.get("client_name"),
        delivered=True,
        carrier_delivered_at=proof.get("carrier_delivered_at"),
        booking_created_at=proof.get("booking_created_at"),
    )


def send_awaiting_customer_reminder(draft_id: int) -> Dict[str, Any]:
    """Manual reminder while ``operator_status == awaiting_customer``.

    Mints a fresh receipt token (plaintext is never stored) and queues
    ``customer_delivery_reminder``. Does NOT mutate customer reply fields
    (confirmed_good / issue_reported stay untouched; awaiting remains awaiting).
    """
    from ..core.config import settings
    from ..config.email_routing import resolve_customer_delivery_confirmation_cc

    if not settings.customer_delivery_confirmation_enabled:
        return {"reminded": False, "reason": "feature_disabled"}

    db = _db_path()
    summary = dcdb.get_delivery_summary_for_draft(db, int(draft_id))
    if summary is None:
        return {"reminded": False, "reason": "no_delivery_record"}
    if summary.get("operator_status") != "awaiting_customer":
        return {
            "reminded": False,
            "reason": "not_awaiting_customer",
            "operator_status": summary.get("operator_status"),
        }

    notification = dcdb.get_notification_for_draft(db, int(draft_id))
    receipt = dcdb.get_receipt_for_draft(db, int(draft_id))
    awb = (summary.get("awb") or (notification or {}).get("awb") or "").strip()
    if not awb:
        return {"reminded": False, "reason": "no_awb"}

    email_to = ((notification or {}).get("email_to") or "").strip()
    if not email_to:
        try:
            from . import proforma_invoice_link_db as pildb
            draft = pildb.get_draft_by_id(
                _storage_root() / "proforma_links.db", int(draft_id),
            )
        except Exception:
            draft = None
        if draft is not None:
            email_to = resolve_customer_email(draft, _storage_root())
    if not email_to:
        return {"reminded": False, "reason": "no_customer_email", "awb": awb}

    customer_name = (
        summary.get("customer_name")
        or (notification or {}).get("client_name")
        or (receipt or {}).get("customer_name")
    )
    origin = (notification or {}).get("origin_batch_id") or (receipt or {}).get(
        "origin_batch_id"
    )

    token = secrets.token_urlsafe(32)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=RECEIPT_TOKEN_TTL_DAYS)
    ).strftime("%Y-%m-%dT%H:%M:%fZ")
    dcdb.create_receipt_token_row(
        db,
        token_hash=_hash_token(token),
        awb=awb,
        draft_id=int(draft_id),
        batch_id=None,
        origin_batch_id=origin,
        client_name=customer_name,
        customer_name=customer_name,
        expires_at=expires_at,
        carrier_delivered_at=(receipt or {}).get("carrier_delivered_at"),
    )
    link = build_receipt_link(token)
    subject = "Reminder: please confirm your Estrella shipment arrived safely"
    html_body, text_body = _delivery_email_bodies(
        customer_name,
        awb,
        link,
        carrier_delivered_at=(receipt or {}).get("carrier_delivered_at"),
    )
    # Soft reminder preface — same confirmation link semantics.
    preface_html = (
        "<p><strong>Reminder:</strong> we have not yet received your "
        "delivery confirmation. Please use the button below.</p>"
    )
    html_body = preface_html + html_body
    text_body = (
        "Reminder: we have not yet received your delivery confirmation.\n\n"
        + text_body
    )
    email_cc = resolve_customer_delivery_confirmation_cc(email_to)

    try:
        from . import email_service
        email_id = email_service.queue_email(
            to=email_to,
            cc=email_cc,
            subject=subject,
            body_html=html_body,
            body_text=text_body,
            batch_id="",
            email_type="customer_delivery_reminder",
            attachments=[],
        )
    except Exception as exc:
        log.warning("delivery reminder queue failed draft=%s awb=%s: %s", draft_id, awb, exc)
        return {"reminded": False, "reason": "email_queue_failed", "detail": str(exc)}

    # Touch queued_at when a notification row exists — do not change reply state.
    if notification is not None:
        try:
            dcdb.mark_notification_queued(
                db,
                awb,
                email_id=email_id,
                email_to=email_to,
                email_cc=email_cc,
                queued_at=_now_utc_iso(),
            )
        except Exception as exc:
            log.debug("reminder mark_notification_queued: %s", exc)

    # Reply-state invariant: still awaiting_customer after reminder.
    after = dcdb.get_delivery_summary_for_draft(db, int(draft_id))
    return {
        "reminded": True,
        "awb": awb,
        "email_id": email_id,
        "email_to": email_to,
        "operator_status": (after or {}).get("operator_status"),
    }


def _format_delivered_at(carrier_delivered_at: Optional[str]) -> Optional[str]:
    """One display string for the carrier delivery time — HTML and text share it.

    Returns ``None`` when no timestamp was supplied, so both MIME parts omit the
    row together and neither can show the customer something the other does not.
    """
    raw = (carrier_delivered_at or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(
            raw.replace("Z", "+00:00")
        ).strftime("%d %b %Y %H:%M UTC")
    except Exception:
        return raw[:32]


# Only what cannot be inlined: text-size clamping, Outlook table gutters, and an
# additive small-screen block. Every colour / padding / font is inline as well,
# because Gmail drops <style> entirely.
_EMAIL_STYLE = """
    body,table,td,a{-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;}
    table{border-collapse:collapse;mso-table-lspace:0pt;mso-table-rspace:0pt;}
    @media only screen and (max-width:600px){
      .card{width:100% !important;}
      .pad{padding-left:16px !important;padding-right:16px !important;}
      .fact{display:block !important;width:100% !important;
            border-right:0 !important;border-bottom:1px solid #F0E5C8 !important;}
      .fact-last{border-bottom:0 !important;}
      .cta-link{display:block !important;padding-left:16px !important;padding-right:16px !important;}
      .h1{font-size:20px !important;}
    }
"""

# The customer-facing outcomes the secure receipt link can report. Mirrors the
# six issue categories the receipt page offers, plus "good condition".
_REPORTABLE_OUTCOMES = (
    "received in good condition",
    "damaged package or box",
    "damaged packing",
    "damaged goods",
    "missing item(s)",
    "suspected loss or theft",
    "other issue",
)

_SUPPORT_SENTENCE = (
    "Please confirm that your shipment arrived safely. If there is any damage, "
    "missing item or packaging problem, you can report it and attach photographs."
)


def _delivery_email_bodies(
    customer_name: Optional[str],
    awb: str,
    link: str,
    *,
    carrier_delivered_at: Optional[str] = None,
    delivery_location: Optional[str] = None,
) -> tuple[str, str]:
    """Transactional Estrella delivery-confirmation email (HTML + plain text).

    Table-based, email-client-safe HTML — no JS, no webfont, no remote image.
    Estrella house style (emerald / gold / cream / ink); DHL is named only as the
    carrier. The single CTA opens the secure /receipt/&#123;token&#125; page.

    ``delivery_location`` is presentational only: the already-normalised city +
    country code from the carrier's delivered event. Empty / missing → the cell
    is omitted rather than guessed at.
    """
    from html import escape

    who = escape(customer_name or "Customer")
    awb_e = escape(awb)
    link_e = escape(link)
    when_disp = _format_delivered_at(carrier_delivered_at)
    loc_disp = (delivery_location or "").strip() or None

    mono = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Courier New',monospace"
    sans = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

    # (label, value, monospace?) — order is fixed; optional cells simply absent.
    facts: List[tuple] = [
        ("Recipient", who, False),
        ("Carrier", "DHL", False),
        ("Tracking / AWB", awb_e, True),
    ]
    if when_disp:
        facts.append(("Delivered", escape(when_disp), False))
    if loc_disp:
        facts.append(("Location", escape(loc_disp), False))

    fact_cells = []
    for idx, (label, value, is_mono) in enumerate(facts):
        last = idx == len(facts) - 1
        cls = "fact fact-last" if last else "fact"
        edge = "" if last else "border-right:1px solid #F0E5C8;"
        vfont = mono if is_mono else sans
        vbreak = "break-all" if is_mono else "break-word"
        fact_cells.append(
            f'<td class="{cls}" bgcolor="#FBF8F1" valign="top"'
            f' style="padding:10px 12px;background:#FBF8F1;{edge}">'
            f'<div style="font-family:{sans};font-size:8.5px;letter-spacing:0.12em;'
            f'text-transform:uppercase;font-weight:600;color:#8B6914;'
            f'padding-bottom:4px;">{label.upper()}</div>'
            f'<div style="font-family:{vfont};font-size:12px;font-weight:700;'
            f'color:#0B3D2E;line-height:1.35;word-break:{vbreak};'
            f'overflow-wrap:anywhere;">{value}</div></td>'
        )
    facts_row = "".join(fact_cells)

    outcomes_html = " &middot; ".join(escape(o) for o in _REPORTABLE_OUTCOMES)
    support_html = escape(_SUPPORT_SENTENCE)

    html = f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml"
 xmlns:v="urn:schemas-microsoft-com:vml"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:w="urn:schemas-microsoft-com:office:word">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<meta http-equiv="X-UA-Compatible" content="IE=edge"/>
<meta name="color-scheme" content="light only"/>
<meta name="supported-color-schemes" content="light"/>
<title>Delivery confirmation</title>
<!--[if mso]><xml><o:OfficeDocumentSettings><o:AllowPNG/>
<o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml><![endif]-->
<style type="text/css">{_EMAIL_STYLE}</style>
</head>
<body style="margin:0;padding:0;background-color:#FBF8F1;color:#0F172A;font-family:{sans};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">
Your Estrella shipment has been delivered &ndash; please confirm its condition.
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
 bgcolor="#FBF8F1" style="background-color:#FBF8F1;">
<tr><td align="center" style="padding:24px 12px;">
<!--[if mso]><table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->
<table role="presentation" class="card" width="600" cellpadding="0" cellspacing="0" border="0"
 style="width:600px;max-width:600px;background-color:#ffffff;border:1px solid #E2E8F0;">

<tr><td class="pad" bgcolor="#0B3D2E"
 style="background-color:#0B3D2E;padding:20px 24px;">
  <div style="font-family:{sans};font-size:13px;letter-spacing:0.22em;text-transform:uppercase;
   font-weight:700;color:#C9A24B;">Estrella Jewels</div>
  <div style="height:1px;line-height:1px;font-size:0;background-color:#C9A24B;
   opacity:0.5;margin:10px 0 12px;">&nbsp;</div>
  <div style="font-family:{sans};font-size:9px;letter-spacing:0.18em;text-transform:uppercase;
   font-weight:600;color:#C9A24B;padding-bottom:6px;">Delivery confirmation</div>
  <h1 class="h1" style="margin:0;font-family:{sans};font-size:18px;line-height:1.35;
   font-weight:700;color:#ffffff;">Your Estrella shipment has been delivered</h1>
</td></tr>

<tr><td class="pad" style="padding:24px 24px 8px;font-family:{sans};font-size:13px;
 line-height:1.55;color:#0F172A;">
  <p style="margin:0 0 12px;">Dear {who},</p>
  <p style="margin:0 0 18px;">{support_html}</p>
</td></tr>

<tr><td class="pad" style="padding:0 24px 20px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
   style="width:100%;border:1px solid #E2E8F0;border-radius:6px;">
    <tr>{facts_row}</tr>
  </table>
</td></tr>

<tr><td class="pad" align="center" style="padding:0 24px 18px;">
  <!--[if mso]>
  <v:roundrect href="{link_e}" arcsize="8%" stroke="f" fillcolor="#0B3D2E"
   style="height:44px;width:262px;v-text-anchor:middle;">
  <w:anchorlock/>
  <center style="color:#ffffff;font-family:Arial,sans-serif;font-size:13px;font-weight:bold;">
  Confirm delivery condition</center>
  </v:roundrect>
  <![endif]-->
  <!--[if !mso]><!-->
  <a class="cta-link" href="{link_e}"
   style="display:inline-block;background-color:#0B3D2E;color:#ffffff;font-family:{sans};
   font-size:13px;font-weight:600;line-height:20px;text-decoration:none;border-radius:4px;
   padding:12px 22px;mso-hide:all;">Confirm delivery condition</a>
  <!--<![endif]-->
</td></tr>

<tr><td class="pad" style="padding:0 24px 18px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
   style="width:100%;background-color:#F0F6F4;border-left:3px solid #0B3D2E;">
    <tr><td style="padding:12px;font-family:{sans};font-size:10.5px;line-height:1.6;color:#475569;">
      The secure link lets you report: {outcomes_html} &mdash; with comments and photographs.
    </td></tr>
  </table>
</td></tr>

<tr><td class="pad" style="padding:0 24px 22px;font-family:{sans};font-size:10.5px;
 line-height:1.6;color:#475569;word-break:break-all;overflow-wrap:anywhere;">
  If the button does not open, use this secure link:<br/>
  <a href="{link_e}" style="color:#0B3D2E;">{link_e}</a>
</td></tr>

<tr><td class="pad" bgcolor="#F8FAFC" align="center"
 style="background-color:#F8FAFC;padding:16px 24px;font-family:{sans};font-size:9.5px;
 line-height:1.7;color:#64748B;text-align:center;">
  Estrella Jewels Sp. z o.o. &middot; ul. Saba&#322;y 58, 02-174 Warszawa &middot; NIP PL5252812119<br/>
  info@estrellajewels.eu &middot; www.estrellajewels.eu
</td></tr>

</table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr></table>
</body></html>"""

    who_txt = customer_name or "Customer"
    lines = [
        "Your Estrella shipment has been delivered",
        "",
        f"Dear {who_txt},",
        "",
        _SUPPORT_SENTENCE,
        "",
        "SHIPMENT DETAILS",
        f"  Recipient: {who_txt}",
        "  Carrier:   DHL",
        f"  AWB:       {awb}",
    ]
    if when_disp:
        lines.append(f"  Delivered: {when_disp}")
    if loc_disp:
        lines.append(f"  Location:  {loc_disp}")
    lines += [
        "",
        "Confirm delivery condition:",
        link,
        "",
        "The secure link lets you report:",
    ]
    lines += [f"  - {o}" for o in _REPORTABLE_OUTCOMES]
    lines += [
        "",
        "You can add comments and photographs when reporting an issue.",
        "",
        "Thank you,",
        "Estrella Jewels",
        "Estrella Jewels Sp. z o.o. | ul. Sabaly 58, 02-174 Warszawa | NIP PL5252812119",
        "info@estrellajewels.eu | www.estrellajewels.eu",
        "",
    ]
    text = "\n".join(lines)
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
