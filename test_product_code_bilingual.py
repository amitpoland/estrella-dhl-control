#!/usr/bin/env python3
"""
test_product_code_bilingual.py
==============================
Tests for the 2026-05 PZ row schema update:
  - stable product_code = invoice_no + "-" + line_position (1-indexed)
  - bilingual nazwa = "<Polish> / <English>"
  - product_code uniqueness within batch
  - freight allocation untouched (per-invoice, by value)

Reference batch: SHIPMENT_2824221912_2026-04 (3 invoices, 7 lines):
  EJL/25-26/1247  → 1 line  (-1)
  EJL/25-26/1248  → 4 lines (-1..-4)
  EJL/25-26/1249  → 2 lines (-1..-2)

Run directly:  python3 test_product_code_bilingual.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pz_import_processor import (  # noqa: E402
    build_en_name, build_pl_name, get_full_nazwa, calculate_landed,
)


def _mk_item(family: str, karat: str, item_type: str, qty: int, total_usd: float, hsn: str = "71131900"):
    return {
        "description_en": build_en_name({"family": family, "karat": karat, "item_type": item_type}),
        "pl_desc":        build_pl_name({"family": family, "karat": karat, "item_type": item_type}),
        "item_type":      item_type,
        "family":         family,
        "karat":          karat,
        "hsn":            hsn,
        "quantity":       qty,
        "unit":           "PCS",
        "unit_price_usd": round(total_usd / qty, 2),
        "total_usd":      total_usd,
        "gross_weight":   0.0,
        "net_weight":     0.0,
    }


def _batch_2824221912_invoices():
    """Recreate the invoice/item structure of SHIPMENT_2824221912_2026-04."""
    return [
        {
            "invoice_no": "EJL/25-26/1247",
            "invoice_date": "09-03-2026",
            "filename":   "1247 Invoice.pdf",
            "fob_usd":    626.0, "freight_usd": 15.0, "insurance_usd": 10.0,
            "cif_usd":    651.0,
            "buyer_name": "ESTRELLA JEWELS SP Z O O", "buyer_nip": "5252812119",
            "exporter_name": "Estrella Jewels LLP",
            "items": [
                _mk_item("Plain", "9KT", "RING", 2, 626.0, "71131911"),
            ],
        },
        {
            "invoice_no": "EJL/25-26/1248",
            "invoice_date": "09-03-2026",
            "filename":   "1248 Invoice.pdf",
            "fob_usd":   12318.0, "freight_usd": 15.0, "insurance_usd": 10.0,
            "cif_usd":   12343.0,
            "buyer_name": "ESTRELLA JEWELS SP Z O O", "buyer_nip": "5252812119",
            "exporter_name": "Estrella Jewels LLP",
            "items": [
                _mk_item("Diamond / Colour Stone Studded", "14KT", "RING",      5, 3082.0, "71131913"),
                _mk_item("Diamond Studded",                "14KT", "RING",      6, 2351.0, "71131913"),
                _mk_item("Diamond / Colour Stone Studded", "14KT", "EARRINGS", 10, 3429.0, "71131919"),
                _mk_item("Diamond Studded",                "14KT", "EARRINGS",  6, 3456.0, "71131919"),
            ],
        },
        {
            "invoice_no": "EJL/25-26/1249",
            "invoice_date": "09-03-2026",
            "filename":   "1249 Invoice.pdf",
            "fob_usd":    1150.0, "freight_usd": 15.0, "insurance_usd": 10.0,
            "cif_usd":    1175.0,
            "buyer_name": "ESTRELLA JEWELS SP Z O O", "buyer_nip": "5252812119",
            "exporter_name": "Estrella Jewels LLP",
            "items": [
                _mk_item("Lab Grown Diamond", "14KT", "RING", 2, 588.0, "71131913"),
                _mk_item("Lab Grown Diamond", "18KT", "RING", 1, 562.0, "71131913"),
            ],
        },
    ]


def _build_rows():
    invoices = _batch_2824221912_invoices()
    zc429 = {"duty_pln": 1261.0, "total_cif_usd": 14169.0, "lrn": "26S00OGP0S"}
    nbp   = {"usd_rate": 3.6962}
    rows, _totals = calculate_landed(invoices, zc429, nbp, corrections_log=[])
    return invoices, rows


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestBilingualNaming(unittest.TestCase):
    def test_get_full_nazwa_uses_slash_separator(self):
        item = {"family": "Plain", "karat": "9KT", "item_type": "RING"}
        n = get_full_nazwa(item)
        self.assertIn(" / ", n)
        # Polish must come first, English after
        pl = build_pl_name(item)
        en = build_en_name(item)
        self.assertTrue(n.startswith(pl))
        self.assertTrue(n.endswith(en))

    def test_every_row_has_bilingual_name(self):
        _, rows = _build_rows()
        self.assertEqual(len(rows), 7)
        for r in rows:
            self.assertIn("nazwa",    r)
            self.assertIn("nazwa_pl", r)
            self.assertIn("nazwa_en", r)
            self.assertIn(" / ",      r["nazwa"])
            self.assertTrue(r["nazwa"].startswith(r["nazwa_pl"]))
            self.assertTrue(r["nazwa"].endswith(r["nazwa_en"]))


class TestProductCodeBatch2824221912(unittest.TestCase):
    def setUp(self):
        self.invoices, self.rows = _build_rows()

    def test_invoice_1247_has_one_code(self):
        codes = [r["product_code"] for r in self.rows if r["invoice_no"] == "EJL/25-26/1247"]
        self.assertEqual(codes, ["EJL/25-26/1247-1"])

    def test_invoice_1248_has_four_codes(self):
        codes = [r["product_code"] for r in self.rows if r["invoice_no"] == "EJL/25-26/1248"]
        self.assertEqual(codes, [
            "EJL/25-26/1248-1", "EJL/25-26/1248-2",
            "EJL/25-26/1248-3", "EJL/25-26/1248-4",
        ])

    def test_invoice_1249_has_two_codes(self):
        codes = [r["product_code"] for r in self.rows if r["invoice_no"] == "EJL/25-26/1249"]
        self.assertEqual(codes, ["EJL/25-26/1249-1", "EJL/25-26/1249-2"])

    def test_all_codes_unique_within_batch(self):
        codes = [r["product_code"] for r in self.rows]
        self.assertEqual(len(codes), len(set(codes)))

    def test_codes_are_deterministic_on_re_run(self):
        codes_1 = [r["product_code"] for r in self.rows]
        _, rows2 = _build_rows()
        codes_2 = [r["product_code"] for r in rows2]
        self.assertEqual(codes_1, codes_2)

    def test_line_position_resets_per_invoice(self):
        """Even though invoice 1248 follows 1247 globally, its first line is -1."""
        first_1248 = next(r for r in self.rows if r["invoice_no"] == "EJL/25-26/1248")
        self.assertEqual(first_1248["line_position"], 1)
        self.assertEqual(first_1248["product_code"], "EJL/25-26/1248-1")


class TestFreightAllocationUnchanged(unittest.TestCase):
    """User constraint: per-invoice freight allocation must not become global."""

    def test_freight_rate_is_per_invoice(self):
        invoices, rows = _build_rows()
        # Each invoice has its own freight rate; rates should differ across invoices.
        rate_by_invoice = {}
        for r in rows:
            rate_by_invoice.setdefault(r["invoice_no"], r["freight_rate_pct"])
        # 3 distinct invoices → at least 2 distinct freight rates
        self.assertGreaterEqual(len(set(rate_by_invoice.values())), 2)

    def test_total_freight_pln_allocated_within_invoice(self):
        invoices, rows = _build_rows()
        # Sum of allocated_ship_usd per invoice must equal that invoice's
        # freight + insurance — proves no cross-invoice leakage.
        for inv in invoices:
            inv_lines     = [r for r in rows if r["invoice_no"] == inv["invoice_no"]]
            allocated_usd = round(sum(r["allocated_ship_usd"] for r in inv_lines), 2)
            expected      = round(inv["freight_usd"] + inv["insurance_usd"], 2)
            self.assertAlmostEqual(allocated_usd, expected, places=1,
                                    msg=f"Invoice {inv['invoice_no']} freight leaked")


class TestProductCodeNotBasedOnTranslation(unittest.TestCase):
    """Codes must be invoice-derived, never translation-derived."""

    def test_code_does_not_change_when_polish_name_changes(self):
        invoices = _batch_2824221912_invoices()
        # Mutate Polish description; product_code must stay the same.
        invoices[0]["items"][0]["pl_desc"] = "ZUPEŁNIE INNA NAZWA"
        zc429 = {"duty_pln": 1261.0, "total_cif_usd": 14169.0, "lrn": "X"}
        nbp   = {"usd_rate": 3.6962}
        rows, _t = calculate_landed(invoices, zc429, nbp, corrections_log=[])
        first = next(r for r in rows if r["invoice_no"] == "EJL/25-26/1247")
        self.assertEqual(first["product_code"], "EJL/25-26/1247-1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
