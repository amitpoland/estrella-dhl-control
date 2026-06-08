"""Tests for sales_packing_parser.py"""
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from decimal import Decimal
import pytest
from app.api.sales_packing_parser import (
    parse_ejl_sales_packing,
    validate_grand_total,
    build_patch_lookup,
    generate_description,
    SalesPackingRow,
)

_HEADER = "Sr\tCtg\tDesign\tDesign Description\tKt\tCol\tQuality\tQty\tValue (EUR)\tTotal Value (EUR)"

_TWO_ROW_TSV = "\n".join([
    _HEADER,
    "1\tPND\tJP01823-0.20\tTest\t14KT\tW\tGH-SI1\t3\t211\t633",
    "2\tRNG\tJP01824-0.15\tTest\t18KT\tP\tGH-VS1\t5\t316\t1580",
    "Grand Total\t\t\t\t\t\t\t\t\t2213",
])


class TestParseEjlSalesPacking:
    def test_two_rows_parsed(self):
        rows, _ = parse_ejl_sales_packing(_TWO_ROW_TSV)
        assert len(rows) == 2

    def test_row1_qty(self):
        rows, _ = parse_ejl_sales_packing(_TWO_ROW_TSV)
        assert rows[0].qty == 3

    def test_row1_unit_price(self):
        rows, _ = parse_ejl_sales_packing(_TWO_ROW_TSV)
        assert rows[0].unit_price == Decimal("211")

    def test_row1_line_total(self):
        rows, _ = parse_ejl_sales_packing(_TWO_ROW_TSV)
        assert rows[0].line_total == Decimal("633")

    def test_row2_unit_price(self):
        rows, _ = parse_ejl_sales_packing(_TWO_ROW_TSV)
        assert rows[1].unit_price == Decimal("316")

    def test_row2_line_total(self):
        rows, _ = parse_ejl_sales_packing(_TWO_ROW_TSV)
        assert rows[1].line_total == Decimal("1580")

    def test_grand_total_parsed(self):
        _, gt = parse_ejl_sales_packing(_TWO_ROW_TSV)
        assert gt == Decimal("2213")

    def test_product_codes(self):
        rows, _ = parse_ejl_sales_packing(_TWO_ROW_TSV)
        assert rows[0].product_code == "JP01823-0.20"
        assert rows[1].product_code == "JP01824-0.15"

    def test_subtotal_rows_skipped(self):
        tsv = "\n".join([
            _HEADER,
            "1\tPND\tJP01823-0.20\tTest\t14KT\tW\tGH-SI1\t3\t211\t633",
            "Subtotal\t\t\t\t\t\t\t3\t\t633",
            "2\tRNG\tJP01824-0.15\tTest\t18KT\tP\tGH-VS1\t5\t316\t1580",
            "Grand Total\t\t\t\t\t\t\t\t\t2213",
        ])
        rows, _ = parse_ejl_sales_packing(tsv)
        assert len(rows) == 2

    def test_empty_input(self):
        rows, gt = parse_ejl_sales_packing("")
        assert rows == []
        assert gt is None

    def test_no_header_returns_empty(self):
        rows, gt = parse_ejl_sales_packing("1\t2\t3\n4\t5\t6")
        assert rows == []

    def test_no_grand_total_returns_none(self):
        tsv = "\n".join([
            _HEADER,
            "1\tPND\tJP01823-0.20\tTest\t14KT\tW\tGH-SI1\t3\t211\t633",
        ])
        _, gt = parse_ejl_sales_packing(tsv)
        assert gt is None

    def test_fallback_category(self):
        tsv = "\n".join([
            _HEADER,
            "1\tXXX\tJP01823-0.20\tTest\t14KT\tW\tGH-SI1\t1\t100\t100",
        ])
        rows, _ = parse_ejl_sales_packing(tsv)
        assert rows[0].desc_pl != ""


class TestValidateGrandTotal:
    def test_exact_match_passes(self):
        rows = [SalesPackingRow(1, "PND", "X", "14KT", "W", "GH-SI1", 1,
                                Decimal("100"), Decimal("100"), "", "")]
        assert validate_grand_total(rows, Decimal("100")) is None

    def test_mismatch_returns_error(self):
        rows = [SalesPackingRow(1, "PND", "X", "14KT", "W", "GH-SI1", 1,
                                Decimal("100"), Decimal("100"), "", "")]
        err = validate_grand_total(rows, Decimal("200"))
        assert err is not None
        assert "100" in err

    def test_within_tolerance_passes(self):
        rows = [SalesPackingRow(1, "PND", "X", "14KT", "W", "GH-SI1", 1,
                                Decimal("100"), Decimal("100.01"), "", "")]
        assert validate_grand_total(rows, Decimal("100"), Decimal("0.02")) is None

    def test_beyond_tolerance_fails(self):
        rows = [SalesPackingRow(1, "PND", "X", "14KT", "W", "GH-SI1", 1,
                                Decimal("100"), Decimal("100.05"), "", "")]
        err = validate_grand_total(rows, Decimal("100"), Decimal("0.02"))
        assert err is not None


class TestBuildPatchLookup:
    def test_keyed_by_product_code(self):
        rows = [
            SalesPackingRow(1, "PND", "JP123", "14KT", "W", "GH-SI1", 1,
                            Decimal("100"), Decimal("100"), "", ""),
        ]
        lkp = build_patch_lookup(rows)
        assert "JP123" in lkp

    def test_first_occurrence_wins(self):
        rows = [
            SalesPackingRow(1, "PND", "JP123", "14KT", "W", "GH-SI1", 1,
                            Decimal("100"), Decimal("100"), "first", ""),
            SalesPackingRow(2, "PND", "JP123", "18KT", "Y", "GH-SI2", 2,
                            Decimal("200"), Decimal("400"), "second", ""),
        ]
        lkp = build_patch_lookup(rows)
        assert lkp["JP123"].unit_price == Decimal("100")


class TestGenerateDescription:
    def test_pendant_14kt_white_diamonds(self):
        pl, en = generate_description("PND", "14KT", "W", "GH-SI1")
        assert "wisiorek" in pl
        assert "14-karatowego" in pl
        assert "pendant" in en

    def test_ring_18kt_rose(self):
        pl, en = generate_description("RNG", "18KT", "R", "GH-VS1")
        assert "pierścionek" in pl
        assert "różowego" in pl

    def test_earrings_sapphire(self):
        pl, en = generate_description("EAR", "14KT", "W", "SAPPHIRE")
        assert "kolczyki" in pl
        assert "szafirami" in pl

    def test_emerald(self):
        pl, en = generate_description("PND", "18KT", "Y", "EMERALD")
        assert "szmaragdami" in pl
        assert "emeralds" in en

    def test_no_color_fallback(self):
        pl, en = generate_description("PND", "14KT", "", "GH-SI1")
        assert "białego" not in pl
        assert "białego" not in en

    def test_descriptions_populated_from_tsv(self):
        rows, _ = parse_ejl_sales_packing(_TWO_ROW_TSV)
        assert rows[0].desc_pl != ""
        assert rows[0].desc_en != ""
        assert rows[1].desc_pl != ""
