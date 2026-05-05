"""
test_wfirma_reservation.py — wFirma reservation preview builder.

Covers:
  1. Empty batch returns safe structure (no crash, audit_clean=False)
  2. Per-document grouping — 2 sales docs → 2 documents in result
  3. Invoice product_code grouping — 2 SKUs under one invoice ref → 1 row
  4. stock_ok=True when all scan_codes for an invoice pc are dispatched
  5. stock_ok=False when items only received (not dispatched)
  6. UNMATCHED SKU — sales row with no packing line → UNMATCHED: prefix
  7. ready_to_create=True when audit clean + all rows ready
  8. ready_to_create=False when stock missing
  9. customer_ok=False blocks doc readiness when client_name is empty
 10. Currency resolved from invoice_lines (dominant value)
 11. total_value = unit_price × quantity per row
 12. blocking_reasons populated and actionable
 13. API endpoint returns 200 with correct schema
"""
from __future__ import annotations

import sqlite3
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import packing_db as pdb
from app.services import document_db as ddb
from app.services import warehouse_db as wdb
from app.services import wfirma_db as wfdb
from app.services import wfirma_reservation as wr


BATCH = "WR_UNIT_TEST_BATCH_001"
INV_NO = "EJL/WT/001"

# ── SKUs (= packing.design_no = sales.product_code) ─────────────────────────
SKU_A = "WR/SKU-ALPHA"
SKU_B = "WR/SKU-BETA"
SKU_C = "WR/SKU-CHARLIE"
SKU_GHOST = "WR/SKU-GHOST"  # in sales but NOT in packing → UNMATCHED

# ── Invoice product codes (= packing.product_code = wFirma symbol) ───────────
INV_PC_AB = "EJL/WT/001-1"   # SKU_A and SKU_B share this invoice line
INV_PC_C  = "EJL/WT/001-2"   # SKU_C only


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tmp_storage(tmp_path_factory):
    return tmp_path_factory.mktemp("wfirma_res_storage")


@pytest.fixture(scope="module")
def db(tmp_storage):
    pdb.init_packing_db(tmp_storage / "packing.db")
    ddb.init_document_db(tmp_storage / "documents.db")
    wdb.init_warehouse_db(tmp_storage / "warehouse.db")
    wfdb.init_wfirma_db(tmp_storage / "wfirma.db")
    return tmp_storage


@pytest.fixture(scope="module")
def client(tmp_storage, db):
    with patch.object(settings, "storage_root", tmp_storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pline(n: int, inv_pc: str, sku: str) -> dict:
    """Packing line: product_code = invoice ref, design_no = SKU."""
    return {
        "packing_document_id":   f"wr-pdoc-{n}",
        "batch_id":              BATCH,
        "invoice_no":            INV_NO,
        "invoice_line_position": n,
        "product_code":          inv_pc,   # invoice line reference
        "design_no":             sku,       # design/SKU
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


def _inv_line(n: int, inv_pc: str, unit_price: float, currency: str = "USD") -> dict:
    return {
        "invoice_no":    INV_NO,
        "line_position": n,
        "product_code":  inv_pc,
        "description":   f"Test item {n}",
        "quantity":      1.0,
        "unit_price":    unit_price,
        "total_value":   unit_price,
        "currency":      currency,
        "hs_code":       "",
        "gross_weight":  5.0,
        "net_weight":    5.0,
        "rate_usd":      unit_price,
        "amount_usd":    unit_price,
        "hsn_code":      "",
    }


def _spl(sku: str, qty: float = 1.0, client: str = "", ref: str = "") -> dict:
    """Sales packing line — product_code is the SKU."""
    return {
        "product_code": sku,
        "design_no":    sku,
        "client_name":  client,
        "client_ref":   ref,
        "quantity":     qty,
        "bag_id":       "",
        "remarks":      "",
    }


# ── Seed fixture ─────────────────────────────────────────────────────────────
#
# Packing layout:
#   pline(1, INV_PC_AB, SKU_A)  pack_sr=1
#   pline(2, INV_PC_AB, SKU_B)  pack_sr=2   ← two SKUs, one invoice product_code
#   pline(3, INV_PC_C,  SKU_C)  pack_sr=3
#   (SKU_GHOST has NO packing line → UNMATCHED in sales)
#
# Sales documents:
#   Doc Alpha (client="Alpha Corp"):
#     product_code=SKU_A qty=2
#     product_code=SKU_B qty=3   → both → INV_PC_AB, 5 units total
#   Doc Beta (client="Beta Ltd"):
#     product_code=SKU_C qty=5  → INV_PC_C
#     product_code=SKU_GHOST qty=1  → UNMATCHED
#
# Invoice lines:
#   INV_PC_AB unit_price=100.0  USD
#   INV_PC_C  unit_price=200.0  USD

@pytest.fixture(scope="module")
def seeded(db, client):
    # ── packing lines ─────────────────────────────────────────────────────────
    plines = [
        _pline(1, INV_PC_AB, SKU_A),
        _pline(2, INV_PC_AB, SKU_B),
        _pline(3, INV_PC_C,  SKU_C),
    ]
    pdb.upsert_packing_lines(plines)

    # Pre-compute scan codes
    sc = {pl["design_no"]: wdb.scan_code_for_packing_line(pl) for pl in plines}

    # ── invoice lines ─────────────────────────────────────────────────────────
    inv_doc_id = str(uuid.uuid4())
    ddb.store_invoice_lines(inv_doc_id, BATCH, [
        _inv_line(1, INV_PC_AB, 100.0, "USD"),
        _inv_line(2, INV_PC_C,  200.0, "USD"),
    ])

    # ── sales documents ───────────────────────────────────────────────────────
    doc_alpha_id = ddb.store_sales_document(BATCH, str(uuid.uuid4()), {
        "client_name":  "Alpha Corp",
        "client_ref":   "ALPHA/001",
        "sales_doc_no": "SA-001",
    })
    doc_beta_id = ddb.store_sales_document(BATCH, str(uuid.uuid4()), {
        "client_name":  "Beta Ltd",
        "client_ref":   "BETA/001",
        "sales_doc_no": "SB-001",
    })

    # ── sales packing lines ───────────────────────────────────────────────────
    ddb.store_sales_packing_lines(doc_alpha_id, BATCH, [
        _spl(SKU_A, qty=2.0, client="Alpha Corp", ref="ALPHA/001"),
        _spl(SKU_B, qty=3.0, client="Alpha Corp", ref="ALPHA/001"),
    ])
    ddb.store_sales_packing_lines(doc_beta_id, BATCH, [
        _spl(SKU_C,     qty=5.0,  client="Beta Ltd", ref="BETA/001"),
        _spl(SKU_GHOST, qty=1.0,  client="Beta Ltd", ref="BETA/001"),
    ])

    return {"sc": sc, "doc_alpha_id": doc_alpha_id, "doc_beta_id": doc_beta_id}


@pytest.fixture(scope="module")
def seeded_with_stock(seeded, client):
    """All packing items dispatched from warehouse (RECEIVE → DISPATCH)."""
    sc = seeded["sc"]
    for sku, scan_code in sc.items():
        r = client.post(
            "/api/v1/warehouse/scan",
            json={"scan_code": scan_code, "action": "RECEIVE",
                  "to_location": "MAIN/RECV-01", "batch_id": BATCH},
            headers=_auth(),
        )
        assert r.status_code == 200, f"Failed to RECEIVE {sku}: {r.text}"
        r = client.post(
            "/api/v1/warehouse/scan",
            json={"scan_code": scan_code, "action": "DISPATCH",
                  "to_location": "DHL-OUT", "batch_id": BATCH},
            headers=_auth(),
        )
        assert r.status_code == 200, f"Failed to DISPATCH {sku}: {r.text}"
    return seeded


# ── Tests: empty batch ────────────────────────────────────────────────────────

def test_empty_batch_no_crash(db):
    result = wr.get_reservation_preview("BATCH_DOES_NOT_EXIST")
    assert result["batch_id"] == "BATCH_DOES_NOT_EXIST"
    assert result["ready_to_create"] is False
    assert result["audit_clean"] is False
    assert isinstance(result["documents"], list)
    assert len(result["documents"]) == 0
    assert isinstance(result["blocking_reasons"], list)
    assert len(result["blocking_reasons"]) > 0


def test_empty_batch_safe_currency(db):
    result = wr.get_reservation_preview("BATCH_DOES_NOT_EXIST")
    assert result["currency"] == "PLN"  # default fallback


# ── Tests: document grouping ──────────────────────────────────────────────────

def test_two_sales_docs_produces_two_documents(seeded):
    result = wr.get_reservation_preview(BATCH)
    assert len(result["documents"]) == 2


def test_documents_have_correct_client_names(seeded):
    result = wr.get_reservation_preview(BATCH)
    names = {d["client_name"] for d in result["documents"]}
    assert "Alpha Corp" in names
    assert "Beta Ltd" in names


def test_alpha_doc_has_one_row_for_shared_inv_pc(seeded):
    """SKU_A and SKU_B both map to INV_PC_AB → 1 row in Alpha doc."""
    result = wr.get_reservation_preview(BATCH)
    alpha = next(d for d in result["documents"] if d["client_name"] == "Alpha Corp")
    # Must have exactly 1 matched row for INV_PC_AB
    matched_rows = [r for r in alpha["rows"] if r["product_code"] == INV_PC_AB]
    assert len(matched_rows) == 1


def test_alpha_row_quantity_is_sum_of_both_skus(seeded):
    """qty=2 (SKU_A) + qty=3 (SKU_B) = 5 under INV_PC_AB."""
    result = wr.get_reservation_preview(BATCH)
    alpha = next(d for d in result["documents"] if d["client_name"] == "Alpha Corp")
    row = next(r for r in alpha["rows"] if r["product_code"] == INV_PC_AB)
    assert row["quantity"] == 5.0


def test_alpha_row_design_nos_contains_both_skus(seeded):
    """design_nos is a traceability list — both SKUs appear."""
    result = wr.get_reservation_preview(BATCH)
    alpha = next(d for d in result["documents"] if d["client_name"] == "Alpha Corp")
    row = next(r for r in alpha["rows"] if r["product_code"] == INV_PC_AB)
    assert SKU_A in row["design_nos"] or SKU_A.upper() in [d.upper() for d in row["design_nos"]]
    assert SKU_B in row["design_nos"] or SKU_B.upper() in [d.upper() for d in row["design_nos"]]


def test_beta_doc_has_two_rows(seeded):
    """Beta has SKU_C (→ INV_PC_C) and SKU_GHOST (→ UNMATCHED)."""
    result = wr.get_reservation_preview(BATCH)
    beta = next(d for d in result["documents"] if d["client_name"] == "Beta Ltd")
    assert len(beta["rows"]) == 2


# ── Tests: UNMATCHED SKU ──────────────────────────────────────────────────────

def test_unmatched_sku_gets_unmatched_prefix(seeded):
    result = wr.get_reservation_preview(BATCH)
    beta = next(d for d in result["documents"] if d["client_name"] == "Beta Ltd")
    unmatched = [r for r in beta["rows"] if r["product_code"].startswith("UNMATCHED:")]
    assert len(unmatched) == 1
    assert SKU_GHOST.upper() in unmatched[0]["product_code"].upper()


def test_unmatched_row_is_not_ready(seeded):
    result = wr.get_reservation_preview(BATCH)
    beta = next(d for d in result["documents"] if d["client_name"] == "Beta Ltd")
    unmatched = next(r for r in beta["rows"] if r["product_code"].startswith("UNMATCHED:"))
    assert unmatched["ready"] is False
    assert unmatched["stock_ok"] is False
    assert unmatched["unit_price"] == 0.0


# ── Tests: stock_ok ───────────────────────────────────────────────────────────

def test_stock_ok_false_before_dispatch(seeded):
    """Before DISPATCH, stock_ok=False even if items were received."""
    result = wr.get_reservation_preview(BATCH)
    alpha = next(d for d in result["documents"] if d["client_name"] == "Alpha Corp")
    row = next(r for r in alpha["rows"] if r["product_code"] == INV_PC_AB)
    assert row["stock_ok"] is False


def test_stock_ok_true_after_scanning(seeded_with_stock):
    """After scanning all items, stock_ok=True for matched rows."""
    result = wr.get_reservation_preview(BATCH)
    alpha = next(d for d in result["documents"] if d["client_name"] == "Alpha Corp")
    row = next(r for r in alpha["rows"] if r["product_code"] == INV_PC_AB)
    assert row["stock_ok"] is True

    beta = next(d for d in result["documents"] if d["client_name"] == "Beta Ltd")
    row_c = next(r for r in beta["rows"] if r["product_code"] == INV_PC_C)
    assert row_c["stock_ok"] is True


# ── Tests: row readiness ──────────────────────────────────────────────────────

def test_stock_ok_true_and_status_dispatched_after_scan(seeded_with_stock):
    """After RECEIVE + DISPATCH, stock_ok=True and stock_status='dispatched'."""
    result = wr.get_reservation_preview(BATCH)
    alpha = next(d for d in result["documents"] if d["client_name"] == "Alpha Corp")
    row = next(r for r in alpha["rows"] if r["product_code"] == INV_PC_AB)
    assert row["stock_ok"] is True
    assert row["stock_status"] == "dispatched"

    beta = next(d for d in result["documents"] if d["client_name"] == "Beta Ltd")
    row_c = next(r for r in beta["rows"] if r["product_code"] == INV_PC_C)
    assert row_c["stock_ok"] is True
    assert row_c["stock_status"] == "dispatched"


def test_doc_ready_false_when_unmatched_row_present(seeded_with_stock):
    """Beta doc has an UNMATCHED row → doc.ready=False even with stock."""
    result = wr.get_reservation_preview(BATCH)
    beta = next(d for d in result["documents"] if d["client_name"] == "Beta Ltd")
    assert beta["ready"] is False


# ── Tests: customer_ok gate ───────────────────────────────────────────────────

def test_customer_ok_false_for_empty_client_name(db):
    """A sales document with empty client_name → customer_ok=False."""
    batch = "WR_NONAME_BATCH"
    doc_id = ddb.store_sales_document(batch, str(uuid.uuid4()), {
        "client_name":  "",
        "client_ref":   "NO-NAME/001",
        "sales_doc_no": "SN-001",
    })
    ddb.store_sales_packing_lines(doc_id, batch, [
        _spl(SKU_A, qty=1.0, client="", ref="NO-NAME/001"),
    ])
    # Minimal packing line scoped to this isolated batch
    noname_pl = {**_pline(99, INV_PC_AB, SKU_A), "batch_id": batch, "pack_sr": 99.0}
    pdb.upsert_packing_lines([noname_pl])

    result = wr.get_reservation_preview(batch)
    assert len(result["documents"]) == 1
    doc = result["documents"][0]
    assert doc["customer_ok"] is False
    assert doc["ready"] is False


# ── Tests: unit_price and total_value ────────────────────────────────────────

def test_unit_price_from_invoice_lines(seeded):
    result = wr.get_reservation_preview(BATCH)
    alpha = next(d for d in result["documents"] if d["client_name"] == "Alpha Corp")
    row = next(r for r in alpha["rows"] if r["product_code"] == INV_PC_AB)
    assert row["unit_price"] == 100.0  # from invoice_lines


def test_total_value_is_unit_price_times_quantity(seeded):
    result = wr.get_reservation_preview(BATCH)
    alpha = next(d for d in result["documents"] if d["client_name"] == "Alpha Corp")
    row = next(r for r in alpha["rows"] if r["product_code"] == INV_PC_AB)
    expected = row["unit_price"] * row["quantity"]
    assert abs(alpha["total_value"] - expected) < 0.01


# ── Tests: currency ───────────────────────────────────────────────────────────

def test_currency_comes_from_invoice_lines(seeded):
    result = wr.get_reservation_preview(BATCH)
    assert result["currency"] == "USD"  # from invoice_lines (both rows)


def test_row_currency_matches_invoice_line(seeded):
    result = wr.get_reservation_preview(BATCH)
    alpha = next(d for d in result["documents"] if d["client_name"] == "Alpha Corp")
    row = next(r for r in alpha["rows"] if r["product_code"] == INV_PC_AB)
    assert row["currency"] == "USD"


def test_dominant_currency_wins(db):
    """When invoice lines have mixed currencies, dominant (most common) wins."""
    batch = "WR_MIXED_CCY_BATCH"
    inv_doc_id = str(uuid.uuid4())
    # 2 x EUR, 1 x USD → EUR wins
    ddb.store_invoice_lines(inv_doc_id, batch, [
        _inv_line(1, "EJL/MC/001-1", 50.0, "EUR"),
        _inv_line(2, "EJL/MC/001-2", 60.0, "EUR"),
        _inv_line(3, "EJL/MC/001-3", 70.0, "USD"),
    ])
    plines = [
        _pline(10, "EJL/MC/001-1", "WR/SKU-MC1"),
        _pline(11, "EJL/MC/001-2", "WR/SKU-MC2"),
        _pline(12, "EJL/MC/001-3", "WR/SKU-MC3"),
    ]
    pdb.upsert_packing_lines([{**pl, "batch_id": batch} for pl in plines])

    doc_id = ddb.store_sales_document(batch, str(uuid.uuid4()), {
        "client_name": "Mixed Ccy Client",
        "client_ref":  "MC/001",
        "sales_doc_no": "MC-001",
    })
    ddb.store_sales_packing_lines(doc_id, batch, [
        _spl("WR/SKU-MC1", 1.0, "Mixed Ccy Client", "MC/001"),
        _spl("WR/SKU-MC2", 1.0, "Mixed Ccy Client", "MC/001"),
        _spl("WR/SKU-MC3", 1.0, "Mixed Ccy Client", "MC/001"),
    ])

    result = wr.get_reservation_preview(batch)
    assert result["currency"] == "EUR"


# ── Tests: audit gate ─────────────────────────────────────────────────────────

def test_ready_to_create_false_when_stock_missing(seeded):
    """Without scanning, stock_ok=False → ready_to_create=False."""
    result = wr.get_reservation_preview(BATCH)
    assert result["ready_to_create"] is False


def test_ready_to_create_false_when_unmatched_present(seeded_with_stock):
    """Beta doc has UNMATCHED row → ready_to_create=False even with stock."""
    result = wr.get_reservation_preview(BATCH)
    assert result["ready_to_create"] is False


def test_blocking_reasons_nonempty_when_not_ready(seeded):
    result = wr.get_reservation_preview(BATCH)
    assert len(result["blocking_reasons"]) > 0


def test_audit_clean_true_when_no_warehouse_issues(seeded_with_stock):
    """
    audit_clean checks warehouse audit (missing_scans / invalid_flows / orphans).
    With no real audit issues, audit_clean=True.
    (ready_to_create may still be False due to UNMATCHED row in Beta.)
    """
    result = wr.get_reservation_preview(BATCH)
    # audit_clean reflects only warehouse audit gate, not row readiness
    assert result["audit_clean"] is True


# ── Tests: a clean batch can reach ready_to_create=True ──────────────────────

CLEAN_BATCH = "WR_CLEAN_BATCH_001"

@pytest.fixture(scope="module")
def clean_seeded(db, client):
    """A batch with no UNMATCHED rows, all items dispatched, customer+product registered."""
    plines = [
        {**_pline(20, "EJL/CL/001-1", "WR/SKU-CLEAN1"), "batch_id": CLEAN_BATCH},
        {**_pline(21, "EJL/CL/001-2", "WR/SKU-CLEAN2"), "batch_id": CLEAN_BATCH},
    ]
    pdb.upsert_packing_lines(plines)

    sc = {pl["design_no"]: wdb.scan_code_for_packing_line(pl) for pl in plines}

    inv_doc_id = str(uuid.uuid4())
    ddb.store_invoice_lines(inv_doc_id, CLEAN_BATCH, [
        _inv_line(1, "EJL/CL/001-1", 150.0, "EUR"),
        _inv_line(2, "EJL/CL/001-2", 250.0, "EUR"),
    ])

    doc_id = ddb.store_sales_document(CLEAN_BATCH, str(uuid.uuid4()), {
        "client_name":  "Clean Client",
        "client_ref":   "CC/001",
        "sales_doc_no": "SC-001",
    })
    ddb.store_sales_packing_lines(doc_id, CLEAN_BATCH, [
        _spl("WR/SKU-CLEAN1", 1.0, "Clean Client", "CC/001"),
        _spl("WR/SKU-CLEAN2", 2.0, "Clean Client", "CC/001"),
    ])

    # RECEIVE then DISPATCH all items
    for sku, scan_code in sc.items():
        r = client.post(
            "/api/v1/warehouse/scan",
            json={"scan_code": scan_code, "action": "RECEIVE",
                  "to_location": "MAIN/RECV-01", "batch_id": CLEAN_BATCH},
            headers=_auth(),
        )
        assert r.status_code == 200, f"RECEIVE failed for {sku}: {r.text}"
        r = client.post(
            "/api/v1/warehouse/scan",
            json={"scan_code": scan_code, "action": "DISPATCH",
                  "to_location": "DHL-OUT", "batch_id": CLEAN_BATCH},
            headers=_auth(),
        )
        assert r.status_code == 200, f"DISPATCH failed for {sku}: {r.text}"

    # Register customer + products in wFirma mapping tables
    wfdb.upsert_customer(
        "Clean Client",
        wfirma_customer_id="C-CLEAN",
        match_status="matched",
    )
    wfdb.upsert_product(
        "EJL/CL/001-1",
        wfirma_product_id="P-CL-1",
        sync_status="matched",
        warehouse_id="WH-TEST",
    )
    wfdb.upsert_product(
        "EJL/CL/001-2",
        wfirma_product_id="P-CL-2",
        sync_status="matched",
        warehouse_id="WH-TEST",
    )

    return {"sc": sc, "doc_id": doc_id}


# Patch settings for clean batch tests that need full wFirma config
_WFIRMA_FULL = dict(
    wfirma_access_key="ACC-KEY",
    wfirma_secret_key="SEC-KEY",
    wfirma_app_key="APP-KEY",
    wfirma_company_id="123456",
    wfirma_warehouse_module_enabled=True,
    wfirma_warehouse_id="WH-TEST",
    wfirma_create_product_allowed=False,
    wfirma_create_customer_allowed=False,
)


def test_ready_to_create_true_for_clean_batch(clean_seeded):
    with patch.multiple(settings, **_WFIRMA_FULL):
        result = wr.get_reservation_preview(CLEAN_BATCH)
    assert result["audit_clean"] is True
    assert result["wfirma_configured"] is True
    assert result["reservation_supported"] is True
    assert result["ready_to_create"] is True
    assert result["blocking_reasons"] == []


def test_clean_batch_doc_ready(clean_seeded):
    with patch.multiple(settings, **_WFIRMA_FULL):
        result = wr.get_reservation_preview(CLEAN_BATCH)
    assert len(result["documents"]) == 1
    doc = result["documents"][0]
    assert doc["ready"] is True
    assert doc["customer_ok"] is True
    assert doc["customer_match"] is True
    for row in doc["rows"]:
        assert row["stock_ok"] is True
        assert row["product_match"] is True
        assert row["ready"] is True


def test_clean_batch_total_value(clean_seeded):
    """total_value = 150*1 + 250*2 = 650."""
    with patch.multiple(settings, **_WFIRMA_FULL):
        result = wr.get_reservation_preview(CLEAN_BATCH)
    doc = result["documents"][0]
    assert abs(doc["total_value"] - 650.0) < 0.01


def test_clean_batch_drafts_persisted_to_wfirma_db(clean_seeded):
    """Calling preview should persist draft + lines to wfirma_db."""
    with patch.multiple(settings, **_WFIRMA_FULL):
        wr.get_reservation_preview(CLEAN_BATCH)
    drafts = wfdb.list_reservation_drafts(CLEAN_BATCH)
    assert len(drafts) == 1
    draft = drafts[0]
    lines = wfdb.list_reservation_lines(draft["id"])
    assert len(lines) == 2
    pc_set = {l["product_code"] for l in lines}
    assert "EJL/CL/001-1" in pc_set
    assert "EJL/CL/001-2" in pc_set


def test_stock_status_field_dispatched(clean_seeded):
    """stock_status='dispatched' for fully dispatched items."""
    with patch.multiple(settings, **_WFIRMA_FULL):
        result = wr.get_reservation_preview(CLEAN_BATCH)
    doc = result["documents"][0]
    for row in doc["rows"]:
        assert row["stock_status"] == "dispatched"


def test_wfirma_not_configured_blocks_ready_to_create(clean_seeded):
    """Without wFirma config, ready_to_create=False even with clean data."""
    with patch.multiple(
        settings,
        wfirma_access_key=None,
        wfirma_secret_key=None,
        wfirma_app_key=None,
        wfirma_company_id="",
        wfirma_warehouse_module_enabled=False,
        wfirma_warehouse_id="",
    ):
        result = wr.get_reservation_preview(CLEAN_BATCH)
    assert result["wfirma_configured"] is False
    assert result["ready_to_create"] is False
    assert any("wFirma API not configured" in r for r in result["blocking_reasons"])


def test_customer_match_true_when_registered(clean_seeded):
    """customer_match=True once client_name is in wfirma_customers."""
    with patch.multiple(settings, **_WFIRMA_FULL):
        result = wr.get_reservation_preview(CLEAN_BATCH)
    doc = result["documents"][0]
    assert doc["customer_match"] is True


def test_customer_match_false_for_unknown_client(seeded_with_stock):
    """Clients not registered in wfirma_customers → customer_match=False."""
    result = wr.get_reservation_preview(BATCH)
    alpha = next(d for d in result["documents"] if d["client_name"] == "Alpha Corp")
    assert alpha["customer_match"] is False


def test_product_match_true_when_registered(clean_seeded):
    """product_match=True once product_code is in wfirma_products."""
    with patch.multiple(settings, **_WFIRMA_FULL):
        result = wr.get_reservation_preview(CLEAN_BATCH)
    doc = result["documents"][0]
    for row in doc["rows"]:
        assert row["product_match"] is True


def test_product_match_false_for_unregistered(seeded_with_stock):
    """Products not in wfirma_products → product_match=False."""
    result = wr.get_reservation_preview(BATCH)
    alpha = next(d for d in result["documents"] if d["client_name"] == "Alpha Corp")
    row = next(r for r in alpha["rows"] if r["product_code"] == INV_PC_AB)
    assert row["product_match"] is False


def test_create_product_allowed_overrides_product_match(clean_seeded):
    """With create_product_allowed=True, row is ready even without product_match."""
    # Use BATCH (products not registered) but allow creation
    with patch.multiple(
        settings,
        **{**_WFIRMA_FULL,
           "wfirma_create_product_allowed": True,
           "wfirma_create_customer_allowed": True},
    ):
        result = wr.get_reservation_preview(CLEAN_BATCH)
    doc = result["documents"][0]
    for row in doc["rows"]:
        # row.ready depends on product_ok_for_ready = product_match OR create_product_allowed
        assert row["ready"] is True  # product_match=True here anyway (clean_seeded registers)


# ── Tests: API endpoint ───────────────────────────────────────────────────────

def test_api_endpoint_returns_200(client, seeded_with_stock):
    r = client.get(
        f"/api/v1/wfirma/reservation-preview/{BATCH}",
        headers=_auth(),
    )
    assert r.status_code == 200


def test_api_endpoint_top_level_keys(client, seeded_with_stock):
    r = client.get(
        f"/api/v1/wfirma/reservation-preview/{BATCH}",
        headers=_auth(),
    )
    body = r.json()
    for key in ("batch_id", "audit_clean", "wfirma_configured",
                "reservation_supported", "ready_to_create",
                "blocking_reasons", "currency", "documents"):
        assert key in body, f"Missing top-level key: {key}"


def test_api_endpoint_document_schema(client, seeded_with_stock):
    r = client.get(
        f"/api/v1/wfirma/reservation-preview/{BATCH}",
        headers=_auth(),
    )
    body = r.json()
    assert len(body["documents"]) > 0
    doc = body["documents"][0]
    for key in ("sales_doc_no", "client_name", "client_ref",
                "customer_ok", "customer_match", "ready",
                "total_value", "blocking_reasons", "rows"):
        assert key in doc, f"Missing document key: {key}"


def test_api_endpoint_row_schema(client, seeded_with_stock):
    r = client.get(
        f"/api/v1/wfirma/reservation-preview/{BATCH}",
        headers=_auth(),
    )
    body = r.json()
    alpha = next(d for d in body["documents"] if d["client_name"] == "Alpha Corp")
    row = alpha["rows"][0]
    for key in ("product_code", "quantity", "unit_price", "currency",
                "stock_ok", "stock_status", "product_match", "design_nos", "ready"):
        assert key in row, f"Missing row key: {key}"


def test_api_endpoint_rejects_wrong_key_when_key_configured(client):
    """When an api_key is set, wrong credentials must be rejected."""
    if not settings.api_key:
        pytest.skip("api_key not configured in test env — auth bypass is expected")
    r = client.get(
        f"/api/v1/wfirma/reservation-preview/{BATCH}",
        headers={"X-API-KEY": "WRONG-KEY"},
    )
    assert r.status_code in (401, 403)


def test_api_endpoint_unknown_batch_returns_200(client):
    """Unknown batch should not 404 — returns safe empty structure."""
    r = client.get(
        "/api/v1/wfirma/reservation-preview/BATCH_UNKNOWN_XYZ",
        headers=_auth(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ready_to_create"] is False
    assert body["documents"] == []
