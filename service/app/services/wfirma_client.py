"""
wfirma_client.py — wFirma API client skeleton.

Skeleton only — no live API calls are made here.
All methods raise NotImplementedError until the POST /reservations/create
route is approved for implementation.

API contract source: docs/wfirma_api_research.md
Auth:
  - Standard modules (contractors, goods, invoices, vat_codes):
      Headers: accessKey, secretKey, appKey
  - Warehouse modules (warehouse_document_r, etc.):

"""
from __future__ import annotations


from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

import requests as _requests

from ..core.config import settings
from ..core.logging import get_logger

log = get_logger(__name__)

BASE_URL = "https://api2.wfirma.pl"

# Modules that require Basic Auth (login:password) instead of API Key headers
_WAREHOUSE_MODULES = frozenset({
    "warehouse_document_r",
    "warehouse_document_p_w",
    "warehouse_document_p_z",
    "warehouse_document_r_w",
    "warehouse_document_w_z",
    "warehouse_document_z_d",
    "warehouse_document_contents",
})


# ── Data transfer objects ─────────────────────────────────────────────────────

@dataclass
class WFirmaContractor:
    """Contractor (customer) record from wFirma."""
    wfirma_id: str
    name: str
    nip: str = ""
    country: str = ""
    zip: str = ""
    city: str = ""


@dataclass
class WFirmaProduct:
    """Good (product) record from wFirma."""
    wfirma_id: str
    name: str
    code: str           # = product_code / invoice symbol (e.g. "EJL/26-27/015-6")
    unit: str = "szt."
    count: float = 0.0  # current stock (read-only from wFirma)
    reserved: float = 0.0  # currently reserved (read-only from wFirma)

    @property
    def available(self) -> float:
        """Units available for new reservations."""
        return max(0.0, self.count - self.reserved)


@dataclass
class ReservationLine:
    """One product line in a reservation."""
    product_code: str       # our product_code (packing.product_code)
    wfirma_good_id: str    # wFirma good ID — resolved before API call
    product_name: str
    qty: float
    unit_price: float
    unit: str = "szt."
    currency: str = "PLN"


@dataclass
class ReservationRequest:
    """Input for create_reservation()."""
    batch_id: str
    client_name: str
    wfirma_contractor_id: str   # resolved before API call
    wfirma_warehouse_id: str
    date: str                   # YYYY-MM-DD
    lines: List[ReservationLine] = field(default_factory=list)
    currency: str = "PLN"
    description: str = ""


@dataclass
class ReservationResult:
    """Output from create_reservation()."""
    ok: bool
    wfirma_reservation_id: Optional[str] = None
    error: Optional[str] = None
    raw_response: Optional[str] = None


@dataclass
class ProformaRequest:
    """Input for create_proforma_draft()."""
    client_name: str
    client_zip: str
    client_city: str
    lines: List[ReservationLine] = field(default_factory=list)
    currency: str = "PLN"


@dataclass
class ProformaResult:
    """Output from create_proforma_draft()."""
    ok: bool
    wfirma_invoice_id: Optional[str] = None
    error: Optional[str] = None
    raw_response: Optional[str] = None


# ── Config check ──────────────────────────────────────────────────────────────

def check_config() -> Dict[str, Any]:
    """
    Validate that all required wFirma settings are present.

    Returns a dict with:
      ok (bool)           — True if all required credentials are set
      missing (list[str]) — names of missing settings
      warehouse_ok (bool) — True if warehouse-specific settings are also present
    """
    missing: List[str] = []

    # API Key auth — required for ALL modules (wFirma deprecated Basic Auth on 2023-07-02)
    if not getattr(settings, "wfirma_access_key", None):
        missing.append("WFIRMA_ACCESS_KEY")
    if not getattr(settings, "wfirma_secret_key", None):
        missing.append("WFIRMA_SECRET_KEY")
    if not getattr(settings, "wfirma_app_key", None):
        missing.append("WFIRMA_APP_KEY")
    if not getattr(settings, "wfirma_company_id", None):
        missing.append("WFIRMA_COMPANY_ID")

    warehouse_ok = bool(
        getattr(settings, "wfirma_warehouse_module_enabled", False)
        and getattr(settings, "wfirma_warehouse_id", None)
    )

    return {
        "ok": len(missing) == 0,
        "missing": missing,
        "warehouse_ok": warehouse_ok,
    }


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _api_key_headers() -> Dict[str, str]:
    """
    Return the 3-header API Key auth headers required by all wFirma modules.
    Raises ValueError if any credential is missing.
    """
    access_key = getattr(settings, "wfirma_access_key", None)
    secret_key = getattr(settings, "wfirma_secret_key", None)
    app_key    = getattr(settings, "wfirma_app_key", None)

    if not (access_key and secret_key and app_key):
        raise ValueError(
            "wFirma API Key credentials not configured "
            "(WFIRMA_ACCESS_KEY / WFIRMA_SECRET_KEY / WFIRMA_APP_KEY)"
        )

    return {
        "accessKey": access_key,
        "secretKey": secret_key,
        "appKey":    app_key,
        "Content-Type": "application/xml",
        "Accept":       "application/xml",
    }


def _headers_for_module(module: str) -> Dict[str, str]:
    """
    Select correct auth headers for the given wFirma module.

    wFirma deprecated Basic Auth on 2023-07-02.  All modules — including
    warehouse_document_r — now require the 3-header API Key method.
    """
    return _api_key_headers()


def _url(module: str, action: str) -> str:
    """Build the wFirma endpoint URL."""
    company_id = getattr(settings, "wfirma_company_id", "")
    return (
        f"{BASE_URL}/{module}/{action}"
        f"?outputFormat=xml&inputFormat=xml&company_id={company_id}"
    )


# ── XML helpers ───────────────────────────────────────────────────────────────

def _parse_status(xml_text: str) -> tuple[str, str]:
    """
    Extract (code, description) from a wFirma XML response.
    Returns ("PARSE_ERROR", message) on malformed XML.
    """
    try:
        root = ET.fromstring(xml_text)
        status = root.find("status")
        if status is None:
            return "UNKNOWN", ""
        code = (status.findtext("code") or "").upper()
        desc = status.findtext("description") or ""
        return code, desc
    except ET.ParseError as exc:
        return "PARSE_ERROR", str(exc)


def _find_text(element: ET.Element, *path: str) -> str:
    """Safely extract text from nested XML elements."""
    node = element
    for tag in path:
        if node is None:
            return ""
        node = node.find(tag)
    return (node.text or "").strip() if node is not None else ""


# ── Live HTTP helpers (read-only) ─────────────────────────────────────────────

# Minimal probe XML bodies for each module — just enough to confirm reachability.
_PROBE_XML: Dict[str, str] = {
    "contractors": """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <contractors>
    <parameters>
      <page><start>0</start><limit>1</limit></page>
    </parameters>
  </contractors>
</api>""",
    "goods": """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <goods>
    <parameters>
      <page><start>0</start><limit>1</limit></page>
    </parameters>
  </goods>
</api>""",
    "warehouses": """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <warehouses>
    <parameters>
      <fields>
        <field>Warehouse.id</field>
        <field>Warehouse.name</field>
      </fields>
    </parameters>
  </warehouses>
</api>""",
    "vat_codes": """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <vat_codes>
    <parameters>
      <page><start>0</start><limit>1</limit></page>
    </parameters>
  </vat_codes>
</api>""",
}


def _http_request(method: str, module: str, action: str, body_xml: str = "") -> tuple[int, str]:
    """
    Make a synchronous HTTP request to the wFirma API.

    Returns (http_status_code, response_text).
    Raises ConnectionError on network failure.
    Raises ValueError if credentials are missing (from _headers_for_module).
    """
    url = _url(module, action)
    headers = _headers_for_module(module)
    try:
        resp = _requests.request(
            method.upper(),
            url,
            headers=headers,
            data=body_xml.encode("utf-8") if body_xml else None,
            timeout=(5, 15),
        )
        return resp.status_code, resp.text
    except _requests.exceptions.RequestException as exc:
        raise ConnectionError(f"wFirma HTTP error ({module}/{action}): {exc}") from exc


def probe_endpoint(module: str, action: str = "find") -> Dict[str, Any]:
    """
    Probe a wFirma read endpoint for reachability.

    Returns a dict with:
      ok (bool)             — True if HTTP < 400 AND wFirma status == OK
      http_status (int)     — HTTP response code (0 = network failure)
      wfirma_status (str)   — wFirma <status><code> value
      error (str)           — Error description, empty on success
    """
    body = _PROBE_XML.get(
        module,
        f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <{module}>
    <parameters>
      <page><start>0</start><limit>1</limit></page>
    </parameters>
  </{module}>
</api>""",
    )
    try:
        http_status, response_text = _http_request("GET", module, action, body)
        wfirma_code, wfirma_desc = _parse_status(response_text)
        ok = http_status < 400 and wfirma_code == "OK"
        return {
            "ok": ok,
            "http_status": http_status,
            "wfirma_status": wfirma_code,
            "error": wfirma_desc if not ok else "",
        }
    except (ConnectionError, ValueError) as exc:
        return {
            "ok": False,
            "http_status": 0,
            "wfirma_status": "CONNECTION_ERROR",
            "error": str(exc),
        }


def list_warehouses() -> List[Dict[str, str]]:
    """
    Fetch all warehouses from wFirma. Read-only.

    Returns a list of {"id": str, "name": str} dicts.
    Raises RuntimeError if the API returns an error.
    Raises ConnectionError on network failure.

    API: GET warehouses/find
    Auth: API Key headers
    """
    body = _PROBE_XML["warehouses"]
    http_status, response_text = _http_request("GET", "warehouses", "find", body)
    if http_status >= 400:
        raise RuntimeError(f"warehouses/find HTTP {http_status}")
    code, desc = _parse_status(response_text)
    if code != "OK":
        raise RuntimeError(f"warehouses/find wFirma status={code}: {desc}")
    root = ET.fromstring(response_text)
    result: List[Dict[str, str]] = []
    for wh in root.findall(".//warehouse"):
        result.append({
            "id":   _find_text(wh, "id"),
            "name": _find_text(wh, "name"),
        })
    return result


def find_vat_code_id_live(rate: int = 23) -> Optional[str]:
    """
    Live implementation: find the wFirma internal ID for a VAT rate.

    Returns the ID string (e.g. "222") or None if not found.
    Raises RuntimeError if the API returns an error status.
    Raises ConnectionError on network failure.

    NOTE: This is the live version. The stub `find_vat_code_id()` below still
    raises NotImplementedError and is kept for the write-gate tests.

    API: GET vat_codes/find
    Auth: API Key headers
    """
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <vat_codes>
    <parameters>
      <conditions>
        <condition>
          <field>code</field>
          <operator>eq</operator>
          <value>{int(rate)}</value>
        </condition>
      </conditions>
    </parameters>
  </vat_codes>
</api>"""
    http_status, response_text = _http_request("GET", "vat_codes", "find", body)
    if http_status >= 400:
        raise RuntimeError(f"vat_codes/find HTTP {http_status}")
    code, desc = _parse_status(response_text)
    if code != "OK":
        raise RuntimeError(f"vat_codes/find wFirma status={code}: {desc}")
    root = ET.fromstring(response_text)
    vat_node = root.find(".//vat_code")
    if vat_node is None:
        return None
    return _find_text(vat_node, "id") or None


# ── Contractors ───────────────────────────────────────────────────────────────

def search_customer(name: str, nip: Optional[str] = None) -> Optional[WFirmaContractor]:
    """
    Search for a contractor in wFirma by name (partial match) or NIP.

    Returns the first matching WFirmaContractor, or None if not found.
    Raises RuntimeError if the API returns an error status.
    Raises ConnectionError on network failure.

    API: GET contractors/find
    Auth: API Key headers
    """
    if not name and not nip:
        return None
    if nip:
        cond = f"<field>nip</field><operator>eq</operator><value>{_esc(nip)}</value>"
    else:
        cond = f"<field>name</field><operator>like</operator><value>%{_esc(name)}%</value>"
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <contractors>
    <parameters>
      <conditions>
        <condition>{cond}</condition>
      </conditions>
      <page><start>0</start><limit>1</limit></page>
    </parameters>
  </contractors>
</api>"""
    http_status, response_text = _http_request("GET", "contractors", "find", body)
    if http_status >= 400:
        raise RuntimeError(f"contractors/find HTTP {http_status}")
    code, desc = _parse_status(response_text)
    if code != "OK":
        raise RuntimeError(f"contractors/find wFirma status={code}: {desc}")
    root = ET.fromstring(response_text)
    node = root.find(".//contractor")
    if node is None:
        return None
    return WFirmaContractor(
        wfirma_id=_find_text(node, "id"),
        name=_find_text(node, "name"),
        nip=_find_text(node, "nip"),
        country=_find_text(node, "country"),
        zip=_find_text(node, "zip"),
        city=_find_text(node, "city"),
    )


def create_customer(
    name: str,
    nip: str = "",
    country: str = "",
    zip_code: str = "",
    city: str = "",
) -> WFirmaContractor:
    """
    Create a new contractor in wFirma.

    Returns the created WFirmaContractor with the assigned wFirma ID.
    Raises NotImplementedError — live calls not yet enabled.

    API: POST contractors/add
    Auth: API Key headers
    Payload: XML with <name>, <nip>, <country>, <zip>, <city>
    """
    raise NotImplementedError(
        "create_customer: live wFirma API calls not yet enabled."
    )


# ── Products (Goods) ──────────────────────────────────────────────────────────

def get_product_by_code(product_code: str) -> Optional[WFirmaProduct]:
    """
    Search for a good in wFirma by its `code` field (= our product_code / invoice symbol).

    Returns WFirmaProduct with current `count` and `reserved` values,
    or None if no good with that code exists.
    Raises RuntimeError if the API returns an error status.
    Raises ConnectionError on network failure.

    API: GET goods/find
    Auth: API Key headers
    Search: conditions.code.eq = product_code
    Returns fields: id, name, code, unit, count, reserved
    """
    if not product_code:
        return None
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <goods>
    <parameters>
      <conditions>
        <condition>
          <field>code</field>
          <operator>eq</operator>
          <value>{_esc(product_code)}</value>
        </condition>
      </conditions>
      <page><start>0</start><limit>1</limit></page>
    </parameters>
  </goods>
</api>"""
    http_status, response_text = _http_request("GET", "goods", "find", body)
    if http_status >= 400:
        raise RuntimeError(f"goods/find HTTP {http_status}")
    code, desc = _parse_status(response_text)
    if code != "OK":
        raise RuntimeError(f"goods/find wFirma status={code}: {desc}")
    root = ET.fromstring(response_text)
    node = root.find(".//good")
    if node is None:
        return None
    def _f(tag: str) -> float:
        try:
            return float(_find_text(node, tag) or 0)
        except (ValueError, TypeError):
            return 0.0
    return WFirmaProduct(
        wfirma_id=_find_text(node, "id"),
        name=_find_text(node, "name"),
        code=_find_text(node, "code") or product_code,
        unit=_find_text(node, "unit") or "szt.",
        count=_f("count"),
        reserved=_f("reserved"),
    )


def create_product(
    product_code: str,
    name: str,
    unit: str = "szt.",
    netto: float = 0.0,
    vat_code_id: Optional[str] = None,
    warehouse_type: str = "simple",
) -> WFirmaProduct:
    """
    Create a new good in wFirma.

    Returns the created WFirmaProduct with the assigned wFirma ID.
    Raises NotImplementedError — live calls not yet enabled.

    API: POST goods/add
    Auth: API Key headers
    Payload: XML with <name>, <code>, <unit>, <netto>, <type>good</type>,
             <vat_code><id>...</id></vat_code>, <warehouse_type>
    """
    raise NotImplementedError(
        "create_product: live wFirma API calls not yet enabled."
    )


def get_stock(wfirma_good_id: str) -> Dict[str, float]:
    """
    Get current stock and reserved quantities for a good.

    Returns {"count": float, "reserved": float, "available": float}
    Raises NotImplementedError — live calls not yet enabled.

    API: GET goods/get (or goods/find with id condition)
    Auth: API Key headers
    Key fields: count (current stock), reserved (currently reserved)
    """
    raise NotImplementedError(
        "get_stock: live wFirma API calls not yet enabled."
    )


# ── VAT Codes ─────────────────────────────────────────────────────────────────

def find_vat_code_id(rate: int = 23) -> Optional[str]:
    """
    Find the wFirma internal ID for a VAT rate (e.g. 23 for 23% VAT).

    Returns the ID string to use in <vat_code><id>X</id></vat_code>,
    or None if not found.

    API: GET vat_codes/find
    Auth: API Key headers
    Search: conditions.code.eq = str(rate)
    Note: vat_codes are read-only — IDs are stable and can be cached.

    Implementation delegates to find_vat_code_id_live (already implemented).
    """
    return find_vat_code_id_live(rate)


# ── Reservations ──────────────────────────────────────────────────────────────

def create_reservation(req: ReservationRequest) -> ReservationResult:
    """
    Create a warehouse reservation document (type R) in wFirma.

    Pre-conditions (caller must verify before calling):
    - req.wfirma_contractor_id is a valid wFirma contractor ID
    - Every line.wfirma_good_id is a valid wFirma good ID
    - Available stock (count - reserved) >= line.qty for each line
    - wFirma warehouse module is enabled and req.wfirma_warehouse_id is set

    API: POST warehouse_document_r/add
    Auth: Basic Auth (login:password)
    Payload shape:
        <api>
          <warehouse_documents>
            <warehouse_document>
              <date>YYYY-MM-DD</date>
              <contractor><id>...</id></contractor>
              <price_type>netto</price_type>
              <status>pending</status>
              <warehouse_document_contents>
                <warehouse_document_content>
                  <name>...</name>
                  <unit_count>...</unit_count>
                  <price>...</price>
                  <good><id>...</id></good>
                  <unit>...</unit>
                </warehouse_document_content>
              </warehouse_document_contents>
            </warehouse_document>
          </warehouse_documents>
        </api>

    Returns ReservationResult.
    Returns ReservationResult(ok=False, error=...) on:
      - HTTP error from wFirma
      - wFirma <status><code> != "OK"
      - Connection error
      - XML parse error
    Never raises — orchestrator gets a structured failure result.
    """
    if not req.wfirma_contractor_id or not req.lines:
        return ReservationResult(
            ok=False,
            error="invalid request: contractor_id and lines required",
        )

    body_xml = _build_reservation_xml(req)
    try:
        http_status, response_text = _http_request(
            "POST", "warehouse_document_r", "add", body_xml,
        )
    except (ConnectionError, ValueError) as exc:
        return ReservationResult(ok=False, error=f"connection: {exc}")

    if http_status >= 400:
        return ReservationResult(
            ok=False,
            error=f"HTTP {http_status}",
            raw_response=response_text,
        )

    code, desc = _parse_status(response_text)
    if code != "OK":
        return ReservationResult(
            ok=False,
            error=f"{code}: {desc}" if desc else code,
            raw_response=response_text,
        )

    # Parse the created reservation ID
    try:
        root = ET.fromstring(response_text)
    except ET.ParseError as exc:
        return ReservationResult(
            ok=False,
            error=f"parse_error: {exc}",
            raw_response=response_text,
        )
    wd_node = root.find(".//warehouse_document")
    wfirma_id = _find_text(wd_node, "id") if wd_node is not None else ""
    if not wfirma_id:
        return ReservationResult(
            ok=False,
            error="no warehouse_document.id in response",
            raw_response=response_text,
        )
    return ReservationResult(
        ok=True,
        wfirma_reservation_id=wfirma_id,
        raw_response=response_text,
    )


def _build_reservation_xml(req: ReservationRequest) -> str:
    """
    Build the XML payload for warehouse_document_r/add.

    Does NOT make any network call. Safe to call in tests.
    Returns a well-formed XML string.
    """
    lines_xml = ""
    for line in req.lines:
        lines_xml += f"""
        <warehouse_document_content>
          <name>{_esc(line.product_name)}</name>
          <unit_count>{line.qty:.4f}</unit_count>
          <price>{line.unit_price:.2f}</price>
          <good>
            <id>{_esc(line.wfirma_good_id)}</id>
          </good>
          <unit>{_esc(line.unit)}</unit>
        </warehouse_document_content>"""

    desc_xml = f"<description>{_esc(req.description)}</description>" if req.description else ""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <warehouse_documents>
    <warehouse_document>
      <date>{req.date}</date>
      <contractor>
        <id>{_esc(req.wfirma_contractor_id)}</id>
      </contractor>
      <price_type>netto</price_type>
      <status>pending</status>
      {desc_xml}
      <warehouse_document_contents>{lines_xml}
      </warehouse_document_contents>
    </warehouse_document>
  </warehouse_documents>
</api>"""


# ── Proforma invoice (fallback) ───────────────────────────────────────────────

def create_proforma_draft(req: ProformaRequest) -> ProformaResult:
    """
    Create a proforma invoice in wFirma (type=proforma).

    Used as fallback when:
    - Warehouse module is not enabled, OR
    - Reservation API is unavailable for a specific line item

    Does NOT block stock — it is a financial document only.

    API: POST invoices/add
    Auth: API Key headers
    Payload shape:
        <api>
          <invoices>
            <invoice>
              <contractor>
                <name>...</name>
                <zip>...</zip>
                <city>...</city>
              </contractor>
              <type>proforma</type>
              <invoicecontents>
                <invoicecontent>
                  <name>...</name>
                  <count>...</count>
                  <unit_count>...</unit_count>
                  <price>...</price>
                  <unit>...</unit>
                </invoicecontent>
              </invoicecontents>
            </invoice>
          </invoices>
        </api>

    Returns ProformaResult with wfirma_invoice_id on success.
    Raises NotImplementedError — live calls not yet enabled.
    """
    raise NotImplementedError(
        "create_proforma_draft: live wFirma API calls not yet enabled."
    )


def _build_proforma_xml(req: ProformaRequest) -> str:
    """
    Build the XML payload for invoices/add with type=proforma.

    Does NOT make any network call. Safe to call in tests.
    Returns a well-formed XML string.
    """
    lines_xml = ""
    for line in req.lines:
        lines_xml += f"""
        <invoicecontent>
          <name>{_esc(line.product_name)} {_esc(line.product_code)}</name>
          <count>{line.qty:.4f}</count>
          <unit_count>{line.qty:.4f}</unit_count>
          <price>{line.unit_price:.2f}</price>
          <unit>{_esc(line.unit)}</unit>
        </invoicecontent>"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <invoice>
      <contractor>
        <name>{_esc(req.client_name)}</name>
        <zip>{_esc(req.client_zip)}</zip>
        <city>{_esc(req.client_city)}</city>
      </contractor>
      <type>proforma</type>
      <invoicecontents>{lines_xml}
      </invoicecontents>
    </invoice>
  </invoices>
</api>"""


# ── Internal utility ──────────────────────────────────────────────────────────

def _esc(value: Any) -> str:
    """XML-escape a value for safe embedding in XML body."""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
