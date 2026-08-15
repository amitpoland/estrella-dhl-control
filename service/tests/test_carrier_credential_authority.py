"""Authority tests for Carrier Master credential resolvers (Release B).

Proves: one resolver, migration bridge (no dual-truth), rotation preserves A,
per-carrier isolation, no plaintext in meta, logistics lacks credentials.write.
"""
from __future__ import annotations

import pytest

from app.auth.permissions import (
    PERMISSION_CATALOGUE,
    has_permission,
    permissions_for_role,
)
from app.services.carrier.credentials import (
    CapabilityState,
    CarrierCredentialNotConfigured,
    CredentialIdentity,
    MemoryCredentialStore,
    configure_credential_store,
    resolve_carrier_capability,
    resolve_carrier_credentials,
)
from app.services.carrier.credentials.migration import configure_migrated_identities
from app.services.carrier.credentials.rotation import rotate_credentials

_ALL_TEST_IDS = frozenset(
    {
        "dhl/production/ship",
        "dhl/production/track",
        "dhl/production/epod",
        "dhl/production/documents",
        "fedex/sandbox/ship_rate",
        "ups/production/ship",
    }
)


@pytest.fixture()
def store():
    s = MemoryCredentialStore()
    configure_credential_store(s)
    configure_migrated_identities(_ALL_TEST_IDS)
    yield s
    configure_credential_store(None)
    configure_migrated_identities(None)


def test_permissions_catalogue_includes_credential_verbs():
    assert "carriers.credentials.write" in PERMISSION_CATALOGUE
    assert "carriers.credentials.view" in PERMISSION_CATALOGUE


def test_logistics_cannot_mutate_credentials():
    perms = permissions_for_role("logistics")
    assert "carriers.edit" in perms
    assert "carriers.credentials.write" not in perms
    assert not has_permission("logistics", "carriers.credentials.write")


def test_admin_can_mutate_credentials():
    assert has_permission("admin", "carriers.credentials.write")
    assert has_permission("admin", "carriers.credentials.view")


def test_master_admin_lacks_credential_write_by_default():
    assert "carriers.credentials.write" not in permissions_for_role("master_admin")


def test_resolve_not_configured_fail_closed(store):
    meta = resolve_carrier_capability("dhl", "ship", "production", store=store)
    assert meta.state == CapabilityState.NOT_CONFIGURED
    with pytest.raises(CarrierCredentialNotConfigured):
        resolve_carrier_credentials("dhl", "ship", "production", store=store)


def test_dhl_ready_does_not_imply_fedex(store):
    identity = CredentialIdentity("dhl", "production", "ship")
    slot = store.put_candidate(
        identity, {"api_key": "k1", "api_secret": "s1secret"}, updated_by="admin"
    )
    store.activate_slot(identity, slot, updated_by="admin", validated=True)

    dhl = resolve_carrier_capability("dhl", "ship", "production", store=store)
    fedex = resolve_carrier_capability("fedex", "ship_rate", "sandbox", store=store)
    assert dhl.state == CapabilityState.READY
    assert fedex.state == CapabilityState.NOT_CONFIGURED


def test_disable_fedex_leaves_dhl(store):
    dhl_id = CredentialIdentity("dhl", "production", "ship")
    fx_id = CredentialIdentity("fedex", "sandbox", "ship_rate")
    for ident, fields in (
        (dhl_id, {"api_key": "dk", "api_secret": "dsxxxx"}),
        (fx_id, {"client_id": "fi", "client_secret": "fsxxxx"}),
    ):
        slot = store.put_candidate(ident, fields, updated_by="admin")
        store.activate_slot(ident, slot, updated_by="admin", validated=True)

    store.disable(fx_id, updated_by="admin")
    assert (
        resolve_carrier_capability("dhl", "ship", "production", store=store).state
        == CapabilityState.READY
    )
    assert (
        resolve_carrier_capability("fedex", "ship_rate", "sandbox", store=store).state
        == CapabilityState.DISABLED
    )


def test_global_kill_blocks_all_without_clearing_store(store):
    identity = CredentialIdentity("dhl", "production", "track")
    slot = store.put_candidate(
        identity, {"api_key": "tk", "api_secret": "tsxxxx"}, updated_by="admin"
    )
    store.activate_slot(identity, slot, updated_by="admin", validated=True)

    meta = resolve_carrier_capability(
        "dhl", "track", "production", store=store, global_kill=True
    )
    assert meta.state == CapabilityState.BLOCKED_GLOBAL
    assert (
        resolve_carrier_capability(
            "dhl", "track", "production", store=store, global_kill=False
        ).state
        == CapabilityState.READY
    )


def test_meta_never_contains_raw_secrets(store):
    identity = CredentialIdentity("dhl", "production", "ship")
    secret = "super-secret-value-XYZ9"
    slot = store.put_candidate(
        identity, {"api_key": "key", "api_secret": secret}, updated_by="admin"
    )
    store.activate_slot(identity, slot, updated_by="admin", validated=True)
    meta = store.get_meta(identity)
    blob = repr(meta)
    assert secret not in blob
    assert "super-secret" not in blob
    assert meta.masked_suffix == "XYZ9"
    assert meta.fingerprint is not None


def test_failed_rotation_preserves_previous(store):
    identity = CredentialIdentity("dhl", "production", "epod")
    slot_a = store.put_candidate(
        identity, {"api_key": "AKEY", "api_secret": "ASECRET99"}, updated_by="admin"
    )
    store.activate_slot(identity, slot_a, updated_by="admin", validated=True)
    before = store.get_bundle(identity)

    with pytest.raises(Exception, match="previous credential preserved"):
        rotate_credentials(
            store,
            identity,
            {"api_key": "BKEY", "api_secret": "BSECRET88"},
            updated_by="admin",
            validate=lambda _i, _f: False,
        )

    after = store.get_bundle(identity)
    assert after.fields == before.fields
    assert after.fingerprint == before.fingerprint


def test_successful_rotation_activates_b(store):
    identity = CredentialIdentity("dhl", "production", "documents")
    slot_a = store.put_candidate(
        identity, {"api_key": "AKEY", "api_secret": "ASECRET99"}, updated_by="admin"
    )
    store.activate_slot(identity, slot_a, updated_by="admin", validated=True)

    meta = rotate_credentials(
        store,
        identity,
        {"api_key": "BKEY", "api_secret": "BSECRET88"},
        updated_by="admin",
        validate=lambda _i, _f: True,
    )
    assert meta.state == CapabilityState.READY
    bundle = store.get_bundle(identity)
    assert bundle.fields["api_key"] == "BKEY"
    assert bundle.slot == "B"


def test_rotate_without_validate_is_stored_unvalidated(store):
    identity = CredentialIdentity("dhl", "production", "ship")
    slot = store.put_candidate(
        identity, {"api_key": "A", "api_secret": "ASECRET99"}, updated_by="admin"
    )
    store.activate_slot(identity, slot, updated_by="admin", validated=True)
    meta = rotate_credentials(
        store,
        identity,
        {"api_key": "B", "api_secret": "BSECRET88"},
        updated_by="admin",
        validate=None,
    )
    assert meta.state == CapabilityState.STORED_UNVALIDATED
    assert store.get_bundle(identity).fields["api_key"] == "A"


def test_capability_sharing_is_explicit_separate_identities(store):
    ship = CredentialIdentity("dhl", "production", "ship")
    epod = CredentialIdentity("dhl", "production", "epod")
    fields = {"api_key": "k", "api_secret": "sxxxx"}
    for ident in (ship, epod):
        slot = store.put_candidate(ident, fields, updated_by="admin")
        store.activate_slot(ident, slot, updated_by="admin", validated=True)
    assert (
        resolve_carrier_credentials("dhl", "ship", "production", store=store).fields
        == fields
    )
    assert (
        resolve_carrier_credentials("dhl", "epod", "production", store=store).fields
        == fields
    )


def test_ups_not_configured_blocks_independently(store):
    meta = resolve_carrier_capability("ups", "ship", "production", store=store)
    assert meta.state == CapabilityState.NOT_CONFIGURED


def test_migration_bridge_no_dual_truth(store, monkeypatch):
    """Production path (store=None): migrated → process store; else → Settings."""
    configure_credential_store(store)
    configure_migrated_identities(frozenset({"dhl/production/ship"}))
    identity = CredentialIdentity("dhl", "production", "ship")
    slot = store.put_candidate(
        identity, {"api_key": "STORE", "api_secret": "STORESEC"}, updated_by="admin"
    )
    store.activate_slot(identity, slot, updated_by="admin", validated=True)

    from app.core.config import settings

    monkeypatch.setattr(settings, "dhl_express_api_key", "ENVKEY")
    monkeypatch.setattr(settings, "dhl_express_api_secret", "ENVSECRET")

    # No store kwarg → migration policy
    bundle = resolve_carrier_credentials("dhl", "ship", "production")
    assert bundle.fields["api_key"] == "STORE"

    track = CredentialIdentity("dhl", "production", "track")
    tslot = store.put_candidate(
        track, {"api_key": "TRACKSTORE", "api_secret": "TSEC"}, updated_by="admin"
    )
    store.activate_slot(track, tslot, updated_by="admin", validated=True)
    monkeypatch.setattr(settings, "dhl_tracking_api_key", "TRACKENV")
    monkeypatch.setattr(settings, "dhl_tracking_api_secret", "TRACKENVSEC")
    legacy = resolve_carrier_credentials("dhl", "track", "production")
    assert legacy.fields["api_key"] == "TRACKENV"
