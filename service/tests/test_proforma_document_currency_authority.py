"""Document vs source currency authority for Proforma service charges.

Pins the permanent model:
  source_currency (frozen Sales Packing provenance)
    → NBP PLN hub revalue
    → document_currency (draft.currency) for goods + freight + insurance

Readiness / preview must compare service charges to document_currency, NEVER
to sales packing / source currency after the draft has been revalued.

Draft #82 shape (generic — not by draft id):
  source_currency=USD, document_currency=PLN, service charges PLN → no
  currency-mismatch blocker.
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
from app.services import document_db as ddb
from app.services import packing_db as pdb
from app.services import proforma_invoice_link_db as pildb
from app.services import proforma_service_charges_db as scdb
from app.services import warehouse_db as wdb
from app.services import wfirma_db as wfdb
from app.services import wfirma_client as _wc


BATCH = "BATCH_DOC_CCY_AUTH"


@pytest.fixture(autouse=True)
def _prime_vat():
    _wc._VAT_CODE_ID_CACHE["23"] = "222"
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
    pildb.init_db(tmp_path / "proforma_links.db")
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


def _seed_sales_usd(*, client_name: str, design_no: str, product_code: str):
    from app.services import inventory_state_engine as ise

    pdb.upsert_packing_lines([{
        "batch_id": BATCH, "invoice_no": "INV/DOC",
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
              "sales_doc_no": "SO-DOC"},
    )
    ddb.store_sales_packing_lines(sd, BATCH, [{
        "client_name": client_name, "client_ref": "REF",
        "product_code": design_no, "design_no": design_no,
        "bag_id": "", "quantity": 1.0, "remarks": "",
        "unit_price": 100.0, "currency": "USD",
        "total_value": 100.0, "price_source": "packing_list",
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


def _currency_mismatch_reasons(body: dict) -> list:
    return [
        br for br in (body.get("blocking_reasons") or [])
        if "does not match" in str(br) and "currency" in str(br)
    ]


def test_usd_source_pln_document_pln_charges_no_mismatch(client, storage):
    """Draft #82 shape: source USD + document PLN + PLN charges must not
    false-block on currency. Sales packing remains USD provenance."""
    client_name = "DOC-PLN-CLIENT"
    design_no = "D-DOC82"
    product_code = "EJL/DOC82"
    _seed_sales_usd(
        client_name=client_name, design_no=design_no, product_code=product_code,
    )
    db = storage / "proforma_links.db"
    draft, created = pildb.auto_create_draft_from_sales_packing(
        db,
        batch_id=BATCH,
        client_name=client_name,
        currency="USD",
        lines=[{
            "product_code": product_code, "design_no": design_no,
            "qty": 1, "unit_price": 100.0, "currency": "USD",
            "price_source": "sales_packing", "name_pl": "Pierścień",
        }],
    )
    assert created
    # Simulate post-revalue document state (nbp write path already ran).
    pln_lines = [{
        "line_id": 1, "product_code": product_code, "design_no": design_no,
        "qty": 1, "unit_price": 373.24, "currency": "PLN",
        "source_unit_price": 100.0, "source_currency": "USD",
        "price_source": "sales_packing", "name_pl": "Pierścień",
    }]
    pln_charges = [
        {"charge_id": 1, "charge_type": "freight", "amount": 50.0,
         "currency": "PLN", "resolution": "manual_amount",
         "source_amount": 13.4, "source_currency": "USD"},
        {"charge_id": 2, "charge_type": "insurance", "amount": 10.0,
         "currency": "PLN", "resolution": "manual_amount",
         "source_amount": 2.68, "source_currency": "USD"},
    ]
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "UPDATE proforma_drafts SET currency=?, source_currency=?, "
            "editable_lines_json=?, service_charges_json=?, "
            "exchange_rate=?, fx_cross_rate=? WHERE id=?",
            (
                "PLN", "USD",
                json.dumps(pln_lines), json.dumps(pln_charges),
                1.0, 3.7324, draft.id,
            ),
        )
        conn.commit()

    body = client.post(
        f"/api/v1/proforma/preview/{BATCH}/{client_name}",
        headers=_auth(),
    ).json()
    assert body["currency"] == "PLN"
    assert body.get("document_currency") == "PLN"
    assert body.get("source_currency") == "USD"
    assert _currency_mismatch_reasons(body) == [], body.get("blocking_reasons")


def test_usd_source_eur_document_eur_charges_no_mismatch(client, storage):
    client_name = "DOC-EUR-CLIENT"
    design_no = "D-EUR"
    product_code = "EJL/EUR"
    _seed_sales_usd(
        client_name=client_name, design_no=design_no, product_code=product_code,
    )
    db = storage / "proforma_links.db"
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db, batch_id=BATCH, client_name=client_name, currency="USD",
        lines=[{
            "product_code": product_code, "design_no": design_no,
            "qty": 1, "unit_price": 100.0, "currency": "USD",
            "name_pl": "Ring",
        }],
    )
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "UPDATE proforma_drafts SET currency=?, source_currency=?, "
            "editable_lines_json=?, service_charges_json=? WHERE id=?",
            (
                "EUR", "USD",
                json.dumps([{
                    "line_id": 1, "product_code": product_code,
                    "design_no": design_no, "qty": 1,
                    "unit_price": 91.84, "currency": "EUR",
                    "source_unit_price": 100.0, "source_currency": "USD",
                    "name_pl": "Ring",
                }]),
                json.dumps([{
                    "charge_id": 1, "charge_type": "freight",
                    "amount": 20.0, "currency": "EUR",
                    "resolution": "manual_amount",
                }]),
                draft.id,
            ),
        )
        conn.commit()

    body = client.post(
        f"/api/v1/proforma/preview/{BATCH}/{client_name}",
        headers=_auth(),
    ).json()
    assert body["currency"] == "EUR"
    assert body.get("source_currency") == "USD"
    assert _currency_mismatch_reasons(body) == []


def test_real_mismatched_saved_charge_still_blocks(client, storage):
    """Genuine document-currency mismatch must still block (not a bypass)."""
    client_name = "DOC-MISMATCH"
    design_no = "D-MM"
    product_code = "EJL/MM"
    _seed_sales_usd(
        client_name=client_name, design_no=design_no, product_code=product_code,
    )
    db = storage / "proforma_links.db"
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db, batch_id=BATCH, client_name=client_name, currency="PLN",
        lines=[{
            "product_code": product_code, "design_no": design_no,
            "qty": 1, "unit_price": 373.0, "currency": "PLN",
            "source_unit_price": 100.0, "source_currency": "USD",
            "name_pl": "Ring",
        }],
    )
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "UPDATE proforma_drafts SET currency=?, source_currency=?, "
            "service_charges_json=? WHERE id=?",
            (
                "PLN", "USD",
                json.dumps([{
                    "charge_id": 1, "charge_type": "freight",
                    "amount": 25.0, "currency": "USD",  # wrong vs document
                    "resolution": "manual_amount",
                }]),
                draft.id,
            ),
        )
        conn.commit()

    body = client.post(
        f"/api/v1/proforma/preview/{BATCH}/{client_name}",
        headers=_auth(),
    ).json()
    assert body["ready"] is False
    assert any("does not match document currency" in br
               for br in body["blocking_reasons"])
    assert any("'PLN'" in br for br in body["blocking_reasons"])


def test_same_currency_usd_stable(client, storage):
    client_name = "DOC-USD-SAME"
    design_no = "D-USD"
    product_code = "EJL/USD"
    _seed_sales_usd(
        client_name=client_name, design_no=design_no, product_code=product_code,
    )
    db = storage / "proforma_links.db"
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db, batch_id=BATCH, client_name=client_name, currency="USD",
        lines=[{
            "product_code": product_code, "design_no": design_no,
            "qty": 1, "unit_price": 100.0, "currency": "USD",
            "name_pl": "Ring",
        }],
    )
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "UPDATE proforma_drafts SET source_currency=?, "
            "service_charges_json=? WHERE id=?",
            (
                "USD",
                json.dumps([{
                    "charge_id": 1, "charge_type": "freight",
                    "amount": 15.0, "currency": "USD",
                    "resolution": "manual_amount",
                }]),
                draft.id,
            ),
        )
        conn.commit()

    body = client.post(
        f"/api/v1/proforma/preview/{BATCH}/{client_name}",
        headers=_auth(),
    ).json()
    assert body["currency"] == "USD"
    assert body.get("source_currency") == "USD"
    assert _currency_mismatch_reasons(body) == []


def test_revalue_keeps_source_and_sets_charge_document_currency():
    """Write-time revalue: source frozen; charge currency follows document."""
    from app.services import nbp_rate_service as nbp

    engine_table = {
        "table_no": "A/152/2026",
        "table_date": "2026-08-07",
        "usd_rate": 3.7324,
        "eur_rate": 4.1000,
        "inr_rate": 0.04,
        "rates": {"USD": 3.7324, "EUR": 4.1000, "INR": 0.04},
    }
    lines = [{
        "line_id": 1, "qty": 1, "unit_price": 100.0, "currency": "USD",
    }]
    charges = [{
        "charge_id": 1, "charge_type": "freight",
        "amount": 10.0, "currency": "USD", "resolution": "manual_amount",
    }]
    with patch("app.services.nbp_rate_service._call_engine",
               return_value=engine_table):
        snap1 = nbp.revalue_commercial_snapshot(
            lines=lines, service_charges=charges,
            source_ccy="USD", doc_ccy="PLN", issue_date="2026-08-08",
        )
        snap2 = nbp.revalue_commercial_snapshot(
            lines=snap1["lines"], service_charges=snap1["service_charges"],
            source_ccy="USD", doc_ccy="EUR", issue_date="2026-08-08",
        )
    assert snap1["lines"][0]["source_currency"] == "USD"
    assert snap1["lines"][0]["source_unit_price"] == 100.0
    assert snap1["lines"][0]["currency"] == "PLN"
    assert snap1["service_charges"][0]["currency"] == "PLN"
    assert snap1["service_charges"][0]["source_currency"] == "USD"
    # Second hop must revalue from frozen source USD, not compound PLN→EUR.
    assert snap2["lines"][0]["source_unit_price"] == 100.0
    assert snap2["service_charges"][0]["source_amount"] == 10.0
    assert snap2["lines"][0]["currency"] == "EUR"
    assert snap2["service_charges"][0]["currency"] == "EUR"
    expected_eur = round(100.0 * 3.7324 / 4.1000, 4)
    assert abs(snap2["lines"][0]["unit_price"] - expected_eur) < 0.01


def test_source_grep_no_product_line_currency_comparison():
    """Duplicate authority retired: readiness must not compare to 'product
    line currency' (which historically meant sales packing / source)."""
    src = Path(__file__).resolve().parents[1] / "app" / "api" / "routes_proforma.py"
    text = src.read_text(encoding="utf-8")
    assert "product line currency" not in text
    assert "document currency" in text
    assert "document_currency" in text
