"""A dedup repair may remove a duplicate row. It may not remove an operator's decision.

PR #1312 put the allocation columns on ``packing_lines``: an operator binding a
line to a customer now lives ON the row. ``quarantine_duplicates`` removes surplus
rows and picks the survivor by generic field-richness, which knows nothing about
who decided what -- so the copy carrying the binding can be the copy that goes.

The repair is not allowed to decide an allocation. It defers the group and says so.
"""
from __future__ import annotations

import sqlite3

from app.services.packing_dedupe_repair import (
    find_duplicate_groups,
    quarantine_duplicates,
)

CLOCK = lambda: "2026-08-22T00:00:00+00:00"  # noqa: E731


def _db():
    con = sqlite3.connect(":memory:")
    con.execute("""CREATE TABLE packing_documents (
        id TEXT PRIMARY KEY, batch_id TEXT, doc_stage TEXT,
        source_file_hash TEXT, withdrawn_reason TEXT DEFAULT '')""")
    con.execute("""CREATE TABLE packing_lines (
        id TEXT PRIMARY KEY, packing_document_id TEXT, batch_id TEXT,
        invoice_no TEXT, product_code TEXT, design_no TEXT, quantity REAL,
        pack_sr REAL, bag_id TEXT, tray_id TEXT, batch_no TEXT, scan_code TEXT,
        allocation_source TEXT DEFAULT '',
        allocated_customer_id TEXT DEFAULT '')""")
    return con


def _doc(con, doc_id, batch="B1", stage="final", file_hash="h"):
    con.execute("INSERT INTO packing_documents VALUES (?,?,?,?,'')",
                (doc_id, batch, stage, file_hash))


def _line(con, line_id, doc_id, *, pack_sr=None, source="", customer="",
          rich=False):
    """``rich`` = the per-invoice form: it carries the serial, the bag and the
    tray. The per-client form carries none of them."""
    con.execute("INSERT INTO packing_lines VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (line_id, doc_id, "B1", "EJL/26-27/178", "EJL/26-27/178-1",
                 "JR08007", 1.0, pack_sr,
                 "BAG-7" if rich else "", "TRAY-2" if rich else "",
                 "BN-9" if rich else "",
                 "c|d", source, customer))


def _bound_surplus():
    """The richer document wins on richness; the binding sits on the loser.

    This is not a contrived arrangement: the per-invoice form carries pack_sr
    and reads richer, while an operator allocating from the per-client packing
    list binds the row in front of them.
    """
    con = _db()
    _doc(con, "dA", file_hash="hA")
    _doc(con, "dB", file_hash="hB")
    _line(con, "L1", "dA", pack_sr=1.0, rich=True)         # richer, unbound
    _line(con, "L2", "dB", source="operator_allocated",
          customer="4321")                                  # the decision
    return con


def test_the_bound_row_is_the_one_richness_would_discard():
    """Guards the premise. The binding partially defends itself -- the two
    allocation columns are populated fields, so a bound row scores higher --
    but that is an accident of field counting, not a rule: a richer document
    still outranks it. If richness ever kept L2, this test stops meaning
    anything and would silently pass forever."""
    con = _bound_surplus()
    group = find_duplicate_groups(con)[0]
    assert group["kept"]["id"] == "L1"
    assert [r["id"] for r in group["surplus"]] == ["L2"]


def test_a_group_whose_surplus_carries_a_binding_is_reported_as_such():
    con = _bound_surplus()
    group = find_duplicate_groups(con)[0]
    assert group["operator_bound_surplus"] == ["L2"]


def test_the_repair_refuses_to_delete_an_operator_binding():
    con = _bound_surplus()
    report = quarantine_duplicates(con, repair_ref="r", reason="dup",
                                   clock=CLOCK, dry_run=False)
    assert report["quarantined"] == 0
    assert report["deferred_operator_bound"] == ["L2"]
    assert report["deferred_groups"] == 1
    live = {r[0] for r in con.execute("SELECT id FROM packing_lines")}
    assert live == {"L1", "L2"}


def test_an_identical_binding_on_both_copies_is_not_a_conflict():
    """Same customer on both rows: quarantining one loses nothing, so the
    repair proceeds. A deferral rule that never proceeds is a disabled repair."""
    con = _db()
    _doc(con, "dA", file_hash="hA")
    _doc(con, "dB", file_hash="hB")
    _line(con, "L1", "dA", pack_sr=1.0, rich=True,
          source="operator_allocated", customer="4321")
    _line(con, "L2", "dB", source="operator_allocated", customer="4321")
    report = quarantine_duplicates(con, repair_ref="r", reason="dup",
                                   clock=CLOCK, dry_run=False)
    assert report["quarantined"] == 1
    assert report["deferred_operator_bound"] == []


def test_a_binding_only_on_the_survivor_is_not_a_conflict():
    """Nothing is lost when the copy that goes carried no decision."""
    con = _db()
    _doc(con, "dA", file_hash="hA")
    _doc(con, "dB", file_hash="hB")
    _line(con, "L1", "dA", pack_sr=1.0, rich=True,
          source="operator_allocated", customer="4321")
    _line(con, "L2", "dB")
    report = quarantine_duplicates(con, repair_ref="r", reason="dup",
                                   clock=CLOCK, dry_run=False)
    assert report["quarantined"] == 1
    assert report["deferred_operator_bound"] == []


def test_a_supplier_suggestion_is_not_a_decision():
    """``supplier_preallocated`` is the supplier's claim, not an operator's
    commitment. Deferring on it would stall every repair on advisory data."""
    con = _db()
    _doc(con, "dA", file_hash="hA")
    _doc(con, "dB", file_hash="hB")
    _line(con, "L1", "dA", pack_sr=1.0, rich=True)
    _line(con, "L2", "dB", source="supplier_preallocated", customer="4321")
    report = quarantine_duplicates(con, repair_ref="r", reason="dup",
                                   clock=CLOCK, dry_run=False)
    assert report["quarantined"] == 1
    assert report["deferred_operator_bound"] == []


def test_a_schema_without_the_allocation_columns_still_repairs():
    """The repair predates the columns and must not require them."""
    con = sqlite3.connect(":memory:")
    con.execute("""CREATE TABLE packing_documents (
        id TEXT PRIMARY KEY, batch_id TEXT, doc_stage TEXT,
        source_file_hash TEXT, withdrawn_reason TEXT DEFAULT '')""")
    con.execute("""CREATE TABLE packing_lines (
        id TEXT PRIMARY KEY, packing_document_id TEXT, batch_id TEXT,
        invoice_no TEXT, product_code TEXT, design_no TEXT, quantity REAL,
        pack_sr REAL, bag_id TEXT, scan_code TEXT)""")
    _doc(con, "dA", file_hash="hA")
    _doc(con, "dB", file_hash="hB")
    for lid, doc, sr in (("L1", "dA", 1.0), ("L2", "dB", None)):
        con.execute("INSERT INTO packing_lines VALUES (?,?,?,?,?,?,?,?,'',?)",
                    (lid, doc, "B1", "EJL/26-27/178", "EJL/26-27/178-1",
                     "JR08007", 1.0, sr, "c|d"))
    report = quarantine_duplicates(con, repair_ref="r", reason="dup",
                                   clock=CLOCK, dry_run=False)
    assert report["quarantined"] == 1
    assert report["deferred_operator_bound"] == []
