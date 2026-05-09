"""
test_inventory_state_direct_dispatch.py — DIRECT_DISPATCH_READY lifecycle.

Pins the contract for the new direct-dispatch path added so DHL/agency-to-
client flows can issue Proforma without forcing warehouse stock promotion.

Coverage
--------
  1. PURCHASE_TRANSIT → DIRECT_DISPATCH_READY succeeds with full evidence
  2. Same transition fails when operator missing
  3. Same transition fails when customer_allocation missing
  4. Same transition fails when customs_cleared is False
  5. Same transition fails when no RECEIVE movement event exists
  6. RECEIVE scan alone does NOT promote inventory_state
  7. DIRECT_DISPATCH_READY → CLIENT_DISPATCHED legal
  8. CLIENT_DISPATCHED → CLOSED legal
  9. Existing warehouse-stock chain still works
  10. PROFORMA_ELIGIBLE_STATES pins the eligible set
"""
from __future__ import annotations

import pytest

from app.services import warehouse_db as wdb
from app.services import inventory_state_engine as ise


@pytest.fixture()
def db(tmp_path):
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    return tmp_path


def _seed_pl(scan_code: str, batch_id: str = "B-DIRECT") -> None:
    """Seed a packing line so warehouse_db.record_scan accepts the code."""
    # warehouse_db.record_scan looks up scan_code via packing_db, but for the
    # transition() evidence check we only need a row in
    # inventory_movement_events. We insert a RECEIVE event directly via the
    # warehouse_db connection helper.
    import sqlite3, uuid
    from datetime import datetime, timezone
    con = sqlite3.connect(str(wdb._db_path))
    con.execute(
        """INSERT INTO inventory_movement_events
           (id, batch_id, scan_code, action, from_location, to_location,
            operator, event_time, note, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (str(uuid.uuid4()), batch_id, scan_code, "RECEIVE",
         "", "MAIN-WH-INBOUND", "amit",
         datetime.now(timezone.utc).isoformat(), "",
         datetime.now(timezone.utc).isoformat()),
    )
    con.commit()
    con.close()


def _seed_purchase(scan_code: str, batch_id: str = "B-DIRECT") -> None:
    ise.transition(scan_code=scan_code, to_state=ise.PURCHASE_TRANSIT,
                   batch_id=batch_id)


# ── 1. Happy path ────────────────────────────────────────────────────────────

def test_direct_dispatch_ready_with_full_evidence(db):
    sc = "EJL/26-27/123-2|sr1|PND"
    _seed_purchase(sc)
    _seed_pl(sc)

    row = ise.transition(
        scan_code=sc, to_state=ise.DIRECT_DISPATCH_READY,
        operator="amit",
        customer_allocation="Clear-Diamonds Ltd",
        customs_cleared=True,
    )
    assert row["state"] == ise.DIRECT_DISPATCH_READY

    history = ise.get_history(sc)
    assert history[-1]["from_state"] == ise.PURCHASE_TRANSIT
    assert history[-1]["to_state"]   == ise.DIRECT_DISPATCH_READY
    assert history[-1]["trigger"]    == "direct_dispatch_marked"


# ── 2-5. Evidence gates ─────────────────────────────────────────────────────

@pytest.mark.parametrize("missing_field, kwargs, fragment", [
    ("operator",
     dict(operator="", customer_allocation="X", customs_cleared=True),
     "operator"),
    ("customer_allocation",
     dict(operator="amit", customer_allocation="", customs_cleared=True),
     "customer_allocation"),
    ("customs_cleared",
     dict(operator="amit", customer_allocation="X", customs_cleared=False),
     "customs_cleared"),
])
def test_direct_dispatch_requires_field(db, missing_field, kwargs, fragment):
    sc = f"EJL/26-27/X|sr1|D-{missing_field}"
    _seed_purchase(sc)
    _seed_pl(sc)
    with pytest.raises(ValueError, match=fragment):
        ise.transition(scan_code=sc, to_state=ise.DIRECT_DISPATCH_READY,
                       **kwargs)
    # State must be unchanged.
    assert ise.get_state(sc)["state"] == ise.PURCHASE_TRANSIT


def test_direct_dispatch_requires_receive_movement_event(db):
    sc = "EJL/26-27/X|sr1|NO_MOVE"
    _seed_purchase(sc)
    # NB: no _seed_pl — there is no RECEIVE movement event.
    with pytest.raises(ValueError, match="RECEIVE movement event"):
        ise.transition(
            scan_code=sc, to_state=ise.DIRECT_DISPATCH_READY,
            operator="amit", customer_allocation="X", customs_cleared=True,
        )
    assert ise.get_state(sc)["state"] == ise.PURCHASE_TRANSIT


# ── 6. RECEIVE scan does not auto-promote ───────────────────────────────────

def test_receive_event_alone_does_not_promote(db):
    """Inserting a RECEIVE movement event must NOT mutate inventory_state.
    State changes only via inventory_state_engine.transition()."""
    sc = "EJL/26-27/X|sr1|RECEIVE_ONLY"
    _seed_purchase(sc)
    _seed_pl(sc)
    assert ise.get_state(sc)["state"] == ise.PURCHASE_TRANSIT


# ── 7. DIRECT_DISPATCH_READY → CLIENT_DISPATCHED ────────────────────────────

def test_direct_dispatch_ready_to_client_dispatched(db):
    sc = "EJL/26-27/X|sr1|TO_DISPATCH"
    _seed_purchase(sc)
    _seed_pl(sc)
    ise.transition(scan_code=sc, to_state=ise.DIRECT_DISPATCH_READY,
                   operator="amit", customer_allocation="X",
                   customs_cleared=True)
    row = ise.transition(scan_code=sc, to_state=ise.CLIENT_DISPATCHED)
    assert row["state"] == ise.CLIENT_DISPATCHED
    assert ise.get_history(sc)[-1]["trigger"] == "client_dispatched"


# ── 8. CLIENT_DISPATCHED → CLOSED ───────────────────────────────────────────

def test_client_dispatched_to_closed(db):
    sc = "EJL/26-27/X|sr1|TO_CLOSE"
    _seed_purchase(sc)
    _seed_pl(sc)
    ise.transition(scan_code=sc, to_state=ise.DIRECT_DISPATCH_READY,
                   operator="amit", customer_allocation="X",
                   customs_cleared=True)
    ise.transition(scan_code=sc, to_state=ise.CLIENT_DISPATCHED)
    row = ise.transition(scan_code=sc, to_state=ise.CLOSED)
    assert row["state"] == ise.CLOSED


# ── 9. Existing warehouse chain still works ─────────────────────────────────

def test_warehouse_stock_chain_unchanged(db):
    sc = "EJL/26-27/X|sr1|UNCHANGED"
    ise.transition(scan_code=sc, to_state=ise.PURCHASE_TRANSIT, batch_id="B")
    ise.transition(scan_code=sc, to_state=ise.WAREHOUSE_STOCK)
    ise.transition(scan_code=sc, to_state=ise.SALES_TRANSIT)
    ise.transition(scan_code=sc, to_state=ise.CLOSED)
    assert ise.get_state(sc)["state"] == ise.CLOSED


def test_warehouse_stock_does_not_require_direct_dispatch_evidence(db):
    """Regression: the evidence gate must fire ONLY for DIRECT_DISPATCH_READY,
    never for the existing PURCHASE_TRANSIT → WAREHOUSE_STOCK path."""
    sc = "EJL/26-27/X|sr1|NO_EVIDENCE_NEEDED"
    ise.transition(scan_code=sc, to_state=ise.PURCHASE_TRANSIT, batch_id="B")
    # No operator, no customer, no customs — must succeed for warehouse stock.
    row = ise.transition(scan_code=sc, to_state=ise.WAREHOUSE_STOCK)
    assert row["state"] == ise.WAREHOUSE_STOCK


# ── 10. Eligible-state set pinned ───────────────────────────────────────────

def test_proforma_eligible_states_pinned():
    assert ise.PROFORMA_ELIGIBLE_STATES == frozenset({
        ise.WAREHOUSE_STOCK,
        ise.DIRECT_DISPATCH_READY,
        ise.CLIENT_DISPATCHED,
    })
    # PURCHASE_TRANSIT must NOT be eligible.
    assert ise.PURCHASE_TRANSIT not in ise.PROFORMA_ELIGIBLE_STATES
    assert ise.SALES_TRANSIT    not in ise.PROFORMA_ELIGIBLE_STATES
    assert ise.CLOSED           not in ise.PROFORMA_ELIGIBLE_STATES


# ── Illegal transitions still blocked ───────────────────────────────────────

def test_purchase_transit_cannot_skip_to_client_dispatched(db):
    sc = "EJL/26-27/X|sr1|SKIP"
    _seed_purchase(sc)
    with pytest.raises(ValueError, match="Illegal transition"):
        ise.transition(scan_code=sc, to_state=ise.CLIENT_DISPATCHED)


def test_warehouse_stock_cannot_jump_to_direct_dispatch_ready(db):
    """Once at WAREHOUSE_STOCK, the item is in the stock pool. Routing it
    to DIRECT_DISPATCH_READY is not a supported flow — keep the lifecycle
    simple. Use SALES_TRANSIT for that case."""
    sc = "EJL/26-27/X|sr1|WS_TO_DD"
    ise.transition(scan_code=sc, to_state=ise.PURCHASE_TRANSIT, batch_id="B")
    ise.transition(scan_code=sc, to_state=ise.WAREHOUSE_STOCK)
    with pytest.raises(ValueError, match="Illegal transition"):
        ise.transition(scan_code=sc, to_state=ise.DIRECT_DISPATCH_READY,
                       operator="amit", customer_allocation="X",
                       customs_cleared=True)
