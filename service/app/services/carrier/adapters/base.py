"""
Abstract base class for carrier adapters.
No business logic. No HTTP. No DB.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models.shipment import ShipmentRequest, ShipmentResult


class AbstractCarrierAdapter(ABC):

    @abstractmethod
    def create_shipment(self, request: ShipmentRequest) -> ShipmentResult:
        ...

    @abstractmethod
    def get_shipment(self, tracking_ref: str) -> ShipmentResult:
        ...
