"""Carrier credential authority — public surface.

Canonical resolvers only. Adapters consume CredentialBundle; coordinator never
sees vendor field names or raw secrets.
"""
from __future__ import annotations

from .exceptions import CarrierCredentialError, CarrierCredentialNotConfigured
from .file_store import DpapiCredentialStore
from .models import (
    CAPABILITIES,
    CARRIERS,
    ENVIRONMENTS,
    CapabilityState,
    CredentialBundle,
    CredentialIdentity,
    CredentialMeta,
)
from .resolver import (
    configure_credential_store,
    configure_global_kill,
    resolve_carrier_capability,
    resolve_carrier_credentials,
)
from .store import CredentialStore, MemoryCredentialStore

__all__ = [
    "CAPABILITIES",
    "CARRIERS",
    "ENVIRONMENTS",
    "CapabilityState",
    "CarrierCredentialError",
    "CarrierCredentialNotConfigured",
    "CredentialBundle",
    "CredentialIdentity",
    "CredentialMeta",
    "CredentialStore",
    "DpapiCredentialStore",
    "MemoryCredentialStore",
    "configure_credential_store",
    "configure_global_kill",
    "resolve_carrier_capability",
    "resolve_carrier_credentials",
]
