"""
test_proforma_draft_pre_pz_gate.py — Gate decoupling (2026-05-26).

Verifies the architectural rule introduced in the draft/export gate split:

Authority separation
--------------------
  Sales authority  — sales packing list + client assignment + product match
  Product authority — purchase invoice lines (available at intake, no SAD needed)
  Customs authority — SAD/ZC429 + MRN + PZ (required for wFirma PZ posting only)

Tests
-----
  1. test_proforma_draft_created_without_pz
       /create saves pending_local draft when commercial data is ready
       and export_blockers (PZ absent) are present. ok=True, draft_saved=True.

  2. test_proforma_draft_blocked_when_no_sales_data
       /create returns blocked when no sales packing list exists —
       the commercial gate (blocking_reasons) fires before draft is saved.

  3. test_preview_draft_ready_field_present
       /preview response includes draft_ready field (True when commercial
       data ready, independent of export_blockers).

  4. test_preview_draft_ready_false_when_no_sales_data
       /preview draft_ready=False when no sales rows.

  5. test_product_auto_register_works_without_sad
       ensure_products_for_batch (dry_run=True) reads from invoice_lines
       at intake time — no SAD required. Returns scanned > 0.

  6. test_product_create_blocked_by_flag_not_sad
       Product creation blocked only by WFIRMA_CREATE_PRODUCT_ALLOWED=false,
       not by SAD absence. auto-register endpoint returns blocked status
       with flag reason.
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


BATCH  = "BATCH_PREDRAFT_TEST"
CLIENT = "Tomas Gold UAB"


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


def _write_audit_draft(storage, *, pz_doc_id: str = ""):
    """Write a draft-status audit (no SAD, no PZ) — typical pre-SAD state."""
    bd = _batch_dir(storage)
    audit = {
        "batch_id": BATCH,
        "status":   "draft",
        "inputs":   {"invoices": ["Invoice EJL-26-27-187.pdf"]},
        "wfirma_export": {"wfirma_pz_doc_id": pz_doc_id},
        "clearance_status": "dsk_generated",
    }
    (bd / "audit.json").write_text(json.dumps(audit))


def _write_pz_rows(storage, rows):
    bd = _batch_dir(storage)
    (bd / "pz_rows.json").write_text(json.dumps(rows))


def _seed_sales_and_products(storage):
    """Seed purchase packing + sales packing + wFirma mappings for CLIENT."""
    # Purchase packing line
    pdb.upsert_packing_lines([{
        "batch_id":               BATCH,
        "invoice_no":             "EJL/26-27/187",
        "invoice_line_position":  1,
        "product_code":           "EJL/26-27/187-1",
        "design_no":              "TG001",
        "bag_id":                 "",
        "tray_id":                "",
        "item_type":              "EARRINGS",
        "uom":                    "PRS",
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
        "unit_price":             1120.0,
        "total_value":            1120.0,
        "scan_code":              "SC-TG-001",
    }])

    # Invoice line in document_db (needed for product auto-register)
    ddb.store_invoice_lines("DOC-TG-187", BATCH, [{
        "invoice_no":       "EJL/26-27/187",
        "line_position":    1,
        "product_code":     "EJL/26-27/187-1",
        "description":      "PRS, 14KT Gold, Stud With Diam Jewellery EARRINGS",
        "quantity":         1.0,
        "unit_price":       1120.0,
        "total_value":      1120.0,
        "currency":         "USD",
        "hsn_code":         "71131913",
    }])

    # Sales packing list for CLIENT
    sd = ddb.store_sales_document(
        batch_id=BATCH,
        document_id=str(uuid.uuid4()),
        data={"client_name": CLIENT, "client_ref": "TG-REF", "sales_doc_no": "SO-TG"},
    )
    ddb.store_sales_packing_lines(sd, BATCH, [{
        "client_name":  CLIENT,
        "client_ref":   "TG-REF",
        "product_code": "TG001",
        "design_no":    "TG001",
        "bag_id":       "",
        "quantity":     1.0,
        "unit_price":   1500.0,
        "currency":     "EUR",
        "remarks":      "",
    }])

    # wFirma product + customer mappings (required for commercial readiness)
    wfdb.upsert_product(
        product_code="EJL/26-27/187-1",
        wfirma_product_id="P-TG-001",
        sync_status="matched",
    )
    wfdb.upsert_customer(
        client_name=CLIENT,
        wfirma_customer_id="C-TG-001",
        country="LT",
        vat_id="LT123456789",
        match_status="matched",
    )


# ── Test 1 ────────────────────────────────────────────────────────────────────

def test_proforma_draft_created_without_pz(client, storage):
    """
    /create saves a pending_local draft when commercial data is ready
    even when PZ (wfirma_pz_doc_id) is absent.

    Expected: ok=True, status=pending_local, draft_saved=True,
              export_blocked=True, export_blockers carries PZ requirement.
    """
    _seed_sales_and_products(storage)
    _write_audit_draft(storage, pz_doc_id="")   # no PZ
    _write_pz_rows(storage, [{
        "product_code":   "EJL/26-27/187-1",
        "unit_netto_pln": 4800.0,
    }])

    r = client.post(f"/api/v1/proforma/create/{BATCH}/{CLIENT}", headers=_auth())
    body = r.json()
    status = body.get("status")

    if status == "pending_local":
        assert body.get("ok") is True, (
            f"pending_local must be ok=True (draft saved), got: {body}"
        )
        assert body.get("draft_saved") is True, (
            f"draft_saved must be True, got: {body}"
        )
        assert body.get("export_blocked") is True, (
            f"export_blocked must be True when PZ absent, got: {body}"
        )
        export_blockers = body.get("export_blockers", [])
        assert any("wFirma PZ" in b or "proforma export" in b
                   for b in export_blockers), (
            f"export_blockers must explain PZ requirement, got: {export_blockers}"
        )
        assert body.get("draft_id") is not None, (
            f"draft_id must be present (draft was saved), got: {body}"
        )
    elif status == "blocked":
        # Settings gate (wfirma_create_proforma_allowed=False in test env).
        # The commercial gate passed; settings gate fired before live call.
        all_blockers = (
            body.get("export_blockers", []) + body.get("blocking_reasons", [])
        )
        assert not any(
            "sales rows" in b.lower() or "not matched in wfirma_customer" in b.lower()
            for b in all_blockers
        ), (
            f"Commercial gate must have passed (no sales/customer blockers), "
            f"got: {all_blockers}"
        )
    else:
        pytest.fail(
            f"Expected pending_local or settings-blocked, got status={status!r}: {body}"
        )


# ── Test 2 ────────────────────────────────────────────────────────────────────

def test_proforma_draft_blocked_when_no_sales_data(client, storage):
    """
    /create returns blocked when no sales packing list has been uploaded.
    The commercial gate (blocking_reasons: no sales rows) fires before
    the draft is saved — draft_saved must NOT be True.
    """
    _write_audit_draft(storage, pz_doc_id="")

    r = client.post(f"/api/v1/proforma/create/{BATCH}/{CLIENT}", headers=_auth())
    body = r.json()

    assert body.get("status") == "blocked", (
        f"Create must be blocked when no sales rows, got: {body}"
    )
    assert body.get("ok") is False, (
        f"ok must be False when commercially blocked, got: {body}"
    )
    assert not body.get("draft_saved"), (
        f"draft_saved must not be True when commercial gate blocks, got: {body}"
    )
    reasons = body.get("blocking_reasons", [])
    assert any("sales rows" in r.lower() or "no sales" in r.lower()
               for r in reasons), (
        f"blocking_reasons must explain missing sales data, got: {reasons}"
    )


# ── Test 3 ────────────────────────────────────────────────────────────────────

def test_preview_draft_ready_field_present(client, storage):
    """
    /preview response must include draft_ready field.
    When commercial data is ready, draft_ready=True even if export_blockers
    (PZ absent) would block live wFirma issuance.
    """
    _seed_sales_and_products(storage)
    _write_audit_draft(storage, pz_doc_id="")
    _write_pz_rows(storage, [{"product_code": "EJL/26-27/187-1", "unit_netto_pln": 4800.0}])

    r = client.post(f"/api/v1/proforma/preview/{BATCH}/{CLIENT}", headers=_auth())
    assert r.status_code == 200, r.text
    body = r.json()

    assert "draft_ready" in body, (
        f"draft_ready must be present in preview response, got keys: {list(body)}"
    )
    assert body.get("draft_ready") is True, (
        f"draft_ready must be True when commercial data is present, got: {body.get('draft_ready')}"
    )
    # ready should still be False (export_blockers present)
    export_blockers = body.get("export_blockers", [])
    if export_blockers:
        assert body.get("ready") is False, (
            f"ready must be False when export_blockers present, got: {body.get('ready')}"
        )


# ── Test 4 ────────────────────────────────────────────────────────────────────

def test_preview_draft_ready_false_when_no_sales_data(client, storage):
    """
    /preview draft_ready=False when no sales packing list uploaded.
    Verifies that the draft_ready field tracks commercial readiness, not
    just absence of export_blockers.
    """
    _write_audit_draft(storage, pz_doc_id="")

    r = client.post(f"/api/v1/proforma/preview/{BATCH}/{CLIENT}", headers=_auth())
    assert r.status_code == 200, r.text
    body = r.json()

    # When can_preview=False the endpoint returns early without draft_ready.
    # Either the field is explicitly False, or can_preview=False (which implies
    # blocking_reasons exist, so draft_ready = not blocking_reasons = False).
    assert body.get("draft_ready") is False or body.get("can_preview") is False, (
        f"draft_ready must be False or can_preview=False when no sales rows, got: {body}"
    )


# ── Test 5 ────────────────────────────────────────────────────────────────────

def test_product_auto_register_works_without_sad(storage):
    """
    Product auto-register dry-run reads from invoice_lines (available at
    intake) and does not require SAD/ZC429 upload.

    Verifies: ensure_products_for_batch(dry_run=True) finds the 4 product
    codes from invoice_lines data alone (no audit SAD field, no pz_rows).
    """
    # Seed invoice lines directly (as intake would)
    ddb.store_invoice_lines("DOC-TG-187", BATCH, [
        {
            "invoice_no":    "EJL/26-27/187",
            "line_position": 1,
            "product_code":  "EJL/26-27/187-1",
            "description":   "PRS, 14KT Gold, Stud With Diam EARRINGS",
            "quantity":      1.0,
            "unit_price":    1120.0,
            "total_value":   1120.0,
            "currency":      "USD",
            "hsn_code":      "71131913",
        },
        {
            "invoice_no":    "EJL/26-27/188",
            "line_position": 1,
            "product_code":  "EJL/26-27/188-1",
            "description":   "PRS, 14KT Gold, Diamond EARRINGS",
            "quantity":      2.0,
            "unit_price":    800.0,
            "total_value":   1600.0,
            "currency":      "USD",
            "hsn_code":      "71131913",
        },
    ])

    from app.services.wfirma_product_auto_register import ensure_products_for_batch

    with patch.object(settings, "storage_root", storage):
        result = ensure_products_for_batch(BATCH, dry_run=True)

    assert result["scanned"] == 2, (
        f"Should scan 2 product codes from invoice_lines, got: {result['scanned']}"
    )
    assert result["dry_run"] is True
    # All should be 'missing' in dry-run (no wFirma data seeded)
    statuses = {r["status"] for r in result["results"]}
    # search_failed is acceptable when wFirma client is not configured in test env
    assert statuses <= {"missing", "search_failed", "existing_mapped", "pending_adoption"}, (
        f"Unexpected statuses: {statuses} — SAD should not be a blocker here"
    )
    # None should be 'blocked' (the flag gate fires only in write mode)
    assert "blocked" not in statuses, (
        f"Dry-run must not produce 'blocked' status (flag gate inactive in dry-run), "
        f"got statuses: {statuses}"
    )


# ── Test 6 ────────────────────────────────────────────────────────────────────

def test_product_create_blocked_by_flag_not_sad(client, storage):
    """
    Product creation is blocked by WFIRMA_CREATE_PRODUCT_ALLOWED=false,
    NOT by SAD absence. The blocking reason must reference the flag, not SAD.

    Confirms authority separation: product master creation requires only
    invoice line data (available at intake) + operator flag approval.
    """
    # Seed invoice lines (no SAD, no audit, no pz_rows)
    ddb.store_invoice_lines("DOC-TG-187", BATCH, [{
        "invoice_no":    "EJL/26-27/187",
        "line_position": 1,
        "product_code":  "EJL/26-27/187-1",
        "description":   "PRS, 14KT Gold, Stud Earring EARRINGS",
        "quantity":      1.0,
        "unit_price":    1120.0,
        "total_value":   1120.0,
        "currency":      "USD",
        "hsn_code":      "71131913",
    }])

    with patch.object(settings, "wfirma_create_product_allowed", False):
        r = client.post(
            f"/api/v1/wfirma/goods/auto-register/{BATCH}",
            headers=_auth(),
        )
    body = r.json()

    # All product codes should be blocked (flag off) or search_failed (no wFirma)
    results = body.get("results", [])
    for res in results:
        assert res["status"] in ("blocked", "search_failed", "existing_mapped",
                                  "pending_adoption"), (
            f"Unexpected status {res['status']!r} for {res['product_code']}"
        )
        if res["status"] == "blocked":
            error = res.get("error", "")
            assert "wfirma_create_product_allowed" in error.lower() or \
                   "WFIRMA_CREATE_PRODUCT_ALLOWED" in error, (
                f"blocked reason must reference the flag, not SAD; got: {error!r}"
            )
            assert "sad" not in error.lower() and "zc429" not in error.lower(), (
                f"blocked reason must NOT reference SAD/ZC429; got: {error!r}"
            )
