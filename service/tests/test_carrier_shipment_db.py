"""
test_carrier_shipment_db.py — SQLite registry tests.

Required coverage:
  1. ``init_db`` creates ``carrier_shipments`` and
     ``carrier_shipment_transitions`` tables.
  2. ``upsert_shipment`` inserts a new row with a fresh uuid and
     returns it.
  3. Composite uniqueness on ``(carrier, awb)`` — second upsert with
     the same pair updates instead of duplicating.
  4. ``get_by_awb`` and ``get_by_id`` round-trip the row.
  5. ``get_by_batch`` returns all rows for a batch.
  6. ``list_by_state`` and ``count_by_state`` return correct values.
  7. ``record_transition`` is append-only — three calls write three
     rows.
  8. Unknown carrier and unknown state raise ValueError.
  9. The DB layer does NOT enforce state-machine legality (that's the
     state engine's job) — illegal transitions can still be recorded.
"""
from __future__ import annotations

import sqlite3

import pytest

from app.services.carrier import carrier_shipment_db as csdb
from app.services.carrier import carrier_state_engine as cse


@pytest.fixture()
def db(tmp_path):
    csdb.init_db(tmp_path / "carrier.db")
    return tmp_path / "carrier.db"


# ── 1. Init creates tables ──────────────────────────────────────────────────

def test_init_creates_tables(db):
    con = sqlite3.connect(str(db))
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('carrier_shipments','carrier_shipment_transitions')"
    ).fetchall()
    con.close()
    names = sorted(r[0] for r in rows)
    assert names == ["carrier_shipment_transitions", "carrier_shipments"]


# ── 2. Insert ───────────────────────────────────────────────────────────────

def test_upsert_inserts_new(db):
    row = csdb.upsert_shipment(
        carrier="dhl",
        awb="1234567890",
        state=cse.PRE_AWB,
        batch_id="B-100",
    )
    assert row["id"]
    assert row["carrier"] == "dhl"
    assert row["awb"] == "1234567890"
    assert row["state"] == cse.PRE_AWB
    assert row["batch_id"] == "B-100"
    assert row["created_at"]
    assert row["updated_at"]


# ── 3. Composite uniqueness ────────────────────────────────────────────────

def test_upsert_updates_same_carrier_awb(db):
    a = csdb.upsert_shipment(
        carrier="dhl", awb="AAA-1", state=cse.PRE_AWB, batch_id="B-1",
    )
    b = csdb.upsert_shipment(
        carrier="dhl", awb="AAA-1", state=cse.AWB_ISSUED,
        label_sha256="abc123", manifest_path="/tmp/m.json",
    )
    # Same id, updated state and label fields, batch_id preserved
    assert a["id"] == b["id"]
    assert b["state"] == cse.AWB_ISSUED
    assert b["label_sha256"] == "abc123"
    assert b["manifest_path"] == "/tmp/m.json"
    assert b["batch_id"] == "B-1"


def test_upsert_different_carrier_or_awb_creates_new_row(db):
    a = csdb.upsert_shipment(carrier="dhl", awb="X-1", state=cse.PRE_AWB)
    b = csdb.upsert_shipment(carrier="fedex", awb="X-1", state=cse.PRE_AWB)
    c = csdb.upsert_shipment(carrier="dhl", awb="X-2", state=cse.PRE_AWB)
    assert len({a["id"], b["id"], c["id"]}) == 3


# ── 4. Read-back ────────────────────────────────────────────────────────────

def test_get_by_awb_and_id(db):
    a = csdb.upsert_shipment(carrier="dhl", awb="AWB-RB",
                             state=cse.PRE_AWB, batch_id="B-RB")
    by_awb = csdb.get_by_awb("dhl", "AWB-RB")
    by_id = csdb.get_by_id(a["id"])
    assert by_awb["id"] == a["id"]
    assert by_id["awb"] == "AWB-RB"


def test_get_by_awb_missing_returns_none(db):
    assert csdb.get_by_awb("dhl", "nope") is None
    assert csdb.get_by_id("not-a-uuid") is None


# ── 5. get_by_batch ─────────────────────────────────────────────────────────

def test_get_by_batch(db):
    csdb.upsert_shipment(carrier="dhl", awb="B-A", state=cse.PRE_AWB, batch_id="X")
    csdb.upsert_shipment(carrier="dhl", awb="B-B", state=cse.PRE_AWB, batch_id="X")
    csdb.upsert_shipment(carrier="dhl", awb="B-C", state=cse.PRE_AWB, batch_id="Y")
    rows_x = csdb.get_by_batch("X")
    rows_y = csdb.get_by_batch("Y")
    assert sorted(r["awb"] for r in rows_x) == ["B-A", "B-B"]
    assert sorted(r["awb"] for r in rows_y) == ["B-C"]


# ── 6. list_by_state / count_by_state ───────────────────────────────────────

def test_list_and_count_by_state(db):
    csdb.upsert_shipment(carrier="dhl", awb="S-1", state=cse.PRE_AWB, batch_id="B")
    csdb.upsert_shipment(carrier="dhl", awb="S-2", state=cse.PRE_AWB, batch_id="B")
    csdb.upsert_shipment(carrier="dhl", awb="S-3", state=cse.LABEL_CREATED, batch_id="B")

    in_pre = csdb.list_by_state(cse.PRE_AWB, batch_id="B")
    in_lab = csdb.list_by_state(cse.LABEL_CREATED, batch_id="B")
    assert sorted(r["awb"] for r in in_pre) == ["S-1", "S-2"]
    assert sorted(r["awb"] for r in in_lab) == ["S-3"]

    counts = csdb.count_by_state(batch_id="B")
    assert counts[cse.PRE_AWB] == 2
    assert counts[cse.LABEL_CREATED] == 1
    assert counts[cse.DELIVERED] == 0
    # Counts cover every known state
    assert set(counts.keys()) == set(cse.STATES)


def test_list_by_state_unknown_state_raises(db):
    with pytest.raises(ValueError):
        csdb.list_by_state("garbage")


# ── 7. Append-only transitions ──────────────────────────────────────────────

def test_record_transition_appends(db):
    a = csdb.upsert_shipment(carrier="dhl", awb="T-1", state=cse.PRE_AWB)
    csdb.record_transition(shipment_id=a["id"], from_state="",
                           to_state=cse.PRE_AWB, reason="created")
    csdb.record_transition(shipment_id=a["id"], from_state=cse.PRE_AWB,
                           to_state=cse.AWB_ISSUED, reason="dhl-ok")
    csdb.record_transition(shipment_id=a["id"], from_state=cse.AWB_ISSUED,
                           to_state=cse.LABEL_CREATED)
    history = csdb.get_transitions(a["id"])
    assert [(r["from_state"], r["to_state"]) for r in history] == [
        ("", cse.PRE_AWB),
        (cse.PRE_AWB, cse.AWB_ISSUED),
        (cse.AWB_ISSUED, cse.LABEL_CREATED),
    ]


# ── 8. Validation ───────────────────────────────────────────────────────────

def test_upsert_unknown_carrier_raises(db):
    with pytest.raises(ValueError):
        csdb.upsert_shipment(carrier="usps", awb="X", state=cse.PRE_AWB)


def test_upsert_unknown_state_raises(db):
    with pytest.raises(ValueError):
        csdb.upsert_shipment(carrier="dhl", awb="X", state="garbage")


def test_upsert_blank_awb_raises(db):
    with pytest.raises(ValueError):
        csdb.upsert_shipment(carrier="dhl", awb="", state=cse.PRE_AWB)


def test_record_transition_unknown_to_state_raises(db):
    a = csdb.upsert_shipment(carrier="dhl", awb="V-1", state=cse.PRE_AWB)
    with pytest.raises(ValueError):
        csdb.record_transition(
            shipment_id=a["id"], from_state=cse.PRE_AWB, to_state="garbage",
        )


# ── 9. DB does NOT enforce state-machine legality ──────────────────────────

def test_db_does_not_enforce_legality(db):
    """
    The DB layer accepts any pair of valid states. Legality enforcement
    is the state engine's responsibility — this test pins that
    separation so it doesn't quietly drift.
    """
    a = csdb.upsert_shipment(carrier="dhl", awb="L-1", state=cse.PRE_AWB)
    # PRE_AWB → DELIVERED is illegal in the state engine, but the DB
    # accepts it because it doesn't validate.
    row = csdb.record_transition(
        shipment_id=a["id"],
        from_state=cse.PRE_AWB,
        to_state=cse.DELIVERED,
    )
    assert row["to_state"] == cse.DELIVERED
