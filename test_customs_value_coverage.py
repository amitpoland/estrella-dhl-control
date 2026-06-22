"""
test_customs_value_coverage.py — customs value coverage authority (Lesson N, 2026-06-22).

Pins the two-signal authority model for customs invoice reference verification:

  invoice_value_coverage   — financial authority (True/False/None).
                             HARD BLOCK when False. Cannot be operator-overridden.
  invoice_refs_completeness — administrative completeness (string, non-blocking).
                             "review_needed" surfaces as advisory; does NOT block PZ.

Four cases:
  A — ref missing from N935, value included in SAD CIF  → REVIEW_NEEDED, not BLOCKED
  B — ref missing from N935, CIF mismatch               → BLOCKED (CIF authority)
  C — SAD N935 ref has no matching PDF                   → BLOCKED (missing_pdf)
  D — exact match                                        → PASS (verified)

These are permanent regression guards. A warning may not be promoted back into a
hard blocker without an explicit business rule + a new test.
"""
import sys
import os

# Allow root-level import when running from repo root or service directory
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from pz_import_processor import verify_sad_invoice_match


def _make_invoice(inv_no: str, cif_usd: float, items=None) -> dict:
    """Minimal invoice dict for verify_sad_invoice_match."""
    return {
        "invoice_no": inv_no,
        "cif_usd":    cif_usd,
        "fob_usd":    cif_usd * 0.95,
        "freight_usd":    cif_usd * 0.03,
        "insurance_usd":  cif_usd * 0.02,
        "items": items or [],
        "_raw_text": "",
    }


def _make_zc429(refs: list, total_cif_usd: float) -> dict:
    """Minimal ZC429 dict with N935 refs and CIF total."""
    return {
        "invoice_refs":        refs,
        "invoice_refs_method": "N935",
        "inferred_refs":       [],
        "total_cif_usd":       total_cif_usd,
        "duty_pln":            0.0,
        "sad_qty_by_type":     {},
        "cn_code":             "",
        "customs_rate_usd":    4.0,
        "sad_additions_pln":   0.0,
    }


# ── Case A: ref missing from N935, value included in SAD CIF ─────────────────

def test_case_a_ref_missing_value_included_is_review_needed():
    """
    Invoice EJL/300 is present in the PDF set but NOT listed in SAD N935.
    However, all 11 invoice values sum exactly to the SAD CIF.
    Expected: invoice_refs_match=None (not False), invoice_value_coverage=True,
              invoice_refs_completeness="review_needed", no blocking.
    This mirrors the exact AWB 9158478722 scenario (2026-06-22).
    """
    invoices = [
        _make_invoice("EJL/290", 200.0),
        _make_invoice("EJL/291", 150.0),
        _make_invoice("EJL/300", 50.0),   # NOT in SAD N935 refs
    ]
    # SAD N935 only lists 290 and 291; 300 was omitted by the broker
    sad_cif = 200.0 + 150.0 + 50.0  # = 400.0 — all invoice values are covered
    zc429 = _make_zc429(["EJL/290", "EJL/291"], sad_cif)

    result = verify_sad_invoice_match(invoices, zc429)

    # Core authority signals
    assert result["invoice_refs_match"] is None, (
        "extra_not_in_sad with covered CIF must produce None (advisory), not False"
    )
    assert result["invoice_value_coverage"] is True, (
        "CIF match with no missing_in_pdfs must produce invoice_value_coverage=True"
    )
    assert result["invoice_refs_completeness"] == "review_needed", (
        "N935 administrative omission must be labelled review_needed"
    )

    # extra_not_in_sad carries the omitted invoice ref
    assert "EJL/300" in result["extra_invoices_not_in_sad"]
    # missing_in_pdfs must be empty (we have PDFs for all N935 refs)
    assert result["missing_invoices_in_pdfs"] == []
    # CIF is confirmed
    assert result["cif_match"] is True


# ── Case B: ref missing from N935, CIF mismatch ──────────────────────────────

def test_case_b_ref_missing_cif_mismatch_is_blocked():
    """
    Invoice EJL/300 is in the PDF set but NOT in SAD N935.
    AND the SAD CIF is less than the sum of all invoices (value undeclared).
    Uses $600 undeclared value — exceeds the $500 soft-threshold so cif_match=False.
    Expected: invoice_value_coverage=False (CIF mismatch), cif_match=False, BLOCKED.
    """
    invoices = [
        _make_invoice("EJL/290", 200.0),
        _make_invoice("EJL/291", 150.0),
        _make_invoice("EJL/300", 600.0),   # NOT in N935, NOT in SAD CIF — $600 gap
    ]
    sad_cif = 200.0 + 150.0   # = 350.0 — invoice 300's $600 is NOT included (diff > $500)
    zc429 = _make_zc429(["EJL/290", "EJL/291"], sad_cif)

    result = verify_sad_invoice_match(invoices, zc429)

    # CIF is a confirmed mismatch (diff = $50, > $1 tolerance)
    assert result["cif_match"] is False
    # invoice_value_coverage must be False (CIF mismatch → value not covered)
    assert result["invoice_value_coverage"] is False
    # N935 omits invoice 300 → review_needed on the admin side too
    assert result["invoice_refs_completeness"] == "review_needed"
    # extra_not_in_sad correctly identifies 300
    assert "EJL/300" in result["extra_invoices_not_in_sad"]


# ── Case C: SAD N935 lists invoice with no matching PDF ──────────────────────

def test_case_c_sad_ref_without_pdf_is_blocked():
    """
    SAD N935 references EJL/999 but we have no PDF for it.
    Expected: invoice_refs_match=False, invoice_value_coverage=False,
              invoice_refs_completeness="missing_pdf", BLOCKED.
    """
    invoices = [
        _make_invoice("EJL/290", 200.0),
        _make_invoice("EJL/291", 150.0),
    ]
    sad_cif = 200.0 + 150.0 + 100.0   # SAD includes EJL/999 value
    zc429 = _make_zc429(["EJL/290", "EJL/291", "EJL/999"], sad_cif)

    result = verify_sad_invoice_match(invoices, zc429)

    # SAD holds a ref we cannot produce — hard signal
    assert result["invoice_refs_match"] is False, (
        "SAD ref without PDF must produce invoice_refs_match=False"
    )
    assert result["invoice_value_coverage"] is False
    assert result["invoice_refs_completeness"] == "missing_pdf"
    assert "EJL/999" in result["missing_invoices_in_pdfs"]
    # No extra_not_in_sad (all our PDFs are in the SAD)
    assert result["extra_invoices_not_in_sad"] == []


# ── Case D: exact match ───────────────────────────────────────────────────────

def test_case_d_exact_match_is_pass():
    """
    All SAD N935 refs have matching PDFs and vice-versa; CIF matches exactly.
    Expected: invoice_refs_match=True, invoice_value_coverage=True,
              invoice_refs_completeness="verified".
    """
    invoices = [
        _make_invoice("EJL/290", 200.0),
        _make_invoice("EJL/291", 150.0),
    ]
    sad_cif = 200.0 + 150.0   # exact match
    zc429 = _make_zc429(["EJL/290", "EJL/291"], sad_cif)

    result = verify_sad_invoice_match(invoices, zc429)

    assert result["invoice_refs_match"] is True
    assert result["invoice_value_coverage"] is True
    assert result["invoice_refs_completeness"] == "verified"
    assert result["missing_invoices_in_pdfs"] == []
    assert result["extra_invoices_not_in_sad"] == []
    assert result["cif_match"] is True


# ── Invariant: Case A does not emit a blocking amendment flag ─────────────────

def test_case_a_amendment_flags_do_not_include_blocking_ref_flag():
    """
    For Case A (extra_not_in_sad, value covered), build_amendment_flags must NOT
    emit 'Invoices in PDF set not listed in SAD'. That flag is blocking; it must
    only appear when value coverage is not confirmed.
    """
    from pz_import_processor import build_amendment_flags

    invoices = [
        _make_invoice("EJL/290", 200.0),
        _make_invoice("EJL/291", 150.0),
        _make_invoice("EJL/300", 50.0),
    ]
    sad_cif = 400.0
    zc429 = _make_zc429(["EJL/290", "EJL/291"], sad_cif)
    verification = verify_sad_invoice_match(invoices, zc429)
    corrections_log = []

    flags = build_amendment_flags(invoices, zc429, verification, corrections_log)

    blocking_ref_flags = [
        f for f in flags if "Invoices in PDF set not listed in SAD" in f
    ]
    assert blocking_ref_flags == [], (
        f"Case A must not emit a blocking 'not listed in SAD' flag, got: {blocking_ref_flags}"
    )
    # Also must not emit the master structural flag
    structural_flags = [f for f in flags if "Review needed: SAD / invoice set" in f]
    assert structural_flags == [], (
        f"Case A must not emit the structural mismatch flag, got: {structural_flags}"
    )
