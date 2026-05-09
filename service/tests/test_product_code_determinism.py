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
    # Intentional change (Option B, AWB 6049349806 fix): canonical_item_sort_key
    # now returns a single-element tuple `(original_index,)` so product_codes
    # follow invoice line order instead of (item_type, description, hs, price,
    # qty) sort order. The earlier 6-tuple sort renumbered <invoice>-<N> codes
    # whenever an invoice mixed item types and made auto-register (invoice
    # order) and pz_rows.json (sorted order) disagree. Today's parser is
    # deterministic by original_index, so re-parse stability is preserved.
    key = canonical_item_sort_key(_FOUR_ITEMS[0], 0)
    assert isinstance(key, tuple)
    assert len(key) == 1
    assert key == (0,)
    # Sanity: each original_index produces its own unique key
    keys = [canonical_item_sort_key(it, i) for i, it in enumerate(_FOUR_ITEMS)]
    assert keys == [(0,), (1,), (2,), (3,)]


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


def test_codes_follow_input_list_order():
    """Intentional contract change (Option B, AWB 6049349806 fix):
    product_code <invoice>-<N> now means the Nth item in the parser's
    input list (which is the customs invoice's line order). Shuffling
    the items dict is no longer a real-world scenario — the parser
    produces a deterministic list per PDF read. This test pins the new
    contract: codes follow input order strictly.

    The OLD behaviour (shuffled-input → identical mapping by description)
    was an artificial protection against parser non-determinism; the
    parser is deterministic today. Pinning sorted-by-content order
    instead caused product_codes to drift away from invoice line
    positions whenever an invoice mixed item types — e.g. invoice 123
    with RING/PENDANT/EARRINGS lines was renumbered alphabetically by
    item_type, which made `EJL/26-27/123-2` reference the SECOND
    SORTED item, not the second invoice line. auto-register
    (which reads invoice_lines in invoice order) and pz_rows.json
    (formerly sorted) ended up disagreeing on the same code, producing
    drifted line content in wFirma PZ documents."""
    rows = _run(_FOUR_ITEMS)
    # rows is invoice-positional now: input list[i] → product_code -<i+1>
    by_pos = {r["line_position"]: r["description_en"] for r in rows}
    expected = {i + 1: it["description_en"] for i, it in enumerate(_FOUR_ITEMS)}
    assert by_pos == expected, (
        f"product_code line_position must match input order:\n"
        f"  expected: {expected}\n"
        f"  got:      {by_pos}"
    )

    # Shuffling the input now intentionally changes which code each item gets,
    # because the input order IS the canonical order. Verify the contract by
    # reversing the input and checking codes mirror.
    reversed_items = _FOUR_ITEMS[::-1]
    rev_rows = _run(reversed_items)
    rev_by_pos = {r["line_position"]: r["description_en"] for r in rev_rows}
    expected_rev = {i + 1: it["description_en"] for i, it in enumerate(reversed_items)}
    assert rev_by_pos == expected_rev, (
        "Reversed input must produce reversed code → description mapping"
    )


def test_codes_stable_when_parser_input_is_stable():
    """Re-parse-stability claim: the same parser input (deterministic
    PDF read) produces identical codes every time. This is the practical
    invariant — what actually matters for re-parsing the same PDF
    against the same parser version."""
    reference = _codes_by_desc(_run(_FOUR_ITEMS))
    for _ in range(5):
        # Same input list passed in identical order — deterministic parser.
        result = _codes_by_desc(_run(_FOUR_ITEMS[:]))
        assert result == reference


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


def test_two_identical_items_still_get_unique_codes():
    """Two items with identical attributes must still receive unique
    product_codes by virtue of invoice-position numbering.

    Intentional change (Option B + duplicate-warning cleanup): the
    earlier ``test_duplicate_canonical_key_does_not_crash`` also
    asserted that a [WARN] was appended to corrections_log when two
    items shared a multi-tier canonical key. After the sort became
    ``(original_index,)``, no two items can share a canonical key by
    construction, and the surrounding warning loop emitted a false
    [WARN] per item on every multi-line invoice. The block was removed.
    What remains is the structural guarantee: identical items still
    coexist with unique codes."""
    identical = [
        _mk_item("Plain", "9KT", "RING", 2, 400.0, "71131911"),
        _mk_item("Plain", "9KT", "RING", 2, 400.0, "71131911"),  # exact duplicate
    ]
    log = []
    rows, _ = calculate_landed([_invoice(identical)], _ZC429, _NBP, corrections_log=log)
    codes = [r["product_code"] for r in rows]
    assert len(codes) == len(set(codes)), \
        "Identical items must still yield unique invoice-positional codes"
    assert codes == [f"{_INV_NO}-1", f"{_INV_NO}-2"]
    # NEW: corrections_log must NOT carry a stale "canonical" / "share
    # identical canonical sort key" entry — that warning was vestigial
    # under the old multi-tier sort.
    for entry in log:
        assert "share identical canonical" not in entry, (
            "Stale canonical-key warning re-introduced — see Option B "
            "duplicate-warning cleanup"
        )


def test_no_false_canonical_warnings_on_mixed_invoice():
    """AWB 6049349806 invoice 123 case: 5 mixed-type lines must NOT
    trigger any false canonical-key warnings in corrections_log."""
    five_mixed = [
        _mk_item("Lab Grown Diamond", "14KT",  "RING",     1, 176.0, "71131914"),
        _mk_item("Plain",             "14KT",  "PENDANT",  1,  36.0, "71131911"),
        _mk_item("Plain",             "SL925", "PENDANT",  1,   4.0, "71131141"),
        _mk_item("Lab Grown Diamond", "SL925", "EARRINGS", 1,  43.0, "71131144"),
        _mk_item("Lab Grown Diamond", "SL925", "EARRINGS", 3, 171.0, "71131914"),
    ]
    log = []
    # Scale ZC429 numbers to a plausible duty rate (~3%) for this small
    # synthetic invoice — _ZC429.duty_pln=500 is calibrated for the
    # 4-item _FOUR_ITEMS bundle, not these 5 mixed items.
    fob = sum(it["total_usd"] for it in five_mixed)  # 430 USD
    inv = {**_invoice(five_mixed), "fob_usd": fob, "cif_usd": fob + 60.0}
    zc429_scaled = {"duty_pln": 60.0, "total_cif_usd": fob + 60.0,
                    "lrn": "TEST_LRN"}
    rows, _ = calculate_landed([inv], zc429_scaled, _NBP, corrections_log=log)
    assert len(rows) == 5
    # Codes are invoice-positional (Option B contract)
    assert [r["product_code"] for r in rows] == [
        f"{_INV_NO}-1", f"{_INV_NO}-2", f"{_INV_NO}-3",
        f"{_INV_NO}-4", f"{_INV_NO}-5",
    ]
    # Nothing in corrections_log mentions the vestigial canonical warning
    canonical_warnings = [e for e in log if "canonical" in e.lower()]
    assert canonical_warnings == [], (
        f"Multi-line invoice must NOT produce canonical-key warnings. "
        f"Got: {canonical_warnings}"
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
