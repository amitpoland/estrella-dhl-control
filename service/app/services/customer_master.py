"""
customer_master.py — orchestration over customer_master_db.

Layer 1 surface for the proforma writer:

    CustomerMasterResolver(db_path).get(bill_to_contractor_id) → CustomerMaster
        .to_vat_input()                       → CustomerForVAT
        .pick_currency(target_default)        → str
        .pick_language_id(target_default)     → str | None
        .pick_insurance_min(vat_code)         → Decimal     (override OR vat-based default)
        .pick_freight(override)               → Decimal | None    (override > master.fixed)
        .pick_freight_service_id(default)     → str
        .pick_insurance_service_id(default)   → str
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

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Optional

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


def pick_freight(c: CustomerMaster, override: Optional[Decimal] = None) -> Optional[Decimal]:
    """Decide the freight amount for this customer.

    Priority (highest first):
        1. operator override (if supplied)             → always wins
        2. master.freight_last_amount when freight_mode == 'fixed'
        3. None  (caller MUST require operator --freight input)

    The 'fixed' guard is intentional: variable / manual / no_data customers
    have no reliable repeating value, so we refuse to silently reuse last.
    """
    if override is not None:
        return Decimal(override)
    if c.freight_last_amount is not None and (c.freight_mode or "") == "fixed":
        return Decimal(c.freight_last_amount)
    return None


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
    "pick_invoice_series_id",
    "pick_proforma_series_id",
    "pick_vat_mode",
    "ship_to_shape",
]
