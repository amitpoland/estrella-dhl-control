"""
test_polish_desc_font.py — Regression tests for Polish description PDF font.

Ensures:
  1. Generated PDF uses ArialUnicodeMS (not Helvetica) for Polish text
  2. Filename follows POLISH_DESC_AWB_<awb>_<date>.pdf pattern
  3. PDF contains extractable Polish characters (Wartość, Ilość, etc.)
  4. No silent fallback to Helvetica when Unicode font is available
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest


_BATCH = {
    "tracking_no": "1234567890",
    "carrier": "DHL",
    "invoice_totals": {
        "total_cif_usd": 3000.0,
        "total_fob_usd": 2900.0,
        "total_freight_usd": 80.0,
        "total_insurance_usd": 20.0,
        "total_pcs": 2,
        "total_prs": 1,
    },
    "verification": {"invoice_cif_total_usd": 3000.0},
    "pz_rows": [
        {
            "lp": 1,
            "invoice_no": "EJL-TEST-001",
            "name_en": "Ring",
            "name_pl": "Pierścionek złoto próby 585",
            "qty": 2,
            "unit": "PCS",
            "unit_price_usd": 1000.0,
            "line_fob_usd": 2000.0,
            "item_type": "rings",
        },
        {
            "lp": 2,
            "invoice_no": "EJL-TEST-001",
            "name_en": "Earrings",
            "name_pl": "Kolczyki złote biżuteria",
            "qty": 1,
            "unit": "PRS",
            "unit_price_usd": 900.0,
            "line_fob_usd": 900.0,
            "item_type": "earrings",
        },
    ],
    "clearance_decision": {"total_value_usd": 3000.0},
}


def _generate(tmp_path: Path) -> dict:
    from customs_description_engine import generate_customs_description_package
    pkg = generate_customs_description_package(
        batch=_BATCH, awb="1234567890", output_dir=str(tmp_path)
    )
    return pkg.get("pdf") or {}


def test_pdf_generated(tmp_path):
    """PDF must be generated without error."""
    pdf = _generate(tmp_path)
    assert pdf.get("generated") is True, f"PDF not generated: {pdf.get('error')}"
    assert pdf.get("output_path")
    assert Path(pdf["output_path"]).exists()


def test_filename_pattern(tmp_path):
    """Filename must follow POLISH_DESC_AWB_<awb>_<YYYYMMDD>.pdf."""
    pdf = _generate(tmp_path)
    fname = pdf.get("filename", "")
    assert fname.startswith("POLISH_DESC_AWB_"), f"Bad filename prefix: {fname!r}"
    assert re.match(r"POLISH_DESC_AWB_\d+_\d{8}\.pdf", fname), \
        f"Filename does not match expected pattern: {fname!r}"


def test_embedded_font_is_not_helvetica(tmp_path):
    """The embedded font must be ArialUnicodeMS, not Helvetica."""
    pdf = _generate(tmp_path)
    raw = open(pdf["output_path"], "rb").read().decode("latin-1", errors="replace")
    font_names = set(re.findall(r"/FontName\s+/(\S+)", raw))
    assert any("Arial" in f or "DejaVu" in f or "FreeSans" in f for f in font_names), \
        f"No Unicode font found in PDF. Fonts: {font_names}"
    helvetica_only = all("Helvetica" in f and "Arial" not in f for f in font_names)
    assert not helvetica_only, "PDF is using Helvetica only — Polish chars will be broken"


def test_polish_chars_in_extracted_text(tmp_path):
    """Key Polish characters must be extractable from the PDF."""
    pytest.importorskip("pypdf")
    import pypdf
    pdf = _generate(tmp_path)
    reader = pypdf.PdfReader(pdf["output_path"])
    text = "".join(page.extract_text() or "" for page in reader.pages)
    assert "Wartość" in text, f"'Wartość' not found in extracted text"
    assert "ś" in text or "ć" in text or "ł" in text, \
        "No Polish diacritic characters found in extracted text"
