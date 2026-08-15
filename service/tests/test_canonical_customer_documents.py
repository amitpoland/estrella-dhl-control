"""Canonical Packing List + CMR document authority — ownership + regression pins."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "service" / "app"


def test_packing_parties_prefer_draft_overrides_over_customer_master():
    from app.services.commercial_document_parties import resolve_document_parties
    from app.services.commercial_packing_list import build_commercial_packing_document

    draft = SimpleNamespace(
        id=1,
        batch_id="B1",
        client_name="Fallback Client",
        currency="EUR",
        wfirma_proforma_fullnumber="PROF 1/2026",
        wfirma_invoice_number=None,
        issue_date="2026-08-01",
        buyer_override_json=json.dumps({
            "name": "Override Buyer",
            "street": "Buyer St 1",
            "city": "Krakow",
            "zip": "30-001",
            "country": "PL",
            "vat_id": "PL999",
        }),
        ship_to_override_json=json.dumps({
            "name": "Override ShipTo",
            "street": "Ship St 2",
            "city": "Gdansk",
            "zip": "80-001",
            "country": "PL",
        }),
        editable_lines_json=json.dumps([{
            "product_code": "EJL/A-1",
            "design_no": "JR1",
            "item_type": "RNG",
            "qty": 1,
            "unit_price": 10.0,
            "description_en": "Ring",
            "origin": "IN",
        }]),
    )
    company = SimpleNamespace(
        legal_name="Estrella", street="ul. 1", postal_city="Warszawa",
        country="PL", vat_eu="PL1", email="", phone="", nip="PL1",
    )
    # Customer Master would disagree — must NOT win over draft overrides.
    customer = SimpleNamespace(
        name="CM Buyer", vat_number="PL000", nip="PL000",
    )

    with patch(
        "app.services.customer_master.resolve_billing_address",
        return_value={
            "name": "CM Buyer", "street": "CM St", "city": "CM City",
            "postal_code": "00-000", "country": "DE", "email": "", "phone": "",
        },
    ), patch(
        "app.services.customer_master.resolve_delivery_address",
        return_value={
            "name": "CM Ship", "street": "CM Del", "city": "CM DelCity",
            "postal_code": "11-111", "country": "DE",
        },
    ):
        seller, buyer, shipto = resolve_document_parties(
            draft=draft, company=company, customer=customer,
        )
        doc = build_commercial_packing_document(
            draft=draft, storage_root=Path("."), company=company, customer=customer,
        )

    assert buyer["name"] == "Override Buyer"
    assert buyer["vat"] == "PL999"
    assert shipto["name"] == "Override ShipTo"
    assert shipto["city"] == "Gdansk"
    assert doc["buyer"]["name"] == "Override Buyer"
    assert doc["shipto"]["name"] == "Override ShipTo"
    assert seller["name"] == "Estrella"


def test_packing_email_and_hub_share_exporter_function():
    """FUNCTION ownership — email and Hub call the same export entry."""
    cs = (APP / "services" / "customer_send.py").read_text(encoding="utf-8")
    routes = (APP / "api" / "routes_shipment_documents.py").read_text(encoding="utf-8")
    resolver = (APP / "services" / "canonical_customer_documents.py").read_text(encoding="utf-8")
    assert "resolve_canonical_document_bytes" in cs
    assert "export_packing_list_pdf_for_draft" in resolver
    assert "export_packing_list_pdf_for_draft" in routes
    assert "from reportlab" not in (APP / "services" / "commercial_packing_list.py").read_text(
        encoding="utf-8"
    )


def test_cmr_confirmation_and_download_share_exporter_function():
    dcs = (APP / "services" / "delivery_confirmation_service.py").read_text(encoding="utf-8")
    routes = (APP / "api" / "routes_shipment_documents.py").read_text(encoding="utf-8")
    cmr = (APP / "services" / "commercial_cmr.py").read_text(encoding="utf-8")
    assert "resolve_canonical_document_bytes" in dcs
    assert "cmr.pdf" in routes
    assert "render_commercial_cmr_html" in cmr
    assert "html_to_pdf_bytes" in cmr
    # ReportLab must not be the active presentation path.
    assert "from reportlab" not in cmr
    assert "SimpleDocTemplate" not in cmr


def test_cmr_html_contains_classic_fields():
    from app.services.commercial_cmr_html import render_commercial_cmr_html

    html = render_commercial_cmr_html({
        "cmr_no": "CMR-EJ-TEST",
        "doc_ref": "PROF 7/2026",
        "seller": {"name": "Estrella Jewels", "addr": "ul. 1", "city": "Warszawa", "vat": "PL1"},
        "shipto": {"name": "Consignee Co", "addr": "Ship 1", "city": "Berlin", "zip": "10115", "country": "Germany"},
        "buyer": {"vat": "DE123"},
        "carrier": {
            "name": "DHL", "awb": "1234567890", "service": "EXPRESS",
            "incoterm": "DAP", "origin": "Warszawa", "insurance": "Yes — covered",
            "weight_kg": 1.5,
        },
        "lines": [{"item_type": "Ring", "qty": 2, "net_weight": 3.0, "origin": "India"}],
        "goods_summary": "14KT · Diamond",
        "goods_origin_country": "India",
    })
    for needle in (
        "Estrella", "Consignee Co", "Berlin", "Proforma PROF 7/2026",
        "Ring", "Polybag + Jewellery box", "DHL", "1234567890", "DAP",
        "Country of Origin: India", "signature", "CMR · Delivery Note",
    ):
        assert needle in html, needle


def test_cmr_build_uses_draft_ship_to_override(tmp_path):
    from app.services.commercial_cmr import build_cmr_document

    draft = SimpleNamespace(
        id=7,
        batch_id="BATCH_CMR",
        client_name="Client",
        wfirma_proforma_fullnumber="PROF 7/2026",
        buyer_override={"name": "Buyer Co", "vat_id": "PL111", "city": "Warszawa", "street": "B1", "zip": "00-001", "country": "PL"},
        ship_to_override={"name": "Ship Co", "street": "S1", "city": "Poznan", "zip": "60-001", "country": "PL"},
        editable_lines_json=json.dumps([
            {"item_type": "RNG", "qty": 2, "net_weight": 3.0, "origin": "IN", "metal": "18KT/W"},
        ]),
        service_charges_json=json.dumps([{"charge_type": "insurance", "amount": 10}]),
        incoterm="DAP",
    )
    company = SimpleNamespace(
        legal_name="Estrella Jewels", street="ul. Test", postal_city="Warszawa",
        country="PL", vat_eu="PL123", email="a@b.c", phone="", nip="PL123",
    )
    doc = build_cmr_document(
        draft=draft,
        storage_root=tmp_path,
        company=company,
        customer=None,
        shipment_row={"tracking_ref": "1234567890", "provider": "DHL", "service_product": "EXPRESS", "weight_kg": 2},
        cmr_number="CMR-EJ-TEST",
    )
    assert doc["shipto"]["name"] == "Ship Co"
    assert doc["shipto"]["city"] == "Poznan"
    assert doc["buyer"]["vat"] == "PL111"
    assert doc["carrier"]["awb"] == "1234567890"
    assert doc["carrier"]["incoterm"] == "DAP"
    assert doc["carrier"]["insurance"]
    assert "India" in (doc["goods_origin_country"] or "")


def test_resolve_canonical_document_bytes_packing(tmp_path, monkeypatch):
    from app.services.canonical_customer_documents import resolve_canonical_document_bytes

    draft = SimpleNamespace(
        id=99,
        batch_id="BATCH_R",
        client_name="C",
        currency="EUR",
        wfirma_proforma_fullnumber="PROF 99/2026",
        editable_lines_json=json.dumps([{
            "product_code": "X", "design_no": "D", "item_type": "RNG",
            "qty": 1, "unit_price": 5.0, "description_en": "R", "origin": "IN",
        }]),
    )
    company = SimpleNamespace(
        legal_name="E", street="s", postal_city="W", country="PL",
        vat_eu="PL1", email="", phone="", nip="PL1",
    )

    class _DP:
        @staticmethod
        def _load_company_profile(_r):
            return company

        @staticmethod
        def _load_proforma_draft(_b, _c, _r):
            return draft

        @staticmethod
        def _resolve_customer_from_batch(_b, _c, _r):
            return None

    monkeypatch.setattr(
        "app.services.commercial_packing_list.doc_package", _DP, raising=False,
    )
    import app.services.carrier.doc_package as dp_mod
    monkeypatch.setattr(dp_mod, "_load_company_profile", _DP._load_company_profile)
    monkeypatch.setattr(dp_mod, "_load_proforma_draft", _DP._load_proforma_draft)
    monkeypatch.setattr(dp_mod, "_resolve_customer_from_batch", _DP._resolve_customer_from_batch)

    def _fake_get_draft(_db, did):
        assert int(did) == 99
        return draft

    monkeypatch.setattr(
        "app.services.proforma_invoice_link_db.get_draft_by_id", _fake_get_draft,
    )
    # Avoid Chrome dependency in CI/unit — stub the final PDF render.
    monkeypatch.setattr(
        "app.services.commercial_packing_list.render_commercial_packing_list_pdf",
        lambda _doc: b"%PDF-CANON-PACK",
    )
    pdf, name = resolve_canonical_document_bytes(
        "packing_list", 99, storage_root=tmp_path,
    )
    assert pdf == b"%PDF-CANON-PACK"
    assert name.endswith(".pdf")


def test_no_second_cmr_or_packing_module_names():
    services = APP / "services"
    forbidden = (
        "packing_list_v2.py", "cmr_v2.py", "email_packing_list.py",
        "email_cmr.py", "customer_document_copy.py",
    )
    for name in forbidden:
        assert not (services / name).exists(), name


def test_frontend_cmr_download_uses_server_route():
    api = (APP / "static" / "v2" / "pz-api.js").read_text(encoding="utf-8")
    detail = (APP / "static" / "v2" / "proforma-detail.jsx").read_text(encoding="utf-8")
    assert "downloadCmrPdf" in api
    assert "cmr.pdf" in api
    assert "downloadCmrPdf" in detail


def test_future_shipment_independent_of_specific_refs(tmp_path):
    """Second unrelated fixture — no PROF/AWB-specific branches."""
    from app.services.commercial_packing_list import build_commercial_packing_document
    from app.services.commercial_cmr import build_cmr_document

    draft_a = SimpleNamespace(
        id=1, batch_id="BATCH_A", client_name="Alpha", currency="EUR",
        wfirma_proforma_fullnumber="PROF A/1", issue_date="2026-01-01",
        buyer_override={"name": "Alpha Buyer", "vat_id": "PL1", "street": "A", "city": "A", "zip": "1", "country": "PL"},
        ship_to_override={},
        editable_lines_json=json.dumps([{"item_type": "RNG", "qty": 1, "unit_price": 1, "product_code": "A", "design_no": "A", "origin": "IN"}]),
    )
    draft_b = SimpleNamespace(
        id=2, batch_id="BATCH_B", client_name="Beta", currency="USD",
        wfirma_proforma_fullnumber="PROF B/2", issue_date="2026-02-02",
        buyer_override={"name": "Beta Buyer", "vat_id": "DE9", "street": "B", "city": "B", "zip": "2", "country": "DE"},
        ship_to_override={"name": "Beta Ship", "street": "BS", "city": "Munich", "zip": "80331", "country": "DE"},
        editable_lines_json=json.dumps([{"item_type": "PNG", "qty": 3, "unit_price": 2, "product_code": "B", "design_no": "B", "origin": "IN", "net_weight": 1.1}]),
        incoterm="CIP",
    )
    company = SimpleNamespace(
        legal_name="Estrella", street="s", postal_city="W", country="PL",
        vat_eu="PL1", email="", phone="", nip="PL1",
    )
    pa = build_commercial_packing_document(draft=draft_a, storage_root=tmp_path, company=company)
    pb = build_commercial_packing_document(draft=draft_b, storage_root=tmp_path, company=company)
    assert pa["buyer"]["name"] == "Alpha Buyer"
    assert pb["shipto"]["name"] == "Beta Ship"
    assert pa["currency"] == "EUR" and pb["currency"] == "USD"

    ca = build_cmr_document(
        draft=draft_a, storage_root=tmp_path, company=company,
        shipment_row={"tracking_ref": "111", "provider": "DHL"}, cmr_number="CMR-A",
    )
    cb = build_cmr_document(
        draft=draft_b, storage_root=tmp_path, company=company,
        shipment_row={"tracking_ref": "222", "provider": "DHL"}, cmr_number="CMR-B",
    )
    assert ca["cmr_no"] == "CMR-A" and cb["cmr_no"] == "CMR-B"
    assert cb["shipto"]["city"] == "Munich"
    assert cb["carrier"]["incoterm"] == "CIP"
