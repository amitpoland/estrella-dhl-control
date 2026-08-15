"""Carrier credential errors — fail closed, no secret content."""
from __future__ import annotations


class CarrierCredentialError(Exception):
    """Base credential authority error."""


class CarrierCredentialNotConfigured(CarrierCredentialError):
    """No active credential for (carrier, capability, environment)."""
