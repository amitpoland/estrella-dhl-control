"""
Phase D tests — idempotency guarantees of CarrierCoordinator.

Verifies that the coordinator never calls the adapter a second time
for a completed request, recovers from PENDING, and raises clearly
for FAILED.
All DB paths use tmp_path. No HTTP. No production storage.
"""
import dataclasses
from unittest.mock import MagicMock, patch

import pytest

from app.services.carrier.coordinator import CarrierCoordinator, CoordinatorConfig
from app.services.carrier.factory import CarrierConfig
from app.services.carrier.models.shipment import (
    CarrierGateError,
    ShipmentMode,
    ShipmentRequest,
    ShipmentResult,
    ShipmentState,
    compute_idempotency_key,
)
from app.services.carrier.persistence.shadow_log_db import count as shadow_count
from app.services.carrier.persistence.shipment_db import (
    get_shipment,
    insert_shipment,
    update_state,
)


def _shadow_config(tmp_path) -> CoordinatorConfig:
    return CoordinatorConfig(
        carrier_config=CarrierConfig(status="shadow"),
        shipment_db_path=tmp_path / "shipments.db",
        shadow_log_db_path=tmp_path / "shadow.db",
    )


def _req(batch_id: str = "BATCH-IDEM") -> ShipmentRequest:
    return ShipmentRequest(
        batch_id=batch_id,
        shipper_account="ACC-001",
        recipient_address={"name": "Test", "country": "PL"},
        declared_value=999.0,
        currency="USD",
        weight_kg=3.0,
        dimensions={"length": 30, "width": 20, "height": 15},
    )


# ── first call writes PENDING then COMPLETE ───────────────────────────────────


def test_first_call_writes_pending_then_complete(tmp_path):
    coord = CarrierCoordinator(_shadow_config(tmp_path))
    req = _req()
    key = compute_idempotency_key(req)

    result = coord.create_shipment(req)

    row = get_shipment(tmp_path / "shipments.db", key)
    assert row is not None
    assert row["state"] == "complete"
    assert result.state == ShipmentState.COMPLETE


def test_first_call_writes_shadow_log_entry(tmp_path):
    coord = CarrierCoordinator(_shadow_config(tmp_path))
    coord.create_shipment(_req())
    assert shadow_count(tmp_path / "shadow.db") == 1


# ── second call returns cached result without adapter call ────────────────────


def test_second_call_returns_complete(tmp_path):
    coord = CarrierCoordinator(_shadow_config(tmp_path))
    req = _req()
    coord.create_shipment(req)
    result2 = coord.create_shipment(req)
    assert result2.state == ShipmentState.COMPLETE


def test_second_call_does_not_add_shadow_log_entry(tmp_path):
    coord = CarrierCoordinator(_shadow_config(tmp_path))
    req = _req()
    coord.create_shipment(req)
    coord.create_shipment(req)
    # Second call is a cache hit — shadow log must still have exactly one entry.
    assert shadow_count(tmp_path / "shadow.db") == 1


def test_second_call_does_not_create_duplicate_db_row(tmp_path):
    """Only one shipment row per idempotency key."""
    import sqlite3

    coord = CarrierCoordinator(_shadow_config(tmp_path))
    req = _req()
    coord.create_shipment(req)
    coord.create_shipment(req)

    conn = sqlite3.connect(str(tmp_path / "shipments.db"))
    count = conn.execute("SELECT COUNT(*) FROM carrier_shipments").fetchone()[0]
    conn.close()
    assert count == 1


def test_second_call_returns_deterministic_tracking_ref(tmp_path):
    coord = CarrierCoordinator(_shadow_config(tmp_path))
    req = _req()
    r1 = coord.create_shipment(req)
    r2 = coord.create_shipment(req)
    assert r1.tracking_ref == r2.tracking_ref


# ── PENDING recovery ──────────────────────────────────────────────────────────


def test_pending_recovery_completes(tmp_path):
    """Simulate a crash after PENDING insert: coordinator must recover on re-call."""
    cfg = _shadow_config(tmp_path)
    coord = CarrierCoordinator(cfg)
    req = _req()
    key = compute_idempotency_key(req)

    # Manually insert a PENDING row (simulates a crashed coordinator)
    from app.services.carrier.persistence.shipment_db import init_db
    init_db(tmp_path / "shipments.db")
    insert_shipment(
        tmp_path / "shipments.db",
        ShipmentResult(
            idempotency_key=key,
            mode=ShipmentMode.SHADOW,
            state=ShipmentState.PENDING,
            simulated=True,
        ),
        req.batch_id,
    )

    result = coord.create_shipment(req)
    assert result.state == ShipmentState.COMPLETE


def test_pending_recovery_writes_shadow_log(tmp_path):
    cfg = _shadow_config(tmp_path)
    coord = CarrierCoordinator(cfg)
    req = _req()
    key = compute_idempotency_key(req)

    from app.services.carrier.persistence.shipment_db import init_db
    init_db(tmp_path / "shipments.db")
    insert_shipment(
        tmp_path / "shipments.db",
        ShipmentResult(
            idempotency_key=key,
            mode=ShipmentMode.SHADOW,
            state=ShipmentState.PENDING,
            simulated=True,
        ),
        req.batch_id,
    )

    coord.create_shipment(req)
    assert shadow_count(tmp_path / "shadow.db") == 1


# ── FAILED state raises ───────────────────────────────────────────────────────


def test_failed_state_raises_carrier_gate_error(tmp_path):
    cfg = _shadow_config(tmp_path)
    coord = CarrierCoordinator(cfg)
    req = _req()
    key = compute_idempotency_key(req)

    from app.services.carrier.persistence.shipment_db import init_db
    init_db(tmp_path / "shipments.db")
    insert_shipment(
        tmp_path / "shipments.db",
        ShipmentResult(
            idempotency_key=key,
            mode=ShipmentMode.SHADOW,
            state=ShipmentState.PENDING,
            simulated=True,
        ),
        req.batch_id,
    )
    update_state(tmp_path / "shipments.db", key, ShipmentState.FAILED, error="simulated failure")

    with pytest.raises(CarrierGateError, match="previously failed"):
        coord.create_shipment(req)


def test_failed_error_message_includes_error_detail(tmp_path):
    cfg = _shadow_config(tmp_path)
    coord = CarrierCoordinator(cfg)
    req = _req()
    key = compute_idempotency_key(req)

    from app.services.carrier.persistence.shipment_db import init_db
    init_db(tmp_path / "shipments.db")
    insert_shipment(
        tmp_path / "shipments.db",
        ShipmentResult(
            idempotency_key=key,
            mode=ShipmentMode.SHADOW,
            state=ShipmentState.PENDING,
            simulated=True,
        ),
        req.batch_id,
    )
    update_state(tmp_path / "shipments.db", key, ShipmentState.FAILED, error="timeout on DHL")

    with pytest.raises(CarrierGateError) as exc:
        coord.create_shipment(req)
    assert "timeout on DHL" in str(exc.value)


# ── different requests get different rows ─────────────────────────────────────


def test_different_batch_ids_get_independent_rows(tmp_path):
    coord = CarrierCoordinator(_shadow_config(tmp_path))
    r1 = coord.create_shipment(_req("BATCH-A"))
    r2 = coord.create_shipment(_req("BATCH-B"))
    assert r1.idempotency_key != r2.idempotency_key
    assert r1.tracking_ref != r2.tracking_ref
