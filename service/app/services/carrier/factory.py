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
    use_sandbox: bool = False
    account_number: Optional[str] = None
    live_allowlist: str = ""                       # comma-separated batch_ids; empty = no live


def get_adapter(
    config: CarrierConfig,
    provider: str = "DHL",
) -> AbstractCarrierAdapter:
    """
    Return the carrier adapter for the selected provider + status gate.

    Raises CarrierGateError for "pending" and any unknown status.
    Never falls back silently to DHL when FedEx/UPS is selected.
    """
    code = (provider or "DHL").strip().upper() or "DHL"
    if code == "UPS":
        from .adapters.ups import UpsSandboxAdapter, ups_credentials_present

        # Fail closed and loudly: an unconfigured UPS is never substituted
        # with DHL, and no adapter is handed back that looks bookable.
        if not ups_credentials_present():
            raise CarrierGateError("UPS_NOT_CONFIGURED")
        return UpsSandboxAdapter(config)
    if code == "FEDEX":
        from .adapters.fedex import FedExSandboxAdapter

        return FedExSandboxAdapter(config)
    if code == "OTHER":
        raise CarrierGateError("OTHER_IS_EXTERNAL_ONLY")
    if code != "DHL":
        raise CarrierGateError(
            f"Unknown booking provider {code!r}. Never silently routed to DHL."
        )

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
