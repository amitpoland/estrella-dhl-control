"""
carrier.base — shared, carrier-agnostic dataclasses.

Anything in this module is consumed by both the state engine, the label
store, the shipment DB, and the adapter protocol. Concrete carriers
(DHL/FedEx/UPS) MUST NOT import their own copies of these types — the
whole point of Layer-2 is one set of names.

DL-A scope: small set of value types with no behaviour. No HTTP client,
no audit hooks, no DB code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

# ── Carrier identifiers ──────────────────────────────────────────────────────
#
# Carrier strings are deliberately lowercase and stable. The shipment
# registry uses these as part of a composite unique key, so any rename
# is a schema migration.

CARRIER_DHL: str = "dhl"
CARRIER_FEDEX: str = "fedex"
CARRIER_UPS: str = "ups"

KNOWN_CARRIERS: Tuple[str, ...] = (CARRIER_DHL, CARRIER_FEDEX, CARRIER_UPS)


# ── Address / package value types ────────────────────────────────────────────

@dataclass(frozen=True)
class CarrierAddress:
    """Postal address used for ship-from / ship-to.

    Frozen so a single ``CarrierAddress`` instance can be hashed and
    safely shared across multiple shipment requests.
    """
    name:        str
    company:     str = ""
    street_1:    str = ""
    street_2:    str = ""
    city:        str = ""
    postal_code: str = ""
    country:     str = ""        # ISO 3166-1 alpha-2 (e.g. "PL", "US")
    phone:       str = ""
    email:       str = ""


@dataclass(frozen=True)
class PackageSpec:
    """One physical package within a shipment.

    Multi-piece shipments are represented as multiple ``PackageSpec``
    instances on a single ``CarrierShipmentRequest`` — never as N
    separate shipments. DHL Create Shipment supports up to 999 pieces
    per AWB; this layer simply forwards.
    """
    weight_kg:          float
    length_cm:          float
    width_cm:           float
    height_cm:          float
    declared_value:     float = 0.0
    declared_currency:  str = "USD"
    description:        str = ""


# ── Shipment request / response ──────────────────────────────────────────────

@dataclass(frozen=True)
class CarrierShipmentRequest:
    """All inputs the coordinator hands to an adapter to create a shipment.

    The adapter is responsible for translating this into the carrier's
    wire format and back. It MUST NOT mutate the request, and MUST NOT
    look up addresses, customer data, or audit state — that all happens
    upstream in the coordinator (DL-D).
    """
    batch_id:      str
    ship_from:     CarrierAddress
    ship_to:       CarrierAddress
    packages:      Tuple[PackageSpec, ...]
    service_code:  str = ""              # carrier-specific service tier
    reference:     str = ""              # operator-visible reference
    metadata:      Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RawShipmentResponse:
    """The raw, carrier-specific result of a successful create-shipment.

    ``label_bytes`` is whatever format the carrier returned (PDF, ZPL,
    PNG); the label store hashes and persists it as-is. ``raw`` carries
    the full decoded response body so future evidence/lineage code can
    inspect it without re-fetching.
    """
    awb:                str
    carrier:            str
    label_bytes:        bytes
    label_format:       str = "pdf"      # "pdf" | "zpl" | "png"
    label_filename:     str = ""
    raw:                Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RawCancelResponse:
    """Result of a cancel/void call.

    DHL allows void only before handover; this layer does not enforce
    that — the state engine does. Adapters surface whatever the carrier
    returned and let the coordinator interpret it.
    """
    carrier:        str
    awb:            str
    accepted:       bool
    reason:         str = ""
    raw:            Dict[str, Any] = field(default_factory=dict)


# ── Inbound carrier event (webhook / poll) ───────────────────────────────────

@dataclass(frozen=True)
class CarrierEvent:
    """One normalized event from a carrier (webhook push or polled).

    Whatever the wire format, the adapter's ``parse_webhook_event`` must
    yield an instance of this. The coordinator then maps ``event_code``
    onto the state engine via a per-carrier translation table.
    """
    carrier:        str
    awb:            str
    event_code:     str
    occurred_at:    str                  # ISO-8601
    location:       str = ""
    description:    str = ""
    raw:            Dict[str, Any] = field(default_factory=dict)


# ── Label artefact ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LabelArtefact:
    """A persisted label file, returned from the label store.

    ``sha256`` is content-addressed: same bytes produce the same path.
    """
    sha256:     str
    path:       str
    size:       int
    mime:       str = ""
    label_format: str = ""


# ── Helpers ──────────────────────────────────────────────────────────────────

def is_known_carrier(carrier: Optional[str]) -> bool:
    """True iff *carrier* is one of the known lowercase carrier IDs."""
    if not carrier:
        return False
    return carrier in KNOWN_CARRIERS
