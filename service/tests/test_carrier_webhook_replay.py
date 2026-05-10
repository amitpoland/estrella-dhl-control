"""
Phase G tests — webhook replay protection (idempotency).

Verifies that duplicate event deliveries (same event_id) are acknowledged
with HTTP 200 but stored only once in the carrier_events DB.

All tests use tmp_path DBs and dependency_overrides.
No production storage, no HTTP to DHL.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes_carrier_webhook import (
    _get_event_db_path,
    _require_webhook_secret,
    router,
)
from app.services.carrier.persistence.event_db import get_event, get_events_for_batch

_TEST_SECRET = "phase-g-replay-test-secret"


def _sign(body: bytes, secret: str = _TEST_SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _make_client(db_path: Path, secret: str = _TEST_SECRET) -> TestClient:
    app = FastAPI()
    app.dependency_overrides[_require_webhook_secret] = lambda: secret
    app.dependency_overrides[_get_event_db_path] = lambda: db_path
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def _post(client: TestClient, payload: dict) -> object:
    body = json.dumps(payload).encode()
    sig = _sign(body)
    return client.post(
        "/api/v1/carrier/webhook/dhl",
        content=body,
        headers={"DHL-Signature": sig, "Content-Type": "application/json"},
    )


# ── first delivery stores the event ──────────────────────────────────────────


def test_first_delivery_returns_200(tmp_path):
    db = tmp_path / "events.db"
    client = _make_client(db)
    response = _post(client, {"eventId": "EVT-001", "event": "DELIVERED", "batchId": "BATCH-R"})
    assert response.status_code == 200


def test_first_delivery_accepted_true(tmp_path):
    db = tmp_path / "events.db"
    client = _make_client(db)
    response = _post(client, {"eventId": "EVT-002", "event": "DELIVERED", "batchId": "BATCH-R"})
    assert response.json()["accepted"] is True


def test_first_delivery_event_written_to_db(tmp_path):
    db = tmp_path / "events.db"
    client = _make_client(db)
    _post(client, {"eventId": "EVT-003", "event": "IN-TRANSIT", "batchId": "BATCH-R"})
    row = get_event(db, "EVT-003")
    assert row is not None
    assert row["event_id"] == "EVT-003"


def test_first_delivery_event_type_stored(tmp_path):
    db = tmp_path / "events.db"
    client = _make_client(db)
    _post(client, {"eventId": "EVT-004", "event": "HELD", "batchId": "BATCH-R"})
    row = get_event(db, "EVT-004")
    assert row["event_type"] == "HELD"


def test_first_delivery_batch_id_stored(tmp_path):
    db = tmp_path / "events.db"
    client = _make_client(db)
    _post(client, {"eventId": "EVT-005", "event": "DELIVERED", "batchId": "MY-BATCH"})
    row = get_event(db, "EVT-005")
    assert row["batch_id"] == "MY-BATCH"


# ── duplicate delivery is idempotent ──────────────────────────────────────────


def test_duplicate_delivery_returns_200(tmp_path):
    db = tmp_path / "events.db"
    client = _make_client(db)
    payload = {"eventId": "EVT-DUP-001", "event": "DELIVERED"}
    _post(client, payload)
    response2 = _post(client, payload)
    assert response2.status_code == 200


def test_duplicate_delivery_accepted_false(tmp_path):
    """Second delivery of the same event_id returns accepted=False."""
    db = tmp_path / "events.db"
    client = _make_client(db)
    payload = {"eventId": "EVT-DUP-002", "event": "DELIVERED"}
    _post(client, payload)
    response2 = _post(client, payload)
    assert response2.json()["accepted"] is False


def test_duplicate_delivery_stored_only_once(tmp_path):
    """event_db must have exactly one row for a duplicate-delivered event."""
    db = tmp_path / "events.db"
    client = _make_client(db)
    payload = {"eventId": "EVT-DUP-003", "event": "DELIVERED", "batchId": "BATCH-DUP"}
    _post(client, payload)
    _post(client, payload)

    conn = sqlite3.connect(str(db))
    count = conn.execute(
        "SELECT COUNT(*) FROM carrier_events WHERE event_id = ?",
        ("EVT-DUP-003",),
    ).fetchone()[0]
    conn.close()
    assert count == 1


def test_triple_delivery_stored_only_once(tmp_path):
    """Three deliveries of the same event_id = one row in DB."""
    db = tmp_path / "events.db"
    client = _make_client(db)
    payload = {"eventId": "EVT-TRIPLE", "event": "DELIVERED"}
    _post(client, payload)
    _post(client, payload)
    _post(client, payload)

    conn = sqlite3.connect(str(db))
    count = conn.execute(
        "SELECT COUNT(*) FROM carrier_events WHERE event_id = ?",
        ("EVT-TRIPLE",),
    ).fetchone()[0]
    conn.close()
    assert count == 1


def test_third_delivery_returns_200(tmp_path):
    db = tmp_path / "events.db"
    client = _make_client(db)
    payload = {"eventId": "EVT-TRIPLE-2", "event": "DELIVERED"}
    _post(client, payload)
    _post(client, payload)
    r3 = _post(client, payload)
    assert r3.status_code == 200


# ── different event_ids are stored independently ──────────────────────────────


def test_different_event_ids_stored_independently(tmp_path):
    db = tmp_path / "events.db"
    client = _make_client(db)
    _post(client, {"eventId": "EVT-A", "event": "DELIVERED", "batchId": "BATCH-X"})
    _post(client, {"eventId": "EVT-B", "event": "IN-TRANSIT", "batchId": "BATCH-X"})

    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM carrier_events").fetchone()[0]
    conn.close()
    assert count == 2


def test_different_event_ids_both_accepted(tmp_path):
    db = tmp_path / "events.db"
    client = _make_client(db)
    r1 = _post(client, {"eventId": "EVT-C", "event": "DELIVERED"})
    r2 = _post(client, {"eventId": "EVT-D", "event": "RETURNED"})
    assert r1.json()["accepted"] is True
    assert r2.json()["accepted"] is True


# ── tracking identifiers not persisted ───────────────────────────────────────


def test_tracking_number_not_stored_in_payload(tmp_path):
    """shipmentTrackingNumber must be stripped from stored payload."""
    db = tmp_path / "events.db"
    client = _make_client(db)
    payload = {
        "eventId": "EVT-STRIP-001",
        "event": "DELIVERED",
        "shipmentTrackingNumber": "1234567890",
        "batchId": "BATCH-STRIP",
    }
    _post(client, payload)
    row = get_event(db, "EVT-STRIP-001")
    assert row is not None
    stored = json.loads(row["payload_json"])
    assert "shipmentTrackingNumber" not in stored


def test_awb_not_stored_in_payload(tmp_path):
    db = tmp_path / "events.db"
    client = _make_client(db)
    payload = {
        "eventId": "EVT-STRIP-002",
        "event": "DELIVERED",
        "awbNumber": "AWB-REAL-9999",
    }
    _post(client, payload)
    row = get_event(db, "EVT-STRIP-002")
    stored = json.loads(row["payload_json"])
    assert "awbNumber" not in stored


def test_event_id_stored_despite_tracking_strip(tmp_path):
    """Stripping tracking fields must not affect event_id storage."""
    db = tmp_path / "events.db"
    client = _make_client(db)
    payload = {
        "eventId": "EVT-STRIP-003",
        "event": "DELIVERED",
        "trackingNumber": "REAL-TRACK-123",
    }
    _post(client, payload)
    row = get_event(db, "EVT-STRIP-003")
    assert row is not None
    assert row["event_id"] == "EVT-STRIP-003"


# ── response never echoes payload ─────────────────────────────────────────────


def test_200_response_does_not_echo_event_id(tmp_path):
    db = tmp_path / "events.db"
    client = _make_client(db)
    payload = {"eventId": "EVT-ECHO-TEST", "event": "DELIVERED"}
    response = _post(client, payload)
    assert "EVT-ECHO-TEST" not in response.text


def test_200_response_keys_are_minimal(tmp_path):
    """Response JSON must only contain 'status' and 'accepted'."""
    db = tmp_path / "events.db"
    client = _make_client(db)
    payload = {"eventId": "EVT-MINIMAL", "event": "DELIVERED"}
    response = _post(client, payload)
    data = response.json()
    assert set(data.keys()) == {"status", "accepted"}
