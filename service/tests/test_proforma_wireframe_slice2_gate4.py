"""
test_proforma_wireframe_slice2_gate4.py — GATE-4 dispositions from Slice 1 (#870).

Two SCHEDULED items recorded as Slice 2 GATE-1 eligibility:
  (a) proforma_draft_sync END-TO-END variant path — variant-identity fields
      survive documents.db persistence (store_sales_packing_lines) through
      sync_draft_from_packing_upload grouping into the draft's editable_lines.
      (Slice 1 tested the pildb boundary directly; this exercises the full
      sync chain including the documents.db round-trip.)
  (b) update_draft_line PATCH preserves variant keys — an operator qty/price
      edit must not strip variant identity (in-place patch contract), and the
      EDITABLE_LINE_FIELDS whitelist still rejects variant keys as patch
      targets (variant fields are reset-refreshed, not per-line edited).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services import document_db as ddb
from app.services import proforma_invoice_link_db as pildb
from app.services import customer_master_db as cmdb
from app.services import wfirma_db as wfdb
from app.services.customer_master_db import CustomerMaster
from app.services.proforma_draft_sync import sync_draft_from_packing_upload

CID_ACME = "182241571"

VARIANT_COLS = {
    "client_po":      "Adagia new order",
    "karat":          "14KT",
    "metal":          "GOLD/P",
    "metal_color":    "P",
    "quality_string": "FG-VS (LAB",
    "stone_type":     "LAB DIAMOND",
    "size":           "17.0M",
    "diamond_weight": 0.51,
    "color_weight":   0.0,
}


@pytest.fixture()
def storage(tmp_path) -> Path:
    ddb.init_document_db(tmp_path / "documents.db")
    pildb.init_db(tmp_path / "proforma_links.db")
    cmdb.init_db(tmp_path / "customer_master.sqlite")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    with patch.object(settings, "storage_root", tmp_path):
        yield tmp_path


@pytest.fixture()
def proforma_db(storage) -> Path:
    return storage / "proforma_links.db"


def _seed_sales_packing(storage: Path, batch_id: str) -> None:
    cmdb.upsert_customer(
        storage / "customer_master.sqlite",
        CustomerMaster(bill_to_contractor_id=CID_ACME,
                       bill_to_name="ACME CORP", country="PL"),
    )
    ship = ddb.register_document(
        batch_id=batch_id, document_type="sales_packing_list",
        file_name="sales_pl.xlsx", source="intake",
        client_contractor_id=CID_ACME,
    ) or ""
    sd_id = ddb.store_sales_document(
        batch_id=batch_id, document_id=ship,
        data={"client_name": "ACME CORP",
              "document_type": "sales_packing_list",
              "client_contractor_id": CID_ACME},
    )
    ddb.store_sales_packing_lines(sd_id, batch_id, [{
        "client_name":  "ACME CORP",
        "product_code": "EJL-RNG-0001",
        "design_no":    "JR02075",
        "quantity":     1.0,
        "unit_price":   300.0,
        "total_value":  300.0,
        "currency":     "EUR",
        **VARIANT_COLS,
    }])


# ── (a) end-to-end sync path ─────────────────────────────────────────────────

def test_sync_end_to_end_carries_variant_fields(storage, proforma_db):
    b = "B-WF-SYNC-1"
    _seed_sales_packing(storage, b)

    result = sync_draft_from_packing_upload(
        batch_id=b, operator="test", db_path=proforma_db,
        master_db_path=storage / "master_data.sqlite",
    )
    assert result["created"] == 1

    drafts = pildb.list_drafts_for_batch(proforma_db, b)
    assert len(drafts) == 1
    lines = json.loads(drafts[0].editable_lines_json)
    assert len(lines) == 1
    ln = lines[0]
    # documents.db round-trip: every variant column survives store →
    # get_sales_packing_lines → grouping → draft birth.
    assert ln["client_po"] == VARIANT_COLS["client_po"]
    assert ln["karat"] == VARIANT_COLS["karat"]
    assert ln["metal_color"] == VARIANT_COLS["metal_color"]
    assert ln["quality_string"] == VARIANT_COLS["quality_string"]
    assert ln["stone_type"] == VARIANT_COLS["stone_type"]
    assert ln["size"] == VARIANT_COLS["size"]
    assert ln["diamond_weight"] == pytest.approx(0.51)
    assert ln["color_weight"] == pytest.approx(0.0)


# ── (b) PATCH preservation ───────────────────────────────────────────────────

def _seed_direct_draft(db: Path):
    draft, created = pildb.auto_create_draft_from_sales_packing(
        db, batch_id="B-WF-PATCH", client_name="ACME", currency="EUR",
        lines=[{
            "product_code": "EJL-RNG-0001", "design_no": "JR02075",
            "qty": 1, "unit_price": 300.0, "currency": "EUR",
            "price_source": "packing_xlsx_value", "client_ref": "PO-1",
            **VARIANT_COLS,
        }],
        operator="intake",
    )
    assert created
    return draft


def _first_line_id(draft) -> int:
    # line_id is assigned by _ensure_line_ids at read time (the GET/PATCH
    # projection), not persisted at birth — derive it the way the route does.
    lines = pildb._ensure_line_ids(json.loads(draft.editable_lines_json))
    return int(lines[0]["line_id"])


def test_line_patch_preserves_variant_fields(proforma_db):
    draft = _seed_direct_draft(proforma_db)
    line_id = _first_line_id(draft)

    refreshed = pildb.update_draft_line(
        proforma_db, draft.id, line_id,
        {"qty": 3, "unit_price": 275.0},
        "alice", draft.updated_at,
    )
    ln = json.loads(refreshed.editable_lines_json)[0]
    assert ln["qty"] == 3.0 and ln["unit_price"] == 275.0
    for k, v in VARIANT_COLS.items():
        got = ln[k]
        if isinstance(v, float):
            assert got == pytest.approx(v), f"{k} lost on PATCH"
        else:
            assert got == v, f"{k} lost on PATCH"


def test_line_patch_rejects_variant_keys(proforma_db):
    """Variant identity is reset-refreshed from sales packing, never per-line
    edited — the EDITABLE_LINE_FIELDS whitelist must keep rejecting them."""
    draft = _seed_direct_draft(proforma_db)
    line_id = _first_line_id(draft)
    with pytest.raises(ValueError, match="unknown line patch field"):
        pildb.update_draft_line(
            proforma_db, draft.id, line_id,
            {"karat": "18KT"}, "alice", draft.updated_at,
        )
