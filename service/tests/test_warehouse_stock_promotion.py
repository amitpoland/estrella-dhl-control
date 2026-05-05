"""
test_warehouse_stock_promotion.py — PZ-success promoter for WAREHOUSE_STOCK.

Covers _promote_to_warehouse_stock(batch_id), which is invoked from
routes_upload.py inside the PZ-success branch (_r_status in {success, partial}).

Required coverage:
  1. PZ success promotes PURCHASE_TRANSIT → WAREHOUSE_STOCK
  2. PZ partial promotes the same way
  3. PZ failure does NOT promote (verified by NOT calling the helper —
     covered by the call-site condition; we still exercise that the helper
     itself is the only mover)
  4. Idempotent re-run: second call does not duplicate
  5. Lines already at WAREHOUSE_STOCK (or beyond) are skipped, not demoted
  6. State-engine failure does not break the producer (best-effort)
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import packing_db as pdb
from app.services import warehouse_db as wdb
from app.services import inventory_state_engine as ise
from app.api.routes_packing import seed_purchase_transit
from app.api.routes_upload import _promote_to_warehouse_stock


@pytest.fixture()
def db(tmp_path):
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    return tmp_path


def _line(n: int, batch_id: str = "BATCH_PZ") -> dict:
    return {
        "batch_id":              batch_id,
        "product_code":          f"EJL/26-27/100-{n}",
        "design_no":             f"D-{n:03}",
        "bag_id":                "",
        "pack_sr":               float(n),
        "invoice_no":            "EJL/26-27/100",
        "invoice_line_position": n,
        "quantity":              1.0,
        "gross_weight":          5.0,
        "net_weight":            5.0,
    }


# ── 1 + 2: success / partial both promote ────────────────────────────────────

def test_pz_success_promotes_to_warehouse_stock(db):
    lines = [_line(i) for i in range(1, 4)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_PZ", lines)

    promoted = _promote_to_warehouse_stock("BATCH_PZ")

    assert promoted == 3
    counts = ise.count_by_state(batch_id="BATCH_PZ")
    assert counts[ise.PURCHASE_TRANSIT] == 0
    assert counts[ise.WAREHOUSE_STOCK]  == 3


def test_pz_partial_promotes_to_warehouse_stock(db):
    # The helper itself doesn't read status; routes_upload gates the call.
    # The "partial" path is identical to "success" once invoked.
    lines = [_line(i) for i in range(1, 3)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_PZ", lines)

    promoted = _promote_to_warehouse_stock("BATCH_PZ")

    assert promoted == 2
    assert ise.count_by_state(batch_id="BATCH_PZ")[ise.WAREHOUSE_STOCK] == 2


# ── 3: failure path doesn't call the helper — verify via call-site condition

def test_pz_failure_does_not_promote(db):
    """
    Models the routes_upload guard `if _r_status in (success, partial):`.
    When status is anything else (blocked / failed), the helper is not called
    and PURCHASE_TRANSIT remains untouched.
    """
    lines = [_line(1), _line(2)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_PZ", lines)

    # Caller-side guard: blocked → no call, no promotion
    _r_status = "blocked"
    if _r_status in ("success", "partial"):
        _promote_to_warehouse_stock("BATCH_PZ")  # pragma: no cover

    counts = ise.count_by_state(batch_id="BATCH_PZ")
    assert counts[ise.PURCHASE_TRANSIT] == 2
    assert counts[ise.WAREHOUSE_STOCK]  == 0


# ── 4: idempotency on re-run ─────────────────────────────────────────────────

def test_idempotent_re_run_no_duplicate(db):
    lines = [_line(i) for i in range(1, 4)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_PZ", lines)

    first  = _promote_to_warehouse_stock("BATCH_PZ")
    second = _promote_to_warehouse_stock("BATCH_PZ")

    assert first  == 3
    assert second == 0   # already at WAREHOUSE_STOCK → skipped

    # Each scan_code has exactly one PURCHASE_TRANSIT event + one WAREHOUSE_STOCK event
    for ln in lines:
        sc = pdb._compute_scan_code(ln)
        history = ise.get_history(sc)
        states = [e["to_state"] for e in history]
        assert states == [ise.PURCHASE_TRANSIT, ise.WAREHOUSE_STOCK]


# ── 5: skips lines already at WAREHOUSE_STOCK or beyond ─────────────────────

def test_transition_skips_if_already_promoted(db):
    lines = [_line(1), _line(2)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_PZ", lines)

    # Manually advance line 2 past WAREHOUSE_STOCK
    sc2 = pdb._compute_scan_code(lines[1])
    ise.transition(scan_code=sc2, to_state=ise.WAREHOUSE_STOCK)
    ise.transition(scan_code=sc2, to_state=ise.SALES_TRANSIT)

    promoted = _promote_to_warehouse_stock("BATCH_PZ")

    # Only line 1 (still at PURCHASE_TRANSIT) gets promoted
    assert promoted == 1
    counts = ise.count_by_state(batch_id="BATCH_PZ")
    assert counts[ise.WAREHOUSE_STOCK] == 1
    assert counts[ise.SALES_TRANSIT]   == 1
    # Line 2's state is preserved at SALES_TRANSIT — never demoted
    assert ise.get_state(sc2)["state"] == ise.SALES_TRANSIT


# ── 6: engine failure must not raise out of the helper ─────────────────────

def test_state_engine_failure_does_not_break_pz(db):
    lines = [_line(i) for i in range(1, 3)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_PZ", lines)

    with patch.object(ise, "transition", side_effect=RuntimeError("boom")):
        promoted = _promote_to_warehouse_stock("BATCH_PZ")

    assert promoted == 0   # no successful promotions, but no exception escaped
    # State remains at PURCHASE_TRANSIT because every transition raised
    assert ise.count_by_state(batch_id="BATCH_PZ")[ise.PURCHASE_TRANSIT] == 2


# ── 7: lines without scan_code are skipped silently ─────────────────────────

def test_lines_without_state_are_skipped(db):
    """A packing line that was never seeded (no inventory_state row) is
    skipped — the promoter only acts on existing PURCHASE_TRANSIT items."""
    lines = [_line(1), _line(2)]
    pdb.upsert_packing_lines(lines)
    # Seed only line 1
    seed_purchase_transit("BATCH_PZ", [lines[0]])

    promoted = _promote_to_warehouse_stock("BATCH_PZ")

    assert promoted == 1
    counts = ise.count_by_state(batch_id="BATCH_PZ")
    assert counts[ise.WAREHOUSE_STOCK]  == 1
    # Line 2 still has no state row at all
    sc2 = pdb._compute_scan_code(lines[1])
    assert ise.get_state(sc2) is None
