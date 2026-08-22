"""The repair and its reversal, exercised by the same tests.

A reversal path nobody runs is a reversal path nobody has. Every test that
quarantines also restores and asserts the table is back where it started.
"""
from __future__ import annotations

import sqlite3

import pytest

from app.services.packing_dedupe_repair import (
    find_duplicate_groups,
    quarantine_duplicates,
    restore,
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
        pack_sr REAL, bag_id TEXT, scan_code TEXT)""")
    return con


def _doc(con, doc_id, batch, stage="final", file_hash="h"):
    con.execute("INSERT INTO packing_documents VALUES (?,?,?,?,'')",
                (doc_id, batch, stage, file_hash))


def _line(con, line_id, doc_id, batch, *, pack_sr=None, qty=1.0,
          design="JR08007", code="EJL/26-27/178-1", inv="EJL/26-27/178"):
    con.execute("INSERT INTO packing_lines VALUES (?,?,?,?,?,?,?,?,'',?)",
                (line_id, doc_id, batch, inv, code, design, qty, pack_sr,
                 "%s|%s" % (code, design)))


def _two_forms_of_one_line():
    """The production shape: same goods, two files, one carries pack_sr."""
    con = _db()
    _doc(con, "dA", "B1", file_hash="hA")
    _doc(con, "dB", "B1", file_hash="hB")
    _line(con, "L1", "dA", "B1", pack_sr=1.0)   # per-invoice form, richer
    _line(con, "L2", "dB", "B1", pack_sr=None)  # per-client form
    return con


def test_the_duplicate_is_found():
    con = _two_forms_of_one_line()
    groups = find_duplicate_groups(con)
    assert len(groups) == 1
    assert len(groups[0]["surplus"]) == 1


def test_the_richer_row_survives_not_the_first():
    """Insertion order must not decide which record of the goods we keep.
    The per-invoice form carries pack_sr and says strictly more."""
    con = _two_forms_of_one_line()
    group = find_duplicate_groups(con)[0]
    assert group["kept"]["id"] == "L1"
    assert group["surplus"][0]["id"] == "L2"


def test_dry_run_writes_nothing():
    con = _two_forms_of_one_line()
    before = con.execute("SELECT COUNT(*) FROM packing_lines").fetchone()[0]
    report = quarantine_duplicates(con, repair_ref="r1", reason="dup", clock=CLOCK)
    assert report["dry_run"] and report["quarantined"] == 0
    assert con.execute("SELECT COUNT(*) FROM packing_lines").fetchone()[0] == before


def test_quarantine_then_restore_returns_the_table_to_where_it_started():
    """THE reversal proof. Not 'a reversal exists' -- a reversal that ran."""
    con = _two_forms_of_one_line()
    before = con.execute(
        "SELECT id, packing_document_id, quantity, pack_sr FROM packing_lines "
        "ORDER BY id").fetchall()

    report = quarantine_duplicates(con, repair_ref="r1", reason="dup",
                                   clock=CLOCK, dry_run=False)
    assert report["quarantined"] == 1
    assert con.execute("SELECT COUNT(*) FROM packing_lines").fetchone()[0] == 1

    back = restore(con, repair_ref="r1", clock=CLOCK)
    assert back["restored"] == 1
    after = con.execute(
        "SELECT id, packing_document_id, quantity, pack_sr FROM packing_lines "
        "ORDER BY id").fetchall()
    assert after == before


def test_nothing_is_ever_deleted_outright():
    con = _two_forms_of_one_line()
    quarantine_duplicates(con, repair_ref="r1", reason="dup", clock=CLOCK,
                          dry_run=False)
    held = con.execute("SELECT row_json FROM packing_line_quarantine").fetchall()
    assert len(held) == 1 and "L2" in held[0][0]


def test_restore_is_idempotent():
    con = _two_forms_of_one_line()
    quarantine_duplicates(con, repair_ref="r1", reason="d", clock=CLOCK,
                          dry_run=False)
    assert restore(con, repair_ref="r1", clock=CLOCK)["restored"] == 1
    assert restore(con, repair_ref="r1", clock=CLOCK)["restored"] == 0


def test_an_advance_final_pair_is_never_quarantined():
    """ADVERSARY: the destructive mistake. Same bytes under two stages is one
    document ingested twice, and both records are legitimate -- quarantining the
    advance one destroys the early view of the shipment."""
    con = _db()
    _doc(con, "dAdv", "ADVANCE_x", stage="advance", file_hash="same")
    _doc(con, "dFin", "SHIP_x", stage="final", file_hash="same")
    _line(con, "L1", "dAdv", "ADVANCE_x")
    _line(con, "L2", "dFin", "SHIP_x")
    assert find_duplicate_groups(con) == []
    report = quarantine_duplicates(con, repair_ref="r", reason="d", clock=CLOCK,
                                   dry_run=False)
    assert report["quarantined"] == 0
    assert con.execute("SELECT COUNT(*) FROM packing_lines").fetchone()[0] == 2


def test_a_genuine_lot_is_never_quarantined():
    """Three identical rings in one document are three lines. The ordinal keeps
    them apart, so they never collide and never look like duplicates."""
    con = _db()
    _doc(con, "d1", "B1")
    for i in range(3):
        _line(con, "L%d" % i, "d1", "B1", pack_sr=float(i + 1))
    assert find_duplicate_groups(con) == []


def test_an_already_withdrawn_document_is_out_of_scope():
    con = _two_forms_of_one_line()
    con.execute("UPDATE packing_documents SET withdrawn_reason='earlier' "
                "WHERE id='dB'")
    assert find_duplicate_groups(con) == []


@pytest.mark.parametrize("ref", ["r1", "r2"])
def test_repairs_are_independent(ref):
    con = _two_forms_of_one_line()
    quarantine_duplicates(con, repair_ref=ref, reason="d", clock=CLOCK,
                          dry_run=False)
    assert restore(con, repair_ref="other", clock=CLOCK)["restored"] == 0
    assert restore(con, repair_ref=ref, clock=CLOCK)["restored"] == 1
