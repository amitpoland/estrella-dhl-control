"""
test_intake_add_document_packing_persist.py — add-document no-persist gap fix.

The /add-document packing branch parsed rows via process_packing_upload but
never stored them: no packing_document upsert, no packing_lines rows, no
PURCHASE_TRANSIT seed, no PM4 sync trigger. Every packing document added
through that path silently missed the packing authority (CMR weights, variant
identity, Product Master sync).

Fix under test: ONE persistence helper `_persist_packing_rows` (superset
mapping from the primary /intake path, incl. pack_sr — the dedup uniqueness
key — plus unit_price/total_value) used by BOTH the /add-packing-list backfill
path (whose inline copy had diverged and lost those 3 keys) and the
/add-document packing branch (which now also schedules PM4).

Coverage:
  1. helper unit test — full superset mapping + transit seed + count
  2. helper no-rows short-circuit
  3. source pins — both call sites wired; PM4 scheduled on add-document;
     primary /intake path left byte-identical (hot-path discipline)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

from app.api import routes_intake as ri

ROUTES = Path(ri.__file__)

SUPERSET_KEYS = {
    "packing_document_id", "batch_id", "invoice_no", "invoice_line_position",
    "product_code", "design_no", "batch_no", "bag_id", "tray_id", "item_type",
    "uom", "quantity", "gross_weight", "net_weight", "metal", "karat",
    "stone_type", "metal_color", "quality_string", "size", "diamond_weight",
    "color_weight", "remarks", "extracted_confidence",
    "requires_manual_review", "invoice_no_raw", "supplier_name",
    "pack_sr", "unit_price", "total_value",
}


def _parse_result(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "document": {"batch_id": "B-ADP", "file_name": "pl.xlsx"},
        "packing_rows": rows,
        "supplier": "",
    }


# ── 1. Helper unit test ───────────────────────────────────────────────────────

def test_persist_helper_superset_mapping_and_transit_seed():
    stored: Dict[str, Any] = {}
    with patch.object(ri.pdb, "upsert_packing_document", return_value=77) as updoc, \
         patch.object(ri.pdb, "upsert_packing_lines") as uplines, \
         patch.object(ri, "seed_purchase_transit") as seed:
        n = ri._persist_packing_rows("B-ADP", _parse_result([{
            "invoice_no": "INV-1", "invoice_line_position": 4,
            "product_code": "EJL-RNG-0001", "design_no": "JR02075",
            "item_type": "RNG", "quantity": 2, "gross_weight": 3.2,
            "net_weight": 2.9, "karat": "14KT", "metal_color": "P",
            "quality_string": "FG-VS", "size": "17.0M",
            "diamond_weight": 0.51, "color_weight": 0,
            "line_position": 9, "unit_price": 300, "total_value": 600,
        }]), "Supplier X")
    assert n == 1
    updoc.assert_called_once()
    uplines.assert_called_once()
    rec = uplines.call_args[0][0][0]
    assert set(rec.keys()) == SUPERSET_KEYS, (
        f"mapping drift — missing {SUPERSET_KEYS - set(rec.keys())}, "
        f"extra {set(rec.keys()) - SUPERSET_KEYS}"
    )
    assert rec["packing_document_id"] == 77
    assert rec["pack_sr"] == 9                    # dedup uniqueness key
    assert rec["unit_price"] == 300.0
    assert rec["total_value"] == 600.0
    assert rec["karat"] == "14KT" and rec["size"] == "17.0M"
    assert rec["supplier_name"] == "Supplier X"
    seed.assert_called_once()
    assert seed.call_args[0][0] == "B-ADP"


def test_persist_helper_no_rows_short_circuit():
    with patch.object(ri.pdb, "upsert_packing_document", return_value=1), \
         patch.object(ri.pdb, "upsert_packing_lines") as uplines, \
         patch.object(ri, "seed_purchase_transit") as seed:
        n = ri._persist_packing_rows("B-ADP", _parse_result([]), "")
    assert n == 0
    uplines.assert_not_called()
    seed.assert_not_called()


# ── 3. Source pins ────────────────────────────────────────────────────────────

def test_both_secondary_paths_use_the_helper():
    src = ROUTES.read_text(encoding="utf-8")
    assert src.count("_persist_packing_rows(") >= 3, \
        "helper must be defined and called from backfill + add-document"
    # add-document packing branch: persist + PM4 with the stored count
    i = src.index('elif policy["parser"] == "packing":')
    block = src[i:i + 1600]
    assert "_persist_packing_rows(" in block, "add-document packing branch must persist"
    assert "schedule_product_master_sync(background, batch_id, n_stored)" in block, \
        "add-document must schedule PM4 on stored rows"


def test_add_document_signature_has_background_tasks():
    src = ROUTES.read_text(encoding="utf-8")
    m = re.search(r"async def add_document_to_batch\(\s*background:\s*BackgroundTasks", src)
    assert m, "add_document_to_batch must accept BackgroundTasks for PM4 scheduling"


def test_primary_intake_path_untouched_this_change():
    """Hot-path discipline: /intake keeps its inline superset block until the
    helper has a verification window. This pin documents the deliberate
    remaining copy (fold-in is the registered follow-up)."""
    src = ROUTES.read_text(encoding="utf-8")
    # the primary block's unique marker (its Sr/PkSr comment) is still inline
    assert src.count('"pack_sr":               r.get("line_position")') >= 2, \
        "primary inline mapping + helper mapping both present (expected until fold-in)"
