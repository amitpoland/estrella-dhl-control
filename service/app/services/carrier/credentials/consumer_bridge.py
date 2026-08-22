"""Thin DHL consumer bridge — secrets via resolve_carrier_credentials only.

Unmigrated identities still resolve to legacy Settings (resolver policy).
Migrated identities resolve to secure store only. Consumers never import DPAPI
or file_store. Soft-miss returns empty fields (parity with blank Settings).
"""
from __future__ import annotations

from typing import Mapping

from app.core.config import settings

from .exceptions import CarrierCredentialNotConfigured
from .resolver import resolve_carrier_credentials


def resolve_dhl_secret_fields(capability: str) -> dict[str, str]:
    """Return secret fields for dhl/production/<capability>; empty on soft-miss."""
    try:
        bundle = resolve_carrier_credentials("dhl", capability, "production")
    except CarrierCredentialNotConfigured:
        return {}
    return {str(k): str(v) for k, v in (bundle.fields or {}).items()}


def resolve_fedex_secret_fields(
    capability: str = "ship_rate",
    environment: str = "sandbox",
) -> dict[str, str]:
    """Return FedEx secret fields via the single resolver; empty on soft-miss."""
    try:
        bundle = resolve_carrier_credentials("fedex", capability, environment)
    except CarrierCredentialNotConfigured:
        return {}
    return {str(k): str(v) for k, v in (bundle.fields or {}).items()}


def resolve_ups_secret_fields(
    capability: str = "ship",
    environment: str = "sandbox",
) -> dict[str, str]:
    """Return UPS secret fields via the single resolver; empty on soft-miss."""
    try:
        bundle = resolve_carrier_credentials("ups", capability, environment)
    except CarrierCredentialNotConfigured:
        return {}
    return {str(k): str(v) for k, v in (bundle.fields or {}).items()}


def express_carrier_config_kwargs(capability: str) -> dict:
    """Build CarrierConfig kwargs: secrets from resolver, gate/URL from Settings."""
    fields: Mapping[str, str] = resolve_dhl_secret_fields(capability)
    return {
        "status": settings.carrier_api_status,
        "api_key": fields.get("api_key") or "",
        "api_secret": fields.get("api_secret") or "",
        "api_url": settings.dhl_express_api_url,
        "use_sandbox": settings.dhl_express_use_sandbox,
        "account_number": fields.get("account_number")
        or (settings.dhl_express_account_number or ""),
        "live_allowlist": settings.carrier_live_allowlist,
        "fedex_allow_production": bool(
            getattr(settings, "fedex_allow_production", False)
        ),
    }
