"""
vat_resolver.py — pick the correct wFirma vat_code_id for a sales document line.

Inputs:
    customer.country        ISO-3166 alpha-2 (e.g. "PL", "DE", "IN", "US")
    customer.vat_eu_valid   one of {True, False, None}  — pre-checked or manual
                            None means "not yet validated" — treated as not valid
                            so we never accept WDT until VIES confirms.

Output:
    int — wFirma vat_code_id

Rules (locked, derived from live wFirma vat_codes/find on 2026-05-03):
    Polish customer                                 → 222 (23%)
    EU customer with valid VAT-EU number            → 228 (WDT 0%)
    Non-EU customer                                 → 229 (EXP 0%)
    EU customer without/with-unknown VAT-EU         → ManualReviewRequired

Anything else (unknown country code, missing country, B2C cases) raises
ManualReviewRequired so the proforma writer blocks the sale until a human
decides. We never silently default — wrong VAT is a real legal liability.

This module is a pure function (no I/O). VIES validation is a SEPARATE layer
to be wired in once the proforma writer is live-proven.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ── wFirma vat_code IDs (locked from live vat_codes/find) ────────────────────

VAT_CODE_PL_23 = 222   # standard 23% PL domestic
VAT_CODE_WDT   = 228   # intra-Community supply, 0%
VAT_CODE_EXP   = 229   # export to non-EU, 0%

# All three are confirmed via live wFirma probe and present in this account.


# ── EU country set (post-Brexit, 27 members) ─────────────────────────────────
# Northern Ireland (XI) is intentionally NOT included by default — its goods
# treatment is special (NI Protocol). Add only after the accountant confirms.

EU_COUNTRIES = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI",
    "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU",
    "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
})


# ── Public types ──────────────────────────────────────────────────────────────

class ManualReviewRequired(Exception):
    """Raised when VAT treatment cannot be auto-decided. Caller MUST block
    proforma creation and route to a human."""

    def __init__(self, message: str, customer_country: Optional[str] = None,
                 vat_eu_valid: Optional[bool] = None) -> None:
        super().__init__(message)
        self.customer_country = customer_country
        self.vat_eu_valid     = vat_eu_valid


@dataclass(frozen=True)
class CustomerForVAT:
    """Minimal customer view the resolver needs.

    `country` is ISO-3166 alpha-2. `vat_eu_valid` is True only when an
    external check (e.g. VIES) has confirmed the VAT-EU number is currently
    active. None means "unknown" and is treated the same as False so we
    never assume WDT eligibility.
    """
    country:       Optional[str]
    vat_eu_valid:  Optional[bool] = None       # True / False / None (unknown)
    vat_eu_number: Optional[str]  = None       # informational only


# ── Resolver ──────────────────────────────────────────────────────────────────

def _normalise_country(country: Optional[str]) -> Optional[str]:
    if not country:
        return None
    c = country.strip().upper()
    return c or None


def pick_vat_code(customer: CustomerForVAT) -> int:
    """Return the wFirma vat_code_id for this customer.

    Raises ManualReviewRequired if the case is ambiguous (EU customer
    without a confirmed-valid VAT-EU number, missing country, etc).

    The resolver is the SAME for proforma, invoice, and any other sales
    document. wFirma stores the vat_code_id at the line level, so this
    function is called once per line.
    """
    country = _normalise_country(customer.country)

    if country is None:
        raise ManualReviewRequired(
            "customer.country is missing — cannot decide VAT treatment without it",
            customer_country=country,
            vat_eu_valid=customer.vat_eu_valid,
        )

    # Polish customer — domestic 23%
    if country == "PL":
        return VAT_CODE_PL_23

    # EU customer
    if country in EU_COUNTRIES:
        if customer.vat_eu_valid is True:
            return VAT_CODE_WDT
        # vat_eu_valid is False, None, or anything else → block.
        # We deliberately do NOT auto-fall back to 23% PL — that would
        # mis-classify when the customer is actually OSS-registered or
        # eligible for reverse charge under specific rules.
        raise ManualReviewRequired(
            f"EU customer in country {country!r} has no confirmed-valid "
            f"VAT-EU number (vat_eu_valid={customer.vat_eu_valid}). "
            "Tax treatment depends on B2B/B2C, OSS registration, threshold. "
            "Route to manual review.",
            customer_country=country,
            vat_eu_valid=customer.vat_eu_valid,
        )

    # Non-EU — export
    return VAT_CODE_EXP


__all__ = [
    "CustomerForVAT",
    "ManualReviewRequired",
    "EU_COUNTRIES",
    "VAT_CODE_PL_23",
    "VAT_CODE_WDT",
    "VAT_CODE_EXP",
    "pick_vat_code",
]
