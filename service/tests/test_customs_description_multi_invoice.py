"""
test_customs_description_multi_invoice.py — Regression for the service-side
Polish customs description generator (customs_description_engine.py) on the
aggregate-only shape (the AWB 6049349806 shape: invoice_names +
invoice_totals.product_counts_by_unit only, no per-line rows/invoices).

AUTHORITY CHANGE (customs-description-resolver): a batch with only aggregate
totals has NO per-line description authority. The synthetic type-level fallback
emits generic text ("Wyrób jubilerski" / "metal szlachetny"), which must NEVER
reach a customs document (Lesson N). Such a batch now BLOCKS before generation
with row-level `descriptions_missing_for_customs` detail (one row per aggregate
item type) — it does not produce a generic aggregate PDF.

Pins:
  - aggregate-only batch → pkg blocked, guard=descriptions_missing_for_customs
  - one deduped block row per aggregate item type (RING/PENDANT/EARRINGS),
    reason=aggregate_only_no_description_authority, invoice="aggregate fallback"
  - NO PDF/SAD file written to disk; no attachment path/filename
  - synthetic-line helpers (_build_synthetic_lines_from_totals /
    _extract_invoice_refs_from_names) remain correct — they feed the block-row
    enumeration, not customs output
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


def test_multi_invoice_aggregate_only_blocks_with_row_detail(tmp_path):
    """Aggregate-only fallback (invoice_totals/product_counts but no per-line
    items) has NO per-line description authority. It must BLOCK before
    generation with row-level `descriptions_missing_for_customs` detail — the
    old behavior (a generic "Wyrób jubilerski" customs PDF) is a Lesson-N
    violation and is no longer permitted."""
    from customs_description_engine import generate_customs_description_package

    audit = _audit_6049349806_shape()
    pkg = generate_customs_description_package(
        batch=audit, awb="6049349806", output_dir=str(tmp_path),
    )
    assert pkg["blocked"] is True
    assert pkg["guard"] == "descriptions_missing_for_customs"
    # No generic customs document was produced.
    assert pkg["pdf"]["generated"] is False
    assert pkg["pdf"]["output_path"] is None
    assert pkg["json"]["generated"] is False
    assert not list(Path(tmp_path).glob("*.pdf"))

    rows = pkg["missing"]
    assert rows, "expected row-level aggregate detail"
    for r in rows:
        assert r["reason"] == "aggregate_only_no_description_authority"
        assert r["invoice"] == "aggregate fallback"
        assert r["forbidden_token"] is None
        assert r["suggested_correction_route"]
    # One row per aggregate item type (deduped) — operator sees each type.
    codes = {r["product_code"] for r in rows}
    assert {"RING", "PENDANT", "EARRINGS"} <= codes


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


def test_aggregate_only_writes_no_customs_document(tmp_path):
    """The aggregate-only block must not leave any generated artifact on disk —
    no generic PDF/SAD JSON reaches the filesystem for the proactive dispatch
    builder to attach."""
    from customs_description_engine import generate_customs_description_package
    audit = _audit_6049349806_shape()
    pkg = generate_customs_description_package(
        batch=audit, awb="6049349806", output_dir=str(tmp_path),
    )
    assert pkg["blocked"] is True
    assert pkg["json"]["output_path"] is None
    # Nothing written to disk (recursively) — no aggregate/generic customs file.
    assert not list(Path(tmp_path).rglob("*.pdf"))
    assert not list(Path(tmp_path).rglob("*.json"))


def test_proposal_attachment_absent_when_aggregate_blocked(tmp_path):
    """When the aggregate-only block fires, there is NO attachment path/filename,
    so the proactive dispatch builder cannot attach a generic customs PDF."""
    from customs_description_engine import generate_customs_description_package
    audit = _audit_6049349806_shape()
    pkg = generate_customs_description_package(
        batch=audit, awb="6049349806", output_dir=str(tmp_path),
    )
    pdf = pkg["pdf"]
    assert pdf["generated"] is False
    assert pdf["output_path"] is None
    assert pdf["filename"] is None
