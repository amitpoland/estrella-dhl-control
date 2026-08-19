r"""Item 8: the dedup change, proved against real historical batches.

``upsert_packing_lines`` had a secondary dedup that fired on
``(batch_id, invoice_no, invoice_line_position, bag_id)`` whenever the primary
key missed and a bag_id was present. It exists to tolerate OCR variance in
design_no within one physical bag.

For an advance list every row has ``invoice_line_position IS NULL``, so that
check degenerated to "same bag = same row" and a multi-design bag stored one
line -- silent quantity loss. The fix restricts the check to rows that carry no
serial of their own (``pack_sr is None``): a row that came with a serial
already has the source list's identity statement, and "same bag" must not
override it.

These tests replay REAL production rows to show the fix changes nothing that
already exists. They read a snapshot of the deployed database; they never
write to it.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))

from app.services import packing_db as pdb   # noqa: E402


def _rows(db: Path, sql: str, args=()):
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


def test_no_historical_row_is_in_the_changed_branch(production_db_snapshot):
    """The narrowed branch was only ever reachable for a row with a bag_id.
    No historical row has both a bag_id and a pack_sr, so no stored row can
    have taken it."""
    db = production_db_snapshot("packing.db")
    n = _rows(db, "SELECT COUNT(*) c FROM packing_lines "
                  "WHERE pack_sr IS NOT NULL AND bag_id IS NOT NULL "
                  "AND bag_id <> ''")[0]["c"]
    assert n == 0, (
        f"{n} historical rows carry both pack_sr and bag_id; re-verify the "
        "dedup change against them before trusting this proof")


def test_replaying_every_historical_batch_reproduces_its_row_count(
        production_db_snapshot, tmp_path):
    """Re-ingest each real batch into an empty database and require the same
    number of lines back. A dedup that merged too much would come back short;
    one that merged too little would come back long."""
    src = production_db_snapshot("packing.db")
    batches = [r["batch_id"] for r in _rows(
        src, "SELECT batch_id, COUNT(*) c FROM packing_lines "
             "GROUP BY batch_id ORDER BY c DESC")]
    if not batches:
        pytest.skip("deployed packing.db has no lines")

    mismatches = []
    for i, batch in enumerate(batches):
        original = _rows(src, "SELECT * FROM packing_lines WHERE batch_id=? "
                              "ORDER BY id", (batch,))
        pdb.init_packing_db(tmp_path / f"replay_{i}.db")
        stored = pdb.upsert_packing_lines(
            [{k: v for k, v in row.items() if k != "id"} for row in original])
        if stored != len(original):
            mismatches.append((batch, len(original), stored))

    assert not mismatches, (
        "batches whose replay row count changed (batch, was, now): %r"
        % mismatches[:10])


def test_replay_is_idempotent_on_real_rows(production_db_snapshot, tmp_path):
    """Re-ingesting the same real batch twice must not duplicate it -- the
    property the secondary check was protecting."""
    src = production_db_snapshot("packing.db")
    batch = _rows(src, "SELECT batch_id, COUNT(*) c FROM packing_lines "
                       "GROUP BY batch_id ORDER BY c DESC LIMIT 1")
    if not batch:
        pytest.skip("deployed packing.db has no lines")
    batch_id = batch[0]["batch_id"]
    rows = [{k: v for k, v in r.items() if k != "id"} for r in
            _rows(src, "SELECT * FROM packing_lines WHERE batch_id=?", (batch_id,))]

    pdb.init_packing_db(tmp_path / "idem.db")
    pdb.upsert_packing_lines(rows)
    pdb.upsert_packing_lines(rows)

    after = _rows(tmp_path / "idem.db",
                  "SELECT COUNT(*) c FROM packing_lines WHERE batch_id=?",
                  (batch_id,))[0]["c"]
    assert after == len(rows), f"re-ingest duplicated rows: {len(rows)} -> {after}"
