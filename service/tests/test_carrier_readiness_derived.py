"""Carrier readiness is derived at read time — never stored, never leaky.

GET /api/v1/carriers-config/readiness composes three authorities that already
own the facts: the credential resolver (is a secret provisioned?), the carrier
factory (does a bookable adapter exist?) and the global carrier_api_status
gate. It must therefore:

  - resolve as its own path, not as a carrier_code lookup
  - never return a credential value, only the resolver's safe projection
  - reflect a configuration change on the very next call (proving nothing is
    stored or cached — a stored flag would be a second authority)
  - report an unresolvable carrier as not-ready, never raise
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    for p in (str(here.parents[1]), str(here.parents[2])):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings

_API = "/api/v1/carriers-config/readiness"
_HDR = {"X-API-Key": "TESTKEY"}

# Synthetic — the repo is public. Distinctive enough that a leak is findable.
_DHL_KEY = "dhl-key-SYNTHETIC-AAAA"
_DHL_SECRET = "dhl-secret-SYNTHETIC-BBBB"
_FEDEX_SECRET = "fedex-secret-SYNTHETIC-CCCC"
_UPS_SECRET = "ups-secret-SYNTHETIC-DDDD"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "TESTKEY")
    monkeypatch.setattr(settings, "carrier_api_status", "pending")
    monkeypatch.setattr(settings, "dhl_express_api_key", _DHL_KEY, raising=False)
    monkeypatch.setattr(settings, "dhl_express_api_secret", _DHL_SECRET, raising=False)
    monkeypatch.setattr(settings, "fedex_client_id", "fedex-client-id", raising=False)
    monkeypatch.setattr(settings, "fedex_client_secret", _FEDEX_SECRET, raising=False)
    monkeypatch.setattr(settings, "ups_client_id", "ups-client-id", raising=False)
    monkeypatch.setattr(settings, "ups_client_secret", _UPS_SECRET, raising=False)
    import app.api.routes_master_data as md

    md._DB_PATH = tmp_path / "master_data.sqlite"
    app = FastAPI()
    app.include_router(md.carriers_config_router)
    return TestClient(app, raise_server_exceptions=True)


def _rows(client) -> list:
    r = client.get(_API, headers=_HDR)
    assert r.status_code == 200, r.text
    return r.json()["carriers"]


def _row(client, carrier: str, environment: str) -> dict:
    for row in _rows(client):
        if row["carrier_code"] == carrier and row["environment"] == environment:
            return row
    raise AssertionError(f"{carrier}/{environment} missing from readiness")


# ── The route resolves as itself ─────────────────────────────────────────────


def test_readiness_is_not_swallowed_by_the_carrier_code_path(client):
    """Registered before GET /{carrier_code}, which would 404 it as a lookup."""
    r = client.get(_API, headers=_HDR)
    assert r.status_code == 200, r.text
    assert "not found" not in r.text.lower()
    assert r.json()["count"] == len(r.json()["carriers"]) > 0


def test_readiness_requires_authentication(client):
    assert client.get(_API).status_code in (401, 403)


# ── No credential value ever reaches the browser ─────────────────────────────


def test_no_secret_value_appears_anywhere_in_the_response(client):
    raw = client.get(_API, headers=_HDR).text
    for secret in (_DHL_KEY, _DHL_SECRET, _FEDEX_SECRET, _UPS_SECRET):
        assert secret not in raw
    # and no field that would carry one
    for banned in ("api_secret", "client_secret", "access_token", "password"):
        assert banned not in raw


def test_the_row_reports_state_not_the_credential(client):
    ship = next(
        c for c in _row(client, "DHL", "production")["credentials"]
        if c["capability"] == "ship"
    )
    assert ship["configured"] is True
    assert ship["state"] == "ready"
    # "ship" needs no separate provisioning axis — the adapter IS the wiring.
    assert ship["provisioned"] is True
    assert ship["capability_ready"] is True
    assert set(ship) == {
        "capability", "environment", "state", "configured", "active",
        "masked_suffix", "last_validated_at", "reason",
        # Credentials alone are not readiness: the capability must also exist.
        "provisioned", "capability_ready", "not_provisioned_reason",
    }


# ── Derived, not stored ──────────────────────────────────────────────────────


def test_a_gate_change_shows_up_on_the_very_next_call(client, monkeypatch):
    """Nothing is persisted or cached, so nothing can go stale."""
    before = _row(client, "DHL", "production")["adapter"]
    assert before["available"] is False
    assert "pending" in before["reason"]

    monkeypatch.setattr(settings, "carrier_api_status", "shadow")
    after = _row(client, "DHL", "production")["adapter"]
    assert after["available"] is True
    assert after["adapter"] == "DhlExpressShadowAdapter"


def test_a_credential_removal_shows_up_on_the_very_next_call(client, monkeypatch):
    assert _row(client, "UPS", "sandbox")["credentials"][0]["configured"] is True
    monkeypatch.setattr(settings, "ups_client_secret", "", raising=False)
    ups = _row(client, "UPS", "sandbox")
    assert ups["credentials"][0]["configured"] is False
    assert ups["credentials"][0]["state"] == "not_configured"
    assert ups["ready"] is False


def test_readiness_adds_no_table_and_no_column():
    src = (
        Path(__file__).resolve().parents[1] / "app" / "services" / "master_data_db.py"
    ).read_text(encoding="utf-8")
    assert "readiness" not in src.lower()


# ── Unresolvable never raises ────────────────────────────────────────────────


def test_an_unresolvable_carrier_reports_not_ready_rather_than_raising(
    client, monkeypatch
):
    import app.services.carrier.credentials.resolver as resolver

    def _boom(*a, **kw):
        raise RuntimeError("credential store unreachable")

    monkeypatch.setattr(resolver, "resolve_carrier_capability", _boom)

    r = client.get(_API, headers=_HDR)
    assert r.status_code == 200, r.text
    for row in r.json()["carriers"]:
        assert row["ready"] is False
        for cred in row["credentials"]:
            assert cred["configured"] is False
            assert cred["state"] == "not_configured"
            assert cred["reason"] == "RuntimeError"
    assert "unreachable" not in r.text  # the message is logged, not published


def test_an_adapter_fault_reports_not_ready_rather_than_raising(client, monkeypatch):
    import app.services.carrier.factory as factory

    monkeypatch.setattr(
        factory, "get_adapter",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("adapter exploded")),
    )
    for row in _rows(client):
        assert row["adapter"]["available"] is False
        assert row["ready"] is False


# ── Fail-closed carriers keep their reason ───────────────────────────────────


def test_ups_without_credentials_reads_as_not_configured_never_as_dhl(
    client, monkeypatch
):
    monkeypatch.setattr(settings, "carrier_api_status", "live")
    monkeypatch.setattr(settings, "ups_client_id", "", raising=False)
    monkeypatch.setattr(settings, "ups_client_secret", "", raising=False)
    ups = _row(client, "UPS", "sandbox")["adapter"]
    assert ups["available"] is False
    assert "UPS_NOT_CONFIGURED" in ups["reason"]
    assert "Dhl" not in (ups["adapter"] or "")


def test_the_sandbox_adapters_name_themselves_sandbox(client, monkeypatch):
    """The class name is the production-blocked disclosure on the row."""
    monkeypatch.setattr(settings, "carrier_api_status", "live")
    assert _row(client, "FEDEX", "production")["adapter"]["adapter"] == (
        "FedExSandboxAdapter"
    )
    assert _row(client, "UPS", "sandbox")["adapter"]["adapter"] == "UpsSandboxAdapter"


# ── Optional capabilities are read from the adapter, never self-reported ─────


def test_optional_capabilities_come_from_overriding_the_base(client, monkeypatch):
    monkeypatch.setattr(settings, "carrier_api_status", "live")
    dhl = _row(client, "DHL", "production")["adapter"]["optional_capabilities"]
    assert dhl["track_shipment"] is True
    assert dhl["fetch_electronic_pod"] is True
    # FedEx and UPS inherit the base refusals — never claimed as implemented.
    fedex = _row(client, "FEDEX", "sandbox")["adapter"]["optional_capabilities"]
    assert set(fedex.values()) == {False}


# ── The UI reads this endpoint, not a second one ─────────────────────────────


def test_the_carriers_page_renders_the_derived_readiness(client):
    src = (
        Path(__file__).resolve().parents[1]
        / "app" / "static" / "v2" / "carriers-page.jsx"
    ).read_text(encoding="utf-8")
    assert "PzApi.getCarriersReadiness()" in src
    assert 'data-testid="readiness-tab"' in src
    api = (
        Path(__file__).resolve().parents[1] / "app" / "static" / "v2" / "pz-api.js"
    ).read_text(encoding="utf-8")
    assert "carriers-config/readiness" in api
