"""
PR A — Proforma Display Contract Lock (2026-06-10)

Source-grep regression contract for the 7 display rules fixed in this PR.
No server required — all assertions read JSX source files directly.
Regression baseline: Draft #24 (PROF 123/2026, UAB Tomas Gold, €79,000.23).

Rules locked:
  #3  Payment due calculation uses payment_terms_days fallback
  #5  Bank details populated from companyProfile.bank_accounts (not [])
  #6  Footer payment terms driven by paymentDays prop (not hardcoded '7 days')
  #7  Footer contrast: fontSize 10, color #334155
  #8  Origin fallback chain: ln.origin || origin_country || companyProfile.country
  #9  PL/EN descriptions: desc_pl + desc_en mapped from editable_lines
  #10 Country codes expanded via COUNTRY_NAMES lookup (_expandCountry applied ≥2×)
"""
import re
from pathlib import Path

_ROOT = Path(__file__).parent.parent
PROFORMA_DETAIL = _ROOT / "app" / "static" / "v2" / "proforma-detail.jsx"
DOC_PROFORMA    = _ROOT / "app" / "static" / "v2" / "estrella-doc-proforma.jsx"


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Rule #10: COUNTRY_NAMES dict ──────────────────────────────────────────────

def test_country_names_dict_defined():
    src = _src(PROFORMA_DETAIL)
    assert "COUNTRY_NAMES" in src, "COUNTRY_NAMES lookup missing from proforma-detail.jsx"


def test_country_names_contains_required_codes():
    src = _src(PROFORMA_DETAIL)
    # JS object keys may be unquoted (PL: 'Poland') or quoted ('PL': 'Poland').
    # Check for the mapped country names — if the value is present the key is too.
    for code, name in (("PL", "Poland"), ("LT", "Lithuania"), ("DE", "Germany"),
                       ("IN", "India"), ("ES", "Spain")):
        assert name in src, \
            f"Country name '{name}' (for code {code}) missing from COUNTRY_NAMES"


def test_expand_country_applied_to_buyer_and_seller():
    src = _src(PROFORMA_DETAIL)
    assert "_expandCountry" in src, "_expandCountry helper not found in proforma-detail.jsx"
    count = src.count("_expandCountry(")
    assert count >= 2, \
        f"_expandCountry called {count} time(s) — expected ≥2 (buyer.country + seller.country)"


# ── Rule #5: Bank details from companyProfile ─────────────────────────────────

def test_banks_not_hardcoded_empty():
    src = _src(PROFORMA_DETAIL)
    assert "banks:    []" not in src, "banks still hardcoded to [] in previewDocData"
    assert "banks: []" not in src,    "banks still hardcoded to [] in previewDocData"


def test_banks_populated_from_company_profile():
    src = _src(PROFORMA_DETAIL)
    assert "bank_accounts" in src, \
        "companyProfile.bank_accounts not referenced — banks will always be empty"


# ── Rule #6: Footer payment terms driven by prop ─────────────────────────────

def test_compliance_footer_not_hardcoded_7_days():
    src = _src(DOC_PROFORMA)
    compliance_fn = src[src.index("function EJDocCompliance"):]
    closing = compliance_fn.index("\nfunction ", 1) if "\nfunction " in compliance_fn[1:] else len(compliance_fn)
    body = compliance_fn[:closing]
    # The old hardcoded text was literally "within 7 days of invoice date" in JSX.
    # The fix renders {daysLabel} instead — the string "within 7 days of" must not appear
    # as static JSX text. A "7 days" default-value string in a JS ternary is acceptable.
    assert "within 7 days of" not in body, \
        "EJDocCompliance still has hardcoded 'within 7 days of' JSX text — must use paymentDays prop"


def test_compliance_footer_accepts_payment_days_prop():
    src = _src(DOC_PROFORMA)
    assert "paymentDays" in src, \
        "EJDocCompliance does not accept paymentDays prop"


def test_compliance_callers_pass_payment_days():
    src = _src(DOC_PROFORMA)
    count = src.count("paymentDays={")
    assert count >= 3, \
        f"paymentDays prop passed {count} time(s) — expected ≥3 (Classic + Modern + Bold)"


# ── Rule #7: Footer contrast ──────────────────────────────────────────────────

def test_compliance_footer_font_size_10():
    src = _src(DOC_PROFORMA)
    fn_start = src.index("function EJDocCompliance")
    closing = src.index("\nfunction ", fn_start + 1)
    body = src[fn_start:closing]
    # Must contain fontSize: 10 in the outer wrapper div
    m = re.search(r"fontSize[:\s]+(\d+)", body[:400])
    assert m, "No fontSize found near EJDocCompliance wrapper"
    assert int(m.group(1)) >= 10, \
        f"EJDocCompliance wrapper fontSize is {m.group(1)} — expected ≥10 for print readability"


def test_compliance_footer_contrast_color():
    src = _src(DOC_PROFORMA)
    fn_start = src.index("function EJDocCompliance")
    closing = src.index("\nfunction ", fn_start + 1)
    body = src[fn_start:closing]
    assert "#64748B" not in body[:400], \
        "EJDocCompliance wrapper still uses low-contrast color #64748B"
    assert "#334155" in body[:400], \
        "EJDocCompliance wrapper does not use high-contrast color #334155"


# ── Rule #3: Payment due fallback ─────────────────────────────────────────────

def test_payment_due_uses_terms_days_fallback():
    src = _src(PROFORMA_DETAIL)
    assert "payment_terms_days" in src, \
        "payment_terms_days not used — payment due fallback is missing"


def test_payment_due_checks_wfirma_payment_due():
    src = _src(PROFORMA_DETAIL)
    assert "wfirma_payment_due" in src, \
        "wfirma_payment_due not referenced — post-wFirma due date will be ignored"


# ── Rule #9: PL/EN descriptions ───────────────────────────────────────────────

def test_description_pl_mapped_from_editable_lines():
    src = _src(PROFORMA_DETAIL)
    assert "description_pl" in src, \
        "description_pl not mapped from editable_lines in lines array"


def test_description_en_mapped_from_editable_lines():
    src = _src(PROFORMA_DETAIL)
    assert "description_en" in src or "desc_en" in src, \
        "description_en / desc_en not mapped from editable_lines"


def test_doc_renders_desc_en_and_desc_pl():
    src = _src(DOC_PROFORMA)
    assert "desc_en" in src, "doc template does not reference desc_en for EN description"
    assert "desc_pl" in src, "doc template does not reference desc_pl for PL description"


# ── Rule #8: Origin fallback ──────────────────────────────────────────────────

def test_origin_fallback_uses_origin_country():
    src = _src(PROFORMA_DETAIL)
    assert "origin_country" in src, \
        "origin_country not in origin fallback chain — line items may show '—' for origin"
