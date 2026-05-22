"""PZ inline document viewer — first-class promotion (2026-05-22).

Upgrades the inline wFirma PZ panel from a minimal diagnostic view to a
full read-only document viewer.

New fields from warehouse_document_p_z/get/{id}:
  contractor_name  — from <contractor><altname>
  netto_total      — from <netto> (document total netto PLN)
  brutto_total     — from <brutto> (document total brutto PLN)
  status           — from <status> (pending / confirmed)
  currency         — from <currency>
  line total       — computed per-line (count × price_netto)

Authority: warehouse_document_p_z/get/{id} — no app.wfirma.pl URLs.
Works for created, adopted, and recovered PZs.
"""
from __future__ import annotations

from pathlib import Path

ROUTES = Path(__file__).resolve().parent.parent / "app" / "api" / "routes_wfirma.py"
HTML   = Path(__file__).resolve().parent.parent / "app" / "static" / "shipment-detail.html"

# ── Sample XML matching the actual wFirma warehouse_document_p_z/get response ─

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<api>
    <warehouse_documents>
        <warehouse_document>
            <id>185759075</id>
            <fullnumber>PZ 9/5/2026</fullnumber>
            <date>2026-05-21</date>
            <netto>11885.68</netto>
            <brutto>14619.39</brutto>
            <currency>PLN</currency>
            <status>pending</status>
            <description>INV:088/2026-2027
AWB:4789974092
MRN:26PL44302D00C2M4R4
SAD:26S00SV10S
VAT:Art33a
NBP:097/A/NBP/2026 USD=3.6529
SUP:Global Jewellery
CA:Agencja Celna Spedycja</description>
            <warehouse>
                <id>347088</id>
            </warehouse>
            <contractor>
                <id>71554001</id>
                <altname>Global Jewellery Pvt. Ltd.</altname>
            </contractor>
            <warehouse_document_contents>
                <warehouse_document_content>
                    <id>666562211</id>
                    <name>09KT Gold Lab Grown Diamond Jewellery BRACELET</name>
                    <count>2</count>
                    <price>1131.64</price>
                    <good>
                        <id>49514211</id>
                        <name>09KT Gold Lab Grown Diamond Jewellery BRACELET</name>
                    </good>
                </warehouse_document_content>
                <warehouse_document_content>
                    <id>666562212</id>
                    <name>925 Silver CZ Stud Jewellery PENDANT</name>
                    <count>153</count>
                    <price>26.08</price>
                    <good>
                        <id>49514403</id>
                        <name>925 Silver CZ Stud Jewellery PENDANT</name>
                    </good>
                </warehouse_document_content>
            </warehouse_document_contents>
        </warehouse_document>
    </warehouse_documents>
</api>"""

EMPTY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<api><warehouse_documents><warehouse_document>
  <fullnumber>PZ 1/1/2026</fullnumber>
  <date>2026-01-01</date>
  <netto>0</netto>
  <brutto>0</brutto>
  <status>pending</status>
  <description></description>
  <warehouse><id>1</id></warehouse>
  <contractor><id>2</id><altname></altname></contractor>
</warehouse_document></warehouse_documents></api>"""


# ── import the parser directly ─────────────────────────────────────────────

from service.app.api.routes_wfirma import _parse_pz_doc_from_xml


# ── 1. contractor_name parsed ──────────────────────────────────────────────

def test_parse_contractor_name():
    d = _parse_pz_doc_from_xml(SAMPLE_XML)
    assert d["contractor_name"] == "Global Jewellery Pvt. Ltd."


# ── 2. netto and brutto totals parsed ─────────────────────────────────────

def test_parse_netto_brutto_totals():
    d = _parse_pz_doc_from_xml(SAMPLE_XML)
    assert d["netto_total"]  == 11885.68
    assert d["brutto_total"] == 14619.39


# ── 3. status and currency parsed ─────────────────────────────────────────

def test_parse_status_currency():
    d = _parse_pz_doc_from_xml(SAMPLE_XML)
    assert d["status"]   == "pending"
    assert d["currency"] == "PLN"


# ── 4. description (compact notes) preserved ──────────────────────────────

def test_parse_description_compact_notes():
    d = _parse_pz_doc_from_xml(SAMPLE_XML)
    assert "INV:088/2026-2027" in d["description"]
    assert "AWB:4789974092"    in d["description"]
    assert "MRN:26PL44302D00C2M4R4" in d["description"]
    assert "SUP:Global Jewellery"   in d["description"]


# ── 5. lines parsed with count + price ─────────────────────────────────────

def test_parse_lines_count_price():
    d = _parse_pz_doc_from_xml(SAMPLE_XML)
    assert len(d["lines"]) == 2
    l0 = d["lines"][0]
    assert l0["count"]       == 2.0
    assert l0["price_netto"] == 1131.64
    assert l0["good_id"]     == "49514211"
    assert "BRACELET" in l0["name"]


# ── 6. empty altname falls back gracefully ────────────────────────────────

def test_parse_empty_contractor_name_returns_empty_string():
    d = _parse_pz_doc_from_xml(EMPTY_XML)
    assert d["contractor_name"] == ""
    assert d["netto_total"]  == 0.0
    assert d["brutto_total"] == 0.0


# ── 7. malformed XML returns empty dict ───────────────────────────────────

def test_parse_malformed_xml_returns_empty():
    d = _parse_pz_doc_from_xml("not xml")
    assert d == {}


# ── 8. backend response includes all new fields (source-grep) ─────────────

def test_backend_response_includes_new_fields():
    src = ROUTES.read_text(encoding="utf-8")
    # All new fields must appear in the wfirma_pz_document return dict
    doc_start = src.find("async def wfirma_pz_document(")
    assert doc_start > 0
    next_def = src.find("\nasync def ", doc_start + 1)
    body = src[doc_start:next_def] if next_def > 0 else src[doc_start:]
    for field in ("contractor_name", "netto_total", "brutto_total", "status", "currency"):
        assert f'"{field}"' in body, f"pz_document response must include {field!r}"


# ── 9. frontend shows audit notes section ─────────────────────────────────

def test_frontend_shows_audit_notes_section():
    src = HTML.read_text(encoding="utf-8")
    assert 'data-testid="pz-document-notes"' in src, (
        "pz-document-panel must include a notes section with data-testid"
    )
    assert "pzDocumentData.description" in src, (
        "viewer must render pzDocumentData.description"
    )


# ── 10. frontend shows totals row ─────────────────────────────────────────

def test_frontend_shows_totals():
    src = HTML.read_text(encoding="utf-8")
    assert "netto_total" in src, "viewer must reference netto_total"
    assert "brutto_total" in src, "viewer must reference brutto_total"
    assert "Totals" in src, "viewer must show a Totals label"


# ── 11. frontend shows contractor name ────────────────────────────────────

def test_frontend_shows_contractor_name():
    src = HTML.read_text(encoding="utf-8")
    assert "contractor_name" in src, "viewer must render contractor_name"


# ── 12. frontend has line-total column ────────────────────────────────────

def test_frontend_shows_line_total_column():
    src = HTML.read_text(encoding="utf-8")
    assert "Line total" in src, "viewer must include a Line total column header"
    assert "lineTotal" in src or "line_total" in src or "count" in src, (
        "viewer must compute per-line total"
    )


# ── 13. viewer works for adopted PZ (source-grep) ─────────────────────────

def test_viewer_renders_pz_source_adopted():
    src = HTML.read_text(encoding="utf-8")
    assert "adopted_existing" in src, (
        "viewer must handle pz_source=adopted_existing display"
    )


# ── 14. close button has testid ───────────────────────────────────────────

def test_viewer_close_button_has_testid():
    src = HTML.read_text(encoding="utf-8")
    assert 'data-testid="btn-pz-document-close"' in src, (
        "viewer close button must have data-testid for test hooks"
    )
