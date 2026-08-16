"""PLN → INR cross-rate pins for the Insurance FX boundary.

Operator ruling (2026-08-16): the India official authority does not publish
PLN, so the PLN leg of the Insurance Export Statement is resolved *inside the
existing FX boundary* as an approved USD-bridge cross rate::

    NBP Table A:      1 USD = X PLN      (PLN per 1 USD)
    India benchmark:  1 USD = Y INR      (INR per 1 USD)
    INR per 1 PLN  =  Y / X

Never ``Y * X``. Both legs start from the same requested date (invoice date − 1
calendar day, owned by the India authority) and each resolves independently
**backward**; the two effective dates may differ and neither may move forward.
NBP's own published INR quote is never read, and NBP is never consulted for a
currency the India authority publishes.

Every test here mocks the two upstream authorities — no network, and no
hardcoded production rate.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.config import settings
from app.services import india_official_fx, insurance_fx_provider, nbp_rate_service
from app.services.insurance_fx_provider import (
    CROSS_RATE_FORMULA,
    InsuranceFxError,
    MAX_NBP_STALENESS_DAYS,
    SOURCE_PLN_BRIDGE,
    get_rate,
)

INVOICE_DATE = "2026-08-11"
REQUESTED = "2026-08-10"


@pytest.fixture(autouse=True)
def _india_official_provider(monkeypatch):
    monkeypatch.setattr(settings, "insurance_fx_provider", "india_official")
    monkeypatch.setattr(
        insurance_fx_provider, "_NBP_USD_MEMO", {}, raising=False
    )
    yield


def _india_quote(rate="87.500000", effective="2026-08-08", requested=REQUESTED):
    return {
        "currency": "USD",
        "rate": Decimal(rate),
        "requested_date": requested,
        "effective_date": effective,
        "staleness_days": 2,
        "quote_unit": 1,
        "rate_as_published": Decimal(rate),
        "source": "rbi_reference_rate_archive",
    }


def _nbp_quote(rate=3.6421, table_date="2026-08-07", table_number="152/A/NBP/2026"):
    return {
        "rate": rate,
        "source": "NBP",
        "table_number": table_number,
        "table_date": table_date,
        "accounting_date": INVOICE_DATE,
        "currency": "USD",
    }


def _wire(monkeypatch, india=None, nbp=None, calls=None):
    """Install both upstream authorities, recording their call arguments."""
    seen = calls if calls is not None else {"india": [], "nbp": []}

    def fake_india(currency, invoice_date):
        seen["india"].append((currency, invoice_date))
        payload = india if india is not None else _india_quote()
        if isinstance(payload, Exception):
            raise payload
        return payload

    def fake_nbp(currency, accounting_date):
        seen["nbp"].append((currency, accounting_date))
        payload = nbp if nbp is not None else _nbp_quote()
        if isinstance(payload, Exception):
            raise payload
        return payload

    monkeypatch.setattr(
        india_official_fx, "resolve_for_invoice_date", fake_india
    )
    monkeypatch.setattr(nbp_rate_service, "fetch_rate", fake_nbp)
    return seen


# --------------------------------------------------------------------------
# Orientation and arithmetic
# --------------------------------------------------------------------------


def test_pln_rate_is_india_usd_divided_by_nbp_pln_per_usd(monkeypatch):
    _wire(monkeypatch)
    quote = get_rate("PLN", INVOICE_DATE)

    expected = Decimal("87.500000") / Decimal("3.6421")
    assert quote["rate"] == expected
    assert quote["currency"] == "PLN"
    assert quote["source"] == SOURCE_PLN_BRIDGE
    assert quote["derivation"] == "cross_rate"
    assert quote["formula"] == CROSS_RATE_FORMULA


def test_pln_is_never_multiplied_by_pln_per_usd(monkeypatch):
    _wire(monkeypatch)
    quote = get_rate("PLN", INVOICE_DATE)

    inr_per_usd = Decimal("87.500000")
    pln_per_usd = Decimal("3.6421")
    assert quote["rate"] != inr_per_usd * pln_per_usd
    # 1 PLN buys far fewer INR than 1 USD does — the direction proof.
    assert quote["rate"] < inr_per_usd
    assert quote["rate"] > 0


def test_rate_is_decimal_not_float(monkeypatch):
    _wire(monkeypatch)
    quote = get_rate("PLN", INVOICE_DATE)
    assert isinstance(quote["rate"], Decimal)
    assert isinstance(quote["nbp_leg"]["rate"], Decimal)
    assert isinstance(quote["india_leg"]["rate"], Decimal)


def test_nbp_leg_orientation_is_declared_pln_per_usd(monkeypatch):
    _wire(monkeypatch)
    quote = get_rate("PLN", INVOICE_DATE)
    assert quote["nbp_leg"]["orientation"] == "PLN_per_USD"
    assert quote["india_leg"]["orientation"] == "INR_per_USD"
    assert quote["nbp_leg"]["table"] == "A"
    assert quote["nbp_leg"]["table_number"] == "152/A/NBP/2026"


# --------------------------------------------------------------------------
# Date rule: one requested date, two independent backward resolutions
# --------------------------------------------------------------------------


def test_both_legs_are_asked_for_the_same_invoice_date(monkeypatch):
    seen = _wire(monkeypatch)
    quote = get_rate("PLN", INVOICE_DATE)

    # The India authority owns the −1 calendar day; the NBP engine owns its own
    # "business day preceding the invoice date" rule. Both are handed the raw
    # invoice date so neither rule is double-applied.
    assert seen["india"] == [("USD", INVOICE_DATE)]
    assert seen["nbp"] == [("USD", INVOICE_DATE)]
    assert quote["requested_date"] == REQUESTED
    assert quote["nbp_leg"]["requested_date"] == REQUESTED
    assert quote["india_leg"]["requested_date"] == REQUESTED


def test_effective_dates_may_differ_and_both_stay_backward(monkeypatch):
    _wire(
        monkeypatch,
        india=_india_quote(effective="2026-08-08"),
        nbp=_nbp_quote(table_date="2026-08-07"),
    )
    quote = get_rate("PLN", INVOICE_DATE)

    assert quote["india_leg"]["effective_date"] == "2026-08-08"
    assert quote["nbp_leg"]["effective_date"] == "2026-08-07"
    assert quote["india_leg"]["effective_date"] <= REQUESTED
    assert quote["nbp_leg"]["effective_date"] <= REQUESTED
    # The applied evidence is no fresher than the older leg.
    assert quote["effective_date"] == "2026-08-07"
    assert quote["staleness_days"] == 3


def test_nbp_weekend_and_holiday_walk_back_is_accepted(monkeypatch):
    # Invoice Monday 2026-08-17 → requested Sunday 2026-08-16 → NBP's own walk
    # lands on Friday 2026-08-14. A backward result is normal, never an error.
    _wire(
        monkeypatch,
        india=_india_quote(effective="2026-08-14", requested="2026-08-16"),
        nbp=_nbp_quote(table_date="2026-08-14"),
    )
    quote = get_rate("PLN", "2026-08-17")
    assert quote["nbp_leg"]["effective_date"] == "2026-08-14"
    assert quote["nbp_leg"]["staleness_days"] == 2


def test_nbp_table_dated_after_requested_date_fails_closed(monkeypatch):
    _wire(monkeypatch, nbp=_nbp_quote(table_date="2026-08-12"))
    with pytest.raises(InsuranceFxError) as ei:
        get_rate("PLN", INVOICE_DATE)
    assert ei.value.kind == "rate_orientation_invalid"


def test_nbp_leg_beyond_official_lookback_fails_closed(monkeypatch):
    stale = "2026-01-01"  # far more than MAX_NBP_STALENESS_DAYS before requested
    _wire(monkeypatch, nbp=_nbp_quote(table_date=stale))
    with pytest.raises(InsuranceFxError) as ei:
        get_rate("PLN", INVOICE_DATE)
    assert ei.value.kind == "historical_rate_unavailable"
    assert str(MAX_NBP_STALENESS_DAYS) in str(ei.value)


# --------------------------------------------------------------------------
# Fail-closed on every upstream defect — no rate is ever invented or zeroed
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad_rate", [0, -3.64, "abc", None])
def test_unusable_nbp_rate_fails_closed(monkeypatch, bad_rate):
    _wire(monkeypatch, nbp=_nbp_quote(rate=bad_rate))
    with pytest.raises(InsuranceFxError) as ei:
        get_rate("PLN", INVOICE_DATE)
    assert ei.value.kind == "provider_payload_invalid"


def test_malformed_nbp_effective_date_fails_closed(monkeypatch):
    _wire(monkeypatch, nbp=_nbp_quote(table_date="not-a-date"))
    with pytest.raises(InsuranceFxError) as ei:
        get_rate("PLN", INVOICE_DATE)
    assert ei.value.kind == "provider_payload_invalid"


def test_nbp_transport_failure_fails_closed(monkeypatch):
    _wire(
        monkeypatch,
        nbp=nbp_rate_service.NbpRateError("upstream", "NBP unreachable"),
    )
    with pytest.raises(InsuranceFxError) as ei:
        get_rate("PLN", INVOICE_DATE)
    assert ei.value.kind == "provider_transport_error"


def test_nbp_missing_rate_is_reported_as_not_published(monkeypatch):
    _wire(
        monkeypatch,
        nbp=nbp_rate_service.NbpRateError("missing_rate", "no USD in table"),
    )
    with pytest.raises(InsuranceFxError) as ei:
        get_rate("PLN", INVOICE_DATE)
    assert ei.value.kind == "official_rate_not_published"


def test_unexpected_nbp_engine_exception_fails_closed(monkeypatch):
    _wire(monkeypatch, nbp=RuntimeError("engine asked for stdin"))
    with pytest.raises(InsuranceFxError) as ei:
        get_rate("PLN", INVOICE_DATE)
    assert ei.value.kind == "provider_transport_error"


def test_india_usd_leg_failure_fails_closed_without_touching_nbp(monkeypatch):
    seen = _wire(
        monkeypatch,
        india=india_official_fx.OfficialFxError(
            "official_rate_not_published", "RBI archive gap"
        ),
    )
    with pytest.raises(InsuranceFxError) as ei:
        get_rate("PLN", INVOICE_DATE)
    assert ei.value.kind == "official_rate_not_published"
    assert seen["nbp"] == []  # no half-resolved cross rate


# --------------------------------------------------------------------------
# NBP stays in its lane
# --------------------------------------------------------------------------


def test_nbp_published_inr_quote_is_never_requested(monkeypatch):
    seen = _wire(monkeypatch)
    get_rate("PLN", INVOICE_DATE)
    assert [c[0] for c in seen["nbp"]] == ["USD"]
    assert all(c[0] != "INR" for c in seen["nbp"])


@pytest.mark.parametrize("currency", ["USD", "EUR", "GBP"])
def test_nbp_is_never_consulted_for_currencies_india_publishes(
    monkeypatch, currency
):
    seen = _wire(monkeypatch, india=_india_quote())
    quote = get_rate(currency, INVOICE_DATE)
    assert seen["nbp"] == []
    assert quote["source"] == "rbi_reference_rate_archive"
    assert "nbp_leg" not in quote
    assert "derivation" not in quote


def test_nbp_rate_service_is_never_a_module_level_binding():
    # The bridge is a deliberate, single-purpose lazy import inside
    # ``_nbp_usd_leg``. A module-level binding would make NBP reachable from
    # every other code path in this boundary.
    assert not hasattr(insurance_fx_provider, "nbp_rate_service")


# --------------------------------------------------------------------------
# Immutable-fact caching
# --------------------------------------------------------------------------


def test_second_resolution_reuses_the_cached_nbp_leg(monkeypatch):
    seen = _wire(monkeypatch)
    first = get_rate("PLN", INVOICE_DATE)
    second = get_rate("PLN", INVOICE_DATE)

    assert len(seen["nbp"]) == 1  # upstream hit once
    assert first["rate"] == second["rate"]
    assert first["nbp_leg"] == second["nbp_leg"]
    assert first["effective_date"] == second["effective_date"]


def test_cached_nbp_leg_keeps_full_provenance(monkeypatch):
    _wire(monkeypatch)
    get_rate("PLN", INVOICE_DATE)
    cached = get_rate("PLN", INVOICE_DATE)["nbp_leg"]
    for key in (
        "source",
        "table",
        "table_number",
        "orientation",
        "requested_date",
        "effective_date",
        "rate",
        "staleness_days",
    ):
        assert key in cached


def test_a_resolved_historical_quote_is_never_overwritten(monkeypatch):
    seen = _wire(monkeypatch)
    original = get_rate("PLN", INVOICE_DATE)["nbp_leg"]

    # Upstream now answers differently for the same requested date — an
    # official past publication cannot change, so the stored fact wins.
    _wire(monkeypatch, nbp=_nbp_quote(rate=9.9999, table_number="999/A"), calls=seen)
    again = get_rate("PLN", INVOICE_DATE)["nbp_leg"]
    assert again == original
    assert len(seen["nbp"]) == 1


def test_historical_rerun_is_deterministic_across_a_cold_cache(monkeypatch):
    _wire(monkeypatch)
    warm = get_rate("PLN", INVOICE_DATE)
    monkeypatch.setattr(insurance_fx_provider, "_NBP_USD_MEMO", {})
    cold = get_rate("PLN", INVOICE_DATE)
    assert warm["rate"] == cold["rate"]
    assert warm["nbp_leg"] == cold["nbp_leg"]
    assert warm["india_leg"] == cold["india_leg"]


def test_the_boundary_puts_the_engine_dir_on_the_path_itself(monkeypatch):
    """The NBP adapter delegates to a root engine module that lives outside the
    app package in production (Lesson J). Other route modules happen to add it
    to ``sys.path`` when they are imported — this boundary must not silently
    depend on that having happened, or a PLN row fails closed for a reason that
    has nothing to do with FX."""
    import sys

    from app.core.config import settings

    _wire(monkeypatch)
    engine_dir = str(settings.engine_dir)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != engine_dir])
    assert engine_dir not in sys.path

    get_rate("PLN", INVOICE_DATE)
    assert engine_dir in sys.path
