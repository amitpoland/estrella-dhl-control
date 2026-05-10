"""
Phase G tests — HMAC-SHA256 signature verification.

Verifies that the webhook route correctly accepts only requests whose
DHL-Signature header matches HMAC-SHA256(secret, raw_body), and that
the response never echoes raw payload or secrets.

All tests use dependency_overrides on an isolated FastAPI app.
No production storage, no HTTP to DHL.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes_carrier_webhook import (
    _get_event_db_path,
    _require_webhook_secret,
    router,
)

_TEST_SECRET = "phase-g-signature-test-secret"
_ALT_SECRET = "different-secret-entirely"

_BASE_PAYLOAD = {"eventId": "EVT-SIG-001", "event": "SHIPMENT-DELIVERED", "batchId": "BATCH-SIG"}


def _sign(body: bytes, secret: str = _TEST_SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _make_body(payload: dict | None = None) -> bytes:
    return json.dumps(payload or _BASE_PAYLOAD).encode()


def _make_client(tmp_path: Path, secret: str = _TEST_SECRET) -> TestClient:
    app = FastAPI()
    app.dependency_overrides[_require_webhook_secret] = lambda: secret
    db = tmp_path / "events.db"
    app.dependency_overrides[_get_event_db_path] = lambda: db
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


# ── missing signature header ──────────────────────────────────────────────────


def test_missing_signature_header_returns_401(tmp_path):
    client = _make_client(tmp_path)
    body = _make_body()
    response = client.post(
        "/api/v1/carrier/webhook/dhl",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 401


def test_missing_signature_response_does_not_contain_payload(tmp_path):
    client = _make_client(tmp_path)
    secret_value = "super-secret-canary"
    body = json.dumps({"eventId": "E1", "event": "TEST", "secret": secret_value}).encode()
    response = client.post(
        "/api/v1/carrier/webhook/dhl",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert secret_value not in response.text


# ── invalid signature ─────────────────────────────────────────────────────────


def test_wrong_signature_returns_401(tmp_path):
    client = _make_client(tmp_path)
    body = _make_body()
    response = client.post(
        "/api/v1/carrier/webhook/dhl",
        content=body,
        headers={"DHL-Signature": "badsignature", "Content-Type": "application/json"},
    )
    assert response.status_code == 401


def test_signature_for_different_secret_returns_401(tmp_path):
    """Signature computed with a different secret must not pass."""
    client = _make_client(tmp_path, secret=_TEST_SECRET)
    body = _make_body()
    wrong_sig = _sign(body, secret=_ALT_SECRET)
    response = client.post(
        "/api/v1/carrier/webhook/dhl",
        content=body,
        headers={"DHL-Signature": wrong_sig, "Content-Type": "application/json"},
    )
    assert response.status_code == 401


def test_signature_for_different_body_returns_401(tmp_path):
    """Reusing a valid signature for a modified body must fail."""
    client = _make_client(tmp_path)
    original_body = _make_body()
    valid_sig = _sign(original_body)

    # Different body — same sig should not verify
    modified_body = json.dumps({"eventId": "EVT-TAMPERED", "event": "MODIFIED"}).encode()
    response = client.post(
        "/api/v1/carrier/webhook/dhl",
        content=modified_body,
        headers={"DHL-Signature": valid_sig, "Content-Type": "application/json"},
    )
    assert response.status_code == 401


def test_empty_signature_returns_401(tmp_path):
    client = _make_client(tmp_path)
    body = _make_body()
    response = client.post(
        "/api/v1/carrier/webhook/dhl",
        content=body,
        headers={"DHL-Signature": "", "Content-Type": "application/json"},
    )
    assert response.status_code in (401, 422)


def test_invalid_response_body_does_not_echo_raw_payload(tmp_path):
    """401 response must never echo the raw request body."""
    client = _make_client(tmp_path)
    canary = "canary-secret-data-xyzabc"
    body = json.dumps({"eventId": "EVT-X", "event": "TEST", "sensitiveField": canary}).encode()
    response = client.post(
        "/api/v1/carrier/webhook/dhl",
        content=body,
        headers={"DHL-Signature": "wrong", "Content-Type": "application/json"},
    )
    assert canary not in response.text


# ── valid signature ───────────────────────────────────────────────────────────


def test_valid_signature_returns_200(tmp_path):
    client = _make_client(tmp_path)
    body = _make_body()
    sig = _sign(body)
    response = client.post(
        "/api/v1/carrier/webhook/dhl",
        content=body,
        headers={"DHL-Signature": sig, "Content-Type": "application/json"},
    )
    assert response.status_code == 200


def test_valid_signature_response_contains_status_ok(tmp_path):
    client = _make_client(tmp_path)
    body = _make_body()
    sig = _sign(body)
    response = client.post(
        "/api/v1/carrier/webhook/dhl",
        content=body,
        headers={"DHL-Signature": sig, "Content-Type": "application/json"},
    )
    data = response.json()
    assert data["status"] == "ok"


def test_valid_response_does_not_echo_raw_payload(tmp_path):
    """200 response must not echo back any field values from the payload."""
    client = _make_client(tmp_path)
    canary = "canary-payload-value-12345"
    body = json.dumps({"eventId": "EVT-CANARY", "event": canary}).encode()
    sig = _sign(body)
    response = client.post(
        "/api/v1/carrier/webhook/dhl",
        content=body,
        headers={"DHL-Signature": sig, "Content-Type": "application/json"},
    )
    assert canary not in response.text


def test_valid_response_does_not_contain_secret(tmp_path):
    """Response body must never contain the HMAC secret."""
    client = _make_client(tmp_path, secret=_TEST_SECRET)
    body = _make_body()
    sig = _sign(body)
    response = client.post(
        "/api/v1/carrier/webhook/dhl",
        content=body,
        headers={"DHL-Signature": sig, "Content-Type": "application/json"},
    )
    assert _TEST_SECRET not in response.text


def test_valid_signature_response_accepted_true(tmp_path):
    """First delivery of an event_id is accepted (new)."""
    client = _make_client(tmp_path)
    body = _make_body()
    sig = _sign(body)
    response = client.post(
        "/api/v1/carrier/webhook/dhl",
        content=body,
        headers={"DHL-Signature": sig, "Content-Type": "application/json"},
    )
    assert response.json()["accepted"] is True


# ── payload validation ────────────────────────────────────────────────────────


def test_payload_missing_event_id_returns_400(tmp_path):
    client = _make_client(tmp_path)
    body = json.dumps({"event": "NO-ID-HERE"}).encode()
    sig = _sign(body)
    response = client.post(
        "/api/v1/carrier/webhook/dhl",
        content=body,
        headers={"DHL-Signature": sig, "Content-Type": "application/json"},
    )
    assert response.status_code == 400


def test_invalid_json_returns_400(tmp_path):
    client = _make_client(tmp_path)
    body = b"not-json{"
    sig = _sign(body)
    response = client.post(
        "/api/v1/carrier/webhook/dhl",
        content=body,
        headers={"DHL-Signature": sig, "Content-Type": "application/json"},
    )
    assert response.status_code == 400


def test_json_array_returns_400(tmp_path):
    """Payload must be a JSON object, not an array."""
    client = _make_client(tmp_path)
    body = json.dumps([{"eventId": "E1"}]).encode()
    sig = _sign(body)
    response = client.post(
        "/api/v1/carrier/webhook/dhl",
        content=body,
        headers={"DHL-Signature": sig, "Content-Type": "application/json"},
    )
    assert response.status_code == 400
