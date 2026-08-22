"""The dedupe path itself, through the real upsert.

The unit tests prove the KEY is shape-invariant. This proves the thing that
actually caused the incident: ingesting the same commercial line from the
per-invoice form and then from the per-client form stores ONE group, while a
genuine lot keeps every one of its lines.

Absorb happens only across documents of the SAME stage — the classifier's
DUPLICATE rule, decidable mid-ingestion because it needs no totals. An
advance/final pair stores both records and is linked afterwards with its
variance (R17).
"""
from __future__ import annotations

import sqlite3

import pytest

import app.services.packing_db as packing_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "packing.db"
    packing_db.init_packing_db(path)
    monkeypatch.setattr(packing_db, "_db_path", path)
    con = sqlite3.connect(str(path))
    for doc_id, batch, stage, fhash in (
            ("dA", "B1", "final", "hashA"),
            ("dB", "B1", "final", "hashB"),
            ("dADV", "ADVANCE_x", "advance", "hashA"),
            ("dOTHER", "B2", "final", "hashC")):
        con.execute(
            "INSERT INTO packing_documents (id, batch_id, invoice_no, "
            "source_file_path, source_file_hash, parser_name, parser_version, "
            "extraction_status, doc_stage, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,'','')",
            (doc_id, batch, "EJL/26-27/178", doc_id + ".xls", fhash, "t", "1",
             "complete", stage))
    con.commit()
    con.close()
    return path


def _line(doc, batch="B1", *, pack_sr=None, design="JR08007", qty=1.0,
          invoice="EJL/26-27/178", code="EJL/26-27/178-1"):
    return {
        "packing_document_id": doc, "batch_id": batch,
        "invoice_no": invoice, "product_code": code,
        "design_no": design, "quantity": qty, "pack_sr": pack_sr,
        "bag_id": "", "invoice_line_position": None, "unit_price": 0.0,
    }


def _count(path, doc=None):
    con = sqlite3.connect(str(path))
    if doc:
        n = con.execute("SELECT COUNT(*) FROM packing_lines "
                        "WHERE packing_document_id=?", (doc,)).fetchone()[0]
    else:
        n = con.execute("SELECT COUNT(*) FROM packing_lines").fetchone()[0]
    con.close()
    return n


def test_the_two_supplier_forms_store_one_group(db):
    """THE incident, reproduced end to end and then prevented. Both documents
    are stage 'final' -- the classifier's DUPLICATE rule -- so the second form
    is absorbed."""
    packing_db.upsert_packing_lines([_line("dA", pack_sr=1.0)])
    assert _count(db) == 1
    packing_db.upsert_packing_lines([_line("dB", pack_sr=None)])
    assert _count(db) == 1, "the per-client form was stored as a second row"


def test_the_reverse_order_also_stores_one_group(db):
    packing_db.upsert_packing_lines([_line("dB", pack_sr=None)])
    packing_db.upsert_packing_lines([_line("dA", pack_sr=1.0)])
    assert _count(db) == 1


def test_a_genuine_lot_still_stores_every_line(db):
    """ADVERSARY: over-dedupe is the opposite failure and loses goods. Three
    identical rings in one file are three lines and must stay three."""
    packing_db.upsert_packing_lines(
        [_line("dA", pack_sr=float(i + 1)) for i in range(3)])
    assert _count(db) == 3


def test_a_genuine_lot_with_no_serials_still_stores_every_line(db):
    """L1, the pre-existing over-dedupe: with no serial the fallback key is
    identical for every lot line, and the old code matched them all to the
    first stored row. The multiplicity-aware fallback stores all three."""
    packing_db.upsert_packing_lines([_line("dA") for _ in range(3)])
    assert _count(db) == 3


def test_a_duplicate_lot_absorbs_to_the_same_multiplicity(db):
    """A lot of three re-ingested from another same-stage file stays three,
    not six -- and not zero."""
    packing_db.upsert_packing_lines(
        [_line("dA", pack_sr=float(i + 1)) for i in range(3)])
    packing_db.upsert_packing_lines([_line("dB") for _ in range(3)])
    assert _count(db) == 3
    assert _count(db, "dB") == 0


def test_re_ingesting_the_same_file_is_idempotent(db):
    lot = [_line("dA", pack_sr=float(i + 1)) for i in range(3)]
    packing_db.upsert_packing_lines(lot)
    packing_db.upsert_packing_lines(lot)
    assert _count(db) == 3


def test_an_advance_document_is_never_absorbed(db):
    """Different stage is NOT the duplicate rule. The advance record is a
    legitimate early view and both documents must exist -- withdrawal of either
    would destroy real history. They are linked, not merged."""
    packing_db.upsert_packing_lines([_line("dA", pack_sr=1.0)])
    packing_db.upsert_packing_lines([_line("dADV", batch="ADVANCE_x")])
    assert _count(db) == 2


def test_a_thin_line_is_never_absorbed_on_the_weak_key(db):
    """Neither invoice_no nor product_code: the key is design+quantity only,
    and two unrelated shipments can coincide there. Absorbing would eat a real
    line, so both are stored and left for human review."""
    thin_a = _line("dA", invoice="", code=None, design="JE01868")
    thin_b = _line("dOTHER", batch="B2", invoice="", code=None, design="JE01868")
    packing_db.upsert_packing_lines([thin_a])
    packing_db.upsert_packing_lines([thin_b])
    assert _count(db) == 2


def test_different_designs_are_never_collapsed(db):
    packing_db.upsert_packing_lines([
        _line("dA", design="JR08007"), _line("dA", design="JR08008")])
    assert _count(db) == 2


def test_the_key_is_persisted_group_shaped(db):
    packing_db.upsert_packing_lines([_line("dA", pack_sr=1.0)])
    con = sqlite3.connect(str(db))
    key = con.execute("SELECT packing_line_key FROM packing_lines").fetchone()[0]
    con.close()
    assert key == "EJL/26-27/178|EJL/26-27/178-1|JR08007|1"


def test_advance_final_link_carries_the_variance(db):
    """R17. Same bytes under two stages link -- and the link must CARRY the
    disagreement, never absorb it. The production pair extracted 24 rows as
    advance and 21 as final from identical bytes; a link that hid that would
    bury the parser defect."""
    packing_db.upsert_packing_lines(
        [_line("dA", pack_sr=float(i + 1)) for i in range(3)])          # 3 rows
    packing_db.upsert_packing_lines(
        [_line("dADV", batch="ADVANCE_x", design="JR0800%d" % i, qty=2.0)
         for i in range(6)])                                            # 6 rows
    made = packing_db.link_advance_final_documents()
    assert made == 1
    links = packing_db.advance_final_links()
    assert len(links) == 1
    link = links[0]
    assert link["kind"] == "ADVANCE_FINAL"
    assert link["line_count_variance"] == 3          # 6 vs 3
    assert link["total_variance"] == pytest.approx(9.0)   # 12.0 vs 3.0
    # and the advance document's batch now points at the final's
    con = sqlite3.connect(str(db))
    linked = con.execute("SELECT linked_batch_id FROM packing_documents "
                         "WHERE id='dADV'").fetchone()[0]
    con.close()
    assert linked == "B1"


def test_linking_is_idempotent(db):
    packing_db.upsert_packing_lines([_line("dA", pack_sr=1.0)])
    packing_db.upsert_packing_lines([_line("dADV", batch="ADVANCE_x")])
    assert packing_db.link_advance_final_documents() == 1
    assert packing_db.link_advance_final_documents() == 0
