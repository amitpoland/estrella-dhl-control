"""Insurance FX boundary — the ONLY FX authority for the Insurance Export
Statement (insurer-facing INR conversion).

Design (operator ruling, 2026-08-15 PR #1249 repair directive):

- The insurer benchmark for CCY→INR has NOT been established yet (candidate:
  FBIL reference rate — pending business confirmation). Until an approved
  benchmark feed is configured, this module FAILS CLOSED: ``get_rate`` raises
  :class:`InsuranceFxUnconfiguredError` and the statement row degrades to
  NEEDS REVIEW with null INR columns.
- NBP PLN-hub cross-rates are deliberately NOT a registered provider. NBP is
  a Polish-accounting authority, not an insurance benchmark; substituting it
  silently is forbidden. There is intentionally no import of
  ``nbp_rate_service`` anywhere in this module.
- The only provider implemented today is ``operator_fixed``: an explicit,
  operator-approved per-currency rate table supplied via configuration
  (``INSURANCE_FX_OPERATOR_RATES_JSON``). When the approved benchmark feed
  exists it will be added here as a new named provider — the statement
  service never learns provider internals.

Quote contract — every successful ``get_rate`` returns at least::

    {
        "requested_date":  "YYYY-MM-DD",   # invoice date the caller asked for
        "effective_date":  "YYYY-MM-DD",   # date the rate is effective for
        "currency":        "USD",
        "rate":            Decimal(...),   # INR per 1 unit of currency
        "source":          "operator_fixed",
    }

The rate is returned UN-quantized; rounding is exclusively a serialization
concern of the statement layer.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Dict

from ..core.config import settings

logger = logging.getLogger("pz.insurance_fx")

PROVIDER_OPERATOR_FIXED = "operator_fixed"


class InsuranceFxError(Exception):
    """Base error for the insurance FX boundary. Row-level: the statement
    maps this to NEEDS REVIEW + null INR columns, never a 500."""


class InsuranceFxUnconfiguredError(InsuranceFxError):
    """No approved insurance FX provider is configured (fail-closed state)."""


def _operator_fixed_rates() -> Dict[str, Decimal]:
    raw = (settings.insurance_fx_operator_rates_json or "").strip()
    if not raw:
        raise InsuranceFxUnconfiguredError(
            "Insurance FX provider 'operator_fixed' selected but "
            "INSURANCE_FX_OPERATOR_RATES_JSON is empty — operator rate "
            "input required"
        )
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise InsuranceFxError(
            "INSURANCE_FX_OPERATOR_RATES_JSON is not valid JSON: %s" % exc
        )
    if not isinstance(parsed, dict):
        raise InsuranceFxError(
            "INSURANCE_FX_OPERATOR_RATES_JSON must be a JSON object "
            "mapping currency code to rate"
        )
    rates: Dict[str, Decimal] = {}
    for ccy, value in parsed.items():
        try:
            rates[str(ccy).strip().upper()] = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise InsuranceFxError(
                "Invalid operator FX rate for %r" % ccy
            )
    return rates


def get_rate(currency: str, invoice_date: str) -> Dict[str, object]:
    """Resolve the approved insurance INR rate for ``currency`` on
    ``invoice_date`` (YYYY-MM-DD).

    Fail-closed: raises :class:`InsuranceFxUnconfiguredError` when no
    approved provider is configured, and :class:`InsuranceFxError` for any
    provider-level failure. Callers must degrade the affected row — never
    substitute another FX source.
    """
    ccy = (currency or "").strip().upper()
    if not ccy:
        raise InsuranceFxError("Currency missing — cannot resolve FX rate")

    provider = (settings.insurance_fx_provider or "").strip().lower()
    if not provider:
        raise InsuranceFxUnconfiguredError(
            "Insurance FX provider not configured — approved insurer "
            "benchmark pending; operator-approved rate input required "
            "(INSURANCE_FX_PROVIDER / INSURANCE_FX_OPERATOR_RATES_JSON)"
        )

    if provider == PROVIDER_OPERATOR_FIXED:
        rates = _operator_fixed_rates()
        rate = rates.get(ccy)
        if rate is None:
            raise InsuranceFxError(
                "No operator-approved insurance FX rate for %s" % ccy
            )
        return {
            "requested_date": invoice_date,
            "effective_date": invoice_date,
            "currency": ccy,
            "rate": rate,
            "source": PROVIDER_OPERATOR_FIXED,
        }

    # Unknown provider names fail closed as well — never fall back.
    raise InsuranceFxError(
        "Unknown insurance FX provider %r — refusing to substitute "
        "another FX source" % provider
    )


__all__ = [
    "InsuranceFxError",
    "InsuranceFxUnconfiguredError",
    "PROVIDER_OPERATOR_FIXED",
    "get_rate",
]
