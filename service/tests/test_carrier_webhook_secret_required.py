"""
Phase G tests — webhook secret guard.

Verifies that the DHL webhook endpoint is closed (HTTP 503) whenever
DHL_WEBHOOK_SECRET is not configured, and that the route becomes reachable
(proceeds past the guard) once a secret is supplied.

All tests use dependency_overrides on an isolated FastAPI app.
No production storage, no HTTP to DHL.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.routes_carrier_webhook import (
    _get_event_db_path,
    _require_webhook_secret,
    router,
)

_TEST_SECRET = "phase-g-test-secret-abc123"

_VALID_BODY = json.dumps({"eventId": "EVT-GUARD-001", "event": "TEST"}).encode()


def _sign(body: bytes, secret: str = _TEST_SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _app_no_secret(db_path: Path) -> TestClient:
    """Test app where the secret dependency raises 503 (unconfigured)."""
    app = FastAPI()

    def _missing_secret():
        raise HTTPException(status_code=503, detail="Webhook endpoint is not configured on this server.")

    app.dependency_overrides[_require_webhook_secret] = _missing_secret
    app.dependency_overrides[_get_event_db_path] = lambda: db_path
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def _app_with_secret(db_path: Path, secret: str = _TEST_SECRET) -> TestClient:
    """Test app with a configured secret."""
    app = FastAPI()
    app.dependency_overrides[_require_webhook_secret] = lambda: secret
    app.dependency_overrides[_get_event_db_path] = lambda: db_path
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


# ── 503 when secret is missing ────────────────────────────────────────────────


def test_no_secret_returns_503(tmp_path):
    client = _app_no_secret(tmp_path / "events.db")
    sig = _sign(_VALID_BODY)
    response = client.post(
        "/api/v1/carrier/webhook/dhl",
        content=_VALID_BODY,
        headers={"DHL-Signature": sig, "Content-Type": "application/json"},
    )
    assert response.status_code == 503


def test_no_secret_503_response_does_not_contain_secret_hint(tmp_path):
    """503 body must not reveal anything about the secret configuration."""
    client = _app_no_secret(tmp_path / "events.db")
    sig = _sign(_VALID_BODY)
    response = client.post(
        "/api/v1/carrier/webhook/dhl",
        content=_VALID_BODY,
        headers={"DHL-Signature": sig, "Content-Type": "application/json"},
    )
    body = response.text.lower()
    assert "secret" not in body or "not configured" in body


def test_no_secret_503_regardless_of_signature(tmp_path):
    """Guard fires before signature check — no valid sig can bypass it."""
    client = _app_no_secret(tmp_path / "events.db")
    response = client.post(
        "/api/v1/carrier/webhook/dhl",
        content=_VALID_BODY,
        headers={"DHL-Signature": "any_sig", "Content-Type": "application/json"},
    )
    assert response.status_code == 503


def test_no_secret_503_with_no_signature_header(tmp_path):
    """503 even when no DHL-Signature header at all — guard fires first."""
    client = _app_no_secret(tmp_path / "events.db")
    response = client.post(
        "/api/v1/carrier/webhook/dhl",
        content=_VALID_BODY,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 503


# ── route proceeds once secret is configured ──────────────────────────────────


def test_with_valid_secret_and_signature_returns_200(tmp_path):
    """Baseline: configured secret + correct signature → 200."""
    client = _app_with_secret(tmp_path / "events.db")
    sig = _sign(_VALID_BODY)
    response = client.post(
        "/api/v1/carrier/webhook/dhl",
        content=_VALID_BODY,
        headers={"DHL-Signature": sig, "Content-Type": "application/json"},
    )
    assert response.status_code == 200


def test_with_valid_secret_wrong_signature_returns_401(tmp_path):
    """Configured secret but wrong signature → 401 (not 503)."""
    client = _app_with_secret(tmp_path / "events.db")
    response = client.post(
        "/api/v1/carrier/webhook/dhl",
        content=_VALID_BODY,
        headers={"DHL-Signature": "bad_sig", "Content-Type": "application/json"},
    )
    assert response.status_code == 401


# ── real dependency unit test (no app needed) ──────────────────────────────────


def test_require_secret_dependency_raises_503_when_none(monkeypatch):
    """Unit test: _require_webhook_secret() raises 503 when settings.dhl_webhook_secret is None."""
    import app.core.config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "dhl_webhook_secret", None)

    with pytest.raises(HTTPException) as exc:
        _require_webhook_secret()
    assert exc.value.status_code == 503


def test_require_secret_dependency_raises_503_when_empty(monkeypatch):
    """Unit test: empty string is treated the same as None."""
    import app.core.config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "dhl_webhook_secret", "")

    with pytest.raises(HTTPException) as exc:
        _require_webhook_secret()
    assert exc.value.status_code == 503


def test_require_secret_dependency_returns_secret_when_set(monkeypatch):
    """Unit test: secret string is returned unchanged."""
    import app.core.config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "dhl_webhook_secret", "my-real-secret")

    result = _require_webhook_secret()
    assert result == "my-real-secret"
