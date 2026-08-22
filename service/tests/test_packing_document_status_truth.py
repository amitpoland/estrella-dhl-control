"""A packing document must not claim more than the write left behind.

``extraction_status`` was written from the parse, before a single row was
stored, and nothing corrected it. Production carries one document that parsed
245 rows, skipped 0, totalled $3,172, stored zero lines and reads ``complete``
-- on a shipment whose batch holds no packing lines at all.
"""
from __future__ import annotations

import app.services.packing_db as pdb


def _doc(con, doc_id, *, status="complete", batch="B1", stage="final", h="h"):
    con.execute(
        "INSERT INTO packing_documents (id, batch_id, invoice_no, source_file_path,"
        " source_file_hash, parser_name, parser_version, extraction_status,"
        " created_at, updated_at, doc_stage) "
        "VALUES (?,?,'INV','p',?,'x','1',?, '2026-01-01','2026-01-01',?)",
        (doc_id, batch, h, status, stage))


def _rows(doc_id, n, *, batch="B1", inv="INV", design="D1"):
    return [{
        "packing_document_id": doc_id, "batch_id": batch, "invoice_no": inv,
        "product_code": "P%d" % i, "design_no": design, "quantity": 1.0,
        "pack_sr": float(i), "invoice_line_position": i,
    } for i in range(1, n + 1)]


def _status(con, doc_id):
    return con.execute("SELECT extraction_status FROM packing_documents WHERE id=?",
                       (doc_id,)).fetchone()[0]


def _init(tmp_path):
    pdb.init_packing_db(tmp_path / "packing.db")
    return pdb._connect()


def test_a_document_whose_rows_all_stored_keeps_its_status(tmp_path):
    con = _init(tmp_path)
    _doc(con, "d1")
    con.commit()
    assert pdb.upsert_packing_lines(_rows("d1", 3)) == 3
    with pdb._connect() as c:
        assert _status(c, "d1") == "complete"


def test_a_re_registered_file_reads_absorbed_not_lost(tmp_path):
    """The benign case must not read like the dangerous one. Both stored zero."""
    con = _init(tmp_path)
    _doc(con, "d1")
    _doc(con, "d2")
    con.commit()
    assert pdb.upsert_packing_lines(_rows("d1", 3)) == 3
    pdb.upsert_packing_lines(_rows("d2", 3))            # same keys, second document
    with pdb._connect() as c:
        assert c.execute("SELECT COUNT(*) FROM packing_lines "
                         "WHERE packing_document_id='d2'").fetchone()[0] == 0
        assert _status(c, "d2") == pdb.ROWS_ABSORBED
        assert _status(c, "d1") == "complete"


def test_absorbed_and_lost_are_different_words(tmp_path):
    """If they ever collapse to one value the distinction this exists for is gone."""
    assert pdb.ROWS_ABSORBED != pdb.ROWS_LOST


def test_an_already_honest_status_is_not_overwritten(tmp_path):
    """'empty' already says the parse produced nothing. Rewriting it would
    replace a parser's account of itself with a persistence outcome."""
    con = _init(tmp_path)
    _doc(con, "d1", status="empty")
    con.commit()
    pdb.upsert_packing_lines(_rows("d1", 2))
    with pdb._connect() as c:
        c.execute("DELETE FROM packing_lines WHERE packing_document_id='d1'")
    pdb.upsert_packing_lines(_rows("d1", 2))
    with pdb._connect() as c:
        assert _status(c, "d1") == "empty"


def test_a_document_offered_no_rows_is_untouched(tmp_path):
    con = _init(tmp_path)
    _doc(con, "d1")
    _doc(con, "d2")
    con.commit()
    pdb.upsert_packing_lines(_rows("d1", 2))
    with pdb._connect() as c:
        assert _status(c, "d2") == "complete"


# ── The status authority ─────────────────────────────────────────────────────
# A document can reach 'complete' without its rows ever being offered to the
# write path -- that is exactly what happened in production, so no write-time
# hook can see it. The registry asks this function, and this function must not
# repeat a claim the database contradicts.

def _diag(con, doc_id, claimed):
    con.execute("UPDATE packing_documents SET parser_diagnostic_json=? WHERE id=?",
                ('{"rows_extracted": %d, "rows_skipped": 0}' % claimed, doc_id))


def test_a_document_claiming_rows_it_does_not_hold_is_not_complete(tmp_path):
    """A claim with nothing behind it anywhere. The goods really are missing."""
    con = _init(tmp_path)
    _doc(con, "d1", h="hA")
    _diag(con, "d1", 245)
    con.commit()
    with pdb._connect() as c:
        row = c.execute("SELECT id, extraction_status, parser_diagnostic_json "
                        "FROM packing_documents WHERE id='d1'").fetchone()
        assert pdb._status_against_stored_rows(c, row) == pdb.ROWS_LOST


def test_rows_belonging_to_no_live_document_are_orphaned_not_lost(tmp_path):
    """939ae11b: all 245 rows of its parse ARE in packing_lines, under document
    id c838d434, which no longer exists -- the only 245 orphans in 1598 rows.

    'lost' would send someone to re-ingest goods the database already holds.
    That is the duplication failure, and it is the one this distinction exists
    to prevent: the two words describe opposite recovery actions.
    """
    con = _init(tmp_path)
    _doc(con, "d1", h="hA")
    _diag(con, "d1", 245)
    con.commit()
    _doc(con, "gone", h="hB")
    con.commit()
    pdb.upsert_packing_lines(_rows("gone", 3))          # same batch B1
    with pdb._connect() as c:
        c.execute("DELETE FROM packing_documents WHERE id='gone'")
        row = c.execute("SELECT id, extraction_status, parser_diagnostic_json "
                        "FROM packing_documents WHERE id='d1'").fetchone()
        assert pdb._status_against_stored_rows(c, row) == pdb.ROWS_ORPHANED


def test_orphaned_absorbed_and_lost_are_three_different_words(tmp_path):
    assert len({pdb.ROWS_ABSORBED, pdb.ROWS_ORPHANED, pdb.ROWS_LOST}) == 3


def test_the_same_claim_with_the_rows_present_stays_complete(tmp_path):
    con = _init(tmp_path)
    _doc(con, "d1", h="hA")
    _diag(con, "d1", 3)
    con.commit()
    pdb.upsert_packing_lines(_rows("d1", 3))
    with pdb._connect() as c:
        row = c.execute("SELECT id, extraction_status, parser_diagnostic_json "
                        "FROM packing_documents WHERE id='d1'").fetchone()
        assert pdb._status_against_stored_rows(c, row) == "complete"


def test_a_re_registration_of_the_same_file_reads_absorbed(tmp_path):
    """Same bytes, second registration, rows live under the first: benign."""
    con = _init(tmp_path)
    _doc(con, "d1", h="hSAME")
    _doc(con, "d2", h="hSAME")
    _diag(con, "d2", 3)
    con.commit()
    pdb.upsert_packing_lines(_rows("d1", 3))
    with pdb._connect() as c:
        row = c.execute("SELECT id, extraction_status, parser_diagnostic_json "
                        "FROM packing_documents WHERE id='d2'").fetchone()
        assert pdb._status_against_stored_rows(c, row) == pdb.ROWS_ABSORBED


def test_a_document_that_claims_nothing_is_left_alone(tmp_path):
    """No recorded claim is nothing to contradict. This refuses one false
    statement; it does not invent a stricter contract for every document."""
    con = _init(tmp_path)
    _doc(con, "d1", h="hA")
    con.commit()
    with pdb._connect() as c:
        row = c.execute("SELECT id, extraction_status, parser_diagnostic_json "
                        "FROM packing_documents WHERE id='d1'").fetchone()
        assert pdb._status_against_stored_rows(c, row) == "complete"


# ── Orphans: goods with no document accounting for them ──────────────────────

def test_the_only_live_delete_path_leaves_no_orphans(tmp_path):
    """Exactly one code path in the application deletes a packing_documents row,
    and it deletes the lines first. Pinned so a future 'just remove the row'
    cannot quietly become the second one."""
    con = _init(tmp_path)
    _doc(con, "d1")
    con.commit()
    pdb.upsert_packing_lines(_rows("d1", 3))
    pdb.delete_packing_document_and_lines("d1")
    assert pdb.orphan_packing_lines() == []


def test_an_orphan_is_reported_with_its_dead_document_id(tmp_path):
    """Production holds 245 of these, 15% of the table, and nothing surfaced them."""
    con = _init(tmp_path)
    _doc(con, "d1")
    con.commit()
    pdb.upsert_packing_lines(_rows("d1", 3))
    with pdb._connect() as c:
        c.execute("DELETE FROM packing_documents WHERE id='d1'")   # what the FK would refuse
    found = pdb.orphan_packing_lines()
    assert len(found) == 1
    assert found[0]["packing_document_id"] == "d1"
    assert found[0]["rows_orphaned"] == 3
