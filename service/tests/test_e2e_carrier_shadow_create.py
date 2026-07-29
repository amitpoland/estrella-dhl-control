"""
Phase D end-to-end tests — full shadow create_shipment flow.

Exercises the complete coordinator path from request to persisted result.
Verifies correctness of every layer: result contract, DB state, shadow log
content, redaction, and the absence of any live data in persistence.
All DB paths use tmp_path. No HTTP. No production storage.

Note: These tests bypass HTTP routes and call coordinator directly, so they
are unaffected by AWB address authority changes (Campaign 02.5 Workstream 3).
The recipient_address flows directly to the coordinator as-is.
"""
import json

import pytest

from app.services.carrier.coordinator import CarrierCoordinator, CoordinatorConfig
from app.services.carrier.factory import CarrierConfig
from app.services.carrier.models.shipment import (
    ShipmentMode,
    ShipmentRequest,
    ShipmentState,
    compute_idempotency_key,
)
from app.services.carrier.persistence.shadow_log_db import (
    count as shadow_count,
    get_entries_for_batch,
)
from app.services.carrier.persistence.shipment_db import get_shipment


def _cfg(tmp_path) -> CoordinatorConfig:
    return CoordinatorConfig(
        carrier_config=CarrierConfig(status="shadow"),
        shipment_db_path=tmp_path / "shipments.db",
        shadow_log_db_path=tmp_path / "shadow.db",
    )


def _req(batch_id: str = "BATCH-E2E") -> ShipmentRequest:
    return ShipmentRequest(
        batch_id=batch_id,
        shipper_account="ACC-E2E",
        recipient_address={"name": "Estrella Jewels", "country": "PL"},
        declared_value=2500.0,
        currency="USD",
        weight_kg=0.5,
        dimensions={"length": 15, "width": 10, "height": 5},
    )


# ── result contract ───────────────────────────────────────────────────────────


def test_result_state_is_complete(tmp_path):
    result = CarrierCoordinator(_cfg(tmp_path)).create_shipment(_req())
    assert result.state == ShipmentState.COMPLETE


def test_result_mode_is_shadow(tmp_path):
    result = CarrierCoordinator(_cfg(tmp_path)).create_shipment(_req())
    assert result.mode == ShipmentMode.SHADOW


def test_result_simulated_is_true(tmp_path):
    result = CarrierCoordinator(_cfg(tmp_path)).create_shipment(_req())
    assert result.simulated is True


def test_result_tracking_ref_starts_with_sim(tmp_path):
    result = CarrierCoordinator(_cfg(tmp_path)).create_shipment(_req())
    assert result.tracking_ref is not None
    assert result.tracking_ref.startswith("SIM-")


def test_result_idempotency_key_matches_compute(tmp_path):
    req = _req()
    result = CarrierCoordinator(_cfg(tmp_path)).create_shipment(req)
    assert result.idempotency_key == compute_idempotency_key(req)


def test_result_has_no_error(tmp_path):
    result = CarrierCoordinator(_cfg(tmp_path)).create_shipment(_req())
    assert result.error is None


# ── shipment_db state ─────────────────────────────────────────────────────────


def test_shipment_db_row_exists_after_create(tmp_path):
    cfg = _cfg(tmp_path)
    req = _req()
    CarrierCoordinator(cfg).create_shipment(req)
    key = compute_idempotency_key(req)
    row = get_shipment(tmp_path / "shipments.db", key)
    assert row is not None


def test_shipment_db_row_state_is_complete(tmp_path):
    cfg = _cfg(tmp_path)
    req = _req()
    CarrierCoordinator(cfg).create_shipment(req)
    key = compute_idempotency_key(req)
    row = get_shipment(tmp_path / "shipments.db", key)
    assert row["state"] == "complete"


def test_shipment_db_row_mode_is_shadow(tmp_path):
    cfg = _cfg(tmp_path)
    req = _req()
    CarrierCoordinator(cfg).create_shipment(req)
    key = compute_idempotency_key(req)
    row = get_shipment(tmp_path / "shipments.db", key)
    assert row["mode"] == "shadow"


# ── shadow log content ────────────────────────────────────────────────────────


def test_shadow_log_has_one_entry(tmp_path):
    cfg = _cfg(tmp_path)
    CarrierCoordinator(cfg).create_shipment(_req())
    assert shadow_count(tmp_path / "shadow.db") == 1


def test_shadow_log_batch_id_matches_request(tmp_path):
    cfg = _cfg(tmp_path)
    CarrierCoordinator(cfg).create_shipment(_req("BATCH-LOG"))
    entries = get_entries_for_batch(tmp_path / "shadow.db", "BATCH-LOG")
    assert len(entries) == 1


def test_shadow_log_request_json_contains_batch_id(tmp_path):
    cfg = _cfg(tmp_path)
    CarrierCoordinator(cfg).create_shipment(_req("BATCH-REQ"))
    entries = get_entries_for_batch(tmp_path / "shadow.db", "BATCH-REQ")
    req_payload = json.loads(entries[0]["request_json"])
    assert req_payload["batch_id"] == "BATCH-REQ"


def test_shadow_log_response_json_is_valid_json(tmp_path):
    cfg = _cfg(tmp_path)
    CarrierCoordinator(cfg).create_shipment(_req())
    entries = get_entries_for_batch(tmp_path / "shadow.db", "BATCH-E2E")
    resp = json.loads(entries[0]["response_json"])
    assert isinstance(resp, dict)


# ── redaction in shadow log ───────────────────────────────────────────────────


def test_shadow_log_response_has_no_label_data(tmp_path):
    """labelData must never appear as a value in the shadow log."""
    cfg = _cfg(tmp_path)
    CarrierCoordinator(cfg).create_shipment(_req())
    entries = get_entries_for_batch(tmp_path / "shadow.db", "BATCH-E2E")
    raw = entries[0]["response_json"]
    # The key may appear (redactor keeps keys, replaces values) but the value
    # must be the redacted sentinel, not real bytes.
    resp = json.loads(raw)
    if "labelData" in resp:
        assert resp["labelData"] == "[REDACTED:binary]"


def test_shadow_log_response_tracking_ref_is_preserved_for_shadow(tmp_path):
    """Shadow sim refs are safe to log — redactor must NOT strip them."""
    cfg = _cfg(tmp_path)
    req = _req()
    result = CarrierCoordinator(cfg).create_shipment(req)
    entries = get_entries_for_batch(tmp_path / "shadow.db", req.batch_id)
    resp = json.loads(entries[0]["response_json"])
    assert resp.get("tracking_ref") == result.tracking_ref


# ── no live data in persistence ───────────────────────────────────────────────


def test_no_live_awb_in_shadow_log(tmp_path):
    """Simulated tracking refs start with SIM- — not a real DHL AWB pattern."""
    cfg = _cfg(tmp_path)
    result = CarrierCoordinator(cfg).create_shipment(_req())
    entries = get_entries_for_batch(tmp_path / "shadow.db", "BATCH-E2E")
    resp = json.loads(entries[0]["response_json"])
    tracking = resp.get("tracking_ref", "")
    assert tracking.startswith("SIM-"), f"Expected SIM- prefix, got: {tracking!r}"


def test_no_http_client_imported_by_coordinator():
    """Coordinator must not import any HTTP library."""
    import inspect
    import app.services.carrier.coordinator as mod
    src = inspect.getsource(mod)
    assert "import httpx" not in src
    assert "import requests" not in src
    assert "urllib.request" not in src
