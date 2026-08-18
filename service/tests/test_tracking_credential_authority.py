"""tracking_service must own no DHL credential authority of its own.

Two independent proofs:

1. SOURCE — no direct ``settings.dhl_*`` credential read survives in
   ``tracking_service``; every secret arrives through the canonical resolver
   (``resolve_carrier_credentials`` via ``consumer_bridge``).
2. BEHAVIOUR — with ``dhl/production/track`` migrated, the legacy tracking call
   consumes the secure store and CANNOT fall back to legacy Settings/.env, even
   when those carry a (poisoned) value. Migrated => store ONLY. No merge.

Origin: A1 carrier-authority cleanup after PR #1280 — the last resolver bypass
in the DHL tracking path (``_call_dhl_legacy`` read ``settings.dhl_api_key``).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services import tracking_service as ts
from app.services.carrier.credentials import migration, resolver
from app.services.carrier.credentials.models import CredentialBundle, CredentialIdentity

_SRC = Path(ts.__file__).read_text(encoding="utf-8")

# Credential-bearing Settings attributes. Non-secret gate/URL/routing settings
# (dhl_tracking_api_status, dhl_express_api_url, ...) stay legitimately here.
_CREDENTIAL_SETTINGS = (
    "dhl_api_key",
    "dhl_api_secret",
    "dhl_tracking_api_key",
    "dhl_tracking_api_secret",
    "dhl_express_api_key",
    "dhl_express_api_secret",
    "fedex_client_id",
    "fedex_client_secret",
)


def _strip_comments_and_docstrings(src: str) -> str:
    """Crude but sufficient: drop # comments and triple-quoted blocks."""
    src = re.sub(r'"""(?:.|\n)*?"""', "", src)
    src = re.sub(r"'''(?:.|\n)*?'''", "", src)
    return re.sub(r"#[^\n]*", "", src)


@pytest.mark.parametrize("attr", _CREDENTIAL_SETTINGS)
def test_no_direct_credential_settings_read_in_tracking_service(attr):
    """No runtime read of a DHL/FedEx credential Settings field."""
    code = _strip_comments_and_docstrings(_SRC)
    hits = re.findall(rf"settings\.{attr}\b", code)
    assert not hits, (
        f"tracking_service reads settings.{attr} directly ({len(hits)}x) — "
        "route it through resolve_carrier_credentials / consumer_bridge instead"
    )


def test_tracking_service_resolves_through_the_consumer_bridge():
    """Positive half: the canonical resolver really is the credential source."""
    assert "consumer_bridge import resolve_dhl_secret_fields" in _SRC
    assert "_resolve_dhl_credentials()" in _SRC


# ── Behavioural proof: migrated => store ONLY ───────────────────────────────

_POISON = "LEGACY-ENV-POISON-MUST-NEVER-BE-SENT"
_STORE_KEY = "STORE-ONLY-KEY"

_CANNED = {
    "shipments": [{
        "events": [{
            "timestamp": "2026-07-29T12:00:00",
            "description": "Shipment processed at facility",
            "location": {"address": {"addressLocality": "Warsaw", "countryCode": "PL"}},
        }],
        "origin": {"address": {"addressLocality": "Mumbai", "countryCode": "IN"}},
        "destination": {"address": {"addressLocality": "Warsaw", "countryCode": "PL"}},
        "status": {"status": "transit", "description": "In transit"},
    }]
}


class _StoreOnly:
    """Duck-typed store — the resolver only ever calls get_bundle()."""

    def get_bundle(self, identity: CredentialIdentity) -> CredentialBundle:
        return CredentialBundle(identity=identity, fields={"api_key": _STORE_KEY})


@pytest.fixture
def captured_headers(monkeypatch):
    """Fake httpx client that records the outbound headers; no network."""
    seen: list[dict] = []

    class _Resp:
        def raise_for_status(self): return None
        def json(self): return _CANNED

    class _Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url, headers=None, **k):
            seen.append(dict(headers or {}))
            return _Resp()

    monkeypatch.setattr(ts.httpx, "Client", _Client)
    monkeypatch.setattr(ts.settings, "dhl_tracking_api_status", "active", raising=False)
    # Poison every legacy alias — none of them may reach the wire once migrated.
    monkeypatch.setattr(ts.settings, "dhl_api_key", _POISON, raising=False)
    monkeypatch.setattr(ts.settings, "dhl_tracking_api_key", _POISON, raising=False)
    return seen


@pytest.fixture
def migrated_track():
    """Mark dhl/production/track migrated, with a store that serves it."""
    migration.configure_migrated_identities(frozenset({"dhl/production/track"}))
    resolver.configure_credential_store(_StoreOnly())
    try:
        yield
    finally:
        migration.configure_migrated_identities(None)
        resolver.configure_credential_store(None)


def test_migrated_track_uses_store_and_never_legacy_env(captured_headers, migrated_track):
    ts._call_dhl_legacy("1234567890")

    assert len(captured_headers) == 1
    sent = captured_headers[0]["DHL-API-Key"]
    assert sent == _STORE_KEY
    assert _POISON not in sent, "migrated identity leaked the legacy .env credential"


def test_migrated_track_with_empty_store_fails_closed(captured_headers, monkeypatch):
    """Migrated + no store configured => empty key, NOT a legacy fallback."""
    migration.configure_migrated_identities(frozenset({"dhl/production/track"}))
    resolver.configure_credential_store(None)
    try:
        ts._call_dhl_legacy("1234567890")
    finally:
        migration.configure_migrated_identities(None)

    sent = captured_headers[0]["DHL-API-Key"]
    assert sent == "", f"expected fail-closed empty key, got {sent!r}"
    assert _POISON not in sent


def test_unmigrated_track_still_resolves_the_legacy_alias(captured_headers):
    """Control: unmigrated => legacy Settings ONLY, proving the poison test
    above is a real result and not a constant-empty artefact."""
    migration.configure_migrated_identities(frozenset())
    try:
        ts._call_dhl_legacy("1234567890")
    finally:
        migration.configure_migrated_identities(None)

    assert captured_headers[0]["DHL-API-Key"] == _POISON
