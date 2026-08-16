"""India Official Reference FX Authority — offline unit tests.

Every test in this file is network-free: the transport is stubbed and the
parser is exercised against a captured shape of the real RBI archive table.
The one thing these tests never do is assert a hardcoded "official" rate as a
production constant — the fixture below is test input, not an approved rate.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.config import settings
from app.services import india_official_fx as fx
from app.services import insurance_fx_provider


# Shape captured from the live archive (headers declare the quotation unit,
# rows are DD/MM/YYYY). Values are synthetic test input, not approved rates.
ARCHIVE_HTML = """
<table>
<tr><td><b>Date</b></td>
    <td><b>USD (INR / 1 USD)</b></td>
    <td><b>EUR (INR / 1 EUR)</b></td>
    <td><b>JPY (INR / 100 JPY)</b></td></tr>
<tr><td>14/08/2026</td><td>95.0000</td><td>110.0000</td><td>60.0000</td></tr>
<tr><td>13/08/2026</td><td>94.0000</td><td>109.0000</td><td>59.0000</td></tr>
<tr><td>07/08/2026</td><td>93.0000</td><td>108.0000</td><td>-</td></tr>
</table>
"""


@pytest.fixture
def fx_store(tmp_path, monkeypatch):
    """Isolated cache + stubbed transport; asserts the network is never used
    unless the test explicitly allows it."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    calls = []

    def _fetch(start, end):
        calls.append((start, end))
        return fx._parse_archive(ARCHIVE_HTML)

    monkeypatch.setattr(fx, "_fetch_window", _fetch)
    return calls


# ── parser ────────────────────────────────────────────────────────────────


def test_parser_reads_orientation_from_the_header_not_a_hardcoded_table():
    rows = {(r["currency"], r["effective_date"]): r for r in fx._parse_archive(ARCHIVE_HTML)}
    jpy = rows[("JPY", "2026-08-14")]
    assert jpy["quote_unit"] == 100
    assert jpy["rate_as_published"] == "60.0000"
    # 100 JPY published → stored as INR per 1 JPY.
    assert jpy["rate_inr_per_unit"] == Decimal("0.6")
    assert rows[("USD", "2026-08-14")]["rate_inr_per_unit"] == Decimal("95.0000")


def test_parser_skips_unpublished_cells():
    assert ("JPY", "2026-08-07") not in {
        (r["currency"], r["effective_date"]) for r in fx._parse_archive(ARCHIVE_HTML)
    }


def test_parser_fails_closed_when_the_rate_table_is_absent():
    with pytest.raises(fx.OfficialFxError) as exc:
        fx._parse_archive("<html><body>maintenance</body></html>")
    assert exc.value.kind == "provider_payload_invalid"


def test_parser_fails_closed_on_an_unreadable_quotation_unit():
    with pytest.raises(fx.OfficialFxError) as exc:
        fx._parse_archive("<tr><td><b>USD (INR / 1 EUR)</b></td></tr>")
    assert exc.value.kind == "rate_orientation_invalid"


# ── date rule ─────────────────────────────────────────────────────────────


def test_date_rule_uses_invoice_date_minus_one(fx_store):
    quote = fx.resolve_for_invoice_date("USD", "2026-08-14")
    assert quote["requested_date"] == "2026-08-13"
    assert quote["effective_date"] == "2026-08-13"
    assert quote["staleness_days"] == 0
    assert quote["rate"] == Decimal("94.0000")


def test_date_rule_never_moves_forward(fx_store):
    """A publication dated on or after the invoice date is never applied."""
    quote = fx.resolve_for_invoice_date("USD", "2026-08-14")
    assert quote["effective_date"] < "2026-08-14"


def test_date_rule_walks_back_over_non_publication_days(fx_store):
    # Invoice 2026-08-10 → requested 08-09 (Sunday) → latest publication 08-07.
    quote = fx.resolve_for_invoice_date("USD", "2026-08-10")
    assert quote["requested_date"] == "2026-08-09"
    assert quote["effective_date"] == "2026-08-07"
    assert quote["staleness_days"] == 2


def test_todays_rate_is_never_used_for_a_historical_invoice(fx_store):
    quote = fx.resolve_for_invoice_date("EUR", "2026-08-14")
    assert quote["effective_date"] == "2026-08-13"
    assert quote["rate"] == Decimal("109.0000")


# ── currencies ────────────────────────────────────────────────────────────


def test_pln_fails_closed_and_invents_no_cross_rate(fx_store):
    with pytest.raises(fx.OfficialFxError) as exc:
        fx.resolve_for_invoice_date("PLN", "2026-08-14")
    assert exc.value.kind == "unsupported_currency"


def test_inr_is_not_a_convertible_currency(fx_store):
    with pytest.raises(fx.OfficialFxError) as exc:
        fx.resolve_for_invoice_date("INR", "2026-08-14")
    assert exc.value.kind == "unsupported_currency"


def test_date_before_published_history_is_reported_as_historical_gap(fx_store):
    with pytest.raises(fx.OfficialFxError) as exc:
        fx.resolve_for_invoice_date("USD", "2026-08-06")
    assert exc.value.kind == "historical_rate_unavailable"


# ── cache ─────────────────────────────────────────────────────────────────


def test_second_resolution_is_served_from_cache(fx_store):
    fx.resolve_for_invoice_date("USD", "2026-08-14")
    fetches = len(fx_store)
    fx.resolve_for_invoice_date("USD", "2026-08-14")
    fx.resolve_for_invoice_date("EUR", "2026-08-14")
    assert len(fx_store) == fetches


def test_backfill_is_idempotent(fx_store):
    first = fx.backfill("2026-08-01", "2026-08-14")
    second = fx.backfill("2026-08-01", "2026-08-14")
    assert first["inserted"] > 0
    assert second["inserted"] == 0
    assert second["already_present"] == first["inserted"]


def test_a_contradicting_source_value_blocks_instead_of_overwriting(fx_store, monkeypatch):
    fx.resolve_for_invoice_date("USD", "2026-08-14")
    monkeypatch.setattr(
        fx,
        "_fetch_window",
        lambda s, e: fx._parse_archive(ARCHIVE_HTML.replace("94.0000", "99.9999")),
    )
    with pytest.raises(fx.OfficialFxError) as exc:
        fx.backfill("2026-08-01", "2026-08-14")
    assert exc.value.kind == "official_rate_conflict"


def test_fetch_window_wider_than_the_archive_returns_completely_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    from datetime import date

    with pytest.raises(fx.OfficialFxError) as exc:
        fx._fetch_window(date(2020, 1, 1), date(2026, 1, 1))
    assert exc.value.kind == "provider_payload_invalid"


# ── boundary: insurance_fx_provider relabels, never second-guesses ────────


def test_provider_boundary_passes_the_official_quote_through(fx_store, monkeypatch):
    monkeypatch.setattr(settings, "insurance_fx_provider", "india_official")
    quote = insurance_fx_provider.get_rate("USD", "2026-08-14")
    assert quote["rate"] == Decimal("94.0000")
    assert quote["effective_date"] == "2026-08-13"
    assert quote["source"] == fx.SOURCE_RBI_ARCHIVE
    assert quote["staleness_days"] == 0


def test_provider_boundary_carries_the_taxonomy_kind(fx_store, monkeypatch):
    monkeypatch.setattr(settings, "insurance_fx_provider", "india_official")
    with pytest.raises(insurance_fx_provider.InsuranceFxError) as exc:
        insurance_fx_provider.get_rate("PLN", "2026-08-14")
    assert exc.value.kind == "unsupported_currency"


def test_provider_boundary_never_falls_back_to_another_fx_source(fx_store, monkeypatch):
    """No NBP, no second provider — an official gap stays a gap."""
    monkeypatch.setattr(settings, "insurance_fx_provider", "india_official")
    monkeypatch.setattr(
        fx,
        "resolve_for_invoice_date",
        lambda c, d: (_ for _ in ()).throw(
            fx.OfficialFxError("official_rate_not_published", "no publication")
        ),
    )
    with pytest.raises(insurance_fx_provider.InsuranceFxError) as exc:
        insurance_fx_provider.get_rate("USD", "2026-08-14")
    assert exc.value.kind == "official_rate_not_published"


def test_unconfigured_provider_still_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "insurance_fx_provider", "")
    with pytest.raises(insurance_fx_provider.InsuranceFxUnconfiguredError) as exc:
        insurance_fx_provider.get_rate("USD", "2026-08-14")
    assert exc.value.kind == "provider_not_configured"


def test_the_fx_authority_never_imports_the_polish_accounting_authority():
    source = (
        __import__("pathlib").Path(fx.__file__).read_text(encoding="utf-8")
        + __import__("pathlib").Path(insurance_fx_provider.__file__).read_text(encoding="utf-8")
    )
    assert "import nbp_rate_service" not in source
    assert "from .nbp_rate_service" not in source
