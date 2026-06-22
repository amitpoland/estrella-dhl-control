"""test_sales_packing_code_detection.py

Sales packing list product-code detection (AWB 9158478722 class).

The real design code is often in the DESCRIPTION column (→ item_type) while
PRODUCT is blank or holds an EJL order reference. normalize_sales_row_codes
routes the real code into design_no (the sales_packing_matcher key) and the
EJL ref into order_ref, ignoring non-product tokens like PND. product_code is
never set here — the matcher mints the canonical product_code from purchase
evidence keyed on design_no.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services.sales_packing_code_detection import (   # noqa: E402
    is_order_ref, is_product_code, is_category_token, is_placeholder,
    normalize_sales_row_codes,
)


# ── Detection primitives ────────────────────────────────────────────────────

@pytest.mark.parametrize("v", [
    "EJL/26-27/299-1", "EJL/26-27/298-3", "EJL/26-27/299",
    " ejl / 26-27 / 290-1 ", "EJL/26-27/300-12",
])
def test_is_order_ref_true(v):
    assert is_order_ref(v) is True


@pytest.mark.parametrize("v", ["J4006R01513", "CSTN00026", "PND", "", "—", "PROF/12"])
def test_is_order_ref_false(v):
    assert is_order_ref(v) is False


@pytest.mark.parametrize("v", [
    "J4006R01513", "CSTN00026", "JR04929", "JE02341", "JBR00254-1.50",
    "J4502R00930-.04", "JP02436", "J4506P00551-S", "J4009E00582",
])
def test_is_product_code_true(v):
    assert is_product_code(v) is True


@pytest.mark.parametrize("v", [
    "", "—", "-", "PND", "RNG", "EAR", "EJL/26-27/299-1", "ABC", "PND ", "12",
])
def test_is_product_code_false(v):
    assert is_product_code(v) is False, v


def test_category_and_placeholder_helpers():
    assert is_category_token("pnd") and is_category_token("RNG")
    assert not is_category_token("J4006R01513")
    assert is_placeholder("—") and is_placeholder("") and is_placeholder("N/A")
    assert not is_placeholder("J4006R01513")


# ── normalize_sales_row_codes — task examples ───────────────────────────────

def test_product_from_description_when_product_blank():
    # PRODUCT=— (design blank), DESCRIPTION=J4006R01513
    row, cls = normalize_sales_row_codes({"design_no": "—", "item_type": "J4006R01513"})
    assert row["design_no"] == "J4006R01513"
    assert "design_from_description" in cls
    assert "product_code" not in row or not row.get("product_code")   # matcher mints it


def test_product_from_description_when_product_is_order_ref():
    # PRODUCT=EJL/26-27/298-3, DESCRIPTION=J4009E00582
    row, cls = normalize_sales_row_codes(
        {"design_no": "EJL/26-27/298-3", "item_type": "J4009E00582"})
    assert row["design_no"] == "J4009E00582"
    assert row["order_ref"] == "EJL/26-27/298-3"
    assert "order_ref_from_design" in cls and "design_from_description" in cls


def test_cstn_code_from_description():
    # PRODUCT=EJL/26-27/299-1, DESCRIPTION=CSTN00026
    row, _ = normalize_sales_row_codes(
        {"design_no": "EJL/26-27/299-1", "item_type": "CSTN00026"})
    assert row["design_no"] == "CSTN00026"
    assert row["order_ref"] == "EJL/26-27/299-1"


def test_pnd_is_not_promoted_to_a_product():
    # PRODUCT=—, DESCRIPTION=PND → no design code minted (ignore PND)
    row, cls = normalize_sales_row_codes({"design_no": "—", "item_type": "PND"})
    assert row["design_no"] == ""
    assert not row.get("product_code")
    assert "design_from_description" not in cls


def test_ejl_never_becomes_design_or_product_code():
    row, _ = normalize_sales_row_codes(
        {"design_no": "EJL/26-27/299-1", "item_type": "—"})
    assert row["design_no"] == ""                  # not the EJL ref
    assert row["order_ref"] == "EJL/26-27/299-1"   # preserved separately
    assert not row.get("product_code")


def test_genuine_pnd_in_design_column_preserved_for_disambiguator():
    # Files where the design column legitimately holds "PND" must keep it so
    # the gated PND price-tiebreak disambiguator can still run.
    row, cls = normalize_sales_row_codes({"design_no": "PND", "item_type": "PND"})
    assert row["design_no"] == "PND"
    assert cls == "unchanged"


def test_existing_real_design_is_left_untouched():
    # Normal EJL files (Design column holds the real code) must not change.
    row, cls = normalize_sales_row_codes(
        {"design_no": "JP01823-0.20", "item_type": "RNG"})
    assert row["design_no"] == "JP01823-0.20"
    assert cls == "unchanged"


def test_currency_fields_pass_through_unchanged_eur_and_usd():
    eur = normalize_sales_row_codes(
        {"design_no": "—", "item_type": "J4006R01513",
         "unit_price": 220.0, "currency": "EUR"})[0]
    usd = normalize_sales_row_codes(
        {"design_no": "EJL/26-27/299-1", "item_type": "CSTN00026",
         "unit_price": 618.0, "currency": "USD"})[0]
    assert eur["currency"] == "EUR" and eur["unit_price"] == 220.0
    assert usd["currency"] == "USD" and usd["unit_price"] == 618.0


def test_awb_9158478722_fixture_rows_resolve_expected_design_codes():
    """The AWB 9158478722 mixed layout produces the expected design_no values
    that the matcher will resolve to canonical EJL product_codes."""
    fixture = [
        {"design_no": "—",                "item_type": "J4006R01513"},
        {"design_no": "EJL/26-27/298-3",  "item_type": "J4009E00582"},
        {"design_no": "EJL/26-27/299-1",  "item_type": "CSTN00026"},
        {"design_no": "—",                "item_type": "PND"},
        {"design_no": "JR04929",          "item_type": "RNG"},   # already correct
    ]
    out = [normalize_sales_row_codes(dict(r))[0] for r in fixture]
    assert [r["design_no"] for r in out] == [
        "J4006R01513", "J4009E00582", "CSTN00026", "", "JR04929",
    ]
    # EJL refs preserved as order_ref, never as a code.
    assert out[1]["order_ref"] == "EJL/26-27/298-3"
    assert out[2]["order_ref"] == "EJL/26-27/299-1"
    # PND row stays unresolved (no product created/adopted).
    assert out[3]["design_no"] == "" and not out[3].get("product_code")
