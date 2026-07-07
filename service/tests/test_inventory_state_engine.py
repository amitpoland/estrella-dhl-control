"""
test_inventory_state_engine.py — Lifecycle state model for PZ inventory.

Required coverage:
  1. test_state_transition_pz_to_stock
  2. test_state_transition_invoice_to_sales_transit
  3. test_state_single_location_only          (one item is in exactly one state)
  4. test_no_duplicate_stock_across_states    (state queries return disjoint sets)

Plus thin guards:
  - illegal transition raises
  - terminal state (CLOSED) blocks further transitions
  - get_history records every transition
"""
from __future__ import annotations

import pytest

from app.services import warehouse_db as wdb
from app.services import inventory_state_engine as ise


@pytest.fixture()
def db(tmp_path):
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    return tmp_path


# ── 1. PURCHASE_TRANSIT → WAREHOUSE_STOCK ────────────────────────────────────

def test_state_transition_pz_to_stock(db):
    sc = "EJL/26-27/100-1|sr1|D-001"
    ise.transition(scan_code=sc, to_state=ise.PURCHASE_TRANSIT,
                   product_code="EJL/26-27/100-1", design_no="D-001",
                   batch_id="B1")
    row = ise.transition(scan_code=sc, to_state=ise.WAREHOUSE_STOCK)
    assert row["state"] == ise.WAREHOUSE_STOCK
    assert row["scan_code"] == sc

    history = ise.get_history(sc)
    assert [(e["from_state"], e["to_state"]) for e in history] == [
        ("", ise.PURCHASE_TRANSIT),
        (ise.PURCHASE_TRANSIT, ise.WAREHOUSE_STOCK),
    ]
    assert history[0]["trigger"] == "pz_generated"
    assert history[1]["trigger"] == "warehouse_receive"


# ── 2. WAREHOUSE_STOCK → SALES_TRANSIT ───────────────────────────────────────

def test_state_transition_invoice_to_sales_transit(db):
    sc = "EJL/26-27/200-2|sr2|D-002"
    ise.transition(scan_code=sc, to_state=ise.PURCHASE_TRANSIT, batch_id="B2")
    ise.transition(scan_code=sc, to_state=ise.WAREHOUSE_STOCK)
    row = ise.transition(scan_code=sc, to_state=ise.SALES_TRANSIT)
    assert row["state"] == ise.SALES_TRANSIT
    last_event = ise.get_history(sc)[-1]
    assert last_event["from_state"] == ise.WAREHOUSE_STOCK
    assert last_event["to_state"]   == ise.SALES_TRANSIT
    assert last_event["trigger"]    == "invoice_issued"


# ── 3. Single state per item ─────────────────────────────────────────────────

def test_state_single_location_only(db):
    sc = "SOLO|sr1|D-X"
    ise.transition(scan_code=sc, to_state=ise.PURCHASE_TRANSIT, batch_id="B3")
    ise.transition(scan_code=sc, to_state=ise.WAREHOUSE_STOCK)
    ise.transition(scan_code=sc, to_state=ise.SALES_TRANSIT)

    # Exactly one row in inventory_state, exactly one state
    in_purchase  = ise.list_by_state(ise.PURCHASE_TRANSIT, batch_id="B3")
    in_warehouse = ise.list_by_state(ise.WAREHOUSE_STOCK,  batch_id="B3")
    in_sales     = ise.list_by_state(ise.SALES_TRANSIT,    batch_id="B3")
    in_closed    = ise.list_by_state(ise.CLOSED,           batch_id="B3")

    assert [r["scan_code"] for r in in_purchase]  == []
    assert [r["scan_code"] for r in in_warehouse] == []
    assert [r["scan_code"] for r in in_sales]     == [sc]
    assert [r["scan_code"] for r in in_closed]    == []

    # The item's row carries its current state, not history
    cur = ise.get_state(sc)
    assert cur["state"] == ise.SALES_TRANSIT


# ── 4. Disjoint state sets — no item appears in two states ──────────────────

def test_no_duplicate_stock_across_states(db):
    items = [
        ("A|sr1|DA", ise.PURCHASE_TRANSIT, ["P"]),
        ("B|sr1|DB", ise.WAREHOUSE_STOCK,  ["P", "W"]),
        ("C|sr1|DC", ise.SALES_TRANSIT,    ["P", "W", "S"]),
        ("D|sr1|DD", ise.CLOSED,           ["P", "W", "S", "C"]),
    ]
    next_state = {
        "P": ise.PURCHASE_TRANSIT, "W": ise.WAREHOUSE_STOCK,
        "S": ise.SALES_TRANSIT,    "C": ise.CLOSED,
    }
    for sc, _final, path in items:
        for step in path:
            ise.transition(scan_code=sc, to_state=next_state[step], batch_id="B4")

    # Each item appears in exactly one bucket
    buckets = {s: {r["scan_code"] for r in ise.list_by_state(s, batch_id="B4")}
               for s in ise.STATES}

    assert buckets[ise.PURCHASE_TRANSIT] == {"A|sr1|DA"}
    assert buckets[ise.WAREHOUSE_STOCK]  == {"B|sr1|DB"}
    assert buckets[ise.SALES_TRANSIT]    == {"C|sr1|DC"}
    assert buckets[ise.CLOSED]           == {"D|sr1|DD"}

    # No scan_code appears in more than one state
    seen: set[str] = set()
    for s in ise.STATES:
        overlap = buckets[s] & seen
        assert overlap == set(), f"scan_code in two states: {overlap}"
        seen |= buckets[s]

    # Total tracked = 4, sum of disjoint counts = 4
    counts = ise.count_by_state(batch_id="B4")
    assert sum(counts.values()) == 4
    assert counts == {
        ise.PURCHASE_TRANSIT:      1, ise.WAREHOUSE_STOCK:       1,
        ise.SALES_TRANSIT:         1, ise.CLOSED:                1,
        ise.DIRECT_DISPATCH_READY: 0, ise.CLIENT_DISPATCHED:     0,
        ise.SAMPLE_OUT:            0,  # Phase B.1 — added with Sample-out activation
        ise.RETURNED_FROM_CLIENT:  0,  # Phase B.2 — added with Returns activation
        ise.RETURNED_TO_PRODUCER:  0,  # Phase B.2 — added with Returns activation
        ise.WRITTEN_OFF:           0,  # Returns QC Disposition — write-off terminal
    }


# ── Guards ───────────────────────────────────────────────────────────────────

def test_illegal_transition_raises(db):
    sc = "ILLEGAL|sr1|DX"
    ise.transition(scan_code=sc, to_state=ise.PURCHASE_TRANSIT, batch_id="BX")
    # PURCHASE_TRANSIT → SALES_TRANSIT is not legal (must go through WAREHOUSE_STOCK)
    with pytest.raises(ValueError, match="Illegal transition"):
        ise.transition(scan_code=sc, to_state=ise.SALES_TRANSIT)


def test_terminal_state_blocks_further_transitions(db):
    sc = "TERM|sr1|DX"
    for s in (ise.PURCHASE_TRANSIT, ise.WAREHOUSE_STOCK, ise.SALES_TRANSIT, ise.CLOSED):
        ise.transition(scan_code=sc, to_state=s, batch_id="BT")
    with pytest.raises(ValueError, match="Illegal transition"):
        ise.transition(scan_code=sc, to_state=ise.PURCHASE_TRANSIT)


def test_unknown_state_raises(db):
    with pytest.raises(ValueError, match="Unknown to_state"):
        ise.transition(scan_code="X", to_state="BOGUS_STATE")


def test_initial_state_must_be_purchase_transit(db):
    # First transition for a scan_code can only go to PURCHASE_TRANSIT
    with pytest.raises(ValueError, match="Illegal transition"):
        ise.transition(scan_code="NEW|sr1|D", to_state=ise.WAREHOUSE_STOCK)
