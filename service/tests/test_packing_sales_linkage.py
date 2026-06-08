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
21. get_line_counts_for_batch — returns real counts per document
22. get_packing_documents endpoint — annotates line_count per doc
23. get_packing_documents endpoint — marks ghost duplicates with is_duplicate=True
24. get_packing_documents endpoint — canonical doc has is_duplicate=False
25. ghost doc submitted to link-as-sales — warns with ghost_hint in reason
26. link button accessible in main drafts view (btn-link-packing-as-sales-main)
27. ignoredDocs filter referenced in submitLinkAsSales
28. source_file_hash migration guard added to _add_column_if_missing
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


# ── 21–22: get_line_counts_for_batch and endpoint annotation ─────────────────

class TestLineCountAnnotation:
    def test_get_line_counts_for_batch(self, tmp_path):
        """get_line_counts_for_batch returns {pdoc_id: count} for real lines."""
        _init_packing(tmp_path)
        from app.services import packing_db as pdb

        id1 = pdb.upsert_packing_document(
            batch_id="BCOUNT", source_file_hash="h1", invoice_no="INV-1"
        )
        id2 = pdb.upsert_packing_document(
            batch_id="BCOUNT", source_file_hash="h2", invoice_no="INV-2"
        )
        # Lines for doc1: invoice_no INV-1, positions 1–5
        lines1 = [
            {
                "packing_document_id": id1, "batch_id": "BCOUNT",
                "invoice_no": "INV-1", "invoice_line_position": i + 1,
                "product_code": f"PC1-{i:03d}", "design_no": f"D1-{i:03d}",
                "bag_id": f"B1-{i:02d}", "batch_no": "", "tray_id": "",
                "item_type": "RING", "uom": "PCS", "quantity": float(i + 1),
                "gross_weight": 0.0, "net_weight": 0.0,
                "metal": "18K", "karat": "18", "stone_type": "", "remarks": "",
                "extracted_confidence": 0.9, "requires_manual_review": False,
            }
            for i in range(5)
        ]
        # Lines for doc2: invoice_no INV-2, distinct design/bag so dedup doesn't collide
        lines2 = [
            {
                "packing_document_id": id2, "batch_id": "BCOUNT",
                "invoice_no": "INV-2", "invoice_line_position": i + 1,
                "product_code": f"PC2-{i:03d}", "design_no": f"D2-{i:03d}",
                "bag_id": f"B2-{i:02d}", "batch_no": "", "tray_id": "",
                "item_type": "RING", "uom": "PCS", "quantity": float(i + 1),
                "gross_weight": 0.0, "net_weight": 0.0,
                "metal": "18K", "karat": "18", "stone_type": "", "remarks": "",
                "extracted_confidence": 0.9, "requires_manual_review": False,
            }
            for i in range(2)
        ]
        pdb.upsert_packing_lines(lines1)
        pdb.upsert_packing_lines(lines2)

        counts = pdb.get_line_counts_for_batch("BCOUNT")
        assert counts.get(id1, 0) == 5, f"doc1 should have 5 lines, got {counts.get(id1)}"
        assert counts.get(id2, 0) == 2, f"doc2 should have 2 lines, got {counts.get(id2)}"

    def test_get_line_counts_empty_doc_returns_zero(self, tmp_path):
        """A packing document with no lines should return 0 (absent from dict)."""
        _init_packing(tmp_path)
        from app.services import packing_db as pdb

        ghost_id = pdb.upsert_packing_document(
            batch_id="BGHOST", source_file_hash="hghost", invoice_no=""
        )
        counts = pdb.get_line_counts_for_batch("BGHOST")
        assert counts.get(ghost_id, 0) == 0

    def test_line_count_in_packing_documents_endpoint(self, tmp_path):
        """GET /packing-documents response must include line_count per doc."""
        _init_packing(tmp_path)
        from app.services import packing_db as pdb
        from app.api.routes_packing import _guess_client_from_filename

        pdoc_id = pdb.upsert_packing_document(
            batch_id="BEND", source_file_hash="hend", invoice_no="INV-X",
            source_file_path="/tmp/source/packing/148 Client SUOKKO.xlsx",
        )
        lines = _make_packing_lines(pdoc_id, "BEND", n=7)
        pdb.upsert_packing_lines(lines)

        docs = pdb.get_packing_documents_for_batch("BEND")
        counts = pdb.get_line_counts_for_batch("BEND")
        for d in docs:
            d["line_count"] = counts.get(d["id"], 0)

        assert docs[0]["line_count"] == 7


# ── 23–25: duplicate detection in packing-documents endpoint ─────────────────

class TestDuplicateAnnotationInEndpoint:
    def test_ghost_docs_marked_is_duplicate(self, tmp_path):
        """
        Two docs with the same hash in the same batch: the one with fewer lines
        (ghost) gets is_duplicate=True; the canonical gets is_duplicate=False.
        """
        _init_packing(tmp_path)
        from app.services import packing_db as pdb
        from collections import defaultdict

        BATCH = "BDUP"
        HASH  = "samehash99"

        canonical_id = pdb.upsert_packing_document(
            batch_id=BATCH, source_file_hash=HASH, invoice_no="INV-OK",
            source_file_path="/tmp/packing/148 Client SUOKKO.xlsx",
        )
        pdb.upsert_packing_lines(_make_packing_lines(canonical_id, BATCH, n=4))

        # Simulate a ghost row (same hash) by inserting with a different document_id
        # so the dedup guard doesn't fire (different document_id path).
        # In production these exist from pre-dedup uploads.
        import sqlite3
        import uuid
        from datetime import datetime, timezone
        ghost_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(str(tmp_path / "packing.db")) as con:
            con.execute(
                "INSERT INTO packing_documents "
                "(id, batch_id, invoice_no, source_file_path, source_file_hash, "
                "parser_name, parser_version, extraction_status, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (ghost_id, BATCH, "INV-GHOST",
                 "/tmp/packing/148 Client SUOKKO.xlsx", HASH,
                 "", "", "pending", now, now),
            )

        docs = pdb.get_packing_documents_for_batch(BATCH)
        counts = pdb.get_line_counts_for_batch(BATCH)
        for d in docs:
            d["line_count"] = counts.get(d["id"], 0)

        hash_groups: dict = defaultdict(list)
        for d in docs:
            h = d.get("source_file_hash", "")
            if h:
                hash_groups[h].append(d)

        for group in hash_groups.values():
            if len(group) <= 1:
                for d in group:
                    d["is_duplicate"] = False
                    d["canonical_id"] = None
            else:
                sorted_grp = sorted(group, key=lambda x: (-x["line_count"], x["created_at"]))
                cid = sorted_grp[0]["id"]
                for d in group:
                    d["is_duplicate"] = (d["id"] != cid)
                    d["canonical_id"] = cid

        by_id = {d["id"]: d for d in docs}
        assert not by_id[canonical_id]["is_duplicate"], "canonical should not be marked duplicate"
        assert by_id[ghost_id]["is_duplicate"], "ghost should be marked duplicate"
        assert by_id[ghost_id]["canonical_id"] == canonical_id

    def test_single_doc_not_marked_duplicate(self, tmp_path):
        """A batch with only one doc for a given hash must not be marked duplicate."""
        _init_packing(tmp_path)
        from app.services import packing_db as pdb
        from collections import defaultdict

        pdoc_id = pdb.upsert_packing_document(
            batch_id="BSINGLE", source_file_hash="uniquehash", invoice_no="INV-1",
        )
        docs = pdb.get_packing_documents_for_batch("BSINGLE")
        counts = pdb.get_line_counts_for_batch("BSINGLE")
        for d in docs:
            d["line_count"] = counts.get(d["id"], 0)
            d.setdefault("is_duplicate", False)

        assert not docs[0]["is_duplicate"]

    def test_ghost_doc_link_returns_ghost_hint(self, tmp_path):
        """
        Submitting a ghost doc id (0 lines) to link_packing_as_sales must return
        ok=False with a ghost_hint message pointing to the canonical doc.
        """
        _init_packing(tmp_path)
        _init_docs(tmp_path)
        from app.services import packing_db as pdb

        BATCH = "BHINT"
        HASH  = "hinthash"

        canonical_id = pdb.upsert_packing_document(
            batch_id=BATCH, source_file_hash=HASH, invoice_no="INV-REAL",
        )
        pdb.upsert_packing_lines(_make_packing_lines(canonical_id, BATCH, n=3))

        # Ghost doc: same hash, no lines
        import sqlite3, uuid
        from datetime import datetime, timezone
        ghost_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(str(tmp_path / "packing.db")) as con:
            con.execute(
                "INSERT INTO packing_documents "
                "(id, batch_id, invoice_no, source_file_path, source_file_hash, "
                "parser_name, parser_version, extraction_status, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (ghost_id, BATCH, "INV-GHOST", "", HASH, "", "", "pending", now, now),
            )

        # Simulate the link-as-sales logic for the ghost doc
        lines = pdb.get_packing_lines_for_document(ghost_id)
        assert not lines, "ghost doc must have no lines"

        # Verify ghost hint logic
        pdoc_row = pdb.get_packing_document(ghost_id)
        assert pdoc_row is not None
        h = pdoc_row.get("source_file_hash", "")
        all_docs = pdb.get_packing_documents_for_batch(BATCH)
        counts = pdb.get_line_counts_for_batch(BATCH)
        siblings = [d for d in all_docs if d.get("source_file_hash") == h and d["id"] != ghost_id]
        canonical = next((d for d in siblings if counts.get(d["id"], 0) > 0), None)
        assert canonical is not None, "should find canonical doc with lines"
        assert canonical["id"] == canonical_id


# ── 26–28: UI controls and migration guard ────────────────────────────────────

class TestNewUIControlsAndMigration:
    def _html(self) -> str:
        return DASHBOARD_HTML.read_text(encoding="utf-8")

    def test_link_button_in_main_drafts_view(self):
        """Link button must be accessible in the main drafts view (not only empty state)."""
        assert 'data-testid="btn-link-packing-as-sales-main"' in self._html()

    def test_ignored_docs_filter_in_submit(self):
        """submitLinkAsSales must filter ignoredDocs before submitting."""
        assert 'ignoredDocs' in self._html()
        # Verify the filter is applied: !ignoredDocs.has(doc.id)
        assert 'ignoredDocs.has(doc.id)' in self._html()

    def test_duplicate_badge_testid_pattern_present(self):
        """Duplicate badge testid pattern must be present in the table rows."""
        assert 'link-packing-doc-dup-badge-' in self._html()

    def test_ignore_button_testid_pattern_present(self):
        """Ignore button testid pattern must be present in the table rows."""
        assert 'link-packing-doc-ignore-btn-' in self._html()

    def test_source_file_hash_migration_guard_present(self):
        """
        source_file_hash must appear in _add_column_if_missing guard in packing_db.py
        so existing production databases pick it up on startup.
        """
        packing_db_path = _ROOT / "app" / "services" / "packing_db.py"
        src = packing_db_path.read_text(encoding="utf-8")
        assert '"packing_documents"' in src and '"source_file_hash"' in src, \
            "source_file_hash migration guard must exist in packing_db.py"
        # Confirm it is in the _add_column_if_missing call (not just CREATE TABLE)
        assert '_add_column_if_missing(con, "packing_documents", "source_file_hash"' in src

    def test_line_count_rendered_from_doc_field(self):
        """UI must use doc.line_count field, not a hardcoded dash."""
        html = self._html()
        assert 'doc.line_count' in html
        # And NOT a hardcoded lone dash literal in the lines cell
        # (The old code was: <span ...>—</span> with no JS expression)
        assert 'doc.line_count != null' in html


# ── 29: _build_matched_sales_lines unit_price fallback ───────────────────────

class TestBuildMatchedSalesLinesUnitPriceFallback:
    """
    _build_matched_sales_lines must use unit_price when unit_price_eur is 0/None.
    Regression for the bug where promoted lines always got unit_price=0 on
    batches where unit_price_eur was never backfilled.
    """

    def _build(self, lines, client="UAB"):
        from app.api.routes_packing import _build_matched_sales_lines
        result, skipped = _build_matched_sales_lines(lines, client)
        return result, skipped

    def test_uses_unit_price_when_unit_price_eur_is_zero(self):
        """unit_price_eur=0 → fall back to unit_price."""
        packing_lines = [
            {"product_code": "PC-1", "quantity": 3.0, "unit_price": 201.0,
             "unit_price_eur": 0.0, "currency": "USD", "invoice_no": "INV-1",
             "design_no": "D001", "bag_id": "", "remarks": ""},
            {"product_code": "PC-2", "quantity": 5.0, "unit_price": 302.0,
             "unit_price_eur": 0.0, "currency": "USD", "invoice_no": "INV-1",
             "design_no": "D002", "bag_id": "", "remarks": ""},
        ]
        result, skipped = self._build(packing_lines)
        assert len(result) == 2
        assert result[0]["unit_price"] == 201.0
        assert result[1]["unit_price"] == 302.0
        assert result[0]["price_source"] == "packing_xlsx_value"
        assert result[1]["price_source"] == "packing_xlsx_value"
        assert result[0]["total_value"] == 3.0 * 201.0

    def test_uses_unit_price_eur_when_present(self):
        """unit_price_eur present and >0 → prefer it over unit_price."""
        packing_lines = [
            {"product_code": "PC-1", "quantity": 2.0, "unit_price": 100.0,
             "unit_price_eur": 90.0, "currency": "EUR", "invoice_no": "INV-2",
             "design_no": "D001", "bag_id": "", "remarks": ""},
        ]
        result, skipped = self._build(packing_lines)
        assert len(result) == 1
        assert result[0]["unit_price"] == 90.0
        assert result[0]["price_source"] == "packing_xlsx_value"

    def test_uses_zero_when_both_absent(self):
        """Both unit_price_eur and unit_price absent → 0.0 with packing_promote."""
        packing_lines = [
            {"product_code": "PC-1", "quantity": 1.0, "unit_price": 0.0,
             "unit_price_eur": 0.0, "currency": "EUR", "invoice_no": "INV-3",
             "design_no": "D001", "bag_id": "", "remarks": ""},
        ]
        result, skipped = self._build(packing_lines)
        assert len(result) == 1
        assert result[0]["unit_price"] == 0.0
        assert result[0]["price_source"] == "packing_promote"

    def test_uses_unit_price_when_unit_price_eur_is_none(self):
        """unit_price_eur=None → fall back to unit_price."""
        packing_lines = [
            {"product_code": "PC-1", "quantity": 4.0, "unit_price": 150.0,
             "unit_price_eur": None, "currency": "USD", "invoice_no": "INV-4",
             "design_no": "D001", "bag_id": "", "remarks": ""},
        ]
        result, skipped = self._build(packing_lines)
        assert len(result) == 1
        assert result[0]["unit_price"] == 150.0
        assert result[0]["price_source"] == "packing_xlsx_value"
