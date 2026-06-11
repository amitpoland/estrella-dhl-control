"""test_proforma_pre_approve_surfacing.py

Regression for: blank name_pl and zero unit_price NOT surfaced in
blocking_reasons before the operator clicks Approve.

Before the fix, _preflight_approve() was only called at approve time,
so blank name_pl produced a 422 surprise. Now the same check runs at
preview time and appears in blocking_reasons so the operator sees it
before attempting to approve.

Tests:
  1. Draft with blank name_pl → preview blocking_reasons includes the count
  2. Draft with zero unit_price → preview blocking_reasons includes the count
  3. Draft with both blank name_pl and zero unit_price → both appear
  4. Draft with all name_pl filled → no blank-name_pl blocker in preview
  5. No draft exists for batch/client → no spurious blocker added
  6. Approve endpoint still rejects (422) when name_pl blank (guard preserved)
"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_engine_candidates = [
    Path(__file__).parent.parent.parent / "engine",
    Path(__file__).parent.parent.parent.parent / "engine",
]
for _p in _engine_candidates:
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
        break


BATCH = "BATCH_PRE_APPROVE_TEST"
CLIENT = "GOTO_JEWELLERY"
PRODUCT_CODE = "EJL/26-27/254-1"


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def storage(tmp_path):
    from app.services import packing_db as pdb
    from app.services import document_db as ddb
    from app.services import wfirma_db as wfdb
    from app.services import proforma_invoice_link_db as pildb

    pdb.init_packing_db(tmp_path / "packing.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    pildb.init_db(tmp_path / "proforma_links.db")

    # batch audit.json required by some guard helpers
    out = tmp_path / "outputs" / BATCH
    (out / "source").mkdir(parents=True, exist_ok=True)
    audit = {"batch_id": BATCH, "tracking_no": BATCH,
             "awb": BATCH, "carrier": "DHL", "timeline": []}
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")

    return tmp_path


@pytest.fixture()
def client(storage):
    from app.core.config import settings
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c, storage


def _auth():
    from app.core.config import settings
    return {"X-API-KEY": settings.api_key or "test-key"}


def _op_headers():
    return {"X-Operator": "test-op", **_auth()}


# ── seed helpers ──────────────────────────────────────────────────────────────

def _seed_batch_data(storage: Path):
    """Seed minimal packing + sales data so the preview has resolution_rows."""
    from app.services import packing_db as pdb
    from app.services import document_db as ddb
    from app.services import wfirma_db as wfdb

    # Purchase packing (product_code ↔ design_no mapping)
    pdb.upsert_packing_lines([{
        "batch_id":              BATCH,
        "invoice_no":            "INV/TEST",
        "invoice_line_position": 1,
        "product_code":          PRODUCT_CODE,
        "design_no":             PRODUCT_CODE,
        "bag_id": "", "tray_id": "", "item_type": "RNG",
        "uom": "PCS", "quantity": 1.0, "gross_weight": 0.0,
        "net_weight": 0.0, "metal": "", "karat": "", "stone_type": "",
        "remarks": "", "extracted_confidence": 1.0,
        "requires_manual_review": False, "pack_sr": 1.0,
        "unit_price": 50.0, "total_value": 50.0,
    }])

    # Sales packing (provides unit_price + currency for the preview)
    sd = ddb.store_sales_document(
        batch_id=BATCH,
        document_id=str(uuid.uuid4()),
        data={"client_name": CLIENT, "client_ref": "REF-TEST",
              "sales_doc_no": "SO-TEST"},
    )
    ddb.store_sales_packing_lines(sd, BATCH, [{
        "client_name":  CLIENT,
        "client_ref":   "REF-TEST",
        "product_code": PRODUCT_CODE,
        "design_no":    PRODUCT_CODE,
        "bag_id": "", "quantity": 1.0, "remarks": "",
        "unit_price": 100.0, "total_value": 100.0,
        "currency": "EUR", "price_source": "packing_list",
    }])

    # wFirma product + customer (required for ready=True path)
    wfdb.upsert_product(
        product_code=PRODUCT_CODE,
        wfirma_product_id="99",
        sync_status="matched",
    )
    wfdb.upsert_customer(
        client_name=CLIENT,
        wfirma_customer_id="7",
        country="BG",
        vat_id="",
        match_status="matched",
    )


def _seed_draft(
    storage: Path,
    editable_lines: list,
    draft_state: str = "draft",
) -> int:
    """Insert a draft with the given editable_lines_json and return its id."""
    db = storage / "proforma_links.db"
    with sqlite3.connect(str(db)) as conn:
        cur = conn.execute(
            """
            INSERT INTO proforma_drafts
              (batch_id, client_name, status, currency, draft_state,
               wfirma_proforma_id, wfirma_proforma_fullnumber,
               source_lines_json, editable_lines_json, service_charges_json,
               clone_generation, draft_version,
               created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))
            """,
            (BATCH, CLIENT, "draft", "EUR", draft_state,
             None, "",
             "[]", json.dumps(editable_lines), "[]", 0, 1),
        )
        conn.commit()
        return cur.lastrowid


# ── 1. Blank name_pl surfaces in blocking_reasons ────────────────────────────

def test_blank_name_pl_surfaces_in_preview_blocking_reasons(client):
    c, storage = client
    _seed_batch_data(storage)

    # Draft has 3 lines, all with blank name_pl
    lines = [
        {"line_id": str(i), "product_code": f"EJL/26-27/254-{i}",
         "name_pl": "", "unit_price": 50.0}
        for i in range(1, 4)
    ]
    _seed_draft(storage, lines)

    r = c.post(f"/api/v1/proforma/preview/{BATCH}/{CLIENT}", headers=_auth())
    assert r.status_code == 200, r.text
    body = r.json()

    blocking = body.get("blocking_reasons", [])
    assert any("blank commercial description (name_pl)" in br for br in blocking), (
        f"Expected blank name_pl blocker in blocking_reasons, got: {blocking}"
    )
    assert any("3" in br and "name_pl" in br for br in blocking), (
        f"Expected count '3' in name_pl blocker, got: {blocking}"
    )


# ── 2. Zero unit_price surfaces in blocking_reasons ──────────────────────────

def test_zero_unit_price_surfaces_in_preview_blocking_reasons(client):
    c, storage = client
    _seed_batch_data(storage)

    # Draft has 2 lines with zero unit_price, name_pl filled
    lines = [
        {"line_id": str(i), "product_code": f"EJL/26-27/254-{i}",
         "name_pl": "Pierścionek złoty", "unit_price": 0}
        for i in range(1, 3)
    ]
    _seed_draft(storage, lines)

    r = c.post(f"/api/v1/proforma/preview/{BATCH}/{CLIENT}", headers=_auth())
    assert r.status_code == 200, r.text
    body = r.json()

    blocking = body.get("blocking_reasons", [])
    assert any("zero/missing unit_price" in br for br in blocking), (
        f"Expected zero unit_price blocker in blocking_reasons, got: {blocking}"
    )
    assert any("2" in br and "unit_price" in br for br in blocking), (
        f"Expected count '2' in unit_price blocker, got: {blocking}"
    )


# ── 3. Both blank name_pl and zero unit_price → both appear ──────────────────

def test_both_blank_name_pl_and_zero_price_both_surface(client):
    c, storage = client
    _seed_batch_data(storage)

    lines = [
        {"line_id": "1", "product_code": "EJL/26-27/254-1",
         "name_pl": "",  "unit_price": 0},
        {"line_id": "2", "product_code": "EJL/26-27/254-2",
         "name_pl": "",  "unit_price": 0},
    ]
    _seed_draft(storage, lines)

    r = c.post(f"/api/v1/proforma/preview/{BATCH}/{CLIENT}", headers=_auth())
    body = r.json()
    blocking = body.get("blocking_reasons", [])

    assert any("name_pl" in br for br in blocking), blocking
    assert any("unit_price" in br for br in blocking), blocking


# ── 4. All name_pl filled → no blank-name_pl blocker ─────────────────────────

def test_filled_name_pl_no_spurious_blocker(client):
    c, storage = client
    _seed_batch_data(storage)

    lines = [
        {"line_id": "1", "product_code": PRODUCT_CODE,
         "name_pl": "Pierścionek złoty", "unit_price": 100.0},
    ]
    _seed_draft(storage, lines)

    r = c.post(f"/api/v1/proforma/preview/{BATCH}/{CLIENT}", headers=_auth())
    body = r.json()
    blocking = body.get("blocking_reasons", [])

    assert not any("name_pl" in br for br in blocking), (
        f"Unexpected name_pl blocker when all lines filled: {blocking}"
    )
    assert not any("unit_price" in br for br in blocking), (
        f"Unexpected unit_price blocker when prices set: {blocking}"
    )


# ── 5. No draft → no spurious blocker ────────────────────────────────────────

def test_no_draft_no_spurious_pre_approve_blocker(client):
    c, storage = client
    _seed_batch_data(storage)
    # No draft seeded for this batch/client

    r = c.post(f"/api/v1/proforma/preview/{BATCH}/{CLIENT}", headers=_auth())
    body = r.json()
    blocking = body.get("blocking_reasons", [])

    assert not any("name_pl" in br for br in blocking), (
        f"Spurious name_pl blocker when no draft exists: {blocking}"
    )
    assert not any("unit_price" in br and "import sales" in br for br in blocking), (
        f"Spurious unit_price blocker when no draft exists: {blocking}"
    )


# ── 6. Approve still rejects 422 when name_pl blank (guard preserved) ────────

def test_approve_still_returns_422_when_name_pl_blank(client):
    c, storage = client
    _seed_batch_data(storage)

    lines = [
        {"line_id": "1", "product_code": PRODUCT_CODE,
         "name_pl": "", "unit_price": 100.0},
    ]
    draft_id = _seed_draft(storage, lines, draft_state="draft")

    r = c.post(
        f"/api/v1/proforma/draft/{draft_id}/approve",
        json={"expected_updated_at": "", "confirm_token": "YES_APPROVE_LOCAL_PROFORMA_DRAFT"},
        headers=_op_headers(),
    )
    assert r.status_code == 422, r.text
    assert "blank commercial description" in r.json()["detail"], r.text
