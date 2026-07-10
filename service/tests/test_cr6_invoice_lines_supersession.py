"""CR6 (MASTER-EXEC-1 Campaign Run 6, gap G2) — invoice_lines supersession.

Root cause: invoice_lines has a random-UUID PK, so every re-upload appended a
full duplicate row set (INSERT OR IGNORE never ignored) and orphaned rows from
the prior document stayed ACTIVE and authoritative (the "Wyrób jubilerski"
placeholder / stale-authority defect, SHIPMENT_8341809162).

Pins: supersede-on-reupload is per (batch_id, invoice_no) and document-scoped;
canonical accessors return only active rows; rows are never deleted (mint /
history immutability); other invoices in the batch are untouched; the retro
maintenance heal deactivates older-document duplicates; the document-scoped
registry reader still shows a superseded document's own lines.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services import document_db as ddb  # noqa: E402


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from app.core import config as cfg
    # store_invoice_lines projects into product_master (reservation_queue.db)
    monkeypatch.setattr(cfg.settings, "storage_root", tmp_path)
    ddb.init_document_db(tmp_path / "documents.db")
    return tmp_path


def _lines(inv_no, n, desc="Gold ring 585"):
    return [{"invoice_no": inv_no, "line_position": i, "description": desc,
             "quantity": 1, "unit_price": 10, "total_value": 10,
             "currency": "USD"} for i in range(1, n + 1)]


def _all_rows(batch):
    import sqlite3
    con = sqlite3.connect(str(ddb._db_path)); con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM invoice_lines WHERE batch_id=?", (batch,)).fetchall()]
    con.close()
    return rows


class TestSupersession:
    def test_reupload_supersedes_prior_document(self, db):
        ddb.store_invoice_lines("DOC1", "B1", _lines("INV-1", 3))
        ddb.store_invoice_lines("DOC2", "B1", _lines("INV-1", 2))  # re-upload, 1 line removed
        active = ddb.get_invoice_lines_for_batch("B1")
        assert len(active) == 2                       # only the new document's truth
        assert {r["document_id"] for r in active} == {"DOC2"}
        # the orphan (INV-1-3) is no longer authoritative
        assert "INV-1-3" not in {r["product_code"] for r in active}

    def test_history_preserved_never_deleted(self, db):
        ddb.store_invoice_lines("DOC1", "B1", _lines("INV-1", 3))
        ddb.store_invoice_lines("DOC2", "B1", _lines("INV-1", 2))
        rows = _all_rows("B1")
        assert len(rows) == 5                          # 3 old (inactive) + 2 new
        old = [r for r in rows if r["document_id"] == "DOC1"]
        assert all(r["active"] == 0 and r["superseded_by"] == "DOC2" for r in old)

    def test_other_invoice_untouched(self, db):
        ddb.store_invoice_lines("DOC1", "B1", _lines("INV-1", 2))
        ddb.store_invoice_lines("DOC2", "B1", _lines("INV-2", 2))
        active = ddb.get_invoice_lines_for_batch("B1")
        assert len(active) == 4                        # different invoice_no: no supersession
        assert {r["invoice_no"] for r in active} == {"INV-1", "INV-2"}

    def test_same_document_not_self_superseded(self, db):
        ddb.store_invoice_lines("DOC1", "B1", _lines("INV-1", 2))
        rows = _all_rows("B1")
        assert all(r["active"] == 1 for r in rows)

    def test_product_code_mint_stable_across_reupload(self, db):
        ddb.store_invoice_lines("DOC1", "B1", _lines("INV-1", 2))
        ddb.store_invoice_lines("DOC2", "B1", _lines("INV-1", 2))
        active = ddb.get_invoice_lines_for_batch("B1")
        assert sorted(r["product_code"] for r in active) == ["INV-1-1", "INV-1-2"]

    def test_get_invoice_lines_by_invoice_no_filters_active(self, db):
        ddb.store_invoice_lines("DOC1", "B1", _lines("INV-1", 3))
        ddb.store_invoice_lines("DOC2", "B1", _lines("INV-1", 1))
        assert len(ddb.get_invoice_lines("B1", "INV-1")) == 1

    def test_document_scoped_reader_still_shows_superseded_doc(self, db):
        # registry/history view is document-scoped and intentionally unfiltered
        ddb.store_invoice_lines("DOC1", "B1", _lines("INV-1", 3))
        ddb.store_invoice_lines("DOC2", "B1", _lines("INV-1", 2))
        assert len(ddb.get_invoice_lines_for_document("DOC1")) == 3


class TestRetroHeal:
    def test_supersede_stale_heals_pre_fix_duplicates(self, db):
        import sqlite3, uuid
        # simulate PRE-FIX state: two documents' rows all active (bypass writer)
        con = sqlite3.connect(str(ddb._db_path))
        for doc, created in (("DOCA", "2026-07-01T00:00:00"), ("DOCB", "2026-07-05T00:00:00")):
            for pos in (1, 2):
                con.execute(
                    "INSERT INTO invoice_lines (id, document_id, batch_id, invoice_no,"
                    " line_position, product_code, created_at, active, superseded_by)"
                    " VALUES (?,?,?,?,?,?,?,1,'')",
                    (str(uuid.uuid4()), doc, "B9", "INV-9", pos, f"INV-9-{pos}", created))
        con.commit(); con.close()
        n = ddb.supersede_stale_invoice_lines("B9")
        assert n == 2                                  # DOCA's rows retired
        active = ddb.get_invoice_lines_for_batch("B9")
        assert {r["document_id"] for r in active} == {"DOCB"}
        assert ddb.supersede_stale_invoice_lines("B9") == 0   # idempotent

    def test_retro_heal_scoped_to_batch(self, db):
        ddb.store_invoice_lines("DOC1", "B1", _lines("INV-1", 1))
        assert ddb.supersede_stale_invoice_lines("OTHER") == 0
        assert len(ddb.get_invoice_lines_for_batch("B1")) == 1


class TestReaderAuthority:
    def test_stale_rows_invisible_to_description_source(self, db):
        # description_engine reads invoice_lines directly; superseded rows with
        # placeholder descriptions must not be authoritative anymore.
        ddb.store_invoice_lines("DOC1", "B1", _lines("INV-1", 2, desc="PLACEHOLDER"))
        ddb.store_invoice_lines("DOC2", "B1", _lines("INV-1", 2, desc="Gold ring 585"))
        active = ddb.get_invoice_lines_for_batch("B1")
        assert all(r["description"] == "Gold ring 585" for r in active)

    def test_direct_readers_carry_active_filter(self):
        import inspect
        from app.services import (dual_valuation, product_master_backfill,
                                  wfirma_product_registration, proforma_draft_sync,
                                  ai_reverification, rule_based_reverification,
                                  intelligence_graph, description_engine)
        from app.services.carrier import doc_package
        for mod in (dual_valuation, product_master_backfill,
                    wfirma_product_registration, proforma_draft_sync,
                    ai_reverification, rule_based_reverification,
                    intelligence_graph, description_engine, doc_package):
            src = inspect.getsource(mod)
            if "FROM invoice_lines" in src:
                assert "active=1" in src or "active = 1" in src, mod.__name__
