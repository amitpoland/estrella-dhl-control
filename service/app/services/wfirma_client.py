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


import threading as _threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

import requests as _requests

from ..core.circuit_breaker import CircuitBreakerError, get_circuit_breaker
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
    """Contractor (customer) record from wFirma.

    B0 (MDOC-cache) 2026-05-16: extended with optional contact fields
    parsed opportunistically from contractors/find. wFirma's response
    shape varies — every extended field defaults to "" so missing
    fields never break the dataclass.
    """
    wfirma_id: str
    name: str
    nip: str = ""
    country: str = ""
    zip: str = ""
    city: str = ""
    # B0 enrichment — opportunistically parsed from wFirma XML if present.
    email:           str = ""
    phone:           str = ""
    mobile:          str = ""
    street:          str = ""
    account_payments: str = ""  # bank account / SWIFT used for payments
    payment_method:  str = ""
    payment_term:    str = ""   # e.g. "14" days (string for safety)


@dataclass
class ContractorFetchResult:
    """Output from ``fetch_contractor_by_id`` — structured read-back of a
    single wFirma contractor record by numeric id.

    B0 deep-enrichment 2026-05-16: extended with optional commercial-default
    fields parsed opportunistically from the wFirma XML. Each extra field
    defaults to "" so a missing element never breaks the dataclass — the
    apply path COALESCEs only when local is empty.
    """
    ok: bool
    contractor_id: str = ""
    name: str = ""
    nip: str = ""
    country: str = ""
    # Primary address (Nabywca billing).
    street: str = ""
    city: str = ""
    zip: str = ""
    # Alternate / contact address (Odbiorca / ship-to). Populated only
    # when the contractor record carries ``different_contact_address=1``;
    # otherwise these fields are empty strings.
    different_contact_address: bool = False
    contact_name:    str = ""
    contact_person:  str = ""
    contact_street:  str = ""
    contact_city:    str = ""
    contact_zip:     str = ""
    contact_country: str = ""
    # B0 deep-enrichment — actual wFirma contractor-detail fields. Names
    # below match the XML keys observed live for contractor 75483443
    # (Railing sp z o.o., 2026-05-17). Fields wFirma does NOT expose at the
    # contractor level (default_currency, invoiceseries_id, proformaseries_id)
    # have been removed — they are operator-managed dictionaries.
    email:           str = ""
    phone:           str = ""
    mobile:          str = ""
    skype:           str = ""
    fax:             str = ""
    url:             str = ""
    description:     str = ""
    regon:           str = ""
    payment_days:    str = ""   # integer days as string ("0" if not set)
    payment_method:  str = ""
    discount_percent: str = ""  # "0.00" if not set
    account_number:   str = ""  # bank account (flat <account_number> when set)
    translation_language_id: str = ""   # extracted from <translation_language><id>X</id>
    buyer:    str = ""    # "1"/"0" — wFirma role flag
    seller:   str = ""
    receiver: str = ""
    tags:     str = ""
    error: Optional[str] = None
    raw_response: Optional[str] = None


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
    """
    Input for create_proforma_draft().

    Per validated wFirma invoices/add shape, contractor and goods are
    referenced BY ID — not by inline name fields. The wfirma_contractor_id
    must be a non-empty wFirma id resolved from wfirma_customers by the
    caller (route layer); each line's wfirma_good_id must be resolved from
    wfirma_products. The client_name / zip / city are kept for logging and
    operator-facing display only — they are NOT serialised into the XML
    payload.
    """
    client_name:           str
    client_zip:            str
    client_city:           str
    lines:                 List[ReservationLine] = field(default_factory=list)
    currency:              str = "PLN"
    wfirma_contractor_id:  str = ""
    # Per-line VAT code id resolved from wFirma vat_codes lookup (field
    # <code> matches one of "23", "WDT", "EXP", etc.). Required: a
    # caller that hasn't decided the VAT context yet has no business
    # building a proforma payload — see decide_proforma_vat_context().
    vat_code_id:           str = ""
    # Optional Odbiorca / ship-to contractor — when set AND not equal to
    # ``wfirma_contractor_id``, ``_build_proforma_xml`` emits
    # ``<contractor_receiver><id>...</id></contractor_receiver>``.
    # Empty string AND the literal "0" both mean "no separate receiver"
    # (per wFirma's read-side normalisation in
    # ``app/tools/sync_customer_invoice_snapshot.py``: id "0" is the
    # canonical "no receiver" sentinel). Set per-customer via
    # ``wfdb.set_customer_ship_to(...)`` and threaded through by
    # ``routes_proforma._build_proforma_request``.
    wfirma_contractor_receiver_id: str = ""
    # Optional series id — when set and not "0", emits
    # ``<series><id>...</id></series>`` in the invoice XML.
    # Resolved from customer_master.preferred_proforma_series_id by
    # ``routes_proforma._build_proforma_request``. Empty = wFirma default.
    series_id: str = ""
    # Optional issue date. When set to a valid YYYY-MM-DD string, emitted
    # as <date> in the proforma XML so wFirma records the operator-supplied
    # date instead of its own server date. Empty = wFirma default (today).
    date: str = ""
    # Optional payment method. Mapped from CustomerMaster.preferred_payment_method
    # to a wFirma-accepted string (przelew/gotowka/karta/kompensata).
    # "other" or empty = omit the XML element so wFirma uses its own default.
    payment_method: str = ""


@dataclass
class ProformaResult:
    """Output from create_proforma_draft().

    Phase 9: ``wfirma_invoice_number`` is the canonical operator-readable
    proforma number (e.g. ``"PROF 92/2026"``) extracted from the wFirma
    response with priority ``<fullnumber>`` → ``<full_number>`` → ``<number>``.
    Empty string when neither ``invoices/add`` nor the verify-after-create
    fetch surfaced a number — posting still succeeds in that case.
    """
    ok: bool
    wfirma_invoice_id: Optional[str] = None
    error: Optional[str] = None
    raw_response: Optional[str] = None
    wfirma_invoice_number: str = ""


@dataclass
class PZLine:
    """One goods line in a PZ (Przyjęcie Zewnętrzne) document."""
    good_id: str
    count: float
    price: float


@dataclass
class PZRequest:
    """Input for create_warehouse_pz()."""
    contractor_id: str
    warehouse_id: str
    date: str                   # YYYY-MM-DD
    description: str
    lines: List[PZLine] = field(default_factory=list)


@dataclass
class PZResult:
    """Output from create_warehouse_pz()."""
    ok: bool
    wfirma_pz_doc_id: str = ""
    error: Optional[str] = None
    raw_response: Optional[str] = None


@dataclass
class PZFetchResult:
    """Result of a wFirma warehouse PZ document lookup (fetch or search)."""
    ok: bool
    pz_doc_id: str = ""
    pz_number: str = ""
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


def _http_request(method: str, module: str, action: str, body_xml: str = "",
                  id_suffix: Optional[str] = None) -> tuple[int, str]:
    """
    Make a synchronous HTTP request to the wFirma API.

    Returns (http_status_code, response_text).
    Raises ConnectionError on network failure.
    Raises ValueError if credentials are missing (from _headers_for_module).

    *id_suffix* (optional): when provided, appended to the URL path BEFORE
    the query string — used by goods/edit which expects
    `/goods/edit/{wfirma_product_id}` rather than the row id in the body.
    Other actions (find, add, get, delete) leave id_suffix=None.
    """
    base = _url(module, action)
    if id_suffix:
        # Insert /{id_suffix} between path and query string.
        path, _, query = base.partition("?")
        url = f"{path}/{_esc(id_suffix)}" + (f"?{query}" if query else "")
    else:
        url = base
    breaker = get_circuit_breaker("wfirma")

    # Check circuit BEFORE building headers — avoids raising ValueError for
    # missing credentials when the circuit is already open and we want to
    # return the fallback response immediately.
    if breaker.state.value == "open":
        log.warning(
            "wfirma circuit OPEN — request rejected (%s %s/%s)",
            method, module, action,
        )
        return 503, "circuit_breaker_open"

    headers = _headers_for_module(module)

    def _do_request() -> tuple[int, str]:
        resp = _requests.request(
            method.upper(),
            url,
            headers=headers,
            data=body_xml.encode("utf-8") if body_xml else None,
            timeout=(5, breaker.config.call_timeout),
        )
        return resp.status_code, resp.text

    try:
        return breaker.call(_do_request)
    except CircuitBreakerError:
        log.warning(
            "wfirma circuit OPEN — request rejected (%s %s/%s)",
            method, module, action,
        )
        return 503, "circuit_breaker_open"
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


def count_contractors() -> int:
    """
    Total number of contractors in the configured wFirma company.

    API: GET contractors/count. Read-only. Used as a pre-flight
    before paginated list_contractors_page() loops so the caller can
    pre-allocate / bound the loop.

    Raises RuntimeError on non-OK status / HTTP ≥ 400.
    """
    body = """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <contractors>
    <parameters>
      <conditions/>
    </parameters>
  </contractors>
</api>"""
    http_status, response_text = _http_request("GET", "contractors", "count", body)
    if http_status >= 400:
        raise RuntimeError(f"contractors/count HTTP {http_status}")
    code, desc = _parse_status(response_text)
    if code != "OK":
        raise RuntimeError(f"contractors/count wFirma status={code}: {desc}")
    root = ET.fromstring(response_text)
    # wFirma returns <total>N</total> on count actions.
    total_node = root.find(".//total")
    if total_node is None or not (total_node.text or "").strip():
        return 0
    try:
        return int(total_node.text.strip())
    except (TypeError, ValueError):
        return 0


def fetch_contractor_by_id(contractor_id: str) -> "ContractorFetchResult":
    """
    Fetch a single wFirma contractor by numeric id.

    Uses path-based ``GET contractors/get/{id}``. The earlier ``find``
    + ``<field>id eq …>`` pattern is unsafe for id lookups — wFirma
    silently ignores ``id`` in find conditions and returns the first
    1000-contractor collection (same trap that hit fetch_invoice_xml /
    fetch_warehouse_pz; both are now path-based).

    Returns
    -------
    ContractorFetchResult(ok=True, ...) on success, with
    name / nip / country / address fields populated.

    ContractorFetchResult(ok=False, error=...) when:
      - HTTP 404 (record absent in wFirma)
      - HTTP ≥ 400 (server / auth / etc.)
      - wFirma status code other than OK
      - XML parse error
      - no <contractor> in response

    Never raises — caller-side checks ``result.ok`` and surfaces a
    blocking reason on the operator response.
    """
    if not (contractor_id or "").strip():
        return ContractorFetchResult(
            ok=False, error="contractor_id is required",
        )
    safe_id = _esc(contractor_id).strip()
    try:
        http_status, response_text = _http_request(
            "GET", "contractors", f"get/{safe_id}", "",
        )
    except (ConnectionError, ValueError) as exc:
        return ContractorFetchResult(
            ok=False, contractor_id=contractor_id,
            error=f"connection: {exc}",
        )

    if http_status == 404:
        return ContractorFetchResult(
            ok=False, contractor_id=contractor_id,
            error=f"contractor {contractor_id!r} not found",
            raw_response=response_text,
        )
    if http_status >= 400:
        return ContractorFetchResult(
            ok=False, contractor_id=contractor_id,
            error=f"HTTP {http_status}", raw_response=response_text,
        )

    code, desc = _parse_status(response_text)
    if code != "OK":
        return ContractorFetchResult(
            ok=False, contractor_id=contractor_id,
            error=f"{code}: {desc}" if desc else code,
            raw_response=response_text,
        )

    try:
        root = ET.fromstring(response_text)
    except ET.ParseError as exc:
        return ContractorFetchResult(
            ok=False, contractor_id=contractor_id,
            error=f"XML parse error: {exc}", raw_response=response_text,
        )

    node = root.find(".//contractor")
    if node is None:
        return ContractorFetchResult(
            ok=False, contractor_id=contractor_id,
            error=f"no <contractor> in response for id={contractor_id}",
            raw_response=response_text,
        )

    fetched_id = _find_text(node, "id") or contractor_id
    diff_addr  = (_find_text(node, "different_contact_address") or "0").strip() == "1"
    return ContractorFetchResult(
        ok                        = True,
        contractor_id             = fetched_id,
        name                      = _find_text(node, "name") or _find_text(node, "altname"),
        nip                       = _find_text(node, "nip"),
        country                   = _find_text(node, "country"),
        street                    = _find_text(node, "street"),
        city                      = _find_text(node, "city"),
        zip                       = _find_text(node, "zip"),
        different_contact_address = diff_addr,
        contact_name              = _find_text(node, "contact_name"),
        contact_person            = _find_text(node, "contact_person"),
        contact_street            = _find_text(node, "contact_street"),
        contact_city              = _find_text(node, "contact_city"),
        contact_zip               = _find_text(node, "contact_zip"),
        contact_country           = _find_text(node, "contact_country"),
        # B0 deep-enrichment — XML keys verified against live contractor
        # 75483443 (2026-05-17). Bank account and language id are nested
        # under their own elements; flat parsers would miss them.
        email                     = _find_text(node, "email") or "",
        phone                     = _find_text(node, "phone") or _find_text(node, "tel") or "",
        mobile                    = _find_text(node, "mobile") or "",
        skype                     = _find_text(node, "skype") or "",
        fax                       = _find_text(node, "fax") or "",
        url                       = _find_text(node, "url") or "",
        description               = _find_text(node, "description") or "",
        regon                     = _find_text(node, "regon") or "",
        payment_days              = _find_text(node, "payment_days") or "",
        payment_method            = _find_text(node, "payment_method") or "",
        discount_percent          = _find_text(node, "discount_percent") or "",
        # Bank account is exposed two ways: flat <account_number> (legacy)
        # and nested <contractor_account><number>...</number>. Both checked.
        account_number            = (_find_text(node, "account_number") or
                                     (node.findtext(".//contractor_account/number") or "")).strip(),
        # Language id is nested: <translation_language><id>X</id></translation_language>.
        # We pick "0" out (the documented "no preference" sentinel) and surface
        # only real ids.
        translation_language_id   = (lambda tid: tid if (tid and tid != "0") else "")(
            (node.findtext("translation_language/id") or "").strip()
        ),
        buyer                     = _find_text(node, "buyer") or "",
        seller                    = _find_text(node, "seller") or "",
        receiver                  = _find_text(node, "receiver") or "",
        tags                      = _find_text(node, "tags") or "",
        raw_response              = response_text,
    )


def list_contractors_page(page: int, limit: int) -> List[WFirmaContractor]:
    """
    Read one page of wFirma contractors (no conditions — full master list).

    API: GET contractors/find with <page>N</page><limit>K</limit> as
    SIBLINGS at the <parameters> root. The legacy nested
    <page><start>...</start><limit>...</limit></page> shape is ignored
    by wFirma — it always returns the first page (live diagnostic
    2026-05-06: Shape S1/S7/S8 all returned ids 38142296..44980520
    regardless of <start> or <limit>; Shape S2/S3 with sibling
    <page>N</page><limit>K</limit> advanced the cursor).

    *page* is 1-indexed (page=1 is the first page).

    Returns a list of WFirmaContractor (possibly empty when *page*
    exceeds the total). Raises RuntimeError on non-OK status / HTTP ≥ 400.
    """
    if page < 1 or limit <= 0:
        raise ValueError("page must be >=1 and limit must be >0")
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <contractors>
    <parameters>
      <conditions/>
      <page>{int(page)}</page>
      <limit>{int(limit)}</limit>
    </parameters>
  </contractors>
</api>"""
    http_status, response_text = _http_request("GET", "contractors", "find", body)
    if http_status >= 400:
        raise RuntimeError(f"contractors/find HTTP {http_status}")
    code, desc = _parse_status(response_text)
    if code != "OK":
        # Empty page — wFirma returns NOT_FOUND when start exceeds total.
        if code == "NOT FOUND" or "OUT_OF_BOUNDS" in (desc or "").upper():
            return []
        raise RuntimeError(f"contractors/find wFirma status={code}: {desc}")
    root = ET.fromstring(response_text)
    out: List[WFirmaContractor] = []
    # wFirma's contractors/find serialises some nested address/contact
    # records as additional <contractor> elements deep in the tree. They
    # carry blank <name> and either id="0" or a duplicate of the parent
    # contractor's id. iter() would scoop them up; we restrict to the
    # direct children of the top-level <contractors> collection and
    # additionally skip any node missing a non-zero id and a non-blank
    # name (live wFirma data 2026-05-06: 40 raw nodes → 20 real rows).
    contractors = root.find("contractors")
    if contractors is None:
        return out
    for node in contractors.findall("contractor"):
        wid = (_find_text(node, "id") or "").strip()
        if not wid or wid == "0":
            continue
        name = (_find_text(node, "name") or "").strip()
        if not name:
            continue
        out.append(WFirmaContractor(
            wfirma_id        = wid,
            name             = name,
            nip              = _find_text(node, "nip") or "",
            country          = _find_text(node, "country") or "",
            zip              = _find_text(node, "zip") or "",
            city             = _find_text(node, "city") or "",
            # B0 enrichment — wFirma sometimes returns these in the list
            # response; never raises if the element is missing.
            email            = _find_text(node, "email") or "",
            phone            = _find_text(node, "phone") or _find_text(node, "tel") or "",
            mobile           = _find_text(node, "mobile") or "",
            street           = _find_text(node, "street") or "",
            account_payments = _find_text(node, "account_payments") or "",
            payment_method   = _find_text(node, "payment_method") or "",
            payment_term     = _find_text(node, "payment_term") or "",
        ))
    return out


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
    if not (name or "").strip():
        raise ValueError("name is required")

    fields = [f"<name>{_esc(name)}</name>"]
    if (nip or "").strip():
        fields.append(f"<nip>{_esc(nip)}</nip>")
    if (country or "").strip():
        fields.append(f"<country>{_esc(country)}</country>")
    if (zip_code or "").strip():
        fields.append(f"<zip>{_esc(zip_code)}</zip>")
    if (city or "").strip():
        fields.append(f"<city>{_esc(city)}</city>")
    inner = "\n      ".join(fields)
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <contractors>
    <contractor>
      {inner}
    </contractor>
  </contractors>
</api>"""

    http_status, response_text = _http_request(
        "POST", "contractors", "add", body,
    )
    if http_status >= 400:
        raise RuntimeError(
            f"contractors/add HTTP {http_status}: {response_text[:200]}"
        )
    code, desc = _parse_status(response_text)
    if code != "OK":
        raise RuntimeError(f"contractors/add wFirma status={code}: {desc}")
    root = ET.fromstring(response_text)
    node = root.find(".//contractor")
    if node is None:
        raise RuntimeError("contractors/add: no <contractor> in response")
    new_id = _find_text(node, "id") or ""
    if not new_id:
        raise RuntimeError(
            "contractors/add: response had no <id> — refusing blank id"
        )
    return WFirmaContractor(
        wfirma_id = new_id,
        name      = _find_text(node, "name") or name,
        nip       = _find_text(node, "nip")  or (nip or ""),
        country   = _find_text(node, "country") or country,
        zip       = _find_text(node, "zip")  or zip_code,
        city      = _find_text(node, "city") or city,
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
    description: str = "",
) -> WFirmaProduct:
    """
    Create a new good in wFirma.

    Returns the created WFirmaProduct with the assigned wFirma ID.
    Raises RuntimeError when wFirma rejects the create (non-OK status,
    HTTP error, etc.).
    Raises ConnectionError on network failure.

    API: POST goods/add
    Auth: API Key headers
    Payload: XML with <name>, <code>, <unit>, <netto>, <type>good</type>,
             <vat_code><id>...</id></vat_code>, <warehouse_type>, <description>
    """
    if not product_code:
        raise ValueError("product_code is required")
    if not name:
        raise ValueError("name is required")

    vat_xml = (
        f"<vat_code><id>{_esc(vat_code_id)}</id></vat_code>"
        if vat_code_id else ""
    )
    desc_xml = (
        f"<description>{_esc(description)}</description>"
        if description else ""
    )
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <goods>
    <good>
      <name>{_esc(name)}</name>
      <code>{_esc(product_code)}</code>
      <unit>{_esc(unit)}</unit>
      <netto>{netto:.2f}</netto>
      <type>good</type>
      <warehouse_type>{_esc(warehouse_type)}</warehouse_type>
      {vat_xml}
      {desc_xml}
    </good>
  </goods>
</api>"""
    http_status, response_text = _http_request("POST", "goods", "add", body)
    if http_status >= 400:
        raise RuntimeError(f"goods/add HTTP {http_status}: {response_text[:200]}")
    code, desc = _parse_status(response_text)
    if code != "OK":
        raise RuntimeError(f"goods/add wFirma status={code}: {desc}")
    root = ET.fromstring(response_text)
    node = root.find(".//good")
    if node is None:
        raise RuntimeError("goods/add: no <good> in response")
    return WFirmaProduct(
        wfirma_id = _find_text(node, "id"),
        name      = _find_text(node, "name") or name,
        code      = _find_text(node, "code") or product_code,
        unit      = _find_text(node, "unit") or unit,
        count     = 0.0,
        reserved  = 0.0,
    )


def edit_product(
    wfirma_product_id: str,
    *,
    name:        Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Edit selected fields of an existing wFirma good identified by id.

    Minimal partial update: only fields passed (non-None, non-empty) are
    serialised into the payload — wFirma leaves omitted fields untouched.
    code / price / vat / unit / count / reserved / type / warehouse_type
    are NEVER in the body and therefore can never be mutated by this call.

    API: POST goods/edit
    Auth: API Key headers
    Returns: dict with the parsed <good> response (id, name, code, unit).
    Raises ValueError on missing id or no fields to update.
    Raises RuntimeError on non-OK wFirma status / HTTP ≥ 400 / missing id
    in response.
    Raises ConnectionError on network failure (propagated from _http_request).
    """
    if not (wfirma_product_id or "").strip():
        raise ValueError("wfirma_product_id is required")

    fields: List[str] = []
    if name is not None and (name or "").strip():
        fields.append(f"<name>{_esc(name)}</name>")
    if description is not None and (description or "").strip():
        fields.append(f"<description>{_esc(description)}</description>")
    if not fields:
        raise ValueError("at least one of name/description must be non-empty")

    # wFirma goods/edit requires the target id in the URL path, NOT in the
    # body. id-in-body returns NOT_FOUND (verified live: wFirma treats body
    # <id> as a search condition, finds zero rows, refuses to mutate).
    inner = "\n          ".join(fields)
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <goods>
    <good>
          {inner}
    </good>
  </goods>
</api>"""

    http_status, response_text = _http_request(
        "POST", "goods", "edit", body, id_suffix=wfirma_product_id,
    )
    if http_status >= 400:
        raise RuntimeError(
            f"goods/edit HTTP {http_status}: {response_text[:200]}"
        )
    code, desc = _parse_status(response_text)
    if code != "OK":
        raise RuntimeError(f"goods/edit wFirma status={code}: {desc}")

    root = ET.fromstring(response_text)
    node = root.find(".//good")
    if node is None:
        raise RuntimeError("goods/edit: no <good> in response")
    out_id = _find_text(node, "id") or ""
    if not out_id:
        raise RuntimeError("goods/edit: response had no <id> — refusing to confirm")
    return {
        "wfirma_id": out_id,
        "name":      _find_text(node, "name"),
        "code":      _find_text(node, "code"),
        "unit":      _find_text(node, "unit"),
    }


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


# ── PZ (Przyjęcie Zewnętrzne) — goods receipt ────────────────────────────────

def _build_pz_xml(req: PZRequest) -> str:
    """Build the XML payload for warehouse_document_p_z/add. Pure, no HTTP."""
    lines_xml = ""
    for line in req.lines:
        lines_xml += f"""
        <warehouse_document_content>
          <unit_count>{line.count:.4f}</unit_count>
          <price>{line.price:.2f}</price>
          <good>
            <id>{_esc(line.good_id)}</id>
          </good>
        </warehouse_document_content>"""

    desc_xml = f"<description>{_esc(req.description)}</description>" if req.description else ""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <warehouse_documents>
    <warehouse_document>
      <type>PZ</type>
      <date>{req.date}</date>
      <contractor>
        <id>{_esc(req.contractor_id)}</id>
      </contractor>
      <warehouse>
        <id>{_esc(req.warehouse_id)}</id>
      </warehouse>
      <price_type>netto</price_type>
      {desc_xml}
      <warehouse_document_contents>{lines_xml}
      </warehouse_document_contents>
    </warehouse_document>
  </warehouse_documents>
</api>"""


def fetch_warehouse_pz(pz_doc_id: str) -> "PZFetchResult":
    """
    Fetch a single warehouse PZ document by its wFirma numeric ID.

    Uses path-based ``GET warehouse_document_p_z/get/{id}``. The earlier
    implementation used ``warehouse_document_p_z/find`` with a
    ``<condition><field>id eq …>`` body, but wFirma silently ignores
    unsupported filterable fields on that operation and returns the
    full first-1000-PZ list — the parser then took the first node and
    returned an unrelated 2020 document instead of the requested one.

    The path-based ``get/{id}`` operation is the wFirma-canonical way
    to retrieve a single document by id and respects the request
    correctly (verified live against wFirma).

    Returns PZFetchResult(ok=True, pz_doc_id=..., pz_number=...) on success.
    Returns PZFetchResult(ok=False, error=...) if the document is not found,
    the API returns an error, or a network/parse error occurs.  Never raises.
    """
    if not (pz_doc_id or "").strip():
        return PZFetchResult(ok=False, error="pz_doc_id is required")
    safe_id = _esc(pz_doc_id).strip()
    try:
        # Path-based id lookup — empty body, the id rides in the URL.
        http_status, response_text = _http_request(
            "GET", "warehouse_document_p_z", f"get/{safe_id}", "",
        )
    except (ConnectionError, ValueError) as exc:
        return PZFetchResult(ok=False, error=f"connection: {exc}")
    if http_status == 404:
        return PZFetchResult(
            ok=False, error=f"PZ document {pz_doc_id!r} not found",
            raw_response=response_text,
        )
    if http_status >= 400:
        return PZFetchResult(
            ok=False, error=f"HTTP {http_status}", raw_response=response_text,
        )
    code, desc = _parse_status(response_text)
    if code != "OK":
        return PZFetchResult(
            ok=False, error=f"{code}: {desc}" if desc else code,
            raw_response=response_text,
        )
    try:
        root = ET.fromstring(response_text)
    except ET.ParseError as exc:
        return PZFetchResult(
            ok=False, error=f"XML parse error: {exc}", raw_response=response_text,
        )
    wd_node = root.find(".//warehouse_document")
    if wd_node is None:
        return PZFetchResult(
            ok=False, error=f"PZ document {pz_doc_id!r} not found",
            raw_response=response_text,
        )
    fetched_id = _find_text(wd_node, "id") or pz_doc_id
    # wFirma's read response on warehouse_document_p_z/get/{id} uses
    # <fullnumber> (no underscore), but the query/find body uses
    # <full_number>. Try both spellings before falling through to the
    # bare numeric <number>, which is just the per-month sequence
    # ("4") — never a canonical operator-readable PZ id.
    pz_number  = (
        _find_text(wd_node, "fullnumber")
        or _find_text(wd_node, "full_number")
        or _find_text(wd_node, "number")
        or ""
    )
    return PZFetchResult(ok=True, pz_doc_id=fetched_id, pz_number=pz_number,
                         raw_response=response_text)


def find_warehouse_pz_by_number(pz_number: str) -> "PZFetchResult":
    """
    Search for a warehouse PZ by its document number (full_number field).

    Uses warehouse_document_p_z/find with a full_number-eq condition.
    Returns the first matching PZ document, or PZFetchResult(ok=False) if none.
    Never raises.
    """
    if not (pz_number or "").strip():
        return PZFetchResult(ok=False, error="pz_number is required")
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <warehouse_document_p_z>
    <parameters>
      <conditions>
        <condition>
          <field>full_number</field>
          <operator>eq</operator>
          <value>{_esc(pz_number)}</value>
        </condition>
      </conditions>
      <page><start>0</start><limit>1</limit></page>
    </parameters>
  </warehouse_document_p_z>
</api>"""
    try:
        http_status, response_text = _http_request(
            "GET", "warehouse_document_p_z", "find", body,
        )
    except (ConnectionError, ValueError) as exc:
        return PZFetchResult(ok=False, error=f"connection: {exc}")
    if http_status >= 400:
        return PZFetchResult(
            ok=False, error=f"HTTP {http_status}", raw_response=response_text,
        )
    code, desc = _parse_status(response_text)
    if code != "OK":
        return PZFetchResult(
            ok=False, error=f"{code}: {desc}" if desc else code,
            raw_response=response_text,
        )
    try:
        root = ET.fromstring(response_text)
    except ET.ParseError as exc:
        return PZFetchResult(
            ok=False, error=f"XML parse error: {exc}", raw_response=response_text,
        )
    wd_node = root.find(".//warehouse_document")
    if wd_node is None:
        return PZFetchResult(
            ok=False,
            error=f"no PZ document found with number {pz_number!r}",
            raw_response=response_text,
        )
    fetched_id     = _find_text(wd_node, "id") or ""
    # wFirma's read responses (warehouse_document_p_z/find result rows)
    # use ``<fullnumber>`` (no underscore). The query/find body field
    # name is ``full_number`` (kept above) — different namespace from the
    # response. Try concatenated first, then underscored, then bare
    # ``<number>`` (per-month sequence) as last-resort fallback so that
    # callers don't display "4" instead of "PZ 4/5/2026".
    fetched_number = (
        _find_text(wd_node, "fullnumber")
        or _find_text(wd_node, "full_number")
        or _find_text(wd_node, "number")
        or pz_number
    )
    return PZFetchResult(ok=True, pz_doc_id=fetched_id, pz_number=fetched_number,
                         raw_response=response_text)


def create_warehouse_pz(req: PZRequest) -> PZResult:
    """
    Create a PZ (goods receipt) document in wFirma.

    Pre-conditions (caller must verify before calling):
    - settings.wfirma_create_pz_allowed is True
    - req.contractor_id is a valid wFirma contractor ID
    - Every line.good_id is a valid wFirma good ID
    - req.warehouse_id matches the configured wFirma warehouse

    Returns PZResult(ok=True, wfirma_pz_doc_id=...) on success.
    Returns PZResult(ok=False, error=...) on HTTP error, wFirma ERROR status,
    connection failure, or missing document id in response. Never raises.

    API: POST warehouse_document_p_z/add
    Auth: API Key headers (Basic Auth deprecated by wFirma 2023-07-02)
    """
    if not getattr(settings, "wfirma_create_pz_allowed", False):
        return PZResult(ok=False, error="WFIRMA_CREATE_PZ_ALLOWED is not enabled")

    if not req.contractor_id or not req.lines:
        return PZResult(ok=False, error="invalid request: contractor_id and lines required")

    body_xml = _build_pz_xml(req)
    try:
        http_status, response_text = _http_request(
            "POST", "warehouse_document_p_z", "add", body_xml,
        )
    except (ConnectionError, ValueError) as exc:
        return PZResult(ok=False, error=f"connection: {exc}")

    if http_status >= 400:
        return PZResult(ok=False, error=f"HTTP {http_status}", raw_response=response_text)

    code, desc = _parse_status(response_text)
    if code != "OK":
        return PZResult(
            ok=False,
            error=f"{code}: {desc}" if desc else code,
            raw_response=response_text,
        )

    try:
        root = ET.fromstring(response_text)
    except ET.ParseError as exc:
        return PZResult(ok=False, error=f"parse_error: {exc}", raw_response=response_text)

    wd_node = root.find(".//warehouse_document")
    wfirma_id = _find_text(wd_node, "id") if wd_node is not None else ""
    if not wfirma_id:
        return PZResult(
            ok=False,
            error="no warehouse_document.id in response",
            raw_response=response_text,
        )
    return PZResult(ok=True, wfirma_pz_doc_id=wfirma_id, raw_response=response_text)


# ── Proforma invoice (fallback) ───────────────────────────────────────────────

def _extract_fullnumber(invoice_node: Optional[ET.Element]) -> str:
    """Return the canonical operator-readable Proforma number from an
    ``<invoice>`` ElementTree node.

    Priority order (Phase 9 spec):

      1. ``<fullnumber>``  — single-word, most reliable on read responses
      2. ``<full_number>`` — underscore variant; some find/edit shapes
      3. ``<number>``      — bare per-month sequence; last-resort fallback

    Empty string if the node is None or none of the fields carry text.
    Bare ``<number>`` is intentionally tried LAST: when ``<fullnumber>``
    exists alongside, it always wins.
    """
    if invoice_node is None:
        return ""
    for tag in ("fullnumber", "full_number", "number"):
        node = invoice_node.find(tag)
        if node is not None and (node.text or "").strip():
            return node.text.strip()
    return ""


def create_proforma_draft(req: ProformaRequest) -> ProformaResult:
    """
    Create a proforma invoice in wFirma (type=proforma).

    Returns ProformaResult with wfirma_invoice_id (and best-effort number /
    currency) on success.
    Raises RuntimeError on non-OK wFirma status, missing id in response, or
    HTTP ≥ 400.
    Raises ConnectionError on network failure (propagated from _http_request).
    Mirrors the pattern of create_product.

    API: POST invoices/add
    Payload built by _build_proforma_xml(req).
    """
    if not req.client_name:
        raise ValueError("client_name is required")
    if not req.lines:
        raise ValueError("at least one line is required")

    body = _build_proforma_xml(req)
    http_status, response_text = _http_request("POST", "invoices", "add", body)
    if http_status >= 400:
        raise RuntimeError(
            f"invoices/add HTTP {http_status}: {response_text[:200]}"
        )
    code, desc = _parse_status(response_text)
    if code != "OK":
        raise RuntimeError(f"invoices/add wFirma status={code}: {desc}")

    root = ET.fromstring(response_text)
    node = root.find(".//invoice")
    if node is None:
        raise RuntimeError("invoices/add: no <invoice> in response")
    wfirma_id = _find_text(node, "id") or ""
    if not wfirma_id:
        raise RuntimeError("invoices/add: response had no <id> — refusing blank")

    # Verify-after-create: wFirma can return status=OK + a valid invoice id
    # while silently persisting only a subset of the submitted lines (live
    # incident 2026-05-06: 12 lines submitted, 1 persisted — see
    # docs/wfirma.skill.md and scripts/diag_proforma_line_count.py).
    # Fetch the new proforma immediately and compare the persisted
    # invoicecontent count against the expected request line count.
    expected_count = len(req.lines)
    try:
        verify_xml = fetch_invoice_xml(wfirma_id)
    except Exception as exc:
        raise RuntimeError(
            f"invoices/add succeeded (id={wfirma_id}) but verify-fetch "
            f"failed: {type(exc).__name__}: {exc} — proforma may be in "
            "unknown persisted state, do NOT retry without manual review"
        ) from exc

    verify_root = ET.fromstring(verify_xml)
    persisted_lines = verify_root.findall(".//invoicecontent")
    actual_count = len(persisted_lines)
    if actual_count != expected_count:
        persisted_good_ids = [
            (ln.find("good").findtext("id") if ln.find("good") is not None else "")
            for ln in persisted_lines
        ]
        expected_good_ids = [ln.wfirma_good_id for ln in req.lines]
        missing = [g for g in expected_good_ids if g not in persisted_good_ids]
        raise RuntimeError(
            f"invoices/add partial persistence: wfirma_invoice_id={wfirma_id} "
            f"expected_count={expected_count} actual_count={actual_count} "
            f"missing_good_ids={missing[:10]} — proforma EXISTS in wFirma "
            "but lines were silently dropped; do NOT mark as success"
        )

    # VAT code parity — reuses persisted_lines, no additional HTTP call.
    # wFirma can silently rewrite per-line vat_code on persist; treat a
    # missing <vat_code>/<id> element as actual_vat_code_id="" (mismatch).
    expected_vat = (req.vat_code_id or "").strip()
    vat_mismatches = []
    for ln in persisted_lines:
        good_node = ln.find("good")
        gid = (good_node.findtext("id") or "").strip() if good_node is not None else ""
        vc_node = ln.find("vat_code")
        actual_vat = (vc_node.findtext("id") or "").strip() if vc_node is not None else ""
        if actual_vat != expected_vat:
            vat_mismatches.append({
                "good_id": gid,
                "expected_vat_code_id": expected_vat,
                "actual_vat_code_id": actual_vat,
            })
    if vat_mismatches:
        raise RuntimeError(
            f"invoices/add vat_code mismatch: wfirma_invoice_id={wfirma_id} "
            f"expected_count={expected_count} actual_count={actual_count} "
            f"expected_vat_code_id={expected_vat!r} "
            f"mismatched_vat_codes={vat_mismatches[:10]} — "
            "wFirma silently rewrote per-line VAT; do NOT mark as success"
        )

    # Phase 9 — extract canonical operator-readable Proforma number.
    # We prefer the verify-after-create XML (which is the authoritative
    # post-write read of the new invoice), and fall back to the
    # ``invoices/add`` response. No second wFirma call is made.
    full_number = _extract_fullnumber(verify_root.find(".//invoice"))
    if not full_number:
        # The create response's <invoice> node is the next-best source.
        full_number = _extract_fullnumber(node)

    return ProformaResult(
        ok                    = True,
        wfirma_invoice_id     = wfirma_id,
        error                 = None,
        raw_response          = response_text,
        wfirma_invoice_number = full_number,
    )


# wFirma's vat_codes carry a stable <code> field (e.g. "23", "WDT",
# "EXP"). VAT ids vary across deployments but the <code> values are
# semantic — we resolve by code rather than rate so the same lookup
# table works for PL standard, WDT, export, NP, ZW, etc.

# EU member states (ISO 3166-1 alpha-2). Used to decide whether a
# non-PL customer qualifies for WDT (intra-community supply, 0% VAT)
# vs. true export.
_EU_COUNTRIES: frozenset = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
    "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
    "PL", "PT", "RO", "SK", "SI", "ES", "SE",
})


def decide_proforma_vat_context(customer_country: str,
                                 customer_vat_id: str = "") -> Dict[str, Any]:
    """
    Pure-data decision: which VAT regime applies to a proforma for a
    given customer? Returns:

      {"context": "domestic" | "wdt" | "export" | "blocked",
       "vat_code": "23" | "WDT" | "EXP" | None,
       "reason":   <human readable>}

    Rules (Polish accounting):
      - PL                   → 23%             (domestic)
      - EU non-PL + valid VAT → WDT 0%          (intra-community supply)
      - EU non-PL + no VAT    → BLOCKED         (cannot apply WDT
                                                  without a VAT number)
      - non-EU                → EXP 0%          (export)
      - country missing       → BLOCKED         (unknown VAT status)

    No country/region mapping fallbacks; missing data must surface as
    a hard block so the operator decides explicitly.
    """
    cc  = (customer_country or "").strip().upper()
    vat = (customer_vat_id  or "").strip().upper()
    if not cc:
        return {"context": "blocked", "vat_code": None,
                "reason": "customer_country missing — cannot determine "
                          "VAT treatment"}
    if cc == "PL":
        return {"context": "domestic", "vat_code": "23",
                "reason": "PL domestic — standard 23% VAT"}
    if cc in _EU_COUNTRIES:
        if not vat:
            return {"context": "blocked", "vat_code": None,
                    "reason": (f"EU customer country={cc} has no VAT id — "
                               "cannot apply WDT 0% without a VAT number")}
        return {"context": "wdt", "vat_code": "WDT",
                "reason": f"EU intra-community supply (country={cc})"}
    return {"context": "export", "vat_code": "EXP",
            "reason": f"non-EU export (country={cc})"}


def find_vat_code_id_by_code(code: str) -> Optional[str]:
    """
    Look up a wFirma vat_code's id by its <code> field value
    (e.g. "23", "WDT", "EXP", "NP", "ZW"). Returns the id or None.
    Read-only. Cached via the same dict as _resolve_vat_code_id.
    """
    code_norm = (code or "").strip().upper()
    if not code_norm:
        return None
    cached = _VAT_CODE_ID_CACHE.get(code_norm)
    if cached:
        return cached
    with _vat_code_cache_lock:
        # Double-check under lock.
        cached = _VAT_CODE_ID_CACHE.get(code_norm)
        if cached:
            return cached
        body = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <vat_codes>
    <parameters>
      <conditions>
        <condition><field>code</field><operator>eq</operator><value>{_esc(code_norm)}</value></condition>
      </conditions>
    </parameters>
  </vat_codes>
</api>"""
        http_status, response_text = _http_request("GET", "vat_codes", "find", body)
        if http_status >= 400:
            raise RuntimeError(f"vat_codes/find HTTP {http_status}")
        status, desc = _parse_status(response_text)
        if status != "OK":
            raise RuntimeError(f"vat_codes/find wFirma status={status}: {desc}")
        root = ET.fromstring(response_text)
        node = root.find(".//vat_code")
        if node is None:
            return None
        vid = (_find_text(node, "id") or "").strip() or None
        if vid:
            _VAT_CODE_ID_CACHE[code_norm] = vid
    return vid


def resolve_vat_code_id_for_context(vat_code: str) -> str:
    """
    Resolve the wFirma vat_code id for a context-determined code
    ("23" | "WDT" | "EXP" | …). Raises RuntimeError if unresolvable
    — callers must surface as blocked, never silently fall back.
    """
    vid = find_vat_code_id_by_code(vat_code)
    if not vid:
        raise RuntimeError(
            f"resolve_vat_code_id_for_context: wFirma has no vat_code "
            f"with code={vat_code!r} — cannot build proforma payload"
        )
    return vid


_VAT_CODE_ID_CACHE: Dict[Any, str] = {}
# Lock prevents double-fetch under concurrent first calls (benign but wastes a
# wFirma API round-trip). No TTL needed — vat_codes are stable read-only data.
# No disk persistence needed — process-lifetime cache is sufficient.
_vat_code_cache_lock = _threading.Lock()


def _resolve_vat_code_id(rate: int = 23) -> str:
    """
    Resolve the wFirma internal vat_code id for *rate* (default 23 = standard
    PL VAT). Cached process-wide because vat_codes are read-only / stable.

    Raises RuntimeError if wFirma returns no vat_code for the requested rate
    — never silently default. Required by _build_proforma_xml since live
    incident 2026-05-06 (PROF 92/2026) confirmed wFirma silently drops
    invoicecontent rows that omit <vat_code><id>...</id></vat_code>.
    """
    cached = _VAT_CODE_ID_CACHE.get(int(rate))
    if cached:
        return cached
    with _vat_code_cache_lock:
        # Double-check under lock in case another thread populated it.
        cached = _VAT_CODE_ID_CACHE.get(int(rate))
        if cached:
            return cached
        vid = find_vat_code_id_live(rate)
        if not vid:
            raise RuntimeError(
                f"_resolve_vat_code_id: wFirma returned no vat_code for rate={rate} "
                "— cannot build proforma payload without per-line VAT id"
            )
        _VAT_CODE_ID_CACHE[int(rate)] = vid
    return vid


def _build_proforma_xml(req: ProformaRequest) -> str:
    """
    Build the XML payload for invoices/add with type=proforma.

    Per validated wFirma shape (docs/WFIRMA_ENDPOINT_MAP.md) and the
    field set observed on the persisted line of PROF 92/2026:
      <contractor><id>{wfirma_contractor_id}</id></contractor>
      <invoicecontent>
        <good><id>{wfirma_good_id}</id></good>
        <count>…</count><unit_count>…</unit_count>
        <price>…</price><unit>…</unit>
        <vat_code><id>{vat_code_id}</id></vat_code>
        <discount>1</discount>          <!-- discount profile = none -->
        <discount_percent>0.00</discount_percent>
        <price_modified>1</price_modified> <!-- price overrides product master -->
      </invoicecontent>

    Live incident 2026-05-06: omitting these per-line fields caused
    wFirma to silently persist only the first invoicecontent of a
    12-line submission while still returning OK at invoice level.

    Does NOT make a network call EXCEPT once per process to resolve
    the vat_code id (cached). Raises if VAT id cannot be resolved.

    Validation:
      - wfirma_contractor_id must be non-empty.
      - Every line's wfirma_good_id must be non-empty.
    Raises ValueError on either miss — callers MUST resolve IDs first.
    """
    if not (req.wfirma_contractor_id or "").strip():
        raise ValueError(
            "wfirma_contractor_id is required — resolve via wfdb.get_customer "
            "before building the proforma payload"
        )

    # Validate every line BEFORE any live VAT lookup so a bad request
    # doesn't waste a network call.
    for idx, line in enumerate(req.lines):
        if not (line.wfirma_good_id or "").strip():
            raise ValueError(
                f"line {idx} ({line.product_code!r}): wfirma_good_id is "
                "required — resolve via wfdb.get_product before building "
                "the proforma payload"
            )

    # VAT code id MUST be supplied by the caller (decided per customer
    # context — domestic / WDT / export — see decide_proforma_vat_context).
    # Refusing to default to 23% here is critical: silent 23% on an EU
    # WDT customer would produce a tax-mistake invoice.
    vat_code_id = (req.vat_code_id or "").strip()
    if not vat_code_id:
        raise ValueError(
            "vat_code_id is required on ProformaRequest — caller must "
            "decide via decide_proforma_vat_context() and resolve via "
            "resolve_vat_code_id_for_context() before building the payload"
        )

    lines_xml = ""
    for line in req.lines:
        lines_xml += f"""
        <invoicecontent>
          <good><id>{_esc(line.wfirma_good_id)}</id></good>
          <count>{line.qty:.4f}</count>
          <unit_count>{line.qty:.4f}</unit_count>
          <price>{line.unit_price:.2f}</price>
          <unit>{_esc(line.unit)}</unit>
          <vat_code><id>{_esc(vat_code_id)}</id></vat_code>
          <discount>1</discount>
          <discount_percent>0.00</discount_percent>
          <price_modified>1</price_modified>
        </invoicecontent>"""

    currency_xml = (
        f"<currency>{_esc(req.currency)}</currency>"
        if (req.currency or "").strip() else ""
    )

    # Optional Odbiorca block. Emit ONLY when the receiver id is a
    # genuine non-empty, non-zero, non-self-referential value:
    #   • empty / whitespace → omit (Shape A: same_as_bill_to or bill_to_alt)
    #   • literal "0"        → omit (wFirma's "no separate receiver" sentinel)
    #   • equals bill-to id  → omit (silly self-reference; defence-in-depth
    #                                 — the wfirma_db helper also rejects it)
    receiver_id  = (req.wfirma_contractor_receiver_id or "").strip()
    bill_to_id   = (req.wfirma_contractor_id or "").strip()
    receiver_xml = ""
    if receiver_id and receiver_id != "0" and receiver_id != bill_to_id:
        receiver_xml = (
            f"<contractor_receiver><id>{_esc(receiver_id)}</id>"
            f"</contractor_receiver>"
        )

    # Emit <series><id>…</id></series> only when a non-empty, non-zero
    # series id was resolved from customer_master.preferred_proforma_series_id.
    # Empty string or "0" → omit so wFirma uses its own default series.
    _sid = (req.series_id or "").strip()
    series_xml = (
        f"<series><id>{_esc(_sid)}</id></series>"
        if _sid and _sid != "0" else ""
    )

    # Emit <date> only when a well-formed YYYY-MM-DD date is supplied.
    import re as _re
    _d = (req.date or "").strip()
    date_xml = (
        f"<date>{_esc(_d)}</date>"
        if _re.fullmatch(r"\d{4}-\d{2}-\d{2}", _d) else ""
    )

    # Map preferred_payment_method to wFirma XML values.
    # Any unrecognised or empty value omits the element (wFirma uses its own default).
    _PM_MAP = {
        "transfer":     "przelew",
        "cash":         "gotowka",
        "card":         "karta",
        "compensation": "kompensata",
    }
    _pm_key = (req.payment_method or "").strip().lower()
    _pm_val = _PM_MAP.get(_pm_key, "")
    paymentmethod_xml = (
        f"<paymentmethod>{_esc(_pm_val)}</paymentmethod>"
        if _pm_val else ""
    )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <invoice>
      <contractor><id>{_esc(req.wfirma_contractor_id)}</id></contractor>
      {receiver_xml}
      <type>proforma</type>
      {currency_xml}
      {series_xml}
      {date_xml}
      {paymentmethod_xml}
      <invoicecontents>{lines_xml}
      </invoicecontents>
    </invoice>
  </invoices>
</api>"""


# ── invoices/delete ─────────────────────────────────────────────────────────

def delete_invoice(invoice_id: str) -> Dict[str, Any]:
    """
    Delete a wFirma invoice (or proforma) by id.

    Intended for cancel+reissue of wrong-payload proformas (e.g.
    partial-line or wrong-VAT). A proforma that has been fiscalised or
    converted to a final invoice cannot be deleted via this path —
    wFirma will return non-OK status.

    Returns {"ok": True, "wfirma_invoice_id": invoice_id} on success.
    Raises RuntimeError on non-OK wFirma status or HTTP >= 400.
    Raises ConnectionError on network failure.

    API: POST invoices/delete/{invoice_id}  (id in URL, empty body)
    """
    if not (invoice_id or "").strip():
        raise ValueError("invoice_id is required")
    http_status, response_text = _http_request(
        "POST", "invoices", "delete", "", id_suffix=invoice_id,
    )
    if http_status >= 400:
        raise RuntimeError(
            f"invoices/delete HTTP {http_status} for id={invoice_id}: "
            f"{response_text[:200]}"
        )
    code, desc = _parse_status(response_text)
    if code != "OK":
        raise RuntimeError(
            f"invoices/delete wFirma status={code} for id={invoice_id}: {desc}"
        )
    return {"ok": True, "wfirma_invoice_id": invoice_id}


# ── invoices/find + invoices/edit helpers (line-name refresh path) ──────────

_INVOICE_LEDGER_PAGE_LIMIT      = 200
_INVOICE_LEDGER_SAFETY_CAP      = 5000


def fetch_invoices_for_contractor(
    contractor_id: str,
    date_from:     str,
    date_to:       str,
    types:         tuple = ("normal", "correction", "proforma"),
) -> List[ET.Element]:
    """Phase 10A — paginated read-only ``invoices/find`` for one contractor.

    READ-ONLY. Uses ``GET invoices/find`` with the proven filter
    combination from
    ``app/tools/sync_customer_invoice_snapshot.py:130-136``:

      • ``type``           ``eq``  (one condition per element of ``types``)
      • ``contractor_id``  ``eq``
      • ``date``           ``ge`` ``date_from``
      • ``date``           ``le`` ``date_to``

    The ``date`` conditions are sent because they are DOCUMENTED in
    ``docs/WFIRMA_ENDPOINT_MAP.md:155``, but wFirma is known to silently
    ignore unsupported filter shapes (existing ``fetch_invoice_xml``
    docstring documents this). Callers MUST therefore re-filter the
    returned list by ``<date>`` Python-side; this helper returns
    everything wFirma sends and does NOT date-filter itself.

    Pagination: ``start``/``limit`` of 200, with a 5000-doc safety cap
    so a runaway / mis-filtered query never hangs the request thread.

    Returns the list of parsed ``<invoice>`` Element nodes.
    Raises:
      ValueError      — empty contractor_id, or date_from > date_to.
      RuntimeError    — wFirma status != OK on any page.
      ConnectionError — network failure (propagated from _http_request).
    """
    cid = (contractor_id or "").strip()
    if not cid:
        raise ValueError("contractor_id is required")
    df = (date_from or "").strip()
    dt = (date_to   or "").strip()
    if df and dt and df > dt:
        raise ValueError(f"date_from {df!r} is after date_to {dt!r}")
    if not isinstance(types, tuple) or not types:
        raise ValueError("types must be a non-empty tuple")

    type_conditions = "".join(
        f"<condition><field>type</field>"
        f"<operator>eq</operator><value>{_esc(t)}</value></condition>"
        for t in types
    )
    contractor_condition = (
        f"<condition><field>contractor_id</field>"
        f"<operator>eq</operator><value>{_esc(cid)}</value></condition>"
    )
    date_conditions = ""
    if df:
        date_conditions += (
            f"<condition><field>date</field>"
            f"<operator>ge</operator><value>{_esc(df)}</value></condition>"
        )
    if dt:
        date_conditions += (
            f"<condition><field>date</field>"
            f"<operator>le</operator><value>{_esc(dt)}</value></condition>"
        )

    out: List[ET.Element] = []
    start = 0
    page_size = _INVOICE_LEDGER_PAGE_LIMIT
    while True:
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<api><invoices><parameters>'
              '<conditions>'
                f'{type_conditions}'
                f'{contractor_condition}'
                f'{date_conditions}'
              '</conditions>'
              f'<page><start>{start}</start><limit>{page_size}</limit></page>'
            '</parameters></invoices></api>'
        )
        http_status, response_text = _http_request(
            "GET", "invoices", "find", body)
        if http_status >= 400:
            raise RuntimeError(
                f"invoices/find HTTP {http_status} (start={start}): "
                f"{response_text[:200]}"
            )
        code, desc = _parse_status(response_text)
        if code != "OK":
            raise RuntimeError(
                f"invoices/find wFirma status={code}: {desc}"
            )
        try:
            root = ET.fromstring(response_text)
        except ET.ParseError as exc:
            raise RuntimeError(
                f"invoices/find: malformed XML at start={start}: {exc}"
            ) from exc
        invoices = root.findall("invoices/invoice")
        if not invoices:
            break
        out.extend(invoices)
        if len(invoices) < page_size:
            break
        start += page_size
        # Safety cap — stop if pagination would exceed the cap on the
        # NEXT page. The check uses ``start`` (the index of the next
        # page's first row), so a 5000-cap stops at exactly 5000 rows.
        if start >= _INVOICE_LEDGER_SAFETY_CAP:
            break
    return out


# ── Phase 10B — payments/find wrapper for Statement of Account ─────────────

def fetch_payments_for_contractor(
    contractor_id: str,
    date_from:     str,
    date_to:       str,
) -> List[ET.Element]:
    """Phase 10B — paginated read-only ``payments/find`` for one contractor.

    READ-ONLY. Uses ``GET payments/find`` with the proven filter
    combination from the Phase 10A.5 live probe
    (``docs/WFIRMA_PAYMENTS_PROBE_EVIDENCE.md``):

      • ``contractor_id``  ``eq``
      • ``date``           ``ge`` ``date_from``  (when supplied)
      • ``date``           ``le`` ``date_to``    (when supplied)

    Mirrors :func:`fetch_invoices_for_contractor`:

      * Pagination ``start``/``limit`` of 200, safety cap 5000.
      * Date filters are SENT to wFirma but the caller MUST also
        Python-side filter by ``<date>`` on the returned nodes,
        because wFirma is documented to silently ignore unsupported
        filter shapes.

    Returns the list of parsed ``<payment>`` Element nodes from
    ``payments/find``'s ``<payments><payment>`` collection.

    Raises:
      ValueError      — empty ``contractor_id``, ``date_from > date_to``.
      RuntimeError    — wFirma status != OK on any page; HTTP ≥ 400.
      ConnectionError — network failure (propagated from _http_request).

    Never calls ``payments/add``, ``payments/edit``, ``payments/delete``,
    or any other write/state-changing endpoint.
    """
    cid = (contractor_id or "").strip()
    if not cid:
        raise ValueError("contractor_id is required")
    df = (date_from or "").strip()
    dt = (date_to   or "").strip()
    if df and dt and df > dt:
        raise ValueError(f"date_from {df!r} is after date_to {dt!r}")

    contractor_condition = (
        f"<condition><field>contractor_id</field>"
        f"<operator>eq</operator><value>{_esc(cid)}</value></condition>"
    )
    date_conditions = ""
    if df:
        date_conditions += (
            f"<condition><field>date</field>"
            f"<operator>ge</operator><value>{_esc(df)}</value></condition>"
        )
    if dt:
        date_conditions += (
            f"<condition><field>date</field>"
            f"<operator>le</operator><value>{_esc(dt)}</value></condition>"
        )

    out: List[ET.Element] = []
    start = 0
    page_size = _INVOICE_LEDGER_PAGE_LIMIT
    while True:
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<api><payments><parameters>'
              '<conditions>'
                f'{contractor_condition}'
                f'{date_conditions}'
              '</conditions>'
              f'<page><start>{start}</start><limit>{page_size}</limit></page>'
            '</parameters></payments></api>'
        )
        http_status, response_text = _http_request(
            "GET", "payments", "find", body)
        if http_status >= 400:
            raise RuntimeError(
                f"payments/find HTTP {http_status} (start={start}): "
                f"{response_text[:200]}"
            )
        code, desc = _parse_status(response_text)
        if code != "OK":
            raise RuntimeError(
                f"payments/find wFirma status={code}: {desc}"
            )
        try:
            root = ET.fromstring(response_text)
        except ET.ParseError as exc:
            raise RuntimeError(
                f"payments/find: malformed XML at start={start}: {exc}"
            ) from exc
        payments = root.findall("payments/payment")
        if not payments:
            break
        out.extend(payments)
        if len(payments) < page_size:
            break
        start += page_size
        if start >= _INVOICE_LEDGER_SAFETY_CAP:
            break
    return out


def fetch_invoice_xml(invoice_id: str) -> str:
    """
    Read a single invoice (or proforma) by id.

    Uses path-based ``GET invoices/get/{id}``. The earlier implementation
    used ``invoices/find`` with a ``<condition><field>id eq …>`` body,
    but wFirma silently ignores unsupported filterable fields on its
    ``find`` operations and returns the first-1000 collection — the
    parser then took the first node and returned an unrelated invoice.
    Same anti-pattern was fixed for ``fetch_warehouse_pz`` previously.

    Returns the full XML response text (so callers can extract the
    <invoicecontents> verbatim for round-trip restate edits).
    Raises RuntimeError on non-OK status / HTTP ≥ 400 / no <invoice>.
    Raises ConnectionError on network failure.
    """
    if not (invoice_id or "").strip():
        raise ValueError("invoice_id is required")
    safe_id = _esc(invoice_id).strip()
    # Path-based id lookup — empty body, the id rides in the URL.
    http_status, response_text = _http_request(
        "GET", "invoices", f"get/{safe_id}", "")
    if http_status == 404:
        raise RuntimeError(
            f"invoices/get: invoice {invoice_id!r} not found")
    if http_status >= 400:
        raise RuntimeError(
            f"invoices/get HTTP {http_status}: {response_text[:200]}")
    code, desc = _parse_status(response_text)
    if code != "OK":
        raise RuntimeError(f"invoices/get wFirma status={code}: {desc}")
    root = ET.fromstring(response_text)
    if root.find(".//invoice") is None:
        raise RuntimeError(
            f"invoices/get: no <invoice> in response for id={invoice_id}")
    return response_text


def fetch_proforma_enrichment(invoice_id: str) -> dict:
    """Phase 3 — read post-posting enrichment fields from wFirma.

    Calls ``fetch_invoice_xml()`` (invoices/get/{id}) and extracts the
    three fields needed to enrich a posted ProformaDraft:

    - ``issue_date``      (wFirma XML element <date>)
    - ``payment_due``     (wFirma XML element <paymentdate>)
    - ``payment_method``  (wFirma XML element <paymentmethod>)

    Returns a dict with those three keys. Values are strings (empty string
    when the element is absent). Never raises on a missing XML element —
    callers should treat empty strings as "not available".

    Raises RuntimeError / ConnectionError when the API call itself fails
    (same contract as ``fetch_invoice_xml``).

    READ-ONLY — never writes to wFirma.
    """
    xml_text = fetch_invoice_xml(invoice_id)
    root = ET.fromstring(xml_text)
    node = root.find(".//invoice")

    def _t(*tags: str) -> str:
        for tag in tags:
            v = _find_text(node, tag) if node is not None else ""
            if v:
                return v
        return ""

    return {
        "issue_date":     _t("date"),
        "payment_due":    _t("paymentdate", "payment_date"),
        "payment_method": _t("paymentmethod", "payment_method"),
    }


def fetch_company_account_iban(account_id: str) -> Optional[str]:
    """Phase 3 — fetch the IBAN string for a wFirma company bank account.

    Uses ``GET company_accounts/get/{id}`` (read-only). Returns the IBAN
    string (stripped) or None when the account has no IBAN or the
    element is absent.

    Raises RuntimeError on wFirma error status.
    Raises ConnectionError on network failure.
    Returns None (not raises) when the account_id maps to no IBAN.

    READ-ONLY — never writes to wFirma.
    """
    if not (account_id or "").strip():
        return None
    safe_id = _esc(str(account_id).strip())
    http_status, response_text = _http_request(
        "GET", "company_accounts", f"get/{safe_id}", "")
    if http_status == 404:
        return None
    if http_status >= 400:
        raise RuntimeError(
            f"company_accounts/get HTTP {http_status}: {response_text[:200]}")
    code, desc = _parse_status(response_text)
    if code != "OK":
        raise RuntimeError(
            f"company_accounts/get wFirma status={code}: {desc}")
    try:
        root = ET.fromstring(response_text)
        node = root.find(".//company_account")
        iban_raw = _find_text(node, "iban") if node is not None else ""
        return iban_raw.strip() or None
    except Exception:
        return None


def fetch_invoice_pdf(invoice_id: str) -> bytes:
    """Fetch the PDF bytes for a wFirma invoice / proforma.

    READ-ONLY. Uses path-based ``GET invoices/download/{id}`` (confirmed
    in ``docs/WFIRMA_API_VALIDATED_MAP.md``). wFirma returns one of two
    response shapes:

      a) **XML envelope with base64 file** — the dbojdo / webit SDK
         shape. We parse the XML, look for a base64-encoded blob in
         common field names (``file``, ``pdf``, ``content``,
         ``invoice``) and decode it.
      b) **Raw PDF bytes** — some installations stream binary directly.
         We detect this by the ``%PDF-`` magic header.

    Raises:
      ValueError      — empty / whitespace ``invoice_id``
      RuntimeError    — HTTP ≥ 400, wFirma status != OK, missing PDF
                        payload in response
      ConnectionError — network failure (propagated from _http_request)

    Never calls ``invoices/add``, ``invoices/edit``, ``invoices/send``,
    ``invoices/fiscalise`` or any other write/state-changing endpoint.
    """
    if not (invoice_id or "").strip():
        raise ValueError("invoice_id is required")
    safe_id = _esc(invoice_id).strip()
    http_status, response_text = _http_request(
        "GET", "invoices", f"download/{safe_id}", "")
    if http_status == 404:
        raise RuntimeError(
            f"invoices/download: invoice {invoice_id!r} not found")
    if http_status >= 400:
        raise RuntimeError(
            f"invoices/download HTTP {http_status}: {response_text[:200]}")

    # Shape (b): raw PDF bytes streamed directly. ``response_text`` is
    # whatever requests decoded the body as, but the magic header is
    # detectable in the first ~16 chars regardless of decoding.
    if (response_text or "").startswith("%PDF-"):
        return response_text.encode("latin-1", errors="ignore")

    # Shape (a): XML envelope. Confirm OK first, then hunt for a base64 blob.
    code, desc = _parse_status(response_text)
    if code != "OK":
        raise RuntimeError(
            f"invoices/download wFirma status={code}: {desc}")
    try:
        root = ET.fromstring(response_text)
    except ET.ParseError as exc:
        raise RuntimeError(
            f"invoices/download: response is neither PDF nor parseable XML: {exc}"
        ) from exc

    # Search common field names. wFirma SDKs use <file> most often. We
    # try each in turn, attempt base64 decode, and accept the first one
    # whose decoded bytes carry the PDF magic header. This is more
    # robust than length-heuristics — a tiny PDF may decode to <100
    # bytes and a non-PDF text field may be arbitrarily long.
    import base64
    candidates = ("file", "pdf", "content", "data", "invoice")
    decoded_bytes: Optional[bytes] = None
    last_error: Optional[str] = None
    for tag in candidates:
        for node in root.iter(tag):
            blob = (node.text or "").strip()
            if not blob:
                continue
            # Strip whitespace/newlines that some installations inject.
            cleaned = "".join(blob.split())
            try:
                trial = base64.b64decode(cleaned, validate=False)
            except Exception as exc:
                last_error = f"{tag}: decode failed ({exc})"
                continue
            if trial.startswith(b"%PDF-"):
                decoded_bytes = trial
                break
            last_error = (f"{tag}: decoded {len(trial)} bytes, "
                          f"magic={trial[:8]!r} (not %PDF-)")
        if decoded_bytes is not None:
            break

    if decoded_bytes is None:
        raise RuntimeError(
            f"invoices/download: no base64 PDF payload found in response for "
            f"id={invoice_id} — fields tried: {candidates}"
            + (f"; last error: {last_error}" if last_error else "")
        )
    return decoded_bytes


def edit_invoice_line_name(invoice_id: str,
                            invoicecontent_xml: str,
                            new_name: str) -> Dict[str, Any]:
    """
    Edit a single proforma line's <name> via full-line restate.

    wFirma rejects partial invoicecontent edits (just <id>+<name> returns
    NOT_FOUND). The full row must be restated; only <name> may differ.
    Live diagnostic 2026-05-06 confirmed this shape on POST
    /invoices/edit/{invoice_id}.

    Args:
      invoice_id          — wFirma invoice id (in URL path).
      invoicecontent_xml  — full <invoicecontent>...</invoicecontent> element
                            extracted verbatim from invoices/find.
      new_name            — replacement value for <name>. Must be non-empty.

    The function:
      - parses the provided element
      - replaces ONLY the <name> text (creates the node if missing)
      - preserves every other child sub-element exactly
      - posts the restated <invoicecontent> inside <invoice><invoicecontents>
      - fails loudly on non-OK status or HTTP ≥ 400

    Returns dict with line id + new name as confirmed by request.
    """
    if not (invoice_id or "").strip():
        raise ValueError("invoice_id is required")
    if not (invoicecontent_xml or "").strip():
        raise ValueError("invoicecontent_xml is required")
    if not (new_name or "").strip():
        raise ValueError("new_name is required (non-empty)")

    try:
        ic = ET.fromstring(invoicecontent_xml)
    except ET.ParseError as exc:
        raise ValueError(f"invoicecontent_xml is not well-formed: {exc}") from exc
    if ic.tag != "invoicecontent":
        raise ValueError(
            f"invoicecontent_xml root must be <invoicecontent>, got <{ic.tag}>"
        )

    name_node = ic.find("name")
    if name_node is None:
        name_node = ET.SubElement(ic, "name")
    name_node.text = new_name

    line_id = (ic.findtext("id") or "").strip()
    restated_line_xml = ET.tostring(ic, encoding="unicode")

    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <invoice>
      <invoicecontents>
        {restated_line_xml}
      </invoicecontents>
    </invoice>
  </invoices>
</api>"""

    http_status, response_text = _http_request(
        "POST", "invoices", "edit", body, id_suffix=invoice_id,
    )
    if http_status >= 400:
        raise RuntimeError(
            f"invoices/edit HTTP {http_status}: {response_text[:200]}"
        )
    code, desc = _parse_status(response_text)
    if code != "OK":
        raise RuntimeError(f"invoices/edit wFirma status={code}: {desc}")

    return {
        "invoice_id":         invoice_id,
        "invoicecontent_id":  line_id,
        "new_name":           new_name,
        "raw_response":       response_text,
    }


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


# ── B0 dictionary refresh 2026-05-17 — verified live endpoint ────────────────
#
# wFirma exposes exactly one dictionary endpoint relevant to the Client Master
# Invoices tab: `series/find`. It returns every series (invoice + proforma +
# offer + spec + margin) in one response, discriminated by <type>. The
# other dictionaries we initially considered — invoiceseries, proformaseries,
# languages, currencies — all return CONTROLLER NOT FOUND (probe captured in
# tasks/reports/wfirma-dictionary-endpoint-probe.md). Read-only. Never raises.

def fetch_series() -> List[Dict[str, str]]:
    """Read-only fetch of all wFirma series (invoice / proforma / offer / etc.).

    Returns a list of normalised dicts:
        {"id":    "<wfirma series id>",
         "label": "<template, e.g. 'FV [numer]/[rok]'>",
         "code":  "<short name, often 'domyślna'>",
         "type":  "<normal|margin|proforma|offer|spec|...>"}

    On any failure path (HTTP error, CONTROLLER NOT FOUND, malformed XML)
    returns []. The caller treats that as "live source unavailable" and
    falls back to the baseline dictionary.

    Hard rule: read-only. Never POST/PUT/DELETE.
    """
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<api><series><parameters><page>1</page><limit>200</limit></parameters></series></api>'
    )
    try:
        http_status, response_text = _http_request("GET", "series", "find", body)
    except Exception:
        return []
    if http_status >= 400 or not response_text:
        return []
    try:
        root = ET.fromstring(response_text)
    except Exception:
        return []
    code, _desc = _parse_status(response_text)
    if code != "OK":
        # CONTROLLER NOT FOUND, NOT FOUND, etc. — caller falls back to baseline.
        return []
    out: List[Dict[str, str]] = []
    container = root.find("series")
    if container is None:
        return out
    for node in container.findall("series"):
        sid = (_find_text(node, "id") or "").strip()
        if not sid or sid == "0":
            continue
        tpl = (_find_text(node, "template") or "").strip()
        name = (_find_text(node, "name") or "").strip()
        typ = (_find_text(node, "type") or "").strip().lower()
        vis = (_find_text(node, "visibility") or "").strip().lower()
        # Label: prefer the template (operator recognises FV/PROF/OF), then name, then id.
        label = tpl or name or f"Series #{sid}"
        out.append({"id": sid, "label": label, "code": name, "type": typ,
                    "visibility": vis})
    return out
