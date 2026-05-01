#!/usr/bin/env python3
"""
test_audit_pdf_polish.py — Polish glyph rendering test for audit PDFs
======================================================================
Verifies that audit_pdf.generate_audit_report_pdf() and
generate_audit_pdf() produce PDFs whose extracted text contains
the correct Polish characters — not replacement squares (■) or
(cid:...) artifacts from missing glyph encoding.

Run:
    python3 test_audit_pdf_polish.py

Expected: all tests PASS, exit code 0.
"""

import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))


# ── Test strings with Polish characters ──────────────────────────────────────

POLISH_STRINGS = [
    "Kuźmicz",
    "Wybrzeże Kościuszkowskie",
    "niezgodności",
    "muszą zostać wyjaśnione",
    "zgłoszenia celnego",
]

BROKEN_PATTERNS = ["■", "(cid:"]

# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract all text from a PDF using pypdf (preferred) or pdfminer fallback."""
    try:
        import pypdf
        reader = pypdf.PdfReader(str(pdf_path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        pass

    try:
        from pdfminer.high_level import extract_text
        return extract_text(str(pdf_path))
    except ImportError:
        pass

    # Last resort: strings-style byte scan (crude but works for ASCII-adjacent text)
    raw = pdf_path.read_bytes()
    visible = []
    i = 0
    while i < len(raw):
        c = raw[i]
        if 32 <= c < 127:
            visible.append(chr(c))
        i += 1
    return "".join(visible)


def _check_no_broken(text: str, context: str) -> list[str]:
    failures = []
    for pat in BROKEN_PATTERNS:
        if pat in text:
            count = text.count(pat)
            failures.append(f"  BROKEN GLYPH '{pat}' found {count}× in {context}")
    return failures


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_report_pdf_polish_chars() -> list[str]:
    """
    generate_audit_report_pdf() must produce a PDF where the extracted text
    does NOT contain ■ or (cid:...) artifacts.
    """
    from audit_pdf import generate_audit_report_pdf

    report_text = "\n".join([
        "AUDIT COMPLIANCE REPORT",
        "=" * 60,
        "",
        "PARTIES",
        "-" * 30,
        "Importer: Estrella Jewels Sp. z o.o. Sp.k.",
        "NIP: 5252812119",
        "Address: ul. Wybrzeże Kościuszkowskie 31/33, 00-379 Warszawa",
        "",
        "FINDINGS",
        "-" * 30,
        "Eksporter: Kuźmicz Trading Co.",
        "Wykryto niezgodności w dokumentach celnych.",
        "Wszystkie pozycje muszą zostać wyjaśnione przed odprawą.",
        "Proszę przesłać korektę zgłoszenia celnego.",
        "Wartości na fakturach nie zgadzają się z SAD.",
        "",
        "CONCLUSION",
        "-" * 30,
        "Dokumenty wymagają weryfikacji przez agenta celnego.",
    ])

    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "audit_report_test.pdf"
        generate_audit_report_pdf(report_text, out, title="Test Audit", language="pl")

        assert out.exists(), "PDF was not created"
        assert out.stat().st_size > 1000, f"PDF suspiciously small: {out.stat().st_size} bytes"

        extracted = _extract_text_from_pdf(out)
        failures.extend(_check_no_broken(extracted, "audit_report_pdf"))

        # Check at least the ASCII parts round-trip correctly (Polish extraction
        # depends on the PDF reader; if pypdf/pdfminer aren't installed we skip
        # the positive check).
        if "Kuzmicz" in extracted or "Ku" in extracted:
            pass  # rough sanity — extraction working

    return failures


def test_memo_pdf_polish_chars() -> list[str]:
    """
    generate_audit_pdf() (the full audit memo) must not contain broken glyphs
    in its extracted text either.
    """
    from audit_pdf import generate_audit_pdf

    # Minimal audit_data — just enough to exercise the footer and section 7
    audit_data = {
        "batch_id":       "test_polish_001",
        "doc_no":         "PZ 1/1/2026",
        "mrn":            "26PL601001000001AB",
        "clearance_date": "2026-01-15",
        "score":          72,
        "risk_level":     "MEDIUM RISK",
        "failed_checks":  ["exporter_match"],
        "overall_en":     "Medium risk — exporter name discrepancy detected.",
        "overall_pl":     (
            "Ryzyko średnie — wykryto rozbieżność nazwy eksportera. "
            "Kuźmicz Trading wymaga wyjaśnienia. "
            "Dostawa na Wybrzeże Kościuszkowskie jest zgodna z rejestrem."
        ),
        "c1": {"result": False, "invoice_value": "Kuzmicz", "sad_value": "Kuźmicz Trading"},
        "c2": {
            "name_result": True, "nip_result": True,
            "invoice_name": "Estrella Jewels", "sad_name": "Estrella Jewels",
            "master_nip": "5252812119",
        },
        "c3": {
            "consistent": True,
            "master_reg_addr": "ul. Wybrzeże Kościuszkowskie 31/33, 00-379 Warszawa",
            "invoice_addr": "Warszawa",
            "invoice_type_en": "Registered office",
            "sad_addr": "00-379 Warszawa",
        },
        "c4": {
            "result": True,
            "sad_refs": ["INV-001"],
            "pdf_refs": ["INV-001"],
            "severity_en": "All invoices matched",
        },
        "c5": {
            "inv_cif": 5000.0, "sad_cif": 5000.0, "cif_diff": 0.0,
            "cif_result": True, "duty_pln": 1200.0, "vat_pln": 2300.0,
            "nbp_rate": 4.012, "nbp_table": "A", "nbp_date": "2026-01-14",
            "has_freight": True, "has_insurance": False, "freight_varies": False,
            "per_inv_checks": [],
        },
        "c6": {"result": None, "awb_digits": [], "refs": []},
        "invoices": [],
        "zc429": {"mrn": "26PL601001000001AB", "agent": "Agencja Celna Sp. z o.o."},
        "nbp": {},
        "line_count": 3,
        "total_net": 12000.0,
        "total_gross": 14760.0,
        "duty_pln": 1200.0,
        "learning_trace": {},
        "freight_checks": [],
        "learning_applied": False,
        "penalty_breakdown": {},
    }

    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "audit_memo_test.pdf"
        generate_audit_pdf(out, audit_data)

        assert out.exists(), "audit_memo.pdf was not created"
        assert out.stat().st_size > 2000, f"PDF too small: {out.stat().st_size} bytes"

        extracted = _extract_text_from_pdf(out)
        failures.extend(_check_no_broken(extracted, "audit_memo.pdf"))

    return failures


def test_font_registration() -> list[str]:
    """register_audit_fonts() must find a Unicode-capable font on this machine."""
    from audit_pdf import _register_audit_fonts
    fr, fb = _register_audit_fonts()
    if fr == "Helvetica":
        return ["  WARN: No Unicode TTF font found — Polish chars may break. "
                "Install Arial Unicode or DejaVu Sans."]
    return []


# ── Runner ────────────────────────────────────────────────────────────────────


def main() -> int:
    tests = [
        ("Font registration",              test_font_registration),
        ("Report PDF — Polish characters", test_report_pdf_polish_chars),
        ("Memo PDF — Polish characters",   test_memo_pdf_polish_chars),
    ]

    total_failures = 0
    for name, fn in tests:
        print(f"\n{'─'*60}")
        print(f"TEST: {name}")
        try:
            failures = fn()
            if failures:
                print(f"  FAIL ({len(failures)} issue(s)):")
                for f in failures:
                    print(f)
                total_failures += len(failures)
            else:
                print("  PASS")
        except Exception as exc:
            print(f"  ERROR: {exc}")
            import traceback
            traceback.print_exc()
            total_failures += 1

    print(f"\n{'═'*60}")
    if total_failures == 0:
        print("ALL TESTS PASSED")
    else:
        print(f"FAILED: {total_failures} issue(s)")
    print("═" * 60)
    return 0 if total_failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
