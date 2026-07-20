"""Phase 5 — Shipment capture hardening tests.

Coverage:
  - ShipmentResult has service_product + dimensions_json fields (source-grep)
  - carrier_shipments table has additive columns (source-grep + DB round-trip)
  - insert_shipment persists service_product + dimensions_json
  - update_shipment_fields stores only non-None args
  - init_db additive ALTER is idempotent
  - Coordinator flow: dimensions_json captured from request in COMPLETE result
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

# ── Source-grep tests ─────────────────────────────────────────────────────────

_MODELS  = Path(__file__).parent.parent / "app" / "services" / "carrier" / "models" / "shipment.py"
_SDB     = Path(__file__).parent.parent / "app" / "services" / "carrier" / "persistence" / "shipment_db.py"
_COORD   = Path(__file__).parent.parent / "app" / "services" / "carrier" / "coordinator.py"

_models_src = _MODELS.read_text(encoding="utf-8")
_sdb_src    = _SDB.read_text(encoding="utf-8")
_coord_src  = _COORD.read_text(encoding="utf-8")


def test_shipment_result_has_service_product():
    assert "service_product" in _models_src


def test_shipment_result_has_dimensions_json():
    assert "dimensions_json" in _models_src


def test_shipment_db_has_additive_columns():
    assert "service_product" in _sdb_src
    assert "dimensions_json" in _sdb_src


def test_shipment_db_has_update_shipment_fields():
    assert "def update_shipment_fields" in _sdb_src


def test_shipment_db_insert_includes_new_fields():
    assert "service_product" in _sdb_src
    assert "dimensions_json" in _sdb_src


def test_coordinator_captures_dimensions_from_request():
    assert "dimensions_json" in _coord_src


def test_coordinator_imports_json():
    assert "import json" in _coord_src


def test_coordinator_calls_update_shipment_fields():
    assert "update_shipment_fields" in _coord_src


# ── DB round-trip tests ───────────────────────────────────────────────────────

def test_init_db_creates_phase5_columns(tmp_path):
    """init_db creates service_product and dimensions_json columns."""
    from app.services.carrier.persistence.shipment_db import init_db

    db = tmp_path / "cs.db"
    init_db(db)

    with sqlite3.connect(str(db)) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(carrier_shipments)")]
    assert "service_product" in cols
    assert "dimensions_json" in cols


def test_init_db_idempotent(tmp_path):
    """Running init_db twice does not raise."""
    from app.services.carrier.persistence.shipment_db import init_db

    db = tmp_path / "cs2.db"
    init_db(db)
    init_db(db)  # idempotent

    with sqlite3.connect(str(db)) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(carrier_shipments)")]
    assert "service_product" in cols
    assert "dimensions_json" in cols


def test_insert_shipment_stores_service_product_and_dimensions(tmp_path):
    """insert_shipment persists service_product and dimensions_json."""
    from app.services.carrier.persistence.shipment_db import init_db, insert_shipment, get_shipment
    from app.services.carrier.models.shipment import ShipmentMode, ShipmentResult, ShipmentState

    db = tmp_path / "cs3.db"
    init_db(db)

    result = ShipmentResult(
        idempotency_key="abc123",
        mode=ShipmentMode.SHADOW,
        state=ShipmentState.PENDING,
        simulated=True,
        service_product="EXPRESS_WORLDWIDE",
        dimensions_json='{"length": 20, "width": 15, "height": 10}',
    )
    insert_shipment(db, result, batch_id="B001")

    row = get_shipment(db, "abc123")
    assert row is not None
    assert row["service_product"] == "EXPRESS_WORLDWIDE"
    dims = json.loads(row["dimensions_json"])
    assert dims["length"] == 20


def test_insert_shipment_nullable_fields(tmp_path):
    """service_product and dimensions_json may be None."""
    from app.services.carrier.persistence.shipment_db import init_db, insert_shipment, get_shipment
    from app.services.carrier.models.shipment import ShipmentMode, ShipmentResult, ShipmentState

    db = tmp_path / "cs4.db"
    init_db(db)

    result = ShipmentResult(
        idempotency_key="def456",
        mode=ShipmentMode.SHADOW,
        state=ShipmentState.PENDING,
        simulated=True,
    )
    insert_shipment(db, result, batch_id="B002")

    row = get_shipment(db, "def456")
    assert row["service_product"] is None
    assert row["dimensions_json"] is None


def test_update_shipment_fields_stores_values(tmp_path):
    """update_shipment_fields writes service_product and dimensions_json."""
    from app.services.carrier.persistence.shipment_db import (
        init_db, insert_shipment, get_shipment, update_shipment_fields,
    )
    from app.services.carrier.models.shipment import ShipmentMode, ShipmentResult, ShipmentState

    db = tmp_path / "cs5.db"
    init_db(db)

    result = ShipmentResult(
        idempotency_key="ghi789",
        mode=ShipmentMode.SHADOW,
        state=ShipmentState.PENDING,
        simulated=True,
    )
    insert_shipment(db, result, batch_id="B003")

    update_shipment_fields(
        db, "ghi789",
        service_product="EXPRESS_12",
        dimensions_json='{"length": 30}',
    )

    row = get_shipment(db, "ghi789")
    assert row["service_product"] == "EXPRESS_12"
    assert json.loads(row["dimensions_json"])["length"] == 30


def test_update_shipment_fields_noop_when_all_none(tmp_path):
    """update_shipment_fields with all-None args is a no-op (no error)."""
    from app.services.carrier.persistence.shipment_db import (
        init_db, insert_shipment, update_shipment_fields,
    )
    from app.services.carrier.models.shipment import ShipmentMode, ShipmentResult, ShipmentState

    db = tmp_path / "cs6.db"
    init_db(db)

    result = ShipmentResult(
        idempotency_key="jkl000",
        mode=ShipmentMode.SHADOW,
        state=ShipmentState.PENDING,
        simulated=True,
    )
    insert_shipment(db, result, batch_id="B004")

    # Should not raise
    update_shipment_fields(db, "jkl000")


def test_coordinator_complete_result_has_dimensions_json(tmp_path):
    """Full coordinator flow: COMPLETE result carries dimensions_json from request."""
    from app.services.carrier.coordinator import CarrierCoordinator, CoordinatorConfig
    from app.services.carrier.factory import CarrierConfig
    from app.services.carrier.models.shipment import ShipmentMode, ShipmentRequest

    carrier_cfg = CarrierConfig(status="shadow")
    cfg = CoordinatorConfig(
        carrier_config=carrier_cfg,
        shipment_db_path=tmp_path / "ship.db",
        shadow_log_db_path=tmp_path / "slog.db",
    )
    coord = CarrierCoordinator(cfg)

    request = ShipmentRequest(
        batch_id="B100",
        shipper_account="ACC",
        recipient_address={"city": "Warsaw"},
        declared_value=500.0,
        currency="EUR",
        weight_kg=1.5,
        dimensions={"length": 25, "width": 20, "height": 15},
    )
    result = coord.create_shipment(request)

    assert result.dimensions_json is not None
    dims = json.loads(result.dimensions_json)
    assert dims["length"] == 25
    assert dims["width"] == 20
