"""Application credential service — sole owner of store I/O for routes/adapters.

Routes and adapters must not open DPAPI files directly.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Callable, Mapping, Optional

from .exceptions import CarrierCredentialError, CarrierCredentialNotConfigured
from .models import CapabilityState, CredentialBundle, CredentialIdentity, CredentialMeta
from .resolver import get_credential_store, resolve_carrier_capability, resolve_carrier_credentials
from .rotation import rotate_credentials
from .store import CredentialStore

log = logging.getLogger(__name__)

Validator = Callable[[CredentialIdentity, Mapping[str, str]], bool]


def _actor(user: Optional[dict]) -> str:
    if not user:
        return "unknown"
    return str(user.get("email") or user.get("username") or user.get("id") or "admin")


def meta_to_public(meta: CredentialMeta) -> dict[str, Any]:
    """Masked projection safe for GET / audit."""
    return {
        "carrier": meta.identity.carrier,
        "environment": meta.identity.environment,
        "capability": meta.identity.capability,
        "credential_reference": meta.identity.key,
        "configured": meta.configured,
        "active": meta.active,
        "state": meta.state.value if isinstance(meta.state, CapabilityState) else str(meta.state),
        "masked_identifier": meta.masked_suffix,
        "fingerprint": meta.fingerprint,
        "last_validated_at": meta.last_validated_at,
        "last_rotated_at": meta.last_rotated_at,
        "updated_by": meta.updated_by,
    }


def audit_credential_event(
    action: str,
    meta: CredentialMeta,
    *,
    actor: str,
    validation_result: Optional[str] = None,
) -> dict[str, Any]:
    """Safe audit payload — never includes raw secrets."""
    payload = {
        "carrier": meta.identity.carrier,
        "capability": meta.identity.capability,
        "environment": meta.identity.environment,
        "action": action,
        "actor": actor,
        "credential_reference": meta.identity.key,
        "fingerprint": meta.fingerprint,
        "masked_identifier": meta.masked_suffix,
        "state": meta.state.value if isinstance(meta.state, CapabilityState) else str(meta.state),
    }
    if validation_result is not None:
        payload["validation_result"] = validation_result
    return payload


class CarrierCredentialService:
    def __init__(self, store: Optional[CredentialStore] = None) -> None:
        self._store = store

    @property
    def store(self) -> CredentialStore:
        return self._store or get_credential_store()

    def status(
        self, carrier: str, capability: str, environment: str
    ) -> dict[str, Any]:
        meta = resolve_carrier_capability(
            carrier, capability, environment, store=self.store
        )
        return meta_to_public(meta)

    def list_status(self) -> list[dict[str, Any]]:
        listing = getattr(self.store, "list_metas", None)
        if callable(listing):
            return [meta_to_public(m) for m in listing()]
        return []

    def store_candidate(
        self,
        carrier: str,
        capability: str,
        environment: str,
        fields: Mapping[str, str],
        *,
        user: Optional[dict],
    ) -> dict[str, Any]:
        identity = CredentialIdentity(carrier, environment, capability)
        self.store.put_candidate(identity, fields, updated_by=_actor(user))
        if hasattr(self.store, "mark_stored_unvalidated"):
            meta = self.store.mark_stored_unvalidated(identity, updated_by=_actor(user))
        else:
            meta = self.store.get_meta(identity)
            meta = CredentialMeta(
                identity=identity,
                configured=meta.configured,
                active=meta.active,
                fingerprint=meta.fingerprint,
                masked_suffix=meta.masked_suffix,
                last_validated_at=meta.last_validated_at,
                last_rotated_at=meta.last_rotated_at,
                updated_by=_actor(user),
                state=CapabilityState.STORED_UNVALIDATED,
            )
        log.info(
            "carrier_credential_candidate_stored ref=%s actor=%s",
            identity.key,
            _actor(user),
        )
        return meta_to_public(meta)

    def rotate(
        self,
        carrier: str,
        capability: str,
        environment: str,
        fields: Mapping[str, str],
        *,
        user: Optional[dict],
        validate: Optional[Validator] = None,
    ) -> dict[str, Any]:
        identity = CredentialIdentity(carrier, environment, capability)
        meta = rotate_credentials(
            self.store,
            identity,
            fields,
            updated_by=_actor(user),
            validate=validate,
        )
        result = "pass" if meta.state == CapabilityState.READY else meta.state.value
        log.info(
            "carrier_credential_rotate ref=%s actor=%s result=%s",
            identity.key,
            _actor(user),
            result,
        )
        return meta_to_public(meta)

    def activate_validated(
        self,
        carrier: str,
        capability: str,
        environment: str,
        slot: str,
        *,
        user: Optional[dict],
    ) -> dict[str, Any]:
        """Activate only after mark_validated — never for unvalidated candidates."""
        identity = CredentialIdentity(carrier, environment, capability)
        meta = self.store.get_meta(identity)
        if meta.state == CapabilityState.STORED_UNVALIDATED:
            raise CarrierCredentialError(
                "refusing to activate unvalidated credential; run validate first"
            )
        meta = self.store.activate_slot(
            identity, slot, updated_by=_actor(user), validated=True
        )
        return meta_to_public(meta)

    def disable(
        self,
        carrier: str,
        capability: str,
        environment: str,
        *,
        user: Optional[dict],
    ) -> dict[str, Any]:
        identity = CredentialIdentity(carrier, environment, capability)
        meta = self.store.disable(identity, updated_by=_actor(user))
        log.info(
            "carrier_credential_disabled ref=%s actor=%s",
            identity.key,
            _actor(user),
        )
        return meta_to_public(meta)

    def resolve_runtime(
        self, carrier: str, capability: str, environment: str
    ) -> CredentialBundle:
        return resolve_carrier_credentials(
            carrier, capability, environment, store=self.store
        )
