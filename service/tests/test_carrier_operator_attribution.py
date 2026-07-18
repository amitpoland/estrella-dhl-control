"""
Carrier operator attribution (X-Operator) — 2026-07-18.

Post-merge follow-up from PR #940 (transport-m1): carrier booking writes did
not carry an X-Operator attribution header, so the carrier audit trail could
not name the operator who initiated a booking.

Pins:
  DB layer
    - insert_shipment(..., operator=) writes booked_by; absent → NULL.
    - a state transition (update_state) never mutates booked_by.
  Coordinator
    - a fresh booking records the operator and returns it on the result.
    - an idempotent replay preserves the ORIGINAL booker even when a DIFFERENT
      operator triggers the replay (audit integrity — never re-attributed).
    - operator is NOT part of the idempotency key (two operators, same intent,
      resolve to the SAME shipment — no duplicate-AWB risk).
  Route
    - POST /{batch_id}/shipment records + echoes booked_by from X-Operator.
    - a missing header falls back to the stable default "operator".
    - the header is sanitised (printable-only, length-capped) → no audit-log
      injection / unbounded values.
    - GET /{batch_id}/shipment echoes booked_by (null for legacy rows).
  do-not-use write
    - X-Operator is accepted as the fallback for do_not_use_by; the body's
      operator field still wins; neither present → NULL.

No live DHL calls. All storage under tmp_path.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes_carrier_actions import (
    _clean_operator,
    _get_carrier_config,
    _get_coordinator,
    _get_shipment_db_path,
    router as actions_router,
)
from app.core.security import require_api_key
from app.services.carrier.coordinator import CarrierCoordinator, CoordinatorConfig
from app.services.carrier.factory import CarrierConfig
from app.services.carrier.models.shipment import (
    ShipmentMode,
    ShipmentRequest,
    ShipmentResult,
    ShipmentState,
    compute_idempotency_key,
)
from app.services.carrier.persistence import shipment_db


# ── helpers ────────────────────────────────────────────────────────────────────


def _cfg(tmp_path) -> CoordinatorConfig:
    return CoordinatorConfig(
        carrier_config=CarrierConfig(status="shadow"),
        shipment_db_path=tmp_path / "shipments.db",
        shadow_log_db_path=tmp_path / "shadow.db",
    )


def _req(batch_id: str = "BATCH-OP", **over) -> ShipmentRequest:
    kw = dict(
        batch_id=batch_id,
        shipper_account="ACC-OP",
        recipient_address={"name": "Estrella Jewels", "country": "PL"},
        declared_value=2500.0,
        currency="USD",
        weight_kg=0.5,
        dimensions={"length": 15, "width": 10, "height": 5},
    )
    kw.update(over)
    return ShipmentRequest(**kw)


def _shipment_db_path(tmp_path) -> Path:
    root = tmp_path / "carrier"
    root.mkdir(parents=True, exist_ok=True)
    p = root / "carrier_shipments.db"
    shipment_db.init_db(p)
    return p


# ── DB layer ────────────────────────────────────────────────────────────────────


class TestInsertRecordsBookedBy:
    def test_operator_written_to_booked_by(self, tmp_path):
        db = _shipment_db_path(tmp_path)
        res = ShipmentResult(idempotency_key="k1", mode=ShipmentMode.SHADOW,
                             state=ShipmentState.PENDING, simulated=True)
        shipment_db.insert_shipment(db, res, "B1", operator="amit")
        row = shipment_db.get_shipment(db, "k1")
        assert row["booked_by"] == "amit"

    def test_absent_operator_is_null(self, tmp_path):
        db = _shipment_db_path(tmp_path)
        res = ShipmentResult(idempotency_key="k2", mode=ShipmentMode.SHADOW,
                             state=ShipmentState.PENDING, simulated=True)
        shipment_db.insert_shipment(db, res, "B1")
        row = shipment_db.get_shipment(db, "k2")
        assert row["booked_by"] is None

    def test_state_transition_does_not_touch_booked_by(self, tmp_path):
        """update_state must never rewrite the original booker."""
        db = _shipment_db_path(tmp_path)
        res = ShipmentResult(idempotency_key="k3", mode=ShipmentMode.SHADOW,
                             state=ShipmentState.PENDING, simulated=True)
        shipment_db.insert_shipment(db, res, "B1", operator="alice")
        shipment_db.update_state(db, "k3", ShipmentState.COMPLETE,
                                 tracking_ref="SIM-X")
        row = shipment_db.get_shipment(db, "k3")
        assert row["booked_by"] == "alice"
        assert row["state"] == "complete"


# ── Coordinator ─────────────────────────────────────────────────────────────────


class TestCoordinatorAttribution:
    def test_fresh_booking_records_and_returns_operator(self, tmp_path):
        coord = CarrierCoordinator(_cfg(tmp_path))
        result = coord.create_shipment(_req(), operator="alice")
        assert result.booked_by == "alice"
        row = shipment_db.get_shipment(tmp_path / "shipments.db",
                                       compute_idempotency_key(_req()))
        assert row["booked_by"] == "alice"

    def test_replay_preserves_original_booker(self, tmp_path):
        """A replay by a DIFFERENT operator must report the ORIGINAL booker."""
        coord = CarrierCoordinator(_cfg(tmp_path))
        first = coord.create_shipment(_req(), operator="alice")
        assert first.replayed is False
        replay = coord.create_shipment(_req(), operator="mallory")
        assert replay.replayed is True
        assert replay.booked_by == "alice"          # NOT mallory
        row = shipment_db.get_shipment(tmp_path / "shipments.db",
                                       compute_idempotency_key(_req()))
        assert row["booked_by"] == "alice"

    def test_operator_not_in_idempotency_key(self, tmp_path):
        """Two operators booking the same intent resolve to the SAME shipment."""
        coord = CarrierCoordinator(_cfg(tmp_path))
        r1 = coord.create_shipment(_req(), operator="alice")
        r2 = coord.create_shipment(_req(), operator="bob")
        assert r1.idempotency_key == r2.idempotency_key
        assert r2.replayed is True                   # bob replayed alice's row

    def test_missing_operator_stores_null(self, tmp_path):
        coord = CarrierCoordinator(_cfg(tmp_path))
        result = coord.create_shipment(_req())
        assert result.booked_by is None


# ── Sanitiser ────────────────────────────────────────────────────────────────────


class TestCleanOperator:
    def test_default_when_empty(self):
        assert _clean_operator(None) == "operator"
        assert _clean_operator("") == "operator"
        assert _clean_operator("   ") == "operator"

    def test_passthrough_normal_name(self):
        assert _clean_operator("amit") == "amit"

    def test_strips_control_characters(self):
        # newline / tab / null are non-printable → removed (audit-log injection)
        assert _clean_operator("ali\nce\t") == "alice"
        assert _clean_operator("a\x00b") == "ab"

    def test_caps_length(self):
        assert len(_clean_operator("x" * 500)) == 120

    def test_non_string_sentinel_treated_as_absent(self):
        # FastAPI Header sentinel leaks through on a direct unit call.
        assert _clean_operator(object()) == "operator"


# ── Route: POST/GET e2e ─────────────────────────────────────────────────────────


@contextmanager
def _settings(tmp_path):
    mock = MagicMock()
    mock.carrier_storage_root = None
    mock.storage_root = tmp_path
    mock.awb_address_authority_enabled = False
    mock.dhl_express_account_number = "ACC-TEST"
    with patch("app.core.config.settings", mock):
        yield


def _route_app(tmp_path):
    app = FastAPI()
    app.include_router(actions_router)
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[_get_carrier_config] = lambda: CarrierConfig(status="shadow")
    root = tmp_path / "carrier"
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "carrier_shipments.db"
    coord = CarrierCoordinator(CoordinatorConfig(
        carrier_config=CarrierConfig(status="shadow"),
        shipment_db_path=db_path,
        shadow_log_db_path=root / "shadow_log.db",
    ))
    app.dependency_overrides[_get_coordinator] = lambda: coord
    app.dependency_overrides[_get_shipment_db_path] = lambda: db_path
    return app, db_path


_BODY = {
    "shipper_account": "ACC",
    "recipient_address": {"city": "Berlin", "country": "DE"},
    "declared_value": 200.0,
    "currency": "EUR",
    "weight_kg": 2.0,
    "dimensions": {"length": 10, "width": 10, "height": 10},
}


class TestCreateShipmentRoute:
    def test_header_recorded_and_echoed(self, tmp_path):
        app, db_path = _route_app(tmp_path)
        client = TestClient(app)
        with _settings(tmp_path):
            resp = client.post("/api/v1/carrier/BATCH-R1/shipment",
                               json=_BODY, headers={"X-Operator": "amit"})
        assert resp.status_code == 200
        assert resp.json()["booked_by"] == "amit"
        # persisted in the audit row
        row = shipment_db.get_shipment_by_batch_id(db_path, "BATCH-R1")
        assert row["booked_by"] == "amit"

    def test_missing_header_defaults_to_operator(self, tmp_path):
        app, _ = _route_app(tmp_path)
        client = TestClient(app)
        with _settings(tmp_path):
            resp = client.post("/api/v1/carrier/BATCH-R2/shipment", json=_BODY)
        assert resp.json()["booked_by"] == "operator"

    def test_header_sanitised_in_response(self, tmp_path):
        app, _ = _route_app(tmp_path)
        client = TestClient(app)
        with _settings(tmp_path):
            resp = client.post("/api/v1/carrier/BATCH-R3/shipment",
                               json=_BODY, headers={"X-Operator": "a\tb c"})
        # tab removed; spaces are printable and kept
        assert resp.json()["booked_by"] == "ab c"

    def test_get_echoes_booked_by(self, tmp_path):
        app, _ = _route_app(tmp_path)
        client = TestClient(app)
        with _settings(tmp_path):
            client.post("/api/v1/carrier/BATCH-R4/shipment",
                        json=_BODY, headers={"X-Operator": "carol"})
            resp = client.get("/api/v1/carrier/BATCH-R4/shipment")
        assert resp.status_code == 200
        assert resp.json()["booked_by"] == "carol"

    def test_get_legacy_row_booked_by_null(self, tmp_path):
        app, db_path = _route_app(tmp_path)
        # seed a legacy row with no attribution
        res = ShipmentResult(idempotency_key="leg", mode=ShipmentMode.SHADOW,
                             state=ShipmentState.COMPLETE, simulated=True)
        shipment_db.insert_shipment(db_path, res, "BATCH-LEG")
        client = TestClient(app)
        with _settings(tmp_path):
            resp = client.get("/api/v1/carrier/BATCH-LEG/shipment")
        assert resp.status_code == 200
        assert resp.json()["booked_by"] is None


# ── Route: do-not-use fallback ──────────────────────────────────────────────────


class TestDoNotUseOperatorFallback:
    def _seed(self, tmp_path):
        db = _shipment_db_path(tmp_path)
        res = ShipmentResult(idempotency_key="dnu", mode=ShipmentMode.SHADOW,
                             state=ShipmentState.PENDING, simulated=True)
        shipment_db.insert_shipment(db, res, "BATCH-DNU")
        shipment_db.update_state(db, "dnu", ShipmentState.COMPLETE,
                                 tracking_ref="7010522735")
        return db

    def test_header_used_when_body_absent(self, tmp_path):
        from app.api import routes_carrier_actions as rca
        db = self._seed(tmp_path)
        with _settings(tmp_path):
            rca.mark_shipment_do_not_use(
                "BATCH-DNU", "7010522735",
                rca.DoNotUseBody(reason="duplicate"),
                _auth=None, db_path=db, x_operator="hdr-op",
            )
        info = shipment_db.get_do_not_use(db, "BATCH-DNU", "7010522735")
        assert info["do_not_use_by"] == "hdr-op"

    def test_body_wins_over_header(self, tmp_path):
        from app.api import routes_carrier_actions as rca
        db = self._seed(tmp_path)
        with _settings(tmp_path):
            rca.mark_shipment_do_not_use(
                "BATCH-DNU", "7010522735",
                rca.DoNotUseBody(reason="duplicate", operator="body-op"),
                _auth=None, db_path=db, x_operator="hdr-op",
            )
        info = shipment_db.get_do_not_use(db, "BATCH-DNU", "7010522735")
        assert info["do_not_use_by"] == "body-op"

    def test_null_when_neither_present(self, tmp_path):
        from app.api import routes_carrier_actions as rca
        db = self._seed(tmp_path)
        with _settings(tmp_path):
            rca.mark_shipment_do_not_use(
                "BATCH-DNU", "7010522735",
                rca.DoNotUseBody(reason="duplicate"),
                _auth=None, db_path=db,
            )
        info = shipment_db.get_do_not_use(db, "BATCH-DNU", "7010522735")
        assert info["do_not_use_by"] is None
