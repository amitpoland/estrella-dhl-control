"""A dedupe repair may delete a duplicate. It may not delete a confirmation.

`packing_dedupe_repair` removes the surplus copies of a DUPLICATE key group and
picks the survivor by generic completeness — how many fields are populated,
ranked per document by that document's richest row. Nothing in that score knows
which row a human confirmed.

The operator-review columns (`operator_review_status`, `operator_confirmed_at`,
`operator_confirmed_by`) are the current authority for a human decision on a
packing line; the allocation columns that used to serve that purpose were retired
by #1323 and are deliberately not consulted here.

Written fail-first: the premise is proved against unmodified code before any
repair is made.
"""
from __future__ import annotations

import uuid

import app.services.packing_db as pdb
from app.services.packing_dedupe_repair import (
    _operator_confirmed,
    _richness,
    find_duplicate_groups,
    quarantine_duplicates,
)

CLOCK = lambda: "2026-08-22T00:00:00+00:00"  # noqa: E731

INV   = "EJL/26-27/178"
CODE  = "EJL/26-27/178-1"
DESGN = "JR08007"


def _init(tmp_path):
    pdb.init_packing_db(tmp_path / "packing.db")


def _doc(doc_id, *, batch="B1", stage="final", file_hash="h"):
    with pdb._connect() as con:
        con.execute(
            "INSERT INTO packing_documents (id, batch_id, invoice_no, source_file_path,"
            " source_file_hash, parser_name, parser_version, extraction_status,"
            " created_at, updated_at, doc_stage) "
            "VALUES (?,?,?,'p',?,'x','1','complete','2026-01-01','2026-01-01',?)",
            (doc_id, batch, INV, file_hash, stage))


def _line(doc_id, *, batch="B1"):
    """The per-invoice form of one commercial line: serial, bag and tray."""
    pdb.upsert_packing_lines([{
        "packing_document_id": doc_id, "batch_id": batch, "invoice_no": INV,
        "product_code": CODE, "design_no": DESGN, "quantity": 1.0,
        "invoice_line_position": 1,
        "pack_sr": 1.0, "bag_id": "BAG-7", "tray_id": "TRAY-2", "batch_no": "BN-9",
    }])
    with pdb._connect() as con:
        return con.execute(
            "SELECT id FROM packing_lines WHERE packing_document_id=?",
            (doc_id,)).fetchone()[0]


def _historical_second_copy(of_line, doc_id):
    """The same commercial line as the per-client form held under a second
    document — the shape the 38 production duplicate groups are in.

    Written directly because **no current code path can produce it**: since #1318
    the cross-document absorb refuses a second document's copy of the same key at
    write time, and `force_reextract` re-points the existing row rather than
    inserting a second one. Every group this repair exists to clean up predates
    that absorb, so the fixture reproduces the stored state, not a live flow.
    The per-client form carries no serial, bag, tray or batch number.
    """
    new_id = str(uuid.uuid4())
    with pdb._connect() as con:
        cols = [r[1] for r in con.execute("PRAGMA table_info(packing_lines)")]
        thin = ("id", "packing_document_id", "pack_sr", "bag_id", "tray_id", "batch_no")
        keep = [c for c in cols if c not in thin]
        con.execute(
            "INSERT INTO packing_lines (id, packing_document_id, pack_sr, bag_id,"
            " tray_id, batch_no, %s) SELECT ?, ?, NULL, '', '', '', %s"
            " FROM packing_lines WHERE id = ?"
            % (",".join(keep), ",".join(keep)), (new_id, doc_id, of_line))
    return new_id


def _confirm(line_id, by="amit"):
    """What an operator confirming a line leaves behind on current main."""
    with pdb._connect() as con:
        con.execute(
            "UPDATE packing_lines SET operator_review_status='confirmed',"
            " operator_confirmed_at='2026-08-20T10:00:00+00:00',"
            " operator_confirmed_by=? WHERE id=?", (by, line_id))


def _live_confirmations():
    with pdb._connect() as con:
        return [dict(r) for r in con.execute(
            "SELECT id, operator_review_status, operator_confirmed_by FROM packing_lines"
            " WHERE TRIM(COALESCE(operator_review_status,''))='confirmed'")]


def _confirmed_on_the_poorer_document(tmp_path):
    """The production shape: the richer per-invoice form is the one the scorer
    keeps, and the operator confirmed the per-client copy in front of them."""
    _init(tmp_path)
    _doc("dRICH", file_hash="hA")
    _doc("dPOOR", file_hash="hB")
    rich = _line("dRICH")
    poor = _historical_second_copy(rich, "dPOOR")
    _confirm(poor)
    return rich, poor


def test_premise_completeness_alone_would_discard_the_confirmed_row(tmp_path):
    """Guards the whole file, and asserts on the SCORER rather than the outcome.

    The fix changes which document is kept, so pinning the old outcome would
    make this test describe a behaviour that no longer exists. What must stay
    true is the thing that made the defect possible: on the production shape the
    unconfirmed per-invoice form still out-scores the confirmed per-client form
    on generic completeness. The margin is ONE point — the confirmation's own
    three populated columns nearly rescue it, which is an accident of field
    counting, not a rule. If completeness ever started preferring the confirmed
    row on its own, everything below would stop meaning anything.
    """
    rich, poor = _confirmed_on_the_poorer_document(tmp_path)
    with pdb._connect() as con:
        rows = {r["id"]: r for r in con.execute("SELECT * FROM packing_lines")}
    assert _richness(rows[rich]) > _richness(rows[poor])
    assert _operator_confirmed(rows[poor]) and not _operator_confirmed(rows[rich])


def test_an_operator_confirmation_survives_the_repair(tmp_path):
    """FAIL-FIRST. Against unmodified code the confirmation is quarantined and
    the live set keeps no record that a human ever confirmed this line."""
    rich, poor = _confirmed_on_the_poorer_document(tmp_path)
    assert len(_live_confirmations()) == 1
    with pdb._connect() as con:
        quarantine_duplicates(con, repair_ref="r1", reason="dup",
                              clock=CLOCK, dry_run=False)
    assert len(_live_confirmations()) == 1, (
        "the operator's confirmation was removed from the live set by a dedupe repair"
    )


def test_the_confirmed_document_becomes_the_survivor(tmp_path):
    """The mechanism, stated directly: a confirmation outranks completeness."""
    rich, poor = _confirmed_on_the_poorer_document(tmp_path)
    with pdb._connect() as con:
        group = find_duplicate_groups(con)[0]
    assert group["kept_doc"] == "dPOOR"
    assert [r["id"] for r in group["surplus"]] == [rich]
    assert group["operator_confirmed_surplus"] == []


def test_the_duplicate_is_still_repaired(tmp_path):
    """A rule that stops the repair is not a fix. The surplus copy still goes;
    what changed is WHICH copy is surplus."""
    rich, poor = _confirmed_on_the_poorer_document(tmp_path)
    with pdb._connect() as con:
        report = quarantine_duplicates(con, repair_ref="r", reason="dup",
                                       clock=CLOCK, dry_run=False)
    assert report["quarantined"] == 1
    assert report["deferred_groups"] == 0
    with pdb._connect() as con:
        live = {r[0] for r in con.execute("SELECT id FROM packing_lines")}
    assert live == {poor}


def test_two_confirmations_in_one_group_are_deferred_not_adjudicated(tmp_path):
    """Ranking settles one confirmation. Two is a disagreement between two
    humans, and a repair does not decide that."""
    rich, poor = _confirmed_on_the_poorer_document(tmp_path)
    _confirm(rich, by="jigar")
    with pdb._connect() as con:
        report = quarantine_duplicates(con, repair_ref="r", reason="dup",
                                       clock=CLOCK, dry_run=False)
    assert report["quarantined"] == 0
    assert report["deferred_groups"] == 1
    assert len(report["deferred_operator_confirmed"]) == 1
    assert len(_live_confirmations()) == 2


def test_draft_review_metadata_is_not_a_decision(tmp_path):
    """THE NEGATIVE COMPANION. Populated confirmation metadata without the
    'confirmed' status must not acquire the protection a decision gets —
    otherwise every row that accumulated metadata becomes unrepairable and the
    repair quietly stops working."""
    _init(tmp_path)
    _doc("dRICH", file_hash="hA")
    _doc("dPOOR", file_hash="hB")
    rich = _line("dRICH")
    poor = _historical_second_copy(rich, "dPOOR")
    with pdb._connect() as con:
        con.execute(
            "UPDATE packing_lines SET operator_review_status='pending',"
            " operator_confirmed_at='2026-08-20T10:00:00+00:00',"
            " operator_confirmed_by='amit' WHERE id=?", (poor,))
    with pdb._connect() as con:
        rows = {r["id"]: r for r in con.execute("SELECT * FROM packing_lines")}
        assert not _operator_confirmed(rows[poor])
        report = quarantine_duplicates(con, repair_ref="r", reason="dup",
                                       clock=CLOCK, dry_run=False)
    assert report["quarantined"] == 1
    assert report["deferred_groups"] == 0
    with pdb._connect() as con:
        live = {r[0] for r in con.execute("SELECT id FROM packing_lines")}
    assert live == {rich}, "draft metadata protected a row it should not have"
