"""
test_proforma_preview_gate_separation.py — Campaign 12 (2026-05-20).

Verifies the gate separation introduced in Campaign 12:
  - wfirma_pz_doc_id is an EXPORT gate, not a preview gate
  - batch_lifecycle=DHL_TRANSIT derived from clearance_status when
    inventory_state rows are absent
  - Orphan packing lines (not linked to any sales client) retain
    their invoice provenance (invoice_no, product_code, scan_code)

Tests:
  1. test_proforma_preview_not_blocked_by_missing_pz_doc
     Preview returns HTTP 200 + can_preview=True even without wFirma PZ.
     blocking_reasons does NOT contain PZ requirement.
     export_blockers DOES contain PZ requirement.

  2. test_proforma_create_blocked_by_missing_pz_doc
     Create endpoint returns blocked when export_blockers non-empty
     (wFirma PZ not yet created).

  3. test_inventory_state_derives_transit_from_tracking
     When inventory_state rows = 0 AND clearance_status = "dsk_generated",
     _derive_batch_lifecycle returns "DHL_TRANSIT" and stock_status for
     lines with scan_codes returns "dhl_transit" (eligible for preview).

  4. test_orphan_packing_line_retains_invoice_provenance
     A packing_lines row with invoice_no, product_code, scan_code that
     has no corresponding sales_packing_lines client assignment retains
     all original fields intact in the DB (orphan provenance preserved).
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
from app.services import inventory_state_engine as ise


BATCH  = "BATCH_GS_TEST"
CLIENT = "Diamond Point"


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _vat_cache():
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


def _write_audit(storage, *, pz_doc_id: str = "", clearance_status: str = ""):
    bd = _batch_dir(storage)
    audit = {
        "batch_id": BATCH,
        "wfirma_export": {
            "wfirma_pz_doc_id": pz_doc_id,
        },
        "clearance_status": clearance_status,
    }
    (bd / "audit.json").write_text(json.dumps(audit))


def _write_pz_rows(storage, rows):
    bd = _batch_dir(storage)
    (bd / "pz_rows.json").write_text(json.dumps(rows))


def _pz_row(code: str, price: float = 100.0) -> dict:
    return {
        "product_code":   code,
        "unit_netto_pln": price,
        "invoice_no":     "EJL/GS",
        "description_en": "Gate separation test item",
        "quantity":       1,
        "total_usd":      50.0,
    }


def _seed_sales_client(storage, *, scan_code: str = "SC-GS-001"):
    """Seed minimum data for CLIENT with one product/design line."""
    pdb.upsert_packing_lines([{
        "batch_id":               BATCH,
        "invoice_no":             "EJL/GS",
        "invoice_line_position":  1,
        "product_code":           "EJL/GS-1",
        "design_no":              "GS001",
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
        "scan_code":              scan_code,
    }])

    sd = ddb.store_sales_document(
        batch_id=BATCH,
        document_id=str(uuid.uuid4()),
        data={"client_name": CLIENT, "client_ref": "GS-REF", "sales_doc_no": "SO-GS"},
    )
    ddb.store_sales_packing_lines(sd, BATCH, [{
        "client_name":  CLIENT,
        "client_ref":   "GS-REF",
        "product_code": "GS001",
        "design_no":    "GS001",
        "bag_id":       "",
        "quantity":     1.0,
        "unit_price":   150.0,
        "currency":     "EUR",
        "remarks":      "",
    }])

    wfdb.upsert_product(
        product_code="EJL/GS-1",
        wfirma_product_id="99",
        sync_status="matched",
    )
    wfdb.upsert_customer(
        client_name=CLIENT,
        wfirma_customer_id="42",
        country="NL",
        vat_id="NL90484280B01",
        match_status="matched",
    )


# ── Test 1 ────────────────────────────────────────────────────────────────────

def test_proforma_preview_not_blocked_by_missing_pz_doc(client, storage):
    """
    Gate separation: wfirma_pz_doc_id is an EXPORT gate, not a preview gate.

    When wfirma_pz_doc_id is absent:
    - Preview endpoint returns HTTP 200 (not 422)
    - can_preview = True (lines exist, data can be shown)
    - export_blockers carries "proforma export requires wFirma PZ"
    - blocking_reasons does NOT contain the PZ requirement
    - batch_lifecycle is present in the response
    """
    _seed_sales_client(storage)
    _write_audit(storage, pz_doc_id="")   # no PZ yet
    _write_pz_rows(storage, [_pz_row("EJL/GS-1")])

    r = client.post(f"/api/v1/proforma/preview/{BATCH}/{CLIENT}", headers=_auth())
    assert r.status_code == 200, f"Preview must return 200, got {r.status_code}: {r.text}"
    body = r.json()

    # Export blocker present
    export_blockers = body.get("export_blockers", [])
    assert any("proforma export requires wFirma PZ" in b for b in export_blockers), (
        f"export_blockers must contain PZ requirement, got: {export_blockers}"
    )

    # blocking_reasons must NOT contain the PZ requirement
    reasons = body.get("blocking_reasons", [])
    pz_in_blocking = [r for r in reasons if "warehouse PZ not yet created" in r
                      or "proforma export requires wFirma PZ" in r]
    assert pz_in_blocking == [], (
        f"PZ requirement must NOT appear in blocking_reasons after gate separation, "
        f"got: {pz_in_blocking}"
    )

    # can_preview=True — preview is allowed without PZ
    assert body.get("can_preview") is True, (
        f"can_preview must be True when lines exist (PZ is export gate), "
        f"got: {body.get('can_preview')}"
    )

    # batch_lifecycle is surfaced
    assert "batch_lifecycle" in body, "batch_lifecycle must be present in preview response"

    # Response includes the commercial lines
    lines = body.get("lines", [])
    assert len(lines) >= 1, f"Expected at least 1 line, got: {lines}"


# ── Test 2 ────────────────────────────────────────────────────────────────────

def test_proforma_create_blocked_by_missing_pz_doc(client, storage):
    """
    Create endpoint is blocked when wfirma_pz_doc_id absent.

    Even though preview is allowed (can_preview=True), the create/export
    path checks export_blockers and returns blocked.
    ready=False because export_blockers is non-empty.
    """
    _seed_sales_client(storage)
    _write_audit(storage, pz_doc_id="")   # no PZ
    _write_pz_rows(storage, [_pz_row("EJL/GS-1")])

    # Create endpoint — should be blocked
    r = client.post(f"/api/v1/proforma/create/{BATCH}/{CLIENT}", headers=_auth())
    body = r.json()

    # Either 200 with ok=False/status=blocked, or HTTP 4xx
    assert body.get("ok") is False or body.get("status") == "blocked", (
        f"Create must be blocked when PZ absent, got: {body}"
    )

    # Export blockers or blocking_reasons must carry the PZ requirement
    all_blockers = (
        body.get("export_blockers", []) + body.get("blocking_reasons", [])
    )
    assert any(
        "proforma export requires wFirma PZ" in b or
        "wfirma proforma create disabled" in b or
        "wFirma PZ" in b
        for b in all_blockers
    ), (
        f"Create response must explain PZ requirement, got blockers: {all_blockers}"
    )


# ── Test 3 ────────────────────────────────────────────────────────────────────

def test_inventory_state_derives_transit_from_tracking(client, storage):
    """
    When inventory_state rows = 0 AND clearance_status = 'dsk_generated',
    batch_lifecycle = 'DHL_TRANSIT' and lines with scan_codes show
    stock_status = 'dhl_transit' (preview-eligible, not a hard blocker).
    """
    from app.api.routes_proforma import _derive_batch_lifecycle, _build_preview

    _seed_sales_client(storage, scan_code="SC-TRANSIT-001")
    _write_audit(storage, pz_doc_id="", clearance_status="dsk_generated")
    _write_pz_rows(storage, [_pz_row("EJL/GS-1")])

    with patch.object(settings, "storage_root", storage):
        # 1. Lifecycle derivation — no inventory rows + dsk_generated → DHL_TRANSIT
        lifecycle = _derive_batch_lifecycle(BATCH)
        assert lifecycle == "DHL_TRANSIT", (
            f"Expected DHL_TRANSIT when inventory=0 + clearance_status=dsk_generated, "
            f"got: {lifecycle}"
        )

        # 2. Preview with DHL_TRANSIT lifecycle
        preview = _build_preview(BATCH, CLIENT)

    # batch_lifecycle in response
    assert preview.get("batch_lifecycle") == "DHL_TRANSIT", (
        f"batch_lifecycle must be DHL_TRANSIT in preview response, got: {preview.get('batch_lifecycle')}"
    )

    # Scan-coded lines should show dhl_transit stock_status (not missing_state)
    lines = preview.get("lines", [])
    assert len(lines) >= 1, "Expected at least 1 line"
    for ln in lines:
        if ln.get("product_code"):
            st = ln.get("stock_status", "")
            assert st == "dhl_transit", (
                f"Line {ln.get('product_code')} should be dhl_transit in DHL_TRANSIT batch, "
                f"got stock_status={st!r}"
            )
            assert ln.get("stock_ok") is True, (
                f"stock_ok must be True for dhl_transit lines, got: {ln.get('stock_ok')}"
            )

    # stock-related blocking_reasons must NOT contain "missing_state" for DHL_TRANSIT
    reasons = preview.get("blocking_reasons", [])
    missing_state_reasons = [r for r in reasons if "inventory_state_engine has not seeded" in r]
    assert missing_state_reasons == [], (
        f"DHL_TRANSIT batch must not have missing_state blocking reasons, got: {missing_state_reasons}"
    )


# ── Test 4 ────────────────────────────────────────────────────────────────────

def test_orphan_packing_line_retains_invoice_provenance(storage):
    """
    A packing_lines row with no corresponding sales_packing_lines client
    assignment retains its original invoice_no, product_code, and scan_code.

    The DB must not clear or overwrite these fields when a line is orphaned
    (i.e. when no link-as-sales mapping was ever created for it).

    This guards against any future refactor that might anonymize or clear
    provenance fields on unlinked packing lines, ensuring operators can
    always identify which invoice the orphan belongs to for correction.
    """
    ORPHAN_BATCH   = "BATCH_ORPHAN_TEST"
    ORPHAN_INVOICE = "EJL/26-27/178"
    ORPHAN_PRODUCT = "JR08007"

    # Write the packing line (purchase side) with no client assignment.
    # scan_code is computed by packing_db from product_code + pack_sr + design_no.
    pdb.upsert_packing_lines([{
        "batch_id":               ORPHAN_BATCH,
        "invoice_no":             ORPHAN_INVOICE,
        "invoice_line_position":  1,
        "product_code":           ORPHAN_PRODUCT,
        "design_no":              ORPHAN_PRODUCT,
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

    # Verify no sales_packing_lines link exists for this batch/product
    sales_rows = ddb.get_sales_packing_lines(ORPHAN_BATCH) or []
    orphan_sales = [r for r in sales_rows if r.get("product_code") == ORPHAN_PRODUCT]
    assert orphan_sales == [], (
        f"Expected no sales link for orphan product, got: {orphan_sales}"
    )

    # Retrieve the packing_lines row and verify provenance is intact
    pl_rows = pdb.get_packing_lines_for_batch(ORPHAN_BATCH)
    assert pl_rows, f"Expected packing_lines rows for {ORPHAN_BATCH}"

    orphan_rows = [r for r in pl_rows if r.get("product_code") == ORPHAN_PRODUCT]
    assert orphan_rows, (
        f"Expected packing_lines row for product_code={ORPHAN_PRODUCT!r}, "
        f"got rows: {[r.get('product_code') for r in pl_rows]}"
    )

    orphan = orphan_rows[0]

    # Invoice provenance must be retained — these must never be cleared on orphan lines
    assert orphan.get("invoice_no") == ORPHAN_INVOICE, (
        f"Orphan packing line must retain invoice_no={ORPHAN_INVOICE!r}, "
        f"got: {orphan.get('invoice_no')}"
    )
    assert orphan.get("product_code") == ORPHAN_PRODUCT, (
        f"Orphan packing line must retain product_code={ORPHAN_PRODUCT!r}, "
        f"got: {orphan.get('product_code')}"
    )
    # scan_code is computed (product_code|sr{pack_sr}|design_no) — must be non-null
    # so warehouse scans can identify this line even without a client assignment.
    computed_scan = orphan.get("scan_code")
    assert computed_scan is not None and computed_scan != "", (
        f"Orphan packing line must have a computed scan_code (not null), "
        f"got: {computed_scan!r}.  Warehouse lookups rely on scan_code to identify "
        "unlinked lines for operator correction via link-as-sales."
    )
    assert ORPHAN_PRODUCT in computed_scan, (
        f"scan_code {computed_scan!r} must contain product_code {ORPHAN_PRODUCT!r} "
        "for operator identification of orphan lines"
    )

    # Correction path: link-as-sales endpoint must exist for operator remediation
    from app.api.routes_packing import router as packing_router
    route_paths = [r.path for r in packing_router.routes]
    assert any("link-as-sales" in p for p in route_paths), (
        f"link-as-sales endpoint must exist in packing router for orphan correction; "
        f"routes: {route_paths}"
    )
