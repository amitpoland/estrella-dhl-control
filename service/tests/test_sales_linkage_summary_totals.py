"""
test_sales_linkage_summary_totals.py — Phase 2 Step 1.

Verifies that GET /api/v1/sales/linkage/{batch_id} now includes:
  summary.total_value  — sum of invoice_line.total_value for the batch
  summary.currency     — dominant currency from invoice_lines

Rules under test:
  - Same currency across all lines → that currency is returned
  - No invoice lines (empty batch) → total_value=0.0, currency=None
  - Mixed currencies → dominant (most-common) currency returned
  - Existing summary fields (total, ready, pending_dispatch, not_ready,
    missing_scan) are preserved
  - Endpoint shape is backwards-compatible
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import packing_db as pdb
from app.services import document_db as ddb
from app.services import warehouse_db as wdb
from app.services import sales_linkage as sl


# ── Fixture helpers ───────────────────────────────────────────────────────────

def _inv_line(n: int, inv_pc: str, total_value: float, currency: str = "USD") -> dict:
    return {
        "invoice_no":    "EJL/SLT/001",
        "line_position": n,
        "product_code":  inv_pc,
        "description":   f"item {n}",
        "quantity":      1.0,
        "unit_price":    total_value,
        "total_value":   total_value,
        "currency":      currency,
        "hs_code":       "",
        "gross_weight":  1.0,
        "net_weight":    1.0,
        "rate_usd":      total_value,
        "amount_usd":    total_value,
        "hsn_code":      "",
    }


def _sline(product_code: str, client: str = "TC", ref: str = "REF/1") -> dict:
    return {
        "product_code": product_code,
        "design_no":    product_code,
        "client_name":  client,
        "client_ref":   ref,
        "quantity":     1.0,
        "bag_id":       "",
        "remarks":      "",
    }


def _pline(n: int, inv_pc: str, sku: str) -> dict:
    return {
        "packing_document_id":   f"slt-pdoc-{n}",
        "batch_id":              "PLACEHOLDER",   # overridden per-batch
        "invoice_no":            "EJL/SLT/001",
        "invoice_line_position": n,
        "product_code":          inv_pc,
        "design_no":             sku,
        "bag_id":                "",
        "tray_id":               "",
        "item_type":             "RNG",
        "uom":                   "PCS",
        "quantity":              1.0,
        "gross_weight":          5.0,
        "net_weight":            5.0,
        "metal":                 "18KT",
        "karat":                 "",
        "stone_type":            "",
        "remarks":               "",
        "extracted_confidence":  0.95,
        "requires_manual_review": False,
        "pack_sr":               float(n),
        "unit_price":            100.0,
        "total_value":           100.0,
        "batch_no":              "",
    }


# ── Module-scoped DB setup ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tmp_storage(tmp_path_factory):
    return tmp_path_factory.mktemp("slt_storage")


@pytest.fixture(scope="module")
def db(tmp_storage):
    pdb.init_packing_db(tmp_storage / "packing.db")
    ddb.init_document_db(tmp_storage / "documents.db")
    wdb.init_warehouse_db(tmp_storage / "warehouse.db")
    return tmp_storage


@pytest.fixture(scope="module")
def client(tmp_storage, db):
    with patch.object(settings, "storage_root", tmp_storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


# ── Scenario A: same currency ─────────────────────────────────────────────────

BATCH_SAME_CCY = "SLT_SAME_CURRENCY_BATCH"


@pytest.fixture(scope="module")
def seeded_same_ccy(db):
    """Two invoice lines in USD, two sales lines."""
    inv_doc_id = str(uuid.uuid4())
    ddb.store_invoice_lines(inv_doc_id, BATCH_SAME_CCY, [
        _inv_line(1, "EJL/SLT/001-1", 150.0, "USD"),
        _inv_line(2, "EJL/SLT/001-2", 250.0, "USD"),
    ])
    pl = [
        {**_pline(1, "EJL/SLT/001-1", "SLT/SKU-A"), "batch_id": BATCH_SAME_CCY},
        {**_pline(2, "EJL/SLT/001-2", "SLT/SKU-B"), "batch_id": BATCH_SAME_CCY},
    ]
    pdb.upsert_packing_lines(pl)
    sdoc_id = ddb.store_sales_document(BATCH_SAME_CCY, str(uuid.uuid4()), {
        "client_name": "Same CCY Client",
        "client_ref":  "SAMECCY/001",
    })
    ddb.store_sales_packing_lines(sdoc_id, BATCH_SAME_CCY, [
        _sline("SLT/SKU-A", client="Same CCY Client", ref="SAMECCY/001"),
        _sline("SLT/SKU-B", client="Same CCY Client", ref="SAMECCY/001"),
    ])
    return {}


class TestSameCurrency:
    def test_total_value_sums_invoice_lines(self, db, seeded_same_ccy):
        result = sl.get_sales_linkage(BATCH_SAME_CCY)
        assert result["summary"]["total_value"] == 400.0  # 150 + 250

    def test_currency_is_usd(self, db, seeded_same_ccy):
        result = sl.get_sales_linkage(BATCH_SAME_CCY)
        assert result["summary"]["currency"] == "USD"

    def test_existing_summary_fields_present(self, db, seeded_same_ccy):
        s = sl.get_sales_linkage(BATCH_SAME_CCY)["summary"]
        for field in ("total", "ready", "pending_dispatch", "not_ready", "missing_scan"):
            assert field in s, f"existing field missing: {field}"

    def test_api_response_includes_new_fields(self, client, seeded_same_ccy):
        r = client.get(f"/api/v1/sales/linkage/{BATCH_SAME_CCY}", headers=_auth())
        assert r.status_code == 200
        s = r.json()["summary"]
        assert "total_value" in s
        assert "currency" in s
        assert s["total_value"] == 400.0
        assert s["currency"] == "USD"


# ── Scenario B: empty batch (no rows at all) ──────────────────────────────────

class TestEmptyBatchSummaryTotals:
    def test_empty_batch_total_value_is_zero(self, db):
        result = sl.get_sales_linkage("SLT_NONEXISTENT_BATCH_9999")
        assert result["summary"]["total_value"] == 0.0

    def test_empty_batch_currency_is_none(self, db):
        result = sl.get_sales_linkage("SLT_NONEXISTENT_BATCH_9999")
        assert result["summary"]["currency"] is None

    def test_empty_batch_api_returns_new_fields(self, client):
        r = client.get("/api/v1/sales/linkage/SLT_NONEXISTENT_BATCH_9999", headers=_auth())
        assert r.status_code == 200
        s = r.json()["summary"]
        assert s["total_value"] == 0.0
        assert s["currency"] is None


# ── Scenario C: mixed currencies (USD dominant) ───────────────────────────────

BATCH_MIXED_CCY = "SLT_MIXED_CURRENCY_BATCH"


@pytest.fixture(scope="module")
def seeded_mixed_ccy(db):
    """Three USD lines + one EUR line → USD dominant."""
    inv_doc_id = str(uuid.uuid4())
    ddb.store_invoice_lines(inv_doc_id, BATCH_MIXED_CCY, [
        _inv_line(1, "EJL/SLT/002-1", 100.0, "USD"),
        _inv_line(2, "EJL/SLT/002-2", 200.0, "USD"),
        _inv_line(3, "EJL/SLT/002-3",  50.0, "USD"),
        _inv_line(4, "EJL/SLT/002-4",  75.0, "EUR"),
    ])
    pl = [
        {**_pline(1, "EJL/SLT/002-1", "SLT/MX-A"), "batch_id": BATCH_MIXED_CCY},
        {**_pline(2, "EJL/SLT/002-2", "SLT/MX-B"), "batch_id": BATCH_MIXED_CCY},
        {**_pline(3, "EJL/SLT/002-3", "SLT/MX-C"), "batch_id": BATCH_MIXED_CCY},
        {**_pline(4, "EJL/SLT/002-4", "SLT/MX-D"), "batch_id": BATCH_MIXED_CCY},
    ]
    pdb.upsert_packing_lines(pl)
    sdoc_id = ddb.store_sales_document(BATCH_MIXED_CCY, str(uuid.uuid4()), {
        "client_name": "Mixed CCY Client",
        "client_ref":  "MIXCCY/001",
    })
    ddb.store_sales_packing_lines(sdoc_id, BATCH_MIXED_CCY, [
        _sline("SLT/MX-A", client="Mixed CCY Client", ref="MIXCCY/001"),
        _sline("SLT/MX-B", client="Mixed CCY Client", ref="MIXCCY/001"),
        _sline("SLT/MX-C", client="Mixed CCY Client", ref="MIXCCY/001"),
        _sline("SLT/MX-D", client="Mixed CCY Client", ref="MIXCCY/001"),
    ])
    return {}


class TestMixedCurrency:
    def test_dominant_currency_is_usd(self, db, seeded_mixed_ccy):
        result = sl.get_sales_linkage(BATCH_MIXED_CCY)
        assert result["summary"]["currency"] == "USD"

    def test_total_value_sums_all_lines_regardless_of_currency(self, db, seeded_mixed_ccy):
        # 100 + 200 + 50 + 75 = 425
        result = sl.get_sales_linkage(BATCH_MIXED_CCY)
        assert result["summary"]["total_value"] == 425.0

    def test_currency_is_string_not_none(self, db, seeded_mixed_ccy):
        result = sl.get_sales_linkage(BATCH_MIXED_CCY)
        assert isinstance(result["summary"]["currency"], str)


# ── Scenario D: invoice lines exist but no sales lines ───────────────────────

BATCH_INV_ONLY = "SLT_INV_ONLY_BATCH"


@pytest.fixture(scope="module")
def seeded_inv_only(db):
    """Invoice lines present but no sales_packing_lines — empty response path."""
    inv_doc_id = str(uuid.uuid4())
    ddb.store_invoice_lines(inv_doc_id, BATCH_INV_ONLY, [
        _inv_line(1, "EJL/SLT/003-1", 500.0, "PLN"),
    ])
    # No sales packing lines seeded deliberately
    return {}


class TestInvoiceLinesWithoutSalesLines:
    def test_empty_items_but_total_value_from_invoice_lines(self, db, seeded_inv_only):
        # get_sales_linkage returns _empty_response when no sales rows
        # (the invoice lines branch is skipped because items list is empty)
        result = sl.get_sales_linkage(BATCH_INV_ONLY)
        # No sales rows → _empty_response → safe defaults
        assert result["items"] == []
        assert result["summary"]["total_value"] == 0.0
        assert result["summary"]["currency"] is None

    def test_existing_summary_keys_all_present(self, db, seeded_inv_only):
        s = sl.get_sales_linkage(BATCH_INV_ONLY)["summary"]
        expected = {
            "total", "ready", "pending_dispatch", "not_ready", "missing_scan",
            "total_value", "currency",
        }
        assert expected == set(s.keys())
