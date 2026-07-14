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
import re
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


# Canonical product-variant identity, derived from the purchase packing document
# (invoice_packing_extractor writes these fields into packing_lines).  The order
# is the business-authority order agreed for Slice 1; it is stored verbatim in
# product_master.normalized_design_attributes so the sales-side exact-variant
# matcher (Slice 2) can compare against the Master without re-reading packing
# internals.  This is identity ONLY — it never affects billing or quantity.
_VARIANT_SIGNATURE_FIELDS = (
    "design_no", "karat", "metal_color", "diamond_weight",
    "quality_string", "color_weight", "stone_type", "size",
)


def _sig_text(value: Any) -> str:
    """Uppercase, trim, collapse internal whitespace — for text variant fields."""
    return re.sub(r"\s+", " ", str(value or "").strip().upper())


def _sig_num(value: Any) -> str:
    """Normalise a numeric variant field (weights) to a stable string.

    Blank/zero → '' (absent), otherwise up to 3 decimals with trailing zeros
    trimmed, so ``0.50`` and ``0.5`` produce the identical signature token.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return ""
    if f == 0:
        return ""
    return ("%.3f" % f).rstrip("0").rstrip(".")


def build_variant_signature(row: Dict[str, Any]) -> str:
    """Canonical, order-stable variant signature for one packing row.

    Fields (business-authority order): design_no | karat | metal_color |
    diamond_weight | quality_string | color_weight | stone_type | size.
    Text fields are uppercased/trimmed/whitespace-collapsed; weight fields are
    numeric-normalised.  Pure function — no I/O, no side effects.
    """
    parts: List[str] = []
    for field in _VARIANT_SIGNATURE_FIELDS:
        if field in ("diamond_weight", "color_weight"):
            parts.append(_sig_num(row.get(field)))
        else:
            parts.append(_sig_text(row.get(field)))
    return "|".join(parts)


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
        variant_sig    = build_variant_signature(row)

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
                normalized_design_attributes = variant_sig,
            )
            audit_safe(
                # 'upsert' is the canonical valid audit op (VALID_OPS in
                # core/audit.py). The prior 'cpa_upsert' was rejected by
                # write_audit, so every product_master upsert silently failed
                # to record an audit event. The provenance stays in after.source.
                "product_master", "upsert", product_code,
                actor=actor,
                after={
                    "product_code": product_code,
                    "design_no":    design_no,
                    "batch_id":     batch_id,
                    "variant_signature": variant_sig,
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


def design_to_product_codes(
    batch_id: str,
    *,
    packing_rows: Optional[List[Dict[str, Any]]] = None,
    packing_db_path: Optional[Path] = None,
) -> Dict[str, List[str]]:
    """Canonical {design_no(stripped): [product_code, …]} for the batch.

    Thin delegation to product_authority_resolver.design_to_product_codes.
    CPA is the single service boundary for product-authority reads; callers
    must not import product_authority_resolver.design_to_product_codes directly.
    """
    from .product_authority_resolver import design_to_product_codes as _f  # noqa: PLC0415
    return _f(batch_id, packing_rows=packing_rows, packing_db_path=packing_db_path)


def reconcile_billed_ambiguity(
    ambiguous_design_codes: Dict[str, Any],
    draft_lines: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Reconcile batch-level design_no ambiguity against what is billed.

    Thin delegation to product_authority_resolver.reconcile_billed_ambiguity.
    CPA is the single service boundary for product-authority logic; callers
    must not import product_authority_resolver.reconcile_billed_ambiguity directly.
    """
    from .product_authority_resolver import reconcile_billed_ambiguity as _f  # noqa: PLC0415
    return _f(ambiguous_design_codes, draft_lines)


def analyze_product_code_billing(
    draft_lines: List[Dict[str, Any]],
    available_by_pc: Dict[str, Any],
    invoice_by_pc: Optional[Dict[str, str]] = None,
    unassigned_by_design: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Aggregate billed quantity per product_code vs available quantity.

    Thin delegation to product_authority_resolver.analyze_product_code_billing.
    CPA is the single service boundary for product-authority logic; callers
    must not import product_authority_resolver.analyze_product_code_billing directly.

    ``unassigned_by_design`` (from authority_snapshot) lets the over-bill result
    carry evidence of packing pieces that exist for a code's design but were never
    assigned a product_code — surfaced, never counted as available.
    """
    from .product_authority_resolver import analyze_product_code_billing as _f  # noqa: PLC0415
    return _f(draft_lines, available_by_pc, invoice_by_pc, unassigned_by_design)


__all__ = [
    "upsert_product_master_from_packing",
    "build_variant_signature",
    "authority_snapshot",
    "is_billed_product_code_valid",
    "reconcile_billed",
    "query_sales_resolution",
    "design_to_product_codes",
    "reconcile_billed_ambiguity",
    "analyze_product_code_billing",
]
