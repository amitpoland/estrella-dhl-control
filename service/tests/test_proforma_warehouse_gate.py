"""
test_proforma_warehouse_gate.py — Warehouse readiness gate for proforma preview.

Verifies that _build_preview (and therefore both /preview and /create) correctly
blocks a proforma when the batch has not yet been committed to wFirma PZ, has
unresolved product_codes, or has price conflicts in pz_rows.json — and that it
is allowed once all three conditions are satisfied.

Tests:
  1. blocked_without_pz_doc_id          — audit.json present but no PZ doc ID
  2. blocked_with_unresolved_goods       — PZ created but a product_code unresolved
  3. blocked_with_price_conflicts        — PZ created, all resolved, but price conflict
  4. allowed_after_pz_exists_all_resolved — all green: no warehouse blocking reason
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import document_db  as ddb
from app.services import packing_db   as pdb
from app.services import warehouse_db as wdb
from app.services import wfirma_db    as wfdb
from app.services import wfirma_client as _wc


BATCH  = "BATCH_WHG_TEST"
CLIENT = "ACME"

# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _vat_cache():
    """Pre-populate VAT code cache so tests stay offline."""
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
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


# ── helpers ───────────────────────────────────────────────────────────────────

def _batch_dir(storage):
    d = storage / "outputs" / BATCH
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_audit(storage, *, pz_doc_id: str = ""):
    bd = _batch_dir(storage)
    audit = {
        "batch_id": BATCH,
        "wfirma_export": {
            "wfirma_pz_doc_id": pz_doc_id,
        },
    }
    (bd / "audit.json").write_text(json.dumps(audit))


def _write_pz_rows(storage, rows):
    bd = _batch_dir(storage)
    (bd / "pz_rows.json").write_text(json.dumps(rows))


def _pz_row(code: str, price: float = 100.0) -> dict:
    return {
        "product_code":    code,
        "unit_netto_pln":  price,
        "invoice_no":      "EJL/T",
        "description_en":  "Test item",
        "quantity":        1,
        "total_usd":       50.0,
    }


def _seed_happy_path(storage):
    """
    Seed the minimum data for the proforma preview to pass all *non-warehouse*
    gates for one product EJL/T-1 / design JE001 / client ACME.
    """
    # packing_lines
    pdb.upsert_packing_lines([{
        "batch_id":               BATCH,
        "invoice_no":             "EJL/T",
        "invoice_line_position":  1,
        "product_code":           "EJL/T-1",
        "design_no":              "JE001",
        "bag_id":                 "",
        "tray_id":                "",
        "item_type":              "RNG",
        "uom":                    "PCS",
        "quantity":               1.0,
        "gross_weight":           0.0,
        "net_weight":             0.0,
        "metal":                  "",
        "karat":                  "",
        "stone_type":             "",
        "remarks":                "",
        "extracted_confidence":   1.0,
        "requires_manual_review": False,
        "pack_sr":                1.0,
        "unit_price":             0.0,
        "total_value":            0.0,
    }])

    # sales document + packing lines
    sd = ddb.store_sales_document(
        batch_id=BATCH,
        document_id=str(uuid.uuid4()),
        data={"client_name": CLIENT, "client_ref": "REF", "sales_doc_no": "SO-WHG"},
    )
    ddb.store_sales_packing_lines(sd, BATCH, [{
        "client_name":  CLIENT,
        "client_ref":   "REF",
        "product_code": "JE001",
        "design_no":    "JE001",
        "bag_id":       "",
        "quantity":     1.0,
        "remarks":      "",
    }])

    # invoice pricing
    ddb.store_invoice_lines("doc-whg", BATCH, [{
        "invoice_no":    "EJL/T",
        "line_position": 1,
        "product_code":  "EJL/T-1",
        "description":   "",
        "quantity":      1.0,
        "unit_price":    100.0,
        "total_value":   100.0,
        "currency":      "USD",
        "rate_usd":      100.0,
        "amount_usd":    100.0,
    }])

    # matched product
    wfdb.upsert_product(
        product_code="EJL/T-1",
        wfirma_product_id="42",
        sync_status="matched",
    )

    # matched customer
    wfdb.upsert_customer(
        client_name=CLIENT,
        wfirma_customer_id="9",
        country="PL",
        vat_id="",
        match_status="matched",
    )


# ── tests ─────────────────────────────────────────────────────────────────────

def test_blocked_without_pz_doc_id(client, storage):
    """
    audit.json exists but wfirma_pz_doc_id is empty →
    blocking_reasons must mention 'warehouse PZ not yet created'.
    """
    _seed_happy_path(storage)
    _write_audit(storage, pz_doc_id="")          # no PZ yet
    _write_pz_rows(storage, [_pz_row("EJL/T-1")])

    r = client.post(f"/api/v1/proforma/preview/{BATCH}/{CLIENT}", headers=_auth())
    body = r.json()

    assert body["ready"] is False
    reasons = body.get("blocking_reasons", [])
    assert any("warehouse PZ not yet created" in reason for reason in reasons), (
        f"Expected 'warehouse PZ not yet created' in blocking_reasons, got: {reasons}"
    )


def test_blocked_with_unresolved_goods(client, storage):
    """
    PZ doc exists; pz_rows.json contains a code (EJL/T-2) that is NOT in
    wfirma_products → blocking_reasons must mention 'unresolved in wfirma_products'
    and include the code.
    """
    _seed_happy_path(storage)
    _write_audit(storage, pz_doc_id="183167843")   # PZ exists
    _write_pz_rows(storage, [
        _pz_row("EJL/T-1"),          # resolved (seeded in _seed_happy_path)
        _pz_row("EJL/T-2", 200.0),   # NOT in wfirma_products
    ])

    r = client.post(f"/api/v1/proforma/preview/{BATCH}/{CLIENT}", headers=_auth())
    body = r.json()

    assert body["ready"] is False
    reasons = body.get("blocking_reasons", [])
    assert any("unresolved in wfirma_products" in reason for reason in reasons), (
        f"Expected unresolved reason in blocking_reasons, got: {reasons}"
    )
    assert any("EJL/T-2" in reason for reason in reasons), (
        f"Expected code name EJL/T-2 in blocking_reasons, got: {reasons}"
    )


def test_blocked_with_price_conflicts(client, storage):
    """
    PZ doc exists; all codes resolved; but EJL/T-1 appears with two different
    unit_netto_pln values → blocking_reasons must mention 'price conflicts in pz_rows'.
    """
    _seed_happy_path(storage)
    _write_audit(storage, pz_doc_id="183167843")
    _write_pz_rows(storage, [
        _pz_row("EJL/T-1", 100.0),   # same code, price A
        _pz_row("EJL/T-1", 200.0),   # same code, price B — conflict!
    ])

    r = client.post(f"/api/v1/proforma/preview/{BATCH}/{CLIENT}", headers=_auth())
    body = r.json()

    assert body["ready"] is False
    reasons = body.get("blocking_reasons", [])
    assert any("price conflicts in pz_rows" in reason for reason in reasons), (
        f"Expected price-conflict reason in blocking_reasons, got: {reasons}"
    )


def test_allowed_after_pz_exists_all_resolved(client, storage):
    """
    PZ doc exists, all product_codes resolved, no price conflicts →
    no warehouse-related blocking reason. Preview should be ready=True
    once non-warehouse gates also pass.
    """
    _seed_happy_path(storage)
    _write_audit(storage, pz_doc_id="183167843")
    _write_pz_rows(storage, [_pz_row("EJL/T-1", 100.0)])   # resolved, single price

    r = client.post(f"/api/v1/proforma/preview/{BATCH}/{CLIENT}", headers=_auth())
    body = r.json()

    reasons = body.get("blocking_reasons", [])
    warehouse_reasons = [
        reason for reason in reasons
        if any(kw in reason for kw in (
            "warehouse PZ not yet created",
            "unresolved in wfirma_products",
            "price conflicts in pz_rows",
        ))
    ]
    assert warehouse_reasons == [], (
        f"Expected no warehouse blocking reasons, got: {warehouse_reasons}"
    )
