"""
test_global_supplier_regression.py — Regression: EJL paths unchanged when Global supplier absent.

These tests verify that:
1. supplier_detect returns None for EJL text
2. supplier_detect returns "global_jewellery" for Global text
3. EJL packing extractor returns non-global parser_name for EJL fixtures
4. EJL invoice parser path is not affected by supplier detection import
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── supplier_detect regression ────────────────────────────────────────────────

class TestSupplierDetectRegression:
    def test_ejl_text_returns_none(self):
        from app.services.supplier_detect import detect_supplier
        ejl_text = "EJL/26-27/100 Invoice ESTRELLA JEWELS LIMITED Mumbai"
        assert detect_supplier(ejl_text) is None

    def test_empty_text_returns_none(self):
        from app.services.supplier_detect import detect_supplier
        assert detect_supplier("") is None

    def test_none_returns_none(self):
        from app.services.supplier_detect import detect_supplier
        assert detect_supplier(None) is None

    def test_global_returns_code(self):
        from app.services.supplier_detect import detect_supplier
        assert detect_supplier("Global Jewellery Pvt. Ltd.") == "global_jewellery"

    def test_global_pvt_no_dot(self):
        from app.services.supplier_detect import detect_supplier
        assert detect_supplier("Global Jewellery Pvt Ltd") == "global_jewellery"

    def test_partial_match_no_false_positive(self):
        from app.services.supplier_detect import detect_supplier
        # "Global" alone should NOT match
        assert detect_supplier("Global Trading Co.") is None

    def test_jewellery_alone_no_false_positive(self):
        from app.services.supplier_detect import detect_supplier
        assert detect_supplier("Jewellery Pvt Ltd") is None


# ── EJL packing extractor regression ─────────────────────────────────────────

class TestEJLPackingExtractorUnchanged:
    def test_ejl_xlsx_uses_default_parser(self, tmp_path):
        """An EJL-format XLSX must NOT trigger the Global path."""
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        # EJL preamble — no Global Jewellery text
        ws.append(["ESTRELLA JEWELS LIMITED"])
        ws.append(["Invoice: EJL/26-27/100"])
        ws.append([])
        # EJL-style header
        ws.append(["Sr", "Design No.", "Kt/Color", "Qty", "Gross Wt", "Net Wt", "Value"])
        ws.append([1, "EJL-001", "18KT/W", 2, 5.0, 4.5, 200.0])
        path = tmp_path / "ejl_packing.xlsx"
        wb.save(str(path))

        from app.services.invoice_packing_extractor import extract_packing
        rows, parser_name, parser_version, diag = extract_packing(path)

        # Must NOT be global parser
        assert parser_name != "global_packing_v1"
        assert diag.get("supplier") != "global_jewellery"

    def test_global_xlsx_uses_global_parser(self, tmp_path):
        """A Global Jewellery XLSX must trigger the Global path."""
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Global Jewellery Pvt. Ltd."])
        ws.append(["Invoice No.: 088/2026-2027"])
        ws.append([])
        ws.append(["Sr", "Type", "Style No.", "Metal", "Qty", "Gross Wt", "Net Wt", "FOB Value"])
        ws.append([1, "Bracelet", "JBR00377", "9", 1, 3.420, 3.178, 232.00])
        path = tmp_path / "global_packing.xlsx"
        wb.save(str(path))

        from app.services.invoice_packing_extractor import extract_packing
        rows, parser_name, parser_version, diag = extract_packing(path)

        assert parser_name == "global_packing_v1"
        assert diag.get("supplier") == "global_jewellery"
        assert len(rows) == 1


# ── safe_float regression ─────────────────────────────────────────────────────

class TestSafeFloatInExtractor:
    def test_safe_float_is_importable(self):
        from app.services.invoice_packing_extractor import _safe_float
        assert callable(_safe_float)

    def test_safe_float_ite_1(self):
        from app.services.invoice_packing_extractor import _safe_float
        assert _safe_float("ite 1") == 0.0

    def test_safe_float_numeric(self):
        from app.services.invoice_packing_extractor import _safe_float
        assert _safe_float("3.420") == pytest.approx(3.420)

    def test_safe_float_none(self):
        from app.services.invoice_packing_extractor import _safe_float
        assert _safe_float(None) == 0.0


# ── description_engine regression ────────────────────────────────────────────

class TestDescriptionEngineNewFunction:
    def test_function_is_importable(self):
        from app.services.description_engine import regenerate_descriptions_for_packing_lines
        assert callable(regenerate_descriptions_for_packing_lines)

    def test_dry_run_default(self):
        """dry_run=True by default — should not write anything."""
        from app.services.description_engine import regenerate_descriptions_for_packing_lines
        result = regenerate_descriptions_for_packing_lines(batch_id="NONEXISTENT_BATCH")
        # No packing lines → scanned=0, written=0
        assert result["dry_run"] is True
        assert result["written"] == 0
        assert "errors" in result

    def test_existing_function_still_importable(self):
        """Ensure the original EJL function still exists and is callable."""
        from app.services.description_engine import regenerate_descriptions_for_invoice_lines
        assert callable(regenerate_descriptions_for_invoice_lines)
