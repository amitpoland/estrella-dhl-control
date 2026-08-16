"""Static authority checks for carrier credential campaign (pre-commit)."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.carrier.credentials import resolve_carrier_credentials
from app.services.carrier.credentials.resolver import resolve_carrier_capability

_ROOT = Path(__file__).resolve().parents[1]
_APP = _ROOT / "app"
_CRED = _APP / "services" / "carrier" / "credentials"
_ROUTES = _APP / "api" / "routes_carrier_credentials.py"

# Synthetic patterns that must never appear as literal production secrets in tree.
_FORBIDDEN_LITERALS = (
    "DHL_EXPRESS_API_SECRET=",
    "-----BEGIN",
)


def _py_files(root: Path):
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        yield p


def test_carrier_credential_migrated_defaults_empty():
    assert (settings.carrier_credential_migrated or "") == ""


def test_exactly_one_public_credential_resolver():
    init = (_CRED / "__init__.py").read_text(encoding="utf-8")
    assert "resolve_carrier_credentials" in init
    # No vendor-named public secret getters in package
    for name in ("get_dhl_secret", "get_fedex_secret", "get_ups_secret"):
        assert name not in init


def test_routes_do_not_import_dpapi_or_file_store_directly():
    src = _ROUTES.read_text(encoding="utf-8")
    assert "from app.services.carrier.credentials.dpapi" not in src
    assert "from app.services.carrier.credentials.file_store" not in src
    assert "DpapiCredentialStore" not in src
    assert "protect(" not in src
    assert "unprotect(" not in src
    assert "CarrierCredentialService" in src


def test_no_reveal_secret_endpoint():
    src = _ROUTES.read_text(encoding="utf-8")
    assert "reveal_secret" not in src.lower()
    assert "raw_secret" not in src
    assert re.search(r"@router\.(get|post).*reveal", src, re.I) is None
    assert "/reveal" not in src.lower()
    # Doc may say "No Reveal Secret" — that is intentional prohibition text.


def test_adapters_do_not_import_credential_file_store():
    adapters = _APP / "services" / "carrier" / "adapters"
    for p in _py_files(adapters):
        text = p.read_text(encoding="utf-8")
        assert "credentials.file_store" not in text
        assert "credentials.dpapi" not in text


def test_no_plaintext_secret_constants_in_credential_package():
    for p in _py_files(_CRED):
        text = p.read_text(encoding="utf-8")
        for bad in _FORBIDDEN_LITERALS:
            assert bad not in text, f"{p}: forbidden literal {bad}"
        # No long hex-looking assigned secrets (32+ hex chars as string assign)
        for m in re.finditer(r'=\s*["\']([0-9a-fA-F]{40,})["\']', text):
            pytest.fail(f"{p}: suspicious long hex literal")


def test_unmigrated_uses_legacy_settings_only(monkeypatch):
    from app.services.carrier.credentials.migration import configure_migrated_identities
    from app.services.carrier.credentials.resolver import configure_credential_store
    from app.services.carrier.credentials import MemoryCredentialStore, CredentialIdentity

    configure_migrated_identities(frozenset())  # nothing migrated
    store = MemoryCredentialStore()
    configure_credential_store(store)
    identity = CredentialIdentity("dhl", "production", "ship")
    slot = store.put_candidate(
        identity, {"api_key": "STOREONLY", "api_secret": "STORESEC99"}, updated_by="t"
    )
    store.activate_slot(identity, slot, updated_by="t", validated=True)

    monkeypatch.setattr(settings, "dhl_express_api_key", "LEGACYKEY")
    monkeypatch.setattr(settings, "dhl_express_api_secret", "LEGACYSEC")

    # Production call path: store=None → legacy because not migrated
    bundle = resolve_carrier_credentials("dhl", "ship", "production")
    assert bundle.fields["api_key"] == "LEGACYKEY"

    configure_credential_store(None)
    configure_migrated_identities(None)
