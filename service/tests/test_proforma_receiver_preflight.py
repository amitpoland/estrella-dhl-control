"""
test_proforma_receiver_preflight.py — Step 3 of Nabywca/Odbiorca support.

Pins the live wFirma receiver preflight + read-side helpers + dashboard
ship-to surfacing.

Coverage (matches scope rules):
  1. ``fetch_contractor_by_id`` uses path-based ``contractors/get/{id}``.
  2. HTTP 404 / wFirma NOT_FOUND returns ``ok=False``.
  3. Valid XML returns ``name``/``nip``/``country``/contact fields.
  4. Proforma create blocks when receiver id missing in wFirma.
  5. Proforma create proceeds to live wFirma call when receiver exists.
  6. Empty receiver id does not call the preflight at all.
  7. Dashboard source-grep confirms ship_to is rendered.

Plus thin guards:
  - Source-grep that ``contractors/get/`` (not ``contractors/find``) is
    the path used by the new fetcher.
  - readiness aggregator includes ``ship_to_mode`` /
    ``ship_to_wfirma_customer_id`` / ``ship_to_warning`` per customer.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import wfirma_client as wc
from app.services import packing_db    as pdb
from app.services import warehouse_db  as wdb
from app.services import document_db   as ddb
from app.services import wfirma_db     as wfdb
from app.services import inventory_state_engine as ise
from app.services import proforma_service_charges_db as scdb
from app.services import proforma_invoice_link_db as pildb


BATCH = "BATCH_RECEIVER_PREFLIGHT"


# ── Helper-level: fetch_contractor_by_id ──────────────────────────────────

_OK_XML = """<?xml version="1.0"?>
<api>
  <contractors>
    <contractor>
      <id>190263843</id>
      <name>Impact Gallery sp. z o.o.</name>
      <nip>5130281425</nip>
      <country>PL</country>
      <street>ul. Krakowska 12</street>
      <city>Warszawa</city>
      <zip>00-001</zip>
      <different_contact_address>1</different_contact_address>
      <contact_name>Impact Gallery — Warehouse</contact_name>
      <contact_person>Jan Kowalski</contact_person>
      <contact_street>ul. Magazynowa 5</contact_street>
      <contact_city>Warszawa</contact_city>
      <contact_zip>02-672</contact_zip>
      <contact_country>PL</contact_country>
    </contractor>
  </contractors>
  <status><code>OK</code></status>
</api>"""


def _stub(http_status: int, xml: str):
    captured = {}
    def _fake(method, module, op, body):
        captured["method"] = method
        captured["module"] = module
        captured["op"]     = op
        captured["body"]   = body
        return http_status, xml
    return patch.object(wc, "_http_request", side_effect=_fake), captured


# 1. Path-based GET contractors/get/{id}

def test_fetch_contractor_uses_path_based_get():
    p, captured = _stub(200, _OK_XML)
    with p:
        r = wc.fetch_contractor_by_id("190263843")
    assert r.ok is True
    assert captured["method"] == "GET"
    assert captured["module"] == "contractors"
    assert captured["op"]     == "get/190263843"
    assert captured["body"]   == ""


def test_fetch_contractor_does_NOT_use_find_with_id_condition():
    """Source-grep: the new fetcher must use ``contractors/get/{id}``,
    NOT a ``find`` with ``<field>id</field>`` condition body. wFirma
    silently ignores id in find conditions and returns the first 1000
    contractor collection — same trap that hit fetch_invoice_xml /
    fetch_warehouse_pz earlier in the project."""
    src = Path(wc.__file__).read_text(encoding="utf-8")
    fn_idx = src.find("def fetch_contractor_by_id(")
    assert fn_idx > 0
    body = src[fn_idx: fn_idx + 4000]
    assert 'f"get/{safe_id}"' in body
    # Defensive: no <field>id</field> in this function's body (find
    # bodies elsewhere in the module are still fine).
    assert "<field>id</field>" not in body


# 2. 404 → ok=False

def test_fetch_contractor_404_returns_ok_false():
    p, _ = _stub(404, "<api><status><code>ERROR</code></status></api>")
    with p:
        r = wc.fetch_contractor_by_id("999")
    assert r.ok is False
    assert "not found" in (r.error or "").lower()


def test_fetch_contractor_500_returns_ok_false():
    p, _ = _stub(500, "internal error")
    with p:
        r = wc.fetch_contractor_by_id("190263843")
    assert r.ok is False
    assert "HTTP 500" in (r.error or "")


def test_fetch_contractor_wfirma_error_returns_ok_false():
    p, _ = _stub(200,
        "<api><status><code>ERROR</code><description>nope</description></status></api>")
    with p:
        r = wc.fetch_contractor_by_id("190263843")
    assert r.ok is False
    assert "ERROR" in (r.error or "") or "nope" in (r.error or "")


def test_fetch_contractor_xml_parse_error_returns_ok_false():
    p, _ = _stub(200, "this is not xml")
    with p:
        r = wc.fetch_contractor_by_id("190263843")
    assert r.ok is False


def test_fetch_contractor_no_node_returns_ok_false():
    p, _ = _stub(200,
        '<api><contractors></contractors><status><code>OK</code></status></api>')
    with p:
        r = wc.fetch_contractor_by_id("190263843")
    assert r.ok is False
    assert "no <contractor>" in (r.error or "")


# 3. Valid XML → projects all expected fields

def test_fetch_contractor_projects_full_record():
    p, _ = _stub(200, _OK_XML)
    with p:
        r = wc.fetch_contractor_by_id("190263843")
    assert r.ok                        is True
    assert r.contractor_id             == "190263843"
    assert r.name                      == "Impact Gallery sp. z o.o."
    assert r.nip                       == "5130281425"
    assert r.country                   == "PL"
    assert r.street                    == "ul. Krakowska 12"
    assert r.city                      == "Warszawa"
    assert r.zip                       == "00-001"
    assert r.different_contact_address is True
    assert r.contact_name              == "Impact Gallery — Warehouse"
    assert r.contact_person            == "Jan Kowalski"
    assert r.contact_street            == "ul. Magazynowa 5"
    assert r.contact_zip               == "02-672"
    assert r.contact_country           == "PL"


def test_fetch_contractor_empty_id_returns_ok_false():
    """Defensive: empty id short-circuits before any HTTP call."""
    with patch.object(wc, "_http_request",
                      side_effect=AssertionError("must not call")):
        r = wc.fetch_contractor_by_id("")
    assert r.ok is False
    assert "required" in (r.error or "").lower()


def test_fetch_contractor_normalises_different_contact_address_zero():
    xml = _OK_XML.replace(
        "<different_contact_address>1</different_contact_address>",
        "<different_contact_address>0</different_contact_address>")
    p, _ = _stub(200, xml)
    with p:
        r = wc.fetch_contractor_by_id("190263843")
    assert r.ok                        is True
    assert r.different_contact_address is False


# ── Route-level: Proforma create preflight ────────────────────────────────

@pytest.fixture(autouse=True)
def _prime_vat():
    wc._VAT_CODE_ID_CACHE["23"]  = "222"
    wc._VAT_CODE_ID_CACHE["WDT"] = "228"
    wc._VAT_CODE_ID_CACHE["EXP"] = "229"
    yield


@pytest.fixture()
def storage(tmp_path):
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    scdb.init(tmp_path / "proforma_links.db")
    pildb.init_db(tmp_path / "proforma_links.db")
    (tmp_path / "outputs" / BATCH).mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


def _gate_create_on():
    return patch.object(settings, "wfirma_create_proforma_allowed", True)


def _seed_ready_proforma(*, design="JE100", product_code="EJL/X-1",
                          client_name="ACME"):
    pdb.upsert_packing_lines([{
        "batch_id": BATCH, "invoice_no": "INV/X",
        "invoice_line_position": 1, "product_code": product_code,
        "design_no": design, "bag_id": "", "tray_id": "",
        "item_type": "RNG", "uom": "PCS", "quantity": 1.0,
        "gross_weight": 0.0, "net_weight": 0.0, "metal": "", "karat": "",
        "stone_type": "", "remarks": "", "extracted_confidence": 1.0,
        "requires_manual_review": False, "pack_sr": 1.0,
        "unit_price": 0.0, "total_value": 0.0,
    }])
    sd = ddb.store_sales_document(
        batch_id=BATCH, document_id=str(uuid.uuid4()),
        data={"client_name": client_name, "client_ref": "REF",
              "sales_doc_no": "SO"},
    )
    ddb.store_sales_packing_lines(sd, BATCH, [{
        "client_name":  client_name, "client_ref": "REF",
        "product_code": design, "design_no": design,
        "bag_id": "", "quantity": 1.0, "remarks": "",
        "unit_price":   200.0, "currency": "EUR",
        "total_value":  200.0, "price_source": "packing_list",
    }])
    ddb.store_invoice_lines("doc-x", BATCH, [{
        "invoice_no": "INV/X", "line_position": 1,
        "product_code": product_code, "description": "",
        "quantity": 1.0, "unit_price": 999.0, "total_value": 999.0,
        "currency": "USD", "rate_usd": 999.0, "amount_usd": 999.0,
    }])
    wfdb.upsert_product(product_code=product_code,
                        wfirma_product_id="42", sync_status="matched")
    wfdb.upsert_customer(client_name=client_name,
                         wfirma_customer_id="9001", country="PL",
                         vat_id="PL5252812119", match_status="matched")
    sc = f"{product_code}|sr1|{design}"
    ise.transition(scan_code=sc, to_state=ise.PURCHASE_TRANSIT, batch_id=BATCH)
    ise.transition(scan_code=sc, to_state=ise.WAREHOUSE_STOCK)


# 4. Create blocks when receiver missing in wFirma

def test_create_blocks_when_receiver_missing_in_wfirma(client, storage):
    _seed_ready_proforma()
    wfdb.set_customer_ship_to(client_name="ACME",
                                mode="separate_contractor",
                                ship_to_wfirma_customer_id="190263843")

    fail = wc.ContractorFetchResult(
        ok=False, contractor_id="190263843",
        error="contractor '190263843' not found")

    with _gate_create_on(), \
         patch.object(wc, "fetch_contractor_by_id", return_value=fail), \
         patch.object(wc, "create_proforma_draft",
                      side_effect=AssertionError(
                          "must not call create when receiver missing")):
        body = client.post(
            f"/api/v1/proforma/create/{BATCH}/ACME",
            headers=_auth()).json()
    assert body["ok"]     is False
    assert body["status"] == "blocked"
    assert any("190263843" in r and "not found in wFirma" in r
               for r in body["blocking_reasons"]), body["blocking_reasons"]


# 5. Create proceeds when receiver exists

def test_create_proceeds_when_receiver_exists(client, storage):
    _seed_ready_proforma()
    wfdb.set_customer_ship_to(client_name="ACME",
                                mode="separate_contractor",
                                ship_to_wfirma_customer_id="190263843")

    ok = wc.ContractorFetchResult(
        ok=True, contractor_id="190263843",
        name="Impact Gallery sp. z o.o.")
    fake_create = wc.ProformaResult(ok=True, wfirma_invoice_id="WF-OK")

    with _gate_create_on(), \
         patch.object(wc, "fetch_contractor_by_id", return_value=ok) as mock_fetch, \
         patch.object(wc, "create_proforma_draft", return_value=fake_create) as mock_create:
        body = client.post(
            f"/api/v1/proforma/create/{BATCH}/ACME",
            headers=_auth()).json()
    assert body["ok"]     is True
    assert body["status"] == "issued"
    assert body["wfirma_proforma_id"] == "WF-OK"
    mock_fetch.assert_called_once_with("190263843")
    mock_create.assert_called_once()


# 6. Empty receiver id does not call the preflight

def test_create_does_not_call_preflight_when_no_receiver(client, storage):
    _seed_ready_proforma()
    # default ship_to_mode is same_as_bill_to → no receiver threaded
    fake_create = wc.ProformaResult(ok=True, wfirma_invoice_id="WF-OK")
    with _gate_create_on(), \
         patch.object(wc, "fetch_contractor_by_id",
                      side_effect=AssertionError(
                          "must not call preflight when receiver empty")), \
         patch.object(wc, "create_proforma_draft", return_value=fake_create):
        body = client.post(
            f"/api/v1/proforma/create/{BATCH}/ACME",
            headers=_auth()).json()
    assert body["status"] == "issued"


def test_create_does_not_call_preflight_for_bill_to_alt(client, storage):
    """``bill_to_alt`` is a Shape-A flavour — wFirma renders ship-to
    from the bill-to contractor's own alt-address. The Proforma payload
    carries no receiver block, so the preflight must NOT fire."""
    _seed_ready_proforma()
    wfdb.set_customer_ship_to(client_name="ACME", mode="bill_to_alt")
    fake_create = wc.ProformaResult(ok=True, wfirma_invoice_id="WF-OK")
    with _gate_create_on(), \
         patch.object(wc, "fetch_contractor_by_id",
                      side_effect=AssertionError(
                          "must not call preflight for bill_to_alt")), \
         patch.object(wc, "create_proforma_draft", return_value=fake_create):
        body = client.post(
            f"/api/v1/proforma/create/{BATCH}/ACME",
            headers=_auth()).json()
    assert body["status"] == "issued"


def test_create_blocks_when_preflight_raises(client, storage):
    """Network failure / unexpected exception in fetch_contractor_by_id
    must short-circuit with a clear blocked reason — never reach the
    create call with an unverified receiver."""
    _seed_ready_proforma()
    wfdb.set_customer_ship_to(client_name="ACME",
                                mode="separate_contractor",
                                ship_to_wfirma_customer_id="190263843")
    with _gate_create_on(), \
         patch.object(wc, "fetch_contractor_by_id",
                      side_effect=ConnectionError("net down")), \
         patch.object(wc, "create_proforma_draft",
                      side_effect=AssertionError("must not call create")):
        body = client.post(
            f"/api/v1/proforma/create/{BATCH}/ACME",
            headers=_auth()).json()
    assert body["ok"]     is False
    assert body["status"] == "blocked"
    assert any("preflight failed" in r
               for r in body["blocking_reasons"]), body["blocking_reasons"]


# Readiness aggregator surfaces ship_to fields
def test_readiness_aggregator_surfaces_ship_to_fields(client, storage):
    _seed_ready_proforma(client_name="ACME")
    wfdb.set_customer_ship_to(client_name="ACME",
                                mode="separate_contractor",
                                ship_to_wfirma_customer_id="190263843")
    body = client.get(
        f"/dashboard/batches/{BATCH}/proforma-readiness",
        headers=_auth()).json()
    details = body["customers"]["details"]
    by_name = {d["client_name"]: d for d in details}
    acme = by_name.get("ACME")
    assert acme is not None
    assert acme["ship_to_mode"]                == "separate_contractor"
    assert acme["ship_to_wfirma_customer_id"]  == "190263843"
    assert acme["ship_to_warning"]             is False


def test_readiness_aggregator_warning_for_missing_receiver(client, storage):
    _seed_ready_proforma(client_name="ACME")
    # Stamp separate_contractor mode but force receiver empty (legacy row).
    with sqlite3.connect(str(wfdb._db_path)) as con:
        con.execute("UPDATE wfirma_customers SET ship_to_mode=?, "
                     "ship_to_wfirma_customer_id=? WHERE client_name=?",
                     ("separate_contractor", "", "ACME"))
    body = client.get(
        f"/dashboard/batches/{BATCH}/proforma-readiness",
        headers=_auth()).json()
    by_name = {d["client_name"]: d for d in body["customers"]["details"]}
    acme = by_name.get("ACME")
    assert acme["ship_to_warning"] is True


# 7. Dashboard source-grep: ship_to is rendered

def test_dashboard_renders_ship_to():
    """Pin: dashboard.html reads ship_to_mode / ship_to_wfirma_customer_id /
    ship_to_warning and renders a row in the customer table when mode is
    not ``same_as_bill_to``."""
    src = Path("app/static/dashboard.html").read_text(encoding="utf-8")
    # Field references.
    assert "ship_to_mode"               in src
    assert "ship_to_wfirma_customer_id" in src
    assert "ship_to_warning"            in src
    # Conditional rendering on non-default mode.
    assert "ship_to_mode !== 'same_as_bill_to'" in src
    # Operator-visible Odbiorca label and warning copy.
    assert "Odbiorca:"                            in src
    assert "separate_contractor needs a receiver id" in src
    # The data-testid we attached for this row is present.
    assert 'data-testid="ship-to-row"' in src
