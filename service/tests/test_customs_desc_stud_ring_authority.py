"""
test_customs_desc_stud_ring_authority.py — Regression: final product noun
has higher priority than descriptor keywords when detecting item type.

Authority rule: the LAST item-type keyword in a commercial invoice
description is the final product noun and determines the customs type.
"Stud" appearing before "RING" is a style/setting descriptor, not an
earring type indicator.

Pinned cases (AWB 8400636576 real invoice descriptions):
  - "PCS, 14KT Gold,LGD Gold Stud Jewell RING" → RING
  - "PCS, 14KT Gold, LGD Gold Stud Jewell RING" → RING
  - "PCS, PT950 Platinum,Stud With Diam Jewel RING" → RING + diamonds
  - "PCS, 14KT Gold,Stud Jewelry DIA&CLS RING" → RING

Generalised:
  - "Stud ... RING"    → RING   (not STUD)
  - "Stud ... PENDANT" → PENDANT (not STUD)
  - "Gold Stud"        → STUD   (only type in string, earrings correct)
  - "18KT EARRINGS LGD" → EARRINGS (no STUD present, unchanged)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import customs_description_engine as cde


# ── Misclassified ring cases (AWB 8400636576 real descriptions) ──────────────

def test_lgd_gold_stud_ring_classified_as_ring():
    """EJL/26-27/233 and /234: 'Stud Jewell RING' → RING, not STUD."""
    r = cde.normalize_item_description("PCS, 14KT Gold,LGD Gold Stud Jewell RING")
    assert r["item_type"] == "RING", f"Expected RING, got {r['item_type']!r}"
    assert r["item_type_pl"] == "Pierścionek"
    assert "Pierścionek" in r["polish_customs_description"]
    assert "Kolczyki" not in r["polish_customs_description"]


def test_lgd_gold_stud_ring_with_space():
    """EJL/26-27/234: space variant of the same description."""
    r = cde.normalize_item_description("PCS, 14KT Gold, LGD Gold Stud Jewell RING")
    assert r["item_type"] == "RING"
    assert "Pierścionek" in r["polish_customs_description"]


def test_lgd_ring_has_lab_diamonds():
    """Stones (LGD) are still detected alongside the final-noun fix."""
    r = cde.normalize_item_description("PCS, 14KT Gold,LGD Gold Stud Jewell RING")
    assert r["stones_pl"] == "diamenty laboratoryjne"
    assert r["natural_or_lab"] == "lab_grown"
    assert "diamentami laboratoryjnymi" in r["polish_customs_description"]


def test_pt950_stud_with_diam_ring_classified_as_ring():
    """EJL/26-27/235 item 3: 'Stud With Diam Jewel RING' → RING + diamonds."""
    r = cde.normalize_item_description("PCS, PT950 Platinum,Stud With Diam Jewel RING")
    assert r["item_type"] == "RING", f"Expected RING, got {r['item_type']!r}"
    assert "Pierścionek" in r["polish_customs_description"]
    assert "Kolczyki" not in r["polish_customs_description"]


def test_pt950_stud_diam_ring_has_diamonds():
    """'Diam' abbreviation detected as diamonds."""
    r = cde.normalize_item_description("PCS, PT950 Platinum,Stud With Diam Jewel RING")
    assert r["stones_pl"] == "diamenty"
    assert "diamentami" in r["polish_customs_description"]


def test_stud_jewelry_dia_cls_ring_classified_as_ring():
    """EJL/26-27/236 item 1: 'Stud Jewelry DIA&CLS RING' → RING."""
    r = cde.normalize_item_description("PCS, 14KT Gold,Stud Jewelry DIA&CLS RING")
    assert r["item_type"] == "RING", f"Expected RING, got {r['item_type']!r}"
    assert "Pierścionek" in r["polish_customs_description"]
    assert r["stones_pl"] == "diamenty i kamienie szlachetne"
    assert "diamentami i kamieniami szlachetnymi" in r["polish_customs_description"]


# ── Generalised final-noun-authority cases ───────────────────────────────────

def test_stud_pendant_gives_pendant():
    """'Stud' before 'PENDANT' → PENDANT (not STUD)."""
    r = cde.normalize_item_description("14KT Gold Stud Style PENDANT DIA")
    assert r["item_type"] == "PENDANT", f"Expected PENDANT, got {r['item_type']!r}"
    assert "Wisiorek" in r["polish_customs_description"]


# ── Non-regression: standalone STUD still means earrings ────────────────────

def test_standalone_stud_is_earrings():
    """When STUD is the only item-type keyword, it correctly means earrings."""
    r = cde.normalize_item_description("14KT Gold Stud Plain")
    assert r["item_type"] == "STUD"
    assert r["item_type_pl"] == "Kolczyki wkrętki"


def test_earrings_unchanged():
    """Standard EARRINGS description unaffected."""
    r = cde.normalize_item_description("18KT EARRINGS LGD")
    assert r["item_type"] == "EARRINGS"
    assert r["item_type_pl"] == "Kolczyki"


# ── Batch-level: AWB 8400636576 summary totals ───────────────────────────────

def _awb_8400636576_batch() -> dict:
    """Minimal batch reproducing all 7 invoice lines from AWB 8400636576."""
    return {
        "invoices": [
            {
                "invoice_number": "EJL/26-27/233",
                "items": [{"product_code": "EJL/26-27/233-1",
                            "description": "PCS, 14KT Gold,LGD Gold Stud Jewell RING",
                            "item_type": "", "quantity": 1, "unit_price": 279.0,
                            "line_total": 279.0, "hsn_code": "71131914"}],
            },
            {
                "invoice_number": "EJL/26-27/234",
                "items": [{"product_code": "EJL/26-27/234-1",
                            "description": "PCS, 14KT Gold, LGD Gold Stud Jewell RING",
                            "item_type": "", "quantity": 1, "unit_price": 872.0,
                            "line_total": 872.0, "hsn_code": "71131914"}],
            },
            {
                "invoice_number": "EJL/26-27/235",
                "items": [
                    {"product_code": "EJL/26-27/235-1",
                     "description": "PCS, 18KT Gold,Plain Jewellery PENDANT",
                     "item_type": "", "quantity": 7, "unit_price": 650.0,
                     "line_total": 4550.0, "hsn_code": "71131911"},
                    {"product_code": "EJL/26-27/235-2",
                     "description": "PCS, PT950 Platinum,Plain Jewel RING",
                     "item_type": "", "quantity": 1, "unit_price": 2555.0,
                     "line_total": 2555.0, "hsn_code": "71131921"},
                    {"product_code": "EJL/26-27/235-3",
                     "description": "PCS, PT950 Platinum,Stud With Diam Jewel RING",
                     "item_type": "", "quantity": 1, "unit_price": 2830.0,
                     "line_total": 2830.0, "hsn_code": "71131923"},
                ],
            },
            {
                "invoice_number": "EJL/26-27/236",
                "items": [
                    {"product_code": "EJL/26-27/236-1",
                     "description": "PCS, 14KT Gold,Stud Jewelry DIA&CLS RING",
                     "item_type": "", "quantity": 1, "unit_price": 516.0,
                     "line_total": 516.0, "hsn_code": "71131919"},
                    {"product_code": "EJL/26-27/236-2",
                     "description": "PCS, 14KT Gold,Plain Jewellery RING",
                     "item_type": "", "quantity": 1, "unit_price": 675.0,
                     "line_total": 675.0, "hsn_code": "71131911"},
                ],
            },
        ],
        "invoice_totals": {"total_cif_usd": 12427.0},
    }


def test_awb_8400636576_ring_count():
    """After fix: 6 rings total (no STUD lines)."""
    lines = cde.process_batch_items(_awb_8400636576_batch())
    ring_qty = sum(l["quantity"] for l in lines if l["item_type"] == "RING")
    assert ring_qty == 6, f"Expected 6 rings, got {ring_qty}"


def test_awb_8400636576_pendant_count():
    """After fix: 7 pendants total."""
    lines = cde.process_batch_items(_awb_8400636576_batch())
    pendant_qty = sum(l["quantity"] for l in lines if l["item_type"] == "PENDANT")
    assert pendant_qty == 7, f"Expected 7 pendants, got {pendant_qty}"


def test_awb_8400636576_no_stud_lines():
    """After fix: zero lines classified as STUD."""
    lines = cde.process_batch_items(_awb_8400636576_batch())
    stud_lines = [l for l in lines if l["item_type"] == "STUD"]
    assert stud_lines == [], f"Expected no STUD lines, got: {stud_lines}"


def test_awb_8400636576_total_pcs():
    """After fix: total 13 PCS."""
    lines = cde.process_batch_items(_awb_8400636576_batch())
    total = sum(l["quantity"] for l in lines)
    assert total == 13, f"Expected 13 total PCS, got {total}"
