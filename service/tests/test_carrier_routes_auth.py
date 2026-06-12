"""
Phase J tests — carrier route authentication.

Verifies that all carrier action and shadow routes require a valid API key,
and that the coordinator is never invoked when authentication fails.

Uses isolated FastAPI test apps with dependency_overrides that force 401.
No real DB, no real coordinator.

Note: Authentication occurs before AWB address authority logic (Campaign 02.5),
so these tests are unaffected by the feature flag changes.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.routes_carrier_actions import (
    _get_carrier_config,
    _get_coordinator,
    router as actions_router,
)
from app.api.routes_carrier_shadow import (
    router as shadow_router,
)
from app.core.security import require_api_key
from app.services.carrier.factory import CarrierConfig


# ── Dependency stubs ──────────────────────────────────────────────────────────


def _reject_auth() -> None:
    raise HTTPException(status_code=401, detail="Invalid or missing API key.")


def _shadow_config() -> CarrierConfig:
    return CarrierConfig(status="shadow")


# ── Auth-enforced test app ────────────────────────────────────────────────────


@pytest.fixture()
def auth_app():
    """Fresh FastAPI app with authentication forced to always reject (401)."""
    app = FastAPI()
    app.include_router(shadow_router)
    app.include_router(actions_router)
    app.dependency_overrides[require_api_key] = _reject_auth
    app.dependency_overrides[_get_carrier_config] = _shadow_config
    return app


# ═══════════════════════════════════════════════════════════════════════════════
# POST /shipment
# ═══════════════════════════════════════════════════════════════════════════════


def test_post_shipment_no_key_returns_401(auth_app):
    client = TestClient(auth_app, raise_server_exceptions=False)
    # Mock settings to prevent any potential import issues during auth failure
    with patch('app.core.config.settings') as mock_settings:
        mock_settings.awb_address_authority_enabled = False
        resp = client.post(
            "/api/v1/carrier/BATCH-001/shipment",
            json={
                "shipper_account": "ACC",
                "recipient_address": {},
                "declared_value": 100.0,
                "currency": "EUR",
                "weight_kg": 1.5,
                "dimensions": {},
            },
        )
    assert resp.status_code == 401


def test_post_shipment_coordinator_not_called_when_unauthed(auth_app):
    """Coordinator must never be invoked if authentication fails."""
    spy = MagicMock()
    auth_app.dependency_overrides[_get_coordinator] = lambda: spy
    client = TestClient(auth_app, raise_server_exceptions=False)
    client.post(
        "/api/v1/carrier/BATCH-001/shipment",
        json={
            "shipper_account": "ACC",
            "recipient_address": {},
            "declared_value": 100.0,
            "currency": "EUR",
            "weight_kg": 1.5,
            "dimensions": {},
        },
    )
    spy.create_shipment.assert_not_called()


def test_post_shipment_401_body_does_not_contain_internals(auth_app):
    client = TestClient(auth_app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/carrier/BATCH-001/shipment",
        json={
            "shipper_account": "ACC",
            "recipient_address": {},
            "declared_value": 100.0,
            "currency": "EUR",
            "weight_kg": 1.5,
            "dimensions": {},
        },
    )
    assert resp.status_code == 401
    assert "tracking" not in resp.text.lower()
    assert "shadow" not in resp.text.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# GET /shipment
# ═══════════════════════════════════════════════════════════════════════════════


def test_get_shipment_no_key_returns_401(auth_app):
    client = TestClient(auth_app, raise_server_exceptions=False)
    resp = client.get("/api/v1/carrier/BATCH-001/shipment")
    assert resp.status_code == 401


def test_get_shipment_no_key_no_db_access(auth_app, tmp_path):
    """Auth must short-circuit before any DB dependency is resolved."""
    # Do NOT provide a db override — if auth short-circuits correctly,
    # the DB path dependency is never called and no error occurs.
    client = TestClient(auth_app, raise_server_exceptions=False)
    resp = client.get("/api/v1/carrier/BATCH-001/shipment")
    assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# GET /shadow/log
# ═══════════════════════════════════════════════════════════════════════════════


def test_get_shadow_log_no_key_returns_401(auth_app):
    client = TestClient(auth_app, raise_server_exceptions=False)
    resp = client.get("/api/v1/carrier/shadow/log")
    assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# GET /status
# ═══════════════════════════════════════════════════════════════════════════════


def test_get_status_no_key_returns_401(auth_app):
    client = TestClient(auth_app, raise_server_exceptions=False)
    resp = client.get("/api/v1/carrier/status")
    assert resp.status_code == 401
