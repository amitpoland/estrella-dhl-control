"""
Phase J tests — carrier route gate behavior.

Tests that pending status returns 503, shadow mode returns simulated results,
GET /shadow/log returns metadata-only entries, GET /status returns current config.

Uses isolated FastAPI test apps with dependency_overrides.
No real carrier API calls. No production storage.

Updated for Campaign 02.5 Workstream 3 — includes AWB address authority flag OFF
to maintain backward compatibility testing.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.routes_carrier_actions import (
    _get_carrier_config,
    _get_coordinator,
    _get_shipment_db_path,
    router as actions_router,
)
from app.api.routes_carrier_shadow import (
    _get_shadow_log_db_path,
    router as shadow_router,
)
from app.core.security import require_api_key
from app.services.carrier.factory import CarrierConfig
from app.services.carrier.models.shipment import (
    ShipmentMode,
    ShipmentResult,
    ShipmentState,
)
from app.services.carrier.persistence import shadow_log_db, shipment_db


# ── Shared dependency stubs ───────────────────────────────────────────────────


def _no_auth() -> None:
    return None


def _shadow_config() -> CarrierConfig:
    return CarrierConfig(status="shadow")


def _pending_config():
    raise HTTPException(
        status_code=503,
        detail="Carrier API is not yet activated (carrier_api_status=pending).",
    )


# ── Test app fixture ──────────────────────────────────────────────────────────


@pytest.fixture()
def test_app():
    """Fresh isolated FastAPI app with both carrier routers per test."""
    app = FastAPI()
    # shadow router first so static paths (/shadow/log, /status) resolve
    # before the dynamic /{batch_id}/shipment pattern.
    app.include_router(shadow_router)
    app.include_router(actions_router)
    app.dependency_overrides[require_api_key] = _no_auth
    return app


# ═══════════════════════════════════════════════════════════════════════════════
# Gate: pending → 503
# ═══════════════════════════════════════════════════════════════════════════════


def test_post_shipment_pending_returns_503(test_app):
    test_app.dependency_overrides[_get_carrier_config] = _pending_config
    client = TestClient(test_app, raise_server_exceptions=False)
    # Mock settings with AWB authority flag OFF for gate test isolation
    with patch('app.core.config.settings') as mock_settings:
        mock_settings.awb_address_authority_enabled = False
        resp = client.post(
            "/api/v1/carrier/BATCH-001/shipment",
            json={
                "shipper_account": "ACC",
                "recipient_address": {},
                "declared_value": 100.0,
                "currency": "USD",
                "weight_kg": 1.0,
                "dimensions": {},
            },
        )
    assert resp.status_code == 503


def test_post_shipment_pending_body_mentions_pending(test_app):
    test_app.dependency_overrides[_get_carrier_config] = _pending_config
    client = TestClient(test_app, raise_server_exceptions=False)
    # Mock settings with AWB authority flag OFF for gate test isolation
    with patch('app.core.config.settings') as mock_settings:
        mock_settings.awb_address_authority_enabled = False
        resp = client.post(
            "/api/v1/carrier/BATCH-001/shipment",
            json={
                "shipper_account": "ACC",
                "recipient_address": {},
                "declared_value": 100.0,
                "currency": "USD",
                "weight_kg": 1.0,
                "dimensions": {},
            },
        )
    assert "pending" in resp.text.lower()


def test_get_shipment_pending_returns_503(test_app):
    test_app.dependency_overrides[_get_carrier_config] = _pending_config
    client = TestClient(test_app, raise_server_exceptions=False)
    resp = client.get("/api/v1/carrier/BATCH-001/shipment")
    assert resp.status_code == 503


# ═══════════════════════════════════════════════════════════════════════════════
# POST /shipment — shadow mode
# ═══════════════════════════════════════════════════════════════════════════════


def _shadow_result() -> ShipmentResult:
    return ShipmentResult(
        idempotency_key="a" * 64,
        mode=ShipmentMode.SHADOW,
        state=ShipmentState.COMPLETE,
        tracking_ref="SIM-ABCD1234",
        simulated=True,
    )


def _post_shipment(client: TestClient, batch_id: str = "BATCH-001"):
    # Mock settings with AWB authority flag OFF for shadow mode testing
    with patch('app.core.config.settings') as mock_settings:
        mock_settings.awb_address_authority_enabled = False
        return client.post(
            f"/api/v1/carrier/{batch_id}/shipment",
            json={
                "shipper_account": "ACC",
                "recipient_address": {"city": "Berlin"},
                "declared_value": 200.0,
                "currency": "EUR",
                "weight_kg": 2.0,
                "dimensions": {"length": 10, "width": 10, "height": 10},
            },
        )


def test_post_shipment_shadow_returns_200(test_app):
    mock_coordinator = MagicMock()
    mock_coordinator.create_shipment.return_value = _shadow_result()
    test_app.dependency_overrides[_get_carrier_config] = _shadow_config
    test_app.dependency_overrides[_get_coordinator] = lambda: mock_coordinator
    client = TestClient(test_app)
    assert _post_shipment(client).status_code == 200


def test_post_shipment_shadow_returns_simulated_true(test_app):
    mock_coordinator = MagicMock()
    mock_coordinator.create_shipment.return_value = _shadow_result()
    test_app.dependency_overrides[_get_carrier_config] = _shadow_config
    test_app.dependency_overrides[_get_coordinator] = lambda: mock_coordinator
    client = TestClient(test_app)
    assert _post_shipment(client).json()["simulated"] is True


def test_post_shipment_shadow_returns_mode_shadow(test_app):
    mock_coordinator = MagicMock()
    mock_coordinator.create_shipment.return_value = _shadow_result()
    test_app.dependency_overrides[_get_carrier_config] = _shadow_config
    test_app.dependency_overrides[_get_coordinator] = lambda: mock_coordinator
    client = TestClient(test_app)
    assert _post_shipment(client).json()["mode"] == "shadow"


def test_post_shipment_shadow_returns_complete_state(test_app):
    mock_coordinator = MagicMock()
    mock_coordinator.create_shipment.return_value = _shadow_result()
    test_app.dependency_overrides[_get_carrier_config] = _shadow_config
    test_app.dependency_overrides[_get_coordinator] = lambda: mock_coordinator
    client = TestClient(test_app)
    assert _post_shipment(client).json()["state"] == "complete"


def test_post_shipment_returns_batch_id_from_path(test_app):
    mock_coordinator = MagicMock()
    mock_coordinator.create_shipment.return_value = _shadow_result()
    test_app.dependency_overrides[_get_carrier_config] = _shadow_config
    test_app.dependency_overrides[_get_coordinator] = lambda: mock_coordinator
    client = TestClient(test_app)
    assert _post_shipment(client, "MY-BATCH").json()["batch_id"] == "MY-BATCH"


def test_post_shipment_returns_idempotency_key(test_app):
    mock_coordinator = MagicMock()
    mock_coordinator.create_shipment.return_value = _shadow_result()
    test_app.dependency_overrides[_get_carrier_config] = _shadow_config
    test_app.dependency_overrides[_get_coordinator] = lambda: mock_coordinator
    client = TestClient(test_app)
    data = _post_shipment(client).json()
    assert data["idempotency_key"] == "a" * 64


# ═══════════════════════════════════════════════════════════════════════════════
# GET /shipment — state retrieval
# ═══════════════════════════════════════════════════════════════════════════════


def test_get_shipment_not_found_returns_404(test_app, tmp_path):
    db_path = tmp_path / "shipments.db"
    shipment_db.init_db(db_path)
    test_app.dependency_overrides[_get_carrier_config] = _shadow_config
    test_app.dependency_overrides[_get_shipment_db_path] = lambda: db_path
    client = TestClient(test_app, raise_server_exceptions=False)
    resp = client.get("/api/v1/carrier/UNKNOWN-BATCH/shipment")
    assert resp.status_code == 404


def test_get_shipment_returns_200_for_existing(test_app, tmp_path):
    db_path = tmp_path / "shipments.db"
    shipment_db.init_db(db_path)
    result = ShipmentResult(
        idempotency_key="b" * 64,
        mode=ShipmentMode.SHADOW,
        state=ShipmentState.COMPLETE,
        simulated=True,
    )
    shipment_db.insert_shipment(db_path, result, "MY-BATCH")
    test_app.dependency_overrides[_get_carrier_config] = _shadow_config
    test_app.dependency_overrides[_get_shipment_db_path] = lambda: db_path
    client = TestClient(test_app)
    assert client.get("/api/v1/carrier/MY-BATCH/shipment").status_code == 200


def test_get_shipment_returns_correct_batch_id(test_app, tmp_path):
    db_path = tmp_path / "shipments.db"
    shipment_db.init_db(db_path)
    shipment_db.insert_shipment(
        db_path,
        ShipmentResult(idempotency_key="c" * 64, mode=ShipmentMode.SHADOW,
                       state=ShipmentState.COMPLETE, simulated=True),
        "MY-BATCH",
    )
    test_app.dependency_overrides[_get_carrier_config] = _shadow_config
    test_app.dependency_overrides[_get_shipment_db_path] = lambda: db_path
    client = TestClient(test_app)
    assert client.get("/api/v1/carrier/MY-BATCH/shipment").json()["batch_id"] == "MY-BATCH"


def test_get_shipment_returns_state(test_app, tmp_path):
    db_path = tmp_path / "shipments.db"
    shipment_db.init_db(db_path)
    shipment_db.insert_shipment(
        db_path,
        ShipmentResult(idempotency_key="d" * 64, mode=ShipmentMode.SHADOW,
                       state=ShipmentState.COMPLETE, simulated=True),
        "MY-BATCH",
    )
    test_app.dependency_overrides[_get_carrier_config] = _shadow_config
    test_app.dependency_overrides[_get_shipment_db_path] = lambda: db_path
    client = TestClient(test_app)
    assert client.get("/api/v1/carrier/MY-BATCH/shipment").json()["state"] == "complete"


def test_get_shipment_response_has_no_tracking_ref(test_app, tmp_path):
    """GET /shipment must never expose tracking_ref — structural DB invariant."""
    db_path = tmp_path / "shipments.db"
    shipment_db.init_db(db_path)
    shipment_db.insert_shipment(
        db_path,
        ShipmentResult(idempotency_key="e" * 64, mode=ShipmentMode.SHADOW,
                       state=ShipmentState.COMPLETE, simulated=True),
        "MY-BATCH",
    )
    test_app.dependency_overrides[_get_carrier_config] = _shadow_config
    test_app.dependency_overrides[_get_shipment_db_path] = lambda: db_path
    client = TestClient(test_app)
    data = client.get("/api/v1/carrier/MY-BATCH/shipment").json()
    assert "tracking_ref" not in data


def test_get_shipment_returns_simulated_bool(test_app, tmp_path):
    db_path = tmp_path / "shipments.db"
    shipment_db.init_db(db_path)
    shipment_db.insert_shipment(
        db_path,
        ShipmentResult(idempotency_key="f" * 64, mode=ShipmentMode.SHADOW,
                       state=ShipmentState.COMPLETE, simulated=True),
        "MY-BATCH",
    )
    test_app.dependency_overrides[_get_carrier_config] = _shadow_config
    test_app.dependency_overrides[_get_shipment_db_path] = lambda: db_path
    client = TestClient(test_app)
    data = client.get("/api/v1/carrier/MY-BATCH/shipment").json()
    assert data["simulated"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# GET /shadow/log
# ═══════════════════════════════════════════════════════════════════════════════


def test_get_shadow_log_returns_200(test_app, tmp_path):
    db_path = tmp_path / "shadow.db"
    shadow_log_db.init_db(db_path)
    test_app.dependency_overrides[_get_shadow_log_db_path] = lambda: db_path
    client = TestClient(test_app)
    assert client.get("/api/v1/carrier/shadow/log").status_code == 200


def test_get_shadow_log_empty_returns_empty_list(test_app, tmp_path):
    db_path = tmp_path / "shadow.db"
    shadow_log_db.init_db(db_path)
    test_app.dependency_overrides[_get_shadow_log_db_path] = lambda: db_path
    client = TestClient(test_app)
    data = client.get("/api/v1/carrier/shadow/log").json()
    assert data["entries"] == []
    assert data["count"] == 0


def test_get_shadow_log_returns_entries(test_app, tmp_path):
    db_path = tmp_path / "shadow.db"
    shadow_log_db.init_db(db_path)
    shadow_log_db.append_entry(db_path, "BATCH-A", "a" * 64, {"req": 1}, {"resp": 1})
    shadow_log_db.append_entry(db_path, "BATCH-A", "b" * 64, {"req": 2}, {"resp": 2})
    test_app.dependency_overrides[_get_shadow_log_db_path] = lambda: db_path
    client = TestClient(test_app)
    data = client.get("/api/v1/carrier/shadow/log").json()
    assert data["count"] == 2
    assert len(data["entries"]) == 2


def test_get_shadow_log_entries_have_no_json_blobs(test_app, tmp_path):
    """Shadow log entries must not expose request_json or response_json."""
    db_path = tmp_path / "shadow.db"
    shadow_log_db.init_db(db_path)
    shadow_log_db.append_entry(db_path, "BATCH-A", "a" * 64, {"secret": "data"}, {"resp": "val"})
    test_app.dependency_overrides[_get_shadow_log_db_path] = lambda: db_path
    client = TestClient(test_app)
    entries = client.get("/api/v1/carrier/shadow/log").json()["entries"]
    for entry in entries:
        assert "request_json" not in entry
        assert "response_json" not in entry


def test_get_shadow_log_entries_have_expected_keys(test_app, tmp_path):
    db_path = tmp_path / "shadow.db"
    shadow_log_db.init_db(db_path)
    shadow_log_db.append_entry(db_path, "BATCH-A", "a" * 64, {}, {})
    test_app.dependency_overrides[_get_shadow_log_db_path] = lambda: db_path
    client = TestClient(test_app)
    entry = client.get("/api/v1/carrier/shadow/log").json()["entries"][0]
    assert "id" in entry
    assert "batch_id" in entry
    assert "idempotency_key" in entry
    assert "created_at" in entry


def test_get_shadow_log_batch_filter(test_app, tmp_path):
    db_path = tmp_path / "shadow.db"
    shadow_log_db.init_db(db_path)
    shadow_log_db.append_entry(db_path, "BATCH-A", "a" * 64, {}, {})
    shadow_log_db.append_entry(db_path, "BATCH-B", "b" * 64, {}, {})
    test_app.dependency_overrides[_get_shadow_log_db_path] = lambda: db_path
    client = TestClient(test_app)
    data = client.get("/api/v1/carrier/shadow/log?batch_id=BATCH-A").json()
    assert data["count"] == 1
    assert data["entries"][0]["batch_id"] == "BATCH-A"


def test_get_shadow_log_limit_respected(test_app, tmp_path):
    db_path = tmp_path / "shadow.db"
    shadow_log_db.init_db(db_path)
    for i in range(10):
        shadow_log_db.append_entry(db_path, "BATCH-X", f"{'a' * 63}{i}", {}, {})
    test_app.dependency_overrides[_get_shadow_log_db_path] = lambda: db_path
    client = TestClient(test_app)
    data = client.get("/api/v1/carrier/shadow/log?limit=3").json()
    assert data["count"] == 3
    assert len(data["entries"]) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# GET /status
# ═══════════════════════════════════════════════════════════════════════════════


def test_get_status_returns_200(test_app):
    client = TestClient(test_app)
    assert client.get("/api/v1/carrier/status").status_code == 200


def test_get_status_has_carrier_api_status_field(test_app):
    client = TestClient(test_app)
    data = client.get("/api/v1/carrier/status").json()
    assert "carrier_api_status" in data


def test_get_status_has_carrier_plt_status_field(test_app):
    client = TestClient(test_app)
    data = client.get("/api/v1/carrier/status").json()
    assert "carrier_plt_status" in data


def test_get_status_does_not_require_carrier_active(test_app):
    """Status endpoint works even when carrier_api_status=pending."""
    # test_app already has no auth override; no carrier config override needed.
    client = TestClient(test_app)
    resp = client.get("/api/v1/carrier/status")
    assert resp.status_code == 200
