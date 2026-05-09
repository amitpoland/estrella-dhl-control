"""
DhlExpressShadowAdapter — deterministic simulation, no HTTP, no real AWBs.

Behaviour contract:
  - Every response has simulated=True and mode=SHADOW.
  - Idempotency key is sha256 of a canonical JSON of the request fields
    that identify a unique shipment intent (batch_id, shipper_account,
    weight_kg, declared_value, currency). Same inputs → same key always.
  - Simulated tracking ref is "SIM-{first-8-hex-chars-of-key}" — stable
    across calls for the same request, clearly marked as non-real.
  - No HTTP, no DB, no filesystem access. Pure in-memory computation.
  - No httpx / requests / urllib imports anywhere in this module.
"""
from __future__ import annotations

import hashlib

from .base import AbstractCarrierAdapter
from ..models.shipment import (
    ShipmentMode,
    ShipmentRequest,
    ShipmentResult,
    ShipmentState,
    compute_idempotency_key,
)


class DhlExpressShadowAdapter(AbstractCarrierAdapter):

    # ── public interface ──────────────────────────────────────────────────────

    def create_shipment(self, request: ShipmentRequest) -> ShipmentResult:
        key = _idempotency_key(request)
        return ShipmentResult(
            idempotency_key=key,
            mode=ShipmentMode.SHADOW,
            state=ShipmentState.SUBMITTED,
            tracking_ref=_sim_ref(key),
            simulated=True,
        )

    def get_shipment(self, tracking_ref: str) -> ShipmentResult:
        key = hashlib.sha256(tracking_ref.encode()).hexdigest()
        return ShipmentResult(
            idempotency_key=key,
            mode=ShipmentMode.SHADOW,
            state=ShipmentState.COMPLETE,
            tracking_ref=tracking_ref,
            simulated=True,
        )


# ── helpers ───────────────────────────────────────────────────────────────────

# Alias kept for backward-compatibility with tests that import _idempotency_key directly.
_idempotency_key = compute_idempotency_key


def _sim_ref(idempotency_key: str) -> str:
    return f"SIM-{idempotency_key[:8].upper()}"
