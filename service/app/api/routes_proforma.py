"""
routes_proforma.py — wFirma proforma preview + create-shell endpoints.

  POST /api/v1/proforma/preview/{batch_id}/{client_name}
        Read-only resolution: design_no → wfirma product_code, currency, FX,
        per-line stock_status, readiness gates. No writes, no live wFirma
        calls.

  POST /api/v1/proforma/create/{batch_id}/{client_name}
        Create-shell. Runs the same preview, enforces readiness gates,
        persists a local pending_local draft (idempotent on
        (batch_id, client_name)). Does NOT yet call wFirma — the live
        create wiring is deferred.
"""
from __future__ import annotations

import json
import sqlite3
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException
from fastapi.responses import JSONResponse, Response, HTMLResponse

from ..core.config import settings
from ..core.security import require_api_key
from ..core.logging import get_logger
from ..services import cpa_product_service as _cpa
from ..services import document_db as ddb
from ..services import packing_db  as pdb
from ..services import warehouse_db as wdb  # noqa: F401  (kept for cross-DB queries)
from ..services import wfirma_db   as wfdb
from ..services import inventory_state_engine as ise
from ..services import proforma_invoice_link_db as pildb
from ..services import wfirma_client
from ..services.customer_master_db import (
    get_customer as get_customer_master,
    list_customers as _list_customer_master,
)
from ..services.proforma_draft_governance import (
    check_top_patch, check_line_patch, check_post_readiness, check_convert_series,
)
from ..services.customer_master import (
    pick_freight, compute_insurance_suggestion,
    pick_proforma_series_id, pick_invoice_series_id,
)
from ..services.master_data_db import get_company_profile
from ..services import name_normalization
from .sales_packing_parser import (
    parse_ejl_sales_packing,
    validate_grand_total,
    build_patch_lookup,
)

log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1/proforma", tags=["proforma"])
_auth  = Depends(require_api_key)


def _norm(s: str) -> str:
    return (s or "").strip().upper()


# ── Stock helpers (read-only, no writes) ─────────────────────────────────────
# Proforma readiness uses the lifecycle state model, not the physical
# DISPATCH scan: a proforma can be issued for goods that are present in
# WAREHOUSE_STOCK but have not yet shipped.

def _scan_codes_per_product(batch_id: str) -> Dict[str, List[str]]:
    """{ wfirma_product_code: [scan_code, ...] } from packing_lines."""
    if pdb._db_path is None:
        return {}
    out: Dict[str, List[str]] = {}
    with sqlite3.connect(str(pdb._db_path), check_same_thread=False) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT product_code, scan_code FROM packing_lines "
            "WHERE batch_id=? AND scan_code IS NOT NULL",
            (batch_id,),
        ).fetchall()
    for r in rows:
        pc = r["product_code"] or ""
        sc = r["scan_code"]    or ""
        if pc and sc:
            out.setdefault(pc, []).append(sc)
    return out


def _state_codes(batch_id: str) -> Dict[str, List[str]]:
    """{ inventory_state: [scan_code, ...] } for this batch.

    Uses a single SQL query via list_all_states_for_batch() instead of N
    separate calls (one per state).  Falls back to an empty dict on any error
    so downstream stock_ok=False logic degrades gracefully.
    """
    try:
        return ise.list_all_states_for_batch(batch_id)
    except Exception:
        return {}


# ── Warehouse readiness gate ─────────────────────────────────────────────────

def _check_warehouse_readiness(batch_id: str) -> List[str]:
    """
    Batch-level warehouse gate for proforma creation.

    Returns [] when audit.json is absent (graceful pass-through for test
    environments that don't seed a processed batch).

    Checks (in order):
      1. All product_codes in pz_rows.json are resolved in wfirma_products
         (wfirma_product_id set + sync_status == "matched")
      2. No price conflicts — same product_code must not carry two different
         unit_netto_pln values in pz_rows.json

    NOTE: The wfirma_pz_doc_id check was intentionally moved to
    _check_proforma_export_prerequisites(), which is an export/create gate —
    NOT a preview gate.  Preview must work before the wFirma PZ is created.
    """
    output_dir = settings.storage_root / "outputs" / batch_id
    audit_path = output_dir / "audit.json"

    if not audit_path.exists():
        return []

    reasons: List[str] = []

    # 1+2. Inspect pz_rows.json for unresolved codes and price conflicts
    pz_rows_path = output_dir / "pz_rows.json"
    if not pz_rows_path.exists():
        return reasons

    try:
        with pz_rows_path.open() as f:
            pz_rows: List[Dict[str, Any]] = json.load(f)
    except Exception:
        reasons.append("warehouse readiness check failed: could not read pz_rows.json")
        return reasons

    # 2. Unresolved product_codes — batch fetch (C6 T6: O(1) vs O(N) per-code)
    if wfdb._db_path is not None:
        all_codes = sorted({
            (r.get("product_code") or "").strip()
            for r in pz_rows
            if (r.get("product_code") or "").strip()
        })
        _prods_map = wfdb.get_products_batch(all_codes) if all_codes else {}
        unresolved = []
        for code in all_codes:
            prod = _prods_map.get(code)
            if not (prod and prod.get("wfirma_product_id") and prod.get("sync_status") == "matched"):
                unresolved.append(code)
        if unresolved:
            sample = ", ".join(unresolved[:3]) + ("…" if len(unresolved) > 3 else "")
            reasons.append(
                f"{len(unresolved)} product_code(s) unresolved in wfirma_products: {sample}"
            )

    # 3. Price conflicts
    prices_by_code: Dict[str, set] = {}
    for r in pz_rows:
        code = (r.get("product_code") or "").strip()
        price = r.get("unit_netto_pln")
        if code and price is not None:
            prices_by_code.setdefault(code, set()).add(round(float(price), 4))
    conflicts = sorted(code for code, prices in prices_by_code.items() if len(prices) > 1)
    if conflicts:
        sample = ", ".join(conflicts[:3]) + ("…" if len(conflicts) > 3 else "")
        reasons.append(
            f"{len(conflicts)} product_code(s) have price conflicts in pz_rows: {sample}"
        )

    return reasons


# ── Export prerequisites gate ────────────────────────────────────────────────

def _check_proforma_export_prerequisites(batch_id: str) -> List[str]:
    """Gates specific to wFirma proforma export/create — NOT required for preview.

    A commercial preview can be shown before the wFirma PZ is created.
    Actual proforma issuance (write to wFirma) requires a PZ to exist.

    In advisory mode (settings.advisory_gates_enabled=True), the PZ-before-proforma
    requirement becomes an advisory warning rather than a hard blocker — the
    proforma draft can be created and reviewed without a wFirma PZ existing.
    The wFirma write flag (WFIRMA_CREATE_PROFORMA_ALLOWED) remains hard.

    Returns [] when audit.json is absent (graceful pass-through).
    Returns [] in advisory mode (caller sees the advisory in export_advisories).
    """
    output_dir = settings.storage_root / "outputs" / batch_id
    audit_path = output_dir / "audit.json"
    if not audit_path.exists():
        return []
    try:
        with audit_path.open() as f:
            audit = json.load(f)
    except Exception:
        return ["export prerequisites check failed: could not read audit.json"]

    wfirma_export = audit.get("wfirma_export") or {}
    pz_doc_id = (wfirma_export.get("wfirma_pz_doc_id") or "").strip()
    if not pz_doc_id:
        msg = (
            "proforma export requires wFirma PZ — "
            "run wFirma PZ create before issuing a proforma"
        )
        # Advisory mode: return advisory warning (empty blockers list = not blocked)
        if settings.advisory_gates_enabled:
            return []   # caller should check export_advisories for the advisory
        return [msg]
    return []


# ── Batch lifecycle derivation ───────────────────────────────────────────────

_LIFECYCLE_TRANSIT_STATUSES: frozenset = frozenset({
    "dsk_generated", "dsk_transfer_queued", "agency_email_queued",
    "dsk_sent", "reply_sent", "reply_queued", "dsk_transfer_sent",
})


def _derive_batch_lifecycle(batch_id: str) -> str:
    """Derive the batch lifecycle from inventory rows + audit clearance status.

    Returns:
        "POST_IMPORT"  — inventory_state rows exist (goods at warehouse or dispatched)
        "DHL_TRANSIT"  — no inventory rows but clearance_status indicates active transit
                         (DSK sent to agency, reply queued, etc.)
        "PRE_IMPORT"   — no inventory rows and no transit indicator
        "UNKNOWN"      — audit unreadable or batch not found
    """
    try:
        all_states = ise.list_all_states_for_batch(batch_id)
        has_inventory = bool(any(all_states.values()))
    except Exception:
        has_inventory = False

    if has_inventory:
        return "POST_IMPORT"

    output_dir = settings.storage_root / "outputs" / batch_id
    audit_path = output_dir / "audit.json"
    if not audit_path.exists():
        return "UNKNOWN"
    try:
        with audit_path.open() as f:
            audit = json.load(f)
        cs = (audit.get("clearance_status") or "").lower().strip()
        if cs in _LIFECYCLE_TRANSIT_STATUSES:
            return "DHL_TRANSIT"
        return "PRE_IMPORT"
    except Exception:
        return "UNKNOWN"


# ── Customer resolver (single source of truth — used by preview, payload   ──
#    builder, and adopt-issued contractor verifier) ─────────────────────────

def _normalize_client_name(raw: str) -> str:
    return name_normalization.proforma_normalize_client_name(raw)


def _resolve_customer_via_master(
    norm: str,
) -> Optional[Dict[str, Any]]:
    """Try to resolve a normalized client name against Customer Master.

    Customer Master is the PRIMARY AUTHORITY for client identity, email,
    and address (PROJECT_STATE DECISIONS 2026-06-07). wfirma_customers
    cache is a helper/fallback only.

    Match strategies tried in order:
      1. Exact normalized match (case-insensitive).
      2. Prefix match — draft name is a leading substring of the
         Customer Master ``bill_to_name`` (e.g. draft ``Anastazia
         Panakova`` matches CM ``Anastazia Panakova - Zlatnictvo
         Panaks``). Only word-boundary prefix is accepted (space or
         separator after the draft name in the master name).
      3. Reverse-prefix — CM ``bill_to_name`` is a leading substring
         of the draft name. Same boundary rule.

    Returns a dict suitable for ``out.update(...)`` in the caller when
    exactly one unambiguous match is found.  Returns ``None`` when zero
    matches (caller should fall through to wfirma cache).  Returns an
    ambiguous-flagged dict when >1 match found.
    """
    cm_db = _customer_master_db_path()
    all_cm = _list_customer_master(cm_db, limit=10000, active=True)
    if not all_cm:
        return None

    norm_lc = norm.lower()
    exact_matches = []
    prefix_matches = []
    rev_prefix_matches = []

    for cm in all_cm:
        cm_name_raw = (cm.bill_to_name or "").strip()
        if not cm_name_raw or not cm.bill_to_contractor_id:
            continue
        cm_norm = _normalize_client_name(cm_name_raw).lower()

        if cm_norm == norm_lc:
            exact_matches.append(cm)
        elif cm_norm.startswith(norm_lc + " ") or cm_norm.startswith(norm_lc + " - "):
            prefix_matches.append(cm)
        elif norm_lc.startswith(cm_norm + " ") or norm_lc.startswith(cm_norm + " - "):
            rev_prefix_matches.append(cm)

    # ── Exact match ─────────────────────────────────────────────────
    if len(exact_matches) == 1:
        cm = exact_matches[0]
        return {
            "found":                True,
            "match_strategy":       "customer_master",
            "customer":             {"client_name": cm.bill_to_name,
                                     "wfirma_customer_id": str(cm.bill_to_contractor_id)},
            "wfirma_customer_id":   str(cm.bill_to_contractor_id),
            "resolved_wfirma_name": cm.bill_to_name,
        }
    if len(exact_matches) > 1:
        return {
            "ambiguous":      True,
            "match_strategy": "ambiguous",
            "candidates":     [c.bill_to_name for c in exact_matches],
            "candidate_ids":  [str(c.bill_to_contractor_id) for c in exact_matches],
        }

    # ── Prefix match (draft name ⊆ CM name) ────────────────────────
    if len(prefix_matches) == 1:
        cm = prefix_matches[0]
        return {
            "found":                True,
            "match_strategy":       "customer_master_prefix",
            "customer":             {"client_name": cm.bill_to_name,
                                     "wfirma_customer_id": str(cm.bill_to_contractor_id)},
            "wfirma_customer_id":   str(cm.bill_to_contractor_id),
            "resolved_wfirma_name": cm.bill_to_name,
        }
    if len(prefix_matches) > 1:
        return {
            "ambiguous":      True,
            "match_strategy": "ambiguous",
            "candidates":     [c.bill_to_name for c in prefix_matches],
            "candidate_ids":  [str(c.bill_to_contractor_id) for c in prefix_matches],
        }

    # ── Reverse-prefix match (CM name ⊆ draft name) ────────────────
    if len(rev_prefix_matches) == 1:
        cm = rev_prefix_matches[0]
        return {
            "found":                True,
            "match_strategy":       "customer_master_reverse_prefix",
            "customer":             {"client_name": cm.bill_to_name,
                                     "wfirma_customer_id": str(cm.bill_to_contractor_id)},
            "wfirma_customer_id":   str(cm.bill_to_contractor_id),
            "resolved_wfirma_name": cm.bill_to_name,
        }
    if len(rev_prefix_matches) > 1:
        return {
            "ambiguous":      True,
            "match_strategy": "ambiguous",
            "candidates":     [c.bill_to_name for c in rev_prefix_matches],
            "candidate_ids":  [str(c.bill_to_contractor_id) for c in rev_prefix_matches],
        }

    # No match in Customer Master — caller falls through to wfirma cache
    return None


def _resolve_customer(
    client_name: str,
    batch_id: Optional[str] = None,
    client_contractor_id: str = "",
) -> Dict[str, Any]:
    """Resolve a sales-list client name to a customer identity.

    Authority chain (highest priority first):
      0. **Packing-upload selection** — when ``batch_id`` is provided AND
         the operator picked a Customer Master client during sales packing
         upload (stored in ``packing_contractor_resolution`` as confirmed
         + role=client + matched_master_type=customer_master), use that
         selection. NIP and wFirma ``contractor_id`` outrank display name.
         Display-name divergence between the proforma's free-text and the
         master record's ``bill_to_name`` becomes an advisory note, never
         a blocker. See ``services/customer_resolution_authority.py``.
      1. **Customer Master direct match** — normalized name match against
         ``customer_master.bill_to_name``. Customer Master is the primary
         authority for client identity, email, and address (PROJECT_STATE
         DECISIONS 2026-06-07). Supports exact, prefix (draft name is
         leading substring of master name), and reverse-prefix matching.
         Single unambiguous match required.
      2. **wfirma_customers cache fallback** — normalized exact match
         (case-insensitive) against ``wfirma_customers`` cache. This is
         a helper cache, NOT the authority. Used only when Customer Master
         match fails.
      3. Prefix/reverse-prefix tolerance against wfirma_customers cache.

    Result dict shape::

        {
          "raw_input":              <as given>,
          "normalized_name":        <stripped+collapsed>,
          "found":                  bool,           # exactly one match
          "ambiguous":              bool,           # 2+ candidates
          "match_strategy":         "packing_master" | "customer_master" |
                                    "customer_master_prefix" |
                                    "customer_master_reverse_prefix" |
                                    "exact" | "prefix" |
                                    "reverse_prefix" | "ambiguous" | "none",
          "customer":               <full wfirma_customers row dict> | None,
          "wfirma_customer_id":     str | "",
          "resolved_wfirma_name":   str,            # the customer's stored name
          "candidates":             List[str],      # display names when ambiguous
          "advisory":               str,            # operator-facing note (empty
                                                    # when no display-name drift)
        }

    The resolver does NOT call the live wFirma API. It reads only local
    state: ``customer_master`` (primary authority), ``wfirma_customers``
    (cache fallback), ``packing_contractor_resolution``, and
    ``documents.db``. No mutation; no creation; safe for read-only
    preview gates and write payload builders alike.
    """
    raw = client_name or ""
    norm = _normalize_client_name(raw)
    out: Dict[str, Any] = {
        "raw_input":            raw,
        "normalized_name":      norm,
        "found":                False,
        "ambiguous":            False,
        "match_strategy":       "none",
        "customer":             None,
        "wfirma_customer_id":   "",
        "resolved_wfirma_name": "",
        "candidates":           [],
        "advisory":             "",
    }

    # 0a. PER-DOCUMENT upload-time client selection — primary authority.
    #     Walks sales_documents → shipment_documents.client_contractor_id
    #     → customer_master. Correct granularity for multi-client
    #     shipments where one batch carries N sales packing list uploads,
    #     each with its own operator-selected client.
    #     Failures here MUST NOT crash the resolver — fall through on
    #     any exception so a transient DB issue cannot block readiness.
    if batch_id and raw:
        try:
            from ..services.customer_resolution_authority import (
                derive_customer_authority_for_draft,
            )
            per_doc = derive_customer_authority_for_draft(
                batch_id=batch_id,
                client_name=raw,
                documents_db_path=settings.storage_root / "documents.db",
                customer_master_db_path=_customer_master_db_path(),
                client_contractor_id=client_contractor_id,
            )
            if per_doc is not None:
                out.update({
                    "found":                True,
                    "match_strategy":       per_doc.get("match_strategy",
                                                        "per_document_upload"),
                    "wfirma_customer_id":   per_doc["wfirma_customer_id"],
                    "resolved_wfirma_name": per_doc["resolved_master_name"],
                    "advisory":             per_doc["advisory"],
                })
                return out
        except Exception as _pd_err:  # pragma: no cover — defensive
            log.warning(
                "[%s] per-document customer authority failed for %r: %s "
                "— falling through to per-batch packing-master",
                batch_id, raw, _pd_err,
            )

    # 0b. Per-BATCH packing-master selection (legacy from PR #296+#297).
    #     SECONDARY fallback for batches without per-document upload
    #     selections persisted. Uses UNIQUE(batch_id, role) → returns
    #     the SAME contractor for every draft on the batch. Correct only
    #     for single-client batches; for multi-client batches the 0a
    #     path above resolves cleanly per-document and this path is
    #     reached only when 0a returns None (defensive).
    if batch_id:
        try:
            from ..services.customer_resolution_authority import (
                derive_customer_resolution_via_packing,
            )
            packing_master = derive_customer_resolution_via_packing(
                batch_id=batch_id,
                client_name=raw,
                customer_master_db_path=_customer_master_db_path(),
                packing_resolution_db_path=(
                    settings.storage_root / "packing_resolutions.sqlite"
                ),
            )
            if packing_master is not None:
                out.update({
                    "found":                True,
                    "match_strategy":       "packing_master",
                    "wfirma_customer_id":   packing_master["wfirma_customer_id"],
                    "resolved_wfirma_name": packing_master["resolved_master_name"],
                    "advisory":             packing_master["advisory"],
                })
                return out
        except Exception as _pm_err:  # pragma: no cover — defensive
            log.warning(
                "[%s] packing-master customer resolution failed: %s "
                "— falling through to name-based resolver",
                batch_id, _pm_err,
            )

    if not norm:
        return out

    # ------------------------------------------------------------------
    # 1. Customer Master direct match — PRIMARY AUTHORITY
    #    Customer Master is the source of truth for client identity,
    #    email, and address (PROJECT_STATE DECISIONS 2026-06-07).
    #    wfirma_customers cache is a helper; Customer Master is authority.
    # ------------------------------------------------------------------
    try:
        cm_match = _resolve_customer_via_master(norm)
        if cm_match is not None:
            out.update(cm_match)
            return out
    except Exception as _cm_err:  # pragma: no cover — defensive
        log.warning(
            "Customer Master direct match failed for %r: %s "
            "— falling through to wfirma_customers cache",
            raw, _cm_err,
        )

    # ------------------------------------------------------------------
    # 2. wfirma_customers cache — FALLBACK only
    #    Used when Customer Master match fails (e.g. customer not yet in
    #    Customer Master, or name format differs).
    # ------------------------------------------------------------------
    if wfdb._db_path is None:
        return out

    # 2a. Normalized exact match against wfirma_customers cache.
    cust = wfdb.get_customer(norm)
    if cust and cust.get("wfirma_customer_id"):
        out.update({
            "found":                True,
            "match_strategy":       "exact",
            "customer":             cust,
            "wfirma_customer_id":   cust["wfirma_customer_id"],
            "resolved_wfirma_name": cust.get("client_name", ""),
        })
        return out

    # 2b/2c. Walk wfirma_customers for prefix / reverse-prefix candidates.
    norm_lc = norm.lower()
    all_rows = wfdb.list_customers()
    prefix_matches: List[Dict[str, Any]] = []
    rev_prefix_matches: List[Dict[str, Any]] = []
    for row in all_rows:
        wf_name = (row.get("client_name") or "").strip()
        if not wf_name or not row.get("wfirma_customer_id"):
            continue
        wf_norm = _normalize_client_name(wf_name).lower()
        if wf_norm == norm_lc:
            # Exact match got missed in step 2a only when match_status filter
            # excluded it; treat as exact.
            out.update({
                "found":                True,
                "match_strategy":       "exact",
                "customer":             row,
                "wfirma_customer_id":   row["wfirma_customer_id"],
                "resolved_wfirma_name": wf_name,
            })
            return out
        if wf_norm.startswith(norm_lc + " ") or wf_norm.startswith(norm_lc + ","):
            prefix_matches.append(row)
        elif norm_lc.startswith(wf_norm + " ") or norm_lc.startswith(wf_norm + ","):
            rev_prefix_matches.append(row)

    if len(prefix_matches) == 1:
        row = prefix_matches[0]
        out.update({
            "found":                True,
            "match_strategy":       "prefix",
            "customer":             row,
            "wfirma_customer_id":   row["wfirma_customer_id"],
            "resolved_wfirma_name": row["client_name"],
        })
        return out

    if len(prefix_matches) > 1:
        out.update({
            "ambiguous":      True,
            "match_strategy": "ambiguous",
            "candidates":     [r["client_name"] for r in prefix_matches],
        })
        return out

    # No prefix candidates — try reverse direction
    if len(rev_prefix_matches) == 1:
        row = rev_prefix_matches[0]
        out.update({
            "found":                True,
            "match_strategy":       "reverse_prefix",
            "customer":             row,
            "wfirma_customer_id":   row["wfirma_customer_id"],
            "resolved_wfirma_name": row["client_name"],
        })
        return out

    if len(rev_prefix_matches) > 1:
        out.update({
            "ambiguous":      True,
            "match_strategy": "ambiguous",
            "candidates":     [r["client_name"] for r in rev_prefix_matches],
        })
        return out

    return out


# ── Preview core (callable from both /preview and /create) ──────────────────

def _validate_args(batch_id: str, client_name: str) -> str:
    """Common path-arg validation. Returns the trimmed client_name."""
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    cn = (client_name or "").strip()
    if not cn:
        raise HTTPException(status_code=400, detail="client_name is required.")
    return cn


def _build_preview(batch_id: str, client_name: str,
                   client_contractor_id: str = "") -> Dict[str, Any]:
    """
    Canonical preview resolution. Returns the canonical preview dict.
    Identical body shape to what /preview emits over HTTP — used directly
    by the /create endpoint to share the exact same gating logic.

    ⚠  KNOWN WRITE-ON-READ (GOVERNANCE NOTE 2026-05-19):
    The populate_from_packing() call below writes to design_product_mapping
    (bridge table, not financial data) as a side-effect of preview.
    This is intentional: the bridge must be populated before the operator
    sees ambiguity warnings in the preview panel. The write is idempotent
    and safe. Do NOT remove without ensuring the bridge is populated via an
    alternative explicit trigger before both preview and create paths.
    See: design_product_bridge.populate_from_packing().
    """
    blocking_reasons: List[str] = []
    warehouse_blockers: List[str] = []
    export_blockers:    List[str] = []
    export_advisories:  List[str] = []

    # ── 0a. Export prerequisites (wFirma PZ required for create — NOT preview) ─
    # Preview is intentionally allowed before the PZ exists so operators can
    # verify commercial data, customer mapping, and line items before customs.
    # In advisory mode the prerequisite returns [] (not a blocker) and we add
    # the advisory message to export_advisories for UI display.
    _prereq_blockers = _check_proforma_export_prerequisites(batch_id)
    export_blockers.extend(_prereq_blockers)
    if not _prereq_blockers and settings.advisory_gates_enabled:
        # Check if PZ is actually missing (advisory mode suppressed it from blockers)
        _adv_dir = settings.storage_root / "outputs" / batch_id / "audit.json"
        if _adv_dir.exists():
            try:
                import json as _adv_json
                _adv_audit = _adv_json.loads(_adv_dir.read_text())
                _adv_pz = ((_adv_audit.get("wfirma_export") or {}).get("wfirma_pz_doc_id") or "").strip()
                if not _adv_pz:
                    export_advisories.append(
                        "advisory: wFirma PZ not yet created — proforma draft available for review; "
                        "PZ required before final wFirma proforma issuance"
                    )
            except Exception:
                pass

    # ── 0b. Warehouse readiness (product resolution + price conflicts) ─────────
    warehouse_blockers.extend(_check_warehouse_readiness(batch_id))
    blocking_reasons.extend(warehouse_blockers)

    # ── 0c. Batch lifecycle (TRANSIT derivation from clearance_status) ─────────
    batch_lifecycle = _derive_batch_lifecycle(batch_id)

    # ── 0b. Populate design_product_mapping from packing_lines (idempotent) ──
    # The bridge data lives on every packing_lines row (product_code +
    # design_no). Project it into design_product_mapping so this preview —
    # and any future resolver that walks the registry — can read a single
    # source of truth without re-deriving from packing_lines each time.
    bridge_summary: Dict[str, Any] = {}
    try:
        from ..services.design_product_bridge import populate_from_packing
        bridge_summary = populate_from_packing(batch_id)
    except Exception as exc:
        # Never fatal — preview still works via v_sales_to_wfirma view.
        bridge_summary = {"errors": [f"design_product_bridge: {exc}"]}

    # Ambiguity surfaces as a blocker the operator must resolve before a
    # Proforma is built (otherwise the wrong product_code might be billed).
    # Example: PND mapped to both EJL/26-27/123-2 AND EJL/26-27/123-3.
    for design_no, codes in (bridge_summary.get("ambiguous_design_codes") or {}).items():
        blocking_reasons.append(
            f"design_no {design_no!r} maps to multiple product_codes "
            f"in this batch: {codes} — clarify which line to bill"
        )

    # Resolve customer up-front so the early-exit path (no sales rows) and
    # the full path produce a consistent response shape and so a passing
    # preview implies _build_proforma_request will succeed at this step.
    # Pass batch_id so the packing-upload Customer Master selection (set when
    # the operator picked a client during sales packing intake) outranks
    # any name-based fallback. See _resolve_customer docstring authority chain.
    customer_resolution = _resolve_customer(
        client_name, batch_id=batch_id,
        client_contractor_id=client_contractor_id,
    )

    # ── 1. Resolution rows (sales → wFirma product_code) ────────────────────
    resolution_rows = [
        r for r in _cpa.query_sales_resolution(batch_id)
        if (r.get("client_name") or "").strip() == client_name
    ]
    if not resolution_rows:
        # Also surface customer-resolution blockers in the early-exit path
        # so the operator UI sees ambiguity / missing-customer reasons even
        # before any sales rows exist.
        early_blockers: List[str] = list(blocking_reasons)
        early_blockers.append(f"no sales rows for client {client_name!r}")
        if customer_resolution["ambiguous"]:
            early_blockers.append(
                f"multiple wfirma customer candidates for {client_name!r}: "
                f"{customer_resolution['candidates']} — clarify which mapping "
                "to use before issuing a proforma"
            )
        elif not customer_resolution["found"]:
            early_blockers.append(
                f"customer {client_name!r} not matched in wfirma_customers"
            )
        return {
            "ok":               False,
            "batch_id":         batch_id,
            "client_name":      client_name,
            "currency":         "unknown",
            "exchange_rate":    None,
            "can_preview":      False,
            "ready":            False,
            "blocking_reasons": early_blockers,
            "export_blockers":        export_blockers,
            "export_advisories":      export_advisories,
            "line_mismatch_advisories": [],
            "stock_advisories":       [],
            "warehouse_blockers":     warehouse_blockers,
            "batch_lifecycle":        batch_lifecycle,
            "lines":                  [],
            "customer_resolution": {
                "normalized_customer_name":   customer_resolution["normalized_name"],
                "resolved_wfirma_customer_name": customer_resolution["resolved_wfirma_name"],
                "wfirma_customer_id":         customer_resolution["wfirma_customer_id"],
                "match_strategy":             customer_resolution["match_strategy"],
                "candidates":                 customer_resolution["candidates"],
            },
        }

    # ── 2. Pricing source: SALES packing list, NOT import invoice ──────────
    # Customer Proformas must use what we bill the client (sales_packing_lines
    # unit_price/currency), never the supplier cost the engine recorded for
    # customs (invoice_lines.rate_usd). The sales price/currency is read
    # per-row off v_sales_to_wfirma (see resolution_rows below).

    # ── 3. Stock readiness via inventory_state (NOT warehouse DISPATCH) ─────
    # A proforma may be issued when every scan_code for the product_code is
    # in one of the eligible states:
    #   WAREHOUSE_STOCK         classic warehoused goods
    #   DIRECT_DISPATCH_READY   customs-cleared, operator-marked direct ship
    #   CLIENT_DISPATCHED       already physically dispatched to client
    # PURCHASE_TRANSIT (not yet received), SALES_TRANSIT (already promised
    # on another proforma/invoice), and CLOSED (delivered) all block
    # availability for a NEW proforma.
    sc_per_product   = _scan_codes_per_product(batch_id)
    state_codes      = _state_codes(batch_id)
    in_warehouse     = set(state_codes.get(ise.WAREHOUSE_STOCK,        []))
    in_direct_ready  = set(state_codes.get(ise.DIRECT_DISPATCH_READY,  []))
    in_dispatched    = set(state_codes.get(ise.CLIENT_DISPATCHED,      []))
    in_purchase      = set(state_codes.get(ise.PURCHASE_TRANSIT,       []))
    in_sales_transit = set(state_codes.get(ise.SALES_TRANSIT,          []))
    in_closed        = set(state_codes.get(ise.CLOSED,                 []))
    # Phase B.1 — SAMPLE_OUT is explicitly NOT in PROFORMA_ELIGIBLE_STATES
    # (see SAMPLE_OUT_DESIGN.md §6.2). A piece physically out at a client
    # cannot satisfy a proforma until it's returned to WAREHOUSE_STOCK.
    in_sample_out    = set(state_codes.get(ise.SAMPLE_OUT,             []))

    # Eligible = any state listed in PROFORMA_ELIGIBLE_STATES. We aggregate
    # to the strictest descriptive label so the UI reports cleanly.
    _eligible_sets = {
        "warehouse_stock":        in_warehouse,
        "direct_dispatch_ready":  in_direct_ready,
        "client_dispatched":      in_dispatched,
    }

    _is_dhl_transit = (batch_lifecycle == "DHL_TRANSIT")

    # PZ-created / DHL-delivered bypass for PURCHASE_TRANSIT pieces.
    # When the wFirma PZ exists (goods accepted into accounting) OR DHL
    # tracking confirms physical delivery, pieces still in PURCHASE_TRANSIT
    # are treated as warehouse-eligible for proforma issuance.
    # Physical scan-in (warehouse_receive trigger) is optional audit — not a gate.
    # Rule confirmed by operator 2026-06-11.
    _pz_created    = False
    _dhl_delivered = False
    try:
        _audit_file = settings.storage_root / "outputs" / batch_id / "audit.json"
        if _audit_file.exists():
            _audit_data = json.loads(_audit_file.read_text())
            _pz_created = bool(
                (_audit_data.get("wfirma_export") or {}).get("wfirma_pz_doc_id", "").strip()
            )
            from ..services.dhl_delivery_bridge import is_dhl_delivered as _bridge_delivered
            _dhl_delivered = _bridge_delivered(_audit_data)
    except Exception:
        pass  # never let the bypass check break preview

    def _stock_status(pc: str) -> str:
        scs = sc_per_product.get(pc, [])
        if not scs:
            return "no_scan_codes"
        # Pass when every scan_code is in *some* eligible state (mixed
        # eligible states are still a pass — e.g. half WAREHOUSE_STOCK,
        # half DIRECT_DISPATCH_READY).
        eligible_union = in_warehouse | in_direct_ready | in_dispatched
        if all(sc in eligible_union for sc in scs):
            # Report the dominant single state if all match; else "mixed_eligible".
            for label, sset in _eligible_sets.items():
                if all(sc in sset for sc in scs):
                    return label
            return "mixed_eligible"
        if any(sc in in_sample_out for sc in scs):
            return "sample_out"
        if any(sc in in_purchase for sc in scs):
            # Bypass: PZ created in wFirma OR DHL confirms delivery.
            if _pz_created or _dhl_delivered:
                return "purchase_transit_pz_or_delivered"
            return "purchase_transit"
        if any(sc in in_sales_transit for sc in scs):
            return "sales_transit"
        if any(sc in in_closed for sc in scs):
            return "closed"
        # No inventory_state rows exist yet — check batch lifecycle.
        # When DHL_TRANSIT: goods are en-route/at customs agency; preview is
        # allowed (operator can verify commercial data before goods arrive).
        # Create is still gated by export_blockers (wFirma PZ required).
        if _is_dhl_transit:
            return "dhl_transit"
        return "missing_state"

    _ELIGIBLE_LABELS = {
        "warehouse_stock", "direct_dispatch_ready",
        "client_dispatched", "mixed_eligible",
        # dhl_transit: goods not yet at warehouse but actively in transit;
        # preview-eligible so operators can prepare commercial documents early.
        "dhl_transit",
        # purchase_transit_pz_or_delivered: wFirma PZ created (goods accepted
        # into accounting) OR DHL tracking confirms delivery — physical scan-in
        # is optional audit, not a gate (operator rule 2026-06-11).
        "purchase_transit_pz_or_delivered",
    }

    def _stock_ok(pc: str) -> bool:
        return _stock_status(pc) in _ELIGIBLE_LABELS

    # ── 4. Build per-line response ──────────────────────────────────────────
    lines: List[Dict[str, Any]] = []
    unmatched_count    = 0
    missing_price      = 0
    missing_product    = 0
    stock_blocked: Counter = Counter()  # stock_status (excluding warehouse_stock)
    line_currencies: List[str] = []
    line_fx:            List[float] = []

    # Bridge fallback for any row whose v_sales_to_wfirma join failed
    # (e.g. packing_lines and sales_packing_lines disagree on the design
    # spelling, or the join was missed by a casing edge). The
    # design_product_mapping registry was populated above from the same
    # packing_lines source, so this lookup is consistent with the
    # primary resolver.
    from ..services.design_product_bridge import (
        get_product_codes_for_design as _bridge_lookup,
    )
    bridge_resolved_codes: Dict[str, List[str]] = {}

    for r in resolution_rows:
        product_code = r.get("wfirma_product_code")  # may be None
        design_no    = r.get("sales_design_no") or ""
        qty          = float(r.get("qty") or 0)

        # ── Sales-side pricing (canonical for customer Proformas) ──────────
        # The customer Proforma must reflect what we BILL the client, not
        # the supplier cost we paid. Read from sales_packing_lines via
        # v_sales_to_wfirma; never substitute import-side cost as a
        # silent fallback. Operators who genuinely need cost-basis
        # invoicing (rare; internal stock transfers) must record those
        # prices on the sales packing list explicitly.
        sales_unit_price   = r.get("sales_unit_price")
        sales_currency     = (r.get("sales_currency") or "").upper()
        sales_price_source = r.get("sales_price_source") or ""

        # Fallback: when the view did not project a product_code, consult
        # design_product_mapping as a secondary source. Single match
        # resolves cleanly; multi-match records the ambiguity for the
        # operator (the global ambiguity check above would already have
        # flagged it as a top-level blocker).
        if not product_code and design_no:
            mapped = _bridge_lookup(design_no)
            bridge_resolved_codes[design_no] = mapped
            if len(mapped) == 1:
                product_code = mapped[0]

        if not product_code:
            unmatched_count += 1
            lines.append({
                "product_code":  None,
                "design_no":     design_no,
                "qty":           qty,
                "unit_price":    None,
                "currency":      "unknown",
                "exchange_rate": None,
                "line_value":    None,
                "stock_ok":      False,
                "product_match": False,
                "price_source":  "",
            })
            continue

        # Use sales price/currency. If absent, this line counts toward
        # missing_price and the preview blocks; we DO NOT silently fall
        # through to import-invoice cost.
        try:
            unit_price = float(sales_unit_price) if sales_unit_price not in (None, "") else None
        except (TypeError, ValueError):
            unit_price = None
        if unit_price is not None and unit_price <= 0:
            unit_price = None
        currency   = sales_currency or "unknown"
        fx         = None  # sales rows don't carry FX; wFirma applies its own
        price_source = sales_price_source if unit_price is not None else "missing"
        line_value = (unit_price * qty) if unit_price is not None else None

        if unit_price is None or currency == "unknown":
            missing_price += 1
        else:
            line_currencies.append(currency)

        prod_rec = wfdb.get_product(product_code) if wfdb._db_path is not None else None
        product_match = bool(
            prod_rec
            and prod_rec.get("wfirma_product_id")
            and prod_rec.get("sync_status") == "matched"
        )
        if not product_match:
            missing_product += 1

        st = _stock_status(product_code)
        s_ok = st in _ELIGIBLE_LABELS
        if not s_ok:
            stock_blocked[st] += 1

        lines.append({
            "product_code":  product_code,
            "design_no":     design_no,
            "qty":           qty,
            "unit_price":    unit_price,
            "currency":      currency,
            "exchange_rate": fx,
            "line_value":    line_value,
            "stock_ok":      s_ok,
            "stock_status":  st,
            "product_match": product_match,
            "price_source":  price_source,
        })

    # ── 5. Header currency + FX (dominant across priced lines) ─────────────
    if line_currencies:
        currency = Counter(line_currencies).most_common(1)[0][0]
    else:
        currency = "unknown"
    exchange_rate = (sum(line_fx) / len(line_fx)) if line_fx else None

    # ── 6. Readiness gates ─────────────────────────────────────────────────
    # Phase 8: unmatched sales designs become an inbox advisory in advisory mode
    # rather than a hard blocking reason.
    line_mismatch_advisories: List[str] = []
    if unmatched_count:
        _mismatch_msg = (
            f"{unmatched_count} sales design(s) not mapped to a wFirma product_code — "
            "verify the sales packing list matches the purchase invoice and design_product_mapping "
            "is populated (approve/correct/split via Inbox)"
        )
        if settings.advisory_gates_enabled:
            line_mismatch_advisories.append(_mismatch_msg)
        else:
            blocking_reasons.append(
                f"{unmatched_count} sales design(s) not mapped to a wFirma product_code"
            )
    if missing_price:
        blocking_reasons.append(
            f"{missing_price} line(s) missing sales unit_price or currency on the "
            "customer packing list — re-upload the sales packing list with prices "
            "or set them via the sales-pricing endpoint"
        )
    if missing_product:
        blocking_reasons.append(
            f"{missing_product} product(s) not matched in wfirma_products"
        )
    # Authority: PROFORMA (2026-06-22). A proforma is built from customer +
    # product master + pricing. Inventory / stock state MUST NOT hard-block a
    # proforma — a proforma can legitimately be issued before goods are received
    # (business rule "Proforma can be created without stock"). Stock state is
    # therefore surfaced as an ADVISORY, never a blocker. Double-billing of
    # already-committed / delivered pieces remains protected by the over-bill
    # fail-closed gate in `_derive_draft_readiness` (billed_qty vs available_qty),
    # which is the correct fiscal authority for that risk.
    # Stock is reported per state; never written.
    _STATE_BLURB = {
        "purchase_transit": "still in PURCHASE_TRANSIT (not yet received in warehouse)",
        "sales_transit":    "already in SALES_TRANSIT (committed to another proforma/invoice)",
        "closed":           "in CLOSED state (already delivered)",
        # Improved: distinguish "scans exist in packing but no inventory_state
        # was ever written" (engine never ran) from the no-scan-at-all case.
        "missing_state":    "have packing_lines scan_codes but no inventory_state row "
                            "— inventory_state_engine has not seeded this batch",
        "no_scan_codes":    "have no scan_codes in packing_lines for the resolved product_code",
    }
    stock_advisories: List[str] = []
    for state, count in stock_blocked.items():
        blurb = _STATE_BLURB.get(state, f"in unexpected state {state!r}")
        stock_advisories.append(f"{count} product(s) {blurb}")

    # Customer match — uses the central resolver result computed above.
    # Same resolver used by _build_proforma_request so a passing preview
    # implies a successful payload build at the customer-resolution step.
    customer_match = customer_resolution["found"]
    _dev_bypass = getattr(settings, "ej_dev_workflow_bypass", False)
    if customer_resolution["ambiguous"]:
        blocking_reasons.append(
            f"multiple wfirma customer candidates for {client_name!r}: "
            f"{customer_resolution['candidates']} — clarify which mapping "
            "to use before issuing a proforma"
        )
    elif not customer_match:
        if _dev_bypass:
            # Bypass mode: demote to warning so preview renders. wFirma write
            # gates are NOT relaxed — only preview blocking is softened.
            export_blockers.append(
                f"[DEV-BYPASS] customer {client_name!r} not matched in "
                "wfirma_customers — preview allowed but wFirma issue blocked"
            )
        else:
            blocking_reasons.append(
                f"customer {client_name!r} not matched in wfirma_customers"
            )

    # ── Ship-to (Odbiorca) readiness ──────────────────────────────────────
    # When the customer is mapped, surface the mode + receiver state so
    # the operator can verify Odbiorca routing before issuing. Missing
    # receiver under separate_contractor mode is a hard blocker (matches
    # the validation in _build_proforma_request).
    ship_to_mode = ""
    ship_to_receiver_id = ""
    ship_to_cm_conflict: Optional[str] = None  # non-blocking warning
    if customer_match:
        cust_row = customer_resolution.get("customer") or {}
        ship_to_mode        = (cust_row.get("ship_to_mode")
                                or "same_as_bill_to").lower()
        ship_to_receiver_id = (cust_row.get("ship_to_wfirma_customer_id")
                                or "").strip()
        bill_to_id = (customer_resolution.get("wfirma_customer_id") or "").strip()
        if ship_to_mode == "separate_contractor":
            if not ship_to_receiver_id:
                blocking_reasons.append(
                    f"ship_to_mode is 'separate_contractor' for "
                    f"{client_name!r} but ship_to_wfirma_customer_id is "
                    "empty — set the receiver via PUT "
                    "/api/v1/wfirma/customers/{name}/ship-to before issuing"
                )
            elif ship_to_receiver_id == bill_to_id:
                blocking_reasons.append(
                    f"ship_to_wfirma_customer_id equals the bill-to id "
                    f"for {client_name!r} — separate_contractor requires a "
                    "DIFFERENT receiver"
                )

        # ── Cross-validation: CustomerMaster.ship_to_contractor_id vs
        # wfirma_customers.ship_to_wfirma_customer_id (NON-BLOCKING).
        # If CustomerMaster has a ship_to_contractor_id set AND it differs
        # from what wfirma_customers records as the receiver, surface a
        # warning so the operator knows which value actually drives the proforma.
        # See: service/docs/authority-graph-commercial-draft.md — Conflict 1.
        if bill_to_id:
            try:
                _cm_ship = get_customer_master(_customer_master_db_path(), bill_to_id)
                if _cm_ship is not None:
                    _cm_rcv = (_cm_ship.ship_to_contractor_id or "").strip()
                    if _cm_rcv and _cm_rcv != ship_to_receiver_id:
                        ship_to_cm_conflict = (
                            f"CustomerMaster.ship_to_contractor_id={_cm_rcv!r} "
                            f"differs from wfirma_customers.ship_to_wfirma_customer_id="
                            f"{ship_to_receiver_id!r}. "
                            "Proforma uses wfirma_customers value. "
                            "Update via PATCH /api/v1/wfirma/customers/{name}/ship-to."
                        )
            except Exception:
                pass  # never let cross-validation break the preview

    # ── Service charges (operator-entered freight / insurance) ─────────────
    # Loaded read-only here so the preview surfaces them before create.
    from ..services.insurance_wording import build_insurance_line_name as _ins_wording
    service_charges: List[Dict[str, Any]] = []
    service_charge_warnings: List[str] = []
    try:
        from ..services import proforma_service_charges_db as _scdb
        service_charges = _scdb.list_charges(batch_id, client_name)
    except Exception as exc:
        log.warning("service_charges read failed for %s/%s: %s",
                    batch_id, client_name, exc)
    # Each charge contributes to the line-currency dominant calc and the
    # final total. Operator MUST submit charges in the same currency as
    # the product lines — mixed currencies block create.
    sc_currencies = {(c.get("currency") or "").upper() for c in service_charges
                     if (c.get("currency") or "").strip()}
    if service_charges and currency != "unknown" and \
       sc_currencies and sc_currencies != {currency}:
        blocking_reasons.append(
            f"service charge currency {sorted(sc_currencies)} does not match "
            f"product line currency {currency!r}"
        )
    service_charge_total = sum(float(c.get("amount") or 0)
                                for c in service_charges)
    product_total = sum((ln.get("line_value") or 0) for ln in lines)
    final_total   = product_total + service_charge_total

    # ── Draft-level pre-approve checks ───────────────────────────────────────
    # If a draft exists for this batch/client, surface blank name_pl and zero
    # unit_price as blocking_reasons NOW so the operator sees them in the UI
    # before clicking Approve — not as a 422 surprise after clicking the button.
    # Same logic as _preflight_approve(); surfaced here for proactive visibility.
    try:
        _pf_db = settings.storage_root / "proforma_links.db"
        if _pf_db.exists():
            _existing_draft = pildb.get_draft(_pf_db, batch_id, client_name)
            if _existing_draft is not None and _existing_draft.editable_lines_json:
                import json as _pf_json
                _edit_lines = _pf_json.loads(_existing_draft.editable_lines_json or "[]")
                if isinstance(_edit_lines, list):
                    _blank_name_pl = sum(
                        1 for ln in _edit_lines
                        if not (ln.get("name_pl") or "").strip()
                    )
                    if _blank_name_pl:
                        blocking_reasons.append(
                            f"{_blank_name_pl} line(s) have blank commercial description (name_pl) "
                            "— import sales prices before approving"
                        )
                    _zero_unit_price = sum(
                        1 for ln in _edit_lines
                        if not (ln.get("unit_price") or 0)
                    )
                    if _zero_unit_price:
                        blocking_reasons.append(
                            f"{_zero_unit_price} line(s) have zero/missing unit_price "
                            "— import sales prices before approving"
                        )
    except Exception:
        pass  # non-fatal — preview still works without editable-lines pre-approve check

    # can_preview: True when sales rows exist and lines can be shown.
    # Does NOT require wFirma PZ — that's an export gate, not a preview gate.
    # (The early-exit path above sets can_preview=False when no sales rows exist.)
    can_preview = True

    # draft_ready: commercial-data gate for local draft persistence.
    # Requires only sales packing list + customer match + product resolution.
    # Does NOT require wFirma PZ or SAD — those are export/customs gates.
    draft_ready = not blocking_reasons

    # ready: full gate for live proforma issuance to wFirma.
    # Both commercial data AND export prerequisites (wFirma PZ) must be clear.
    ready = draft_ready and not export_blockers

    return {
        "ok":               True,
        "batch_id":         batch_id,
        "client_name":      client_name,
        "currency":         currency,
        "exchange_rate":    exchange_rate,
        "can_preview":      can_preview,
        "draft_ready":      draft_ready,
        "ready":            ready,
        "blocking_reasons": blocking_reasons,
        "export_blockers":  export_blockers,
        "export_advisories":       export_advisories,
        "line_mismatch_advisories": line_mismatch_advisories,
        "stock_advisories":        stock_advisories,
        "warehouse_blockers":      warehouse_blockers,
        "batch_lifecycle":         batch_lifecycle,
        "lines":                   lines,
        # Operator-entered freight / insurance (not derived from import cost).
        # insurance entries include the canonical wording that will appear on
        # the commercial document (generated by insurance_wording module).
        "service_charges":  [
            {
                "charge_type":          c.get("charge_type"),
                "amount":               c.get("amount"),
                "currency":             c.get("currency"),
                "note":                 c.get("note") or "",
                "insurance_line_name":  (
                    _ins_wording()
                    if (c.get("charge_type") or "").lower() == "insurance"
                    else None
                ),
            }
            for c in service_charges
        ],
        "totals": {
            "product_total":         product_total,
            "service_charge_total":  service_charge_total,
            "final_total":           final_total,
            "currency":              currency,
        },
        # Diagnostic surface for the design→product bridge population that
        # ran at the top of this preview. Operator UI / debugging tools
        # use this to see what was projected and what's ambiguous.
        "design_product_bridge": {
            "scanned":               bridge_summary.get("scanned", 0),
            "inserted":              bridge_summary.get("inserted", 0),
            "updated":               bridge_summary.get("updated", 0),
            "ambiguous_design_codes": bridge_summary.get("ambiguous_design_codes", {}),
            "errors":                bridge_summary.get("errors", []),
            "fallback_resolutions":  bridge_resolved_codes,
        },
        # Customer-resolution diagnostic (mirrors what _build_proforma_request
        # will see). Operator UI uses this to show the candidate name BEFORE
        # the operator hits Create.
        "customer_resolution": {
            "normalized_customer_name":   customer_resolution["normalized_name"],
            "resolved_wfirma_customer_name": customer_resolution["resolved_wfirma_name"],
            "wfirma_customer_id":         customer_resolution["wfirma_customer_id"],
            "match_strategy":             customer_resolution["match_strategy"],
            "candidates":                 customer_resolution["candidates"],
        },
        # Ship-to (Odbiorca) state per Step 1 mapping. Surfaced read-only
        # so the operator UI can show the receiver routing before Create.
        # cm_conflict is a non-blocking warning when CustomerMaster and
        # wfirma_customers hold different ship-to contractor IDs. The proforma
        # always uses wfirma_customers. See authority-graph-commercial-draft.md.
        "ship_to": {
            "mode":                       ship_to_mode or "same_as_bill_to",
            "ship_to_wfirma_customer_id": ship_to_receiver_id,
            "cm_conflict":                ship_to_cm_conflict,
        },
        # Product registration readiness (Phase 2 — safe autonomous dry-run).
        # Reports which invoice-line product_codes are NOT yet registered in
        # wFirma without creating anything. Operator must call
        # POST /api/v1/wfirma/goods/auto-register/{batch_id} (write=true)
        # before issuing the proforma if any codes are missing.
        # GOVERNANCE: product.auto_register_dry_run → SAFE_AUTONOMOUS.
        "product_registration": _build_product_registration_scan(batch_id),
    }


# ── HTTP endpoints ──────────────────────────────────────────────────────────

@router.post("/preview/{batch_id}/{client_name:path}", dependencies=[_auth])
def proforma_preview(batch_id: str, client_name: str) -> JSONResponse:
    """Read-only proforma preview — same shape as _build_preview."""
    cn = _validate_args(batch_id, client_name)
    return JSONResponse(_build_preview(batch_id, cn))


# ── Local DB path for proforma drafts/links ─────────────────────────────────

def _proforma_db_path():
    return settings.storage_root / "proforma_links.db"


def _customer_master_db_path():
    return settings.storage_root / "customer_master.sqlite"


def _build_product_registration_scan(batch_id: str) -> Dict[str, Any]:
    """Dry-run scan: which invoice-line product_codes are not yet in wFirma?

    Called from _build_preview so the operator sees registration gaps BEFORE
    hitting Create.  Never creates anything (dry_run=True always).
    Failures are isolated — a broken scan returns an error stub, never raises.

    Returns::

        {
          "scanned":          int,  # distinct product_codes in this batch
          "registered":       int,  # already mapped in wFirma
          "missing":          int,  # not in wFirma (need manual auto-register)
          "missing_codes":    [str],
          "status":           "all_registered" | "missing_codes" | "scan_failed" | "skipped",
          "error":            str,  # non-empty on scan_failed
        }
    """
    if not batch_id:
        return {"scanned": 0, "registered": 0, "missing": 0,
                "missing_codes": [], "status": "skipped", "error": ""}
    try:
        from ..services.wfirma_product_auto_register import ensure_products_for_batch
        scan = ensure_products_for_batch(batch_id, dry_run=True)
        scanned   = scan.get("scanned", 0)
        missing_n = scan.get("missing", 0)
        existing  = scan.get("existing_mapped", 0)
        missing_codes = [
            r["product_code"]
            for r in (scan.get("results") or [])
            if r.get("status") == "missing"
        ]
        status = "all_registered" if missing_n == 0 else "missing_codes"
        return {
            "scanned":       scanned,
            "registered":    existing,
            "missing":       missing_n,
            "missing_codes": missing_codes,
            "status":        status,
            "error":         "",
        }
    except Exception as exc:
        log.warning(
            "[%s] product_registration_scan failed: %s",
            batch_id, exc,
        )
        return {
            "scanned":       0,
            "registered":    0,
            "missing":       0,
            "missing_codes": [],
            "status":        "scan_failed",
            "error":         f"{type(exc).__name__}: {exc}",
        }


def _build_service_charge_lines(
    charges: List[Dict[str, Any]],
    doc_currency: str,
) -> "tuple[List[wfirma_client.ReservationLine], str]":
    """
    Build wFirma ``ReservationLine`` objects for service charges that have
    a registered product mapping in ``wfirma_products`` (keyed by charge_type).

    Emission rules:
      - charge_type must be in ALLOWED_SERVICE_CHARGE_TYPES
      - wfirma_products must have a non-empty wfirma_product_id for that code
      - charge.currency must match doc_currency (or be empty → adopts doc_currency)
      - amount must be positive and parseable

    Returns ``(lines, unmapped_note)``:
      - ``lines``: ReservationLine list to append to ProformaRequest.lines
      - ``unmapped_note``: non-empty when any charge type could not be emitted

    Uses module-level ``wfdb`` so test monkeypatching works.
    """
    if not charges:
        return [], ""

    from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN

    lines: List[wfirma_client.ReservationLine] = []
    unmapped: List[str] = []
    d_ccy = (doc_currency or "").strip().upper()

    for c in charges:
        ct = (c.get("charge_type") or "").strip().lower()
        if not ct or ct not in pildb.ALLOWED_SERVICE_CHARGE_TYPES:
            if ct:
                unmapped.append(f"{ct}(unknown_type)")
            continue

        prod = wfdb.get_product(ct) if wfdb._db_path is not None else None
        good_id = (prod or {}).get("wfirma_product_id") or ""
        if not good_id:
            unmapped.append(ct)
            continue

        # Currency gate: only include charges whose currency matches the document.
        c_ccy = (c.get("currency") or "").strip().upper()
        use_ccy = c_ccy or d_ccy
        if c_ccy and d_ccy and c_ccy != d_ccy:
            unmapped.append(f"{ct}(currency_mismatch:{c_ccy}≠{d_ccy})")
            continue

        # Decimal-safe amount parsing (ROUND_HALF_EVEN preserves accounting parity).
        try:
            amount = Decimal(str(c.get("amount") or 0)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_EVEN
            )
        except InvalidOperation:
            unmapped.append(f"{ct}(invalid_amount)")
            continue
        if amount <= 0:
            continue

        # Canonical wording: insurance line name is always generated by the
        # centralized insurance_wording module — never taken from freeform
        # product registry text.  Freight keeps the registry label.
        if ct == "insurance":
            from ..services.insurance_wording import build_insurance_line_name
            _line_name = build_insurance_line_name()
        else:
            _line_name = (
                (prod.get("product_name_pl") or "").strip()
                or (prod.get("product_name") or "").strip()
                or ct
            )

        lines.append(wfirma_client.ReservationLine(
            product_code   = ct,
            wfirma_good_id = good_id,
            product_name   = _line_name,
            qty            = 1.0,
            unit_price     = float(amount),
            unit           = (prod.get("unit") or "szt."),
            currency       = use_ccy,
        ))

    note = ""
    if unmapped:
        note = (
            f"service charges ({', '.join(sorted(set(unmapped)))}) not included "
            "in wFirma proforma content — "
            "register a service product mapping or check currency alignment"
        )
    return lines, note


def _build_proforma_request(preview: Dict[str, Any]) -> "wfirma_client.ProformaRequest":
    """
    Build a wfirma_client.ProformaRequest from a ready preview dict.
    Caller-supplied values are NOT used here — every field is derived from
    server state (preview, packing_lines, wfirma_products / wfirma_customers).

    Resolves wFirma master IDs from the local mapping tables:
      - wfirma_customer_id from wfirma_customers (by client_name)
      - wfirma_product_id  from wfirma_products  (per product_code)
    Raises ValueError naming the missing mapping(s) if any required ID is
    absent. Caller must surface this as a blocked status — never as a 500.
    """
    client_name = (preview.get("client_name") or "").strip()
    # Use the same resolver as the preview so a passing preview implies
    # a successful payload build at this point.
    resolution = _resolve_customer(client_name)
    if resolution["ambiguous"]:
        raise ValueError(
            f"multiple wfirma customer candidates for {client_name!r}: "
            f"{resolution['candidates']} — refusing to auto-pick"
        )
    cust = resolution["customer"]
    contractor_id = resolution["wfirma_customer_id"]
    if not contractor_id:
        raise ValueError(
            f"wfirma_customers has no wfirma_customer_id for "
            f"{client_name!r} (normalized {resolution['normalized_name']!r}) — "
            "register the customer mapping before creating a proforma"
        )

    # Resolve customer master (SSOT for VAT + document defaults, ADR-027 D1).
    # bill_to_contractor_id in customer_master == wfirma_customer_id.
    _cm = get_customer_master(_customer_master_db_path(), contractor_id)
    cm_proforma_series = pick_proforma_series_id(_cm) if _cm else ""
    cm_payment_method = ((_cm.preferred_payment_method or "").strip().lower()
                         if _cm else "")
    cm_payment_terms_days = (_cm.payment_terms_days if _cm else None)
    cm_language_id = ((_cm.default_language_id or "").strip() if _cm else "")

    # ── D1/D2: VAT context from customer_master (ADR-027) ──────────────────
    # Priority 1: vat_mode operator override.
    # Priority 2: derived from country + vat_eu_number.
    # Last-resort: wfirma_customers mirror or live search_customer (read-only).
    _vat_warnings: List[str] = []

    if _cm is not None:
        try:
            _cm_vat = wfirma_client.resolve_vat_context_from_master(_cm)
        except ValueError as _ve:
            raise ValueError(
                f"vat_mode resolution failed for {client_name!r}: {_ve}"
            )
        if _cm_vat["blocked"]:
            # customer_master has no country — fall back to wfirma_customers
            customer_country = ((cust or {}).get("country") or "").strip()
            customer_vat_id  = ((cust or {}).get("vat_id")  or "").strip()
            if not customer_country:
                try:
                    live = wfirma_client.search_customer(client_name)
                except Exception:
                    live = None
                if live is not None:
                    customer_country = (live.country or "").strip()
                    customer_vat_id  = (live.nip or "").strip()
            _fallback = wfirma_client.decide_proforma_vat_context(
                customer_country=customer_country,
                customer_vat_id=customer_vat_id,
            )
            if _fallback["context"] == "blocked":
                raise ValueError(
                    f"vat decision blocked for {client_name!r}: "
                    f"{_cm_vat['blocked_reason']} "
                    f"(fallback also failed: {_fallback['reason']})"
                )
            vat_code_str    = _fallback["vat_code"]
            _decision_source = "fallback_wfirma"
        else:
            vat_code_str    = _cm_vat["vat_code"]
            _decision_source = _cm_vat["decision_source"]
            _vat_warnings.extend(_cm_vat["warnings"])
    else:
        # No customer_master at all — use legacy path
        customer_country = ((cust or {}).get("country") or "").strip()
        customer_vat_id  = ((cust or {}).get("vat_id")  or "").strip()
        if not customer_country or (customer_country.upper() != "PL"
                                     and not customer_vat_id):
            try:
                live = wfirma_client.search_customer(client_name)
            except Exception:
                live = None
            if live is not None:
                customer_country = customer_country or (live.country or "").strip()
                customer_vat_id  = customer_vat_id  or (live.nip     or "").strip()
        _legacy = wfirma_client.decide_proforma_vat_context(
            customer_country=customer_country,
            customer_vat_id=customer_vat_id,
        )
        if _legacy["context"] == "blocked":
            raise ValueError(
                f"vat decision blocked for {client_name!r}: {_legacy['reason']}"
            )
        vat_code_str    = _legacy["vat_code"]
        _decision_source = "fallback_wfirma"

    # Resolve live numeric vat_code_id (never persisted — always live at post).
    try:
        vat_code_id = wfirma_client.resolve_vat_code_id_for_context(vat_code_str)
    except Exception as exc:
        raise ValueError(
            f"vat_code resolution failed for {vat_code_str!r}: {exc}"
        )

    lines = []
    missing_products: List[str] = []
    for ln in preview.get("lines", []):
        pc = ln.get("product_code") or ""
        prod = wfdb.get_product(pc) if (pc and wfdb._db_path is not None) else None
        good_id = (prod or {}).get("wfirma_product_id") or ""
        if not good_id:
            missing_products.append(pc or "<unknown>")
            continue
        lines.append(wfirma_client.ReservationLine(
            product_code   = pc,
            wfirma_good_id = good_id,
            product_name   = ln.get("design_no") or pc,
            qty            = float(ln.get("qty") or 0),
            unit_price     = float(ln.get("unit_price") or 0),
            unit           = "szt.",
            currency       = (ln.get("currency") or preview.get("currency") or "PLN"),
        ))
    if missing_products:
        raise ValueError(
            "wfirma_products missing wfirma_product_id for: "
            + ", ".join(missing_products[:5])
            + ("…" if len(missing_products) > 5 else "")
        )

    # ── Ship-to (Odbiorca) — Shape B threading ────────────────────────────
    # Read the per-customer ship_to_mode + ship_to_wfirma_customer_id set
    # via PUT /api/v1/wfirma/customers/{name}/ship-to (Step 1 helper).
    # Behaviour:
    #   same_as_bill_to / bill_to_alt → no receiver block emitted; wFirma
    #                                    renders ship-to from the bill-to
    #                                    contractor record.
    #   separate_contractor           → ship_to_wfirma_customer_id is
    #                                    threaded into ProformaRequest;
    #                                    builder emits <contractor_receiver>.
    #
    # Validation: separate_contractor requires a non-empty receiver id
    # (the Step-1 helper already enforces this on write, but defence-
    # in-depth at request-build time catches a stale row that pre-dates
    # the helper landing).
    ship_to_mode    = ((cust or {}).get("ship_to_mode") or "same_as_bill_to").lower()
    ship_to_rcv_id  = ((cust or {}).get("ship_to_wfirma_customer_id") or "").strip()
    if ship_to_mode == "separate_contractor" and not ship_to_rcv_id:
        raise ValueError(
            f"ship_to_mode is 'separate_contractor' for {client_name!r} but "
            "ship_to_wfirma_customer_id is empty — set the receiver via "
            "PUT /api/v1/wfirma/customers/{name}/ship-to before issuing"
        )
    if ship_to_mode == "separate_contractor" and ship_to_rcv_id == contractor_id:
        # Should be impossible (helper rejects self-reference) but guard
        # against a stale row that pre-dates the helper.
        raise ValueError(
            f"ship_to_wfirma_customer_id equals the bill-to "
            f"wfirma_customer_id for {client_name!r} — separate_contractor "
            "requires a DIFFERENT receiver"
        )
    receiver_id = ship_to_rcv_id if ship_to_mode == "separate_contractor" else ""

    _req = wfirma_client.ProformaRequest(
        client_name                   = client_name,
        client_zip                    = "",
        client_city                   = "",
        lines                         = lines,
        currency                      = preview.get("currency") or "PLN",
        wfirma_contractor_id          = contractor_id,
        vat_code_id                   = vat_code_id,
        wfirma_contractor_receiver_id = receiver_id,
        series_id                     = cm_proforma_series or "",
        payment_method                = cm_payment_method,
        # ADR-027 D6 — document defaults from customer_master
        payment_terms_days            = cm_payment_terms_days,
        translation_language_id       = cm_language_id,
    )
    return _req, _vat_warnings


@router.post("/create/{batch_id}/{client_name:path}", dependencies=[_auth])
def proforma_create(
    batch_id:     str,
    client_name:  str,
    x_operator:   Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """
    Create a wFirma proforma when all gates are satisfied.

    Status values:
      blocked        — preview not ready, OR settings gate is off
                       (no draft persisted, no live call)
      skipped        — existing draft is in pending_local or issued
      issued         — live wFirma call succeeded; draft.status='issued',
                       wfirma_proforma_id populated
      failed         — live wFirma call returned an error; draft.status='failed',
                       retryable

    Idempotent on (batch_id, client_name). Failed drafts ARE retryable;
    pending_local and issued drafts short-circuit as skipped.
    """
    cn = _validate_args(batch_id, client_name)
    preview = _build_preview(batch_id, cn)

    # ── 1. Existing draft short-circuit (issued / pending_local) ────────────
    existing = pildb.get_draft(_proforma_db_path(), batch_id, cn)
    if existing is not None and existing.status in ("issued", "pending_local"):
        return JSONResponse({
            "ok":                  True,
            "status":              "skipped",
            "existing_status":     existing.status,
            "batch_id":            batch_id,
            "client_name":         cn,
            "wfirma_proforma_id":  existing.wfirma_proforma_id,
            "currency":            existing.currency,
            "exchange_rate":       existing.exchange_rate,
            "draft_id":            existing.id,
        })

    # ── 2. Commercial readiness gate (warehouse + customer + stock) ──────────
    # draft_ready = not blocking_reasons (product/customer/stock/price).
    # Export blockers (wFirma PZ required for live issuance) are checked
    # separately after the local draft is saved — they do NOT block draft
    # persistence, only live wFirma issuance.
    if not preview.get("draft_ready"):
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "blocking_reasons": preview.get("blocking_reasons", []),
            "export_blockers":  preview.get("export_blockers", []),
            "currency":         preview.get("currency"),
            "exchange_rate":    preview.get("exchange_rate"),
        })

    # ── 3a. Service-charge snapshot (Phase 6D) ──────────────────────────
    # Service charges are snapshotted into the draft at create time so
    # the finance dual-write hook always sees the charges that were live
    # when the operator confirmed the proforma.
    #
    # wFirma proforma CONTENT: charges are only included as line items
    # when a wFirma service product mapping exists in wfirma_products.
    # If no mapping is present the proforma is created without those
    # lines (warn, don't block) — the snapshot still powers accounting.
    _raw_service_charges: List[Dict[str, Any]] = preview.get("service_charges") or []
    _service_charges_json_snapshot = json.dumps(
        [{"charge_type": c.get("charge_type"), "amount": c.get("amount"),
          "currency": c.get("currency"), "note": c.get("note") or ""}
         for c in _raw_service_charges],
        ensure_ascii=False,
        sort_keys=True,
    )
    _service_charges_wfirma_warning: Optional[str] = None
    if _raw_service_charges:
        # Check whether a service product mapping exists for any charge type.
        # If not, note it in the response but do not block.
        # Use module-level wfdb so monkeypatching in tests works correctly.
        _sc_types = {(c.get("charge_type") or "").lower() for c in _raw_service_charges}
        _unmapped = [
            ct for ct in _sc_types
            if wfdb._db_path is None or not wfdb.get_product(ct)
        ]
        if _unmapped:
            _service_charges_wfirma_warning = (
                f"service charges ({', '.join(sorted(_unmapped))}) snapshotted for "
                "accounting but NOT included in wFirma proforma content — "
                "register a service product mapping to include them as line items"
            )
            log.warning(
                "[%s/%s] %s", batch_id, cn, _service_charges_wfirma_warning
            )

    # ── 3. Settings gate — no live call when disabled ──────────────────────
    if not settings.wfirma_create_proforma_allowed:
        return JSONResponse({
            "ok":               False,
            "status":            "blocked",
            "batch_id":          batch_id,
            "client_name":       cn,
            "blocking_reasons":  ["wfirma proforma create disabled "
                                  "(WFIRMA_CREATE_PROFORMA_ALLOWED=false)"],
            "currency":          preview.get("currency"),
            "exchange_rate":     preview.get("exchange_rate"),
        })

    # ── 4. Lock or upsert the draft row (pending_local) ────────────────────
    source_lines = [
        {
            "product_code": ln.get("product_code"),
            "design_no":    ln.get("design_no"),
            "qty":          ln.get("qty"),
            "unit_price":   ln.get("unit_price"),
            "currency":     ln.get("currency"),
        }
        for ln in preview.get("lines", [])
    ]
    source_lines_json = json.dumps(source_lines, ensure_ascii=False)

    if existing is not None and existing.status == "failed":
        # Retry path — keep the same row; refresh service_charges_json
        # so a retry after charges were added picks up the current snapshot.
        draft = existing
        if _raw_service_charges:
            try:
                pildb._commit_draft_update(
                    _proforma_db_path(), draft.id,
                    new_state           = draft.draft_state or "post_failed",
                    new_service_charges = [
                        {"charge_type": c.get("charge_type"),
                         "amount":      c.get("amount"),
                         "currency":    c.get("currency"),
                         "note":        c.get("note") or ""}
                        for c in _raw_service_charges
                    ],
                )
                draft = pildb.get_draft_by_id(_proforma_db_path(), draft.id) or draft
            except Exception as _sc_upd_exc:
                log.warning("[%s/%s] retry service_charges update failed: %s",
                            batch_id, cn, _sc_upd_exc)
    else:
        draft, _ = pildb.upsert_pending_draft(
            _proforma_db_path(),
            batch_id              = batch_id,
            client_name           = cn,
            currency              = preview.get("currency", ""),
            exchange_rate         = preview.get("exchange_rate"),
            source_lines_json     = source_lines_json,
            service_charges_json  = _service_charges_json_snapshot,
        )

    # ── GAP-17: advisory check — each line product_code should exist in product_master ──
    # Advisory only (NOT a hard block). If a product_code is absent from product_master,
    # write an advisory action_proposal to audit.json so the operator sees it in the Inbox.
    try:
        from ..services.reservation_db import validate_product_code_in_master as _gap17_val
        _gap17_rq = settings.storage_root / "reservation_queue.db"
        _gap17_audit = settings.storage_root / "outputs" / batch_id / "audit.json"
        if _gap17_rq.exists() and _gap17_audit.exists():
            _gap17_missing = [
                ln.get("product_code", "")
                for ln in (preview.get("lines") or [])
                if ln.get("product_code") and not _gap17_val(_gap17_rq, ln["product_code"])
            ]
            if _gap17_missing:
                from ..pipelines.pz import _advisory_to_action_proposal, _write_advisory_proposal
                _gap17_adv_entry = _advisory_to_action_proposal(
                    {
                        "code": "GAP17_PRODUCT_NOT_IN_MASTER",
                        "message": (
                            f"{len(_gap17_missing)} product_code(s) not in product_master "
                            f"(GAP-17): {_gap17_missing[:5]}"
                        ),
                        "action": "Run product master backfill or register the products.",
                    },
                    batch_id, "proforma_create",
                )
                _gap17_audit_data = json.loads(_gap17_audit.read_text(encoding="utf-8"))
                _write_advisory_proposal(_gap17_audit, _gap17_adv_entry)
    except Exception as _gap17_exc:
        log.debug("[%s/%s] GAP-17 editable_lines check failed (non-fatal): %s",
                  batch_id, cn, _gap17_exc)

    # ── 4b. Export gate — wFirma PZ required for live issuance ──────────────
    # The local draft has been persisted as pending_local. Live issuance to
    # wFirma defers until wFirma PZ is created. Operator can see the draft
    # in the dashboard now and proceed to PZ creation, then retry /create.
    _export_blockers = preview.get("export_blockers") or []
    if _export_blockers:
        return JSONResponse({
            "ok":              True,
            "status":          "pending_local",
            "draft_saved":     True,
            "export_blocked":  True,
            "batch_id":        batch_id,
            "client_name":     cn,
            "draft_id":        draft.id,
            "export_blockers": _export_blockers,
            "currency":        preview.get("currency"),
            "exchange_rate":   preview.get("exchange_rate"),
            "note": (
                "Draft saved locally. Proforma issuance to wFirma requires "
                "wFirma PZ — run PZ create then retry this endpoint."
            ),
        })

    # ── 5. Live wFirma call (only path with external write) ────────────────
    # _build_proforma_request resolves wfirma_customer_id + per-line
    # wfirma_product_id from local mappings. Missing mappings = blocked,
    # not failed — this is a configuration gate, not an external write
    # failure. Refusing to build avoids any chance of submitting a payload
    # that wFirma would reject or, worse, accept by creating a duplicate
    # contractor inline.
    try:
        req, _legacy_vat_warnings = _build_proforma_request(preview)
    except ValueError as exc:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "draft_id":         draft.id,
            "blocking_reasons": [str(exc)],
        })

    # ── Service charge lines — emit mapped charges as wFirma line items ────
    # Only charges with a wfirma_products mapping are included. Unmapped
    # charges are already snapshotted for accounting (finance_dual_write) —
    # the note is surfaced to the operator but does NOT block the create.
    if _raw_service_charges:
        _sc_lines, _sc_lines_note = _build_service_charge_lines(
            _raw_service_charges, req.currency
        )
        req.lines.extend(_sc_lines)
        if _sc_lines_note:
            _service_charges_wfirma_warning = _sc_lines_note

    # ── Live wFirma receiver preflight (Step 3 of Nabywca/Odbiorca) ────────
    # When a separate Odbiorca contractor was threaded into the request
    # (Shape B), confirm it actually exists in wFirma master before the
    # invoices/add call. Without this, a typo or since-deleted contractor
    # surfaces only as a generic wFirma error AFTER a partial state has
    # been written. Read-only call; never creates. Skipped entirely for
    # Shape A (empty receiver id).
    receiver_id = (req.wfirma_contractor_receiver_id or "").strip()
    if receiver_id:
        try:
            rcv = wfirma_client.fetch_contractor_by_id(receiver_id)
        except Exception as exc:
            return JSONResponse({
                "ok":               False,
                "status":           "blocked",
                "batch_id":         batch_id,
                "client_name":      cn,
                "draft_id":         draft.id,
                "blocking_reasons": [
                    f"receiver preflight failed: {type(exc).__name__}: {exc}"
                ],
            })
        if not rcv.ok:
            return JSONResponse({
                "ok":               False,
                "status":           "blocked",
                "batch_id":         batch_id,
                "client_name":      cn,
                "draft_id":         draft.id,
                "blocking_reasons": [
                    f"receiver contractor id {receiver_id!r} not found in "
                    f"wFirma — {rcv.error or 'unavailable'}. Register the "
                    "receiver in wFirma master or update the ship-to "
                    "mapping via PUT /api/v1/wfirma/customers/{name}/ship-to"
                ],
            })

    try:
        result = wfirma_client.create_proforma_draft(req)
    except Exception as exc:
        # Treat any unexpected failure (NotImplementedError, network, parse)
        # as a retryable failure. Mark draft and surface error.
        pildb.mark_draft_failed(
            _proforma_db_path(), batch_id, cn,
            notes=f"{type(exc).__name__}: {exc}"[:500],
        )
        return JSONResponse({
            "ok":          False,
            "status":      "failed",
            "batch_id":    batch_id,
            "client_name": cn,
            "draft_id":    draft.id,
            "error":       f"{type(exc).__name__}: {exc}",
        })

    if not result.ok:
        pildb.mark_draft_failed(
            _proforma_db_path(), batch_id, cn,
            notes=(result.error or "wfirma create_proforma_draft returned ok=false")[:500],
        )
        return JSONResponse({
            "ok":          False,
            "status":      "failed",
            "batch_id":    batch_id,
            "client_name": cn,
            "draft_id":    draft.id,
            "error":       result.error or "unknown",
        })

    # ── 6. Success: mark issued, persist wfirma_proforma_id ────────────────
    pildb.mark_draft_issued(
        _proforma_db_path(), batch_id, cn,
        wfirma_proforma_id         = result.wfirma_invoice_id or "",
        wfirma_proforma_fullnumber = result.wfirma_invoice_number or "",
    )
    final = pildb.get_draft(_proforma_db_path(), batch_id, cn)

    # ── 6a. Phase 3 — best-effort post-posting enrichment ─────────────────
    # Fetch issue_date / payment_due / payment_method from wFirma and store
    # on the draft. Best-effort: never fails the main flow.
    _wfirma_id_for_enrich = (result.wfirma_invoice_id or "").strip()
    if _wfirma_id_for_enrich and final:
        try:
            _enrich = wfirma_client.fetch_proforma_enrichment(
                _wfirma_id_for_enrich)
            pildb.write_postposting_enrichment(
                _proforma_db_path(),
                final.id,
                wfirma_issue_date     = _enrich.get("issue_date") or None,
                wfirma_payment_due    = _enrich.get("payment_due") or None,
                wfirma_payment_method = _enrich.get("payment_method") or None,
            )
            final = pildb.get_draft(_proforma_db_path(), batch_id, cn)
        except Exception as _enrich_exc:
            log.warning("[%s] post-posting enrichment skipped: %s",
                        batch_id, _enrich_exc)

    # Append-only audit hardening: persist Proforma id under
    # audit.proforma_issued[] and emit a timeline event so audit.json
    # alone reflects the issued state. Best-effort.
    try:
        from ..services.audit_persist import record_proforma_issued
        from ..core.config import settings as _s
        _audit_path = _s.storage_root / "outputs" / batch_id / "audit.json"
        # Phase 9.2 — surface the X-Operator header on the legacy route
        # so its audit rows match the Phase-5 /post identity quality.
        # Fallback mirrors the PZ flow's _operator_or_default: trimmed
        # header value if non-empty, otherwise the literal "operator".
        # Stays NON-mandatory — old callers without the header keep
        # working and just record under the safe-fallback identity.
        _op = ((x_operator or "").strip() or "operator")
        record_proforma_issued(
            _audit_path,
            batch_id                   = batch_id,
            client_name                = cn,
            wfirma_proforma_id         = result.wfirma_invoice_id or "",
            wfirma_proforma_fullnumber = (result.wfirma_invoice_number or ""),
            line_count                 = len(preview.get("lines") or []),
            currency                   = (final or draft).currency or "",
            operator                   = _op,
        )
    except Exception as _exc:
        log.warning("[%s] proforma_create audit append skipped: %s",
                    batch_id, _exc)

    _resp: Dict[str, Any] = {
        "ok":                  True,
        "status":              "issued",
        "batch_id":            batch_id,
        "client_name":         cn,
        "draft_id":            final.id if final else draft.id,
        "wfirma_proforma_id":  result.wfirma_invoice_id,
        "wfirma_proforma_fullnumber": (final or draft).wfirma_proforma_fullnumber or "",
        "currency":            (final or draft).currency,
        "exchange_rate":       (final or draft).exchange_rate,
        "service_charges_snapshotted": len(_raw_service_charges),
    }
    if _service_charges_wfirma_warning:
        _resp["service_charges_note"] = _service_charges_wfirma_warning
    if _legacy_vat_warnings:
        _resp["vat_warnings"] = _legacy_vat_warnings
    return JSONResponse(_resp)


# ── Cancel-issued-for-reissue ───────────────────────────────────────────────
#
# Deletes a wrong-payload proforma from wFirma and resets the local draft
# to failed/retryable so the create route can issue a corrected payload.
# The wFirma delete MUST succeed before the local row is changed — if the
# delete fails the local draft remains 'issued' so no data is lost.

@router.post("/cancel-issued-for-reissue/{batch_id}/{client_name:path}",
             dependencies=[_auth])
def cancel_issued_proforma_for_reissue(
    batch_id:    str,
    client_name: str,
    confirm:     str = "",
) -> JSONResponse:
    """
    Cancel an issued wFirma proforma and reset the local draft to
    failed/retryable. Intended for cancel+reissue of wrong-payload or
    partial-line proformas (e.g. PROF 92/2026 — 1 line instead of 12,
    wrong vat_code).

    Guards (in order):
      1. WFIRMA_DELETE_INVOICE_ALLOWED=true
      2. confirm == "YES_DELETE_AND_REISSUE_ONE_PROFORMA"
      3. Local draft status must be "issued"
      4. wfirma_proforma_id must be present on the draft
      5. wFirma delete must return OK before the local row is changed

    Normalisation: ``_validate_args`` (strip-only). Must match the create
    route exactly — uppercasing here would break the lookup against
    proforma_drafts rows persisted by create with mixed-case client names.
    """
    cn = _validate_args(batch_id, client_name)

    # ── 1. Settings gate ───────────────────────────────────────────────────
    if not settings.wfirma_delete_invoice_allowed:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "blocking_reasons": ["WFIRMA_DELETE_INVOICE_ALLOWED=false — "
                                 "enable to proceed"],
        })

    # ── 2. Explicit confirmation string ────────────────────────────────────
    if confirm != "YES_DELETE_AND_REISSUE_ONE_PROFORMA":
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "blocking_reasons": ["confirm string missing or wrong — "
                                 "must be YES_DELETE_AND_REISSUE_ONE_PROFORMA"],
        })

    # ── 3 + 4. Local draft state ────────────────────────────────────────────
    existing = pildb.get_draft(_proforma_db_path(), batch_id, cn)
    if existing is None:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "blocking_reasons": ["no local draft found for this batch/client"],
        })
    if existing.status != "issued":
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "blocking_reasons": [
                f"draft status is {existing.status!r} — must be 'issued' "
                "to cancel"
            ],
        })
    wfirma_id = (existing.wfirma_proforma_id or "").strip()
    if not wfirma_id:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "blocking_reasons": ["wfirma_proforma_id is missing on draft — "
                                 "cannot identify which invoice to delete"],
        })

    # ── 5. wFirma delete — local row untouched until this returns OK ────────
    try:
        wfirma_client.delete_invoice(wfirma_id)
    except Exception as exc:
        return JSONResponse({
            "ok":                 False,
            "status":             "failed",
            "batch_id":           batch_id,
            "client_name":        cn,
            "wfirma_proforma_id": wfirma_id,
            "error": (
                f"wFirma delete failed — local draft unchanged: "
                f"{type(exc).__name__}: {exc}"
            ),
        })

    # Confirmed delete — now reset local row.
    try:
        pildb.mark_draft_cancelled_for_reissue(
            _proforma_db_path(), batch_id, cn,
            deleted_wfirma_id=wfirma_id,
            reason="cancel-issued-for-reissue endpoint",
        )
    except Exception as exc:
        log.error(
            "delete_invoice ok but local reset failed batch=%s client=%s "
            "wfirma_id=%s err=%s", batch_id, cn, wfirma_id, exc,
        )
        return JSONResponse({
            "ok":                 False,
            "status":             "failed",
            "batch_id":           batch_id,
            "client_name":        cn,
            "wfirma_proforma_id": wfirma_id,
            "error": (
                f"wFirma delete succeeded (id={wfirma_id}) but local reset "
                f"failed: {type(exc).__name__}: {exc} — "
                "proforma is gone from wFirma; create can be retried manually"
            ),
        })

    # Append-only audit hardening: emit a `proforma_cancelled` timeline
    # event so audit.json carries proof of the cancellation. Best-effort —
    # never breaks the operator-facing response (the local row is already
    # reset; the wFirma document is already gone).
    try:
        from ..services.audit_persist import record_proforma_cancelled
        from ..core.config import settings as _s
        _audit_path = _s.storage_root / "outputs" / batch_id / "audit.json"
        record_proforma_cancelled(
            _audit_path,
            batch_id                       = batch_id,
            client_name                    = cn,
            deleted_wfirma_proforma_id     = wfirma_id,
            replaced_by_wfirma_proforma_id = "",
            reason                         = "cancel-issued-for-reissue endpoint",
            operator                       = "",
            source                         = "cancel_for_reissue",
        )
    except Exception as _exc:
        log.warning("[%s] cancel: audit append skipped: %s", batch_id, _exc)

    return JSONResponse({
        "ok":                True,
        "status":            "cancelled_for_reissue",
        "batch_id":          batch_id,
        "client_name":       cn,
        "deleted_wfirma_id": wfirma_id,
        "local_status":      "failed",
        "next_step":         (
            f"POST /api/v1/proforma/create/{batch_id}/{client_name} "
            "to reissue with corrected payload"
        ),
    })


# ── Adopt an existing wFirma proforma into local draft tracking ──────────────
#
# Used when an old proforma was issued before local draft tracking was added.
# Registers the wFirma id locally as status='issued' so cancel-issued-for-
# reissue can run against it. Does NOT make any wFirma writes.

from pydantic import BaseModel as _BaseModel  # noqa: E402 — localised import


class _AdoptIssuedBody(_BaseModel):
    wfirma_proforma_id: str
    reason: str


@router.post("/adopt-issued/{batch_id}/{client_name:path}", dependencies=[_auth])
def adopt_issued_proforma(
    batch_id:    str,
    client_name: str,
    body:        _AdoptIssuedBody,
) -> JSONResponse:
    """
    Register an existing wFirma proforma that predates local draft tracking.

    Behaviour:
      • Fetches the invoice XML to confirm type=proforma and id match.
      • Optionally verifies contractor id against local wfirma_customers mapping
        (warns if no mapping found; blocks if mapping present but contractor
        id mismatches).
      • Idempotent if called twice with the same wfirma_proforma_id.
      • Blocks if a different issued proforma is already registered locally.
      • No wFirma writes, no financial field changes.
    """
    cn              = _norm(client_name)
    wfirma_id_body  = (body.wfirma_proforma_id or "").strip()
    reason          = (body.reason or "").strip()

    if not wfirma_id_body:
        return JSONResponse({"ok": False, "status": "blocked",
                             "blocking_reasons": ["wfirma_proforma_id is required"]})
    if not reason:
        return JSONResponse({"ok": False, "status": "blocked",
                             "blocking_reasons": ["reason is required"]})

    # ── Fetch invoice XML ─────────────────────────────────────────────────────
    try:
        invoice_xml = wfirma_client.fetch_invoice_xml(wfirma_id_body)
    except Exception as exc:
        return JSONResponse({
            "ok":     False,
            "status": "blocked",
            "error":  f"wFirma XML fetch failed: {type(exc).__name__}: {exc}",
        })

    # ── Verify type=proforma ──────────────────────────────────────────────────
    try:
        root = ET.fromstring(invoice_xml)
    except ET.ParseError as exc:
        return JSONResponse({
            "ok":     False,
            "status": "blocked",
            "error":  f"wFirma returned invalid XML: {exc}",
        })

    invoice_node = root.find(".//invoice")
    if invoice_node is None:
        return JSONResponse({
            "ok":     False,
            "status": "blocked",
            "error":  "wFirma XML has no <invoice> element",
        })
    invoice_type = (invoice_node.findtext("type") or "").strip().lower()
    if invoice_type != "proforma":
        return JSONResponse({
            "ok":     False,
            "status": "blocked",
            "error":  f"wFirma document type is {invoice_type!r}, expected 'proforma'",
        })

    # ── Verify id matches body ────────────────────────────────────────────────
    fetched_id = (invoice_node.findtext("id") or "").strip()
    if fetched_id and fetched_id != wfirma_id_body:
        return JSONResponse({
            "ok":     False,
            "status": "blocked",
            "error":  (
                f"wFirma returned invoice id={fetched_id!r} but body "
                f"wfirma_proforma_id={wfirma_id_body!r} — id mismatch"
            ),
        })

    # ── Contractor verification ───────────────────────────────────────────────
    # Use the central resolver (same as preview / payload builder) so a
    # whitespace-padded or "Ltd"-suffixed sales name still verifies
    # against the wFirma contractor id.
    contractor_warn = None
    _resolution = _resolve_customer(cn)
    cust = _resolution["customer"] if _resolution["found"] else None
    if cust and cust.get("wfirma_customer_id"):
        expected_contractor_id = str(cust["wfirma_customer_id"]).strip()
        contractor_node        = invoice_node.find(".//contractor")
        fetched_contractor_id  = ""
        if contractor_node is not None:
            fetched_contractor_id = (contractor_node.findtext("id") or "").strip()
        if fetched_contractor_id and fetched_contractor_id != expected_contractor_id:
            return JSONResponse({
                "ok":     False,
                "status": "blocked",
                "error":  (
                    f"contractor id mismatch: wFirma returned {fetched_contractor_id!r}, "
                    f"local mapping expects {expected_contractor_id!r} for {cn!r}"
                ),
            })
        if not fetched_contractor_id:
            contractor_warn = "contractor id absent in XML — could not verify"
    else:
        contractor_warn = (
            f"no wfirma_customers mapping for {cn!r} — contractor not verified"
        )

    # ── Adopt locally ─────────────────────────────────────────────────────────
    try:
        draft, was_created = pildb.adopt_issued_draft(
            _proforma_db_path(), batch_id, cn,
            wfirma_proforma_id=wfirma_id_body,
            reason=reason,
        )
    except ValueError as exc:
        return JSONResponse({
            "ok":     False,
            "status": "blocked",
            "error":  str(exc),
        })

    result: Dict[str, Any] = {
        "ok":                  True,
        "status":              "adopted" if was_created else "already_adopted",
        "batch_id":            batch_id,
        "client_name":         cn,
        "wfirma_proforma_id":  wfirma_id_body,
        "local_status":        draft.status,
        "was_created":         was_created,
        "next_step": (
            f"POST /api/v1/proforma/cancel-issued-for-reissue/{batch_id}/{client_name} "
            "to delete from wFirma and reset for reissue"
        ),
    }
    if contractor_warn:
        result["contractor_warning"] = contractor_warn
    return JSONResponse(result)


# ── Refresh proforma line names from locked description blocks ──────────────
#
# Operator-approved per-call. wFirma freezes invoicecontent <name> at issue
# time; the only way to bring an existing proforma's line names in sync with
# the current product master description_line is to POST a full-line restate
# to /invoices/edit/{invoice_id}. Live diagnostic 2026-05-06 confirmed:
#   - partial line edits are rejected (NOT_FOUND)
#   - header edits succeed
#   - full-line restate (only <name> changed) succeeds
#
# This route never deletes/reissues the proforma, never touches contractor /
# currency / quantity / price / VAT, never updates local DB rows, and never
# converts the proforma to a final invoice.

def _build_wfirma_id_to_code_map() -> Dict[str, str]:
    """{wfirma_product_id → product_code} from wfirma_products."""
    out: Dict[str, str] = {}
    if wfdb._db_path is None:
        return out
    for row in wfdb.list_products():
        wid = (row.get("wfirma_product_id") or "").strip()
        pc  = (row.get("product_code")      or "").strip()
        if wid and pc:
            out[wid] = pc
    return out


def _resolve_correct_line_name(product_code: str) -> Optional[str]:
    """Return the locked description_line for a product_code, or None."""
    if not product_code or ddb._db_path is None:
        return None
    row = ddb.get_product_description(product_code)
    if not row:
        return None
    return (row.get("description_line") or "").strip() or None


@router.post("/{wfirma_id}/refresh-line-names", dependencies=[_auth])
def proforma_refresh_line_names(wfirma_id: str) -> JSONResponse:
    """
    Refresh existing wFirma proforma line names from the locked product
    descriptions. Operator-approved per call. One proforma id per call.

    Status values:
      blocked  — settings gate off, OR id is not a proforma, OR a required
                 product mapping is missing for some line (refusal to start
                 a partial refresh)
      ok       — all stale lines were updated successfully
      partial  — some line edits failed at wFirma (per-line errors reported)
    """
    if not (wfirma_id or "").strip():
        raise HTTPException(status_code=400, detail="wfirma_id is required")

    # Settings gate — no live call when disabled.
    if not settings.wfirma_edit_invoice_allowed:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "wfirma_id":        wfirma_id,
            "blocking_reasons": ["wfirma invoice edit disabled "
                                 "(WFIRMA_EDIT_INVOICE_ALLOWED=false)"],
        })

    # Fetch + verify type=proforma BEFORE any edit.
    try:
        invoice_xml = wfirma_client.fetch_invoice_xml(wfirma_id)
    except (RuntimeError, ValueError, ConnectionError) as exc:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "wfirma_id":        wfirma_id,
            "blocking_reasons": [f"fetch failed: {type(exc).__name__}: {exc}"],
        })

    root = ET.fromstring(invoice_xml)
    invoice = root.find(".//invoice")
    if invoice is None:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "wfirma_id":        wfirma_id,
            "blocking_reasons": ["invoices/find returned no <invoice>"],
        })

    invoice_type = (invoice.findtext("type") or "").strip().lower()
    if invoice_type != "proforma":
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "wfirma_id":        wfirma_id,
            "blocking_reasons": [f"invoice type={invoice_type!r} — refusing "
                                 "edits on non-proforma documents"],
        })

    contents = invoice.find("invoicecontents")
    lines = list(contents.findall("invoicecontent")) if contents is not None else []
    if not lines:
        return JSONResponse({
            "ok":        True,
            "status":    "ok",
            "wfirma_id": wfirma_id,
            "checked":   0,
            "updated":   0,
            "skipped":   0,
            "errors":    [],
            "lines":     [],
        })

    # ── Resolve all mappings BEFORE any edit. Refuse to start if any
    #    line lacks a good/id or product_code mapping (avoids partial drift).
    id_to_code = _build_wfirma_id_to_code_map()

    plan: List[Dict[str, Any]] = []
    setup_errors: List[Dict[str, Any]] = []
    for ic in lines:
        line_id      = (ic.findtext("id") or "").strip()
        current_name = (ic.findtext("name") or "").strip()
        good_id      = ""
        good_node    = ic.find("good")
        if good_node is not None:
            good_id = (good_node.findtext("id") or "").strip()

        if not line_id:
            setup_errors.append({"line_id": line_id, "error": "missing invoicecontent <id>"})
            continue
        if not good_id:
            setup_errors.append({
                "line_id": line_id, "good_id": "", "current_name": current_name,
                "error":   "missing <good><id> on invoicecontent — cannot resolve product",
            })
            continue
        product_code = id_to_code.get(good_id, "")
        if not product_code:
            setup_errors.append({
                "line_id": line_id, "good_id": good_id, "current_name": current_name,
                "error": (
                    f"no wfirma_products row maps wfirma_product_id={good_id!r} "
                    "to a local product_code"
                ),
            })
            continue
        correct_name = _resolve_correct_line_name(product_code)
        if not correct_name:
            setup_errors.append({
                "line_id": line_id, "good_id": good_id, "product_code": product_code,
                "current_name": current_name,
                "error": (
                    f"no product_descriptions row with description_line for "
                    f"product_code={product_code!r}"
                ),
            })
            continue
        plan.append({
            "line_id":       line_id,
            "good_id":       good_id,
            "product_code":  product_code,
            "current_name":  current_name,
            "correct_name":  correct_name,
            "ic_xml":        ET.tostring(ic, encoding="unicode"),
        })

    if setup_errors:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "wfirma_id":        wfirma_id,
            "blocking_reasons": [
                f"{len(setup_errors)} line(s) missing required mappings — "
                "refusing partial refresh"
            ],
            "errors": setup_errors,
        })

    # ── Execute edits. Skip lines already at the correct name. ──────────────
    checked = len(plan)
    updated = 0
    skipped = 0
    line_results: List[Dict[str, Any]] = []
    edit_errors: List[Dict[str, Any]]  = []

    for entry in plan:
        if entry["current_name"] == entry["correct_name"]:
            skipped += 1
            line_results.append({
                "line_id":      entry["line_id"],
                "product_code": entry["product_code"],
                "status":       "already_correct",
                "name":         entry["current_name"],
            })
            continue
        try:
            wfirma_client.edit_invoice_line_name(
                wfirma_id, entry["ic_xml"], entry["correct_name"],
            )
            updated += 1
            line_results.append({
                "line_id":      entry["line_id"],
                "product_code": entry["product_code"],
                "status":       "updated",
                "old_name":     entry["current_name"],
                "new_name":     entry["correct_name"],
            })
        except Exception as exc:
            edit_errors.append({
                "line_id":      entry["line_id"],
                "product_code": entry["product_code"],
                "current_name": entry["current_name"],
                "correct_name": entry["correct_name"],
                "error":        f"{type(exc).__name__}: {exc}",
            })
            line_results.append({
                "line_id":      entry["line_id"],
                "product_code": entry["product_code"],
                "status":       "failed",
                "error":        f"{type(exc).__name__}: {exc}",
            })

    # ── Verify-after-edit: re-fetch and confirm each updated line ──────────
    # wFirma returned status=OK on each edit, but a final re-fetch closes
    # the loop — if any persisted name does not match what we sent, the
    # edit silently no-op'd and the route must surface that as a hard
    # failed_verification rather than green status=ok.
    verify_errors: List[Dict[str, Any]] = []
    if updated > 0 and not edit_errors:
        try:
            verify_xml  = wfirma_client.fetch_invoice_xml(wfirma_id)
            verify_root = ET.fromstring(verify_xml)
            actual_by_id: Dict[str, str] = {}
            for ic in verify_root.iter("invoicecontent"):
                lid = (ic.findtext("id") or "").strip()
                if lid:
                    actual_by_id[lid] = (ic.findtext("name") or "").strip()
            for entry in plan:
                if entry["current_name"] == entry["correct_name"]:
                    continue  # not edited; skipped above
                actual = actual_by_id.get(entry["line_id"], "")
                if actual != entry["correct_name"]:
                    verify_errors.append({
                        "line_id":      entry["line_id"],
                        "product_code": entry["product_code"],
                        "expected":     entry["correct_name"],
                        "actual":       actual,
                    })
        except Exception as exc:
            verify_errors.append({
                "line_id":  "",
                "error":    f"verify fetch failed: {type(exc).__name__}: {exc}",
            })

    if edit_errors:
        overall_status = "partial"
    elif verify_errors:
        overall_status = "failed_verification"
    else:
        overall_status = "ok"

    return JSONResponse({
        "ok":             not edit_errors and not verify_errors,
        "status":         overall_status,
        "wfirma_id":      wfirma_id,
        "checked":        checked,
        "updated":        updated,
        "skipped":        skipped,
        "errors":         edit_errors,
        "verify_errors":  verify_errors,
        "lines":          line_results,
    })


# ── Proforma Document (read-only view) ────────────────────────────────────────

def _parse_proforma_from_xml(xml_text: str) -> dict:
    """
    Parse a wFirma invoices/find response into a structured proforma summary.

    Returns: invoice_type, full_number, date, contractor_id, currency, lines.
    Lines: name, quantity, unit_price, total_net, vat_rate.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}

    inv = root.find(".//invoice")
    if inv is None:
        return {}

    def _txt(*path):
        node = inv
        for tag in path:
            if node is None:
                return ""
            node = node.find(tag)
        return (node.text or "").strip() if node is not None else ""

    invoice_type  = _txt("type") or _txt("invoice_type") or ""
    # wFirma's invoice/proforma read response carries the canonical
    # operator-readable number under ``<fullnumber>`` (no underscore),
    # e.g. "PROF 92/2026". Bare ``<number>`` is the per-month sequence
    # ("92") and only useful as a last-resort fallback. The find/edit
    # query bodies use ``<full_number>`` — a separate namespace, left
    # untouched.
    full_number   = (
        _txt("fullnumber")
        or _txt("full_number")
        or _txt("number")
        or ""
    )
    date          = _txt("date") or _txt("invoice_date") or ""
    contractor_id = _txt("contractor", "id") or _txt("contractor_id") or ""
    # Optional Odbiorca / ship-to contractor reference. wFirma normalises
    # "no separate receiver" as id="0" on read responses (per the snapshot
    # tool's convention). Project as empty string in that case so callers
    # don't display the sentinel as a real id.
    contractor_receiver_id = _txt("contractor_receiver", "id") or ""
    if contractor_receiver_id.strip() == "0":
        contractor_receiver_id = ""
    currency      = _txt("currency") or "PLN"
    status        = _txt("status") or ""

    lines: List[dict] = []
    for ic in root.findall(".//invoicecontent"):
        def _ctxt(*path):
            node = ic
            for tag in path:
                if node is None:
                    return ""
                node = node.find(tag)
            return (node.text or "").strip() if node is not None else ""

        name = _ctxt("name") or ""
        try:
            qty = float(_ctxt("count") or _ctxt("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1.0
        try:
            unit_price = float(_ctxt("price_netto") or _ctxt("unit_price") or 0)
        except (TypeError, ValueError):
            unit_price = 0.0
        try:
            total_net = float(_ctxt("netto") or _ctxt("total_netto") or 0)
        except (TypeError, ValueError):
            total_net = 0.0
        vat_rate = _ctxt("vat", "code") or _ctxt("vat_code") or ""

        lines.append({
            "name":       name,
            "quantity":   qty,
            "unit_price": unit_price,
            "total_net":  total_net,
            "vat_rate":   vat_rate,
        })

    return {
        "invoice_type":           invoice_type,
        "full_number":            full_number,
        "date":                   date,
        "contractor_id":          contractor_id,
        "contractor_receiver_id": contractor_receiver_id,
        "currency":               currency,
        "status":                 status,
        "lines":                  lines,
    }


@router.get("/{batch_id}/{client_name:path}/document", dependencies=[_auth])
async def proforma_document(batch_id: str, client_name: str) -> JSONResponse:
    """
    Read-only view of the linked wFirma proforma invoice.

    Reads the wfirma_proforma_id from the proforma_drafts table, fetches the
    invoice XML from wFirma, and returns structured JSON with header + lines.

    Blocks if invoice_type is not 'proforma' (safety guard against viewing
    regular invoices via this endpoint).

    No writes are performed.

    Response fields
    ---------------
    batch_id          echoed
    client_name       echoed
    wfirma_proforma_id  wFirma invoice ID
    invoice_type      must be 'proforma'
    full_number       human-readable invoice number
    date              invoice date
    contractor_id     wFirma contractor (customer) ID
    currency          invoice currency
    status            wFirma document status
    line_count        number of invoice lines
    lines             list of {name, quantity, unit_price, total_net, vat_rate}
    raw_xml           raw wFirma XML response (for diagnostics)
    """
    cn = (client_name or "").strip()
    if not cn:
        raise HTTPException(status_code=400, detail="client_name is required")

    db_path = _proforma_db_path()
    draft   = pildb.get_draft(db_path, batch_id, cn)

    if draft is None or not (draft.wfirma_proforma_id or "").strip():
        raise HTTPException(
            status_code=404,
            detail={
                "error":      "No proforma linked to this shipment/client.",
                "code":       "PROFORMA_NOT_LINKED",
                "batch_id":   batch_id,
                "client_name": cn,
            },
        )

    wfirma_id = draft.wfirma_proforma_id.strip()

    try:
        xml_text = wfirma_client.fetch_invoice_xml(wfirma_id)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error":    f"wFirma fetch failed: {exc}",
                "code":     "PROFORMA_FETCH_FAILED",
                "batch_id": batch_id,
                "wfirma_proforma_id": wfirma_id,
            },
        )

    parsed = _parse_proforma_from_xml(xml_text)

    # Safety: reject if wFirma says this is not a proforma
    invoice_type = (parsed.get("invoice_type") or "").lower()
    if invoice_type and invoice_type != "proforma":
        log.warning(
            "[%s/%s] proforma_document: wFirma id %s is type=%r, not proforma",
            batch_id, cn, wfirma_id, invoice_type,
        )
        raise HTTPException(
            status_code=409,
            detail={
                "error":        f"Document {wfirma_id!r} is type {invoice_type!r}, not proforma.",
                "code":         "NOT_A_PROFORMA",
                "batch_id":     batch_id,
                "wfirma_id":    wfirma_id,
                "invoice_type": invoice_type,
            },
        )

    log.info(
        "[%s/%s] proforma_document: fetched proforma %s (%d lines)",
        batch_id, cn, wfirma_id, len(parsed.get("lines", [])),
    )

    return JSONResponse({
        "batch_id":           batch_id,
        "client_name":        cn,
        "wfirma_proforma_id": wfirma_id,
        "invoice_type":       parsed.get("invoice_type", ""),
        "full_number":        parsed.get("full_number", ""),
        "date":               parsed.get("date", ""),
        "contractor_id":      parsed.get("contractor_id", ""),
        "currency":           parsed.get("currency", "PLN"),
        "status":             parsed.get("status", ""),
        "line_count":         len(parsed.get("lines", [])),
        "lines":              parsed.get("lines", []),
        "raw_xml":            xml_text,
    })


@router.get("/{batch_id}/{client_name:path}/document.pdf",
             dependencies=[_auth])
async def proforma_document_pdf(batch_id: str, client_name: str) -> Response:
    """Download the PDF of the linked wFirma Proforma.

    READ-ONLY: calls ``wfirma_client.fetch_invoice_pdf`` (path-based
    ``GET invoices/download/{id}``). Never writes to wFirma.

    Returns:
      200 + ``application/pdf`` — bytes streamed back to the operator.
      404 — no draft for (batch, client), or draft has no
            ``wfirma_proforma_id`` (i.e. not yet posted).
      502 — wFirma fetch / parse failed.

    The download filename uses ``wfirma_proforma_fullnumber`` if known
    on the local draft (e.g. ``PRO 12_2026.pdf``); otherwise it falls
    back to the wFirma id (``proforma-465123456.pdf``).
    """
    cn = (client_name or "").strip()
    if not cn:
        raise HTTPException(status_code=400, detail="client_name is required")

    db_path = _proforma_db_path()
    draft   = pildb.get_draft(db_path, batch_id, cn)
    if draft is None or not (draft.wfirma_proforma_id or "").strip():
        raise HTTPException(
            status_code=404,
            detail={
                "error":       "No proforma linked to this shipment/client.",
                "code":        "PROFORMA_NOT_LINKED",
                "batch_id":    batch_id,
                "client_name": cn,
            },
        )
    wfirma_id = draft.wfirma_proforma_id.strip()

    try:
        pdf_bytes = wfirma_client.fetch_invoice_pdf(wfirma_id)
    except Exception as exc:
        log.warning(
            "[%s/%s] proforma_document_pdf: fetch_invoice_pdf failed for id=%s: %s",
            batch_id, cn, wfirma_id, exc,
        )
        raise HTTPException(
            status_code=502,
            detail={
                "error":              f"wFirma PDF fetch failed: {exc}",
                "code":               "PROFORMA_PDF_FETCH_FAILED",
                "batch_id":           batch_id,
                "wfirma_proforma_id": wfirma_id,
            },
        )

    # Build a sensible filename. fullnumber may include slashes in wFirma
    # series notation (e.g. "PRO 12/2026") which are invalid on most
    # filesystems / Content-Disposition headers — sanitise to underscores.
    fullnumber = (draft.wfirma_proforma_fullnumber or "").strip()
    if fullnumber:
        safe = "".join(c if (c.isalnum() or c in "._- ") else "_"
                        for c in fullnumber)
        filename = f"{safe}.pdf"
    else:
        filename = f"proforma-{wfirma_id}.pdf"

    # Guard: wFirma sometimes returns an empty or near-empty response body
    # that passes the XML/base64 path but yields zero actual PDF content.
    # Treat < 200 bytes as a broken response — return 502 rather than serving
    # a blank PDF that appears to open but prints blank pages in the browser.
    if len(pdf_bytes) < 200:
        log.warning(
            "[%s/%s] proforma_document_pdf: suspiciously small PDF (%d bytes) "
            "for wfirma_id=%s — returning 502 instead of serving blank",
            batch_id, cn, len(pdf_bytes), wfirma_id,
        )
        raise HTTPException(
            status_code=502,
            detail={
                "error": (
                    f"wFirma returned an unusably small PDF ({len(pdf_bytes)} bytes) "
                    f"for proforma id={wfirma_id}. "
                    "Use the Atlas Print Preview (◫ Preview → ↓ Download PDF) as an alternative."
                ),
                "code": "PROFORMA_PDF_EMPTY",
                "wfirma_proforma_id": wfirma_id,
            },
        )

    log.info(
        "[%s/%s] proforma_document_pdf: served %d bytes for wfirma_id=%s",
        batch_id, cn, len(pdf_bytes), wfirma_id,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            # attachment: forces browser download rather than inline display.
            # Chrome's built-in inline PDF viewer can print blank pages for
            # some wFirma-generated PDFs. Forcing a download lets the OS native
            # PDF viewer handle print, which renders correctly.
            # Lesson G: regenerable/live-fetched artifacts MUST carry no-store.
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma":        "no-cache",
            "Expires":       "0",
        },
    )


# ── Service charges (operator-entered freight / insurance) ─────────────────

class _ServiceChargeIn(_BaseModel):
    charge_type: str
    amount:      float
    currency:    str
    note:        Optional[str] = ""


class _ServiceChargesReq(_BaseModel):
    charges: List[_ServiceChargeIn]


@router.get(
    "/service-charges/{batch_id}/{client_name:path}",
    dependencies=[_auth],
)
def get_service_charges(batch_id: str, client_name: str) -> JSONResponse:
    """List operator-entered service charges for (batch, client)."""
    cn = _validate_args(batch_id, client_name)
    from ..services import proforma_service_charges_db as _scdb
    return JSONResponse({
        "batch_id":    batch_id,
        "client_name": cn,
        "charges":     _scdb.list_charges(batch_id, cn),
    })


@router.post(
    "/service-charges/{batch_id}/{client_name:path}",
    dependencies=[_auth],
)
def set_service_charges(
    batch_id: str, client_name: str, body: _ServiceChargesReq,
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """
    Replace all freight/insurance charges for (batch, client).
    Idempotent. Each charge: {charge_type, amount, currency, note?}.
    Allowed types: freight, insurance.
    """
    cn = _validate_args(batch_id, client_name)
    from ..services import proforma_service_charges_db as _scdb
    operator = (x_operator or "").strip()
    try:
        result = _scdb.replace_all(
            batch_id    = batch_id,
            client_name = cn,
            charges     = [c.dict() for c in (body.charges or [])],
            created_by  = operator,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return JSONResponse({
        "ok":          True,
        "batch_id":    batch_id,
        "client_name": cn,
        "charges":     result,
    })


@router.delete(
    "/service-charges/{batch_id}/{client_name}/{charge_type}",
    dependencies=[_auth],
)
def delete_service_charge(
    batch_id: str, client_name: str, charge_type: str,
) -> JSONResponse:
    """Remove one service charge. 404 if not present."""
    cn = _validate_args(batch_id, client_name)
    from ..services import proforma_service_charges_db as _scdb
    if (charge_type or "").strip().lower() not in _scdb.ALLOWED_CHARGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"charge_type must be one of "
                   f"{sorted(_scdb.ALLOWED_CHARGE_TYPES)}",
        )
    deleted = _scdb.delete_charge(batch_id, cn, charge_type.lower())
    if not deleted:
        raise HTTPException(status_code=404,
                            detail="charge not found")
    return JSONResponse({"ok": True, "deleted": True,
                          "batch_id": batch_id, "client_name": cn,
                          "charge_type": charge_type.lower()})


# ── Proforma → final invoice conversion (manual two-step flow) ─────────────
#
# Strict operator-only conversion. No background path, no auto-conversion.
#
#   GET  /api/v1/proforma/to-invoice-preview/{batch_id}/{client_name}
#        Pure read: fetches the live wFirma proforma, parses it, builds a
#        FinalInvoicePlan, returns the planned XML + summary. Never calls
#        invoices/add. Never writes the link row.
#
#   POST /api/v1/proforma/to-invoice/{batch_id}/{client_name}
#        Live conversion. Requires ALL of:
#          • settings.wfirma_create_invoice_allowed  (env: WFIRMA_CREATE_INVOICE_ALLOWED)
#          • confirm token "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA"
#          • X-Operator header
#          • existing local proforma_drafts row with status='issued'
#          • no existing proforma_invoice_links row for this proforma_id
#        Then:
#          1. Re-fetch the live proforma XML from wFirma
#          2. Parse it via proforma_to_invoice.parse_proforma_xml
#          3. Build the final-invoice plan (preserves contractor_receiver
#             when present on the source proforma)
#          4. Optional Step-3-style receiver preflight via
#             wfirma_client.fetch_contractor_by_id
#          5. Insert pending link row (proforma_invoice_links — UNIQUE on
#             proforma_id is the duplicate-conversion guard)
#          6. POST invoices/add with the final-invoice XML
#          7. On success, mark the link row 'issued' with the new
#             wfirma_invoice_id + fullnumber

_FINAL_INVOICE_CONFIRM_TOKEN = "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA"

# ── Human approval boundary ───────────────────────────────────────────────────
# INVOICE_APPROVAL_REQUIRED is a sentinel that documents the human approval
# requirement. Any automated path that bypasses these checks is a bug.
# The three mandatory gates are:
#   1. WFIRMA_CREATE_INVOICE_ALLOWED env flag (ops kill-switch)
#   2. Explicit confirmation token in request body (prevents accidental calls)
#   3. X-Operator header (non-empty — ensures attribution)
#
# These are NEVER bypassed by shadow/live flags, background workers,
# webhooks, or retry loops. Invoice issuance is manual-only.
INVOICE_APPROVAL_REQUIRED = True


def _check_invoice_approval_gates(
    batch_id:    str,
    client_name: str,
    operator:    str,
    confirm:     str,
) -> Optional[JSONResponse]:
    """
    Centralised human-approval gate for invoice conversion.

    Returns a JSONResponse(ok=False, status='blocked') if any gate fails,
    or None if all gates pass.

    Gates checked (in order):
      1. WFIRMA_CREATE_INVOICE_ALLOWED env flag
      2. Confirmation token
      3. Non-empty X-Operator header

    Caller is responsible for firing the audit event on all paths.
    """
    if not settings.wfirma_create_invoice_allowed:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      client_name,
            "blocking_reasons": [
                "WFIRMA_CREATE_INVOICE_ALLOWED=false — flip the flag and "
                "restart to enable manual conversion"
            ],
        })
    if (confirm or "").strip() != _FINAL_INVOICE_CONFIRM_TOKEN:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      client_name,
            "blocking_reasons": [
                f"confirm token missing or wrong — must be "
                f"{_FINAL_INVOICE_CONFIRM_TOKEN!r}"
            ],
        })
    if not (operator or "").strip():
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      client_name,
            "blocking_reasons": ["X-Operator header is required"],
        })
    return None


def _proforma_link_db_path():
    return _proforma_db_path()


def _gather_conversion_inputs(batch_id: str, client_name: str
                                ) -> tuple[Optional[str], Optional[str]]:
    """Look up the local proforma draft for (batch, client). Returns
    ``(wfirma_proforma_id, error_reason)``. ``error_reason`` is set when
    the draft is missing or not in ``issued`` status."""
    cn = _validate_args(batch_id, client_name)
    draft = pildb.get_draft(_proforma_db_path(), batch_id, cn)
    if draft is None:
        return None, f"no local proforma_drafts row for {batch_id!r}/{cn!r}"
    if draft.status != "issued":
        return None, (
            f"draft status is {draft.status!r} — must be 'issued' to convert"
        )
    pid = (draft.wfirma_proforma_id or "").strip()
    if not pid:
        return None, "draft has no wfirma_proforma_id"
    return pid, None


def _link_already_exists(proforma_id: str) -> bool:
    """True if a proforma_invoice_links row already exists for this
    proforma_id (any status). Uses the canonical conversion link DB."""
    try:
        from ..services import proforma_invoice_link_db as plink
        from ..core.config import settings as _s
        # The proforma_invoice_links table lives in proforma_links.db
        # alongside proforma_drafts (init'd by main.py).
        link_db = _s.storage_root / "proforma_links.db"
        existing = plink.get_link_by_proforma(link_db, proforma_id)
        return existing is not None
    except Exception:
        return False


def _build_conversion_plan(proforma_id: str, *, operator: str
                             ) -> Dict[str, Any]:
    """Live-fetch the proforma, parse, build plan. Returns
    ``{"snap": ProformaSnapshot, "plan": FinalInvoicePlan,
       "plan_xml": str}`` or raises ``RuntimeError`` / ``ValueError``."""
    from ..services import proforma_to_invoice as p2i
    from ..core.timezone_utils import warsaw_today as _warsaw_today

    xml = wfirma_client.fetch_invoice_xml(proforma_id)
    snap = p2i.parse_proforma_xml(xml)
    # Default series id = preserve source proforma's series. Operator
    # may pass an override at execute time via the request body if
    # they need to change series (e.g. WDT vs proforma).
    # Fallback chain: proforma XML series → customer master preferred_invoice_series_id.
    series_id = (snap.series_id or "").strip()
    if not series_id or series_id == "0":
        _cm_inv = get_customer_master(_customer_master_db_path(), snap.contractor_id)
        series_id = pick_invoice_series_id(_cm_inv) or "" if _cm_inv else ""
    plan = p2i.build_final_invoice_plan(
        snap,
        final_series_id      = series_id or "0",   # validated below if "0"
        invoice_date         = _warsaw_today(),
        operator_description = "",
    )
    if not plan.series_id or plan.series_id == "0":
        raise ValueError(
            f"source proforma {snap.proforma_number!r} has no series id "
            "and no preferred_invoice_series_id in customer master "
            "— cannot infer final-invoice series. Operator must set "
            "series_id explicitly."
        )
    plan_xml = p2i.build_final_invoice_xml(plan)
    return {"snap": snap, "plan": plan, "plan_xml": plan_xml}


@router.get(
    "/to-invoice-preview/{batch_id}/{client_name:path}",
    dependencies=[_auth],
)
def proforma_to_invoice_preview(
    batch_id: str, client_name: str,
) -> JSONResponse:
    """
    Read-only preview of the Proforma → Invoice conversion plan.

    Returns the planned final-invoice XML + a structured summary. Never
    calls wFirma's invoices/add. Never writes proforma_invoice_links.

    Blocked when:
      • No local proforma_drafts row for (batch, client).
      • Draft is not in ``issued`` status.
      • Existing proforma_invoice_links row already converted this
        proforma to an invoice (avoids the operator clicking Convert
        on an already-converted Proforma).
    """
    cn = _validate_args(batch_id, client_name)
    pid, err = _gather_conversion_inputs(batch_id, cn)
    if err:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "blocking_reasons": [err],
        })
    if _link_already_exists(pid):
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "wfirma_proforma_id": pid,
            "blocking_reasons": [
                f"proforma_id {pid!r} already has a conversion link — "
                "refusing duplicate conversion"
            ],
        })

    # SINGLE READINESS AUTHORITY: conversion preview is blocked while the
    # underlying draft carries unresolved blocking reasons (intent="convert"
    # — same gate as approve/post, plus export prerequisites).
    _cvp_draft = pildb.get_draft(_proforma_db_path(), batch_id, cn)
    if _cvp_draft is not None:
        _cvp_ready = _derive_draft_readiness(_cvp_draft, intent="convert")
        if not _cvp_ready["ready"]:
            return JSONResponse({
                "ok":               False,
                "status":           "blocked",
                "batch_id":         batch_id,
                "client_name":      cn,
                "wfirma_proforma_id": pid,
                "blocking_reasons": _cvp_ready["blocking_reasons"],
                "blockers":         _cvp_ready["blockers"],
                "readiness_intent": "convert",
            })

    from ..services import proforma_to_invoice as p2i_module
    try:
        plan_data = _build_conversion_plan(pid, operator="")
    except p2i_module.ZeroBillableInvoice as exc:
        # #532: preview surfaces the same zero-billable block as execute, so
        # the operator sees the blocker before clicking Convert.
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "wfirma_proforma_id": pid,
            "blocking_reasons": [str(exc)],
            "repair_action":    (
                "Price the proforma lines from the sales packing list "
                "(import-sales-prices) before converting to an invoice."
            ),
        })
    except Exception as exc:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "wfirma_proforma_id": pid,
            "blocking_reasons": [
                f"plan build failed: {type(exc).__name__}: {exc}"
            ],
        })

    snap = plan_data["snap"]
    plan = plan_data["plan"]
    return JSONResponse({
        "ok":                  True,
        "status":              "preview",
        "batch_id":            batch_id,
        "client_name":         cn,
        "wfirma_proforma_id":  pid,
        "summary": {
            "source_proforma_number":   snap.proforma_number,
            "source_proforma_total":    str(snap.total),
            "currency":                 snap.currency,
            "contractor_id":            plan.contractor_id,
            "contractor_receiver_id":   plan.contractor_receiver_id or "",
            "ship_to_preserved_from_proforma": bool(plan.contractor_receiver_id),
            "series_id":                plan.series_id,
            "line_count":               len(plan.contents),
            # #532 disclosure: lines dropped from the invoice because they were
            # priced at zero (packing_promote / non-revenue). A non-empty list
            # means the invoice intentionally shrank vs the proforma — never a
            # silent omission.
            "excluded_line_count":      len(plan.excluded_lines),
            "excluded_line_names":      [l.name for l in plan.excluded_lines],
            "expected_total":           str(plan.expected_total),
            "back_reference":           plan.description,
            "final_date":               plan.date,
            # Canonical wording for any insurance lines in the conversion plan.
            # Empty list means no insurance line in this proforma.
            "insurance_line_names": [
                l.name for l in plan.contents
                if "insurance" in l.name.lower()
                   or "ubezpieczenie" in l.name.lower()
            ],
        },
        "plan_xml":            plan_data["plan_xml"],
        "warning": (
            "Manual final invoice action. Confirming will create a real "
            "wFirma invoice and write a Proforma→Invoice link."
        ),
    })


class _FinalInvoiceConfirmReq(_BaseModel):
    confirm:                str
    operator_description:   Optional[str] = ""
    final_series_id:        Optional[str] = ""   # if blank, copy source proforma series
    override_payment_method: Optional[str] = ""  # transfer|cash|card|compensation
    override_invoice_date:   Optional[str] = ""  # YYYY-MM-DD; overrides wFirma invoice issue date
    override_sale_date:      Optional[str] = ""  # YYYY-MM-DD; base for payment due calculation
    override_payment_days:   Optional[int] = None  # adds to sale_date (or invoice_date) → paymentdate


@router.post(
    "/to-invoice/{batch_id}/{client_name:path}",
    dependencies=[_auth],
)
def proforma_to_invoice(
    batch_id:    str,
    client_name: str,
    body:        _FinalInvoiceConfirmReq,
    x_operator:  Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """
    Convert an issued Proforma to a final wFirma invoice. Manual
    operator action — never auto-fired.

    Required:
      • settings.wfirma_create_invoice_allowed = true
      • body.confirm == "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA"
      • X-Operator header (non-empty)
      • Local proforma_drafts row in ``issued`` status
      • No existing proforma_invoice_links row for this proforma_id

    Flow (each step gates the next; stops on first failure):
      1. Validate gates.
      2. Look up local proforma_drafts → wfirma_proforma_id.
      3. Live-fetch the proforma XML from wFirma.
      4. Parse → build FinalInvoicePlan (preserves contractor_receiver).
      5. Insert pending link row (UNIQUE on proforma_id catches races).
      6. POST invoices/add with the planned XML.
      7. Mark link 'issued' with the new wfirma_invoice_id and number.
    """
    cn       = _validate_args(batch_id, client_name)
    operator = (x_operator or "").strip()

    # 1. Human approval gate (centralised — see INVOICE_APPROVAL_REQUIRED).
    # Fires audit attempt event on every path so the audit trail is complete.
    _gate_blocked = _check_invoice_approval_gates(
        batch_id=batch_id,
        client_name=cn,
        operator=operator,
        confirm=body.confirm or "",
    )
    if _gate_blocked is not None:
        # Extract the blocking reason for the audit event.
        try:
            _br = (_gate_blocked.body or b"").decode()
            import json as _j
            _br_text = "; ".join(_j.loads(_br).get("blocking_reasons", []))
        except Exception:
            _br_text = "gate blocked"
        try:
            from ..services.audit_persist import record_invoice_approval_attempt
            from ..core.config import settings as _s2
            record_invoice_approval_attempt(
                _s2.storage_root / "outputs" / batch_id / "audit.json",
                batch_id=batch_id,
                client_name=cn,
                wfirma_proforma_id="",
                operator=operator,
                outcome="blocked",
                blocking_reason=_br_text,
            )
        except Exception:
            pass
        return _gate_blocked

    # 2. Local draft lookup
    pid, err = _gather_conversion_inputs(batch_id, cn)
    if err:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "blocking_reasons": [err],
        })

    # 2b. Duplicate-conversion guard (pre-flight; UNIQUE catches races
    # at insert time too).
    if _link_already_exists(pid):
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "wfirma_proforma_id": pid,
            "blocking_reasons": [
                f"proforma_id {pid!r} already has a conversion link — "
                "refusing duplicate conversion"
            ],
        })

    # 2c. SINGLE READINESS AUTHORITY: an issued draft that has since gained
    # blockers (re-uploaded packing, customer-master change, unmapped
    # products) must not convert. Same gate as approve/post, intent="convert"
    # — blocks BEFORE the live wFirma fetch and BEFORE the link insert.
    _cv_draft = pildb.get_draft(_proforma_db_path(), batch_id, cn)
    if _cv_draft is not None:
        _cv_ready = _derive_draft_readiness(_cv_draft, intent="convert")
        if not _cv_ready["ready"]:
            _record_readiness_block(
                _proforma_db_path(), int(_cv_draft.id), _cv_ready, operator,
            )
            return JSONResponse({
                "ok":               False,
                "status":           "blocked",
                "batch_id":         batch_id,
                "client_name":      cn,
                "wfirma_proforma_id": pid,
                "blocking_reasons": _cv_ready["blocking_reasons"],
                "blockers":         _cv_ready["blockers"],
                "readiness_intent": "convert",
            })

    # 3+4. Fetch + parse + plan
    try:
        from ..services import proforma_to_invoice as p2i
        from ..services import proforma_invoice_link_db as plink
        from ..core.timezone_utils import warsaw_today as _warsaw_today

        proforma_xml = wfirma_client.fetch_invoice_xml(pid)
        snap = p2i.parse_proforma_xml(proforma_xml)
        # ADR-027 D6 — invoice series precedence (WF3):
        #   1. body.final_series_id (operator-chosen)  — wins if provided
        #   2. customer_master.preferred_invoice_series_id — SSOT
        #   3. empty → <series> omitted; wFirma contractor default applies
        # NOTE: snap.series_id (the proforma's own series) is intentionally
        # NOT in the fallback chain — a proforma series (e.g. "PROF/2026")
        # must not be reused for a final invoice.
        series_id = (body.final_series_id or "").strip()
        if not series_id or series_id == "0":
            _cm_inv2 = get_customer_master(_customer_master_db_path(), snap.contractor_id)
            series_id = (pick_invoice_series_id(_cm_inv2) or "") if _cm_inv2 else ""
        if series_id == "0":
            series_id = ""  # normalise wFirma sentinel to empty
        # series_id may now be empty → build_final_invoice_xml omits <series>
        # (wFirma contractor default applies). This is valid per ADR-027 D6 step 3.
        if not series_id:
            log.info(
                "[%s/%s] invoice convert: no series_id resolved; "
                "<series> will be omitted (wFirma contractor default)",
                batch_id, cn,
            )
        # Governance: passes silently for empty (step 3 = omit is valid);
        # raises only for literal "0" sentinel (invalid element).
        try:
            check_convert_series(series_id)
        except ValueError as exc:
            return JSONResponse({
                "ok":               False,
                "status":           "blocked",
                "batch_id":         batch_id,
                "client_name":      cn,
                "blocking_reasons": [str(exc)],
            })
        # Resolve operator payment overrides
        _ALLOWED_PM_EN = {"transfer", "cash", "card", "compensation"}
        _PM_EN_TO_WF   = {"transfer": "przelew", "cash": "gotowka",
                          "card": "karta", "compensation": "kompensata"}
        _override_method_en = (body.override_payment_method or "").strip().lower()
        if _override_method_en and _override_method_en not in _ALLOWED_PM_EN:
            return JSONResponse({
                "ok": False, "status": "blocked",
                "batch_id": batch_id, "client_name": cn,
                "blocking_reasons": [
                    f"override_payment_method '{_override_method_en}' not valid. "
                    f"Must be one of: transfer, cash, card, compensation."
                ],
            })
        _override_method_wf   = _PM_EN_TO_WF.get(_override_method_en) if _override_method_en else None
        _override_invoice_date = (body.override_invoice_date or "").strip() or None
        _override_sale_date   = (body.override_sale_date or "").strip() or None
        _override_days        = body.override_payment_days  # Optional[int]

        # Compute invoice_date and paymentdate from override fields
        from datetime import timedelta as _td, datetime as _dt
        _invoice_date = _warsaw_today()
        if _override_invoice_date:
            try:
                _invoice_date = _dt.fromisoformat(_override_invoice_date).date()
            except ValueError:
                pass
        # Payment due base: explicit sale date, else invoice date
        _payment_base = _invoice_date
        if _override_sale_date:
            try:
                _payment_base = _dt.fromisoformat(_override_sale_date).date()
            except ValueError:
                pass
        _paymentdate = None
        if _override_days is not None:
            _paymentdate = (_payment_base + _td(days=_override_days)).isoformat()

        # Build operator_description; append override annotations for audit trail
        _op_desc = (body.operator_description or "").strip()
        _audit_parts = []
        if _override_method_en:
            _audit_parts.append(f"payment_method={_override_method_en}")
        if _override_invoice_date:
            _audit_parts.append(f"invoice_date={_override_invoice_date}")
        if _override_sale_date:
            _audit_parts.append(f"sale_date={_override_sale_date}")
        if _override_days is not None:
            _audit_parts.append(f"payment_days={_override_days}")
        if _audit_parts:
            _op_desc = (_op_desc + " [override: " + ", ".join(_audit_parts) + "]").strip()

        plan = p2i.build_final_invoice_plan(
            snap,
            final_series_id      = series_id,
            invoice_date         = _invoice_date,
            paymentdate          = _paymentdate,
            paymentmethod        = _override_method_wf,
            operator_description = _op_desc,
        )
    except p2i.ZeroBillableInvoice as exc:
        # #532: every line priced at zero (packing_promote / non-revenue).
        # Block the invoice — never POST a zero-value document to wFirma.
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "wfirma_proforma_id": pid,
            "blocking_reasons": [str(exc)],
            "repair_action":    (
                "Price the proforma lines from the sales packing list "
                "(import-sales-prices) before converting to an invoice."
            ),
        })
    except Exception as exc:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "wfirma_proforma_id": pid,
            "blocking_reasons": [
                f"plan build failed: {type(exc).__name__}: {exc}"
            ],
        })

    # 4b. Optional receiver preflight (Step-3-style). Only fires when
    # the plan carries a contractor_receiver — guarantees that we never
    # POST a final invoice with a stale receiver id.
    rcv_id = (plan.contractor_receiver_id or "").strip()
    if rcv_id:
        try:
            rcv = wfirma_client.fetch_contractor_by_id(rcv_id)
        except Exception as exc:
            return JSONResponse({
                "ok":               False,
                "status":           "blocked",
                "batch_id":         batch_id,
                "client_name":      cn,
                "wfirma_proforma_id": pid,
                "blocking_reasons": [
                    f"receiver preflight failed: {type(exc).__name__}: {exc}"
                ],
            })
        if not rcv.ok:
            return JSONResponse({
                "ok":               False,
                "status":           "blocked",
                "batch_id":         batch_id,
                "client_name":      cn,
                "wfirma_proforma_id": pid,
                "blocking_reasons": [
                    f"receiver contractor id {rcv_id!r} not found in "
                    f"wFirma — {rcv.error or 'unavailable'}"
                ],
            })

    plan_xml = p2i.build_final_invoice_xml(plan)

    # 4c. Human approval audit — record the approved attempt BEFORE the
    # live wFirma call so the event appears even if invoices/add fails.
    try:
        from ..services.audit_persist import record_invoice_approval_attempt
        from ..core.config import settings as _s3
        record_invoice_approval_attempt(
            _s3.storage_root / "outputs" / batch_id / "audit.json",
            batch_id=batch_id,
            client_name=cn,
            wfirma_proforma_id=pid,
            operator=operator,
            outcome="approved",
        )
    except Exception:
        pass

    # 5. Insert pending link row (UNIQUE guard catches races).
    link_db = settings.storage_root / "proforma_links.db"
    pending = plink.ProformaInvoiceLink(
        proforma_id     = pid,
        proforma_number = snap.proforma_number,
        converted_at    = "",      # helper stamps if blank
        operator        = operator,
        source_total    = snap.total,
        currency        = snap.currency,
        status          = "pending",
    )
    try:
        plink.create_pending_link(link_db, pending)
    except plink.ProformaAlreadyConverted as exc:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "wfirma_proforma_id": pid,
            "blocking_reasons": [str(exc)],
        })

    # 6. Live wFirma invoices/add.
    try:
        http_status, response_text = wfirma_client._http_request(
            "POST", "invoices", "add", plan_xml,
        )
        if http_status >= 400:
            raise RuntimeError(
                f"invoices/add HTTP {http_status}: {response_text[:200]}"
            )
        code, desc = wfirma_client._parse_status(response_text)
        if code != "OK":
            raise RuntimeError(
                f"invoices/add wFirma status={code}: {desc}"
            )
        import xml.etree.ElementTree as _ET
        root = _ET.fromstring(response_text)
        node = root.find(".//invoice")
        if node is None:
            raise RuntimeError("invoices/add: no <invoice> in response")
        wfirma_inv_id  = (node.findtext("id") or "").strip()
        wfirma_inv_num = (
            node.findtext("fullnumber")
            or node.findtext("full_number")
            or node.findtext("number")
            or ""
        )
        if not wfirma_inv_id or not wfirma_inv_num:
            raise RuntimeError(
                f"invoices/add response missing id ({wfirma_inv_id!r}) "
                f"or fullnumber ({wfirma_inv_num!r})"
            )
    except Exception as exc:
        try:
            plink.mark_failed(link_db, pid,
                               notes=f"{type(exc).__name__}: {exc}"[:500])
        except Exception:
            pass
        return JSONResponse({
            "ok":               False,
            "status":           "failed",
            "batch_id":         batch_id,
            "client_name":      cn,
            "wfirma_proforma_id": pid,
            "error":            f"{type(exc).__name__}: {exc}",
        })

    # 6b. Verify-after-create: fetch the created invoice back from wFirma
    # and confirm it matches the source proforma's shape. This mirrors the
    # pattern in create_proforma_draft() but checks type, contractor,
    # line count, currency, total (within rounding), and receiver.
    # Failure here means the invoice EXISTS in wFirma but is malformed —
    # mark_failed so the operator knows to inspect manually.
    try:
        verify_xml = wfirma_client.fetch_invoice_xml(wfirma_inv_id)
        import xml.etree.ElementTree as _VET
        verify_root = _VET.fromstring(verify_xml)
        v_inv = verify_root.find(".//invoice")
        if v_inv is None:
            raise RuntimeError(
                f"verify-after-create: fetched invoice {wfirma_inv_id} "
                "but no <invoice> element in response"
            )

        # Check 1: invoice ID exists (already guaranteed by reaching here)
        v_id = (v_inv.findtext("id") or "").strip()
        if not v_id:
            raise RuntimeError(
                "verify-after-create: fetched invoice has empty <id>"
            )

        # Check 2: type is normal (not proforma)
        v_type = (v_inv.findtext("type") or "").strip().lower()
        if v_type not in ("normal", "vat"):
            raise RuntimeError(
                f"verify-after-create: expected type='normal' or 'vat', "
                f"got type={v_type!r} — wFirma may have created wrong document type"
            )

        # Check 3: contractor matches source proforma
        v_contractor_node = v_inv.find("contractor")
        v_contractor_id = (
            (v_contractor_node.findtext("id") or "").strip()
            if v_contractor_node is not None else ""
        )
        if v_contractor_id != plan.contractor_id:
            raise RuntimeError(
                f"verify-after-create: contractor mismatch — "
                f"expected={plan.contractor_id!r} got={v_contractor_id!r}"
            )

        # Check 4: line count matches source proforma
        v_lines = verify_root.findall(".//invoicecontent")
        expected_line_count = len(plan.contents)
        actual_line_count = len(v_lines)
        if actual_line_count != expected_line_count:
            raise RuntimeError(
                f"verify-after-create: line count mismatch — "
                f"expected={expected_line_count} persisted={actual_line_count} "
                f"(wFirma silently dropped lines)"
            )

        # Check 4b: per-line field verification (name, good_id, unit_count, price, vat)
        for idx, (expected_line, actual_el) in enumerate(
            zip(plan.contents, v_lines), start=1
        ):
            _a_name = (actual_el.findtext("name") or "").strip()
            _a_good_node = actual_el.find("good")
            _a_good_id = (
                (_a_good_node.findtext("id") or "").strip()
                if _a_good_node is not None else ""
            )
            _a_unit_count = (actual_el.findtext("unit_count") or "").strip()
            _a_price = (actual_el.findtext("price") or "").strip()
            _a_vat_node = actual_el.find("vat_code")
            _a_vat_id = (
                (_a_vat_node.findtext("id") or "").strip()
                if _a_vat_node is not None else ""
            )
            _mismatches = []
            if _a_name != expected_line.name:
                _mismatches.append(
                    f"name: expected={expected_line.name!r} got={_a_name!r}"
                )
            if _a_good_id != expected_line.good_id:
                _mismatches.append(
                    f"good_id: expected={expected_line.good_id!r} got={_a_good_id!r}"
                )
            if _a_unit_count != expected_line.unit_count:
                _mismatches.append(
                    f"unit_count: expected={expected_line.unit_count!r} got={_a_unit_count!r}"
                )
            if _a_price != expected_line.price:
                _mismatches.append(
                    f"price: expected={expected_line.price!r} got={_a_price!r}"
                )
            if _a_vat_id != expected_line.vat_code_id:
                _mismatches.append(
                    f"vat_code_id: expected={expected_line.vat_code_id!r} got={_a_vat_id!r}"
                )
            if _mismatches:
                raise RuntimeError(
                    f"verify-after-create: line {idx} field mismatch — "
                    + "; ".join(_mismatches)
                )

        # Check 5: currency matches
        v_currency = (v_inv.findtext("currency") or "").strip()
        if v_currency and v_currency != plan.currency:
            raise RuntimeError(
                f"verify-after-create: currency mismatch — "
                f"expected={plan.currency!r} got={v_currency!r}"
            )

        # Check 6: total matches within rounding tolerance (0.02)
        from decimal import Decimal as _D, InvalidOperation as _DI
        v_total_str = (v_inv.findtext("total") or "0").strip()
        try:
            v_total = _D(v_total_str)
        except _DI:
            v_total = _D("0")
        total_diff = abs(v_total - plan.expected_total)
        if total_diff > _D("0.02"):
            raise RuntimeError(
                f"verify-after-create: total mismatch beyond tolerance — "
                f"expected={plan.expected_total} got={v_total} "
                f"diff={total_diff} (tolerance=0.02)"
            )

        # Check 7: contractor_receiver preserved when present
        if plan.contractor_receiver_id:
            v_rcv_node = v_inv.find("contractor_receiver")
            v_rcv_id = (
                (v_rcv_node.findtext("id") or "").strip()
                if v_rcv_node is not None else ""
            )
            if v_rcv_id != plan.contractor_receiver_id:
                raise RuntimeError(
                    f"verify-after-create: contractor_receiver mismatch — "
                    f"expected={plan.contractor_receiver_id!r} "
                    f"got={v_rcv_id!r}"
                )

    except Exception as exc:
        _vac_note = f"verify-after-create FAILED: {type(exc).__name__}: {exc}"
        try:
            plink.mark_failed(link_db, pid, notes=_vac_note[:500])
        except Exception:
            pass
        # Audit: record the verification failure as a failed attempt.
        try:
            from ..services.audit_persist import record_invoice_approval_attempt
            from ..core.config import settings as _s4
            record_invoice_approval_attempt(
                _s4.storage_root / "outputs" / batch_id / "audit.json",
                batch_id=batch_id,
                client_name=cn,
                wfirma_proforma_id=pid,
                operator=operator,
                outcome="failed",
                blocking_reason=_vac_note[:500],
            )
        except Exception:
            pass
        return JSONResponse({
            "ok":               False,
            "status":           "failed",
            "batch_id":         batch_id,
            "client_name":      cn,
            "wfirma_proforma_id": pid,
            "wfirma_invoice_id": wfirma_inv_id,
            "error":            _vac_note[:500],
            "verify_after_create_failed": True,
        })

    # 7. Promote link to issued. The expected_total comes from wFirma's
    # own recalculation of the line items; we trust it as the canonical
    # value and store it alongside the source_total for audit.
    link_marked_issued = False
    try:
        plink.mark_issued(
            link_db, pid,
            invoice_id     = wfirma_inv_id,
            invoice_number = wfirma_inv_num,
            invoice_total  = plan.expected_total,
            notes          = (f"converted by {operator} from proforma "
                              f"{snap.proforma_number}")[:500],
        )
        link_marked_issued = True
    except Exception as exc:
        log.warning("[%s] proforma->invoice link mark_issued failed: %s",
                    batch_id, exc)

    # 8. Append-only audit hardening: emit a `proforma_converted_to_invoice`
    # timeline event so audit.json carries proof of the manual conversion.
    # Fires ONLY after the live invoice was created AND the link row was
    # marked issued. Never fires for blocked / failed paths or for the
    # rare case where mark_issued itself raised. Idempotent on
    # (batch_id, wfirma_proforma_id, wfirma_invoice_id).
    if link_marked_issued:
        try:
            from ..services.audit_persist import (
                record_proforma_converted_to_invoice,
            )
            from ..core.config import settings as _s
            _audit_path = (_s.storage_root / "outputs" / batch_id
                            / "audit.json")
            record_proforma_converted_to_invoice(
                _audit_path,
                batch_id           = batch_id,
                client_name        = cn,
                wfirma_proforma_id = pid,
                wfirma_invoice_id  = wfirma_inv_id,
                invoice_number     = wfirma_inv_num,
                operator           = operator,
                source             = "manual_convert_button",
            )
        except Exception as _exc:
            log.warning("[%s] convert audit append skipped: %s",
                        batch_id, _exc)

    return JSONResponse({
        "ok":                       True,
        "status":                   "issued",
        "batch_id":                 batch_id,
        "client_name":              cn,
        "wfirma_proforma_id":       pid,
        "wfirma_invoice_id":        wfirma_inv_id,
        "wfirma_invoice_number":    wfirma_inv_num,
        "currency":                 plan.currency,
        "expected_total":           str(plan.expected_total),
        "contractor_receiver_id":   plan.contractor_receiver_id or "",
        # #532 disclosure: zero-price (packing_promote / non-revenue) lines that
        # were excluded from this invoice. Empty in the normal case.
        "excluded_line_count":      len(plan.excluded_lines),
        "excluded_line_names":      [l.name for l in plan.excluded_lines],
        "operator":                 operator,
    })


# ── Phase 2 — read-only editable-draft endpoints ─────────────────────────────

def _line_count(editable_lines_json: str) -> int:
    """Return the number of editable lines for a draft, cheaply.

    Same source as _draft_to_full: parses d.editable_lines_json and takes
    len(). Returns 0 for null / empty string / malformed JSON — identical
    to the fallback _safe_loads(blob, []) used in the detail path.
    """
    try:
        v = json.loads(editable_lines_json or "[]")
        return len(v) if isinstance(v, list) else 0
    except Exception:
        return 0


def _draft_to_summary(d: "pildb.ProformaDraft") -> Dict[str, Any]:
    """Compact projection for the batch listing endpoint. Excludes the big
    JSON blobs so the listing stays cheap.

    Phase pipeline: includes posting lifecycle metadata so the dashboard
    can show post_failed errors, posting timestamps, and posted attribution
    without fetching the full draft payload.
    """
    # Surface a capped error hint when the draft is in post_failed state.
    # The notes field carries the error text written by mark_post_failed.
    notes_hint = ""
    if d.draft_state == "post_failed" and d.notes:
        notes_hint = (d.notes or "")[:300]

    return {
        "id":                         d.id,
        "batch_id":                   d.batch_id,
        "client_name":                d.client_name,
        "draft_state":                d.draft_state,
        "draft_version":              d.draft_version,
        "currency":                   d.currency,
        "wfirma_proforma_id":         d.wfirma_proforma_id,
        "wfirma_proforma_fullnumber": d.wfirma_proforma_fullnumber,
        "supersedes_draft_id":        d.supersedes_draft_id,
        "superseded_by_draft_id":     d.superseded_by_draft_id,
        "approved_at":                d.approved_at,
        "approved_by":                d.approved_by,
        "posted_at":                  d.posted_at,
        "posted_by":                  d.posted_by,
        "locked_at":                  d.locked_at,
        "posting_started_at":         d.posting_started_at,
        "posting_started_by":         d.posting_started_by,
        "post_failed_at":             d.post_failed_at,
        "error_hint":                 notes_hint,
        "created_at":                 d.created_at,
        "updated_at":                 d.updated_at,
        # Phase 6 — packing-upload auto-sync metadata
        "last_packing_sync_at":       d.last_packing_sync_at,
        "packing_sync_warning":       d.packing_sync_warning,
        # Sprint-24 clone provenance
        "clone_generation":           getattr(d, "clone_generation", 0),
        "source_ref_id":              getattr(d, "source_ref_id", None),
        # Sprint 1.1 — display-only line count for the Pro Forma list view.
        # Derived from editable_lines_json (same source as _draft_to_full).
        # Never mutates any customs value.
        "line_count":                 _line_count(d.editable_lines_json or ""),
    }


def _draft_to_full(d: "pildb.ProformaDraft") -> Dict[str, Any]:
    """Full editable payload — parses the JSON blobs into native lists/dicts
    so the dashboard can render without a second decode step."""
    def _safe_loads(blob: str, default):
        try:
            v = json.loads(blob or "")
        except Exception:
            return default
        return v if v is not None else default

    raw_lines = _safe_loads(d.editable_lines_json, [])
    if not isinstance(raw_lines, list):
        raw_lines = []
    # Phase 3 — every line surfaced to the dashboard carries a stable
    # line_id so PATCH-by-id is unambiguous. We do NOT persist this back
    # here (read-only projection); update_draft_line writes a normalised
    # copy on its own.
    editable_lines = pildb._ensure_line_ids(raw_lines)

    # PR 2C.2 — display-only flag: true when any line still has unit_price ≤ 0.
    # Signals to the dashboard that "Reset draft from packing" is needed to
    # carry through real EUR billing prices. No DB write; derived on read.
    needs_pricing_refresh = any(
        float(ln.get("unit_price", 0) or 0) <= 0
        for ln in editable_lines
    )

    return {
        **_draft_to_summary(d),
        "remarks":               d.remarks,
        "buyer_override":        _safe_loads(d.buyer_override_json,    {}),
        "ship_to_override":      _safe_loads(d.ship_to_override_json,  {}),
        "payment_terms":         _safe_loads(d.payment_terms_json,     {}),
        "editable_lines":        editable_lines,
        "service_charges":       _safe_loads(d.service_charges_json,   []),
        # Legacy/source-of-truth for the wFirma posting payload — kept for
        # debug/operator visibility. The editable fields above are what the
        # dashboard should edit; source_lines is read-only history.
        "source_lines":          _safe_loads(d.source_lines_json,      []),
        "notes":                 d.notes,
        "exchange_rate":         d.exchange_rate,
        "status_legacy":         d.status,
        # PR 2C.2 — read-only pricing health flag (no write, no mutation)
        "needs_pricing_refresh": needs_pricing_refresh,
    }


def _enrich_invoice_line_names(lines: List[Dict[str, Any]]) -> None:
    """Phase C — annotate each editable line with the customer-facing INVOICE
    line-name authority: the wFirma goods-registry name that actually prints on
    the proforma/invoice the customer receives.

    The generated wFirma proforma references each good by id, so the line name
    printed on the customer document is whatever ``<name>`` is stored in the
    wFirma goods registry (mirrored locally as ``wfirma_products.product_name``)
    — NOT the live ``description_engine`` canonical text and NOT ``name_pl``.
    Surfacing this single authority lets the Sales editor, the printable
    preview, and the generated invoice all render the SAME description (one
    authority, one renderer).

    Read-only projection. Never registers a product, never edits wFirma, never
    changes the stored name. Mutates each line dict in place, adding:

      ``invoice_line_name``        — the registered goods name (what prints), or
                                     '' when the product is not yet registered.
      ``invoice_line_name_source`` — 'wfirma_goods'        (registered → this is
                                     authoritative) or 'pending_registration'
                                     (no goods record yet — the name shown is the
                                     pending value that will be registered).
    """
    if not lines:
        return
    prod_index: Dict[str, Dict[str, Any]] = {}
    try:
        from ..services import wfirma_db as _wfdb_inv
        codes = sorted({
            str(ln.get("product_code") or "").strip()
            for ln in lines
            if str(ln.get("product_code") or "").strip()
        })
        if codes:
            prod_index = _wfdb_inv.get_products_batch(codes) or {}
    except Exception as exc:  # pragma: no cover - enrichment is best-effort
        log.warning("invoice line-name enrichment unavailable (non-fatal): %s", exc)
        prod_index = {}
    for ln in lines:
        pc = str(ln.get("product_code") or "").strip()
        inv_name = (str((prod_index.get(pc) or {}).get("product_name") or "")).strip()
        if inv_name:
            ln["invoice_line_name"] = inv_name
            ln["invoice_line_name_source"] = "wfirma_goods"
        else:
            ln["invoice_line_name"] = ""
            ln["invoice_line_name_source"] = "pending_registration"


# ── M6 — Cross-batch proforma search (read-only) ─────────────────────────────
# Authority: proforma_drafts table ONLY. No wFirma, no invoice ledger,
# no email, no mutation. Purely read-only index.


@router.get("/search", dependencies=[_auth])
def search_proforma_drafts(
    client_name: Optional[str] = None,
    batch_id: Optional[str] = None,
    wfirma_proforma_id: Optional[str] = None,
    wfirma_proforma_fullnumber: Optional[str] = None,
    draft_state: Optional[str] = None,
    currency: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 25,
) -> JSONResponse:
    """Cross-batch proforma draft search.

    M6 Prior Proforma Search — read-only. Returns matching drafts from
    the proforma_drafts table with pagination. Authority source is
    proforma_drafts ONLY — no wFirma API, no invoice ledger, no
    external queries.

    Does NOT: mutate state, post, send, convert, cancel, create, delete.
    """
    filters: Dict[str, Any] = {}
    if client_name:
        filters["client_name"] = client_name
    if batch_id:
        filters["batch_id"] = batch_id
    if wfirma_proforma_id:
        filters["wfirma_proforma_id"] = wfirma_proforma_id
    if wfirma_proforma_fullnumber:
        filters["wfirma_proforma_fullnumber"] = wfirma_proforma_fullnumber
    if draft_state:
        filters["draft_state"] = draft_state
    if currency:
        filters["currency"] = currency
    if date_from:
        filters["date_from"] = date_from
    if date_to:
        filters["date_to"] = date_to

    result = pildb.search_drafts(
        _proforma_db_path(),
        filters=filters,
        page=page,
        page_size=page_size,
    )

    return JSONResponse({
        "ok": True,
        "results": [_draft_to_search_result(d) for d in result["results"]],
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
        "filters": filters,
    })


def _draft_to_search_result(d: "pildb.ProformaDraft") -> Dict[str, Any]:
    """Compact projection for the cross-batch search endpoint.

    Returns only the fields needed for search result display —
    no JSON blobs, no posting metadata, no governance fields.
    """
    return {
        "id":                         d.id,
        "batch_id":                   d.batch_id,
        "client_name":                d.client_name,
        "draft_state":                d.draft_state,
        "status":                     d.status,
        "currency":                   d.currency,
        "wfirma_proforma_id":         d.wfirma_proforma_id,
        "wfirma_proforma_fullnumber": d.wfirma_proforma_fullnumber,
        "created_at":                 d.created_at,
        "updated_at":                 d.updated_at,
    }


@router.get("/drafts/{batch_id}", dependencies=[_auth])
def list_proforma_drafts(batch_id: str) -> JSONResponse:
    """List every editable Proforma Draft for *batch_id* (oldest first).

    Read-only. Returns a compact summary per draft (no JSON blobs).
    Empty list if the batch has no drafts. Never raises 404 — the
    operator may want to render an empty pane.
    """
    if not (batch_id or "").strip():
        raise HTTPException(status_code=400, detail="batch_id is required")
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="invalid batch_id")
    drafts = pildb.list_drafts_for_batch(_proforma_db_path(), batch_id)
    return JSONResponse({
        "ok":       True,
        "batch_id": batch_id,
        "drafts":   [_draft_to_summary(d) for d in drafts],
        "count":    len(drafts),
    })


@router.get("/draft/{draft_id}", dependencies=[_auth])
def get_proforma_draft(draft_id: int) -> JSONResponse:
    """Return the full editable payload for a single draft.

    Read-only. 404 if no draft with this id exists.

    Includes an additive ``customer_resolution`` block (PR — proforma UI
    usability) so the dashboard can surface customer-mapping status
    without a second roundtrip.  The block is the same shape that
    ``_resolve_customer`` returns for preview/post — read-only against
    the local ``wfirma_customers`` mirror.  Never calls the wFirma API.
    Failure to resolve returns a safe ``"none"`` shape; the GET never
    500s on resolver errors.
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    d = pildb.get_draft_by_id(_proforma_db_path(), int(draft_id))
    if d is None:
        raise HTTPException(status_code=404, detail=f"draft {draft_id} not found")
    full = _draft_to_full(d)
    # Customer resolution — defensive: failure must not 500 the GET.
    # Pass batch_id so per-document and per-batch packing-master paths
    # are used (strongest resolution). Enrich with Customer Master email
    # so the frontend can display it without a separate lookup.
    try:
        full["customer_resolution"] = _resolve_customer(
            d.client_name or "", batch_id=d.batch_id,
        )
        _enrich_customer_resolution_with_email(full["customer_resolution"])
    except Exception as exc:
        log.warning("draft %s customer_resolution failed (non-fatal): %s",
                    draft_id, exc)
        full["customer_resolution"] = {
            "raw_input":             d.client_name or "",
            "normalized_name":       "",
            "found":                 False,
            "ambiguous":             False,
            "match_strategy":        "none",
            "customer":              None,
            "wfirma_customer_id":    "",
            "resolved_wfirma_name":  "",
            "candidates":            [],
        }
    # Read-time enrichment — when a line's item_type / name_pl /
    # description_bilingual are blank/null, look them up from
    # product_descriptions and surface on the GET response.  NEVER
    # writes back; this is a pure projection so the operator UI
    # immediately sees the canonical bilingual block without having
    # to click Enrich.  Manual overrides (non-blank values already in
    # editable_lines_json) are preserved untouched.
    # PR-202: extend enrichment with a product_master fallback for
    # item_type ONLY (name_pl has no canonical source in product_master).
    # Operator-supplied values are still NEVER overwritten — the
    # `if not (ln.get(key) or "").strip()` guard applies to both the
    # product_descriptions read and the product_master fallback.
    pm_index: Dict[str, Dict[str, Any]] = {}
    try:
        from ..services import reservation_db as _rdb
        rdb_path = settings.storage_root / "reservation_queue.db"
        if rdb_path.exists():
            for pm in (_rdb.list_product_masters(rdb_path) or []):
                code = str(pm.get("product_code") or "").strip()
                if code and code not in pm_index:
                    pm_index[code] = pm
    except Exception as exc:
        log.warning("draft %s product_master fallback unavailable "
                    "(non-fatal): %s", draft_id, exc)
    try:
        for ln in (full.get("editable_lines") or []):
            pc = str(ln.get("product_code") or "").strip()
            if not pc:
                continue
            row = ddb.get_product_description(pc) or {}
            if row:
                if not (ln.get("item_type") or "").strip():
                    v = (row.get("item_type") or "").strip()
                    if v:
                        ln["item_type"] = v
                if not (ln.get("name_pl") or "").strip():
                    v = (row.get("name_pl") or "").strip()
                    if v:
                        ln["name_pl"] = v
                if not (ln.get("description_bilingual") or "").strip():
                    v = ((row.get("description_bilingual") or "").strip()
                         or (row.get("description_block") or "").strip())
                    if v:
                        ln["description_bilingual"] = v
            # product_master fallback — item_type only.  Never aliases
            # design_no as product_code; never invents product_code.
            if not (ln.get("item_type") or "").strip():
                pm = pm_index.get(pc)
                if pm:
                    v = (pm.get("item_type") or "").strip()
                    if v:
                        ln["item_type"] = v
    except Exception as exc:
        log.warning("draft %s read-time enrichment failed (non-fatal): %s",
                    draft_id, exc)
    # Phase C — annotate each line with the customer-facing invoice line-name
    # authority (wFirma goods name) so the editor shows what will actually
    # print, matching the preview and the generated invoice.
    _enrich_invoice_line_names(full.get("editable_lines") or [])
    return JSONResponse({
        "ok":    True,
        "draft": full,
    })


# ── Sprint-24: clone endpoint ─────────────────────────────────────────────────

@router.post("/draft/{draft_id}/clone", dependencies=[_auth])
def clone_proforma_draft(draft_id: int) -> JSONResponse:
    """Create a deep copy of a draft as a new unposted 'draft' row.

    Source draft is NEVER modified. Clone gets status=draft,
    draft_state=draft, wfirma_proforma_id=None. The new row is identified
    by clone_generation (≥1) and source_ref_id pointing to the source.

    Response: { ok, draft_id, source_id, clone_generation, draft: {...} }
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")

    src = pildb.get_draft_by_id(_proforma_db_path(), int(draft_id))
    if src is None:
        raise HTTPException(status_code=404, detail=f"draft {draft_id} not found")

    try:
        clone = pildb.clone_draft(_proforma_db_path(), int(draft_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        log.error("clone_proforma_draft: failed for source %s: %s", draft_id, exc)
        raise HTTPException(status_code=500, detail=f"Clone failed: {exc}") from exc

    full = _draft_to_full(clone)
    try:
        full["customer_resolution"] = _resolve_customer(
            clone.client_name or "", batch_id=clone.batch_id,
        )
        _enrich_customer_resolution_with_email(full["customer_resolution"])
    except Exception:
        full["customer_resolution"] = {"raw_input": clone.client_name or "",
                                       "found": False, "ambiguous": False}
    return JSONResponse({
        "ok":               True,
        "draft_id":         clone.id,
        "source_id":        draft_id,
        "clone_generation": clone.clone_generation,
        "draft":            full,
    })


# ── Service-product registry ─────────────────────────────────────────────────
# Canonical wFirma product mappings for freight / insurance service charges.
# These drive _build_service_charge_lines so that service charges are emitted
# as real wFirma line items on proformas and invoices.
#
# Registration flow:
#   1. Operator creates the product in wFirma (e.g., "Fracht" / "Ubezpieczenie").
#   2. Operator calls PUT /api/v1/proforma/service-products/{charge_type}
#      with the wFirma-issued product id.
#   3. From that point, every proforma/invoice with matching service charges
#      will include the charge as a line item in the wFirma XML.


@router.get("/service-products", dependencies=[_auth])
def get_service_products() -> JSONResponse:
    """Return the wFirma product mapping for each allowed service charge type.

    Read-only. Tells the operator which charge types are mapped (will be
    emitted as wFirma line items) vs unmapped (accounting-only, no line).

    Response::

        {
          "ok": true,
          "service_products": [
            {
              "charge_type":       "freight",
              "wfirma_product_id": "12345",   // null when not mapped
              "product_name":      "Fracht",
              "vat_rate":          "23",
              "unit":              "szt.",
              "status":            "mapped"   // "mapped" | "unmapped"
            },
            ...
          ]
        }
    """
    rows = []
    for ct in pildb.ALLOWED_SERVICE_CHARGE_TYPES:
        prod = wfdb.get_product(ct) if wfdb._db_path is not None else None
        good_id = (prod or {}).get("wfirma_product_id") or None
        rows.append({
            "charge_type":       ct,
            "wfirma_product_id": good_id,
            "product_name":      (prod or {}).get("product_name_pl") or (prod or {}).get("product_name") or "",
            "vat_rate":          (prod or {}).get("vat_rate") or "23",
            "unit":              (prod or {}).get("unit") or "szt.",
            "status":            "mapped" if good_id else "unmapped",
        })
    return JSONResponse({"ok": True, "service_products": rows})


class _ServiceProductBody(_BaseModel):
    wfirma_product_id: str
    product_name:      Optional[str] = ""
    vat_rate:          Optional[str] = "23"
    unit:              Optional[str] = "szt."


@router.put("/service-products/{charge_type}", dependencies=[_auth])
def register_service_product(
    charge_type: str,
    body:        _ServiceProductBody,
    x_operator:  Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Register or update the wFirma product mapping for a service charge type.

    The ``charge_type`` must be one of the canonical allowed types
    (``freight`` | ``insurance``).  The ``wfirma_product_id`` must be the
    numeric id of a product that already exists in wFirma.

    After registration, any proforma or invoice containing that charge type
    will emit it as a real wFirma line item (same currency as document,
    qty=1, unit_price=charge amount, vat_code = document-level vat context).

    Body::

        {
          "wfirma_product_id": "12345",
          "product_name":      "Fracht",   // optional display label
          "vat_rate":          "23",       // informational — wFirma's own VAT governs
          "unit":              "szt."
        }
    """
    ct = (charge_type or "").strip().lower()
    if ct not in pildb.ALLOWED_SERVICE_CHARGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"charge_type {ct!r} not allowed — must be one of "
                   f"{sorted(pildb.ALLOWED_SERVICE_CHARGE_TYPES)}",
        )
    pid = (body.wfirma_product_id or "").strip()
    if not pid:
        raise HTTPException(
            status_code=400,
            detail="wfirma_product_id is required and must be non-empty",
        )
    if wfdb._db_path is None:
        raise HTTPException(
            status_code=503,
            detail="wfirma_db not initialised — check storage_root",
        )
    wfdb.upsert_product(
        ct,
        wfirma_product_id = pid,
        product_name_pl   = (body.product_name or "").strip(),
        vat_rate          = (body.vat_rate or "23").strip(),
        unit              = (body.unit or "szt.").strip(),
        sync_status       = "mapped",
    )
    prod = wfdb.get_product(ct)
    return JSONResponse({
        "ok":               True,
        "charge_type":      ct,
        "wfirma_product_id": pid,
        "product_name":     (prod or {}).get("product_name_pl") or "",
        "vat_rate":         (prod or {}).get("vat_rate") or "23",
        "unit":             (prod or {}).get("unit") or "szt.",
        "status":           "mapped",
        "operator":         x_operator or "",
    })


@router.get("/product-options", dependencies=[_auth])
def list_proforma_product_options() -> JSONResponse:
    """Return the local product-master option list for the Add-line
    selector in the proforma draft UI.

    Read-only.  Reads ``product_descriptions`` (canonical bilingual
    name/item_type per product_code) and joins with ``product_master``
    (canonical identity registry) when present.  Never calls the
    wFirma API; never writes any local row.

    Response shape::

        {
          "ok":    true,
          "count": int,
          "options": [
            {
              "product_code": str,
              "item_type":    str,    # may be ""
              "name_pl":      str,    # may be ""
              "design_no":    str,    # may be "" (from product_master)
            },
            ...
          ]
        }
    """
    options: List[Dict[str, Any]] = []
    seen: set = set()
    # Read product_descriptions directly — no helper in document_db today
    # and adding one is out of scope for this PR.  Read-only SELECT.
    try:
        import sqlite3 as _sql
        docs_path = settings.storage_root / "documents.db"
        if docs_path.exists():
            with _sql.connect(str(docs_path)) as con:
                con.row_factory = _sql.Row
                for r in con.execute(
                    "SELECT product_code, item_type, name_pl "
                    "FROM product_descriptions "
                    "WHERE product_code<>'' "
                    "ORDER BY product_code"
                ).fetchall():
                    pc = (r["product_code"] or "").strip()
                    if not pc or pc in seen:
                        continue
                    seen.add(pc)
                    options.append({
                        "product_code": pc,
                        "item_type":    (r["item_type"] or "").strip(),
                        "name_pl":      (r["name_pl"] or "").strip(),
                        "design_no":    "",
                    })
    except Exception as exc:
        log.warning("product-options: product_descriptions read failed "
                    "(non-fatal): %s", exc)
    # Augment with design_no from product_master where available.
    try:
        from ..core.config import settings as _s
        from ..services import reservation_db as _rdb
        rdb_path = _s.storage_root / "reservation_queue.db"
        if rdb_path.exists():
            pm_rows = _rdb.list_product_masters(rdb_path) or []
            pm_by_code = {(r.get("product_code") or "").strip(): r
                          for r in pm_rows
                          if (r.get("product_code") or "").strip()}
            for opt in options:
                pm = pm_by_code.get(opt["product_code"])
                if pm:
                    opt["design_no"] = (pm.get("design_no") or "").strip()
            # Include any product_master codes missing from
            # product_descriptions so the operator can still pick them.
            for pc, pm in pm_by_code.items():
                if pc in seen:
                    continue
                seen.add(pc)
                options.append({
                    "product_code": pc,
                    "item_type":    "",
                    "name_pl":      "",
                    "design_no":    (pm.get("design_no") or "").strip(),
                })
    except Exception as exc:
        log.warning("product-options: product_master read failed "
                    "(non-fatal): %s", exc)
    options.sort(key=lambda o: o["product_code"])
    return JSONResponse({"ok": True, "count": len(options),
                         "options": options})


@router.get("/draft/{draft_id}/preview.html", dependencies=[_auth])
def get_proforma_draft_preview_html(draft_id: int) -> HTMLResponse:
    """Render a human-readable HTML preview of a proforma draft.

    Read-only.  Builds a printable invoice-style HTML snapshot of the
    current ``editable_lines`` + customer_resolution + service charges
    + buyer/ship-to/payment terms.  Operator can browser-print this
    surface to PDF.  Never calls wFirma; never modifies any local row.

    This endpoint is the human-readable counterpart to the JSON
    payload returned by ``POST /preview/{batch_id}/{client_name}``
    (which stays available for debugging / programmatic audit).
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    d = pildb.get_draft_by_id(_proforma_db_path(), int(draft_id))
    if d is None:
        raise HTTPException(status_code=404, detail=f"draft {draft_id} not found")

    from html import escape as _esc
    import json as _json
    import datetime as _dt
    from pathlib import Path as _Path

    def _safe(s) -> str:
        return _esc(str(s)) if s is not None else ""

    # ── Company profile (read-only; missing → banner) ─────────────────────────
    _master_db = settings.storage_root / "master_data.sqlite"
    try:
        company_profile = get_company_profile(_master_db)
    except Exception:
        company_profile = None

    # ── Audit.json read-through (read-only; never raises) ─────────────────────
    _audit_awb = "—"
    _audit_carrier = "—"
    _audit_clearance_path = "—"
    try:
        _audit_path = settings.storage_root / "outputs" / (d.batch_id or "") / "audit.json"
        if _audit_path.exists():
            with open(str(_audit_path), "r", encoding="utf-8") as _af:
                _audit_data = _json.load(_af)
            _audit_awb = _safe(_audit_data.get("awb") or "—")
            _audit_carrier = _safe(_audit_data.get("carrier") or "—")
            _cd = _audit_data.get("clearance_decision") or {}
            _audit_clearance_path = _safe(_cd.get("clearance_path") or "—")
    except Exception:
        pass  # leave defaults as "—"

    # Lines.
    try:
        lines = _json.loads(d.editable_lines_json or "[]") or []
    except Exception:
        lines = []
    # Phase C — annotate with the customer-facing invoice line-name authority
    # (wFirma goods name) so this printable preview matches the editor and the
    # generated invoice. Read-only.
    _enrich_invoice_line_names(lines)
    try:
        charges = _json.loads(d.service_charges_json or "[]") or []
    except Exception:
        charges = []
    try:
        buyer = _json.loads(d.buyer_override_json or "{}") or {}
    except Exception:
        buyer = {}
    try:
        ship_to = _json.loads(d.ship_to_override_json or "{}") or {}
    except Exception:
        ship_to = {}
    try:
        terms = _json.loads(d.payment_terms_json or "{}") or {}
    except Exception:
        terms = {}

    # Customer resolution (read-only; resolver failure → safe block).
    try:
        cust = _resolve_customer(d.client_name or "")
    except Exception:
        cust = {"wfirma_customer_id": "", "resolved_wfirma_name": "",
                "match_strategy": "none", "found": False}

    # ── VAT context label (document-level, same for all lines) ────────────────
    try:
        _cust_country = cust.get("country") or ""
        _cust_vat     = cust.get("vat_id") or ""
        _vat_decision = wfirma_client.decide_proforma_vat_context(
            _cust_country, _cust_vat
        )
        _vat_label = {
            "domestic": "23% VAT",
            "wdt":      "0% (WDT)",
            "export":   "0% (EXP)",
            "blocked":  "VAT TBD",
        }.get(_vat_decision.get("context", ""), "VAT TBD")
    except Exception:
        # Fallback: simple heuristic when decide_proforma_vat_context fails
        if (d.currency or "") == "EUR" and cust.get("wfirma_customer_id"):
            _vat_label = "0% (WDT/EXP)"
        else:
            _vat_label = "23% VAT"

    # Totals — additive only; no engine calls.
    def _num(x):
        try: return float(x or 0)
        except Exception: return 0.0
    lines_total = sum(_num(ln.get("qty")) * _num(ln.get("unit_price"))
                      for ln in lines)
    charges_total = sum(_num(c.get("amount")) for c in charges)
    grand_total = lines_total + charges_total

    # ── PLN reference total ────────────────────────────────────────────────────
    _pln_total_html = ""
    _fx_info_html   = ""
    try:
        _exr = float(d.exchange_rate or 0)
    except Exception:
        _exr = 0.0
    if _exr and _exr > 0:
        _pln_total = grand_total * _exr
        _pln_total_html = (
            f"<dt>PLN equivalent:</dt>"
            f"<dd>{_pln_total:.2f} PLN</dd>"
        )
        _fx_parts: List[str] = []
        if d.fx_rate_date:
            _fx_parts.append(f"Rate date: {_safe(d.fx_rate_date)}")
        if d.fx_rate_source:
            _fx_parts.append(f"Source: {_safe(d.fx_rate_source)}")
        if _fx_parts:
            _fx_info_html = (
                f"<dt style='font-size:10px;color:#888;'>"
                f"{' · '.join(_fx_parts)}</dt>"
                f"<dd></dd>"
            )

    def _bilingual_desc(ln) -> str:
        """Resolve the line description for the printable preview.

        Phase C — single authority: the customer-facing invoice prints the
        wFirma goods-registry name, so prefer ``invoice_line_name`` when the
        product is registered. This keeps the preview identical to the generated
        invoice. Fall back to the customs bilingual sentence only when the
        product is not yet registered (pending — no goods name exists yet), so
        the operator still sees a meaningful pending value.

        Format (fallback): "{Polish}. / {English}" — mirrors the wFirma layout.
        """
        inv = (ln.get("invoice_line_name") or "").strip()
        if inv and ln.get("invoice_line_name_source") == "wfirma_goods":
            return inv
        pl = (ln.get("description_pl") or ln.get("name_pl") or "").strip()
        en = (ln.get("description_en") or "").strip()
        if pl and en:
            return f"{pl} / {en}"
        return pl or en

    rows_html: List[str] = []
    for ln in lines:
        rows_html.append(
            "<tr>"
            f"<td>{_safe(ln.get('product_code'))}</td>"
            f"<td>{_safe(ln.get('item_type'))}</td>"
            f"<td style='max-width:340px;white-space:normal;'>"
            f"{_safe(_bilingual_desc(ln))}</td>"
            f"<td>{_safe(ln.get('design_no'))}</td>"
            f"<td>{_safe(ln.get('hs_code'))}</td>"
            f"<td>{_vat_label}</td>"
            f"<td class='num'>{_safe(ln.get('qty'))}</td>"
            f"<td class='num'>{_safe(ln.get('unit_price'))}</td>"
            f"<td>{_safe(ln.get('currency'))}</td>"
            f"<td class='num'>{_num(ln.get('qty')) * _num(ln.get('unit_price')):.2f}</td>"
            "</tr>"
        )
    charges_html: List[str] = []
    for c in charges:
        charges_html.append(
            "<tr>"
            f"<td>{_safe(c.get('charge_type'))}</td>"
            f"<td>{_safe(c.get('label'))}</td>"
            f"<td class='num'>{_safe(c.get('amount'))}</td>"
            f"<td>{_safe(c.get('currency'))}</td>"
            "</tr>"
        )

    def _addr_block(label: str, src: dict) -> str:
        if not src:
            return f"<div class='addr'><div class='addr-h'>{label}</div>" \
                   f"<div class='addr-empty'>— default —</div></div>"
        keys = ("name", "street", "city", "zip", "country",
                "vat_id", "phone", "email")
        items = "".join(
            f"<div>{_safe(src.get(k))}</div>"
            for k in keys if src.get(k)
        )
        return f"<div class='addr'><div class='addr-h'>{label}</div>{items}</div>"

    terms_html = ""
    if terms:
        terms_html = "<dl class='terms'>" + "".join(
            f"<dt>{_safe(k)}</dt><dd>{_safe(v)}</dd>"
            for k, v in terms.items()
        ) + "</dl>"
    else:
        terms_html = "<div class='terms-empty'>— default payment terms —</div>"

    cust_badge = ("✓ Matched" if cust.get("wfirma_customer_id")
                  else ("⚠ Ambiguous" if cust.get("ambiguous")
                        else "✗ Unmatched"))

    # ── Seller block HTML ──────────────────────────────────────────────────────
    if company_profile is None:
        _seller_html = (
            "<div style='background:#fde;color:#831;padding:8px 12px;"
            "border-radius:4px;font-size:12px;font-weight:700;'>"
            "Company profile not configured — go to Settings &gt; Company profile "
            "to add seller details."
            "</div>"
        )
        _bank_html = ""
    else:
        cp = company_profile
        _seller_lines: List[str] = []
        if cp.legal_name:
            _seller_lines.append(
                f"<div style='font-weight:700;'>{_safe(cp.legal_name)}</div>"
            )
        if cp.street:
            _seller_lines.append(f"<div>{_safe(cp.street)}</div>")
        if cp.postal_city:
            _seller_lines.append(f"<div>{_safe(cp.postal_city)}</div>")
        if cp.country:
            _seller_lines.append(f"<div>{_safe(cp.country)}</div>")
        if cp.nip:
            _seller_lines.append(f"<div>NIP: {_safe(cp.nip)}</div>")
        if cp.vat_eu:
            _seller_lines.append(f"<div>VAT-EU: {_safe(cp.vat_eu)}</div>")
        if cp.email:
            _seller_lines.append(f"<div>{_safe(cp.email)}</div>")
        if cp.phone:
            _seller_lines.append(f"<div>{_safe(cp.phone)}</div>")
        _seller_html = (
            "<div class='addr'>"
            "<div class='addr-h'>Seller</div>"
            + "".join(_seller_lines)
            + "</div>"
        )

        # Bank details — omit entire section if all fields are None
        _bank_fields = [
            ("IBAN EUR", cp.iban_eur),
            ("IBAN USD", cp.iban_usd),
            ("IBAN PLN", cp.iban_pln),
            ("SWIFT/BIC", cp.swift),
            ("Bank",      cp.bank_name),
        ]
        _bank_rows = [
            f"<div><span style='color:#888;min-width:72px;display:inline-block;'>"
            f"{_safe(lbl)}:</span> {_safe(val)}</div>"
            for lbl, val in _bank_fields if val
        ]
        if _bank_rows:
            _bank_html = (
                "<h2>Bank details</h2>"
                "<div class='addr'>"
                + "".join(_bank_rows)
                + "</div>"
            )
        else:
            _bank_html = ""

    # ── Document number header (draft vs posted) ───────────────────────────────
    _doc_number_html: str
    if getattr(d, "wfirma_proforma_fullnumber", None):
        _doc_number_html = (
            f"<div style='font-size:13px;font-weight:700;margin-bottom:4px;'>"
            f"Document: {_safe(d.wfirma_proforma_fullnumber)}"
            f"</div>"
        )
    else:
        _doc_number_html = (
            "<div style='display:inline-block;background:#fff3cd;"
            "color:#856404;padding:2px 8px;border-radius:3px;"
            "font-size:11px;font-weight:700;margin-bottom:4px;'>"
            "DRAFT — not yet posted"
            "</div>"
        )

    # ── Phase 3 — wFirma post-posting enrichment display ──────────────────────
    # When wFirma post-posting dates are absent (draft not yet posted, or
    # enrichment fetch not yet run), compute Payment Due By from
    # payment_terms_json["days"] so the operator sees the expected due date
    # even before the proforma is issued.
    _wfirma_dates_html = ""
    _issue_date   = getattr(d, "wfirma_issue_date", None)
    _payment_due  = getattr(d, "wfirma_payment_due", None)
    _pay_method   = getattr(d, "wfirma_payment_method", None)

    _due_estimated = False
    _pt_days_val   = 0
    # Enrich payment method from payment_terms_json when wFirma field is absent
    if not _pay_method and terms:
        _pay_method = str(terms.get("method") or "").strip() or None
    # Compute estimated payment due when wFirma hasn't stored it yet
    if not _payment_due and terms:
        try:
            _pt_days_val = int(terms.get("days") or 0)
            if _pt_days_val > 0:
                _base = (
                    _dt.date.fromisoformat(str(_issue_date)[:10])
                    if _issue_date
                    else _dt.date.today()
                )
                _payment_due  = (_base + _dt.timedelta(days=_pt_days_val)).isoformat()
                _due_estimated = True
        except Exception:
            pass

    if any((_issue_date, _payment_due, _pay_method)):
        _rows = []
        if _issue_date:
            _rows.append(f"<dt>Issue date:</dt><dd>{_safe(_issue_date)}</dd>")
        if _payment_due:
            _note = (
                f" <span style='font-size:10px;color:#888;font-style:italic;'>"
                f"(estimated — {_pt_days_val}-day terms)</span>"
                if _due_estimated else ""
            )
            _rows.append(
                f"<dt>Termin p&#322;atno&#347;ci / Payment due by:</dt>"
                f"<dd>{_safe(_payment_due)}{_note}</dd>"
            )
        if _pay_method:
            _rows.append(f"<dt>Payment method:</dt><dd>{_safe(_pay_method)}</dd>")
        _wfirma_dates_html = (
            "<dl class='terms' style='margin-top:6px;'>"
            + "".join(_rows)
            + "</dl>"
        )

    # ── Incoterm + insurance section ───────────────────────────────────────────
    _incoterm_val  = _safe(d.incoterm) if d.incoterm else "—"
    try:
        _ins_eur = float(d.insurance_eur)
        _insurance_val = f"{_ins_eur:.2f} EUR"
    except (TypeError, ValueError, AttributeError):
        _insurance_val = "—"

    html = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>Proforma draft #{d.id} — {_safe(d.client_name)}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif;
          max-width: 960px; margin: 18px auto; padding: 12px 24px;
          color: #1a1a1a; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  h2 {{ font-size: 13px; text-transform: uppercase;
        letter-spacing: 0.08em; color: #666;
        margin: 22px 0 6px; border-bottom: 1px solid #ddd;
        padding-bottom: 3px; }}
  .meta {{ color: #555; font-size: 12px; margin-bottom: 6px; }}
  .pill {{ display: inline-block; padding: 1px 6px; border-radius: 3px;
          font-size: 11px; font-weight: 700;
          background: #eef; color: #224; }}
  .pill.warn {{ background: #fde; color: #831; }}
  .pill.ok   {{ background: #dfd; color: #163; }}
  .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  .grid3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }}
  .addr {{ font-size: 12px; line-height: 1.4; }}
  .addr-h {{ font-size: 11px; text-transform: uppercase;
              letter-spacing: 0.08em; color: #888; margin-bottom: 4px; }}
  .addr-empty {{ color: #aaa; font-style: italic; font-size: 11px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th, td {{ padding: 5px 6px; border-bottom: 1px solid #eee;
            text-align: left; vertical-align: top; }}
  th {{ font-size: 10px; text-transform: uppercase;
        letter-spacing: 0.05em; color: #666; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .totals {{ margin-top: 12px; width: 360px; margin-left: auto;
              font-size: 12px; }}
  .totals dt {{ display: inline-block; width: 60%; }}
  .totals dd {{ display: inline-block; width: 40%; text-align: right;
                margin: 0; font-variant-numeric: tabular-nums; }}
  .totals .grand {{ font-weight: 700; font-size: 13px; margin-top: 4px;
                     padding-top: 4px; border-top: 1px solid #444; }}
  .footer {{ margin-top: 30px; font-size: 10px; color: #888;
              border-top: 1px solid #ddd; padding-top: 8px; }}
  .terms dt {{ display: inline-block; min-width: 80px;
                font-weight: 700; font-size: 11px; color: #555; }}
  .terms dd {{ display: inline; margin: 0; font-size: 12px; }}
  .terms dd:after {{ content: ""; display: block; }}
  .terms-empty {{ color: #aaa; font-style: italic; font-size: 11px; }}
  @media print {{
    body {{ margin: 0; }}
    .noprint {{ display: none; }}
  }}
</style>
</head><body>
  <div class="noprint" style="text-align:right;font-size:11px;color:#888;
                                margin-bottom:10px;">
    Read-only proforma draft preview · browser-print to PDF
  </div>
  <h1>Proforma DRAFT — {_safe(d.client_name)}</h1>
  {_doc_number_html}
  {_wfirma_dates_html}
  <div class="meta">
    Draft #{d.id} · v{d.draft_version} ·
    state <span class="pill">{_safe(d.draft_state)}</span> ·
    batch <code>{_safe(d.batch_id)}</code>
  </div>

  <h2>Seller</h2>
  {_seller_html}
  {_bank_html}

  <h2>Customer mapping</h2>
  <div style="font-size:12px;">
    <strong>Sales client:</strong> {_safe(d.client_name)}<br>
    <strong>wFirma customer:</strong>
      {_safe(cust.get('resolved_wfirma_name') or '—')}
      <code>{_safe(cust.get('wfirma_customer_id') or '—')}</code>
      <span class="pill {'ok' if cust.get('wfirma_customer_id') else 'warn'}">{cust_badge}</span>
      <span class="meta">match strategy: {_safe(cust.get('match_strategy'))}</span>
  </div>

  <h2>Buyer / Ship-to / Payment terms</h2>
  <div class="grid3">
    {_addr_block("Buyer override", buyer)}
    {_addr_block("Ship-to override", ship_to)}
    <div class="addr"><div class="addr-h">Payment terms</div>
      {terms_html}</div>
  </div>

  <h2>Shipment</h2>
  <div style="font-size:12px;">
    <div><span style="color:#888;min-width:110px;display:inline-block;">AWB:</span>
      {_audit_awb}</div>
    <div><span style="color:#888;min-width:110px;display:inline-block;">Carrier:</span>
      {_audit_carrier}</div>
    <div><span style="color:#888;min-width:110px;display:inline-block;">Clearance path:</span>
      {_audit_clearance_path}</div>
  </div>

  <h2>Shipment terms</h2>
  <div style="font-size:12px;">
    <div><span style="color:#888;min-width:110px;display:inline-block;">Incoterm:</span>
      {_incoterm_val}</div>
    <div><span style="color:#888;min-width:110px;display:inline-block;">Insurance declared:</span>
      {_insurance_val}</div>
  </div>

  <h2>Lines ({len(lines)})</h2>
  <table>
    <thead><tr>
      <th>Product code</th><th>Item type</th>
      <th>Description (PL / EN)</th>
      <th>Design</th><th>HS code</th><th>VAT</th>
      <th class="num">Qty</th>
      <th class="num">Unit price</th><th>Currency</th>
      <th class="num">Line total</th>
    </tr></thead>
    <tbody>{''.join(rows_html) or '<tr><td colspan="10" style="color:#aaa;text-align:center;">(no lines)</td></tr>'}</tbody>
  </table>

  <h2>Service charges ({len(charges)})</h2>
  <table>
    <thead><tr><th>Type</th><th>Label</th>
      <th class="num">Amount</th><th>Currency</th></tr></thead>
    <tbody>{''.join(charges_html) or '<tr><td colspan="4" style="color:#aaa;text-align:center;">(no charges)</td></tr>'}</tbody>
  </table>

  {('<h2>Remarks</h2><div style="font-size:12px;white-space:pre-wrap;">' + _safe(d.remarks) + '</div>') if d.remarks else ''}

  <div class="totals">
    <dl>
      <dt>Lines total:</dt><dd>{lines_total:.2f}</dd>
      <dt>Service charges:</dt><dd>{charges_total:.2f}</dd>
      <dt class="grand">Grand total:</dt><dd class="grand">{grand_total:.2f} {_safe(d.currency)}</dd>
      {_pln_total_html}
      {_fx_info_html}
    </dl>
  </div>

  <div class="footer">
    Generated locally from proforma_drafts row #{d.id} —
    no wFirma call was made.
    Updated {_safe(d.updated_at)}.
  </div>
</body></html>
"""
    return HTMLResponse(content=html)


@router.get("/draft/{draft_id}/events", dependencies=[_auth])
def get_proforma_draft_events(draft_id: int) -> JSONResponse:
    """Return the chronological event log for a draft.

    Read-only. 404 if no draft with this id exists. Empty ``events`` is
    valid (a draft created via a non-Phase-2 path may have no events).
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    d = pildb.get_draft_by_id(_proforma_db_path(), int(draft_id))
    if d is None:
        raise HTTPException(status_code=404, detail=f"draft {draft_id} not found")
    events = pildb.list_draft_events(_proforma_db_path(), int(draft_id))
    return JSONResponse({
        "ok":       True,
        "draft_id": int(draft_id),
        "events":   events,
        "count":    len(events),
    })


# ── Phase 3 — editable mutation endpoints ───────────────────────────────────
#
# All four write endpoints share:
#   - X-Operator header (required, non-empty)
#   - expected_updated_at (optimistic-lock; in body for PATCH/POST,
#     query param for DELETE)
#   - 404 when the draft id is unknown
#   - 409 on lock mismatch (DraftConflict) or non-editable state
#     (DraftNotEditable)
#   - 400 on validation failure
#   - response shape: {ok: True, draft: <full payload>}

def _require_operator(x_operator: Optional[str]) -> str:
    op = (x_operator or "").strip()
    if not op:
        raise HTTPException(
            status_code=400,
            detail="X-Operator header is required for draft mutations",
        )
    return op


def _draft_edit_dispatch(
    draft_id: int,
    operation,                     # callable: () -> ProformaDraft
) -> JSONResponse:
    """Run a draft mutation and translate domain errors → HTTP."""
    try:
        refreshed = operation()
    except pildb.DraftNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except pildb.DraftConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except pildb.DraftNotEditable as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return JSONResponse({
        "ok":    True,
        "draft": _draft_to_full(refreshed),
    })


@router.patch("/draft/{draft_id}", dependencies=[_auth])
def patch_proforma_draft(
    draft_id:  int,
    body:      Dict[str, Any],
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """PATCH the editable top-level fields of a draft.

    Body shape::

        {
          "expected_updated_at": "<iso-utc>",
          "patch": {"remarks": "...", "payment_terms": {...}, ...}
        }

    Allowed patch keys: remarks, buyer_override, ship_to_override,
    payment_terms, currency, exchange_rate.
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    operator = _require_operator(x_operator)
    expected = str(body.get("expected_updated_at") or "")
    patch    = body.get("patch") or {}
    # Governance check on top-level fields (currency, buyer/ship_to overrides).
    # No-op when proforma_draft_governance_enabled=False.
    try:
        check_top_patch(patch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _draft_edit_dispatch(draft_id, lambda: pildb.update_draft_fields(
        _proforma_db_path(),
        int(draft_id),
        patch,
        operator,
        expected,
    ))


@router.patch("/draft/{draft_id}/lines/{line_id}", dependencies=[_auth])
def patch_proforma_draft_line(
    draft_id:  int,
    line_id:   int,
    body:      Dict[str, Any],
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """PATCH a single editable line.

    Body::
        {"expected_updated_at": "...", "patch": {"qty": 3, "unit_price": 10.0}}
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    if not isinstance(line_id, int) or line_id <= 0:
        raise HTTPException(status_code=400, detail="invalid line_id")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    operator = _require_operator(x_operator)
    expected = str(body.get("expected_updated_at") or "")
    patch    = body.get("patch") or {}
    # Governance check on line fields (hs_code format, qty/unit_price sign).
    # No-op when proforma_draft_governance_enabled=False.
    try:
        check_line_patch(patch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _draft_edit_dispatch(draft_id, lambda: pildb.update_draft_line(
        _proforma_db_path(),
        int(draft_id), int(line_id),
        patch,
        operator,
        expected,
    ))


@router.post("/draft/{draft_id}/service-charges", dependencies=[_auth])
def post_proforma_draft_service_charge(
    draft_id:  int,
    body:      Dict[str, Any],
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Append a service charge.

    Body::
        {
          "expected_updated_at": "...",
          "charge": {"charge_type":"freight","amount":50,"currency":"EUR",
                     "label":"DHL fee"}
        }
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    operator = _require_operator(x_operator)
    expected = str(body.get("expected_updated_at") or "")
    charge   = body.get("charge") or {}
    return _draft_edit_dispatch(draft_id, lambda: pildb.add_draft_service_charge(
        _proforma_db_path(),
        int(draft_id),
        charge,
        operator,
        expected,
    ))


def _preflight_approve(db_path, draft_id: int):
    """Return error string if draft fails sales-price/description checks, else None."""
    import json as _json_pf
    draft = pildb.get_draft_by_id(db_path, draft_id)
    if draft is None:
        return None  # let approve_draft surface the 404
    lines = _json_pf.loads(draft.editable_lines_json or "[]")

    blank_desc = [
        ln.get("product_code", f"line_{i}")
        for i, ln in enumerate(lines)
        if not (ln.get("name_pl") or "").strip()
    ]
    if blank_desc:
        first_five = blank_desc[:5]
        return (
            f"Approval blocked: {len(blank_desc)} line(s) have blank commercial "
            f"description (name_pl). Import sales prices first. "
            f"First affected: {first_five}"
        )

    zero_price = [
        ln.get("product_code", f"line_{i}")
        for i, ln in enumerate(lines)
        if not (ln.get("unit_price") or 0)
    ]
    if zero_price:
        first_five = zero_price[:5]
        return (
            f"Approval blocked: {len(zero_price)} line(s) have zero/missing unit_price. "
            f"Import sales prices first. First affected: {first_five}"
        )

    # #529 — margin-mask guard. A priced line that still carries a cost-basis
    # price_source means the cost figure was never replaced with the sales
    # figure (import-sales-prices was not run, or ran before this stamp landed).
    # Invoicing at the cost price masks Estrella's margin. Only the two cost
    # labels are rejected; sales_packing_list, bulk_recovery, and manual sales
    # lines are accepted. The frozen valuation math is untouched — this asserts
    # provenance, it does not compute or alter any financial value.
    _COST_BASIS_LABELS = {"packing_xlsx_value", "packing_promote"}

    def _is_priced(ln) -> bool:
        # Defensive coercion: a malformed/non-numeric unit_price must not raise
        # (would 500 the readiness gate). Treat unparseable as "not priced" so
        # the zero_price guard above owns that case, mirroring its `or 0` safety.
        try:
            return float(ln.get("unit_price") or 0) > 0
        except (TypeError, ValueError):
            return False

    stale_cost = [
        ln.get("product_code", f"line_{i}")
        for i, ln in enumerate(lines)
        if _is_priced(ln)
        and (ln.get("price_source") or "") in _COST_BASIS_LABELS
    ]
    if stale_cost:
        first_five = stale_cost[:5]
        return (
            f"Approval blocked: {len(stale_cost)} priced line(s) still carry a "
            f"cost-basis price_source (packing_xlsx_value/packing_promote) — the "
            f"sales margin would be masked at invoice. Re-import sales prices so "
            f"every priced line is labelled sales_packing_list. "
            f"First affected: {first_five}"
        )

    authority = draft.sales_price_authority_total_eur
    if authority is not None:
        line_total = sum(
            float(ln.get("total_eur") or ln.get("net") or 0)
            for ln in lines
        )
        diff = abs(line_total - float(authority))
        if diff > 0.05:
            return (
                f"Approval blocked: draft total {line_total:.2f} EUR differs from "
                f"sales-packing authority {authority:.2f} EUR by {diff:.2f} EUR "
                f"(tolerance 0.05). Reimport or correct lines."
            )

    return None


# ── SINGLE READINESS AUTHORITY (split-authority fix, 2026-06-12) ────────────
# Root cause of "Approved + Blocking Reasons" (drafts #32/#33): four readiness
# definitions existed — _build_preview (display only), _preflight_approve
# (approve route), inline checks in _build_proforma_request_from_draft (post
# route), and frontend draftState gating. _derive_draft_readiness composes
# them into ONE authority consulted by approve, post, and convert. The
# frontend reads it via GET /draft/{id}/readiness — it reflects truth, it
# does not produce it (Lesson F rule 5).

_READINESS_INTENTS = ("approve", "post", "convert")


def _repair_hint_for_blocker(reason: str) -> str:
    """Map a blocking reason to the exact operator repair action (Lesson M:
    blocked state must display the repair path, never just 'blocked')."""
    r = (reason or "").lower()
    if "maps to multiple product_codes" in r:
        return ("Select the exact product_code for this design_no via "
                "POST /api/v1/proforma/draft/{draft_id}/resolve-ambiguity "
                "(or the 'Resolve product' action on the draft page).")
    if "wfirma_product" in r or "wfirma_products" in r:
        return ("Register the listed products in wFirma and add the "
                "wfirma_product_id mapping to wfirma_products, then re-check "
                "readiness.")
    if "vat_mode" in r:
        return "Correct customer_master.vat_mode (unknown integer mapping)."
    if "eu vat" in r or "vat_eu" in r or "vies" in r or "vat decision" in r \
            or "vat context" in r:
        return ("Add the buyer's EU VAT number to Customer Master (verify "
                "via VIES). Do NOT change vat_mode to bypass missing VAT "
                "data.")
    if "customer" in r or "kontrahent" in r or "contractor" in r:
        return ("Fix the customer mapping in wfirma_customers / Customer "
                "Master for this client, then re-check readiness.")
    if "unit_price" in r or "sales price" in r or "name_pl" in r \
            or "packing" in r or "authority" in r:
        return ("Import/refresh sales prices from the sales packing list so "
                "every line has name_pl + unit_price and totals match the "
                "sales-packing authority.")
    if "stock" in r or "reservation" in r or "warehouse" in r:
        return "Resolve warehouse stock/reservation state for the affected lines."
    if "pz" in r or "export" in r or "customs" in r:
        return "Complete the wFirma PZ / export prerequisites for this batch first."
    return "Resolve this blocker, then re-run readiness."


def _eu_vat_candidate_from_master(cm: Any) -> Optional[Dict[str, str]]:
    """Surface an on-file ``nip`` as a confirm-and-save EU-VAT CANDIDATE.

    Context: the customer's canonical EU-VAT field is ``vat_eu_number`` (paired
    with ``vat_eu_valid`` for VIES). The general tax-id field ``nip`` sometimes
    already holds the EU VAT (e.g. an HU buyer stored as ``nip='HU32207880'``),
    while ``vat_eu_number`` is left blank. When that happens the WDT gate blocks
    for a "blank" VAT that is, to the operator, plainly on file — an authority
    mismatch between what is stored and what the gate reads.

    This returns the ``nip`` as a candidate ONLY when it is formatted as this EU
    country's VAT (ISO-country prefix). It is deliberately conservative:

      * It NEVER makes the customer WDT-eligible by itself. The readiness gate
        still blocks until ``vat_eu_number`` is explicitly populated. This only
        powers the operator's "save to Customer Master" action and the
        authority-honest blocker wording — there is no silent nip→EU-VAT
        acceptance (WDT is tax-sensitive; see safety gate).
      * A bare domestic tax id (no country prefix) is NOT offered, so we never
        assert EU-VAT eligibility from the wrong kind of number.

    Returns ``{"candidate_vat", "candidate_source"}`` or ``None``.
    """
    from ..models.vat_resolver import EU_COUNTRIES  # noqa: PLC0415
    country = (getattr(cm, "country", None)       or "").strip().upper()
    vat_eu  = (getattr(cm, "vat_eu_number", None) or "").strip()
    nip     = (getattr(cm, "nip", None)           or "").strip()
    if vat_eu:                                   # canonical field already set
        return None
    if not country or country not in EU_COUNTRIES:
        return None
    if not nip:
        return None
    if nip.upper().replace(" ", "").startswith(country):
        return {"candidate_vat": nip, "candidate_source": "nip"}
    return None


# #684 billed-line ambiguity reconciliation and #686 over-bill analysis now live
# in the single canonical resolver (product_authority_resolver). They are
# re-exported here under their historical private names so the readiness gate
# and the existing tests are unchanged. See service/docs/adr/ADR-product-authority.md.
from ..services.cpa_product_service import (  # noqa: E402
    reconcile_billed_ambiguity as _reconcile_billed_ambiguity,
    analyze_product_code_billing as _analyze_product_code_billing,
)


def _derive_draft_readiness(
    draft: "pildb.ProformaDraft", *, intent: str,
) -> Dict[str, Any]:
    """THE single backend readiness gate for proforma draft lifecycle writes.

    Consulted by: approve (intent="approve"), post to wFirma (intent="post"),
    convert to invoice (intent="convert"), and the read-only
    ``GET /draft/{id}/readiness`` endpoint that drives frontend button state.

    Composition (every check fail-CLOSED — a derivation error is a blocker,
    never a silent pass):
      1. ``_build_preview`` blocking_reasons — design_no ambiguity, warehouse
         readiness, customer resolution, price conflicts. Export blockers
         (wFirma PZ prerequisite) additionally apply to post/convert.
      2. ``_preflight_approve`` — blank name_pl, zero unit_price,
         sales-packing authority mismatch.
      3. Missing wfirma_products mappings — exact product codes listed;
         blocks UNCONDITIONALLY (does NOT honour advisory_gates_enabled:
         silently skipping unresolved lines from the wFirma request is the
         defect this gate removes).
      4. WDT EU-VAT requirement — resolved VAT context "wdt" with a blank
         buyer vat_eu_number blocks BEFORE any wFirma call. Applies to the
         operator vat_mode override too: an override chooses the context,
         it never waives the legally required buyer VAT number.

    Returns ``{ready, intent, draft_id, draft_status, blockers:[{reason,
    repair_action}], blocking_reasons:[str], warnings:[str]}``.

    NEVER mutates draft state. (Known write-on-read: ``_build_preview``
    populates the design_product_mapping bridge — same governed side-effect
    the preview endpoint has carried since 2026-05-19.)
    """
    intent = (intent or "").strip().lower()
    if intent not in _READINESS_INTENTS:
        raise ValueError(
            f"unknown readiness intent {intent!r} — expected one of "
            f"{_READINESS_INTENTS}"
        )

    blockers: List[Dict[str, str]] = []
    warnings: List[str] = []
    _seen: set = set()
    # Structured WDT-VAT resolution data so the frontend can offer an explicit
    # "save EU VAT to Customer Master" action (never auto-applied). None unless
    # the WDT/nip-candidate case below is detected.
    _vat_resolution: Optional[Dict[str, Any]] = None

    def _add(reason: str, repair_action: str = "", authority: str = "PROFORMA") -> None:
        # Authority tagging (2026-06-22): every emitted blocker declares which
        # business authority owns it (PRODUCT / PROFORMA / IMPORT_PZ / WAREHOUSE /
        # SALES). Governance rule: a warning may not be promoted to a hard blocker
        # without an explicit business rule + regression test.
        key = (reason or "").strip()
        if not key or key in _seen:
            return
        _seen.add(key)
        blockers.append({
            "reason":        reason,
            "repair_action": repair_action or _repair_hint_for_blocker(reason),
            "authority":     authority,
        })

    def _advise(msg: str) -> None:
        """Surface an advisory (warning) — never blocks readiness."""
        m = (msg or "").strip()
        if m and m not in warnings:
            warnings.append(m)

    # ── 1. Comprehensive preview authority (ambiguity / warehouse / customer)
    preview: Dict[str, Any] = {}
    try:
        preview = _build_preview(
            draft.batch_id or "", draft.client_name or "",
            client_contractor_id=getattr(draft, "client_contractor_id", "") or "",
        )
    except HTTPException as exc:
        _add(f"readiness preview failed: {exc.detail}",
             "Fix the batch_id/client_name identifiers on the draft.")
    except Exception as exc:
        _add(f"readiness preview failed: {type(exc).__name__}: {exc}",
             "Inspect batch data — preview derivation must succeed before "
             "approve/post/convert (fail-closed).")
    # Draft lines loaded once here (product_code is the identity authority —
    # rule 6) so the ambiguity reconciliation below and the wfirma_products
    # check (section 3) share the same parsed lines.
    try:
        _r_lines = json.loads(draft.editable_lines_json or "[]") or []
    except Exception:
        _r_lines = []
        _add("editable_lines_json is not valid JSON — draft lines unreadable",
             "Reset the draft from the sales packing list.")

    # Reconcile batch-level design ambiguity against what is ACTUALLY billed.
    # The preview's "maps to multiple product_codes" blockers collapse design_no
    # across the whole batch (ignoring invoice context AND the product_code the
    # billed line already carries). A design only BLOCKS when a billed line on
    # this draft cannot be pinned to a valid product_code; a design no line bills
    # is a batch artifact (note, not a blocker). No product_code is ever guessed.
    _ambig_recon = _reconcile_billed_ambiguity(
        preview.get("ambiguous_design_codes") or {}, _r_lines)

    # The draft's billed product_codes — the billing authority (rule 6). Warehouse
    # / stock and wfirma_products blockers must be scoped to THESE codes, not the
    # client's whole sales packing list for the batch. The preview's blocking_reasons
    # count *design-lines* across the client's entire sales packing (e.g. 61 lines
    # for only 2 distinct billed product_codes), which inflates and mis-attributes
    # the gate to other drafts'/clients' pieces on the same shipment. So we SKIP the
    # client-wide design-ambiguity, wfirma_products, and per-state stock blockers
    # here and RE-DERIVE them draft-scoped: ambiguity below (billed-line product_code
    # authority), wfirma_products in section 3, and stock state in section 3b.
    _billed_pcs = {
        (str(ln.get("product_code") or "")).strip()
        for ln in _r_lines
        if (str(ln.get("product_code") or "")).strip()
    }
    _STOCK_STATE_MARKERS = (
        "still in PURCHASE_TRANSIT", "already in SALES_TRANSIT",
        "in CLOSED state", "no inventory_state row",
        "no scan_codes in packing_lines", "in unexpected state",
    )
    for reason in (preview.get("blocking_reasons") or []):
        _rs = str(reason)
        if "maps to multiple product_codes" in _rs:
            continue   # re-derived below with billed-line product_code authority
        if "not matched in wfirma_products" in _rs:
            continue   # section 3 re-derives this draft-scoped (distinct billed codes)
        if any(_m in _rs for _m in _STOCK_STATE_MARKERS):
            continue   # section 3b re-derives this draft-scoped (distinct billed codes)
        _add(_rs)
    for _amb_design, _amb_codes in _ambig_recon["genuinely_ambiguous"].items():
        _add(
            f"design_no {_amb_design!r} maps to multiple product_codes in this "
            f"batch: {_amb_codes} — clarify which line to bill"
        )
    for _nb_design in _ambig_recon["not_billed"]:
        warnings.append(
            f"design_no {_nb_design!r} has multiple candidate product_codes in "
            "the batch packing but no line on this draft bills it — batch "
            "artifact, not a billing blocker"
        )

    if intent in ("post", "convert"):
        for reason in (preview.get("export_blockers") or []):
            _add(str(reason),
                 "Complete the wFirma PZ / export prerequisites for this "
                 "batch first.")

    # ── 2. Draft-local approval preflight ─────────────────────────────────
    try:
        _pf_err = _preflight_approve(_proforma_db_path(), int(draft.id))
    except Exception as exc:
        _pf_err = (f"approval preflight failed: "
                   f"{type(exc).__name__}: {exc}")
    if _pf_err:
        _add(_pf_err)

    # ── 3. Missing wfirma_products mappings (unconditional block) ─────────
    # _r_lines was parsed once above (shared with the ambiguity reconciliation).
    _missing_codes: List[str] = []
    for _ln in _r_lines:
        _pc = (str(_ln.get("product_code") or "")).strip()
        try:
            _prod = (wfdb.get_product(_pc)
                     if (_pc and wfdb._db_path is not None) else None)
        except Exception:
            _prod = None
        if not ((_prod or {}).get("wfirma_product_id") or ""):
            _missing_codes.append(_pc or "<blank product_code>")
    if _missing_codes:
        _uniq = sorted(set(_missing_codes))
        _add(
            f"{len(_uniq)} product(s) not matched in wfirma_products "
            f"(missing wfirma_product_id): {', '.join(_uniq[:10])}"
            + ("…" if len(_uniq) > 10 else ""),
            "Register the listed products in wFirma and add the "
            "wfirma_product_id mapping to wfirma_products, then re-check "
            "readiness.",
        )

    # ── 3b. Warehouse / stock state, scoped to the draft's billed codes ───
    # Authority: PROFORMA (2026-06-22). Stock state is ADVISORY for a proforma —
    # a proforma may be issued before goods are received (business rule "Proforma
    # can be created without stock; inventory/PZ must not block proforma"). The
    # double-billing risk (committed / delivered pieces) is owned by the over-bill
    # fail-closed gate below (§7, billed_qty vs available_qty), which is the correct
    # quantity-risk authority. Stock-state counts here are emitted via `_advise`,
    # never `_add`, so they never block approve/post/convert. (Scoped to the
    # draft's DISTINCT billed product_codes — never the whole batch/client.)
    _DRAFT_STOCK_BLURB = {
        "purchase_transit": "still in PURCHASE_TRANSIT (not yet received in warehouse)",
        "sales_transit":    "already in SALES_TRANSIT (committed to another proforma/invoice)",
        "closed":           "in CLOSED state (already delivered)",
        "missing_state":    "have packing_lines scan_codes but no inventory_state row "
                            "— inventory_state_engine has not seeded this batch",
        "no_scan_codes":    "have no scan_codes in packing_lines for the resolved product_code",
    }
    _pc_stock: Dict[str, Any] = {}   # product_code -> (stock_ok, stock_status)
    for _pl in (preview.get("lines") or []):
        _plpc = (str(_pl.get("product_code") or "")).strip()
        if _plpc and _plpc not in _pc_stock:
            _pc_stock[_plpc] = (bool(_pl.get("stock_ok")),
                                str(_pl.get("stock_status") or ""))
    _stock_blocked_draft: Dict[str, int] = {}
    for _pc in sorted(_billed_pcs):
        _ok, _st = _pc_stock.get(_pc, (True, ""))
        if not _ok and _st:
            _stock_blocked_draft[_st] = _stock_blocked_draft.get(_st, 0) + 1
    for _st, _cnt in sorted(_stock_blocked_draft.items()):
        _blurb = _DRAFT_STOCK_BLURB.get(_st, f"in stock state {_st!r}")
        _advise(
            f"{_cnt} product(s) {_blurb} (advisory — stock does not block the proforma; "
            "double-billing is guarded by the over-bill quantity check)"
        )

    # ── 4. WDT EU-VAT requirement (requirement 6) ─────────────────────────
    try:
        _r_res = _resolve_customer(draft.client_name or "",
                                   batch_id=draft.batch_id)
        _r_contractor = (_r_res.get("wfirma_customer_id") or "").strip()
        _r_cm = (get_customer_master(_customer_master_db_path(), _r_contractor)
                 if _r_contractor else None)
        if _r_cm is not None:
            try:
                _r_vat = wfirma_client.resolve_vat_context_from_master(_r_cm)
            except ValueError as _r_ve:
                _r_vat = None
                _add(f"vat_mode resolution failed for "
                     f"{draft.client_name!r}: {_r_ve}")
            if _r_vat is not None:
                if _r_vat.get("blocked"):
                    _add("VAT context blocked: "
                         + str(_r_vat.get("blocked_reason") or "unknown"),
                         "Set the customer's country (and VAT data) in "
                         "Customer Master.")
                elif (_r_vat.get("context") or "") == "wdt":
                    _r_vat_eu = (getattr(_r_cm, "vat_eu_number", None)
                                 or "").strip()
                    if not _r_vat_eu:
                        # The gate authority is customer_master.vat_eu_number.
                        # If a nip is on file that is formatted as this EU
                        # country's VAT, surface it as a confirm-and-save
                        # candidate so the operator has an inline repair path —
                        # WITHOUT auto-accepting it (still blocks until saved).
                        _cand = _eu_vat_candidate_from_master(_r_cm)
                        if _cand:
                            _vat_resolution = {
                                "context":              "wdt",
                                "vat_eu_number":        "",
                                "candidate_vat":        _cand["candidate_vat"],
                                "candidate_source":     _cand["candidate_source"],
                                "contractor_id":        _r_contractor,
                                "needs_save_to_master": True,
                            }
                            _add(
                                "WDT (intra-EU 0%) requires the buyer's EU VAT "
                                "in Customer Master. Tax number "
                                f"{_cand['candidate_vat']!r} is on file (nip) "
                                "but the canonical vat_eu_number field is "
                                "blank — confirm it is the EU VAT and save it "
                                "to Customer Master.",
                                "Use 'Save EU VAT to Customer Master' to write "
                                f"{_cand['candidate_vat']} into vat_eu_number "
                                "(then VIES-verify). Do NOT change vat_mode to "
                                "bypass missing VAT data.",
                            )
                        else:
                            _add(
                                "WDT (intra-EU 0%) requires the buyer's EU VAT "
                                "number — customer master vat_eu_number is "
                                "blank",
                                "Add the buyer's EU VAT number to Customer "
                                "Master (verify via VIES). Do NOT change "
                                "vat_mode to bypass missing VAT data.",
                            )
                    elif getattr(_r_cm, "vat_eu_valid", None) is not True:
                        _vat_mode_override = (
                            _r_vat.get("decision_source") == "operator_vat_mode"
                        )
                        if getattr(_r_cm, "vat_eu_valid", None) is False:
                            if not _vat_mode_override:
                                # VIES confirmed INVALID, no operator override —
                                # block readiness: WDT 0% is not substantiated.
                                _add(
                                    "WDT blocked: VIES confirmed EU VAT number "
                                    f"{getattr(_r_cm, 'vat_eu_number', '') or ''!r} "
                                    "is INVALID — WDT 0% is not substantiated.",
                                    "Obtain a valid EU VAT number and re-run VIES "
                                    "validation "
                                    "(POST /api/v1/customer-master/{id}/validate-vat),"
                                    " or set vat_mode override to apply a different "
                                    "VAT treatment.",
                                )
                            else:
                                # VIES confirmed INVALID but vat_mode override is
                                # active — operator has explicitly chosen VAT
                                # treatment; advisory only, does not block.
                                warnings.append(
                                    "vies_invalid_override_active: VIES confirmed "
                                    "EU VAT number "
                                    f"{getattr(_r_cm, 'vat_eu_number', '') or ''!r} "
                                    "is INVALID, but operator vat_mode override is "
                                    "active — VAT treatment proceeds under operator "
                                    "authority. Verify the VAT number and re-run "
                                    "VIES when available. "
                                    "(advisory — does not block; D3 ADR-027)"
                                )
                        else:
                            warnings.append(
                                "vies_unverified: buyer vat_eu_number present "
                                "but VIES validity not confirmed (advisory — "
                                "does not block; D3 ADR-027)"
                            )
        elif _r_contractor:
            warnings.append(
                "no customer_master record for contractor "
                f"{_r_contractor!r} — VAT resolved via legacy fallback at "
                "post time"
            )
    except Exception as exc:
        # Customer-resolution failures are already preview blockers; a
        # readiness-internal VAT derivation crash still fails closed.
        _add(f"VAT readiness check failed: {type(exc).__name__}: {exc}",
             "Inspect customer master data for this client.")

    # ── 5. Duplicate / over-bill product_code guard (billing integrity) ────
    # product_code = one purchase invoice line (a lot that may hold several
    # designs/pieces). A product_code MAY be billed on multiple draft lines, but
    # only up to the available packing quantity (rule 2 — the packing-line
    # quantity is the split authority). Billing MORE than available is a
    # double-bill of a physical line → hard blocker (rule 4). Mere duplication
    # within the available quantity is legitimate (mixed lots) and does NOT
    # block; it is surfaced in the structured field for transparency. Never
    # auto-corrects or merges (rule 5).
    duplicate_product_codes: List[Dict[str, Any]] = []
    product_authority_available = True
    try:
        from ..services.cpa_product_service import (  # noqa: PLC0415
            authority_snapshot as _cpa_authority_snapshot,
        )
        _auth = _cpa_authority_snapshot(draft.batch_id or "")
        if not _auth.get("authority_available", True):
            # FAIL CLOSED (OQ-PR689-OVERBILL-FAILCLOSED): packing_lines authority
            # could not be READ — we cannot prove product_code validity, available
            # quantity, or over-bill status. Block approve/post/convert rather than
            # silently pass on an unprovable billing state. No fallback to
            # product_master (advisory only); no auto-correction.
            product_authority_available = False
            _add(
                "packing authority unavailable — cannot validate product "
                "identity or billed quantity ("
                + str(_auth.get("authority_error") or "packing_lines read failed")
                + ")",
                "Restore packing_lines read access for this batch (packing_db), "
                "then re-check readiness. Approve/post/convert stay blocked until "
                "product identity and billed quantity can be validated.",
            )
        else:
            duplicate_product_codes = _analyze_product_code_billing(
                _r_lines,
                _auth["available_by_product_code"],
                _auth["invoice_by_product_code"])
    except Exception as exc:
        # FAIL CLOSED: an unexpected failure evaluating the over-bill guard is a
        # HARD BLOCKER, not a warning — never approve/post/convert when the
        # billing-integrity check could not run.
        product_authority_available = False
        _add(
            "packing authority guard failed — cannot validate billed quantity "
            f"({type(exc).__name__}: {exc})",
            "Inspect the packing_lines read path; readiness stays blocked until "
            "the over-bill guard can run.",
        )
    for _dp in duplicate_product_codes:
        if _dp["over_billed"]:
            _designs = ", ".join(_dp["design_nos"][:6]) + (
                "…" if len(_dp["design_nos"]) > 6 else "")
            _add(
                f"product_code {_dp['product_code']!r} is billed "
                f"{_dp['billed_qty']:g} but only {_dp['available_qty']:g} "
                f"available in packing (invoice {_dp['invoice_no']}) — "
                f"over-billed across {_dp['line_count']} draft lines "
                f"[{_designs}]: confirm split-quantity or correct the sales lines",
                "Reduce the billed quantity to the available packing quantity, "
                "or fix the product_code on the duplicated sales lines. Do NOT "
                "auto-merge lines or silently pick one.",
            )

    # Structured ambiguity data so the frontend renders an exact product_code
    # selector — ONLY for designs a billed line cannot resolve (rule 6). Designs
    # already pinned by a billed line's product_code, or not billed at all, are
    # excluded here so the operator is not asked to re-resolve them.
    ambiguous_designs: Dict[str, Any] = dict(_ambig_recon["genuinely_ambiguous"])
    resolved_designs:  Dict[str, Any] = {}
    try:
        from ..services.design_product_bridge import populate_from_packing
        _bs = populate_from_packing(draft.batch_id or "")
        resolved_designs  = dict(_bs.get("resolved_design_codes") or {})
    except Exception as exc:
        warnings.append(f"design bridge summary unavailable: "
                        f"{type(exc).__name__}: {exc}")

    return {
        "ready":             not blockers,
        "intent":            intent,
        "draft_id":          int(draft.id),
        "draft_status":      draft.status,
        "blockers":          blockers,
        "blocking_reasons":  [b["reason"] for b in blockers],
        "warnings":          warnings,
        "ambiguous_designs": ambiguous_designs,
        "resolved_designs":  resolved_designs,
        "vat_resolution":    _vat_resolution,
        "duplicate_product_codes": duplicate_product_codes,
        "product_authority_available": product_authority_available,
    }


def _record_readiness_block(
    db_path, draft_id: int, readiness: Dict[str, Any], operator: str,
) -> None:
    """Append-only audit trail: a lifecycle write was refused by the
    readiness gate. Best-effort — never blocks the refusal response."""
    try:
        pildb._record_draft_event(
            db_path,
            draft_id    = int(draft_id),
            event       = "readiness_blocked",
            detail_json = json.dumps({
                "intent":           readiness.get("intent"),
                "blocking_reasons": readiness.get("blocking_reasons") or [],
            }, ensure_ascii=False),
            operator    = operator or "",
        )
    except Exception as exc:
        log.warning("[draft %s] readiness_blocked audit event failed "
                    "(non-fatal): %s", draft_id, exc)


@router.get("/draft/{draft_id}/readiness", dependencies=[_auth])
def get_draft_readiness(draft_id: int, intent: str = "approve") -> JSONResponse:
    """Read-only readiness for a draft, per intent (approve|post|convert).

    This is the SAME authority the approve/post/convert routes enforce —
    the frontend uses it to disable buttons with the exact reason +
    repair action (Lesson M). No state change. (Known write-on-read:
    design_product_mapping bridge population, as on /preview.)
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    _i = (intent or "").strip().lower()
    if _i not in _READINESS_INTENTS:
        raise HTTPException(
            status_code=400,
            detail=f"intent must be one of {list(_READINESS_INTENTS)}",
        )
    d = pildb.get_draft_by_id(_proforma_db_path(), int(draft_id))
    if d is None:
        raise HTTPException(status_code=404,
                            detail=f"draft {draft_id} not found")
    return JSONResponse({"ok": True, **_derive_draft_readiness(d, intent=_i)})


@router.post("/draft/{draft_id}/resolve-ambiguity", dependencies=[_auth])
def resolve_draft_design_ambiguity(
    draft_id:   int,
    body:       Dict[str, Any],
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Operator selects the exact product_code for an ambiguous design_no
    (requirement 4 of the readiness campaign).

    Body::
        {"design_no": "J4007R08118-0.6", "product_code": "EJL/26-27/257-2"}

    The selection is persisted batch-scoped in design_ambiguity_resolution
    (reservation_queue.db) and audited as a draft event. The chosen code
    must be a CURRENT candidate for the design in this batch — stale or
    invented codes are rejected. Resolution clears the ambiguity blocker in
    the readiness authority; it never edits draft lines, prices, or any
    posted document.
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    operator     = _require_operator(x_operator)
    design_no    = str(body.get("design_no") or "").strip()
    product_code = str(body.get("product_code") or "").strip()
    if not design_no or not product_code:
        raise HTTPException(
            status_code=400,
            detail="design_no and product_code are both required",
        )

    db = _proforma_db_path()
    draft = pildb.get_draft_by_id(db, int(draft_id))
    if draft is None:
        raise HTTPException(status_code=404,
                            detail=f"draft {draft_id} not found")
    if draft.status in ("posted", "cancelled", "superseded"):
        raise HTTPException(
            status_code=409,
            detail=f"draft {draft_id} is {draft.status!r} — ambiguity "
                   "resolution is only meaningful before posting",
        )

    from ..services.design_product_bridge import (
        populate_from_packing, record_ambiguity_resolution,
    )
    summary = populate_from_packing(draft.batch_id or "")
    _amb      = (summary.get("ambiguous_design_codes") or {}).get(design_no)
    _resolved = (summary.get("resolved_design_codes") or {}).get(design_no)
    candidates = list(_amb or (_resolved or {}).get("candidates") or [])
    if not candidates:
        raise HTTPException(
            status_code=400,
            detail=f"design_no {design_no!r} is not ambiguous in batch "
                   f"{draft.batch_id!r} — nothing to resolve",
        )
    if product_code not in candidates:
        raise HTTPException(
            status_code=400,
            detail=f"product_code {product_code!r} is not a candidate for "
                   f"design_no {design_no!r} in this batch — candidates: "
                   f"{candidates}",
        )

    rec = record_ambiguity_resolution(
        draft.batch_id or "", design_no, product_code, operator,
    )
    try:
        pildb._record_draft_event(
            db,
            draft_id    = int(draft_id),
            event       = "ambiguity_resolved",
            detail_json = json.dumps({
                "design_no":    design_no,
                "product_code": product_code,
                "candidates":   candidates,
                "batch_id":     draft.batch_id,
            }, ensure_ascii=False),
            operator    = operator,
        )
    except Exception as exc:
        log.warning("[draft %s] ambiguity_resolved audit event failed "
                    "(non-fatal): %s", draft_id, exc)

    return JSONResponse({
        "ok":         True,
        "resolution": rec,
        "readiness":  _derive_draft_readiness(draft, intent="approve"),
    })


# ── Phase 4 — lifecycle controls + line add/remove ─────────────────────────

@router.post("/draft/{draft_id}/approve", dependencies=[_auth])
def approve_proforma_draft(
    draft_id:  int,
    body:      Dict[str, Any],
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Lock a draft as ``approved``.

    Body::
        {
          "expected_updated_at": "...",
          "confirm_token": "YES_APPROVE_LOCAL_PROFORMA_DRAFT"
        }

    Allowed from: draft, editing, post_failed.
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    operator = _require_operator(x_operator)
    expected = str(body.get("expected_updated_at") or "")
    token    = str(body.get("confirm_token") or "")
    # SINGLE READINESS AUTHORITY: approve consults the same gate as post and
    # convert (includes _preflight_approve plus ambiguity / wfirma_products /
    # WDT-EU-VAT checks). A draft with unresolved blocking reasons can no
    # longer become Approved. Missing draft falls through so approve_draft
    # surfaces the canonical 404.
    _ap_db    = _proforma_db_path()
    _ap_draft = pildb.get_draft_by_id(_ap_db, int(draft_id))
    if _ap_draft is not None:
        _ap_ready = _derive_draft_readiness(_ap_draft, intent="approve")
        if not _ap_ready["ready"]:
            _record_readiness_block(_ap_db, int(draft_id), _ap_ready, operator)
            raise HTTPException(
                status_code=422,
                detail="Approval blocked by readiness gate: "
                       + " | ".join(_ap_ready["blocking_reasons"]),
            )
    return _draft_edit_dispatch(draft_id, lambda: pildb.approve_draft(
        _proforma_db_path(),
        int(draft_id),
        operator,
        expected,
        confirm_token=token,
    ))


@router.post("/draft/{draft_id}/re-open", dependencies=[_auth])
def reopen_proforma_draft(
    draft_id:  int,
    body:      Dict[str, Any],
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Move an approved draft back to ``editing``.

    Body::
        {
          "expected_updated_at": "...",
          "confirm_token": "YES_REOPEN_LOCAL_PROFORMA_DRAFT"
        }

    Allowed only from: approved.
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    operator = _require_operator(x_operator)
    expected = str(body.get("expected_updated_at") or "")
    token    = str(body.get("confirm_token") or "")
    return _draft_edit_dispatch(draft_id, lambda: pildb.reopen_draft(
        _proforma_db_path(),
        int(draft_id),
        operator,
        expected,
        confirm_token=token,
    ))




@router.post("/draft/{draft_id}/import-sales-prices", dependencies=[_auth])
def import_draft_sales_prices(
    draft_id:   int,
    body:       Dict[str, Any],
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Import sales-side prices and commercial descriptions from a TSV packing list.

    Body::
        {
          "expected_updated_at": "...",
          "tsv_text":            "<tab-separated EJL packing list>",
          "invoice_ref":         "EJL/26-27/244"    (optional, for audit)
        }

    Parses the TSV, validates the grand total, patches matching draft lines
    with sales unit_price, line total (EUR), and PL/EN descriptions.
    Auto-reopens an approved draft to editing before patching.
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    operator   = _require_operator(x_operator)
    expected   = str(body.get("expected_updated_at") or "")
    tsv_text   = str(body.get("tsv_text") or "")
    invoice_ref = str(body.get("invoice_ref") or "")

    if not tsv_text.strip():
        raise HTTPException(status_code=400, detail="tsv_text is required")

    import json as _json_imp
    rows, grand_total = parse_ejl_sales_packing(tsv_text)
    if not rows:
        raise HTTPException(status_code=422, detail="No data rows found in TSV")

    total_err = validate_grand_total(rows, grand_total)
    if total_err:
        raise HTTPException(status_code=422, detail=f"Grand total mismatch: {total_err}")

    # Sr-keyed lookup for precise 1:1 matching by draft line_id (= TSV Sr column)
    sr_lookup = {r.sr: r for r in rows}
    # Design-no fallback for formats without Sr tracking
    lookup = build_patch_lookup(rows)

    draft = pildb.get_draft_by_id(_proforma_db_path(), draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"draft {draft_id} not found")

    lines = _json_imp.loads(draft.editable_lines_json or "[]")
    matched, unmatched = 0, 0
    for ln in lines:
        # Prefer line_id → TSV Sr (exact 1:1 per-row match, correct per-variant pricing)
        line_id = ln.get("line_id")
        row = sr_lookup.get(int(line_id)) if line_id is not None else None
        if row is None:
            # Fallback: design_no / product_code / sku (first-occurrence only)
            key = (ln.get("design_no") or ln.get("product_code") or ln.get("sku") or "").strip()
            row = lookup.get(key)
        if row is None:
            unmatched += 1
            continue
        ln["unit_price"]   = float(row.unit_price)
        ln["total_eur"]    = float(row.line_total)
        ln["currency"]     = "EUR"
        # Authority: read customs-grade Polish description from product_descriptions;
        # never fabricate from TSV category codes (Lesson N / single-authority rule).
        _pc = str(ln.get("product_code") or "").strip()
        _pd_row = ddb.get_product_description(_pc) if _pc else None
        _pd_text = (
            (_pd_row or {}).get("description_pl")
            or (_pd_row or {}).get("name_pl")
            or ""
        ).strip()
        if _pd_text:
            ln["name_pl"] = _pd_text
        else:
            ln["name_pl"] = ""
            ln.setdefault("_warnings", []).append(
                f"Polish customs description missing for product_code={_pc!r}. "
                "Generate customs description package first. "
                "Proforma must not fabricate Polish description."
            )
        ln["remarks"]      = row.desc_en
        # #529 — stamp sales-price provenance. Before this, a line repriced from
        # the sales packing list still carried its cost-basis price_source
        # (packing_xlsx_value / packing_promote) from routes_packing.py:2327,
        # which masks the sales margin at invoice. The sales packing list is the
        # authority for the sales price, so label it as such.
        ln["price_source"] = "sales_packing_list"
        matched += 1

    authority_total = float(grand_total) if grand_total is not None else sum(
        float(r.line_total) for r in rows
    )

    refreshed = pildb.apply_sales_price_patch(
        _proforma_db_path(),
        draft_id,
        operator,
        expected,
        patched_lines=lines,
        sales_authority_total_eur=authority_total,
        sales_invoice_ref=invoice_ref,
    )

    return JSONResponse({
        "ok":               True,
        "rows_parsed":      len(rows),
        "lines_matched":    matched,
        "lines_unmatched":  unmatched,
        "grand_total_eur":  authority_total,
        "draft":            _draft_to_summary(refreshed),
    })


@router.post("/draft/{draft_id}/cancel", dependencies=[_auth])
def cancel_proforma_draft(
    draft_id:  int,
    body:      Dict[str, Any],
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Mark a draft ``cancelled`` (LOCAL only — does NOT delete a wFirma
    Proforma; for that use the existing ``cancel-issued-for-reissue`` route).

    Body::
        {"expected_updated_at": "...", "reason": "client withdrew order"}
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    operator = _require_operator(x_operator)
    expected = str(body.get("expected_updated_at") or "")
    reason   = str(body.get("reason") or "")
    return _draft_edit_dispatch(draft_id, lambda: pildb.cancel_draft(
        _proforma_db_path(),
        int(draft_id),
        operator,
        expected,
        reason=reason,
    ))


@router.delete("/draft/{draft_id}", dependencies=[_auth])
def purge_proforma_draft(
    draft_id:   int,
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Hard-delete a local-only cancelled draft (no wFirma references).

    Guards: draft_state must be 'cancelled', wfirma_proforma_id absent,
    wfirma_proforma_fullnumber absent.  Removes the draft row and its
    event log; service charges and lines live in JSON columns and are
    removed with the row.
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    operator = _require_operator(x_operator)
    try:
        pildb.purge_cancelled_draft(_proforma_db_path(), int(draft_id), operator)
    except pildb.DraftNotFound:
        raise HTTPException(status_code=404, detail=f"draft {draft_id} not found")
    except pildb.DraftNotEditable as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return JSONResponse({"ok": True, "purged_draft_id": draft_id})


# ── M2: Send Proforma Email ─────────────────────────────────────────────────
# POST /api/v1/proforma/draft/{draft_id}/send-email
#
# Authority chain:
#   UI tb-send click → confirmation modal → PzApi.sendProformaEmail
#   → this route → queue_email → SMTP (via email_sender)
#
# Lesson E compliance:
#   1. Validates draft state + PDF + recipient at execution time
#   2. Idempotent via _find_pending_duplicate (batch_id + email_type + recipient)
#   3. Terminal states (cancelled/deleted/converted) suppress with 422
#   4. Durable queue entry before SMTP attempt
#   5. SMTP config is production-gated via ZOHO_FROM_EMAIL

_PROFORMA_SEND_TOKEN = "YES_SEND_PROFORMA_EMAIL"
_PROFORMA_TERMINAL_STATES = frozenset({"cancelled", "deleted", "converted", "invoiced"})

import re as _re_proforma

_EMAIL_BASIC_RE = _re_proforma.compile(r"^[^\s@\r\n]+@[^\s@\r\n]+\.[^\s@\r\n]+$")


def _sanitise_email_field(value: str, field_name: str) -> str:
    """Strip and reject CRLF injection in email-header fields.

    Raises HTTPException(400) if the value contains \\r or \\n — these are
    SMTP header injection vectors.  Also validates basic email format when
    the value is non-empty.
    """
    v = (value or "").strip()
    if not v:
        return ""
    if "\r" in v or "\n" in v:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name}: contains illegal newline characters",
        )
    if not _EMAIL_BASIC_RE.match(v):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name}: '{v}' is not a valid email address",
        )
    return v


def _sanitise_subject(value: str) -> str:
    """Strip CRLF from subject to prevent header injection."""
    v = (value or "").strip()
    return v.replace("\r", "").replace("\n", "")


def _enrich_customer_resolution_with_email(cr: Dict[str, Any]) -> None:
    """Add Customer Master email to a customer_resolution dict (in-place).

    When resolution found a wfirma_customer_id, look up the Customer Master
    record and add ``customer.bill_to_email`` so the frontend can display
    the customer's email without a separate API call.

    Mutates ``cr`` dict in-place. Never raises — failures are silently
    skipped (the GET must not 500 on enrichment errors).
    """
    if not cr.get("found"):
        return
    cid = cr.get("wfirma_customer_id") or ""
    if not cid:
        return
    try:
        from ..services.customer_master_db import get_customer as _get_cm
        from ..services.customer_master import pick_email as _pick_email
        cm = _get_cm(_customer_master_db_path(), int(cid))
        if cm is None:
            return
        # Enrich the customer dict (or create one) with Customer Master email
        cust = cr.get("customer") or {}
        if not isinstance(cust, dict):
            cust = {}
        cust["bill_to_email"] = _pick_email(cm)
        cr["customer"] = cust
    except Exception:
        pass


def _resolve_proforma_recipient(draft: "pildb.ProformaDraft") -> str:
    """Resolve customer email from Customer Master via draft's client_name.

    Authority chain (PROJECT_STATE.md DECISIONS 2026-06-07):
      draft.client_name → _resolve_customer(batch_id) → wfirma_customer_id
      → customer_master_db → pick_email(customer)

    pick_email priority: bill_to_email first, ship_to_email fallback.
    Returns empty string if not resolvable.
    """
    cn = (draft.client_name or "").strip()
    if not cn:
        return ""
    try:
        cr = _resolve_customer(cn, batch_id=getattr(draft, "batch_id", None))
    except Exception:
        return ""
    cid = cr.get("wfirma_customer_id") or ""
    if not cid:
        return ""
    try:
        from ..services.customer_master_db import get_customer as _get_cm
        from ..services.customer_master import pick_email as _pick_email
        cm = _get_cm(_customer_master_db_path(), int(cid))
        if cm is None:
            return ""
        return _pick_email(cm)
    except Exception:
        return ""


def _proforma_email_body(draft: "pildb.ProformaDraft", subject: str) -> str:
    """Build a simple HTML email body for proforma send."""
    from html import escape as _esc
    doc_no = _esc(draft.wfirma_proforma_fullnumber or f"Draft #{draft.id}")
    client = _esc(draft.client_name or "Customer")
    return (
        f"<p>Dear {client},</p>"
        f"<p>Please find attached the proforma invoice: <strong>{doc_no}</strong>.</p>"
        "<p>If you have any questions, please do not hesitate to contact us.</p>"
        "<p>Best regards,<br>Estrella Jewels</p>"
    )


@router.post("/draft/{draft_id}/send-email", dependencies=[_auth])
def send_proforma_email(
    draft_id:   int,
    body:       Dict[str, Any],
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Send proforma PDF to customer via email.

    Guards:
      - 400: invalid draft_id
      - 400: missing X-Operator
      - 422: invalid confirm_token
      - 404: draft not found
      - 422: draft in terminal state (cancelled/deleted/converted/invoiced)
      - 422: no wfirma_proforma_id (no PDF available)
      - 422: customer email not resolvable
      - 409: duplicate pending send (idempotency)

    Lesson E:
      1. Validates draft state + PDF + recipient at execution time
      2. Idempotent via queue_email._find_pending_duplicate
      3. Terminal-state suppression
      4. Durable queue entry before SMTP attempt
      5. SMTP config production-gated
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    operator = _require_operator(x_operator)

    # 1. Confirm token — prevents accidental sends
    token = str(body.get("confirm_token") or "")
    if token != _PROFORMA_SEND_TOKEN:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid confirmation token — expected {_PROFORMA_SEND_TOKEN}",
        )

    # 2. Load draft (Lesson E P1: validate at execution time)
    d = pildb.get_draft_by_id(_proforma_db_path(), int(draft_id))
    if d is None:
        raise HTTPException(status_code=404, detail=f"draft {draft_id} not found")

    # 3. Terminal-state guard (Lesson E P3)
    state = (d.draft_state or d.status or "").strip().lower()
    if state in _PROFORMA_TERMINAL_STATES:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot send email: draft is in terminal state '{state}'",
        )

    # 4. PDF guard — wfirma_proforma_id must exist
    if not d.wfirma_proforma_id:
        raise HTTPException(
            status_code=422,
            detail="Cannot send email: draft has no wFirma proforma (no PDF available). "
                   "Post the draft to wFirma first.",
        )

    # 5. Resolve recipient (Lesson E P1: execution-time validation)
    #    Sanitise against CRLF injection (security review gate).
    recipient_override = _sanitise_email_field(
        body.get("recipient_override") or "", "recipient_override"
    )
    recipient = recipient_override or _resolve_proforma_recipient(d)
    if not recipient:
        raise HTTPException(
            status_code=422,
            detail="No recipient email found. Set bill_to_email in Customer Master "
                   "or provide recipient_override.",
        )

    # 6. Build email — sanitise subject + CC against header injection
    doc_no = d.wfirma_proforma_fullnumber or f"Draft #{d.id}"
    subject = _sanitise_subject(
        (body.get("subject_override") or "").strip() or f"Proforma {doc_no}"
    )
    message_body = (body.get("message_body") or "").strip()
    html_body = message_body if message_body else _proforma_email_body(d, subject)
    cc_list = body.get("cc") or []
    if isinstance(cc_list, list):
        cc_validated = [_sanitise_email_field(c, "cc") for c in cc_list]
        cc_str = ", ".join(c for c in cc_validated if c)
    else:
        cc_str = _sanitise_email_field(str(cc_list), "cc")

    # 7. Fetch proforma PDF from wFirma (authority: wfirma_proforma_id)
    #
    # Authority chain:
    #   draft.wfirma_proforma_id → wfirma_client.fetch_invoice_pdf (read-only)
    #   → PDF bytes → temp file under storage_root → queue_email(attachments=...)
    #   → email_sender._attachments_for_queue (security: path under storage_root)
    #   → SMTP attachment → temp file cleanup
    #
    # The fetch is read-only (GET invoices/download/{id}).  If wFirma is
    # unreachable or the PDF is missing, the send is blocked with 422.
    batch_id = d.batch_id or ""
    wfirma_id = d.wfirma_proforma_id.strip()
    pdf_filename = f"proforma-{doc_no.replace('/', '-').replace(' ', '_')}.pdf"

    from ..services import wfirma_client as _wfc
    try:
        pdf_bytes = _wfc.fetch_invoice_pdf(wfirma_id)
    except Exception as exc:
        log.warning(
            "send_proforma_email: fetch_invoice_pdf failed for wfirma_id=%s: %s",
            wfirma_id, exc,
        )
        raise HTTPException(
            status_code=422,
            detail="Cannot send email: failed to fetch proforma PDF from wFirma. "
                   f"wfirma_id={wfirma_id}. Try again later or check wFirma status.",
        )

    if not pdf_bytes or len(pdf_bytes) < 10:
        raise HTTPException(
            status_code=422,
            detail="Cannot send email: wFirma returned empty PDF. "
                   f"wfirma_id={wfirma_id}.",
        )

    # Write PDF to a temp file under storage_root so _attachments_for_queue
    # security check passes (path must be under storage_root).
    _pdf_dir = settings.storage_root / "proforma_email_pdfs"
    _pdf_dir.mkdir(parents=True, exist_ok=True)
    # Sanitise filename for filesystem safety (no path traversal)
    _safe_fn = "".join(
        c if (c.isalnum() or c in "._-") else "_" for c in pdf_filename
    )
    # Add draft_id prefix to avoid race conditions on concurrent requests
    _safe_fn = f"{draft_id}_{_safe_fn}"
    _pdf_path = _pdf_dir / _safe_fn
    _pdf_path.write_bytes(pdf_bytes)

    # 8. Queue email (Lesson E P2+P4: idempotency + replay safety)
    from ..services import email_service
    try:
        queue_id = email_service.queue_email(
            to=recipient,
            subject=subject,
            body_html=html_body,
            batch_id=batch_id or f"proforma-{draft_id}",
            cc=cc_str,
            from_address="import@estrellajewels.eu",
            email_type="proforma_send",
            attachments=[{"label": _safe_fn, "path": str(_pdf_path)}],
        )
    except email_service.FollowupSuppressedError as fse:
        # Clean up temp PDF on suppression
        try:
            _pdf_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(
            status_code=409,
            detail=f"Send suppressed: {fse.detail}",
        )
    finally:
        # Clean up temp PDF after queue_email() — SMTP is synchronous,
        # so the file has been consumed by the time we get here.
        try:
            _pdf_path.unlink(missing_ok=True)
        except OSError:
            pass

    # 9. Timeline event
    from ..core import timeline as tl
    audit_root = settings.storage_root / "batches" / batch_id if batch_id else None
    if audit_root and (audit_root / "audit.json").exists():
        tl.log_event(
            audit_root / "audit.json",
            tl.EV_PROFORMA_EMAIL_QUEUED,
            "operator",
            operator,
            {
                "draft_id":     draft_id,
                "recipient":    recipient,
                "subject":      subject,
                "queue_id":     queue_id,
                "pdf":          pdf_filename,
                "pdf_attached": True,
                "pdf_bytes":    len(pdf_bytes),
            },
        )

    log.info(
        "proforma email queued: draft=%d recipient=%s subject=%r queue_id=%s operator=%s",
        draft_id, recipient, subject, queue_id, operator,
    )

    return JSONResponse({
        "ok":           True,
        "queued_id":    queue_id,
        "recipient":    recipient,
        "subject":      subject,
        "pdf_filename": pdf_filename,
        "pdf_attached": True,
        "pdf_bytes":    len(pdf_bytes),
        "audit_event":  "proforma_email_queued",
    })


@router.post("/draft/{draft_id}/reset-from-sales-packing",
             dependencies=[_auth])
def reset_proforma_draft_from_sales_packing(
    draft_id:  int,
    body:      Dict[str, Any],
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Rebuild ``editable_lines`` from the LATEST sales_packing_lines for
    this draft's batch+client.

    Body::
        {"expected_updated_at": "...", "reset_all": false}

    With ``reset_all=true``, buyer/ship-to/payment-terms/remarks/
    service-charges are also wiped.

    Allowed only in editable states (draft / editing / post_failed).
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    operator = _require_operator(x_operator)
    expected = str(body.get("expected_updated_at") or "")
    reset_all = bool(body.get("reset_all") or False)

    # Fetch the draft so we know which batch+client to pull from.
    d = pildb.get_draft_by_id(_proforma_db_path(), int(draft_id))
    if d is None:
        raise HTTPException(status_code=404, detail=f"draft {draft_id} not found")

    # Resolve sales_packing_lines for this batch+client. Filter
    # client-side so we don't add a new doc_db helper.
    all_rows = ddb.get_sales_packing_lines(d.batch_id) or []
    target = (d.client_name or "").strip().upper()
    matched = [r for r in all_rows
                if (r.get("client_name") or "").strip().upper() == target]

    # Reshape sales_packing_lines columns into the helper's input shape.
    sales_lines = [
        {
            "product_code": r.get("product_code") or "",
            "design_no":    r.get("design_no") or "",
            "qty":          r.get("quantity") or 0,
            "unit_price":   r.get("unit_price") or 0,
            "currency":     (r.get("currency") or d.currency or "").upper(),
            "price_source": r.get("price_source") or "",
            "client_ref":   r.get("client_ref") or "",
            # Attribute passthrough for the generated name_pl fallback
            # (used only on a product_descriptions miss; declines when the
            # category is unrecognised). Generally absent on these rows.
            "ctg":          r.get("ctg") or r.get("category") or "",
            "kt":           r.get("kt") or r.get("karat") or "",
            "col":          r.get("col") or r.get("metal_color") or "",
            "quality":      r.get("quality") or r.get("quality_string") or "",
        }
        for r in matched
    ]

    # Route through the shared batch-scoped resolver so reset behaviour
    # matches sync_draft_from_packing_upload. Lines whose product_code is
    # still empty after resolution fall through to the DB layer's skip.
    from ..services.proforma_draft_sync import resolve_sales_lines_for_batch
    sales_lines, _resolution = resolve_sales_lines_for_batch(
        d.batch_id, sales_lines,
    )

    return _draft_edit_dispatch(draft_id, lambda: pildb.reset_draft_from_sales_packing(
        _proforma_db_path(),
        int(draft_id),
        operator,
        expected,
        sales_lines=sales_lines,
        reset_all=reset_all,
        name_pl_lookup=ddb.get_product_description,
        desc_generate=None,
        product_mapping_lookup=wfdb.get_product,
    ))


@router.post("/draft/{draft_id}/enrich-from-product-descriptions",
             dependencies=[_auth])
def enrich_proforma_draft_lines(
    draft_id:   int,
    body:       Dict[str, Any],
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Enrich editable lines with canonical product-description annotations.

    Pure annotation — no price changes, no state changes, no wFirma calls.
    ``source_lines_json`` is never modified.

    Body::
        {"expected_updated_at": "..."}

    Response::
        {"ok": true, "draft_id": N, "enriched_count": N, "missing_count": M,
         "draft": {...}}

    Errors:
        400 — missing expected_updated_at
        404 — draft not found
        409 — draft not in editable state, or OCC conflict
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    operator = (x_operator or "").strip() or "system"
    expected = str(body.get("expected_updated_at") or "")
    if not expected:
        raise HTTPException(status_code=400,
                            detail="expected_updated_at is required")

    def _lookup(pc: str) -> Optional[Dict[str, Any]]:
        return ddb.get_product_description(pc)

    try:
        refreshed = pildb.enrich_draft_lines(
            _proforma_db_path(),
            int(draft_id),
            operator,
            expected,
            _lookup,
        )
    except pildb.DraftNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except pildb.DraftNotEditable as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except pildb.DraftConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    lines = json.loads(refreshed.editable_lines_json or "[]") or []
    n_hit  = sum(1 for ln in lines if ln.get("name_pl") is not None)
    n_miss = sum(1 for ln in lines if ln.get("name_pl") is None)
    return JSONResponse({
        "ok":             True,
        "draft_id":       draft_id,
        "enriched_count": n_hit,
        "missing_count":  n_miss,
        "draft":          _draft_to_full(refreshed),
    })


@router.post("/draft/{draft_id}/lines", dependencies=[_auth])
def post_proforma_draft_line(
    draft_id:  int,
    body:      Dict[str, Any],
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Append a new editable line.

    Body::
        {
          "expected_updated_at": "...",
          "line": {"product_code":"X","qty":1,"unit_price":10,"currency":"EUR"}
        }
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    operator = _require_operator(x_operator)
    expected = str(body.get("expected_updated_at") or "")
    line     = body.get("line") or {}
    return _draft_edit_dispatch(draft_id, lambda: pildb.add_draft_line(
        _proforma_db_path(),
        int(draft_id),
        line,
        operator,
        expected,
    ))


@router.delete("/draft/{draft_id}/lines/{line_id}", dependencies=[_auth])
def delete_proforma_draft_line(
    draft_id:             int,
    line_id:              int,
    expected_updated_at:  str = "",
    force:                bool = False,
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Remove a line. ``force=true`` is required to remove the last line."""
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    if not isinstance(line_id, int) or line_id <= 0:
        raise HTTPException(status_code=400, detail="invalid line_id")
    operator = _require_operator(x_operator)
    return _draft_edit_dispatch(draft_id, lambda: pildb.remove_draft_line(
        _proforma_db_path(),
        int(draft_id),
        int(line_id),
        operator,
        str(expected_updated_at or ""),
        force=bool(force),
    ))


@router.delete("/draft/{draft_id}/service-charges/{charge_id}",
               dependencies=[_auth])
def delete_proforma_draft_service_charge(
    draft_id:             int,
    charge_id:            int,
    expected_updated_at:  str = "",
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Remove a service charge by id.

    ``expected_updated_at`` is supplied as a query parameter (DELETE has
    no body in our convention)."""
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    if not isinstance(charge_id, int) or charge_id <= 0:
        raise HTTPException(status_code=400, detail="invalid charge_id")
    operator = _require_operator(x_operator)
    return _draft_edit_dispatch(draft_id, lambda: pildb.remove_draft_service_charge(
        _proforma_db_path(),
        int(draft_id),
        int(charge_id),
        operator,
        str(expected_updated_at or ""),
    ))


# ── PR 2C.3c — bulk price recovery ───────────────────────────────────────────

@router.post("/draft/{draft_id}/bulk-price-recovery", dependencies=[_auth])
def post_bulk_price_recovery(
    draft_id:   int,
    body:       Dict[str, Any],
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Bulk-apply unit prices to editable lines, matched by ``product_code``.

    Body shape::

        {
          "expected_updated_at": "<iso-utc>",
          "prices": [
            {"product_code": "EJL/26-27/148-1", "unit_price": 61.00},
            ...
          ],
          "confirm_overwrite": "YES_OVERWRITE_EXISTING_PRICES"   // optional
        }

    Only ``unit_price`` and ``price_source="bulk_recovery"`` are written.
    All other line fields (qty, currency, design_no, client_ref, item_type,
    name_pl, description_*) are preserved.  ``source_lines_json`` is never
    read or written.

    When any line already has ``unit_price > 0`` and ``confirm_overwrite`` is
    absent or wrong, returns HTTP 400::

        {
          "ok": false,
          "requires_confirm_overwrite": true,
          "codes_with_existing_price": [...],
          "detail": "..."
        }

    Success response::

        {
          "ok": true,
          "draft_id": <int>,
          "updated_count": <int>,
          "unmatched_codes": [...],
          "still_zero_count": <int>,
          "overwritten_count": <int>,
          "needs_pricing_refresh": <bool>,
          "draft": { ... full draft payload ... }
        }
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")

    operator    = _require_operator(x_operator)
    expected    = str(body.get("expected_updated_at") or "")
    prices      = body.get("prices")
    raw_confirm = body.get("confirm_overwrite")

    if not isinstance(prices, list):
        raise HTTPException(status_code=400, detail="prices must be a list")

    confirm_overwrite = (
        isinstance(raw_confirm, str)
        and raw_confirm.strip() == "YES_OVERWRITE_EXISTING_PRICES"
    )

    # Run the DB operation.  OverwriteRequired gets its own structured 400
    # so the dashboard can display the confirmation panel without parsing
    # a generic error string.
    try:
        refreshed = pildb.bulk_price_recovery(
            _proforma_db_path(),
            int(draft_id),
            prices,
            operator,
            expected,
            confirm_overwrite=confirm_overwrite,
        )
    except pildb.OverwriteRequired as exc:
        return JSONResponse(
            status_code=400,
            content={
                "ok":                         False,
                "requires_confirm_overwrite":  True,
                "codes_with_existing_price":   exc.codes,
                "detail":                     str(exc),
            },
        )
    except pildb.DraftNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except pildb.DraftConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except pildb.DraftNotEditable as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Pull operation metrics from the most-recent event logged by
    # bulk_price_recovery (updated_count / unmatched_codes / etc.).
    events = pildb.list_draft_events(_proforma_db_path(), int(draft_id))
    metrics: Dict[str, Any] = {}
    if events:
        try:
            metrics = json.loads(events[-1].get("detail_json") or "{}")
        except Exception:
            metrics = {}

    # Recompute needs_pricing_refresh from the freshly committed lines.
    try:
        refreshed_lines = json.loads(refreshed.editable_lines_json or "[]") or []
    except Exception:
        refreshed_lines = []
    needs_pricing_refresh = any(
        float(ln.get("unit_price", 0) or 0) <= 0 for ln in refreshed_lines
    )

    return JSONResponse({
        "ok":                    True,
        "draft_id":              int(draft_id),
        "updated_count":         metrics.get("updated_count", 0),
        "unmatched_codes":       metrics.get("unmatched_codes", []),
        "still_zero_count":      metrics.get("still_zero_count", 0),
        "overwritten_count":     metrics.get("overwritten_count", 0),
        "needs_pricing_refresh": needs_pricing_refresh,
        "draft":                 _draft_to_full(refreshed),
    })


# ── PR B — customer address + service-charge authority ───────────────────────


def _resolve_cm_for_draft(draft_id: int):
    """Resolve Customer Master for a draft without currency requirements.

    Returns ``(draft, cm | None, blocked_reason | None)``.
    Uses buyer_override.wfirma_customer_id first (explicit selection),
    then falls back to _resolve_customer name resolution.
    """
    d = pildb.get_draft_by_id(_proforma_db_path(), draft_id)
    if d is None:
        return None, None, f"draft id={draft_id} not found"

    try:
        buyer_override = json.loads(d.buyer_override_json or "{}") or {}
    except Exception:
        buyer_override = {}

    override_cid = (buyer_override.get("wfirma_customer_id") or "").strip()
    if override_cid:
        cm = get_customer_master(_customer_master_db_path(), override_cid)
        if cm is None:
            return d, None, (
                f"Customer Master record not found for contractor_id={override_cid!r} "
                "stored in buyer_override — re-select the correct buyer"
            )
        return d, cm, None

    resolution = _resolve_customer(d.client_name)
    if not resolution.get("found") or not resolution.get("wfirma_customer_id"):
        return d, None, (
            f"customer {d.client_name!r} not found in Customer Master — "
            "use the Customer Mapping tab to link this client first"
        )

    cm = get_customer_master(_customer_master_db_path(), resolution["wfirma_customer_id"])
    if cm is None:
        return d, None, (
            f"Customer Master record missing for contractor_id="
            f"{resolution['wfirma_customer_id']!r} (client {d.client_name!r})"
        )
    return d, cm, None


@router.post("/draft/{draft_id}/apply-customer-address", dependencies=[_auth],
             summary="Project Customer Master bill-to/ship-to onto the draft as buyer_override")
def apply_customer_address(
    draft_id:   int,
    body:       Dict[str, Any],
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Apply Customer Master address data as buyer_override (and optionally ship_to_override).

    Reads the Customer Master linked to this draft and writes its
    bill_to / ship_to fields into the draft overrides.  The Customer
    Master record itself is NEVER modified.

    Body::

        {
          "expected_updated_at": "2026-06-10T09:00:00+00:00",
          "clear_ship_to": false    // optional; true = also clear ship_to_override
        }

    Response: full draft object wrapped in {"ok": true, "draft": {...}}.

    Blocked when:
    - No Customer Master record is linked or resolvable (404)
    - Draft is in a non-editable state (409)
    - Optimistic-lock conflict (409)
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    operator = _require_operator(x_operator)
    expected = str(body.get("expected_updated_at") or "")

    d, cm, blocked = _resolve_cm_for_draft(draft_id)
    if blocked:
        raise HTTPException(status_code=404, detail=blocked)

    # Build buyer_override from Customer Master
    buyer_override: Dict[str, Any] = {
        "name":               cm.bill_to_name or "",
        "street":             cm.bill_to_street or "",
        "city":               cm.bill_to_city or "",
        "zip":                cm.bill_to_postal_code or "",
        "country":            cm.country or "",
        "nip":                cm.nip or "",
        "vat_id":             cm.vat_eu_number or "",
        "email":              cm.bill_to_email or "",
        "phone":              cm.bill_to_phone or "",
        "wfirma_customer_id": cm.bill_to_contractor_id,
        "_source":            "customer_master",
    }

    # Ship-to override: written when Customer Master has an alternate address
    ship_to_override: Optional[Dict[str, Any]] = None
    if cm.ship_to_use_alternate:
        ship_to_override = {
            "name":    cm.ship_to_name    or cm.bill_to_name or "",
            "street":  cm.ship_to_street  or "",
            "city":    cm.ship_to_city    or "",
            "zip":     cm.ship_to_zip     or "",
            "country": cm.ship_to_country or cm.country or "",
            "phone":   cm.ship_to_phone   or "",
            "email":   cm.ship_to_email   or "",
        }
    elif body.get("clear_ship_to"):
        # Caller requested explicit clear
        ship_to_override = {}

    return _draft_edit_dispatch(draft_id, lambda: pildb.apply_customer_address_to_draft(
        _proforma_db_path(),
        int(draft_id),
        cm_name            = cm.bill_to_name,
        cm_contractor_id   = cm.bill_to_contractor_id,
        buyer_override     = buyer_override,
        ship_to_override   = ship_to_override,
        operator           = operator,
        expected_updated_at= expected,
    ))


@router.get("/draft/{draft_id}/suggest-service-charges", dependencies=[_auth],
            summary="Combined freight + insurance suggestion from Customer Master")
def suggest_service_charges(draft_id: int) -> JSONResponse:
    """Return a combined freight + insurance suggestion for a single API call.

    Internally calls the same logic as /suggest-freight and /suggest-insurance
    and bundles both results together.  Also inspects the draft's existing
    service_charges to populate the ``already_applied`` flag per charge type.

    Response shape::

        {
          "ok": true,
          "draft_id": 42,
          "draft_currency": "EUR",
          "freight": {
            "available": true,
            "already_applied": false,
            "amount": "120.00",
            "currency": "EUR",
            "label": "FedEx Courier",
            "wfirma_service_id": "13002743",
            "blocked_reason": null
          },
          "insurance": {
            "available": false,
            "already_applied": false,
            "amount": null,
            "currency": null,
            "label": null,
            "wfirma_service_id": null,
            "blocked_reason": "insurance_enabled=false for this customer"
          }
        }
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")

    d, draft_currency, cm, blocked_reason = _suggest_lookup(draft_id)
    base = {"draft_id": draft_id, "draft_currency": draft_currency or ""}

    if blocked_reason:
        return JSONResponse({
            **base, "ok": False,
            "freight":   {"available": False, "already_applied": False, "blocked_reason": blocked_reason},
            "insurance": {"available": False, "already_applied": False, "blocked_reason": blocked_reason},
        })

    # Which types are already on the draft?
    import json as _j
    try:
        existing_charges = _j.loads(d.service_charges_json or "[]") or []
    except Exception:
        existing_charges = []
    applied_types = {(c.get("charge_type") or "").lower() for c in existing_charges}

    # Freight suggestion
    freight_result = pick_freight(cm, draft_currency)
    if freight_result.get("ok"):
        from decimal import Decimal as _Dec
        freight_entry = {
            "available":       True,
            "already_applied": "freight" in applied_types,
            "amount":          str(freight_result["amount"]),
            "currency":        draft_currency,
            "label":           freight_result.get("label"),
            "wfirma_service_id": freight_result["wfirma_service_id"],
            "blocked_reason":  None,
        }
    else:
        # cm is resolved here (resolution-blocked path returned above): expose
        # the exact record + missing field + deep-link so the operator repairs
        # the freight authority IN Customer Master, then retries.
        freight_entry = {
            "available":       False,
            "already_applied": "freight" in applied_types,
            "amount":          None,
            "currency":        None,
            "label":           None,
            "wfirma_service_id": None,
            "blocked_reason":  freight_result.get("reason", "no freight data"),
            "freight_authority": _freight_authority_block(cm, freight_result),
        }

    # Insurance suggestion (needs sales total for formula mode)
    try:
        lines = _j.loads(d.editable_lines_json or "[]") or []
    except Exception:
        lines = []
    from decimal import Decimal as _Dec
    sales_total = sum(
        _Dec(str(ln.get("qty", 0) or 0)) * _Dec(str(ln.get("unit_price", 0) or 0))
        for ln in lines
    )
    ins_result = compute_insurance_suggestion(cm, draft_currency, sales_total)
    if ins_result.get("ok"):
        ins_entry = {
            "available":       True,
            "already_applied": "insurance" in applied_types,
            "amount":          str(ins_result["amount"]),
            "currency":        draft_currency,
            "label":           ins_result.get("label"),
            "wfirma_service_id": ins_result["wfirma_service_id"],
            "formula_basis":   ins_result.get("formula_basis"),
            "blocked_reason":  None,
        }
    else:
        ins_entry = {
            "available":       False,
            "already_applied": "insurance" in applied_types,
            "amount":          None,
            "currency":        None,
            "label":           None,
            "wfirma_service_id": None,
            "formula_basis":   None,
            "blocked_reason":  ins_result.get("reason", "no insurance data"),
        }

    return JSONResponse({**base, "ok": True, "freight": freight_entry, "insurance": ins_entry})


@router.post("/draft/{draft_id}/apply-service-charges", dependencies=[_auth],
             summary="Apply Customer Master freight/insurance as service charges")
def apply_service_charges(
    draft_id:   int,
    body:       Dict[str, Any],
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Apply Customer Master freight and/or insurance as draft service charges.

    Idempotent: a charge type that already exists on the draft is skipped
    (returned in ``skipped``) rather than raising an error.

    Body::

        {
          "expected_updated_at": "2026-06-10T09:00:00+00:00",
          "apply": ["freight", "insurance"]   // one or both
        }

    Response::

        {
          "ok": true,
          "draft_id": 42,
          "applied":  [{"charge_type": "freight", "amount": "120.00", ...}],
          "skipped":  [{"charge_type": "insurance", "reason": "insurance_enabled=false ..."}],
          "draft":    { ... full draft object ... }
        }
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    operator = _require_operator(x_operator)
    expected = str(body.get("expected_updated_at") or "")
    apply_types = [str(t).lower() for t in (body.get("apply") or [])]
    if not apply_types:
        raise HTTPException(status_code=400, detail="apply list must be non-empty")
    unknown = [t for t in apply_types if t not in {"freight", "insurance"}]
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown charge type(s): {unknown}")

    d, draft_currency, cm, blocked_reason = _suggest_lookup(draft_id)
    if blocked_reason:
        raise HTTPException(status_code=409, detail=blocked_reason)

    import json as _j
    try:
        existing_charges = _j.loads(d.service_charges_json or "[]") or []
    except Exception:
        existing_charges = []
    applied_types_now = {(c.get("charge_type") or "").lower() for c in existing_charges}

    # Compute suggestions for requested types
    from decimal import Decimal as _Dec
    try:
        lines = _j.loads(d.editable_lines_json or "[]") or []
    except Exception:
        lines = []
    sales_total = sum(
        _Dec(str(ln.get("qty", 0) or 0)) * _Dec(str(ln.get("unit_price", 0) or 0))
        for ln in lines
    )
    suggestions: Dict[str, Any] = {}
    if "freight" in apply_types:
        suggestions["freight"] = pick_freight(cm, draft_currency)
    if "insurance" in apply_types:
        suggestions["insurance"] = compute_insurance_suggestion(cm, draft_currency, sales_total)

    applied: list = []
    skipped: list = []
    current_updated_at = expected

    for ctype in apply_types:
        if ctype in applied_types_now:
            skipped.append({"charge_type": ctype, "reason": f"{ctype} charge already exists on this draft"})
            continue
        suggestion = suggestions.get(ctype, {})
        if not suggestion.get("ok"):
            skipped.append({"charge_type": ctype, "reason": suggestion.get("reason", f"no {ctype} data")})
            continue

        charge = {
            "charge_type":       ctype,
            "amount":            float(suggestion["amount"]),
            "currency":          draft_currency,
            "label":             suggestion.get("label") or "",
            "wfirma_service_id": suggestion.get("wfirma_service_id"),
        }
        if ctype == "insurance" and suggestion.get("formula_basis"):
            charge["formula_basis"] = suggestion["formula_basis"]

        try:
            refreshed = pildb.add_draft_service_charge(
                _proforma_db_path(),
                int(draft_id),
                charge,
                operator,
                current_updated_at,
            )
            # Chain updated_at so next add uses the refreshed timestamp
            current_updated_at = refreshed.updated_at or current_updated_at
            applied_types_now.add(ctype)
            applied.append({**charge, "charge_id": next(
                c["charge_id"] for c in (json.loads(refreshed.service_charges_json or "[]") or [])
                if c.get("charge_type") == ctype
            )})
            d = refreshed  # keep in sync for final response
        except (pildb.DraftNotFound, pildb.DraftConflict, pildb.DraftNotEditable) as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            # Duplicate detected concurrently or other validation error
            skipped.append({"charge_type": ctype, "reason": str(exc)})

    return JSONResponse({
        "ok":       True,
        "draft_id": draft_id,
        "applied":  applied,
        "skipped":  skipped,
        "draft":    _draft_to_full(d),
    })


# ── PR 2C.3b — customer-master suggestions ────────────────────────────────────

def _cm_freight_edit_url(contractor_id: str) -> Optional[str]:
    """Deep-link to the exact Customer Master record's edit view.

    customer-master-v2.html reads ``?contractor_id=`` and opens that record, so
    the freight blocker can route the operator straight to the record whose
    freight authority is missing — no manual hunt through the customer list.
    """
    cid = (contractor_id or "").strip()
    # safe="" mirrors the frontend's encodeURIComponent (encodes '/' too) so the
    # backend-built deep-link matches customer-master-v2.html's own link format.
    return (f"/dashboard/customer-master-v2.html?contractor_id={quote(cid, safe='')}"
            if cid else None)


def _freight_authority_block(cm: Optional["CustomerMaster"],
                             pick_result: Dict[str, Any]) -> Dict[str, Any]:
    """Structured repair context for a BLOCKED freight suggestion.

    Customer Master is the single freight authority. When ``pick_freight`` blocks
    because the resolved record is missing a freight field, surface WHICH record
    (contractor_id + name) and WHICH field, plus a deep-link to edit that exact
    record — so the operator fixes the authority in Customer Master and retries,
    with no draft-level override or guessed fallback.

    ``resolved`` is True only when a Customer Master record was actually resolved;
    callers must NOT synthesise an identity when resolution itself failed.
    """
    if cm is None:
        return {"resolved": False}
    missing = pick_result.get("field")
    return {
        "resolved":      True,
        "contractor_id": cm.bill_to_contractor_id,
        "bill_to_name":  cm.bill_to_name,
        "missing_field": missing,
        # Deep-link only when a Customer Master field is what's missing. A block
        # with no CM field to repair (e.g. unsupported draft currency) gets no
        # edit link — there is nothing on the record to fix.
        "edit_url":      _cm_freight_edit_url(cm.bill_to_contractor_id) if missing else None,
    }


def _suggest_lookup(draft_id: int):
    """Shared setup for suggest-freight / suggest-insurance.

    Returns ``(draft, draft_currency, customer_master | None, blocked_reason | None)``.
    ``blocked_reason`` is a non-empty string when the call should return a
    blocked response; the other values are only meaningful when it is ``None``.

    Authority chain (Customer Master is primary):
      1. buyer_override_json.wfirma_customer_id — explicit operator selection
         (stored when operator picks a candidate from the CustomerMappingTab).
         Use this contractor_id directly; do NOT run name resolution.
      2. Name resolution via _resolve_customer.  If ambiguous (multiple CM
         candidates) and no explicit selection: block with a clear message so
         the operator knows they must select first.
    """
    d = pildb.get_draft_by_id(_proforma_db_path(), draft_id)
    if d is None:
        return None, None, None, f"draft id={draft_id} not found"

    draft_currency = (d.currency or "").upper()
    if draft_currency not in ("EUR", "USD"):
        return d, draft_currency, None, (
            f"draft currency {draft_currency!r} is not supported; "
            "only EUR and USD drafts can receive suggestions"
        )

    # ── Priority 1: explicit contractor selection stored in buyer_override ──
    try:
        buyer_override = json.loads(d.buyer_override_json or "{}") or {}
    except Exception:
        buyer_override = {}
    override_contractor_id = (buyer_override.get("wfirma_customer_id") or "").strip()

    if override_contractor_id:
        cm = get_customer_master(_customer_master_db_path(), override_contractor_id)
        if cm is None:
            return d, draft_currency, None, (
                f"Customer Master record not found for selected "
                f"contractor_id={override_contractor_id!r} — "
                "update the Customer Master entry or re-select the correct buyer"
            )
        return d, draft_currency, cm, None

    # ── Priority 2: name-based resolution ──────────────────────────────────
    # First check for ambiguity so the error message is actionable.
    norm = _normalize_client_name(d.client_name or "")
    if norm:
        try:
            cm_probe = _resolve_customer_via_master(norm)
            if cm_probe is not None and cm_probe.get("ambiguous"):
                candidates = cm_probe.get("candidates") or []
                cands_str = ", ".join(f'"{c}"' for c in candidates[:5])
                return d, draft_currency, None, (
                    f"Customer {d.client_name!r} matches multiple Customer Master records "
                    f"({cands_str}) — open the Customer Mapping tab and select the correct "
                    "buyer before suggesting freight or insurance"
                )
        except Exception:
            pass  # defensive — fall through to full resolution

    resolution = _resolve_customer(d.client_name)
    if not resolution.get("found") or not resolution.get("wfirma_customer_id"):
        return d, draft_currency, None, (
            f"customer {d.client_name!r} not found in wFirma mapping — "
            "cannot look up customer master"
        )

    contractor_id = resolution["wfirma_customer_id"]
    cm = get_customer_master(_customer_master_db_path(), contractor_id)
    if cm is None:
        return d, draft_currency, None, (
            f"no customer master record for contractor_id={contractor_id!r} "
            f"(client_name={d.client_name!r})"
        )

    return d, draft_currency, cm, None


@router.get("/draft/{draft_id}/suggest-freight", dependencies=[_auth],
            summary="Suggest freight service charge from customer master")
def suggest_freight_endpoint(draft_id: int) -> JSONResponse:
    """Return a freight amount suggestion derived from the customer master.

    Reads ``freight_fixed_amount_eur`` / ``freight_fixed_amount_usd`` for the
    customer linked to this draft.  Returns a structured suggestion the UI can
    use to pre-fill the service-charge add form.  Does NOT write any data.

    Response shape (success)::

        {
          "ok": true,
          "draft_id": 42,
          "draft_currency": "EUR",
          "suggestion": {
            "amount": "120.00",
            "wfirma_service_id": "13002743",
            "label": "FedEx Courier",
            "legacy_fallback": false
          }
        }

    Response shape (blocked)::

        {
          "ok": false,
          "blocked": true,
          "reason": "...",
          "draft_id": 42,
          "draft_currency": "EUR"
        }
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")

    d, draft_currency, cm, blocked_reason = _suggest_lookup(draft_id)
    base = {"draft_id": draft_id, "draft_currency": draft_currency or ""}

    if blocked_reason:
        return JSONResponse({**base, "ok": False, "blocked": True, "reason": blocked_reason})

    result = pick_freight(cm, draft_currency)
    if not result.get("ok"):
        # cm is resolved here (resolution-blocked path returned above), so
        # surface the exact record + missing field + deep-link for repair.
        return JSONResponse({**base, "ok": False, "blocked": True,
                             "reason": result.get("reason", "unknown"),
                             "freight_authority": _freight_authority_block(cm, result)})

    from decimal import Decimal as _Dec
    return JSONResponse({
        **base,
        "ok": True,
        "suggestion": {
            "amount":            str(result["amount"]),
            "wfirma_service_id": result["wfirma_service_id"],
            "label":             result.get("label"),
            "legacy_fallback":   bool(result.get("legacy_fallback", False)),
        },
    })


@router.get("/draft/{draft_id}/suggest-insurance", dependencies=[_auth],
            summary="Calculate insurance service charge from customer master")
def suggest_insurance_endpoint(draft_id: int) -> JSONResponse:
    """Return an insurance amount suggestion derived from the customer master.

    Uses ``insurance_fixed_amount_eur`` / ``insurance_fixed_amount_usd`` (fixed
    mode) or ``insurance_rate`` + minimum (formula mode).  Blocked when
    ``insurance_enabled`` is ``False`` or when the draft has unpriced lines
    (``needs_pricing_refresh``).  Does NOT write any data.

    Response shape (success)::

        {
          "ok": true,
          "draft_id": 42,
          "draft_currency": "EUR",
          "suggestion": {
            "amount": "35.00",
            "wfirma_service_id": "13102217",
            "label": "Insurance",
            "formula_basis": null
          }
        }
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")

    d, draft_currency, cm, blocked_reason = _suggest_lookup(draft_id)
    base = {"draft_id": draft_id, "draft_currency": draft_currency or ""}

    if blocked_reason:
        return JSONResponse({**base, "ok": False, "blocked": True, "reason": blocked_reason})

    # Block on unpriced lines — insurance formula would be meaningless
    import json as _json
    try:
        lines = _json.loads(d.editable_lines_json or "[]") or []
    except Exception:
        lines = []
    needs_pricing_refresh = any(
        float(ln.get("unit_price", 0) or 0) <= 0 for ln in lines
    )
    if needs_pricing_refresh:
        return JSONResponse({
            **base,
            "ok": False, "blocked": True,
            "reason": (
                "draft has lines with unit_price <= 0 — "
                "reset draft from packing to populate prices before suggesting insurance"
            ),
        })

    # Sales total = sum of (qty × unit_price) across editable lines
    from decimal import Decimal as _Dec
    sales_total = sum(
        _Dec(str(ln.get("qty", 0) or 0)) * _Dec(str(ln.get("unit_price", 0) or 0))
        for ln in lines
    )

    result = compute_insurance_suggestion(cm, draft_currency, sales_total)
    if not result.get("ok"):
        return JSONResponse({**base, "ok": False, "blocked": True,
                             "reason": result.get("reason", "unknown")})

    return JSONResponse({
        **base,
        "ok": True,
        "suggestion": {
            "amount":            str(result["amount"]),
            "wfirma_service_id": result["wfirma_service_id"],
            "label":             result.get("label"),
            "formula_basis":     result.get("formula_basis"),
        },
    })


# ── Phase 5 — operator-driven posting to wFirma ────────────────────────────
#
# Single endpoint: POST /api/v1/proforma/draft/{draft_id}/post
#
# Hard rules:
#   - Source of truth is the persisted draft. NEVER re-read sales_packing_lines
#     for prices/qty/currency in this path. Master-data lookups (wfirma_db
#     product/customer, vat-context resolver, receiver preflight) are
#     allowed.
#   - Service charges block posting until the wFirma service-product
#     mapping ships (Phase 6).
#   - Single-currency drafts only.
#   - Idempotent on draft_id: a draft with wfirma_proforma_id set, or in
#     state posting/posted, returns 409 with no wFirma call.
#   - approved → posting commit happens BEFORE the wFirma call; any
#     subsequent failure transitions to post_failed (never silently back).


def _post_validation_error(draft_id: int, msg: str) -> JSONResponse:
    """Pre-commit validation failure: no wFirma call, no state change.
    Returns ``{ok:false, status:"blocked", ...}`` shape mirroring the
    legacy /create route so dashboard rendering can converge."""
    return JSONResponse(
        status_code=400,
        content={
            "ok":               False,
            "status":           "blocked",
            "draft_id":         int(draft_id),
            "blocking_reasons": [msg],
        },
    )


def _post_validation_errors(
    draft_id: int, readiness: Dict[str, Any],
) -> JSONResponse:
    """Multi-blocker variant of ``_post_validation_error`` for the single
    readiness authority: same ``{ok:false, status:"blocked"}`` shape, all
    blocking reasons listed, plus structured blockers with repair actions
    (Lesson M). No wFirma call, no state change."""
    return JSONResponse(
        status_code=400,
        content={
            "ok":               False,
            "status":           "blocked",
            "draft_id":         int(draft_id),
            "blocking_reasons": readiness.get("blocking_reasons") or [],
            "blockers":         readiness.get("blockers") or [],
            "readiness_intent": readiness.get("intent"),
        },
    )


def _build_proforma_request_from_draft(
    draft: "pildb.ProformaDraft",
) -> "wfirma_client.ProformaRequest":
    """Build a ``ProformaRequest`` strictly from persisted draft fields.

    Pricing, quantity, currency, product_code come from
    ``editable_lines_json`` only — no live preview, no sales_packing_lines.
    Master-data lookups (wfirma_customer_id, wfirma_product_id, vat_code_id,
    receiver id) ARE made — these are static references, not pricing.

    Raises ``ValueError`` for any missing/inconsistent input. The caller
    must surface the message verbatim as a blocking reason — never as a 500.
    """
    client_name = (draft.client_name or "").strip()
    if not client_name:
        raise ValueError("draft has no client_name")

    # Parse lines
    try:
        lines_raw = json.loads(draft.editable_lines_json or "[]") or []
    except Exception:
        raise ValueError("editable_lines_json is not valid JSON")
    if not isinstance(lines_raw, list) or not lines_raw:
        raise ValueError("editable_lines_json must be a non-empty list")

    # Service-charge block — charges are snapshotted in the draft for accounting
    # (finance_dual_write). Those with a wFirma product mapping become line items;
    # those without are noted but do NOT block posting (Phase 6D).
    try:
        charges = json.loads(draft.service_charges_json or "[]") or []
    except Exception:
        charges = []
    _sc_wfirma_note: str = ""
    if charges:
        # Use module-level wfdb reference (same as product line resolution above)
        # so monkeypatching in tests works correctly.
        _sc_types = {(c.get("charge_type") or "").lower() for c in charges}
        _sc_unmapped = [
            ct for ct in _sc_types
            if wfdb._db_path is None or not wfdb.get_product(ct)
        ]
        if _sc_unmapped:
            _sc_wfirma_note = (
                f"service charges ({', '.join(sorted(_sc_unmapped))}) snapshotted "
                "for accounting but NOT included in wFirma proforma content — "
                "register a service product mapping to include them as line items"
            )

    # Single-currency check
    line_ccys = {(ln.get("currency") or "").upper() for ln in lines_raw
                  if (ln.get("currency") or "").strip()}
    if len(line_ccys) > 1:
        raise ValueError(
            f"draft has mixed line currencies {sorted(line_ccys)}; "
            "Proforma posting requires a single currency across all lines"
        )
    draft_ccy = (draft.currency or "").strip().upper()
    if line_ccys and draft_ccy and next(iter(line_ccys)) != draft_ccy:
        raise ValueError(
            f"draft.currency={draft_ccy!r} disagrees with line currency "
            f"{next(iter(line_ccys))!r}"
        )
    currency = (next(iter(line_ccys)) if line_ccys else draft_ccy) or "PLN"

    # Per-line validation (qty>0, unit_price>=0)
    for idx, ln in enumerate(lines_raw, start=1):
        try:
            q = float(ln.get("qty") or 0)
        except (TypeError, ValueError):
            raise ValueError(f"line {idx}: qty must be numeric")
        if q <= 0:
            raise ValueError(f"line {idx}: qty must be > 0")
        try:
            up = float(ln.get("unit_price") or 0)
        except (TypeError, ValueError):
            raise ValueError(f"line {idx}: unit_price must be numeric")
        if up < 0:
            raise ValueError(f"line {idx}: unit_price must be >= 0")
        if not str(ln.get("product_code") or "").strip():
            raise ValueError(f"line {idx}: product_code is required")

    # Customer resolution (master-data lookup, not pricing)
    resolution = _resolve_customer(client_name)
    if resolution["ambiguous"]:
        raise ValueError(
            f"multiple wfirma customer candidates for {client_name!r}: "
            f"{resolution['candidates']} — refusing to auto-pick"
        )
    cust = resolution["customer"]
    contractor_id = resolution["wfirma_customer_id"]
    if not contractor_id:
        raise ValueError(
            f"wfirma_customers has no wfirma_customer_id for {client_name!r} "
            "(normalized "
            f"{resolution['normalized_name']!r}) — register the mapping first"
        )

    # ── D1/D2: VAT from customer_master (ADR-027) ─────────────────────────
    _cm_vat_rec = get_customer_master(_customer_master_db_path(), contractor_id)
    _vat_warnings_draft: List[str] = []

    if _cm_vat_rec is not None:
        try:
            _cm_vat = wfirma_client.resolve_vat_context_from_master(_cm_vat_rec)
        except ValueError as _ve:
            raise ValueError(
                f"vat_mode resolution failed for {client_name!r}: {_ve}"
            )
        if _cm_vat["blocked"]:
            # Fall back to wfirma_customers mirror then live search
            customer_country = ((cust or {}).get("country") or "").strip()
            customer_vat_id  = ((cust or {}).get("vat_id")  or "").strip()
            if not customer_country:
                try:
                    live = wfirma_client.search_customer(client_name)
                except Exception:
                    live = None
                if live is not None:
                    customer_country = (live.country or "").strip()
                    customer_vat_id  = (live.nip or "").strip()
            _fallback = wfirma_client.decide_proforma_vat_context(
                customer_country=customer_country,
                customer_vat_id=customer_vat_id,
            )
            if _fallback["context"] == "blocked":
                raise ValueError(
                    f"vat decision blocked for {client_name!r}: "
                    f"{_cm_vat['blocked_reason']} "
                    f"(fallback also failed: {_fallback['reason']})"
                )
            vat_code_str     = _fallback["vat_code"]
            _resolved_ctx    = _fallback["context"]
            _decision_source = "fallback_wfirma"
            _d3_vies_flag    = False   # fallback path — D3 not applicable
        else:
            vat_code_str     = _cm_vat["vat_code"]
            _resolved_ctx    = _cm_vat["context"]
            _decision_source = _cm_vat["decision_source"]
            _vat_warnings_draft.extend(_cm_vat["warnings"])
            _d3_vies_flag    = bool(_cm_vat.get("d3_vies_warning", False))
    else:
        # No customer_master — legacy path; D3 not applicable
        customer_country = ((cust or {}).get("country") or "").strip()
        customer_vat_id  = ((cust or {}).get("vat_id")  or "").strip()
        if not customer_country or (customer_country.upper() != "PL"
                                     and not customer_vat_id):
            try:
                live = wfirma_client.search_customer(client_name)
            except Exception:
                live = None
            if live is not None:
                customer_country = customer_country or (live.country or "").strip()
                customer_vat_id  = customer_vat_id  or (live.nip     or "").strip()
        _legacy = wfirma_client.decide_proforma_vat_context(
            customer_country=customer_country,
            customer_vat_id=customer_vat_id,
        )
        if _legacy["context"] == "blocked":
            raise ValueError(
                f"vat decision blocked for {client_name!r}: {_legacy['reason']}"
            )
        vat_code_str     = _legacy["vat_code"]
        _resolved_ctx    = _legacy["context"]
        _decision_source = "fallback_wfirma"
        _d3_vies_flag    = False   # legacy path — D3 not applicable

    # ── D4: drift check (ADR-027) ─────────────────────────────────────────
    # If the draft already has a frozen vat_context and it differs from what
    # we resolved now, emit a DRIFT WARNING — never silent change.
    # NOTE: the actual DB freeze is done by the route AFTER start_post so it
    # does not disturb the optimistic-lock timestamp used by start_post.
    _frozen_ctx = (draft.vat_context or "").strip()
    if _frozen_ctx and _frozen_ctx != _resolved_ctx:
        _vat_warnings_draft.append(
            f"vat_drift: frozen vat_context={_frozen_ctx!r} differs from "
            f"re-resolved context={_resolved_ctx!r} — check customer master "
            "changes since draft creation"
        )

    # Resolve numeric vat_code_id live (never persisted).
    try:
        vat_code_id = wfirma_client.resolve_vat_code_id_for_context(vat_code_str)
    except Exception as exc:
        raise ValueError(
            f"vat_code resolution failed for {vat_code_str!r}: {exc}"
        )

    # Per-line wfirma_good_id resolution (master-data, not pricing)
    rlines: List[wfirma_client.ReservationLine] = []
    missing_products: List[str] = []
    for ln in lines_raw:
        pc = (ln.get("product_code") or "").strip()
        prod = wfdb.get_product(pc) if (pc and wfdb._db_path is not None) else None
        good_id = (prod or {}).get("wfirma_product_id") or ""
        if not good_id:
            missing_products.append(pc or "<unknown>")
            continue
        rlines.append(wfirma_client.ReservationLine(
            product_code   = pc,
            wfirma_good_id = good_id,
            product_name   = (ln.get("design_no") or pc),
            qty            = float(ln.get("qty") or 0),
            unit_price     = float(ln.get("unit_price") or 0),
            unit           = "szt.",
            currency       = (ln.get("currency") or currency or "PLN").upper(),
        ))
    if missing_products:
        missing_msg = (
            "wfirma_products missing wfirma_product_id for: "
            + ", ".join(missing_products[:5])
            + ("…" if len(missing_products) > 5 else "")
        )
        # HS-2 advisory mode: emit warning instead of blocking
        # The wFirma write flag (WFIRMA_CREATE_PROFORMA_ALLOWED) remains hard;
        # in advisory mode the draft can be reviewed but cannot be posted to
        # wFirma until products are resolved.
        if not settings.advisory_gates_enabled:
            raise ValueError(missing_msg)
        # Advisory mode: emit a wfirma_product_registration inbox proposal so the
        # operator sees it in the Inbox and can approve registration before posting.
        # Lines without wfirma_good_id are skipped from the request for now.
        import logging as _adv_log
        _adv_log.getLogger(__name__).warning(
            "advisory mode: %s — unresolved lines skipped; registration proposal emitted",
            missing_msg
        )
        try:
            from ..services.wfirma_product_registration import create_registration_proposal
            # Locate the draft's audit.json to write the proposal into
            _reg_batch = (draft.batch_id or "").strip()
            if _reg_batch:
                _reg_audit_path = settings.storage_root / "outputs" / _reg_batch / "audit.json"
                if _reg_audit_path.exists():
                    import json as _reg_json
                    _reg_audit = _reg_json.loads(_reg_audit_path.read_text(encoding="utf-8"))
                    _reg_prop = create_registration_proposal(
                        _reg_audit, _reg_batch, missing_products
                    )
                    if _reg_prop:
                        _reg_audit_path.write_text(
                            _reg_json.dumps(_reg_audit, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
        except Exception as _reg_exc:
            _adv_log.getLogger(__name__).warning(
                "advisory mode: registration proposal write failed (non-fatal): %s", _reg_exc
            )

    # Ship-to / Odbiorca (same logic as legacy _build_proforma_request)
    ship_to_mode   = ((cust or {}).get("ship_to_mode") or "same_as_bill_to").lower()
    ship_to_rcv_id = ((cust or {}).get("ship_to_wfirma_customer_id") or "").strip()
    if ship_to_mode == "separate_contractor" and not ship_to_rcv_id:
        raise ValueError(
            f"ship_to_mode is 'separate_contractor' for {client_name!r} but "
            "ship_to_wfirma_customer_id is empty"
        )
    if ship_to_mode == "separate_contractor" and ship_to_rcv_id == contractor_id:
        raise ValueError(
            f"ship_to_wfirma_customer_id equals bill-to id for {client_name!r}"
        )
    receiver_id = ship_to_rcv_id if ship_to_mode == "separate_contractor" else ""

    # D6: document defaults from customer_master (ADR-027)
    # _cm_vat_rec was already fetched above for the VAT decision.
    _cm_d6 = _cm_vat_rec  # same record — no second DB read needed
    draft_proforma_series   = (pick_proforma_series_id(_cm_d6) or "") if _cm_d6 else ""
    _d6_payment_terms_days  = (_cm_d6.payment_terms_days if _cm_d6 else None)
    _d6_payment_method      = ((_cm_d6.preferred_payment_method or "").strip().lower()
                               if _cm_d6 else "")
    _d6_language_id         = ((_cm_d6.default_language_id or "").strip() if _cm_d6 else "")

    # D5: currency — use sale-line dominant; default_currency as fallback
    _d5_default_ccy = ((_cm_d6.default_currency or "").strip().upper() if _cm_d6 else "")
    if _d5_default_ccy and currency and currency != _d5_default_ccy:
        _vat_warnings_draft.append(
            f"currency_mismatch: draft currency={currency!r} differs from "
            f"customer_master.default_currency={_d5_default_ccy!r} (D5 ADR-027)"
        )

    # Service charge lines — append mapped charges as additional wFirma line items.
    # Uses same module-level wfdb for testability. Unmapped charges are noted
    # (already snapshotted for accounting); they do not block the create.
    if charges:
        _sc_extra_lines, _sc_extra_note = _build_service_charge_lines(charges, currency)
        rlines.extend(_sc_extra_lines)
        if _sc_extra_note and not _sc_wfirma_note:
            _sc_wfirma_note = _sc_extra_note

    # _d3_vies_flag is the structured D3 signal (not a substring check) —
    # True when context==wdt AND vat_eu_valid is not True.
    _vat_freeze = (_resolved_ctx, vat_code_str, _decision_source, _d3_vies_flag)
    return wfirma_client.ProformaRequest(
        client_name                   = client_name,
        client_zip                    = "",
        client_city                   = "",
        lines                         = rlines,
        currency                      = currency,
        wfirma_contractor_id          = contractor_id,
        vat_code_id                   = vat_code_id,
        wfirma_contractor_receiver_id = receiver_id,
        series_id                     = draft_proforma_series,
        payment_method                = _d6_payment_method,
        # ADR-027 D6 — document defaults from customer_master
        payment_terms_days            = _d6_payment_terms_days,
        translation_language_id       = _d6_language_id,
    ), _sc_wfirma_note, _vat_warnings_draft, _vat_freeze


@router.post("/draft/{draft_id}/post", dependencies=[_auth])
def post_proforma_draft_to_wfirma(
    draft_id:  int,
    body:      Dict[str, Any],
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Post an ``approved`` local Proforma Draft to wFirma.

    Body::
        {
          "expected_updated_at": "<iso-utc>",
          "confirm_token": "YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA"
        }

    Outcomes:
      - ``200 {status:"posted", wfirma_proforma_id}`` — wFirma write succeeded
        and the local draft has been transitioned to ``posted``.
      - ``200 {status:"failed"}`` — wFirma rejected; draft is now ``post_failed``.
      - ``400 blocked`` — pre-commit validation failure; no wFirma call,
        no state change.
      - ``409`` — wrong state, stale lock, or draft already posted.
      - ``500`` — wFirma succeeded but local persistence failed; the
        response carries ``wfirma_proforma_id`` so the operator can
        manually adopt via ``POST /adopt-issued/{batch}/{client}``.
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise HTTPException(status_code=400, detail="invalid draft_id")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    operator      = _require_operator(x_operator)
    expected      = str(body.get("expected_updated_at") or "")
    confirm_token = str(body.get("confirm_token") or "")

    # ── Settings gate (no live call when disabled) ─────────────────────────
    if not settings.wfirma_create_proforma_allowed:
        return _post_validation_error(
            draft_id,
            "wfirma proforma create disabled "
            "(WFIRMA_CREATE_PROFORMA_ALLOWED=false)",
        )

    db = _proforma_db_path()

    # ── Pre-flight inspection (no state change yet) ────────────────────────
    pre = pildb.get_draft_by_id(db, int(draft_id))
    if pre is None:
        raise HTTPException(status_code=404, detail=f"draft {draft_id} not found")
    if (pre.wfirma_proforma_id or "").strip():
        raise HTTPException(
            status_code=409,
            detail=f"draft {draft_id} already has wfirma_proforma_id="
                   f"{pre.wfirma_proforma_id!r}",
        )

    # ── SINGLE READINESS AUTHORITY (split-authority fix) ───────────────────
    # Forced revalidation: an already-approved draft that has since gained
    # blockers (new packing upload, customer-master change, product mapping
    # removed) is re-checked here and blocked BEFORE start_post and BEFORE
    # any wFirma call. Approve-time readiness is never trusted at post time.
    _post_ready = _derive_draft_readiness(pre, intent="post")
    if not _post_ready["ready"]:
        _record_readiness_block(db, int(draft_id), _post_ready, operator)
        return _post_validation_errors(draft_id, _post_ready)

    # ── Zero-price guard ───────────────────────────────────────────────────
    # PR 2C.2: every line must carry a positive unit_price before posting.
    # Lines with unit_price == 0 indicate the EUR billing price was never
    # populated (packing list not yet promoted, or an old draft created
    # before the price passthrough was deployed).  The operator must
    # reset the draft from the packing list to pick up real prices.
    try:
        _pre_lines = json.loads(pre.editable_lines_json or "[]") or []
    except Exception:
        _pre_lines = []
    zero_price_lines = [
        ln for ln in _pre_lines
        if float(ln.get("unit_price", 0) or 0) <= 0
    ]
    if zero_price_lines:
        return _post_validation_error(
            draft_id,
            f"{len(zero_price_lines)} line(s) have unit_price ≤ 0 — "
            "refresh prices from packing list before posting",
        )

    # Governance: hs_code required on all lines (customs requirement).
    # No-op when proforma_draft_governance_enabled=False.
    try:
        check_post_readiness(_pre_lines)
    except ValueError as exc:
        return _post_validation_error(draft_id, str(exc))

    # Build the wFirma request from persisted fields BEFORE start_post —
    # this surfaces missing-mapping / mixed-currency / service-charge
    # blockers without ever leaving the draft in `posting`.
    try:
        req, _sc_post_note, _post_vat_warnings, _vat_freeze = (
            _build_proforma_request_from_draft(pre)
        )
    except ValueError as exc:
        return _post_validation_error(draft_id, str(exc))

    # Receiver preflight (live wFirma read; same as legacy /create)
    receiver_id = (req.wfirma_contractor_receiver_id or "").strip()
    if receiver_id:
        try:
            rcv = wfirma_client.fetch_contractor_by_id(receiver_id)
        except Exception as exc:
            return _post_validation_error(
                draft_id,
                f"receiver preflight failed: {type(exc).__name__}: {exc}",
            )
        if not rcv.ok:
            return _post_validation_error(
                draft_id,
                f"receiver contractor id {receiver_id!r} not found in wFirma — "
                f"{rcv.error or 'unavailable'}",
            )

    # ── Commit point: approved → posting ───────────────────────────────────
    try:
        posting = pildb.start_post(
            db, int(draft_id), operator, expected,
            confirm_token=confirm_token,
        )
    except pildb.DraftNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except pildb.DraftConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except pildb.DraftNotEditable as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # ── D4 freeze: write vat_context/vat_code/decision_source now that ────────
    # start_post has taken the optimistic lock and transitioned to 'posting'.
    # The freeze UPDATE changes updated_at, but start_post already succeeded
    # so the lock is no longer in use. Best-effort: never blocks the post.
    try:
        _f_ctx, _f_code, _f_src, _f_d3 = _vat_freeze
        pildb.freeze_draft_vat_context(
            db, posting.id,
            vat_context     = _f_ctx,
            vat_code        = _f_code,
            decision_source = _f_src,
        )
    except Exception as _fe:
        log.warning("[draft %s] freeze_draft_vat_context failed (non-fatal): %s",
                    draft_id, _fe)

    # ── D3 VIES advisory (ADR-027): write Inbox proposal for vies_unverified ──
    # Keyed off the structured _f_d3 flag (context==wdt + vat_eu_valid not True)
    # — NOT a substring of the warning text, so wording changes don't silently
    # break advisory firing.
    # Acknowledge-and-proceed — never blocks the post; never silent-downgrade.
    if _f_d3:
        try:
            from ..pipelines.pz import _advisory_to_action_proposal, _write_advisory_proposal
            _vies_audit = (
                settings.storage_root / "outputs"
                / (pre.batch_id or f"draft-{draft_id}") / "audit.json"
            )
            # Pull the human-readable message from vat_warnings if present;
            # fall back to a default so advisory still fires even if warning list
            # is empty (structured flag is the source of truth).
            _vies_msg_candidates = [
                w for w in (_post_vat_warnings or [])
                if "vies_unverified" in w.lower()
            ]
            _vies_adv = {
                "code":    "vies_unverified",
                "message": (_vies_msg_candidates[0] if _vies_msg_candidates else
                            "WDT context applied but VIES validity not confirmed "
                            "(D3 ADR-027). Operator acknowledged and proceeded."),
                "action":  (
                    "Verify the customer's EU VAT number via VIES "
                    "(https://ec.europa.eu/taxation_customs/vies/) or set "
                    "vat_mode override on the customer master."
                ),
            }
            _vies_proposal = _advisory_to_action_proposal(
                _vies_adv,
                batch_id  = pre.batch_id or f"draft-{draft_id}",
                trigger_source = "proforma_post_d3_vies",
            )
            _write_advisory_proposal(_vies_audit, _vies_proposal)
        except Exception as _d3_exc:
            log.warning("[draft %s] D3 vies advisory write (non-fatal): %s",
                        draft_id, _d3_exc)

    # ── Live wFirma call ──────────────────────────────────────────────────
    try:
        result = wfirma_client.create_proforma_draft(req)
    except Exception as exc:
        # Network / runtime / verify-after-create failure (TRANSIENT).
        # Move to post_failed; operator can re-open + edit + approve to retry.
        error_str = f"{type(exc).__name__}: {exc}"
        try:
            pildb.mark_post_failed(
                db, int(draft_id),
                error=error_str,
                operator=operator,
            )
        except Exception as inner:
            log.error("[draft %s] mark_post_failed itself failed: %s",
                      draft_id, inner)

        # B9 recovery: create a wfirma_post_retry proposal if the type is
        # enabled. The bare error STILL returns unchanged; the proposal is
        # additive and non-fatal.
        try:
            from ..services.wfirma_recovery import (
                create_wfirma_proposal, recovery_enabled_types,
            )
            _b9_type = "wfirma_post_retry"
            if _b9_type in recovery_enabled_types():
                _audit_path = (
                    settings.storage_root / "outputs"
                    / (pre.batch_id or f"draft-{draft_id}") / "audit.json"
                )
                _audit_path.parent.mkdir(parents=True, exist_ok=True)
                import json as _jb9
                _b9_audit = (
                    _jb9.loads(_audit_path.read_text(encoding="utf-8"))
                    if _audit_path.exists()
                    else {"batch_id": pre.batch_id or "", "action_proposals": []}
                )
                create_wfirma_proposal(
                    audit=_b9_audit,
                    batch_id=pre.batch_id or f"draft-{draft_id}",
                    proposal_type=_b9_type,
                    context={
                        "draft_id":       int(draft_id),
                        "batch_id":       pre.batch_id or "",
                        "client_name":    pre.client_name or "",
                        "error_message":  error_str,
                        "failed_at":      pre.post_failed_at or "",
                        "posted_by":      operator,
                    },
                    resolution_data={},
                    reason=(
                        f"Transient wFirma failure on draft #{draft_id}: {error_str}"
                    ),
                )
                from ..utils.io import write_json_atomic
                write_json_atomic(_audit_path, _b9_audit)
        except Exception as _b9_exc:
            log.warning("[draft %s] B9 proposal creation failed (non-fatal): %s",
                        draft_id, _b9_exc)

        return JSONResponse({
            "ok":          False,
            "status":      "failed",
            "draft_id":    int(draft_id),
            "error":       error_str,
        })

    if not result.ok:
        try:
            pildb.mark_post_failed(
                db, int(draft_id),
                error=(result.error or "wfirma create_proforma_draft returned ok=false"),
                operator=operator,
            )
        except Exception as inner:
            log.error("[draft %s] mark_post_failed itself failed: %s",
                      draft_id, inner)
        return JSONResponse({
            "ok":          False,
            "status":      "failed",
            "draft_id":    int(draft_id),
            "error":       result.error or "unknown",
        })

    # ── wFirma success → mark posted ──────────────────────────────────────
    wfirma_id   = result.wfirma_invoice_id or ""
    full_number = getattr(result, "wfirma_invoice_number", "") or ""

    try:
        posted = pildb.mark_post_succeeded(
            db, int(draft_id),
            wfirma_proforma_id         = wfirma_id,
            wfirma_proforma_fullnumber = full_number,
            operator                   = operator,
        )
    except Exception as exc:
        # The dangerous case: wFirma created the Proforma but our DB
        # write failed. Record an orphan event (best effort) and return
        # 500 with wfirma_proforma_id so the operator can adopt.
        log.error(
            "[draft %s] wFirma success (id=%s) but local mark_post_succeeded "
            "failed: %s — orphan recovery required",
            draft_id, wfirma_id, exc,
        )
        recorded = pildb.record_post_orphan(
            db, int(draft_id),
            wfirma_proforma_id = wfirma_id,
            error              = f"{type(exc).__name__}: {exc}",
            operator           = operator,
        )
        return JSONResponse(
            status_code=500,
            content={
                "ok":                  False,
                "status":              "orphan",
                "draft_id":            int(draft_id),
                "wfirma_proforma_id":  wfirma_id,
                "error":               f"{type(exc).__name__}: {exc}",
                "orphan_event_recorded": bool(recorded),
                "recovery_hint":       "use POST /api/v1/proforma/adopt-issued/"
                                       "{batch}/{client} with the wfirma_proforma_id "
                                       "above to re-link",
            },
        )

    # ── Phase 6F.5 dual-write hook (feature-flagged, default OFF) ─────────
    # Fires ONLY after mark_post_succeeded returns successfully. Failure-
    # isolated: any exception is swallowed inside the helper. Does not
    # alter the response shape or status code. See approval package
    # tasks/phase-6f-5-dual-write-approval-package.md.
    if settings.finance_dual_write_enabled:
        try:
            from ..services.finance_dual_write import dual_write_proforma_post
            dual_write_proforma_post(
                db_path              = settings.storage_root / "finance_postings.sqlite",
                batch_id             = posted.batch_id or "",
                client_name          = posted.client_name or "",
                currency             = posted.currency or "",
                full_number          = full_number,
                service_charges_json = posted.service_charges_json,
                enabled              = settings.finance_dual_write_enabled,
                shadow               = settings.finance_dual_write_shadow,
            )
        except Exception as exc:
            log.warning("[draft %s] finance_dual_write hook failed: %s",
                        draft_id, exc)

    # ── Audit trail (best-effort, post-state-commit) ──────────────────────
    try:
        from ..services.audit_persist import record_proforma_issued
        audit_path = settings.storage_root / "outputs" / posted.batch_id / "audit.json"
        record_proforma_issued(
            audit_path,
            batch_id                   = posted.batch_id,
            client_name                = posted.client_name,
            wfirma_proforma_id         = wfirma_id,
            wfirma_proforma_fullnumber = full_number,
            line_count                 = len(json.loads(posted.editable_lines_json or "[]") or []),
            currency                   = posted.currency or "",
            operator                   = operator,
        )
    except Exception as exc:
        log.warning("[draft %s] proforma_issued audit append skipped: %s",
                    draft_id, exc)

    _post_resp: Dict[str, Any] = {
        "ok":                         True,
        "status":                     "posted",
        "draft_id":                   posted.id,
        "wfirma_proforma_id":         wfirma_id,
        "wfirma_proforma_fullnumber": full_number,
        "currency":                   posted.currency,
        # ADR-027 D4 — surface frozen VAT context from the now-updated draft
        "vat_context":                posted.vat_context or "",
        "vat_code":                   posted.vat_code or "",
        "decision_source":            posted.decision_source or "",
        "draft":                      _draft_to_full(posted),
    }
    if _sc_post_note:
        _post_resp["service_charges_note"] = _sc_post_note
    if _post_vat_warnings:
        _post_resp["vat_warnings"] = _post_vat_warnings
    return JSONResponse(_post_resp)


# ── Phase pipeline — batch-level aggregation ──────────────────────────────────

@router.get("/pipeline/{batch_id}", dependencies=[_auth])
def get_proforma_pipeline(batch_id: str):
    """Batch-level proforma pipeline state.

    Returns an aggregated view of:
    - All proforma drafts for the batch (with posting lifecycle metadata)
    - Per-draft wFirma reservation draft status (cross-joined from wfirma_reservation_drafts)
    - Reservation queue stats by status for the batch
    - High-level flags: needs_attention, has_posted, all_posted, client_count

    Designed to feed:
    - Stage 1 Sale card (pipeline summary tiles)
    - ProformaDraftPanel (per-draft posting visibility)
    - Pipeline Summary wFirma pill (lifecycle state)
    """
    from ..services import reservation_db as rdb

    # ── 1. Load all proforma drafts ──────────────────────────────────────────
    proforma_db = _proforma_db_path()
    try:
        drafts = pildb.list_drafts_for_batch(proforma_db, batch_id)
    except Exception as exc:
        log.warning("[pipeline %s] list_drafts_for_batch failed: %s", batch_id, exc)
        drafts = []

    # ── 2. Load wFirma reservation drafts and build lookup ───────────────────
    # wfirma_reservation_drafts is keyed by (batch_id, client_name).
    # It tracks the pre-creation stage (pending/submitting/created/failed)
    # and holds the wfirma_reservation_id once created.
    try:
        res_draft_rows = wfdb.list_reservation_drafts(batch_id)
    except Exception as exc:
        log.warning("[pipeline %s] list_reservation_drafts failed: %s", batch_id, exc)
        res_draft_rows = []

    res_draft_by_client: Dict[str, Dict[str, Any]] = {
        r["client_name"]: r for r in res_draft_rows
    }

    # ── 3. Load reservation queue stats for this batch ───────────────────────
    # Gracefully absent — the queue DB may not yet exist or may not be
    # configured for this batch.
    queue_stats: Dict[str, int] = {}
    try:
        queue_db = settings.storage_root / "reservation_queue.db"
        if queue_db.exists():
            queue_rows = rdb.list_reservation_queue(queue_db, batch_id=batch_id)
            for row in queue_rows:
                s = row.get("status") or "unknown"
                queue_stats[s] = queue_stats.get(s, 0) + 1
    except Exception as exc:
        log.warning("[pipeline %s] reservation queue stats failed: %s", batch_id, exc)

    # ── 4. Build per-draft summaries with reservation status cross-joined ────
    by_state: Dict[str, int] = {}
    enriched_drafts: List[Dict[str, Any]] = []

    for d in drafts:
        summary = _draft_to_summary(d)
        state = d.draft_state or "draft"
        by_state[state] = by_state.get(state, 0) + 1

        # Cross-join reservation draft metadata by client_name
        res = res_draft_by_client.get(d.client_name)
        if res:
            summary["reservation_status"]      = res.get("status")
            summary["wfirma_reservation_id"]   = res.get("wfirma_reservation_id")
            summary["reservation_ready"]       = bool(res.get("ready_to_create"))
            summary["reservation_last_error"]  = res.get("last_error")
            summary["reservation_submitted_at"]= res.get("submitted_at")
        else:
            summary["reservation_status"]      = None
            summary["wfirma_reservation_id"]   = None
            summary["reservation_ready"]       = False
            summary["reservation_last_error"]  = None
            summary["reservation_submitted_at"]= None

        enriched_drafts.append(summary)

    # ── 5. Derive high-level flags ────────────────────────────────────────────
    client_count = len(enriched_drafts)

    # needs_attention: any draft in a failure or stuck-posting state
    attention_states = {"post_failed", "posting"}
    needs_attention = any(
        (d.draft_state in attention_states) for d in drafts
    )
    # post_failed always needs attention; posting needs attention only when
    # posting_started_at is stale (>10 min) — use simple flag for now
    post_failed_count = by_state.get("post_failed", 0)
    if post_failed_count:
        needs_attention = True

    has_posted    = by_state.get("posted", 0) > 0
    all_posted    = client_count > 0 and by_state.get("posted", 0) == client_count
    has_approved  = by_state.get("approved", 0) > 0
    has_draft     = (by_state.get("draft", 0) + by_state.get("editing", 0)) > 0
    has_cancelled = by_state.get("cancelled", 0) > 0

    # pipeline_stage: single highest-priority lifecycle label for the batch
    # (used by Pipeline Summary wFirma pill)
    if post_failed_count:
        pipeline_stage = "post_failed"
    elif all_posted:
        pipeline_stage = "all_posted"
    elif has_posted:
        pipeline_stage = "partial_posted"
    elif has_approved:
        pipeline_stage = "approved"
    elif has_draft:
        pipeline_stage = "drafting"
    elif client_count == 0:
        pipeline_stage = "none"
    else:
        pipeline_stage = "other"

    return JSONResponse({
        "ok":             True,
        "batch_id":       batch_id,
        "client_count":   client_count,
        "pipeline_stage": pipeline_stage,
        "needs_attention": needs_attention,
        "has_posted":     has_posted,
        "all_posted":     all_posted,
        "has_approved":   has_approved,
        "has_draft":      has_draft,
        "has_cancelled":  has_cancelled,
        "by_state":       by_state,
        "queue_stats":    queue_stats,
        "drafts":         enriched_drafts,
    })


# ── Phase 5.5A / 6 — Visibility + Intelligence helpers + endpoints ─────────────

def _master_db_path() -> "Path":
    return settings.storage_root / "master_data.sqlite"


def _carrier_shipment_db_path() -> "Path":
    return settings.storage_root / "carrier_shipments.db"


def _build_shipment_panel(batch_id: Optional[str]) -> Dict[str, Any]:
    """Read-only: returns shipment intelligence for a batch.

    Sources: audit.json (AWB, carrier, clearance_path) + carrier_shipments DB
    (service_product, dimensions). Never raises — bad data returns None fields.
    """
    result: Dict[str, Any] = {
        "awb":             None,
        "carrier":         None,
        "clearance_path":  None,
        "service_product": None,
        "dimensions":      None,
    }
    if not batch_id:
        return result

    # audit.json
    try:
        _audit_path = settings.storage_root / "outputs" / batch_id / "audit.json"
        if _audit_path.exists():
            with open(str(_audit_path), "r", encoding="utf-8") as _af:
                _ad = json.load(_af)
            result["awb"]     = _ad.get("awb") or None
            result["carrier"] = _ad.get("carrier") or None
            _cd = _ad.get("clearance_decision") or {}
            result["clearance_path"] = _cd.get("clearance_path") or None
    except Exception:
        pass

    # carrier_shipments DB (Phase 5 fields: service_product, dimensions_json)
    try:
        from ..services.carrier.persistence.shipment_db import (
            get_shipment_by_batch_id as _get_carrier_shipment,
        )
        _cdb = _carrier_shipment_db_path()
        if _cdb.exists():
            row = _get_carrier_shipment(_cdb, batch_id)
            if row:
                result["service_product"] = row.get("service_product")
                _dims_raw = row.get("dimensions_json")
                if _dims_raw:
                    try:
                        result["dimensions"] = json.loads(_dims_raw)
                    except Exception:
                        result["dimensions"] = None
    except Exception:
        pass

    return result


def _build_draft_readiness_panel(
    draft: "pildb.ProformaDraft",
    lines: List[Dict[str, Any]],
    company_completeness: Dict[str, Any],
    shipment_panel: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a readiness inspection dict.

    Fields: commercial_state (str), blockers (list), warnings (list),
    safe_to_defer (list), ready_for_posting (bool).
    Read-only. Never raises.
    """
    blockers: List[str] = []
    warnings: List[str] = []
    safe_to_defer: List[str] = []

    # Company profile
    if not company_completeness.get("present"):
        blockers.append("Company profile not configured — required for posting.")
    else:
        for f in company_completeness.get("missing_mandatory", []):
            blockers.append(f"Company profile missing mandatory field: {f}")
        for f in company_completeness.get("missing_recommended", []):
            warnings.append(f"Company profile missing recommended field: {f}")

    # Client name
    if not (draft.client_name or "").strip():
        blockers.append("No client name — draft cannot be posted.")

    # Lines
    if not lines:
        blockers.append("No product lines — add at least one line before posting.")
    else:
        zero_price = [ln for ln in lines if float(ln.get("unit_price", 0) or 0) <= 0]
        if zero_price:
            pcs = ", ".join(str(ln.get("product_code", "?")) for ln in zero_price[:5])
            blockers.append(f"Lines with zero/missing price: {pcs}")

        missing_hs = [
            ln for ln in lines
            if not str(ln.get("hs_code") or ln.get("hsn_code") or "").strip()
        ]
        if missing_hs:
            pcs = ", ".join(str(ln.get("product_code", "?")) for ln in missing_hs[:5])
            warnings.append(f"Lines missing HS code (required for customs): {pcs}")

        missing_pl = [
            ln for ln in lines
            if not str(ln.get("name_pl") or "").strip()
        ]
        if missing_pl:
            pcs = ", ".join(str(ln.get("product_code", "?")) for ln in missing_pl[:5])
            warnings.append(f"Lines missing Polish name (name_pl): {pcs}")

    # AWB — optional but worth noting
    if not shipment_panel.get("awb"):
        safe_to_defer.append("AWB not linked — can post without it but limits tracking.")

    # Draft state checks
    state = draft.draft_state or "draft"
    if state == "posted":
        blockers.append("Draft already posted — create a new draft to re-post.")
    elif state == "cancelled":
        blockers.append("Draft is cancelled — cannot post.")
    elif state == "posting":
        warnings.append("Posting already in progress — wait for completion.")
    elif state == "post_failed":
        warnings.append("Previous posting attempt failed — check error and retry.")

    # Derive commercial state label
    if draft.wfirma_proforma_id and state == "posted":
        commercial_state = "posted"
    elif state == "approved":
        commercial_state = "ready_for_posting"
    elif not blockers:
        commercial_state = "ready_for_review"
    elif lines:
        commercial_state = "partial"
    else:
        commercial_state = "draft"

    ready_for_posting = (
        len(blockers) == 0
        and state in ("draft", "editing", "approved")
    )

    return {
        "commercial_state":  commercial_state,
        "blockers":          blockers,
        "warnings":          warnings,
        "safe_to_defer":     safe_to_defer,
        "ready_for_posting": ready_for_posting,
    }


def _build_document_status(draft: "pildb.ProformaDraft") -> Dict[str, Any]:
    """Read-only document status projection."""
    return {
        "has_local_preview":          True,   # always: preview.html endpoint
        "wfirma_issued":              bool(draft.wfirma_proforma_id),
        "wfirma_proforma_id":         draft.wfirma_proforma_id,
        "wfirma_proforma_fullnumber": draft.wfirma_proforma_fullnumber,
        "draft_state":                draft.draft_state,
        "posted_at":                  draft.posted_at,
        "posted_by":                  draft.posted_by,
    }


def _build_product_lines_panel(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Read-only: return a display projection of editable lines.

    Enriches with master_data.sqlite (product_local + product_descriptions)
    for HS code override and PL/EN names where the line lacks them.
    Language policy: PL + EN only — name_sk is never surfaced.
    Never raises; enrichment failures are absorbed silently.
    """
    from ..services.master_data_db import get_product_local as _get_pl
    from ..services import document_db as _ddb_local

    _mdb = _master_db_path()
    _docs_db = getattr(_ddb_local, "_db_path", None)

    # Build name lookup from product_descriptions once (PL + EN only)
    _name_lookup: Dict[str, Dict[str, str]] = {}
    if _docs_db:
        try:
            with sqlite3.connect(str(_docs_db)) as _c:
                _c.row_factory = sqlite3.Row
                for _r in _c.execute(
                    "SELECT product_code, name_pl, name_en FROM product_descriptions"
                ).fetchall():
                    _pc = (_r["product_code"] or "").strip()
                    if _pc:
                        _name_lookup[_pc] = {
                            "name_pl": _r["name_pl"] or "",
                            "name_en": _r["name_en"] or "",
                        }
        except Exception:
            pass

    result = []
    for ln in lines:
        pc = str(ln.get("product_code") or "").strip()

        hs         = str(ln.get("hs_code") or ln.get("hsn_code") or "").strip()
        hs_source  = "line" if hs else None
        origin_country = "IN"

        if pc and _mdb.exists():
            try:
                pl_row = _get_pl(_mdb, pc)
                # Phase 4B Wave 4: only apply the overlay when it is ACTIVE.
                # An inactive overlay means "no overlay" → fall back to the
                # line value / default origin.
                if pl_row and getattr(pl_row, "active", True):
                    origin_country = pl_row.origin_country or "IN"
                    if not hs and pl_row.hs_code_override:
                        hs        = pl_row.hs_code_override
                        hs_source = "product_local"
            except Exception:
                pass

        name_pl = str(ln.get("name_pl") or "").strip()
        name_en = str(ln.get("name_en") or "").strip()
        name_en_source = "line" if name_en else None

        if pc and pc in _name_lookup:
            if not name_pl and _name_lookup[pc].get("name_pl"):
                name_pl = _name_lookup[pc]["name_pl"]
            if not name_en and _name_lookup[pc].get("name_en"):
                name_en        = _name_lookup[pc]["name_en"]
                name_en_source = "product_descriptions"

        result.append({
            "line_id":        ln.get("line_id") or ln.get("id"),
            "product_code":   pc,
            "name_pl":        name_pl,
            "name_en":        name_en,
            "name_en_source": name_en_source,
            "hs_code":        hs,
            "hs_source":      hs_source,
            "origin_country": origin_country,
            "unit_price":     ln.get("unit_price"),
            "qty":            ln.get("qty"),
            "currency":       ln.get("currency"),
        })

    return result


@router.get("/draft/{draft_id}/visibility", dependencies=[_auth])
def get_proforma_draft_visibility(draft_id: int) -> JSONResponse:
    """Phase 5.5A — Operator-facing workflow visibility for a single draft.

    Returns:
    - shipment_panel: AWB, carrier, service_product, dimensions, clearance_path
    - company_completeness: score, missing mandatory/recommended fields
    - readiness: commercial_state, blockers, warnings, safe_to_defer
    - document_status: wfirma_issued, wfirma_proforma_id, draft_state
    - product_lines_panel: per-line display projection (PL+EN names, HS, origin)

    Read-only. No mutations. 404 if draft does not exist.
    """
    d = pildb.get_draft_by_id(_proforma_db_path(), int(draft_id))
    if d is None:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found.")

    # Decode lines once
    try:
        lines: List[Dict[str, Any]] = json.loads(d.editable_lines_json or "[]") or []
    except Exception:
        lines = []
    if not isinstance(lines, list):
        lines = []

    # Company profile + completeness
    try:
        company_profile = get_company_profile(_master_db_path())
    except Exception:
        company_profile = None

    from ..services.proforma_intelligence import (
        company_profile_completeness as _cp_completeness,
    )
    company_completeness = _cp_completeness(company_profile)

    # Panels
    shipment_panel      = _build_shipment_panel(d.batch_id)
    readiness           = _build_draft_readiness_panel(
        d, lines, company_completeness, shipment_panel,
    )
    document_status     = _build_document_status(d)
    product_lines_panel = _build_product_lines_panel(lines)

    return JSONResponse({
        "ok":                   True,
        "draft_id":             draft_id,
        "batch_id":             d.batch_id,
        "client_name":          d.client_name,
        "shipment_panel":       shipment_panel,
        "company_completeness": company_completeness,
        "readiness":            readiness,
        "document_status":      document_status,
        "product_lines_panel":  product_lines_panel,
    })


@router.get("/draft/{draft_id}/intelligence", dependencies=[_auth])
def get_proforma_draft_intelligence(draft_id: int) -> JSONResponse:
    """Phase 6 — AI intelligence lane for a single draft.

    Returns:
    - anomalies: detected price / HS / naming anomalies per line
    - suggestions: inferred missing field values (PL+EN names, HS codes)
    - confidence: overall draft confidence score (0.0–1.0) with sub-scores
    - corpus_size: number of historical posted drafts used for corpus stats

    All values are assistive only. Every suggestion requires operator
    review before downstream action. Language policy: PL + EN only.
    Read-only. 404 if draft does not exist.
    """
    d = pildb.get_draft_by_id(_proforma_db_path(), int(draft_id))
    if d is None:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found.")

    from ..services import proforma_intelligence as _intel

    try:
        lines: List[Dict[str, Any]] = json.loads(d.editable_lines_json or "[]") or []
    except Exception:
        lines = []
    if not isinstance(lines, list):
        lines = []

    # Company profile for confidence scoring
    try:
        company_profile = get_company_profile(_master_db_path())
    except Exception:
        company_profile = None

    cp_info = _intel.company_profile_completeness(company_profile)

    # Corpus stats from posted drafts only (trusted historical data)
    corpus = _intel.build_corpus_stats(_proforma_db_path())

    # Anomaly detection + missing-field inference
    anomalies   = _intel.detect_line_anomalies(lines, corpus=corpus)
    suggestions = _intel.infer_missing_fields(lines, master_db_path=_master_db_path())

    # Confidence scoring
    has_awb = bool(_build_shipment_panel(d.batch_id).get("awb"))
    cp_fields = cp_info.get("fields", {})
    confidence = _intel.score_draft_confidence(
        lines=lines,
        company_profile_present=cp_info["present"],
        company_profile_fields_filled=sum(1 for v in cp_fields.values() if v),
        company_profile_fields_total=len(cp_fields),
        has_shipment_awb=has_awb,
    )

    return JSONResponse({
        "ok":          True,
        "draft_id":    draft_id,
        "batch_id":    d.batch_id,
        "client_name": d.client_name,
        "anomalies": [
            {
                "line_id":      a.line_id,
                "product_code": a.product_code,
                "anomaly_type": a.anomaly_type,
                "severity":     a.severity,
                "message":      a.message,
                "confidence":   a.confidence,
            }
            for a in anomalies
        ],
        "suggestions": [
            {
                "product_code":    s.product_code,
                "field":           s.field,
                "suggested_value": s.suggested_value,
                "confidence":      s.confidence,
                "source":          s.source,
            }
            for s in suggestions
        ],
        "confidence": {
            "overall":  confidence.overall,
            "company":  confidence.company,
            "lines":    confidence.lines,
            "shipment": confidence.shipment,
            "pricing":  confidence.pricing,
        },
        "corpus_size": corpus.corpus_size,
    })


# ── Sprint-24 helper: optional session user (proper Depends, avoids raw Request) ─
def _get_current_user_optional(
    pz_session: Optional[str] = Cookie(default=None),
) -> Optional[dict]:
    """Inject the authenticated user from the session cookie, or None.
    Used by draft_to_invoice_by_id to derive operator server-side.
    Does NOT raise 401/403 — callers handle None themselves.
    """
    if not pz_session:
        return None
    try:
        from ..auth.service import decode_token, get_user_by_id  # noqa: PLC0415
        payload = decode_token(pz_session)
        if not payload:
            return None
        return get_user_by_id(payload.get("sub"))
    except Exception:
        return None


# ── Sprint-24 Screen-B aliases (read + write) ────────────────────────────────
#
# Thin aliases translating draft_id-keyed routes → existing (batch_id,
# client_name)-keyed functions. The POST to-invoice alias is the critical
# addition: it derives operator from the authenticated SESSION (not X-Operator
# header / window.prompt) so Convert-to-Invoice is un-spoofable from the UI.

@router.get(
    "/draft/{draft_id}/to-invoice-preview",
    dependencies=[_auth],
    summary="Sprint-24: preview conversion plan via draft_id (alias)",
)
def draft_to_invoice_preview_by_id(draft_id: int) -> JSONResponse:
    """Read-only alias: resolves draft_id → (batch_id, client_name) and
    delegates to the existing proforma_to_invoice_preview function.

    No write. No wFirma call. Blocked when:
    - draft_id unknown (404)
    - draft has no wfirma_proforma_id (returns blocked)
    - proforma_invoice_links already has an issued link (already converted)
    """
    d = pildb.get_draft_by_id(_proforma_db_path(), int(draft_id))
    if d is None:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found.")
    return proforma_to_invoice_preview(d.batch_id, d.client_name)


@router.get(
    "/draft/{draft_id}/invoice-link",
    dependencies=[_auth],
    summary="Sprint-24: conversion result for a draft (read-only join on proforma_invoice_links)",
)
def get_draft_invoice_link(draft_id: int) -> JSONResponse:
    """Read-only: returns the proforma_invoice_links row for this draft's
    wfirma_proforma_id if one exists, else {ok: false, status: 'not_converted'}.

    The Overview tab uses this to populate wFirma invoice ID and invoice number
    without denormalizing a new column onto proforma_drafts.
    """
    d = pildb.get_draft_by_id(_proforma_db_path(), int(draft_id))
    if d is None:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found.")

    pid = (d.wfirma_proforma_id or "").strip()
    if not pid:
        return JSONResponse({
            "ok":     False,
            "status": "not_converted",
            "reason": "draft has no wfirma_proforma_id — proforma not yet posted to wFirma",
        })

    from ..services import proforma_invoice_link_db as plink
    link_db = settings.storage_root / "proforma_links.db"
    link = plink.get_link_by_proforma(link_db, pid)
    if link is None:
        return JSONResponse({
            "ok":                 False,
            "status":             "not_converted",
            "wfirma_proforma_id": pid,
            "reason":             "no conversion link found — proforma not yet converted to invoice",
        })

    return JSONResponse({
        "ok":                 True,
        "status":             link.status,   # pending | issued | failed | rolled_back
        "wfirma_proforma_id": link.proforma_id,
        "wfirma_proforma_number": link.proforma_number,
        "invoice_id":         link.invoice_id,
        "invoice_number":     link.invoice_number,
        "invoice_total":      str(link.invoice_total) if link.invoice_total else str(link.source_total),
        "currency":           link.currency,
        "notes":              link.notes,
        "converted_at":       link.converted_at,
    })


@router.post(
    "/draft/{draft_id}/to-invoice",
    dependencies=[_auth],
    summary="Sprint-24: convert proforma → invoice via draft_id (session-operator alias)",
)
def draft_to_invoice_by_id(
    draft_id: int,
    body: _FinalInvoiceConfirmReq,
    session_user: Optional[dict] = Depends(_get_current_user_optional),
) -> JSONResponse:
    """POST alias: resolves draft_id → (batch_id, client_name) and delegates to
    the existing proforma_to_invoice function.

    Safety invariants preserved:
    - ALL existing guard rails in proforma_to_invoice() apply unchanged:
      wfirma_create_invoice_allowed flag gate, confirm token, UNIQUE(proforma_id)
      duplicate-conversion guard, pending-link-pre-call, mark_failed, audit event.
    - Operator is derived SERVER-SIDE from the authenticated session (full_name
      or email from the JWT cookie). X-Operator header is NOT accepted — the
      operator identity comes from the session, not from client-controlled input.
    - No wFirma call if wfirma_create_invoice_allowed is False (returns 503).

    Deterministic idempotency key note: the actual guard is UNIQUE(proforma_id)
    on proforma_invoice_links, which is immutable. The key displayed in the
    modal is f"prof-{wfirma_proforma_id[:12]}-conv" — informational only.
    """
    d = pildb.get_draft_by_id(_proforma_db_path(), int(draft_id))
    if d is None:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found.")

    # Derive operator from session via get_current_user_optional Depends.
    # Falls back to "session-user" when authenticated via API key (no session).
    operator = (
        ((session_user or {}).get("full_name") or "").strip()
        or ((session_user or {}).get("email") or "").strip()
        or "session-user"
    )

    return proforma_to_invoice(d.batch_id, d.client_name, body, x_operator=operator)


# ── Phase 9 — Payload disclosure endpoints ───────────────────────────────────

@router.get("/draft/{draft_id}/disclose-post", dependencies=[_auth],
            summary="Phase 9: payload disclosure for proforma post (WF2.4)")
def disclose_proforma_post(draft_id: int) -> JSONResponse:
    """Return the exact payload that would be sent to wFirma on Post.

    Read-only — no wFirma call, no DB write. Operator reviews this before
    clicking the final Post button.
    """
    from ..services.payload_disclosure import build_proforma_post_disclosure
    d = pildb.get_draft_by_id(_proforma_db_path(), int(draft_id))
    if d is None:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found.")
    return JSONResponse(build_proforma_post_disclosure(d))


@router.get("/draft/{draft_id}/disclose-convert", dependencies=[_auth],
            summary="Phase 9: payload disclosure for proforma→invoice convert (WF2.5)")
def disclose_proforma_convert(
    draft_id: int,
    final_series_id: str = "",
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Return the exact payload that would be sent to wFirma on Convert.

    Read-only — fetches the proforma XML from wFirma (no write), builds the
    disclosure. Operator reviews before clicking the final Convert button.
    """
    from ..services.payload_disclosure import build_invoice_convert_disclosure
    from ..services import proforma_to_invoice as p2i

    d = pildb.get_draft_by_id(_proforma_db_path(), int(draft_id))
    if d is None:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found.")
    if not (d.wfirma_proforma_id or "").strip():
        raise HTTPException(
            status_code=422,
            detail="Draft has no wfirma_proforma_id — post to wFirma before converting.",
        )
    try:
        xml  = wfirma_client.fetch_invoice_xml(d.wfirma_proforma_id)
        snap = p2i.parse_proforma_xml(xml)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not fetch proforma from wFirma: {exc}",
        ) from exc

    operator = (x_operator or "").strip() or "unknown"

    # Fetch customer master defaults for payment pre-fill
    _cm_method, _cm_days = "", None
    try:
        from ..services.customer_master_db import get_customer_master as _get_cm
        _cm_d = _get_cm(_customer_master_db_path(), snap.contractor_id)
        if _cm_d:
            _cm_method = (_cm_d.preferred_payment_method or "").strip()
            _cm_days   = _cm_d.payment_terms_days
    except Exception:
        pass

    return JSONResponse(
        build_invoice_convert_disclosure(
            snap,
            final_series_id=final_series_id,
            operator=operator,
            customer_default_method=_cm_method,
            customer_default_days=_cm_days,
        )
    )


# ── Phase 5 — Dual-valuation endpoint ────────────────────────────────────────

@router.get("/{batch_id}/{client_name}/dual-valuation", dependencies=[_auth],
            summary="Phase 5: return purchase (customs) and sales (warehouse) values")
def get_dual_valuation(batch_id: str, client_name: str) -> JSONResponse:
    """Return both value bases for a batch.

    purchase_* = customs / SAD / PZ cost basis (from purchase invoice)
    sales_*    = warehouse / sales value (from sales packing list)

    Read-only. No wFirma call.
    """
    from ..services.dual_valuation import resolve_dual_values, summarize
    result = resolve_dual_values(batch_id, settings.storage_root)
    return JSONResponse(summarize(result))


# (clone_proforma_draft already defined at line 3412 from PR #407 Phase 2/3 — no duplicate needed)


# ─────────────────────────────────────────────────────────────────────────────
# ADR-029 Proforma Workspace — conflict detection foundation (PR-1)
#
# Advisory drift/eligibility detection (ADR-029 §3, a typed extension of ADR-025
# soft validation). All three routes are gated by ``conflict_detection_enabled``
# (default OFF) and return a 200 no-op when the flag is off so the surface is inert until
# the workspace opt-in. Detection is pure / local-only / wFirma-free (ADR-021
# Invariant 7): the customer is resolved from local masters and passed into the
# pure detector; persistence + audit live in proforma_conflict_db.
# ─────────────────────────────────────────────────────────────────────────────

from ..services import proforma_conflict_db as pcdb        # noqa: E402
from ..services.proforma_conflict_detector import (         # noqa: E402
    detect_conflicts as _detect_conflicts,
)
from ..models.vat_resolver import CustomerForVAT as _CustomerForVAT  # noqa: E402


def _proforma_conflicts_db_path():
    """Separate store for advisory conflicts (kept out of proforma_links.db so
    the drafts schema is untouched by this slice)."""
    return settings.storage_root / "proforma_conflicts.db"


def _conflicts_enabled() -> bool:
    return bool(getattr(settings, "conflict_detection_enabled", False))


def _resolve_customer_for_conflicts(draft: "pildb.ProformaDraft"):
    """Local-only resolution: draft → CustomerMaster + CustomerForVAT context.

    Returns ``(customer, vat_context)`` — either may be None when the customer
    cannot be resolved locally. NEVER calls wFirma (ADR-021)."""
    cn = (draft.client_name or "").strip()
    if not cn:
        return None, None
    try:
        cr = _resolve_customer(cn, batch_id=getattr(draft, "batch_id", None))
    except Exception:
        return None, None
    cid = (cr.get("wfirma_customer_id") or "").strip()
    if not cid:
        return None, None
    try:
        customer = get_customer_master(_customer_master_db_path(), str(cid))
    except Exception:
        return None, None
    if customer is None:
        return None, None
    vat_context = _CustomerForVAT(
        country=getattr(customer, "country", None),
        vat_eu_valid=getattr(customer, "vat_eu_valid", None),
    )
    return customer, vat_context


class _ConflictResolveBody(_BaseModel):
    resolution_type:   str
    resolution_reason: Optional[str] = None


@router.post("/draft/{draft_id}/conflicts/scan", dependencies=[_auth],
             summary="ADR-029: detect advisory conflicts for a draft (flag-gated)")
def scan_draft_conflicts(
    draft_id:   int,
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Run the PR-1 conflict detectors against a draft and upsert findings.

    Advisory only — never blocks. Gated by ``conflict_detection_enabled``;
    returns a 200 no-op when off. Pure/local detection; the detector does no wFirma I/O.
    Returns the full current conflict list for the draft (including any prior
    operator-resolved rows) so the UI sees the complete picture.
    """
    if not _conflicts_enabled():
        return JSONResponse({"enabled": False, "draft_id": draft_id, "conflicts": []})

    draft = pildb.get_draft_by_id(_proforma_db_path(), draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"draft {draft_id} not found")

    pid = str(draft_id)
    operator = (x_operator or "").strip() or None
    customer, vat_context = _resolve_customer_for_conflicts(draft)

    detections = _detect_conflicts(
        proforma_id     = pid,
        currency        = getattr(draft, "currency", None),
        vat_code        = getattr(draft, "vat_code", None),
        vat_context     = vat_context,
        service_charges = getattr(draft, "service_charges_json", None),
        customer        = customer,
    )

    db_path = _proforma_conflicts_db_path()
    for d in detections:
        pcdb.upsert_conflict(
            db_path,
            proforma_id     = pid,
            conflict_type   = d.conflict_type,
            severity        = d.severity,
            authority_owner = d.authority_owner,
            field_affected  = d.field_affected,
            current_value   = d.current_value,
            master_value    = d.master_value,
            reason          = d.reason,
            evidence        = d.evidence,
            actor           = operator,
        )

    conflicts = pcdb.list_conflicts(db_path, pid)
    return JSONResponse({
        "draft_id":        draft_id,
        "proforma_id":     pid,
        "detected_count":  len(detections),
        "customer_resolved": customer is not None,
        "conflicts":       [c.to_dict() for c in conflicts],
    })


@router.get("/draft/{draft_id}/conflicts", dependencies=[_auth],
            summary="ADR-029: list advisory conflicts for a draft (flag-gated)")
def list_draft_conflicts(
    draft_id: int,
    statuses: Optional[str] = None,
) -> JSONResponse:
    """List stored conflicts for a draft. ``statuses`` is an optional CSV filter
    (e.g. ``open,acknowledged``). Gated by ``conflict_detection_enabled``."""
    if not _conflicts_enabled():
        return JSONResponse({"draft_id": draft_id, "proforma_id": str(draft_id),
                             "count": 0, "conflicts": []})

    pid = str(draft_id)
    status_filter: Optional[List[str]] = None
    if statuses:
        status_filter = [s.strip() for s in statuses.split(",") if s.strip()] or None

    conflicts = pcdb.list_conflicts(
        _proforma_conflicts_db_path(), pid, statuses=status_filter,
    )
    return JSONResponse({
        "draft_id":    draft_id,
        "proforma_id": pid,
        "count":       len(conflicts),
        "conflicts":   [c.to_dict() for c in conflicts],
    })


@router.post("/draft/{draft_id}/conflicts/{conflict_id}/resolve", dependencies=[_auth],
             summary="ADR-029: apply an operator resolution to a conflict (flag-gated)")
def resolve_draft_conflict(
    draft_id:    int,
    conflict_id: int,
    body:        _ConflictResolveBody,
    x_operator:  Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Apply an operator resolution (use_master_default / override_with_reason /
    regenerate_lines / accept_and_proceed / revert) to one conflict.

    ``override_with_reason`` requires a non-empty ``resolution_reason``.
    The ``X-Operator`` header supplies ``resolved_by`` and is required for
    attribution. Gated by ``conflict_detection_enabled``."""
    if not _conflicts_enabled():
        return JSONResponse({"enabled": False, "draft_id": draft_id})

    operator = (x_operator or "").strip()
    if not operator:
        raise HTTPException(status_code=400, detail="X-Operator header is required")

    db_path = _proforma_conflicts_db_path()
    existing = pcdb.get_conflict(db_path, conflict_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"conflict {conflict_id} not found")
    if str(existing.proforma_id) != str(draft_id):
        raise HTTPException(
            status_code=404,
            detail=f"conflict {conflict_id} does not belong to draft {draft_id}",
        )

    try:
        resolved = pcdb.resolve_conflict(
            db_path,
            conflict_id,
            resolution_type   = body.resolution_type,
            resolution_reason = body.resolution_reason,
            resolved_by       = operator,
            actor             = operator,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return JSONResponse({
        "draft_id":    draft_id,
        "proforma_id": resolved.proforma_id,
        "conflict":    resolved.to_dict(),
    })
