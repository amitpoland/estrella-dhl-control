"""Credential store interfaces.

Production: DPAPI-sealed files under C:\\PZ-secrets\\carriers\\
Tests: MemoryCredentialStore
"""
from __future__ import annotations

import hashlib
import json
import threading
from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Mapping

from .exceptions import CarrierCredentialError, CarrierCredentialNotConfigured
from .models import CapabilityState, CredentialBundle, CredentialIdentity, CredentialMeta


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def fingerprint_fields(fields: Mapping[str, str]) -> str:
    """Stable non-reversible fingerprint for status APIs."""
    payload = json.dumps({k: fields[k] for k in sorted(fields)}, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def masked_suffix_from_fields(fields: Mapping[str, str]) -> str | None:
    for key in ("api_secret", "client_secret", "secret", "password"):
        val = fields.get(key)
        if val and len(val) >= 4:
            return val[-4:]
    for val in fields.values():
        if val and len(val) >= 4:
            return val[-4:]
    return None


@dataclass
class _SlotRecord:
    fields: dict[str, str]
    fingerprint: str
    masked_suffix: str | None
    created_at: str
    validated_at: str | None = None


@dataclass
class _IdentityRecord:
    active_slot: str | None = None  # "A" | "B" | None
    slots: dict[str, _SlotRecord] = field(default_factory=dict)
    disabled: bool = False
    not_provisioned: bool = False
    stored_unvalidated: bool = False
    updated_by: str | None = None
    last_rotated_at: str | None = None


class CredentialStore(ABC):
    @abstractmethod
    def get_bundle(self, identity: CredentialIdentity) -> CredentialBundle:
        ...

    @abstractmethod
    def get_meta(self, identity: CredentialIdentity) -> CredentialMeta:
        ...

    @abstractmethod
    def put_candidate(
        self,
        identity: CredentialIdentity,
        fields: Mapping[str, str],
        *,
        updated_by: str,
    ) -> str:
        """Write inactive candidate slot; return slot id ('A'|'B'). Does not activate."""

    @abstractmethod
    def activate_slot(
        self,
        identity: CredentialIdentity,
        slot: str,
        *,
        updated_by: str,
        validated: bool,
    ) -> CredentialMeta:
        """Activate slot after successful validation. Retires the other slot."""

    @abstractmethod
    def mark_validated(self, identity: CredentialIdentity, slot: str) -> None:
        ...

    @abstractmethod
    def disable(self, identity: CredentialIdentity, *, updated_by: str) -> CredentialMeta:
        ...

    @abstractmethod
    def set_not_provisioned(
        self, identity: CredentialIdentity, *, updated_by: str, value: bool = True
    ) -> CredentialMeta:
        ...


class MemoryCredentialStore(CredentialStore):
    """In-process store for tests and local dry-runs. Never used for production secrets."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, _IdentityRecord] = {}

    def _rec(self, identity: CredentialIdentity) -> _IdentityRecord:
        key = identity.key
        if key not in self._records:
            self._records[key] = _IdentityRecord()
        return self._records[key]

    def get_bundle(self, identity: CredentialIdentity) -> CredentialBundle:
        with self._lock:
            rec = self._records.get(identity.key)
            if rec is None or rec.disabled or not rec.active_slot:
                raise CarrierCredentialNotConfigured(identity.key)
            slot = rec.active_slot
            data = rec.slots.get(slot)
            if data is None:
                raise CarrierCredentialNotConfigured(identity.key)
            return CredentialBundle(
                identity=identity,
                fields=deepcopy(data.fields),
                fingerprint=data.fingerprint,
                slot=slot,
            )

    def get_meta(self, identity: CredentialIdentity) -> CredentialMeta:
        with self._lock:
            rec = self._records.get(identity.key)
            if rec is None:
                return CredentialMeta(
                    identity=identity,
                    configured=False,
                    active=False,
                    state=CapabilityState.NOT_CONFIGURED,
                )
            if rec.not_provisioned:
                return CredentialMeta(
                    identity=identity,
                    configured=False,
                    active=False,
                    state=CapabilityState.NOT_PROVISIONED,
                    updated_by=rec.updated_by,
                )
            if rec.disabled:
                return CredentialMeta(
                    identity=identity,
                    configured=bool(rec.slots),
                    active=False,
                    state=CapabilityState.DISABLED,
                    updated_by=rec.updated_by,
                    last_rotated_at=rec.last_rotated_at,
                )
            if rec.stored_unvalidated:
                active = bool(rec.active_slot and rec.active_slot in rec.slots)
                data = rec.slots.get(rec.active_slot) if active else None
                return CredentialMeta(
                    identity=identity,
                    configured=active,
                    active=active,
                    fingerprint=data.fingerprint if data else None,
                    masked_suffix=data.masked_suffix if data else None,
                    last_validated_at=data.validated_at if data else None,
                    last_rotated_at=rec.last_rotated_at,
                    updated_by=rec.updated_by,
                    state=CapabilityState.STORED_UNVALIDATED,
                )
            if not rec.active_slot or rec.active_slot not in rec.slots:
                return CredentialMeta(
                    identity=identity,
                    configured=False,
                    active=False,
                    state=CapabilityState.NOT_CONFIGURED,
                    updated_by=rec.updated_by,
                )
            data = rec.slots[rec.active_slot]
            return CredentialMeta(
                identity=identity,
                configured=True,
                active=True,
                fingerprint=data.fingerprint,
                masked_suffix=data.masked_suffix,
                last_validated_at=data.validated_at,
                last_rotated_at=rec.last_rotated_at,
                updated_by=rec.updated_by,
                state=CapabilityState.READY,
            )

    def put_candidate(
        self,
        identity: CredentialIdentity,
        fields: Mapping[str, str],
        *,
        updated_by: str,
    ) -> str:
        if not fields:
            raise CarrierCredentialError("empty credential fields")
        clean = {str(k): str(v) for k, v in fields.items() if v is not None and str(v) != ""}
        if not clean:
            raise CarrierCredentialError("empty credential fields")
        with self._lock:
            rec = self._rec(identity)
            # Write into the inactive slot; never overwrite active until activate_slot.
            if rec.active_slot == "A":
                slot = "B"
            else:
                slot = "A"
            rec.slots[slot] = _SlotRecord(
                fields=clean,
                fingerprint=fingerprint_fields(clean),
                masked_suffix=masked_suffix_from_fields(clean),
                created_at=_utc_now(),
            )
            rec.updated_by = updated_by
            rec.not_provisioned = False
            rec.stored_unvalidated = True
            return slot

    def mark_stored_unvalidated(
        self, identity: CredentialIdentity, *, updated_by: str
    ) -> CredentialMeta:
        with self._lock:
            rec = self._rec(identity)
            rec.stored_unvalidated = True
            rec.updated_by = updated_by
            return self.get_meta(identity)

    def mark_validated(self, identity: CredentialIdentity, slot: str) -> None:
        with self._lock:
            rec = self._records.get(identity.key)
            if rec is None or slot not in rec.slots:
                raise CarrierCredentialNotConfigured(identity.key)
            rec.slots[slot].validated_at = _utc_now()

    def activate_slot(
        self,
        identity: CredentialIdentity,
        slot: str,
        *,
        updated_by: str,
        validated: bool,
    ) -> CredentialMeta:
        if slot not in ("A", "B"):
            raise CarrierCredentialError(f"invalid slot: {slot!r}")
        with self._lock:
            rec = self._rec(identity)
            if slot not in rec.slots:
                raise CarrierCredentialNotConfigured(f"{identity.key}:{slot}")
            if not validated:
                raise CarrierCredentialError("refusing to activate unvalidated credential")
            other = "B" if slot == "A" else "A"
            rec.active_slot = slot
            rec.slots.pop(other, None)  # retire previous after successful activate
            rec.disabled = False
            rec.not_provisioned = False
            rec.stored_unvalidated = False
            rec.updated_by = updated_by
            rec.last_rotated_at = _utc_now()
            rec.slots[slot].validated_at = rec.slots[slot].validated_at or _utc_now()
            return self.get_meta(identity)

    def rotate_atomic(
        self,
        identity: CredentialIdentity,
        new_fields: Mapping[str, str],
        *,
        updated_by: str,
        validate: Callable[[CredentialIdentity, Mapping[str, str]], bool],
    ) -> CredentialMeta:
        with self._lock:
            slot = self.put_candidate(identity, new_fields, updated_by=updated_by)
            loaded = dict(self._records[identity.key].slots[slot].fields)
            try:
                ok = bool(validate(identity, loaded))
            except Exception:
                raise CarrierCredentialError(
                    "validation failed; previous credential preserved"
                ) from None
            if not ok:
                raise CarrierCredentialError(
                    "validation failed; previous credential preserved"
                )
            return self.activate_slot(
                identity, slot, updated_by=updated_by, validated=True
            )

    def disable(self, identity: CredentialIdentity, *, updated_by: str) -> CredentialMeta:
        with self._lock:
            rec = self._rec(identity)
            rec.disabled = True
            rec.updated_by = updated_by
            return self.get_meta(identity)

    def set_not_provisioned(
        self, identity: CredentialIdentity, *, updated_by: str, value: bool = True
    ) -> CredentialMeta:
        with self._lock:
            rec = self._rec(identity)
            rec.not_provisioned = value
            rec.updated_by = updated_by
            return self.get_meta(identity)
