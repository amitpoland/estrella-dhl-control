"""
2026-07-06 duplicate-AWB incident regression tests.

Two production bugs, both pinned here:

1. Coordinator replay: a completed idempotency key re-invoked
   adapter.create_shipment(). Safe for the shadow adapter; for the LIVE
   adapter every replay booked a brand-new DHL shipment (3 duplicate live
   AWBs). A completed key must return the STORED result with ZERO adapter
   or HTTP calls, and tracking_ref must be persisted at COMPLETE.

2. Frontend: the AWB modal read r.tracking_ref instead of r.data.tracking_ref
   (PzApi wraps responses as {ok, data}), so every SUCCESS rendered as a
   failure — which is what drove the operator retries. Pinned via source
   checks on proforma-detail.jsx.

All DHL HTTP is mocked. No live calls. DB paths use tmp_path only.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.carrier.coordinator import CarrierCoordinator, CoordinatorConfig
from app.services.carrier.factory import CarrierConfig
from app.services.carrier.models.shipment import (
    ShipmentMode,
    ShipmentRequest,
    ShipmentState,
    compute_idempotency_key,
)
from app.services.carrier.persistence.shipment_db import get_shipment


JSX = Path(__file__).resolve().parents[1] / "app" / "static" / "v2" / "proforma-detail.jsx"


def _live_coordinator(tmp_path) -> CarrierCoordinator:
    return CarrierCoordinator(CoordinatorConfig(
        carrier_config=CarrierConfig(
            status="live",
            api_key="test-key",
            api_secret="test-secret",
            api_url="https://express.api.dhl.com",
            use_sandbox=False,
            account_number="427294774",
            live_allowlist="*",
        ),
        shipment_db_path=tmp_path / "shipments.db",
        shadow_log_db_path=tmp_path / "shadow.db",
    ))


def _shadow_coordinator(tmp_path) -> CarrierCoordinator:
    return CarrierCoordinator(CoordinatorConfig(
        carrier_config=CarrierConfig(status="shadow"),
        shipment_db_path=tmp_path / "shipments.db",
        shadow_log_db_path=tmp_path / "shadow.db",
    ))


def _req(batch_id: str = "BATCH-REPLAY") -> ShipmentRequest:
    return ShipmentRequest(
        batch_id=batch_id,
        shipper_account="427294774",
        recipient_address={
            "name": "Test Receiver", "street": "Gedimino 1", "city": "Vilnius",
            "postal_code": "01000", "country_code": "LT", "phone": "+37060000000",
        },
        declared_value=500.0,
        currency="EUR",
        weight_kg=1.5,
        dimensions={"length_cm": 20, "width_cm": 15, "height_cm": 10},
        product_code="U",
    )


@contextmanager
def _mock_settings(tmp_path):
    mock = MagicMock()
    mock.dhl_express_shipper_name = "Estrella Jewels"
    mock.dhl_express_shipper_address1 = "ul. Sabaly 58"
    mock.dhl_express_shipper_city = "Warszawa"
    mock.dhl_express_shipper_postal_code = "02-174"
    mock.dhl_express_shipper_country_code = "PL"
    mock.dhl_express_shipper_phone = "+48516081994"
    mock.carrier_storage_root = None
    mock.storage_root = tmp_path
    with patch("app.core.config.settings", mock):
        yield mock


def _rates_resp(codes):
    resp = MagicMock()
    resp.is_success = True
    resp.json.return_value = {"products": [{"productCode": c} for c in codes]}
    return resp


def _ship_resp(tracking_ref):
    resp = MagicMock()
    resp.is_success = True
    resp.json.return_value = {"shipmentTrackingNumber": tracking_ref, "documents": []}
    return resp


# ── live replay: zero adapter/HTTP calls ─────────────────────────────────────


class TestLiveCompletedReplay:
    def _first_and_replay(self, tmp_path):
        coord = _live_coordinator(tmp_path)
        req = _req()
        with _mock_settings(tmp_path), patch("httpx.Client") as mock_cls:
            mock_client = mock_cls.return_value.__enter__.return_value
            mock_client.get.return_value = _rates_resp(["U", "K"])
            mock_client.post.return_value = _ship_resp("AWB-FIRST-001")
            first = coord.create_shipment(req)
            replay = coord.create_shipment(req)
        return first, replay, mock_client

    def test_replay_makes_zero_http_calls(self, tmp_path):
        """Completed idempotency replay must not touch DHL at all."""
        _, _, client = self._first_and_replay(tmp_path)
        # Exactly ONE shipment POST (the first call); the replay adds none.
        assert client.post.call_count == 1

    def test_replay_returns_same_tracking_ref(self, tmp_path):
        first, replay, _ = self._first_and_replay(tmp_path)
        assert first.tracking_ref == "AWB-FIRST-001"
        assert replay.tracking_ref == "AWB-FIRST-001"
        assert replay.state == ShipmentState.COMPLETE

    def test_replay_reports_live_mode_not_simulated(self, tmp_path):
        _, replay, _ = self._first_and_replay(tmp_path)
        assert replay.mode == ShipmentMode.LIVE
        assert replay.simulated is False

    def test_first_live_success_persists_tracking_ref(self, tmp_path):
        coord = _live_coordinator(tmp_path)
        req = _req()
        key = compute_idempotency_key(req)
        with _mock_settings(tmp_path), patch("httpx.Client") as mock_cls:
            mock_client = mock_cls.return_value.__enter__.return_value
            mock_client.get.return_value = _rates_resp(["U"])
            mock_client.post.return_value = _ship_resp("AWB-PERSIST-77")
            coord.create_shipment(req)

        row = get_shipment(tmp_path / "shipments.db", key)
        assert row is not None
        assert row["state"] == "complete"
        assert row["tracking_ref"] == "AWB-PERSIST-77"
        assert row["mode"] == "live"
        assert row["simulated"] == 0

    def test_replay_with_legacy_row_missing_tracking_ref_makes_no_http_call(self, tmp_path):
        """Pre-migration COMPLETE rows have no tracking_ref — the replay must
        still NOT re-book; it returns COMPLETE with tracking_ref=None."""
        coord = _live_coordinator(tmp_path)
        req = _req()
        key = compute_idempotency_key(req)
        with _mock_settings(tmp_path), patch("httpx.Client") as mock_cls:
            mock_client = mock_cls.return_value.__enter__.return_value
            mock_client.get.return_value = _rates_resp(["U"])
            mock_client.post.return_value = _ship_resp("AWB-LEGACY-1")
            coord.create_shipment(req)

            # Simulate a legacy row: blank out the persisted tracking_ref.
            con = sqlite3.connect(str(tmp_path / "shipments.db"))
            con.execute(
                "UPDATE carrier_shipments SET tracking_ref = NULL WHERE idempotency_key = ?",
                (key,),
            )
            con.commit()
            con.close()

            replay = coord.create_shipment(req)

        assert mock_client.post.call_count == 1  # no second booking
        assert replay.state == ShipmentState.COMPLETE
        assert replay.tracking_ref is None


# ── shadow behavior stays safe ────────────────────────────────────────────────


class TestShadowReplayUnchanged:
    def test_shadow_replay_returns_stored_deterministic_ref(self, tmp_path):
        coord = _shadow_coordinator(tmp_path)
        req = _req("BATCH-SHADOW-REPLAY")
        r1 = coord.create_shipment(req)
        r2 = coord.create_shipment(req)
        assert r1.tracking_ref == r2.tracking_ref
        assert r2.state == ShipmentState.COMPLETE
        assert r2.simulated is True

    def test_shadow_tracking_ref_persisted(self, tmp_path):
        coord = _shadow_coordinator(tmp_path)
        req = _req("BATCH-SHADOW-PERSIST")
        key = compute_idempotency_key(req)
        r1 = coord.create_shipment(req)
        row = get_shipment(tmp_path / "shipments.db", key)
        assert row["tracking_ref"] == r1.tracking_ref


# ── frontend response-shape pins (source checks) ──────────────────────────────


class TestAwbModalResponseShape:
    def _src(self) -> str:
        return JSX.read_text(encoding="utf-8")

    def test_modal_reads_tracking_ref_from_data(self):
        src = self._src()
        assert "data.tracking_ref" in src, (
            "AWB modal must read tracking_ref from the PzApi {ok, data} envelope"
        )

    def test_modal_success_uses_unwrapped_data(self):
        src = self._src()
        assert "setResult(data)" in src, (
            "AWB modal success path must setResult(data) — the unwrapped payload"
        )

    def test_modal_error_reads_r_error(self):
        src = self._src()
        assert "r.error" in src, "error path must preserve PzApi r.error handling"

    def test_old_buggy_success_check_absent(self):
        src = self._src()
        assert "if (r && r.tracking_ref)" not in src, (
            "old success check reads the wrapper, not the payload — this is the "
            "2026-07-06 duplicate-AWB incident bug"
        )
