"""DPAPI-backed credential file store.

Layout under root (default production intent: C:\\PZ-secrets\\carriers):

  {carrier}/{environment}/{capability}.{A|B}   # DPAPI ciphertext
  {carrier}/{environment}/{capability}.active  # "A" or "B"
  {carrier}/{environment}/{capability}.meta.json  # safe metadata only

Never writes raw secrets to meta JSON or master_data.sqlite.
"""
from __future__ import annotations

import json
import logging
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Mapping

from .acl import assert_store_root_secure, atomic_write_bytes, harden_directory_acls
from .dpapi import protect, unprotect
from .exceptions import CarrierCredentialError, CarrierCredentialNotConfigured
from .models import CapabilityState, CredentialBundle, CredentialIdentity, CredentialMeta
from .store import (
    CredentialStore,
    fingerprint_fields,
    masked_suffix_from_fields,
    _utc_now,
)

log = logging.getLogger(__name__)

Validator = Callable[[CredentialIdentity, Mapping[str, str]], bool]


def _atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


class DpapiCredentialStore(CredentialStore):
    def __init__(
        self,
        root: Path | str,
        *,
        enforce_acl: bool = True,
        harden_on_init: bool = False,
    ) -> None:
        self._root = Path(root)
        self._lock = threading.RLock()
        self._enforce_acl = enforce_acl
        self._root.mkdir(parents=True, exist_ok=True)
        if harden_on_init:
            harden_directory_acls(self._root)
        if enforce_acl:
            assert_store_root_secure(self._root)

    def _dir(self, identity: CredentialIdentity) -> Path:
        # Identity components are enum-validated — no path traversal.
        return self._root / identity.carrier / identity.environment

    def _slot_path(self, identity: CredentialIdentity, slot: str) -> Path:
        return self._dir(identity) / f"{identity.capability}.{slot}"

    def _active_path(self, identity: CredentialIdentity) -> Path:
        return self._dir(identity) / f"{identity.capability}.active"

    def _meta_path(self, identity: CredentialIdentity) -> Path:
        return self._dir(identity) / f"{identity.capability}.meta.json"

    def _read_meta(self, identity: CredentialIdentity) -> dict[str, Any]:
        path = self._meta_path(identity)
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_meta(self, identity: CredentialIdentity, meta: dict[str, Any]) -> None:
        forbidden = {
            "api_key",
            "api_secret",
            "client_id",
            "client_secret",
            "password",
            "token",
            "secret",
            "fields",
            "plaintext",
        }
        clean = {k: v for k, v in meta.items() if k not in forbidden}
        _atomic_write_text(
            self._meta_path(identity), json.dumps(clean, indent=2, sort_keys=True)
        )

    def _read_active_slot(self, identity: CredentialIdentity) -> str | None:
        path = self._active_path(identity)
        if not path.is_file():
            return None
        slot = path.read_text(encoding="utf-8").strip().upper()
        return slot if slot in ("A", "B") else None

    def _load_slot_fields(self, identity: CredentialIdentity, slot: str) -> dict[str, str]:
        path = self._slot_path(identity, slot)
        if not path.is_file():
            raise CarrierCredentialNotConfigured(f"{identity.key}:{slot}")
        try:
            raw = unprotect(path.read_bytes())
        except CarrierCredentialError as exc:
            raise CarrierCredentialError("undecryptable credential") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CarrierCredentialError("corrupt sealed credential payload") from exc
        if (
            payload.get("carrier") != identity.carrier
            or payload.get("environment") != identity.environment
            or payload.get("capability") != identity.capability
        ):
            raise CarrierCredentialError("credential identity mismatch")
        fields = payload.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise CarrierCredentialError("sealed credential missing fields")
        return {str(k): str(v) for k, v in fields.items()}

    def get_bundle(self, identity: CredentialIdentity) -> CredentialBundle:
        with self._lock:
            if self._enforce_acl:
                assert_store_root_secure(self._root)
            meta = self._read_meta(identity)
            if meta.get("disabled"):
                raise CarrierCredentialNotConfigured(identity.key)
            slot = self._read_active_slot(identity)
            if not slot:
                raise CarrierCredentialNotConfigured(identity.key)
            fields = self._load_slot_fields(identity, slot)
            return CredentialBundle(
                identity=identity,
                fields=deepcopy(fields),
                fingerprint=meta.get("fingerprint") or fingerprint_fields(fields),
                slot=slot,
            )

    def get_meta(self, identity: CredentialIdentity) -> CredentialMeta:
        with self._lock:
            meta = self._read_meta(identity)
            if meta.get("not_provisioned"):
                return CredentialMeta(
                    identity=identity,
                    configured=False,
                    active=False,
                    state=CapabilityState.NOT_PROVISIONED,
                    updated_by=meta.get("updated_by"),
                )
            if meta.get("disabled"):
                return CredentialMeta(
                    identity=identity,
                    configured=bool(meta.get("fingerprint")),
                    active=False,
                    state=CapabilityState.DISABLED,
                    fingerprint=meta.get("fingerprint"),
                    masked_suffix=meta.get("masked_suffix"),
                    last_validated_at=meta.get("last_validated_at"),
                    last_rotated_at=meta.get("last_rotated_at"),
                    updated_by=meta.get("updated_by"),
                )
            if meta.get("stored_unvalidated") and meta.get("candidate_slot"):
                return CredentialMeta(
                    identity=identity,
                    configured=bool(self._read_active_slot(identity)),
                    active=bool(self._read_active_slot(identity)),
                    fingerprint=meta.get("fingerprint"),
                    masked_suffix=meta.get("masked_suffix"),
                    last_validated_at=meta.get("last_validated_at"),
                    last_rotated_at=meta.get("last_rotated_at"),
                    updated_by=meta.get("updated_by"),
                    state=CapabilityState.STORED_UNVALIDATED,
                )
            slot = self._read_active_slot(identity)
            if not slot or not self._slot_path(identity, slot).is_file():
                return CredentialMeta(
                    identity=identity,
                    configured=False,
                    active=False,
                    state=CapabilityState.NOT_CONFIGURED,
                    updated_by=meta.get("updated_by"),
                )
            return CredentialMeta(
                identity=identity,
                configured=True,
                active=True,
                fingerprint=meta.get("fingerprint"),
                masked_suffix=meta.get("masked_suffix"),
                last_validated_at=meta.get("last_validated_at"),
                last_rotated_at=meta.get("last_rotated_at"),
                updated_by=meta.get("updated_by"),
                state=CapabilityState.READY,
            )

    def put_candidate(
        self,
        identity: CredentialIdentity,
        fields: Mapping[str, str],
        *,
        updated_by: str,
    ) -> str:
        clean = {str(k): str(v) for k, v in fields.items() if v is not None and str(v) != ""}
        if not clean:
            raise CarrierCredentialError("empty credential fields")
        with self._lock:
            if self._enforce_acl:
                assert_store_root_secure(self._root)
            active = self._read_active_slot(identity)
            slot = "B" if active == "A" else "A"
            payload = {
                "version": 1,
                "carrier": identity.carrier,
                "environment": identity.environment,
                "capability": identity.capability,
                "slot": slot,
                "fields": clean,
            }
            sealed = protect(
                json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                description=f"pz-carrier:{identity.key}:{slot}",
            )
            atomic_write_bytes(self._slot_path(identity, slot), sealed)
            meta = self._read_meta(identity)
            meta["updated_by"] = updated_by
            meta["candidate_slot"] = slot
            meta["candidate_fingerprint"] = fingerprint_fields(clean)
            meta["candidate_masked_suffix"] = masked_suffix_from_fields(clean)
            meta["not_provisioned"] = False
            meta["stored_unvalidated"] = True
            self._write_meta(identity, meta)
            return slot

    def mark_stored_unvalidated(
        self, identity: CredentialIdentity, *, updated_by: str
    ) -> CredentialMeta:
        with self._lock:
            meta = self._read_meta(identity)
            meta["stored_unvalidated"] = True
            meta["updated_by"] = updated_by
            self._write_meta(identity, meta)
            return self.get_meta(identity)

    def mark_validated(self, identity: CredentialIdentity, slot: str) -> None:
        with self._lock:
            if not self._slot_path(identity, slot).is_file():
                raise CarrierCredentialNotConfigured(f"{identity.key}:{slot}")
            meta = self._read_meta(identity)
            meta["last_validated_at"] = _utc_now()
            meta["validated_slot"] = slot
            meta["stored_unvalidated"] = False
            self._write_meta(identity, meta)

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
        if not validated:
            raise CarrierCredentialError("refusing to activate unvalidated credential")
        with self._lock:
            if not self._slot_path(identity, slot).is_file():
                raise CarrierCredentialNotConfigured(f"{identity.key}:{slot}")
            fields = self._load_slot_fields(identity, slot)
            _atomic_write_text(self._active_path(identity), slot)
            other = "B" if slot == "A" else "A"
            other_path = self._slot_path(identity, other)
            if other_path.is_file():
                try:
                    other_path.unlink()
                except OSError:
                    pass
            meta = {
                "fingerprint": fingerprint_fields(fields),
                "masked_suffix": masked_suffix_from_fields(fields),
                "last_validated_at": _utc_now(),
                "last_rotated_at": _utc_now(),
                "updated_by": updated_by,
                "active_slot": slot,
                "disabled": False,
                "not_provisioned": False,
                "stored_unvalidated": False,
                "credential_reference": identity.key,
            }
            self._write_meta(identity, meta)
            return self.get_meta(identity)

    def rotate_atomic(
        self,
        identity: CredentialIdentity,
        new_fields: Mapping[str, str],
        *,
        updated_by: str,
        validate: Validator,
    ) -> CredentialMeta:
        """Hold one lock across put → load-from-disk → validate → activate."""
        with self._lock:
            if self._enforce_acl:
                assert_store_root_secure(self._root)
            # Inline put without releasing lock
            clean = {
                str(k): str(v)
                for k, v in new_fields.items()
                if v is not None and str(v) != ""
            }
            if not clean:
                raise CarrierCredentialError("empty credential fields")
            active = self._read_active_slot(identity)
            slot = "B" if active == "A" else "A"
            payload = {
                "version": 1,
                "carrier": identity.carrier,
                "environment": identity.environment,
                "capability": identity.capability,
                "slot": slot,
                "fields": clean,
            }
            sealed = protect(
                json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                description=f"pz-carrier:{identity.key}:{slot}",
            )
            atomic_write_bytes(self._slot_path(identity, slot), sealed)
            # Validate fields loaded from disk (not caller dict alone)
            loaded = self._load_slot_fields(identity, slot)
            try:
                ok = bool(validate(identity, loaded))
            except Exception:
                log.warning("credential validate raised identity=%s", identity.key)
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
            meta = self._read_meta(identity)
            meta["disabled"] = True
            meta["updated_by"] = updated_by
            self._write_meta(identity, meta)
            return self.get_meta(identity)

    def set_not_provisioned(
        self, identity: CredentialIdentity, *, updated_by: str, value: bool = True
    ) -> CredentialMeta:
        with self._lock:
            meta = self._read_meta(identity)
            meta["not_provisioned"] = value
            meta["updated_by"] = updated_by
            self._write_meta(identity, meta)
            return self.get_meta(identity)

    def list_metas(self) -> list[CredentialMeta]:
        """Walk store for masked metadata (no decrypt)."""
        out: list[CredentialMeta] = []
        if not self._root.is_dir():
            return out
        for carrier_dir in sorted(self._root.iterdir()):
            if not carrier_dir.is_dir() or carrier_dir.name not in ("dhl", "fedex", "ups"):
                continue
            for env_dir in sorted(carrier_dir.iterdir()):
                if not env_dir.is_dir():
                    continue
                for meta_path in sorted(env_dir.glob("*.meta.json")):
                    cap = meta_path.name[: -len(".meta.json")]
                    try:
                        identity = CredentialIdentity(
                            carrier_dir.name, env_dir.name, cap
                        )
                    except ValueError:
                        continue
                    out.append(self.get_meta(identity))
        return out
