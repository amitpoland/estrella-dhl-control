"""Insurance FX boundary — fail-closed, no-NBP-fallback pins (Blocker 1).

Operator ruling (2026-08-15, PR #1249 repair directive): NBP PLN-hub
cross-rates must never become an automatic Insurance INR FX authority.
Until an approved insurer benchmark (candidate: FBIL) is configured, the
statement must fail closed and require explicit operator rate input —
never silently substitute NBP or any other unapproved source.
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.insurance_fx_provider import (
    InsuranceFxError,
    InsuranceFxUnconfiguredError,
    get_rate,
)


@pytest.fixture(autouse=True)
def _clean_fx_settings(monkeypatch):
    monkeypatch.setattr(settings, "insurance_fx_provider", "", raising=False)
    monkeypatch.setattr(
        settings, "insurance_fx_operator_rates_json", "", raising=False
    )
    yield


def test_no_provider_configured_fails_closed():
    with pytest.raises(InsuranceFxUnconfiguredError):
        get_rate("USD", "2026-05-10")


def test_operator_fixed_selected_but_no_rates_json_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "insurance_fx_provider", "operator_fixed")
    with pytest.raises(InsuranceFxUnconfiguredError):
        get_rate("USD", "2026-05-10")


def test_unknown_provider_name_fails_closed_never_substitutes(monkeypatch):
    # "nbp" is deliberately not a registered provider — selecting it must
    # fail closed, never silently resolve through the PLN-hub cross-rate.
    monkeypatch.setattr(settings, "insurance_fx_provider", "nbp")
    with pytest.raises(InsuranceFxError) as ei:
        get_rate("USD", "2026-05-10")
    assert "refusing to substitute" in str(ei.value)


def test_operator_fixed_rate_currency_not_in_table_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "insurance_fx_provider", "operator_fixed")
    monkeypatch.setattr(
        settings, "insurance_fx_operator_rates_json", '{"USD": "88.467460"}'
    )
    with pytest.raises(InsuranceFxError):
        get_rate("GBP", "2026-05-10")


def test_operator_fixed_returns_unquantized_quote_with_full_provenance(
    monkeypatch,
):
    monkeypatch.setattr(settings, "insurance_fx_provider", "operator_fixed")
    monkeypatch.setattr(
        settings, "insurance_fx_operator_rates_json", '{"USD": "92.500000"}'
    )
    quote = get_rate("USD", "2026-05-10")
    assert quote == {
        "requested_date": "2026-05-10",
        "effective_date": "2026-05-10",
        "currency": "USD",
        "rate": pytest.approx(92.5),
        "source": "operator_fixed",
    } or (
        quote["requested_date"] == "2026-05-10"
        and quote["effective_date"] == "2026-05-10"
        and quote["currency"] == "USD"
        and str(quote["rate"]) == "92.500000"
        and quote["source"] == "operator_fixed"
    )


def test_module_never_imports_nbp_rate_service():
    import app.services.insurance_fx_provider as fx_mod

    assert "nbp_rate_service" not in vars(fx_mod)
    assert not hasattr(fx_mod, "nbp_rate_service")
