"""
test_global_invoice_parser.py — Unit tests for global_invoice_parser.py

Fixture values from Invoice 088/2026-2027:
  FOB  USD 3,172.00
  Freight   USD 125.00
  Insurance USD  25.00
  CIF  USD 3,322.00
  183 PCS + 62 PRS = 245 total
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── Helpers ───────────────────────────────────────────────────────────────────

_SAMPLE_TEXT = """
COMMERCIAL INVOICE

Global Jewellery Pvt. Ltd.
Invoice No.: 088/2026-2027
Date: 15/04/2026

FOB Value: USD 3,172.00
Freight: USD 125.00
Insurance: USD 25.00
CIF Value: USD 3,322.00

Total Quantity: 183 PCS + 62 PRS
"""

_SPARSE_TEXT = """
Global Jewellery Pvt. Ltd.
088/2026-2027
3172.00
125.00
25.00
183 PCS
62 PRS
"""


def _fake_read_text(text: str):
    """Patch _read_pdf_text to return a given string."""
    def _inner(path):
        return text
    return _inner


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestInvoiceNoExtraction:
    def test_invoice_no_detected(self):
        from app.services.global_invoice_parser import parse_global_invoice_pdf
        with patch("app.services.global_invoice_parser._read_pdf_text",
                   _fake_read_text(_SAMPLE_TEXT)):
            result = parse_global_invoice_pdf(Path("/fake/invoice.pdf"), "invoice.pdf")
        assert result["invoice_no"] == "088/2026-2027"

    def test_invoice_no_in_sparse_text(self):
        from app.services.global_invoice_parser import parse_global_invoice_pdf
        with patch("app.services.global_invoice_parser._read_pdf_text",
                   _fake_read_text(_SPARSE_TEXT)):
            result = parse_global_invoice_pdf(Path("/fake/invoice.pdf"), "invoice.pdf")
        assert result["invoice_no"] == "088/2026-2027"

    def test_no_invoice_no_fallback(self):
        from app.services.global_invoice_parser import parse_global_invoice_pdf
        with patch("app.services.global_invoice_parser._read_pdf_text",
                   _fake_read_text("Some random text without invoice number.")):
            result = parse_global_invoice_pdf(Path("/fake/invoice.pdf"))
        assert result["invoice_no"] == ""
        assert result["extraction_method"] == "fallback"


class TestCIFTotals:
    def test_fob(self):
        from app.services.global_invoice_parser import parse_global_invoice_pdf
        with patch("app.services.global_invoice_parser._read_pdf_text",
                   _fake_read_text(_SAMPLE_TEXT)):
            result = parse_global_invoice_pdf(Path("/fake/invoice.pdf"))
        assert result["fob_usd"] == pytest.approx(3172.00)

    def test_freight(self):
        from app.services.global_invoice_parser import parse_global_invoice_pdf
        with patch("app.services.global_invoice_parser._read_pdf_text",
                   _fake_read_text(_SAMPLE_TEXT)):
            result = parse_global_invoice_pdf(Path("/fake/invoice.pdf"))
        assert result["freight_usd"] == pytest.approx(125.00)

    def test_insurance(self):
        from app.services.global_invoice_parser import parse_global_invoice_pdf
        with patch("app.services.global_invoice_parser._read_pdf_text",
                   _fake_read_text(_SAMPLE_TEXT)):
            result = parse_global_invoice_pdf(Path("/fake/invoice.pdf"))
        assert result["insurance_usd"] == pytest.approx(25.00)

    def test_cif(self):
        from app.services.global_invoice_parser import parse_global_invoice_pdf
        with patch("app.services.global_invoice_parser._read_pdf_text",
                   _fake_read_text(_SAMPLE_TEXT)):
            result = parse_global_invoice_pdf(Path("/fake/invoice.pdf"))
        assert result["cif_usd"] == pytest.approx(3322.00)

    def test_cif_calculated_when_not_explicit(self):
        """When CIF line missing, should be calculated as FOB + freight + insurance."""
        text = "Global Jewellery 088/2026-2027 FOB Value: USD 3,172.00 Freight: USD 125.00 Insurance: USD 25.00"
        from app.services.global_invoice_parser import parse_global_invoice_pdf
        with patch("app.services.global_invoice_parser._read_pdf_text",
                   _fake_read_text(text)):
            result = parse_global_invoice_pdf(Path("/fake/invoice.pdf"))
        assert result["cif_usd"] == pytest.approx(3322.00)


class TestQtyTotals:
    def test_pcs(self):
        from app.services.global_invoice_parser import parse_global_invoice_pdf
        with patch("app.services.global_invoice_parser._read_pdf_text",
                   _fake_read_text(_SAMPLE_TEXT)):
            result = parse_global_invoice_pdf(Path("/fake/invoice.pdf"))
        assert result["total_qty_pcs"] == 183

    def test_prs(self):
        from app.services.global_invoice_parser import parse_global_invoice_pdf
        with patch("app.services.global_invoice_parser._read_pdf_text",
                   _fake_read_text(_SAMPLE_TEXT)):
            result = parse_global_invoice_pdf(Path("/fake/invoice.pdf"))
        assert result["total_qty_prs"] == 62

    def test_total_in_aggregate_line(self):
        from app.services.global_invoice_parser import parse_global_invoice_pdf
        with patch("app.services.global_invoice_parser._read_pdf_text",
                   _fake_read_text(_SAMPLE_TEXT)):
            result = parse_global_invoice_pdf(Path("/fake/invoice.pdf"))
        assert len(result["lines"]) == 1
        assert result["lines"][0]["quantity"] == 245.0


class TestAggregateLineProductCode:
    def test_aggregate_product_code(self):
        from app.services.global_invoice_parser import parse_global_invoice_pdf
        with patch("app.services.global_invoice_parser._read_pdf_text",
                   _fake_read_text(_SAMPLE_TEXT)):
            result = parse_global_invoice_pdf(Path("/fake/invoice.pdf"))
        assert result["lines"][0]["product_code"] == "088/2026-2027-AGG"

    def test_exactly_one_line(self):
        from app.services.global_invoice_parser import parse_global_invoice_pdf
        with patch("app.services.global_invoice_parser._read_pdf_text",
                   _fake_read_text(_SAMPLE_TEXT)):
            result = parse_global_invoice_pdf(Path("/fake/invoice.pdf"))
        assert len(result["lines"]) == 1


class TestSafetyAndEdgeCases:
    def test_empty_pdf_no_crash(self):
        from app.services.global_invoice_parser import parse_global_invoice_pdf
        with patch("app.services.global_invoice_parser._read_pdf_text",
                   _fake_read_text("")):
            result = parse_global_invoice_pdf(Path("/fake/invoice.pdf"))
        assert result["supplier"] == "global_jewellery"
        assert result["error"] == "pdf_text_empty"

    def test_unrelated_text_no_crash(self):
        from app.services.global_invoice_parser import parse_global_invoice_pdf
        with patch("app.services.global_invoice_parser._read_pdf_text",
                   _fake_read_text("Lorem ipsum dolor sit amet")):
            result = parse_global_invoice_pdf(Path("/fake/invoice.pdf"))
        assert result["supplier"] == "global_jewellery"
        assert result["fob_usd"] == 0.0
        assert result["cif_usd"] == 0.0

    def test_supplier_field_always_set(self):
        from app.services.global_invoice_parser import parse_global_invoice_pdf
        with patch("app.services.global_invoice_parser._read_pdf_text",
                   _fake_read_text(_SAMPLE_TEXT)):
            result = parse_global_invoice_pdf(Path("/fake/invoice.pdf"))
        assert result["supplier"] == "global_jewellery"

    def test_currency_always_usd(self):
        from app.services.global_invoice_parser import parse_global_invoice_pdf
        with patch("app.services.global_invoice_parser._read_pdf_text",
                   _fake_read_text(_SAMPLE_TEXT)):
            result = parse_global_invoice_pdf(Path("/fake/invoice.pdf"))
        assert result["currency"] == "USD"
        assert result["lines"][0]["currency"] == "USD"


class TestSupplierDetection:
    def test_detect_global_from_text(self):
        from app.services.supplier_detect import detect_supplier
        assert detect_supplier("Global Jewellery Pvt. Ltd.") == "global_jewellery"

    def test_detect_global_with_no_dot(self):
        from app.services.supplier_detect import detect_supplier
        assert detect_supplier("Global Jewellery Pvt Ltd Mumbai") == "global_jewellery"

    def test_detect_global_case_insensitive(self):
        from app.services.supplier_detect import detect_supplier
        assert detect_supplier("GLOBAL JEWELLERY PVT. LTD.") == "global_jewellery"
