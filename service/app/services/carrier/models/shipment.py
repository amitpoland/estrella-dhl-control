"""
Pure data models for the carrier subsystem.
No business logic. No HTTP. No DB.
No imports from customs-clearance services.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ShipmentMode(str, Enum):
    SHADOW = "shadow"
    LIVE = "live"


class ShipmentState(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class ShipmentRequest:
    batch_id: str
    shipper_account: str
    recipient_address: dict   # may include email, phone, company
    declared_value: float
    currency: str
    weight_kg: float
    dimensions: dict
    special_instructions: Optional[str] = None
    # Upgraded AWB modal fields
    product_code: str = "P"                      # DHL productCode (P=Express Worldwide)
    description: str = "Jewellery"               # content.description
    customer_reference: Optional[str] = None     # proforma/order ref → customerReferences CU
    shipment_reference: Optional[str] = None     # batch/internal ref  → customerReferences AAO
    receiver_vat_id: Optional[str] = None        # DHL registrationNumbers EUV
    receiver_eori: Optional[str] = None          # DHL registrationNumbers EOR
    box_type_code: Optional[str] = None          # Box Master profile selected in the AWB modal
                                                 # (display/persistence only — dims already resolved)


@dataclass
class ShipmentResult:
    idempotency_key: str
    mode: ShipmentMode
    state: ShipmentState
    tracking_ref: Optional[str] = None
    error: Optional[str] = None
    simulated: bool = False
    # Phase 5 — carrier API response fields captured for audit/proforma
    service_product: Optional[str] = None   # e.g. "EXPRESS_WORLDWIDE"
    dimensions_json: Optional[str] = None   # JSON-serialised dimensions dict
    # True when served from the stored COMPLETE row (idempotency replay) —
    # no adapter call was made, no new shipment was created.
    replayed: bool = False


class CarrierGateError(Exception):
    """Raised when the carrier API gate is not in the required state."""


class CarrierConfigError(Exception):
    """Raised when carrier configuration is invalid or incomplete."""


class CarrierAllowlistError(Exception):
    """Raised when a batch_id is not on the live allowlist."""


def compute_idempotency_key(request: ShipmentRequest) -> str:
    """
    Deterministic idempotency key for a shipment request.

    sha256 of the canonical JSON of the fields that uniquely identify
    a shipment intent. Same inputs always produce the same key.
    Used by both the adapter and the coordinator (so the coordinator
    can query the DB before calling the adapter).
    """
    canonical = json.dumps(
        {
            "batch_id": request.batch_id,
            "shipper_account": request.shipper_account,
            "weight_kg": request.weight_kg,
            "declared_value": request.declared_value,
            "currency": request.currency,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
