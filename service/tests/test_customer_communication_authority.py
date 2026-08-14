"""Customer communication authority — AWB + delivery follow-up + shipping info."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

APP = Path(__file__).resolve().parents[1] / "app"


def test_air_waybill_promotes_dhl_transport_label_when_waybill_missing():
    from app.services.customer_send import _resolve_air_waybill_entry
    from app.services.shipment_document_manifest import GENERATED

    manifest = {
        "groups": {
            "carrier": [
                {
                    "document_type": "dhl_label",
                    "status": GENERATED,
                    "download_available": True,
                    "download_url": "/api/v1/carrier/B/label/3302692422",
                    "reference": "3302692422",
                    "source": "DHL",
                },
                {
                    "document_type": "dhl_waybill",
                    "status": "Pending",
                    "download_available": False,
                    "download_url": None,
                    "reference": "3302692422",
                },
            ]
        }
    }
    entry = _resolve_air_waybill_entry(manifest)
    assert entry is not None
    assert entry["document_type"] == "air_waybill"
    assert entry["_store_kind"] == "label"
    assert entry["reference"] == "3302692422"


def test_air_waybill_prefers_waybill_doc_over_label():
    from app.services.customer_send import _resolve_air_waybill_entry
    from app.services.shipment_document_manifest import GENERATED

    manifest = {
        "groups": {
            "carrier": [
                {
                    "document_type": "dhl_label",
                    "status": GENERATED,
                    "download_available": True,
                    "download_url": "/label",
                    "reference": "1",
                },
                {
                    "document_type": "dhl_waybill",
                    "status": GENERATED,
                    "download_available": True,
                    "download_url": "/waybill",
                    "reference": "1",
                },
            ]
        }
    }
    entry = _resolve_air_waybill_entry(manifest)
    assert entry["_store_kind"] == "waybill-doc"


def test_whitelist_has_shipping_information_no_cmr():
    from app.services.customer_send import CUSTOMER_SENDABLE_DOCUMENT_TYPES
    assert "shipping_information" in CUSTOMER_SENDABLE_DOCUMENT_TYPES
    assert "cmr" not in CUSTOMER_SENDABLE_DOCUMENT_TYPES


def test_delivery_followup_delivered_without_confirmation_row(monkeypatch, tmp_path):
    from app.services import delivery_followup as dfu

    monkeypatch.setattr(
        "app.services.delivery_confirmation_db.get_delivery_summary_for_draft",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.proforma_invoice_link_db.get_draft_by_id",
        lambda *a, **k: SimpleNamespace(
            id=80, batch_id="BATCH_X", client_name="Client",
        ),
    )
    monkeypatch.setattr(
        "app.services.shipment_document_manifest._batch_client_count",
        lambda *a, **k: 1,
    )
    monkeypatch.setattr(
        "app.services.carrier.persistence.shipment_db.get_shipment_for_draft",
        lambda *a, **k: {
            "tracking_ref": "3302692422",
            "provider": "DHL",
            "service_product": "U",
        },
    )
    monkeypatch.setattr(
        "app.services.delivery_confirmation_service._prove_outbound_delivered",
        lambda awb: {
            "ok": True,
            "awb": awb,
            "carrier_delivered_at": "2026-08-11T19:22:46",
        },
    )
    monkeypatch.setattr(
        "app.services.tracking_service._load_cache",
        lambda *a, **k: {
            "3302692422": {
                "status": "delivered",
                "last_update": "2026-08-11T19:22:46",
                "last_location": "CASTLEREA - IE",
            }
        },
    )
    monkeypatch.setattr(
        "app.services.tracking_service.select_cached_tracking_record",
        lambda cache, awb: cache.get(awb),
    )

    out = dfu.compose_delivery_followup(
        draft_id=80,
        storage_root=tmp_path,
        proforma_db=tmp_path / "p.db",
        carrier_db=tmp_path / "c.db",
    )
    assert out["carrier"]["delivered"] is True
    assert out["carrier"]["awb"] == "3302692422"
    assert out["confirmation"]["state"] == "not_sent"
    assert out["confirmation"]["can_send"] is True
    assert out["confirmation"]["can_remind"] is False


def test_ui_no_longer_hardcodes_no_delivery_record_alone():
    src = (APP / "static" / "v2" / "proforma-detail.jsx").read_text(encoding="utf-8")
    assert "delivery_followup" in src
    assert "shipping_information" in src
    assert "send-recipients-group" in src
    assert "No delivery record" not in src
    assert "No outbound delivery yet" in src


def test_shipping_information_pdf_builds():
    from app.services.commercial_shipping_information import (
        build_shipping_information_document,
        render_shipping_information_pdf,
    )
    draft = SimpleNamespace(
        id=1, batch_id="B", client_name="Client",
        wfirma_proforma_fullnumber="PROF 1/2026", currency="USD",
    )
    row = {
        "tracking_ref": "3302692422",
        "provider": "DHL",
        "batch_id": "B",
        "service_product": "U",
        "weight_kg": 0.3,
        "dimensions_json": '{"length_cm":25,"width_cm":20,"height_cm":5}',
        "box_type_code": "DHL-BRACELET",
        "declared_value": 1828.0,
        "currency": "USD",
        "created_at": "2026-08-03T11:09:50Z",
        "client_ref": "Client",
    }
    model = build_shipping_information_document(draft=draft, shipment_row=row)
    pdf = render_shipping_information_pdf(model)
    assert pdf[:4] == b"%PDF"
    assert model["authority"] == "commercial_shipping_information"
