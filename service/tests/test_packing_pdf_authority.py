"""
Packing Authority Restoration — PDF extraction convergence.

Synthetic-fixture regression proving the PDF packing extractor resolves into the
SAME canonical row-validity + normalisation contract as the Excel path. The real
acceptance batch (18-07-26.zip / invoices 427 & 428) is NOT available, so these
fixtures model the EJL PDF structure (title/preamble rows before the real header)
rather than assert real-batch piece counts. Real 427/428 acceptance and true EJL
PDF-layout convergence remain UNVERIFIED follow-up evidence.

Frozen root cause exercised: the PDF path used to treat the first table row as the
header and emit empty/degenerate mappings as extracted rows. After the repair it
discovers the real header, applies the shared validity contract, and never emits
or counts an empty mapping.
"""
import openpyxl
import pdfplumber
import pytest

from app.services import invoice_packing_extractor as ipe
from app.services.invoice_packing_extractor import (
    _extract_packing_pdf,
    _invoice_no_from_preamble,
    _validate_and_normalise_row,
    extract_packing,
)


# ── Fake pdfplumber so tests never touch a real PDF binary ───────────────────
class _FakePage:
    def __init__(self, tables):
        self._tables = tables

    def extract_tables(self):
        return self._tables

    def extract_text(self):
        # Non-EJL-supplier text so supplier routing stays on the EJL path.
        return ""


class _FakePDF:
    def __init__(self, pages):
        self._pages = [_FakePage(tables) for tables in pages]

    @property
    def pages(self):
        return self._pages

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_pdf(monkeypatch, pages):
    """pages = list-per-page of list-of-tables of rows."""
    monkeypatch.setattr(pdfplumber, "open", lambda *a, **k: _FakePDF(pages))


def _pdf_path(tmp_path):
    p = tmp_path / "packing.pdf"
    p.write_bytes(b"%PDF-1.4 synthetic")
    return p


# ── Root-cause repair: title row skipped, real header found ──────────────────
def test_title_row_skipped_real_header_found(tmp_path, monkeypatch):
    pages = [[[
        ["SHIPMENT PACKING LIST", "", "", ""],
        ["", "", "", ""],
        ["PkSr", "DesignNo", "Kt/Color", "Qty"],
        ["1", "D-001", "18KT/Y", "2"],
    ]]]
    _patch_pdf(monkeypatch, pages)
    rows = _extract_packing_pdf(_pdf_path(tmp_path))
    assert len(rows) == 1
    r = rows[0]
    assert r["design_no"] == "D-001"
    assert r["line_position"] == "1"          # PkSr → line_position → pack_sr
    assert r["metal"] == "18KT/Y"
    assert r["metal_color"] == "Y"
    assert r["karat"] == "18KT"


def test_empty_mapping_never_emitted(tmp_path, monkeypatch):
    # Header found, but the only data rows are empty / non-numeric-qty → nothing
    # may be emitted. Reproduces the empty-dict-as-row defect.
    pages = [[[
        ["PkSr", "DesignNo", "Kt/Color", "Qty"],
        ["", "", "", ""],
        ["9", "D-777", "14KT", ""],           # design present, qty missing
    ]]]
    _patch_pdf(monkeypatch, pages)
    rows = _extract_packing_pdf(_pdf_path(tmp_path))
    assert rows == []


def test_subtotal_row_excluded(tmp_path, monkeypatch):
    pages = [[[
        ["PkSr", "DesignNo", "Kt/Color", "Qty"],
        ["1", "D-001", "18KT/Y", "2"],
        ["Grand Total", "", "", "2"],
    ]]]
    _patch_pdf(monkeypatch, pages)
    rows = _extract_packing_pdf(_pdf_path(tmp_path))
    assert len(rows) == 1
    assert rows[0]["design_no"] == "D-001"


def test_non_numeric_quantity_excluded(tmp_path, monkeypatch):
    pages = [[[
        ["PkSr", "DesignNo", "Kt/Color", "Qty"],
        ["1", "D-001", "18KT/Y", "n/a"],
    ]]]
    _patch_pdf(monkeypatch, pages)
    assert _extract_packing_pdf(_pdf_path(tmp_path)) == []


def test_multipage_data_rows_collected(tmp_path, monkeypatch):
    # Header on page 1; data continues on page 2 with no repeated header.
    pages = [
        [[["PkSr", "DesignNo", "Kt/Color", "Qty"], ["1", "D-001", "18KT/Y", "2"]]],
        [[["2", "D-002", "14KT/W", "3"]]],
    ]
    _patch_pdf(monkeypatch, pages)
    rows = _extract_packing_pdf(_pdf_path(tmp_path))
    assert [r["design_no"] for r in rows] == ["D-001", "D-002"]


def test_repeated_header_on_later_page_self_drops(tmp_path, monkeypatch):
    pages = [
        [[["PkSr", "DesignNo", "Kt/Color", "Qty"], ["1", "D-001", "18KT/Y", "2"]]],
        [[["PkSr", "DesignNo", "Kt/Color", "Qty"], ["2", "D-002", "14KT/W", "3"]]],
    ]
    _patch_pdf(monkeypatch, pages)
    rows = _extract_packing_pdf(_pdf_path(tmp_path))
    # The repeated header row has non-numeric "Qty" → dropped by the shared gate.
    assert [r["design_no"] for r in rows] == ["D-001", "D-002"]


# ── PDF ↔ Excel canonical parity (same logical document, both formats) ───────
def _build_parity_xlsx(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Invoice #", "EJL/26-27/013"])
    ws.append([])
    ws.append(["PkSr", "DesignNo", "Kt/Color", "Qty"])
    ws.append(["1", "D-001", "18KT/Y", 2])
    wb.save(str(path))


def test_pdf_excel_canonical_field_parity(tmp_path, monkeypatch):
    xlsx = tmp_path / "packing.xlsx"
    _build_parity_xlsx(xlsx)
    excel_rows = ipe._extract_packing_excel(xlsx, engine="openpyxl")
    assert len(excel_rows) == 1
    er = excel_rows[0]

    pages = [[[
        ["Invoice #", "EJL/26-27/013", "", ""],
        ["PkSr", "DesignNo", "Kt/Color", "Qty"],
        ["1", "D-001", "18KT/Y", "2"],
    ]]]
    _patch_pdf(monkeypatch, pages)
    pdf_rows = _extract_packing_pdf(_pdf_path(tmp_path))
    assert len(pdf_rows) == 1
    pr = pdf_rows[0]

    # Identity + normalised fields must be identical across formats.
    for field in ("design_no", "metal", "metal_color", "karat",
                  "line_position", "invoice_no"):
        assert str(pr.get(field)) == str(er.get(field)), field
    # Quantity numerically equal (Excel keeps native int, PDF keeps string).
    assert float(pr["quantity"]) == float(er["quantity"])
    # The serial that routes stamp into the dedup key is present in both.
    assert pr["line_position"] == "1" and str(er["line_position"]) == "1"


# ── Failure-classification parity via the dispatcher ─────────────────────────
def test_failure_reason_header_not_detected(tmp_path, monkeypatch):
    pages = [[[
        ["SHIPMENT PACKING LIST", ""],
        ["some", "freetext"],
    ]]]
    _patch_pdf(monkeypatch, pages)
    rows, _name, _ver, diag = extract_packing(_pdf_path(tmp_path))
    assert rows == []
    assert diag["failure_reason"] == "header_not_detected"


def test_failure_reason_empty_sheet(tmp_path, monkeypatch):
    # Real header present, but every data row is dropped → "empty_sheet", NOT
    # "header_not_detected".
    pages = [[[
        ["PkSr", "DesignNo", "Kt/Color", "Qty"],
        ["Grand Total", "", "", "5"],
        ["1", "D-001", "18KT", "x"],
    ]]]
    _patch_pdf(monkeypatch, pages)
    rows, _name, _ver, diag = extract_packing(_pdf_path(tmp_path))
    assert rows == []
    assert diag["failure_reason"] == "empty_sheet"


# ── Shared-helper unit tests ─────────────────────────────────────────────────
def test_validate_row_drops_non_numeric_quantity():
    assert _validate_and_normalise_row({"quantity": "abc", "design_no": "D"}) is None


def test_validate_row_drops_missing_identity():
    assert _validate_and_normalise_row({"quantity": "2"}) is None


def test_validate_row_stamps_invoice_hint_when_absent():
    out = _validate_and_normalise_row(
        {"quantity": "2", "design_no": "D"}, invoice_no_hint="EJL/26-27/013")
    assert out["invoice_no"] == "EJL/26-27/013"


def test_validate_row_hint_never_overwrites_existing_invoice():
    out = _validate_and_normalise_row(
        {"quantity": "2", "design_no": "D", "invoice_no": "REAL"},
        invoice_no_hint="HINT")
    assert out["invoice_no"] == "REAL"


def test_validate_row_metal_color_split_and_karat():
    out = _validate_and_normalise_row(
        {"quantity": "1", "design_no": "D", "metal": "14KT/W"})
    assert out["metal"] == "14KT/W"
    assert out["metal_color"] == "W"
    assert out["karat"] == "14KT"


def test_invoice_preamble_form_a():
    rows = [["Invoice #", "EJL/26-27/013"], ["PkSr", "Qty"]]
    assert _invoice_no_from_preamble(rows) == "EJL/26-27/013"


def test_invoice_preamble_form_b():
    rows = [["Export No : EJL/26-27/015"], ["PkSr", "Qty"]]
    assert _invoice_no_from_preamble(rows) == "EJL/26-27/015"


def test_invoice_preamble_none_when_absent():
    assert _invoice_no_from_preamble([["PkSr", "Qty"], ["1", "2"]]) == ""


# ── Full-chain + boundary coverage (GATE-1 test-coverage findings) ───────────
def test_full_repair_chain_with_preamble_offset(tmp_path, monkeypatch):
    # Header is NOT at row 0 (title + preamble first), AND subtotal + non-numeric
    # rows are interleaved — exercises header-discovery AND every validity gate
    # together, so a partial reversion of either half is caught.
    pages = [[[
        ["SHIPMENT PACKING LIST", "", "", ""],
        ["Invoice #", "EJL/26-27/013", "", ""],
        ["", "", "", ""],
        ["PkSr", "DesignNo", "Kt/Color", "Qty"],
        ["1", "D-001", "18KT/Y", "2"],
        ["Grand Total", "", "", "2"],          # subtotal → excluded
        ["frt", "", "", "n/a"],                # footer, non-numeric qty → excluded
    ]]]
    _patch_pdf(monkeypatch, pages)
    rows = _extract_packing_pdf(_pdf_path(tmp_path))
    assert len(rows) == 1
    assert rows[0]["design_no"] == "D-001"
    assert rows[0]["invoice_no"] == "EJL/26-27/013"   # stamped from preamble


def test_multi_table_single_page_concatenation(tmp_path, monkeypatch):
    # Preamble in one table, header+data in a second table on the SAME page.
    pages = [[
        [["Invoice #", "EJL/26-27/013"]],
        [["PkSr", "DesignNo", "Kt/Color", "Qty"], ["1", "D-001", "18KT/Y", "2"]],
    ]]
    _patch_pdf(monkeypatch, pages)
    rows = _extract_packing_pdf(_pdf_path(tmp_path))
    assert len(rows) == 1
    assert rows[0]["design_no"] == "D-001"
    assert rows[0]["invoice_no"] == "EJL/26-27/013"


def test_header_qty_without_design_not_detected(tmp_path, monkeypatch):
    # qty column present but NO design/category alias → no header → no rows.
    pages = [[[
        ["Sr", "Qty", "Metal", "Size"],
        ["1", "2", "18KT", "6.5"],
    ]]]
    _patch_pdf(monkeypatch, pages)
    assert _extract_packing_pdf(_pdf_path(tmp_path)) == []


def _filler(n):
    return [["info %d" % i, "", "", ""] for i in range(n)]


def test_header_at_scan_window_boundary_found(tmp_path, monkeypatch):
    # Header at index 24 (24 preamble rows) — last position inside the 25-row
    # scan window; must still be found.
    table = _filler(24) + [
        ["PkSr", "DesignNo", "Kt/Color", "Qty"],
        ["1", "D-001", "18KT/Y", "2"],
    ]
    _patch_pdf(monkeypatch, [[table]])
    rows = _extract_packing_pdf(_pdf_path(tmp_path))
    assert len(rows) == 1 and rows[0]["design_no"] == "D-001"


def test_header_beyond_scan_window_not_found(tmp_path, monkeypatch):
    # Header at index 25 (25 preamble rows) — one past the scan window. Documents
    # the known limitation: extraction fails cleanly (0 rows, header_not_detected)
    # rather than silently mis-parsing.
    table = _filler(25) + [
        ["PkSr", "DesignNo", "Kt/Color", "Qty"],
        ["1", "D-001", "18KT/Y", "2"],
    ]
    _patch_pdf(monkeypatch, [[table]])
    rows, _name, _ver, diag = extract_packing(_pdf_path(tmp_path))
    assert rows == []
    assert diag["failure_reason"] == "header_not_detected"


def test_zero_quantity_row_is_emitted(tmp_path, monkeypatch):
    # Pins CURRENT behaviour: a numeric "0" quantity passes the shared numeric
    # gate and is emitted — identical to the Excel path (shared contract). This
    # is documentation of existing behaviour, not a new rule; changing it would
    # alter the shared Excel contract and is out of scope for this repair.
    pages = [[[
        ["PkSr", "DesignNo", "Kt/Color", "Qty"],
        ["1", "D-001", "18KT/Y", "0"],
    ]]]
    _patch_pdf(monkeypatch, pages)
    rows = _extract_packing_pdf(_pdf_path(tmp_path))
    assert len(rows) == 1 and str(rows[0]["quantity"]) == "0"
