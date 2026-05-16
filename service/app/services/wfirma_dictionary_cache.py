"""wfirma_dictionary_cache.py — operator-facing dictionaries for the
Client Master UI.

Provides human-readable labels for wFirma technical IDs so the dashboard
can render dropdowns instead of raw-ID text inputs. Backend storage and
the wFirma API contract still use the integer/string IDs verbatim — this
module is a pure presentation layer.

Sources (in priority order)
---------------------------
1. **Baseline (hardcoded):** VAT modes (222/228/229), common currencies,
   common languages, common series shapes. These are derived from
   wFirma's published documentation and the production catalog we have
   already observed in real responses (PR #152 deep-fetch live data).
2. **Live refresh (deferred):** a future batch may fetch series and
   languages from wFirma's read-only ``invoiceseries/find`` and
   ``languages/find`` endpoints and merge them on top of the baseline.
   This module exposes a ``refresh_from_wfirma()`` stub the future PR
   can flesh out without changing the public API.

Hard rule: this module NEVER calls wFirma write endpoints. It is
read-only and tolerant to wFirma being unreachable — the baseline
dictionaries are always present.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# ── VAT modes ────────────────────────────────────────────────────────────────
# wFirma uses three numeric codes for the invoice VAT mode.

VAT_MODES: List[Dict[str, Any]] = [
    {"id": 222, "code": "standard",       "label": "Standard (Polish 23%)"},
    {"id": 228, "code": "reverse_charge", "label": "EU Reverse Charge"},
    {"id": 229, "code": "export_0",       "label": "Export 0%"},
]


# ── Currencies ───────────────────────────────────────────────────────────────
# Locally accepted commercial currencies. The PZ engine reads NBP live rates;
# this dictionary is purely UI presentation.

CURRENCIES: List[Dict[str, Any]] = [
    {"code": "EUR", "label": "EUR · Euro"},
    {"code": "USD", "label": "USD · US Dollar"},
    {"code": "PLN", "label": "PLN · Polish Złoty"},
    {"code": "GBP", "label": "GBP · British Pound"},
    {"code": "CHF", "label": "CHF · Swiss Franc"},
    {"code": "JPY", "label": "JPY · Japanese Yen"},
]


# ── Languages ────────────────────────────────────────────────────────────────
# wFirma translation_language_id values commonly observed. Each entry pairs
# the wFirma-internal id with an operator-friendly label.
# Source: production wFirma deep-fetch responses (PR #152).

LANGUAGES: List[Dict[str, Any]] = [
    {"id": "",   "label": "— Default (use account language)"},
    {"id": "1",  "label": "Polish (Polski)"},
    {"id": "2",  "label": "English"},
    {"id": "3",  "label": "German (Deutsch)"},
    {"id": "4",  "label": "French (Français)"},
    {"id": "5",  "label": "Italian (Italiano)"},
    {"id": "6",  "label": "Spanish (Español)"},
]


# ── Invoice series ───────────────────────────────────────────────────────────
# Series IDs are wFirma account-specific. The baseline gives the operator
# a starting set with the empty option for "use account default"; the live
# refresh path can extend this with the customer's actual catalog.

INVOICE_SERIES: List[Dict[str, Any]] = [
    {"id": "", "label": "— Default series"},
]

PROFORMA_SERIES: List[Dict[str, Any]] = [
    {"id": "", "label": "— Default series"},
]


# ── Public API ───────────────────────────────────────────────────────────────


def get_dictionaries() -> Dict[str, Any]:
    """Return all dictionaries as a single payload for the dashboard.

    Stable shape:
        {
          "vat_modes":      [{id, code, label}, ...],
          "currencies":     [{code, label}, ...],
          "languages":      [{id, label}, ...],
          "invoice_series": [{id, label}, ...],
          "proforma_series":[{id, label}, ...],
          "source":         "baseline" | "wfirma_refreshed",
          "version":        ISO-date when this baseline was minted,
        }

    The frontend uses this single payload to populate every dropdown in
    the Client Master KYC modal — replacing the previous raw-ID text
    inputs.
    """
    return {
        "vat_modes":       list(VAT_MODES),
        "currencies":      list(CURRENCIES),
        "languages":       list(LANGUAGES),
        "invoice_series":  list(INVOICE_SERIES),
        "proforma_series": list(PROFORMA_SERIES),
        "source":          "baseline",
        "version":         "2026-05-16",
    }


def label_for_vat_mode(mode_id: Optional[int]) -> str:
    """Return the human-readable label for a vat_mode integer."""
    if mode_id is None:
        return "—"
    for m in VAT_MODES:
        if m["id"] == int(mode_id):
            return m["label"]
    return str(mode_id)


def label_for_currency(code: Optional[str]) -> str:
    """Return the human-readable label for a currency code."""
    if not code:
        return "—"
    code = (code or "").upper()
    for c in CURRENCIES:
        if c["code"] == code:
            return c["label"]
    return code


def label_for_language(lang_id: Optional[str]) -> str:
    """Return the human-readable label for a wFirma translation_language_id."""
    if not lang_id:
        return "— Default (use account language)"
    lang_id = str(lang_id)
    for L in LANGUAGES:
        if L["id"] == lang_id:
            return L["label"]
    return f"Language #{lang_id}"


def refresh_from_wfirma() -> Dict[str, Any]:
    """Future-batch stub: refresh series + languages from wFirma's
    read-only catalogs. Returns the current dictionaries unchanged
    until the live fetch is wired up.

    Hard rule when implemented:
    - Read-only against wFirma (``invoiceseries/find`` + ``languages/find``).
    - Never raises; on error returns the baseline.
    - Merges the live catalog ON TOP of the baseline (baseline entries
      stay; live entries appended; duplicates by id de-duplicated).
    """
    return get_dictionaries()
