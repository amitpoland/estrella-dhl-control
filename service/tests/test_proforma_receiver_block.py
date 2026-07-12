"""
test_proforma_receiver_block.py — Step 2 of Nabywca/Odbiorca support.

Pins the wFirma `<contractor_receiver>` emission rules in
``_build_proforma_xml`` and the read-side projection in
``_parse_proforma_from_xml``. Also pins the preview/build-time blockers
when ``ship_to_mode='separate_contractor'`` is misconfigured.

Coverage (matches the numbered scope rules):
  1. XML includes contractor_receiver for separate_contractor (with
     non-self-reference receiver id).
  2. XML omits contractor_receiver for same_as_bill_to.
  3. XML omits contractor_receiver for bill_to_alt.
  4. separate_contractor without receiver blocks preview AND
     _build_proforma_request raises ValueError.
  5. self-reference receiver is omitted by builder defence-in-depth AND
     blocked at preview/build time.
  6. read-back parser returns contractor_receiver_id (and normalises "0"
     to empty string).
  7. pricing/currency XML lines unchanged.
"""
from __future__ import annotations

import re
import sqlite3
import uuid
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


BATCH = "BATCH_RECEIVER_TEST"


# ── Direct builder/dataclass tests ──────────────────────────────────────────

def _base_request(*, receiver_id: str = "") -> wc.ProformaRequest:
    return wc.ProformaRequest(
        client_name                   = "ACME",
        client_zip                    = "",
        client_city                   = "",
        lines                         = [wc.ReservationLine(
            product_code   = "EJL/X-1",
            wfirma_good_id = "42",
            product_name   = "JE100",
            qty            = 1.0,
            unit_price     = 200.0,
            unit           = "szt.",
            currency       = "EUR",
        )],
        currency                      = "EUR",
        wfirma_contractor_id          = "9001",
        vat_code_id                   = "228",
        wfirma_contractor_receiver_id = receiver_id,
    )


# ── 1. separate_contractor → emits <contractor_receiver> ───────────────────

def test_xml_includes_contractor_receiver_when_set():
    xml = wc._build_proforma_xml(_base_request(receiver_id="99990004"))
    assert "<contractor_receiver><id>99990004</id></contractor_receiver>" in xml
    # Sanity: still has bill-to.
    assert "<contractor><id>9001</id></contractor>" in xml


# ── 2/3. same_as_bill_to / bill_to_alt → omits the block ───────────────────

def test_xml_omits_contractor_receiver_when_empty():
    xml = wc._build_proforma_xml(_base_request(receiver_id=""))
    assert "<contractor_receiver" not in xml


def test_xml_omits_contractor_receiver_when_zero_sentinel():
    """wFirma's read-side normalisation treats id='0' as 'no receiver'.
    The builder must NOT emit '<contractor_receiver><id>0</id></...>' —
    that would round-trip to a literal lookup against contractor 0."""
    xml = wc._build_proforma_xml(_base_request(receiver_id="0"))
    assert "<contractor_receiver" not in xml


def test_xml_omits_contractor_receiver_when_whitespace():
    xml = wc._build_proforma_xml(_base_request(receiver_id="   "))
    assert "<contractor_receiver" not in xml


# ── 5. Self-reference is omitted by builder ─────────────────────────────────

def test_xml_omits_contractor_receiver_on_self_reference():
    """Defence-in-depth: even if a stale request slips past the route's
    self-reference guard, the builder MUST NOT emit a self-referential
    receiver block."""
    req = _base_request(receiver_id="9001")  # equals bill-to id
    xml = wc._build_proforma_xml(req)
    assert "<contractor_receiver" not in xml


# ── 7. Pricing/currency XML unchanged when receiver added ──────────────────

def test_pricing_currency_xml_unchanged_when_receiver_added():
    bare    = wc._build_proforma_xml(_base_request(receiver_id=""))
    with_rx = wc._build_proforma_xml(_base_request(receiver_id="99990004"))

    # Strip the receiver block from the expanded XML and confirm the
    # remainder matches byte-for-byte (modulo whitespace inserted at the
    # placeholder position).
    stripped = re.sub(
        r"\s*<contractor_receiver><id>[^<]+</id></contractor_receiver>\s*",
        " ", with_rx,
    )
    # Both should carry identical line content, currency, and vat_code.
    for fragment in (
        "<count>1.0000</count>",
        "<price>200.00</price>",
        "<currency>EUR</currency>",
        "<vat_code><id>228</id></vat_code>",
        "<contractor><id>9001</id></contractor>",
    ):
        assert fragment in bare,    f"baseline missing: {fragment}"
        assert fragment in with_rx, f"receiver-added missing: {fragment}"
        assert fragment in stripped, f"stripped lost: {fragment}"


# ── 6. Read-back parser projects contractor_receiver_id ────────────────────

_PROFORMA_WITH_RCV = """<?xml version="1.0"?>
<api>
  <invoices>
    <invoice>
      <id>X</id>
      <type>proforma</type>
      <fullnumber>PROF 99/2026</fullnumber>
      <contractor><id>9001</id></contractor>
      <contractor_receiver><id>99990004</id></contractor_receiver>
      <currency>EUR</currency>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""


_PROFORMA_NO_RCV = _PROFORMA_WITH_RCV.replace(
    "<contractor_receiver><id>99990004</id></contractor_receiver>", "")


_PROFORMA_RCV_ZERO = _PROFORMA_WITH_RCV.replace(
    "<contractor_receiver><id>99990004</id></contractor_receiver>",
    "<contractor_receiver><id>0</id></contractor_receiver>")


def test_parser_projects_contractor_receiver_id():
    from app.api.routes_proforma import _parse_proforma_from_xml
    parsed = _parse_proforma_from_xml(_PROFORMA_WITH_RCV)
    assert parsed["contractor_receiver_id"] == "99990004"
    assert parsed["contractor_id"]          == "9001"


def test_parser_returns_empty_receiver_when_omitted():
    from app.api.routes_proforma import _parse_proforma_from_xml
    parsed = _parse_proforma_from_xml(_PROFORMA_NO_RCV)
    assert parsed["contractor_receiver_id"] == ""


def test_parser_normalises_zero_receiver_to_empty():
    """wFirma's "no receiver" sentinel is id='0'. Parser should hide it
    from operator-facing responses so the dashboard doesn't display a
    spurious receiver of literal contractor 0."""
    from app.api.routes_proforma import _parse_proforma_from_xml
    parsed = _parse_proforma_from_xml(_PROFORMA_RCV_ZERO)
    assert parsed["contractor_receiver_id"] == ""


# ── 4/5. Preview-level blockers (route integration) ────────────────────────

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
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


def _seed_full_line(*, design="JE100", product_code="EJL/X-1",
                     client_name="ACME"):
    pdb.upsert_packing_lines([{
        "batch_id": BATCH, "invoice_no": "INV/X",
        "invoice_line_position": 1, "product_code": product_code,
        "design_no": design, "bag_id": "", "tray_id": "",
        "item_type": "RNG", "uom": "PCS", "quantity": 1.0,
        "gross_weight": 0.0, "net_weight": 0.0,
        "metal": "", "karat": "", "stone_type": "", "remarks": "",
        "extracted_confidence": 1.0, "requires_manual_review": False,
        "pack_sr": 1.0, "unit_price": 0.0, "total_value": 0.0,
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


# ── 4. Preview blocks separate_contractor without receiver ─────────────────

def test_preview_blocks_separate_contractor_without_receiver(client, storage):
    _seed_full_line()
    # Force separate_contractor mode without a receiver id (would also
    # be blocked by the helper, but test the validation path that catches
    # a stale/legacy row that pre-dates the helper landing).
    with sqlite3.connect(str(wfdb._db_path)) as con:
        con.execute("UPDATE wfirma_customers SET ship_to_mode=?, "
                     "ship_to_wfirma_customer_id=? WHERE client_name=?",
                     ("separate_contractor", "", "ACME"))

    body = client.post(f"/api/v1/proforma/preview/{BATCH}/ACME",
                       headers=_auth()).json()
    assert body["ready"] is False
    assert any("'separate_contractor'" in r and "empty" in r
               for r in body["blocking_reasons"]), body["blocking_reasons"]
    assert body["ship_to"]["mode"] == "separate_contractor"
    assert body["ship_to"]["ship_to_wfirma_customer_id"] == ""


def test_build_proforma_request_raises_on_missing_receiver(client, storage):
    """Defence-in-depth: even if preview were bypassed, the
    request-build raises before reaching wFirma."""
    from app.api.routes_proforma import _build_preview, _build_proforma_request
    _seed_full_line()
    with sqlite3.connect(str(wfdb._db_path)) as con:
        con.execute("UPDATE wfirma_customers SET ship_to_mode=?, "
                     "ship_to_wfirma_customer_id=? WHERE client_name=?",
                     ("separate_contractor", "", "ACME"))
    preview = _build_preview(BATCH, "ACME")
    # Preview is not ready, but the test directly verifies the build-
    # time guard.
    with pytest.raises(ValueError, match="empty"):
        _build_proforma_request(preview)


# ── 5. Self-reference blocked at preview ────────────────────────────────────

def test_preview_blocks_separate_contractor_self_reference(client, storage):
    _seed_full_line()
    with sqlite3.connect(str(wfdb._db_path)) as con:
        # bill_to is "9001"; force receiver to the same id (a stale row
        # the helper rejects on write — defence-in-depth at preview).
        con.execute("UPDATE wfirma_customers SET ship_to_mode=?, "
                     "ship_to_wfirma_customer_id=? WHERE client_name=?",
                     ("separate_contractor", "9001", "ACME"))
    body = client.post(f"/api/v1/proforma/preview/{BATCH}/ACME",
                       headers=_auth()).json()
    assert body["ready"] is False
    assert any("DIFFERENT receiver" in r
               for r in body["blocking_reasons"]), body["blocking_reasons"]


# ── 2/3. Preview shows ship_to mode without blocking ────────────────────────

def test_preview_same_as_bill_to_no_blocker(client, storage):
    _seed_full_line()
    body = client.post(f"/api/v1/proforma/preview/{BATCH}/ACME",
                       headers=_auth()).json()
    assert body["ready"] is True
    assert body["ship_to"]["mode"]                       == "same_as_bill_to"
    assert body["ship_to"]["ship_to_wfirma_customer_id"] == ""


def test_preview_bill_to_alt_no_blocker(client, storage):
    _seed_full_line()
    wfdb.set_customer_ship_to(client_name="ACME", mode="bill_to_alt")
    body = client.post(f"/api/v1/proforma/preview/{BATCH}/ACME",
                       headers=_auth()).json()
    assert body["ready"] is True
    assert body["ship_to"]["mode"] == "bill_to_alt"


def test_preview_separate_contractor_with_receiver_ready(client, storage):
    _seed_full_line()
    wfdb.set_customer_ship_to(client_name="ACME",
                                mode="separate_contractor",
                                ship_to_wfirma_customer_id="99990004")
    body = client.post(f"/api/v1/proforma/preview/{BATCH}/ACME",
                       headers=_auth()).json()
    assert body["ready"] is True, body["blocking_reasons"]
    assert body["ship_to"]["mode"]                       == "separate_contractor"
    assert body["ship_to"]["ship_to_wfirma_customer_id"] == "99990004"


# ── End-to-end: build threads receiver into ProformaRequest ─────────────────

def test_build_proforma_request_threads_receiver(client, storage):
    from app.api.routes_proforma import _build_preview, _build_proforma_request
    _seed_full_line()
    wfdb.set_customer_ship_to(client_name="ACME",
                                mode="separate_contractor",
                                ship_to_wfirma_customer_id="99990004")
    preview = _build_preview(BATCH, "ACME")
    assert preview["ready"] is True
    req, _warnings = _build_proforma_request(preview)  # ADR-027: returns (req, warnings)
    assert req.wfirma_contractor_receiver_id == "99990004"
    # Builder emits the receiver block.
    xml = wc._build_proforma_xml(req)
    assert "<contractor_receiver><id>99990004</id></contractor_receiver>" in xml


def test_build_proforma_request_omits_receiver_when_same_as_bill_to(
    client, storage,
):
    from app.api.routes_proforma import _build_preview, _build_proforma_request
    _seed_full_line()
    # default ship_to_mode is same_as_bill_to
    preview = _build_preview(BATCH, "ACME")
    req, _warnings = _build_proforma_request(preview)  # ADR-027: returns (req, warnings)
    assert req.wfirma_contractor_receiver_id == ""
    xml = wc._build_proforma_xml(req)
    assert "<contractor_receiver" not in xml
