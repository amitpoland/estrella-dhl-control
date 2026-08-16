"""Resolver consumer wiring — unmigrated stays Settings-only; no DPAPI in consumers."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.carrier.credentials.consumer_bridge import (
    express_carrier_config_kwargs,
    resolve_dhl_secret_fields,
)
from app.services.carrier.credentials.migration import configure_migrated_identities
from app.services.carrier.credentials.store import MemoryCredentialStore
from app.services.carrier.credentials.resolver import configure_credential_store
from app.services.carrier.factory import CarrierConfig

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


@pytest.fixture(autouse=True)
def _reset_migration_and_store():
    configure_migrated_identities(frozenset())
    configure_credential_store(None)
    yield
    configure_migrated_identities(None)
    configure_credential_store(None)


def test_ship_config_uses_resolver_legacy_when_unmigrated(monkeypatch):
    monkeypatch.setattr(settings, "dhl_express_api_key", "ship-key")
    monkeypatch.setattr(settings, "dhl_express_api_secret", "ship-secret")
    monkeypatch.setattr(settings, "dhl_express_account_number", "ACCT")
    monkeypatch.setattr(settings, "carrier_api_status", "live")
    configure_migrated_identities(frozenset())
    kw = express_carrier_config_kwargs("ship")
    assert kw["api_key"] == "ship-key"
    assert kw["api_secret"] == "ship-secret"
    assert kw["account_number"] == "ACCT"


def test_ship_config_soft_miss_empty_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "dhl_express_api_key", "")
    monkeypatch.setattr(settings, "dhl_express_api_secret", "")
    configure_migrated_identities(frozenset())
    fields = resolve_dhl_secret_fields("ship")
    assert fields == {}


def test_unified_track_fields_from_tracking_settings(monkeypatch):
    monkeypatch.setattr(settings, "dhl_tracking_api_key", "trk-key")
    monkeypatch.setattr(settings, "dhl_tracking_api_secret", "")
    configure_migrated_identities(frozenset())
    fields = resolve_dhl_secret_fields("track")
    assert fields.get("api_key") == "trk-key"


def test_mydhl_uses_ship_identity_not_track(monkeypatch):
    monkeypatch.setattr(settings, "dhl_express_api_key", "express-k")
    monkeypatch.setattr(settings, "dhl_express_api_secret", "express-s")
    monkeypatch.setattr(settings, "dhl_tracking_api_key", "unified-only")
    configure_migrated_identities(frozenset())
    ship = resolve_dhl_secret_fields("ship")
    track = resolve_dhl_secret_fields("track")
    assert ship.get("api_key") == "express-k"
    assert track.get("api_key") == "unified-only"


def test_epod_and_documents_share_express_legacy_map(monkeypatch):
    monkeypatch.setattr(settings, "dhl_express_api_key", "k")
    monkeypatch.setattr(settings, "dhl_express_api_secret", "s")
    monkeypatch.setattr(settings, "carrier_api_status", "live")
    configure_migrated_identities(frozenset())
    epod = express_carrier_config_kwargs("epod")
    docs = express_carrier_config_kwargs("documents")
    assert epod["api_key"] == docs["api_key"] == "k"
    assert isinstance(CarrierConfig(**epod), CarrierConfig)


def test_consumers_no_dual_lookup_when_store_seeded_unmigrated(monkeypatch):
    """Store has different secrets but migrated empty → Settings wins."""
    from app.services.carrier.credentials.models import CredentialIdentity
    from app.services.carrier.credentials.store import fingerprint_fields

    monkeypatch.setattr(settings, "dhl_express_api_key", "settings-key")
    monkeypatch.setattr(settings, "dhl_express_api_secret", "settings-sec")
    store = MemoryCredentialStore()
    identity = CredentialIdentity("dhl", "production", "ship")
    store.put_candidate(
        identity,
        {"api_key": "store-key", "api_secret": "store-sec"},
        updated_by="test",
    )
    # Activate without external validate path used in Memory store tests:
    meta = store.activate_slot(identity, "A", updated_by="test", validated=True)
    assert meta.configured
    configure_credential_store(store)
    configure_migrated_identities(frozenset())
    fields = resolve_dhl_secret_fields("ship")
    assert fields.get("api_key") == "settings-key"
    assert fields.get("api_key") != "store-key"


def test_consumers_do_not_import_dpapi():
    paths = [
        APP / "services" / "carrier" / "credentials" / "consumer_bridge.py",
        APP / "api" / "routes_carrier_actions.py",
        APP / "services" / "carrier" / "epod_service.py",
        APP / "services" / "carrier" / "document_image_service.py",
        APP / "services" / "tracking_service.py",
    ]
    forbidden = ("credentials.dpapi", "credentials.file_store", "from .dpapi", "from .file_store")
    for path in paths:
        src = path.read_text(encoding="utf-8")
        # consumer_bridge and consumers must not import dpapi/file_store
        if path.name == "consumer_bridge.py":
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert "dpapi" not in node.module
                    assert "file_store" not in node.module
        for token in forbidden:
            if path.name == "tracking_service.py" and "credentials.consumer_bridge" in src:
                assert "credentials.dpapi" not in src
                assert "credentials.file_store" not in src
                break
            assert token not in src, f"{path.name} must not reference {token}"


def test_awb_preferred_carrier_helper_in_proforma_detail():
    src = (APP / "static" / "v2" / "proforma-detail.jsx").read_text(encoding="utf-8")
    assert "_awbPreferredCarrierFromCm" in src
    assert "setCarrierTouched(true)" in src
    assert "carrierTouched" in src
