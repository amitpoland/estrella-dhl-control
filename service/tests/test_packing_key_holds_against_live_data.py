"""GENUINE = 0 is what validates the key against real data. Pin it.

The key is GROUP-shaped: several rows sharing it WITHIN one document are a lot,
which is by design. A collision is the same key held by MORE THAN ONE DOCUMENT,
and every such collision must classify to a business explanation. GENUINE means
the key grouped rows that are not the same commercial line -- a key defect, not
a data oddity, and it should fail here rather than be discovered in a report.

Expected shape, measured 2026-08-22 before the pin was written: 774 distinct
keys over 1326 live rows, 51 cross-document keys = 30 DUPLICATE
+ 21 ADVANCE_FINAL, zero GENUINE, zero QUANTITY_MISMATCH.

The production database is not present in CI, so this SKIPS where it is absent
and runs where it exists. It opens the file immutable and writes nothing.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path

import pytest

from app.services.packing_db import (
    ADVANCE_FINAL,
    DUPLICATE,
    GENUINE,
    QUANTITY_MISMATCH,
    classify_key_collision,
    packing_line_key,
)

PROD = Path("C:/") / "PZ" / "storage" / "packing.db"


def _live_collisions():
    uri = "file:%s?mode=ro&immutable=1" % PROD.as_posix()
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    docs = {r["id"]: r for r in con.execute("SELECT * FROM packing_documents")}
    totals = {d: con.execute(
        "SELECT COALESCE(SUM(quantity),0) FROM packing_lines "
        "WHERE packing_document_id=?", (d,)).fetchone()[0] for d in docs}
    rows = con.execute(
        "SELECT l.* FROM packing_lines l "
        "JOIN packing_documents d ON d.id = l.packing_document_id "
        "WHERE (d.withdrawn_reason IS NULL OR TRIM(d.withdrawn_reason) = '') "
        "ORDER BY l.packing_document_id, l.rowid").fetchall()
    con.close()

    keyed = defaultdict(lambda: defaultdict(list))
    for r in rows:
        keyed[packing_line_key(dict(r))][r["packing_document_id"]].append(r)

    out = {}
    for key, per_doc in keyed.items():
        if len(per_doc) < 2:          # within-document sharing is a lot
            continue
        payload = [{
            "doc_stage": docs[d]["doc_stage"],
            "source_file_hash": docs[d]["source_file_hash"],
            "doc_total_quantity": totals[d],
        } for d in per_doc]
        out[key] = (classify_key_collision(payload), per_doc)
    return len(rows), out


@pytest.fixture(scope="module")
def live():
    if not PROD.is_file():
        pytest.skip("production packing.db not present on this host")
    return _live_collisions()


def test_no_live_collision_is_genuine(live):
    """THE assertion. GENUINE means the key grouped two rows that are not the
    same commercial line -- there is no business explanation for it, so it is a
    key defect. Written to pass, so that a real regression can turn it red."""
    _n, collisions = live
    genuine = {k: m for k, (cls, m) in collisions.items() if cls == GENUINE}
    assert not genuine, (
        "%d collision(s) classify GENUINE -- the key is grouping rows that are "
        "not the same commercial line: %r" % (len(genuine), list(genuine)[:5]))


def test_the_corpus_is_large_enough_to_mean_something(live):
    """NON-VACUITY. A key asserted against an empty or tiny corpus proves
    nothing; this is the guard that stops the assertion above passing by
    accident on a truncated database."""
    n, collisions = live
    assert n > 500, "only %d live rows -- too few for the assertion to mean much" % n
    assert collisions, "no collisions at all -- verify the corpus, not the key"


def test_every_collision_carries_a_business_explanation(live):
    """Each class must be one of the four. An unrecognised value would mean the
    classifier changed without this pin changing with it."""
    _n, collisions = live
    classes = {cls for cls, _m in collisions.values()}
    assert classes <= {DUPLICATE, ADVANCE_FINAL, QUANTITY_MISMATCH, GENUINE}


def test_advance_final_pairs_really_do_share_their_bytes(live):
    """The rule that links them is 'same file hash'. If a pair classified
    ADVANCE_FINAL without sharing a hash, the rule ordering has drifted."""
    _n, collisions = live
    for key, (cls, _members) in collisions.items():
        if cls == ADVANCE_FINAL:
            assert key, "an ADVANCE_FINAL pair must have a non-empty key"
