"""Safe credential rotation helper — never activates on failed validation."""
from __future__ import annotations

import logging
from typing import Callable, Mapping, Optional

from .exceptions import CarrierCredentialError
from .models import CapabilityState, CredentialIdentity, CredentialMeta
from .store import CredentialStore

log = logging.getLogger(__name__)

Validator = Callable[[CredentialIdentity, Mapping[str, str]], bool]


def rotate_credentials(
    store: CredentialStore,
    identity: CredentialIdentity,
    new_fields: Mapping[str, str],
    *,
    updated_by: str,
    validate: Optional[Validator] = None,
) -> CredentialMeta:
    """
    A active → store B as candidate → validate B → activate B or keep A.

    If ``validate`` is None, candidate is stored only (STORED_UNVALIDATED);
    active A is preserved. Never pretends validation succeeded.
    """
    if validate is None:
        store.put_candidate(identity, new_fields, updated_by=updated_by)
        if hasattr(store, "mark_stored_unvalidated"):
            return store.mark_stored_unvalidated(identity, updated_by=updated_by)  # type: ignore[attr-defined]
        meta = store.get_meta(identity)
        return CredentialMeta(
            identity=identity,
            configured=meta.configured,
            active=meta.active,
            fingerprint=meta.fingerprint,
            masked_suffix=meta.masked_suffix,
            last_validated_at=meta.last_validated_at,
            last_rotated_at=meta.last_rotated_at,
            updated_by=updated_by,
            state=CapabilityState.STORED_UNVALIDATED,
        )

    rotate_fn = getattr(store, "rotate_atomic", None)
    if callable(rotate_fn):
        try:
            return rotate_fn(
                identity, new_fields, updated_by=updated_by, validate=validate
            )
        except CarrierCredentialError:
            raise
        except Exception:
            log.warning(
                "credential rotation failed type=Exception identity=%s",
                identity.key,
            )
            raise CarrierCredentialError(
                "validation failed; previous credential preserved"
            ) from None

    slot = store.put_candidate(identity, new_fields, updated_by=updated_by)
    try:
        ok = bool(validate(identity, new_fields))
    except Exception:
        log.warning(
            "credential validation raised identity=%s",
            identity.key,
        )
        raise CarrierCredentialError(
            "validation failed; previous credential preserved"
        ) from None
    if not ok:
        raise CarrierCredentialError("validation failed; previous credential preserved")
    store.mark_validated(identity, slot)
    return store.activate_slot(identity, slot, updated_by=updated_by, validated=True)
