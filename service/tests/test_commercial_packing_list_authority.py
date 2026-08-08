"""Commercial Packing List — one document authority for Preview + packages.

Pins:
  * Server PDF consumes draft billed editable_lines (not packing.db row authority)
  * Column set matches EJPackingList / packingListData commercial contract
  * Retired simplified sheet columns are absent
  * Path-DOC assemble + complete-package ZIP both call the same renderer
  * No second packing-list business renderer remains in doc_package
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "service"


def _extract_pdf_text(pdf: bytes) -> str:
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


@pytest.fixture
def draft_with_commercial_lines():
    lines = [
        {
            "product_code": "EJL/TEST-001",
            "design_no": "JR001",
            "item_type": "RNG",
            "qty": 2,
            "unit_price": 100.5,
            "client_po": "PO-9",
            "karat": "18KT",
            "metal_color": "W",
            "quality_string": "VS1",
            "diamond_weight": 0.42,
            "color_weight": 0.0,
            "gross_weight": 3.2,
            "net_weight": 2.8,
            "size": "54",
            "origin": "IN",
            "description_en": "Diamond Ring",
            "description_pl": "Pierścionek diamentowy",
            "metal": "18KT/W",
        },
        {
            "product_code": "EJL/TEST-002",
            "design_no": "JB002",
            "item_type": "BRC",
            "qty": 1,
            "unit_price": 250.0,
            "client_po": "PO-9",
            "karat": "14KT",
            "metal_color": "Y",
            "quality_string": "",
            "diamond_weight": 0,
            "color_weight": 1.1,
            "size": "18",
            "description_en": "Gold Bracelet",
            "description_pl": "",
            "metal": "14KT/Y",
        },
    ]
    return SimpleNamespace(
        batch_id="BATCH_CPL_AUTH",
        client_name="Test Client GmbH",
        currency="EUR",
        wfirma_proforma_fullnumber="PROF 99/2026",
        wfirma_proforma_id="494499999",
        wfirma_invoice_number=None,
        issue_date="2026-08-01",
        editable_lines_json=json.dumps(lines),
    )


def test_build_model_uses_draft_billed_lines_not_packing_db(
    tmp_path, draft_with_commercial_lines,
):
    from app.services.commercial_packing_list import build_commercial_packing_document

    company = SimpleNamespace(
        legal_name="Estrella Jewels", street="ul. Test 1",
        postal_city="Warszawa", country="PL", vat_eu="PL123", email="", phone="",
    )
    doc = build_commercial_packing_document(
        draft=draft_with_commercial_lines,
        storage_root=tmp_path,
        company=company,
        customer=None,
    )
    assert doc["authority"] == "commercial_packing_list"
    assert len(doc["rows"]) == 2
    assert doc["rows"][0]["product_code"] == "EJL/TEST-001"
    assert doc["rows"][0]["client_po"] == "PO-9"
    assert doc["rows"][0]["description_en"] == "Diamond Ring"
    assert doc["rows"][0]["kt"] == "18KT"
    assert doc["rows"][0]["unit_price"] == 100.5
    assert doc["rows"][0]["total_value"] == 201.0
    assert doc["rows"][0]["ctg"] == "Ring"
    assert doc["total_qty"] == 3
    assert abs(doc["grand_total"] - 451.0) < 0.01
    assert doc["doc_ref"] == "PROF 99/2026"


def test_pdf_has_commercial_columns_not_simplified_sheet(
    tmp_path, draft_with_commercial_lines,
):
    from app.services.commercial_packing_list import (
        build_commercial_packing_document,
        render_commercial_packing_list_pdf,
    )

    doc = build_commercial_packing_document(
        draft=draft_with_commercial_lines,
        storage_root=tmp_path,
        company=SimpleNamespace(
            legal_name="Estrella Jewels", street="", postal_city="",
            country="PL", vat_eu="", email="", phone="",
        ),
    )
    pdf = render_commercial_packing_list_pdf(doc)
    assert pdf[:4] == b"%PDF"
    text = _extract_pdf_text(pdf)
    # Canonical commercial markers
    assert "Commercial Packing List" in text
    assert "Client PO" in text
    assert "Product Description" in text
    assert "Diamond Ring" in text
    assert "PO-9" in text
    assert "EJL/TEST-001" in text
    assert "JR001" in text
    # Retired simplified sheet must NOT be the document
    assert "Product Code / Design" not in text
    # Batch id as consignee meta of old sheet should not dominate
    assert "BATCH_CPL_AUTH" not in text or "Proforma" in text


def test_doc_package_render_packing_list_pdf_delegates_to_commercial(
    tmp_path, draft_with_commercial_lines, monkeypatch,
):
    from app.services.carrier import doc_package

    called = {}

    def _fake(**kwargs):
        called.update(kwargs)
        return b"%PDF-commercial-authority"

    monkeypatch.setattr(
        "app.services.commercial_packing_list.render_packing_list_pdf_from_authorities",
        _fake,
    )
    out = doc_package.render_packing_list_pdf(
        "BATCH_CPL_AUTH", tmp_path, None, None, draft_with_commercial_lines,
    )
    assert out == b"%PDF-commercial-authority"
    assert called.get("draft") is draft_with_commercial_lines
    assert called.get("batch_id") == "BATCH_CPL_AUTH"


def test_simplified_packing_sheet_body_removed_from_doc_package():
    src = (SERVICE / "app" / "services" / "carrier" / "doc_package.py").read_text(
        encoding="utf-8"
    )
    assert "Product Code / Design" not in src, (
        "retired simplified packing sheet still present in doc_package.py"
    )
    assert "commercial_packing_list" in src
    assert "render_packing_list_pdf_from_authorities" in src


def test_no_second_packing_pdf_generator_in_services():
    """Only commercial_packing_list may emit packing-list PDF bytes."""
    services = SERVICE / "app" / "services"
    offenders = []
    for path in services.rglob("*.py"):
        if path.name == "commercial_packing_list.py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "Product Code / Design" in text and "Gross Wt (g)" in text and "Dia Wt (ct)" in text:
            offenders.append(str(path.relative_to(SERVICE)))
    assert offenders == [], f"duplicate simplified packing PDF producers: {offenders}"


def test_render_packing_list_pdf_from_authorities_end_to_end(
    tmp_path, draft_with_commercial_lines,
):
    """Public package entry builds commercial PDF with billed-line fields."""
    from app.services.commercial_packing_list import (
        render_packing_list_pdf_from_authorities,
    )

    company = SimpleNamespace(
        legal_name="Estrella Jewels", street="ul. Test 1",
        postal_city="Warszawa", country="PL", vat_eu="PL123", email="", phone="",
    )
    pdf = render_packing_list_pdf_from_authorities(
        batch_id="BATCH_CPL_AUTH",
        storage_root=tmp_path,
        company=company,
        customer=None,
        draft=draft_with_commercial_lines,
    )
    assert pdf[:4] == b"%PDF"
    text = _extract_pdf_text(pdf)
    assert "Commercial Packing List" in text
    assert "Client PO" in text
    assert "PO-9" in text
    assert "Diamond Ring" in text
    assert "Product Code / Design" not in text
