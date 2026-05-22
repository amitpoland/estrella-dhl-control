"""DHL clearance freight display wording — regression lock (2026-05-22).

The Freight (PLN) row in Section 1 — DHL Clearance Values must never
show operator-unsafe internal wording such as 'No freight on invoices'.

Approved display values:
  - freightPln computed          → formatted PLN amount (e.g. '1 234.56 PLN')
  - freightUsd > 0, no rate      → 'USD X.XX (rate not available)'
  - invoice_totals absent        → 'Not declared'
  - invoice_totals present, zero → '0.00 PLN'

Tests:
  1. 'No freight on invoices' never appears in shipment-detail.html.
  2. Approved fallback wording present for zero/absent freight case.
  3. Positive freight renders via fmtPLN path (source-grep).
  4. USD fallback wording present for freightUsd-without-rate case.
  5. 'Not declared' present for invoice_totals-absent case.
  6. DHL clearance routing logic (clearance_path) unchanged.
  7. Freight row is not removed (label still present).
  8. No internal/technical text in freight display branch.
"""
from __future__ import annotations

from pathlib import Path

HTML   = Path(__file__).resolve().parent.parent / "app" / "static" / "shipment-detail.html"
MARKER = "Freight (PLN)"


# ── 1. Banned wording never appears ──────────────────────────────────────────

def test_no_freight_on_invoices_text_absent():
    src = HTML.read_text(encoding="utf-8")
    assert "No freight on invoices" not in src, (
        "'No freight on invoices' must not appear anywhere in shipment-detail.html"
    )


# ── 2. Zero/absent freight fallback is '0.00 PLN' ────────────────────────────

def test_zero_freight_fallback_is_0_pln():
    src = HTML.read_text(encoding="utf-8")
    assert "'0.00 PLN'" in src or '"0.00 PLN"' in src, (
        "Zero/absent freight must render as '0.00 PLN'"
    )


# ── 3. Positive freight uses fmtPLN path ─────────────────────────────────────

def test_positive_freight_uses_fmtpln():
    src = HTML.read_text(encoding="utf-8")
    # freightPln path must call fmtPLN — confirmed by the IIFE structure
    freight_idx = src.find(MARKER)
    assert freight_idx > 0, f"'{MARKER}' label must still exist in shipment-detail.html"
    vicinity = src[freight_idx:freight_idx + 500]
    assert "fmtPLN(freightPln)" in vicinity, (
        "Positive freight (freightPln != null) must call fmtPLN(freightPln)"
    )


# ── 4. USD fallback wording present ──────────────────────────────────────────

def test_usd_fallback_wording_present():
    src = HTML.read_text(encoding="utf-8")
    assert "rate not available" in src, (
        "freightUsd-without-rate fallback must say 'rate not available'"
    )


# ── 5. 'Not declared' present for missing invoice_totals ─────────────────────

def test_not_declared_for_missing_invoice_totals():
    src = HTML.read_text(encoding="utf-8")
    assert "Not declared" in src, (
        "Missing invoice_totals case must render 'Not declared'"
    )
    # Must be gated on !audit.invoice_totals
    assert "audit.invoice_totals" in src, (
        "Freight fallback must check audit.invoice_totals to choose 'Not declared'"
    )


# ── 6. DHL clearance routing unchanged ───────────────────────────────────────

def test_dhl_clearance_routing_logic_unchanged():
    src = HTML.read_text(encoding="utf-8")
    assert "agency_clearance" in src, "agency_clearance path must remain"
    assert "dhl_self_clearance" in src, "dhl_self_clearance path must remain"
    assert "routing_pending" in src, "routing_pending path must remain"
    assert "clearance_path" in src, "clearance_path variable must remain"


# ── 7. Freight row label not removed ─────────────────────────────────────────

def test_freight_row_label_present():
    src = HTML.read_text(encoding="utf-8")
    assert f'label="{MARKER}"' in src or f"label='{MARKER}'" in src, (
        f"InfoRow with label='{MARKER}' must remain in Section 1"
    )


# ── 8. No internal/technical text in freight display branch ──────────────────

def test_no_internal_text_in_freight_display():
    src = HTML.read_text(encoding="utf-8")
    banned = [
        "No freight on invoices",
        "total_freight_usd",   # raw field name must not be displayed
        "invoice_totals.freight",
    ]
    freight_idx = src.find(MARKER)
    vicinity = src[freight_idx:freight_idx + 900]
    for phrase in banned:
        assert phrase not in vicinity, (
            f"Internal text '{phrase}' must not appear in freight display branch"
        )


# ── 9. ⚠ Needs review appears for unparsed status ────────────────────────────

def test_needs_review_text_present_for_unparsed():
    src = HTML.read_text(encoding="utf-8")
    assert "Needs review" in src, (
        "Freight display must show 'Needs review' for unparsed status"
    )
    assert 'data-testid="freight-needs-review"' in src, (
        "Needs review span must have data-testid=freight-needs-review"
    )


# ── 10. AI review button wired with testid ────────────────────────────────────

def test_btn_freight_ai_review_testid_present():
    src = HTML.read_text(encoding="utf-8")
    assert 'data-testid="btn-freight-ai-review"' in src, (
        "AI review button must have data-testid=btn-freight-ai-review"
    )
    assert "invoice_freight_review" in src, (
        "AI review button must reference invoice_freight_review task type"
    )
    assert "ai-bridge/tasks" in src, (
        "AI review button must target the ai-bridge tasks endpoint"
    )


# ── 11. confidently_absent branch renders 0.00 PLN ────────────────────────────

def test_confidently_absent_branch_in_source():
    src = HTML.read_text(encoding="utf-8")
    assert "confidently_absent" in src, (
        "Freight display must handle confidently_absent status → '0.00 PLN'"
    )
    # The branch must resolve to '0.00 PLN'
    freight_idx = src.find(MARKER)
    vicinity = src[freight_idx:freight_idx + 1200]
    assert "confidently_absent" in vicinity and "'0.00 PLN'" in vicinity, (
        "confidently_absent branch must appear in Freight (PLN) display and return '0.00 PLN'"
    )


# ── 12. parsed_positive branch present ────────────────────────────────────────

def test_parsed_positive_branch_in_source():
    src = HTML.read_text(encoding="utf-8")
    assert "parsed_positive" in src, (
        "Freight display must handle parsed_positive status"
    )
    freight_idx = src.find(MARKER)
    vicinity = src[freight_idx:freight_idx + 1200]
    assert "fmtPLN(fa.freight_pln)" in vicinity, (
        "parsed_positive branch must call fmtPLN(fa.freight_pln)"
    )
