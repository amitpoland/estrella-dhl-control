"""
test_sales_linkage.py — Sales linkage layer: warehouse state + audit gate.

Covers:
  1. Item status classification  — ready / pending_dispatch / not_ready / missing_scan
  2. Match key:  sales.product_code → packing.design_no  (SKU alignment)
  3. Normalisation — case/spacing differences still match
  4. Duplicate design_nos — best-status wins across multiple packing lines
  5. Audit gate — preview never blocks; final blocks on gaps; override clears block
  6. Blocking reasons populated correctly
  7. Summary math — total / per-status counts
  8. API endpoint shape and status codes
  9. Empty batch returns safe empty structure
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
from app.services import sales_linkage as sl


BATCH = "SALES_LINK_TEST_BATCH_002"
NOW   = "2026-01-10T12:00:00+00:00"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tmp_storage(tmp_path_factory):
    return tmp_path_factory.mktemp("sales_link2_storage")


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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pline(n: int, product_code: str, design_no: str, **kwargs) -> dict:
    """Minimal packing line — product_code is the INVOICE LINE REF, design_no is the SKU."""
    base = {
        "packing_document_id":   f"sltest-doc-{n}",
        "batch_id":              BATCH,
        "invoice_no":            "EJL/26-27/SL",
        "invoice_line_position": n,
        "product_code":          product_code,   # e.g. EJL/26-27/015-6
        "design_no":             design_no,       # e.g. CSTR01864
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
    base.update(kwargs)
    return base


def _sline(product_code: str, design_no: str, client: str = "TestClient",
           ref: str = "PROF 1/2026", qty: float = 1.0) -> dict:
    """Minimal sales_packing_line — product_code is the SKU (= packing.design_no)."""
    return {
        "product_code": product_code,
        "design_no":    design_no,
        "client_name":  client,
        "client_ref":   ref,
        "quantity":     qty,
        "bag_id":       "",
        "remarks":      "",
    }


# ── Seed ─────────────────────────────────────────────────────────────────────
#
# Packing line layout (invoice-ref, sku):
#   (EJL/26-27/015-1, SKU_DISP)   → RECEIVE + DISPATCH      → ready
#   (EJL/26-27/015-2, SKU_RECV)   → RECEIVE only             → not_ready
#   (EJL/26-27/015-3, SKU_PACK)   → packed (direct insert)   → pending_dispatch
#   (EJL/26-27/015-4, SKU_NONE)   → never scanned            → missing_scan
#   (EJL/26-27/015-5a, SKU_DUP)   → RECEIVE only             → not_ready    \
#   (EJL/26-27/015-5b, SKU_DUP)   → DISPATCH                 → ready        / → best=ready
#   (EJL/26-27/015-6, sku_lower)  → DISPATCH (SKU has mixed case)
#
# Sales rows use bare SKU as product_code (= packing.design_no):
#   SKU_DISP, SKU_RECV, SKU_PACK, SKU_NONE, SKU_DUP, sku_lower (tests normalisation)

SKU_DISP  = "SL/SKU-DISPATCHED"
SKU_RECV  = "SL/SKU-RECEIVED"
SKU_PACK  = "SL/SKU-PACKED"
SKU_NONE  = "SL/SKU-NEVERSCANNED"
SKU_DUP   = "SL/SKU-DUPLICATE"
SKU_LOWER = "sl/sku-lowercase"   # sales sends lowercase, packing stores uppercase


@pytest.fixture(scope="module")
def seeded(db, client):
    # ── packing lines (product_code = invoice ref, design_no = SKU) ──────────
    plines = [
        _pline(1, "EJL/26-27/015-1",  SKU_DISP),
        _pline(2, "EJL/26-27/015-2",  SKU_RECV),
        _pline(3, "EJL/26-27/015-3",  SKU_PACK),
        _pline(4, "EJL/26-27/015-4",  SKU_NONE),
        _pline(5, "EJL/26-27/015-5a", SKU_DUP, pack_sr=5.0),
        _pline(6, "EJL/26-27/015-5b", SKU_DUP, pack_sr=6.0),
        _pline(7, "EJL/26-27/015-6",  SKU_LOWER.upper()),  # stored uppercase
    ]
    pdb.upsert_packing_lines(plines)

    sc = {i: wdb.scan_code_for_packing_line(p) for i, p in enumerate(plines, start=1)}

    # line 1: RECEIVE → DISPATCH
    client.post("/api/v1/warehouse/scan",
                json={"scan_code": sc[1], "action": "RECEIVE", "to_location": "MAIN/RECV-01"},
                headers=_auth())
    client.post("/api/v1/warehouse/scan",
                json={"scan_code": sc[1], "action": "DISPATCH", "to_location": "DHL-OUT"},
                headers=_auth())

    # line 2: RECEIVE only
    client.post("/api/v1/warehouse/scan",
                json={"scan_code": sc[2], "action": "RECEIVE", "to_location": "MAIN/RECV-02"},
                headers=_auth())

    with sqlite3.connect(str(wdb._db_path)) as con:
        # line 3: packed status (pending_dispatch)
        con.execute(
            """INSERT INTO inventory_current_location
               (id, batch_id, product_code, design_no, bag_id, pack_sr,
                scan_code, current_location, current_status, updated_at, updated_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), BATCH, "EJL/26-27/015-3", SKU_PACK, "", 3.0,
             sc[3], "PACK-STATION", "packed", NOW, "test"),
        )
        # line 4: never scanned — no row
        # line 5 (SKU_DUP, first copy): RECEIVE only → not_ready
        con.execute(
            """INSERT INTO inventory_current_location
               (id, batch_id, product_code, design_no, bag_id, pack_sr,
                scan_code, current_location, current_status, updated_at, updated_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), BATCH, "EJL/26-27/015-5a", SKU_DUP, "", 5.0,
             sc[5], "MAIN/RECV-03", "in_warehouse", NOW, "test"),
        )
        # line 6 (SKU_DUP, second copy): DISPATCH → ready
        con.execute(
            """INSERT INTO inventory_current_location
               (id, batch_id, product_code, design_no, bag_id, pack_sr,
                scan_code, current_location, current_status, updated_at, updated_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), BATCH, "EJL/26-27/015-5b", SKU_DUP, "", 6.0,
             sc[6], "DHL-OUT", "dispatched", NOW, "test"),
        )
        # line 7 (lowercase SKU): DISPATCH
        con.execute(
            """INSERT INTO inventory_current_location
               (id, batch_id, product_code, design_no, bag_id, pack_sr,
                scan_code, current_location, current_status, updated_at, updated_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), BATCH, "EJL/26-27/015-6", SKU_LOWER.upper(), "", 7.0,
             sc[7], "DHL-OUT", "dispatched", NOW, "test"),
        )

    # ── sales_packing_lines (product_code = bare SKU) ─────────────────────────
    for i, (sku, dn) in enumerate([
        (SKU_DISP,        SKU_DISP),
        (SKU_RECV,        SKU_RECV),
        (SKU_PACK,        SKU_PACK),
        (SKU_NONE,        SKU_NONE),
        (SKU_DUP,         SKU_DUP),
        (SKU_LOWER,       SKU_LOWER),   # lowercase — normalisation test
    ], start=1):
        ddb.store_sales_packing_lines(
            sales_document_id=f"sdoc-sl-{i}",
            batch_id=BATCH,
            lines=[_sline(product_code=sku, design_no=dn)],
        )

    return {"sc": sc}


# ── 1. Match key: sales.product_code → packing.design_no ─────────────────────

class TestMatchKey:
    def test_dispatched_sku_links_to_ready(self, db, seeded):
        result = sl.get_sales_linkage(BATCH)
        items  = {i["product_code"]: i for i in result["items"]}
        assert items[SKU_DISP]["warehouse_status"] == "ready"

    def test_received_sku_links_to_not_ready(self, db, seeded):
        result = sl.get_sales_linkage(BATCH)
        items  = {i["product_code"]: i for i in result["items"]}
        assert items[SKU_RECV]["warehouse_status"] == "not_ready"

    def test_packed_sku_links_to_pending_dispatch(self, db, seeded):
        result = sl.get_sales_linkage(BATCH)
        items  = {i["product_code"]: i for i in result["items"]}
        assert items[SKU_PACK]["warehouse_status"] == "pending_dispatch"

    def test_unscanned_sku_is_missing_scan(self, db, seeded):
        result = sl.get_sales_linkage(BATCH)
        items  = {i["product_code"]: i for i in result["items"]}
        assert items[SKU_NONE]["warehouse_status"] == "missing_scan"

    def test_ready_item_has_matched_scan_codes(self, db, seeded):
        result = sl.get_sales_linkage(BATCH)
        items  = {i["product_code"]: i for i in result["items"]}
        assert len(items[SKU_DISP]["matched_scan_codes"]) >= 1

    def test_missing_scan_has_no_warehouse_location(self, db, seeded):
        # Packing line exists (scan_code found), but no warehouse row for it
        result = sl.get_sales_linkage(BATCH)
        items  = {i["product_code"]: i for i in result["items"]}
        item   = items[SKU_NONE]
        assert item["warehouse_status"] == "missing_scan"
        assert item.get("current_location") is None
        assert item.get("wh_status") is None


# ── 2. Normalisation ──────────────────────────────────────────────────────────

class TestNormalisation:
    def test_lowercase_sku_matches_uppercase_packing_design_no(self, db, seeded):
        # Sales row uses lowercase SKU, packing stored uppercase
        result = sl.get_sales_linkage(BATCH)
        items  = {i["product_code"]: i for i in result["items"]}
        assert SKU_LOWER in items, f"Expected {SKU_LOWER!r} in items"
        assert items[SKU_LOWER]["warehouse_status"] == "ready"

    def test_norm_function(self):
        from app.services.sales_linkage import _norm
        assert _norm("  CSTR 07596  ") == "CSTR 07596"
        assert _norm("cstr07596")       == "CSTR07596"
        assert _norm("sl/sku-lower")    == "SL/SKU-LOWER"


# ── 3. Duplicate design_no: best-status resolution ───────────────────────────

class TestDuplicateDesignNo:
    def test_dup_sku_with_one_dispatched_returns_ready(self, db, seeded):
        # SKU_DUP has two packing lines: one in_warehouse + one dispatched → best = ready
        result = sl.get_sales_linkage(BATCH)
        items  = {i["product_code"]: i for i in result["items"]}
        assert items[SKU_DUP]["warehouse_status"] == "ready"

    def test_dup_sku_has_two_matched_scan_codes(self, db, seeded):
        result = sl.get_sales_linkage(BATCH)
        items  = {i["product_code"]: i for i in result["items"]}
        assert len(items[SKU_DUP]["matched_scan_codes"]) == 2


# ── 4. Audit gate — preview ───────────────────────────────────────────────────

class TestAuditGatePreview:
    def test_preview_never_blocks(self, db, seeded):
        result = sl.get_sales_linkage(BATCH, mode="preview")
        assert result["blocked"] is False

    def test_preview_shows_audit_warnings_when_gaps_exist(self, db, seeded):
        result = sl.get_sales_linkage(BATCH, mode="preview")
        assert len(result["audit_warnings"]) > 0

    def test_preview_ready_for_invoice_false_when_missing_scans(self, db, seeded):
        result = sl.get_sales_linkage(BATCH, mode="preview")
        assert result["ready_for_invoice"] is False

    def test_preview_blocking_reasons_empty(self, db, seeded):
        result = sl.get_sales_linkage(BATCH, mode="preview")
        assert result["blocking_reasons"] == []


# ── 5. Audit gate — final ─────────────────────────────────────────────────────

class TestAuditGateFinal:
    def test_final_blocks_when_gaps_present(self, db, seeded):
        result = sl.get_sales_linkage(BATCH, mode="final")
        assert result["blocked"] is True

    def test_final_populates_blocking_reasons(self, db, seeded):
        result = sl.get_sales_linkage(BATCH, mode="final")
        assert len(result["blocking_reasons"]) > 0

    def test_final_with_override_not_blocked(self, db, seeded):
        result = sl.get_sales_linkage(BATCH, mode="final", override=True)
        assert result["blocked"] is False

    def test_final_with_override_still_shows_warnings(self, db, seeded):
        result = sl.get_sales_linkage(BATCH, mode="final", override=True)
        assert len(result["audit_warnings"]) > 0


# ── 6. Summary math ───────────────────────────────────────────────────────────

class TestSummaryMath:
    def test_total_equals_sales_rows(self, db, seeded):
        result = sl.get_sales_linkage(BATCH)
        assert result["summary"]["total"] == 6

    def test_ready_count(self, db, seeded):
        result = sl.get_sales_linkage(BATCH)
        # SKU_DISP (dispatched) + SKU_DUP (best=dispatched) + SKU_LOWER (dispatched)
        assert result["summary"]["ready"] == 3

    def test_pending_dispatch_count(self, db, seeded):
        result = sl.get_sales_linkage(BATCH)
        # SKU_PACK (packed)
        assert result["summary"]["pending_dispatch"] == 1

    def test_not_ready_count(self, db, seeded):
        result = sl.get_sales_linkage(BATCH)
        # SKU_RECV (received only)
        assert result["summary"]["not_ready"] == 1

    def test_missing_scan_count(self, db, seeded):
        result = sl.get_sales_linkage(BATCH)
        # SKU_NONE (never scanned)
        assert result["summary"]["missing_scan"] == 1

    def test_counts_sum_to_total(self, db, seeded):
        s = sl.get_sales_linkage(BATCH)["summary"]
        assert (
            s["ready"] + s["pending_dispatch"] + s["not_ready"] + s["missing_scan"]
        ) == s["total"]


# ── 7. API endpoint ───────────────────────────────────────────────────────────

class TestAPIEndpoint:
    def test_preview_returns_200(self, client, seeded):
        r = client.get(f"/api/v1/sales/linkage/{BATCH}", headers=_auth())
        assert r.status_code == 200

    def test_final_with_gaps_returns_409(self, client, seeded):
        r = client.get(f"/api/v1/sales/linkage/{BATCH}?mode=final", headers=_auth())
        assert r.status_code == 409

    def test_final_with_override_returns_200(self, client, seeded):
        r = client.get(
            f"/api/v1/sales/linkage/{BATCH}?mode=final&override=true",
            headers=_auth()
        )
        assert r.status_code == 200

    def test_response_shape(self, client, seeded):
        r = client.get(f"/api/v1/sales/linkage/{BATCH}", headers=_auth())
        body = r.json()
        for key in ("batch_id", "mode", "ready_for_invoice", "blocked",
                    "blocking_reasons", "audit_warnings", "items", "summary"):
            assert key in body, f"response missing key: {key}"

    def test_summary_has_all_fields(self, client, seeded):
        r = client.get(f"/api/v1/sales/linkage/{BATCH}", headers=_auth())
        s = r.json()["summary"]
        for f in ("total", "ready", "pending_dispatch", "not_ready", "missing_scan"):
            assert f in s

    def test_item_has_matched_scan_codes_field(self, client, seeded):
        r = client.get(f"/api/v1/sales/linkage/{BATCH}", headers=_auth())
        for item in r.json()["items"]:
            assert "matched_scan_codes" in item

    def test_invalid_mode_returns_422(self, client, seeded):
        r = client.get(
            f"/api/v1/sales/linkage/{BATCH}?mode=bogus",
            headers=_auth()
        )
        assert r.status_code == 422

    def test_route_exists(self, client, seeded):
        r = client.get(f"/api/v1/sales/linkage/{BATCH}")
        assert r.status_code != 404


# ── 8. Empty batch ────────────────────────────────────────────────────────────

class TestEmptyBatch:
    def test_unknown_batch_returns_empty_structure(self, db):
        result = sl.get_sales_linkage("NO_SUCH_BATCH_XYZ")
        assert result["summary"]["total"] == 0
        assert result["items"] == []

    def test_empty_batch_not_ready(self, db):
        result = sl.get_sales_linkage("NO_SUCH_BATCH_XYZ")
        assert result["ready_for_invoice"] is False

    def test_empty_batch_api_200(self, client, db):
        r = client.get("/api/v1/sales/linkage/NO_SUCH_BATCH_XYZ", headers=_auth())
        assert r.status_code == 200
