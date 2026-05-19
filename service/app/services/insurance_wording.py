"""
insurance_wording.py — Canonical insurance line-name generator.

Why this exists
    Insurance line names on wFirma proformas and final invoices must be
    identical, deterministic, and legally precise.  Scattering the string
    literal across ``routes_proforma``, ``customer_master``, and test tools
    creates drift and makes compliance review hard.

    This module is the single source of truth for every insurance-related
    wording string that appears in commercial documents.

Rules
-----
- Pure functions only. No I/O, no DB, no HTTP.
- DEFAULT_INSURANCE_LINE_NAME is the canonical output when no overrides are
  supplied. Never change this without a compliance sign-off.
- build_insurance_line_name() is deterministic: same inputs → same output,
  always, across Python versions and locales.
- Unicode-safe: all strings are returned as str (Python 3 unicode).
- No line-length truncation — the caller is responsible for any wrapping in
  PDF / UI layers.

Propagation contract
--------------------
The string returned by build_insurance_line_name() is used as:
  1. ReservationLine.product_name → <invoicecontent><name> in proforma XML
  2. Preserved verbatim by proforma_to_invoice.py on invoice conversion
  3. Included in preview responses (insurance_line_name field)
  4. PDF/export layer reads from wFirma XML (no separate propagation needed)

Any layer that currently hardcodes an insurance wording string should be
migrated to call this function.  grep-target: INSURANCE_WORDING_LITERAL.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ── Constants (do not duplicate these elsewhere) ─────────────────────────────

DEFAULT_PROVIDER = "Future Generali India Insurance Company Limited"

DEFAULT_COVERAGE = "Door to Door"

#: The canonical insurance line name that appears on commercial documents.
#: grep-target: INSURANCE_WORDING_LITERAL
DEFAULT_INSURANCE_LINE_NAME: str = (
    "Insurance covers the Door to Door delivery of this package "
    "by Future Generali India Insurance Company Limited."
)

#: The same wording in Polish, for dual-language documents.
DEFAULT_INSURANCE_LINE_NAME_PL: str = (
    "Ubezpieczenie obejmuje dostawę Door to Door tej przesyłki "
    "przez Future Generali India Insurance Company Limited."
)


# ── Input schema ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class InsuranceWordingInput:
    """
    All parameters that may influence the insurance line name.

    Every field has a safe default so callers can pass only the fields
    that differ from the standard case.

    Fields
    ------
    insurance_mode
        ``door_to_door`` (default) | ``warehouse_to_door`` | ``cif_only``
    insurance_provider
        Full legal name of the insurer.  Defaults to Future Generali.
    shipment_mode
        ``air`` | ``sea`` | ``road`` | ``courier`` — currently informational
        only; reserved for future wording variants.
    destination_country
        ISO 3166-1 alpha-2 or full name — informational only for now.
    coverage_type
        ``door_to_door`` | ``warehouse_to_port`` | ``cif`` — maps to coverage
        description in the wording.
    language
        ``en`` (default) | ``pl`` — language of the output string.
    """
    insurance_mode:      str = "door_to_door"
    insurance_provider:  str = DEFAULT_PROVIDER
    shipment_mode:       str = "air"
    destination_country: str = ""
    coverage_type:       str = "door_to_door"
    language:            str = "en"


# ── Builder (core function) ───────────────────────────────────────────────────

def build_insurance_line_name(
    inp: Optional[InsuranceWordingInput] = None,
) -> str:
    """
    Return the canonical insurance line name for a commercial document.

    This is the single authoritative function for generating insurance
    wording.  All other modules that need an insurance line name MUST call
    this function — never construct the string inline.

    Rules
    -----
    - If ``inp`` is None, return ``DEFAULT_INSURANCE_LINE_NAME``.
    - Provider must be a non-empty string; falls back to DEFAULT_PROVIDER.
    - Coverage description follows ``coverage_type``:
        - ``door_to_door`` / ``door_to_door_delivery`` → "Door to Door"
        - ``warehouse_to_port`` → "Warehouse to Port"
        - ``cif`` → "CIF"
        - anything else → "Door to Door" (safe fallback)
    - Language ``pl`` → Polish wording; anything else → English.
    - Output is always a single-line string. No newlines inserted.

    Determinism guarantee: same inputs → same output, no randomness, no
    timestamp, no external state.

    Args:
        inp: ``InsuranceWordingInput`` instance, or None for the default.

    Returns:
        str: The canonical insurance line name.
    """
    if inp is None:
        return DEFAULT_INSURANCE_LINE_NAME

    provider = (inp.insurance_provider or "").strip() or DEFAULT_PROVIDER

    # Coverage description
    ct = (inp.coverage_type or "").strip().lower().replace("-", "_")
    if ct in ("door_to_door", "door_to_door_delivery", ""):
        coverage_en = "Door to Door"
        coverage_pl = "Door to Door"
    elif ct in ("warehouse_to_port", "warehouse_port"):
        coverage_en = "Warehouse to Port"
        coverage_pl = "Magazyn do Portu"
    elif ct == "cif":
        coverage_en = "CIF"
        coverage_pl = "CIF"
    else:
        coverage_en = "Door to Door"
        coverage_pl = "Door to Door"

    lang = (inp.language or "en").strip().lower()
    if lang == "pl":
        return (
            f"Ubezpieczenie obejmuje dostawę {coverage_pl} tej przesyłki "
            f"przez {provider}."
        )
    else:
        return (
            f"Insurance covers the {coverage_en} delivery of this package "
            f"by {provider}."
        )


def default_insurance_line_name() -> str:
    """Convenience wrapper that returns DEFAULT_INSURANCE_LINE_NAME.

    Prefer build_insurance_line_name(None) in new code; this alias exists
    for callers that need a zero-argument callable.
    """
    return DEFAULT_INSURANCE_LINE_NAME


__all__ = [
    "DEFAULT_PROVIDER",
    "DEFAULT_COVERAGE",
    "DEFAULT_INSURANCE_LINE_NAME",
    "DEFAULT_INSURANCE_LINE_NAME_PL",
    "InsuranceWordingInput",
    "build_insurance_line_name",
    "default_insurance_line_name",
]
