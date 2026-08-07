"""
test_packing_db.py — Tests for the packing list DB and extraction pipeline.

Covers:
  1.  init_packing_db creates both tables
  2.  init_packing_db is idempotent
  3.  upsert_packing_document inserts and returns id
  4.  upsert_packing_document updates in place when document_id supplied
  5.  upsert_packing_lines inserts rows, returns count
  6.  upsert_packing_lines skips duplicates (same dedup key)
  7.  upsert_packing_lines replaces on force_reextract=True
  8.  get_packing_lines_for_batch returns only that batch, ordered
  9.  get_packing_lines_for_document returns only that document
  10. get_packing_line_by_product_code returns correct row
  11. load_invoice_lines reads pz_rows.json and assigns sequential positions
  12. product_code sequence matches invoice line order
  13. match_packing_to_invoice — direct match (invoice_no + line_position)
  14. match_packing_to_invoice — fuzzy match (invoice_no + item_type + qty)
  15. match_packing_to_invoice — no-match row marked manual review
  16. design_no stored and retrievable
  17. batch_no stored and retrievable
  18. bag_id stored and retrievable
  19. requires_manual_review stored as 1/0, readable as bool
  20. full pipeline: process_packing_upload with XLSX creates DB rows
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def db(tmp_path):
    from app.services.packing_db import init_packing_db
    db_path = tmp_path / "packing.db"
    init_packing_db(db_path)
    return db_path


def _make_line(**kw) -> Dict[str, Any]:
    defaults = dict(
        packing_document_id="DOC001",
        batch_id="BATCH001",
        invoice_no="EJL/26-27/100",
        invoice_line_position=1,
        product_code="EJL/26-27/100-1",
        design_no="D-100",
        batch_no="BN-001",
        bag_id="BAG-01",
        tray_id="",
        item_type="RING",
        uom="PCS",
        quantity=5.0,
        gross_weight=10.0,
        net_weight=9.5,
        metal="GOLD",
        karat="18K",
        stone_type="",
        remarks="",
        extracted_confidence=1.0,
        requires_manual_review=False,
    )
    defaults.update(kw)
    return defaults


# ── Table creation ─────────────────────────────────────────────────────────────

class TestInit:
    def test_tables_created(self, db):
        import sqlite3
        con = sqlite3.connect(str(db))
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "packing_documents" in tables
        assert "packing_lines" in tables
        con.close()

    def test_init_idempotent(self, tmp_path):
        from app.services.packing_db import init_packing_db
        p = tmp_path / "packing.db"
        init_packing_db(p)
        init_packing_db(p)   # must not raise


# ── packing_documents ─────────────────────────────────────────────────────────

class TestPackingDocuments:
    def test_insert_returns_id(self, db):
        from app.services import packing_db as pdb
        doc_id = pdb.upsert_packing_document(
            batch_id="B1", invoice_no="EJL/26-27/100",
            source_file_path="/tmp/pl.xlsx", source_file_hash="abc123",
            parser_name="test", parser_version="1.0",
            extraction_status="complete",
        )
        assert isinstance(doc_id, str)
        assert len(doc_id) == 36   # UUID4

    def test_get_document(self, db):
        from app.services import packing_db as pdb
        doc_id = pdb.upsert_packing_document(
            batch_id="B1", invoice_no="EJL/26-27/100",
            source_file_hash="h1", parser_name="p", parser_version="1",
            extraction_status="complete",
        )
        doc = pdb.get_packing_document(doc_id)
        assert doc is not None
        assert doc["batch_id"] == "B1"
        assert doc["invoice_no"] == "EJL/26-27/100"
        assert doc["extraction_status"] == "complete"

    def test_update_in_place(self, db):
        from app.services import packing_db as pdb
        doc_id = pdb.upsert_packing_document(
            batch_id="B1", extraction_status="pending",
            source_file_hash="h1", parser_name="p", parser_version="1",
        )
        pdb.upsert_packing_document(
            batch_id="B1", extraction_status="complete",
            source_file_hash="h1", parser_name="p", parser_version="1",
            document_id=doc_id,
        )
        doc = pdb.get_packing_document(doc_id)
        assert doc["extraction_status"] == "complete"

    def test_get_documents_for_batch(self, db):
        from app.services import packing_db as pdb
        pdb.upsert_packing_document(batch_id="B1", source_file_hash="h1",
                                    parser_name="p", parser_version="1")
        pdb.upsert_packing_document(batch_id="B1", source_file_hash="h2",
                                    parser_name="p", parser_version="1")
        pdb.upsert_packing_document(batch_id="B2", source_file_hash="h3",
                                    parser_name="p", parser_version="1")
        docs = pdb.get_packing_documents_for_batch("B1")
        assert len(docs) == 2
        assert all(d["batch_id"] == "B1" for d in docs)


# ── packing_lines ─────────────────────────────────────────────────────────────

class TestPackingLines:
    def test_insert_returns_count(self, db):
        from app.services import packing_db as pdb
        count = pdb.upsert_packing_lines([_make_line()])
        assert count == 1

    def test_dedup_same_key_skipped(self, db):
        from app.services import packing_db as pdb
        pdb.upsert_packing_lines([_make_line()])
        count = pdb.upsert_packing_lines([_make_line()])   # same key
        assert count == 0
        assert len(pdb.get_packing_lines_for_batch("BATCH001")) == 1

    def test_dedup_different_bag_inserted(self, db):
        from app.services import packing_db as pdb
        pdb.upsert_packing_lines([_make_line(bag_id="BAG-01")])
        count = pdb.upsert_packing_lines([_make_line(bag_id="BAG-02")])
        assert count == 1
        assert len(pdb.get_packing_lines_for_batch("BATCH001")) == 2

    def test_force_reextract_overwrites(self, db):
        from app.services import packing_db as pdb
        pdb.upsert_packing_lines([_make_line(quantity=5.0)])
        count = pdb.upsert_packing_lines(
            [_make_line(quantity=7.0)], force_reextract=True
        )
        assert count == 1
        lines = pdb.get_packing_lines_for_batch("BATCH001")
        assert lines[0]["quantity"] == pytest.approx(7.0)

    def test_match_strategy_persisted_on_insert_and_update(self, db):
        """The matcher has always reported WHICH evidence placed a row; the
        write path used to drop it, leaving extracted_confidence as a bare
        number an operator could not audit.  Pinned on both paths because a
        column that is only written on INSERT silently goes stale on re-upload.
        """
        from app.services import packing_db as pdb
        pdb.upsert_packing_lines([_make_line(match_strategy="type+qty+rate+metal")])
        lines = pdb.get_packing_lines_for_batch("BATCH001")
        assert lines[0]["match_strategy"] == "type+qty+rate+metal"

        pdb.upsert_packing_lines(
            [_make_line(match_strategy="type+metal_aggregate")], force_reextract=True
        )
        lines = pdb.get_packing_lines_for_batch("BATCH001")
        assert len(lines) == 1
        assert lines[0]["match_strategy"] == "type+metal_aggregate"

    def test_match_strategy_absent_is_null_not_empty_string(self, db):
        """Unmatched rows carry no strategy; NULL says 'never placed', which is
        distinguishable from a placement whose strategy was lost."""
        from app.services import packing_db as pdb
        pdb.upsert_packing_lines([_make_line()])
        lines = pdb.get_packing_lines_for_batch("BATCH001")
        assert lines[0]["match_strategy"] is None

    def test_match_strategy_does_not_reopen_operator_review(self, db):
        """match_strategy is machine evidence, not source content: improving the
        matcher must not look like the source document changed."""
        from app.services.packing_db import compute_source_revision
        base = _make_line(match_strategy="type+qty")
        changed = _make_line(match_strategy="type+qty+rate+metal")
        assert compute_source_revision(base) == compute_source_revision(changed)

    def test_dedup_pack_sr_across_documents_skipped(self, db):
        """Re-upload contract: packing_document_id is traceability only, NOT
        part of the pack_sr dedup key (batch_id, invoice_no, pack_sr). A
        re-upload registers a NEW document id but must match the same logical
        row instead of duplicating it (the 2 -> 4 defect). bag_id empty =
        aggregated list, so only the pack_sr-primary lookup can match."""
        from app.services import packing_db as pdb
        pdb.upsert_packing_lines(
            [_make_line(packing_document_id="DOC001", pack_sr=14, bag_id="")])
        count = pdb.upsert_packing_lines(
            [_make_line(packing_document_id="DOC002", pack_sr=14, bag_id="")])
        assert count == 0
        lines = pdb.get_packing_lines_for_batch("BATCH001")
        assert len(lines) == 1
        # Without force_reextract the original row — including its
        # traceability pointer — is untouched.
        assert lines[0]["packing_document_id"] == "DOC001"

    def test_dedup_pack_sr_distinct_serials_inserted(self, db):
        """Distinct source serials are distinct physical lines — the widened
        key must not over-collapse them."""
        from app.services import packing_db as pdb
        pdb.upsert_packing_lines([_make_line(pack_sr=14, bag_id="")])
        count = pdb.upsert_packing_lines([_make_line(pack_sr=22, bag_id="")])
        assert count == 1
        assert len(pdb.get_packing_lines_for_batch("BATCH001")) == 2

    def test_force_reextract_pack_sr_updates_across_documents(self, db):
        """force_reextract re-upload finds the row via the pack_sr key even
        under a new document id, updates it in place, and re-points the
        traceability column to the new document."""
        from app.services import packing_db as pdb
        pdb.upsert_packing_lines(
            [_make_line(packing_document_id="DOC001", pack_sr=14, bag_id="",
                        quantity=5.0)])
        count = pdb.upsert_packing_lines(
            [_make_line(packing_document_id="DOC002", pack_sr=14, bag_id="",
                        quantity=7.0)],
            force_reextract=True,
        )
        assert count == 1
        lines = pdb.get_packing_lines_for_batch("BATCH001")
        assert len(lines) == 1
        assert lines[0]["quantity"] == pytest.approx(7.0)
        assert lines[0]["packing_document_id"] == "DOC002"

    def test_force_reextract_confirmed_row_keeps_invoice_line_position(self, db):
        """A confirmed row's product_code and invoice_line_position name ONE
        invoice line together. force_reextract preserves the operator's
        product_code — so it must preserve the position too, or the two columns
        end up naming different invoice lines. pack_sr-keyed, bag_id empty:
        the one lookup path that can match a row at a different position."""
        from app.services import packing_db as pdb
        pdb.upsert_packing_lines(
            [_make_line(pack_sr=14, bag_id="", invoice_line_position=1,
                        product_code="EJL/26-27/100-1")])
        pdb.confirm_product_review("BATCH001", "EJL/26-27/100-1", "op-test")
        count = pdb.upsert_packing_lines(
            [_make_line(pack_sr=14, bag_id="", invoice_line_position=5,
                        product_code="EJL/26-27/100-9")],
            force_reextract=True,
        )
        assert count == 1
        lines = pdb.get_packing_lines_for_batch("BATCH001")
        assert len(lines) == 1
        assert lines[0]["product_code"] == "EJL/26-27/100-1"
        assert lines[0]["invoice_line_position"] == 1
        # EXPLICIT AND INTENTIONAL: pinning the position means a position-ONLY
        # re-extraction leaves the stored row's source_revision equal to the
        # confirmed snapshot, so review does NOT reopen. The governed channel
        # for structural position corrections is the rematch path (which
        # excludes confirmed rows at plan level and surfaces them to the
        # operator), not a silent force_reextract drift.
        assert (
            pdb.compute_source_revision(dict(lines[0]))
            == lines[0]["operator_source_revision"]
        )

    def test_force_reextract_unconfirmed_row_moves_invoice_line_position(self, db):
        """Placement is what a re-extraction exists to correct: an UNCONFIRMED
        row takes the new extraction's position (and code) on force_reextract."""
        from app.services import packing_db as pdb
        pdb.upsert_packing_lines(
            [_make_line(pack_sr=14, bag_id="", invoice_line_position=1,
                        product_code="EJL/26-27/100-1")])
        count = pdb.upsert_packing_lines(
            [_make_line(pack_sr=14, bag_id="", invoice_line_position=5,
                        product_code="EJL/26-27/100-9")],
            force_reextract=True,
        )
        assert count == 1
        lines = pdb.get_packing_lines_for_batch("BATCH001")
        assert len(lines) == 1
        assert lines[0]["product_code"] == "EJL/26-27/100-9"
        assert lines[0]["invoice_line_position"] == 5

    def test_get_lines_for_batch_isolated(self, db):
        from app.services import packing_db as pdb
        pdb.upsert_packing_lines([_make_line(batch_id="B1")])
        pdb.upsert_packing_lines([_make_line(batch_id="B2",
                                             bag_id="BAG-XYZ",
                                             invoice_line_position=2)])
        lines = pdb.get_packing_lines_for_batch("B1")
        assert len(lines) == 1
        assert lines[0]["batch_id"] == "B1"

    def test_get_lines_ordered_by_invoice_position(self, db):
        from app.services import packing_db as pdb
        pdb.upsert_packing_lines([
            _make_line(invoice_line_position=3, bag_id="C"),
            _make_line(invoice_line_position=1, bag_id="A"),
            _make_line(invoice_line_position=2, bag_id="B"),
        ])
        lines = pdb.get_packing_lines_for_batch("BATCH001")
        positions = [l["invoice_line_position"] for l in lines]
        assert positions == [1, 2, 3]

    def test_design_no_stored(self, db):
        from app.services import packing_db as pdb
        pdb.upsert_packing_lines([_make_line(design_no="DESIGN-X")])
        lines = pdb.get_packing_lines_for_batch("BATCH001")
        assert lines[0]["design_no"] == "DESIGN-X"

    def test_batch_no_stored(self, db):
        from app.services import packing_db as pdb
        pdb.upsert_packing_lines([_make_line(batch_no="LOT-999")])
        lines = pdb.get_packing_lines_for_batch("BATCH001")
        assert lines[0]["batch_no"] == "LOT-999"

    def test_bag_id_stored(self, db):
        from app.services import packing_db as pdb
        pdb.upsert_packing_lines([_make_line(bag_id="BAG-007")])
        lines = pdb.get_packing_lines_for_batch("BATCH001")
        assert lines[0]["bag_id"] == "BAG-007"

    def test_requires_manual_review_stored(self, db):
        from app.services import packing_db as pdb
        pdb.upsert_packing_lines([_make_line(requires_manual_review=True,
                                             product_code=None,
                                             invoice_line_position=None)])
        lines = pdb.get_packing_lines_for_batch("BATCH001")
        assert lines[0]["requires_manual_review"] == 1

    def test_get_lines_for_document(self, db):
        from app.services import packing_db as pdb
        pdb.upsert_packing_lines([
            _make_line(packing_document_id="DOC001"),
            _make_line(packing_document_id="DOC002", bag_id="BAG-OTHER",
                       invoice_line_position=2),
        ])
        lines = pdb.get_packing_lines_for_document("DOC001")
        assert len(lines) == 1

    def test_get_line_by_product_code(self, db):
        from app.services import packing_db as pdb
        pdb.upsert_packing_lines([_make_line(product_code="EJL/26-27/100-1")])
        line = pdb.get_packing_line_by_product_code("EJL/26-27/100-1")
        assert line is not None
        assert line["product_code"] == "EJL/26-27/100-1"


# ── Invoice line extraction ───────────────────────────────────────────────────

class TestLoadInvoiceLines:
    def test_reads_pz_rows(self, tmp_path):
        from app.services.invoice_packing_extractor import load_invoice_lines
        pz_rows = [
            {"invoice_no": "EJL/26-27/100", "item_type": "RING",
             "quantity": 2, "unit": "PCS",
             "unit_netto_pln": 100.0, "line_netto_pln": 200.0,
             "description_en": "Gold Ring"},
            {"invoice_no": "EJL/26-27/100", "item_type": "BRACELET",
             "quantity": 1, "unit": "PCS",
             "unit_netto_pln": 300.0, "line_netto_pln": 300.0,
             "description_en": "Gold Bracelet"},
            {"invoice_no": "EJL/26-27/101", "item_type": "EARRINGS",
             "quantity": 3, "unit": "PCS",
             "unit_netto_pln": 50.0, "line_netto_pln": 150.0,
             "description_en": "Silver Earrings"},
        ]
        (tmp_path / "pz_rows.json").write_text(
            json.dumps(pz_rows), encoding="utf-8"
        )
        lines = load_invoice_lines(tmp_path)
        assert len(lines) == 3

    def test_product_code_sequence(self, tmp_path):
        from app.services.invoice_packing_extractor import load_invoice_lines
        pz_rows = [
            {"invoice_no": "EJL/26-27/100", "item_type": "RING", "quantity": 1,
             "unit": "PCS", "unit_netto_pln": 100.0, "line_netto_pln": 100.0,
             "description_en": "R1"},
            {"invoice_no": "EJL/26-27/100", "item_type": "RING", "quantity": 2,
             "unit": "PCS", "unit_netto_pln": 200.0, "line_netto_pln": 400.0,
             "description_en": "R2"},
            {"invoice_no": "EJL/26-27/100", "item_type": "PENDANT", "quantity": 1,
             "unit": "PCS", "unit_netto_pln": 150.0, "line_netto_pln": 150.0,
             "description_en": "P1"},
        ]
        (tmp_path / "pz_rows.json").write_text(
            json.dumps(pz_rows), encoding="utf-8"
        )
        lines = load_invoice_lines(tmp_path)
        codes = [l["product_code"] for l in lines]
        assert codes == [
            "EJL/26-27/100-1",
            "EJL/26-27/100-2",
            "EJL/26-27/100-3",
        ]

    def test_invoice_line_position_sequential(self, tmp_path):
        from app.services.invoice_packing_extractor import load_invoice_lines
        pz_rows = [
            {"invoice_no": "EJL/26-27/100", "item_type": "RING",
             "quantity": 1, "unit": "PCS",
             "unit_netto_pln": 100.0, "line_netto_pln": 100.0,
             "description_en": "R1"},
            {"invoice_no": "EJL/26-27/100", "item_type": "BRACELET",
             "quantity": 1, "unit": "PCS",
             "unit_netto_pln": 200.0, "line_netto_pln": 200.0,
             "description_en": "B1"},
        ]
        (tmp_path / "pz_rows.json").write_text(
            json.dumps(pz_rows), encoding="utf-8"
        )
        lines = load_invoice_lines(tmp_path)
        positions = [l["invoice_line_position"] for l in lines]
        assert positions == [1, 2]

    def test_missing_pz_rows_returns_empty(self, tmp_path):
        from app.services.invoice_packing_extractor import load_invoice_lines
        assert load_invoice_lines(tmp_path) == []


# ── Matching ──────────────────────────────────────────────────────────────────

class TestMatching:
    def _invoice_lines(self):
        return [
            {"invoice_no": "EJL/26-27/100", "invoice_line_position": 1,
             "product_code": "EJL/26-27/100-1", "item_type": "RING",
             "quantity": 2.0},
            {"invoice_no": "EJL/26-27/100", "invoice_line_position": 2,
             "product_code": "EJL/26-27/100-2", "item_type": "BRACELET",
             "quantity": 1.0},
            {"invoice_no": "EJL/26-27/101", "invoice_line_position": 1,
             "product_code": "EJL/26-27/101-1", "item_type": "EARRINGS",
             "quantity": 3.0},
        ]

    def test_direct_match(self):
        from app.services.invoice_packing_extractor import match_packing_to_invoice
        packing = [{"invoice_no": "EJL/26-27/100", "invoice_line_position": 1,
                    "design_no": "D1", "quantity": 2.0}]
        result = match_packing_to_invoice(packing, self._invoice_lines())
        assert result[0]["product_code"] == "EJL/26-27/100-1"
        assert result[0]["requires_manual_review"] is False
        assert result[0]["extracted_confidence"] == pytest.approx(1.0)

    def test_fuzzy_match_item_type_qty(self):
        from app.services.invoice_packing_extractor import match_packing_to_invoice
        packing = [{"invoice_no": "EJL/26-27/100", "item_type": "RING",
                    "quantity": 2.0, "design_no": "D1"}]
        result = match_packing_to_invoice(packing, self._invoice_lines())
        assert result[0]["product_code"] == "EJL/26-27/100-1"
        assert result[0]["extracted_confidence"] == pytest.approx(0.8)

    def test_no_match_manual_review(self):
        from app.services.invoice_packing_extractor import match_packing_to_invoice
        packing = [{"invoice_no": "EJL/26-27/999", "item_type": "NECKLACE",
                    "quantity": 1.0, "design_no": "UNKNOWN"}]
        result = match_packing_to_invoice(packing, self._invoice_lines())
        assert result[0]["product_code"] is None
        assert result[0]["requires_manual_review"] is True
        assert result[0]["extracted_confidence"] == pytest.approx(0.0)

    def test_packing_row_linked_to_correct_product_code(self, db):
        """Full round-trip: match → store → read → verify product_code."""
        from app.services import packing_db as pdb
        from app.services.invoice_packing_extractor import match_packing_to_invoice

        invoice_lines = [
            {"invoice_no": "EJL/26-27/100", "invoice_line_position": 1,
             "product_code": "EJL/26-27/100-1", "item_type": "RING",
             "quantity": 2.0},
        ]
        packing = [{"invoice_no": "EJL/26-27/100", "item_type": "RING",
                    "quantity": 2.0, "design_no": "D-RING",
                    "batch_no": "BN-X", "bag_id": "BAG-10"}]
        matched = match_packing_to_invoice(packing, invoice_lines)

        doc_id = pdb.upsert_packing_document(
            batch_id="BATCH001", invoice_no="EJL/26-27/100",
            source_file_hash="h", parser_name="test", parser_version="1",
            extraction_status="complete",
        )
        lines = [{**m, "packing_document_id": doc_id, "batch_id": "BATCH001"}
                 for m in matched]
        pdb.upsert_packing_lines(lines)

        stored = pdb.get_packing_line_by_product_code("EJL/26-27/100-1")
        assert stored is not None
        assert stored["design_no"] == "D-RING"
        assert stored["batch_no"] == "BN-X"
        assert stored["bag_id"] == "BAG-10"


# ── Full pipeline (XLSX) ──────────────────────────────────────────────────────

class TestProcessPackingUpload:
    def test_xlsx_upload_creates_db_rows(self, tmp_path, db):
        """End-to-end: XLSX with known columns → DB rows with product_codes."""
        import openpyxl
        from app.services.invoice_packing_extractor import process_packing_upload

        # Create pz_rows.json
        pz_rows = [
            {"invoice_no": "EJL/26-27/100", "item_type": "RING",
             "quantity": 2, "unit": "PCS",
             "unit_netto_pln": 100.0, "line_netto_pln": 200.0,
             "description_en": "Gold Ring"},
            {"invoice_no": "EJL/26-27/100", "item_type": "BRACELET",
             "quantity": 1, "unit": "PCS",
             "unit_netto_pln": 300.0, "line_netto_pln": 300.0,
             "description_en": "Gold Bracelet"},
        ]
        (tmp_path / "pz_rows.json").write_text(json.dumps(pz_rows), encoding="utf-8")

        # Create XLSX packing list
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["invoice_no", "item_type", "quantity", "design_no",
                   "batch_no", "bag_id", "metal", "karat"])
        ws.append(["EJL/26-27/100", "RING",     2, "D-001", "BN-A", "BAG-1", "GOLD", "18K"])
        ws.append(["EJL/26-27/100", "BRACELET", 1, "D-002", "BN-B", "BAG-2", "GOLD", "18K"])
        xlsx_path = tmp_path / "packing.xlsx"
        wb.save(str(xlsx_path))

        result = process_packing_upload(
            batch_id="BATCH001",
            batch_output_dir=tmp_path,
            packing_file_path=xlsx_path,
        )
        assert result["total_rows"] == 2
        assert result["matched_count"] == 2
        assert result["unmatched_count"] == 0

        # Verify product_codes assigned
        codes = [r["product_code"] for r in result["packing_rows"]]
        assert "EJL/26-27/100-1" in codes
        assert "EJL/26-27/100-2" in codes

    def test_unmatched_row_marked_manual_review(self, tmp_path, db):
        import openpyxl
        from app.services.invoice_packing_extractor import process_packing_upload

        pz_rows = [{"invoice_no": "EJL/26-27/100", "item_type": "RING",
                    "quantity": 2, "unit": "PCS",
                    "unit_netto_pln": 100.0, "line_netto_pln": 200.0,
                    "description_en": "Ring"}]
        (tmp_path / "pz_rows.json").write_text(json.dumps(pz_rows), encoding="utf-8")

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["invoice_no", "item_type", "quantity", "design_no"])
        ws.append(["EJL/26-27/999", "NECKLACE", 5, "D-UNKNOWN"])  # no match
        xlsx_path = tmp_path / "packing.xlsx"
        wb.save(str(xlsx_path))

        result = process_packing_upload(
            batch_id="BATCH001",
            batch_output_dir=tmp_path,
            packing_file_path=xlsx_path,
        )
        assert result["unmatched_count"] == 1
        row = result["packing_rows"][0]
        assert row["product_code"] is None
        assert row["requires_manual_review"] is True
