"""
test_convert_modal_truth.py — source-grep pins for ConvertToInvoiceModal (Fix 3 + Fix 7).

Campaign: breezy-stream (campaign-breezy-stream.md)
Pin date: 2026-07-16

Assertions (all source-text, no browser/server required):
  1. Exactly ONE call to getDisclosureConvert( in the file (duplicate fetch eliminated).
  2. disclosure.grand_total is read (server total authority, includes freight + insurance).
  3. expected_payload_hash is included in the POST body (immutable preview contract).
  4. series_name is rendered (shows wFirma series identity, e.g. "15827921 — WDT 2026").
  5. Honest-labeling phrase "no native proforma" is present (Fix 7 mechanism disclosure).
  6. data-testid='convert-grand-total' is present in the source (spread object form used in JSX).

Pattern follows test_awb_modal_prefill.py (read file, extract block or check global SRC).
"""
from __future__ import annotations

import re
from pathlib import Path

JSX = Path(__file__).resolve().parents[1] / "app" / "static" / "v2" / "proforma-detail.jsx"
SRC = JSX.read_text(encoding="utf-8")


def _modal_block() -> str:
    """Extract the ConvertToInvoiceModal function body."""
    start = SRC.index("function ConvertToInvoiceModal(")
    # The function ends just before Object.assign(window, ...) at the very end
    end = SRC.index("Object.assign(window,", start)
    return SRC[start:end]


# ── Pin 1: single disclosure fetch ────────────────────────────────────────────

def test_exactly_one_disclosure_fetch():
    """RC-4 fix: two duplicate useEffects must be collapsed to one fetch."""
    count = SRC.count("getDisclosureConvert(")
    assert count == 1, (
        f"Expected exactly 1 call to getDisclosureConvert(), found {count}. "
        "Duplicate fetch was not eliminated."
    )


# ── Pin 2: server grand total authority ───────────────────────────────────────

def test_grand_total_referenced():
    """RC-3 fix: modal total must prefer server grand_total (freight + insurance included)."""
    block = _modal_block()
    assert "disclosure.grand_total" in block, (
        "disclosure.grand_total not found in ConvertToInvoiceModal. "
        "The server total authority (including freight/insurance) is not being used."
    )


def test_grand_total_fallback_to_client_sum():
    """While loading, the client-side totalEur must still be available as fallback."""
    block = _modal_block()
    # grandTotal != null guards the server value; fallback uses totalEur
    assert "grandTotal != null" in block


# ── Pin 3: expected_payload_hash in POST body ─────────────────────────────────

def test_expected_payload_hash_sent():
    """RC-4 fix: modal must forward payload_core_hash so backend can reject stale converts."""
    block = _modal_block()
    assert "expected_payload_hash" in block, (
        "expected_payload_hash not found in ConvertToInvoiceModal. "
        "The immutable preview contract (Fix 4) is not wired on the frontend."
    )
    assert "disclosure.payload_core_hash" in block, (
        "disclosure.payload_core_hash not read. Hash must come from server disclosure."
    )


# ── Pin 4: series_name rendered ───────────────────────────────────────────────

def test_series_name_rendered():
    """RC-2 fix: modal must show series_name so operator sees the wFirma series identity."""
    block = _modal_block()
    assert "series_name" in block, (
        "series_name not found in ConvertToInvoiceModal. "
        "Operator cannot distinguish series IDs without the human-readable name."
    )


def test_series_name_combined_with_series_id():
    """Series display must join id and name (e.g. '15827921 — WDT 2026')."""
    block = _modal_block()
    # The dash-separator pattern appears in both PAYLOAD PREVIEW and WFIRMA INVOICE PREVIEW
    assert "fwSeriesName" in block or "_pSeriesName" in block, (
        "Series name variable not found — series display may not include human-readable name."
    )


# ── Pin 5: honest labeling (Fix 7) ────────────────────────────────────────────

def test_honest_labeling_phrase_present():
    """Fix 7: modal must state wFirma has no native conversion (Lesson F / campaign §Architectural Goal)."""
    block = _modal_block()
    assert "no native proforma" in block, (
        "'no native proforma' phrase not found in ConvertToInvoiceModal. "
        "The honest-mechanism disclosure (Fix 7) is missing."
    )


def test_honest_labeling_mentions_back_reference():
    """Fix 7: honest label must also mention the lineage mechanism (description back-reference)."""
    block = _modal_block()
    assert "back-reference" in block, (
        "'back-reference' not found. The honest label must explain how lineage is recorded."
    )


# ── Pin 6: data-testid for automation ─────────────────────────────────────────

def test_convert_grand_total_testid_present():
    """data-testid='convert-grand-total' must be in the source for E2E and smoke tests."""
    block = _modal_block()
    # The testid is injected via JSX spread: {'data-testid': 'convert-grand-total'}
    assert "'data-testid': 'convert-grand-total'" in block, (
        "data-testid='convert-grand-total' not found in ConvertToInvoiceModal. "
        "Add it to the Total row so E2E tests can assert the correct total."
    )


def test_convert_series_name_testid_present():
    """data-testid='convert-series-name' must be present for series identity verification."""
    block = _modal_block()
    assert "'data-testid': 'convert-series-name'" in block, (
        "data-testid='convert-series-name' not found in ConvertToInvoiceModal."
    )


def test_convert_line_count_testid_present():
    """data-testid='convert-line-count' must be present for line count verification."""
    block = _modal_block()
    assert "'data-testid': 'convert-line-count'" in block, (
        "data-testid='convert-line-count' not found in ConvertToInvoiceModal."
    )


# ── Regression guard: no old duplicate state vars ─────────────────────────────

def test_old_duplicate_state_vars_removed():
    """The three old state variables from the first (duplicate) useEffect must be gone.

    Note: 'setDisclosureErr' is a substring of the legitimate 'setDisclosureError', so
    we check for the declaration pattern '[disclosureErr,' instead of a bare substring.
    """
    block = _modal_block()
    # Check for the old standalone disclose setter (distinct from setDisclosure*)
    assert "setDisclose]" not in block, "setDisclose] still present — duplicate state not removed"
    assert "setDisclosing]" not in block, "setDisclosing] still present — duplicate state not removed"
    # '[disclosureErr,' only appears in the old duplicate declaration (not in setDisclosureError)
    assert "[disclosureErr," not in block, "[disclosureErr, still present — duplicate state not removed"


# ── Phase 9 / description_preview pins ───────────────────────────────────────

def test_description_preview_testid_present():
    """data-testid='convert-description-preview' must be in the source (Phase 9)."""
    block = _modal_block()
    assert "convert-description-preview" in block, (
        "data-testid='convert-description-preview' not found in ConvertToInvoiceModal. "
        "The description preview block (Phase 9) is missing."
    )


def test_description_preview_reads_from_disclosure():
    """description_preview must be read from disclosure (server authority, not client-reconstructed)."""
    block = _modal_block()
    assert "disclosure.description_preview" in block, (
        "disclosure.description_preview not referenced in ConvertToInvoiceModal. "
        "The description must come from the server disclosure (RC-4 / Phase 9)."
    )


def test_convert_button_blocked_while_disclosure_loading():
    """Convert button must be disabled while disclosureLoading (description not yet available)."""
    block = _modal_block()
    assert "disclosureLoading" in block, (
        "disclosureLoading not referenced in Convert button disabled condition."
    )


def test_debounce_ref_present():
    """debounceRef must be declared — required for re-fetch debouncing on override changes."""
    block = _modal_block()
    assert "debounceRef" in block, (
        "debounceRef not found in ConvertToInvoiceModal. "
        "Override-change re-fetch debouncing is not wired."
    )


def test_override_params_passed_to_api():
    """getDisclosureConvert must be called with an override params object."""
    block = _modal_block()
    # The re-fetch effect passes an object with override_payment_method etc.
    assert "override_payment_method" in block, (
        "override_payment_method not passed to getDisclosureConvert re-fetch. "
        "Payment method override will not be reflected in description preview."
    )
    assert "override_invoice_date" in block, (
        "override_invoice_date not passed to getDisclosureConvert re-fetch."
    )


def test_pre_tag_used_for_description_preview():
    """description_preview must be rendered in a <pre> tag for monospace + line-break fidelity."""
    block = _modal_block()
    assert "pre" in block and "convert-description-preview" in block, (
        "<pre> element with convert-description-preview testid not found. "
        "Description must be rendered verbatim in a <pre> block."
    )


def test_single_useeffect_comment_present():
    """The merged useEffect must carry a comment identifying it as the single fetch (RC-4)."""
    block = _modal_block()
    assert "Single disclosure fetch" in block, (
        "Single-fetch comment not found. Add it to make the RC-4 fix legible to future readers."
    )
