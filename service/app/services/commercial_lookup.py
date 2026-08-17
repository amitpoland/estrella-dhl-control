"""commercial_lookup.py — CommercialLookupService.

The ONE authority for operator-selectable commercial enumerations used across
the Proforma commercial surface: payment methods, invoice languages, VAT/WDT
modes, document currencies, and freight/insurance service products.

Every route that lists or validates these values consumes THIS module instead of
maintaining its own table, so the frontend dropdowns, Customer Master record
validation, the operator set-commercial-defaults editor, the service-charge
editor, and any future wFirma sync cannot drift apart. One concept → one
authority (EJ Engineering Constitution).

It FEDERATES existing sources of truth (it does not duplicate them):

  * payment methods / VAT modes → the wFirma-backed dictionary constants
    (``wfirma_dictionary_cache.PAYMENT_METHODS`` / ``VAT_MODES``).
  * invoice languages (Polish / English) → THIS module's canonical map
    (Polish = 0, English = 1). ``wfirma_dictionary_cache.LANGUAGES`` labels
    the same ids for display; it is not a second mapping authority.
  * document currencies → ``nbp_rate_service.CURRENCY_REGISTRY`` (PLN hub FX).
  * freight / delivery methods (Freight / Fedex Courier) → THIS module's
    canonical map (Freight = 17833901, Fedex Courier = 13002743). These are
    distinct wFirma good_ids — never aliases for each other.
  * freight / insurance service-product *metadata* (name/VAT/unit) → the
    proforma service-product registry
    (``proforma_invoice_link_db.get_all_service_product_meta``).

Validation helpers accept ints or strings and normalise before comparison so a
caller cannot be tripped by a typed value (e.g. VAT mode as int ``228``).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from . import nbp_rate_service as _nbp
from . import wfirma_dictionary_cache as _wdc

# Charge types that carry a wFirma service-product mapping.
SERVICE_CHARGE_TYPES = ("freight", "insurance")

# Canonical language map (operator-confirmed). Polish = 0, English = 1.
# Do not invert. "0" is a real language id (Polish), not a drop-sentinel.
WFIRMA_LANG_POLISH = "0"
WFIRMA_LANG_ENGLISH = "1"
WFIRMA_LANG_GERMAN = "3"
INTENDED_TRANSLATION_LANGUAGE_ID = WFIRMA_LANG_ENGLISH

LANGUAGE_CHOICES: List[Dict[str, str]] = [
    {"id": "", "code": "", "label": "— Default (use account language)"},
    {"id": WFIRMA_LANG_POLISH, "code": "PL", "label": "Polish"},
    {"id": WFIRMA_LANG_ENGLISH, "code": "EN", "label": "English"},
]

# Canonical freight / delivery method map. These ids are NOT aliases.
FREIGHT_METHOD_FREIGHT = "17833901"
FREIGHT_METHOD_FEDEX_COURIER = "13002743"
FREIGHT_METHOD_DEFAULT = FREIGHT_METHOD_FEDEX_COURIER  # D2: default stays Fedex Courier
FREIGHT_METHOD_IDS = frozenset({FREIGHT_METHOD_FREIGHT, FREIGHT_METHOD_FEDEX_COURIER})

FREIGHT_METHOD_CHOICES: List[Dict[str, str]] = [
    {"id": FREIGHT_METHOD_FREIGHT, "code": "freight", "label": "Freight"},
    {"id": FREIGHT_METHOD_FEDEX_COURIER, "code": "fedex_courier", "label": "Fedex Courier"},
]


# ── List authorities (label + id) ─────────────────────────────────────────────

def payment_methods() -> List[Dict[str, Any]]:
    return [dict(m) for m in _wdc.PAYMENT_METHODS]


def invoice_languages() -> List[Dict[str, Any]]:
    """Operator-selectable languages. Canonical ids: Polish=0, English=1."""
    return [dict(x) for x in LANGUAGE_CHOICES]


def invoice_language_label(language_id: Any) -> str:
    lid = str(language_id if language_id is not None else "").strip()
    for row in LANGUAGE_CHOICES:
        if str(row.get("id", "")).strip() == lid:
            return str(row.get("label") or lid)
    for row in _wdc.LANGUAGES:
        if str(row.get("id", "")).strip() == lid:
            return str(row.get("label") or lid)
    return lid or "— Default (use account language)"


def currencies() -> List[Dict[str, Any]]:
    """Controlled document currencies (PLN / USD / EUR / INR)."""
    return _nbp.currencies()


def vat_modes() -> List[Dict[str, Any]]:
    return [dict(x) for x in _wdc.VAT_MODES]


def resolve_translation_language_id(
    draft_language_id: Any = None,
    cm_language_id: Any = None,
) -> Dict[str, Any]:
    """Pick the translation language for Proforma/Invoice XML.

    Authority order:
      1. Saved draft ``invoice_language_id`` (operator commercial terms)
      2. Customer Master default — but NEVER accidental German (id 3);
         German from CM alone falls back to English with a warning
      3. Intended commercial default: English (Polish is the account base)

    Returns ``{"language_id", "label", "source", "warning"}``.
    """
    draft = str(draft_language_id if draft_language_id is not None else "").strip()
    cm = str(cm_language_id if cm_language_id is not None else "").strip()
    warning = None

    if draft:
        # Operator explicitly saved a draft value — honour it (incl. German).
        return {
            "language_id": draft,
            "label": invoice_language_label(draft),
            "source": "draft",
            "warning": warning,
        }

    if cm and cm != WFIRMA_LANG_GERMAN:
        return {
            "language_id": cm,
            "label": invoice_language_label(cm),
            "source": "customer_master",
            "warning": warning,
        }

    if cm == WFIRMA_LANG_GERMAN:
        warning = (
            "Customer Master default_language_id is German (3); "
            "commercial documents default to English (1) unless the operator "
            "explicitly saves German on the draft"
        )

    return {
        "language_id": INTENDED_TRANSLATION_LANGUAGE_ID,
        "label": invoice_language_label(INTENDED_TRANSLATION_LANGUAGE_ID),
        "source": "intended_commercial_default",
        "warning": warning,
    }

# ── Id sets (validation authorities) ──────────────────────────────────────────

def payment_method_ids() -> frozenset:
    return frozenset(str(m["id"]).strip().lower() for m in _wdc.PAYMENT_METHODS)


def invoice_language_ids() -> frozenset:
    # "" (use account default language) is a valid selection.
    # Canonical 0/1 plus legacy catalog ids remain valid stored values.
    selectable = frozenset(str(x["id"]).strip() for x in LANGUAGE_CHOICES)
    legacy = frozenset(str(x["id"]).strip() for x in _wdc.LANGUAGES)
    return selectable | legacy


def vat_mode_ids() -> frozenset:
    return frozenset(str(x["id"]).strip() for x in _wdc.VAT_MODES)


# ── Validators (return bool; callers map False → their own 4xx) ────────────────

def validate_payment_method(value: Any) -> bool:
    return str(value if value is not None else "").strip().lower() in payment_method_ids()


def validate_invoice_language(value: Any) -> bool:
    return str(value if value is not None else "").strip() in invoice_language_ids()


def validate_vat_mode(value: Any) -> bool:
    return str(value if value is not None else "").strip() in vat_mode_ids()


def validate_currency(value: Any) -> bool:
    return _nbp.is_document_currency(value)


def validate_charge_type(value: Any) -> bool:
    return str(value if value is not None else "").strip().lower() in SERVICE_CHARGE_TYPES


# ── Canonical language / freight-method resolvers ─────────────────────────────

_LANG_BY_TOKEN = {
    "0": WFIRMA_LANG_POLISH,
    "pl": WFIRMA_LANG_POLISH,
    "polish": WFIRMA_LANG_POLISH,
    "polski": WFIRMA_LANG_POLISH,
    "1": WFIRMA_LANG_ENGLISH,
    "en": WFIRMA_LANG_ENGLISH,
    "english": WFIRMA_LANG_ENGLISH,
}

_FREIGHT_BY_TOKEN = {
    FREIGHT_METHOD_FREIGHT: FREIGHT_METHOD_FREIGHT,
    "freight": FREIGHT_METHOD_FREIGHT,
    "fracht": FREIGHT_METHOD_FREIGHT,
    FREIGHT_METHOD_FEDEX_COURIER: FREIGHT_METHOD_FEDEX_COURIER,
    "fedex courier": FREIGHT_METHOD_FEDEX_COURIER,
    "fedex": FREIGHT_METHOD_FEDEX_COURIER,
    "fedex_courier": FREIGHT_METHOD_FEDEX_COURIER,
}


def map_language_selection(selection: Any) -> Optional[str]:
    """Map a semantic language choice to the canonical numeric id.

    Polish/PL/0 → 0. English/EN/1 → 1. Unknown values are not guessed.
    """
    token = str(selection if selection is not None else "").strip().lower()
    if not token:
        return None
    return _LANG_BY_TOKEN.get(token)


def resolve_language_id(
    selection: Any = None,
    customer_override: Any = None,
) -> Optional[str]:
    """Pick the outgoing translation_language id.

    Precedence: explicit selected language wins, then a stored customer
    value (including legacy catalog ids), else None (omit / account default).
    Never inverts 0/1.
    """
    mapped = map_language_selection(selection)
    if mapped is not None:
        return mapped
    raw = str(selection if selection is not None else "").strip()
    if raw:
        return raw
    cust = str(customer_override if customer_override is not None else "").strip()
    return cust or None


def freight_method_choices() -> List[Dict[str, Any]]:
    return [dict(x) for x in FREIGHT_METHOD_CHOICES]


def freight_method_label(method_id: Any) -> str:
    mid = str(method_id if method_id is not None else "").strip()
    for row in FREIGHT_METHOD_CHOICES:
        if row["id"] == mid:
            return row["label"]
    return mid or "—"


def map_freight_method_selection(selection: Any) -> Optional[str]:
    """Map a semantic freight/delivery choice to the canonical good_id.

    Freight → 17833901. Fedex Courier → 13002743. Never translates one
    canonical id into the other.
    """
    token = str(selection if selection is not None else "").strip().lower()
    if not token:
        return None
    return _FREIGHT_BY_TOKEN.get(token)


def resolve_freight_method_id(
    selection: Any = None,
    customer_override: Any = None,
    default: Optional[str] = FREIGHT_METHOD_DEFAULT,
) -> Optional[str]:
    """Pick the outgoing freight/delivery-method good_id.

    Precedence:
      1. explicit operator/customer-specific configured method (stored as-is)
      2. canonical mapped id for the selected semantic method
      3. existing safe fallback (Fedex Courier) only when nothing is selected

    17833901 and 13002743 are never rewritten into each other.
    """
    cust = str(customer_override if customer_override is not None else "").strip()
    if cust:
        return cust
    mapped = map_freight_method_selection(selection)
    if mapped is not None:
        return mapped
    raw = str(selection if selection is not None else "").strip()
    if raw:
        return raw
    fallback = str(default).strip() if default is not None else ""
    return fallback or None


def is_canonical_freight_method_id(good_id: Any) -> bool:
    return str(good_id if good_id is not None else "").strip() in FREIGHT_METHOD_IDS


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
