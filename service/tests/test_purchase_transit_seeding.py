"""
test_purchase_transit_seeding.py — Producer wiring at packing upload.

Covers seed_purchase_transit():
  1. seeds PURCHASE_TRANSIT for every line with a scan_code
  2. re-upload (re-seed) is idempotent — no duplicate state events
  3. state-engine failure does not break the producer (best-effort)
  4. lines without scan_code are skipped, not raised
  5. seeds carry product_code, design_no, batch_id forward
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import packing_db as pdb
from app.services import warehouse_db as wdb
from app.services import inventory_state_engine as ise
from app.api.routes_packing import seed_purchase_transit


@pytest.fixture()
def db(tmp_path):
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    return tmp_path


def _line(n: int, **kwargs) -> dict:
    base = {
        "batch_id":     "BATCH_PT_TEST",
        "product_code": f"EJL/26-27/100-{n}",
        "design_no":    f"D-{n:03}",
        "bag_id":       "",
        "pack_sr":      float(n),
        "invoice_no":   "EJL/26-27/100",
        "invoice_line_position": n,
        "quantity":     1.0,
        "gross_weight": 5.0,
        "net_weight":   5.0,
    }
    base.update(kwargs)
    return base


# ── 1. Seeds every line ──────────────────────────────────────────────────────

def test_seed_creates_purchase_transit_for_every_line(db):
    lines = [_line(i) for i in range(1, 4)]
    seeded = seed_purchase_transit("BATCH_PT_TEST", lines)
    assert seeded == 3

    for ln in lines:
        sc = pdb._compute_scan_code(ln)
        st = ise.get_state(sc)
        assert st is not None
        assert st["state"]        == ise.PURCHASE_TRANSIT
        assert st["product_code"] == ln["product_code"]
        assert st["design_no"]    == ln["design_no"]
        assert st["batch_id"]     == "BATCH_PT_TEST"

    counts = ise.count_by_state(batch_id="BATCH_PT_TEST")
    assert counts[ise.PURCHASE_TRANSIT] == 3


# ── 2. Re-seed is idempotent ─────────────────────────────────────────────────

def test_reseed_is_idempotent(db):
    lines = [_line(1), _line(2)]
    first  = seed_purchase_transit("BATCH_PT_TEST", lines)
    second = seed_purchase_transit("BATCH_PT_TEST", lines)
    assert first  == 2
    assert second == 0  # already seeded → all skipped

    # No duplicate transition events for the same scan_code
    for ln in lines:
        sc = pdb._compute_scan_code(ln)
        history = ise.get_history(sc)
        assert len(history) == 1
        assert history[0]["to_state"] == ise.PURCHASE_TRANSIT


# ── 3. Engine failure must not break the producer ───────────────────────────

def test_state_engine_failure_does_not_break_producer(db):
    lines = [_line(1), _line(2)]
    with patch.object(ise, "transition", side_effect=RuntimeError("boom")):
        # Must not raise
        seeded = seed_purchase_transit("BATCH_PT_TEST", lines)
    assert seeded == 0
    # No states recorded since every transition raised
    assert ise.count_by_state(batch_id="BATCH_PT_TEST")[ise.PURCHASE_TRANSIT] == 0


# ── 4. Lines without scan_code are skipped ──────────────────────────────────

def test_lines_without_scan_code_are_skipped(db):
    # No product_code → _compute_scan_code returns "" → skip
    bad = {"batch_id": "BATCH_PT_TEST", "product_code": "", "design_no": "",
           "bag_id": "", "pack_sr": None}
    good = _line(1)
    seeded = seed_purchase_transit("BATCH_PT_TEST", [bad, good])
    assert seeded == 1
    assert ise.get_state(pdb._compute_scan_code(good))["state"] == ise.PURCHASE_TRANSIT


# ── 5. Existing-state guard: lines already in any state are skipped ─────────

def test_existing_state_skipped(db):
    ln = _line(1)
    sc = pdb._compute_scan_code(ln)
    # Pre-seed manually to a later state
    ise.transition(scan_code=sc, to_state=ise.PURCHASE_TRANSIT,
                   product_code=ln["product_code"], design_no=ln["design_no"],
                   batch_id="BATCH_PT_TEST")
    ise.transition(scan_code=sc, to_state=ise.WAREHOUSE_STOCK)

    # Now run seeder — must not attempt to demote to PURCHASE_TRANSIT
    seeded = seed_purchase_transit("BATCH_PT_TEST", [ln])
    assert seeded == 0
    assert ise.get_state(sc)["state"] == ise.WAREHOUSE_STOCK
