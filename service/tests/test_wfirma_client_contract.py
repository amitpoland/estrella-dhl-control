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
from app.services import wfirma_client as _wfirma_client_mod


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _prime_vat_code_cache():
    """
    _build_proforma_xml now resolves a per-line vat_code id via a live
    helper. Tests must not hit the network; pre-populate the cache so
    the helper short-circuits, then clear it after the test so we don't
    cross-pollute negative tests that need to exercise the lookup.
    """
    _wfirma_client_mod._VAT_CODE_ID_CACHE[23] = "222"
    yield
    _wfirma_client_mod._VAT_CODE_ID_CACHE.pop(23, None)

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


def _verify_find_response(wfirma_id: str, good_ids):
    """Synthesise an invoices/find response with one <invoicecontent> per id."""
    rows = "".join(
        f"<invoicecontent><id>L{i}</id><good><id>{gid}</id></good></invoicecontent>"
        for i, gid in enumerate(good_ids)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <invoice>
      <id>{wfirma_id}</id>
      <type>proforma</type>
      <invoicecontents>{rows}</invoicecontents>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""


def _http_seq(*responses):
    """Build a fake _http_request that pops responses in order."""
    seq = list(responses)
    captured = []
    def fake(method, module, action, body, id_suffix=None):
        captured.append({"method": method, "module": module, "action": action,
                         "body": body, "id_suffix": id_suffix})
        if not seq:
            raise AssertionError("unexpected extra _http_request call")
        return seq.pop(0)
    fake.captured = captured
    return fake


def test_create_proforma_draft_posts_invoices_add_and_verifies(monkeypatch):
    """add → verify-fetch → success when persisted line count matches."""
    fake = _http_seq(
        (200, _ok_invoice_response("99887766")),
        (200, _verify_find_response("99887766", ["48611875"])),
    )
    monkeypatch.setattr(_wc, "_http_request", fake)

    res = _wc.create_proforma_draft(_proforma_request())
    assert fake.captured[0]["method"] == "POST"
    assert fake.captured[0]["module"] == "invoices"
    assert fake.captured[0]["action"] == "add"
    assert "<type>proforma</type>" in fake.captured[0]["body"]
    assert "<currency>USD</currency>" in fake.captured[0]["body"]
    # Verify-after-create fetch happens immediately.
    assert fake.captured[1]["method"] == "GET"
    assert fake.captured[1]["module"] == "invoices"
    assert fake.captured[1]["action"] == "find"
    assert "<value>99887766</value>" in fake.captured[1]["body"]
    assert res.ok is True
    assert res.wfirma_invoice_id == "99887766"


def test_create_proforma_draft_raises_on_partial_persistence(monkeypatch):
    """
    wFirma returned OK + valid id, but only N of the M submitted lines
    were persisted. Must raise RuntimeError with expected/actual counts
    and the missing good_ids — never silently report success.
    Mirrors live incident on PROF 92/2026 (2026-05-06).
    """
    # Build a 3-line request and have wFirma "persist" only 1.
    line = lambda gid: _wc.ReservationLine(
        product_code=f"EJL/{gid}", wfirma_good_id=gid, product_name="x",
        qty=1, unit_price=10, currency="USD",
    )
    req = _wc.ProformaRequest(
        client_name="Juliany EOOD", client_zip="", client_city="",
        lines=[line("G1"), line("G2"), line("G3")],
        currency="USD", wfirma_contractor_id="C1",
    )
    fake = _http_seq(
        (200, _ok_invoice_response("465611619")),
        (200, _verify_find_response("465611619", ["G1"])),  # only 1 of 3
    )
    monkeypatch.setattr(_wc, "_http_request", fake)
    with pytest.raises(RuntimeError) as excinfo:
        _wc.create_proforma_draft(req)
    msg = str(excinfo.value)
    assert "partial persistence" in msg
    assert "expected_count=3" in msg
    assert "actual_count=1" in msg
    assert "G2" in msg and "G3" in msg
    assert "wfirma_invoice_id=465611619" in msg


def test_create_proforma_draft_raises_when_verify_fetch_fails(monkeypatch):
    """
    add succeeded but the immediate verify-fetch errored. Must raise
    so the caller doesn't mark the draft 'issued' against an unverified
    invoice id.
    """
    fake = _http_seq(
        (200, _ok_invoice_response("465611619")),
        (502, "boom"),
    )
    monkeypatch.setattr(_wc, "_http_request", fake)
    with pytest.raises(RuntimeError, match="verify-fetch failed"):
        _wc.create_proforma_draft(_proforma_request())


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


def test_build_proforma_xml_does_not_collapse_duplicate_good_ids():
    """
    Local builder must emit one <invoicecontent> per request line, even
    when several lines share the same wfirma_good_id (live data: Juliany
    1274-7 appears 4×). Collapsing pre-submission would mask the wFirma
    bug entirely.
    """
    line = lambda gid, qty: _wc.ReservationLine(
        product_code="EJL/X", wfirma_good_id=gid, product_name="x",
        qty=qty, unit_price=10, currency="USD",
    )
    req = _wc.ProformaRequest(
        client_name="C", client_zip="", client_city="",
        lines=[line("G7", 1), line("G7", 1), line("G7", 1), line("G7", 1),
               line("G4", 1), line("G4", 1)],
        currency="USD", wfirma_contractor_id="C1",
    )
    body = _wc._build_proforma_xml(req)
    # 6 distinct invoicecontent blocks even though only 2 unique good_ids.
    assert body.count("<invoicecontent>") == 6
    assert body.count("<good><id>G7</id></good>") == 4
    assert body.count("<good><id>G4</id></good>") == 2


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
    """
    URL contains /goods/edit/{wfirma_product_id} (id in path, NOT body).
    Body contains <name>/<description> only — no <id>, no accounting fields.
    """
    captured = {}
    def fake_http(method, module, action, body, id_suffix=None):
        captured.update(method=method, module=module, action=action,
                        body=body, id_suffix=id_suffix)
        return 200, _ok_good_edit_response("48611875", "new name")
    monkeypatch.setattr(_wc, "_http_request", fake_http)

    out = _wc.edit_product(
        "48611875",
        name        = "Pierścionek z platyny / Diamond Ring",
        description = "Co to za towar / What is this: ...",
    )
    assert captured["method"]    == "POST"
    assert captured["module"]    == "goods"
    assert captured["action"]    == "edit"
    assert captured["id_suffix"] == "48611875"     # id in URL path
    body = captured["body"]
    # Required body fields
    assert "Pierścionek z platyny / Diamond Ring" in body
    assert "<description>Co to za towar / What is this: ...</description>" in body
    # CRITICAL: id MUST NOT appear in the body — wFirma rejects with
    # NOT_FOUND if id is in body (live diagnostic confirmed).
    assert "<id>" not in body, "id must be in URL, not body"
    # Forbidden: must NOT mutate accounting/identity fields
    for forbidden in ("<code>", "<price>", "<vat>", "<unit>",
                      "<count>", "<reserved>", "<type>", "<warehouse_type>"):
        assert forbidden not in body, f"forbidden field {forbidden} in payload"
    # Result shape
    assert out["wfirma_id"] == "48611875"


def test_http_request_appends_id_suffix_to_url():
    """_http_request id_suffix kwarg is inserted into URL path before query."""
    from unittest.mock import patch as _p
    captured = {}
    class _R:
        def __init__(self): self.status_code = 200; self.text = "<api/>"
    def fake_request(method, url, headers=None, data=None, timeout=None):
        captured["url"] = url
        return _R()
    with (
        _p.object(_wc, "_requests") as mock_req,
        _p.object(settings, "wfirma_company_id", "99999"),
    ):
        mock_req.request = fake_request
        mock_req.exceptions.RequestException = Exception
        _wc._http_request("POST", "goods", "edit", "<api/>",
                           id_suffix="48611875")
    assert "/goods/edit/48611875?" in captured["url"]
    assert "company_id=99999" in captured["url"]


def test_edit_product_raises_on_empty_id():
    with pytest.raises(ValueError, match="wfirma_product_id is required"):
        _wc.edit_product("", name="x")


def test_edit_product_raises_when_no_fields_to_update():
    with pytest.raises(ValueError, match="at least one of name/description"):
        _wc.edit_product("48611875")


def test_edit_product_omits_blank_field_from_payload(monkeypatch):
    """Only non-blank fields are serialised into the body."""
    captured = {}
    def fake_http(method, module, action, body, id_suffix=None):
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


# ── invoices/find + invoices/edit (line-name refresh) ──────────────────────

_OK_INVOICE_FIND_XML = """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <invoice>
      <id>465611619</id>
      <type>proforma</type>
      <invoicecontents>
        <invoicecontent>
          <id>1495642083</id>
          <name>Pierścionek (EJL/25-26/1274-3)</name>
          <count>1.0000</count>
          <unit_count>1.0000</unit_count>
          <price>173.00</price>
          <discount>1</discount>
          <discount_percent>0.00</discount_percent>
          <unit>szt.</unit>
          <good><id>48611875</id></good>
          <vat_code><id>222</id></vat_code>
        </invoicecontent>
      </invoicecontents>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""


def test_fetch_invoice_xml_get_invoices_find(monkeypatch):
    captured = {}
    def fake_http(method, module, action, body, id_suffix=None):
        captured.update(method=method, module=module, action=action,
                        body=body, id_suffix=id_suffix)
        return 200, _OK_INVOICE_FIND_XML
    monkeypatch.setattr(_wc, "_http_request", fake_http)

    text = _wc.fetch_invoice_xml("465611619")
    assert captured["method"] == "GET"
    assert captured["module"] == "invoices"
    assert captured["action"] == "find"
    assert captured["id_suffix"] is None
    assert "<field>id</field>" in captured["body"]
    assert "<value>465611619</value>" in captured["body"]
    assert "<id>465611619</id>" in text
    assert "<type>proforma</type>" in text


def test_fetch_invoice_xml_raises_on_empty_id():
    with pytest.raises(ValueError, match="invoice_id is required"):
        _wc.fetch_invoice_xml("")


def test_fetch_invoice_xml_raises_on_non_ok(monkeypatch):
    monkeypatch.setattr(_wc, "_http_request",
                        lambda *a, **k: (200, _err_invoice_response("ERROR", "boom")))
    with pytest.raises(RuntimeError, match="ERROR"):
        _wc.fetch_invoice_xml("465611619")


def test_fetch_invoice_xml_raises_when_no_invoice(monkeypatch):
    no_inv = """<?xml version="1.0" encoding="UTF-8"?>
<api><invoices/><status><code>OK</code></status></api>"""
    monkeypatch.setattr(_wc, "_http_request", lambda *a, **k: (200, no_inv))
    with pytest.raises(RuntimeError, match="no <invoice>"):
        _wc.fetch_invoice_xml("465611619")


_LINE_XML = """<invoicecontent>
          <id>1495642083</id>
          <name>Pierścionek (EJL/25-26/1274-3)</name>
          <count>1.0000</count>
          <unit_count>1.0000</unit_count>
          <price>173.00</price>
          <discount>1</discount>
          <discount_percent>0.00</discount_percent>
          <unit>szt.</unit>
          <good><id>48611875</id></good>
          <vat_code><id>222</id></vat_code>
        </invoicecontent>"""


def test_edit_invoice_line_name_full_restate(monkeypatch):
    """
    URL = /invoices/edit/{invoice_id}; body restates full invoicecontent
    with only <name> swapped. wFirma rejects partial line edits
    (NOT_FOUND), so every other child element must round-trip.
    """
    captured = {}
    def fake_http(method, module, action, body, id_suffix=None):
        captured.update(method=method, module=module, action=action,
                        body=body, id_suffix=id_suffix)
        return 200, _OK_INVOICE_FIND_XML  # OK status echo
    monkeypatch.setattr(_wc, "_http_request", fake_http)

    out = _wc.edit_invoice_line_name(
        "465611619", _LINE_XML,
        "pierścionek ze złota próby 585 / Lab Grown Diamond Studded 14KT Gold Ring",
    )
    assert captured["method"]    == "POST"
    assert captured["module"]    == "invoices"
    assert captured["action"]    == "edit"
    assert captured["id_suffix"] == "465611619"     # id in URL path
    body = captured["body"]
    # Required preserved fields
    assert "<id>1495642083</id>" in body
    assert "<good><id>48611875</id></good>" in body
    assert "<vat_code><id>222</id></vat_code>" in body
    assert "<count>1.0000</count>" in body
    assert "<price>173.00</price>" in body
    assert "<discount>1</discount>" in body
    assert "<unit>szt.</unit>" in body
    # The new name is present, the old name is GONE.
    assert "Lab Grown Diamond Studded 14KT Gold Ring" in body
    assert "Pierścionek (EJL/25-26/1274-3)" not in body
    # Result shape
    assert out["invoice_id"]        == "465611619"
    assert out["invoicecontent_id"] == "1495642083"


def test_edit_invoice_line_name_only_changes_name(monkeypatch):
    """Diff between input <invoicecontent> and emitted XML is exclusively <name>."""
    captured = {}
    def fake_http(method, module, action, body, id_suffix=None):
        captured["body"] = body
        return 200, _OK_INVOICE_FIND_XML
    monkeypatch.setattr(_wc, "_http_request", fake_http)
    _wc.edit_invoice_line_name("465611619", _LINE_XML, "NEW NAME")
    import xml.etree.ElementTree as _ET
    src = _ET.fromstring(_LINE_XML)
    # Locate the emitted invoicecontent inside the <api> body.
    emitted_root = _ET.fromstring(captured["body"])
    emitted = emitted_root.find(".//invoicecontent")
    assert emitted is not None
    src_children = {c.tag for c in src}
    emitted_children = {c.tag for c in emitted}
    assert src_children == emitted_children, "no fields added or dropped"
    for tag in src_children:
        if tag == "name":
            assert (emitted.findtext("name") or "").strip() == "NEW NAME"
        else:
            # Same text and same shallow XML for every other tag.
            assert (_ET.tostring(src.find(tag), encoding="unicode").strip()
                    == _ET.tostring(emitted.find(tag), encoding="unicode").strip()), \
                f"field <{tag}> differs between source and emitted"


def test_edit_invoice_line_name_raises_on_non_ok(monkeypatch):
    monkeypatch.setattr(_wc, "_http_request",
        lambda *a, **k: (200, _err_invoice_response("ERROR", "boom")))
    with pytest.raises(RuntimeError, match="ERROR"):
        _wc.edit_invoice_line_name("465611619", _LINE_XML, "X")


def test_edit_invoice_line_name_raises_on_http_4xx(monkeypatch):
    monkeypatch.setattr(_wc, "_http_request", lambda *a, **k: (500, "boom"))
    with pytest.raises(RuntimeError, match="HTTP 500"):
        _wc.edit_invoice_line_name("465611619", _LINE_XML, "X")


def test_edit_invoice_line_name_validates_args():
    with pytest.raises(ValueError, match="invoice_id is required"):
        _wc.edit_invoice_line_name("", _LINE_XML, "X")
    with pytest.raises(ValueError, match="invoicecontent_xml is required"):
        _wc.edit_invoice_line_name("465611619", "", "X")
    with pytest.raises(ValueError, match="new_name is required"):
        _wc.edit_invoice_line_name("465611619", _LINE_XML, "")
    with pytest.raises(ValueError, match="not well-formed"):
        _wc.edit_invoice_line_name("465611619", "<not xml", "X")
    with pytest.raises(ValueError, match="must be <invoicecontent>"):
        _wc.edit_invoice_line_name("465611619", "<wrong/>", "X")


# ── Per-line shape: missing-fields fix for PROF 92/2026 partial persistence ──

def _line(gid, qty=1.0, price=10.0):
    return _wc.ReservationLine(
        product_code=f"EJL/{gid}", wfirma_good_id=gid, product_name="x",
        qty=qty, unit_price=price, currency="USD",
    )


def _proforma_req(*good_ids):
    return _wc.ProformaRequest(
        client_name="Juliany EOOD", client_zip="", client_city="",
        lines=[_line(g) for g in good_ids],
        currency="USD", wfirma_contractor_id="C-1",
    )


def test_proforma_xml_emits_discount_fields_per_line():
    body = _wc._build_proforma_xml(_proforma_req("G1", "G2", "G3"))
    # one occurrence per line
    assert body.count("<discount>1</discount>") == 3
    assert body.count("<discount_percent>0.00</discount_percent>") == 3
    assert body.count("<price_modified>1</price_modified>") == 3


def test_proforma_xml_emits_vat_code_id_per_line():
    body = _wc._build_proforma_xml(_proforma_req("G1", "G2"))
    assert body.count("<vat_code><id>222</id></vat_code>") == 2


def test_proforma_xml_resolves_vat_code_once_per_process(monkeypatch):
    """A multi-line request should trigger at most one VAT lookup."""
    # Drop the autouse cache priming so we can observe the lookup.
    _wfirma_client_mod._VAT_CODE_ID_CACHE.pop(23, None)
    calls = {"n": 0}
    def fake_lookup(rate=23):
        calls["n"] += 1
        return "222"
    monkeypatch.setattr(_wc, "find_vat_code_id_live", fake_lookup)

    _wc._build_proforma_xml(_proforma_req("G1", "G2", "G3", "G4", "G5"))
    assert calls["n"] == 1, "vat_code lookup must run exactly once for multi-line"

    # Subsequent build re-uses cache → still no extra call.
    _wc._build_proforma_xml(_proforma_req("G6", "G7"))
    assert calls["n"] == 1, "vat_code lookup must be cached process-wide"


def test_proforma_xml_raises_when_vat_lookup_returns_none(monkeypatch):
    """If wFirma has no vat_code for the requested rate, refuse to build."""
    _wfirma_client_mod._VAT_CODE_ID_CACHE.pop(23, None)
    monkeypatch.setattr(_wc, "find_vat_code_id_live", lambda rate=23: None)
    with pytest.raises(RuntimeError, match="no vat_code for rate=23"):
        _wc._build_proforma_xml(_proforma_req("G1"))


def test_proforma_xml_validates_lines_before_vat_lookup(monkeypatch):
    """A bad request (missing wfirma_good_id) must NOT trigger a network call."""
    _wfirma_client_mod._VAT_CODE_ID_CACHE.pop(23, None)
    called = {"n": 0}
    def fake_lookup(rate=23):
        called["n"] += 1
        return "222"
    monkeypatch.setattr(_wc, "find_vat_code_id_live", fake_lookup)

    bad = _wc.ReservationLine(
        product_code="EJL/X", wfirma_good_id="", product_name="x",
        qty=1, unit_price=1, currency="USD",
    )
    req = _wc.ProformaRequest(
        client_name="C", client_zip="", client_city="",
        lines=[bad], currency="USD", wfirma_contractor_id="C1",
    )
    with pytest.raises(ValueError, match="wfirma_good_id is required"):
        _wc._build_proforma_xml(req)
    assert called["n"] == 0, "VAT lookup must not run when validation fails"


def test_proforma_xml_juliany_12line_still_emits_12_blocks():
    """Regression for PROF 92/2026: 12 lines, 7 unique good_ids, no collapse."""
    juliany_pattern = (
        ["G7"] * 4 + ["G4"] * 2 + ["G5"] * 2 +
        ["G3", "G6", "G1", "G2"]   # one each
    )
    body = _wc._build_proforma_xml(_proforma_req(*juliany_pattern))
    assert body.count("<invoicecontent>") == 12
    assert body.count("<good><id>G7</id></good>") == 4
    assert body.count("<good><id>G4</id></good>") == 2
    assert body.count("<good><id>G5</id></good>") == 2
    for one in ("G1", "G2", "G3", "G6"):
        assert body.count(f"<good><id>{one}</id></good>") == 1
    # Per-line shape applies uniformly.
    assert body.count("<vat_code><id>222</id></vat_code>") == 12
    assert body.count("<discount>1</discount>") == 12
    assert body.count("<price_modified>1</price_modified>") == 12
