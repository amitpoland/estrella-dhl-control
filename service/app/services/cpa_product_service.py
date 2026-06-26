"""
cpa_product_service.py — CPA Phase 1: canonical product-master write boundary.

This module is the ONLY authorised writer for product_master rows at
packing-upload time.  All callers must go through
``upsert_product_master_from_packing()`` rather than calling
``reservation_db.upsert_product_master()`` directly.

Design rules (Phase -1 approval):
  * product_code = PRIMARY identity; design_no = CHILD attribute.
  * product_code is minted ONLY by document_db.store_invoice_lines().
    This service NEVER invents product_codes — it receives them from packing rows.
  * Rows with blank product_code are skipped (warning logged, not an error).
  * All writes call audit_safe() AFTER the primary write (Phase 1 contract).
  * product_authority_resolver is the single read path; this module delegates
    to it and never duplicates its design→product_code derivation logic.
  * No schema changes, no route wiring, no consumer migration (Phase 1 scope).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .reservation_db import upsert_product_master
from .product_authority_resolver import (
    reconcile_billed_lines,
    resolve_batch_product_authority,
    validate_billed_product_code,
)
from ..core.audit import audit_safe

log = logging.getLogger(__name__)


def upsert_product_master_from_packing(
    db_path: Path,
    batch_id: str,
    packing_rows: List[Dict[str, Any]],
    *,
    actor: str = "cpa",
) -> Dict[str, Any]:
    """Write product_master rows from packing upload data.

    Skips rows where product_code is blank — they cannot form a valid PM entry.
    Errors on individual rows are captured and returned; they never abort the
    batch.  Returns a summary dict with counts and per-row errors.

    This is the single authorised CPA write path for packing-time PM population.
    Consumers (packing upload route, Phase 2) must call this instead of calling
    upsert_product_master() directly.
    """
    upserted: List[str] = []
    skipped:  List[str] = []
    errors:   Dict[str, str] = {}

    for row in (packing_rows or []):
        product_code = str(row.get("product_code") or "").strip()
        if not product_code:
            design_hint = str(row.get("design_no") or "").strip()
            skipped.append(design_hint or "<blank>")
            continue

        design_no      = str(row.get("design_no")   or "").strip()
        metal          = str(row.get("metal")        or "").strip()
        item_type      = str(row.get("item_type")    or "").strip()
        source_invoice = str(row.get("invoice_no")   or "").strip()

        try:
            upsert_product_master(
                db_path,
                product_code      = product_code,
                design_no         = design_no,
                metal             = metal,
                item_type         = item_type,
                source_invoice_no = source_invoice,
                source_batch_id   = batch_id,
                last_seen_batch_id= batch_id,
                confidence        = "packing",
            )
            audit_safe(
                "product_master", "cpa_upsert", product_code,
                actor=actor,
                after={
                    "product_code": product_code,
                    "design_no":    design_no,
                    "batch_id":     batch_id,
                    "source":       "cpa_packing",
                },
            )
            upserted.append(product_code)
        except Exception as exc:
            log.error(
                "cpa_product_service: upsert failed for %r in batch %r: %s",
                product_code, batch_id, exc,
            )
            errors[product_code] = str(exc)

    return {
        "batch_id":       batch_id,
        "upserted":       upserted,
        "upserted_count": len(upserted),
        "skipped":        skipped,
        "skipped_count":  len(skipped),
        "errors":         errors,
        "error_count":    len(errors),
    }


def authority_snapshot(
    batch_id: str,
    *,
    packing_rows: Optional[List[Dict[str, Any]]] = None,
    packing_db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Canonical product-authority snapshot for a batch.

    Thin delegation to product_authority_resolver.resolve_batch_product_authority.
    CPA callers should use this rather than importing the resolver directly.
    """
    return resolve_batch_product_authority(
        batch_id,
        packing_rows=packing_rows,
        packing_db_path=packing_db_path,
    )


def is_billed_product_code_valid(
    batch_id: str,
    product_code: str,
    design_no: Optional[str] = None,
    *,
    packing_rows: Optional[List[Dict[str, Any]]] = None,
    packing_db_path: Optional[Path] = None,
) -> bool:
    """True iff product_code exists in packing_lines authority for the batch.

    Thin delegation to product_authority_resolver.validate_billed_product_code.
    """
    return validate_billed_product_code(
        batch_id,
        product_code,
        design_no,
        packing_rows=packing_rows,
        packing_db_path=packing_db_path,
    )


def reconcile_billed(
    batch_id: str,
    draft_lines: List[Dict[str, Any]],
    *,
    ambiguous_design_codes: Optional[Dict[str, Any]] = None,
    packing_rows: Optional[List[Dict[str, Any]]] = None,
    packing_db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Combined ambiguity + over-bill reconciliation against packing authority.

    Thin delegation to product_authority_resolver.reconcile_billed_lines.
    """
    return reconcile_billed_lines(
        batch_id,
        draft_lines,
        ambiguous_design_codes=ambiguous_design_codes,
        packing_rows=packing_rows,
        packing_db_path=packing_db_path,
    )


def query_sales_resolution(batch_id: str) -> List[Dict[str, Any]]:
    """Sales allocation rows for a batch, via the v_sales_to_wfirma read path.

    Thin delegation to document_db.query_sales_to_wfirma.  CPA is the single
    service boundary for all product-authority reads; callers must not import
    document_db.query_sales_to_wfirma directly for authority decisions.
    """
    from .document_db import query_sales_to_wfirma as _q  # noqa: PLC0415
    return _q(batch_id)


__all__ = [
    "upsert_product_master_from_packing",
    "authority_snapshot",
    "is_billed_product_code_valid",
    "reconcile_billed",
    "query_sales_resolution",
]
