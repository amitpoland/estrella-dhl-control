"""
AWB label/document download contract tests.

Covers:
  - POST /shipment response contract additions: replayed, label_download_url,
    commercial_documents_url, saved_labels_exist (no filesystem paths)
  - GET /{batch}/label/{ref} download endpoint: PDF content-type, 404 on
    missing, traversal rejection, Lesson-G no-store headers
  - GET /{batch}/documents: 404 when no saved package; ZIP/PDF when present
  - coordinator replay carries replayed=True (zero adapter calls pinned in
    test_carrier_awb_replay.py)
  - modal source pins: download buttons, replay banner, legacy message

No live DHL calls anywhere. All storage under tmp_path.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api import routes_carrier_actions as rca
from app.services.carrier.coordinator import CarrierCoordinator, CoordinatorConfig
from app.services.carrier.factory import CarrierConfig
from app.services.carrier.models.shipment import ShipmentRequest, ShipmentState


JSX = Path(__file__).resolve().parents[1] / "app" / "static" / "v2" / "proforma-detail.jsx"

BATCH = "SHIPMENT_TEST_2026-07_abcd1234"
REF = "1234567890"


@contextmanager
def _storage(tmp_path):
    mock = MagicMock()
    mock.carrier_storage_root = None
    mock.storage_root = tmp_path
    with patch("app.core.config.settings", mock):
        yield mock


def _make_label(tmp_path, batch=BATCH, ref=REF) -> Path:
    labels = tmp_path / "carrier" / "labels"
    labels.mkdir(parents=True, exist_ok=True)
    p = labels / f"{batch}-{ref}.pdf"
    p.write_bytes(b"%PDF-1.4 test label")
    return p


# ── download_label endpoint ───────────────────────────────────────────────────


class TestDownloadLabel:
    def test_returns_pdf_with_correct_content_type(self, tmp_path):
        _make_label(tmp_path)
        with _storage(tmp_path):
            resp = rca.download_label(BATCH, REF, _auth=None)
        assert resp.media_type == "application/pdf"
        assert resp.body.startswith(b"%PDF")
        assert f'filename="AWB-{REF}.pdf"' in resp.headers["content-disposition"]

    def test_sets_no_store_cache_headers(self, tmp_path):
        """Lesson G: download endpoints must never be cached."""
        _make_label(tmp_path)
        with _storage(tmp_path):
            resp = rca.download_label(BATCH, REF, _auth=None)
        assert "no-store" in resp.headers["cache-control"]
        assert resp.headers["pragma"] == "no-cache"

    def test_404_when_label_missing(self, tmp_path):
        with _storage(tmp_path):
            with pytest.raises(HTTPException) as exc:
                rca.download_label(BATCH, "9999999999", _auth=None)
        assert exc.value.status_code == 404

    def test_rejects_path_traversal_ref(self, tmp_path):
        _make_label(tmp_path)
        with _storage(tmp_path):
            for evil in ("../secrets", "..%2F..%2Fetc", "a/b", "x" * 100, ""):
                with pytest.raises(HTTPException) as exc:
                    rca.download_label(BATCH, evil, _auth=None)
                assert exc.value.status_code == 404

    def test_rejects_path_traversal_batch(self, tmp_path):
        _make_label(tmp_path)
        with _storage(tmp_path):
            with pytest.raises(HTTPException) as exc:
                rca.download_label("../../etc", REF, _auth=None)
            assert exc.value.status_code == 404

    def test_404_detail_contains_no_filesystem_path(self, tmp_path):
        with _storage(tmp_path):
            with pytest.raises(HTTPException) as exc:
                rca.download_label(BATCH, "9999999999", _auth=None)
        detail = str(exc.value.detail)
        assert str(tmp_path) not in detail
        assert "\\" not in detail and "/" not in detail.replace("'/'", "")


# ── download_commercial_documents endpoint ────────────────────────────────────


class TestDownloadDocuments:
    def test_404_when_no_saved_package(self, tmp_path):
        with _storage(tmp_path):
            with pytest.raises(HTTPException) as exc:
                rca.download_commercial_documents(BATCH, _auth=None)
        assert exc.value.status_code == 404

    def test_serves_saved_pdf_package(self, tmp_path):
        pkg_dir = tmp_path / "carrier" / "doc_packages"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / f"{BATCH}.pdf").write_bytes(b"%PDF-1.4 docs")
        with _storage(tmp_path):
            resp = rca.download_commercial_documents(BATCH, _auth=None)
        assert resp.media_type == "application/pdf"
        assert "no-store" in resp.headers["cache-control"]

    def test_serves_saved_zip_package(self, tmp_path):
        pkg_dir = tmp_path / "carrier" / "doc_packages"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / f"{BATCH}.zip").write_bytes(b"PK\x03\x04docs")
        with _storage(tmp_path):
            resp = rca.download_commercial_documents(BATCH, _auth=None)
        assert resp.media_type == "application/zip"


# ── URL helpers: contract shape, no fs paths ──────────────────────────────────


class TestUrlHelpers:
    def test_label_file_resolves_only_inside_labels_dir(self, tmp_path):
        _make_label(tmp_path)
        with _storage(tmp_path):
            assert rca._label_file(BATCH, REF) is not None
            assert rca._label_file(BATCH, "../" + REF) is None
            assert rca._label_file("..", REF) is None

    def test_batch_has_any_label(self, tmp_path):
        with _storage(tmp_path):
            assert rca._batch_has_any_label(BATCH) is False
        _make_label(tmp_path)
        with _storage(tmp_path):
            assert rca._batch_has_any_label(BATCH) is True

    def test_response_urls_are_relative_api_paths(self):
        """Pin the URL contract format — never a filesystem path."""
        src = (Path(rca.__file__)).read_text(encoding="utf-8")
        assert '"/api/v1/carrier/{batch_id}/label/{tracking_ref}"' in src.replace("f\"", "\"")
        assert "label_download_url" in src
        assert "commercial_documents_url" in src
        assert "saved_labels_exist" in src


# ── coordinator replay flag ───────────────────────────────────────────────────


class TestReplayedFlag:
    def _shadow(self, tmp_path):
        return CarrierCoordinator(CoordinatorConfig(
            carrier_config=CarrierConfig(status="shadow"),
            shipment_db_path=tmp_path / "s.db",
            shadow_log_db_path=tmp_path / "l.db",
        ))

    def _req(self):
        return ShipmentRequest(
            batch_id=BATCH, shipper_account="427294774",
            recipient_address={"name": "T", "country": "PL"},
            declared_value=10.0, currency="EUR", weight_kg=1.0,
            dimensions={"length_cm": 10, "width_cm": 10, "height_cm": 10},
        )

    def test_first_call_not_replayed(self, tmp_path):
        r = self._shadow(tmp_path).create_shipment(self._req())
        assert r.replayed is False
        assert r.state == ShipmentState.COMPLETE

    def test_second_call_is_replayed(self, tmp_path):
        coord = self._shadow(tmp_path)
        coord.create_shipment(self._req())
        r2 = coord.create_shipment(self._req())
        assert r2.replayed is True
        assert r2.state == ShipmentState.COMPLETE


# ── modal source pins ─────────────────────────────────────────────────────────


class TestModalSourcePins:
    def _src(self):
        return JSX.read_text(encoding="utf-8")

    def test_download_label_button_present(self):
        src = self._src()
        # 2026-07-06 document package: buttons render from a URL list —
        # the testid is an array literal, the URL source unchanged.
        assert "'awb-download-label'" in src
        assert "result.label_download_url" in src

    def test_commercial_documents_button_conditional(self):
        src = self._src()
        assert "'awb-download-documents'" in src
        assert "result.commercial_documents_url" in src  # renders only when non-null (list map)

    def test_replay_banner_present(self):
        src = self._src()
        assert "AWB Already Exists" in src
        assert "no new DHL shipment was created" in src

    def test_legacy_completed_message_present(self):
        src = self._src()
        assert 'data-testid="awb-legacy-completed"' in src
        assert "AWB completed earlier" in src

    def test_replay_reaches_result_view_not_error(self):
        """data.replayed must route to setResult — never the error branch."""
        src = self._src()
        assert "(data.tracking_ref || data.replayed)" in src

    def test_no_filesystem_paths_in_modal(self):
        src = self._src()
        assert "C:\\\\PZ" not in src and "storage/carrier/labels" not in src


# ── AWB logistics visibility (GET contract + persistence) ─────────────────────


class TestShipmentLogisticsContract:
    """GET /shipment returns the AWB logistics/document contract from the
    stored row; POST persists weight/value/currency/box for it."""

    def _create_shadow(self, tmp_path, box_code="BOX-S"):
        (tmp_path / "carrier").mkdir(parents=True, exist_ok=True)
        coord = CarrierCoordinator(CoordinatorConfig(
            carrier_config=CarrierConfig(status="shadow"),
            shipment_db_path=tmp_path / "carrier" / "carrier_shipments.db",
            shadow_log_db_path=tmp_path / "carrier" / "shadow_log.db",
        ))
        req = ShipmentRequest(
            batch_id=BATCH, shipper_account="427294774",
            recipient_address={"name": "T", "country": "PL"},
            declared_value=43.0, currency="EUR", weight_kg=0.3,
            dimensions={"length_cm": 25, "width_cm": 20, "height_cm": 3},
            box_type_code=box_code,
        )
        return coord.create_shipment(req)

    def test_post_persists_logistics_fields(self, tmp_path):
        with _storage(tmp_path):
            self._create_shadow(tmp_path)
        import sqlite3
        con = sqlite3.connect(str(tmp_path / "carrier" / "carrier_shipments.db"))
        con.row_factory = sqlite3.Row
        row = dict(con.execute("SELECT * FROM carrier_shipments").fetchone())
        assert row["weight_kg"] == 0.3
        assert row["declared_value"] == 43.0
        assert row["currency"] == "EUR"
        assert row["box_type_code"] == "BOX-S"

    def test_get_shipment_returns_logistics_contract(self, tmp_path):
        with _storage(tmp_path):
            created = self._create_shadow(tmp_path)
            resp = rca.get_shipment(
                BATCH, _auth=None, _config=None,
                db_path=tmp_path / "carrier" / "carrier_shipments.db",
            )
        import json
        data = json.loads(resp.body)
        assert data["carrier"] == "DHL"
        assert data["tracking_ref"] == created.tracking_ref
        assert data["weight_kg"] == 0.3
        assert data["declared_value"] == 43.0
        assert data["currency"] == "EUR"
        assert data["box_type_code"] == "BOX-S"
        assert data["dimensions"] == {"length_cm": 25, "width_cm": 20, "height_cm": 3}
        assert data["created_at"]
        assert data["documents_available"] is False
        assert data["commercial_documents_url"] is None
        # No filesystem paths anywhere in the payload
        assert str(tmp_path) not in resp.body.decode()

    def test_get_shipment_label_url_when_label_saved(self, tmp_path):
        with _storage(tmp_path):
            created = self._create_shadow(tmp_path)
            _make_label(tmp_path, BATCH, created.tracking_ref)
            resp = rca.get_shipment(
                BATCH, _auth=None, _config=None,
                db_path=tmp_path / "carrier" / "carrier_shipments.db",
            )
        import json
        data = json.loads(resp.body)
        assert data["label_download_url"] == f"/api/v1/carrier/{BATCH}/label/{created.tracking_ref}"

    def test_live_adapter_records_service_product(self, tmp_path):
        """The resolved DHL product code is persisted for the Logistics tab."""
        (tmp_path / "carrier").mkdir(parents=True, exist_ok=True)
        coord = CarrierCoordinator(CoordinatorConfig(
            carrier_config=CarrierConfig(
                status="live", api_key="k", api_secret="s",
                api_url="https://express.api.dhl.com", use_sandbox=False,
                account_number="427294774", live_allowlist="*",
            ),
            shipment_db_path=tmp_path / "carrier" / "carrier_shipments.db",
            shadow_log_db_path=tmp_path / "carrier" / "shadow_log.db",
        ))
        req = ShipmentRequest(
            batch_id=BATCH, shipper_account="427294774",
            recipient_address={"name": "T", "street": "Gedimino 1", "city": "Vilnius",
                               "postal_code": "01000", "country_code": "LT",
                               "phone": "+37060000000"},
            declared_value=43.0, currency="EUR", weight_kg=0.3,
            dimensions={"length_cm": 25, "width_cm": 20, "height_cm": 3},
            product_code="P",
        )
        rates = MagicMock(); rates.is_success = True
        rates.json.return_value = {"products": [{"productCode": "U"}, {"productCode": "K"}]}
        ship = MagicMock(); ship.is_success = True
        ship.json.return_value = {"shipmentTrackingNumber": "AWB-SVC-1", "documents": []}

        with _storage(tmp_path), patch("httpx.Client") as mock_cls:
            client = mock_cls.return_value.__enter__.return_value
            client.get.return_value = rates
            client.post.return_value = ship
            result = coord.create_shipment(req)

        assert result.service_product == "U"
        import sqlite3
        con = sqlite3.connect(str(tmp_path / "carrier" / "carrier_shipments.db"))
        row = con.execute("SELECT service_product FROM carrier_shipments").fetchone()
        assert row[0] == "U"


# ── Logistics / Documents tab source pins ─────────────────────────────────────


class TestTabSourcePins:
    def _src(self):
        return JSX.read_text(encoding="utf-8")

    def test_logistics_awb_summary_present(self):
        src = self._src()
        for tid in ("pf-logistics-awb", "pf-logistics-awb-ref", "pf-logistics-awb-service",
                    "pf-logistics-awb-box", "pf-logistics-awb-mode", "pf-logistics-awb-created"):
            assert f'"{tid}"' in src or f"'{tid}'" in src, f"missing {tid}"

    def test_misleading_backend_pending_text_removed(self):
        src = self._src()
        assert "not a queryable read authority" not in src
        assert 'data-testid="pf-logistics-awb-empty"' in src  # honest empty state instead

    def test_logistics_fetches_recorded_shipment(self):
        src = self._src()
        assert "getCarrierShipment" in src
        assert "loadCarrierShipment" in src

    def test_documents_tab_dhl_label_row(self):
        src = self._src()
        assert "'dhl_label'" in src or '"dhl_label"' in src
        assert "pf-doc-dhl-label-download" in src

    def test_documents_tab_commercial_docs_conditional(self):
        src = self._src()
        assert "'dhl_documents'" in src or '"dhl_documents"' in src
        assert "documents_available" in src
        assert "Not available yet" in src

    def test_box_types_come_from_backend_authority(self):
        src = self._src()
        assert "PzApi.listBoxTypes" in src        # backend Box Master, not hardcoded
        assert "handleBoxSelect" in src           # selection auto-fills dimensions
        assert "box_type_code:      form.box_type_code || null" in src  # persisted with AWB

    def test_result_card_summary_fields(self):
        src = self._src()
        assert 'data-testid="awb-result-summary"' in src
        for label in ("'Batch'", "'Proforma'", "'Customer'", "'Destination'",
                      "'Service'", "'Box type'", "'Declared value'"):
            assert label in src, f"missing result-card row {label}"
