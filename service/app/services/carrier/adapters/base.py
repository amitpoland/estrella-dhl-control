"""
Abstract base class for carrier adapters.
No business logic. No HTTP. No DB.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..models.shipment import (
    CarrierCapabilityUnsupported,
    ShipmentRequest,
    ShipmentResult,
)


class AbstractCarrierAdapter(ABC):

    @abstractmethod
    def create_shipment(self, request: ShipmentRequest) -> ShipmentResult:
        ...

    @abstractmethod
    def get_shipment(self, tracking_ref: str) -> ShipmentResult:
        ...

    # ── Optional capabilities ───────────────────────────────────────────────
    # Deliberately NOT abstract. Booking is the contract every carrier must
    # honour; tracking, proof of delivery and document images are services a
    # given carrier may simply not sell. Declaring them here gives every
    # adapter one documented shape to override and one documented way to say
    # "not supported" — CarrierCapabilityUnsupported, which callers render as
    # skipped. DHL implements all four; FedEx and UPS inherit these until they
    # do. An adapter must never fake one by returning empty bytes or a dict
    # that reads like a real answer.

    def track_shipment(self, tracking_ref: str) -> dict:
        raise CarrierCapabilityUnsupported("track_shipment")

    def fetch_electronic_pod(
        self,
        tracking_ref: str,
        *,
        content: str = "epod-summary",
    ) -> Optional[bytes]:
        raise CarrierCapabilityUnsupported("fetch_electronic_pod")

    def fetch_electronic_pod_outcome(
        self,
        tracking_ref: str,
        *,
        content: str = "epod-summary",
    ) -> dict:
        raise CarrierCapabilityUnsupported("fetch_electronic_pod_outcome")

    def fetch_document_image(
        self,
        tracking_ref: str,
        *,
        type_code: str = "waybill",
        pickup_year_month: str,
        encoding_format: str = "pdf",
    ) -> dict:
        raise CarrierCapabilityUnsupported("fetch_document_image")
