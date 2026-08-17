"""Gross / Credits / Net presentation contract — no financial-formula changes.

Pins the three production fixtures from the 2026-08-17 presentation truth gate
and the UI vocabulary. Remaining / aging / payment matching are out of scope.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.api import routes_ledgers as R
from tests.test_ledger_client_balances_wave4 import _port_customer

ROOT = Path(__file__).resolve().parents[1]
LEDGERS = ROOT / "app" / "static" / "v2" / "ledgers-page.jsx"
HUB = ROOT / "app" / "static" / "v2" / "accounting-hub.jsx"
ANALYTICS = ROOT / "app" / "services" / "accounting_analytics.py"
ROUTES = ROOT / "app" / "api" / "routes_ledgers.py"


def _d(v) -> Decimal:
    return Decimal(str(v or "0"))


def _assert_identities(gross, credits, net, overdue, not_due, due_na="0.00"):
    g, cr, n = _d(gross), _d(credits), _d(net)
    aging = _d(overdue) + _d(not_due) + _d(due_na)
    assert aging == g, f"gross {g} != aging {aging}"
    assert n == g - cr, f"net {n} != gross {g} - credits {cr}"


# ── Helpers (copy-only aliases) ───────────────────────────────────────────

def test_presentation_state_open_offset_credit_clear():
    assert R._presentation_state("100.00", "0.00") == "open"
    assert R._presentation_state("52940.00", "52940.00") == "offset"
    assert R._presentation_state("0.00", "50.00") == "credit"
    assert R._presentation_state("0.00", "0.00") == "clear"


def test_tomas_gold_usd_roster_is_offset_net_zero():
    """UAB Tomas Gold USD: Gross AR 52940, Credits 52940, Net 0, Overdue 52940."""
    row = R._roster_row_from_portfolio_group(
        "USD",
        [_port_customer(
            cid="45722450",
            name="UAB Tomas Gold",
            outstanding="52940.00",
            overdue="52940.00",
            not_due="0.00",
            credit="52940.00",
        )],
    )
    assert row["gross_receivable"] == "52940.00"
    assert row["open"] == "52940.00"
    assert row["credit_balance"] == "52940.00"
    assert row["net_receivable"] == "0.00"
    assert row["overdue_due_date"] == "52940.00"
    assert row["not_due"] == "0.00"
    assert row["presentation_state"] == "offset"
    assert row["state"] == "outstanding"  # legacy filter: gross still open
    _assert_identities(
        row["gross_receivable"], row["credit_balance"], row["net_receivable"],
        row["overdue_due_date"], row["not_due"], row["due_date_unavailable"],
    )


def test_estrella_llp_usd_supplier_credits_explain_net():
    """ESTRELLA JEWELS LLP USD: Gross 687496.63 − Credits 7787.13 = Net 679709.50."""
    packed = R._enrich_supplier_presentation({
        "contractor_id": "38142296",
        "supplier_name": "ESTRELLA JEWELS LLP",
        "currency": "USD",
        "gross_payable": "687496.63",
        "credit_balance": "7787.13",
        "net_payable": "679709.50",
        "overdue": "259217.63",
        "not_due": "428279.00",
        "due_date_unavailable": "0.00",
    })
    assert packed["presentation_state"] == "open"
    _assert_identities(
        packed["gross_payable"], packed["credit_balance"], packed["net_payable"],
        packed["overdue"], packed["not_due"], packed["due_date_unavailable"],
    )


def test_fedex_poland_pln_is_offset_net_zero_with_gross_overdue():
    """Fedex Express Poland PLN: Gross = Credits = Overdue = 3244.03, Net = 0."""
    packed = R._enrich_supplier_presentation({
        "contractor_id": "44980415",
        "supplier_name": "Fedex Express Poland",
        "currency": "PLN",
        "gross_payable": "3244.03",
        "credit_balance": "3244.03",
        "net_payable": "0.00",
        "overdue": "3244.03",
        "not_due": "0.00",
        "due_date_unavailable": "0.00",
    })
    assert packed["presentation_state"] == "offset"
    _assert_identities(
        packed["gross_payable"], packed["credit_balance"], packed["net_payable"],
        packed["overdue"], packed["not_due"], packed["due_date_unavailable"],
    )


def test_portfolio_invariants_hold_for_mixed_credit_row():
    row = R._roster_row_from_portfolio_group(
        "USD",
        [_port_customer(
            outstanding="167896.86",
            overdue="84409.20",
            not_due="83487.66",
            credit="28075.10",
        )],
    )
    _assert_identities(
        row["gross_receivable"], row["credit_balance"], row["net_receivable"],
        row["overdue_due_date"], row["not_due"], row["due_date_unavailable"],
    )
    assert row["net_receivable"] == "139821.76"
    assert row["presentation_state"] == "open"


# ── UI vocabulary (source-grep; no React arithmetic) ──────────────────────

def test_supplier_balance_exposes_gross_credits_net():
    src = LEDGERS.read_text(encoding="utf-8")
    assert "Net Open" in src
    assert "Gross Payable" in src
    assert "Supplier Credits" in src
    assert "ldg-suppliers-authority" in src
    assert "Net Open = Gross Payable − Supplier Credits" in src
    assert "ldg-sup-credits-" in src
    assert "ldg-sup-gross-" in src


def test_client_balance_exposes_gross_credits_net():
    src = LEDGERS.read_text(encoding="utf-8")
    assert "Gross AR" in src
    assert "Net Open" in src
    assert "ldg-client-credits-" in src
    assert "ldg-client-net-" in src
    assert "ldg-client-gross-" in src
    assert "Math.max(0, (Number(c.open)" not in src


def test_client_ledger_tiles_name_gross_credits_net():
    src = LEDGERS.read_text(encoding="utf-8")
    assert "Gross Outstanding" in src
    assert "Customer Credits" in src
    assert "Net Position" in src
    assert "Statement Closing is period activity" in src


def test_supplier_ledger_tiles_include_gross_and_credits():
    src = LEDGERS.read_text(encoding="utf-8")
    assert 'label="Gross Payable"' in src
    assert 'label="Supplier Credits"' in src
    assert 'label="Net Payable"' in src
    assert 'label="Not Due"' in src


def test_overview_does_not_call_net_supplier_payable_generic_supplier_payable():
    hub = HUB.read_text(encoding="utf-8")
    assert "Net Supplier Payable" in hub
    assert 'label="Supplier Payable"' not in hub
    assert "Gross Receivable" in hub
    assert "Gross Overdue AR" in hub
    assert "Net Open = Gross AR − Credits" in hub


def test_management_analysis_terminology_aligned():
    src = LEDGERS.read_text(encoding="utf-8")
    assert "Gross Receivable" in src
    assert "Net Receivable" in src
    assert "Gross Payable" in src
    assert 'label="Supplier Payable"' not in src


def test_no_new_balance_formula_in_frontend():
    for path in (LEDGERS, HUB):
        src = path.read_text(encoding="utf-8")
        assert "remaining_after_payments" not in src
        assert "match_payments_to_" not in src


def test_analytics_formulas_not_rewritten_by_this_campaign():
    """Guard: presentation campaign must not touch remaining/aging builders."""
    src = ANALYTICS.read_text(encoding="utf-8")
    assert "net_payable       = gross_payable − credit_balance" in src
    assert "outstanding = receivable  # positive AR only; credits separate" in src
