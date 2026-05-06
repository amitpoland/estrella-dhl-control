"""
test_product_code_determinism.py
=================================
Verifies that product_code assignment is stable under canonical sort:

  1. Shuffled input order → identical product_codes mapped to identical items
  2. Suffix format is invoice_no-N (1-indexed, no space)
  3. First sorted item always receives -1
  4. Duplicate canonical keys do not crash; warning logged; codes unique
  5. Single-item invoice gets -1
  6. Multi-item invoice codes reset per invoice
  7. canonical_item_sort_key is importable and returns a tuple
"""
from __future__ import annotations

import random
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pz_import_processor import (
    build_en_name, build_pl_name, build_product_code, calculate_landed,
    canonical_item_sort_key,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _mk_item(family, karat, item_type, qty, total_usd, hsn="71131900"):
    return {
        "description_en": build_en_name({"family": family, "karat": karat, "item_type": item_type}),
        "pl_desc":        build_pl_name({"family": family, "karat": karat, "item_type": item_type}),
        "item_type":      item_type,
        "family":         family,
        "karat":          karat,
        "hsn":            hsn,
        "quantity":       qty,
        "unit":           "PCS",
        "unit_price_usd": round(total_usd / qty, 4),
        "total_usd":      total_usd,
        "gross_weight":   0.0,
        "net_weight":     0.0,
    }


_ZC429  = {"duty_pln": 500.0, "total_cif_usd": 5000.0, "lrn": "TEST_LRN"}
_NBP    = {"usd_rate": 4.0}
_INV_NO = "EJL/26-27/TEST"

_FOUR_ITEMS = [
    _mk_item("Diamond Studded",                "14KT", "RING",     3, 900.0,  "71131913"),
    _mk_item("Diamond / Colour Stone Studded", "14KT", "EARRINGS", 4, 1200.0, "71131919"),
    _mk_item("Plain",                          "9KT",  "BRACELET", 2, 400.0,  "71131911"),
    _mk_item("Lab Grown Diamond",              "18KT", "PENDANT",  1, 2500.0, "71131913"),
]


def _invoice(items):
    total = sum(it["total_usd"] for it in items)
    return {
        "invoice_no":    _INV_NO,
        "invoice_date":  "01-05-2026",
        "filename":      "test.pdf",
        "fob_usd":       total,
        "freight_usd":   50.0,
        "insurance_usd": 10.0,
        "cif_usd":       total + 60.0,
        "buyer_name":    "ESTRELLA JEWELS SP Z O O",
        "buyer_nip":     "5252812119",
        "exporter_name": "Estrella Jewels LLP",
        "items":         items,
    }


def _run(items):
    rows, _ = calculate_landed([_invoice(items)], _ZC429, _NBP, corrections_log=[])
    return rows


def _codes_by_desc(rows):
    """Return {description_en: product_code} so we can compare across shuffles."""
    return {r["description_en"]: r["product_code"] for r in rows}


# ── tests ─────────────────────────────────────────────────────────────────────

def test_canonical_sort_key_is_tuple():
    key = canonical_item_sort_key(_FOUR_ITEMS[0], 0)
    assert isinstance(key, tuple)
    assert len(key) == 6


def test_product_code_format_is_1indexed_hyphen():
    rows = _run(_FOUR_ITEMS)
    for r in rows:
        assert r["product_code"].startswith(_INV_NO + "-"), (
            f"Expected {_INV_NO}-N, got {r['product_code']!r}"
        )
        suffix = r["product_code"][len(_INV_NO) + 1:]
        assert suffix.isdigit(), f"Suffix not numeric: {suffix!r}"
        assert int(suffix) >= 1, "suffix must be 1-indexed"


def test_no_bare_invoice_no_in_codes():
    rows = _run(_FOUR_ITEMS)
    codes = [r["product_code"] for r in rows]
    assert _INV_NO not in codes, "Bare invoice_no must not appear as product_code"


def test_first_position_is_minus_1():
    rows = _run(_FOUR_ITEMS)
    assert any(r["product_code"] == f"{_INV_NO}-1" for r in rows)


def test_shuffled_input_produces_same_codes():
    """Core determinism invariant: shuffling input order must not change which
    item gets which product_code."""
    reference = _codes_by_desc(_run(_FOUR_ITEMS))

    rng = random.Random(42)
    for _ in range(20):
        shuffled = _FOUR_ITEMS[:]
        rng.shuffle(shuffled)
        result = _codes_by_desc(_run(shuffled))
        assert result == reference, (
            f"product_code mapping changed after shuffle:\n"
            f"  reference: {reference}\n"
            f"  shuffled:  {result}"
        )


def test_all_codes_unique():
    rows = _run(_FOUR_ITEMS)
    codes = [r["product_code"] for r in rows]
    assert len(codes) == len(set(codes))


def test_line_position_field_present_and_1indexed():
    rows = _run(_FOUR_ITEMS)
    positions = sorted(r["line_position"] for r in rows)
    assert positions == list(range(1, len(_FOUR_ITEMS) + 1))


def test_nazwa_fields_present_in_row():
    rows = _run(_FOUR_ITEMS)
    for r in rows:
        assert "nazwa"    in r, "nazwa missing from row"
        assert "nazwa_pl" in r, "nazwa_pl missing from row"
        assert "nazwa_en" in r, "nazwa_en missing from row"
        assert " / " in r["nazwa"], "nazwa must use ' / ' separator"
        assert r["nazwa"].startswith(r["nazwa_pl"])
        assert r["nazwa"].endswith(r["nazwa_en"])


def test_duplicate_canonical_key_does_not_crash():
    """Two items with identical canonical attributes still get unique codes.
    The warning is logged but execution continues."""
    identical = [
        _mk_item("Plain", "9KT", "RING", 2, 400.0, "71131911"),
        _mk_item("Plain", "9KT", "RING", 2, 400.0, "71131911"),  # exact duplicate
    ]
    log = []
    rows, _ = calculate_landed([_invoice(identical)], _ZC429, _NBP, corrections_log=log)
    codes = [r["product_code"] for r in rows]
    assert len(codes) == len(set(codes)), "Duplicate canonical key must still yield unique codes"
    assert any("canonical" in entry.lower() or "warn" in entry.lower() for entry in log), (
        "Duplicate canonical key must emit a warning to corrections_log"
    )


def test_single_item_invoice_gets_minus_1():
    single = [_mk_item("Plain", "14KT", "RING", 1, 2000.0)]
    fob = 2000.0
    inv = {**_invoice(single), "fob_usd": fob, "cif_usd": fob + 60.0}
    zc429 = {"duty_pln": 50.0, "total_cif_usd": fob + 60.0, "lrn": "X"}
    rows, _ = calculate_landed([inv], zc429, _NBP, corrections_log=[])
    assert rows[0]["product_code"] == f"{_INV_NO}-1"
    assert rows[0]["line_position"] == 1


def test_codes_reset_per_invoice():
    inv_a = {**_invoice([_mk_item("Plain", "9KT", "RING", 1, 1500.0)]),
             "invoice_no": "EJL/A", "fob_usd": 1500.0, "cif_usd": 1560.0}
    inv_b = {**_invoice([_mk_item("Plain", "9KT", "BRACELET", 1, 1000.0),
                          _mk_item("Plain", "9KT", "PENDANT",  1,  500.0)]),
             "invoice_no": "EJL/B", "fob_usd": 1500.0, "cif_usd": 1560.0}
    zc429 = {"duty_pln": 80.0, "total_cif_usd": 3120.0, "lrn": "X"}
    rows, _ = calculate_landed([inv_a, inv_b], zc429, _NBP, corrections_log=[])
    a_codes = [r["product_code"] for r in rows if r["invoice_no"] == "EJL/A"]
    b_codes = sorted(r["product_code"] for r in rows if r["invoice_no"] == "EJL/B")
    assert a_codes == ["EJL/A-1"]
    assert b_codes == ["EJL/B-1", "EJL/B-2"]


def test_golden_totals_unchanged():
    """Canonical sort must not alter financial totals — only code assignment."""
    rows_orig    = _run(_FOUR_ITEMS)
    shuffled     = _FOUR_ITEMS[::-1]  # reverse order
    rows_shuffle = _run(shuffled)

    net_orig    = round(sum(r["line_netto_pln"]  for r in rows_orig),    4)
    net_shuffle = round(sum(r["line_netto_pln"]  for r in rows_shuffle), 4)
    gross_orig    = round(sum(r["line_brutto_pln"] for r in rows_orig),    4)
    gross_shuffle = round(sum(r["line_brutto_pln"] for r in rows_shuffle), 4)

    assert net_orig    == net_shuffle,   "Total netto changed after shuffle"
    assert gross_orig  == gross_shuffle, "Total brutto changed after shuffle"


def test_no_space_hyphen_in_any_generated_code():
    """No generated product_code may contain ' -' (space before hyphen).
    Covers both canonical-sort output and any shuffled permutation."""
    rows = _run(_FOUR_ITEMS)
    for r in rows:
        assert " -" not in r["product_code"], (
            f"Space-before-hyphen found in product_code: {r['product_code']!r}"
        )

    # Also check all 20 shuffled runs
    rng = random.Random(99)
    for _ in range(20):
        shuffled = _FOUR_ITEMS[:]
        rng.shuffle(shuffled)
        for r in _run(shuffled):
            assert " -" not in r["product_code"], (
                f"Space-before-hyphen found after shuffle: {r['product_code']!r}"
            )


def test_build_product_code_helper():
    """build_product_code is the single source of truth for suffix format."""
    assert build_product_code("EJL/25-26/1043", 1)  == "EJL/25-26/1043-1"
    assert build_product_code("EJL/25-26/1043", 2)  == "EJL/25-26/1043-2"
    assert build_product_code("EJL/25-26/1043", 10) == "EJL/25-26/1043-10"
    # No space, no double-hyphen
    for pos in range(1, 8):
        code = build_product_code("EJL/TEST", pos)
        assert " -" not in code, f"Space-before-hyphen in {code!r}"
        assert code == f"EJL/TEST-{pos}"
