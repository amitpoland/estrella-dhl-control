"""
stock_issue.py — Phase-C Wave 2 slice C-3d: shared WAREHOUSE_STOCK →
SALES_TRANSIT stock-issue authority.

Closes the audit §Q3 / wireframe §B gap #2: the engine trigger
``invoice_issued`` (inventory_state_engine legal-transition table
WAREHOUSE_STOCK → SALES_TRANSIT) existed but was UNREACHABLE — no caller
ever fired it. This module is the ONE shared issue function (Business
Feature Completeness standard: every future caller — invoice conversion
today, WZ verification (Wave-4 C-6a), a Run-Now Business API — calls the
same run_stock_issue(); never Logic A / Logic B). Caller today:

  1. routes_proforma.proforma_to_invoice success epilogue
       trigger="invoice_issued"  source="proforma_convert"

Piece selection (documented default; Lesson N: inventory custody state is
ADVISORY to fiscal actions — this function NEVER blocks or fails an
invoice):
  The piece↔invoice-line linkage is preview-time-only (no persisted
  reservation binding — audit §B). For each billed line (product_code,
  qty), up to int(round(qty)) pieces of that product_code currently in
  WAREHOUSE_STOCK are issued, in deterministic scan_code order. A billed
  quantity that exceeds available WAREHOUSE_STOCK pieces is reported as
  ``shortfall`` (advisory mirror), never an exception.

Contract (pinned by test_stock_issue_c3d.py):
  - IDEMPOTENT SKIP: only pieces currently in WAREHOUSE_STOCK are issued.
    Pieces already at SALES_TRANSIT or beyond are skipped — double issue
    no-ops cleanly, never demotes, never raises.
  - BEST-EFFORT: this function never raises. An issue failure must never
    fail the calling conversion — the wFirma invoice already exists.
  - SINGLE-WRITER: state changes go through
    inventory_state_engine.transition() only.
  - AUDIT: per-batch summary mirror (EV_INVENTORY_SALES_TRANSIT_ISSUED)
    and per-line failure mirrors (EV_INVENTORY_TRANSITION_FAILED) to
    audit.json best-effort. Mirror payloads carry NO financial fields
    (product_code + qty counts only; no prices, no totals).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from . import inventory_state_engine as ise
from . import packing_db as pdb
from ..core import timeline as tl

log = logging.getLogger(__name__)


def run_stock_issue(
    batch_id: str,
    *,
    trigger: str,
    source: str,
    lines: List[Dict[str, Any]],
    client_name: str = "",
    operator: str = "system",
    note: str = "",
) -> Dict[str, Any]:
    """Issue billed pieces of *batch_id* WAREHOUSE_STOCK → SALES_TRANSIT.

    ``lines`` — billed lines, each {"product_code": str, "qty": number}
    (any extra keys ignored). Returns {"batch_id", "trigger", "source",
    "issued", "skipped", "shortfall", "errors"} — counters are INTS;
    per-line detail lives in the audit-mirror events. Never raises; see
    module docstring for the full contract.
    """
    result: Dict[str, Any] = {
        "batch_id":  batch_id,
        "trigger":   trigger,
        "source":    source,
        "issued":    0,
        "skipped":   0,
        "shortfall": 0,
        "errors":    0,
    }
    issued_detail: list = []
    try:
        # Billed piece count per product_code (jewelry lines are integral
        # piece/pair counts; fractional input rounds to nearest piece).
        want: Dict[str, int] = {}
        for ln in lines or []:
            pc = str((ln or {}).get("product_code") or "").strip()
            try:
                q = int(round(float((ln or {}).get("qty") or 0)))
            except Exception:
                q = 0
            if pc and q > 0:
                want[pc] = want.get(pc, 0) + q
        if not want:
            return result

        packing = pdb.get_packing_lines_for_batch(batch_id)
        # Deterministic per-code piece pools, scan_code ascending.
        pool: Dict[str, list] = {}
        for line in packing:
            pc = str(line.get("product_code") or "").strip()
            if pc not in want:
                continue
            sc = line.get("scan_code") or pdb._compute_scan_code(line)
            if sc:
                pool.setdefault(pc, []).append(sc)
        for pc in pool:
            pool[pc] = sorted(set(pool[pc]))

        for pc, qty in sorted(want.items()):
            moved_for_code = 0
            for sc in pool.get(pc, []):
                if moved_for_code >= qty:
                    break
                try:
                    st = ise.get_state(sc)
                    # IDEMPOTENT SKIP — unseeded or not in WAREHOUSE_STOCK:
                    # no-op, never demote, never raise. Pieces already at
                    # SALES_TRANSIT count toward the billed quantity (a
                    # replayed conversion must not drain extra pieces).
                    if st is not None and st.get("state") == ise.SALES_TRANSIT:
                        moved_for_code += 1
                        result["skipped"] += 1
                        continue
                    if st is None or st.get("state") != ise.WAREHOUSE_STOCK:
                        result["skipped"] += 1
                        continue
                    ise.transition(
                        scan_code = sc,
                        to_state  = ise.SALES_TRANSIT,
                        trigger   = trigger,
                        operator  = operator,
                        note      = note or f"invoice issue: {client_name}".strip(),
                    )
                    moved_for_code += 1
                    result["issued"] += 1
                    issued_detail.append({"scan_code": sc, "product_code": pc})
                except Exception as _row_exc:
                    # Benign-race recheck (BE-1 idiom): a concurrent path may
                    # have issued the piece between get_state and transition.
                    _now_st = None
                    try:
                        _now_st = ise.get_state(sc)
                    except Exception:
                        _now_st = None
                    if _now_st is not None and _now_st.get("state") == ise.SALES_TRANSIT:
                        moved_for_code += 1
                        result["skipped"] += 1
                        continue
                    result["errors"] += 1
                    log.warning("[%s] stock issue skipped for %s: %s",
                                batch_id, sc, _row_exc)
                    try:
                        from .batch_service import get_output_dir as _god
                        tl.log_event(
                            _god(batch_id) / "audit.json",
                            tl.EV_INVENTORY_TRANSITION_FAILED,
                            trigger_source = source,
                            actor          = "system",
                            detail = {
                                "batch_id":  batch_id,
                                "scan_code": sc,
                                "to_state":  "sales_transit",
                                "error":     str(_row_exc)[:200],
                            },
                        )
                    except Exception as _tl_exc:
                        log.warning(
                            "[%s] issue failure mirror failed (non-fatal): %s",
                            batch_id, _tl_exc,
                        )
            if moved_for_code < qty:
                result["shortfall"] += qty - moved_for_code
    except Exception as _outer:
        log.warning("[%s] stock issue best-effort failure: %s",
                    batch_id, _outer)

    # ── Best-effort per-batch summary mirror — never breaks the caller ──────
    if result["issued"] or result["shortfall"] or result["errors"]:
        try:
            from .batch_service import get_output_dir as _god2
            tl.log_event(
                _god2(batch_id) / "audit.json",
                tl.EV_INVENTORY_SALES_TRANSIT_ISSUED,
                trigger_source = source,
                actor          = operator or "system",
                detail = {
                    "batch_id":    batch_id,
                    "client_name": client_name,
                    "trigger":     trigger,
                    "issued":      result["issued"],
                    "skipped":     result["skipped"],
                    "shortfall":   result["shortfall"],
                    "errors":      result["errors"],
                    "pieces":      issued_detail[:200],
                },
            )
        except Exception as _sum_exc:
            log.warning("[%s] issue summary mirror failed (non-fatal): %s",
                        batch_id, _sum_exc)

    return result
