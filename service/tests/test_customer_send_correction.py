"""Correction campaign: single Packing List authority + air_waybill + CMR on confirmation."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "service"
APP = SERVICE / "app"


def test_customer_sendable_whitelist_has_air_waybill_no_cmr():
    from app.services.customer_send import CUSTOMER_SENDABLE_DOCUMENT_TYPES
    assert "air_waybill" in CUSTOMER_SENDABLE_DOCUMENT_TYPES
    assert "packing_list" in CUSTOMER_SENDABLE_DOCUMENT_TYPES
    assert "cmr" not in CUSTOMER_SENDABLE_DOCUMENT_TYPES
    assert "dhl_waybill" not in CUSTOMER_SENDABLE_DOCUMENT_TYPES


def test_packing_list_export_is_single_authority_and_thin_delegate():
    cs = (APP / "services" / "customer_send.py").read_text(encoding="utf-8")
    assert "resolve_canonical_document_bytes" in cs
    # No independent company/customer/line mapper left in customer_send.
    assert "doc_package.render_packing_list_pdf" not in cs
    assert "_load_company_profile" not in cs
    routes = (APP / "api" / "routes_shipment_documents.py").read_text(encoding="utf-8")
    assert "export_packing_list_pdf_for_draft" in routes


def test_packing_list_email_and_hub_share_fingerprint(tmp_path, monkeypatch):
    from app.services.commercial_packing_list import (
        build_commercial_packing_document,
        export_packing_list_pdf_for_draft,
        fingerprint_commercial_packing_document,
        render_commercial_packing_list_pdf,
    )
    from app.services import customer_send as cs

    lines = [{
        "product_code": "EJL/A-1",
        "design_no": "JR1",
        "item_type": "RNG",
        "qty": 2,
        "unit_price": 10.0,
        "client_po": "PO-1",
        "description_en": "Ring",
        "description_pl": "",
        "karat": "18KT",
        "metal_color": "W",
        "origin": "IN",
    }]
    draft = SimpleNamespace(
        id=42,
        batch_id="BATCH_FP",
        client_name="Client",
        currency="EUR",
        wfirma_proforma_fullnumber="PROF 1/2026",
        wfirma_proforma_id="1",
        wfirma_invoice_number=None,
        issue_date="2026-08-01",
        editable_lines_json=json.dumps(lines),
    )
    company = SimpleNamespace(
        legal_name="Estrella", street="ul. 1", postal_city="Warszawa",
        country="PL", vat_eu="PL1", email="", phone="",
    )

    # Stub Path-DOC loaders so export uses our draft/company.
    class _DP:
        @staticmethod
        def _load_company_profile(_root):
            return company

        @staticmethod
        def _load_proforma_draft(_b, _c, _root):
            return draft

        @staticmethod
        def _resolve_customer_from_batch(_b, _c, _root):
            return None

    monkeypatch.setattr(
        "app.services.commercial_packing_list.doc_package", _DP, raising=False,
    )
    import app.services.carrier.doc_package as dp_mod
    monkeypatch.setattr(dp_mod, "_load_company_profile", _DP._load_company_profile)
    monkeypatch.setattr(dp_mod, "_load_proforma_draft", _DP._load_proforma_draft)
    monkeypatch.setattr(dp_mod, "_resolve_customer_from_batch", _DP._resolve_customer_from_batch)

    model = build_commercial_packing_document(
        draft=draft, storage_root=tmp_path, company=company, customer=None,
    )
    # Avoid Chrome dependency — stub PDF bytes for fingerprint/export path.
    monkeypatch.setattr(
        "app.services.commercial_packing_list.render_commercial_packing_list_pdf",
        lambda _doc: b"%PDF-TEST-PACK",
    )
    monkeypatch.setattr(
        "app.services.proforma_invoice_link_db.get_draft_by_id",
        lambda _db, _id: draft,
    )
    pdf_a, name_a, model_export = export_packing_list_pdf_for_draft(
        draft=draft, storage_root=tmp_path,
    )
    pdf_b, name_b = cs.render_packing_list_pdf_bytes(draft, tmp_path)

    assert fingerprint_commercial_packing_document(model) == fingerprint_commercial_packing_document(model_export)
    assert pdf_a[:4] == b"%PDF"
    assert pdf_b[:4] == b"%PDF"
    assert name_a.endswith(".pdf") and name_b.endswith(".pdf")
    assert model_export.get("authority") == model.get("authority")


def test_cmr_pdf_builds_from_canonical_model(tmp_path, monkeypatch):
    from app.services.commercial_cmr import build_cmr_document, render_cmr_pdf

    draft = SimpleNamespace(
        id=7,
        batch_id="BATCH_CMR",
        client_name="Client",
        wfirma_proforma_fullnumber="PROF 7/2026",
        editable_lines_json=json.dumps([
            {"item_type": "RNG", "qty": 2, "net_weight": 3.0, "origin": "IN", "description_en": "Ring"},
            {"item_type": "PNG", "qty": 1, "net_weight": 1.5, "origin": "IN", "description_en": "Pendant"},
        ]),
    )
    company = SimpleNamespace(
        legal_name="Estrella Jewels", street="ul. Test", postal_city="Warszawa",
        country="PL", vat_eu="PL123", email="a@b.c", phone="",
    )
    doc = build_cmr_document(
        draft=draft,
        storage_root=tmp_path,
        company=company,
        customer=None,
        shipment_row={"tracking_ref": "1234567890", "provider": "DHL", "service_product": "EXPRESS"},
        cmr_number="CMR-EJ-TEST",
    )
    assert doc["authority"] == "commercial_cmr"
    assert doc["cmr_no"] == "CMR-EJ-TEST"
    assert doc["carrier"]["awb"] == "1234567890"
    assert len(doc["lines"]) >= 1
    monkeypatch.setattr(
        "app.services.commercial_cmr.html_to_pdf_bytes",
        lambda _html: b"%PDF-CMR-TEST",
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.chrome_html_pdf.html_to_pdf_bytes",
        lambda _html: b"%PDF-CMR-TEST",
    )
    pdf = render_cmr_pdf(doc)
    assert pdf[:4] == b"%PDF"


def test_confirmation_uses_explicit_cmr_attachments_never_none():
    src = (APP / "services" / "delivery_confirmation_service.py").read_text(encoding="utf-8")
    assert "_cmr_attachment_for_draft" in src
    assert "email_type=\"customer_delivery_confirmation\"" in src or "email_type='customer_delivery_confirmation'" in src
    # Must not leave attachments omitted for confirmation.
    assert "attachments=_cmr_attachment_for_draft" in src


def test_ui_has_air_waybill_no_cmr_checkbox():
    src = (APP / "static" / "v2" / "proforma-detail.jsx").read_text(encoding="utf-8")
    assert "air_waybill" in src
    assert 'data-testid={`send-doc-${d.type}`}' in src or 'send-doc-air_waybill' in src
    assert "Send to Customer" in src
    assert "CMR will be attached automatically when available" in src
    # CMR must not be a selectable document type in the fallback list.
    assert "type: 'cmr'" not in src
    assert "Objectassign" not in src


def test_air_waybill_tracking_only_unavailable():
    from app.services.customer_send import _resolve_air_waybill_entry, assert_types_customer_sendable
    from app.services.shipment_document_manifest import GENERATED, PENDING

    manifest = {
        "groups": {
            "commercial": [],
            "transport": [],
            "carrier": [{
                "document_type": "dhl_waybill",
                "status": PENDING,
                "download_available": False,
                "download_url": None,
                "reference": "1234567890",
                "reason": "tracking only",
            }],
        }
    }
    assert _resolve_air_waybill_entry(manifest) is None
    with pytest.raises(ValueError, match="not available"):
        assert_types_customer_sendable(manifest, ["air_waybill"])


def test_confirmation_attachments_none_still_fail_closed(tmp_path, monkeypatch):
    """customer_delivery_confirmation + attachments=None must not inherit audit docs."""
    from settings_factory import make_test_settings
    from service.app.services import email_sender
    import json, uuid

    s = make_test_settings(tmp_path)
    monkeypatch.setattr("service.app.services.email_sender.settings", s)
    monkeypatch.setattr("service.app.core.config.settings", s)

    batch_id = "SHIPMENT_TEST_CONFIRM"
    out = tmp_path / "outputs" / batch_id
    out.mkdir(parents=True)
    customs = out / "DSK.pdf"
    customs.write_bytes(b"%PDF customs")
    (out / "audit.json").write_text(json.dumps({
        "agency_reply_package": {
            "email_id": str(uuid.uuid4()),
            "attachments": [{"label": "DSK", "path": str(customs)}],
        },
        "dhl_reply_package": {"attachments": []},
        "action_proposals": [],
    }), encoding="utf-8")

    entry = {
        "id": str(uuid.uuid4()),
        "email_type": "customer_delivery_confirmation",
        "batch_id": batch_id,
        "attachments": None,
    }
    found, missing = email_sender._attachments_for_queue(entry)
    assert found == []
    assert missing == []


def test_no_duplicate_packing_list_materializer_in_customer_send():
    src = (APP / "services" / "customer_send.py").read_text(encoding="utf-8")
    # Thin delegate only — no second company/customer/line mapper.
    assert "def render_packing_list_pdf_bytes" in src
    assert "resolve_canonical_document_bytes" in src
    assert "build_commercial_packing_document" not in src
    assert "_load_company_profile" not in src


def test_confirmation_awb_resolve_gates_single_client_fallback():
    """Cross-client AWB misbind must not use ungated single-client fallback."""
    dcs = (APP / "services" / "delivery_confirmation_service.py").read_text(encoding="utf-8")
    cmr = (APP / "services" / "commercial_cmr.py").read_text(encoding="utf-8")
    fu = (APP / "services" / "delivery_followup.py").read_text(encoding="utf-8")
    for src in (dcs, cmr, fu):
        assert "_batch_client_count" in src
    assert "allow_single_client_fallback=single_client" in dcs
    assert "allow_single_client_fallback=single_client" in cmr
    assert "allow_single_client_fallback=single_client" in fu
