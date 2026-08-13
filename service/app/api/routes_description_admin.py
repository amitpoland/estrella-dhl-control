"""
routes_description_admin.py — Admin UI: edit canonical description_pl / description_en.

Endpoints (require X-API-Key or session cookie):
  GET  /api/v1/description-admin/product/{product_code}
       Return current row + live gate (PASS / WARN / BLOCKED) from validate_description_line().

  POST /api/v1/description-admin/product/{product_code}/validate
       Validate (description_pl, description_en) — no write.

  POST /api/v1/description-admin/product/{product_code}/preview
       Generate a candidate from invoice_lines / product_master — no write.
       Never overwrites an existing manual/canonical row.

  POST /api/v1/description-admin/product/{product_code}/converge-drafts
       Retry PD → editable-draft enrich for this product_code. Posted/converted
       drafts are immutable. Never fabricates wfirma_product_id.

  PUT  /api/v1/description-admin/product/{product_code}
       Save as source='manual' only when gate=PASS; writes master_audit event.
       First-save of a missing row is allowed (operator accepted a PASS candidate).

Authority: product_descriptions table in documents.db (PR #741 / f117086).

Guard: only the product_descriptions MASTER row is edited. Posted / issued /
       locked draft snapshots are immutable — their editable_lines_json is NOT
       touched by PUT/preview. Converge-drafts annotates editable drafts only.
       Generation/save never creates a wFirma product.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..core.audit import audit_safe
from ..core.logging import get_logger
from ..core.security import require_api_key
from ..core.config import settings
from ..services import document_db as ddb
from ..services.description_engine import (
    build_description_line,
    preview_generated_description,
    set_manual_block,
)
from ..services.description_length_policy import validate_description_line

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1/description-admin", tags=["description-admin"])
_auth = Depends(require_api_key)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _vr_dict(vr) -> dict:
    return {
        "ok":                 vr.ok,
        "blocked":            vr.blocked,
        "advisory":           vr.advisory,
        "shorthand_detected": vr.shorthand_detected,
        "pl_chars":           vr.pl_chars,
        "en_chars":           vr.en_chars,
        "combined_chars":     vr.combined_chars,
        "compacted":          vr.compacted,
        "compacted_pl":       vr.compacted_pl,
        "compacted_en":       vr.compacted_en,
        "warnings":           vr.warnings,
    }


def _gate(vr) -> str:
    """PASS / WARN / BLOCKED gate string for UI display."""
    if vr.blocked or not vr.ok:
        return "BLOCKED"
    if vr.warnings:
        return "WARN"
    return "PASS"


def _row_response(row: dict) -> dict:
    pl = (row.get("description_pl") or "").strip()
    en = (row.get("description_en") or "").strip()
    vr = validate_description_line(pl, en)
    return {
        **row,
        "rendered_line": row.get("description_line") or build_description_line(pl, en),
        "gate":          _gate(vr),
        "validation":    _vr_dict(vr),
    }


# ── GET ───────────────────────────────────────────────────────────────────────

@router.get("/product/{product_code:path}", dependencies=[_auth])
def get_product_description_admin(product_code: str) -> JSONResponse:
    """Return current description row + live validation gate."""
    row = ddb.get_product_description(product_code.strip())
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No description row found for product_code={product_code!r}. "
                "Process a shipment or run the description generator first."
            ),
        )
    return JSONResponse(_row_response(row))


# ── POST /validate ────────────────────────────────────────────────────────────

class ValidateRequest(BaseModel):
    description_pl: str = ""
    description_en: str = ""


@router.post("/product/{product_code:path}/validate", dependencies=[_auth])
def validate_description_admin(
    product_code: str,
    body: ValidateRequest,
) -> JSONResponse:
    """Validate (description_pl, description_en) — no write."""
    pl = (body.description_pl or "").strip()
    en = (body.description_en or "").strip()
    vr = validate_description_line(pl, en)
    return JSONResponse({
        "product_code":  product_code.strip(),
        "gate":          _gate(vr),
        "rendered_line": build_description_line(pl, en),
        "validation":    _vr_dict(vr),
    })


# ── PUT (save) ────────────────────────────────────────────────────────────────

class SaveRequest(BaseModel):
    description_pl: str
    description_en: str = ""
    name_pl: Optional[str] = None  # if omitted, existing name_pl is preserved
    item_type: Optional[str] = None
    material_pl: Optional[str] = None
    purpose_pl: Optional[str] = None


@router.post("/product/{product_code:path}/preview", dependencies=[_auth])
def preview_description_admin(product_code: str) -> JSONResponse:
    """Generate a candidate description. Never writes product_descriptions or wFirma."""
    pc = product_code.strip()
    preview = preview_generated_description(pc)
    cand = preview.get("candidate") or {}
    vr = validate_description_line(
        str(cand.get("description_pl") or ""),
        str(cand.get("description_en") or ""),
    )
    return JSONResponse({
        **preview,
        "gate": _gate(vr),
        "validation": _vr_dict(vr),
        "rendered_line": build_description_line(
            str(cand.get("description_pl") or ""),
            str(cand.get("description_en") or ""),
        ),
    })


@router.post("/product/{product_code:path}/converge-drafts", dependencies=[_auth])
def converge_drafts_description_admin(product_code: str) -> JSONResponse:
    """Retry PD → editable-draft enrich. Posted/converted drafts are not touched."""
    from ..services.commercial_authority import enrich_editable_drafts_for_product_code
    pc = product_code.strip()
    links = settings.storage_root / "proforma_links.db"
    result = enrich_editable_drafts_for_product_code(
        pc, proforma_db=links, operator="description-admin-converge",
    )
    return JSONResponse(result)


@router.put("/product/{product_code:path}", dependencies=[_auth])
def save_description_admin(
    product_code: str,
    body: SaveRequest,
    request: Request,
) -> JSONResponse:
    """Save description_pl + description_en as source='manual'. Writes audit event."""
    pc = product_code.strip()
    pl = (body.description_pl or "").strip()
    en = (body.description_en or "").strip()

    before = ddb.get_product_description(pc)

    vr = validate_description_line(pl, en)
    if vr.blocked or not vr.ok or vr.warnings:
        # Spec: save enabled only when gate = PASS. WARN (ok but has warnings)
        # is also rejected so backend and UI agree — no bypass via direct API call.
        raise HTTPException(
            status_code=422,
            detail={
                "error":      _gate(vr),
                "advisory":   vr.advisory,
                "validation": _vr_dict(vr),
            },
        )

    name_pl     = ((body.name_pl or "").strip() or
                   ((before or {}).get("name_pl") or "").strip() or pl)
    material_pl = ((body.material_pl or "").strip() or
                   ((before or {}).get("material_pl") or "").strip())
    purpose_pl  = ((body.purpose_pl or "").strip() or
                   ((before or {}).get("purpose_pl")  or "").strip())
    item_type   = ((body.item_type or "").strip() or
                   ((before or {}).get("item_type")   or "").strip())

    try:
        after = set_manual_block(
            product_code   = pc,
            item_type      = item_type,
            name_pl        = name_pl,
            description_pl = pl,
            material_pl    = material_pl,
            purpose_pl     = purpose_pl,
            description_en = en,
        )
    except Exception as exc:
        log.error("description_admin save failed for %r: %s", pc, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Save failed: {exc}")

    audit_safe(
        "product_descriptions",
        "update",
        pc,
        request=request,
        before=before,
        after=after,
    )

    from ..services.commercial_authority import enrich_editable_drafts_for_product_code
    links = settings.storage_root / "proforma_links.db"
    convergence = enrich_editable_drafts_for_product_code(
        pc, proforma_db=links, operator="description-admin-save",
    )
    payload = _row_response(after)
    payload["incomplete_convergence"] = bool(convergence.get("incomplete_convergence"))
    payload["drafts_enriched"] = int(convergence.get("drafts_enriched") or 0)
    return JSONResponse(payload)
