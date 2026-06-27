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
from datetime import date as _date
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
    final_series_id: str = "",
    operator: str = "",
    customer_default_method: str = "",
    customer_default_days: Optional[int] = None,
) -> Dict[str, Any]:
    """Build the payload disclosure for a proforma→invoice convert (WF2.5).

    proforma_snap: a ProformaSnapshot instance or dict (from parse_proforma_xml).
    customer_default_method: preferred_payment_method from customer_master (English form).
    customer_default_days:   payment_terms_days from customer_master.
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
    series_id        = final_series_id or _get("series_id", "")
    source_lines     = _get("lines", []) or []

    # Payment resolution: wFirma XML value → English for display/override
    snap_method_wf = (_get("paymentmethod", "") or "").strip()
    snap_method_en = _PM_MAP_TO_EN.get(snap_method_wf, snap_method_wf)
    snap_paymentdate = (_get("paymentdate", "") or "").strip()

    # Resolved defaults for operator pre-fill (wFirma proforma takes priority)
    resolved_method = snap_method_en or customer_default_method or ""
    resolved_source = (
        "wfirma_proforma" if snap_method_en else
        "customer_master" if customer_default_method else
        "not_set"
    )

    return {
        "disclosure_type":   "invoice_convert",
        "write_target":      "wFirma invoices/add (type=normal — FINAL INVOICE)",
        "flag_required":     "WFIRMA_CREATE_INVOICE_ALLOWED",
        "source_proforma":   proforma_number,
        "payment_resolved": {
            "method":                resolved_method,
            "payment_date":          snap_paymentdate,
            "customer_default_method": customer_default_method or "",
            "customer_default_days": customer_default_days,
            "source":                resolved_source,
        },
        "fields_to_write": {
            "type":           "normal (final invoice)",
            "contractor_id":  contractor_id,
            "currency":       currency,
            "series_id":      series_id,
            "invoice_date":   _date.today().isoformat(),
            "payment_method": resolved_method,
            "line_count":     len(source_lines),
            "operator":       operator,
        },
        "lines": [
            {
                "good_id":    getattr(ln, "wfirma_good_id", ln.get("wfirma_good_id", "") if isinstance(ln, dict) else ""),
                "qty":        getattr(ln, "qty", ln.get("qty", 0) if isinstance(ln, dict) else 0),
                "unit_price": getattr(ln, "unit_price", ln.get("unit_price", 0) if isinstance(ln, dict) else 0),
                "currency":   getattr(ln, "currency", ln.get("currency", currency) if isinstance(ln, dict) else currency),
            }
            for ln in source_lines[:50]
        ],
        "confirm_token_required": "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA",
        "warning": (
            "This action will CREATE a FINAL TAX INVOICE in your live wFirma account. "
            "This is IRREVERSIBLE without manual wFirma deletion. "
            "Verify contractor, series, currency, and all lines before confirming."
        ),
    }


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
