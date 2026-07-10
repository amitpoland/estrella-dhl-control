"""
Tests for POST /api/v1/webhooks/wfirma (Phase 1 — safe receiver only).

Pattern: isolated FastAPI() + dependency_overrides so no real settings or
live DB are touched. All DB writes go to tmp_path (pytest built-in).
"""
from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.routes_webhooks_wfirma import (
    _get_webhook_db_path,
    _require_wfirma_webhook_key,
    router,
)

_TEST_KEY = "test-wfirma-webhook-key-abc123"

_VALID_BODY = json.dumps(
    {
        "webhook_key": _TEST_KEY,
        "event_type": "invoice.created",
        "id": "evt-001",
        "invoice_id": "INV-001",
    }
).encode()

_HEADERS = {"Content-Type": "application/json"}


# ── app factories ─────────────────────────────────────────────────────────────


def _app_unconfigured() -> TestClient:
    """Simulates WFIRMA_WEBHOOK_KEY not set."""
    app = FastAPI()

    def _missing() -> str:
        raise HTTPException(
            status_code=503,
            detail="Webhook endpoint is not configured on this server.",
        )

    app.dependency_overrides[_require_wfirma_webhook_key] = _missing
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def _app_with_key(tmp_path, key: str = _TEST_KEY) -> TestClient:
    app = FastAPI()
    app.dependency_overrides[_require_wfirma_webhook_key] = lambda: key
    app.dependency_overrides[_get_webhook_db_path] = lambda: tmp_path / "events.db"
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


# ── 503 when key is unconfigured ──────────────────────────────────────────────


def test_unconfigured_key_returns_503():
    client = _app_unconfigured()
    r = client.post("/api/v1/webhooks/wfirma", content=_VALID_BODY, headers=_HEADERS)
    assert r.status_code == 503


def test_unconfigured_key_503_fires_before_body_parse():
    """503 must fire even when body is invalid JSON."""
    client = _app_unconfigured()
    r = client.post("/api/v1/webhooks/wfirma", content=b"not-json", headers=_HEADERS)
    assert r.status_code == 503


# ── 400 bad JSON ──────────────────────────────────────────────────────────────


def test_invalid_json_returns_400(tmp_path):
    client = _app_with_key(tmp_path)
    r = client.post("/api/v1/webhooks/wfirma", content=b"not-json{", headers=_HEADERS)
    assert r.status_code == 400


def test_json_array_returns_400(tmp_path):
    client = _app_with_key(tmp_path)
    r = client.post(
        "/api/v1/webhooks/wfirma",
        content=json.dumps([1, 2, 3]).encode(),
        headers=_HEADERS,
    )
    assert r.status_code == 400


# ── 403 on bad or missing key ─────────────────────────────────────────────────


def test_missing_webhook_key_in_body_returns_403(tmp_path):
    client = _app_with_key(tmp_path)
    body = json.dumps({"event_type": "invoice.created"}).encode()
    r = client.post("/api/v1/webhooks/wfirma", content=body, headers=_HEADERS)
    assert r.status_code == 403


def test_wrong_webhook_key_returns_403(tmp_path):
    client = _app_with_key(tmp_path)
    body = json.dumps({"webhook_key": "wrong-key", "event_type": "test"}).encode()
    r = client.post("/api/v1/webhooks/wfirma", content=body, headers=_HEADERS)
    assert r.status_code == 403


def test_empty_webhook_key_returns_403(tmp_path):
    client = _app_with_key(tmp_path)
    body = json.dumps({"webhook_key": "", "event_type": "test"}).encode()
    r = client.post("/api/v1/webhooks/wfirma", content=body, headers=_HEADERS)
    assert r.status_code == 403


# ── 200 valid webhook accepted ────────────────────────────────────────────────


def test_valid_webhook_accepted(tmp_path):
    client = _app_with_key(tmp_path)
    r = client.post("/api/v1/webhooks/wfirma", content=_VALID_BODY, headers=_HEADERS)
    assert r.status_code == 200


def test_response_shape_exact(tmp_path):
    """Response must be exactly {"webhook_key": "<key>"} — no extra fields."""
    client = _app_with_key(tmp_path)
    r = client.post("/api/v1/webhooks/wfirma", content=_VALID_BODY, headers=_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == {"webhook_key"}
    assert data["webhook_key"] == _TEST_KEY


# ── payload storage ───────────────────────────────────────────────────────────


def test_payload_stored_in_db(tmp_path):
    client = _app_with_key(tmp_path)
    r = client.post("/api/v1/webhooks/wfirma", content=_VALID_BODY, headers=_HEADERS)
    assert r.status_code == 200

    db_path = tmp_path / "events.db"
    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute("SELECT * FROM wfirma_webhook_events").fetchall()
    assert len(rows) == 1
    event_id, event_type, payload_json, received_at = rows[0]
    assert event_id == "evt-001"
    assert event_type == "invoice.created"
    assert "invoice_id" in payload_json


def test_webhook_key_not_stored_in_db(tmp_path):
    """webhook_key must NEVER appear in the stored payload_json."""
    client = _app_with_key(tmp_path)
    r = client.post("/api/v1/webhooks/wfirma", content=_VALID_BODY, headers=_HEADERS)
    assert r.status_code == 200

    db_path = tmp_path / "events.db"
    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute(
            "SELECT payload_json FROM wfirma_webhook_events WHERE event_id = 'evt-001'"
        ).fetchone()
    assert row is not None
    assert _TEST_KEY not in row[0]


def test_event_type_stored_when_present(tmp_path):
    client = _app_with_key(tmp_path)
    r = client.post("/api/v1/webhooks/wfirma", content=_VALID_BODY, headers=_HEADERS)
    assert r.status_code == 200

    db_path = tmp_path / "events.db"
    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute(
            "SELECT event_type FROM wfirma_webhook_events WHERE event_id = 'evt-001'"
        ).fetchone()
    assert row is not None
    assert row[0] == "invoice.created"


def test_event_without_id_still_stored(tmp_path):
    """Payloads with no id field should generate a UUID and be stored."""
    client = _app_with_key(tmp_path)
    body = json.dumps({"webhook_key": _TEST_KEY, "event_type": "ping"}).encode()
    r = client.post("/api/v1/webhooks/wfirma", content=body, headers=_HEADERS)
    assert r.status_code == 200

    db_path = tmp_path / "events.db"
    with sqlite3.connect(str(db_path)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM wfirma_webhook_events").fetchone()[0]
    assert count == 1


# ── idempotency ───────────────────────────────────────────────────────────────


def test_duplicate_event_accepted_not_reinserted(tmp_path):
    """Posting the same event_id twice must return 200 both times, but only 1 row stored."""
    client = _app_with_key(tmp_path)
    r1 = client.post("/api/v1/webhooks/wfirma", content=_VALID_BODY, headers=_HEADERS)
    r2 = client.post("/api/v1/webhooks/wfirma", content=_VALID_BODY, headers=_HEADERS)
    assert r1.status_code == 200
    assert r2.status_code == 200

    db_path = tmp_path / "events.db"
    with sqlite3.connect(str(db_path)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM wfirma_webhook_events").fetchone()[0]
    assert count == 1


# ── dependency unit tests ─────────────────────────────────────────────────────


def test_require_key_dep_raises_503_when_none(monkeypatch):
    import app.core.config as cfg
    monkeypatch.setattr(cfg.settings, "wfirma_webhook_key", None)
    with pytest.raises(HTTPException) as exc:
        _require_wfirma_webhook_key()
    assert exc.value.status_code == 503


def test_require_key_dep_raises_503_when_empty(monkeypatch):
    import app.core.config as cfg
    monkeypatch.setattr(cfg.settings, "wfirma_webhook_key", "")
    with pytest.raises(HTTPException) as exc:
        _require_wfirma_webhook_key()
    assert exc.value.status_code == 503


def test_require_key_dep_returns_key_when_set(monkeypatch):
    import app.core.config as cfg
    monkeypatch.setattr(cfg.settings, "wfirma_webhook_key", "my-key")
    assert _require_wfirma_webhook_key() == "my-key"


# ── multi-key support (webhook-disable incident, 2026-07-10) ─────────────────
# wFirma issues a DISTINCT webhook_key per webhook registration and a fresh
# one on re-creation. With only one key honored, any second webhook (e.g. the
# C8A stock-change webhook) or a re-registered webhook 403s on every delivery;
# each 403 reply carries no webhook_key, and after 10 consecutive such replies
# wFirma auto-disables the URL ("No webhook_key key found in JSON reply").
# WFIRMA_WEBHOOK_KEY therefore accepts a comma-separated key set.

_KEY_A = "wfirma-key-invoices-111"
_KEY_B = "wfirma-key-stock-222"


def _body(key: str, event_id: str = "evt-mk-1") -> bytes:
    return json.dumps(
        {"webhook_key": key, "event_type": "goods.stock", "id": event_id}
    ).encode()


def test_multikey_first_key_accepted_and_echoed(tmp_path):
    client = _app_with_key(tmp_path, key=f"{_KEY_A},{_KEY_B}")
    r = client.post("/api/v1/webhooks/wfirma", content=_body(_KEY_A), headers=_HEADERS)
    assert r.status_code == 200
    assert r.json() == {"webhook_key": _KEY_A}


def test_multikey_second_key_accepted_echoed_and_stored(tmp_path):
    """The handshake echo must return the key THIS webhook sent, verbatim."""
    client = _app_with_key(tmp_path, key=f"{_KEY_A},{_KEY_B}")
    r = client.post(
        "/api/v1/webhooks/wfirma", content=_body(_KEY_B, "evt-mk-2"), headers=_HEADERS
    )
    assert r.status_code == 200
    assert r.json() == {"webhook_key": _KEY_B}

    with sqlite3.connect(str(tmp_path / "events.db")) as conn:
        row = conn.execute(
            "SELECT payload_json FROM wfirma_webhook_events WHERE event_id = 'evt-mk-2'"
        ).fetchone()
    assert row is not None
    assert _KEY_B not in row[0]          # secret still never stored


def test_multikey_whitespace_tolerated(tmp_path):
    client = _app_with_key(tmp_path, key=f" {_KEY_A} , {_KEY_B} ")
    r = client.post("/api/v1/webhooks/wfirma", content=_body(_KEY_B), headers=_HEADERS)
    assert r.status_code == 200
    assert r.json() == {"webhook_key": _KEY_B}


def test_multikey_wrong_key_still_403(tmp_path):
    client = _app_with_key(tmp_path, key=f"{_KEY_A},{_KEY_B}")
    r = client.post(
        "/api/v1/webhooks/wfirma", content=_body("not-a-key"), headers=_HEADERS
    )
    assert r.status_code == 403
    assert "webhook_key" not in r.json()  # never echo anything on auth failure


def test_multikey_partial_key_not_accepted(tmp_path):
    """A candidate must match exactly — no prefix/substring acceptance."""
    client = _app_with_key(tmp_path, key=f"{_KEY_A},{_KEY_B}")
    r = client.post(
        "/api/v1/webhooks/wfirma", content=_body(_KEY_A[:-1]), headers=_HEADERS
    )
    assert r.status_code == 403


def test_single_key_backcompat_exact_prefix_behavior(tmp_path):
    """A single un-commaed value must behave exactly as before the fix."""
    client = _app_with_key(tmp_path)          # _TEST_KEY, no comma
    ok = client.post("/api/v1/webhooks/wfirma", content=_VALID_BODY, headers=_HEADERS)
    bad = client.post(
        "/api/v1/webhooks/wfirma", content=_body("wrong"), headers=_HEADERS
    )
    assert ok.status_code == 200
    assert ok.json() == {"webhook_key": _TEST_KEY}
    assert bad.status_code == 403


def test_commas_only_key_value_returns_503(tmp_path):
    """A configured value that parses to ZERO keys must fail closed (503)."""
    client = _app_with_key(tmp_path, key=" , ,")
    r = client.post("/api/v1/webhooks/wfirma", content=_body(_KEY_A), headers=_HEADERS)
    assert r.status_code == 503
