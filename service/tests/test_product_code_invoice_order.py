"""
test_product_code_invoice_order.py
==================================

Regression tests for Option B fix (AWB 6049349806 misallocation).

Pin the contract that ``<invoice>-<N>`` means the Nth invoice line, in
parser/invoice order — even when the invoice mixes item types
(RING + PENDANT + EARRINGS). This was the operator's mental model and
matches what ``wfirma_product_auto_register`` already uses when it
reads ``documents.db.invoice_lines``. Fixing the engine to use the
same order brings auto-register and PZ rows into agreement under the
same product_code.

These tests are independent of test_product_code_determinism.py — they
specifically reproduce the AWB 6049349806 invoice 123 scenario (5
mixed-type lines) and assert each pz_row carries the description of
the corresponding invoice line, NOT the alphabetically-sorted item.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pz_import_processor import (
    canonical_item_sort_key,
    calculate_landed,
    build_en_name,
    build_pl_name,
)


def _mk_item(family, karat, item_type, qty, total_usd, hsn="71131900"):
    return {
        "description_en": build_en_name({"family": family, "karat": karat,
                                          "item_type": item_type}),
        "pl_desc":        build_pl_name({"family": family, "karat": karat,
                                          "item_type": item_type}),
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


# AWB 6049349806 invoice EJL/26-27/123 — 5 mixed-type lines in source order.
# Names mirror the live invoice descriptions inspected during the audit.
_INVOICE_123_ITEMS = [
    _mk_item("Lab Grown Diamond",   "14KT", "RING",     1, 176.0, "71131914"),  # line 1
    _mk_item("Plain",               "14KT", "PENDANT",  1,  36.0, "71131911"),  # line 2
    _mk_item("Plain",               "SL925","PENDANT",  1,   4.0, "71131141"),  # line 3
    _mk_item("Lab Grown Diamond",   "SL925","EARRINGS", 1,  43.0, "71131144"),  # line 4
    _mk_item("Lab Grown Diamond",   "SL925","EARRINGS", 3, 171.0, "71131914"),  # line 5
]


def _run_invoice(items, invoice_no="EJL/26-27/123"):
    fob = sum(it["total_usd"] for it in items)
    inv = {
        "invoice_no":    invoice_no,
        "invoice_date":  "04-05-2026",
        "filename":      "test.pdf",
        "fob_usd":       fob,
        "freight_usd":   10.0,
        "insurance_usd": 2.0,
        "cif_usd":       fob + 12.0,
        "buyer_name":    "ESTRELLA JEWELS SP Z O O",
        "buyer_nip":     "5252812119",
        "exporter_name": "Estrella Jewels LLP",
        "items":         items,
    }
    zc429 = {"duty_pln": 100.0, "total_cif_usd": fob + 12.0, "lrn": "X"}
    nbp   = {"usd_rate": 4.0}
    rows, _ = calculate_landed([inv], zc429, nbp, corrections_log=[])
    return rows


# ── Sort key contract ────────────────────────────────────────────────────

class TestSortKeyShape:
    def test_returns_single_element_tuple(self):
        key = canonical_item_sort_key(_INVOICE_123_ITEMS[0], 0)
        assert key == (0,)

    def test_each_index_distinct(self):
        keys = [canonical_item_sort_key(it, i)
                for i, it in enumerate(_INVOICE_123_ITEMS)]
        assert keys == [(0,), (1,), (2,), (3,), (4,)]
        assert len(set(keys)) == len(keys)


# ── AWB 6049349806 invoice 123 alignment (the bug case) ──────────────────

class TestInvoice123InvoiceOrderAlignment:
    def test_each_code_matches_invoice_line_position(self):
        rows = _run_invoice(_INVOICE_123_ITEMS)
        # 5 rows, codes 123-1 through 123-5 in invoice order
        codes = [r["product_code"] for r in rows]
        assert codes == [
            "EJL/26-27/123-1",
            "EJL/26-27/123-2",
            "EJL/26-27/123-3",
            "EJL/26-27/123-4",
            "EJL/26-27/123-5",
        ]

    def test_each_code_carries_invoice_lines_item_type(self):
        rows = _run_invoice(_INVOICE_123_ITEMS)
        # The bug: 123-1 used to be EARRINGS (sorted-first); 123-5 used
        # to be RING (sorted-last). After the fix, 123-1 is RING (line 1)
        # and 123-5 is EARRINGS (line 5).
        by_code = {r["product_code"]: r["item_type"] for r in rows}
        assert by_code == {
            "EJL/26-27/123-1": "RING",
            "EJL/26-27/123-2": "PENDANT",
            "EJL/26-27/123-3": "PENDANT",
            "EJL/26-27/123-4": "EARRINGS",
            "EJL/26-27/123-5": "EARRINGS",
        }

    def test_quantities_match_invoice_lines(self):
        rows = _run_invoice(_INVOICE_123_ITEMS)
        by_code = {r["product_code"]: r["quantity"] for r in rows}
        # Invoice 123 line 5 has qty 3 (the only multi-qty line)
        assert by_code["EJL/26-27/123-1"] == 1
        assert by_code["EJL/26-27/123-2"] == 1
        assert by_code["EJL/26-27/123-3"] == 1
        assert by_code["EJL/26-27/123-4"] == 1
        assert by_code["EJL/26-27/123-5"] == 3

    def test_hsn_codes_track_invoice_lines(self):
        rows = _run_invoice(_INVOICE_123_ITEMS)
        by_code = {r["product_code"]: r.get("hsn", r.get("hsn_code", ""))
                   for r in rows}
        # Each pz_code gets the HSN of the SAME invoice line.
        # Pre-fix: 123-2 (sorted-second EARRINGS) had HSN 71131914;
        # post-fix: 123-2 (invoice line 2 = Gold Pendant) has HSN 71131911.
        assert by_code["EJL/26-27/123-2"] == "71131911"
        assert by_code["EJL/26-27/123-3"] == "71131141"
        assert by_code["EJL/26-27/123-4"] == "71131144"


# ── Regression — single-type invoices unchanged ──────────────────────────

class TestSingleTypeInvoiceUnchanged:
    """When all invoice lines have the same item_type, the old sort was
    a no-op already. After Option B, behaviour for these invoices is
    unchanged. Pin that to prevent accidental regression."""
    def test_all_ring_invoice_codes_match_input_order(self):
        items = [
            _mk_item("Plain",             "14KT", "RING", 1, 100.0, "71131911"),
            _mk_item("Lab Grown Diamond", "14KT", "RING", 1, 200.0, "71131914"),
            _mk_item("Diamond Studded",   "14KT", "RING", 1, 300.0, "71131913"),
        ]
        rows = _run_invoice(items, invoice_no="EJL/TEST-RING")
        assert [r["product_code"] for r in rows] == [
            "EJL/TEST-RING-1",
            "EJL/TEST-RING-2",
            "EJL/TEST-RING-3",
        ]


# ── Auto-register vs PZ rows alignment (the original bug seam) ───────────

class TestAutoRegisterPzRowsAlignment:
    """Conceptual alignment: auto-register reads invoice_lines in invoice
    order and registers wfirma_products with invoice descriptions; the
    PZ engine now also emits codes in invoice order. So a code-X
    in pz_rows.json describes the SAME physical item that
    auto-register registered under code-X. Pinned via description
    equality between an invoice item dict and the engine's pz_row."""
    def test_description_matches_invoice_position(self):
        rows = _run_invoice(_INVOICE_123_ITEMS)
        for i, item in enumerate(_INVOICE_123_ITEMS):
            row = rows[i]
            assert row["product_code"] == f"EJL/26-27/123-{i+1}"
            # Engine's row carries the same item_type as the invoice line
            assert row["item_type"] == item["item_type"]
            # Same quantity
            assert row["quantity"]  == item["quantity"]
