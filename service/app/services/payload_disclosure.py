"""
payload_disclosure.py — Phase 9: Payload disclosure for wFirma writes.

Before any wFirma write (proforma post, invoice convert), the operator must
see EXACTLY what will be written. This module builds the disclosure payload
from the draft/proforma data WITHOUT making any wFirma calls.

BOUNDARIES (HARD):
  - NEVER writes to wFirma
  - NEVER writes to any DB
  - Read-only: builds the disclosure from local data only
  - No side effects

The operator sees the disclosure in a modal (UI) before clicking "Confirm."
Only after explicit confirmation is the actual write endpoint called.

Two disclosure types:
  1. proforma_post: shows the proforma XML that will be sent to wFirma invoices/add
  2. invoice_convert: shows the final invoice XML that will be created from the proforma
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


# ── Proforma post disclosure ──────────────────────────────────────────────────

def build_proforma_post_disclosure(draft: Any) -> Dict[str, Any]:
    """Build the payload disclosure for a proforma post (WF2.4).

    draft: a ProformaDraft instance or dict.
    Returns a JSON-serialisable disclosure dict showing what will be sent to wFirma.
    No wFirma call. No DB write.
    """
    def _get(key: str, default="") -> Any:
        if hasattr(draft, key):
            return getattr(draft, key, default)
        if isinstance(draft, dict):
            return draft.get(key, default)
        return default

    try:
        import json
        lines = json.loads(_get("editable_lines_json", "[]") or "[]")
    except Exception:
        lines = []

    try:
        import json
        service_charges = json.loads(_get("service_charges_json", "[]") or "[]")
    except Exception:
        service_charges = []

    currency        = _get("currency", "")
    client_name     = _get("client_name", "")
    remarks         = _get("remarks", "")
    draft_id        = _get("id", "")
    batch_id        = _get("batch_id", "")
    incoterm        = _get("incoterm", "")
    # ADR-027 D4 — frozen VAT context (set at post time by freeze_draft_vat_context)
    vat_context     = _get("vat_context", "") or ""
    vat_code        = _get("vat_code", "") or ""
    decision_source = _get("decision_source", "") or ""

    # ADR-027 D3/D5: surface VAT warnings in the modal
    vat_warnings: List[str] = []
    if vat_context == "wdt":
        # Re-check VIES status from the stored draft context if available.
        # The actual warning list is populated at post time by the builder;
        # here we re-derive a disclosure-level hint from the frozen state.
        pass  # warnings come from _post_vat_warnings at post time; frozen fields shown here

    disclosure: Dict[str, Any] = {
        "disclosure_type":  "proforma_post",
        "draft_id":         draft_id,
        "batch_id":         batch_id,
        "write_target":     "wFirma invoices/add (proforma type)",
        "flag_required":    "WFIRMA_CREATE_PROFORMA_ALLOWED",
        "fields_to_write": {
            "client_name":          client_name,
            "currency":             currency,
            "incoterm":             incoterm,
            "remarks":              remarks,
            "line_count":           len(lines),
            "service_charge_count": len(service_charges),
        },
        "lines": [
            {
                "product_code": ln.get("product_code", ""),
                "design_no":    ln.get("design_no", ""),
                "qty":          ln.get("qty", 0),
                "unit_price":   ln.get("unit_price", 0),
                "currency":     ln.get("currency", currency),
            }
            for ln in lines[:50]  # cap at 50 for display
        ],
        "service_charges": service_charges[:10],
        "confirm_token_required": "YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA",
        "warning": (
            "This action will CREATE a proforma in your live wFirma account. "
            "Verify all fields before confirming."
        ),
        # ADR-027 D4 — VAT context frozen at draft creation / first post
        "vat_resolution": {
            "vat_context":     vat_context,
            "vat_code":        vat_code,
            "decision_source": decision_source,
            # Warn if context is set but no code string (should never happen)
            "draft_has_vat_freeze": bool(vat_context and vat_code),
        },
    }
    return disclosure


# ── Invoice convert disclosure ────────────────────────────────────────────────

_PM_MAP_TO_EN = {
    "przelew":    "transfer",
    "gotowka":    "cash",
    "karta":      "card",
    "kompensata": "compensation",
}

_PM_MAP_TO_WF = {v: k for k, v in _PM_MAP_TO_EN.items()}


def build_invoice_convert_disclosure(
    proforma_snap: Any,
    final_series_id: Optional[str] = None,
    operator: str = "",
    draft_method: str = "",
    draft_days: Optional[int] = None,
    draft_invoice_date: Optional[str] = None,
    draft_sale_date: Optional[str] = None,
    customer_default_method: str = "",
    customer_default_days: Optional[int] = None,
    description_preview: Optional[str] = None,
    payload_core_hash_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the payload disclosure for a proforma→invoice convert (WF2.5).

    proforma_snap: a ProformaSnapshot instance or dict (from parse_proforma_xml).
    customer_default_method: preferred_payment_method from customer_master (English).
    customer_default_days:   payment_terms_days from customer_master.
    description_preview: when provided (str), included in result as "description_preview"
        — the exact final invoice description that will be posted to wFirma.  Callers
        that supply this should also supply payload_core_hash_override so the hash is
        consistent with the description-covering execute path.
    payload_core_hash_override: when provided (str), used as "payload_core_hash" instead
        of the internally-computed hash.  Legacy callers (no override) keep old behavior.
    Returns a JSON-serialisable disclosure dict.
    No wFirma call. No DB write.
    """
    def _get(key: str, default="") -> Any:
        if hasattr(proforma_snap, key):
            return getattr(proforma_snap, key, default)
        if isinstance(proforma_snap, dict):
            return proforma_snap.get(key, default)
        return default

    proforma_number  = _get("proforma_number", "")
    contractor_id    = _get("contractor_id", "")
    currency         = _get("currency", "")
    # None = caller did not resolve a series (legacy) → fall back to the snap's own.
    # ""   = ADR-027 D6 step 3: series validly resolved to EMPTY (<series> omitted,
    #        wFirma contractor default). Must NOT fall back to the proforma's series —
    #        the execute path hashes "" and a falsy fallback here desynchronises
    #        payload_core_hash (Opus review D-1).
    series_id        = _get("series_id", "") if final_series_id is None else final_series_id
    # RC-1 fix: ProformaSnapshot field is `contents`, not `lines`
    source_lines     = _get("contents", []) or []

    # Payment method resolution: draft saved > wFirma XML (Polish) > customer master
    snap_method_wf   = (_get("paymentmethod", "") or "").strip()
    snap_method_en   = _PM_MAP_TO_EN.get(snap_method_wf, snap_method_wf)
    snap_paymentdate = (_get("paymentdate", "") or "").strip()
    resolved_method  = draft_method or snap_method_en or customer_default_method or ""
    resolved_source  = (
        "draft_saved"    if draft_method else
        "wfirma_proforma" if snap_method_en else
        "customer_master" if customer_default_method else
        "not_set"
    )

    # RC-1 fix: line projection uses correct LineItem field names.
    # Backward-compat: also accept dict-input (legacy callers).
    def _proj_line(ln) -> Dict[str, Any]:
        if isinstance(ln, dict):
            return {
                "good_id":    str(ln.get("good_id", "") or ""),
                "name":       str(ln.get("name", "") or ""),
                "unit_count": str(ln.get("unit_count", "") or ""),
                "price":      str(ln.get("price", "") or ""),
                "currency":   currency,
            }
        return {
            "good_id":    str(getattr(ln, "good_id", "") or ""),
            "name":       str(getattr(ln, "name", "") or ""),
            "unit_count": str(getattr(ln, "unit_count", "") or ""),
            "price":      str(getattr(ln, "price", "") or ""),
            "currency":   currency,
        }

    projected_lines = [_proj_line(ln) for ln in source_lines[:50]]

    # grand_total = sum(price × unit_count) across all source lines
    _grand_total = Decimal("0")
    for ln in source_lines:
        try:
            if isinstance(ln, dict):
                _p = Decimal(str(ln.get("price", "0") or "0"))
                _q = Decimal(str(ln.get("unit_count", "1") or "1"))
            else:
                _p = Decimal(str(getattr(ln, "price", "0") or "0"))
                _q = Decimal(str(getattr(ln, "unit_count", "1") or "1"))
            _grand_total += _p * _q
        except InvalidOperation:
            pass  # safe fallback: skip malformed line
    grand_total = str(_grand_total)

    # series_name from wfirma_dictionary_cache (graceful on miss / error)
    series_name = "wFirma contractor default" if not series_id else ""
    series_name_note = ""
    try:
        from .wfirma_dictionary_cache import get_dictionaries as _get_dicts
        _catalog = {
            e["id"]: e.get("label", "")
            for e in (_get_dicts().get("invoice_series") or [])
            if e.get("id")
        }
        if not series_id:
            pass  # label already set — must not depend on cache availability
        elif series_id in _catalog:
            series_name = _catalog[series_id]
        else:
            series_name = ""
            series_name_note = "refresh dictionary cache to resolve name"
    except Exception:
        pass  # cache unavailable — series_name stays empty

    # payload_core_hash for immutable-preview contract (RC-4).
    # When payload_core_hash_override is supplied the caller has already computed a
    # description-covering hash via _build_convert_candidate; use it directly.
    # Legacy callers (no override) compute the old hash without description.
    payload_core_hash = ""
    if payload_core_hash_override is not None:
        payload_core_hash = payload_core_hash_override
    else:
        try:
            from .proforma_to_invoice import compute_conversion_core_hash as _chash
            payload_core_hash = _chash(contractor_id, currency, series_id, source_lines)
        except Exception:
            pass  # pure-function — failure is non-fatal

    _fields_to_write: Dict[str, Any] = {
        "type":           "normal (final invoice)",
        "contractor_id":  contractor_id,
        "currency":       currency,
        "series_id":      series_id,
        "series_name":    series_name,
        "payment_method": resolved_method,
        "line_count":     len(source_lines),
        "operator":       operator,
    }
    if series_name_note:
        _fields_to_write["series_name_note"] = series_name_note

    _result: Dict[str, Any] = {
        "disclosure_type":   "invoice_convert",
        "write_target":      "wFirma invoices/add (type=normal — FINAL INVOICE)",
        "flag_required":     "WFIRMA_CREATE_INVOICE_ALLOWED",
        "source_proforma":   proforma_number,
        "payment_resolved": {
            "method":                  resolved_method,
            "payment_date":            snap_paymentdate,
            "invoice_date":            draft_invoice_date,
            "sale_date":               draft_sale_date,
            "payment_days":            draft_days,
            "customer_default_method": customer_default_method or "",
            "customer_default_days":   customer_default_days,
            "source":                  resolved_source,
        },
        "fields_to_write": _fields_to_write,
        "lines":           projected_lines,
        "grand_total":          grand_total,
        "grand_total_currency": currency,
        "series_name":          series_name,
        "payload_core_hash":    payload_core_hash,
        "confirm_token_required": "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA",
        "warning": (
            "This action will CREATE a FINAL TAX INVOICE in your live wFirma account. "
            "This is IRREVERSIBLE without manual wFirma deletion. "
            "Verify contractor, series, currency, and all lines before confirming."
        ),
    }
    if series_name_note:
        _result["series_name_note"] = series_name_note
    # description_preview — exact final invoice description that will be posted.
    # Only included when the caller supplies it (via _build_convert_candidate route).
    if description_preview is not None:
        _result["description_preview"] = description_preview
    return _result


# ── Pre-flight readiness ──────────────────────────────────────────────────────

def check_proforma_post_readiness(draft: Any) -> Dict[str, Any]:
    """Check if a draft is ready for posting (pre-flight, no write).

    Returns {ready: bool, blockers: List[str], advisories: List[str]}.
    The post endpoint still enforces these checks at write time; this is
    a convenience pre-flight for the UI to disable/enable the Post button.
    """
    blockers:   List[str] = []
    advisories: List[str] = []

    def _get(key: str, default="") -> Any:
        if hasattr(draft, key):
            return getattr(draft, key, default)
        if isinstance(draft, dict):
            return draft.get(key, default)
        return default

    client_name = _get("client_name", "")
    if not client_name:
        blockers.append("No client name — draft cannot be posted")

    try:
        import json
        lines = json.loads(_get("editable_lines_json", "[]") or "[]")
    except Exception:
        lines = []

    if not lines:
        blockers.append("No product lines — add at least one line before posting")
    else:
        zero_price = [ln for ln in lines if float(ln.get("unit_price", 0) or 0) <= 0]
        if zero_price:
            blockers.append(f"{len(zero_price)} line(s) have zero/missing unit_price")

    draft_state = _get("draft_state", "") or _get("status", "")
    if draft_state == "posted":
        blockers.append("Draft already posted — create a new draft to re-post")
    elif draft_state == "cancelled":
        blockers.append("Draft is cancelled — cannot post")

    return {
        "ready":      len(blockers) == 0,
        "blockers":   blockers,
        "advisories": advisories,
    }
