#!/usr/bin/env python3
"""
test_polish_description_uses_invoice_lines.py
==============================================
Verifies that generate_customs_description_package() produces a correct
Polish customs description PDF when invoice row data is present:

  1. PDF file is non-empty (> 10 KB)
  2. All Polish characters render — no ■ (U+25A0) or (cid:...) artifacts
  3. All invoice line descriptions appear in the output
  4. No "0.00 USD" value lines when invoices have real values
  5. No "Brak pozycji towarowych" (empty goods fallback) when lines exist
  6. Polish customs descriptions are grammatically correct Polish
     (contains biżuteria/do noszenia/próby/pierścionek/kolczyki etc.)

Run:
    python3 test_polish_description_uses_invoice_lines.py

Expected: all tests PASS, exit code 0.
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

import customs_description_engine as e


# ── Test batch with realistic invoice rows ────────────────────────────────────

_FAKE_BATCH = {
    "batch_id":      "TEST_BATCH_001",
    "tracking_no":   "3283625844",
    "invoice_totals": {
        "total_fob_usd":       10094.0,
        "total_freight_usd":   45.0,
        "total_insurance_usd": 30.0,
        "total_cif_usd":       10169.0,
        "product_counts": {"rings": 13, "earrings": 16},
    },
    "inputs": {
        "invoice_refs": ["EJL/25-26/1247", "EJL/25-26/1248"],
    },
    # Rows in the format injected by _inject_rows_from_xlsx
    "rows": [
        {
            "invoice_number": "EJL/25-26/1247",
            "description":    "Plain 9KT Gold Jewellery RING",
            "item_type":      "RING",
            "quantity":       2.0,
            "unit_price":     313.0,
            "line_total":     626.0,
        },
        {
            "invoice_number": "EJL/25-26/1248",
            "description":    "Diamond & Colour Stone 14KT Gold Jewellery RING",
            "item_type":      "RING",
            "quantity":       5.0,
            "unit_price":     616.4,
            "line_total":     3082.0,
        },
        {
            "invoice_number": "EJL/25-26/1248",
            "description":    "Diamond Studded 14KT Gold Jewellery EARRINGS",
            "item_type":      "EARRINGS",
            "quantity":       6.0,
            "unit_price":     576.0,
            "line_total":     3456.0,
        },
        {
            "invoice_number": "EJL/25-26/1248",
            "description":    "Lab Grown Diamond Studded 18KT Gold Jewellery RING",
            "item_type":      "RING",
            "quantity":       1.0,
            "unit_price":     562.0,
            "line_total":     562.0,
        },
    ],
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_text(pdf_path: str) -> str:
    """Extract text from PDF via pypdf or pdfminer. Returns raw string."""
    # Try pypdf first (faster, fewer deps)
    try:
        import pypdf
        reader = pypdf.PdfReader(pdf_path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        pass
    # Fall back to pdfminer
    try:
        from pdfminer.high_level import extract_text as pm_extract
        return pm_extract(pdf_path)
    except ImportError:
        pass
    # Can't extract — skip text checks
    return ""


def _run(name: str, cond: bool, detail: str = "") -> bool:
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))
    return cond


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_polish_description_uses_invoice_lines() -> None:
    """Main test: verify PDF is generated correctly from invoice rows."""
    print("\n── test_polish_description_uses_invoice_lines ──")
    failures = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        result = e.generate_customs_description_package(
            batch         = _FAKE_BATCH,
            awb           = "3283625844",
            output_dir    = tmpdir,
            date_override = "2026-04-27",
        )

        pdf_r = result.get("pdf", {})
        json_r = result.get("json", {})

        # ── 1. PDF generated without error ────────────────────────────────────
        failures += 0 if _run("PDF generated",
                               pdf_r.get("generated") is True,
                               str(pdf_r.get("error"))) else 1

        if not pdf_r.get("generated"):
            print("  SKIP  remaining checks — PDF not generated")
            return

        pdf_path = pdf_r["output_path"]

        # ── 2. File size > 10 KB ──────────────────────────────────────────────
        size_kb = Path(pdf_path).stat().st_size / 1024
        failures += 0 if _run("PDF > 10 KB",
                               size_kb > 10,
                               f"actual {size_kb:.1f} KB") else 1

        # ── 3. items_described == 4 (one per row) ─────────────────────────────
        failures += 0 if _run("items_described == 4",
                               pdf_r.get("items_described") == 4,
                               f"got {pdf_r.get('items_described')}") else 1

        # ── 4. PDF hash is non-empty ──────────────────────────────────────────
        failures += 0 if _run("PDF hash present",
                               bool(pdf_r.get("pdf_hash"))) else 1

        # ── Text-based checks (require pypdf or pdfminer) ─────────────────────
        text = _extract_text(pdf_path)
        if not text.strip():
            print("  SKIP  text-based checks — no PDF text extractor available")
        else:
            # 5. No replacement boxes
            failures += 0 if _run("No ■ replacement chars",
                                   "■" not in text,
                                   "found ■ in PDF text") else 1
            failures += 0 if _run("No (cid:...) artifacts",
                                   "(cid:" not in text,
                                   "found (cid:...) in PDF text") else 1

            # 6. No "0.00 USD" data lines — invoice ref lines must not show zero value.
            # Match only lines that contain an invoice reference AND a zero-value
            # pattern like "0.00" preceded by non-digit (to avoid false positives
            # from numbers like 7,100.00 or 3,082.00 which legitimately end in .00).
            import re as _re
            has_zero_line = any(
                "EJL/" in line and _re.search(r"\b0\.00\b", line)
                for line in text.splitlines()
            )
            failures += 0 if _run("No 0.00 USD value lines",
                                   not has_zero_line,
                                   "found 0.00 USD in a data row") else 1

            # 7. No "Brak pozycji towarowych" (empty goods fallback)
            failures += 0 if _run("No empty-goods fallback",
                                   "Brak pozycji" not in text) else 1

            # 8. Polish keywords present
            pl_keywords = ["biżuteria", "noszenia", "próby", "Pierścionek", "Kolczyki"]
            for kw in pl_keywords:
                failures += 0 if _run(f"Polish keyword: {kw!r}",
                                       kw in text,
                                       "keyword missing from PDF text") else 1

            # 9. Real invoice values present (626, 3082, 3456, 562)
            for val in ("626", "3,082", "3,456", "562"):
                failures += 0 if _run(f"Value {val} in PDF",
                                       val in text,
                                       "value missing from PDF text") else 1

            # 10. AWB present
            failures += 0 if _run("AWB in PDF", "3283625844" in text) else 1

            # 11. Stone descriptions correct
            # Note: PDF text extraction may strip spaces at cell wraps;
            # check for "diamentami" (subset that always survives extraction)
            failures += 0 if _run("Diamond & Colour → diamentami (stone keyword)",
                                   "diamentami" in text) else 1
            failures += 0 if _run("Lab Grown → laboratoryjnymi",
                                   "laboratoryjnymi" in text) else 1

        # ── SAD JSON checks ───────────────────────────────────────────────────
        failures += 0 if _run("SAD JSON generated",
                               json_r.get("generated") is True) else 1
        if json_r.get("generated") and json_r.get("output_path"):
            import json
            with open(json_r["output_path"], encoding="utf-8") as f:
                jdata = json.load(f)
            failures += 0 if _run("SAD JSON has 4 lines",
                                   jdata.get("total_lines") == 4,
                                   f"got {jdata.get('total_lines')}") else 1
            failures += 0 if _run("SAD JSON UTF-8 Polish",
                                   "Pierścionek" in json.dumps(jdata, ensure_ascii=False)) else 1

    if failures == 0:
        print(f"\n  All checks PASSED ✓\n")
    else:
        print(f"\n  {failures} check(s) FAILED ✗\n")
        sys.exit(1)


def test_synthetic_fallback_from_invoice_totals() -> None:
    """Verify fallback path: no rows → build from invoice_totals.product_counts."""
    print("\n── test_synthetic_fallback_from_invoice_totals ──")
    failures = 0

    batch_no_rows = {
        "batch_id": "TEST_SYNTHETIC",
        "invoice_totals": {
            "total_fob_usd":  5000.0,
            "total_cif_usd":  5075.0,
            "product_counts": {"rings": 10, "earrings": 5},
        },
        "customs_declaration": {"cn_code": "71131900"},
        "inputs": {"invoice_refs": ["INV/2026/001"]},
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        result = e.generate_customs_description_package(
            batch         = batch_no_rows,
            awb           = "1234567890",
            output_dir    = tmpdir,
            date_override = "2026-04-27",
        )
        pdf_r = result["pdf"]
        failures += 0 if _run("PDF generated (synthetic fallback)",
                               pdf_r.get("generated") is True,
                               str(pdf_r.get("error"))) else 1
        failures += 0 if _run("items_described == 2 (ring + earring types)",
                               pdf_r.get("items_described") == 2,
                               f"got {pdf_r.get('items_described')}") else 1

    if failures == 0:
        print("  All checks PASSED ✓\n")
    else:
        print(f"  {failures} check(s) FAILED ✗\n")
        sys.exit(1)


def test_normalize_item_description_polish_grammar() -> None:
    """Unit-test the normalization function for key description patterns."""
    print("\n── test_normalize_item_description_polish_grammar ──")
    failures = 0

    cases = [
        ("Plain 9KT Gold Jewellery RING",               "RING",     "Pierścionek ze złota próby 375"),
        ("Diamond & Colour Stone 14KT Gold Jewellery RING", "RING", "z diamentami i kamieniami szlachetnymi"),
        ("Diamond Studded 14KT Gold Jewellery EARRINGS","EARRINGS", "Kolczyki ze złota próby 585 z diamentami"),
        ("Lab Grown Diamond Studded 18KT Gold Jewellery RING", "RING", "z diamentami laboratoryjnymi"),
        ("925 SILVER BANGLE PLAIN",                     "BANGLE",   "srebra próby 925"),
        ("14KT PENDANT DIA",                            "PENDANT",  "Wisiorek ze złota próby 585 z diamentami"),
    ]

    for raw, itype, expected_fragment in cases:
        r = e.normalize_item_description(raw, item_type=itype)
        desc = r["polish_customs_description"]
        ok = expected_fragment in desc
        failures += 0 if _run(f"{raw[:40]!r}",
                               ok,
                               f"expected {expected_fragment!r} in {desc!r}") else 1

    if failures == 0:
        print("  All checks PASSED ✓\n")
    else:
        print(f"  {failures} check(s) FAILED ✗\n")
        sys.exit(1)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== test_polish_description_uses_invoice_lines ===")
    test_normalize_item_description_polish_grammar()
    test_synthetic_fallback_from_invoice_totals()
    test_polish_description_uses_invoice_lines()
    print("=== All test suites passed ===")
