"""
test_customs_description_multi_invoice.py — Regression for the service-side
Polish customs description generator (customs_description_engine.py) when
the audit has multiple invoices but no per-line attribution (the AWB
6049349806 shape: invoice_names + invoice_totals.product_counts_by_unit only).

Pins:
  - invoice count = len(invoice_names)
  - invoice numbers parsed from leading numeric token in each invoice_names entry
  - one item-type group per non-zero entry of product_counts_by_unit
  - units carried through (PRS for earrings, PCS for rings/pendants)
  - financial breakdown row shows FOB + freight + insurance
  - grand total uses CIF (total_cif_usd), not sum of FOB lines
  - bad-phrase regression: "1 szt. (N/A)", "FAKTURA / INVOICE 1: N/A",
    "GRAND TOTAL: 11 PCS  |  USD 1,679.00" must be absent
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _audit_6049349806_shape() -> dict:
    """Audit shape that triggers the synthetic-multi-invoice fallback."""
    return {
        "awb":         "6049349806",
        "tracking_no": "6049349806",
        "invoice_names": [
            "121 Invoice EJL-26-27-121-04-05-26.pdf",
            "122 Invoice EJL-26-27-122-04-05-26.pdf",
            "123 Invoice EJL-26-27-123-04-05-26.pdf",
            "124 Invoice EJL-26-27-124-04-05-26.pdf",
        ],
        "invoice_totals": {
            "total_pcs":             7,
            "total_prs":             4,
            "total_units":           11,
            "total_fob_usd":         1679.0,
            "total_freight_usd":     75.0,
            "total_insurance_usd":   30.0,
            "total_cif_usd":         1784.0,
            "product_counts": {
                "rings":           5,
                "pendants":        2,
                "earrings":        4,
                "bracelets":       0,
                "necklaces":       0,
                "cufflinks":       0,
                "other_jewellery": 0,
            },
            "product_counts_by_unit": {
                "PCS": {"rings": 5, "pendants": 2},
                "PRS": {"earrings": 4},
            },
        },
        "result":  {"rows": [], "invoices": []},
        "inputs":  {},
    }


def _read_pdf_text(pdf_path: str) -> str:
    import pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def test_multi_invoice_synthetic_pdf_content(tmp_path):
    from customs_description_engine import generate_customs_description_package

    audit = _audit_6049349806_shape()
    pkg = generate_customs_description_package(
        batch=audit, awb="6049349806", output_dir=str(tmp_path),
    )
    pdf = (pkg or {}).get("pdf") or {}
    assert pdf.get("generated") is True, pdf
    out_path = pdf["output_path"]
    assert Path(out_path).is_file()
    assert Path(out_path).name == "POLISH_DESC_AWB_6049349806_20260507.pdf" \
        or Path(out_path).name.startswith("POLISH_DESC_AWB_6049349806_")

    text = _read_pdf_text(out_path)

    # Invoice count + numbers
    assert "4 szt." in text
    for n in ("121", "122", "123", "124"):
        assert n in text, f"invoice {n} missing"

    # Item-type groups (one per non-zero product_counts_by_unit entry)
    assert "RING" in text
    assert "PENDANT" in text
    assert "EARRINGS" in text

    # Quantities + units appear in the consolidated summary
    assert "5 PCS" in text     # rings (consolidated)
    assert "2 PCS" in text     # pendants (consolidated)
    assert "4 PRS" in text     # earrings (consolidated)

    # Financial breakdown
    assert "FOB Value" in text or "Wartość FOB" in text
    assert "Fracht / Freight" in text
    assert "Ubezpieczenie / Insurance" in text
    assert "1,679.00" in text
    assert "75.00" in text
    assert "30.00" in text

    # Grand total uses CIF
    assert "RAZEM CIF" in text
    assert "1,784.00" in text

    # Bad-phrase regressions
    assert "1 szt. (N/A)" not in text
    assert "FAKTURA / INVOICE 1: N/A" not in text
    assert "GRAND TOTAL: 11 PCS  |  USD 1,679.00" not in text
    assert "(N/A)" not in text


def test_invoice_refs_parsed_from_invoice_names():
    from customs_description_engine import _extract_invoice_refs_from_names
    refs = _extract_invoice_refs_from_names(_audit_6049349806_shape())
    assert refs == ["121", "122", "123", "124"]


def test_synthetic_lines_distributed_across_invoice_numbers():
    """When invoice_names has multiple refs, synthetic lines must be split
    across each invoice number (per-invoice clarity for customs)."""
    from customs_description_engine import _build_synthetic_lines_from_totals
    audit = _audit_6049349806_shape()
    lines = _build_synthetic_lines_from_totals(audit)
    assert lines, "synthetic lines should be produced from product_counts"
    inv_nos = {ln.get("invoice_number") for ln in lines}
    assert "N/A" not in inv_nos, f"got {inv_nos}"
    # All four invoice numbers must appear at least once
    for ref in ("121", "122", "123", "124"):
        assert ref in inv_nos, f"invoice {ref} missing from synthetic lines"
    # Aggregate quantities must be preserved by the divmod split
    by_type: dict[str, float] = {}
    for ln in lines:
        by_type[ln["item_type"]] = by_type.get(ln["item_type"], 0) + ln["quantity"]
    assert by_type.get("RING")     == 5
    assert by_type.get("PENDANT")  == 2
    assert by_type.get("EARRINGS") == 4


def test_pdf_has_per_invoice_blocks_and_consolidated_summary(tmp_path):
    """End-to-end content check for the new layout."""
    from customs_description_engine import generate_customs_description_package
    audit = _audit_6049349806_shape()
    pkg = generate_customs_description_package(
        batch=audit, awb="6049349806", output_dir=str(tmp_path),
    )
    text = _read_pdf_text(pkg["pdf"]["output_path"])
    # Per-invoice blocks (pdfplumber may collapse the double-space)
    import re
    for idx, ref in enumerate(("121", "122", "123", "124"), start=1):
        assert re.search(rf"FAKTURA / INVOICE {idx}:\s+{ref}", text), \
            f"missing per-invoice block for index {idx} ref {ref}"
    # Each invoice has its own subtotal
    assert text.count("Razem faktura") >= 4
    # Consolidated summary section present
    assert "PODSUMOWANIE" in text
    assert "CONSOLIDATED CUSTOMS SUMMARY" in text
    # Aggregate qtys per type in summary
    assert "5 PCS" in text     # RING
    assert "2 PCS" in text     # PENDANT
    assert "4 PRS" in text     # EARRINGS


def test_proposal_attachment_path_matches_generator_output(tmp_path):
    """Generator filename pattern must match what the proactive dispatch
    builder expects: POLISH_DESC_AWB_<AWB>_<DATE>.pdf inside polish_descriptions/."""
    from customs_description_engine import generate_customs_description_package
    audit = _audit_6049349806_shape()
    pkg = generate_customs_description_package(
        batch=audit, awb="6049349806", output_dir=str(tmp_path),
    )
    pdf = pkg["pdf"]
    name = Path(pdf["output_path"]).name
    assert name.startswith("POLISH_DESC_AWB_6049349806_")
    assert name.endswith(".pdf")
