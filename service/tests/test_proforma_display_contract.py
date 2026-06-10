"""
PR A — Proforma Display Contract Lock (2026-06-10)
PR C — Payment-due / bank / address authority extension (2026-06-10)

Source-grep regression contract for the display rules fixed in PR A, plus
real-builder payment-terms resolution tests added in PR C (Lesson A: the
REAL ProformaDraft dataclass through the REAL _resolve_effective_payment_terms
and _draft_to_full — no stubs of the builders under test).
Regression baseline: Draft #24 (PROF 123/2026, UAB Tomas Gold, €79,000.23).

Rules locked (PR A):
  #3  Payment due calculation uses payment_terms_days fallback
  #5  Bank details populated from companyProfile (real flat iban_* fields —
      browser verification 2026-06-10 proved bank_accounts does not exist
      in the company-profile API; PR C corrected the lock to the real shape)
  #6  Footer payment terms driven by paymentDays prop (not hardcoded '7 days')
  #7  Footer contrast: fontSize 10, color #334155
  #8  Origin fallback chain: ln.origin || origin_country || companyProfile.country
  #9  PL/EN descriptions: desc_pl + desc_en mapped from editable_lines
  #10 Country codes expanded via COUNTRY_NAMES lookup (_expandCountry applied ≥2×)

Rules locked (PR C):
  - _draft_to_full serializes wfirma_issue_date / wfirma_payment_due /
    payment_terms_days / payment_terms_source / effective_payment_due /
    payment_due_source (root cause of 'PAYMENT DUE —' on posted proformas)
  - payment_terms_days display chain: draft → Customer Master → None;
    due chain: wfirma → computed(base+days) → None; never invented.
    wFirma POST authority UNCHANGED (ADR-027, pinned by tests I7/I9).
  - Compliance footer never invents '7 days'; neutral wording when unknown
  - Missing-bank operator warning visible in modal chrome, print-hidden
  - Address joins normalised via _joinAddr (no '20-1,, Klaipėda' renders)
  - Overview tab reads effective_payment_due (not nonexistent payment_due_date)
"""
import re
import sqlite3
from pathlib import Path

import pytest

from app.services.customer_master_db import CustomerMaster
from app.services import proforma_invoice_link_db as pildb

_ROOT = Path(__file__).parent.parent
PROFORMA_DETAIL = _ROOT / "app" / "static" / "v2" / "proforma-detail.jsx"
DOC_PROFORMA    = _ROOT / "app" / "static" / "v2" / "estrella-doc-proforma.jsx"
ROUTES_PROFORMA = _ROOT / "app" / "api" / "routes_proforma.py"


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
    """PR C correction: the company-profile API serves flat per-currency
    fields (iban_eur / iban_usd / iban_pln + swift + bank_name). The
    bank_accounts array locked by the original PR A test does not exist —
    mapping it rendered the bank block empty on every printed document
    (browser-proven on PROF 123/2026, 2026-06-10)."""
    src = _src(PROFORMA_DETAIL)
    assert "bank_accounts" not in src, \
        "phantom companyProfile.bank_accounts referenced — field does not exist in the API"
    for fld in ("iban_eur", "iban_usd", "iban_pln"):
        assert fld in src, f"banks mapping must read companyProfile.{fld}"
    assert "p.swift" in src and "p.bank_name" in src, \
        "banks mapping must carry swift + bank_name from the company profile"


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

def _compliance_wrapper_style(src: str) -> str:
    """First 400 chars of the EJDocCompliance wrapper div — anchored at the
    function's `return (` so lines added above the JSX (PR C terms logic)
    cannot shift the window off the wrapper style."""
    fn_start = src.index("function EJDocCompliance")
    closing = src.index("\nfunction ", fn_start + 1)
    body = src[fn_start:closing]
    return body[body.index("return ("):][:400]


def test_compliance_footer_font_size_10():
    wrapper = _compliance_wrapper_style(_src(DOC_PROFORMA))
    # Must contain fontSize: 10 in the outer wrapper div
    m = re.search(r"fontSize[:\s]+(\d+)", wrapper)
    assert m, "No fontSize found near EJDocCompliance wrapper"
    assert int(m.group(1)) >= 10, \
        f"EJDocCompliance wrapper fontSize is {m.group(1)} — expected ≥10 for print readability"


def test_compliance_footer_contrast_color():
    wrapper = _compliance_wrapper_style(_src(DOC_PROFORMA))
    assert "#64748B" not in wrapper, \
        "EJDocCompliance wrapper still uses low-contrast color #64748B"
    assert "#334155" in wrapper, \
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


# ═══ PR C — real-builder payment-terms resolution (Lesson A) ═══════════════
#
# Display authority chain (POST authority untouched — ADR-027 reads Customer
# Master directly for <paymentdays>, pinned by tests I7/I9):
#
#   payment_terms_days:    draft.payment_terms_json["days"] (int > 0)
#                          → Customer Master payment_terms_days → None
#   effective_payment_due: wfirma_payment_due
#                          → (wfirma_issue_date or created_at) + days → None

def _draft(**kw) -> "pildb.ProformaDraft":
    """Real ProformaDraft via the real frozen dataclass."""
    base = dict(batch_id="B-CONTRACT", client_name="UAB Tomas Gold",
                status="draft")
    base.update(kw)
    return pildb.ProformaDraft(**base)


def _cm(days) -> CustomerMaster:
    """Real CustomerMaster dataclass with the payment terms under test."""
    return CustomerMaster(
        bill_to_contractor_id="134920664",
        bill_to_name="UAB Tomas Gold",
        country="LT",
        payment_terms_days=days,
    )


def _resolved(found: bool, cid: str = "") -> dict:
    """Real-shape _resolve_customer result (see routes_proforma docstring)."""
    return {
        "raw_input":            "UAB Tomas Gold",
        # _normalize_client_name preserves case (trim + collapse only)
        "normalized_name":      "UAB Tomas Gold",
        "found":                found,
        "ambiguous":            False,
        "match_strategy":       "customer_master" if found else "none",
        "customer":             None,
        "wfirma_customer_id":   cid,
        "resolved_wfirma_name": "UAB Tomas Gold" if found else "",
        "candidates":           [],
        "advisory":             "",
    }


def test_days_from_draft_payment_terms_json():
    from app.api import routes_proforma as rp
    d = _draft(payment_terms_json='{"days": 90, "method": "transfer"}',
               created_at="2026-06-08T10:00:00Z")
    out = rp._resolve_effective_payment_terms(d)
    assert out["payment_terms_days"] == 90
    assert out["payment_terms_source"] == "draft"


def test_days_from_customer_master_when_draft_silent(monkeypatch):
    from app.api import routes_proforma as rp
    monkeypatch.setattr(rp, "_resolve_customer",
                        lambda name, batch_id=None: _resolved(True, "134920664"))
    monkeypatch.setattr(rp, "get_customer_master",
                        lambda db, cid: _cm(30))
    d = _draft(payment_terms_json="{}", created_at="2026-06-08T10:00:00Z")
    out = rp._resolve_effective_payment_terms(d)
    assert out["payment_terms_days"] == 30
    assert out["payment_terms_source"] == "customer_master"


def test_days_none_when_no_authority(monkeypatch):
    from app.api import routes_proforma as rp
    monkeypatch.setattr(rp, "_resolve_customer",
                        lambda name, batch_id=None: _resolved(False))
    d = _draft(payment_terms_json="{}", created_at="2026-06-08T10:00:00Z")
    out = rp._resolve_effective_payment_terms(d)
    assert out["payment_terms_days"] is None
    assert out["payment_terms_source"] is None
    assert out["effective_payment_due"] is None
    assert out["payment_due_source"] is None


def test_zero_days_is_not_authority(monkeypatch):
    """days=0 in the draft json means 'unset', not 'due immediately' —
    it must fall through to Customer Master."""
    from app.api import routes_proforma as rp
    monkeypatch.setattr(rp, "_resolve_customer",
                        lambda name, batch_id=None: _resolved(True, "134920664"))
    monkeypatch.setattr(rp, "get_customer_master",
                        lambda db, cid: _cm(14))
    d = _draft(payment_terms_json='{"days": 0}')
    out = rp._resolve_effective_payment_terms(d)
    assert out["payment_terms_days"] == 14
    assert out["payment_terms_source"] == "customer_master"


def test_due_wfirma_authority_wins():
    """Once wFirma stored a payment date, that date is the authority —
    even when local days would compute something else."""
    from app.api import routes_proforma as rp
    d = _draft(payment_terms_json='{"days": 90}',
               wfirma_issue_date="2026-06-08",
               wfirma_payment_due="2026-09-01",
               created_at="2026-06-08T10:00:00Z")
    out = rp._resolve_effective_payment_terms(d)
    assert out["effective_payment_due"] == "2026-09-01"
    assert out["payment_due_source"] == "wfirma"


def test_due_computed_from_wfirma_issue_date_plus_days():
    from app.api import routes_proforma as rp
    d = _draft(payment_terms_json='{"days": 90}',
               wfirma_issue_date="2026-06-08",
               created_at="2026-01-01T10:00:00Z")
    out = rp._resolve_effective_payment_terms(d)
    # issue date outranks created_at as the computation base
    assert out["effective_payment_due"] == "2026-09-06"
    assert out["payment_due_source"] == "computed"


def test_due_computed_from_created_at_when_no_issue_date():
    from app.api import routes_proforma as rp
    d = _draft(payment_terms_json='{"days": 30}',
               created_at="2026-06-01T08:30:00Z")
    out = rp._resolve_effective_payment_terms(d)
    assert out["effective_payment_due"] == "2026-07-01"
    assert out["payment_due_source"] == "computed"


def test_cm_lookup_failure_degrades_to_none(monkeypatch):
    """A broken Customer Master db must never break the detail endpoint —
    the projection degrades to None, no exception."""
    from app.api import routes_proforma as rp

    def _boom(name, batch_id=None):
        raise RuntimeError("simulated CM failure")

    monkeypatch.setattr(rp, "_resolve_customer", _boom)
    d = _draft(payment_terms_json="{}", created_at="2026-06-08T10:00:00Z")
    out = rp._resolve_effective_payment_terms(d)
    assert out["payment_terms_days"] is None
    assert out["effective_payment_due"] is None


def test_malformed_payment_terms_json_falls_through(monkeypatch):
    from app.api import routes_proforma as rp
    monkeypatch.setattr(rp, "_resolve_customer",
                        lambda name, batch_id=None: _resolved(False))
    d = _draft(payment_terms_json="{not json",
               created_at="2026-06-08T10:00:00Z")
    out = rp._resolve_effective_payment_terms(d)
    assert out["payment_terms_days"] is None


def test_non_numeric_days_falls_through_to_customer_master(monkeypatch):
    """days="abc" raises inside int() — contained, falls to CM."""
    from app.api import routes_proforma as rp
    monkeypatch.setattr(rp, "_resolve_customer",
                        lambda name, batch_id=None: _resolved(True, "134920664"))
    monkeypatch.setattr(rp, "get_customer_master",
                        lambda db, cid: _cm(14))
    d = _draft(payment_terms_json='{"days": "abc"}',
               created_at="2026-06-08T10:00:00Z")
    out = rp._resolve_effective_payment_terms(d)
    assert out["payment_terms_days"] == 14
    assert out["payment_terms_source"] == "customer_master"


def test_negative_days_is_not_authority(monkeypatch):
    """days=-5 means corrupted input, not 'overdue at birth' — fall to CM."""
    from app.api import routes_proforma as rp
    monkeypatch.setattr(rp, "_resolve_customer",
                        lambda name, batch_id=None: _resolved(True, "134920664"))
    monkeypatch.setattr(rp, "get_customer_master",
                        lambda db, cid: _cm(21))
    d = _draft(payment_terms_json='{"days": -5}',
               created_at="2026-06-08T10:00:00Z")
    out = rp._resolve_effective_payment_terms(d)
    assert out["payment_terms_days"] == 21
    assert out["payment_terms_source"] == "customer_master"


def test_malformed_issue_date_degrades_due_to_none():
    """A garbage wfirma_issue_date must not 500 and must not invent a due
    date — days survive, due degrades to None."""
    from app.api import routes_proforma as rp
    d = _draft(payment_terms_json='{"days": 90}',
               wfirma_issue_date="not-a-date",
               created_at="")
    out = rp._resolve_effective_payment_terms(d)
    assert out["payment_terms_days"] == 90
    assert out["effective_payment_due"] is None
    assert out["payment_due_source"] is None


def test_no_date_base_means_no_computed_due():
    """days known but neither wfirma_issue_date nor created_at present —
    nothing to compute from; unknown stays unknown."""
    from app.api import routes_proforma as rp
    d = _draft(payment_terms_json='{"days": 90}',
               wfirma_issue_date="",
               created_at="")
    out = rp._resolve_effective_payment_terms(d)
    assert out["payment_terms_days"] == 90
    assert out["effective_payment_due"] is None
    assert out["payment_due_source"] is None


def test_draft_to_full_serializes_payment_authority_fields():
    """Root cause of the 'PAYMENT DUE —' defect: wfirma_issue_date /
    wfirma_payment_due were stored on the dataclass but never serialized,
    and payment_terms_days never existed in the response. Pin all six."""
    from app.api import routes_proforma as rp
    d = _draft(payment_terms_json='{"days": 90, "method": "transfer"}',
               wfirma_issue_date="2026-06-08",
               wfirma_payment_due="2026-09-06",
               created_at="2026-06-08T10:00:00Z",
               editable_lines_json='[{"product_code":"X","qty":1,"unit_price":2.5}]')
    full = rp._draft_to_full(d)
    assert full["wfirma_issue_date"] == "2026-06-08"
    assert full["wfirma_payment_due"] == "2026-09-06"
    assert full["payment_terms_days"] == 90
    assert full["payment_terms_source"] == "draft"
    assert full["effective_payment_due"] == "2026-09-06"
    assert full["payment_due_source"] == "wfirma"
    # the dict payload the UI edits stays intact alongside the resolution
    assert full["payment_terms"] == {"days": 90, "method": "transfer"}


# ═══ PR C — source-grep contract locks ═════════════════════════════════════

def test_backend_serializes_payment_fields_in_draft_to_full():
    src = _src(ROUTES_PROFORMA)
    assert "_resolve_effective_payment_terms(d)" in src
    assert '"wfirma_issue_date":     d.wfirma_issue_date' in src
    assert '"wfirma_payment_due":    d.wfirma_payment_due' in src


def _func_body(src: str, defname: str) -> str:
    """Slice a top-level function body: from its def line to the next
    column-0 ``def``. Nested defs are indented and don't terminate it."""
    start = src.index(f"def {defname}(")
    nxt = src.find("\ndef ", start + 1)
    return src[start:nxt if nxt != -1 else len(src)]


def test_backend_post_authority_unchanged_marker():
    """Display resolution must stay display-only (ADR-027): neither wFirma
    POST payload builder may call the display helper. The preview builder
    must keep reading Customer Master directly for <paymentdays>."""
    src = _src(ROUTES_PROFORMA)
    assert "ADR-027" in src
    for builder in ("_build_proforma_request",
                    "_build_proforma_request_from_draft"):
        body = _func_body(src, builder)
        assert "_resolve_effective_payment_terms" not in body, (
            f"{builder} must not consume the display-only payment "
            "resolution — POST authority is Customer Master (ADR-027)"
        )
    assert "cm_payment_terms_days" in _func_body(src, "_build_proforma_request")


def test_payment_due_fallback_chain_in_preview():
    src = _src(PROFORMA_DETAIL)
    assert "liveDraft.effective_payment_due" in src
    assert "liveDraft.wfirma_payment_due" in src
    # local compute base prefers the wFirma issue date
    assert ("liveDraft.wfirma_issue_date || liveDraft.invoice_date "
            "|| liveDraft.created_at") in src


def test_payment_days_read_from_serialized_field_with_dict_fallback():
    src = _src(PROFORMA_DETAIL)
    assert "liveDraft.payment_terms_days" in src
    assert "rawPt.days" in src


def test_overview_payment_due_reads_effective_field():
    src = _src(PROFORMA_DETAIL)
    assert "detail.payment_due_date" not in src, \
        "Overview tab must not read the nonexistent payment_due_date field"
    assert "detail.effective_payment_due || detail.wfirma_payment_due" in src


def test_compliance_footer_never_invents_seven_days():
    """No '7 days' literal anywhere in the doc template: real days →
    'within N days'; known due date → 'by <date>'; otherwise neutral
    wording. A fabricated default on a customer-facing document is a
    legal/accounting risk."""
    doc = _src(DOC_PROFORMA)
    assert "'7 days'" not in doc and '"7 days"' not in doc
    assert "Payment due as agreed in the order terms." in doc


def test_missing_bank_warning_is_visible_and_print_hidden():
    """Lesson M: missing bank details surface as an explicit operator
    warning in the modal chrome — not silence. The printed document keeps
    its neutral fallback, so the warning is print-hidden."""
    src = _src(PROFORMA_DETAIL)
    assert 'data-testid="preview-missing-bank-warning"' in src
    assert ".ej-preview-warn { display: none !important; }" in src


# ═══ PR C — HTTP round-trip: effective fields reach the JSON response ══════

@pytest.fixture()
def _http_client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    from app.services import wfirma_db as wfdb
    from app.services import proforma_service_charges_db as scdb
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    pildb.init_db(tmp_path / "proforma_links.db")
    scdb.init(tmp_path / "proforma_links.db")
    from app.main import app
    from app.auth.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "t", "email": "t@local",
    }
    from fastapi.testclient import TestClient
    yield TestClient(app), tmp_path
    app.dependency_overrides.clear()


def test_http_get_draft_returns_effective_payment_fields(_http_client):
    """Integration lock: the resolution is not just a helper — the fields
    must actually reach the GET /api/v1/proforma/draft/{id} JSON payload
    the V2 page renders from."""
    cli, tmp = _http_client
    db = tmp / "proforma_links.db"
    with sqlite3.connect(str(db)) as conn:
        pildb._ensure_drafts_table(conn)
        now = pildb._now_utc_iso()
        cur = conn.execute(
            "INSERT INTO proforma_drafts (batch_id, client_name, status, "
            "currency, draft_state, draft_version, source_lines_json, "
            "editable_lines_json, payment_terms_json, wfirma_issue_date, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("B-RT", "RT Client", "draft", "EUR", "editing", 1, "[]",
             '[{"product_code":"X","qty":1,"unit_price":2.5}]',
             '{"days": 90}', "2026-06-08", now, now),
        )
        draft_id = int(cur.lastrowid)
        conn.commit()

    r = cli.get(f"/api/v1/proforma/draft/{draft_id}")
    assert r.status_code == 200, r.text
    body = r.json()["draft"]
    assert body["payment_terms_days"] == 90
    assert body["payment_terms_source"] == "draft"
    assert body["effective_payment_due"] == "2026-09-06"
    assert body["payment_due_source"] == "computed"
    assert body["wfirma_issue_date"] == "2026-06-08"


def test_address_joins_normalised_via_joinaddr():
    """Trailing commas in stored address parts (Customer Master rows,
    buyer overrides) must not render as '20-1,, Klaipėda'. All three
    party address joins go through _joinAddr."""
    src = _src(PROFORMA_DETAIL)
    assert "const _joinAddr" in src
    assert src.count("_joinAddr([") >= 3, \
        "exporter, buyer and ship-to address joins must all use _joinAddr"
    assert "[bo.street, bo.city, bo.zip].filter(Boolean).join" not in src
