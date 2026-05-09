#!/usr/bin/env python3
"""
test_global_invoice_weight_row_parser.py
========================================
Regression test for the Global Jewellery invoice variant where item rows
omit the per-line HSN/unit and instead carry only weights:

    Pendant 2.687 2.860 4.0 20.50 82.00
    Ring    21.828 23.220 10.0 54.20 542.00

Triggered by SHIPMENT_8722845401 — the previous parser returned 0 items
which made `calculate_landed` raise "Total before-duty PLN is zero".
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

INV_PATH = (
    "/Users/amitgupta/Library/Application Support/estrellajewels/"
    "storage/outputs/SHIPMENT_8722845401_2026-04_7c87b9f3/"
    "source/invoices/417 Global Invoice-2.pdf"
)


@unittest.skipUnless(Path(INV_PATH).exists(),
                     f"reference invoice not present at {INV_PATH}")
class TestGlobalInvoiceWeightRow(unittest.TestCase):
    def setUp(self):
        from pz_import_processor import parse_invoice
        self.log: list = []
        self.inv = parse_invoice(INV_PATH, self.log)

    def test_invoice_format_detected(self):
        self.assertEqual(self.inv.get("invoice_format"), "global_jewellery")

    def test_items_parsed_from_weight_rows(self):
        # The previous parser returned 0; fix raises this above 10.
        self.assertGreater(len(self.inv.get("items", [])), 10,
                           "weight-row variant must produce item lines")

    def test_fob_above_zero(self):
        self.assertGreater(self.inv.get("fob_usd", 0), 0)

    def test_cif_above_fob(self):
        cif = self.inv.get("cif_usd") or 0
        fob = self.inv.get("fob_usd") or 0
        self.assertGreaterEqual(cif, fob - 0.01)

    def test_each_item_has_required_fields(self):
        required = ("item_type", "quantity", "unit_price_usd", "total_usd")
        for it in self.inv.get("items", []):
            for k in required:
                self.assertIn(k, it, f"item missing {k}: {it}")
            self.assertGreater(it["quantity"], 0)
            self.assertGreater(it["total_usd"], 0)

    def test_total_of_line_amounts_matches_fob_within_tolerance(self):
        """Sum of line amounts should equal FOB ± a few dollars (rounding)."""
        line_sum = sum(it.get("total_usd", 0) for it in self.inv.get("items", []))
        fob      = self.inv.get("fob_usd") or 0
        # Allow up to $5 drift for rounding/missed sub-rows
        self.assertLessEqual(abs(line_sum - fob), 5.0,
                             f"line_sum={line_sum} fob={fob}")


# ── Polish desc auto-resolve ──────────────────────────────────────────────────

class TestPolishDescAutoResolve(unittest.TestCase):
    """Stored polish_desc_filename may point at a stale file. Auto-resolve
    must return the newest matching file in <storage_root>/polish_descriptions/.
    """

    def test_resolves_to_newest_when_stored_missing(self):
        import tempfile, time, sys
        sys.path.insert(0, str(Path(__file__).resolve().parent / "service"))
        from app.services.batch_state_normalizer import resolve_polish_desc_filename
        from app.core import config as cfg

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "polish_descriptions").mkdir()
            old = tmp_path / "polish_descriptions" / "POLISH_DESC_AWB_111_OLD.pdf"
            new = tmp_path / "polish_descriptions" / "POLISH_DESC_AWB_111_NEW.pdf"
            old.write_bytes(b"%PDF-1.4 old")
            time.sleep(0.05)
            new.write_bytes(b"%PDF-1.4 new")

            # Repoint settings.storage_root for this test
            orig = cfg.settings.storage_root
            try:
                cfg.settings.storage_root = tmp_path
                resolved = resolve_polish_desc_filename(
                    batch_dir = tmp_path / "batch",   # doesn't exist on disk
                    awb       = "111",
                    stored_fname = "POLISH_DESC_AWB_111_GONE.pdf",  # missing
                )
                self.assertEqual(resolved, "POLISH_DESC_AWB_111_NEW.pdf")
            finally:
                cfg.settings.storage_root = orig

    def test_keeps_stored_when_file_exists(self):
        import tempfile, sys
        sys.path.insert(0, str(Path(__file__).resolve().parent / "service"))
        from app.services.batch_state_normalizer import resolve_polish_desc_filename
        from app.core import config as cfg

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pd_dir = tmp_path / "polish_descriptions"
            pd_dir.mkdir()
            (pd_dir / "POLISH_DESC_AWB_222_KEEP.pdf").write_bytes(b"%PDF-1.4")

            orig = cfg.settings.storage_root
            try:
                cfg.settings.storage_root = tmp_path
                resolved = resolve_polish_desc_filename(
                    batch_dir = tmp_path / "batch",
                    awb       = "222",
                    stored_fname = "POLISH_DESC_AWB_222_KEEP.pdf",
                )
                self.assertEqual(resolved, "POLISH_DESC_AWB_222_KEEP.pdf")
            finally:
                cfg.settings.storage_root = orig

    def test_returns_stored_when_no_awb_match(self):
        import tempfile, sys
        sys.path.insert(0, str(Path(__file__).resolve().parent / "service"))
        from app.services.batch_state_normalizer import resolve_polish_desc_filename
        from app.core import config as cfg

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "polish_descriptions").mkdir()
            (tmp_path / "polish_descriptions" / "POLISH_DESC_AWB_999_X.pdf").write_bytes(b"%PDF-1.4")

            orig = cfg.settings.storage_root
            try:
                cfg.settings.storage_root = tmp_path
                resolved = resolve_polish_desc_filename(
                    batch_dir = tmp_path / "batch",
                    awb       = "111",   # different AWB
                    stored_fname = "OLD_NAME.pdf",
                )
                self.assertEqual(resolved, "OLD_NAME.pdf")
            finally:
                cfg.settings.storage_root = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
