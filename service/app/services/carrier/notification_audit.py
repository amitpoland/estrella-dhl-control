"""MyDHL shipmentNotification build + booking-time audit (no secrets).

Authority: Create Shipment ``shipmentNotification`` entries are derived only
from ``ShipmentRequest.recipient_address``. This module owns the shared
builder used by the live adapter and the durable booking audit written to
``carrier_shipments`` so Control Tower can prove email/SMS were requested.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


PROVIDER = "mydhl_express"
RECIPIENT_AUTHORITY = "shipment_request.recipient_address"


def mask_email(email: Optional[str]) -> Optional[str]:
    email = (email or "").strip()
    if not email or "@" not in email:
        return None
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        return f"{local[:1]}***@{domain}"
    return f"{local[:2]}***@{domain}"


def mask_phone(phone: Optional[str]) -> Optional[str]:
    phone = (phone or "").strip().replace(" ", "")
    if not phone:
        return None
    if len(phone) <= 4:
        return "***"
    return f"{phone[:3]}***{phone[-2:]}"


def build_shipment_notifications(recipient_address: Optional[dict]) -> List[dict]:
    """Build MyDHL ``shipmentNotification`` entries from recipient contact.

    Official shape (MyDHL Express REST Create Shipment):
      [{"typeCode": "email"|"sms", "receiverId": "<email|phone>", "languageCode": "eng"}]
    Email when non-blank. SMS only when phone is E.164-like (leading '+').
    """
    addr = recipient_address or {}
    out: List[dict] = []
    email = (addr.get("email") or "").strip()
    if email and "@" in email:
        out.append({
            "typeCode": "email",
            "receiverId": email,
            "languageCode": "eng",
        })
    phone = (addr.get("phone") or "").strip().replace(" ", "")
    if phone.startswith("+") and len(phone) >= 8 and phone[1:].isdigit():
        out.append({
            "typeCode": "sms",
            "receiverId": phone,
            "languageCode": "eng",
        })
    return out


def build_notification_audit(
    recipient_address: Optional[dict],
    *,
    recipient_source: str = RECIPIENT_AUTHORITY,
    provider: str = PROVIDER,
    requested_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a secret-free booking audit dict for ``carrier_shipments``.

    Never includes raw email/phone — only masks + booleans + metadata.
    """
    notifications = build_shipment_notifications(recipient_address)
    email_req = False
    sms_req = False
    email_masked = None
    sms_masked = None
    for entry in notifications:
        if not isinstance(entry, dict):
            continue
        t = (entry.get("typeCode") or "").strip().lower()
        rid = entry.get("receiverId")
        if t == "email":
            email_req = True
            email_masked = mask_email(str(rid or ""))
        elif t == "sms":
            sms_req = True
            sms_masked = mask_phone(str(rid or ""))
    ts = (requested_at or "").strip() or datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    return {
        "dhl_notify_email_requested": 1 if email_req else 0,
        "dhl_notify_sms_requested": 1 if sms_req else 0,
        "dhl_notify_email_masked": email_masked,
        "dhl_notify_sms_masked": sms_masked,
        "dhl_notify_recipient_source": recipient_source or RECIPIENT_AUTHORITY,
        "dhl_notify_provider": provider or PROVIDER,
        "dhl_notify_requested_at": ts,
        # Convenience for logs / shadow (never secrets)
        "type_codes": [e.get("typeCode") for e in notifications if isinstance(e, dict)],
    }
