"""commercial_lookup.py — CommercialLookupService.

The ONE authority for operator-selectable commercial enumerations used across
the Proforma commercial surface: payment methods, invoice languages, VAT/WDT
modes, and freight/insurance service products.

Every route that lists or validates these values consumes THIS module instead of
maintaining its own table, so the frontend dropdowns, Customer Master record
validation, the operator set-commercial-defaults editor, the service-charge
editor, and any future wFirma sync cannot drift apart. One concept → one
authority (EJ Engineering Constitution).

It FEDERATES existing sources of truth (it does not duplicate them):

  * payment methods / invoice languages / VAT modes → the wFirma-backed
    dictionary constants (``wfirma_dictionary_cache.PAYMENT_METHODS`` /
    ``LANGUAGES`` / ``VAT_MODES``) — the same values ``get_dictionaries()``
    serves to the UI. No network in the validation path (these are baseline
    enum constants; only the series catalog has a live fetch).
  * freight / insurance service products → the proforma service-product
    registry (``proforma_invoice_link_db.get_all_service_product_meta``).

Validation helpers accept ints or strings and normalise before comparison so a
caller cannot be tripped by a typed value (e.g. VAT mode as int ``228``).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from . import wfirma_dictionary_cache as _wdc

# Charge types that carry a wFirma service-product mapping.
SERVICE_CHARGE_TYPES = ("freight", "insurance")


# ── List authorities (label + id) ─────────────────────────────────────────────

def payment_methods() -> List[Dict[str, Any]]:
    return [dict(m) for m in _wdc.PAYMENT_METHODS]


def invoice_languages() -> List[Dict[str, Any]]:
    return [dict(x) for x in _wdc.LANGUAGES]


def vat_modes() -> List[Dict[str, Any]]:
    return [dict(x) for x in _wdc.VAT_MODES]


# ── Id sets (validation authorities) ──────────────────────────────────────────

def payment_method_ids() -> frozenset:
    return frozenset(str(m["id"]).strip().lower() for m in _wdc.PAYMENT_METHODS)


def invoice_language_ids() -> frozenset:
    # "" (use account default language) is a valid selection.
    return frozenset(str(x["id"]).strip() for x in _wdc.LANGUAGES)


def vat_mode_ids() -> frozenset:
    return frozenset(str(x["id"]).strip() for x in _wdc.VAT_MODES)


# ── Validators (return bool; callers map False → their own 4xx) ────────────────

def validate_payment_method(value: Any) -> bool:
    return str(value if value is not None else "").strip().lower() in payment_method_ids()


def validate_invoice_language(value: Any) -> bool:
    return str(value if value is not None else "").strip() in invoice_language_ids()


def validate_vat_mode(value: Any) -> bool:
    return str(value if value is not None else "").strip() in vat_mode_ids()


def validate_charge_type(value: Any) -> bool:
    return str(value if value is not None else "").strip().lower() in SERVICE_CHARGE_TYPES


# ── Freight / insurance service products (from the registry) ───────────────────

def _service_products(db_path: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    if db_path is None:
        return {}
    try:
        from . import proforma_invoice_link_db as _pildb
        return _pildb.get_all_service_product_meta(db_path) or {}
    except Exception:
        return {}


def service_products(db_path: Optional[Path]) -> List[Dict[str, Any]]:
    meta = _service_products(db_path)
    out: List[Dict[str, Any]] = []
    for ct in SERVICE_CHARGE_TYPES:
        m = meta.get(ct) or {}
        out.append({
            "charge_type":       ct,
            "wfirma_product_id": m.get("wfirma_product_id"),
            "product_name":      m.get("product_name"),
        })
    return out


def freight_products(db_path: Optional[Path]) -> List[Dict[str, Any]]:
    return [p for p in service_products(db_path) if p["charge_type"] == "freight"]


def insurance_products(db_path: Optional[Path]) -> List[Dict[str, Any]]:
    return [p for p in service_products(db_path) if p["charge_type"] == "insurance"]


def validate_service_product(charge_type: Any, wfirma_product_id: Any) -> bool:
    """A registered service-product reference is a non-empty id on a valid
    freight/insurance charge type. The registry maps the id → a wFirma good at
    posting; this authority only asserts the shape/enum, never invents a value.
    """
    if not validate_charge_type(charge_type):
        return False
    return bool(str(wfirma_product_id if wfirma_product_id is not None else "").strip())
