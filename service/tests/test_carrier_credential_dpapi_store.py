"""DPAPI file-store + ACL harden tests — Windows only."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.carrier.credentials.acl import atomic_write_bytes
from app.services.carrier.credentials.dpapi import dpapi_available, protect, unprotect
from app.services.carrier.credentials.file_store import DpapiCredentialStore
from app.services.carrier.credentials.models import CapabilityState, CredentialIdentity
from app.services.carrier.credentials.rotation import rotate_credentials

pytestmark = pytest.mark.skipif(not dpapi_available(), reason="DPAPI requires Windows")


def test_dpapi_roundtrip():
    pt = b'{"api_secret":"do-not-log"}'
    ct = protect(pt, description="pz-test")
    assert ct != pt
    assert b"do-not-log" not in ct
    assert unprotect(ct) == pt


def test_atomic_write_preserves_slot_suffix(tmp_path: Path):
    """Path.with_suffix('.tmp') would turn ship.A into ship.tmp — must not."""
    target = tmp_path / "ship.A"
    atomic_write_bytes(target, b"sealed")
    assert target.read_bytes() == b"sealed"
    assert not (tmp_path / "ship.tmp").exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_corrupt_payload_fails_closed(tmp_path: Path):
    store = DpapiCredentialStore(tmp_path / "carriers", enforce_acl=False)
    identity = CredentialIdentity("dhl", "production", "ship")
    slot = store.put_candidate(
        identity, {"api_key": "K", "api_secret": "Sxxxx"}, updated_by="admin"
    )
    store.activate_slot(identity, slot, updated_by="admin", validated=True)
    slot_path = tmp_path / "carriers" / "dhl" / "production" / f"ship.{slot}"
    slot_path.write_bytes(b"not-valid-dpapi")
    with pytest.raises(Exception, match="undecryptable|corrupt"):
        store.get_bundle(identity)


def test_file_store_seal_and_resolve(tmp_path: Path):
    store = DpapiCredentialStore(tmp_path / "carriers", enforce_acl=False)
    identity = CredentialIdentity("dhl", "production", "ship")
    secret = "live-secret-VALUE7"
    slot = store.put_candidate(
        identity, {"api_key": "KEY", "api_secret": secret}, updated_by="admin"
    )
    store.activate_slot(identity, slot, updated_by="admin", validated=True)

    bundle = store.get_bundle(identity)
    assert bundle.fields["api_secret"] == secret

    slot_file = tmp_path / "carriers" / "dhl" / "production" / f"ship.{bundle.slot}"
    raw = slot_file.read_bytes()
    assert secret.encode() not in raw

    meta_path = tmp_path / "carriers" / "dhl" / "production" / "ship.meta.json"
    meta_text = meta_path.read_text(encoding="utf-8")
    assert secret not in meta_text
    meta = json.loads(meta_text)
    assert "fields" not in meta
    assert meta.get("masked_suffix") == "LUE7"
    assert store.get_meta(identity).state == CapabilityState.READY


def test_failed_rotation_preserves_a_on_disk(tmp_path: Path):
    store = DpapiCredentialStore(tmp_path / "carriers", enforce_acl=False)
    identity = CredentialIdentity("dhl", "production", "track")
    slot = store.put_candidate(
        identity, {"api_key": "A", "api_secret": "ASECRET99"}, updated_by="admin"
    )
    store.activate_slot(identity, slot, updated_by="admin", validated=True)
    before = store.get_bundle(identity)

    with pytest.raises(Exception, match="previous credential preserved"):
        rotate_credentials(
            store,
            identity,
            {"api_key": "B", "api_secret": "BSECRET88"},
            updated_by="admin",
            validate=lambda _i, _f: False,
        )

    after = store.get_bundle(identity)
    assert after.fields == before.fields
