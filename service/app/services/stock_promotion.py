"""
stock_promotion.py — slice B×7-1b BE-1: shared PURCHASE_TRANSIT → WAREHOUSE_STOCK
stock promotion authority.

OPERATOR DECISION (a) (2026-07-02, verbatim — PROJECT_STATE DECISIONS
"slice B×7-1b BE-1"):
  "App-pipeline PZs only for now. Direct wFirma PZ bookings should not block
  BE-1. Record direct-wFirma PZ auto-promotion as BE-1c / future extension.
  Rule: If PZ is created through Atlas/EJ pipeline, auto-promote
  PURCHASE_TRANSIT -> WAREHOUSE_STOCK. If PZ is created directly inside
  wFirma, it remains manual/exception handling until webhook/poll extension
  is approved."

This module is the ONE shared promotion function (Business Feature
Completeness standard: scheduler/event, Business API, and UI must all call
the same run_<capability>() — never Logic A / Logic B). Callers:

  1. routes_upload PZ-generation flow (internal PZ generated)
       trigger="pz_generated"  source="pz_pipeline"
  2. routes_wfirma.wfirma_pz_create success path (wFirma PZ booked via app)
       trigger="pz_created"    source="wfirma_pz_create"
  3. global_pz_push correction push success path (wFirma PZ booked via app)
       trigger="pz_created"    source="correction_push"

OUT OF SCOPE — BE-1c, parked: a PZ booked DIRECTLY inside wFirma (bypassing
the Atlas/EJ pipeline) is invisible to this hook; the Track B webhook
scheduler carries no warehouse-document events. Such stock remains
manual/exception handling until the webhook/poll extension is approved.

Contract (pinned by test_stock_promotion_be1.py + the pre-existing
test_warehouse_stock_promotion.py suite):
  - IDEMPOTENT SKIP: only pieces currently in PURCHASE_TRANSIT are promoted.
    Pieces already at WAREHOUSE_STOCK or beyond, and packing lines never
    seeded into inventory_state, are counted as skipped — double promotion
    no-ops cleanly, it never raises and never demotes.
  - BEST-EFFORT: this function never raises. A promotion failure must never
    fail the calling PZ flow — the PZ document already exists.
  - SINGLE-WRITER: state changes go through inventory_state_engine.transition()
    only (the engine stays the sole inventory-state writer).
  - AUDIT: the trigger is recorded on every inventory_state_events row; a
    per-batch summary mirror (EV_INVENTORY_WAREHOUSE_STOCK_PROMOTED) and
    per-line failure mirrors (EV_INVENTORY_TRANSITION_FAILED) go to
    audit.json best-effort. Mirror payloads carry NO financial fields.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from . import inventory_state_engine as ise
from . import packing_db as pdb
from ..core import timeline as tl

log = logging.getLogger(__name__)


def run_stock_promotion(
    batch_id: str,
    *,
    trigger: str,
    source: str,
    operator: str = "system",
    note: str = "",
) -> Dict[str, Any]:
    """Promote every PURCHASE_TRANSIT piece of *batch_id* to WAREHOUSE_STOCK.

    Returns {"batch_id", "trigger", "source", "promoted", "skipped", "errors"}.
    Never raises; see module docstring for the full contract.
    """
    result: Dict[str, Any] = {
        "batch_id": batch_id,
        "trigger":  trigger,
        "source":   source,
        "promoted": 0,
        "skipped":  0,
        "errors":   0,
    }
    try:
        lines = pdb.get_packing_lines_for_batch(batch_id)
        for line in lines:
            sc = ""
            try:
                sc = line.get("scan_code") or pdb._compute_scan_code(line)
                if not sc:
                    result["skipped"] += 1
                    continue
                st = ise.get_state(sc)
                # IDEMPOTENT SKIP — unseeded, already promoted, or moved
                # beyond: no-op, never demote, never raise.
                if st is None or st.get("state") != ise.PURCHASE_TRANSIT:
                    result["skipped"] += 1
                    continue
                ise.transition(
                    scan_code = sc,
                    to_state  = ise.WAREHOUSE_STOCK,
                    trigger   = trigger,
                    operator  = operator,
                    note      = note,
                )
                result["promoted"] += 1
            except Exception as _row_exc:
                # Benign-race recheck (verify-pass hardening, 2026-07-02):
                # between get_state and transition a concurrent promoter
                # (receipt confirm, PZ-generation, another create) may have
                # promoted the piece — transition then raises the engine's
                # illegal-transition error although the final state is
                # correct. Re-read: no longer PURCHASE_TRANSIT means a clean
                # skip, not an error, and no failure mirror is emitted.
                _now_st = None
                if sc:
                    try:
                        _now_st = ise.get_state(sc)
                    except Exception:
                        _now_st = None
                if _now_st is not None and _now_st.get("state") != ise.PURCHASE_TRANSIT:
                    result["skipped"] += 1
                    log.info("[%s] stock promotion: %s promoted by a concurrent "
                             "path — counted as skipped", batch_id, sc)
                    continue
                result["errors"] += 1
                log.warning("[%s] stock promotion skipped for one line: %s",
                            batch_id, _row_exc)
                # Best-effort per-line failure mirror — never raises into the
                # loop. Bounded payload: error str truncated to 200 chars.
                try:
                    from .batch_service import get_output_dir as _get_output_dir
                    _audit_path_fail = _get_output_dir(batch_id) / "audit.json"
                    tl.log_event(
                        _audit_path_fail,
                        tl.EV_INVENTORY_TRANSITION_FAILED,
                        trigger_source = source,
                        actor          = "system",
                        detail = {
                            "batch_id":   batch_id,
                            "scan_code":  line.get("scan_code") or pdb._compute_scan_code(line) or "",
                            "to_state":   "warehouse_stock",
                            "error":      str(_row_exc)[:200],
                        },
                    )
                except Exception as _tl_exc:
                    log.warning(
                        "[%s] inventory transition failure mirror failed (non-fatal): %s",
                        batch_id, _tl_exc,
                    )
    except Exception as _outer:
        log.warning("[%s] stock promotion best-effort failure: %s",
                    batch_id, _outer)

    # ── Best-effort per-batch summary mirror — never breaks the caller ───────
    try:
        from .batch_service import get_output_dir as _get_output_dir
        _audit_path = _get_output_dir(batch_id) / "audit.json"
        tl.log_event(
            _audit_path,
            tl.EV_INVENTORY_WAREHOUSE_STOCK_PROMOTED,
            trigger_source = source,
            actor          = "system",
            detail = {
                "batch_id": batch_id,
                "promoted": result["promoted"],
                "skipped":  result["skipped"],
                "errors":   result["errors"],
                "trigger":  trigger,
            },
        )
    except Exception as _tl_exc:
        log.warning("[%s] stock promotion mirror event failed (non-fatal): %s",
                    batch_id, _tl_exc)

    return result
