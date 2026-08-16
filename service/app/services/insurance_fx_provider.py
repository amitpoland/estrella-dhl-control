"""Insurance FX boundary — the ONLY FX authority for the Insurance Export
Statement (insurer-facing INR conversion).

Design (operator ruling, 2026-08-15 PR #1249 repair directive):

- Until an approved benchmark feed is configured, this module FAILS CLOSED:
  ``get_rate`` raises :class:`InsuranceFxUnconfiguredError` and the statement
  row degrades to NEEDS REVIEW with null INR columns.
- NBP is never an *alternate INR benchmark*. Its published INR quote is never
  read, and it is never substituted for a currency the India authority
  publishes. It is used for exactly one thing, under the operator ruling of
  2026-08-16: the **PLN→USD leg** of the approved PLN cross-rate, because the
  India authority does not publish PLN and no cross-rate may be invented::

      NBP Table A:   1 USD = X PLN        (PLN per 1 USD)
      India benchmark: 1 USD = Y INR      (INR per 1 USD)
      INR per 1 PLN  = Y / X

  PLN amounts are therefore *divided* by X and multiplied by Y — never
  multiplied by X. Both legs start from the same requested date
  (invoice date − 1 calendar day) and each resolves independently **backward**
  to the most recent official publication on or before it; the two effective
  dates are allowed to differ and neither may move forward. Both legs are
  disclosed intact in the quote (``nbp_leg`` / ``india_leg``); the cross rate
  is never flattened into a single opaque number.
- Two providers are implemented, selected by ``INSURANCE_FX_PROVIDER``:
  ``india_official`` — the India Official Reference FX Authority
  (``india_official_fx``: FBIL benchmark semantics, RBI publication, its own
  date rule and cache), and ``operator_fixed`` — an explicit operator-approved
  per-currency rate table (``INSURANCE_FX_OPERATOR_RATES_JSON``) for the
  currencies the official authority does not publish. This boundary only
  relabels a provider quote; the statement service never learns provider
  internals, and an unknown provider name fails closed rather than falling back.

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
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Dict

from ..core.config import settings

logger = logging.getLogger("pz.insurance_fx")

PROVIDER_OPERATOR_FIXED = "operator_fixed"
PROVIDER_INDIA_OFFICIAL = "india_official"

# Currency the India authority does not publish, resolved via the NBP USD leg.
CROSS_RATE_CURRENCY = "PLN"
# The single bridge currency both authorities publish.
BRIDGE_CURRENCY = "USD"
SOURCE_PLN_BRIDGE = "india_official_with_nbp_usd_bridge"
CROSS_RATE_FORMULA = "INR_per_USD / PLN_per_USD"
# Hard ceiling on how far back the NBP leg may reach. NBP's own API refuses a
# query span above 93 days, and the engine's walk stops after 7 business days,
# so this can only fire if the engine's rule is ever loosened — at which point
# an over-stale table must fail closed rather than value a document silently.
MAX_NBP_STALENESS_DAYS = 93

# Immutable-fact memo for the NBP leg: an official Table A publication for a
# past date never changes, so a resolved (requested_date → quote) pair is cached
# for the process lifetime and never overwritten. Keyed by the *requested* date
# so a later table can never silently replace an earlier one.
# ponytail: process-local dict; promote to the FX cache DB only if cross-process
# reuse is ever measured to matter.
_NBP_USD_MEMO: Dict[str, Dict[str, object]] = {}


class InsuranceFxError(Exception):
    """Base error for the insurance FX boundary. Row-level: the statement
    maps this to NEEDS REVIEW + null INR columns, never a 500.

    ``kind`` carries the structured taxonomy through the boundary unchanged
    (``provider_not_configured``, ``official_rate_not_published``,
    ``historical_rate_unavailable``, ``unsupported_currency``,
    ``provider_transport_error``, ``provider_payload_invalid``,
    ``rate_orientation_invalid``, ``official_rate_conflict``) so the statement
    can distinguish "not published" from "misconfigured" — a missing rate is
    never rendered as zero.
    """

    def __init__(self, message: str, kind: str = "provider_error") -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


class InsuranceFxUnconfiguredError(InsuranceFxError):
    """No approved insurance FX provider is configured (fail-closed state)."""

    def __init__(self, message: str, kind: str = "provider_not_configured") -> None:
        super().__init__(message, kind)


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


def _staleness_days(requested_date: str, effective_date: str) -> int:
    """Whole days the applied publication sits *before* the requested date.

    Negative is impossible by contract — a forward lookup is rejected by the
    caller before this is reached.
    """
    return (date.fromisoformat(requested_date) - date.fromisoformat(effective_date)).days


def _nbp_usd_leg(invoice_date: str, requested_date: str) -> Dict[str, object]:
    """PLN per 1 USD from NBP Table A — the repository's canonical NBP authority.

    ``nbp_rate_service.fetch_rate`` delegates to ``pz_import_processor.get_nbp_rate``
    (the ONE NBP fetch authority, not reimplemented here), which owns the
    "business day preceding the invoice date, walking backward over weekends
    and Polish holidays" rule. It is handed the *invoice* date, not the already
    decremented one, because the −1 day is part of that rule.

    Only the USD mid is read. NBP's own INR quote is never touched: it is a
    Polish accounting rate, not the insurer's India benchmark.
    """
    memo = _NBP_USD_MEMO.get(requested_date)
    if memo is not None:
        return memo

    from . import nbp_rate_service  # canonical NBP authority (adapter)

    # The adapter delegates to the root engine module, which lives outside the
    # app package in production (Lesson J: ``C:\PZ\engine``). Other callers put
    # it on the path as an import side-effect; this boundary must not depend on
    # one of them having been imported first.
    engine_dir = str(settings.engine_dir)
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)

    try:
        quote = nbp_rate_service.fetch_rate(BRIDGE_CURRENCY, invoice_date)
    except nbp_rate_service.NbpRateError as exc:
        kind = {
            "unsupported_currency": "unsupported_currency",
            "missing_rate": "official_rate_not_published",
        }.get(exc.kind, "provider_transport_error")
        raise InsuranceFxError(
            "PLN cross-rate: NBP USD leg failed (%s)" % exc.message, kind=kind
        )
    except Exception as exc:  # noqa: BLE001 — any transport/engine defect
        raise InsuranceFxError(
            "PLN cross-rate: NBP USD leg unavailable (%s)" % exc,
            kind="provider_transport_error",
        )

    try:
        pln_per_usd = Decimal(str(quote.get("rate")))
    except (InvalidOperation, ValueError, TypeError):
        raise InsuranceFxError(
            "PLN cross-rate: NBP returned an unreadable USD rate %r"
            % (quote.get("rate"),),
            kind="provider_payload_invalid",
        )
    if not pln_per_usd.is_finite() or pln_per_usd <= 0:
        raise InsuranceFxError(
            "PLN cross-rate: NBP USD rate %s is not a usable quote" % pln_per_usd,
            kind="provider_payload_invalid",
        )

    effective = str(quote.get("table_date") or "").strip()
    try:
        forward = date.fromisoformat(effective) > date.fromisoformat(requested_date)
    except ValueError:
        raise InsuranceFxError(
            "PLN cross-rate: NBP returned an unusable effective date %r" % effective,
            kind="provider_payload_invalid",
        )
    if forward:
        # A table published *after* the requested date would value the document
        # with information that did not exist on the day. Never accepted.
        raise InsuranceFxError(
            "PLN cross-rate: NBP table %s is dated %s, after the requested %s"
            % (quote.get("table_number"), effective, requested_date),
            kind="rate_orientation_invalid",
        )

    staleness = _staleness_days(requested_date, effective)
    if staleness > MAX_NBP_STALENESS_DAYS:
        raise InsuranceFxError(
            "PLN cross-rate: nearest NBP table %s is %d days before the "
            "requested %s — beyond the %d-day official lookback"
            % (effective, staleness, requested_date, MAX_NBP_STALENESS_DAYS),
            kind="historical_rate_unavailable",
        )

    leg = {
        "source": "NBP",
        "table": "A",
        "table_number": quote.get("table_number"),
        "currency": BRIDGE_CURRENCY,
        "orientation": "PLN_per_USD",
        "requested_date": requested_date,
        "effective_date": effective,
        "rate": pln_per_usd,
        "staleness_days": staleness,
    }
    _NBP_USD_MEMO.setdefault(requested_date, leg)
    return _NBP_USD_MEMO[requested_date]


def _pln_cross_rate(invoice_date: str) -> Dict[str, object]:
    """INR per 1 PLN = (INR per 1 USD) / (PLN per 1 USD). Decimal throughout.

    The India leg is resolved first: it owns the requested-date rule, and both
    legs must be asked for the same requested date. A failure on either leg
    fails the whole quote closed — no partial rate, no substituted authority.
    """
    from . import india_official_fx

    try:
        india = india_official_fx.resolve_for_invoice_date(
            BRIDGE_CURRENCY, invoice_date
        )
    except india_official_fx.OfficialFxError as exc:
        raise InsuranceFxError(
            "PLN cross-rate: India USD leg failed (%s)" % exc.message, kind=exc.kind
        )

    requested = str(india["requested_date"])
    inr_per_usd = india["rate"]
    nbp = _nbp_usd_leg(invoice_date, requested)
    pln_per_usd = nbp["rate"]

    inr_per_pln = inr_per_usd / pln_per_usd  # never inr_per_usd * pln_per_usd

    india_leg = {
        "source": india["source"],
        "currency": BRIDGE_CURRENCY,
        "orientation": "INR_per_USD",
        "requested_date": requested,
        "effective_date": india["effective_date"],
        "rate": inr_per_usd,
        "quote_unit": india["quote_unit"],
        "rate_as_published": india["rate_as_published"],
        "staleness_days": india["staleness_days"],
    }
    # The applied evidence is no fresher than the older of the two legs; the
    # individual dates stay visible above and are never flattened away.
    return {
        "requested_date": requested,
        "effective_date": min(str(india["effective_date"]), str(nbp["effective_date"])),
        "currency": CROSS_RATE_CURRENCY,
        "rate": inr_per_pln,
        "source": SOURCE_PLN_BRIDGE,
        "derivation": "cross_rate",
        "formula": CROSS_RATE_FORMULA,
        "staleness_days": max(
            int(india["staleness_days"]), int(nbp["staleness_days"])
        ),
        "quote_unit": 1,
        "rate_as_published": None,
        "nbp_leg": nbp,
        "india_leg": india_leg,
    }


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

    if provider == PROVIDER_INDIA_OFFICIAL:
        # The India Official Reference FX Authority owns the date rule, the
        # quotation orientation and its own cache. This boundary only relabels
        # its quote — it never second-guesses the rate and never falls back.
        if ccy == CROSS_RATE_CURRENCY:
            # PLN is not published by the India authority. Resolved as the
            # approved USD-bridge cross rate — still inside this boundary, and
            # still a single provider setting.
            return _pln_cross_rate(invoice_date)

        from . import india_official_fx

        try:
            quote = india_official_fx.resolve_for_invoice_date(ccy, invoice_date)
        except india_official_fx.OfficialFxError as exc:
            raise InsuranceFxError(exc.message, kind=exc.kind)
        return {
            "requested_date": quote["requested_date"],
            "effective_date": quote["effective_date"],
            "currency": ccy,
            "rate": quote["rate"],
            "source": quote["source"],
            "staleness_days": quote["staleness_days"],
            "quote_unit": quote["quote_unit"],
            "rate_as_published": quote["rate_as_published"],
        }

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
    "BRIDGE_CURRENCY",
    "CROSS_RATE_CURRENCY",
    "CROSS_RATE_FORMULA",
    "MAX_NBP_STALENESS_DAYS",
    "InsuranceFxError",
    "InsuranceFxUnconfiguredError",
    "PROVIDER_INDIA_OFFICIAL",
    "PROVIDER_OPERATOR_FIXED",
    "SOURCE_PLN_BRIDGE",
    "get_rate",
]
