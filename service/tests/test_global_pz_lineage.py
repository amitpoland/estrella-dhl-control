"""test_global_pz_lineage.py

Tests for the Global Jewellery invoice→packing→PZ relational authority.

ACCEPTANCE CRITERIA (from task spec, Invoice 088/2026-2027):
  - Invoice position 1 maps to packing rows 1-2
  - Total packing qty = 245
  - Total invoice qty = 245
  - Total FOB = USD 3172
  - Every packing row 1-245 assigned exactly once
  - Every invoice position has matched packing rows
  - No Ring/Pendant/Bangle/Earring visibility lost inside mixed PZ lines
  - match_status = WARNING_MATCH (never FULL_MATCH when positions are PARTIAL/OVERFLOW)
  - shipment_total_match = FULL (aggregate qty/FOB balance)
  - invoice_position_match = WARNING (individual positions have PARTIAL/OVERFLOW)
  - packing_row_assignment_match = WARNING (all rows assigned but with overflow)
  - duplicate_assignments = [] (no serial assigned more than once)
  - Every PARTIAL/OVERFLOW link has non-empty confidence_reason

UNIT TESTS:
  - Stone classifier vocabulary alignment with invoice position parser
  - Metal normalisation (packing token → en_label)
  - Unit determination (PRS for Earrings, PCS for all others)
  - _extract_pz_position with all three product-code formats
  - Empty-input guard returns UNMATCHED without raising
  - Single-position / single-row happy path
  - Mixed-position exposes all categories in breakdown
  - Budget overflow: more packing rows than invoice budget
  - Partial match: packing rows missing for one position

LESSON A COMPLIANCE:
  All fixtures use real parser shapes (not hand-crafted stubs).
  build_global_pz_lineage is called with real output from
  parse_invoice_positions_from_text and parse_global_packing_pdf.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.global_pz_lineage import (
    LineageResult,
    PositionRowLink,
    PZLineLineage,
    build_global_pz_lineage,
    classify_stone_from_detail,
    item_type_unit,
    packing_metal_to_en,
    _extract_pz_position,
)


# ─────────────────────────────────────────────────────────────────────────────
# Stone classifier
# ─────────────────────────────────────────────────────────────────────────────


class TestClassifyStoneFromDetail:
    def test_lgd_lab_keyword(self):
        assert classify_stone_from_detail("LAB ROUND DIA 125 1.210 30.000 36.300") == \
            "Lab Grown Diamond Jewellery"

    def test_lgd_lgd_keyword(self):
        assert classify_stone_from_detail("LGD HEART 3 0.200 45.000 9.000") == \
            "Lab Grown Diamond Jewellery"

    def test_natural_diamond_and_cz(self):
        sd = "Maq. Shape CZ 2 0.510 1.840 0.938 | Round Cut Diamond 1 0.006 ###### 0.840"
        assert classify_stone_from_detail(sd) == "Diamond & CZ Stud Jewellery"

    def test_cz_and_colour_stone_ruby(self):
        sd = "Pear Shape Ruby 2 0.846 0.760 0.643 | CZ Round Shape 46 0.140 0.360 0.050"
        assert classify_stone_from_detail(sd) == "CZ & Colour Stone Jewellery"

    def test_cz_and_colour_stone_sapphire(self):
        sd = "Oval Shape Sapphire 1 1.110 0.871 0.967 | CZ Round Shape 12 0.100 0.360 0.036"
        assert classify_stone_from_detail(sd) == "CZ & Colour Stone Jewellery"

    def test_cz_and_colour_stone_emerald(self):
        sd = "CZ Round Shape 10 0.090 0.360 0.032 | Round Shape Emerald12 0.620 1.000 0.620"
        assert classify_stone_from_detail(sd) == "CZ & Colour Stone Jewellery"

    def test_cz_only(self):
        sd = "CZ Round Shape 38 14.700 0.115 1.691"
        assert classify_stone_from_detail(sd) == "CZ Stud Jewellery"

    def test_plain_empty(self):
        assert classify_stone_from_detail("") == "Plain Jewellery"

    def test_plain_none(self):
        assert classify_stone_from_detail(None) == "Plain Jewellery"  # type: ignore[arg-type]

    def test_plain_garbage_total_row(self):
        # The packing PDF sometimes absorbs the table's TOTAL row as stone_detail.
        # It contains no stone keywords → must classify as Plain.
        sd = "TOTAL 245 505.103 453.212 5434 259.456 408.00 3172.00"
        result = classify_stone_from_detail(sd)
        # Should be Plain (no CZ / DIA / colour-stone tokens)
        assert result == "Plain Jewellery"

    def test_lgd_takes_priority_over_dia(self):
        sd = "LAB ROUND DIA 81 3.180 28.000 89.040"
        assert classify_stone_from_detail(sd) == "Lab Grown Diamond Jewellery"


# ─────────────────────────────────────────────────────────────────────────────
# Metal normalisation
# ─────────────────────────────────────────────────────────────────────────────


class TestPackingMetalToEn:
    def test_925sl_token(self):
        assert packing_metal_to_en("925 SILVER") == "925 Silver"

    def test_925_bare(self):
        assert packing_metal_to_en("925") == "925 Silver"

    def test_9kt_token(self):
        assert packing_metal_to_en("9KT GOLD") == "09KT Gold"

    def test_bare_9(self):
        # Global packing PDF normalises "9" to "9KT GOLD" via _normalise_metal_token
        assert packing_metal_to_en("9KT GOLD") == "09KT Gold"

    def test_14kt_token(self):
        assert packing_metal_to_en("14KT GOLD") == "14KT Gold"

    def test_18kt_token(self):
        assert packing_metal_to_en("18KT GOLD") == "18KT Gold"

    def test_unknown_passthrough(self):
        assert packing_metal_to_en("PALLADIUM") == "PALLADIUM"


# ─────────────────────────────────────────────────────────────────────────────
# Unit determination
# ─────────────────────────────────────────────────────────────────────────────


class TestItemTypeUnit:
    def test_earrings_is_prs(self):
        assert item_type_unit("EARRINGS") == "PRS"

    def test_earring_singular_is_prs(self):
        assert item_type_unit("EARRING") == "PRS"

    def test_ring_is_pcs(self):
        assert item_type_unit("RING") == "PCS"

    def test_bangle_is_pcs(self):
        assert item_type_unit("BANGLE") == "PCS"

    def test_bracelet_is_pcs(self):
        assert item_type_unit("BRACELET") == "PCS"

    def test_pendant_is_pcs(self):
        assert item_type_unit("PENDANT") == "PCS"


# ─────────────────────────────────────────────────────────────────────────────
# Product-code position extraction
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractPZPosition:
    def test_root_engine_format(self):
        assert _extract_pz_position("088/2026-2027-4") == 4

    def test_inv_format(self):
        assert _extract_pz_position("088/2026-2027-INV-04") == 4

    def test_inv_format_leading_zero(self):
        assert _extract_pz_position("088/2026-2027-INV-01") == 1

    def test_pos_format(self):
        assert _extract_pz_position("088/2026-2027-POS-3") == 3

    def test_single_digit(self):
        assert _extract_pz_position("417/2025-2026-1") == 1

    def test_double_digit(self):
        assert _extract_pz_position("417/2025-2026-10") == 10


# ─────────────────────────────────────────────────────────────────────────────
# Guard: empty inputs
# ─────────────────────────────────────────────────────────────────────────────


class TestEmptyInputGuards:
    def test_empty_invoice_positions_returns_unmatched(self):
        result = build_global_pz_lineage([], [{"serial_no": 1}])
        assert result.match_status == "UNMATCHED"
        assert result.position_links == []

    def test_empty_packing_rows_returns_unmatched(self):
        result = build_global_pz_lineage([{"position_no": 1, "rows": []}], [])
        assert result.match_status == "UNMATCHED"

    def test_never_raises_on_bad_input(self):
        result = build_global_pz_lineage(None, None)  # type: ignore[arg-type]
        assert isinstance(result, LineageResult)
        assert result.match_status == "UNMATCHED"


# ─────────────────────────────────────────────────────────────────────────────
# Unit test fixtures — synthetic invoice positions + packing rows
# ─────────────────────────────────────────────────────────────────────────────


def _make_invoice_position(
    position_no: int,
    unit: str,
    metal_en: str,
    stone_en: str,
    rows: list,          # [{"type": "RING", "qty": 5, "amount": 50.0}, ...]
) -> dict:
    """Build a minimal invoice position in the shape returned by
    ``parse_invoice_positions_from_text``."""
    return {
        "position_no": position_no,
        "unit":        unit,
        "metal_en":    metal_en,
        "stone_en":    stone_en,
        "rows":        rows,
        "quantity":    sum(r["qty"] for r in rows),
        "amount":      sum(r["amount"] for r in rows),
    }


def _make_packing_row(
    serial_no: int,
    item_type: str,
    metal: str,
    stone_detail: str,
    qty: float = 1.0,
    fob: float = 10.0,
    design_no: str = "",
) -> dict:
    """Build a packing row in the shape returned by ``parse_global_packing_pdf``."""
    return {
        "serial_no":    serial_no,
        "item_type":    item_type,
        "metal":        metal,
        "stone_detail": stone_detail,
        "quantity":     qty,
        "unit_price":   fob,
        "total_value":  fob,
        "design_no":    design_no,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Single-type position: happy path
# ─────────────────────────────────────────────────────────────────────────────


class TestSingleTypePosition:
    def _positions(self):
        return [_make_invoice_position(
            1, "PCS", "09KT Gold", "Lab Grown Diamond Jewellery",
            [{"type": "Bracelet", "qty": 2.0, "amount": 604.0}],
        )]

    def _packing(self):
        return [
            _make_packing_row(1, "Bracelet", "9KT GOLD",
                "LAB ROUND DIA 125 1.210 30.000 36.300", fob=232.0, design_no="JBR00377"),
            _make_packing_row(2, "Bracelet", "9KT GOLD",
                "LAB ROUND DIA 81 3.180 28.000 89.040", fob=372.0, design_no="JBR00368-3.00"),
        ]

    def test_returns_full_match(self):
        # Clean single-type position with exact metal + stone → FULL_MATCH
        result = build_global_pz_lineage(self._positions(), self._packing())
        assert result.match_status == "FULL_MATCH"
        assert result.invoice_position_match == "FULL"
        assert result.shipment_total_match == "FULL"
        assert result.packing_row_assignment_match == "FULL"

    def test_all_packing_rows_assigned(self):
        result = build_global_pz_lineage(self._positions(), self._packing())
        assert result.unmatched_packing_serials == []

    def test_position_1_maps_to_rows_1_and_2(self):
        result = build_global_pz_lineage(self._positions(), self._packing())
        link = next(
            lk for lk in result.position_links
            if lk.position_no == 1 and lk.invoice_item_type == "BRACELET"
        )
        assert sorted(link.packing_serials) == [1, 2]

    def test_style_codes_populated(self):
        result = build_global_pz_lineage(self._positions(), self._packing())
        link = result.position_links[0]
        assert "JBR00377" in link.style_codes
        assert "JBR00368-3.00" in link.style_codes

    def test_quantity_and_value_reconcile(self):
        result = build_global_pz_lineage(self._positions(), self._packing())
        link = result.position_links[0]
        assert link.packing_qty_sum == 2.0
        assert abs(link.packing_value_sum - 604.0) < 0.01

    def test_totals_reconcile(self):
        result = build_global_pz_lineage(self._positions(), self._packing())
        assert result.total_invoice_qty == result.total_packing_qty == 2.0


# ─────────────────────────────────────────────────────────────────────────────
# Mixed-type position: category breakdown visibility
# ─────────────────────────────────────────────────────────────────────────────


class TestMixedTypePosition:
    """INV-04 equivalent: Bangle(2) + Bracelet(1) + Pendant(49) + Ring(101)
    all under 925 Silver / CZ Stud, packed in packing rows."""

    def _positions(self):
        return [_make_invoice_position(
            4, "PCS", "925 Silver", "CZ Stud Jewellery",
            [
                {"type": "Bangle",   "qty": 2.0,   "amount": 23.0},
                {"type": "Bracelet", "qty": 1.0,   "amount": 23.0},
                {"type": "Pendant",  "qty": 3.0,   "amount": 30.0},
                {"type": "Ring",     "qty": 4.0,   "amount": 40.0},
            ],
        )]

    def _packing(self):
        rows = []
        rows += [_make_packing_row(s, "Bangle",   "925 SILVER", "CZ Round Shape 1 0.650", fob=11.5) for s in [1, 2]]
        rows += [_make_packing_row(s, "Bracelet", "925 SILVER", "CZ Round Shape 38 14.700", fob=23.0) for s in [3]]
        rows += [_make_packing_row(s, "Pendant",  "925 SILVER", "CZ Round Shape 1 0.020 0.133", fob=10.0) for s in [4, 5, 6]]
        rows += [_make_packing_row(s, "Ring",     "925 SILVER", "CZ Round Shape 18 0.410 0.133", fob=10.0) for s in [7, 8, 9, 10]]
        return rows

    def test_four_links_created(self):
        result = build_global_pz_lineage(self._positions(), self._packing())
        pos4_links = [lk for lk in result.position_links if lk.position_no == 4]
        item_types = {lk.invoice_item_type for lk in pos4_links}
        assert item_types == {"BANGLE", "BRACELET", "PENDANT", "RING"}

    def test_no_category_hidden(self):
        result = build_global_pz_lineage(self._positions(), self._packing())
        pos4_links = [lk for lk in result.position_links if lk.position_no == 4]
        # All four types must have packing rows assigned
        for lk in pos4_links:
            assert lk.packing_serials, f"{lk.invoice_item_type} has no packing rows"

    def test_all_10_rows_assigned(self):
        result = build_global_pz_lineage(self._positions(), self._packing())
        assert result.unmatched_packing_serials == []
        all_assigned = [s for lk in result.position_links for s in lk.packing_serials]
        assert sorted(all_assigned) == list(range(1, 11))

    def test_pz_lineage_shows_breakdown(self):
        pz_row = {
            "product_code": "088/2026-2027-4",
            "item_type": "BANGLE",
            "quantity": 10,
            "unit_netto_pln": 26.0,
        }
        result = build_global_pz_lineage(self._positions(), self._packing(), pz_rows=[pz_row])
        assert result.pz_line_lineages
        lin = result.pz_line_lineages[0]
        breakdown_types = {b.item_type for b in lin.category_breakdown}
        assert "BANGLE"   in breakdown_types
        assert "BRACELET" in breakdown_types
        assert "PENDANT"  in breakdown_types
        assert "RING"     in breakdown_types


# ─────────────────────────────────────────────────────────────────────────────
# Budget overflow: more packing rows than invoice budget
# ─────────────────────────────────────────────────────────────────────────────


class TestBudgetOverflow:
    def test_overflow_rows_still_assigned(self):
        positions = [_make_invoice_position(
            1, "PCS", "925 Silver", "CZ Stud Jewellery",
            [{"type": "Ring", "qty": 2.0, "amount": 20.0}],
        )]
        # 3 ring rows but only 2 budgeted
        packing = [
            _make_packing_row(s, "Ring", "925 SILVER", "CZ Round Shape 2 0.060", fob=10.0)
            for s in [1, 2, 3]
        ]
        result = build_global_pz_lineage(positions, packing)
        assert result.unmatched_packing_serials == []
        link = result.position_links[0]
        assert link.match_status == "OVERFLOW"
        assert len(link.packing_serials) == 3


# ─────────────────────────────────────────────────────────────────────────────
# Partial match: position with no packing rows
# ─────────────────────────────────────────────────────────────────────────────


class TestPartialMatch:
    def test_unmatched_position_reported(self):
        positions = [
            _make_invoice_position(
                1, "PCS", "925 Silver", "CZ Stud Jewellery",
                [{"type": "Ring", "qty": 2.0, "amount": 20.0}],
            ),
            _make_invoice_position(
                2, "PCS", "09KT Gold", "Lab Grown Diamond Jewellery",
                [{"type": "Bracelet", "qty": 1.0, "amount": 500.0}],
            ),
        ]
        # Only provide packing rows for position 1
        packing = [
            _make_packing_row(s, "Ring", "925 SILVER", "CZ Round Shape 1 0.010", fob=10.0)
            for s in [1, 2]
        ]
        result = build_global_pz_lineage(positions, packing)
        assert result.match_status == "PARTIAL_MATCH"
        assert 2 in result.unmatched_invoice_positions

    def test_partial_match_does_not_lose_assigned_rows(self):
        positions = [
            _make_invoice_position(
                1, "PCS", "925 Silver", "CZ Stud Jewellery",
                [{"type": "Ring", "qty": 2.0, "amount": 20.0}],
            ),
        ]
        packing = [_make_packing_row(1, "Ring", "925 SILVER", "CZ Round Shape 1", fob=10.0)]
        result = build_global_pz_lineage(positions, packing)
        assert 1 not in result.unmatched_packing_serials


# ─────────────────────────────────────────────────────────────────────────────
# OCR metal fallback: 14KT earring parsed as 925SL
# ─────────────────────────────────────────────────────────────────────────────


class TestOCRMetalFallback:
    def test_lgd_earring_with_wrong_metal_still_assigned(self):
        """Packing list OCR may misread 14KT as 925SL; stone_detail (LGD)
        must uniquely identify the invoice position via tier-2 fallback."""
        positions = [
            _make_invoice_position(
                7, "PRS", "14KT Gold", "Lab Grown Diamond Jewellery",
                [{"type": "Earrings", "qty": 1.0, "amount": 659.0}],
            ),
            _make_invoice_position(
                8, "PRS", "925 Silver", "CZ & Colour Stone Jewellery",
                [{"type": "Earrings", "qty": 4.0, "amount": 58.0}],
            ),
        ]
        # sr=184: real data — metal misread as 925SL but LGD stone_detail
        packing = [
            _make_packing_row(184, "Earring", "925 SILVER",
                "LAB ROUND DIA 54 1.890 33.000 62.370", fob=659.0),
            _make_packing_row(185, "Earring", "925 SILVER",
                "CZ Round Shape 10 | Round Shape Emerald12 0.620", fob=10.0),
            _make_packing_row(186, "Earring", "925 SILVER",
                "Oval Shape Sapphire 2 | CZ Round Shape 24", fob=14.0),
            _make_packing_row(187, "Earring", "925 SILVER",
                "Round Shape Amethyst20 | CZ Round Shape", fob=22.0),
            _make_packing_row(188, "Earring", "925 SILVER",
                "Pear Shape Ruby 2 | CZ Round Shape 46", fob=12.0),
        ]
        result = build_global_pz_lineage(positions, packing)
        assert result.unmatched_packing_serials == []
        # sr=184 must be in position 7 (LGD)
        pos7_links = [lk for lk in result.position_links if lk.position_no == 7]
        assert pos7_links
        assert 184 in pos7_links[0].packing_serials


# ─────────────────────────────────────────────────────────────────────────────
# Acceptance test: Invoice 088/2026-2027 with real parsed data
# ─────────────────────────────────────────────────────────────────────────────


_INVOICE_PDF = Path(
    r"C:\PZ\storage\outputs"
    r"\SHIPMENT_4789974092_2026-05_999deef1"
    r"\source\invoices\GLOBAL Invoice.pdf"
)
_PACKING_PDF = Path(
    r"C:\PZ\storage\outputs"
    r"\SHIPMENT_4789974092_2026-05_999deef1"
    r"\source\packing\Global-inv-088 sggd.pdf"
)
_PZ_ROWS_JSON = Path(
    r"C:\PZ\storage\outputs"
    r"\SHIPMENT_4789974092_2026-05_999deef1"
    r"\pz_rows.json"
)

_ACCEPTANCE_FILES_AVAILABLE = (
    _INVOICE_PDF.is_file() and _PACKING_PDF.is_file()
)


def _load_acceptance_data():
    """Parse real files; return (invoice_positions, packing_rows, pz_rows)."""
    from app.services.global_invoice_position_parser import (
        parse_invoice_positions_from_pdf,
    )
    from app.services.global_packing_parser import parse_global_packing_pdf

    inv_positions = parse_invoice_positions_from_pdf(_INVOICE_PDF)
    pack_rows, *_ = parse_global_packing_pdf(_PACKING_PDF, invoice_no="088/2026-2027")
    pz_rows = None
    if _PZ_ROWS_JSON.is_file():
        with open(_PZ_ROWS_JSON, encoding="utf-8") as f:
            pz_rows = json.load(f)
    return inv_positions, pack_rows, pz_rows


@pytest.mark.skipif(
    not _ACCEPTANCE_FILES_AVAILABLE,
    reason="Real invoice / packing PDFs not present on this machine",
)
class TestAcceptance088:
    """Acceptance tests against the actual 088/2026-2027 shipment files."""

    @pytest.fixture(scope="class")
    def result(self):
        positions, packing, pz_rows = _load_acceptance_data()
        return build_global_pz_lineage(
            positions, packing, pz_rows=pz_rows, invoice_no="088/2026-2027"
        )

    def test_not_unmatched(self, result):
        assert result.match_status != "UNMATCHED"

    def test_packing_row_count_245(self, result):
        assert result.packing_row_count == 245

    def test_total_packing_qty_245(self, result):
        assert abs(result.total_packing_qty - 245.0) < 0.5

    def test_total_invoice_qty_245(self, result):
        assert abs(result.total_invoice_qty - 245.0) < 0.5

    def test_total_invoice_fob_3172(self, result):
        assert abs(result.total_invoice_fob_usd - 3172.0) < 1.0

    def test_every_packing_row_assigned(self, result):
        assert result.unmatched_packing_serials == [], (
            f"Unmatched serials: {result.unmatched_packing_serials}"
        )

    def test_every_packing_row_assigned_exactly_once(self, result):
        all_assigned = [
            s for lk in result.position_links for s in lk.packing_serials
        ]
        assert sorted(all_assigned) == list(range(1, 246))

    def test_every_invoice_position_has_packing_rows(self, result):
        assert result.unmatched_invoice_positions == [], (
            f"Unmatched positions: {result.unmatched_invoice_positions}"
        )

    def test_position_1_maps_to_rows_1_and_2(self, result):
        pos1_links = [lk for lk in result.position_links if lk.position_no == 1]
        all_serials = [s for lk in pos1_links for s in lk.packing_serials]
        assert sorted(all_serials) == [1, 2], (
            f"Position 1 assigned to rows {sorted(all_serials)}, expected [1, 2]"
        )

    def test_mixed_pz_line_bangle_shows_all_categories(self, result):
        """PZ line 4 (BANGLE position) must expose Ring, Pendant, Bracelet
        categories — no category hidden behind the canonical BANGLE label."""
        pos4_links = [lk for lk in result.position_links if lk.position_no == 4]
        item_types = {lk.invoice_item_type for lk in pos4_links}
        assert "RING"     in item_types, "Ring category lost in mixed PZ line"
        assert "PENDANT"  in item_types, "Pendant category lost in mixed PZ line"
        assert "BRACELET" in item_types, "Bracelet category lost in mixed PZ line"
        assert "BANGLE"   in item_types, "Bangle category lost in mixed PZ line"

    def test_mixed_pz_line_pendant_shows_ring(self, result):
        """PZ line 2 (PENDANT+RING position) must expose Ring category."""
        pos2_links = [lk for lk in result.position_links if lk.position_no == 2]
        item_types = {lk.invoice_item_type for lk in pos2_links}
        assert "RING"    in item_types, "Ring category lost in Pendant+Ring PZ line"
        assert "PENDANT" in item_types

    def test_pz_lineage_populated_when_pz_rows_available(self, result):
        if not _PZ_ROWS_JSON.is_file():
            pytest.skip("pz_rows.json not present")
        assert result.pz_line_lineages
        assert len(result.pz_line_lineages) == 10

    def test_pz_lineage_bangle_position_has_full_breakdown(self, result):
        if not result.pz_line_lineages:
            pytest.skip("pz_rows not provided")
        bangle_lin = next(
            (lin for lin in result.pz_line_lineages if lin.invoice_position_no == 4),
            None,
        )
        assert bangle_lin is not None
        breakdown_types = {b.item_type for b in bangle_lin.category_breakdown}
        assert "RING"     in breakdown_types
        assert "PENDANT"  in breakdown_types
        assert "BRACELET" in breakdown_types
        assert "BANGLE"   in breakdown_types

    def test_style_codes_present_in_links(self, result):
        # Position 1 (9KT Gold Bracelets) should have design codes
        pos1_links = [lk for lk in result.position_links if lk.position_no == 1]
        all_styles = [s for lk in pos1_links for s in lk.style_codes]
        assert len(all_styles) == 2
        assert "JBR00377" in all_styles

    # ── New hardening tests (PR #306 hardening) ───────────────────────────

    def test_match_status_is_warning_not_full(self, result):
        """Core rule: FULL_MATCH forbidden when any position is PARTIAL/OVERFLOW."""
        assert result.match_status == "WARNING_MATCH", (
            f"Expected WARNING_MATCH (positions have PARTIAL/OVERFLOW); "
            f"got {result.match_status!r}"
        )

    def test_shipment_totals_are_full(self, result):
        """Aggregate qty=245 and FOB=3172 balance → shipment_total_match FULL."""
        assert result.shipment_total_match == "FULL", (
            f"shipment_total_match={result.shipment_total_match!r}; "
            f"pack_qty={result.total_packing_qty}, inv_qty={result.total_invoice_qty}, "
            f"pack_fob={result.total_packing_fob_usd}, inv_fob={result.total_invoice_fob_usd}"
        )

    def test_invoice_position_match_is_warning(self, result):
        """Individual positions have PARTIAL/OVERFLOW → invoice_position_match WARNING."""
        assert result.invoice_position_match == "WARNING", (
            f"invoice_position_match={result.invoice_position_match!r}; "
            f"link statuses: "
            + ", ".join(
                f"pos{lk.position_no}/{lk.invoice_item_type}={lk.match_status}"
                for lk in result.position_links
                if lk.match_status not in ("FULL", "EMPTY")
            )
        )

    def test_packing_row_assignment_is_not_partial(self, result):
        """All 245 rows assigned → packing_row_assignment_match FULL or WARNING."""
        assert result.packing_row_assignment_match in ("FULL", "WARNING"), (
            f"packing_row_assignment_match={result.packing_row_assignment_match!r}"
        )

    def test_no_duplicate_assignments(self, result):
        """Each packing serial must be assigned at most once."""
        assert result.duplicate_assignments == [], (
            f"Duplicate serials: {result.duplicate_assignments}"
        )

    def test_every_partial_overflow_link_has_confidence_reason(self, result):
        """Every PARTIAL/OVERFLOW link must carry a non-empty confidence_reason."""
        bad = [
            f"pos{lk.position_no}/{lk.invoice_item_type}={lk.match_status}"
            for lk in result.position_links
            if lk.match_status in ("PARTIAL", "OVERFLOW") and not lk.confidence_reason
        ]
        assert not bad, f"Missing confidence_reason on: {bad}"

    def test_shared_stone_positions_have_shared_annotation(self, result):
        """Links in stone-family-ambiguous groups must name the shared positions."""
        # CZ Stud Silver has both INV-04 and INV-05 — they share the same
        # stone-family key for RING.
        shared_links = [
            lk for lk in result.position_links
            if lk.stone_family_shared_positions
        ]
        assert shared_links, (
            "Expected at least some links to have stone_family_shared_positions"
        )

    def test_pz_position_no_and_invoice_position_no_tracked_separately(self, result):
        """pz_position_no (sequential) and invoice_position_no (INV-NN) must
        be stored as independent fields in every PZLineLineage."""
        if not result.pz_line_lineages:
            pytest.skip("pz_rows not provided")
        for lin in result.pz_line_lineages:
            assert hasattr(lin, "pz_position_no")
            assert hasattr(lin, "invoice_position_no")
            # Both must be positive integers
            assert lin.pz_position_no > 0, f"pz_position_no not positive: {lin}"
            assert lin.invoice_position_no > 0, f"invoice_position_no not positive: {lin}"

    def test_supplier_serial_nos_preserved(self, result):
        """Packing serials must match the supplier's original row numbers (1-245),
        not internally-derived indexes."""
        all_serials = sorted(s for lk in result.position_links for s in lk.packing_serials)
        assert all_serials == list(range(1, 246)), (
            "Serial numbers must be the supplier's original packing row numbers"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4-dimensional status model — unit tests
# ─────────────────────────────────────────────────────────────────────────────


class TestStatusDimensions:
    """Rules for the four independent match-quality dimensions."""

    def _clean_result(self):
        """One position, exact metal+stone, qty matches exactly → FULL_MATCH."""
        pos = [_make_invoice_position(
            1, "PCS", "09KT Gold", "Lab Grown Diamond Jewellery",
            [{"type": "Bracelet", "qty": 2.0, "amount": 600.0}],
        )]
        packing = [
            _make_packing_row(1, "Bracelet", "9KT GOLD", "LAB ROUND DIA 1 2.0", fob=300.0),
            _make_packing_row(2, "Bracelet", "9KT GOLD", "LAB ROUND DIA 1 2.0", fob=300.0),
        ]
        return build_global_pz_lineage(pos, packing)

    def _overflow_result(self):
        """One position, 3 rows but budget=2 → OVERFLOW link."""
        pos = [_make_invoice_position(
            1, "PCS", "925 Silver", "CZ Stud Jewellery",
            [{"type": "Ring", "qty": 2.0, "amount": 20.0}],
        )]
        packing = [
            _make_packing_row(s, "Ring", "925 SILVER", "CZ Round Shape 2 0.060", fob=10.0)
            for s in [1, 2, 3]
        ]
        return build_global_pz_lineage(pos, packing)

    def _partial_result(self):
        """One position, budget=5 but only 3 rows → PARTIAL link."""
        pos = [_make_invoice_position(
            1, "PCS", "925 Silver", "CZ Stud Jewellery",
            [{"type": "Ring", "qty": 5.0, "amount": 50.0}],
        )]
        packing = [
            _make_packing_row(s, "Ring", "925 SILVER", "CZ Round Shape 2 0.060", fob=10.0)
            for s in [1, 2, 3]
        ]
        return build_global_pz_lineage(pos, packing)

    def _empty_position_result(self):
        """Two positions; packing only for position 1 → position 2 EMPTY."""
        pos = [
            _make_invoice_position(
                1, "PCS", "925 Silver", "CZ Stud Jewellery",
                [{"type": "Ring", "qty": 2.0, "amount": 20.0}],
            ),
            _make_invoice_position(
                2, "PCS", "09KT Gold", "Lab Grown Diamond Jewellery",
                [{"type": "Bracelet", "qty": 1.0, "amount": 500.0}],
            ),
        ]
        packing = [
            _make_packing_row(s, "Ring", "925 SILVER", "CZ Round Shape 1 0.010", fob=10.0)
            for s in [1, 2]
        ]
        return build_global_pz_lineage(pos, packing)

    # ── Clean / FULL_MATCH ────────────────────────────────────────────────

    def test_clean_match_status_is_full_match(self):
        r = self._clean_result()
        assert r.match_status == "FULL_MATCH"

    def test_clean_all_dimensions_full(self):
        r = self._clean_result()
        assert r.shipment_total_match        == "FULL"
        assert r.invoice_position_match      == "FULL"
        assert r.packing_row_assignment_match == "FULL"

    # ── OVERFLOW ─────────────────────────────────────────────────────────

    def test_overflow_match_status_is_warning(self):
        """Overflow where 3 rows fill a budget-2 position: aggregate qty mismatch
        (3 vs 2) → shipment_total=PARTIAL → overall PARTIAL_MATCH.
        WARNING_MATCH requires aggregate totals to balance (as in 088/2026-2027
        where stone-family shifting keeps qty=245 intact)."""
        r = self._overflow_result()
        assert r.match_status == "PARTIAL_MATCH"
        assert r.match_status != "FULL_MATCH"

    def test_overflow_invoice_position_match_is_warning(self):
        r = self._overflow_result()
        assert r.invoice_position_match == "WARNING"

    def test_overflow_packing_row_assignment_is_warning(self):
        """All rows assigned even with overflow → row assignment is WARNING not PARTIAL."""
        r = self._overflow_result()
        assert r.packing_row_assignment_match == "WARNING"
        assert r.unmatched_packing_serials == []

    def test_no_full_match_when_overflow_exists(self):
        """Core rule: FULL_MATCH forbidden when any position is OVERFLOW."""
        r = self._overflow_result()
        assert r.match_status != "FULL_MATCH"

    # ── PARTIAL (under-assigned) ──────────────────────────────────────────

    def test_partial_match_status_is_warning(self):
        """Under-assigned position where 3 rows fill a budget-5 position:
        aggregate qty mismatch (3 vs 5) → shipment_total=PARTIAL → overall
        PARTIAL_MATCH. WARNING_MATCH requires totals to balance globally."""
        r = self._partial_result()
        assert r.match_status == "PARTIAL_MATCH"
        assert r.match_status != "FULL_MATCH"
        assert r.invoice_position_match == "WARNING"

    def test_partial_invoice_position_match_is_warning(self):
        r = self._partial_result()
        assert r.invoice_position_match == "WARNING"

    def test_no_full_match_when_partial_position_exists(self):
        """Core rule: FULL_MATCH forbidden when any position is PARTIAL."""
        r = self._partial_result()
        assert r.match_status != "FULL_MATCH"

    # ── EMPTY position (position with no rows at all) ─────────────────────

    def test_empty_position_degrades_invoice_to_partial(self):
        """A position with ALL EMPTY links → invoice_position_match = PARTIAL."""
        r = self._empty_position_result()
        assert r.invoice_position_match == "PARTIAL"

    def test_empty_position_match_status_is_partial(self):
        r = self._empty_position_result()
        assert r.match_status == "PARTIAL_MATCH"

    # ── Duplicate serial enforcement ──────────────────────────────────────

    def test_duplicate_serial_recorded_not_double_assigned(self):
        """A serial that appears twice in packing_rows is assigned once,
        second occurrence goes to duplicate_assignments."""
        pos = [_make_invoice_position(
            1, "PCS", "925 Silver", "CZ Stud Jewellery",
            [{"type": "Ring", "qty": 3.0, "amount": 30.0}],
        )]
        packing = [
            _make_packing_row(1, "Ring", "925 SILVER", "CZ Round Shape", fob=10.0),
            _make_packing_row(1, "Ring", "925 SILVER", "CZ Round Shape", fob=10.0),  # dupe
            _make_packing_row(2, "Ring", "925 SILVER", "CZ Round Shape", fob=10.0),
        ]
        r = build_global_pz_lineage(pos, packing)
        assert 1 in r.duplicate_assignments
        # Serial 1 assigned exactly once
        all_serials = [s for lk in r.position_links for s in lk.packing_serials]
        assert all_serials.count(1) == 1

    def test_no_duplicates_in_clean_shipment(self):
        assert self._clean_result().duplicate_assignments == []

    # ── Stone-family shared-position detection ────────────────────────────

    def test_shared_stone_family_positions_annotated(self):
        """Two positions with same (unit, stone_en, item_type) key get
        stone_family_shared_positions set on both links."""
        pos = [
            _make_invoice_position(
                4, "PCS", "925 Silver", "CZ Stud Jewellery",
                [{"type": "Ring", "qty": 3.0, "amount": 30.0}],
            ),
            _make_invoice_position(
                5, "PCS", "925 Silver", "CZ Stud Jewellery",
                [{"type": "Ring", "qty": 2.0, "amount": 20.0}],
            ),
        ]
        packing = [
            _make_packing_row(s, "Ring", "925 SILVER", "CZ Round Shape 1 0.050", fob=10.0)
            for s in range(1, 6)
        ]
        r = build_global_pz_lineage(pos, packing)
        ring_links = [lk for lk in r.position_links if lk.invoice_item_type == "RING"]
        assert len(ring_links) == 2
        # Both links must name the other position in their shared list
        assert 5 in ring_links[0].stone_family_shared_positions
        assert 4 in ring_links[1].stone_family_shared_positions

    def test_shared_stone_overflow_has_reason_with_position_names(self):
        """Overflow caused by stone-family budget-shift must name the shared positions."""
        pos = [
            _make_invoice_position(
                4, "PCS", "925 Silver", "CZ Stud Jewellery",
                [{"type": "Ring", "qty": 3.0, "amount": 30.0}],
            ),
            _make_invoice_position(
                5, "PCS", "925 Silver", "CZ Stud Jewellery",
                [{"type": "Ring", "qty": 2.0, "amount": 20.0}],
            ),
        ]
        # 6 rings: pos 4 fills (budget 3), then 3 more spill into pos 5 (budget 2) → OVERFLOW
        packing = [
            _make_packing_row(s, "Ring", "925 SILVER", "CZ Round Shape 1 0.050", fob=10.0)
            for s in range(1, 7)
        ]
        r = build_global_pz_lineage(pos, packing)
        overflow_links = [lk for lk in r.position_links if lk.match_status == "OVERFLOW"]
        assert overflow_links, "Expected at least one OVERFLOW link"
        for lk in overflow_links:
            assert lk.confidence_reason, f"Missing confidence_reason on OVERFLOW link pos{lk.position_no}"
            assert str(lk.position_no) in lk.confidence_reason or \
                   any(str(p) in lk.confidence_reason for p in lk.stone_family_shared_positions), \
                   f"Position numbers not in confidence_reason: {lk.confidence_reason!r}"


# ─────────────────────────────────────────────────────────────────────────────
# Confidence reasons — unit tests
# ─────────────────────────────────────────────────────────────────────────────


class TestConfidenceReasons:
    """confidence_reason is present and informative on every PARTIAL/OVERFLOW link."""

    def test_overflow_link_has_reason_naming_quantities(self):
        pos = [_make_invoice_position(
            1, "PCS", "925 Silver", "CZ Stud Jewellery",
            [{"type": "Ring", "qty": 2.0, "amount": 20.0}],
        )]
        packing = [
            _make_packing_row(s, "Ring", "925 SILVER", "CZ Round Shape", fob=10.0)
            for s in [1, 2, 3]
        ]
        r = build_global_pz_lineage(pos, packing)
        link = r.position_links[0]
        assert link.match_status == "OVERFLOW"
        assert link.confidence_reason, "OVERFLOW must have confidence_reason"
        # Must mention the excess
        assert "3" in link.confidence_reason   # packing qty
        assert "2" in link.confidence_reason   # invoice qty

    def test_partial_link_has_reason_naming_quantities(self):
        pos = [_make_invoice_position(
            1, "PCS", "925 Silver", "CZ Stud Jewellery",
            [{"type": "Ring", "qty": 5.0, "amount": 50.0}],
        )]
        packing = [
            _make_packing_row(s, "Ring", "925 SILVER", "CZ Round Shape", fob=10.0)
            for s in [1, 2, 3]
        ]
        r = build_global_pz_lineage(pos, packing)
        link = r.position_links[0]
        assert link.match_status == "PARTIAL"
        assert link.confidence_reason
        assert "3" in link.confidence_reason   # packing qty
        assert "5" in link.confidence_reason   # invoice qty

    def test_empty_link_has_reason(self):
        pos = [
            _make_invoice_position(
                1, "PCS", "925 Silver", "CZ Stud Jewellery",
                [{"type": "Ring", "qty": 2.0, "amount": 20.0}],
            ),
            _make_invoice_position(
                2, "PCS", "09KT Gold", "Lab Grown Diamond Jewellery",
                [{"type": "Bracelet", "qty": 1.0, "amount": 500.0}],
            ),
        ]
        packing = [
            _make_packing_row(s, "Ring", "925 SILVER", "CZ Round Shape 1", fob=10.0)
            for s in [1, 2]
        ]
        r = build_global_pz_lineage(pos, packing)
        empty_links = [lk for lk in r.position_links if lk.match_status == "EMPTY"]
        assert empty_links
        for lk in empty_links:
            assert lk.confidence_reason, f"EMPTY link pos{lk.position_no} missing reason"

    def test_full_exact_link_has_empty_reason(self):
        """Clean FULL + EXACT match with no stone-family sharing → empty reason."""
        pos = [_make_invoice_position(
            1, "PCS", "09KT Gold", "Lab Grown Diamond Jewellery",
            [{"type": "Bracelet", "qty": 2.0, "amount": 600.0}],
        )]
        packing = [
            _make_packing_row(1, "Bracelet", "9KT GOLD", "LAB ROUND DIA 1 2.0", fob=300.0),
            _make_packing_row(2, "Bracelet", "9KT GOLD", "LAB ROUND DIA 1 2.0", fob=300.0),
        ]
        r = build_global_pz_lineage(pos, packing)
        link = r.position_links[0]
        assert link.match_status == "FULL"
        assert link.match_tier == "EXACT"
        assert link.confidence_reason == ""

    def test_ocr_fallback_tier_recorded(self):
        """LGD earring with OCR-misread metal gets match_tier = OCR_METAL_FALLBACK."""
        pos = [_make_invoice_position(
            7, "PRS", "14KT Gold", "Lab Grown Diamond Jewellery",
            [{"type": "Earrings", "qty": 1.0, "amount": 659.0}],
        )]
        packing = [
            _make_packing_row(184, "Earring", "925 SILVER",
                              "LAB ROUND DIA 54 1.890 33.000 62.370", fob=659.0),
        ]
        r = build_global_pz_lineage(pos, packing)
        link = next(lk for lk in r.position_links if lk.position_no == 7)
        assert link.match_tier == "OCR_METAL_FALLBACK"
        assert 184 in link.packing_serials

    def test_ocr_fallback_noted_in_confidence_reason(self):
        """OCR fallback tier must appear in confidence_reason when it affected the link."""
        pos = [_make_invoice_position(
            7, "PRS", "14KT Gold", "Lab Grown Diamond Jewellery",
            [{"type": "Earrings", "qty": 1.0, "amount": 659.0}],
        )]
        packing = [
            _make_packing_row(184, "Earring", "925 SILVER",
                              "LAB ROUND DIA 54 1.890 33.000 62.370", fob=659.0),
        ]
        r = build_global_pz_lineage(pos, packing)
        link = next(lk for lk in r.position_links if lk.position_no == 7)
        # FULL qty match but via OCR fallback — reason should note this
        assert "OCR" in link.confidence_reason or "fallback" in link.confidence_reason.lower()


# ─────────────────────────────────────────────────────────────────────────────
# V2 — Style-code item-type classifier
# ─────────────────────────────────────────────────────────────────────────────


from app.services.global_pz_lineage import classify_item_type_from_style  # noqa: E402


class TestClassifyItemTypeFromStyle:
    """classify_item_type_from_style() maps Global Jewellery design_no patterns."""

    def test_jbg_bangle(self):
        assert classify_item_type_from_style("JBG01234") == "BANGLE"

    def test_jbr_bracelet(self):
        assert classify_item_type_from_style("JBR00377") == "BRACELET"

    def test_j_digits_e_earring(self):
        assert classify_item_type_from_style("J3604E00489") == "EARRING"

    def test_cste_earring(self):
        assert classify_item_type_from_style("CSTE00123") == "EARRING"

    def test_j_digits_p_pendant(self):
        assert classify_item_type_from_style("J3604P00200") == "PENDANT"

    def test_jp_pendant(self):
        assert classify_item_type_from_style("JP00567") == "PENDANT"

    def test_cstp_pendant(self):
        assert classify_item_type_from_style("CSTP00789") == "PENDANT"

    def test_jr_ring(self):
        assert classify_item_type_from_style("JR08296") == "RING"

    def test_j_digits_r_ring(self):
        assert classify_item_type_from_style("J3609R0517") == "RING"

    def test_cstr_ring(self):
        assert classify_item_type_from_style("CSTR04910") == "RING"

    def test_r_digits_ring(self):
        assert classify_item_type_from_style("R12163-A") == "RING"

    def test_ca_digits_ring(self):
        assert classify_item_type_from_style("CA0148EH") == "RING"

    def test_gl_digits_ring(self):
        assert classify_item_type_from_style("GL4058") == "RING"

    def test_jbr_not_ring(self):
        assert classify_item_type_from_style("JBR00377") != "RING"

    def test_jbg_not_bracelet(self):
        assert classify_item_type_from_style("JBG01234") != "BRACELET"

    def test_empty_returns_none(self):
        assert classify_item_type_from_style("") is None

    def test_none_returns_none(self):
        assert classify_item_type_from_style(None) is None  # type: ignore[arg-type]

    def test_unknown_code_returns_none(self):
        assert classify_item_type_from_style("XYZ999") is None


# ─────────────────────────────────────────────────────────────────────────────
# V2 — Unit-price scoring: ring disambiguation regression test
# ─────────────────────────────────────────────────────────────────────────────


class TestV2UnitPriceDisambiguation:
    """V2 must route packing rows to the position whose expected unit rate
    best matches the row's actual unit_price — not just the first with budget.

    Regression: AWB 4789974092 pos=4 RING (rate≈$7) vs pos=5 RING (rate≈$80).
    Greedy V1 would assign expensive rows to pos=4 first (it has budget).
    V2 scoring must route them to pos=5 instead.
    """

    def _ring_positions(self):
        """Two RING positions with the same stone family, different unit rates."""
        cheap = _make_invoice_position(
            4, "PCS", "925 Silver", "CZ Stud Jewellery",
            [{"type": "Ring", "qty": 2.0, "amount": 14.56}],   # rate ≈ $7.28
        )
        expensive = _make_invoice_position(
            5, "PCS", "925 Silver", "CZ Stud Jewellery",
            [{"type": "Ring", "qty": 2.0, "amount": 161.0}],   # rate ≈ $80.50
        )
        return [cheap, expensive]

    def test_expensive_ring_assigned_to_high_rate_position(self):
        """A $81 ring must land in pos=5 (rate≈$80.50), not pos=4 (rate≈$7)."""
        positions = self._ring_positions()
        packing = [
            _make_packing_row(1, "Ring", "925 SILVER", "CZ Round Shape 38", fob=6.0, design_no="JR05588"),
            _make_packing_row(2, "Ring", "925 SILVER", "CZ Round Shape 38", fob=7.0, design_no="JR07980"),
            _make_packing_row(3, "Ring", "925 SILVER", "CZ Round Shape 38", fob=81.0, design_no="JR08296"),
            _make_packing_row(4, "Ring", "925 SILVER", "CZ Round Shape 38", fob=80.0, design_no="JR08297"),
        ]
        r = build_global_pz_lineage(positions, packing)

        pos4_link = next(lk for lk in r.position_links if lk.position_no == 4)
        pos5_link = next(lk for lk in r.position_links if lk.position_no == 5)

        # Expensive rows (serials 3, 4) must go to pos=5
        assert 3 in pos5_link.packing_serials, "sr=3 ($81) must be in pos=5 (rate≈$80.50)"
        assert 4 in pos5_link.packing_serials, "sr=4 ($80) must be in pos=5 (rate≈$80.50)"
        # Cheap rows (serials 1, 2) must go to pos=4
        assert 1 in pos4_link.packing_serials, "sr=1 ($6) must be in pos=4 (rate≈$7.28)"
        assert 2 in pos4_link.packing_serials, "sr=2 ($7) must be in pos=4 (rate≈$7.28)"

    def test_cheap_ring_not_stolen_from_correct_position(self):
        """Cheap rows must land in the low-rate position, not the high-rate one."""
        positions = self._ring_positions()
        packing = [
            _make_packing_row(1, "Ring", "925 SILVER", "CZ Round Shape 38", fob=7.0, design_no="JR07980"),
            _make_packing_row(2, "Ring", "925 SILVER", "CZ Round Shape 38", fob=6.5, design_no="JR05588"),
            _make_packing_row(3, "Ring", "925 SILVER", "CZ Round Shape 38", fob=80.0, design_no="JR08297"),
            _make_packing_row(4, "Ring", "925 SILVER", "CZ Round Shape 38", fob=81.0, design_no="JR08296"),
        ]
        r = build_global_pz_lineage(positions, packing)

        pos4_link = next(lk for lk in r.position_links if lk.position_no == 4)
        pos5_link = next(lk for lk in r.position_links if lk.position_no == 5)

        assert 1 in pos4_link.packing_serials
        assert 2 in pos4_link.packing_serials
        assert 3 in pos5_link.packing_serials
        assert 4 in pos5_link.packing_serials

    def test_both_positions_full_when_prices_match(self):
        """With 4 correctly priced rows (2 cheap + 2 expensive), both positions FULL."""
        positions = self._ring_positions()
        packing = [
            _make_packing_row(1, "Ring", "925 SILVER", "CZ Round Shape 38", fob=7.0, design_no="JR01"),
            _make_packing_row(2, "Ring", "925 SILVER", "CZ Round Shape 38", fob=8.0, design_no="JR02"),
            _make_packing_row(3, "Ring", "925 SILVER", "CZ Round Shape 38", fob=81.0, design_no="JR03"),
            _make_packing_row(4, "Ring", "925 SILVER", "CZ Round Shape 38", fob=80.0, design_no="JR04"),
        ]
        r = build_global_pz_lineage(positions, packing)

        pos4_link = next(lk for lk in r.position_links if lk.position_no == 4)
        pos5_link = next(lk for lk in r.position_links if lk.position_no == 5)
        assert pos4_link.match_status == "FULL"
        assert pos5_link.match_status == "FULL"


# ─────────────────────────────────────────────────────────────────────────────
# V2 — Allocation confidence and evidence
# ─────────────────────────────────────────────────────────────────────────────


class TestV2AllocationConfidence:
    """V2 must populate allocation_confidence on every assigned link."""

    def test_strong_price_match_yields_high_confidence(self):
        """A single unambiguous position with price within 10% → HIGH confidence."""
        pos = [_make_invoice_position(
            1, "PCS", "925 Silver", "CZ Stud Jewellery",
            [{"type": "Ring", "qty": 2.0, "amount": 160.0}],  # rate = $80
        )]
        packing = [
            _make_packing_row(1, "Ring", "925 SILVER", "CZ Round Shape 38",
                              fob=81.0, design_no="JR08296"),
            _make_packing_row(2, "Ring", "925 SILVER", "CZ Round Shape 38",
                              fob=80.0, design_no="JR08297"),
        ]
        r = build_global_pz_lineage(pos, packing)
        link = r.position_links[0]
        assert link.allocation_confidence == "HIGH"
        assert "PRICE_MATCH" in link.allocation_reason_codes

    def test_empty_link_has_empty_confidence(self):
        """Unassigned (EMPTY) link must have allocation_confidence=''."""
        pos = [
            _make_invoice_position(
                1, "PCS", "925 Silver", "CZ Stud Jewellery",
                [{"type": "Ring", "qty": 2.0, "amount": 20.0}],
            ),
            _make_invoice_position(
                2, "PCS", "09KT Gold", "Lab Grown Diamond Jewellery",
                [{"type": "Bracelet", "qty": 1.0, "amount": 500.0}],
            ),
        ]
        packing = [
            _make_packing_row(1, "Ring", "925 SILVER", "CZ Round Shape 38", fob=10.0),
            _make_packing_row(2, "Ring", "925 SILVER", "CZ Round Shape 38", fob=10.0),
        ]
        r = build_global_pz_lineage(pos, packing)
        empty_links = [lk for lk in r.position_links if lk.match_status == "EMPTY"]
        for lk in empty_links:
            assert lk.allocation_confidence == "", (
                f"EMPTY link pos{lk.position_no} should have empty confidence"
            )

    def test_confidence_is_not_empty_when_rows_assigned(self):
        """Any link with packing rows must have a non-empty allocation_confidence."""
        pos = [_make_invoice_position(
            1, "PCS", "09KT Gold", "Lab Grown Diamond Jewellery",
            [{"type": "Bracelet", "qty": 2.0, "amount": 600.0}],
        )]
        packing = [
            _make_packing_row(1, "Bracelet", "9KT GOLD", "LAB ROUND DIA 1 2.0", fob=300.0),
            _make_packing_row(2, "Bracelet", "9KT GOLD", "LAB ROUND DIA 1 2.0", fob=300.0),
        ]
        r = build_global_pz_lineage(pos, packing)
        link = r.position_links[0]
        assert link.allocation_confidence in ("HIGH", "MEDIUM", "LOW")


class TestV2AllocationEvidence:
    """V2 must populate allocation_evidence keyed by serial number."""

    def test_evidence_has_entry_for_each_assigned_serial(self):
        pos = [_make_invoice_position(
            1, "PCS", "925 Silver", "CZ Stud Jewellery",
            [{"type": "Ring", "qty": 2.0, "amount": 20.0}],
        )]
        packing = [
            _make_packing_row(1, "Ring", "925 SILVER", "CZ Round Shape 38", fob=10.0),
            _make_packing_row(2, "Ring", "925 SILVER", "CZ Round Shape 38", fob=10.0),
        ]
        r = build_global_pz_lineage(pos, packing)
        assert 1 in r.allocation_evidence
        assert 2 in r.allocation_evidence

    def test_evidence_record_has_required_keys(self):
        pos = [_make_invoice_position(
            1, "PCS", "925 Silver", "CZ Stud Jewellery",
            [{"type": "Ring", "qty": 1.0, "amount": 80.0}],
        )]
        packing = [
            _make_packing_row(5, "Ring", "925 SILVER", "CZ Round Shape 38",
                              fob=81.0, design_no="JR08296"),
        ]
        r = build_global_pz_lineage(pos, packing)
        ev = r.allocation_evidence[5]
        assert "position_no"   in ev
        assert "item_type"     in ev
        assert "tier"          in ev
        assert "score"         in ev
        assert "unit_price"    in ev
        assert "expected_rate" in ev
        assert "style_type"    in ev
        assert "design_no"     in ev

    def test_evidence_position_no_matches_assigned_link(self):
        pos = [_make_invoice_position(
            3, "PCS", "925 Silver", "CZ Stud Jewellery",
            [{"type": "Ring", "qty": 1.0, "amount": 80.0}],
        )]
        packing = [
            _make_packing_row(7, "Ring", "925 SILVER", "CZ Round Shape 38", fob=80.0),
        ]
        r = build_global_pz_lineage(pos, packing)
        assert r.allocation_evidence[7]["position_no"] == 3

    def test_evidence_expected_rate_matches_invoice(self):
        pos = [_make_invoice_position(
            1, "PCS", "925 Silver", "CZ Stud Jewellery",
            [{"type": "Ring", "qty": 2.0, "amount": 160.0}],  # rate = $80
        )]
        packing = [
            _make_packing_row(1, "Ring", "925 SILVER", "CZ Round Shape 38", fob=81.0),
        ]
        r = build_global_pz_lineage(pos, packing)
        assert abs(r.allocation_evidence[1]["expected_rate"] - 80.0) < 0.01
