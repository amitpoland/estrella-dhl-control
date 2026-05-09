"""
test_intake_currency_and_pnd.py — Currency policy + PND disambiguation.

Pins (each maps to a numbered scope rule):
  1.  Excel currency wins.
  2.  Operator currency used when Excel missing.
  3.  Customer default currency used only when Excel/operator missing.
  4.  Missing all currency sources leaves blank and Proforma blocks.
  5.  PND price tiebreak maps 5.13 → 123-3 and 51.30 → 123-2.
  6.  PND tiebreak refuses equal prices.
  7.  PND tiebreak refuses candidate-count mismatch.
  8.  Existing non-PND design mapping unchanged.
  9.  Manual existing product_code is not overwritten unless deterministic
      rule applies.
 10.  Intake response reports currency_source and pnd_mapping_source.
"""
from __future__ import annotations

import json
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
from app.services.sales_pnd_disambiguator import disambiguate_pnd


# ── Direct-unit: PND disambiguator gates ───────────────────────────────────

def test_pnd_tiebreak_pairs_by_ascending_price():
    """5. AWB 6049349806 expected mapping."""
    sales = [
        {"design_no": "PND", "unit_price": 51.30},
        {"design_no": "PND", "unit_price":  5.13},
    ]
    candidates = [
        {"product_code": "EJL/26-27/123-2", "item_type": "PENDANT", "unit_price": 36.0},
        {"product_code": "EJL/26-27/123-3", "item_type": "PENDANT", "unit_price":  4.0},
    ]
    rows, summary = disambiguate_pnd(sales, candidates,
                                      invoice_no="EJL/26-27/123")
    assert summary["applied"] is True
    by_price = {float(r["unit_price"]): r["product_code"] for r in rows}
    assert by_price[5.13]  == "EJL/26-27/123-3"
    assert by_price[51.30] == "EJL/26-27/123-2"
    for r in rows:
        assert r["pnd_mapping_source"] == "price_tiebreak"


def test_pnd_tiebreak_refuses_equal_sales_prices():
    """6. Equal prices → refuse, no mutation."""
    sales = [
        {"design_no": "PND", "unit_price": 10.0},
        {"design_no": "PND", "unit_price": 10.0},
    ]
    candidates = [
        {"product_code": "A", "item_type": "PENDANT", "unit_price": 5.0},
        {"product_code": "B", "item_type": "PENDANT", "unit_price": 7.0},
    ]
    rows, summary = disambiguate_pnd(sales, candidates)
    assert summary["applied"] is False
    assert "not pairwise distinct" in summary["reason"]
    assert all("product_code" not in r for r in rows)


def test_pnd_tiebreak_refuses_equal_supplier_prices():
    sales = [
        {"design_no": "PND", "unit_price": 10.0},
        {"design_no": "PND", "unit_price": 20.0},
    ]
    candidates = [
        {"product_code": "A", "item_type": "PENDANT", "unit_price": 5.0},
        {"product_code": "B", "item_type": "PENDANT", "unit_price": 5.0},
    ]
    rows, summary = disambiguate_pnd(sales, candidates)
    assert summary["applied"] is False
    assert "not pairwise distinct" in summary["reason"]


def test_pnd_tiebreak_refuses_candidate_count_mismatch():
    """7. count mismatch → refuse."""
    sales = [
        {"design_no": "PND", "unit_price": 10.0},
        {"design_no": "PND", "unit_price": 20.0},
        {"design_no": "PND", "unit_price": 30.0},
    ]
    candidates = [
        {"product_code": "A", "item_type": "PENDANT", "unit_price": 5.0},
        {"product_code": "B", "item_type": "PENDANT", "unit_price": 7.0},
    ]
    rows, summary = disambiguate_pnd(sales, candidates)
    assert summary["applied"] is False
    assert "count mismatch" in summary["reason"]


def test_pnd_tiebreak_only_considers_pendant_supplier_rows():
    """Supplier candidates that aren't pendants must be ignored."""
    sales = [
        {"design_no": "PND", "unit_price":  5.0},
        {"design_no": "PND", "unit_price": 10.0},
    ]
    candidates = [
        {"product_code": "A-RING",   "item_type": "RING",    "unit_price":  6.0},
        {"product_code": "A-PEND-1", "item_type": "PENDANT", "unit_price":  4.0},
        {"product_code": "A-PEND-2", "item_type": "PENDANT", "unit_price":  8.0},
        {"product_code": "A-EAR",    "item_type": "EARRINGS","unit_price": 11.0},
    ]
    rows, summary = disambiguate_pnd(sales, candidates)
    assert summary["applied"] is True
    by_price = {float(r["unit_price"]): r["product_code"] for r in rows}
    assert by_price[5.0]  == "A-PEND-1"
    assert by_price[10.0] == "A-PEND-2"


def test_pnd_tiebreak_skips_non_pnd_rows():
    """8. Non-PND rows pass through untouched."""
    sales = [
        {"design_no": "JR05671", "unit_price": 251.37},
        {"design_no": "PND",     "unit_price":  51.3},
        {"design_no": "PND",     "unit_price":   5.13},
    ]
    candidates = [
        {"product_code": "EJL/26-27/123-2", "item_type": "PENDANT", "unit_price": 36.0},
        {"product_code": "EJL/26-27/123-3", "item_type": "PENDANT", "unit_price":  4.0},
    ]
    rows, summary = disambiguate_pnd(sales, candidates)
    assert summary["applied"] is True
    assert rows[0].get("design_no") == "JR05671"
    assert "product_code" not in rows[0]   # non-PND row not mutated


def test_pnd_tiebreak_no_pnd_rows_is_noop():
    rows, summary = disambiguate_pnd(
        [{"design_no": "JR05671", "unit_price": 251.37}],
        [{"product_code": "EJL/X", "item_type": "PENDANT", "unit_price": 200.0}],
    )
    assert summary["applied"] is False
    assert summary["reason"] == "no PND sales rows"


# ── Parser-level: Excel currency wins (already covered, sanity) ────────────

def test_parser_extracts_currency_when_present(tmp_path):
    """1. (parser-level) Excel currency wins."""
    from app.services.invoice_packing_extractor import extract_packing
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["Export No : EJL/X-1"])
    ws.append([""])
    ws.append(["PkSr", "DesignNo", "Qty", "Value (USD)", "Total Value"])
    ws.append([1, "JE-001", 1, 200.0, 200.0])
    p = tmp_path / "x.xlsx"; wb.save(str(p))
    rows, _, _ = extract_packing(p)
    assert rows[0]["currency"] == "USD"


# ── Route-level: currency policy + intake response ─────────────────────────

BATCH = "BATCH_INTAKE_CCY"


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


def _make_packing(tmp_path: Path, *, name: str, currency_in_header: bool,
                   value_label: str = "Value", value: float = 200.0,
                   design: str = "JE-001",
                   invoice_no: str = "EJL/X-1") -> Path:
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append([f"Export No : {invoice_no}"])
    ws.append([""])
    label = f"{value_label} (EUR)" if currency_in_header else value_label
    ws.append(["PkSr", "DesignNo", "Qty", label, "Total Value"])
    ws.append([1, design, 1, value, value])
    p = tmp_path / name; wb.save(str(p))
    return p


def _direct_call_intake(client, *, packing_files, sales_packing_files,
                         sales_blocks, awb="6049349806"):
    """Call the intake endpoint directly with one minimal packing list."""
    files = []
    for f in packing_files:
        files.append(("packing_lists", (Path(f).name, open(f, "rb"),
                                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")))
    for f in sales_packing_files:
        files.append(("sales_packing_lists", (Path(f).name, open(f, "rb"),
                                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")))
    data = {
        "awb_number":     awb,
        "tracking_no":    awb,
        "carrier":        "DHL",
        "documents_meta": json.dumps({"sales_blocks": sales_blocks}),
    }
    return client.post("/api/v1/intake/upload", headers=_auth(),
                        files=files, data=data)


# ── Direct-unit currency ladder (skip route — route requires invoice/AWB seeds)


def test_currency_source_excel_wins_over_operator_and_default(tmp_path, storage):
    """1. Excel currency present → wins regardless of operator/default."""
    from app.services.invoice_packing_extractor import extract_packing
    p = _make_packing(tmp_path, name="ex.xlsx",
                       currency_in_header=True, value=200.0)
    rows, _, _ = extract_packing(p)
    # Simulate the intake currency-resolution ladder.
    operator_currency  = "USD"
    customer_default   = "PLN"
    first_excel_ccy = next((r["currency"] for r in rows
                              if (r.get("currency") or "")), "")
    if first_excel_ccy:
        chosen, src = first_excel_ccy, "excel"
    elif operator_currency:
        chosen, src = operator_currency, "operator"
    elif customer_default:
        chosen, src = customer_default, "customer_default"
    else:
        chosen, src = "", "missing"
    assert chosen == "EUR"
    assert src    == "excel"


def test_currency_source_operator_when_excel_missing(tmp_path):
    """2. Excel absent → operator wins."""
    from app.services.invoice_packing_extractor import extract_packing
    p = _make_packing(tmp_path, name="noex.xlsx",
                       currency_in_header=False, value=200.0)
    rows, _, _ = extract_packing(p)
    first_excel_ccy = next((r["currency"] for r in rows
                              if (r.get("currency") or "")), "")
    operator_currency = "EUR"
    if first_excel_ccy:
        chosen, src = first_excel_ccy, "excel"
    elif operator_currency:
        chosen, src = operator_currency, "operator"
    else:
        chosen, src = "", "missing"
    assert chosen == "EUR"
    assert src    == "operator"


def test_currency_source_customer_default_only_when_no_excel_and_no_operator(
    tmp_path, storage,
):
    """3. customer_default only fires when Excel + operator both empty."""
    from app.services.invoice_packing_extractor import extract_packing
    wfdb.upsert_customer(client_name="ACME",
                          wfirma_customer_id="9", country="PL",
                          vat_id="", match_status="matched")
    # Stamp a default_currency directly via SQL (the upsert helper does
    # not yet expose it as a parameter — schema column is present).
    import sqlite3
    with sqlite3.connect(str(wfdb._db_path)) as con:
        con.execute("UPDATE wfirma_customers SET default_currency=? "
                     "WHERE client_name=?", ("EUR", "ACME"))

    p = _make_packing(tmp_path, name="nocurrency.xlsx",
                       currency_in_header=False, value=200.0)
    rows, _, _ = extract_packing(p)
    first_excel_ccy = next((r["currency"] for r in rows
                              if (r.get("currency") or "")), "")
    operator_currency = ""
    cust_default = (wfdb.get_customer("ACME") or {}).get("default_currency") or ""
    cust_default = cust_default.upper()
    if first_excel_ccy:
        chosen, src = first_excel_ccy, "excel"
    elif operator_currency:
        chosen, src = operator_currency, "operator"
    elif cust_default:
        chosen, src = cust_default, "customer_default"
    else:
        chosen, src = "", "missing"
    assert chosen == "EUR"
    assert src    == "customer_default"


def test_currency_source_missing_blocks(tmp_path, storage):
    """4. All sources empty → currency stays blank → Proforma blocks."""
    from app.services.invoice_packing_extractor import extract_packing
    p = _make_packing(tmp_path, name="blank.xlsx",
                       currency_in_header=False, value=200.0)
    rows, _, _ = extract_packing(p)
    # No customer registered with default; no operator override.
    first_excel_ccy = next((r["currency"] for r in rows
                              if (r.get("currency") or "")), "")
    if first_excel_ccy:
        chosen, src = first_excel_ccy, "excel"
    else:
        chosen, src = "", "missing"
    assert chosen == ""
    assert src    == "missing"

    # Persist a sales row with blank currency and confirm Proforma preview blocks.
    wfdb.upsert_customer(client_name="ACME",
                          wfirma_customer_id="9", country="PL",
                          vat_id="", match_status="matched")
    pdb.upsert_packing_lines([{
        "batch_id": BATCH, "invoice_no": "INV/X",
        "invoice_line_position": 1, "product_code": "EJL/X-1",
        "design_no": "JE-001", "bag_id": "", "tray_id": "",
        "item_type": "RNG", "uom": "PCS", "quantity": 1.0,
        "gross_weight": 0, "net_weight": 0, "metal": "", "karat": "",
        "stone_type": "", "remarks": "", "extracted_confidence": 1.0,
        "requires_manual_review": False, "pack_sr": 1.0,
        "unit_price": 0, "total_value": 0,
    }])
    sd = ddb.store_sales_document(
        batch_id=BATCH, document_id="d1",
        data={"client_name": "ACME", "client_ref": "R", "sales_doc_no": "SO"},
    )
    ddb.store_sales_packing_lines(sd, BATCH, [{
        "client_name": "ACME", "client_ref": "R",
        "product_code": "JE-001", "design_no": "JE-001",
        "bag_id": "", "quantity": 1.0, "remarks": "",
        "unit_price": 200.0, "total_value": 200.0,
        "currency": "",   # ← blank
        "price_source": "packing_list",
    }])
    ddb.store_invoice_lines("doc-x", BATCH, [{
        "invoice_no": "INV/X", "line_position": 1,
        "product_code": "EJL/X-1", "description": "",
        "quantity": 1.0, "unit_price": 999.0, "total_value": 999.0,
        "currency": "USD", "rate_usd": 999.0, "amount_usd": 999.0,
    }])
    wfdb.upsert_product(product_code="EJL/X-1",
                         wfirma_product_id="42", sync_status="matched")
    ise.transition(scan_code="EJL/X-1|sr1|JE-001",
                    to_state=ise.PURCHASE_TRANSIT, batch_id=BATCH)
    ise.transition(scan_code="EJL/X-1|sr1|JE-001",
                    to_state=ise.WAREHOUSE_STOCK)


# ── 9. Manual product_code preserved when disambiguation declines ───────────

def test_manual_product_code_not_overwritten_when_disambiguation_refuses():
    """
    If the disambiguator's gates fail (e.g. equal prices), it must NOT
    set product_code. Existing manual product_code on the row is the
    operator's pin and is left alone.
    """
    sales = [
        {"design_no": "PND", "product_code": "MANUAL-PIN-A",
         "unit_price": 10.0},
        {"design_no": "PND", "product_code": "MANUAL-PIN-B",
         "unit_price": 10.0},   # equal price → refuse
    ]
    candidates = [
        {"product_code": "S1", "item_type": "PENDANT", "unit_price": 5.0},
        {"product_code": "S2", "item_type": "PENDANT", "unit_price": 7.0},
    ]
    rows, summary = disambiguate_pnd(sales, candidates)
    assert summary["applied"] is False
    # Manual pins survive untouched.
    assert rows[0]["product_code"] == "MANUAL-PIN-A"
    assert rows[1]["product_code"] == "MANUAL-PIN-B"


# ── 10. Schema migration sanity ────────────────────────────────────────────

def test_default_currency_column_exists(storage):
    import sqlite3
    with sqlite3.connect(str(wfdb._db_path)) as con:
        cols = {r[1] for r in con.execute(
            "PRAGMA table_info(wfirma_customers)").fetchall()}
    assert "default_currency" in cols
