"""ONE customer/ship-to party projection for commercial documents.

Authority for seller / buyer / ship-to on Packing List and CMR.

  buyer  ← draft buyer_override (else client_name / Customer Master billing)
  ship-to ← draft ship_to_override (else buyer / delivery)

Preview consumes this via packing-list.json / cmr.json. Exporters call the same
helper. Do not re-implement party cascade in React.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger(__name__)


def _draft_get(draft: Any, key: str, default: Any = None) -> Any:
    if draft is None:
        return default
    if isinstance(draft, dict):
        return draft.get(key, default)
    return getattr(draft, key, default)


def _parse_override(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            parsed = json.loads(s)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def draft_buyer_override(draft: Any) -> Dict[str, Any]:
    """Prefer already-parsed buyer_override; else buyer_override_json."""
    direct = _draft_get(draft, "buyer_override")
    if isinstance(direct, dict) and direct:
        return dict(direct)
    return _parse_override(_draft_get(draft, "buyer_override_json"))


def draft_ship_to_override(draft: Any) -> Dict[str, Any]:
    direct = _draft_get(draft, "ship_to_override")
    if isinstance(direct, dict) and direct:
        return dict(direct)
    return _parse_override(_draft_get(draft, "ship_to_override_json"))


def _party(
    *,
    name: str = "",
    addr: str = "",
    city: str = "",
    zip_code: str = "",
    country: str = "",
    vat: str = "",
    email: str = "",
    phone: str = "",
) -> Dict[str, str]:
    return {
        "name": name or "",
        "addr": addr or "",
        "city": city or "",
        "zip": zip_code or "",
        "country": country or "",
        "vat": vat or "",
        "email": email or "",
        "phone": phone or "",
    }


def seller_from_company(company: Any) -> Dict[str, str]:
    if company is None:
        return _party()
    return _party(
        name=getattr(company, "legal_name", None) or "",
        addr=getattr(company, "street", None) or "",
        city=getattr(company, "postal_city", None) or "",
        country=getattr(company, "country", None) or "",
        vat=getattr(company, "vat_eu", None) or getattr(company, "nip", None) or "",
        email=getattr(company, "email", None) or "",
        phone=getattr(company, "phone", None) or "",
    )


def resolve_document_parties(
    *,
    draft: Any,
    company: Any = None,
    customer: Any = None,
    delivery_addr: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str]]:
    """Return (seller, buyer, shipto) using Preview override authority.

    Order (matches proforma-detail.jsx):
      1. Draft buyer_override / ship_to_override when present
      2. Explicit delivery_addr for ship-to when provided
      3. Customer Master billing/delivery as fill-in for blanks
      4. draft.client_name as last name fallback
    """
    seller = seller_from_company(company)
    bo = draft_buyer_override(draft)
    sto = draft_ship_to_override(draft)
    client_name = str(
        _draft_get(draft, "client_name") or ""
    ).strip()

    # Customer Master fill-in (never overrides a populated draft override field).
    cm_buyer = _party()
    cm_ship = _party()
    if customer is not None:
        try:
            from .customer_master import resolve_billing_address, resolve_delivery_address
            bill = resolve_billing_address(customer) or {}
            deliv = resolve_delivery_address(customer) or {}
            cm_buyer = _party(
                name=bill.get("name", ""),
                addr=bill.get("street", ""),
                city=bill.get("city", ""),
                zip_code=bill.get("postal_code", ""),
                country=bill.get("country", ""),
                email=bill.get("email", ""),
                phone=bill.get("phone", ""),
                vat=getattr(customer, "vat_number", None)
                or getattr(customer, "nip", None)
                or bill.get("vat")
                or "",
            )
            cm_ship = _party(
                name=deliv.get("name", "") or cm_buyer.get("name", ""),
                addr=deliv.get("street", "") or cm_buyer.get("addr", ""),
                city=deliv.get("city", "") or cm_buyer.get("city", ""),
                zip_code=deliv.get("postal_code", "") or cm_buyer.get("zip", ""),
                country=deliv.get("country", "") or cm_buyer.get("country", ""),
                email=deliv.get("email", "") or cm_buyer.get("email", ""),
                phone=deliv.get("phone", "") or cm_buyer.get("phone", ""),
            )
        except Exception as exc:
            log.debug("document parties CM resolve failed: %s", exc)

    buyer = _party(
        name=(bo.get("name") or cm_buyer.get("name") or client_name or ""),
        addr=(bo.get("street") or cm_buyer.get("addr") or ""),
        city=(bo.get("city") or cm_buyer.get("city") or ""),
        zip_code=(bo.get("zip") or cm_buyer.get("zip") or ""),
        country=(bo.get("country") or cm_buyer.get("country") or ""),
        vat=(bo.get("vat_id") or bo.get("vat") or bo.get("nip") or cm_buyer.get("vat") or ""),
        email=(bo.get("email") or cm_buyer.get("email") or ""),
        phone=(bo.get("phone") or cm_buyer.get("phone") or ""),
    )

    # Ship-to: override first, then delivery_addr, then buyer (Preview rule).
    if any(sto.get(k) for k in ("name", "street", "city", "zip", "country")):
        shipto = _party(
            name=sto.get("name") or buyer.get("name") or "",
            addr=sto.get("street") or "",
            city=sto.get("city") or "",
            zip_code=sto.get("zip") or "",
            country=sto.get("country") or "",
            email=sto.get("email") or buyer.get("email") or "",
            phone=sto.get("phone") or buyer.get("phone") or "",
        )
    elif delivery_addr:
        shipto = _party(
            name=delivery_addr.get("name", "") or buyer.get("name", ""),
            addr=delivery_addr.get("street", ""),
            city=delivery_addr.get("city", ""),
            zip_code=delivery_addr.get("postal_code", "") or delivery_addr.get("zip", ""),
            country=delivery_addr.get("country", ""),
            email=delivery_addr.get("email", "") or buyer.get("email", ""),
            phone=delivery_addr.get("phone", "") or buyer.get("phone", ""),
        )
    elif cm_ship.get("name") or cm_ship.get("addr"):
        shipto = cm_ship
    else:
        shipto = dict(buyer)

    return seller, buyer, shipto
