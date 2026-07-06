"""
DHL shipment document package (Transport Label / Waybill Doc / Shipment
Receipt / Commercial Documents) — 2026-07-06.

Pins:
  - the create-shipment body requests label + waybillDoc + receipt image
    options (invoice only when an exportDeclaration exists — inert today)
  - the live adapter saves EVERY returned document separately, one store per
    typeCode; the label keeps its historical location (legacy labels intact)
  - each download endpoint serves application/pdf with Lesson-G no-store
    headers, 404s honestly, rejects traversal, leaks no filesystem path
  - the shipment response contract carries all three per-AWB document URLs
  - a completed replay returns the SAME document URLs with zero new DHL calls
  - Documents tab renders the three DHL rows; modal + Logistics expose buttons

No live DHL calls. All storage under tmp_path.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api import routes_carrier_actions as rca
from app.services.carrier.adapters.live import (
    DhlExpressLiveAdapter,
    _build_shipment_body,
    _save_shipment_documents,
)
from app.services.carrier.coordinator import CarrierCoordinator, CoordinatorConfig
from app.services.carrier.factory import CarrierConfig
from app.services.carrier.models.shipment import ShipmentRequest


JSX = Path(__file__).resolve().parents[1] / "app" / "static" / "v2" / "proforma-detail.jsx"
LIVE = Path(__file__).resolve().parents[1] / "app" / "services" / "carrier" / "adapters" / "live.py"

BATCH = "SHIPMENT_DOCPKG_2026-07_abcd1234"
REF = "1368741791"
_B64 = base64.b64encode(b"%PDF-1.4 test doc").decode()


def _req():
    return ShipmentRequest(
        batch_id=BATCH, shipper_account="427294774",
        recipient_address={
            "name": "Test Receiver", "street": "Gedimino 1", "city": "Vilnius",
            "postal_code": "01000", "country_code": "LT",
            "phone": "+37060000000", "email": "ops@example.com",
        },
        declared_value=100.0, currency="EUR", weight_kg=1.0,
        dimensions={"length_cm": 10, "width_cm": 10, "height_cm": 10},
        product_code="U",
    )


def _fake_settings(tmp_path):
    mock = MagicMock()
    mock.dhl_express_shipper_name = "Estrella Jewels"
    mock.dhl_express_shipper_address1 = "ul. Sabaly 58"
    mock.dhl_express_shipper_city = "Warszawa"
    mock.dhl_express_shipper_postal_code = "02-174"
    mock.dhl_express_shipper_country_code = "PL"
    mock.dhl_express_shipper_phone = "+48516081994"
    mock.carrier_storage_root = None
    mock.storage_root = tmp_path
    return mock


@contextmanager
def _storage(tmp_path):
    with patch("app.core.config.settings", _fake_settings(tmp_path)):
        yield


def _dhl_response(doc_types=("label", "waybillDoc", "receipt")):
    return {
        "shipmentTrackingNumber": REF,
        "documents": [
            {"typeCode": t, "imageFormat": "PDF", "content": _B64} for t in doc_types
        ],
    }


# ── request body: image options ───────────────────────────────────────────────


class TestImageOptionsRequested:
    def test_body_requests_label_waybill_and_receipt(self, tmp_path):
        body = _build_shipment_body(_req(), _fake_settings(tmp_path))
        opts = body["outputImageProperties"]["imageOptions"]
        types = [o["typeCode"] for o in opts]
        assert types[0] == "label"                       # template preserved
        assert opts[0]["templateName"] == "ECOM26_84_001"
        assert "waybillDoc" in types and "receipt" in types
        for o in opts:
            if o["typeCode"] in ("waybillDoc", "receipt"):
                assert o["isRequested"] is True

    def test_invoice_not_requested_without_export_declaration(self, tmp_path):
        body = _build_shipment_body(_req(), _fake_settings(tmp_path))
        types = [o["typeCode"] for o in body["outputImageProperties"]["imageOptions"]]
        assert "invoice" not in types      # no exportDeclaration exists today
        assert "exportDeclaration" not in body["content"]


# ── adapter: each document saved separately ───────────────────────────────────


class TestDocumentsSavedSeparately:
    def test_all_three_documents_saved_to_own_stores(self, tmp_path):
        with _storage(tmp_path):
            _save_shipment_documents(_dhl_response(), BATCH, REF,
                                     _fake_settings(tmp_path))
        assert (tmp_path / "carrier" / "labels" / f"{BATCH}-{REF}.pdf").is_file()
        assert (tmp_path / "carrier" / "waybill_docs" / f"{BATCH}-{REF}.pdf").is_file()
        assert (tmp_path / "carrier" / "shipment_receipts" / f"{BATCH}-{REF}.pdf").is_file()

    def test_invoice_document_lands_in_doc_packages(self, tmp_path):
        _save_shipment_documents(_dhl_response(("invoice",)), BATCH, REF,
                                 _fake_settings(tmp_path))
        assert (tmp_path / "carrier" / "doc_packages" / f"{BATCH}.pdf").is_file()

    def test_unknown_type_skipped_without_error(self, tmp_path):
        _save_shipment_documents(_dhl_response(("qrCode",)), BATCH, REF,
                                 _fake_settings(tmp_path))
        assert not (tmp_path / "carrier" / "qrCode").exists()

    def test_label_keeps_historical_location(self, tmp_path):
        """Legacy compatibility: labels/{batch}-{ref}.pdf unchanged."""
        _save_shipment_documents(_dhl_response(("label",)), BATCH, REF,
                                 _fake_settings(tmp_path))
        p = tmp_path / "carrier" / "labels" / f"{BATCH}-{REF}.pdf"
        assert p.is_file() and p.read_bytes().startswith(b"%PDF")


# ── download endpoints ────────────────────────────────────────────────────────


class TestDocumentEndpoints:
    def _seed(self, tmp_path):
        _save_shipment_documents(_dhl_response(), BATCH, REF, _fake_settings(tmp_path))

    @pytest.mark.parametrize("fn,prefix", [
        (rca.download_label, "AWB"),
        (rca.download_waybill_doc, "WAYBILL"),
        (rca.download_shipment_receipt, "RECEIPT"),
    ])
    def test_each_endpoint_serves_pdf_with_no_store(self, tmp_path, fn, prefix):
        self._seed(tmp_path)
        with _storage(tmp_path):
            resp = fn(BATCH, REF, _auth=None)
        assert resp.media_type == "application/pdf"
        assert resp.body.startswith(b"%PDF")
        assert f'filename="{prefix}-{REF}.pdf"' in resp.headers["content-disposition"]
        assert "no-store" in resp.headers["cache-control"]

    @pytest.mark.parametrize("fn", [
        rca.download_waybill_doc, rca.download_shipment_receipt,
    ])
    def test_404_when_document_absent(self, tmp_path, fn):
        with _storage(tmp_path):
            with pytest.raises(HTTPException) as exc:
                fn(BATCH, "9999999999", _auth=None)
        assert exc.value.status_code == 404
        assert str(tmp_path) not in str(exc.value.detail)   # no fs path leak

    def test_traversal_rejected_on_new_endpoints(self, tmp_path):
        self._seed(tmp_path)
        with _storage(tmp_path):
            for evil in ("../secrets", "a/b", ""):
                with pytest.raises(HTTPException) as exc:
                    rca.download_waybill_doc(BATCH, evil, _auth=None)
                assert exc.value.status_code == 404


# ── response contract + replay ────────────────────────────────────────────────


class TestContractAndReplay:
    def test_shipment_doc_urls_all_three(self, tmp_path):
        _save_shipment_documents(_dhl_response(), BATCH, REF, _fake_settings(tmp_path))
        with _storage(tmp_path):
            urls = rca._shipment_doc_urls(BATCH, REF)
        assert urls == {
            "label_download_url": f"/api/v1/carrier/{BATCH}/label/{REF}",
            "waybill_doc_download_url": f"/api/v1/carrier/{BATCH}/waybill-doc/{REF}",
            "shipment_receipt_download_url": f"/api/v1/carrier/{BATCH}/receipt/{REF}",
        }

    def test_replay_returns_same_doc_urls_without_rebooking(self, tmp_path):
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
        rates = MagicMock(); rates.is_success = True
        rates.json.return_value = {"products": [{"productCode": "U"}]}
        ship = MagicMock(); ship.is_success = True
        ship.json.return_value = _dhl_response()

        with _storage(tmp_path), patch("httpx.Client") as mock_cls:
            client = mock_cls.return_value.__enter__.return_value
            client.get.return_value = rates
            client.post.return_value = ship
            first = coord.create_shipment(_req())
            replay = coord.create_shipment(_req())
            urls_first = rca._shipment_doc_urls(BATCH, first.tracking_ref)
            urls_replay = rca._shipment_doc_urls(BATCH, replay.tracking_ref)

        assert client.post.call_count == 1               # no rebooking
        assert replay.replayed is True
        assert urls_first == urls_replay
        assert urls_replay["waybill_doc_download_url"] is not None
        assert urls_replay["shipment_receipt_download_url"] is not None


# ── UI source pins ────────────────────────────────────────────────────────────


class TestUiPins:
    def _src(self):
        return JSX.read_text(encoding="utf-8")

    def test_documents_tab_has_three_dhl_rows(self):
        src = self._src()
        assert "DHL Transport Label" in src
        assert "DHL Waybill Doc — Hand to Courier" in src
        assert "DHL Shipment Receipt" in src
        assert "'dhl_waybill'" in src and "'dhl_receipt'" in src
        assert "pf-doc-dhl-waybill-download" in src
        assert "pf-doc-dhl-receipt-download" in src

    def test_commercial_documents_row_retained(self):
        src = self._src()
        assert "DHL Commercial Documents" in src
        assert "pf-doc-dhl-documents-download" in src

    def test_modal_result_buttons_for_all_documents(self):
        src = self._src()
        for tid in ("awb-download-label", "awb-download-waybill",
                    "awb-download-receipt", "awb-download-documents"):
            assert tid in src

    def test_logistics_tab_waybill_and_receipt_buttons(self):
        src = self._src()
        assert "pf-logistics-awb-waybill-download" in src
        assert "pf-logistics-awb-receipt-download" in src
        assert "pf-logistics-awb-label-download" in src   # kept

    def test_adapter_requests_full_document_set(self):
        live = LIVE.read_text(encoding="utf-8")
        assert '"typeCode": "waybillDoc", "isRequested": True' in live
        assert '"typeCode": "receipt", "isRequested": True' in live
        assert '"typeCode": "invoice", "isRequested": True' in live  # conditional
