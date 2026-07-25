"""F1: one wFirma invoice may never be linked to two proforma drafts.

The confirm-wfirma-link route pre-checks cross-draft uniqueness with a SELECT
then writes with a separate UPDATE — a TOCTOU window. The existing 2B route
tests mock persist_invoice_to_draft, so they never exercised the real write and
could not catch the race. These tests hit the REAL DB write and prove the
partial-unique index (uq_pd_wfirma_invoice_id) closes the window atomically.
"""
from __future__ import annotations

import sqlite3
import sys
import threading
from pathlib import Path

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services import proforma_invoice_link_db as pildb          # noqa: E402
from app.services.conversion_persistence import persist_invoice_to_draft  # noqa: E402


def _fresh_db(tmp_path) -> Path:
    db = tmp_path / "proforma_links.db"
    pildb.init_db(db)
    return db


def _insert_draft(db: Path, batch_id: str, client: str) -> int:
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.execute(
            "INSERT INTO proforma_drafts "
            "(batch_id, client_name, status, created_at, updated_at) "
            "VALUES (?, ?, 'draft', '2026-07-22T00:00:00', '2026-07-22T00:00:00')",
            (batch_id, client),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def test_index_exists_after_init(tmp_path):
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    idx = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND tbl_name='proforma_drafts'")]
    conn.close()
    assert "uq_pd_wfirma_invoice_id" in idx, (
        "partial-unique index on wfirma_invoice_id missing — F1 unguarded"
    )


def test_second_link_to_same_invoice_raises(tmp_path):
    db = _fresh_db(tmp_path)
    a = _insert_draft(db, "B1", "Acme")
    b = _insert_draft(db, "B2", "Beta")

    persist_invoice_to_draft(db_path=db, draft_id=a,
                             wfirma_invoice_id="INV-777", wfirma_invoice_number="7/2026")

    # Linking the SAME invoice to a different draft must be rejected by the DB.
    with pytest.raises(sqlite3.IntegrityError):
        persist_invoice_to_draft(db_path=db, draft_id=b,
                                 wfirma_invoice_id="INV-777", wfirma_invoice_number="7/2026")

    # And only draft A ended up linked.
    conn = sqlite3.connect(str(db))
    linked = conn.execute(
        "SELECT id FROM proforma_drafts WHERE wfirma_invoice_id='INV-777'").fetchall()
    conn.close()
    assert [r[0] for r in linked] == [a]


def test_relinking_same_draft_is_idempotent(tmp_path):
    """The index must NOT block re-persisting the same (draft, invoice) — that is
    the documented idempotent re-call, not a cross-draft conflict."""
    db = _fresh_db(tmp_path)
    a = _insert_draft(db, "B1", "Acme")
    persist_invoice_to_draft(db_path=db, draft_id=a,
                             wfirma_invoice_id="INV-9", wfirma_invoice_number="9/2026")
    # same draft, same invoice again — must not raise
    persist_invoice_to_draft(db_path=db, draft_id=a,
                             wfirma_invoice_id="INV-9", wfirma_invoice_number="9/2026")


def test_unconverted_drafts_are_exempt(tmp_path):
    """Partial index: many drafts have NULL/'' invoice id; those must not collide
    with each other."""
    db = _fresh_db(tmp_path)
    _insert_draft(db, "B1", "Acme")   # both NULL wfirma_invoice_id
    _insert_draft(db, "B2", "Beta")
    conn = sqlite3.connect(str(db))
    n = conn.execute("SELECT COUNT(*) FROM proforma_drafts").fetchone()[0]
    conn.close()
    assert n == 2, "NULL invoice-id drafts collided under the unique index"


def test_concurrent_confirms_yield_exactly_one_link(tmp_path):
    """Two threads racing to link the same invoice to different drafts: exactly
    one wins, and exactly one draft is linked."""
    db = _fresh_db(tmp_path)
    a = _insert_draft(db, "B1", "Acme")
    b = _insert_draft(db, "B2", "Beta")

    barrier = threading.Barrier(2)
    errors: list[Exception] = []
    oks: list[int] = []

    def _confirm(draft_id: int):
        barrier.wait()
        try:
            persist_invoice_to_draft(db_path=db, draft_id=draft_id,
                                     wfirma_invoice_id="INV-RACE",
                                     wfirma_invoice_number="R/2026")
            oks.append(draft_id)
        except sqlite3.IntegrityError as e:
            errors.append(e)

    t1 = threading.Thread(target=_confirm, args=(a,))
    t2 = threading.Thread(target=_confirm, args=(b,))
    t1.start(); t2.start(); t1.join(); t2.join()

    conn = sqlite3.connect(str(db))
    linked = [r[0] for r in conn.execute(
        "SELECT id FROM proforma_drafts WHERE wfirma_invoice_id='INV-RACE'")]
    conn.close()

    assert len(linked) == 1, f"invoice linked to {len(linked)} drafts — race not closed"
    assert len(oks) == 1 and len(errors) == 1, (
        f"expected exactly one winner + one IntegrityError; got oks={oks} errs={len(errors)}"
    )
    assert linked[0] == oks[0]
