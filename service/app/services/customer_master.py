"""
customer_master.py — orchestration over customer_master_db.

Layer 1 surface for the proforma writer:

    CustomerMasterResolver(db_path).get(bill_to_contractor_id) → CustomerMaster
        .to_vat_input()                       → CustomerForVAT
        .pick_currency(target_default)        → str
        .pick_language_id(target_default)     → str | None
        .pick_insurance_min(vat_code)         → Decimal     (override OR vat-based default)
        .pick_freight(override)               → Decimal | None    (override > master.fixed)
        .pick_freight(draft_currency)         → dict             (currency-aware path)
        .pick_freight_service_id(default)     → str
        .pick_insurance_service_id(default)   → str
        .compute_insurance_suggestion(ccy, sales_total) → dict
        .pick_invoice_series_id(default)      → str | None
        .pick_proforma_series_id(default)     → str | None
        .pick_vat_mode()                      → int | None
        .ship_to_shape()                      → "none" | "alternate_address" | "separate_contractor"

This module contains NO wFirma I/O. It bridges the local customer master
to the pure resolvers that already exist (vat_resolver, proforma_resolver).

Credit / Kuke fields are stored but NOT enforced here — that gate ships in
Layer 3 once we probe customer outstanding-exposure.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional, Union

from app.models.vat_resolver import CustomerForVAT
from app.services.customer_master_db import (
    CustomerMaster,
    get_customer,
    upsert_customer,
)


SHIP_TO_NONE                 = "none"
SHIP_TO_ALTERNATE_ADDRESS    = "alternate_address"   # contact_* fields on same legal entity
SHIP_TO_SEPARATE_CONTRACTOR  = "separate_contractor" # ship_to_contractor_id (different wFirma id)


class CustomerNotFound(KeyError):
    """Raised when get_or_load can't find a customer in the master DB."""


class CustomerMasterResolver:
    """Read-only-ish view over customer_master_db with helper methods.

    The resolver is intentionally thin: each method maps to one decision the
    proforma writer needs, and falls back gracefully when the customer master
    record is absent / partial.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    # ── Read ──────────────────────────────────────────────────────────────────

    def get(self, bill_to_contractor_id: str) -> Optional[CustomerMaster]:
        return get_customer(self.db_path, bill_to_contractor_id)

    def require(self, bill_to_contractor_id: str) -> CustomerMaster:
        c = self.get(bill_to_contractor_id)
        if c is None:
            raise CustomerNotFound(
                f"customer_master has no record for bill_to_contractor_id={bill_to_contractor_id!r}"
            )
        return c

    # ── Write ─────────────────────────────────────────────────────────────────

    def upsert(self, c: CustomerMaster) -> int:
        return upsert_customer(self.db_path, c)


# ── Helpers — pure functions for testing ─────────────────────────────────────

def to_vat_input(c: CustomerMaster) -> CustomerForVAT:
    """Project the customer master into the input expected by vat_resolver."""
    return CustomerForVAT(
        country       = c.country,
        vat_eu_valid  = c.vat_eu_valid,
        vat_eu_number = c.vat_eu_number,
    )


def pick_currency(c: CustomerMaster, target_default: Optional[str] = None) -> Optional[str]:
    """Customer's stored default beats target_default."""
    return c.default_currency or target_default


def pick_language_id(c: CustomerMaster, target_default: Optional[str] = None) -> Optional[str]:
    return c.default_language_id or target_default


def pick_insurance_min(c: CustomerMaster, vat_based_default: Decimal) -> Decimal:
    """Customer override beats the vat-based default."""
    if c.insurance_min_override is not None:
        return Decimal(c.insurance_min_override)
    return Decimal(vat_based_default)


_log = logging.getLogger(__name__)


def pick_freight(
    c: CustomerMaster,
    draft_currency: Optional[str] = None,
    operator_override: Optional[Decimal] = None,
    *,
    override: Optional[Decimal] = None,   # backward-compat alias for operator_override
) -> Union[Optional[Decimal], Dict[str, Any]]:
    """Decide the freight amount for this customer.

    **Legacy path** (``draft_currency`` is not supplied):
        Returns ``Decimal | None``.  Priority:
            1. operator override (``override=`` or ``operator_override``)
            2. ``freight_last_amount`` when ``freight_mode == 'fixed'``
            3. ``None``
        This path is preserved so existing callers do not break.

    **Currency-aware path** (``draft_currency`` is supplied):
        Returns a dict::
            {"ok": True,  "amount": Decimal, "wfirma_service_id": str, "label": str|None}
          or
            {"ok": False, "blocked": True, "reason": str}

        Priority:
            1. ``operator_override`` always wins.
            2. EUR draft → ``freight_fixed_amount_eur``.
            3. USD draft → ``freight_fixed_amount_usd``.
            4. EUR only backward-compat: if ``freight_fixed_amount_eur`` is absent
               and ``freight_last_amount`` + ``freight_mode == 'fixed'`` are set →
               use ``freight_last_amount`` with a deprecation log.

        No cross-currency fallback: an EUR draft never uses USD amounts and
        vice versa.  ``freight_service_id`` must be configured or the call
        is blocked.
    """
    # Resolve backward-compat `override=` kwarg → same as operator_override
    _effective_override = operator_override if operator_override is not None else override

    # ── Legacy path ────────────────────────────────────────────────────────────
    if draft_currency is None:
        if _effective_override is not None:
            return Decimal(_effective_override)
        if c.freight_last_amount is not None and (c.freight_mode or "") == "fixed":
            return Decimal(c.freight_last_amount)
        return None

    # ── Currency-aware path ────────────────────────────────────────────────────
    ccy = (draft_currency or "").upper()

    # Service ID is always required
    service_id = c.freight_service_id
    if not service_id:
        return {
            "ok": False, "blocked": True,
            "reason": "freight_service_id is not configured for this customer",
        }

    label = c.freight_label_en or c.freight_label_pl

    # Operator override always wins
    if _effective_override is not None:
        return {
            "ok": True,
            "amount": Decimal(_effective_override),
            "wfirma_service_id": service_id,
            "label": label,
        }

    if ccy == "EUR":
        amount = c.freight_fixed_amount_eur
        if amount is not None:
            return {
                "ok": True,
                "amount": Decimal(amount),
                "wfirma_service_id": service_id,
                "label": label,
            }
        # Backward-compat: fall through to freight_last_amount for EUR fixed mode only
        if c.freight_last_amount is not None and (c.freight_mode or "") == "fixed":
            _log.warning(
                "pick_freight: using legacy freight_last_amount for EUR "
                "(deprecated — set freight_fixed_amount_eur on customer master)"
            )
            return {
                "ok": True,
                "amount": Decimal(c.freight_last_amount),
                "wfirma_service_id": service_id,
                "label": label,
                "legacy_fallback": True,
            }
        return {
            "ok": False, "blocked": True,
            "reason": "no EUR freight amount configured (freight_fixed_amount_eur is not set)",
        }

    elif ccy == "USD":
        amount = c.freight_fixed_amount_usd
        if amount is not None:
            return {
                "ok": True,
                "amount": Decimal(amount),
                "wfirma_service_id": service_id,
                "label": label,
            }
        return {
            "ok": False, "blocked": True,
            "reason": "no USD freight amount configured (freight_fixed_amount_usd is not set)",
        }

    else:
        return {
            "ok": False, "blocked": True,
            "reason": (
                f"draft_currency {ccy!r} is not supported; "
                "only EUR and USD are accepted"
            ),
        }


def compute_insurance_suggestion(
    c: CustomerMaster,
    draft_currency: str,
    draft_sales_total: Decimal,
) -> Dict[str, Any]:
    """Compute an insurance service-charge suggestion for a draft.

    Returns a dict::
        {"ok": True,  "amount": Decimal, "wfirma_service_id": str,
         "label": str|None, "formula_basis": dict|None}
      or
        {"ok": False, "blocked": True, "reason": str}

    Blocked when:
    - ``insurance_enabled`` is False
    - ``insurance_service_id`` is missing
    - no configured amount for the given currency

    Modes
    -----
    Fixed:
        EUR → ``insurance_fixed_amount_eur``
        USD → ``insurance_fixed_amount_usd``
    Formula (rate-based):
        ``max(draft_sales_total × insurance_rate, minimum)``
        where minimum = ``insurance_min_eur`` (EUR) or ``insurance_min_usd`` (USD).

    ``formula_basis`` only contains: ``sales_total``, ``rate_pct``,
    ``minimum_eur`` or ``minimum_usd``.  CIF / customs / import / pz_ / sad_ /
    zc429_ fields are NEVER included.

    No cross-currency fallback: EUR draft never uses USD amounts and vice versa.
    """
    if not c.insurance_enabled:
        return {
            "ok": False, "blocked": True,
            "reason": "insurance is disabled for this customer",
        }

    service_id = c.insurance_service_id
    if not service_id:
        return {
            "ok": False, "blocked": True,
            "reason": "insurance_service_id is not configured for this customer",
        }

    ccy = (draft_currency or "").upper()
    if ccy not in ("EUR", "USD"):
        return {
            "ok": False, "blocked": True,
            "reason": (
                f"draft_currency {ccy!r} is not supported; "
                "only EUR and USD are accepted"
            ),
        }

    label = c.insurance_label_en or c.insurance_label_pl

    if ccy == "EUR":
        fixed   = c.insurance_fixed_amount_eur
        minimum = c.insurance_min_eur
    else:
        fixed   = c.insurance_fixed_amount_usd
        minimum = c.insurance_min_usd

    # Fixed mode takes precedence over rate/formula
    if fixed is not None:
        return {
            "ok": True,
            "amount": Decimal(fixed),
            "wfirma_service_id": service_id,
            "label": label,
            "formula_basis": None,
        }

    # Formula mode
    rate = c.insurance_rate
    if rate is not None and Decimal(rate) > 0:
        computed = Decimal(draft_sales_total) * Decimal(rate)
        if minimum is not None and Decimal(minimum) > 0:
            computed = max(computed, Decimal(minimum))

        formula_basis: Dict[str, Any] = {
            "sales_total": str(Decimal(draft_sales_total)),
            "rate_pct":    str(Decimal(rate) * 100),
        }
        if ccy == "EUR" and minimum is not None:
            formula_basis["minimum_eur"] = str(Decimal(minimum))
        elif ccy == "USD" and minimum is not None:
            formula_basis["minimum_usd"] = str(Decimal(minimum))

        return {
            "ok": True,
            "amount": computed.quantize(Decimal("0.01")),
            "wfirma_service_id": service_id,
            "label": label,
            "formula_basis": formula_basis,
        }

    return {
        "ok": False, "blocked": True,
        "reason": (
            f"no insurance amount configured for {ccy} "
            "(no fixed amount and no rate set)"
        ),
    }


def pick_freight_service_id(c: CustomerMaster, default: Optional[str] = None) -> Optional[str]:
    """Customer's stored freight good_id beats default. Default constant lives
    on the CustomerMaster dataclass (13002743 — Fedex Courier)."""
    return c.freight_service_id or default


def pick_insurance_service_id(c: CustomerMaster, default: Optional[str] = None) -> Optional[str]:
    """Customer's stored insurance good_id beats default. Default constant
    lives on the CustomerMaster dataclass (13102217)."""
    return c.insurance_service_id or default


def pick_invoice_series_id(c: CustomerMaster, default: Optional[str] = None) -> Optional[str]:
    """Customer's preferred invoice series beats default."""
    return c.preferred_invoice_series_id or default


def pick_proforma_series_id(c: CustomerMaster, default: Optional[str] = None) -> Optional[str]:
    """Customer's preferred proforma series beats default."""
    return c.preferred_proforma_series_id or default


def pick_vat_mode(c: CustomerMaster) -> Optional[int]:
    """Return the customer's stored vat_mode (222 / 228 / 229) or None.

    This is a HINT — the upstream vat_resolver still owns the actual decision,
    using country + vat_eu_valid. Use this only to pre-validate consistency
    or to short-circuit when the resolver agrees.
    """
    return c.vat_mode if c.vat_mode is not None else None


def ship_to_shape(c: CustomerMaster) -> str:
    """Which ship-to shape does this customer use?"""
    if c.ship_to_contractor_id:
        return SHIP_TO_SEPARATE_CONTRACTOR
    if c.ship_to_use_alternate:
        return SHIP_TO_ALTERNATE_ADDRESS
    return SHIP_TO_NONE


__all__ = [
    "CustomerMasterResolver",
    "CustomerNotFound",
    "SHIP_TO_NONE",
    "SHIP_TO_ALTERNATE_ADDRESS",
    "SHIP_TO_SEPARATE_CONTRACTOR",
    "to_vat_input",
    "pick_currency",
    "pick_language_id",
    "pick_insurance_min",
    "pick_freight",
    "pick_freight_service_id",
    "pick_insurance_service_id",
    "compute_insurance_suggestion",
    "pick_invoice_series_id",
    "pick_proforma_series_id",
    "pick_vat_mode",
    "ship_to_shape",
]
