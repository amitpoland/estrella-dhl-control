"""
test_proforma_pricing_source.py — Sales packing-list pricing wins; import
cost is NOT used for customer Proformas. Service charges are operator-
entered, not derived from import cost.

Pins (each maps to a numbered scope rule):
  1. sales packing Excel price is extracted (parser-level)
  2. sales packing Excel currency is extracted (parser-level)
  3. proforma uses sales price, not import-invoice cost
  4. missing sales price blocks create
  5. EUR packing list creates EUR Proforma
  6. USD packing list creates USD Proforma
  7. freight not added unless operator explicitly adds it
  8. insurance not added unless operator explicitly adds it
  9. manual freight/insurance appear as service lines with correct currency
 10. Anastazia regression: 306 EUR sales price must NOT be replaced by
     139.31 EUR (the import-cost-converted value).
"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from unittest.mock import patch

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import wfirma_client as _wc
from app.services import packing_db   as pdb
from app.services import warehouse_db as wdb
from app.services import document_db  as ddb
from app.services import wfirma_db    as wfdb
from app.services import inventory_state_engine as ise
from app.services import proforma_service_charges_db as scdb


BATCH = "BATCH_PFP_PRICING"


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _prime_vat():
    _wc._VAT_CODE_ID_CACHE["23"]  = "222"
    _wc._VAT_CODE_ID_CACHE["WDT"] = "228"
    _wc._VAT_CODE_ID_CACHE["EXP"] = "229"
    yield
    for k in ("23", "WDT", "EXP"):
        _wc._VAT_CODE_ID_CACHE.pop(k, None)


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


# ── seed helpers ─────────────────────────────────────────────────────────────

def _seed_full(*, design_no, product_code, client_name,
               sales_unit_price, sales_currency, sales_total_value=None,
               import_cost_usd=None):
    pdb.upsert_packing_lines([{
        "batch_id": BATCH, "invoice_no": "INV/X",
        "invoice_line_position": 1, "product_code": product_code,
        "design_no": design_no, "bag_id": "", "tray_id": "",
        "item_type": "RNG", "uom": "PCS", "quantity": 1.0,
        "gross_weight": 0.0, "net_weight": 0.0,
        "metal": "", "karat": "", "stone_type": "", "remarks": "",
        "extracted_confidence": 1.0, "requires_manual_review": False,
        "pack_sr": 1.0, "unit_price": 0.0, "total_value": 0.0,
    }])
    sd = ddb.store_sales_document(
        batch_id=BATCH, document_id=str(uuid.uuid4()),
        data={"client_name": client_name, "client_ref": "REF",
              "sales_doc_no": "SO-DD"},
    )
    ddb.store_sales_packing_lines(sd, BATCH, [{
        "client_name":  client_name, "client_ref": "REF",
        "product_code": design_no, "design_no": design_no,
        "bag_id": "", "quantity": 1.0, "remarks": "",
        "unit_price":   sales_unit_price,
        "currency":     sales_currency,
        "total_value":  sales_total_value if sales_total_value is not None
                         else sales_unit_price,
        "price_source": "packing_list" if sales_unit_price else "",
    }])
    # IMPORT-side cost in USD — must be IGNORED by the proforma builder.
    if import_cost_usd is not None:
        ddb.store_invoice_lines("doc-x", BATCH, [{
            "invoice_no": "INV/X", "line_position": 1,
            "product_code": product_code, "description": "",
            "quantity": 1.0, "unit_price": import_cost_usd,
            "total_value": import_cost_usd,
            "currency": "USD", "rate_usd": import_cost_usd,
            "amount_usd": import_cost_usd,
        }])
    wfdb.upsert_product(product_code=product_code,
                        wfirma_product_id="42", sync_status="matched")
    wfdb.upsert_customer(client_name=client_name,
                         wfirma_customer_id="9", country="PL",
                         vat_id="", match_status="matched")
    sc = f"{product_code}|sr1|{design_no}"
    ise.transition(scan_code=sc, to_state=ise.PURCHASE_TRANSIT,
                   batch_id=BATCH)
    ise.transition(scan_code=sc, to_state=ise.WAREHOUSE_STOCK)


# ── 1. & 2. Parser-level (Excel) ────────────────────────────────────────────

def _make_packing_xlsx(tmp_path: Path, *, currency_in_header: bool,
                       value: float = 306.0,
                       value_label: str = "Value (EUR)") -> Path:
    """Build a minimal sales packing list Excel."""
    wb = openpyxl.Workbook()
    ws = wb.active
    # Preamble (currency may live in preamble or in header)
    ws.append(["Export No : EJL/26-27/121"])
    if not currency_in_header:
        ws.append(["Currency", "EUR"])
    ws.append([""])
    # Header row + one data row
    if currency_in_header:
        ws.append(["PkSr", "DesignNo", "Qty", value_label, "Total Value"])
    else:
        ws.append(["PkSr", "DesignNo", "Qty", "Value", "Total Value"])
    ws.append([1, "CSTR07718", 1, value, value])
    p = tmp_path / "anastazia_packing.xlsx"
    wb.save(str(p))
    return p


def test_parser_extracts_unit_price_from_excel(tmp_path):
    from app.services.invoice_packing_extractor import extract_packing
    p = _make_packing_xlsx(tmp_path, currency_in_header=True)
    rows, _, _ = extract_packing(p)
    assert len(rows) == 1
    assert float(rows[0]["unit_price"]) == 306.0


def test_parser_extracts_currency_from_header(tmp_path):
    from app.services.invoice_packing_extractor import extract_packing
    p = _make_packing_xlsx(tmp_path, currency_in_header=True)
    rows, _, _ = extract_packing(p)
    assert rows[0]["currency"] == "EUR"


def test_parser_extracts_currency_from_preamble(tmp_path):
    from app.services.invoice_packing_extractor import extract_packing
    p = _make_packing_xlsx(tmp_path, currency_in_header=False)
    rows, _, _ = extract_packing(p)
    assert rows[0]["currency"] == "EUR"


def test_parser_currency_token_usd(tmp_path):
    from app.services.invoice_packing_extractor import extract_packing
    p = _make_packing_xlsx(tmp_path, currency_in_header=True,
                            value_label="Value (USD)")
    rows, _, _ = extract_packing(p)
    assert rows[0]["currency"] == "USD"


# ── 3. Proforma uses sales price, NOT import cost ──────────────────────────

def test_proforma_uses_sales_price_not_import_cost(client):
    _seed_full(design_no="CSTR07718", product_code="EJL/26-27/121-1",
               client_name="Anastazia Panakova",
               sales_unit_price=306.0, sales_currency="EUR",
               import_cost_usd=164.0)   # cost the supplier billed Estrella
    body = client.post(
        f"/api/v1/proforma/preview/{BATCH}/Anastazia%20Panakova",
        headers=_auth()).json()
    assert body["ready"] is True
    line = body["lines"][0]
    assert line["unit_price"]   == 306.0
    assert line["currency"]     == "EUR"
    assert line["price_source"] == "packing_list"
    assert line["unit_price"]   != 164.0       # import cost rejected


# ── 10. Anastazia regression ────────────────────────────────────────────────

def test_anastazia_306_eur_does_not_become_139_eur(client):
    """Real-world bug: PROF 95/2026 was created at 139.31 EUR per line
    because the builder used import cost ($164 USD ≈ 139 EUR after wFirma
    company FX). After the fix, the line MUST carry the sales price
    verbatim from the packing list."""
    _seed_full(design_no="CSTR07718", product_code="EJL/26-27/121-1",
               client_name="Anastazia Panakova",
               sales_unit_price=306.0, sales_currency="EUR",
               import_cost_usd=164.0)
    body = client.post(
        f"/api/v1/proforma/preview/{BATCH}/Anastazia%20Panakova",
        headers=_auth()).json()
    assert body["lines"][0]["unit_price"] == 306.0
    # The 139.31 value cannot appear anywhere in the preview.
    flat = repr(body)
    assert "139.31" not in flat
    assert body["currency"] == "EUR"


# ── 4. Missing sales price blocks ──────────────────────────────────────────

def test_missing_sales_price_blocks(client):
    _seed_full(design_no="D-NP", product_code="EJL/NP-1",
               client_name="ACME",
               sales_unit_price=0,           # missing
               sales_currency="",            # missing
               import_cost_usd=999.0)        # cost present but ignored
    body = client.post(f"/api/v1/proforma/preview/{BATCH}/ACME",
                       headers=_auth()).json()
    assert body["ready"] is False
    assert any("missing sales unit_price or currency" in br
               for br in body["blocking_reasons"])
    assert body["lines"][0]["unit_price"] is None
    assert body["lines"][0]["price_source"] == "missing"


# ── 5. EUR packing list creates EUR-currency Proforma preview ──────────────

def test_eur_packing_list_drives_eur_currency(client):
    _seed_full(design_no="D-EUR", product_code="EJL/EUR-1",
               client_name="EUR-CLIENT",
               sales_unit_price=200.0, sales_currency="EUR",
               import_cost_usd=164.0)
    body = client.post(f"/api/v1/proforma/preview/{BATCH}/EUR-CLIENT",
                       headers=_auth()).json()
    assert body["currency"] == "EUR"
    assert body["lines"][0]["currency"] == "EUR"


# ── 6. USD packing list creates USD-currency Proforma preview ──────────────

def test_usd_packing_list_drives_usd_currency(client):
    _seed_full(design_no="D-USD", product_code="EJL/USD-1",
               client_name="USD-CLIENT",
               sales_unit_price=400.0, sales_currency="USD",
               import_cost_usd=164.0)
    body = client.post(f"/api/v1/proforma/preview/{BATCH}/USD-CLIENT",
                       headers=_auth()).json()
    assert body["currency"] == "USD"
    assert body["lines"][0]["currency"] == "USD"


# ── 7. & 8. Freight/insurance not silently added ───────────────────────────

def test_freight_not_added_unless_operator_explicitly_adds_it(client):
    _seed_full(design_no="D-NF", product_code="EJL/NF-1",
               client_name="NF-CLIENT",
               sales_unit_price=100.0, sales_currency="EUR",
               import_cost_usd=164.0)
    body = client.post(f"/api/v1/proforma/preview/{BATCH}/NF-CLIENT",
                       headers=_auth()).json()
    assert body["service_charges"] == []
    assert body["totals"]["service_charge_total"] == 0
    assert body["totals"]["product_total"]        == 100.0
    assert body["totals"]["final_total"]          == 100.0


def test_insurance_not_added_unless_operator_explicitly_adds_it(client):
    _seed_full(design_no="D-NI", product_code="EJL/NI-1",
               client_name="NI-CLIENT",
               sales_unit_price=100.0, sales_currency="EUR",
               import_cost_usd=164.0)
    body = client.post(f"/api/v1/proforma/preview/{BATCH}/NI-CLIENT",
                       headers=_auth()).json()
    types = {c["charge_type"] for c in body["service_charges"]}
    assert "insurance" not in types
    assert "freight"   not in types


# ── 9. Manual freight/insurance appear with correct currency ───────────────

def test_manual_service_charges_appear_with_correct_currency(client):
    _seed_full(design_no="D-SC", product_code="EJL/SC-1",
               client_name="SC-CLIENT",
               sales_unit_price=200.0, sales_currency="EUR",
               import_cost_usd=164.0)

    # Operator adds freight + insurance via the new endpoint.
    r = client.post(
        f"/api/v1/proforma/service-charges/{BATCH}/SC-CLIENT",
        headers={**_auth(), "X-Operator": "amit"},
        json={"charges": [
            {"charge_type": "freight",   "amount": 25.50, "currency": "EUR",
             "note": "DHL prepaid"},
            {"charge_type": "insurance", "amount": 10.00, "currency": "EUR"},
        ]},
    )
    assert r.status_code == 200, r.text
    body = client.post(f"/api/v1/proforma/preview/{BATCH}/SC-CLIENT",
                       headers=_auth()).json()
    sc_by_type = {c["charge_type"]: c for c in body["service_charges"]}
    assert sc_by_type["freight"]["amount"]    == 25.50
    assert sc_by_type["freight"]["currency"]  == "EUR"
    assert sc_by_type["freight"]["note"]      == "DHL prepaid"
    assert sc_by_type["insurance"]["amount"]  == 10.00
    assert sc_by_type["insurance"]["currency"] == "EUR"
    # Final total reflects them.
    assert body["totals"]["service_charge_total"] == 35.50
    assert body["totals"]["product_total"]        == 200.0
    assert body["totals"]["final_total"]          == 235.50


def test_service_charge_currency_mismatch_blocks(client):
    """Operator entering USD freight on an EUR Proforma must block."""
    _seed_full(design_no="D-MM", product_code="EJL/MM-1",
               client_name="MM-CLIENT",
               sales_unit_price=200.0, sales_currency="EUR")
    client.post(
        f"/api/v1/proforma/service-charges/{BATCH}/MM-CLIENT",
        headers=_auth(),
        json={"charges": [
            {"charge_type": "freight", "amount": 25.50, "currency": "USD"},
        ]},
    )
    body = client.post(f"/api/v1/proforma/preview/{BATCH}/MM-CLIENT",
                       headers=_auth()).json()
    assert body["ready"] is False
    assert any("does not match product line currency" in br
               for br in body["blocking_reasons"])


def test_service_charge_endpoint_validation(client):
    """Unknown charge_type is rejected; negative amount is rejected."""
    r = client.post(
        f"/api/v1/proforma/service-charges/{BATCH}/X",
        headers=_auth(),
        json={"charges": [{"charge_type": "tip",
                            "amount": 5, "currency": "EUR"}]},
    )
    assert r.status_code == 400
    r = client.post(
        f"/api/v1/proforma/service-charges/{BATCH}/X",
        headers=_auth(),
        json={"charges": [{"charge_type": "freight",
                            "amount": -5, "currency": "EUR"}]},
    )
    assert r.status_code == 400


def test_service_charge_delete(client):
    client.post(
        f"/api/v1/proforma/service-charges/{BATCH}/Z",
        headers=_auth(),
        json={"charges": [{"charge_type": "freight",
                            "amount": 5, "currency": "EUR"}]},
    )
    r = client.delete(
        f"/api/v1/proforma/service-charges/{BATCH}/Z/freight",
        headers=_auth())
    assert r.status_code == 200
    listed = client.get(
        f"/api/v1/proforma/service-charges/{BATCH}/Z",
        headers=_auth()).json()
    assert listed["charges"] == []
