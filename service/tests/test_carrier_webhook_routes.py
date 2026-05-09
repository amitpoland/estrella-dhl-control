"""
test_carrier_webhook_routes.py — DL-E1 webhook ingestion HTTP layer.

Required coverage:
  1. endpoints return 503 when disabled.
  2. activate with matching header/body secret returns 200 and echoes
     secret.
  3. activate stores only secret hash.
  4. activate mismatch returns 400.
  5. events bad JSON returns 400.
  6. events missing shipments returns 400.
  7. events oversize shipments returns 400.
  8. events valid payload with one shipment returns 200 and processes.
  9. events valid payload with two shipments processes both.
  10. missing DHL-API-Key when required returns 401.
  11. IP outside allowlist returns 403.
  12. route file contains only POST decorators.
  13. route file contains no GET / PUT / PATCH / DELETE decorators.
  14. route file does not import requests/httpx/urllib.
  15. route file does not call live DHL network methods.
  16. existing carrier read routes still have no POST.
  17. existing carrier proposal routes still have no POST.
  18. existing carrier action routes remain unchanged in source-grep
      sentinel.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes_carrier_webhook as rcw
from app.core.config import settings
from app.services.carrier import carrier_event_db as ced
from app.services.carrier import carrier_shipment_db as csdb
from app.services.carrier import carrier_state_engine as cse
from app.services.carrier.base import CARRIER_DHL


_ROUTE_FILE = (
    Path(__file__).resolve().parents[1]
    / "app" / "api" / "routes_carrier_webhook.py"
)
_READ_FILE = (
    Path(__file__).resolve().parents[1]
    / "app" / "api" / "routes_carrier.py"
)
_PROPOSAL_FILE = (
    Path(__file__).resolve().parents[1]
    / "app" / "api" / "routes_carrier_proposals.py"
)
_ACTIONS_FILE = (
    Path(__file__).resolve().parents[1]
    / "app" / "api" / "routes_carrier_actions.py"
)


@pytest.fixture(scope="module")
def route_src() -> str:
    return _ROUTE_FILE.read_text(encoding="utf-8")


@pytest.fixture()
def base_setup(tmp_path, monkeypatch):
    """Common setup: tmp storage, both carrier DBs initialised, no auth."""
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    monkeypatch.setattr(
        settings, "carrier_dhl_webhook_enabled", True, raising=False,
    )
    monkeypatch.setattr(
        settings, "carrier_dhl_webhook_ip_allowlist", "", raising=False,
    )
    monkeypatch.setattr(
        settings, "carrier_dhl_webhook_max_shipments_per_push", 200,
        raising=False,
    )
    csdb.init_db(tmp_path / "carrier_shipments.db")
    ced.init_db(tmp_path / "carrier_events.db")
    return tmp_path


@pytest.fixture()
def client(base_setup):
    app = FastAPI()
    app.include_router(rcw.router)
    # Set a real-looking source IP so the IP-allowlist test can match
    # 127.0.0.0/8. TestClient's default client tuple is ("testclient",
    # 50000), which is not a parseable IP — _ip_in_allowlist would
    # then always reject.
    return TestClient(
        app,
        raise_server_exceptions=True,
        client=("127.0.0.1", 12345),
    )


def _seed_handed_to_carrier(awb: str, batch_id: str = "B-WH"):
    """Plant a row at HANDED_TO_CARRIER without going through the
    coordinator (saves a stub-adapter dance)."""
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb=awb,
        state=cse.HANDED_TO_CARRIER, batch_id=batch_id,
    )


def _push_payload(*shipments):
    return {
        "self":      "https://api-eu.dhl.com/push/subscription/test",
        "scope":     "subscription.push",
        "expires":   "2026-12-31T23:59:59Z",
        "note":      "Event push message",
        "shipments": list(shipments),
    }


def _shipment(awb: str, status_code: str,
              ts: str = "2026-04-01T10:00:00Z") -> dict:
    return {
        "id":      awb,
        "service": "express",
        "status": {
            "timestamp":   ts,
            "location":    "Warsaw",
            "statusCode":  status_code,
            "status":      f"DHL emitted {status_code}",
            "description": f"DHL: {status_code}",
        },
    }


# ── 1. endpoints return 503 when disabled ──────────────────────────────────

def test_disabled_activate_returns_503(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(
        settings, "carrier_dhl_webhook_enabled", False, raising=False,
    )
    csdb.init_db(tmp_path / "carrier_shipments.db")
    ced.init_db(tmp_path / "carrier_events.db")
    app = FastAPI()
    app.include_router(rcw.router)
    c = TestClient(app, raise_server_exceptions=True)

    r = c.post(
        "/api/v1/carrier/webhook/dhl/activate",
        json={"secret": "x"},
        headers={"DHL-Hook-Secret": "x"},
    )
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "webhook_disabled"


def test_disabled_events_returns_503(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(
        settings, "carrier_dhl_webhook_enabled", False, raising=False,
    )
    csdb.init_db(tmp_path / "carrier_shipments.db")
    ced.init_db(tmp_path / "carrier_events.db")
    app = FastAPI()
    app.include_router(rcw.router)
    c = TestClient(app, raise_server_exceptions=True)

    r = c.post(
        "/api/v1/carrier/webhook/dhl/events",
        json=_push_payload(_shipment("X", "transit")),
    )
    assert r.status_code == 503


# ── 2. activate happy path ────────────────────────────────────────────────

def test_activate_matching_secret_returns_200_and_echoes(client):
    secret = "dhl-secret-abc-123"
    r = client.post(
        "/api/v1/carrier/webhook/dhl/activate",
        json={"secret": secret, "subscription_id": "sub-T1"},
        headers={"DHL-Hook-Secret": secret},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["secret"] == secret
    assert body["subscription_id"] == "sub-T1"
    assert body["confirmed"] is True


# ── 3. activate stores only secret hash ───────────────────────────────────

def test_activate_persists_only_hash(client, tmp_path):
    secret = "do-not-leak-this-secret"
    r = client.post(
        "/api/v1/carrier/webhook/dhl/activate",
        json={"secret": secret, "subscription_id": "sub-T2"},
        headers={"DHL-Hook-Secret": secret},
    )
    assert r.status_code == 200

    db_path = tmp_path / "carrier_events.db"
    con = sqlite3.connect(str(db_path))
    rows = con.execute(
        "SELECT secret_hash FROM carrier_webhook_subscriptions "
        "WHERE subscription_id=?", ("sub-T2",),
    ).fetchall()
    con.close()
    assert rows
    for r in rows:
        assert secret not in r[0]
        # And the hash is sha256 length
        assert len(r[0]) == 64


# ── 4. activate mismatch returns 400 ─────────────────────────────────────

def test_activate_secret_mismatch_returns_400(client):
    r = client.post(
        "/api/v1/carrier/webhook/dhl/activate",
        json={"secret": "body-secret"},
        headers={"DHL-Hook-Secret": "header-secret"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "secret_mismatch"


def test_activate_missing_secret_returns_400(client):
    r = client.post(
        "/api/v1/carrier/webhook/dhl/activate",
        json={},  # body missing secret
        headers={"DHL-Hook-Secret": "x"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "secret_missing"


# ── 5. events bad JSON ───────────────────────────────────────────────────

def test_events_bad_json_returns_400(client):
    r = client.post(
        "/api/v1/carrier/webhook/dhl/events",
        content=b"not json at all",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "invalid_body"


# ── 6. events missing shipments ─────────────────────────────────────────

def test_events_missing_shipments_returns_400(client):
    r = client.post(
        "/api/v1/carrier/webhook/dhl/events",
        json={"self": "x", "scope": "subscription.push"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "missing_shipments"


# ── 7. events oversize ───────────────────────────────────────────────────

def test_events_oversize_returns_400(client, monkeypatch):
    monkeypatch.setattr(
        settings, "carrier_dhl_webhook_max_shipments_per_push", 2,
        raising=False,
    )
    payload = _push_payload(
        _shipment("A", "transit"),
        _shipment("B", "transit"),
        _shipment("C", "transit"),
    )
    r = client.post(
        "/api/v1/carrier/webhook/dhl/events",
        json=payload,
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "too_many_shipments"


# ── 8. events one shipment, processed ───────────────────────────────────

def test_events_one_shipment_processes(client):
    _seed_handed_to_carrier("WH-1")
    r = client.post(
        "/api/v1/carrier/webhook/dhl/events",
        json=_push_payload(_shipment("WH-1", "transit")),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["shipments_processed"] == 1
    assert body["results"][0]["outcome"] == "applied"

    row = csdb.get_by_awb(CARRIER_DHL, "WH-1")
    assert row["state"] == cse.IN_TRANSIT


# ── 9. events two shipments, both processed ─────────────────────────────

def test_events_two_shipments_processed(client):
    _seed_handed_to_carrier("WH-A")
    _seed_handed_to_carrier("WH-B")
    r = client.post(
        "/api/v1/carrier/webhook/dhl/events",
        json=_push_payload(
            _shipment("WH-A", "transit", ts="2026-04-01T10:00:00Z"),
            _shipment("WH-B", "delivered", ts="2026-04-01T10:00:00Z"),
        ),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["shipments_processed"] == 2
    outcomes = [r["outcome"] for r in body["results"]]
    assert outcomes.count("applied") == 2

    assert csdb.get_by_awb(CARRIER_DHL, "WH-A")["state"] == cse.IN_TRANSIT
    assert csdb.get_by_awb(CARRIER_DHL, "WH-B")["state"] == cse.DELIVERED


def test_events_unknown_shipment_returns_200_no_shipment(client):
    r = client.post(
        "/api/v1/carrier/webhook/dhl/events",
        json=_push_payload(_shipment("UNKNOWN", "transit")),
    )
    assert r.status_code == 200
    assert r.json()["results"][0]["outcome"] == "no_shipment"


def test_events_unknown_status_returns_200_ignored(client):
    _seed_handed_to_carrier("UNK-1")
    r = client.post(
        "/api/v1/carrier/webhook/dhl/events",
        json=_push_payload(_shipment("UNK-1", "scanned-by-aliens")),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["results"][0]["outcome"] == "ignored"
    assert body["results"][0]["unknown_status_code"] is True


def test_events_repeat_event_is_deduped(client):
    _seed_handed_to_carrier("DUP-1")
    payload = _push_payload(_shipment("DUP-1", "transit"))
    r1 = client.post("/api/v1/carrier/webhook/dhl/events", json=payload)
    r2 = client.post("/api/v1/carrier/webhook/dhl/events", json=payload)
    assert r1.json()["results"][0]["outcome"] == "applied"
    assert r2.json()["results"][0]["outcome"] == "deduped"


# ── 10. missing DHL-API-Key returns 401 ─────────────────────────────────

def test_missing_api_key_returns_401(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret-api-key", raising=False)
    _seed_handed_to_carrier("AUTH-1")
    r = client.post(
        "/api/v1/carrier/webhook/dhl/events",
        json=_push_payload(_shipment("AUTH-1", "transit")),
    )
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "unauthorized"


def test_correct_api_key_passes(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret-api-key", raising=False)
    _seed_handed_to_carrier("AUTH-OK")
    r = client.post(
        "/api/v1/carrier/webhook/dhl/events",
        json=_push_payload(_shipment("AUTH-OK", "transit")),
        headers={"DHL-API-Key": "secret-api-key"},
    )
    assert r.status_code == 200


# ── 11. IP outside allowlist returns 403 ─────────────────────────────────

def test_ip_outside_allowlist_returns_403(client, monkeypatch):
    """TestClient connects from 127.0.0.1; 10.0.0.0/8 excludes it."""
    monkeypatch.setattr(
        settings, "carrier_dhl_webhook_ip_allowlist",
        "10.0.0.0/8", raising=False,
    )
    _seed_handed_to_carrier("IP-1")
    r = client.post(
        "/api/v1/carrier/webhook/dhl/events",
        json=_push_payload(_shipment("IP-1", "transit")),
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "forbidden"


def test_ip_inside_allowlist_passes(client, monkeypatch):
    monkeypatch.setattr(
        settings, "carrier_dhl_webhook_ip_allowlist",
        "127.0.0.0/8", raising=False,
    )
    _seed_handed_to_carrier("IP-2")
    r = client.post(
        "/api/v1/carrier/webhook/dhl/events",
        json=_push_payload(_shipment("IP-2", "transit")),
    )
    assert r.status_code == 200


# ── 12+13. Only POST decorators in route file ──────────────────────────

def test_route_file_only_has_post_decorators(route_src):
    decorators = re.findall(
        r"@router\.(get|post|put|patch|delete)\b", route_src,
    )
    assert decorators, "no @router.* decorators in webhook routes"
    for verb in decorators:
        assert verb == "post", (
            f"non-POST verb @router.{verb} found — webhook routes must be "
            f"POST-only."
        )


@pytest.mark.parametrize("verb", ["get", "put", "patch", "delete"])
def test_route_file_no_other_verbs(route_src, verb):
    pattern = re.compile(rf"@router\.{verb}\b")
    assert not pattern.search(route_src)


# ── 14. No HTTP client imports ─────────────────────────────────────────

@pytest.mark.parametrize("forbidden", [
    "import requests", "from requests",
    "import httpx",    "from httpx",
    "import urllib",   "from urllib",
])
def test_route_file_no_http_clients(route_src, forbidden):
    assert forbidden not in route_src, (
        f"routes_carrier_webhook.py contains {forbidden!r}."
    )


# ── 15. No live-DHL network method calls ──────────────────────────────

@pytest.mark.parametrize("forbidden", [
    "DHLExpressLiveAdapter().create_shipment",
    "DHLExpressLiveAdapter().cancel_shipment",
    "DHLExpressLiveAdapter().fetch_label",
    "DHLExpressLiveAdapter().schedule_pickup",
    "live_adapter.create_shipment",
    "live_adapter.cancel_shipment",
    "live_adapter.fetch_label",
])
def test_route_file_no_live_network_methods(route_src, forbidden):
    assert forbidden not in route_src, (
        f"routes_carrier_webhook.py contains {forbidden!r} — DL-E1 is "
        f"parse-only; transport methods land in DL-F."
    )


# ── 16/17/18. Read-only sentinels on existing carrier routes ─────────

def test_read_only_carrier_routes_have_no_post():
    src = _READ_FILE.read_text(encoding="utf-8")
    assert not re.search(r"@router\.post\b", src), (
        "DL-E1 must not introduce POST into routes_carrier.py."
    )


def test_carrier_proposal_routes_have_no_post():
    src = _PROPOSAL_FILE.read_text(encoding="utf-8")
    assert not re.search(r"@router\.post\b", src), (
        "DL-E1 must not introduce POST into routes_carrier_proposals.py."
    )


def test_carrier_action_routes_unchanged_endpoints_present():
    """Sentinel: the four DL-D5 endpoint paths must still exist verbatim
    in routes_carrier_actions.py."""
    src = _ACTIONS_FILE.read_text(encoding="utf-8")
    for path in [
        '"/create-shipment/execute"',
        '"/mark-label-printed/execute"',
        '"/mark-handed-to-carrier/execute"',
        '"/cancel-shipment/execute"',
    ]:
        assert path in src, (
            f"DL-D5 endpoint {path} disappeared from "
            f"routes_carrier_actions.py — DL-E1 must not modify it."
        )
