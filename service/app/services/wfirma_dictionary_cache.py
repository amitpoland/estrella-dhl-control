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


# B0 dictionary refresh 2026-05-17 — runtime in-memory cache of the live
# wFirma catalog. Operator-triggered refresh overwrites the cache; until
# a refresh runs (or after a process restart), get_dictionaries() falls
# back to the baseline. Persistence to disk is intentionally deferred
# (the live wFirma fetch is fast and operator-driven, so an in-memory
# cache is sufficient for now).

_LIVE_CACHE: Dict[str, Any] = {
    "invoice_series":  None,   # None = not refreshed yet; list = live catalog
    "proforma_series": None,
    "fetched_at":      None,
    "source_state": {
        # Each dictionary records its current source:
        #   "baseline"   — hardcoded fallback (no refresh ever ran or live empty)
        #   "live"       — populated from a successful wFirma fetch
        #   "unavailable"— endpoint exists but returned no rows
        #   "error"      — refresh attempt failed (e.g. CONTROLLER NOT FOUND or
        #                  network error). Baseline serves as fallback.
        "invoice_series":  "baseline",
        "proforma_series": "baseline",
        "languages":       "unavailable",   # wFirma exposes no live endpoint
        "currencies":      "unavailable",   # wFirma exposes no live endpoint
        "vat_modes":       "baseline",      # not a remote catalog
    },
}


def _is_visible(entry: Dict[str, str]) -> bool:
    """Filter wFirma series entries that are hidden in the operator UI."""
    vis = (entry.get("visibility") or "").strip().lower()
    return vis in ("", "visible")


def refresh_from_wfirma() -> Dict[str, Any]:
    """Operator-triggered refresh of the live wFirma dictionaries.

    Hard rules:
    - Read-only against wFirma (only ``series/find`` today; languages and
      currencies have no live endpoint and remain on baseline).
    - Never raises. Failures are isolated per dictionary and surface in
      ``source_state``.
    - Merges live entries on top of baseline. Baseline placeholder rows
      stay so the dropdown always has a "Default series" option.
    - Mutates the module-level ``_LIVE_CACHE`` so subsequent
      ``get_dictionaries()`` calls in the same process return the live data.
    """
    import datetime as _dt
    from . import wfirma_client as _wfc

    invoice_live:  List[Dict[str, Any]] = []
    proforma_live: List[Dict[str, Any]] = []
    invoice_state  = "baseline"
    proforma_state = "baseline"

    try:
        all_series = _wfc.fetch_series()
    except Exception:
        all_series = []

    if all_series:
        # Split by type. wFirma series types: normal, margin, proforma,
        # offer, spec. Invoice surfaces use normal + margin (real-invoice
        # shapes). Offer / spec series stay out — they are not invoice
        # defaults.
        for s in all_series:
            if not _is_visible(s):
                continue
            entry = {"id": s["id"], "label": s["label"], "code": s.get("code", "")}
            t = s.get("type") or ""
            if t in ("normal", "margin"):
                invoice_live.append(entry)
            elif t == "proforma":
                proforma_live.append(entry)
        invoice_state  = "live" if invoice_live  else "unavailable"
        proforma_state = "live" if proforma_live else "unavailable"
    else:
        # Endpoint returned nothing — either CONTROLLER NOT FOUND or
        # network error. Mark error; baseline serves.
        invoice_state  = "error"
        proforma_state = "error"

    _LIVE_CACHE["invoice_series"]  = invoice_live  or None
    _LIVE_CACHE["proforma_series"] = proforma_live or None
    _LIVE_CACHE["source_state"]["invoice_series"]  = invoice_state
    _LIVE_CACHE["source_state"]["proforma_series"] = proforma_state
    _LIVE_CACHE["fetched_at"] = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    return get_dictionaries()


def get_dictionaries() -> Dict[str, Any]:
    """Return the merged dictionary payload (baseline + any live overlay).

    Live entries (from a successful ``refresh_from_wfirma()`` call in the
    same process) overlay the baseline. ``source_state`` tells the
    operator UI whether each dictionary is live, baseline, unavailable,
    or in error.
    """
    # Build invoice_series: baseline placeholder + live entries (de-duped by id)
    inv_live  = _LIVE_CACHE.get("invoice_series")  or []
    pro_live  = _LIVE_CACHE.get("proforma_series") or []
    seen_inv: set = {e["id"] for e in inv_live}
    seen_pro: set = {e["id"] for e in pro_live}
    invoice_series  = list(INVOICE_SERIES) + [e for e in inv_live  if e["id"] not in {b["id"] for b in INVOICE_SERIES}]
    proforma_series = list(PROFORMA_SERIES) + [e for e in pro_live if e["id"] not in {b["id"] for b in PROFORMA_SERIES}]

    return {
        "vat_modes":       list(VAT_MODES),
        "currencies":      list(CURRENCIES),
        "languages":       list(LANGUAGES),
        "invoice_series":  invoice_series,
        "proforma_series": proforma_series,
        "source":          "baseline" if not (inv_live or pro_live) else "merged",
        "source_state":    dict(_LIVE_CACHE["source_state"]),
        "fetched_at":      _LIVE_CACHE.get("fetched_at"),
        "version":         "2026-05-17",
    }
