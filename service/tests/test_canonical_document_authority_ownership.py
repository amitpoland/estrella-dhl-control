"""Hard ownership pins: one Packing List / CMR projection + presentation."""
from __future__ import annotations

from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
STATIC = APP / "static" / "v2"
SERVICES = APP / "services"
ROUTES = APP / "api" / "routes_shipment_documents.py"


def test_preview_fetches_canonical_html_not_local_projection():
    detail = (STATIC / "proforma-detail.jsx").read_text(encoding="utf-8")
    assert "getPackingListHtml" in detail
    assert "getCmrHtml" in detail
    assert "getCmrDocument" in detail
    assert "canonical-packing-frame" in detail or "canonical-${activeType}-frame" in detail
    # Local document business projections retired
    assert "const packingListData" not in detail
    assert "const cmrPreviewData" not in detail
    assert "packingData={packingListData}" not in detail
    assert "cmrData={cmrPreviewData}" not in detail
    # Preview must not mount EJPackingList / EJCMR for packing/cmr
    assert "EJPackingList" not in detail or "DocVariant = window.EJPackingList" not in detail
    assert "EJCMRClassic" not in detail or "window.EJCMRClassic" not in detail.split("function ProformaPreviewModal")[1].split("function CancelDraftModal")[0]


def test_api_exposes_html_json_pdf_for_both_docs():
    routes = ROUTES.read_text(encoding="utf-8")
    for needle in (
        "packing-list.html", "packing-list.json", "packing-list.pdf",
        "cmr.html", "cmr.json", "cmr.pdf",
    ):
        assert needle in routes
    api = (STATIC / "pz-api.js").read_text(encoding="utf-8")
    for needle in (
        "getPackingListHtml", "getPackingListDocument", "downloadPackingListPdf",
        "getCmrHtml", "getCmrDocument", "downloadCmrPdf",
    ):
        assert needle in api


def test_single_presentation_modules_are_authority():
    packing_html = (SERVICES / "commercial_packing_list_html.py").read_text(encoding="utf-8")
    cmr_html = (SERVICES / "commercial_cmr_html.py").read_text(encoding="utf-8")
    assert "mirrors EJ" not in packing_html
    assert "mirrors EJ" not in cmr_html
    assert "sole" in packing_html.lower() or "THE sole" in packing_html
    assert "sole" in cmr_html.lower() or "THE sole" in cmr_html
    parties = (SERVICES / "commercial_document_parties.py").read_text(encoding="utf-8")
    assert "Mirrors Proforma Preview" not in parties


def test_email_and_confirmation_use_byte_resolver_only():
    cs = (SERVICES / "customer_send.py").read_text(encoding="utf-8")
    dcs = (SERVICES / "delivery_confirmation_service.py").read_text(encoding="utf-8")
    assert "resolve_canonical_document_bytes" in cs
    assert "resolve_canonical_document_bytes" in dcs
    assert "build_commercial_packing_document" not in cs
    assert "build_cmr_document" not in dcs
    assert "render_cmr_pdf" not in dcs


def test_no_second_document_modules():
    names = {p.name for p in SERVICES.glob("*.py")}
    for forbidden in (
        "packing_list_v2.py", "cmr_v2.py", "email_packing_list.py",
        "email_cmr.py", "customer_document_copy.py",
    ):
        assert forbidden not in names


def test_cmr_preview_projection_does_not_require_number(tmp_path):
    from types import SimpleNamespace
    import json
    from app.services.commercial_cmr import build_cmr_document

    draft = SimpleNamespace(
        id=1, batch_id="B", client_name="C",
        wfirma_proforma_fullnumber="PROF 1",
        buyer_override={"name": "Buyer", "vat_id": "PL1", "street": "s", "city": "c", "zip": "1", "country": "PL"},
        ship_to_override={},
        editable_lines_json=json.dumps([{"item_type": "RNG", "qty": 1, "origin": "IN"}]),
    )
    company = SimpleNamespace(
        legal_name="E", street="s", postal_city="W", country="PL",
        vat_eu="PL1", email="", phone="", nip="PL1",
    )
    doc = build_cmr_document(
        draft=draft, storage_root=tmp_path, company=company, customer=None,
        shipment_row=None, cmr_number=None,
    )
    assert doc["authority"] == "commercial_cmr"
    assert doc["seller"]["name"] == "E"
    assert doc["buyer"]["vat"] == "PL1"


def test_two_fixture_drafts_share_projection_and_html_paths(tmp_path):
    """Materialize two independent drafts through packing + CMR builders.

    Preview JSON and HTML exporters must consume the same document object fields
    (consignee, company, references, items) — no second mapping layer.
    """
    from types import SimpleNamespace
    import json
    from app.services.commercial_packing_list import build_commercial_packing_document
    from app.services.commercial_packing_list_html import render_commercial_packing_list_html
    from app.services.commercial_cmr import build_cmr_document, render_cmr_html
    from app.services.commercial_cmr_html import render_commercial_cmr_html  # noqa: F401 — ownership pin

    company = SimpleNamespace(
        legal_name="Estrella Jewels", street="ul. Test 1", postal_city="Warszawa",
        country="PL", vat_eu="PL5250000000", email="a@b.c", phone="+48", nip="5250000000",
    )

    fixtures = [
        {
            "id": 101, "batch_id": "BATCH_A", "client_name": "Client Alpha",
            "buyer": {"name": "Alpha BV", "vat_id": "NL1", "street": "A 1",
                      "city": "Amsterdam", "zip": "1000", "country": "NL"},
            "lines": [
                {"item_type": "RNG", "qty": 2, "unit_price": 100, "origin": "IN",
                 "description_en": "Ring EN", "description_pl": "Pierścionek",
                 "product_code": "A-1", "design_no": "D1", "metal": "14KT White Gold",
                 "stone_type": "Diamond", "net_weight": 1.2},
            ],
        },
        {
            "id": 202, "batch_id": "BATCH_B", "client_name": "Client Beta",
            "buyer": {"name": "Beta GmbH", "vat_id": "DE1", "street": "B 2",
                      "city": "Berlin", "zip": "10115", "country": "DE"},
            "lines": [
                {"item_type": "PND", "qty": 5, "unit_price": 50, "origin": "IN",
                 "description_en": "Pendant EN", "description_pl": "Wisiorek",
                 "product_code": "B-9", "design_no": "D9", "metal": "18KT Yellow Gold",
                 "stone_type": "Ruby", "net_weight": 3.0},
                {"item_type": "EAR", "qty": 1, "unit_price": 80, "origin": "IN",
                 "description_en": "Earrings EN", "description_pl": "Kolczyki",
                 "product_code": "B-10", "design_no": "D10", "metal": "14KT Pink Gold",
                 "stone_type": "Diamond", "net_weight": 0.8},
            ],
        },
    ]

    for fx in fixtures:
        draft = SimpleNamespace(
            id=fx["id"], batch_id=fx["batch_id"], client_name=fx["client_name"],
            currency="EUR", issue_date="2026-08-15",
            wfirma_proforma_fullnumber=f"PROF {fx['id']}/2026",
            buyer_override=fx["buyer"], ship_to_override={},
            editable_lines_json=json.dumps(fx["lines"]),
            editable_lines=fx["lines"],
        )
        packing = build_commercial_packing_document(
            draft=draft, storage_root=tmp_path, company=company, customer=None,
        )
        packing_html = render_commercial_packing_list_html(packing)
        cmr = build_cmr_document(
            draft=draft, storage_root=tmp_path, company=company, customer=None,
            shipment_row={"tracking_ref": f"AWB{fx['id']}", "provider": "DHL",
                          "weight_kg": 1.5},
            cmr_number=f"CMR-{fx['id']}",
        )
        cmr_html = render_cmr_html(cmr)

        assert packing["authority"] == "commercial_packing_list"
        assert packing["shipto"]["name"] == fx["buyer"]["name"]
        assert packing["seller"]["name"] == "Estrella Jewels"
        assert packing["doc_ref"] == f"PROF {fx['id']}/2026"
        assert len(packing["rows"]) == len(fx["lines"])
        assert fx["buyer"]["name"] in packing_html
        assert "Estrella Jewels" in packing_html
        assert fx["lines"][0]["description_en"] in packing_html or fx["lines"][0]["product_code"] in packing_html

        assert cmr["authority"] == "commercial_cmr"
        assert cmr["shipto"]["name"] == fx["buyer"]["name"]
        assert cmr["cmr_no"] == f"CMR-{fx['id']}"
        assert cmr["carrier"]["awb"] == f"AWB{fx['id']}"
        assert fx["buyer"]["name"] in cmr_html or fx["buyer"]["city"] in cmr_html
        assert "CMR" in cmr_html.upper() or cmr["cmr_no"] in cmr_html
