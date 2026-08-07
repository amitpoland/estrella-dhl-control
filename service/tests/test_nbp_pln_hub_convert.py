"""Canonical PLN-hub FX conversion — nbp_rate_service.convert().

Pins the operator-mandated model:
  source commercial currency → NBP/PLN → selected Proforma currency

Covers: USD→PLN, USD→EUR via PLN, EUR→USD via PLN, INR normalisation,
PLN identity, weekend/holiday previous-table resolution (engine lookback),
and revalue without mutating source commercial authority.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import date, timedelta
from unittest.mock import patch

import pytest

_ROOT = pathlib.Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Canned NBP table — INR mid is the JSON API form (per 1), ≈ HTML 100-INR / 100.
_ENGINE_TABLE = {
    "table_no": "A/135/2026",
    "table_date": "2026-07-14",
    "usd_rate": 3.9512,
    "eur_rate": 4.3021,
    "inr_rate": 0.039705,
    "rates": {
        "USD": 3.9512,
        "EUR": 4.3021,
        "INR": 0.039705,
        "GBP": 4.9000,
    },
}


@pytest.fixture()
def nbp():
    from app.services import nbp_rate_service as nbp
    return nbp


def test_currency_registry_is_pln_usd_eur_inr(nbp):
    codes = [c["code"] for c in nbp.currencies()]
    assert codes == ["PLN", "USD", "EUR", "INR"]
    assert nbp.DOCUMENT_CURRENCIES == ("PLN", "USD", "EUR", "INR")


def test_normalize_inr_html_form_divides_by_100(nbp):
    # HTML table quotes 100 INR = 3.9705 → per-1 = 0.039705
    assert abs(nbp.normalize_nbp_mid("INR", 3.9705) - 0.039705) < 1e-9
    # JSON API already per-1 — leave alone
    assert abs(nbp.normalize_nbp_mid("INR", 0.039705) - 0.039705) < 1e-9


def test_pln_identity(nbp):
    r = nbp.convert("PLN", 100.0, "PLN", "2026-07-15")
    assert r["amount_doc"] == 100.0
    assert r["pln_equivalent"] == 100.0
    assert r["rate_normalized"] == 1.0
    assert r["source"] == "identity"
    assert r["nbp_table"] is None


@patch("app.services.nbp_rate_service._call_engine", return_value=_ENGINE_TABLE)
def test_usd_to_pln(mock_eng, nbp):
    r = nbp.convert("USD", 100.0, "PLN", "2026-07-15")
    assert abs(r["amount_doc"] - 395.12) < 0.01
    assert abs(r["pln_equivalent"] - 395.12) < 0.01
    assert abs(r["doc_to_pln_rate"] - 1.0) < 1e-9
    assert abs(r["source_to_pln_rate"] - 3.9512) < 1e-9
    assert r["nbp_table"] == "A/135/2026"
    assert r["nbp_date"] == "2026-07-14"
    mock_eng.assert_called_once()


@patch("app.services.nbp_rate_service._call_engine", return_value=_ENGINE_TABLE)
def test_usd_to_eur_via_pln(mock_eng, nbp):
    r = nbp.convert("USD", 100.0, "EUR", "2026-07-15")
    # 100 USD → 395.12 PLN → 395.12/4.3021 EUR
    expected = round(100.0 * 3.9512 / 4.3021, 4)
    assert abs(r["amount_doc"] - expected) < 0.001
    assert abs(r["rate_normalized"] - (3.9512 / 4.3021)) < 1e-6
    assert r["cross_leg"]["source_to_pln"]["rate"] == 3.9512
    assert r["cross_leg"]["doc_to_pln"]["rate"] == 4.3021
    # One table for both legs — never invent a USD/EUR pair rate.
    assert mock_eng.call_count == 1


@patch("app.services.nbp_rate_service._call_engine", return_value=_ENGINE_TABLE)
def test_eur_to_usd_via_pln(mock_eng, nbp):
    r = nbp.convert("EUR", 100.0, "USD", "2026-07-15")
    expected = round(100.0 * 4.3021 / 3.9512, 4)
    assert abs(r["amount_doc"] - expected) < 0.001


@patch("app.services.nbp_rate_service._call_engine", return_value=_ENGINE_TABLE)
def test_inr_normalization_in_convert(mock_eng, nbp):
    r = nbp.convert("INR", 10000.0, "PLN", "2026-07-15")
    expected = round(10000.0 * 0.039705, 4)
    assert abs(r["amount_doc"] - expected) < 0.01


@patch("app.services.nbp_rate_service._call_engine", return_value=_ENGINE_TABLE)
def test_same_currency_keeps_amount_computes_pln(mock_eng, nbp):
    r = nbp.convert("USD", 50.0, "USD", "2026-07-15")
    assert abs(r["amount_doc"] - 50.0) < 1e-9
    assert abs(r["pln_equivalent"] - 50.0 * 3.9512) < 0.01
    assert abs(r["rate_normalized"] - 1.0) < 1e-9


def test_unsupported_currency_raises(nbp):
    with pytest.raises(nbp.NbpRateError) as ei:
        nbp.convert("GBP", 10.0, "PLN", "2026-07-15")
    assert ei.value.kind == "unsupported_currency"


@patch("app.services.nbp_rate_service._call_engine", return_value=_ENGINE_TABLE)
def test_revalue_freezes_source_authority(mock_eng, nbp):
    lines = [{"line_id": 1, "qty": 2, "unit_price": 100.0, "currency": "USD"}]
    charges = [{"charge_id": 1, "charge_type": "freight", "amount": 25.0, "currency": "USD"}]
    snap1 = nbp.revalue_commercial_snapshot(
        lines=lines, service_charges=charges,
        source_ccy="USD", doc_ccy="EUR", issue_date="2026-07-15",
    )
    assert snap1["lines"][0]["source_unit_price"] == 100.0
    assert snap1["lines"][0]["source_currency"] == "USD"
    assert snap1["lines"][0]["currency"] == "EUR"
    eur_price = snap1["lines"][0]["unit_price"]
    # Second revalue to PLN must start from frozen source 100 USD, not EUR.
    snap2 = nbp.revalue_commercial_snapshot(
        lines=snap1["lines"], service_charges=snap1["service_charges"],
        source_ccy="USD", doc_ccy="PLN", issue_date="2026-07-15",
    )
    assert snap2["lines"][0]["source_unit_price"] == 100.0
    assert abs(snap2["lines"][0]["unit_price"] - 395.12) < 0.01
    assert snap2["lines"][0]["unit_price"] != eur_price


def test_engine_skips_weekend_before_looking_up_table():
    """Previous-business-day rule: Saturday issue → Friday table attempt first."""
    from pz_import_processor import get_nbp_rate

    # 2026-07-18 is a Saturday; previous calendar day is Friday 17th.
    attempted = []

    class _Resp:
        status_code = 404

        def json(self):
            return []

    def fake_get(url, timeout=10):
        attempted.append(url)
        if "2026-07-14" in url:  # Tuesday — succeed on walk-back
            class _Ok:
                status_code = 200

                def json(self_inner):
                    return [{
                        "no": "A/TEST",
                        "effectiveDate": "2026-07-14",
                        "rates": [
                            {"code": "USD", "mid": 4.0},
                            {"code": "EUR", "mid": 4.5},
                            {"code": "INR", "mid": 0.04},
                        ],
                    }]
            return _Ok()
        return _Resp()

    with patch("pz_import_processor.requests.get", side_effect=fake_get):
        res = get_nbp_rate("2026-07-18")  # Saturday
    assert res["table_no"] == "A/TEST"
    assert "inr_rate" in res
    assert "rates" in res
    # Must NOT attempt Saturday/Sunday URLs as first choice.
    assert attempted, "engine must attempt at least one NBP URL"
    assert "2026-07-18" not in attempted[0]
    assert "2026-07-17" in attempted[0]  # Friday = previous business day


def test_commercial_lookup_blocks_accidental_german_from_cm():
    from app.services import commercial_lookup as cl
    r = cl.resolve_translation_language_id(
        draft_language_id=None, cm_language_id="3",
    )
    assert r["language_id"] == "2"
    assert r["source"] == "intended_commercial_default"
    assert r["warning"]
    # Explicit draft German is honoured.
    r2 = cl.resolve_translation_language_id(
        draft_language_id="3", cm_language_id="2",
    )
    assert r2["language_id"] == "3"
    assert r2["source"] == "draft"


def test_service_product_registry_ui_reads_service_products_key():
    jsx = (pathlib.Path(__file__).parents[1]
           / "app" / "static" / "v2" / "proforma-detail.jsx").read_text(encoding="utf-8")
    assert "products.service_products" in jsx, (
        "ServiceProductRegistryPanel must read API key service_products "
        "(not only the non-existent .mappings)"
    )
    assert "edit-currency" in jsx
    assert "pf-ct-vat-select" not in jsx, (
        "VAT/WDT editable select removed from CommercialTermsEditor — "
        "VatInsurancePanel is the display authority"
    )
