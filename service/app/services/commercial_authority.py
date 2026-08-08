"""Commercial document authority — shared projection + blank-only repair.

Canonical chain:
  Sales Packing (commercial variants / price / Client PO)
    → draft editable_lines (working copy)
    → Proforma / Commercial Packing List / CMR (read)
  Purchase Packing → physical gross/net + product_code identity;
                     may fill BLANK sales variant fields only when Sales
                     Packing never carried them (manual allocation / legacy).
  Product Master product_local.origin_country → ISO origin (never invent).

Incoterm hierarchy (single resolver — no duplicate fields):
  saved draft.incoterm → Customer Master default_incoterm → unset
  UI / Preview / Packing / CMR / Invoice all read the resolved value.

Never invents commercial values. Never invents wfirma_product_id.
wFirma goods writes only through wfirma_product_auto_register (flag-gated).
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)


def resolve_incoterm(
    draft_incoterm: Optional[str] = None,
    cm_default_incoterm: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """ONE Incoterm hierarchy for every commercial consumer.

    Returns ``{"value": str|None, "source": "draft"|"customer_master"|"unset"}``.
    Never invents DAP/EXW — blank stays blank with source ``unset``.
    """
    saved = (draft_incoterm or "").strip().upper()
    if saved:
        return {"value": saved, "source": "draft"}
    cm = (cm_default_incoterm or "").strip().upper()
    if cm:
        return {"value": cm, "source": "customer_master"}
    return {"value": None, "source": "unset"}

# Variant fields that Sales Packing owns for commercial documents.
# client_po is Sales-only (Purchase Packing has no Client PO column).
_VARIANT_FROM_PURCHASE = (
    "karat",
    "metal",
    "metal_color",
    "quality_string",
    "stone_type",
    "size",
    "diamond_weight",
    "color_weight",
    "item_type",
)
_VARIANT_SALES_ONLY = ("client_po",)


def _truthy(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, (int, float)):
        try:
            return float(v) != 0.0
        except (TypeError, ValueError):
            return False
    s = str(v).strip()
    return bool(s) and s not in ("—", "-", "0", "0.0")


def purchase_variant_fields(pl: Dict[str, Any]) -> Dict[str, Any]:
    """Extract commercial-usable variant identity from a purchase packing row."""
    def _wt(key: str) -> float:
        try:
            return float(pl.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    metal = str(pl.get("metal") or "").strip()
    karat = str(pl.get("karat") or "").strip()
    metal_color = str(pl.get("metal_color") or "").strip()
    # Some purchase extracts encode "14KT/W" in metal only.
    if metal and "/" in metal and not karat:
        parts = metal.split("/", 1)
        karat = parts[0].strip()
        if not metal_color and len(parts) > 1:
            metal_color = parts[1].strip()
    return {
        "item_type":      str(pl.get("item_type") or "").strip(),
        "karat":          karat,
        "metal":          metal,
        "metal_color":    metal_color,
        "quality_string": str(pl.get("quality_string") or "").strip(),
        "stone_type":     str(pl.get("stone_type") or "").strip(),
        "size":           str(pl.get("size") or "").strip(),
        "diamond_weight": _wt("diamond_weight"),
        "color_weight":   _wt("color_weight"),
    }


def sales_row_to_draft_input(r: Dict[str, Any], *, currency: str = "") -> Dict[str, Any]:
    """ONE reshape: sales_packing_lines row → draft birth/reset input.

    Replaces duplicated hand-maps in routes_proforma reset and intake callers.
    """
    from .proforma_invoice_link_db import _sales_variant_fields

    qty = r.get("qty", r.get("quantity", 0)) or 0
    try:
        qty_f = float(qty)
    except (TypeError, ValueError):
        qty_f = 0.0
    try:
        up_f = float(r.get("unit_price", 0) or 0)
    except (TypeError, ValueError):
        up_f = 0.0
    cur = str(r.get("currency") or currency or "").upper()
    out = {
        "product_code": str(r.get("product_code") or "").strip(),
        "design_no":    str(r.get("design_no") or "").strip(),
        "qty":          qty_f,
        "unit_price":   up_f,
        "currency":     cur,
        "price_source": str(r.get("price_source") or ""),
        "client_ref":   str(r.get("client_ref") or ""),
        # name_pl generator attrs (fallback only)
        "ctg":     str(r.get("ctg") or r.get("category") or r.get("item_type") or ""),
        "kt":      str(r.get("kt") or r.get("karat") or ""),
        "col":     str(r.get("col") or r.get("metal_color") or ""),
        "quality": str(r.get("quality") or r.get("quality_string") or ""),
        **_sales_variant_fields(r),
    }
    return out


def _purchase_index(batch_id: str) -> Dict[str, Dict[str, Any]]:
    """product_code / design_no → first purchase packing row with variants."""
    from . import packing_db as pdb

    idx: Dict[str, Dict[str, Any]] = {}
    for pl in (pdb.get_packing_lines_for_batch(batch_id) or []):
        fields = purchase_variant_fields(pl)
        if not any(_truthy(fields[k]) for k in _VARIANT_FROM_PURCHASE):
            continue
        pc = str(pl.get("product_code") or "").strip()
        dn = str(pl.get("design_no") or "").strip()
        if pc and pc not in idx:
            idx[pc] = fields
        if dn:
            key = f"dn:{dn.casefold()}"
            if key not in idx:
                idx[key] = fields
    return idx


def enrich_sales_line_blanks_from_purchase(
    sales_ln: Dict[str, Any],
    purchase_idx: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[str]]:
    """Fill only blank variant fields on a sales line from purchase index.

    Never overwrites a non-blank Sales Packing value. Never sets client_po
    from purchase (no such authority).
    """
    pc = str(sales_ln.get("product_code") or "").strip()
    dn = str(sales_ln.get("design_no") or "").strip()
    src = None
    if pc and pc in purchase_idx:
        src = purchase_idx[pc]
    elif dn and f"dn:{dn.casefold()}" in purchase_idx:
        src = purchase_idx[f"dn:{dn.casefold()}"]
    if not src:
        return dict(sales_ln), []
    out = dict(sales_ln)
    filled: List[str] = []
    for k in _VARIANT_FROM_PURCHASE:
        if _truthy(out.get(k)):
            continue
        if _truthy(src.get(k)):
            out[k] = src[k]
            filled.append(k)
    return out, filled


def backfill_sales_variants_from_purchase(batch_id: str) -> Dict[str, Any]:
    """Blank-only UPDATE of sales_packing_lines from purchase packing.

    Safe for legacy sales rows / manual allocations that omitted variants.
    Does not invent Client PO. Does not touch drafts (caller may reset).
    """
    from . import document_db as ddb

    if not batch_id:
        return {"ok": False, "error": "batch_id required"}
    purchase_idx = _purchase_index(batch_id)
    if not purchase_idx:
        return {"ok": True, "batch_id": batch_id, "updated": 0, "reason": "no_purchase_variants"}

    rows = ddb.get_sales_packing_lines(batch_id) or []
    if not rows:
        return {"ok": True, "batch_id": batch_id, "updated": 0, "reason": "no_sales_rows"}

    db_path = getattr(ddb, "_db_path", None)
    if db_path is None:
        return {"ok": False, "error": "document_db not initialised"}

    updated = 0
    field_hits: Dict[str, int] = {}
    with sqlite3.connect(str(db_path)) as con:
        for r in rows:
            enriched, filled = enrich_sales_line_blanks_from_purchase(r, purchase_idx)
            if not filled:
                continue
            rid = r.get("id")
            if not rid:
                continue
            sets = []
            vals: List[Any] = []
            for k in filled:
                sets.append(f"{k}=?")
                vals.append(enriched[k])
                field_hits[k] = field_hits.get(k, 0) + 1
            vals.append(rid)
            con.execute(
                f"UPDATE sales_packing_lines SET {', '.join(sets)} WHERE id=?",
                vals,
            )
            updated += 1
        con.commit()

    log.info(
        "[%s] commercial_authority: backfilled %d sales rows from purchase (%s)",
        batch_id, updated, field_hits,
    )
    return {
        "ok": True,
        "batch_id": batch_id,
        "updated": updated,
        "field_hits": field_hits,
        "purchase_keys": len(purchase_idx),
    }


def repair_editable_draft_from_sales(
    proforma_db: Path,
    draft_id: int,
    operator: str,
) -> Dict[str, Any]:
    """Reset one editable draft from current sales_packing_lines (canonical).

    Uses the same OCC-safe reset as the operator endpoint. Refuses locked states.
    Never invents commercial values — only projects current Sales Packing.
    """
    from . import document_db as ddb
    from . import proforma_invoice_link_db as pildb
    from .proforma_draft_sync import resolve_sales_lines_for_batch

    d = pildb.get_draft_by_id(proforma_db, int(draft_id))
    if d is None:
        return {"ok": False, "draft_id": draft_id, "error": "not_found"}
    state = (d.draft_state or "").strip()
    if state not in ("draft", "editing", "post_failed", ""):
        return {
            "ok": False,
            "draft_id": draft_id,
            "error": "locked_state",
            "state": state,
        }

    all_rows = ddb.get_sales_packing_lines(d.batch_id) or []
    target = (d.client_name or "").strip().upper()
    matched = [
        r for r in all_rows
        if (r.get("client_name") or "").strip().upper() == target
    ]
    if not matched:
        return {"ok": False, "draft_id": draft_id, "error": "no_sales_rows"}

    sales_lines = [
        sales_row_to_draft_input(r, currency=d.currency or "")
        for r in matched
    ]
    sales_lines, _resolution = resolve_sales_lines_for_batch(d.batch_id, sales_lines)
    try:
        updated = pildb.reset_draft_from_sales_packing(
            proforma_db,
            int(draft_id),
            operator,
            d.updated_at,
            sales_lines=sales_lines,
            reset_all=False,
            name_pl_lookup=ddb.get_product_description,
            desc_generate=None,
        )
    except Exception as exc:
        return {
            "ok": False,
            "draft_id": draft_id,
            "error": type(exc).__name__,
            "detail": str(exc),
            "state": state,
        }
    return {
        "ok": True,
        "draft_id": draft_id,
        "batch_id": d.batch_id,
        "client": d.client_name,
        "state": state,
        "lines": len(sales_lines),
        "new_updated_at": getattr(updated, "updated_at", None),
    }


def persist_matched_sales_product_codes(batch_id: str) -> Dict[str, Any]:
    """Re-run invoice-scoped sales matcher and persist newly resolved codes.

    Purchase packing arriving after sales intake left empty product_codes
    (JR00819 class). Sync/reset previously used a weaker resolver and never
    wrote resolved codes back — this closes that gap without inventing codes.
    """
    from . import document_db as ddb
    from .sales_packing_matcher import match_sales_lines_to_packing

    if not (batch_id or "").strip():
        return {"ok": False, "error": "batch_id required", "updated": 0}
    rows = ddb.get_sales_packing_lines(batch_id) or []
    if not rows:
        return {"ok": True, "batch_id": batch_id, "updated": 0, "reason": "no_sales"}

    matched, summary = match_sales_lines_to_packing(batch_id, rows)
    updated = 0
    for before, after in zip(rows, matched):
        old_pc = str(before.get("product_code") or "").strip()
        new_pc = str(after.get("product_code") or "").strip()
        rid = str(before.get("id") or "").strip()
        if old_pc or not new_pc or not rid:
            continue
        if ddb.update_sales_packing_line_product_code(batch_id, rid, new_pc):
            updated += 1
    log.info(
        "[%s] commercial_authority: persisted %d sales product_codes "
        "(matcher resolved=%s ambiguous=%s)",
        batch_id, updated,
        len(summary.get("designs_resolved") or {}),
        len(summary.get("designs_ambiguous") or {}),
    )
    return {
        "ok": True,
        "batch_id": batch_id,
        "updated": updated,
        "matcher": summary,
    }


def promote_and_enrich_batch_drafts(
    batch_id: str,
    *,
    proforma_db: Path,
    batch_dir: Optional[Path] = None,
    operator: str = "commercial_authority",
) -> Dict[str, Any]:
    """Promote batch descriptions → product_descriptions, enrich editable drafts.

    Uses pz_rows.json when present, else authoritative audit.rows stamps.
    Never invents descriptions. Locked drafts are skipped.
    """
    from ..core.config import settings
    from . import document_db as ddb
    from . import proforma_invoice_link_db as pildb
    from .description_engine import promote_pz_rows_to_product_descriptions

    if batch_dir is None:
        batch_dir = Path(settings.storage_root) / "outputs" / batch_id
    promo = promote_pz_rows_to_product_descriptions(Path(batch_dir), dry_run=False)
    enriched = 0
    failed: List[Dict[str, Any]] = []
    skipped_locked = 0
    # Always enrich editable drafts after promote — even when written==0
    # (descriptions already in product_descriptions, drafts still blank).
    if Path(proforma_db).exists():
        for d in pildb.list_drafts_for_batch(Path(proforma_db), batch_id):
            if (d.draft_state or "") not in getattr(
                pildb, "EDITABLE_STATES", ("draft", "editing", "post_failed")
            ):
                skipped_locked += 1
                continue
            try:
                pildb.enrich_draft_lines(
                    Path(proforma_db), d.id, operator,
                    d.updated_at, ddb.get_product_description,
                )
                enriched += 1
            except Exception as exc:
                failed.append({"draft_id": d.id, "error": str(exc)[:200]})
    return {
        "ok": promo.get("status") in ("ok", "incomplete"),
        "batch_id": batch_id,
        "promote": promo,
        "drafts_enriched": enriched,
        "drafts_failed": failed,
        "drafts_locked_skipped": skipped_locked,
    }


def seed_blank_draft_incoterms(
    batch_id: str,
    *,
    proforma_db: Path,
    operator: str = "commercial_authority",
) -> Dict[str, Any]:
    """Persist Customer Master default_incoterm onto editable drafts that
    have a blank saved incoterm. Never overwrites a saved draft value.
    Never touches posted/converted/approved drafts.
    """
    from ..core.config import settings
    from . import customer_master_db as cmdb
    from . import proforma_invoice_link_db as pildb

    seeded: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    cm_path = Path(settings.storage_root) / "customer_master.sqlite"
    if not Path(proforma_db).exists():
        return {"batch_id": batch_id, "seeded": [], "skipped": [{"reason": "no_proforma_db"}]}

    for d in pildb.list_drafts_for_batch(Path(proforma_db), batch_id):
        state = (d.draft_state or "").strip()
        if state not in getattr(pildb, "EDITABLE_STATES", ("draft", "editing", "post_failed")):
            skipped.append({"draft_id": d.id, "reason": "locked_state", "state": state})
            continue
        if (d.incoterm or "").strip():
            skipped.append({"draft_id": d.id, "reason": "draft_already_set"})
            continue
        cid = (getattr(d, "client_contractor_id", None) or "").strip()
        if not cid:
            skipped.append({"draft_id": d.id, "reason": "no_contractor_id"})
            continue
        try:
            cm = cmdb.get_customer(cm_path, cid) if cm_path.exists() else None
        except Exception as exc:
            skipped.append({"draft_id": d.id, "reason": f"cm_lookup:{exc}"[:120]})
            continue
        cm_def = (getattr(cm, "default_incoterm", None) or "").strip().upper() if cm else ""
        if not cm_def:
            skipped.append({"draft_id": d.id, "reason": "cm_default_unset"})
            continue
        try:
            pildb.update_draft_fields(
                Path(proforma_db), int(d.id),
                {"incoterm": cm_def},
                operator=operator,
                expected_updated_at=d.updated_at,
            )
            seeded.append({
                "draft_id": d.id, "incoterm": cm_def, "source": "customer_master",
            })
        except Exception as exc:
            skipped.append({"draft_id": d.id, "reason": f"write:{exc}"[:160]})
    return {"batch_id": batch_id, "seeded": seeded, "skipped": skipped}


def converge_batch_draft_authority(
    batch_id: str,
    *,
    proforma_db: Path,
    operator: str = "commercial_authority",
    reset_editable: bool = True,
) -> Dict[str, Any]:
    """ONE convergence pass for a batch's commercial draft authority.

    1. Blank-fill thin sales variants from purchase
    2. Rematch + persist sales product_codes (invoice-scoped matcher)
    3. Promote descriptions (pz_rows or audit stamps) + enrich drafts
    4. Optionally reset editable drafts from refreshed sales rows
    5. Converge wFirma product mappings (search → reuse / create-if-allowed)
    6. Seed blank draft Incoterm from Customer Master default
    """
    from . import document_db as ddb
    from . import proforma_invoice_link_db as pildb

    out: Dict[str, Any] = {"batch_id": batch_id, "ok": True}
    out["variants"] = backfill_sales_variants_from_purchase(batch_id)
    out["product_codes"] = persist_matched_sales_product_codes(batch_id)
    out["descriptions"] = promote_and_enrich_batch_drafts(
        batch_id, proforma_db=proforma_db, operator=operator,
    )
    resets: List[Dict[str, Any]] = []
    if reset_editable and Path(proforma_db).exists():
        # Re-reset after product_code persist so dropped JR00819-class lines
        # re-enter editable_lines. Enrich already ran; reset re-resolves name_pl.
        for d in pildb.list_drafts_for_batch(Path(proforma_db), batch_id):
            if (d.draft_state or "") not in ("draft", "editing", "post_failed", ""):
                continue
            resets.append(
                repair_editable_draft_from_sales(
                    Path(proforma_db), int(d.id), operator,
                )
            )
            # Enrich again after reset (reset may clear name_pl then refill).
            try:
                d2 = pildb.get_draft_by_id(Path(proforma_db), int(d.id))
                if d2 is not None:
                    pildb.enrich_draft_lines(
                        Path(proforma_db), d2.id, operator,
                        d2.updated_at, ddb.get_product_description,
                    )
            except Exception as exc:
                resets[-1]["enrich_error"] = str(exc)[:200]
    out["draft_resets"] = resets

    # After PL/EN descriptions exist, converge wFirma goods mapping via the
    # existing auto-register authority (search-first; create only when allowed).
    try:
        from . import wfirma_product_auto_register as _wfar
        out["wfirma_products"] = _wfar.converge_products_for_batch(
            batch_id, operator=operator, auto_adopt_exact=True,
        )
    except Exception as exc:
        out["wfirma_products"] = {"ok": False, "error": str(exc)[:300]}
        out["ok"] = False

    out["incoterms"] = seed_blank_draft_incoterms(
        batch_id, proforma_db=proforma_db, operator=operator,
    )
    return out
