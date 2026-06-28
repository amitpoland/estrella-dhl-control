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
            "field": "freight_service_id",
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
            "field": "freight_fixed_amount_eur",
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
            "field": "freight_fixed_amount_usd",
            "reason": "no USD freight amount configured (freight_fixed_amount_usd is not set)",
        }

    else:
        return {
            "ok": False, "blocked": True,
            # No Customer Master field can repair an unsupported draft currency
            # (this is a draft-side problem, not missing freight authority), so
            # there is no missing `field` to deep-link to.
            "field": None,
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


def pick_invoice_series_id_for_vat_context(
    c: CustomerMaster,
    vat_context: str,
) -> str:
    """
    Select invoice series from Customer Master based on VAT/commercial context.

    Customer Master is the ONLY authority. wFirma config is never used as
    a source here — it may only populate empty CM fields during initial sync.

    vat_context == 'wdt'    → c.preferred_wdt_invoice_series_id   (EU WDT, 0% VAT)
    vat_context == 'export' → c.preferred_export_invoice_series_id (non-EU export)
    any other               → c.preferred_invoice_series_id         (domestic / FV)

    Raises ValueError if the required Customer Master series is not set.
    Conversion must be blocked before reaching wFirma if the CM is missing a series.
    """
    name = c.bill_to_name or c.bill_to_contractor_id or "unknown customer"
    if vat_context == "wdt":
        series = c.preferred_wdt_invoice_series_id
        if not series:
            raise ValueError(
                f"WDT invoice series not configured in Customer Master for {name!r}. "
                f"Set preferred_wdt_invoice_series_id on the customer record."
            )
        return series
    if vat_context == "export":
        series = c.preferred_export_invoice_series_id
        if not series:
            raise ValueError(
                f"Export invoice series not configured in Customer Master for {name!r}. "
                f"Set preferred_export_invoice_series_id on the customer record."
            )
        return series
    # domestic / FV / any other context
    series = c.preferred_invoice_series_id
    if not series:
        raise ValueError(
            f"Domestic invoice series not configured in Customer Master for {name!r}. "
            f"Set preferred_invoice_series_id on the customer record."
        )
    return series


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


# ── Address authority helpers (2026-06-07) ─────────────────────────────────────
#
# Authority model (PROJECT_STATE.md DECISIONS 2026-06-07):
#   bill_to_* = invoice / billing authority
#   ship_to_* = DHL delivery / shipping authority
#   DHL must use ship-to first, bill-to fallback second.
#   Billing must never override a separate ship-to address.
#   Shape B (ship_to_contractor_id) is wFirma document receiver identity,
#   NOT DHL physical delivery address.
#
# These are pure functions — no I/O, no mutation, no side effects.

def pick_email(c: CustomerMaster) -> str:
    """Return the best available email for this customer.

    Priority:
      1. bill_to_email — the invoice/billing contact email (primary authority)
      2. ship_to_email — fallback ONLY when bill_to_email is absent
      3. "" — no usable email

    Does NOT mutate the customer record.
    """
    email = (c.bill_to_email or "").strip()
    if email:
        return email
    # Fallback: ship-to email only when billing email is missing
    return (c.ship_to_email or "").strip()


def resolve_billing_address(c: CustomerMaster) -> Dict[str, str]:
    """Return the billing/invoice address fields as a flat dict.

    All values are stripped strings; missing fields are empty strings.
    Uses the top-level ``country`` field as the billing country
    (``bill_to_country`` does not exist as a separate field — the
    CustomerMaster ``country`` IS the billing country).

    Does NOT mutate the customer record.
    """
    return {
        "name":        (c.bill_to_name or "").strip(),
        "street":      (c.bill_to_street or "").strip(),
        "city":        (c.bill_to_city or "").strip(),
        "postal_code": (c.bill_to_postal_code or "").strip(),
        "country":     (c.country or "").strip(),
        "phone":       (c.bill_to_phone or "").strip(),
        "email":       (c.bill_to_email or "").strip(),
    }


def _has_ship_to_address(c: CustomerMaster) -> bool:
    """True when at least one physical ship-to address field is populated.

    Checks street OR city — an address with only a name/phone but no
    location is not a usable delivery address.
    """
    return bool(
        (c.ship_to_street or "").strip()
        or (c.ship_to_city or "").strip()
    )


def resolve_delivery_address(c: CustomerMaster) -> Dict[str, str]:
    """Return the DHL delivery address for this customer.

    Authority (PROJECT_STATE.md DECISIONS 2026-06-07):
      1. If ``ship_to_use_alternate`` is True AND ship-to address fields
         are populated → use ship-to address.
      2. Otherwise → fall back to billing address.

    Billing NEVER overrides a populated ship-to address.
    Shape B (``ship_to_contractor_id``) is a wFirma document receiver
    concept — it does NOT affect DHL physical delivery address resolution.

    Returns a flat dict with stripped strings; missing fields are empty strings.
    The ``"source"`` key indicates which address was used: ``"ship_to"`` or
    ``"bill_to_fallback"``.

    Does NOT mutate the customer record.
    """
    if c.ship_to_use_alternate and _has_ship_to_address(c):
        return {
            "name":        (c.ship_to_name or "").strip(),
            "person":      (c.ship_to_person or "").strip(),
            "street":      (c.ship_to_street or "").strip(),
            "city":        (c.ship_to_city or "").strip(),
            "postal_code": (c.ship_to_zip or "").strip(),
            "country":     (c.ship_to_country or "").strip(),
            "phone":       (c.ship_to_phone or "").strip(),
            "email":       (c.ship_to_email or "").strip(),
            "source":      "ship_to",
        }

    # Fallback to billing address
    billing = resolve_billing_address(c)
    billing["person"] = ""  # billing address has no separate person field
    billing["source"] = "bill_to_fallback"
    return billing


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
    "pick_email",
    "resolve_billing_address",
    "resolve_delivery_address",
]
