"""
test_wfirma_pz_payload.py — payload + probe unit tests.

NEVER hits the wFirma network. The probe tool's HTTP layer is fully mocked.
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[1]      # …/CLI/service
    repo_root   = here.parents[2]      # …/CLI
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from app.tools import build_wfirma_pz_payload as bld   # noqa: E402
from app.tools import probe_wfirma_pz_api as prb       # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _good_payload() -> dict:
    return {
        "batch_id": "TEST_BATCH",
        "invoice_no": "EJL/26-27/013",
        "supplier": "ESTRELLA JEWELS LLP.",
        "supplier_wfirma_id": "38142296",
        "warehouse_id": "347088",
        "document_date": "2026-04-04",
        "rows": [
            {
                "product_code": "EJL/26-27/013-1",
                "wfirma_good_id": "11111111",
                "name": "Wisiorek / Pendant",
                "quantity": 5,
                "unit": "szt.",
                "net_price_pln": 85.97,
            },
            {
                "product_code": "EJL/26-27/013-2",
                "wfirma_good_id": "22222222",
                "name": "Pierścionek / Ring",
                "quantity": 1,
                "unit": "szt.",
                "net_price_pln": 2112.31,
            },
        ],
        "totals": {"net_pln": 2542.16, "vat_rate": 23},
    }


# ── Validation tests ──────────────────────────────────────────────────────────

def test_valid_payload_passes_validation():
    v = bld.validate_pz_ready(_good_payload())
    assert v.ok is True
    assert v.blockers == []


def test_missing_product_code_blocks():
    data = _good_payload()
    data["rows"][0]["product_code"] = ""
    v = bld.validate_pz_ready(data)
    assert v.ok is False
    assert any("product_code MISSING" in b for b in v.blockers)


def test_duplicate_product_code_blocks():
    data = _good_payload()
    data["rows"][1]["product_code"] = data["rows"][0]["product_code"]
    # also change the good_id so we don't collide on both — pure product_code test
    data["rows"][1]["wfirma_good_id"] = "33333333"
    v = bld.validate_pz_ready(data)
    assert v.ok is False
    assert any("duplicate product_code" in b for b in v.blockers)


def test_missing_wfirma_good_id_blocks():
    """NEW: PZ XML references existing goods by ID; missing ID is a hard blocker."""
    data = _good_payload()
    data["rows"][0]["wfirma_good_id"] = ""
    v = bld.validate_pz_ready(data)
    assert v.ok is False
    assert any("wfirma_good_id MISSING" in b for b in v.blockers)


def test_missing_wfirma_good_id_field_entirely_blocks():
    """NEW: even the absence of the key blocks (not just empty string)."""
    data = _good_payload()
    del data["rows"][0]["wfirma_good_id"]
    v = bld.validate_pz_ready(data)
    assert v.ok is False
    assert any("wfirma_good_id MISSING" in b for b in v.blockers)


def test_duplicate_wfirma_good_id_blocks():
    """NEW: same wfirma_good_id on two rows is a hard blocker — would corrupt PZ."""
    data = _good_payload()
    data["rows"][1]["wfirma_good_id"] = data["rows"][0]["wfirma_good_id"]
    v = bld.validate_pz_ready(data)
    assert v.ok is False
    assert any("duplicate wfirma_good_id" in b for b in v.blockers)


def test_missing_supplier_id_blocks():
    data = _good_payload()
    data["supplier_wfirma_id"] = ""
    v = bld.validate_pz_ready(data)
    assert v.ok is False
    assert any("supplier_wfirma_id" in b for b in v.blockers)


def test_missing_warehouse_id_blocks():
    data = _good_payload()
    data["warehouse_id"] = ""
    v = bld.validate_pz_ready(data)
    assert v.ok is False
    assert any("warehouse_id" in b for b in v.blockers)


def test_missing_date_blocks():
    data = _good_payload()
    data["document_date"] = ""
    v = bld.validate_pz_ready(data)
    assert v.ok is False
    assert any("document_date" in b for b in v.blockers)


def test_zero_quantity_blocks():
    data = _good_payload()
    data["rows"][0]["quantity"] = 0
    v = bld.validate_pz_ready(data)
    assert v.ok is False
    assert any("quantity must be > 0" in b for b in v.blockers)


def test_zero_price_blocks():
    data = _good_payload()
    data["rows"][0]["net_price_pln"] = 0
    v = bld.validate_pz_ready(data)
    assert v.ok is False
    assert any("net_price_pln must be > 0" in b for b in v.blockers)


def test_empty_rows_block():
    data = _good_payload()
    data["rows"] = []
    v = bld.validate_pz_ready(data)
    assert v.ok is False
    assert any("rows is empty" in b for b in v.blockers)


# ── XML payload tests ─────────────────────────────────────────────────────────

def test_xml_is_well_formed_and_uses_warehouse_documents_wrapper():
    """Wrapper is the umbrella plural <warehouse_documents>, not the typed module name."""
    xml = bld.build_pz_xml(_good_payload())
    root = ET.fromstring(xml)
    assert root.tag == "api"
    assert root.find("warehouse_documents") is not None
    assert root.find("warehouse_document_p_z") is None
    assert root.find("warehouse_documents/warehouse_document") is not None


def test_xml_document_level_required_fields():
    """type=PZ, status=pending, currency=PLN, vat_payer=1, series.id are all set."""
    xml = bld.build_pz_xml(_good_payload())
    root = ET.fromstring(xml)
    doc = root.find("warehouse_documents/warehouse_document")
    assert doc.findtext("type")      == "PZ"
    assert doc.findtext("status")    == "pending"
    assert doc.findtext("currency")  == "PLN"
    assert doc.findtext("vat_payer") == "1"
    assert doc.find("series/id").text == bld.DEFAULT_PZ_SERIES_ID


def test_xml_per_payload_series_override():
    data = _good_payload()
    data["series_id"] = "99999999"
    xml = bld.build_pz_xml(data)
    root = ET.fromstring(xml)
    assert root.find("warehouse_documents/warehouse_document/series/id").text == "99999999"


def test_xml_currency_and_status_overrides():
    data = _good_payload()
    data["currency"] = "USD"
    data["status"]   = "created"
    xml = bld.build_pz_xml(data)
    root = ET.fromstring(xml)
    doc = root.find("warehouse_documents/warehouse_document")
    assert doc.findtext("currency") == "USD"
    assert doc.findtext("status")   == "created"


def test_xml_uses_dot_decimal_separator():
    xml = bld.build_pz_xml(_good_payload())
    # 85.97 must appear with a dot. Comma must NOT appear inside any <price>.
    assert "<price>85.97</price>" in xml
    assert ",97" not in xml


def test_xml_contains_good_id_for_each_row():
    """NEW: each <warehouse_document_content><good><id> matches wfirma_good_id."""
    data = _good_payload()
    xml = bld.build_pz_xml(data)
    root = ET.fromstring(xml)
    contents = root.findall(f"{bld.WFIRMA_PZ_WRAPPER}/warehouse_document/"
                            f"warehouse_document_contents/warehouse_document_content")
    assert len(contents) == len(data["rows"])
    for c, row in zip(contents, data["rows"]):
        assert c.find("good/id").text == row["wfirma_good_id"]


def test_xml_does_not_contain_good_code_or_unit_inside_good():
    """NEW: removed the upsert shape — <good> may NOT carry <code>/<name>/<unit>."""
    xml = bld.build_pz_xml(_good_payload())
    root = ET.fromstring(xml)
    for good in root.iter("good"):
        # The only legal child of <good> in PZ payload is <id>.
        children = [c.tag for c in list(good)]
        assert children == ["id"], (
            f"<good> has unexpected children {children} — expected only <id>"
        )
    # And the literal opening "<good><code>" pattern must not appear anywhere.
    assert "<code>" not in xml.split("<warehouse_document_contents>")[1], (
        "<code> must not appear inside warehouse_document_contents"
    )


def test_xml_contains_vat_code_id_and_no_literal_vat():
    """NEW: <vat_code><id>222</id></vat_code> only — never <vat>23</vat>."""
    xml = bld.build_pz_xml(_good_payload())
    assert "<vat_code>" in xml
    assert "<id>222</id>" in xml
    assert "<vat>23</vat>" not in xml
    assert "<vat>" not in xml.replace("<vat_code>", "").replace("</vat_code>", "")


def test_xml_uses_default_vat_code_id_when_missing():
    data = _good_payload()
    for row in data["rows"]:
        row.pop("vat_code_id", None)
    xml = bld.build_pz_xml(data)
    root = ET.fromstring(xml)
    for line in root.iter("warehouse_document_content"):
        assert line.find("vat_code/id").text == bld.DEFAULT_VAT_CODE_ID


def test_xml_uses_per_row_vat_code_id_override():
    data = _good_payload()
    data["rows"][0]["vat_code_id"] = "999"
    xml = bld.build_pz_xml(data)
    root = ET.fromstring(xml)
    contents = list(root.iter("warehouse_document_content"))
    assert contents[0].find("vat_code/id").text == "999"
    assert contents[1].find("vat_code/id").text == bld.DEFAULT_VAT_CODE_ID


def test_xml_keeps_line_level_name_and_unit_id():
    """Line-level <name> and <unit><id> describe the line, not the good master."""
    data = _good_payload()
    xml = bld.build_pz_xml(data)
    root = ET.fromstring(xml)
    line0 = list(root.iter("warehouse_document_content"))[0]
    assert line0.findtext("name") == data["rows"][0]["name"]
    assert line0.find("unit/id").text == bld.DEFAULT_UNIT_ID


def test_xml_unit_is_id_reference_not_string():
    """NEW: <unit> must be <unit><id>X</id></unit>, never <unit>szt.</unit>."""
    xml = bld.build_pz_xml(_good_payload())
    root = ET.fromstring(xml)
    for line in root.iter("warehouse_document_content"):
        unit_el = line.find("unit")
        assert unit_el is not None
        children = [c.tag for c in list(unit_el)]
        assert children == ["id"], f"<unit> must contain only <id>, got {children}"
    # The literal text "szt." must not appear inside any <unit> element.
    assert "<unit>szt.</unit>" not in xml


def test_xml_uses_default_unit_id_when_missing():
    data = _good_payload()
    for row in data["rows"]:
        row.pop("unit_id", None)
    xml = bld.build_pz_xml(data)
    root = ET.fromstring(xml)
    for line in root.iter("warehouse_document_content"):
        assert line.find("unit/id").text == bld.DEFAULT_UNIT_ID


def test_xml_uses_per_row_unit_id_override():
    data = _good_payload()
    data["rows"][0]["unit_id"] = "888888"
    xml = bld.build_pz_xml(data)
    contents = list(ET.fromstring(xml).iter("warehouse_document_content"))
    assert contents[0].find("unit/id").text == "888888"
    assert contents[1].find("unit/id").text == bld.DEFAULT_UNIT_ID


# ── Parcel block (warehouse_type=extended hypothesis) ─────────────────────────

def test_xml_each_line_has_parcel_block():
    """For extended warehouse goods, every line must carry one parcel."""
    xml = bld.build_pz_xml(_good_payload())
    root = ET.fromstring(xml)
    for line in root.iter("warehouse_document_content"):
        parcels = line.find("warehouse_good_parcels")
        assert parcels is not None, "missing <warehouse_good_parcels>"
        children = parcels.findall("warehouse_good_parcel")
        assert len(children) == 1, f"expected 1 parcel per line, got {len(children)}"


def test_xml_parcel_count_matches_unit_count():
    data = _good_payload()
    xml = bld.build_pz_xml(data)
    root = ET.fromstring(xml)
    contents = list(root.iter("warehouse_document_content"))
    for line, row in zip(contents, data["rows"]):
        parcel = line.find("warehouse_good_parcels/warehouse_good_parcel")
        # parcel.count must equal line.unit_count (same qty)
        assert float(parcel.findtext("count")) == float(row["quantity"])
        assert float(line.findtext("unit_count")) == float(row["quantity"])


def test_xml_parcel_prices_match_line_price():
    """Parcel purchase_price + production_price both equal the line net price."""
    xml = bld.build_pz_xml(_good_payload())
    root = ET.fromstring(xml)
    contents = list(root.iter("warehouse_document_content"))
    for line in contents:
        line_price = line.findtext("price")
        parcel = line.find("warehouse_good_parcels/warehouse_good_parcel")
        assert parcel.findtext("purchase_price")   == line_price
        assert parcel.findtext("production_price") == line_price


def test_xml_parcel_warehouse_defaults_to_doc_warehouse():
    """parcel.warehouse.id defaults to the document-level warehouse_id."""
    data = _good_payload()
    xml = bld.build_pz_xml(data)
    root = ET.fromstring(xml)
    for line in root.iter("warehouse_document_content"):
        parcel_wh = line.find("warehouse_good_parcels/warehouse_good_parcel/warehouse/id").text
        assert parcel_wh == data["warehouse_id"]


def test_xml_parcel_warehouse_per_row_override():
    data = _good_payload()
    data["rows"][0]["parcel_warehouse_id"] = "999999"
    xml = bld.build_pz_xml(data)
    root = ET.fromstring(xml)
    contents = list(root.iter("warehouse_document_content"))
    p0 = contents[0].find("warehouse_good_parcels/warehouse_good_parcel/warehouse/id").text
    p1 = contents[1].find("warehouse_good_parcels/warehouse_good_parcel/warehouse/id").text
    assert p0 == "999999"
    assert p1 == data["warehouse_id"]


def test_xml_parcel_decimal_uses_dot():
    """Parcel count/prices use dot decimal, just like other XML numeric fields."""
    xml = bld.build_pz_xml(_good_payload())
    # Find parcel <count> and <purchase_price> in the rendered string.
    assert "<count>5.0000</count>" in xml      # row 0 qty=5
    assert "<purchase_price>85.97</purchase_price>" in xml
    assert ",97" not in xml


def test_xml_supplier_warehouse_date_present():
    data = _good_payload()
    xml = bld.build_pz_xml(data)
    assert f"<id>{data['supplier_wfirma_id']}</id>" in xml
    assert f"<id>{data['warehouse_id']}</id>" in xml
    assert f"<date>{data['document_date']}</date>" in xml


def test_xml_escapes_special_chars_in_name():
    data = _good_payload()
    data["rows"][0]["name"] = "Test <evil> & 'quote' \"x\""
    xml = bld.build_pz_xml(data)
    # Must not break the parse
    ET.fromstring(xml)
    assert "<evil>" not in xml   # the literal angle bracket got escaped


def test_endpoint_hypothesis_constants():
    # Sanity guard on the module name — if this changes, callers must be updated.
    assert bld.WFIRMA_PZ_MODULE == "warehouse_document_p_z"
    assert bld.WFIRMA_PZ_ACTION == "add"
    assert bld.SCHEMA_CONFIRMED is False, (
        "Flip SCHEMA_CONFIRMED only after probe verifies the live endpoint"
    )


def test_build_payload_writes_no_xml_on_blockers(tmp_path: Path):
    bad = _good_payload()
    bad["rows"][0]["product_code"] = ""
    src = tmp_path / "PZ_READY_bad.json"
    src.write_text(json.dumps(bad), encoding="utf-8")
    validation, xml = bld.build_payload(src)
    assert validation.ok is False
    assert xml == ""


def test_build_payload_round_trip_from_test_file():
    """Single-line TEST file has wfirma_good_id and must validate + produce XML.

    The 3 batch PZ_READY files (013/014/015) intentionally don't have
    wfirma_good_id yet — those goods haven't been created in wFirma. They
    will validate after the goods-creation step.
    """
    repo = Path(__file__).resolve().parents[2]
    path = repo / "PZ_READY_TEST_single_line.json"
    if not path.is_file():
        pytest.skip("test PZ_READY not present")
    validation, xml = bld.build_payload(path)
    assert validation.ok, f"blockers={validation.blockers}"
    assert xml.startswith("<?xml")
    root = ET.fromstring(xml)
    contents = list(root.iter("warehouse_document_content"))
    assert len(contents) == 1
    assert contents[0].find("good/id").text == "48461283"
    assert contents[0].find("vat_code/id").text == "222"


# ── Probe tests (HTTP fully mocked — NO live calls) ───────────────────────────

def _mock_http(http_status: int, body: str):
    """Return a context manager that patches wfirma_client._http_request + _parse_status."""
    from app.services import wfirma_client as wfc

    def fake_http(method, module, action, body_xml=""):
        return http_status, body

    return patch.object(wfc, "_http_request", side_effect=fake_http)


def test_probe_no_live_http_calls():
    """Even a full run with patched HTTP must never raise — i.e. no real network."""
    with _mock_http(200, '<?xml version="1.0"?><api><status><code>OK</code></status></api>'):
        results = prb.run_probes()
    assert len(results) == len(prb._PROBES)
    for r in results:
        assert "endpoint" in r and "reachable" in r


def test_probe_summary_confirmed_when_pz_endpoints_ok():
    ok_body = '<?xml version="1.0"?><api><status><code>OK</code></status></api>'
    err_body = (
        '<?xml version="1.0"?><api><status><code>INPUT_ERROR</code>'
        '<message>missing fields</message></status></api>'
    )
    from app.services import wfirma_client as wfc

    def fake_http(method, module, action, body_xml=""):
        if module == "warehouse_document_p_z" and action == "add":
            # add_empty probe: server rejects payload but endpoint exists
            return 200, err_body
        return 200, ok_body

    with patch.object(wfc, "_http_request", side_effect=fake_http):
        results = prb.run_probes()
        summary = prb.summarize(results)

    pz_add = next(r for r in results if r["endpoint"] == "warehouse_document_p_z/add")
    assert pz_add["reachable"] is True
    assert pz_add["write_risk"] is False
    assert summary["confirmed"] is True


def test_probe_summary_not_confirmed_on_404():
    err_body = (
        '<?xml version="1.0"?><api><status><code>ACTION_NOT_FOUND</code></status></api>'
    )
    from app.services import wfirma_client as wfc

    def fake_http(method, module, action, body_xml=""):
        if module.startswith("warehouse_document_p_z") or module == "pz":
            return 404, err_body
        return 200, '<?xml version="1.0"?><api><status><code>OK</code></status></api>'

    with patch.object(wfc, "_http_request", side_effect=fake_http):
        results = prb.run_probes()
        summary = prb.summarize(results)
    assert summary["confirmed"] is False
    assert "CSV" in summary["recommendation"]


def test_probe_flags_write_risk_on_unexpected_ok_for_add_empty():
    ok_body = '<?xml version="1.0"?><api><status><code>OK</code></status></api>'
    from app.services import wfirma_client as wfc

    with patch.object(wfc, "_http_request", return_value=(200, ok_body)):
        results = prb.run_probes()
    add_row = next(r for r in results if r["endpoint"] == "warehouse_document_p_z/add")
    assert add_row["write_risk"] is True
