"""
test_supplier_invoice_ingestion.py — Ingestion layer for Estrella supplier invoices.

Tests the atlas/ingestion/supplier_invoices/ module (read-only; no write paths).

Coverage:
  A. classifier.py — last-noun authority rules
  B. parser.py — InvoiceLine field extraction from description strings
  C. parser.py — InvoiceBatch from structured dict
  D. Fixture: AWB 8400636576 — quantity, type, and financial totals
     (proving RING 6, PENDANT 7, total 13, FOB 12277, freight 95,
      insurance 55, CIF 12427, no STUD entries)

Classification authority rule:
    The LAST item-type keyword in a description is the final product noun.
    Descriptor keywords appearing before it (e.g. "Stud" in "Stud Jewell RING")
    do NOT override the final noun.

Read-only guard: confirmed by absence of wFirma / PZ / proforma imports.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add repo root to sys.path so 'atlas' package is importable.
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from atlas.ingestion.supplier_invoices.classifier import classify_product_type
from atlas.ingestion.supplier_invoices.parser import (
    parse_invoice_line,
    parse_invoice_batch,
    InvoiceLine,
    InvoiceBatch,
)
from atlas.ingestion.supplier_invoices.fixtures.awb_8400636576 import (
    AWB_8400636576_BATCH,
    AWB_8400636576_FREIGHT,
    AWB_8400636576_INSURANCE,
)


# ══════════════════════════════════════════════════════════════════════════════
# A. Classifier — last-noun authority
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifier:
    """Authority rule: last keyword wins; stud as non-final word is a style term."""

    @pytest.mark.parametrize("description,expected", [
        # Key corrections from AWB 8400636576
        ("PCS, 14KT Gold,LGD Gold Stud Jewell RING",       "RING"),
        ("PCS, 14KT Gold, LGD Gold Stud Jewell RING",      "RING"),
        ("PCS, PT950 Platinum,Stud With Diam Jewel RING",  "RING"),
        ("PCS, 14KT Gold,Stud Jewelry DIA&CLS RING",       "RING"),
        # Pendant cases
        ("PCS, 18KT Gold,Plain Jewellery PENDANT",         "PENDANT"),
        ("14KT Gold Stud Style PENDANT DIA",               "PENDANT"),
        # Standalone STUD (earrings) — last and only type keyword
        ("14KT Gold Stud Plain",                           "STUD"),
        ("18KT Gold Stud",                                 "STUD"),
        # Explicit earrings
        ("18KT EARRINGS LGD",                              "EARRINGS"),
        # Other types
        ("Silver Bracelet",                                "BRACELET"),
        ("Gold Necklace Chain",                            "CHAIN"),
    ])
    def test_classify_product_type(self, description, expected):
        result = classify_product_type(description)
        assert result == expected, (
            f"classify_product_type({description!r}): "
            f"expected {expected!r}, got {result!r}"
        )

    def test_stud_before_ring_does_not_classify_as_stud(self):
        """Core authority test: STUD before RING must not win."""
        assert classify_product_type("Stud Jewell RING") == "RING"

    def test_stud_before_pendant_does_not_classify_as_stud(self):
        assert classify_product_type("Stud Style PENDANT") == "PENDANT"

    def test_unknown_returns_unknown(self):
        assert classify_product_type("Plain Gold Jewellery") == "UNKNOWN"


# ══════════════════════════════════════════════════════════════════════════════
# B. Parser — InvoiceLine field extraction
# ══════════════════════════════════════════════════════════════════════════════

class TestParseInvoiceLine:

    def test_14kt_gold_stud_ring_classified_as_ring(self):
        line = parse_invoice_line(
            "PCS, 14KT Gold,LGD Gold Stud Jewell RING",
            quantity=1, rate=279.0, amount=279.0, hsn_code="71131914",
        )
        assert isinstance(line, InvoiceLine)
        assert line.product_type == "RING"
        assert line.material     == "Gold"
        assert line.purity_code  == "14KT"
        assert line.quantity     == 1
        assert line.amount       == 279.0
        assert line.hsn_code     == "71131914"

    def test_lgd_stone_detected(self):
        line = parse_invoice_line("PCS, 14KT Gold,LGD Gold Stud Jewell RING")
        assert "LGD" in line.stones

    def test_dia_cls_stones_detected(self):
        line = parse_invoice_line("PCS, 14KT Gold,Stud Jewelry DIA&CLS RING")
        assert "DIA" in line.stones
        assert "CLS" in line.stones

    def test_pt950_platinum_ring(self):
        line = parse_invoice_line(
            "PCS, PT950 Platinum,Plain Jewel RING",
            quantity=1, rate=2555.0, amount=2555.0, hsn_code="71131921",
        )
        assert line.product_type == "RING"
        assert line.material     == "Platinum"
        assert line.purity_code  == "PT950"
        assert line.amount       == 2555.0

    def test_pt950_stud_diam_ring(self):
        """Diam abbreviation detected as stone; type resolves to RING not STUD."""
        line = parse_invoice_line(
            "PCS, PT950 Platinum,Stud With Diam Jewel RING",
            quantity=1, rate=2830.0, amount=2830.0,
        )
        assert line.product_type == "RING"
        assert "DIA" in line.stones  # "Diam" maps to DIA pattern

    def test_18kt_gold_pendant(self):
        line = parse_invoice_line(
            "PCS, 18KT Gold,Plain Jewellery PENDANT",
            quantity=7, rate=650.0, amount=4550.0, hsn_code="71131911",
        )
        assert line.product_type == "PENDANT"
        assert line.material     == "Gold"
        assert line.purity_code  == "18KT"
        assert line.quantity     == 7
        assert line.amount       == 4550.0

    def test_uom_extracted_from_description(self):
        line = parse_invoice_line("PCS, 14KT Gold,Plain RING")
        assert line.uom == "PCS"

    def test_invoice_number_stored(self):
        line = parse_invoice_line("PCS, 14KT Gold,RING", invoice_number="EJL/26-27/233")
        assert line.invoice_number == "EJL/26-27/233"

    def test_no_production_import(self):
        """Ingestion parser must not import any write-path modules."""
        import atlas.ingestion.supplier_invoices.parser as _parser_mod
        import inspect
        src = inspect.getsource(_parser_mod)
        # Check for forbidden IMPORT statements (not word presence in comments)
        forbidden_imports = [
            "import wfirma", "from wfirma",
            "import queue_email", "queue_email(",
            "from app.api.routes_", "import routes_",
        ]
        for f in forbidden_imports:
            assert f.lower() not in src.lower(), (
                f"Forbidden import/call {f!r} found in parser.py — "
                "ingestion layer must be read-only"
            )


# ══════════════════════════════════════════════════════════════════════════════
# C. Parser — InvoiceBatch from dict
# ══════════════════════════════════════════════════════════════════════════════

class TestParseInvoiceBatch:

    @pytest.fixture
    def batch(self) -> InvoiceBatch:
        return parse_invoice_batch(AWB_8400636576_BATCH, awb="8400636576")

    def test_returns_invoice_batch(self, batch):
        assert isinstance(batch, InvoiceBatch)

    def test_awb_set(self, batch):
        assert batch.awb == "8400636576"

    def test_freight_stored(self, batch):
        assert batch.freight_usd == AWB_8400636576_FREIGHT

    def test_insurance_stored(self, batch):
        assert batch.insurance_usd == AWB_8400636576_INSURANCE


# ══════════════════════════════════════════════════════════════════════════════
# D. Fixture: AWB 8400636576 — quantity, type and financial totals
# ══════════════════════════════════════════════════════════════════════════════

class TestAWB8400636576:
    """Pins the corrected batch totals after last-noun-authority fix."""

    @pytest.fixture(scope="class")
    def batch(self) -> InvoiceBatch:
        return parse_invoice_batch(AWB_8400636576_BATCH, awb="8400636576")

    # ── Quantity assertions ────────────────────────────────────────────────────

    def test_total_13_pcs(self, batch):
        assert batch.total_quantity == 13, (
            f"Expected 13 total PCS, got {batch.total_quantity}"
        )

    def test_pendant_7_pcs(self, batch):
        qty_by_type = batch.quantity_by_type
        pendant_qty = qty_by_type.get("PENDANT", 0)
        assert pendant_qty == 7, (
            f"Expected 7 PENDANT PCS, got {pendant_qty}"
        )

    def test_ring_6_pcs(self, batch):
        qty_by_type = batch.quantity_by_type
        ring_qty = qty_by_type.get("RING", 0)
        assert ring_qty == 6, (
            f"Expected 6 RING PCS, got {ring_qty}. "
            "Lines: " + str([l.description for l in batch.lines if l.product_type == "RING"])
        )

    def test_no_stud_category(self, batch):
        """After last-noun-authority fix: no lines should classify as STUD."""
        stud_lines = [l for l in batch.lines if l.product_type == "STUD"]
        assert stud_lines == [], (
            f"Expected zero STUD lines, got {len(stud_lines)}:\n"
            + "\n".join(f"  {l.description!r}" for l in stud_lines)
        )

    def test_ring_plus_pendant_equals_total(self, batch):
        qty_by_type = batch.quantity_by_type
        assert qty_by_type.get("RING", 0) + qty_by_type.get("PENDANT", 0) == 13

    # ── Financial assertions ────────────────────────────────────────────────────

    def test_fob_usd_12277(self, batch):
        """FOB = sum of all line_total values = 12,277."""
        assert batch.computed_fob_usd == 12277.0, (
            f"Expected FOB USD 12,277, got {batch.computed_fob_usd}"
        )

    def test_freight_usd_95(self, batch):
        assert batch.freight_usd == 95.0, (
            f"Expected freight USD 95, got {batch.freight_usd}"
        )

    def test_insurance_usd_55(self, batch):
        assert batch.insurance_usd == 55.0, (
            f"Expected insurance USD 55, got {batch.insurance_usd}"
        )

    def test_cif_usd_12427(self, batch):
        """CIF = FOB + freight + insurance = 12,277 + 95 + 55 = 12,427."""
        assert batch.computed_cif_usd == 12427.0, (
            f"Expected CIF USD 12,427, got {batch.computed_cif_usd}"
        )

    def test_stated_cif_matches_computed(self, batch):
        """Fixture's invoice_totals CIF must match the computed value."""
        assert batch.cif_usd == batch.computed_cif_usd, (
            f"Stated CIF ({batch.cif_usd}) != computed CIF ({batch.computed_cif_usd})"
        )

    # ── Per-invoice traceability ────────────────────────────────────────────────

    def test_all_7_lines_parsed(self, batch):
        assert len(batch.lines) == 7, (
            f"Expected 7 invoice lines, got {len(batch.lines)}"
        )

    def test_invoice_numbers_traceable(self, batch):
        inv_nos = {l.invoice_number for l in batch.lines}
        assert "EJL/26-27/233" in inv_nos
        assert "EJL/26-27/234" in inv_nos
        assert "EJL/26-27/235" in inv_nos
        assert "EJL/26-27/236" in inv_nos

    def test_hsn_codes_present(self, batch):
        """All lines must have an HSN code (required for customs)."""
        for line in batch.lines:
            assert line.hsn_code, (
                f"Missing HSN code for: {line.description!r}"
            )
