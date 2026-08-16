"""Insurance Export Statement — presentation contract pins.

Two operator-reported display defects, both fixed on the presentation layer
only (campaign 2026-08-17; no financial authority touched):

1. ``Needs review`` was shown as a bare chip. The projection has always
   carried ``recommendation_reason`` on every row — the renderer just never
   showed it. These pins fix the direction of that dependency: the reason is
   *displayed*, never *derived* in JSX.
2. PLN is quoted as a USD-bridge cross rate, so its raw Decimal carries 26
   fractional digits and leaked verbatim into both the web table and the PDF.
   ``fx_rate_display`` caps the shown rate at 4 fractional digits while
   ``fx_rate`` — the value ``sum_insured_inr`` was computed from — is
   untouched and still disclosed in full.

The load-bearing pin is ``test_display_rounding_cannot_alter_inr``: the two
precisions must be provably different on the same row, so a future edit that
"simplifies" by rounding the rate before the multiply fails here.
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from app.services import insurance_export_statement as ies
from app.services import insurance_fx_provider

APP = Path(__file__).resolve().parents[1] / "app"
SERVICE = APP / "services" / "insurance_export_statement.py"
RENDERER = APP / "services" / "insurance_export_pdf_renderer.py"
JSX = APP / "static" / "v2" / "insurance-export-tab.jsx"

# A real-shaped PLN cross rate: 26 fractional digits, exactly what the
# provider returns for the PLN bridge and what used to reach the operator.
CROSS_RATE = Decimal("25.80903687427814868024451393")
DISPLAY_RATE = Decimal("25.8090")


@pytest.fixture
def pln_row(monkeypatch, tmp_path):
    """One projected row at the full cross-rate precision.

    Draft and charge-authority lookups are stubbed out: this exercises the
    FX/format path only and must never open a production database.
    """
    monkeypatch.setattr(
        insurance_fx_provider,
        "get_rate",
        lambda ccy, date: {
            "rate": CROSS_RATE,
            "source": "pln_usd_bridge",
            "requested_date": "2026-08-10",
            "effective_date": "2026-08-08",
            "staleness_days": 2,
            "quote_unit": 1,
            "rate_as_published": None,
            "derivation": "cross_rate",
            "formula": "INR_per_USD / PLN_per_USD",
        },
    )
    monkeypatch.setattr(ies, "_link_draft", lambda invoice_id, db_path: None)
    monkeypatch.setattr(ies, "_invoiced_charges", lambda invoice_id, ccy: None)
    return ies._build_row(
        {
            "id": "9001",
            "fullnumber": "FV 9001/2026",
            "date": "2026-08-11",
            "currency": "PLN",
            "brutto": "100000.00",
            "contractor_id": "1",
            "contractor_name": "Test Sp. z o.o.",
        },
        doc_type="normal",
        db_path=tmp_path / "pz.db",
        carrier_db_path=tmp_path / "carrier.db",
        fx_cache={},
    )


# --------------------------------------------------------------------------
# 4-decimal display, and the proof it never reaches the calculation


def test_fx_display_caps_at_four_fractional_digits():
    assert ies._fx_display(CROSS_RATE) == "25.8090"
    # Already-short rates (EUR/USD publish 4dp) are unchanged in value and
    # padded to a fixed width so the column stays aligned.
    assert ies._fx_display(Decimal("95.1234")) == "95.1234"
    assert ies._fx_display(Decimal("95.5")) == "95.5000"
    # Commercial rounding, matching _money — the 5th digit rounds half up.
    assert ies._fx_display(Decimal("25.06585")) == "25.0659"
    assert ies._fx_display(None) is None


def test_row_carries_both_precisions(pln_row):
    assert pln_row["fx_rate"] == str(CROSS_RATE)  # full precision, unchanged
    assert pln_row["fx_rate_display"] == "25.8090"
    assert len(pln_row["fx_rate_display"].split(".")[1]) == 4


def test_display_rounding_cannot_alter_inr(pln_row):
    """The INR column comes from the FULL rate, not the displayed one.

    These two values must differ, otherwise the pin proves nothing.
    """
    base = Decimal("100000.00") * ies.SUM_INSURED_FACTOR
    from_full = ies._money(base * CROSS_RATE)
    from_display = ies._money(base * DISPLAY_RATE)
    assert from_full != from_display, "chosen fixture no longer discriminates"
    assert pln_row["sum_insured_inr"] == from_full


def test_no_rounding_before_the_fx_multiply():
    """The rate reaches the multiply raw; only serialization rounds."""
    code = SERVICE.read_text(encoding="utf-8")
    assert "sum_insured_inr = sum_insured * fx_rate" in code
    # _fx_display is a serializer — it must never feed a calculation.
    for line in code.splitlines():
        if "_fx_display(" in line and "def _fx_display" not in line:
            assert line.strip().startswith('"fx_rate_display"'), line


# --------------------------------------------------------------------------
# Needs-review reason: displayed, never derived


def test_every_needs_review_row_carries_a_reason(pln_row):
    """The projection is the classifier; a review state without a reason is
    the defect this campaign closed."""
    assert pln_row["status"] == ies.InsuranceStatus.NEEDS_REVIEW
    assert pln_row["recommendation_reason"] == "No proforma draft linked to this invoice"


def test_every_forced_review_branch_sets_a_reason():
    """No branch may promote a row to needs_review without a reason string."""
    code = SERVICE.read_text(encoding="utf-8")
    blocks = code.split("status = InsuranceStatus.NEEDS_REVIEW")
    for tail in blocks[1:]:
        window = tail[:600]
        assert "reason" in window, "needs_review set without a reason nearby"


def test_jsx_displays_the_backend_reason():
    code = JSX.read_text(encoding="utf-8")
    assert "recommendation_reason" in code
    assert "ins-export-review-reason-" in code


def test_jsx_invents_no_second_review_taxonomy():
    """The JSX may compare against the backend status, but must never author
    a reason of its own."""
    code = JSX.read_text(encoding="utf-8")
    for backend_phrase in (
        "No proforma draft",
        "Shipment record has no AWB",
        "Missing gross amount",
        "Correction parent could not be confirmed",
        "Insurance FX unavailable",
    ):
        assert backend_phrase not in code, backend_phrase


# --------------------------------------------------------------------------
# Both renderers show the same rate


def test_both_renderers_use_the_display_rate():
    pdf = RENDERER.read_text(encoding="utf-8")
    assert pdf.count('row.get("fx_rate_display")') == 1
    assert pdf.count('adj.get("fx_rate_display")') == 1
    # No renderer prints the raw rate as the primary value.
    assert not re.search(r'_num_cell\((?:row|adj)\.get\("fx_rate"\)\)', pdf)

    jsx = JSX.read_text(encoding="utf-8")
    assert "r.fx_rate_display || r.fx_rate" in jsx


def test_full_precision_rate_stays_disclosed():
    """Capping the display must not hide the applied rate — it moves into the
    provenance hover, it does not disappear."""
    jsx = JSX.read_text(encoding="utf-8")
    assert "insFxProvenanceText(r.fx_provenance, r.fx_rate)" in jsx
    assert "full precision" in jsx


# --------------------------------------------------------------------------
# Subtotals stay presentation-only


def test_group_subtotals_are_not_re_added_to_the_total():
    """Contractor subtotals are rendered from the server payload; the grand
    total is summed from ROWS only, never from the subtotals."""
    code = SERVICE.read_text(encoding="utf-8")
    assert "def _sum_inr(rows" in code
    jsx = JSX.read_text(encoding="utf-8")
    # The JSX renders the subtotal, it never accumulates one.
    assert "ins-export-group-subtotal-" in jsx
    assert not re.search(r"subtotal\w*\s*\+=", jsx)
