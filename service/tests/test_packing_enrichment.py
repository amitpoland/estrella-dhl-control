"""
test_packing_enrichment.py — Packing DB downstream integration tests.

Covers:
  1. get_packing_enrichment_for_batch returns List[row] per product_code
  2. Multi-bag: both bags appear under the same product_code key
  3. Enrichment excludes unmatched (no product_code) rows
  4. wFirma row stays single even when multiple bags exist (no duplication)
  5. wFirma packing_summary shows all bags; bag_count is correct
  6. wFirma graceful degradation with no packing data
  7. match_status is "manual_review" when any bag is flagged
  8. Accounting values unchanged by enrichment
  9. Barcode rows explode per physical bag (one row per bag, not per invoice line)
 10. Barcode excludes unmatched rows; reports count
 11. Manual-review bag flagged in barcode row
 12. barcode_value == product_code
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── Fixtures / helpers ────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    from app.services.packing_db import init_packing_db
    db_path = tmp_path / "packing.db"
    init_packing_db(db_path)
    return db_path


def _insert_bag(
    *,
    batch_id: str         = "B1",
    product_code: str     = "INV/001-1",
    invoice_no: str       = "INV/001",
    invoice_line_position: int = 1,
    design_no: str        = "D-001",
    batch_no: str         = "LOT-A",
    bag_id: str           = "BAG-01",
    tray_id: str          = "",
    quantity: float       = 2.0,
    gross_weight: float   = 10.0,
    net_weight: float     = 9.5,
    requires_manual_review: bool = False,
):
    """Insert one packing line (one physical bag) into the DB."""
    from app.services import packing_db as pdb
    doc_id = pdb.upsert_packing_document(batch_id=batch_id, invoice_no=invoice_no)
    pdb.upsert_packing_lines([{
        "packing_document_id":   doc_id,
        "batch_id":              batch_id,
        "invoice_no":            invoice_no,
        "invoice_line_position": invoice_line_position,
        "product_code":          product_code,
        "design_no":             design_no,
        "batch_no":              batch_no,
        "bag_id":                bag_id,
        "tray_id":               tray_id,
        "item_type":             "RING",
        "uom":                   "PCS",
        "quantity":              quantity,
        "gross_weight":          gross_weight,
        "net_weight":            net_weight,
        "metal":                 "",
        "karat":                 "",
        "stone_type":            "",
        "remarks":               "",
        "extracted_confidence":  0.8,
        "requires_manual_review": requires_manual_review,
    }])


def _insert_unmatched(batch_id: str = "B1"):
    from app.services import packing_db as pdb
    doc_id = pdb.upsert_packing_document(batch_id=batch_id, invoice_no="UNK")
    pdb.upsert_packing_lines([{
        "packing_document_id":   doc_id,
        "batch_id":              batch_id,
        "invoice_no":            "UNK",
        "invoice_line_position": None,
        "product_code":          None,
        "design_no":             "D-X",
        "batch_no":              "LOT-X",
        "bag_id":                "BAG-X",
        "tray_id":               "",
        "item_type":             "NECKLACE",
        "uom":                   "PCS",
        "quantity":              1.0,
        "gross_weight":          5.0,
        "net_weight":            4.5,
        "metal":                 "",
        "karat":                 "",
        "stone_type":            "",
        "remarks":               "",
        "extracted_confidence":  0.0,
        "requires_manual_review": True,
    }])


_DUMMY_AUDIT: Dict[str, Any] = {
    "customs_declaration": {"mrn": "MRN123", "nbp_rate": 4.0},
    "tracking_no": "AWB999",
    "settlement_mode": "standard",
}


def _make_pz_row(
    product_code: str  = "INV/001-1",
    invoice_no: str    = "INV/001",
    unit_netto: float  = 100.0,
    line_netto: float  = 200.0,
    line_brutto: float = 246.0,
) -> Dict[str, Any]:
    return {
        "product_code":       product_code,
        "invoice_no":         invoice_no,
        "description_en":     "Gold Ring",
        "pl_desc":            "Złoty pierścionek",
        "quantity":           5.0,
        "unit":               "PCS",
        "unit_netto_pln":     unit_netto,
        "line_netto_pln":     line_netto,
        "line_brutto_pln":    line_brutto,
        "allocated_duty_pln": 10.0,
        "item_type":          "RING",
    }


# ── 1. get_packing_enrichment_for_batch — return type ────────────────────────

class TestGetPackingEnrichment:

    def test_returns_list_per_product_code(self, db):
        _insert_bag()
        from app.services.packing_db import get_packing_enrichment_for_batch
        enrichment = get_packing_enrichment_for_batch("B1")
        assert "INV/001-1" in enrichment
        bags = enrichment["INV/001-1"]
        assert isinstance(bags, list)
        assert len(bags) == 1
        assert bags[0]["design_no"] == "D-001"
        assert bags[0]["bag_id"]    == "BAG-01"
        assert bags[0]["quantity"]  == pytest.approx(2.0)

    def test_multi_bag_both_appear(self, db):
        """Two bags for the same invoice line must both appear in the list."""
        _insert_bag(bag_id="BAG-01", quantity=2.0)
        _insert_bag(bag_id="BAG-02", quantity=3.0, invoice_line_position=1)
        from app.services.packing_db import get_packing_enrichment_for_batch
        enrichment = get_packing_enrichment_for_batch("B1")
        bags = enrichment["INV/001-1"]
        assert len(bags) == 2
        bag_ids = {b["bag_id"] for b in bags}
        assert bag_ids == {"BAG-01", "BAG-02"}
        total_qty = sum(b["quantity"] for b in bags)
        assert total_qty == pytest.approx(5.0)

    def test_excludes_unmatched_rows(self, db):
        _insert_unmatched()
        from app.services.packing_db import get_packing_enrichment_for_batch
        enrichment = get_packing_enrichment_for_batch("B1")
        assert enrichment == {}

    def test_different_product_codes_separate_keys(self, db):
        _insert_bag(product_code="INV/001-1", invoice_line_position=1, bag_id="BAG-01")
        _insert_bag(product_code="INV/001-2", invoice_line_position=2, bag_id="BAG-02")
        from app.services.packing_db import get_packing_enrichment_for_batch
        enrichment = get_packing_enrichment_for_batch("B1")
        assert len(enrichment) == 2
        assert len(enrichment["INV/001-1"]) == 1
        assert len(enrichment["INV/001-2"]) == 1

    def test_returns_empty_for_unknown_batch(self, db):
        from app.services.packing_db import get_packing_enrichment_for_batch
        assert get_packing_enrichment_for_batch("NONE") == {}

    def test_manual_review_flag_preserved(self, db):
        _insert_bag(requires_manual_review=True)
        from app.services.packing_db import get_packing_enrichment_for_batch
        enrichment = get_packing_enrichment_for_batch("B1")
        assert enrichment["INV/001-1"][0]["requires_manual_review"] == 1


# ── 2. wFirma enrichment — no row duplication ────────────────────────────────

class TestWfirmaEnrichment:

    def test_single_bag_enriched_correctly(self, db):
        _insert_bag()
        from app.services.packing_db import get_packing_enrichment_for_batch
        from app.api.routes_wfirma import _build_wfirma_rows
        enrichment = get_packing_enrichment_for_batch("B1")
        rows = _build_wfirma_rows([_make_pz_row()], _DUMMY_AUDIT, packing_enrichment=enrichment)
        assert len(rows) == 1                          # still ONE row
        r = rows[0]
        assert r["_design_no"]       == "D-001"
        assert r["_bag_id"]          == "BAG-01"       # direct for single-bag
        assert r["_match_status"]    == "matched"
        assert r["_bag_count"]       == 1
        assert "BAG-01(2)" in r["_packing_summary"]

    def test_multi_bag_stays_one_invoice_row(self, db):
        """Two bags must NOT produce two wFirma rows."""
        _insert_bag(bag_id="BAG-01", quantity=2.0)
        _insert_bag(bag_id="BAG-02", quantity=3.0, invoice_line_position=1)
        from app.services.packing_db import get_packing_enrichment_for_batch
        from app.api.routes_wfirma import _build_wfirma_rows
        enrichment = get_packing_enrichment_for_batch("B1")
        rows = _build_wfirma_rows([_make_pz_row()], _DUMMY_AUDIT, packing_enrichment=enrichment)
        assert len(rows) == 1                          # MUST be 1
        r = rows[0]
        assert r["_bag_count"]       == 2
        assert "BAG-01(2)" in r["_packing_summary"]
        assert "BAG-02(3)" in r["_packing_summary"]
        assert r["_bag_id"]          == ""             # blank when multi-bag
        assert r["_match_status"]    == "matched"

    def test_multi_bag_bag_id_blank_for_display(self, db):
        """_bag_id is only populated for single-bag rows to avoid ambiguity."""
        _insert_bag(bag_id="BAG-01", quantity=2.0)
        _insert_bag(bag_id="BAG-02", quantity=3.0, invoice_line_position=1)
        from app.services.packing_db import get_packing_enrichment_for_batch
        from app.api.routes_wfirma import _build_wfirma_rows
        enrichment = get_packing_enrichment_for_batch("B1")
        rows = _build_wfirma_rows([_make_pz_row()], _DUMMY_AUDIT, packing_enrichment=enrichment)
        assert rows[0]["_bag_id"] == ""

    def test_no_enrichment_graceful_degradation(self, db):
        from app.api.routes_wfirma import _build_wfirma_rows
        rows = _build_wfirma_rows([_make_pz_row()], _DUMMY_AUDIT, packing_enrichment={})
        r = rows[0]
        assert r["_design_no"]       == ""
        assert r["_bag_id"]          == ""
        assert r["_match_status"]    == "no_packing_data"
        assert r["_bag_count"]       == 0
        assert r["_packing_summary"] == ""

    def test_none_enrichment_same_as_empty(self, db):
        from app.api.routes_wfirma import _build_wfirma_rows
        rows = _build_wfirma_rows([_make_pz_row()], _DUMMY_AUDIT, packing_enrichment=None)
        assert rows[0]["_match_status"] == "no_packing_data"

    def test_accounting_values_unchanged_multi_bag(self, db):
        """Two bags must NOT change unit price or totals."""
        _insert_bag(bag_id="BAG-01", quantity=2.0)
        _insert_bag(bag_id="BAG-02", quantity=3.0, invoice_line_position=1)
        from app.services.packing_db import get_packing_enrichment_for_batch
        from app.api.routes_wfirma import _build_wfirma_rows
        enrichment = get_packing_enrichment_for_batch("B1")
        pz_row = _make_pz_row(unit_netto=181.12, line_netto=905.60, line_brutto=1113.89)
        rows_with    = _build_wfirma_rows([pz_row], _DUMMY_AUDIT, packing_enrichment=enrichment)
        rows_without = _build_wfirma_rows([pz_row], _DUMMY_AUDIT, packing_enrichment={})
        assert rows_with[0]["cena_netto"]     == pytest.approx(181.12)
        assert rows_with[0]["wartosc_netto"]  == pytest.approx(905.60)
        assert rows_with[0]["wartosc_brutto"] == pytest.approx(1113.89)
        assert rows_with[0]["cena_netto"]     == rows_without[0]["cena_netto"]
        assert rows_with[0]["wartosc_netto"]  == rows_without[0]["wartosc_netto"]

    def test_any_manual_review_bag_sets_status(self, db):
        """If any bag in a multi-bag set is flagged, match_status = manual_review."""
        _insert_bag(bag_id="BAG-01", requires_manual_review=False)
        _insert_bag(bag_id="BAG-02", requires_manual_review=True, invoice_line_position=1)
        from app.services.packing_db import get_packing_enrichment_for_batch
        from app.api.routes_wfirma import _build_wfirma_rows
        enrichment = get_packing_enrichment_for_batch("B1")
        rows = _build_wfirma_rows([_make_pz_row()], _DUMMY_AUDIT, packing_enrichment=enrichment)
        assert rows[0]["_match_status"] == "manual_review"

    def test_no_product_code_status(self, db):
        from app.api.routes_wfirma import _build_wfirma_rows
        pz_row = _make_pz_row()
        pz_row["product_code"] = None
        rows = _build_wfirma_rows([pz_row], _DUMMY_AUDIT, packing_enrichment={"X": []})
        assert rows[0]["_match_status"] == "no_product_code"


# ── 3. Barcode endpoint — one row per physical bag ────────────────────────────

class TestBarcodePreview:

    def test_single_bag_one_barcode_row(self, db):
        _insert_bag()
        from app.services import packing_db as pdb
        all_lines = pdb.get_packing_lines_for_batch("B1")
        matched   = [ln for ln in all_lines if ln.get("product_code")]
        assert len(matched) == 1
        row = matched[0]
        assert row["product_code"]  == "INV/001-1"
        assert row["bag_id"]        == "BAG-01"
        assert row["design_no"]     == "D-001"
        assert row["batch_no"]      == "LOT-A"

    def test_multi_bag_produces_two_barcode_rows(self, db):
        """Two bags for same invoice line → two distinct barcode rows."""
        _insert_bag(bag_id="BAG-01", quantity=2.0)
        _insert_bag(bag_id="BAG-02", quantity=3.0, invoice_line_position=1)
        from app.services import packing_db as pdb
        all_lines = pdb.get_packing_lines_for_batch("B1")
        matched   = [ln for ln in all_lines if ln.get("product_code")]
        rows = [
            {
                "product_code":           ln["product_code"],
                "invoice_no":             ln.get("invoice_no", ""),
                "design_no":              ln.get("design_no", ""),
                "batch_no":               ln.get("batch_no", ""),
                "bag_id":                 ln.get("bag_id", ""),
                "barcode_value": (
                    f"{ln['product_code']}|{ln['bag_id']}"
                    if ln.get("bag_id") else ln["product_code"]
                ),
                "requires_manual_review": bool(ln.get("requires_manual_review")),
            }
            for ln in matched
        ]
        assert len(rows) == 2
        bag_ids = {r["bag_id"] for r in rows}
        assert bag_ids == {"BAG-01", "BAG-02"}
        # product_code is shared; barcode_value must be unique per bag
        assert all(r["product_code"] == "INV/001-1" for r in rows)
        barcode_values = {r["barcode_value"] for r in rows}
        assert barcode_values == {"INV/001-1|BAG-01", "INV/001-1|BAG-02"}

    def test_multi_bag_barcode_values_unique(self, db):
        """Core requirement: two bags → two different barcode_values."""
        _insert_bag(bag_id="BAG-01", quantity=2.0)
        _insert_bag(bag_id="BAG-02", quantity=3.0, invoice_line_position=1)
        from app.services import packing_db as pdb
        all_lines = pdb.get_packing_lines_for_batch("B1")
        matched   = [ln for ln in all_lines if ln.get("product_code")]
        barcodes  = [
            f"{ln['product_code']}|{ln['bag_id']}" if ln.get("bag_id")
            else ln["product_code"]
            for ln in matched
        ]
        assert len(barcodes) == len(set(barcodes)), "barcode_values must be unique per bag"

    def test_barcode_excludes_unmatched(self, db):
        _insert_unmatched()
        from app.services import packing_db as pdb
        all_lines = pdb.get_packing_lines_for_batch("B1")
        matched = [ln for ln in all_lines if ln.get("product_code")]
        assert len(matched) == 0

    def test_unmatched_count_correct(self, db):
        _insert_bag()
        _insert_unmatched()
        from app.services import packing_db as pdb
        all_lines = pdb.get_packing_lines_for_batch("B1")
        matched   = [ln for ln in all_lines if ln.get("product_code")]
        unmatched = [ln for ln in all_lines if not ln.get("product_code")]
        assert len(matched)   == 1
        assert len(unmatched) == 1

    def test_manual_review_flagged_in_barcode(self, db):
        _insert_bag(requires_manual_review=True)
        from app.services import packing_db as pdb
        all_lines = pdb.get_packing_lines_for_batch("B1")
        matched = [ln for ln in all_lines if ln.get("product_code")]
        assert bool(matched[0]["requires_manual_review"]) is True

    def test_single_bag_barcode_value_is_product_code_pipe_bag(self, db):
        _insert_bag(product_code="EJL/26-27/100-3", bag_id="BAG-01")
        from app.services import packing_db as pdb
        all_lines = pdb.get_packing_lines_for_batch("B1")
        matched = [ln for ln in all_lines if ln.get("product_code")]
        ln = matched[0]
        barcode_value = (
            f"{ln['product_code']}|{ln['bag_id']}"
            if ln.get("bag_id") else ln["product_code"]
        )
        assert barcode_value == "EJL/26-27/100-3|BAG-01"

    def test_missing_bag_id_falls_back_to_product_code(self, db):
        """bag_id empty string → barcode_value = product_code only."""
        from app.services import packing_db as pdb
        doc_id = pdb.upsert_packing_document(batch_id="B1", invoice_no="INV/001")
        pdb.upsert_packing_lines([{
            "packing_document_id":   doc_id,
            "batch_id":              "B1",
            "invoice_no":            "INV/001",
            "invoice_line_position": 1,
            "product_code":          "INV/001-1",
            "design_no":             "D-001",
            "batch_no":              "LOT-A",
            "bag_id":                "",          # no bag_id
            "tray_id":               "",
            "item_type":             "RING",
            "uom":                   "PCS",
            "quantity":              1.0,
            "gross_weight":          5.0,
            "net_weight":            4.5,
            "metal": "", "karat": "", "stone_type": "", "remarks": "",
            "extracted_confidence":  0.8,
            "requires_manual_review": False,
        }])
        all_lines = pdb.get_packing_lines_for_batch("B1")
        matched = [ln for ln in all_lines if ln.get("product_code")]
        ln = matched[0]
        barcode_value = (
            f"{ln['product_code']}|{ln['bag_id']}"
            if ln.get("bag_id") else ln["product_code"]
        )
        assert barcode_value == "INV/001-1"
