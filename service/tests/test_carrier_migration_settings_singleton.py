"""Track migration: live Settings singleton, parser, no dual-truth, rollback."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core import config as cfg
from app.services.carrier.credentials import (
    CarrierCredentialNotConfigured,
    CredentialIdentity,
    MemoryCredentialStore,
    configure_credential_store,
    resolve_carrier_credentials,
)
from app.services.carrier.credentials.migration import (
    configure_migrated_identities,
    is_migrated,
    migrated_identity_keys,
)


TRACK = CredentialIdentity("dhl", "production", "track")
SHIP = CredentialIdentity("dhl", "production", "ship")


@pytest.fixture(autouse=True)
def _reset():
    configure_migrated_identities(None)
    configure_credential_store(None)
    yield
    configure_migrated_identities(None)
    configure_credential_store(None)


def test_parser_canonical_track_identity(monkeypatch):
    monkeypatch.setattr(
        cfg,
        "settings",
        SimpleNamespace(carrier_credential_migrated="dhl/production/track"),
    )
    assert migrated_identity_keys() == frozenset({"dhl/production/track"})
    assert is_migrated(TRACK) is True
    assert is_migrated(SHIP) is False


def test_fresh_settings_singleton_after_reload(monkeypatch):
    """STALE_SETTINGS_INSTANCE: helpers must read cfg.settings, not a bound import."""
    stale = SimpleNamespace(carrier_credential_migrated="")
    monkeypatch.setattr(cfg, "settings", stale)
    assert is_migrated(TRACK) is False

    monkeypatch.setattr(
        cfg,
        "settings",
        SimpleNamespace(carrier_credential_migrated="dhl/production/track"),
    )
    assert cfg.settings is not stale
    assert is_migrated(TRACK) is True


def test_migrated_track_ignores_poisoned_env(monkeypatch):
    store = MemoryCredentialStore()
    slot = store.put_candidate(
        TRACK, {"api_key": "STORE-TRACK", "api_secret": "SSEC"}, updated_by="t"
    )
    store.activate_slot(TRACK, slot, updated_by="t", validated=True)
    configure_credential_store(store)
    configure_migrated_identities(frozenset({"dhl/production/track"}))
    monkeypatch.setattr(cfg.settings, "dhl_tracking_api_key", "ENV-TRACK")
    monkeypatch.setattr(cfg.settings, "dhl_tracking_api_secret", "ENV-SEC")
    bundle = resolve_carrier_credentials("dhl", "track", "production")
    assert bundle.fields["api_key"] == "STORE-TRACK"


def test_unmigrated_track_uses_legacy_settings(monkeypatch):
    store = MemoryCredentialStore()
    slot = store.put_candidate(
        TRACK, {"api_key": "STORE-TRACK", "api_secret": "SSEC"}, updated_by="t"
    )
    store.activate_slot(TRACK, slot, updated_by="t", validated=True)
    configure_credential_store(store)
    configure_migrated_identities(frozenset())
    monkeypatch.setattr(cfg.settings, "dhl_tracking_api_key", "ENV-TRACK")
    monkeypatch.setattr(cfg.settings, "dhl_tracking_api_secret", "")
    bundle = resolve_carrier_credentials("dhl", "track", "production")
    assert bundle.fields["api_key"] == "ENV-TRACK"


def test_rollback_removes_only_track_identity(monkeypatch):
    configure_migrated_identities(frozenset({"dhl/production/track", "dhl/production/ship"}))
    assert is_migrated(TRACK) is True
    configure_migrated_identities(frozenset({"dhl/production/ship"}))
    assert is_migrated(TRACK) is False
    assert is_migrated(SHIP) is True


def test_no_vault_then_env_fallback(monkeypatch):
    configure_migrated_identities(frozenset({"dhl/production/track"}))
    configure_credential_store(MemoryCredentialStore())
    monkeypatch.setattr(cfg.settings, "dhl_tracking_api_key", "ENV-SHOULD-NOT-WIN")
    with pytest.raises(CarrierCredentialNotConfigured):
        resolve_carrier_credentials("dhl", "track", "production")
