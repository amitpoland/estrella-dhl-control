"""Multi-currency Client Balance inline presentation — no FX sum, no hidden tooltip-only truth."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.api import routes_ledgers as R
from tests.test_ledger_client_balances_wave4 import _port_customer

ROOT = Path(__file__).resolve().parents[1]
LEDGERS = ROOT / "app" / "static" / "v2" / "ledgers-page.jsx"
HUB = ROOT / "app" / "static" / "v2" / "accounting-hub.jsx"


def _d(v) -> Decimal:
    return Decimal(str(v or "0"))


def test_tomas_gold_multi_currency_legs_and_states():
    row = R._roster_row_from_portfolio_group(
        "USD",
        [
            _port_customer(
                cid="45722450",
                name="UAB Tomas Gold",
                outstanding="52940.00",
                overdue="52940.00",
                not_due="0.00",
                credit="52940.00",
            ),
            _port_customer(
                cid="45722450",
                name="UAB Tomas Gold",
                ccy="EUR",
                outstanding="182229.85",
                overdue="11558.40",
                not_due="170671.45",
                credit="0.00",
            ),
        ],
    )
    assert row["currency"] == "multi"
    assert row["presentation_state"] == "open"  # EUR still open
    assert row["presentation_state_by_currency"]["USD"] == "offset"
    assert row["presentation_state_by_currency"]["EUR"] == "open"
    legs = {leg["currency"]: leg for leg in row["currency_legs"]}
    usd = legs["USD"]
    assert usd["gross_receivable"] == "52940.00"
    assert usd["credit_balance"] == "52940.00"
    assert usd["net_receivable"] == "0.00"
    assert usd["overdue"] == "52940.00"
    assert usd["presentation_state"] == "offset"
    eur = legs["EUR"]
    assert eur["net_receivable"] == "182229.85"
    assert eur["presentation_state"] == "open"


def test_railing_2_pln_usd_legs_independent():
    row = R._roster_row_from_portfolio_group(
        "PLN",
        [
            _port_customer(ccy="PLN", outstanding="96077.65", overdue="18002.90", not_due="78074.75", credit="31296.79"),
            _port_customer(ccy="USD", outstanding="1000.00", overdue="500.00", not_due="500.00", credit="200.00"),
        ],
    )
    assert row["currency"] == "multi"
    legs = {leg["currency"]: leg for leg in row["currency_legs"]}
    assert _d(legs["PLN"]["overdue"]) + _d(legs["PLN"]["not_due"]) == _d(legs["PLN"]["gross_receivable"])
    assert _d(legs["USD"]["net_receivable"]) == _d(legs["USD"]["gross_receivable"]) - _d(legs["USD"]["credit_balance"])
    # Never FX-merge portfolio totals into scalar open
    assert row["open"] is None
    assert row["net_receivable"] is None


def test_diamond_point_single_currency_compact():
    row = R._roster_row_from_portfolio_group(
        "USD",
        [_port_customer(outstanding="167896.86", overdue="84409.20", not_due="83487.66", credit="28075.10")],
    )
    assert row["currency"] == "USD"
    assert row["gross_receivable"] == "167896.86"
    assert len(row["currency_legs"]) == 1


def test_ledgers_ui_shows_inline_multi_not_literal_multi_cell():
    src = LEDGERS.read_text(encoding="utf-8")
    assert "LdgMultiCcyLines" in src
    assert "LdgMultiCcyLegStates" in src
    assert "LdgMultiCurrencyPositionGrid" in src
    assert ">multi</td>" not in src.replace("multi-currency", "")
    assert 'value="multi-currency"' not in src


def test_accounting_hub_inline_multi_not_tooltip_only():
    src = HUB.read_text(encoding="utf-8")
    assert "_accMultiCcyLines" in src
    assert "_accLegStates" in src
    assert 'style={{ color: \'var(--text-3)\' }}>multi</span>' not in src
