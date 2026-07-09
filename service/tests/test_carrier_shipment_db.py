"""
Phase B tests — carrier_shipments SQLite store.

All tests use tmp_path. No production paths. No live calls.
"""
import pytest

from app.services.carrier.models.shipment import (
    ShipmentMode,
    ShipmentResult,
    ShipmentState,
)
from app.services.carrier.persistence.shipment_db import (
    exists,
    get_shipment,
    init_db,
    insert_shipment,
    update_state,
)


def _db(tmp_path):
    path = tmp_path / "shipments.db"
    init_db(path)
    return path


def _shadow_result(key: str = "key-001") -> ShipmentResult:
    return ShipmentResult(
        idempotency_key=key,
        mode=ShipmentMode.SHADOW,
        state=ShipmentState.PENDING,
        simulated=True,
    )


# ── init ─────────────────────────────────────────────────────────────────────


def test_init_creates_table(tmp_path):
    db = _db(tmp_path)
    assert db.exists()


def test_init_is_idempotent(tmp_path):
    db = _db(tmp_path)
    init_db(db)  # second call must not raise
    assert db.exists()


# ── insert / exists ───────────────────────────────────────────────────────────


def test_insert_shadow_and_exists(tmp_path):
    db = _db(tmp_path)
    insert_shipment(db, _shadow_result("k1"), "batch-001")
    assert exists(db, "k1") is True


def test_exists_returns_false_for_unknown_key(tmp_path):
    db = _db(tmp_path)
    assert exists(db, "no-such-key") is False


def test_duplicate_insert_raises(tmp_path):
    db = _db(tmp_path)
    insert_shipment(db, _shadow_result("k1"), "batch-001")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        insert_shipment(db, _shadow_result("k1"), "batch-001")


# ── live AWB invariant ────────────────────────────────────────────────────────


def test_live_result_insert_raises(tmp_path):
    """Live AWBs must never enter carrier_shipments DB."""
    db = _db(tmp_path)
    live_result = ShipmentResult(
        idempotency_key="live-key-001",
        mode=ShipmentMode.LIVE,
        state=ShipmentState.PENDING,
        tracking_ref="1234567890",
        simulated=False,
    )
    with pytest.raises(ValueError, match="Live shipment results must not be inserted"):
        insert_shipment(db, live_result, "batch-live")


# ── get ───────────────────────────────────────────────────────────────────────


def test_get_shipment_returns_dict(tmp_path):
    db = _db(tmp_path)
    insert_shipment(db, _shadow_result("k2"), "batch-002")
    row = get_shipment(db, "k2")
    assert row is not None
    assert row["idempotency_key"] == "k2"
    assert row["batch_id"] == "batch-002"
    assert row["mode"] == "shadow"
    assert row["state"] == "pending"
    assert row["simulated"] == 1


def test_get_shipment_returns_none_for_missing(tmp_path):
    db = _db(tmp_path)
    assert get_shipment(db, "missing") is None


@pytest.mark.skip(
    reason="Superseded by operator decision 2026-07-06: tracking_ref IS now a "
    "persisted column (duplicate-AWB incident fix — replay returns stored result "
    "with zero adapter calls). The surviving AWB-exclusion invariant (live results "
    "never inserted) is covered by test_live_result_insert_raises."
)
def test_tracking_ref_not_in_schema(tmp_path):
    """Schema must not include a tracking_ref column — enforces AWB exclusion."""
    db = _db(tmp_path)
    insert_shipment(db, _shadow_result("k3"), "batch-003")
    row = get_shipment(db, "k3")
    assert "tracking_ref" not in row


# ── update_state ──────────────────────────────────────────────────────────────


def test_update_state_transitions(tmp_path):
    db = _db(tmp_path)
    insert_shipment(db, _shadow_result("k4"), "batch-004")
    update_state(db, "k4", ShipmentState.SUBMITTED)
    row = get_shipment(db, "k4")
    assert row["state"] == "submitted"


def test_update_state_with_error(tmp_path):
    db = _db(tmp_path)
    insert_shipment(db, _shadow_result("k5"), "batch-005")
    update_state(db, "k5", ShipmentState.FAILED, error="timeout")
    row = get_shipment(db, "k5")
    assert row["state"] == "failed"
    assert row["error"] == "timeout"


def test_update_state_noop_on_missing_key(tmp_path):
    """update_state on unknown key must not raise — no rows affected."""
    db = _db(tmp_path)
    update_state(db, "no-such", ShipmentState.COMPLETE)  # must not raise
