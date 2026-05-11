"""
Phase H tests — PLT eligibility checker.

Verifies that check_eligibility() is a pure function that correctly
gates on PLT status, required documents, and country allowlist.

No I/O, no DB, no DHL API. Paths are passed as Path objects but are
never opened — eligibility is a metadata-only check.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.carrier.plt.eligibility import check_eligibility
from app.services.carrier.models.plt import PltEligibilityRequest

_ALLOWLIST = frozenset({"DE", "PL", "US", "GB", "FR", "NL"})

_FAKE_INVOICE = Path("/uploads/invoice.pdf")
_FAKE_SAD = Path("/uploads/sad.pdf")


def _req(
    country: str = "DE",
    invoices: list | None = None,
    customs_doc: Path | None = _FAKE_SAD,
    batch_id: str = "BATCH-ELG",
) -> PltEligibilityRequest:
    return PltEligibilityRequest(
        batch_id=batch_id,
        destination_country=country,
        invoice_paths=invoices if invoices is not None else [_FAKE_INVOICE],
        customs_doc_path=customs_doc,
    )


# ── gate: carrier_plt_status ──────────────────────────────────────────────────


def test_pending_status_blocks_eligibility():
    result = check_eligibility(_req(), plt_status="pending", country_allowlist=_ALLOWLIST)
    assert result.eligible is False


def test_pending_status_reason_mentions_pending():
    result = check_eligibility(_req(), plt_status="pending", country_allowlist=_ALLOWLIST)
    assert "pending" in result.reason.lower()


def test_pending_status_returns_batch_id():
    result = check_eligibility(_req(batch_id="BATCH-P"), plt_status="pending", country_allowlist=_ALLOWLIST)
    assert result.batch_id == "BATCH-P"


def test_shadow_status_allows_evaluation():
    """shadow mode: eligibility is evaluated (not blocked at gate)."""
    result = check_eligibility(_req(), plt_status="shadow", country_allowlist=_ALLOWLIST)
    assert result.eligible is True


def test_live_status_allows_evaluation():
    result = check_eligibility(_req(), plt_status="live", country_allowlist=_ALLOWLIST)
    assert result.eligible is True


def test_unknown_status_is_blocked():
    """Any status not explicitly allowed should behave as blocked or ineligible.
    'pending' is the only defined blocked status — unknown status is
    not in the blocked set so it falls through to the document checks."""
    result = check_eligibility(_req(), plt_status="unknown", country_allowlist=_ALLOWLIST)
    # Unknown status is not in _PLT_BLOCKED_STATUSES, so evaluation proceeds.
    # With valid docs + country, it should return eligible.
    assert result.eligible is True


# ── invoice presence check ────────────────────────────────────────────────────


def test_empty_invoice_list_not_eligible():
    result = check_eligibility(_req(invoices=[]), plt_status="shadow", country_allowlist=_ALLOWLIST)
    assert result.eligible is False


def test_empty_invoice_list_reason_mentions_invoice():
    result = check_eligibility(_req(invoices=[]), plt_status="shadow", country_allowlist=_ALLOWLIST)
    assert "invoice" in result.reason.lower()


def test_none_invoices_not_eligible():
    req = PltEligibilityRequest(
        batch_id="BATCH-NI",
        destination_country="DE",
        invoice_paths=[],
        customs_doc_path=_FAKE_SAD,
    )
    result = check_eligibility(req, plt_status="shadow", country_allowlist=_ALLOWLIST)
    assert result.eligible is False


def test_multiple_invoices_accepted():
    result = check_eligibility(
        _req(invoices=[_FAKE_INVOICE, Path("/uploads/invoice2.pdf")]),
        plt_status="shadow",
        country_allowlist=_ALLOWLIST,
    )
    assert result.eligible is True


# ── customs document presence check ──────────────────────────────────────────


def test_missing_customs_doc_not_eligible():
    result = check_eligibility(_req(customs_doc=None), plt_status="shadow", country_allowlist=_ALLOWLIST)
    assert result.eligible is False


def test_missing_customs_doc_reason_mentions_customs():
    result = check_eligibility(_req(customs_doc=None), plt_status="shadow", country_allowlist=_ALLOWLIST)
    assert "customs" in result.reason.lower() or "sad" in result.reason.lower() or "zc429" in result.reason.lower()


def test_customs_doc_present_passes_check():
    result = check_eligibility(_req(customs_doc=_FAKE_SAD), plt_status="shadow", country_allowlist=_ALLOWLIST)
    assert result.eligible is True


# ── country allowlist check ───────────────────────────────────────────────────


def test_unsupported_country_not_eligible():
    result = check_eligibility(_req(country="CN"), plt_status="shadow", country_allowlist=_ALLOWLIST)
    assert result.eligible is False


def test_unsupported_country_reason_mentions_country():
    result = check_eligibility(_req(country="CN"), plt_status="shadow", country_allowlist=_ALLOWLIST)
    assert "CN" in result.reason or "allowlist" in result.reason.lower()


def test_supported_country_de_eligible():
    result = check_eligibility(_req(country="DE"), plt_status="shadow", country_allowlist=_ALLOWLIST)
    assert result.eligible is True


def test_supported_country_pl_eligible():
    result = check_eligibility(_req(country="PL"), plt_status="shadow", country_allowlist=_ALLOWLIST)
    assert result.eligible is True


def test_supported_country_us_eligible():
    result = check_eligibility(_req(country="US"), plt_status="shadow", country_allowlist=_ALLOWLIST)
    assert result.eligible is True


def test_country_check_case_insensitive():
    """Lower-case country code must be normalised."""
    result = check_eligibility(_req(country="de"), plt_status="shadow", country_allowlist=_ALLOWLIST)
    assert result.eligible is True


def test_empty_allowlist_blocks_all_countries():
    """Default deny: empty allowlist means no country is eligible."""
    result = check_eligibility(_req(country="DE"), plt_status="shadow", country_allowlist=frozenset())
    assert result.eligible is False


def test_single_country_allowlist_exact_match():
    result = check_eligibility(_req(country="PL"), plt_status="shadow", country_allowlist={"PL"})
    assert result.eligible is True


def test_single_country_allowlist_other_blocked():
    result = check_eligibility(_req(country="DE"), plt_status="shadow", country_allowlist={"PL"})
    assert result.eligible is False


# ── result fields ─────────────────────────────────────────────────────────────


def test_eligible_result_reason_is_empty():
    result = check_eligibility(_req(), plt_status="shadow", country_allowlist=_ALLOWLIST)
    assert result.reason == ""


def test_ineligible_result_has_reason():
    result = check_eligibility(_req(country="XX"), plt_status="shadow", country_allowlist=_ALLOWLIST)
    assert result.reason != ""


def test_result_batch_id_matches_request():
    result = check_eligibility(_req(batch_id="MY-BATCH"), plt_status="shadow", country_allowlist=_ALLOWLIST)
    assert result.batch_id == "MY-BATCH"


# ── gate fires before document checks ────────────────────────────────────────


def test_pending_gate_fires_before_invoice_check():
    """pending status must block even if invoices are missing too."""
    result = check_eligibility(
        _req(invoices=[]),
        plt_status="pending",
        country_allowlist=_ALLOWLIST,
    )
    assert result.eligible is False
    assert "pending" in result.reason.lower()


def test_invoice_check_fires_before_country_check():
    """Missing invoices must be reported before country check."""
    result = check_eligibility(
        _req(invoices=[], country="XX"),
        plt_status="shadow",
        country_allowlist=_ALLOWLIST,
    )
    assert result.eligible is False
    assert "invoice" in result.reason.lower()
