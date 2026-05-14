"""
test_pr2c1_blank_product_code.py — PR 2C.1: block blank product_code promotion.

Coverage:
  1. test_build_matched_sales_lines_filters_blank_product_code
     — rows with product_code=None or "" are excluded; skipped count correct.
  2. test_build_matched_sales_lines_filters_requires_manual_review
     — rows with requires_manual_review=True are excluded even if product_code valid.
  3. test_build_matched_sales_lines_keeps_valid_rows
     — mix of valid, blank-code, and manual-review rows; only valid survive.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.api.routes_packing import _build_matched_sales_lines


# ── helpers ───────────────────────────────────────────────────────────────────

def _line(product_code, design_no="D001", requires_manual_review=False):
    return {
        "product_code":          product_code,
        "design_no":             design_no,
        "bag_id":                "BAG-1",
        "invoice_no":            "INV-001",
        "quantity":              1,
        "remarks":               "",
        "requires_manual_review": requires_manual_review,
    }


# ── 1. Blank product_code filtered ───────────────────────────────────────────

def test_build_matched_sales_lines_filters_blank_product_code():
    lines = [
        _line(product_code=None,  design_no="J3609R01707"),  # NULL product_code
        _line(product_code="",    design_no="J3609R01708"),  # empty string
        _line(product_code="   ", design_no="J3609R01709"),  # whitespace only
        _line(product_code="EJL-RNG-417G", design_no="D100"),  # valid
    ]
    sales_lines, skipped = _build_matched_sales_lines(lines, client="SUOKKO")

    assert skipped == 3, f"expected 3 skipped, got {skipped}"
    assert len(sales_lines) == 1
    assert sales_lines[0]["product_code"] == "EJL-RNG-417G"


# ── 2. requires_manual_review=True filtered ───────────────────────────────────

def test_build_matched_sales_lines_filters_requires_manual_review():
    lines = [
        _line(product_code="EJL-RNG-417G", requires_manual_review=True),
        _line(product_code="EJL-PND-ROSE", requires_manual_review=False),
    ]
    sales_lines, skipped = _build_matched_sales_lines(lines, client="SUOKKO")

    assert skipped == 1, f"expected 1 skipped, got {skipped}"
    assert len(sales_lines) == 1
    assert sales_lines[0]["product_code"] == "EJL-PND-ROSE"


# ── 3. Mix: only valid rows survive ──────────────────────────────────────────

def test_build_matched_sales_lines_keeps_valid_rows():
    lines = [
        _line(product_code="EJL-RNG-417G"),                        # valid
        _line(product_code="EJL-PND-ROSE"),                        # valid
        _line(product_code=None, design_no="J3609R01707"),          # blank code
        _line(product_code="", design_no="J3609R01708"),            # blank code
        _line(product_code="EJL-BRC-001", requires_manual_review=True),  # review flag
    ]
    sales_lines, skipped = _build_matched_sales_lines(lines, client="ACME")

    assert skipped == 3, f"expected 3 skipped, got {skipped}"
    assert len(sales_lines) == 2
    codes = {ln["product_code"] for ln in sales_lines}
    assert codes == {"EJL-RNG-417G", "EJL-PND-ROSE"}
    # client_name propagated to every line
    for ln in sales_lines:
        assert ln["client_name"] == "ACME"
