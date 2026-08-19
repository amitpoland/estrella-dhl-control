"""Explicit migration bridge — no dual-truth credential lookup.

Policy:
  if identity is migrated → Carrier Master / DPAPI store ONLY (fail closed)
  else → legacy Settings (.env) ONLY (fail closed)

Never merges both sources.
"""
from __future__ import annotations

import os
from typing import FrozenSet, Optional

from .exceptions import CarrierCredentialNotConfigured
from .models import CredentialBundle, CredentialIdentity

# Process override for tests; production uses settings.carrier_credential_migrated.
_MIGRATED_OVERRIDE: Optional[FrozenSet[str]] = None


def configure_migrated_identities(keys: Optional[FrozenSet[str]]) -> None:
    global _MIGRATED_OVERRIDE
    _MIGRATED_OVERRIDE = keys


def migrated_identity_keys() -> FrozenSet[str]:
    if _MIGRATED_OVERRIDE is not None:
        return _MIGRATED_OVERRIDE
    # Always read the live Settings singleton. `from app.core.config import settings`
    # binds the object at import time; helpers that do `config.settings = Settings()`
    # after writing .env would otherwise leave is_migrated() on a stale instance.
    from app.core import config as cfg

    raw = (getattr(cfg.settings, "carrier_credential_migrated", None) or "").strip()
    if not raw:
        raw = os.environ.get("CARRIER_CREDENTIAL_MIGRATED", "").strip()
    if not raw:
        return frozenset()
    return frozenset(p.strip().lower() for p in raw.split(",") if p.strip())


def is_migrated(identity: CredentialIdentity) -> bool:
    return identity.key in migrated_identity_keys()


def resolve_legacy_settings(identity: CredentialIdentity) -> CredentialBundle:
    """Map neutral identity → Settings fields. Fail closed when absent."""
    from app.core import config as cfg

    live = cfg.settings
    fields: dict[str, str] = {}
    c, env, cap = identity.carrier, identity.environment, identity.capability

    if c == "dhl" and env == "production" and cap in ("ship", "epod", "documents"):
        key = (live.dhl_express_api_key or "").strip()
        secret = (live.dhl_express_api_secret or "").strip()
        if not key or not secret:
            raise CarrierCredentialNotConfigured(identity.key)
        fields = {"api_key": key, "api_secret": secret}
        acct = (live.dhl_express_account_number or "").strip()
        if acct:
            fields["account_number"] = acct
    elif c == "dhl" and env == "production" and cap == "track":
        key = (
            (live.dhl_tracking_api_key or "").strip()
            or (live.dhl_api_key or "").strip()
            or (os.environ.get("DHL_CLIENT_ID") or "").strip()
        )
        secret = (
            (live.dhl_tracking_api_secret or "").strip()
            or (os.environ.get("DHL_CLIENT_SECRET") or "").strip()
        )
        if not key:
            raise CarrierCredentialNotConfigured(identity.key)
        fields = {"api_key": key}
        if secret:
            fields["api_secret"] = secret
    elif c == "fedex" and cap in ("ship_rate", "track"):
        cid = (live.fedex_client_id or "").strip()
        csec = (live.fedex_client_secret or "").strip()
        if not cid or not csec:
            raise CarrierCredentialNotConfigured(identity.key)
        fields = {"client_id": cid, "client_secret": csec}
    elif c == "ups" and cap in ("ship", "ship_rate", "track"):
        cid = (live.ups_client_id or "").strip()
        csec = (live.ups_client_secret or "").strip()
        if not cid or not csec:
            raise CarrierCredentialNotConfigured(identity.key)
        fields = {"client_id": cid, "client_secret": csec}
    else:
        raise CarrierCredentialNotConfigured(identity.key)

    return CredentialBundle(identity=identity, fields=fields, fingerprint=None, slot=None)
