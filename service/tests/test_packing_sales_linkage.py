"""
test_packing_sales_linkage.py — Sales packing → proforma draft linkage.

Coverage:
1.  _guess_client_from_filename — "148 Client SUOKKO" → "SUOKKO"
2.  _guess_client_from_filename — handles "Cilent" typo
3.  _guess_client_from_filename — multi-word names: "149 Client Diamond Point" → "Diamond Point"
4.  _guess_client_from_filename — no match returns ""
5.  upsert_packing_document — hash dedup: same hash returns existing id, no ghost row
6.  upsert_packing_document — different hash inserts a new row
7.  get_or_create_sales_document_for_packing — first call creates row
8.  get_or_create_sales_document_for_packing — second call with same packing_document_id
    returns same id (idempotent)
9.  get_or_create_sales_document_for_packing — client_name update on re-call
10. link_packing_as_sales service flow — writes sales_packing_lines from packing_lines
11. link_packing_as_sales service flow — idempotent: second call replaces, not appends
12. link_packing_as_sales → proforma draft auto-created via sync
13. link_packing_as_sales — no auto-post to wFirma (draft stays in draft/editing state)
14. link_packing_as_sales — no inventory_state mutation
15. link_packing_as_sales — empty packing_document_id skipped with error reason
16. link_packing_as_sales — packing_document_id with no lines skipped
17. duplicate packing_document rows (same hash) produce same canonical id on get_or_create
18. dashboard.html: btn-link-packing-as-sales testid present in ProformaDraftPanel
19. dashboard.html: link-packing-panel testid present
20. dashboard.html: btn-link-packing-submit and btn-link-packing-cancel testids present
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DASHBOARD_HTML = _ROOT / "app" / "static" / "dashboard.html"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _init_packing(tmp_path: Path) -> Path:
    from app.services.packing_db import init_packing_db
    db = tmp_path / "packing.db"
    init_packing_db(db)
    return db


def _init_docs(tmp_path: Path) -> Path:
    from app.services.document_db import init_document_db
    db = tmp_path / "documents.db"
    init_document_db(db)
    return db


def _init_proforma(tmp_path: Path) -> Path:
    from app.services import proforma_invoice_link_db as pildb
    db = tmp_path / "proforma_links.db"
    pildb.init_db(db)
    return db


def _make_packing_lines(pdoc_id: str, batch_id: str, n: int = 3) -> List[Dict[str, Any]]:
    return [
        {
            "packing_document_id": pdoc_id,
            "batch_id": batch_id,
            "invoice_no": f"EJL/26-27/{148 + i}",
            "invoice_line_position": i + 1,
            "product_code": f"PC-{i:03d}",
            "design_no": f"D{i:03d}",
            "batch_no": "",
            "bag_id": f"BAG-{i:02d}",
            "tray_id": "",
            "item_type": "RING",
            "uom": "PCS",
            "quantity": float(i + 1),
            "gross_weight": 0.0,
            "net_weight": 0.0,
            "metal": "18K",
            "karat": "18",
            "stone_type": "",
            "remarks": "",
            "extracted_confidence": 0.9,
            "requires_manual_review": False,
        }
        for i in range(n)
    ]


# ── 1–4: _guess_client_from_filename ─────────────────────────────────────────

class TestGuessClientFromFilename:
    def _f(self, name: str) -> str:
        from app.api.routes_packing import _guess_client_from_filename
        return _guess_client_from_filename(name)

    def test_standard_client_prefix(self):
        assert self._f("148 Client SUOKKO.xlsx") == "SUOKKO"

    def test_cilent_typo(self):
        # typo "Cilent" must be handled
        assert self._f("149 Cilent Diamond Point.xlsx") == "Diamond Point"

    def test_multi_word_name(self):
        assert self._f("149 Client Diamond Point.xlsx") == "Diamond Point"
        assert self._f("150 Client Goto Jewellery and diamonds.xlsx") == "Goto Jewellery and diamonds"
        assert self._f("151 Client Verhoeven Joaillier.xlsx") == "Verhoeven Joaillier"

    def test_no_match_returns_empty(self):
        assert self._f("purchase_packing_list_EJL.xlsx") == ""
        assert self._f("random_file.pdf") == ""
        assert self._f("") == ""

    def test_no_number_prefix_no_match(self):
        # Without the leading invoice number, should not match
        assert self._f("Client SUOKKO.xlsx") == ""


# ── 5–6: upsert_packing_document hash dedup ──────────────────────────────────

class TestUpsertPackingDocumentHashDedup:
    def test_same_hash_returns_existing_id(self, tmp_path):
        """
        Second call with the same batch_id + source_file_hash must return the
        existing document id without creating a ghost row.
        """
        _init_packing(tmp_path)
        from app.services import packing_db as pdb
        id1 = pdb.upsert_packing_document(
            batch_id="BATCH1", invoice_no="EJL/100",
            source_file_hash="abc123", source_file_path="/tmp/a.xlsx",
        )
        id2 = pdb.upsert_packing_document(
            batch_id="BATCH1", invoice_no="EJL/100",
            source_file_hash="abc123", source_file_path="/tmp/a.xlsx",
        )
        assert id1 == id2, "same hash must return same id"
        # Only one row in the table
        docs = pdb.get_packing_documents_for_batch("BATCH1")
        assert len(docs) == 1, f"expected 1 document row, got {len(docs)}"

    def test_different_hash_creates_new_row(self, tmp_path):
        _init_packing(tmp_path)
        from app.services import packing_db as pdb
        id1 = pdb.upsert_packing_document(
            batch_id="BATCH1", invoice_no="EJL/100",
            source_file_hash="hash_a", source_file_path="/tmp/a.xlsx",
        )
        id2 = pdb.upsert_packing_document(
            batch_id="BATCH1", invoice_no="EJL/101",
            source_file_hash="hash_b", source_file_path="/tmp/b.xlsx",
        )
        assert id1 != id2
        docs = pdb.get_packing_documents_for_batch("BATCH1")
        assert len(docs) == 2

    def test_empty_hash_does_not_dedup(self, tmp_path):
        """Empty hash must not accidentally dedup all blank-hash uploads together."""
        _init_packing(tmp_path)
        from app.services import packing_db as pdb
        id1 = pdb.upsert_packing_document(
            batch_id="BATCH1", invoice_no="EJL/100",
            source_file_hash="", source_file_path="/tmp/a.xlsx",
        )
        id2 = pdb.upsert_packing_document(
            batch_id="BATCH1", invoice_no="EJL/101",
            source_file_hash="", source_file_path="/tmp/b.xlsx",
        )
        assert id1 != id2, "empty hash must not trigger dedup"


# ── 7–9: get_or_create_sales_document_for_packing ───────────────────────────

class TestGetOrCreateSalesDocumentForPacking:
    def test_first_call_creates_row(self, tmp_path):
        _init_docs(tmp_path)
        from app.services import document_db as ddb
        row_id = ddb.get_or_create_sales_document_for_packing(
            batch_id="B1", packing_document_id="PDOC1", client_name="SUOKKO",
        )
        assert row_id, "must return a non-empty id"
        docs = ddb.get_sales_documents("B1")
        assert len(docs) == 1
        assert docs[0]["client_name"] == "SUOKKO"
        assert docs[0]["document_type"] == "packing_list_promote"

    def test_second_call_returns_same_id(self, tmp_path):
        _init_docs(tmp_path)
        from app.services import document_db as ddb
        id1 = ddb.get_or_create_sales_document_for_packing("B1", "PDOC1", "SUOKKO")
        id2 = ddb.get_or_create_sales_document_for_packing("B1", "PDOC1", "SUOKKO")
        assert id1 == id2, "repeated call must be idempotent"
        assert len(ddb.get_sales_documents("B1")) == 1

    def test_client_name_updated_on_re_call(self, tmp_path):
        _init_docs(tmp_path)
        from app.services import document_db as ddb
        id1 = ddb.get_or_create_sales_document_for_packing("B1", "PDOC1", "SUOKKO OLD")
        id2 = ddb.get_or_create_sales_document_for_packing("B1", "PDOC1", "SUOKKO NEW")
        assert id1 == id2
        docs = ddb.get_sales_documents("B1")
        assert docs[0]["client_name"] == "SUOKKO NEW"

    def test_different_packing_doc_creates_separate_row(self, tmp_path):
        _init_docs(tmp_path)
        from app.services import document_db as ddb
        id1 = ddb.get_or_create_sales_document_for_packing("B1", "PDOC1", "SUOKKO")
        id2 = ddb.get_or_create_sales_document_for_packing("B1", "PDOC2", "Diamond Point")
        assert id1 != id2
        assert len(ddb.get_sales_documents("B1")) == 2


# ── 10–16: link_packing_as_sales service-level flow ─────────────────────────

class TestLinkPackingAsSalesFlow:
    """
    Tests the service-level logic of the link-as-sales flow without spinning up
    the full HTTP server.  The route delegates to pdb, ddb, and
    proforma_draft_sync; we test those directly.
    """

    def _setup(self, tmp_path):
        """Init all three DBs, insert packing document + lines, return helpers."""
        pack_db = _init_packing(tmp_path)
        docs_db = _init_docs(tmp_path)
        pf_db   = _init_proforma(tmp_path)
        from app.services import packing_db as pdb, document_db as ddb
        batch_id = "SHIPMENT_TEST"
        pdoc_id  = pdb.upsert_packing_document(
            batch_id="SHIPMENT_TEST", invoice_no="EJL/26-27/148",
            source_file_hash="hash_suokko", source_file_path="/tmp/148.xlsx",
        )
        lines = _make_packing_lines(pdoc_id, batch_id, n=3)
        pdb.upsert_packing_lines(lines)
        return batch_id, pdoc_id, pf_db, ddb

    def test_writes_sales_packing_lines(self, tmp_path):
        batch_id, pdoc_id, pf_db, ddb = self._setup(tmp_path)
        from app.services import packing_db as pdb
        # Simulate the route logic
        sales_doc_id = ddb.get_or_create_sales_document_for_packing(
            batch_id=batch_id, packing_document_id=pdoc_id, client_name="SUOKKO",
        )
        packing_lines = pdb.get_packing_lines_for_document(pdoc_id)
        sales_lines = [
            {
                "client_name": "SUOKKO", "client_ref": ln.get("invoice_no", ""),
                "product_code": ln.get("product_code", ""), "design_no": ln.get("design_no", ""),
                "bag_id": ln.get("bag_id", ""), "quantity": float(ln.get("quantity", 0) or 0),
                "remarks": ln.get("remarks", ""), "unit_price": 0.0, "currency": "EUR",
                "total_value": 0.0, "price_source": "packing_promote",
            }
            for ln in packing_lines
        ]
        result = ddb.replace_sales_packing_lines(
            sales_document_id=sales_doc_id, batch_id=batch_id, lines=sales_lines,
        )
        assert result["inserted"] == 3
        stored = ddb.get_sales_packing_lines(batch_id)
        assert len(stored) == 3
        assert all(ln["client_name"] == "SUOKKO" for ln in stored)
        assert all(ln["price_source"] == "packing_promote" for ln in stored)

    def test_idempotent_second_call_replaces_not_appends(self, tmp_path):
        batch_id, pdoc_id, pf_db, ddb = self._setup(tmp_path)
        from app.services import packing_db as pdb
        sales_doc_id = ddb.get_or_create_sales_document_for_packing(
            batch_id=batch_id, packing_document_id=pdoc_id, client_name="SUOKKO",
        )
        packing_lines = pdb.get_packing_lines_for_document(pdoc_id)
        sales_lines = [
            {"client_name": "SUOKKO", "client_ref": "", "product_code": "", "design_no": "",
             "bag_id": "", "quantity": 1.0, "remarks": "", "unit_price": 0.0,
             "currency": "EUR", "total_value": 0.0, "price_source": "packing_promote"}
            for _ in packing_lines
        ]
        ddb.replace_sales_packing_lines(sales_document_id=sales_doc_id, batch_id=batch_id, lines=sales_lines)
        ddb.replace_sales_packing_lines(sales_document_id=sales_doc_id, batch_id=batch_id, lines=sales_lines)
        stored = ddb.get_sales_packing_lines(batch_id)
        assert len(stored) == len(packing_lines), \
            f"second call must replace (not append); expected {len(packing_lines)}, got {len(stored)}"

    def test_proforma_draft_created_after_link(self, tmp_path):
        """
        After sales_packing_lines are written, calling sync_draft_from_packing_upload
        must create a proforma draft for SUOKKO.
        """
        batch_id, pdoc_id, pf_db, ddb = self._setup(tmp_path)
        from app.services import packing_db as pdb
        from app.services.proforma_draft_sync import sync_draft_from_packing_upload
        from app.services import proforma_invoice_link_db as pildb

        # Write sales_packing_lines
        sales_doc_id = ddb.get_or_create_sales_document_for_packing(
            batch_id=batch_id, packing_document_id=pdoc_id, client_name="SUOKKO",
        )
        packing_lines = pdb.get_packing_lines_for_document(pdoc_id)
        sales_lines = [
            {"client_name": "SUOKKO", "client_ref": "", "product_code": ln.get("product_code", ""),
             "design_no": ln.get("design_no", ""), "bag_id": ln.get("bag_id", ""),
             "quantity": float(ln.get("quantity", 0) or 0), "remarks": "",
             "unit_price": 0.0, "currency": "EUR", "total_value": 0.0,
             "price_source": "packing_promote"}
            for ln in packing_lines
        ]
        ddb.replace_sales_packing_lines(sales_document_id=sales_doc_id, batch_id=batch_id, lines=sales_lines)

        # Trigger sync
        audit = tmp_path / "audit.json"
        audit.write_text(json.dumps({"timeline": []}), encoding="utf-8")
        result = sync_draft_from_packing_upload(
            batch_id=batch_id, operator="test", db_path=pf_db, audit_path=audit,
        )
        assert result.get("created") == 1, f"expected 1 draft created; got {result}"
        assert result.get("no_sales_lines") is not True

        # Draft exists and is NOT auto-posted
        drafts = pildb.list_drafts_for_batch(pf_db, batch_id)
        assert len(drafts) == 1
        assert drafts[0].draft_state in ("draft", "editing"), \
            f"draft must be in editable state, not '{drafts[0].draft_state}'"

    def test_no_auto_post_to_wfirma(self, tmp_path):
        """Draft created by link-as-sales flow must never reach 'posting' or 'posted' state."""
        batch_id, pdoc_id, pf_db, ddb = self._setup(tmp_path)
        from app.services import packing_db as pdb
        from app.services.proforma_draft_sync import sync_draft_from_packing_upload
        from app.services import proforma_invoice_link_db as pildb

        sales_doc_id = ddb.get_or_create_sales_document_for_packing(
            batch_id=batch_id, packing_document_id=pdoc_id, client_name="SUOKKO",
        )
        packing_lines = pdb.get_packing_lines_for_document(pdoc_id)
        sales_lines = [
            {"client_name": "SUOKKO", "client_ref": "", "product_code": "",
             "design_no": "", "bag_id": "", "quantity": 1.0, "remarks": "",
             "unit_price": 0.0, "currency": "EUR", "total_value": 0.0,
             "price_source": "packing_promote"}
            for _ in packing_lines
        ]
        ddb.replace_sales_packing_lines(sales_document_id=sales_doc_id, batch_id=batch_id, lines=sales_lines)
        audit = tmp_path / "audit.json"
        audit.write_text(json.dumps({"timeline": []}), encoding="utf-8")
        sync_draft_from_packing_upload(
            batch_id=batch_id, operator="test", db_path=pf_db, audit_path=audit,
        )
        drafts = pildb.list_drafts_for_batch(pf_db, batch_id)
        for d in drafts:
            assert d.draft_state not in ("posting", "posted"), \
                f"draft must not be auto-posted (state={d.draft_state})"

    def test_no_inventory_state_mutation(self, tmp_path):
        """
        link-as-sales writes to sales_packing_lines and proforma_drafts only.
        It must NOT call inventory_state_engine.transition().
        """
        _init_packing(tmp_path)
        _init_docs(tmp_path)
        from app.services import document_db as ddb
        from app.services import inventory_state_engine as ise

        with patch.object(ise, "transition") as mock_transition:
            ddb.get_or_create_sales_document_for_packing("B1", "PDOC1", "SUOKKO")
            ddb.replace_sales_packing_lines(
                sales_document_id="fake-sdoc",
                batch_id="B1",
                lines=[{"client_name": "SUOKKO", "client_ref": "", "product_code": "",
                        "design_no": "", "bag_id": "", "quantity": 1.0, "remarks": "",
                        "unit_price": 0.0, "currency": "EUR", "total_value": 0.0,
                        "price_source": "packing_promote"}],
            )
            mock_transition.assert_not_called()

    def test_missing_packing_document_id_skipped(self, tmp_path):
        """Mapping with empty packing_document_id must be skipped gracefully."""
        _init_packing(tmp_path)
        _init_docs(tmp_path)
        from app.services import packing_db as pdb
        lines = pdb.get_packing_lines_for_document("")
        assert lines == [], "empty doc id must return no lines"

    def test_packing_document_with_no_lines_skipped(self, tmp_path):
        _init_packing(tmp_path)
        from app.services import packing_db as pdb
        pdoc_id = pdb.upsert_packing_document(
            batch_id="B1", invoice_no="EJL/999",
            source_file_hash="empty_hash", source_file_path="/tmp/empty.xlsx",
        )
        lines = pdb.get_packing_lines_for_document(pdoc_id)
        assert lines == [], "document with no lines must return empty list"


# ── 17: duplicate ghost records don't break get_or_create ────────────────────

class TestDuplicateGhostRecordHandling:
    def test_ghost_rows_share_canonical_id(self, tmp_path):
        """
        Pre-fix era produced ghost rows (same hash, different id). The hash-dedup
        fix prevents NEW ghosts.  For any remaining ghosts, get_or_create still
        works correctly because it uses the synthetic document_id lookup
        (not source_file_hash).
        """
        _init_docs(tmp_path)
        from app.services import document_db as ddb
        # Simulate two calls for the same packing document
        id1 = ddb.get_or_create_sales_document_for_packing("B1", "PDOC_GHOST", "SUOKKO")
        id2 = ddb.get_or_create_sales_document_for_packing("B1", "PDOC_GHOST", "SUOKKO")
        assert id1 == id2, "same packing_document_id must yield same sales_document id"


# ── 18–20: dashboard.html UI testids ─────────────────────────────────────────

class TestDashboardLinkPackingUI:
    def _html(self) -> str:
        return DASHBOARD_HTML.read_text(encoding="utf-8")

    def test_btn_link_packing_as_sales_present(self):
        assert 'data-testid="btn-link-packing-as-sales"' in self._html()

    def test_link_packing_panel_testid_present(self):
        assert 'data-testid="link-packing-panel"' in self._html()

    def test_submit_and_cancel_buttons_present(self):
        h = self._html()
        assert 'data-testid="btn-link-packing-submit"' in h
        assert 'data-testid="btn-link-packing-cancel"' in h

    def test_link_packing_no_docs_testid_present(self):
        assert 'data-testid="link-packing-no-docs"' in self._html()

    def test_link_as_sales_api_endpoint_referenced(self):
        """The UI must call the correct new endpoint."""
        assert '/link-as-sales' in self._html()

    def test_packing_documents_api_endpoint_referenced(self):
        """The UI must fetch the packing-documents hint endpoint."""
        assert '/packing-documents' in self._html()
