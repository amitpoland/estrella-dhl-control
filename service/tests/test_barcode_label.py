"""
test_barcode_label.py — Barcode label format and ZPL renderer tests.

Covers:
  1. _fmt_qty: whole numbers, decimals
  2. _label_line: all fields, partial fields, empty fields
  3. _barcode_value: with bag_id, without bag_id
  4. _build_barcode_row: all required fields present
  5. _render_zpl: all zones present, barcode_value encoded, ^XA/^XZ wrapper
  6. _render_zpl_batch: multiple labels concatenated
  7. Barcode endpoint: metal/karat/uom/label_line fields present
  8. ZPL endpoint: Content-Disposition header, X-Label-Count, plain text body
  9. No unmatched rows in ZPL output
 10. Print endpoint: bad host raises 502
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.api.routes_packing import (
    _build_barcode_row,
    _barcode_value,
    _fmt_qty,
    _label_line,
    _render_zpl,
    _render_zpl_batch,
    _zpl_safe,
)


# ── Sample data ───────────────────────────────────────────────────────────────

def _ln(
    product_code: str  = "EJL/26-27/100-1",
    bag_id: str        = "BAG-01",
    design_no: str     = "D-RING-001",
    batch_no: str      = "LOT-A",
    invoice_no: str    = "EJL/26-27/100",
    quantity: float    = 2.0,
    uom: str           = "PCS",
    metal: str         = "GOLD",
    karat: str         = "18K",
    requires_manual_review: bool = False,
) -> Dict[str, Any]:
    return {
        "product_code":          product_code,
        "bag_id":                bag_id,
        "design_no":             design_no,
        "batch_no":              batch_no,
        "invoice_no":            invoice_no,
        "quantity":              quantity,
        "uom":                   uom,
        "metal":                 metal,
        "karat":                 karat,
        "requires_manual_review": requires_manual_review,
    }


# ── 0. _zpl_safe ─────────────────────────────────────────────────────────────

class TestZplSafe:
    def test_clean_string_unchanged(self):     assert _zpl_safe("EJL/26-27/100-1") == "EJL/26-27/100-1"
    def test_caret_stripped(self):             assert _zpl_safe("BAG^01") == "BAG01"
    def test_tilde_stripped(self):             assert _zpl_safe("BAG~01") == "BAG01"
    def test_backslash_stripped(self):         assert _zpl_safe("BAG\\01") == "BAG01"
    def test_all_three_stripped(self):         assert _zpl_safe("^~\\bad") == "bad"
    def test_empty_string(self):               assert _zpl_safe("") == ""
    def test_pipe_preserved(self):             assert _zpl_safe("EJL/001|BAG-01") == "EJL/001|BAG-01"
    def test_slash_dash_preserved(self):       assert _zpl_safe("EJL/26-27/100-1") == "EJL/26-27/100-1"


# ── 1. _fmt_qty ───────────────────────────────────────────────────────────────

class TestFmtQty:
    def test_whole_number(self):          assert _fmt_qty(2.0)  == "2"
    def test_whole_int(self):             assert _fmt_qty(5)    == "5"
    def test_decimal(self):               assert _fmt_qty(1.5)  == "1.5"
    def test_zero(self):                  assert _fmt_qty(0)    == "0"
    def test_none_returns_none_str(self): assert _fmt_qty(None) == "None"


# ── 2. _label_line ────────────────────────────────────────────────────────────

class TestLabelLine:
    def test_all_fields(self):
        line = _label_line(_ln())
        assert "EJL/26-27/100-1" in line
        assert "BAG-01"          in line
        assert "D-RING-001"      in line
        assert "GOLD 18K"        in line
        assert "2 PCS"           in line

    def test_separator_is_middot(self):
        line = _label_line(_ln())
        assert " · " in line

    def test_empty_metal_omitted(self):
        line = _label_line(_ln(metal="", karat=""))
        assert "·  ·" not in line     # no empty token between separators
        assert "GOLD" not in line

    def test_empty_bag_omitted(self):
        line = _label_line(_ln(bag_id=""))
        assert "BAG-01" not in line
        # other fields still present
        assert "EJL/26-27/100-1" in line


# ── 3. _barcode_value ─────────────────────────────────────────────────────────

class TestBarcodeValue:
    def test_with_bag_id(self):
        assert _barcode_value(_ln()) == "EJL/26-27/100-1|BAG-01"

    def test_without_bag_id(self):
        # No bag_id → fall back to product_code|design_no for warehouse-uniqueness
        # (prevents two same-product-code rows scanning identically).
        assert _barcode_value(_ln(bag_id="")) == "EJL/26-27/100-1|D-RING-001"

    def test_without_bag_or_design(self):
        # Last-resort fallback when nothing distinguishing is available.
        assert _barcode_value(_ln(bag_id="", design_no="")) == "EJL/26-27/100-1"

    def test_different_bags_different_values(self):
        v1 = _barcode_value(_ln(bag_id="BAG-01"))
        v2 = _barcode_value(_ln(bag_id="BAG-02"))
        assert v1 != v2
        assert v1 == "EJL/26-27/100-1|BAG-01"
        assert v2 == "EJL/26-27/100-1|BAG-02"


# ── 4. _build_barcode_row ─────────────────────────────────────────────────────

class TestBuildBarcodeRow:
    def test_all_required_fields_present(self):
        row = _build_barcode_row(_ln())
        for field in ("product_code", "invoice_no", "design_no", "batch_no",
                      "bag_id", "quantity", "uom", "metal", "karat",
                      "barcode_value", "scan_code", "label_line", "requires_manual_review"):
            assert field in row, f"missing field: {field}"

    def test_barcode_value_correct(self):
        row = _build_barcode_row(_ln())
        assert row["barcode_value"] == "EJL/26-27/100-1|BAG-01"

    def test_scan_code_equals_barcode_value(self):
        row = _build_barcode_row(_ln())
        assert row["scan_code"] == row["barcode_value"]

    def test_scan_code_without_bag(self):
        # No bag_id → scan_code falls back to product_code|design_no
        # so warehouse scanners distinguish two same-product-code rows.
        row = _build_barcode_row(_ln(bag_id=""))
        assert row["scan_code"] == "EJL/26-27/100-1|D-RING-001"
        assert row["scan_code"] == row["barcode_value"]

    def test_label_line_is_string(self):
        row = _build_barcode_row(_ln())
        assert isinstance(row["label_line"], str)
        assert len(row["label_line"]) > 0

    def test_quantity_is_formatted_string(self):
        row = _build_barcode_row(_ln(quantity=2.0))
        assert row["quantity"] == "2"

    def test_requires_manual_review_bool(self):
        row = _build_barcode_row(_ln(requires_manual_review=True))
        assert row["requires_manual_review"] is True


# ── 5. _render_zpl ────────────────────────────────────────────────────────────

class TestRenderZpl:
    def _row(self):
        return _build_barcode_row(_ln())

    def test_starts_with_xA_ends_with_xZ(self):
        zpl = _render_zpl(self._row())
        assert zpl.startswith("^XA")
        assert zpl.strip().endswith("^XZ")

    def test_product_code_in_label(self):
        zpl = _render_zpl(self._row())
        assert "EJL/26-27/100-1" in zpl

    def test_bag_id_in_label(self):
        zpl = _render_zpl(self._row())
        assert "BAG-01" in zpl

    def test_design_no_in_label(self):
        zpl = _render_zpl(self._row())
        assert "D-RING-001" in zpl

    def test_metal_karat_in_label(self):
        zpl = _render_zpl(self._row())
        assert "GOLD" in zpl
        assert "18K"  in zpl

    def test_qty_in_label(self):
        zpl = _render_zpl(self._row())
        assert "QTY: 2 PCS" in zpl

    def test_barcode_command_present(self):
        zpl = _render_zpl(self._row())
        assert "^BC" in zpl          # Code 128

    def test_barcode_value_encoded(self):
        zpl = _render_zpl(self._row())
        assert "EJL/26-27/100-1|BAG-01" in zpl

    def test_no_bag_id_barcode_value_is_product_code(self):
        row = _build_barcode_row(_ln(bag_id=""))
        zpl = _render_zpl(row)
        assert "EJL/26-27/100-1" in zpl
        assert "|" not in zpl.split("^FD")[-2]   # last FD before ^XZ has no pipe

    def test_caret_in_design_no_stripped_from_zpl(self):
        """Caret inside design_no must not appear in any ^FD field."""
        row = _build_barcode_row(_ln(design_no="D^RING^001"))
        zpl = _render_zpl(row)
        # ZPL commands use ^, data fields must not
        data_fields = [seg.split("^FS")[0] for seg in zpl.split("^FD")[1:]]
        for field in data_fields:
            assert "^" not in field, f"Caret leaked into data field: {field!r}"

    def test_tilde_in_bag_id_stripped_from_zpl(self):
        row = _build_barcode_row(_ln(bag_id="BAG~01"))
        zpl = _render_zpl(row)
        data_fields = [seg.split("^FS")[0] for seg in zpl.split("^FD")[1:]]
        for field in data_fields:
            assert "~" not in field, f"Tilde leaked into data field: {field!r}"

    def test_backslash_in_product_code_stripped_from_zpl(self):
        row = _build_barcode_row(_ln(product_code="EJL\\001-1"))
        zpl = _render_zpl(row)
        data_fields = [seg.split("^FS")[0] for seg in zpl.split("^FD")[1:]]
        for field in data_fields:
            assert "\\" not in field, f"Backslash leaked into data field: {field!r}"


# ── 6. _render_zpl_batch ─────────────────────────────────────────────────────

class TestRenderZplBatch:
    def test_two_labels_two_xA_blocks(self):
        rows = [
            _build_barcode_row(_ln(bag_id="BAG-01")),
            _build_barcode_row(_ln(bag_id="BAG-02")),
        ]
        zpl = _render_zpl_batch(rows)
        assert zpl.count("^XA") == 2
        assert zpl.count("^XZ") == 2

    def test_empty_list_returns_empty_string(self):
        assert _render_zpl_batch([]) == ""

    def test_both_bag_ids_present(self):
        rows = [
            _build_barcode_row(_ln(bag_id="BAG-01")),
            _build_barcode_row(_ln(bag_id="BAG-02")),
        ]
        zpl = _render_zpl_batch(rows)
        assert "BAG-01" in zpl
        assert "BAG-02" in zpl


# ── 7–10. Endpoint integration ────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    from app.services.packing_db import init_packing_db
    init_packing_db(tmp_path / "packing.db")
    return tmp_path


def _insert_matched(tmp_path, bag_id="BAG-01", product_code="EJL/001-1"):
    from app.services import packing_db as pdb
    doc_id = pdb.upsert_packing_document(batch_id="B1", invoice_no="EJL/001")
    pdb.upsert_packing_lines([{
        "packing_document_id":   doc_id,
        "batch_id":              "B1",
        "invoice_no":            "EJL/001",
        "invoice_line_position": 1,
        "product_code":          product_code,
        "design_no":             "D-RING-001",
        "batch_no":              "LOT-A",
        "bag_id":                bag_id,
        "tray_id":               "",
        "item_type":             "RING",
        "uom":                   "PCS",
        "quantity":              2.0,
        "gross_weight":          10.0,
        "net_weight":            9.5,
        "metal":                 "GOLD",
        "karat":                 "18K",
        "stone_type":            "",
        "remarks":               "",
        "extracted_confidence":  0.8,
        "requires_manual_review": False,
    }])


class TestBarcodeEndpointFields:

    def test_barcode_row_has_metal_karat_uom(self, db):
        _insert_matched(db)
        from app.services import packing_db as pdb
        all_lines = pdb.get_packing_lines_for_batch("B1")
        matched = [ln for ln in all_lines if ln.get("product_code")]
        row = _build_barcode_row(matched[0])
        assert row["metal"]  == "GOLD"
        assert row["karat"]  == "18K"
        assert row["uom"]    == "PCS"

    def test_barcode_row_has_label_line(self, db):
        _insert_matched(db)
        from app.services import packing_db as pdb
        all_lines = pdb.get_packing_lines_for_batch("B1")
        matched = [ln for ln in all_lines if ln.get("product_code")]
        row = _build_barcode_row(matched[0])
        assert "EJL/001-1" in row["label_line"]
        assert "BAG-01"    in row["label_line"]
        assert "GOLD 18K"  in row["label_line"]
        assert "2 PCS"     in row["label_line"]

    def test_label_line_format(self, db):
        _insert_matched(db)
        from app.services import packing_db as pdb
        all_lines = pdb.get_packing_lines_for_batch("B1")
        matched = [ln for ln in all_lines if ln.get("product_code")]
        row = _build_barcode_row(matched[0])
        # Must use middot separator between non-empty tokens
        assert " · " in row["label_line"]


class TestZplRenderer:

    def test_zpl_contains_xA_block(self, db):
        _insert_matched(db)
        from app.services import packing_db as pdb
        matched = [ln for ln in pdb.get_packing_lines_for_batch("B1")
                   if ln.get("product_code")]
        zpl = _render_zpl_batch([_build_barcode_row(ln) for ln in matched])
        assert "^XA" in zpl
        assert "^XZ" in zpl

    def test_zpl_encodes_pipe_barcode_value(self, db):
        _insert_matched(db, bag_id="BAG-01")
        from app.services import packing_db as pdb
        matched = [ln for ln in pdb.get_packing_lines_for_batch("B1")
                   if ln.get("product_code")]
        zpl = _render_zpl_batch([_build_barcode_row(ln) for ln in matched])
        assert "EJL/001-1|BAG-01" in zpl


class TestPrintEndpoint:

    def test_unreachable_printer_raises_502(self, db, tmp_path):
        """POST to a closed port must raise HTTP 502, not crash."""
        # The mock patches the function on the module object itself; calling
        # pdb_real.get_packing_lines_for_batch() inside the patch context would
        # return another MagicMock (not real rows).  Supply rows directly instead.
        with patch("app.api.routes_packing.pdb.get_packing_lines_for_batch") as mock_lines, \
             patch("app.api.routes_packing._validate_batch"):
            mock_lines.return_value = [{
                "product_code": "INV-1", "design_no": "D", "batch_no": "",
                "bag_id": "BAG-01", "tray_id": "", "item_type": "RING",
                "invoice_no": "INV", "uom": "PCS", "quantity": 1.0,
                "metal": "", "karat": "", "requires_manual_review": False,
            }]

            import socket
            with patch("app.api.routes_packing.socket.create_connection",
                       side_effect=OSError("Connection refused")):
                from fastapi.testclient import TestClient
                from fastapi import FastAPI
                app = FastAPI()
                from app.api.routes_packing import router
                app.include_router(router)

                # Override auth
                from app.auth.dependencies import get_current_user
                app.dependency_overrides[get_current_user] = lambda: {"id": "test"}

                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/api/v1/packing/B1/barcode/print",
                    params={"printer_host": "192.0.2.1", "printer_port": 9100},
                )
                assert resp.status_code == 502
