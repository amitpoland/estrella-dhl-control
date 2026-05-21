"""test_global_packing_pdf_parser.py

Tests for the Global Jewellery packing-list PDF parser
(``parse_global_packing_pdf`` in ``global_packing_parser.py``) and the
UI dispatcher fix for the polish-description delete button.

Fixture: the production packing PDF for AWB 4789974092 / Invoice
088/2026-2027 — 245 sr.no anchored product rows summing to
USD 3172.00 FOB.

Estrella protection: the dispatch in
``invoice_packing_extractor.extract_packing`` only routes Global
suppliers; EJL files are unchanged. A regression test pins this.
"""
from __future__ import annotations

from pathlib import Path

import pytest


_FIXTURE_PDF = Path(
    r"C:\PZ\storage\outputs\SHIPMENT_4789974092_2026-05_999deef1"
    r"\source\packing\Global-inv-088 sggd.pdf"
)


def _require_fixture():
    if not _FIXTURE_PDF.exists():
        pytest.skip(f"production fixture missing: {_FIXTURE_PDF}")


# ── Core parser contract ──────────────────────────────────────────────────


def test_parser_function_exists():
    from app.services.global_packing_parser import parse_global_packing_pdf
    assert callable(parse_global_packing_pdf)


def test_parses_245_rows_from_production_packing_pdf():
    _require_fixture()
    from app.services.global_packing_parser import parse_global_packing_pdf
    rows, name, version, diag = parse_global_packing_pdf(_FIXTURE_PDF)
    assert len(rows) == 245, f"expected 245 rows, got {len(rows)}"
    assert name == "global_packing_pdf_v1"
    assert diag["failure_reason"] is None


def test_totals_reconcile_to_operator_expected_values():
    """Operator spec — totals MUST equal:
       quantity 245, FOB 3172.00, gross 505.103, net 453.212"""
    _require_fixture()
    from app.services.global_packing_parser import parse_global_packing_pdf
    _, _, _, diag = parse_global_packing_pdf(_FIXTURE_PDF)
    assert diag["total_qty"] == 245.0
    assert diag["total_fob_usd"] == pytest.approx(3172.00, abs=0.02)
    # gross/net can drift by 0.001-0.01 due to per-row float rounding
    assert diag["total_gross_wt"] == pytest.approx(505.103, abs=0.005)
    assert diag["total_net_wt"]   == pytest.approx(453.212, abs=0.005)


def test_invoice_no_extracted_from_preamble():
    _require_fixture()
    from app.services.global_packing_parser import parse_global_packing_pdf
    _, _, _, diag = parse_global_packing_pdf(_FIXTURE_PDF)
    assert diag["invoice_no"] == "088/2026-2027"


def test_product_codes_follow_invoice_no_seq_rule():
    _require_fixture()
    from app.services.global_packing_parser import parse_global_packing_pdf
    rows, _, _, _ = parse_global_packing_pdf(_FIXTURE_PDF)
    assert rows[0]["product_code"]   == "088/2026-2027-1"
    assert rows[244]["product_code"] == "088/2026-2027-245"


def test_serial_numbers_are_complete_1_through_245():
    """Operator concern: missing rows (e.g. plain jewellery rows that
    have no stone metadata between net_wt and FOB) MUST be captured."""
    _require_fixture()
    from app.services.global_packing_parser import parse_global_packing_pdf
    rows, _, _, _ = parse_global_packing_pdf(_FIXTURE_PDF)
    serials = sorted(r["serial_no"] for r in rows)
    assert serials == list(range(1, 246)), (
        f"missing or duplicate sr.no: {set(range(1, 246)) - set(serials)}"
    )


def test_metal_normalisation_maps_9_and_925sl():
    """Cryptic packing metal column ('9', '925SL') maps to canonical keys."""
    _require_fixture()
    from app.services.global_packing_parser import parse_global_packing_pdf
    rows, _, _, _ = parse_global_packing_pdf(_FIXTURE_PDF)
    metals = {r["metal"] for r in rows}
    # Row 1 is "9KT GOLD" (LGD bracelet); row 3 onward 925SL → "925 SILVER"
    assert "925 SILVER" in metals
    assert "9KT GOLD" in metals
    # Original raw tokens preserved for diagnostics
    raw_metals = {r["metal_raw"] for r in rows}
    assert any(rm.lower() in ("9", "925sl") for rm in raw_metals)


def test_plain_jewellery_row_without_stone_metadata_still_parses():
    """Bug found during development: rows like
       "183 Ring CSTR07109-O 925SL 1 8.810 8.810 12.00 12.00"
       (no stone-metadata middle section) were initially being skipped.
       Regex made `rest` optional to fix; pin that behaviour here."""
    _require_fixture()
    from app.services.global_packing_parser import parse_global_packing_pdf
    rows, _, _, _ = parse_global_packing_pdf(_FIXTURE_PDF)
    by_sr = {r["serial_no"]: r for r in rows}
    assert 183 in by_sr, "plain-jewellery row 183 was missed"
    assert 245 in by_sr, "plain-jewellery row 245 was missed"
    r183 = by_sr[183]
    assert r183["item_type"] == "Ring"
    assert r183["total_value"] == pytest.approx(12.00, abs=0.01)


def test_continuation_lines_aggregated_as_stone_detail():
    """Lines with no sr.no anchor (additional stone rows for the
    preceding item) must be appended to the prior row's stone_detail,
    NOT emitted as separate rows."""
    _require_fixture()
    from app.services.global_packing_parser import parse_global_packing_pdf
    rows, _, _, _ = parse_global_packing_pdf(_FIXTURE_PDF)
    # Row 244 has multiple continuation lines (Pear Shape CZ x3 + CZ Round)
    by_sr = {r["serial_no"]: r for r in rows}
    r244 = by_sr.get(244)
    assert r244 is not None
    # stone_detail must contain at least one of the continuation tokens
    sd = r244.get("stone_detail", "") or ""
    assert "Pear Shape CZ" in sd or "CZ Round Shape" in sd, (
        f"continuation aggregation missing in sr.no=244 stone_detail: {sd!r}"
    )


# ── Robustness against malformed input ────────────────────────────────────


def test_parser_returns_empty_on_missing_file(tmp_path):
    from app.services.global_packing_parser import parse_global_packing_pdf
    rows, _, _, diag = parse_global_packing_pdf(tmp_path / "does-not-exist.pdf")
    assert rows == []
    assert diag["failure_reason"] in ("file_open_error", "pdfplumber_not_installed")


def test_parser_does_not_crash_on_fragment_lines(tmp_path):
    """Garbage fragments like 'ite 1' or '######' must not crash."""
    # Use a minimal valid PDF with garbage content — the parser should
    # extract zero rows but never raise.
    pdf_path = tmp_path / "junk.pdf"
    # We can't easily forge a real PDF here without pypdf; instead test
    # by passing the production fixture and ensuring no exceptions even
    # though one row in the source PDF contains '######'.
    _require_fixture()
    from app.services.global_packing_parser import parse_global_packing_pdf
    rows, _, _, diag = parse_global_packing_pdf(_FIXTURE_PDF)
    # Production PDF has '######' on row 26's stone continuation line.
    # Parser must not crash.
    assert isinstance(rows, list)
    assert diag["failure_reason"] is None


# ── Dispatcher integration ────────────────────────────────────────────────


def test_extract_packing_dispatch_routes_pdf_to_pdf_parser():
    """The dispatcher in invoice_packing_extractor.extract_packing must
    route a Global supplier .pdf to parse_global_packing_pdf (not the
    Excel parser, which would reject .pdf)."""
    _require_fixture()
    from app.services.invoice_packing_extractor import extract_packing
    rows, parser, version, diag = extract_packing(_FIXTURE_PDF)
    assert parser == "global_packing_pdf_v1", (
        f"dispatcher routed to wrong parser: {parser}"
    )
    assert len(rows) == 245


def test_extract_packing_excel_branch_unchanged_for_xlsx(tmp_path):
    """Estrella protection invariant: the Excel branch is unchanged.
    A non-Global .xlsx must NOT be routed to the new PDF parser."""
    from app.services.invoice_packing_extractor import extract_packing
    # Empty xlsx — Estrella path returns 0 rows but parser_name must be
    # the Excel parser, NOT the PDF parser.
    try:
        import openpyxl
    except ImportError:
        pytest.skip("openpyxl unavailable")
    p = tmp_path / "empty.xlsx"
    openpyxl.Workbook().save(str(p))
    rows, parser, _, _ = extract_packing(p)
    assert parser != "global_packing_pdf_v1", (
        "Estrella .xlsx wrongly routed to Global PDF parser"
    )


# ── Output delete dispatcher (UI fix) ────────────────────────────────────


def test_polish_desc_filename_pattern_routes_to_dedicated_endpoint():
    """The UI dispatcher in shipment-detail.html must route POLISH_DESC_*
    filenames to the dedicated /polish-description endpoint, not the
    generic /files/{filename} endpoint (which would 404 because polish
    desc PDFs live in storage_root/polish_descriptions/, not in
    outputs/<batch>/)."""
    html_path = (Path(__file__).resolve().parent.parent
                 / "app" / "static" / "shipment-detail.html")
    src = html_path.read_text(encoding="utf-8")
    # Locate the deleteOutputFile function
    idx = src.find("const deleteOutputFile = async")
    assert idx != -1, "deleteOutputFile function missing"
    body = src[idx : idx + 1500]
    # Must contain a POLISH_DESC filename test AND a call to the
    # dedicated polish-description DELETE endpoint
    assert "POLISH_DESC_" in body, (
        "deleteOutputFile must filename-pattern-match POLISH_DESC_"
    )
    assert "/polish-description" in body, (
        "deleteOutputFile must call the dedicated /polish-description "
        "endpoint for polish desc files"
    )


# ── Out-of-scope guard ────────────────────────────────────────────────────


def test_pdf_parser_does_not_touch_forbidden_surfaces():
    src_path = (Path(__file__).resolve().parent.parent
                / "app" / "services" / "global_packing_parser.py")
    src = src_path.read_text(encoding="utf-8")
    # Locate the PDF parser function only
    idx = src.find("def parse_global_packing_pdf(")
    body = src[idx : idx + 6000]
    forbidden = (
        "compute_cif", "DHL_BROKER_THRESHOLD", "WFIRMA_CREATE_",
        "create_invoice", "create_pz", "_guard_wfirma_export",
    )
    for tok in forbidden:
        assert tok not in body, (
            f"PDF parser must not reference {tok!r}"
        )
