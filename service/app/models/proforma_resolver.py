"""
proforma_resolver.py — decide every wFirma proforma field that depends on
customer, currency, or contractor profile.

Inputs:
    customer       : CustomerForVAT      (country + vat_eu_valid)
    currency       : "PLN" | "USD" | "EUR"
    contractor     : ContractorTerms     (payment_method + payment_days from wFirma)
    document_date  : date                (proforma issue date)
    lang_map       : dict[str, int]      (operator-supplied country → language_id)

Output:
    ProformaResolution — every field the proforma writer needs to produce a
    valid <invoice> XML body.

Hard rules (locked, derived from live wFirma probes 2026-05-03):
  Bank accounts (live company_accounts/find):
      PLN → 180686 (Santander)
      USD → 169589 (Santander)
      EUR → 194483 (Santander)
  Languages (live invoices/find):
      element shape: <translation_language><id>N</id></translation_language>
      no languages/find module → no programmatic enumeration
      → operator supplies a country → id map. Fallback to id=1 (default).
  VAT codes (delegated to vat_resolver.pick_vat_code):
      222 = 23% PL,  228 = WDT 0%,  229 = EXP 0%
  Payment terms (live contractor record):
      <payment_method> string code  ('transfer', 'cash', ...)
      <payment_days>   integer days
      → DO NOT hardcode. Read from contractor profile.
      → If both empty AND no fallback supplied → block.

I/O policy:
  This module is split into two functions:
    - fetch_contractor_terms(contractor_id) → live wFirma read (does I/O)
    - resolve_proforma(...)                 → PURE function (no I/O)
  The split lets tests run with mocked terms and never hit wFirma.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Optional

from app.models.vat_resolver import (
    CustomerForVAT,
    ManualReviewRequired,
    pick_vat_code,
)


# ── Live-confirmed constants (this account, 2026-05-03) ──────────────────────

# Maps payment currency → wFirma company_account_id. Confirmed via
# company_accounts/find (3 Santander accounts) and cross-validated against
# 24 historic proforma documents.
#
# In wFirma's XML model:
#   <company_account><id>NNN</id></company_account>   ← reference, what we send
#   <bank_account>PL53...</bank_account>              ← derived IBAN snapshot
# The proforma `add` payload should use <company_account>; <bank_account> is
# auto-populated by wFirma from the linked company_account record.
COMPANY_ACCOUNT_BY_CURRENCY: Dict[str, str] = {
    "PLN": "180686",
    "USD": "169589",
    "EUR": "194483",
}

# Backward-compat alias — same data, different name. Kept until all callers migrate.
BANK_ACCOUNT_BY_CURRENCY: Dict[str, str] = COMPANY_ACCOUNT_BY_CURRENCY

DEFAULT_LANGUAGE_ID = "1"   # Catch-all when operator hasn't mapped a country


# ── Public types ──────────────────────────────────────────────────────────────

class ProformaResolutionBlocked(Exception):
    """Raised when proforma cannot be auto-generated (missing customer
    payment terms, unknown currency, ambiguous VAT). Caller MUST block
    creation and route to manual review."""

    def __init__(self, message: str, **details) -> None:
        super().__init__(message)
        self.details = details


@dataclass(frozen=True)
class ContractorTerms:
    """Payment configuration pulled from the wFirma contractor profile.

    payment_method: wFirma string code  ('transfer', 'cash', 'card', ...)
    payment_days:   number of days from doc date to paymentdate
                    None or 0 means "not configured" — caller must decide
                    whether to block or fall back.
    """
    contractor_id:  str
    payment_method: Optional[str] = None
    payment_days:   Optional[int] = None


@dataclass(frozen=True)
class ProformaResolution:
    """Every field the proforma XML writer needs that depends on inputs.

    company_account_id maps to the wFirma <company_account><id>...</id>...
    XML element. (The dataclass also exposes bank_account_id as an alias for
    callers that pre-date the rename.)
    """
    vat_code_id:         int
    language_id:         str
    company_account_id:  str
    payment_method:      str
    payment_days:        int
    payment_date:        date

    @property
    def bank_account_id(self) -> str:
        """Alias — same value as company_account_id. Use company_account_id
        in new code; this is kept for backward compatibility only."""
        return self.company_account_id

    def to_dict(self) -> dict:
        return {
            "vat_code_id":         self.vat_code_id,
            "language_id":         self.language_id,
            "company_account_id":  self.company_account_id,
            "payment_method":      self.payment_method,
            "payment_days":        self.payment_days,
            "payment_date":        self.payment_date.isoformat(),
        }


# ── Live wFirma fetcher (I/O) ────────────────────────────────────────────────

def fetch_contractor_terms(contractor_id: str) -> ContractorTerms:
    """Read payment_method + payment_days from a live wFirma contractor.

    Returns ContractorTerms with values as-stored. None values mean the
    field is empty/unset on the contractor record — caller decides whether
    to block or fall back.

    Raises ConnectionError on network failure.
    Raises ValueError if contractor_id doesn't resolve.
    """
    import re
    from app.services import wfirma_client as wfc

    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <contractors>
    <parameters>
      <conditions>
        <condition><field>id</field><operator>eq</operator><value>{contractor_id}</value></condition>
      </conditions>
      <page><start>0</start><limit>1</limit></page>
    </parameters>
  </contractors>
</api>"""
    http_status, response = wfc._http_request("GET", "contractors", "find", body)
    if http_status >= 400:
        raise ConnectionError(f"contractors/find HTTP {http_status}")

    m = re.search(r"<contractor>(.*?)</contractor>", response, re.DOTALL)
    if not m:
        raise ValueError(f"contractor id={contractor_id} not found")
    body_str = m.group(1)

    pm_match = re.search(r"<payment_method>([^<]*)</payment_method>", body_str)
    pd_match = re.search(r"<payment_days>([^<]*)</payment_days>", body_str)

    payment_method = pm_match.group(1).strip() if pm_match and pm_match.group(1).strip() else None
    payment_days_raw = pd_match.group(1).strip() if pd_match else ""
    payment_days: Optional[int] = None
    if payment_days_raw:
        try:
            payment_days = int(payment_days_raw)
        except ValueError:
            payment_days = None

    return ContractorTerms(
        contractor_id  = str(contractor_id),
        payment_method = payment_method,
        payment_days   = payment_days,
    )


# ── Pure resolver ────────────────────────────────────────────────────────────

def resolve_proforma(
    customer:             CustomerForVAT,
    currency:             str,
    contractor:           ContractorTerms,
    document_date:        date,
    *,
    lang_map:             Optional[Dict[str, int]] = None,
    default_language_id:  str = DEFAULT_LANGUAGE_ID,
    fallback_payment_method: Optional[str] = None,
    fallback_payment_days:   Optional[int] = None,
) -> ProformaResolution:
    """Combine all decisions for a single proforma. Pure function — no I/O.

    Language resolution:
      country in lang_map      → use lang_map[country]
      country not in lang_map  → use default_language_id (operator-overridable)
      default_language_id blank/None → block

    Raises ProformaResolutionBlocked when:
      - currency is not in BANK_ACCOUNT_BY_CURRENCY
      - default_language_id is blank/None AND country missing from lang_map
      - contractor has no payment_method AND no fallback supplied
      - contractor has no payment_days AND no fallback supplied
    Raises ManualReviewRequired (from vat_resolver) when VAT case is ambiguous.

    The customer's vat_eu_valid is taken AS-IS — actual VIES validation
    is a separate layer that runs upstream.
    """
    currency = (currency or "").strip().upper()
    if currency not in BANK_ACCOUNT_BY_CURRENCY:
        raise ProformaResolutionBlocked(
            f"unsupported currency {currency!r} — known: {sorted(BANK_ACCOUNT_BY_CURRENCY)}",
            currency=currency,
        )
    company_account_id = COMPANY_ACCOUNT_BY_CURRENCY[currency]

    # VAT — delegate to existing resolver. Bubble up ManualReviewRequired.
    vat_code_id = pick_vat_code(customer)

    # Language — country in lang_map first, else default_language_id (overridable),
    # else block. We never silently pick a wrong language.
    cmap = lang_map or {}
    country = (customer.country or "").strip().upper()
    if country and country in cmap:
        language_id = str(cmap[country])
    else:
        # default_language_id must be a non-blank string. Treat None / "" as missing.
        cleaned_default = (str(default_language_id) if default_language_id is not None else "").strip()
        if not cleaned_default:
            raise ProformaResolutionBlocked(
                f"language not resolvable: country {country or '(blank)'!r} not in lang_map "
                f"({sorted(cmap)}) and default_language_id is missing/blank. "
                f"Either map this country or supply a non-blank default_language_id.",
                country=country,
                lang_map_keys=sorted(cmap),
            )
        language_id = cleaned_default

    # Payment method — contractor profile first, then fallback, else block
    payment_method = contractor.payment_method or fallback_payment_method
    if not payment_method:
        raise ProformaResolutionBlocked(
            f"contractor {contractor.contractor_id!r} has no payment_method "
            f"and no fallback was supplied. Set payment_method on the "
            f"customer profile in wFirma, or pass fallback_payment_method.",
            contractor_id=contractor.contractor_id,
        )

    # Payment days — same rule
    payment_days = contractor.payment_days
    if payment_days is None or payment_days <= 0:
        if fallback_payment_days is None:
            raise ProformaResolutionBlocked(
                f"contractor {contractor.contractor_id!r} has no payment_days "
                f"and no fallback was supplied. Set payment_days on the "
                f"customer profile in wFirma, or pass fallback_payment_days.",
                contractor_id=contractor.contractor_id,
            )
        payment_days = int(fallback_payment_days)
        if payment_days <= 0:
            raise ProformaResolutionBlocked(
                f"fallback_payment_days must be > 0, got {payment_days}",
            )

    payment_date = document_date + timedelta(days=int(payment_days))

    return ProformaResolution(
        vat_code_id        = vat_code_id,
        language_id        = language_id,
        company_account_id = company_account_id,
        payment_method     = payment_method,
        payment_days       = int(payment_days),
        payment_date       = payment_date,
    )


__all__ = [
    "BANK_ACCOUNT_BY_CURRENCY",        # alias (kept for back-compat)
    "COMPANY_ACCOUNT_BY_CURRENCY",
    "DEFAULT_LANGUAGE_ID",
    "ContractorTerms",
    "ProformaResolution",
    "ProformaResolutionBlocked",
    "fetch_contractor_terms",
    "resolve_proforma",
]
