"""
test_wfirma_client_contract.py — contract tests for wfirma_client.py

Tests validate:
  - XML payload shapes built by _build_reservation_xml() and _build_proforma_xml()
  - Auth header selection (_headers_for_module)
  - URL construction (_url)
  - check_config() logic
  - Response parsing helpers (_parse_status, _find_text)

These tests make NO live HTTP calls. All network functions raise NotImplementedError
until the POST /reservations/create route is approved.
"""
from __future__ import annotations

from unittest.mock import patch
from xml.etree import ElementTree as ET

import pytest

from app.services.wfirma_client import (
    ProformaRequest,
    ReservationLine,
    ReservationRequest,
    WFirmaContractor,
    WFirmaProduct,
    _WAREHOUSE_MODULES,

    _build_proforma_xml,
    _build_reservation_xml,
    _esc,
    _find_text,
    _headers_for_module,
    _parse_status,
    _url,
    check_config,
    create_customer,
    create_proforma_draft,
    create_reservation,
    find_vat_code_id,
    get_product_by_code,
    get_stock,
    search_customer,
)
from app.core.config import settings


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _full_settings(**overrides):
    """Patch settings with all required wFirma credentials."""
    base = {
        "wfirma_access_key": "ACC-KEY-001",
        "wfirma_secret_key": "SEC-KEY-001",
        "wfirma_app_key":    "APP-KEY-001",
        "wfirma_company_id": "123456",
        "wfirma_warehouse_module_enabled": True,
        "wfirma_warehouse_id": "WH-001",
    }
    base.update(overrides)
    return patch.multiple(settings, **base)


def _sample_lines(n: int = 2) -> list[ReservationLine]:
    return [
        ReservationLine(
            product_code=f"EJL/26-27/015-{i}",
            wfirma_good_id=f"GD-{i}",
            product_name=f"Produkt {i}",
            qty=float(i + 1),
            unit_price=100.0 * (i + 1),
            unit="szt.",
            currency="USD",
        )
        for i in range(1, n + 1)
    ]


# ── Tests: check_config ───────────────────────────────────────────────────────

def test_check_config_all_missing():
    with patch.multiple(
        settings,
        wfirma_access_key=None,
        wfirma_secret_key=None,
        wfirma_company_id="",
        wfirma_app_key=None,
        wfirma_warehouse_module_enabled=False,
        wfirma_warehouse_id="",
    ):
        result = check_config()
    assert result["ok"] is False
    assert "WFIRMA_ACCESS_KEY" in result["missing"]
    assert "WFIRMA_SECRET_KEY" in result["missing"]
    assert "WFIRMA_COMPANY_ID" in result["missing"]
    assert "WFIRMA_APP_KEY" in result["missing"]
    assert result["warehouse_ok"] is False


def test_check_config_credentials_only():
    with _full_settings(
        wfirma_warehouse_module_enabled=False,
        wfirma_warehouse_id="",
    ):
        result = check_config()
    assert result["ok"] is True
    assert result["missing"] == []
    assert result["warehouse_ok"] is False


def test_check_config_full():
    with _full_settings():
        result = check_config()
    assert result["ok"] is True
    assert result["warehouse_ok"] is True


def test_check_config_warehouse_flag_but_no_id():
    with _full_settings(wfirma_warehouse_module_enabled=True, wfirma_warehouse_id=""):
        result = check_config()
    assert result["ok"] is True
    assert result["warehouse_ok"] is False


# ── Tests: URL construction ───────────────────────────────────────────────────

def test_url_format():
    with patch.object(settings, "wfirma_company_id", "99999"):
        u = _url("contractors", "find")
    assert u == (
        "https://api2.wfirma.pl/contractors/find"
        "?outputFormat=xml&inputFormat=xml&company_id=99999"
    )


def test_url_warehouse_module():
    with patch.object(settings, "wfirma_company_id", "99999"):
        u = _url("warehouse_document_r", "add")
    assert "warehouse_document_r/add" in u
    assert "company_id=99999" in u


# ── Tests: auth header selection ──────────────────────────────────────────────

def test_api_key_headers_for_contractors():
    with _full_settings():
        h = _headers_for_module("contractors")
    assert "accessKey" in h
    assert "secretKey" in h
    assert "appKey" in h
    assert "Authorization" not in h


def test_api_key_headers_for_goods():
    with _full_settings():
        h = _headers_for_module("goods")
    assert h["accessKey"] == "ACC-KEY-001"
    assert h["secretKey"] == "SEC-KEY-001"
    assert h["appKey"] == "APP-KEY-001"


def test_api_key_headers_for_invoices():
    with _full_settings():
        h = _headers_for_module("invoices")
    assert "accessKey" in h


def test_api_key_auth_for_warehouse_document_r():
    """warehouse_document_r must now use API Key headers (Basic Auth deprecated 2023-07-02)."""
    with _full_settings():
        h = _headers_for_module("warehouse_document_r")
    assert "accessKey" in h
    assert "secretKey" in h
    assert "appKey" in h
    assert "Authorization" not in h  # no Basic Auth header


def test_api_key_auth_for_all_warehouse_modules():
    """All warehouse modules use API Key headers after wFirma deprecated Basic Auth."""
    with _full_settings():
        for module in _WAREHOUSE_MODULES:
            h = _headers_for_module(module)
            assert "accessKey" in h, f"Expected API Key for {module}"
            assert "Authorization" not in h, f"Stale Basic Auth header in {module}"


def test_api_key_headers_missing_credentials_raises():
    with patch.multiple(
        settings,
        wfirma_access_key=None,
        wfirma_secret_key=None,
        wfirma_app_key=None,
    ):
        with pytest.raises(ValueError, match="WFIRMA_ACCESS_KEY"):
            _headers_for_module("contractors")


def test_api_key_headers_missing_raises_for_warehouse():
    """Warehouse modules also require API Key headers now."""
    with patch.multiple(
        settings,
        wfirma_access_key=None,
        wfirma_secret_key=None,
        wfirma_app_key=None,
    ):
        with pytest.raises(ValueError, match="WFIRMA_ACCESS_KEY"):
            _headers_for_module("warehouse_document_r")


# ── Tests: XML escaping ───────────────────────────────────────────────────────

def test_esc_basic():
    assert _esc("hello") == "hello"


def test_esc_ampersand():
    assert _esc("A&B") == "A&amp;B"


def test_esc_angle_brackets():
    assert _esc("<test>") == "&lt;test&gt;"


def test_esc_quotes():
    assert _esc('say "hi"') == "say &quot;hi&quot;"


def test_esc_product_code_with_slash():
    # Product codes like "EJL/26-27/015-6" must pass through unchanged (/ is safe in XML)
    assert _esc("EJL/26-27/015-6") == "EJL/26-27/015-6"


# ── Tests: _parse_status ──────────────────────────────────────────────────────

def test_parse_status_ok():
    xml = "<api><status><code>OK</code></status></api>"
    code, desc = _parse_status(xml)
    assert code == "OK"
    assert desc == ""


def test_parse_status_error():
    xml = "<api><status><code>ERROR</code><description>Brak autoryzacji</description></status></api>"
    code, desc = _parse_status(xml)
    assert code == "ERROR"
    assert "autoryzacji" in desc


def test_parse_status_malformed():
    code, desc = _parse_status("NOT XML <<<")
    assert code == "PARSE_ERROR"
    assert len(desc) > 0


def test_parse_status_no_status_element():
    xml = "<api><contractors/></api>"
    code, desc = _parse_status(xml)
    assert code == "UNKNOWN"


# ── Tests: _build_reservation_xml ─────────────────────────────────────────────

def _parse_reservation_xml(req: ReservationRequest) -> ET.Element:
    xml_str = _build_reservation_xml(req)
    root = ET.fromstring(xml_str)
    return root


def test_reservation_xml_valid():
    req = ReservationRequest(
        batch_id="BATCH-001",
        client_name="Dream Rings",
        wfirma_contractor_id="C-001",
        wfirma_warehouse_id="WH-001",
        date="2026-05-03",
        lines=_sample_lines(1),
    )
    xml_str = _build_reservation_xml(req)
    # Must be parseable
    root = ET.fromstring(xml_str)
    assert root.tag == "api"


def test_reservation_xml_contractor_id():
    req = ReservationRequest(
        batch_id="B",
        client_name="X",
        wfirma_contractor_id="CUST-999",
        wfirma_warehouse_id="WH-1",
        date="2026-05-01",
        lines=_sample_lines(1),
    )
    root = _parse_reservation_xml(req)
    doc = root.find(".//warehouse_document")
    contractor_id = _find_text(doc, "contractor", "id")
    assert contractor_id == "CUST-999"


def test_reservation_xml_date():
    req = ReservationRequest(
        batch_id="B",
        client_name="X",
        wfirma_contractor_id="C1",
        wfirma_warehouse_id="WH",
        date="2026-05-03",
        lines=_sample_lines(1),
    )
    root = _parse_reservation_xml(req)
    doc = root.find(".//warehouse_document")
    assert _find_text(doc, "date") == "2026-05-03"


def test_reservation_xml_price_type_netto():
    req = ReservationRequest(
        batch_id="B", client_name="X", wfirma_contractor_id="C",
        wfirma_warehouse_id="WH", date="2026-05-01", lines=_sample_lines(1),
    )
    root = _parse_reservation_xml(req)
    doc = root.find(".//warehouse_document")
    assert _find_text(doc, "price_type") == "netto"


def test_reservation_xml_status_pending():
    req = ReservationRequest(
        batch_id="B", client_name="X", wfirma_contractor_id="C",
        wfirma_warehouse_id="WH", date="2026-05-01", lines=_sample_lines(1),
    )
    root = _parse_reservation_xml(req)
    doc = root.find(".//warehouse_document")
    assert _find_text(doc, "status") == "pending"


def test_reservation_xml_line_count():
    req = ReservationRequest(
        batch_id="B", client_name="X", wfirma_contractor_id="C",
        wfirma_warehouse_id="WH", date="2026-05-01", lines=_sample_lines(3),
    )
    root = _parse_reservation_xml(req)
    contents = root.findall(".//warehouse_document_content")
    assert len(contents) == 3


def test_reservation_xml_line_fields():
    line = ReservationLine(
        product_code="EJL/26-27/015-6",
        wfirma_good_id="GD-42",
        product_name="Pierścionek złoty",
        qty=5.0,
        unit_price=123.45,
        unit="szt.",
    )
    req = ReservationRequest(
        batch_id="B", client_name="X", wfirma_contractor_id="C",
        wfirma_warehouse_id="WH", date="2026-05-01", lines=[line],
    )
    root = _parse_reservation_xml(req)
    content = root.find(".//warehouse_document_content")
    assert _find_text(content, "good", "id") == "GD-42"
    assert _find_text(content, "unit_count") == "5.0000"
    assert _find_text(content, "price") == "123.45"
    assert _find_text(content, "unit") == "szt."


def test_reservation_xml_with_description():
    req = ReservationRequest(
        batch_id="B", client_name="X", wfirma_contractor_id="C",
        wfirma_warehouse_id="WH", date="2026-05-01",
        lines=_sample_lines(1),
        description="Batch SHIPMENT_FINAL76V2_2026-05",
    )
    root = _parse_reservation_xml(req)
    doc = root.find(".//warehouse_document")
    assert "Batch SHIPMENT_FINAL76V2_2026-05" in _find_text(doc, "description")


def test_reservation_xml_xml_escaping_in_name():
    line = ReservationLine(
        product_code="EJL/TEST",
        wfirma_good_id="GD-1",
        product_name='Ring <gold> & "silver"',
        qty=1.0,
        unit_price=100.0,
    )
    req = ReservationRequest(
        batch_id="B", client_name="X", wfirma_contractor_id="C",
        wfirma_warehouse_id="WH", date="2026-05-01", lines=[line],
    )
    # Must not raise ParseError
    xml_str = _build_reservation_xml(req)
    ET.fromstring(xml_str)  # Validates XML well-formedness


# ── Tests: _build_proforma_xml ────────────────────────────────────────────────

def _parse_proforma_xml(req: ProformaRequest) -> ET.Element:
    xml_str = _build_proforma_xml(req)
    return ET.fromstring(xml_str)


def test_proforma_xml_valid():
    req = ProformaRequest(
        client_name="Dream Rings",
        client_zip="SW1A 1AA",
        client_city="London",
        lines=_sample_lines(2),
        wfirma_contractor_id="999",
    )
    xml_str = _build_proforma_xml(req)
    root = ET.fromstring(xml_str)
    assert root.tag == "api"


def test_proforma_xml_type_is_proforma():
    req = ProformaRequest(
        client_name="X", client_zip="00-001", client_city="Warsaw",
        lines=_sample_lines(1), wfirma_contractor_id="999",
    )
    root = _parse_proforma_xml(req)
    invoice = root.find(".//invoice")
    assert _find_text(invoice, "type") == "proforma"


def test_proforma_xml_contractor_id_reference():
    """Contractor is referenced by <id>, not by inline name fields."""
    req = ProformaRequest(
        client_name="Dream Rings Ltd",
        client_zip="SW1A 1AA",
        client_city="London",
        lines=_sample_lines(1),
        wfirma_contractor_id="42",
    )
    root = _parse_proforma_xml(req)
    invoice = root.find(".//invoice")
    assert _find_text(invoice, "contractor", "id") == "42"
    # Inline name/zip/city fields must NOT be serialised
    assert invoice.find("contractor/name") is None
    assert invoice.find("contractor/zip")  is None
    assert invoice.find("contractor/city") is None


def test_proforma_xml_line_count():
    req = ProformaRequest(
        client_name="X", client_zip="", client_city="",
        lines=_sample_lines(4), wfirma_contractor_id="999",
    )
    root = _parse_proforma_xml(req)
    lines = root.findall(".//invoicecontent")
    assert len(lines) == 4


def test_proforma_xml_line_fields():
    line = ReservationLine(
        product_code="EJL/26-27/015-6",
        wfirma_good_id="GD-678",
        product_name="Pierścionek złoty",
        qty=3.0,
        unit_price=200.0,
        unit="szt.",
    )
    req = ProformaRequest(
        client_name="X", client_zip="", client_city="", lines=[line],
        wfirma_contractor_id="999",
    )
    root = _parse_proforma_xml(req)
    content = root.find(".//invoicecontent")
    assert _find_text(content, "count") == "3.0000"
    assert _find_text(content, "unit_count") == "3.0000"
    assert _find_text(content, "price") == "200.00"
    assert _find_text(content, "unit") == "szt."
    # Identity is the good id reference, not an inline name
    assert _find_text(content, "good", "id") == "GD-678"
    assert content.find("name") is None


# ── Tests: write methods still gated (only customers/products/proforma) ──────
#
# Phase 3.A implements: search_customer, get_product_by_code, find_vat_code_id,
# create_reservation. The remaining write methods (create_customer,
# create_product, get_stock, create_proforma_draft) stay as NotImplementedError.

def test_create_customer_raises():
    with pytest.raises(NotImplementedError):
        create_customer("Dream Rings")


def test_create_product_validates_required_args():
    """create_product is now implemented; bare-minimum arg validation only."""
    from app.services.wfirma_client import create_product
    with pytest.raises(ValueError, match="product_code is required"):
        create_product("", "Test")
    with pytest.raises(ValueError, match="name is required"):
        create_product("EJL/X", "")


def test_get_stock_raises():
    with pytest.raises(NotImplementedError):
        get_stock("GD-001")


def test_create_proforma_validates_required_args():
    """create_proforma_draft is now implemented; arg validation lives in client."""
    req = ProformaRequest(
        client_name="", client_zip="", client_city="",
        lines=_sample_lines(1),
    )
    with pytest.raises(ValueError, match="client_name"):
        create_proforma_draft(req)


# ── Tests: search_customer (live read, mocked HTTP) ──────────────────────────

def _resp(status_code: int, text: str):
    from unittest.mock import MagicMock
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    return r


_XML_CONTRACTOR_OK = """<api>
  <contractors>
    <contractor>
      <id>12345678</id>
      <name>Dream Rings Ltd</name>
      <nip>GB123456789</nip>
      <country>GB</country>
      <zip>SW1A 1AA</zip>
      <city>London</city>
    </contractor>
  </contractors>
  <status><code>OK</code></status>
</api>"""

_XML_CONTRACTOR_EMPTY = """<api>
  <contractors></contractors>
  <status><code>OK</code></status>
</api>"""

_XML_AUTH_FAILED = """<api>
  <status><code>AUTH_FAILED</code><description>Invalid API key</description></status>
</api>"""


def test_search_customer_match():
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request",
                   return_value=_resp(200, _XML_CONTRACTOR_OK)):
            c = search_customer("Dream Rings")
    assert c is not None
    assert c.wfirma_id == "12345678"
    assert c.name == "Dream Rings Ltd"
    assert c.country == "GB"


def test_search_customer_no_match():
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request",
                   return_value=_resp(200, _XML_CONTRACTOR_EMPTY)):
            c = search_customer("Nobody")
    assert c is None


def test_search_customer_auth_failed_raises():
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request",
                   return_value=_resp(200, _XML_AUTH_FAILED)):
            with pytest.raises(RuntimeError, match="AUTH_FAILED"):
                search_customer("Dream Rings")


def test_search_customer_http_error_raises():
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request",
                   return_value=_resp(500, "<html>Server Error</html>")):
            with pytest.raises(RuntimeError, match="HTTP 500"):
                search_customer("Dream Rings")


def test_search_customer_by_nip_uses_eq_operator():
    captured = {}
    def _capture(method, url, **kwargs):
        captured["body"] = kwargs.get("data", b"").decode("utf-8")
        return _resp(200, _XML_CONTRACTOR_OK)

    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_capture):
            search_customer("", nip="GB123456789")
    # Body should use eq/nip, not like/name
    assert "<field>nip</field>" in captured["body"]
    assert "<operator>eq</operator>" in captured["body"]
    assert "GB123456789" in captured["body"]


# ── Tests: get_product_by_code (live read, mocked HTTP) ──────────────────────

_XML_GOOD_OK = """<api>
  <goods>
    <good>
      <id>987654</id>
      <name>Pierscionek</name>
      <code>EJL/26-27/015-6</code>
      <unit>szt.</unit>
      <count>10.0000</count>
      <reserved>2.0000</reserved>
    </good>
  </goods>
  <status><code>OK</code></status>
</api>"""

_XML_GOOD_EMPTY = """<api>
  <goods></goods>
  <status><code>OK</code></status>
</api>"""


def test_get_product_by_code_match_with_stock():
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request",
                   return_value=_resp(200, _XML_GOOD_OK)):
            p = get_product_by_code("EJL/26-27/015-6")
    assert p is not None
    assert p.wfirma_id == "987654"
    assert p.code == "EJL/26-27/015-6"
    assert p.count == 10.0
    assert p.reserved == 2.0
    assert p.available == 8.0


def test_get_product_by_code_no_match():
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request",
                   return_value=_resp(200, _XML_GOOD_EMPTY)):
            p = get_product_by_code("NOPE")
    assert p is None


def test_get_product_by_code_empty_input():
    p = get_product_by_code("")
    assert p is None


# ── Tests: find_vat_code_id (delegates to find_vat_code_id_live) ─────────────

_XML_VAT_23 = """<api>
  <vat_codes>
    <vat_code><id>222</id><code>23</code><rate>23</rate></vat_code>
  </vat_codes>
  <status><code>OK</code></status>
</api>"""


def test_find_vat_code_id_returns_id():
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request",
                   return_value=_resp(200, _XML_VAT_23)):
            vid = find_vat_code_id(23)
    assert vid == "222"


# ── Tests: create_reservation (live POST, mocked HTTP) ───────────────────────

_XML_RESERVATION_OK = """<api>
  <warehouse_documents>
    <warehouse_document>
      <id>876543</id>
    </warehouse_document>
  </warehouse_documents>
  <status><code>OK</code></status>
</api>"""

_XML_VALIDATION_ERROR = """<api>
  <status><code>VALIDATION_ERROR</code><description>price must be positive</description></status>
</api>"""


def _sample_request(n: int = 2):
    return ReservationRequest(
        batch_id="B1", client_name="Dream Rings",
        wfirma_contractor_id="C-001", wfirma_warehouse_id="WH-001",
        date="2026-05-03",
        lines=_sample_lines(n),
    )


def test_create_reservation_success():
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request",
                   return_value=_resp(200, _XML_RESERVATION_OK)):
            res = create_reservation(_sample_request(2))
    assert res.ok is True
    assert res.wfirma_reservation_id == "876543"
    assert res.error is None or res.error == ""


def test_create_reservation_validation_error():
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request",
                   return_value=_resp(200, _XML_VALIDATION_ERROR)):
            res = create_reservation(_sample_request(1))
    assert res.ok is False
    assert "VALIDATION_ERROR" in res.error
    assert "positive" in res.error


def test_create_reservation_auth_failed():
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request",
                   return_value=_resp(200, _XML_AUTH_FAILED)):
            res = create_reservation(_sample_request(1))
    assert res.ok is False
    assert "AUTH_FAILED" in res.error


def test_create_reservation_connection_error():
    import requests as rq
    def _raise(method, url, **kwargs):
        raise rq.exceptions.ConnectionError("connection refused")

    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_raise):
            res = create_reservation(_sample_request(1))
    assert res.ok is False
    assert "connection" in res.error.lower()


def test_create_reservation_http_500():
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request",
                   return_value=_resp(500, "<html>err</html>")):
            res = create_reservation(_sample_request(1))
    assert res.ok is False
    assert "HTTP 500" in res.error


def test_create_reservation_response_missing_id():
    """OK status but no <warehouse_document><id> — must NOT report success."""
    xml = """<api>
      <warehouse_documents></warehouse_documents>
      <status><code>OK</code></status>
    </api>"""
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request",
                   return_value=_resp(200, xml)):
            res = create_reservation(_sample_request(1))
    assert res.ok is False
    assert "no warehouse_document.id" in res.error


def test_create_reservation_uses_api_key_auth():
    """create_reservation must use API Key headers (Basic Auth deprecated 2023-07-02)."""
    captured = {}
    def _capture(method, url, **kwargs):
        captured["headers"] = kwargs.get("headers") or {}
        captured["url"] = url
        captured["method"] = method
        return _resp(200, _XML_RESERVATION_OK)

    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_capture):
            create_reservation(_sample_request(1))
    assert "warehouse_document_r/add" in captured["url"]
    assert captured["method"].upper() == "POST"
    assert "accessKey" in captured["headers"]
    assert "secretKey" in captured["headers"]
    assert "appKey" in captured["headers"]
    # No Basic Auth header
    assert "Authorization" not in captured["headers"]


def test_create_reservation_xml_body_contains_required_fields():
    captured = {}
    def _capture(method, url, **kwargs):
        captured["body"] = kwargs.get("data", b"").decode("utf-8")
        return _resp(200, _XML_RESERVATION_OK)

    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_capture):
            create_reservation(_sample_request(2))
    body = captured["body"]
    assert "<contractor>" in body
    assert "<id>C-001</id>" in body
    assert "<price_type>netto</price_type>" in body
    assert "<status>pending</status>" in body
    assert body.count("<warehouse_document_content>") == 2


def test_create_reservation_empty_lines_returns_invalid():
    req = ReservationRequest(
        batch_id="B", client_name="X", wfirma_contractor_id="C",
        wfirma_warehouse_id="WH", date="2026-05-03",
        lines=[],
    )
    res = create_reservation(req)
    assert res.ok is False
    assert "lines" in res.error.lower() or "invalid" in res.error.lower()


def test_create_reservation_empty_contractor_returns_invalid():
    req = ReservationRequest(
        batch_id="B", client_name="X", wfirma_contractor_id="",
        wfirma_warehouse_id="WH", date="2026-05-03",
        lines=_sample_lines(1),
    )
    res = create_reservation(req)
    assert res.ok is False


# ── Tests: WFirmaProduct.available ───────────────────────────────────────────

def test_product_available_simple():
    p = WFirmaProduct(wfirma_id="1", name="X", code="EJL/1", count=10.0, reserved=3.0)
    assert p.available == 7.0


def test_product_available_fully_reserved():
    p = WFirmaProduct(wfirma_id="1", name="X", code="EJL/1", count=5.0, reserved=5.0)
    assert p.available == 0.0


def test_product_available_over_reserved_clamps_to_zero():
    # Edge: reserved > count (data inconsistency) — should not return negative
    p = WFirmaProduct(wfirma_id="1", name="X", code="EJL/1", count=3.0, reserved=5.0)
    assert p.available == 0.0


# ── create_proforma_draft live wrapper ─────────────────────────────────────

from app.services import wfirma_client as _wc


def _ok_invoice_response(wfirma_id: str = "55512345") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <invoice>
      <id>{wfirma_id}</id>
      <fullnumber>FP 5/2026</fullnumber>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""


def _err_invoice_response(code: str = "ERROR", desc: str = "boom") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <status><code>{code}</code><message>{desc}</message></status>
</api>"""


def _proforma_request(currency: str = "USD"):
    line = _wc.ReservationLine(
        product_code   = "EJL/25-26/1274-3",
        wfirma_good_id = "48611875",          # required by validated wFirma shape
        product_name   = "Pierścionek",
        qty            = 1.0,
        unit_price     = 173.0,
        unit           = "szt.",
        currency       = currency,
    )
    return _wc.ProformaRequest(
        client_name          = "Juliany EOOD",
        client_zip           = "1000",
        client_city          = "Sofia",
        lines                = [line],
        currency             = currency,
        wfirma_contractor_id = "176578339",  # required by validated wFirma shape
    )


def test_create_proforma_draft_posts_invoices_add(monkeypatch):
    captured = {}
    def fake_http(method, module, action, body):
        captured.update(method=method, module=module, action=action, body=body)
        return 200, _ok_invoice_response("99887766")
    monkeypatch.setattr(_wc, "_http_request", fake_http)

    res = _wc.create_proforma_draft(_proforma_request())
    assert captured["method"] == "POST"
    assert captured["module"] == "invoices"
    assert captured["action"] == "add"
    assert "<type>proforma</type>" in captured["body"]
    # Currency preserved in request XML
    assert "<currency>USD</currency>" in captured["body"]
    # Result shape
    assert res.ok is True
    assert res.wfirma_invoice_id == "99887766"


def test_create_proforma_draft_raises_on_non_ok_status(monkeypatch):
    monkeypatch.setattr(
        _wc, "_http_request",
        lambda *a, **k: (200, _err_invoice_response("DENIED", "no money")),
    )
    with pytest.raises(RuntimeError, match="DENIED"):
        _wc.create_proforma_draft(_proforma_request())


def test_create_proforma_draft_raises_on_http_4xx(monkeypatch):
    monkeypatch.setattr(_wc, "_http_request",
                        lambda *a, **k: (502, "<api/>"))
    with pytest.raises(RuntimeError, match="HTTP 502"):
        _wc.create_proforma_draft(_proforma_request())


def test_create_proforma_draft_raises_when_id_missing(monkeypatch):
    no_id = """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices><invoice><fullnumber>FP 1/2026</fullnumber></invoice></invoices>
  <status><code>OK</code></status>
</api>"""
    monkeypatch.setattr(_wc, "_http_request", lambda *a, **k: (200, no_id))
    with pytest.raises(RuntimeError, match="no <id>"):
        _wc.create_proforma_draft(_proforma_request())


def test_create_proforma_draft_raises_on_empty_lines():
    req = _wc.ProformaRequest(
        client_name="Juliany EOOD", client_zip="", client_city="",
        lines=[], currency="USD",
    )
    with pytest.raises(ValueError, match="at least one line"):
        _wc.create_proforma_draft(req)


def test_create_proforma_draft_raises_on_empty_client_name():
    line = _wc.ReservationLine(
        product_code="X", wfirma_good_id="", product_name="x",
        qty=1, unit_price=1, currency="USD",
    )
    req = _wc.ProformaRequest(
        client_name="", client_zip="", client_city="",
        lines=[line], currency="USD",
    )
    with pytest.raises(ValueError, match="client_name"):
        _wc.create_proforma_draft(req)


# ── edit_product (goods/edit) wrapper ──────────────────────────────────────

def _ok_good_edit_response(wfirma_id: str = "G-EDIT-1",
                            name: str = "new name") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <goods>
    <good>
      <id>{wfirma_id}</id>
      <name>{name}</name>
      <code>EJL/X</code>
      <unit>szt.</unit>
    </good>
  </goods>
  <status><code>OK</code></status>
</api>"""


def test_edit_product_minimal_payload(monkeypatch):
    """Body contains id + name + description ONLY. No accounting fields."""
    captured = {}
    def fake_http(method, module, action, body):
        captured.update(method=method, module=module, action=action, body=body)
        return 200, _ok_good_edit_response("48611875", "new name")
    monkeypatch.setattr(_wc, "_http_request", fake_http)

    out = _wc.edit_product(
        "48611875",
        name        = "Pierścionek z platyny / Diamond Ring",
        description = "Co to za towar / What is this: ...",
    )
    assert captured["method"] == "POST"
    assert captured["module"] == "goods"
    assert captured["action"] == "edit"
    body = captured["body"]
    # Required: id, name, description
    assert "<id>48611875</id>" in body
    assert "Pierścionek z platyny / Diamond Ring" in body
    assert "<description>Co to za towar / What is this: ...</description>" in body
    # Forbidden: must NOT mutate accounting/identity fields
    for forbidden in ("<code>", "<price>", "<vat>", "<unit>",
                      "<count>", "<reserved>", "<type>", "<warehouse_type>"):
        assert forbidden not in body, f"forbidden field {forbidden} in payload"
    # Result shape
    assert out["wfirma_id"] == "48611875"


def test_edit_product_raises_on_empty_id():
    with pytest.raises(ValueError, match="wfirma_product_id is required"):
        _wc.edit_product("", name="x")


def test_edit_product_raises_when_no_fields_to_update():
    with pytest.raises(ValueError, match="at least one of name/description"):
        _wc.edit_product("48611875")


def test_edit_product_omits_blank_field_from_payload(monkeypatch):
    """Only non-blank fields are serialised into the body."""
    captured = {}
    def fake_http(method, module, action, body):
        captured["body"] = body
        return 200, _ok_good_edit_response()
    monkeypatch.setattr(_wc, "_http_request", fake_http)
    _wc.edit_product("48611875", name="just a name update", description="")
    assert "<name>just a name update</name>" in captured["body"]
    assert "<description>" not in captured["body"]


def test_edit_product_raises_on_non_ok_status(monkeypatch):
    monkeypatch.setattr(
        _wc, "_http_request",
        lambda *a, **k: (200, _err_invoice_response("DENIED", "reason")),
    )
    with pytest.raises(RuntimeError, match="DENIED"):
        _wc.edit_product("48611875", name="x")


def test_edit_product_raises_on_http_4xx(monkeypatch):
    monkeypatch.setattr(_wc, "_http_request",
                        lambda *a, **k: (404, "not found"))
    with pytest.raises(RuntimeError, match="HTTP 404"):
        _wc.edit_product("48611875", name="x")


def test_edit_product_raises_when_response_id_missing(monkeypatch):
    no_id = """<?xml version="1.0" encoding="UTF-8"?>
<api><goods><good><name>x</name></good></goods><status><code>OK</code></status></api>"""
    monkeypatch.setattr(_wc, "_http_request", lambda *a, **k: (200, no_id))
    with pytest.raises(RuntimeError, match="no <id>"):
        _wc.edit_product("48611875", name="x")


def test_build_proforma_xml_omits_currency_when_blank():
    line = _wc.ReservationLine(
        product_code="X", wfirma_good_id="GID-1", product_name="x",
        qty=1, unit_price=1, currency="",
    )
    req = _wc.ProformaRequest(
        client_name="C", client_zip="", client_city="",
        lines=[line], currency="", wfirma_contractor_id="CID-1",
    )
    xml = _wc._build_proforma_xml(req)
    assert "<currency>" not in xml


# ── XML shape: contractor/id and good/id references ────────────────────────

def test_build_proforma_xml_uses_contractor_id_reference():
    """Validated wFirma shape: <contractor><id>...</id></contractor>."""
    xml = _wc._build_proforma_xml(_proforma_request())
    assert "<contractor><id>176578339</id></contractor>" in xml
    # No inline contractor name/address fields
    assert "<contractor><name>" not in xml
    assert "<zip>"  not in xml
    assert "<city>" not in xml


def test_build_proforma_xml_uses_good_id_reference_per_line():
    """Validated wFirma shape: <invoicecontent><good><id>...</id></good>...]"""
    xml = _wc._build_proforma_xml(_proforma_request())
    assert "<good><id>48611875</id></good>" in xml
    # The line block must NOT carry product_code/product_name as identity —
    # identity is the good_id only.
    assert "EJL/25-26/1274-3" not in xml
    assert "Pierścionek"      not in xml


def test_build_proforma_xml_raises_on_missing_contractor_id():
    line = _wc.ReservationLine(
        product_code="X", wfirma_good_id="GID-1", product_name="x",
        qty=1, unit_price=1, currency="USD",
    )
    req = _wc.ProformaRequest(
        client_name="C", client_zip="", client_city="",
        lines=[line], currency="USD", wfirma_contractor_id="",
    )
    with pytest.raises(ValueError, match="wfirma_contractor_id is required"):
        _wc._build_proforma_xml(req)


def test_build_proforma_xml_raises_on_missing_good_id():
    line = _wc.ReservationLine(
        product_code="X", wfirma_good_id="", product_name="x",
        qty=1, unit_price=1, currency="USD",
    )
    req = _wc.ProformaRequest(
        client_name="C", client_zip="", client_city="",
        lines=[line], currency="USD", wfirma_contractor_id="CID-1",
    )
    with pytest.raises(ValueError, match="wfirma_good_id is required"):
        _wc._build_proforma_xml(req)
