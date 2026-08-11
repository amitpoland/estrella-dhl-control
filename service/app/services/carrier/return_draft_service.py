"""Linked return DRAFT lifecycle (Slice A) — prepare / get / patch only.

NO MyDHL createShipment. NO Live Create Return. create_return stays HOLD.
Persistence reuses carrier_shipments (additive columns + direction=return).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..contact_normalize import normalize_email, normalize_phone_e164
from ..country_lookup import (
    country_display_name,
    is_eu_country,
    normalize_country_alpha2,
)
from .models.shipment import compute_return_idempotency_key
from .persistence import shipment_db

DHL_RETURN_CAPABILITY_PENDING = "pending"
CREATE_RETURN_DISABLED_REASON = "DHL return capability pending"
CUSTOMS_NOT_REQUIRED = "not_required"
CUSTOMS_REQUIRED_PENDING = "required_pending"
CUSTOMS_INCOMPLETE = "incomplete"


class ReturnDraftError(Exception):
    """Business error for return-draft prepare/patch (maps to HTTP)."""

    def __init__(self, code: str, message: str, *, http_status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _snapshot_outbound(row: dict) -> dict:
    """Copy of outbound fields used to prove zero mutation after prepare."""
    return {
        k: row.get(k)
        for k in (
            "idempotency_key",
            "batch_id",
            "client_ref",
            "mode",
            "state",
            "tracking_ref",
            "weight_kg",
            "declared_value",
            "currency",
            "updated_at",
            "shipment_direction",
            "parent_tracking_ref",
        )
    }


def _estrella_receiver_preview(storage_root: Path) -> Dict[str, Any]:
    """Estrella as return receiver — company_profile, then DHL shipper env."""
    from ...core.config import settings
    from ..master_data_db import get_company_profile

    preview: Dict[str, Any] = {"source": "estrella_shipper_settings"}
    cp = None
    try:
        cp = get_company_profile(Path(storage_root) / "master_data.sqlite")
    except Exception:
        cp = None
    if cp is not None:
        postal_city = (getattr(cp, "postal_city", None) or "").strip()
        city, zip_code = postal_city, ""
        # Common "00-000 City" / "City 00-000" — keep honest when unsure.
        if postal_city and " " in postal_city:
            parts = postal_city.split()
            if parts[0][:1].isdigit():
                zip_code, city = parts[0], " ".join(parts[1:])
            elif parts[-1][:1].isdigit():
                city, zip_code = " ".join(parts[:-1]), parts[-1]
        cc = normalize_country_alpha2(getattr(cp, "country", None) or "PL") or "PL"
        preview.update({
            "name": (getattr(cp, "legal_name", None) or getattr(cp, "short_name", None) or "").strip(),
            "street": (getattr(cp, "street", None) or "").strip(),
            "city": city,
            "postal_code": zip_code,
            "country_code": cc,
            "country_name": country_display_name(cc),
            "phone": (getattr(cp, "phone", None) or "").strip(),
            "email": (getattr(cp, "email", None) or "").strip(),
            "source": "company_profile",
        })
        return preview

    cc = normalize_country_alpha2(settings.dhl_express_shipper_country_code) or "PL"
    preview.update({
        "name": (settings.dhl_express_shipper_name or "").strip(),
        "street": (settings.dhl_express_shipper_address1 or "").strip(),
        "city": (settings.dhl_express_shipper_city or "").strip(),
        "postal_code": (settings.dhl_express_shipper_postal_code or "").strip(),
        "country_code": cc,
        "country_name": country_display_name(cc),
        "phone": (settings.dhl_express_shipper_phone or "").strip(),
        "email": "",
        "source": "estrella_shipper_settings",
    })
    return preview


def _customer_shipper_preview(
    storage_root: Path,
    *,
    batch_id: str,
    client_ref: Optional[str],
    client_contractor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Customer as return shipper — reverse of outbound receiver (CM authority)."""
    from ..customer_master import resolve_delivery_address
    from .. import customer_master_db as cmdb
    from .doc_package import _resolve_customer_from_batch

    customer = None
    cid = (client_contractor_id or "").strip() or None
    if cid:
        try:
            customer = cmdb.get_customer(
                Path(storage_root) / "customer_master.sqlite", cid
            )
        except Exception:
            customer = None
    if customer is None:
        try:
            customer = _resolve_customer_from_batch(
                batch_id, client_name=client_ref, storage_root=Path(storage_root)
            )
        except Exception:
            customer = None
    if customer is None:
        return {
            "name": "",
            "street": "",
            "city": "",
            "postal_code": "",
            "country_code": None,
            "country_name": None,
            "phone": "",
            "email": "",
            "source": "unresolved",
        }

    addr = resolve_delivery_address(customer)
    cc = normalize_country_alpha2(addr.get("country"))
    return {
        "name": addr.get("name") or "",
        "person": addr.get("person") or "",
        "street": addr.get("street") or "",
        "city": addr.get("city") or "",
        "postal_code": addr.get("postal_code") or "",
        "country_code": cc,
        "country_name": country_display_name(cc),
        "phone": addr.get("phone") or "",
        "email": addr.get("email") or "",
        "source": addr.get("source") or "customer_master",
    }


def _customs_status(shipper_cc: Optional[str], receiver_cc: Optional[str]) -> str:
    origin = normalize_country_alpha2(shipper_cc)
    dest = normalize_country_alpha2(receiver_cc)
    if not origin or not dest:
        return CUSTOMS_INCOMPLETE
    if is_eu_country(origin) and is_eu_country(dest):
        return CUSTOMS_NOT_REQUIRED
    return CUSTOMS_REQUIRED_PENDING


def _normalize_contacts(
    email_raw: Optional[str],
    phone_raw: Optional[str],
    country_code: Optional[str],
) -> Dict[str, Any]:
    email, email_err = normalize_email(email_raw)
    phone, phone_err, needs_review = normalize_phone_e164(
        phone_raw, country_code=country_code
    )
    cc = normalize_country_alpha2(country_code)
    return {
        "contact_email": email,
        "contact_phone_e164": phone,
        "contact_country_code": cc,
        "contact_needs_review": 1 if (needs_review or email_err or phone_err) else 0,
        "email_error": email_err,
        "phone_error": phone_err,
        "country_name": country_display_name(cc),
    }


def _row_to_api(row: dict) -> Dict[str, Any]:
    shipper = {}
    receiver = {}
    try:
        if row.get("proposed_shipper_json"):
            shipper = json.loads(row["proposed_shipper_json"])
    except (TypeError, ValueError, json.JSONDecodeError):
        shipper = {}
    try:
        if row.get("proposed_receiver_json"):
            receiver = json.loads(row["proposed_receiver_json"])
    except (TypeError, ValueError, json.JSONDecodeError):
        receiver = {}
    cc = normalize_country_alpha2(row.get("contact_country_code"))
    return {
        "idempotency_key": row.get("idempotency_key"),
        "batch_id": row.get("batch_id"),
        "client_ref": row.get("client_ref"),
        "shipment_direction": "return",
        "return_intent_status": row.get("return_intent_status") or "prepared",
        "parent_tracking_ref": row.get("parent_tracking_ref"),
        "parent_idempotency_key": row.get("parent_idempotency_key"),
        "return_reason": row.get("return_reason"),
        "proposed_shipper": shipper,
        "proposed_receiver": receiver,
        "pieces": row.get("pieces"),
        "weight_kg": row.get("weight_kg"),
        "declared_value": row.get("declared_value"),
        "currency": row.get("currency"),
        "customs_requirement_status": row.get("customs_requirement_status"),
        "contact_email": row.get("contact_email"),
        "contact_phone_e164": row.get("contact_phone_e164"),
        "contact_country_code": cc,
        "contact_country_name": country_display_name(cc),
        "contact_needs_review": bool(row.get("contact_needs_review")),
        "dhl_return_capability": row.get("dhl_return_capability") or DHL_RETURN_CAPABILITY_PENDING,
        "create_return_available": False,
        "create_return_disabled_reason": CREATE_RETURN_DISABLED_REASON,
        "tracking_ref": None,  # draft is never a tracking candidate
        "mode": row.get("mode"),
        "state": row.get("state"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "booked_by": row.get("booked_by"),
    }


def prepare_return_draft(
    *,
    storage_root: Path,
    carrier_db_path: Path,
    batch_id: str,
    parent_tracking_ref: str,
    client_ref: Optional[str] = None,
    client_contractor_id: Optional[str] = None,
    return_reason: Optional[str] = None,
    pieces: Optional[int] = None,
    weight_kg: Optional[float] = None,
    declared_value: Optional[float] = None,
    currency: Optional[str] = None,
    contact_email: Optional[str] = None,
    contact_phone: Optional[str] = None,
    operator: Optional[str] = None,
) -> Dict[str, Any]:
    """Create (or return existing) linked return DRAFT. Zero DHL writes.

    Parent outbound row is never mutated. Idempotent on
    (direction=return, batch_id, parent_tracking_ref, client_ref).
    """
    parent_ref = (parent_tracking_ref or "").strip()
    if not parent_ref:
        raise ReturnDraftError(
            "PARENT_TRACKING_REQUIRED",
            "parent_tracking_ref (outbound AWB) is required to prepare a return.",
        )
    if not (batch_id or "").strip():
        raise ReturnDraftError("BATCH_REQUIRED", "batch_id is required.")

    shipment_db.init_db(carrier_db_path)

    parent = shipment_db.get_shipment_by_tracking_ref(carrier_db_path, parent_ref)
    if parent is None:
        # Honest miss — still allow prepare when UI knows the AWB from labels,
        # but prefer matching the outbound row for linkage.
        parent = {}
    elif (parent.get("batch_id") or "") != batch_id:
        raise ReturnDraftError(
            "PARENT_BATCH_MISMATCH",
            "Outbound AWB does not belong to this batch.",
            http_status=404,
        )

    parent_snapshot_before = _snapshot_outbound(parent) if parent else None
    parent_key = parent.get("idempotency_key") if parent else None

    key = compute_return_idempotency_key(
        batch_id=batch_id,
        parent_tracking_ref=parent_ref,
        client_ref=(client_ref or None),
    )
    existing = shipment_db.get_return_draft(
        carrier_db_path, batch_id=batch_id, idempotency_key=key
    )
    if existing:
        return {
            "draft": _row_to_api(existing),
            "created": False,
            "replayed": True,
            "parent_unchanged": True,
            "dhl_create_called": False,
        }

    shipper = _customer_shipper_preview(
        storage_root,
        batch_id=batch_id,
        client_ref=client_ref,
        client_contractor_id=client_contractor_id,
    )
    receiver = _estrella_receiver_preview(storage_root)

    email_src = contact_email if contact_email is not None else shipper.get("email")
    phone_src = contact_phone if contact_phone is not None else shipper.get("phone")
    contacts = _normalize_contacts(
        email_src, phone_src, shipper.get("country_code")
    )
    customs = _customs_status(
        shipper.get("country_code"), receiver.get("country_code")
    )

    w_kg = weight_kg if weight_kg is not None else parent.get("weight_kg")
    d_val = declared_value if declared_value is not None else parent.get("declared_value")
    curr = currency if currency is not None else (parent.get("currency") or "EUR")

    try:
        shipment_db.insert_return_draft(
            carrier_db_path,
            idempotency_key=key,
            batch_id=batch_id,
            parent_tracking_ref=parent_ref,
            parent_idempotency_key=parent_key,
            client_ref=client_ref,
            return_reason=(return_reason or "").strip() or None,
            proposed_shipper_json=json.dumps(shipper, sort_keys=True),
            proposed_receiver_json=json.dumps(receiver, sort_keys=True),
            pieces=pieces if pieces is not None else 1,
            weight_kg=float(w_kg) if w_kg is not None else None,
            declared_value=float(d_val) if d_val is not None else None,
            currency=curr,
            customs_requirement_status=customs,
            contact_email=contacts["contact_email"],
            contact_phone_e164=contacts["contact_phone_e164"],
            contact_country_code=contacts["contact_country_code"],
            contact_needs_review=contacts["contact_needs_review"],
            operator=operator,
        )
    except sqlite3.IntegrityError:
        # Race: concurrent prepare with same key — return existing.
        existing = shipment_db.get_return_draft(
            carrier_db_path, batch_id=batch_id, idempotency_key=key
        )
        if existing:
            return {
                "draft": _row_to_api(existing),
                "created": False,
                "replayed": True,
                "parent_unchanged": True,
                "dhl_create_called": False,
            }
        raise

    # Prove outbound parent untouched (zero mutation preferred).
    parent_unchanged = True
    if parent_snapshot_before and parent_key:
        after = shipment_db.get_shipment(carrier_db_path, parent_key)
        parent_unchanged = _snapshot_outbound(after or {}) == parent_snapshot_before

    draft = shipment_db.get_return_draft(
        carrier_db_path, batch_id=batch_id, idempotency_key=key
    )
    return {
        "draft": _row_to_api(draft or {"idempotency_key": key, "batch_id": batch_id}),
        "created": True,
        "replayed": False,
        "parent_unchanged": parent_unchanged,
        "dhl_create_called": False,
    }


def get_return_draft_api(
    carrier_db_path: Path,
    *,
    batch_id: str,
    parent_tracking_ref: Optional[str] = None,
    client_ref: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    row = shipment_db.get_return_draft(
        carrier_db_path,
        batch_id=batch_id,
        parent_tracking_ref=parent_tracking_ref,
        client_ref=client_ref,
        idempotency_key=idempotency_key,
    )
    return _row_to_api(row) if row else None


def patch_return_draft(
    carrier_db_path: Path,
    *,
    batch_id: str,
    idempotency_key: str,
    return_reason: Optional[str] = None,
    pieces: Optional[int] = None,
    weight_kg: Optional[float] = None,
    declared_value: Optional[float] = None,
    currency: Optional[str] = None,
    contact_email: Optional[str] = None,
    contact_phone: Optional[str] = None,
    contact_country_code: Optional[str] = None,
    customs_requirement_status: Optional[str] = None,
) -> Dict[str, Any]:
    """Edit an existing return DRAFT. Never enables Live Create."""
    existing = shipment_db.get_return_draft(
        carrier_db_path, batch_id=batch_id, idempotency_key=idempotency_key
    )
    if not existing or (existing.get("batch_id") or "") != batch_id:
        raise ReturnDraftError(
            "RETURN_DRAFT_NOT_FOUND",
            "Return draft not found for this batch.",
            http_status=404,
        )

    cc = contact_country_code
    if cc is None:
        cc = existing.get("contact_country_code")
    email_src = contact_email if contact_email is not None else existing.get("contact_email")
    phone_src = contact_phone if contact_phone is not None else existing.get("contact_phone_e164")
    contacts = _normalize_contacts(email_src, phone_src, cc)

    allowed_customs = {
        CUSTOMS_NOT_REQUIRED,
        CUSTOMS_REQUIRED_PENDING,
        CUSTOMS_INCOMPLETE,
        None,
    }
    if customs_requirement_status not in allowed_customs and customs_requirement_status is not None:
        raise ReturnDraftError(
            "CUSTOMS_STATUS_INVALID",
            f"customs_requirement_status must be one of "
            f"{CUSTOMS_NOT_REQUIRED}, {CUSTOMS_REQUIRED_PENDING}, {CUSTOMS_INCOMPLETE}.",
        )

    n = shipment_db.update_return_draft(
        carrier_db_path,
        idempotency_key,
        return_reason=return_reason,
        pieces=pieces,
        weight_kg=weight_kg,
        declared_value=declared_value,
        currency=currency,
        customs_requirement_status=customs_requirement_status,
        contact_email=contacts["contact_email"] if contact_email is not None else None,
        contact_phone_e164=(
            contacts["contact_phone_e164"] if contact_phone is not None else None
        ),
        contact_country_code=(
            contacts["contact_country_code"] if contact_country_code is not None else None
        ),
        contact_needs_review=(
            contacts["contact_needs_review"]
            if (contact_email is not None or contact_phone is not None
                or contact_country_code is not None)
            else None
        ),
    )
    if n < 1:
        raise ReturnDraftError(
            "RETURN_DRAFT_NOT_FOUND",
            "Return draft not found for this batch.",
            http_status=404,
        )
    row = shipment_db.get_return_draft(
        carrier_db_path, batch_id=batch_id, idempotency_key=idempotency_key
    )
    return _row_to_api(row)


def assert_create_return_blocked() -> Tuple[int, Dict[str, Any]]:
    """Live Create Return is HOLD — always blocked until capability confirmed."""
    return 422, {
        "error": CREATE_RETURN_DISABLED_REASON,
        "code": "DHL_RETURN_CAPABILITY_PENDING",
        "create_return_available": False,
        "dhl_return_capability": DHL_RETURN_CAPABILITY_PENDING,
        "guidance": (
            "Prepare Return draft is available. Live Create Return is disabled "
            "until DHL account return capability is confirmed."
        ),
    }
