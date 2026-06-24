"""
routes_description_admin.py — Admin UI: edit canonical description_pl / description_en.

Endpoints (require X-API-Key or session cookie):
  GET  /api/v1/description-admin/product/{product_code}
       Return current row + live gate (PASS / WARN / BLOCKED) from validate_description_line().

  POST /api/v1/description-admin/product/{product_code}/validate
       Validate (description_pl, description_en) — no write.

  PUT  /api/v1/description-admin/product/{product_code}
       Save as source='manual'; writes master_audit event.

Authority: product_descriptions table in documents.db (PR #741 / f117086).

Guard: only the product_descriptions MASTER row is edited. Posted / issued /
       locked draft snapshots are immutable — their editable_lines_json is NOT
       touched. Future drafts pick up new values via get_description_block().
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..core.audit import audit_safe
from ..core.logging import get_logger
from ..core.security import require_api_key
from ..services import document_db as ddb
from ..services.description_engine import build_description_line, set_manual_block
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
    if before is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No description row found for product_code={pc!r}. "
                "Process a shipment or run the description generator first."
            ),
        )

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
                   (before.get("name_pl") or "").strip())
    material_pl = (before.get("material_pl") or "").strip()
    purpose_pl  = (before.get("purpose_pl")  or "").strip()
    item_type   = (before.get("item_type")   or "").strip()

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

    return JSONResponse(_row_response(after))
