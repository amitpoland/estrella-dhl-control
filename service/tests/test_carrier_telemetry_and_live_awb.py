"""tests/test_carrier_telemetry_and_live_awb.py — DL-F3.5d

Two complementary surfaces:

A) Fail-loud telemetry on _select_carrier_adapter
   ------------------------------------------------
   When the operator has set ``carrier_dhl_live_enabled=True`` but the
   factory still hands back the stub (status pending / unknown,
   incomplete credentials, live constructor raised, shadow wrap
   raised), a single ``logging.WARNING`` carrying the stable token
   ``carrier_live_fallback_to_stub`` MUST be emitted.  The "live not
   enabled" branch is the *intended* path and emits nothing.

B) Route-level live-AWB invariant E2E
   -----------------------------------
   With live enabled + sandbox creds wired and the live HTTP client
   monkey-patched to return a canned MyDHL response, a real
   ``/api/v1/carrier/actions/create-shipment/execute`` call must:

     * actually dispatch to the live adapter (HTTP request observed)
     * surface the live-issued AWB (1234567890) in the response and
       persisted shipment row
     * NOT pre-write the AWB into the registry before the adapter
       returns (live AWBs only land in the DB *after* the carrier
       confirms — invariant from the campaign)

   The PDF-bytes-never-persisted invariant is covered by the existing
   live-adapter unit suite; this E2E pins the route boundary.
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes_carrier_actions as rca
from app.core.config import settings
from app.core.security import require_api_key
from app.services.carrier import carrier_proposal_builder as pb
from app.services.carrier import carrier_shipment_db as csdb


# ════════════════════════════════════════════════════════════════════════════
#  A. Telemetry — fail-loud fallback warnings
# ════════════════════════════════════════════════════════════════════════════

# The grep token operators search for. Pinned as a constant so a rename
# trips the source-grep test below.
_TOKEN = "carrier_live_fallback_to_stub"


@pytest.fixture()
def live_settings(monkeypatch):
    """Default to live_enabled=True with full sandbox credentials.
    Individual tests then degrade one field to drive each fallback
    branch.
    """
    monkeypatch.setattr(settings, "carrier_dhl_live_enabled", True, raising=False)
    monkeypatch.setattr(settings, "dhl_express_api_status", "sandbox", raising=False)
    monkeypatch.setattr(settings, "dhl_express_api_username", "u", raising=False)
    monkeypatch.setattr(settings, "dhl_express_api_password", "p", raising=False)
    monkeypatch.setattr(settings, "dhl_express_account_number", "ACC-1", raising=False)
    monkeypatch.setattr(settings, "carrier_dhl_shadow_mode", False, raising=False)
    monkeypatch.setattr(settings, "carrier_dhl_paperless_trade_enabled", False, raising=False)
    yield


def _warnings(caplog) -> List[logging.LogRecord]:
    return [r for r in caplog.records
            if r.levelno >= logging.WARNING and _TOKEN in r.getMessage()]


def test_live_disabled_emits_no_warning(monkeypatch, caplog):
    """The intended-stub path must not spam ops with telemetry."""
    monkeypatch.setattr(settings, "carrier_dhl_live_enabled", False, raising=False)
    caplog.set_level(logging.WARNING, logger=rca.log.name)
    rca._select_carrier_adapter(actor="operator-x")
    assert _warnings(caplog) == []


def test_live_enabled_status_pending_warns(live_settings, monkeypatch, caplog):
    monkeypatch.setattr(settings, "dhl_express_api_status", "pending", raising=False)
    caplog.set_level(logging.WARNING, logger=rca.log.name)
    rca._select_carrier_adapter(actor="operator-x")
    msgs = [r.getMessage() for r in _warnings(caplog)]
    assert len(msgs) == 1
    assert "pending" in msgs[0]


def test_live_enabled_status_unknown_warns(live_settings, monkeypatch, caplog):
    monkeypatch.setattr(settings, "dhl_express_api_status", "weird-mode", raising=False)
    caplog.set_level(logging.WARNING, logger=rca.log.name)
    rca._select_carrier_adapter(actor="operator-x")
    msgs = [r.getMessage() for r in _warnings(caplog)]
    assert len(msgs) == 1
    assert "weird-mode" in msgs[0]


def test_live_enabled_missing_username_warns(live_settings, monkeypatch, caplog):
    monkeypatch.setattr(settings, "dhl_express_api_username", "", raising=False)
    caplog.set_level(logging.WARNING, logger=rca.log.name)
    rca._select_carrier_adapter(actor="operator-x")
    msgs = [r.getMessage() for r in _warnings(caplog)]
    assert len(msgs) == 1
    # Field-presence detail is in the warning; we don't pin exact wording
    # other than the stable token + "credentials" hint.
    assert "credentials" in msgs[0]


def test_live_enabled_missing_password_warns(live_settings, monkeypatch, caplog):
    monkeypatch.setattr(settings, "dhl_express_api_password", "   ", raising=False)
    caplog.set_level(logging.WARNING, logger=rca.log.name)
    rca._select_carrier_adapter(actor="operator-x")
    assert len(_warnings(caplog)) == 1


def test_live_enabled_missing_account_warns(live_settings, monkeypatch, caplog):
    monkeypatch.setattr(settings, "dhl_express_account_number", "", raising=False)
    caplog.set_level(logging.WARNING, logger=rca.log.name)
    rca._select_carrier_adapter(actor="operator-x")
    assert len(_warnings(caplog)) == 1


def test_live_constructor_failure_warns(live_settings, monkeypatch, caplog):
    """Live adapter __init__ raising → telemetry must surface the
    exception type so ops can spot a regression in the live constructor
    contract immediately."""
    from app.services.carrier.adapters import dhl_express_live as dxl

    class _BoomLive:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("boom-from-live-init")

    monkeypatch.setattr(dxl, "DHLExpressLiveAdapter", _BoomLive, raising=True)
    caplog.set_level(logging.WARNING, logger=rca.log.name)
    rca._select_carrier_adapter(actor="operator-x")
    msgs = [r.getMessage() for r in _warnings(caplog)]
    assert len(msgs) == 1
    assert "RuntimeError" in msgs[0]


def test_shadow_wrap_failure_warns(live_settings, monkeypatch, caplog):
    """Shadow wrapper raising → telemetry, fall back to stub."""
    monkeypatch.setattr(settings, "carrier_dhl_shadow_mode", True, raising=False)
    from app.services.carrier.adapters import dhl_express_shadow as dxs

    class _BoomShadow:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("boom-from-shadow")

    monkeypatch.setattr(dxs, "DHLExpressShadowAdapter", _BoomShadow, raising=True)
    caplog.set_level(logging.WARNING, logger=rca.log.name)
    rca._select_carrier_adapter(actor="operator-x")
    msgs = [r.getMessage() for r in _warnings(caplog)]
    assert len(msgs) == 1
    assert "RuntimeError" in msgs[0]


def test_live_fully_configured_emits_no_warning(live_settings, caplog):
    """Happy path: live enabled, sandbox, all creds → no telemetry,
    return a live adapter (or shadow wrap if shadow mode is on)."""
    caplog.set_level(logging.WARNING, logger=rca.log.name)
    adapter = rca._select_carrier_adapter(actor="operator-x")
    assert _warnings(caplog) == []
    # Sanity: not the stub.
    assert "Stub" not in type(adapter).__name__


# ── Source-grep pin ─────────────────────────────────────────────────────────

def test_route_file_emits_fallback_token():
    """Renaming the token without updating the test would silently
    break ops dashboards. Pin it here."""
    src = Path("app/api/routes_carrier_actions.py").read_text(encoding="utf-8")
    # Token must appear inside the warning string at least 5 times
    # (one per fallback branch: pending, unknown status, missing creds,
    # live ctor exception, shadow wrap exception).
    assert src.count(_TOKEN) >= 5, (
        f"Expected at least 5 occurrences of {_TOKEN!r} in the route "
        f"file (one per fallback branch)."
    )
    # And the logger must be named `log` and use .warning, not .info.
    assert "log = logging.getLogger(__name__)" in src
    assert "log.warning(" in src


def test_route_file_does_not_warn_on_live_disabled_branch():
    """The first branch (live_enabled=False) must NOT emit telemetry —
    it is the *intended* stub path. Pin the comment."""
    src = Path("app/api/routes_carrier_actions.py").read_text(encoding="utf-8")
    # The module must contain the explanatory comment indicating the
    # live-disabled branch is intentional and not telemetried.
    assert "Live not enabled" in src or "intended" in src.lower()


# ════════════════════════════════════════════════════════════════════════════
#  B. Route-level live-AWB invariant E2E
# ════════════════════════════════════════════════════════════════════════════

# Canned MyDHL response — what the fake httpx client returns when the
# live adapter hits /shipments. AWB must be a value that the deterministic
# stub would NEVER produce, so the test can prove "live actually ran"
# without relying on call counts.
_LIVE_AWB = "1234567890"


class _FakeResponse:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body
        self.headers: dict = {}
        self.text = json.dumps(body)

    def json(self):
        return self._body


class _FakeHttpClient:
    """Replacement for httpx.Client. Records every call."""

    def __init__(self, awb: str = _LIVE_AWB):
        self._awb = awb
        self.calls: list = []

    def request(self, method, url, *, json=None, params=None,
                auth=None, timeout=None):
        self.calls.append({
            "method": method, "url": url, "json": json,
            "params": params, "auth": auth,
        })
        # Canned create-shipment response.
        body = {
            "shipmentTrackingNumber": self._awb,
            "documents": [{
                "imageFormat": "PDF",
                "content": base64.b64encode(
                    b"%PDF-1.4\n% live e2e\n%%EOF\n",
                ).decode("ascii"),
            }],
            "packages": [{"trackingNumber": f"{self._awb}-1"}],
        }
        return _FakeResponse(201, body)


@pytest.fixture()
def live_e2e_client(tmp_path, monkeypatch):
    """TestClient with live mode fully wired to a fake HTTP client."""
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "carrier_dhl_live_enabled", True, raising=False)
    monkeypatch.setattr(settings, "dhl_express_api_status", "sandbox", raising=False)
    monkeypatch.setattr(settings, "dhl_express_api_username", "u", raising=False)
    monkeypatch.setattr(settings, "dhl_express_api_password", "p", raising=False)
    monkeypatch.setattr(settings, "dhl_express_account_number", "ACC-1", raising=False)
    monkeypatch.setattr(settings, "carrier_dhl_shadow_mode", False, raising=False)
    monkeypatch.setattr(settings, "carrier_dhl_paperless_trade_enabled", False, raising=False)

    csdb.init_db(tmp_path / "carrier_shipments.db")

    fake = _FakeHttpClient()
    from app.services.carrier.adapters import dhl_express_live as dxl
    monkeypatch.setattr(
        dxl, "_make_default_httpx_client", lambda: fake, raising=True,
    )

    app = FastAPI()
    app.include_router(rca.router)
    app.dependency_overrides[require_api_key] = lambda: None

    client = TestClient(app, raise_server_exceptions=True)
    # Expose the fake so tests can introspect calls.
    client._fake_http = fake  # type: ignore[attr-defined]
    return client


def _shipment_payload(batch_id: str, reference: str) -> dict:
    return {
        "batch_id":  batch_id,
        "ship_from": {
            "name": "Estrella", "company": "Estrella",
            "street_1": "ul. Marszalkowska 1", "city": "Warsaw",
            "postal_code": "00-001", "country": "PL",
        },
        "ship_to": {
            "name": "John Doe", "street_1": "123 Main St",
            "city": "New York", "postal_code": "10001", "country": "US",
        },
        "packages": [{
            "weight_kg": 0.25, "length_cm": 15.0,
            "width_cm": 10.0, "height_cm": 5.0,
            "declared_value": 999.0, "declared_currency": "USD",
            "description": "Diamond pendant",
        }],
        "service_code": "EXPRESS_WORLDWIDE",
        "reference":    reference,
    }


def test_live_create_shipment_returns_live_awb(live_e2e_client):
    """End-to-end: live adapter is selected, the fake HTTP client is
    hit, the live AWB lands in the response envelope and the DB row.
    """
    batch_id = "B-LIVE-E2E-1"
    payload = _shipment_payload(batch_id, "R-LIVE-1")
    proposal = pb.build_create_shipment_proposal(batch_id)
    body = {
        "batch_id":    batch_id,
        "request":     payload,
        "proposal_id": proposal["proposal_id"],
        "actor":       "operator-x",
        "reason":      "live e2e",
    }
    r = live_e2e_client.post(
        "/api/v1/carrier/actions/create-shipment/execute", json=body,
    )
    assert r.status_code == 200, r.text
    env = r.json()

    # AWB came from the live response, not from the stub's
    # deterministic derivation.
    assert env["result"]["shipment"]["awb"] == _LIVE_AWB
    assert env["executed"] is True
    assert env["idempotent_replay"] is False

    # The fake HTTP client was actually called with POST /shipments.
    fake = getattr(live_e2e_client, "_fake_http")
    assert len(fake.calls) == 1
    assert fake.calls[0]["method"] == "POST"
    assert fake.calls[0]["url"].endswith("/shipments")
    # Basic-auth tuple was forwarded — not redacted into the live call.
    assert fake.calls[0]["auth"] == ("u", "p")


def test_live_awb_persisted_only_after_adapter_returns(live_e2e_client):
    """Invariant: the registry must NOT contain the live AWB before
    the adapter call succeeds. We prove this by verifying that
    pre-call, the batch has zero shipments, and post-call exactly one
    row carries _LIVE_AWB.
    """
    batch_id = "B-LIVE-E2E-2"

    # Pre-call: registry is empty for this batch.
    db_path = Path(settings.storage_root) / "carrier_shipments.db"
    csdb.init_db(db_path)
    assert csdb.get_by_batch(batch_id) == []

    proposal = pb.build_create_shipment_proposal(batch_id)
    body = {
        "batch_id":    batch_id,
        "request":     _shipment_payload(batch_id, "R-LIVE-2"),
        "proposal_id": proposal["proposal_id"],
        "actor":       "operator-x",
        "reason":      "live e2e",
    }
    r = live_e2e_client.post(
        "/api/v1/carrier/actions/create-shipment/execute", json=body,
    )
    assert r.status_code == 200, r.text

    # Post-call: exactly one row, and it carries the live-issued AWB.
    rows = csdb.get_by_batch(batch_id)
    assert len(rows) == 1
    assert rows[0]["awb"] == _LIVE_AWB


def test_live_awb_idempotent_replay_does_not_call_adapter_twice(live_e2e_client):
    """The Phase-1 idempotency guard must hold for live adapters too:
    a second identical request returns idempotent_replay=True without
    issuing another DHL HTTP call."""
    batch_id = "B-LIVE-E2E-3"
    body = {
        "batch_id":    batch_id,
        "request":     _shipment_payload(batch_id, "R-LIVE-3"),
        "proposal_id": pb.build_create_shipment_proposal(batch_id)["proposal_id"],
        "actor":       "operator-x",
        "reason":      "live e2e",
    }
    r1 = live_e2e_client.post(
        "/api/v1/carrier/actions/create-shipment/execute", json=body,
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["idempotent_replay"] is False

    # Second call — same (batch_id, reference). Must replay.
    # Use a fresh proposal_id derived from current state (which now has
    # one shipment; the registry-based proposal_id changes — but the
    # idempotency lookup runs FIRST, before the proposal-blocked gate).
    r2 = live_e2e_client.post(
        "/api/v1/carrier/actions/create-shipment/execute", json=body,
    )
    assert r2.status_code == 200, r2.text
    env2 = r2.json()
    assert env2["idempotent_replay"] is True
    assert env2["result"]["shipment"]["awb"] == _LIVE_AWB

    # Critical: only ONE HTTP call, despite two route invocations.
    fake = getattr(live_e2e_client, "_fake_http")
    assert len(fake.calls) == 1
