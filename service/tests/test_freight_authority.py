"""Freight authority service — unit tests (2026-05-22).

derive_freight_authority() is the single backend authority for freight
parse-status. These tests pin all four status values and the PLN/USD
conversion logic, ensuring no internal wording leaks to the frontend.

Status values locked by these tests:
  parsed_positive    — freight_usd > 0 OR found_count > 0 with total == 0
  confidently_absent — found_count == 0, invoice_totals present
  unparsed           — invoice_totals present, found_count absent (old audit)
  missing_invoice    — invoice_totals absent from audit
"""
from __future__ import annotations

import pytest

from app.services.freight_authority import derive_freight_authority

# ── helpers ───────────────────────────────────────────────────────────────────

def _audit(*, invoice_totals=None, exchange_rate=None, sad_rate=None):
    a: dict = {}
    if invoice_totals is not None:
        a["invoice_totals"] = invoice_totals
    if exchange_rate is not None:
        a["customs_declaration"] = {"exchange_rate": exchange_rate}
    elif sad_rate is not None:
        a["clearance_decision"] = {"sad_customs_rate": sad_rate}
    return a


# ── 1. missing_invoice when invoice_totals absent ─────────────────────────────

def test_missing_invoice_totals_returns_missing_invoice():
    r = derive_freight_authority({})
    assert r["freight_status"] == "missing_invoice"
    assert r["freight_pln"]    is None
    assert r["freight_usd"]    is None
    assert r["freight_source"] is None


def test_empty_invoice_totals_returns_missing_invoice():
    r = derive_freight_authority({"invoice_totals": None})
    assert r["freight_status"] == "missing_invoice"


# ── 2. parsed_positive when freight_usd > 0 ───────────────────────────────────

def test_positive_freight_returns_parsed_positive():
    r = derive_freight_authority(_audit(invoice_totals={
        "total_freight_usd": 123.45,
        "freight_found_count": 1,
    }))
    assert r["freight_status"] == "parsed_positive"
    assert r["freight_usd"]    == 123.45
    assert r["freight_review_reason"] is None


def test_positive_freight_computes_pln_when_rate_present():
    r = derive_freight_authority(_audit(
        invoice_totals={"total_freight_usd": 100.0, "freight_found_count": 1},
        exchange_rate=4.0,
    ))
    assert r["freight_status"] == "parsed_positive"
    assert r["freight_pln"]    == 400.0


def test_positive_freight_pln_none_when_no_rate():
    r = derive_freight_authority(_audit(
        invoice_totals={"total_freight_usd": 100.0, "freight_found_count": 1},
    ))
    assert r["freight_status"] == "parsed_positive"
    assert r["freight_pln"]    is None
    assert r["freight_usd"]    == 100.0


def test_sad_customs_rate_used_as_fallback():
    r = derive_freight_authority(_audit(
        invoice_totals={"total_freight_usd": 50.0, "freight_found_count": 1},
        sad_rate=3.8,
    ))
    assert r["freight_pln"] == pytest.approx(190.0, abs=0.01)


# ── 3. confidently_absent when found_count == 0 ───────────────────────────────

def test_zero_freight_with_found_count_zero_returns_confidently_absent():
    r = derive_freight_authority(_audit(invoice_totals={
        "total_freight_usd": 0.0,
        "freight_found_count": 0,
    }))
    assert r["freight_status"] == "confidently_absent"
    assert r["freight_usd"]    == 0.0
    assert r["freight_review_reason"] is None


def test_confidently_absent_pln_is_none():
    r = derive_freight_authority(_audit(
        invoice_totals={"total_freight_usd": 0.0, "freight_found_count": 0},
        exchange_rate=4.0,
    ))
    assert r["freight_status"] == "confidently_absent"
    # PLN is None (not 0.0) — caller renders '0.00 PLN' from status, not from pln
    assert r["freight_pln"] is None


# ── 4. unparsed when found_count absent (old audit.json) ─────────────────────

def test_zero_freight_with_no_annotation_returns_unparsed():
    r = derive_freight_authority(_audit(invoice_totals={
        "total_freight_usd": 0.0,
        # no freight_found_count key
    }))
    assert r["freight_status"] == "unparsed"
    assert r["freight_review_reason"] is not None


def test_unparsed_has_review_reason_string():
    r = derive_freight_authority(_audit(invoice_totals={"total_freight_usd": 0.0}))
    reason = r["freight_review_reason"]
    assert isinstance(reason, str) and len(reason) > 0


# ── 5. found_count > 0, freight == 0 ─────────────────────────────────────────

def test_zero_freight_with_found_count_positive_is_parsed_positive():
    """Freight row found but amount parsed as zero → treated as explicit zero."""
    r = derive_freight_authority(_audit(invoice_totals={
        "total_freight_usd": 0.0,
        "freight_found_count": 1,
    }))
    assert r["freight_status"] == "parsed_positive"
    assert r["freight_pln"]    == 0.0
    assert r["freight_usd"]    == 0.0


# ── 6. no internal wording leaks ──────────────────────────────────────────────

def test_derivation_never_returns_no_freight_on_invoices_string():
    banned = "No freight on invoices"
    for case in [
        {},
        _audit(invoice_totals={"total_freight_usd": 0.0}),
        _audit(invoice_totals={"total_freight_usd": 0.0, "freight_found_count": 0}),
        _audit(invoice_totals={"total_freight_usd": 100.0, "freight_found_count": 1}),
    ]:
        r = derive_freight_authority(case)
        for v in r.values():
            assert banned not in str(v), f"Banned phrase found in {r}"


# ── 7. source-grep: freight_authority in routes_dashboard ────────────────────

def test_freight_authority_injected_in_batch_detail():
    from pathlib import Path
    src = (Path(__file__).parent.parent / "app" / "api" / "routes_dashboard.py"
           ).read_text(encoding="utf-8")
    assert "freight_authority" in src, (
        "routes_dashboard.py must inject freight_authority into batch response"
    )
    assert "derive_freight_authority" in src, (
        "routes_dashboard.py must call derive_freight_authority"
    )
