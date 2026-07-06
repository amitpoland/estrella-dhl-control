"""
product_master_sync.py — Slice 1: the ONE shared Product Master synchronization.

Composes the EXISTING purchase-side write-authority helpers into a single,
idempotent, observable capability. It creates NO new authority — every write
targets an existing store, through its existing owner:

    packing_lines (per-piece authority, read-only source)
        → cpa_product_service.upsert_product_master_from_packing  (product_master)
        → design_product_bridge.populate_from_packing            (design_product_mapping)
        → description_engine.regenerate_descriptions_for_packing_lines (product_descriptions)
        → wfirma_product_auto_register.ensure_products_for_batch  (wfirma_product_mirror, PREVIEW only)

Governance (Slice 1 constraints):
  * product_code is NEVER minted here — it is read from packing_lines (minted by
    document_db.store_invoice_lines). Blank-product_code rows are skipped.
  * The Master stays ADVISORY — this module reads packing and writes the Master;
    it gates nothing and never blocks billing / packing operations.
  * The wFirma goods step runs in DRY-RUN (match/preview) only — it never creates
    a wFirma product. Live create stays behind wfirma_create_product_allowed and
    the C-1w write-path slices.
  * No schema migration: the variant identity is stored in the existing
    product_master.normalized_design_attributes column (see cpa_product_service
    .build_variant_signature).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from . import reservation_db as rdb

log = logging.getLogger(__name__)


def _db_path() -> Path:
    return settings.storage_root / "reservation_queue.db"


def _distinct_codes(packing_rows: List[Dict[str, Any]]) -> List[str]:
    """Ordered-unique non-blank product_codes present in the packing rows."""
    seen: set = set()
    out: List[str] = []
    for r in (packing_rows or []):
        pc = str(r.get("product_code") or "").strip()
        if pc and pc not in seen:
            seen.add(pc)
            out.append(pc)
    return out


def run_product_master_sync(
    batch_id: str,
    *,
    dry_run: bool = False,
    operator: str = "operator",
) -> Dict[str, Any]:
    """Synchronize the Product Master (and its dependents) from a batch's
    purchase packing list.

    ``dry_run=True``  → preview only: writes NOTHING, reports would-be counts.
                        Does not touch the persisted sync-status row.
    ``dry_run=False`` → writes product_master + design_product_mapping +
                        product_descriptions; wFirma goods step stays preview.

    Returns a summary shaped for the canonical status contract plus the
    per-stage sub-results.
    """
    started = time.time()
    db = _db_path()
    rdb.init_reservation_db(db)

    from . import packing_db as pdb  # local import: packing_db owns its own path

    try:
        packing_rows = pdb.get_packing_lines_for_batch(batch_id) or []
    except Exception as exc:
        log.error("[product_master_sync] packing read failed for %s: %s", batch_id, exc)
        packing_rows = []

    codes = _distinct_codes(packing_rows)
    processed = len(packing_rows)
    # Codes already present in the Master BEFORE this run — used to split
    # created vs updated honestly (get_product_master_statuses returns only the
    # codes that exist).
    existing_before = set(rdb.get_product_master_statuses(db, codes).keys())

    # ── DRY RUN: preview only, no writes, no status mutation ──────────────────
    if dry_run:
        skipped = sum(
            1 for r in packing_rows if not str(r.get("product_code") or "").strip()
        )
        desc = _safe_descriptions(batch_id, dry_run=True)
        mirror = _safe_mirror_preview(batch_id)
        return {
            "batch_id":    batch_id,
            "dry_run":     True,
            "processed":   processed,
            "created":     len([c for c in codes if c not in existing_before]),
            "updated":     len([c for c in codes if c in existing_before]),
            "skipped":     skipped,
            "errors":      0,
            "last_error":  "",
            "duration_ms": int((time.time() - started) * 1000),
            "descriptions": desc,
            "mirror":       mirror,
            "design_mapping": {},
        }

    # ── LIVE RUN ──────────────────────────────────────────────────────────────
    rdb.mark_product_master_sync_started(db, batch_id)
    errors: List[str] = []

    # 1. product_master (+ variant signature) via the single authorised writer.
    from . import cpa_product_service as cpa
    cpa_res = cpa.upsert_product_master_from_packing(
        db, batch_id, packing_rows, actor=operator,
    )
    upserted = set(cpa_res.get("upserted") or [])
    created = len(upserted - existing_before)
    updated = len(upserted & existing_before)
    skipped = int(cpa_res.get("skipped_count") or 0)
    errors.extend(str(v) for v in (cpa_res.get("errors") or {}).values())

    # 2. design_no → product_code registry (idempotent).
    from . import design_product_bridge as bridge
    try:
        bridge_res = bridge.populate_from_packing(batch_id)
        errors.extend(str(e) for e in (bridge_res.get("errors") or []))
    except Exception as exc:
        bridge_res = {"errors": [str(exc)]}
        errors.append(f"design_mapping: {exc}")

    # 3. legal PL/EN descriptions (single description authority).
    desc = _safe_descriptions(batch_id, dry_run=False)
    errors.extend(str(e) for e in (desc.get("errors") or []))

    # 4. wFirma goods MIRROR — preview/match only, never creates.
    mirror = _safe_mirror_preview(batch_id)
    errors.extend(str(e) for e in (mirror.get("errors") or []))

    duration_ms = int((time.time() - started) * 1000)
    last_error = errors[0] if errors else ""
    rdb.mark_product_master_sync_finished(
        db, batch_id,
        processed=processed, created=created, updated=updated,
        skipped=skipped, errors=len(errors), last_error=last_error,
        duration_ms=duration_ms,
    )

    log.info(
        "[product_master_sync] batch=%s processed=%d created=%d updated=%d "
        "skipped=%d errors=%d dur=%dms",
        batch_id, processed, created, updated, skipped, len(errors), duration_ms,
    )
    return {
        "batch_id":    batch_id,
        "dry_run":     False,
        "processed":   processed,
        "created":     created,
        "updated":     updated,
        "skipped":     skipped,
        "errors":      len(errors),
        "last_error":  last_error,
        "duration_ms": duration_ms,
        "descriptions": desc,
        "mirror":       mirror,
        "design_mapping": bridge_res,
    }


# ── defensive step wrappers (a downstream outage must not crash the sync) ─────

def _safe_descriptions(batch_id: str, *, dry_run: bool) -> Dict[str, Any]:
    from . import description_engine as deng
    try:
        return deng.regenerate_descriptions_for_packing_lines(
            batch_id=batch_id, dry_run=dry_run,
        )
    except Exception as exc:
        log.warning("[product_master_sync] descriptions step failed: %s", exc)
        return {"errors": [f"descriptions: {exc}"]}


def _safe_mirror_preview(batch_id: str) -> Dict[str, Any]:
    """wFirma goods mirror in DRY-RUN — search/match only, zero create calls."""
    from . import wfirma_product_auto_register as auto
    try:
        return auto.ensure_products_for_batch(batch_id, dry_run=True)
    except Exception as exc:
        log.warning("[product_master_sync] mirror preview failed: %s", exc)
        return {"errors": [f"mirror: {exc}"]}


def get_status(batch_id: Optional[str] = None) -> Dict[str, Any]:
    """Canonical status envelope for the Product Master sync.

    Returns the four-questions contract fields. When no run has been recorded,
    returns an honest 'never run' envelope (healthy, not running, blank times).
    """
    row = rdb.get_product_master_sync_status(_db_path(), batch_id)
    if row is None:
        return {
            "batch_id":          batch_id or "",
            "healthy":           True,
            "running":           False,
            "last_started_at":   None,
            "last_completed_at": None,
            "duration_ms":       0,
            "processed":         0,
            "created":           0,
            "updated":           0,
            "skipped":           0,
            "errors":            0,
            "last_error":        None,
            "ever_run":          False,
        }
    return {
        "batch_id":          row.get("batch_id") or "",
        "healthy":           bool(row.get("healthy", 1)),
        "running":           bool(row.get("running", 0)),
        "last_started_at":   row.get("last_started_at") or None,
        "last_completed_at": row.get("last_completed_at") or None,
        "duration_ms":       int(row.get("duration_ms") or 0),
        "processed":         int(row.get("processed") or 0),
        "created":           int(row.get("created") or 0),
        "updated":           int(row.get("updated") or 0),
        "skipped":           int(row.get("skipped") or 0),
        "errors":            int(row.get("errors") or 0),
        "last_error":        row.get("last_error") or None,
        "ever_run":          True,
    }
