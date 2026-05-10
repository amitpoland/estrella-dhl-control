"""
CarrierFactory — selects the correct adapter from carrier_api_status.

Rules:
  "pending" → CarrierGateError (explicit, loud — not a fallback)
  "shadow"  → DhlExpressShadowAdapter
  "live"    → DhlExpressLiveAdapter (further gated by allowlist + credentials)
  anything else → CarrierGateError (unknown state is always an error)

No silent downgrade. If the status is unexpected the call fails loudly
so that misconfiguration is never masked as degraded behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .adapters.base import AbstractCarrierAdapter
from .models.shipment import CarrierGateError


@dataclass
class CarrierConfig:
    """Lightweight config passed to the factory. Built by the caller from Settings."""

    status: str                                    # "pending" | "shadow" | "live"
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    api_url: str = "https://express.api.dhl.com"
    account_number: Optional[str] = None
    live_allowlist: str = ""                       # comma-separated batch_ids; empty = no live


def get_adapter(config: CarrierConfig) -> AbstractCarrierAdapter:
    """
    Return the carrier adapter for the current status gate.

    Raises CarrierGateError for "pending" and any unknown status.
    Never falls back silently to a lower-capability adapter.
    """
    if config.status == "shadow":
        from .adapters.shadow import DhlExpressShadowAdapter
        return DhlExpressShadowAdapter()

    if config.status == "live":
        from .adapters.live import DhlExpressLiveAdapter
        return DhlExpressLiveAdapter(config)

    if config.status == "pending":
        raise CarrierGateError(
            "carrier_api_status is 'pending' — carrier API is not yet activated. "
            "Set CARRIER_API_STATUS=shadow or CARRIER_API_STATUS=live in .env to enable."
        )

    raise CarrierGateError(
        f"Unknown carrier_api_status: {config.status!r}. "
        "Expected 'pending', 'shadow', or 'live'."
    )
