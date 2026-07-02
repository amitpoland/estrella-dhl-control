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


def _read_wfirma_pz_doc_id(batch_id: str) -> str:
    """Best-effort audit read — '' when unbooked (pz_generated fires before
    the wFirma PZ exists) or when the audit is unreadable. Never raises."""
    try:
        import json
        from .batch_service import get_output_dir
        audit_path = get_output_dir(batch_id) / "audit.json"
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        return str((audit.get("wfirma_export") or {}).get("wfirma_pz_doc_id") or "")
    except Exception:
        return ""


def run_stock_promotion(
    batch_id: str,
    *,
    trigger: str,
    source: str,
    operator: str = "system",
    note: str = "",
) -> Dict[str, Any]:
    """Promote every PURCHASE_TRANSIT piece of *batch_id* to WAREHOUSE_STOCK.

    Returns {"batch_id", "trigger", "source", "promoted", "skipped",
    "errors", "note_no"} — the three counters are INTS (callers needing
    per-line detail read the audit-mirror events, not this dict); "note_no"
    is the Stock Promotion Note ('' when nothing moved); "note_failed": True
    appears ONLY when pieces were promoted but the derivative Note write
    failed (state truth stands; reconcile from inventory_state_events).
    Never raises; see module docstring for the full contract.
    """
    result: Dict[str, Any] = {
        "batch_id": batch_id,
        "trigger":  trigger,
        "source":   source,
        "promoted": 0,
        "skipped":  0,
        "errors":   0,
        "note_no":  "",
    }
    # BE-2: the moved subset, captured in-loop for the Stock Promotion Note.
    moved: list = []
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
                moved.append({
                    "scan_code":           sc,
                    "design_no":           str(line.get("design_no", "") or ""),
                    "batch_no":            str(line.get("batch_no", "") or ""),
                    "invoice_no":          str(line.get("invoice_no", "") or ""),
                    "packing_document_id": str(line.get("packing_document_id", "") or ""),
                    "state_before":        str(st.get("state") or ""),
                    "state_after":         ise.WAREHOUSE_STOCK,
                })
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

    # ── BE-2: Stock Promotion Note (PROJECT_STATE DECISIONS "BE-2 Stock
    # Promotion Note") — ONE Note covering exactly the moved subset; a no-op
    # promotion (nothing moved) produces NO Note. Best-effort by doctrine:
    # STATE TRUTH > DOCUMENT — the transitions above are already committed
    # and must never be rolled back or failed because the derivative
    # document could not be written; a miss is reconcilable from
    # inventory_state_events, so we log LOUDLY and continue.
    if moved:
        try:
            from .stock_promotion_note_db import write_promotion_note
            result["note_no"] = write_promotion_note(
                batch_id         = batch_id,
                moved            = moved,
                trigger          = trigger,
                source           = source,
                operator         = operator,
                reason_note      = note,
                wfirma_pz_doc_id = _read_wfirma_pz_doc_id(batch_id),
            )
        except Exception as _note_exc:
            # Programmatic signal (BE-2b verify-pass hardening): callers must
            # be able to distinguish "promoted with document" from "promoted
            # but the derivative Note failed" without reading logs.
            result["note_failed"] = True
            log.error(
                "[%s] STOCK PROMOTION NOTE WRITE FAILED — %d piece(s) were "
                "promoted but carry NO note document (reconcile from "
                "inventory_state_events): %s",
                batch_id, len(moved), _note_exc,
            )

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
                "note_no":  result["note_no"],
            },
        )
    except Exception as _tl_exc:
        log.warning("[%s] stock promotion mirror event failed (non-fatal): %s",
                    batch_id, _tl_exc)

    return result
