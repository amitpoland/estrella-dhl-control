"""Canonical carrier credential + capability resolvers.

Adapters consume CredentialBundle. Coordinator must not learn vendor key names.

Production call (store=None):
  migrated identity → process store ONLY
  else → legacy Settings ONLY

Explicit store= (tests / DI) uses that store directly — never merges with Settings.
"""
from __future__ import annotations

from typing import Callable, Optional

from .exceptions import CarrierCredentialNotConfigured
from .migration import is_migrated, resolve_legacy_settings
from .models import CapabilityState, CredentialBundle, CredentialIdentity, CredentialMeta
from .store import CredentialStore

_STORE: Optional[CredentialStore] = None
_GLOBAL_KILL: Callable[[], bool] | None = None


def configure_credential_store(store: CredentialStore | None) -> None:
    global _STORE
    _STORE = store


def configure_global_kill(predicate: Callable[[], bool] | None) -> None:
    global _GLOBAL_KILL
    _GLOBAL_KILL = predicate


def get_credential_store() -> CredentialStore:
    if _STORE is None:
        raise CarrierCredentialNotConfigured("credential store not configured")
    return _STORE


def resolve_carrier_credentials(
    carrier: str,
    capability: str,
    environment: str,
    *,
    store: CredentialStore | None = None,
) -> CredentialBundle:
    identity = CredentialIdentity(
        carrier=carrier, environment=environment, capability=capability
    )
    if store is not None:
        return store.get_bundle(identity)
    if is_migrated(identity):
        return get_credential_store().get_bundle(identity)
    return resolve_legacy_settings(identity)


def resolve_carrier_capability(
    carrier: str,
    capability: str,
    environment: str,
    *,
    store: CredentialStore | None = None,
    global_kill: bool | None = None,
) -> CredentialMeta:
    identity = CredentialIdentity(
        carrier=carrier, environment=environment, capability=capability
    )
    if global_kill is None and _GLOBAL_KILL is not None:
        global_kill = bool(_GLOBAL_KILL())
    if global_kill:
        return CredentialMeta(
            identity=identity,
            configured=False,
            active=False,
            state=CapabilityState.BLOCKED_GLOBAL,
        )

    if store is not None:
        return store.get_meta(identity)

    if is_migrated(identity):
        try:
            return get_credential_store().get_meta(identity)
        except CarrierCredentialNotConfigured:
            return CredentialMeta(
                identity=identity,
                configured=False,
                active=False,
                state=CapabilityState.NOT_CONFIGURED,
            )

    try:
        resolve_legacy_settings(identity)
        return CredentialMeta(
            identity=identity,
            configured=True,
            active=True,
            state=CapabilityState.READY,
        )
    except CarrierCredentialNotConfigured:
        return CredentialMeta(
            identity=identity,
            configured=False,
            active=False,
            state=CapabilityState.NOT_CONFIGURED,
        )
