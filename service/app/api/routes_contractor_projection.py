"""
routes_contractor_projection.py — PR-2 Contractor-at-Birth backfill + blocks.
==============================================================================

Operator-triggered reconciliation surface for the contractor-at-birth
projection. Two responsibilities, both batch-scoped:

  1. POST /api/v1/admin/contractor-projection/backfill/{batch_id}
     Repairs a historical batch whose sales rows were born before PR-2 carried
     ``shipment_documents.client_contractor_id`` onto the sales chain:
       a. project the contractor authority onto sales_documents +
          sales_packing_lines (idempotent; fills empties only; never changes
          client_name),
       b. re-run the proforma draft sync so contractor-recovered drafts are
          materialised and unresolved documents surface as VISIBLE blocked
          draft-birth records.
     Local-DB only. No wFirma API call, no booking, no SMTP, no external write.

  2. GET /api/v1/admin/contractor-projection/blocks/{batch_id}
     Read the open (or all) draft-birth blocked records for a batch so an
     operator can see exactly why a draft could not be born.

Design rules (mirror AUTHORITY_MAP §Proforma + §Document Readiness):
  * Backfill is operator-driven (require_admin). It never runs automatically.
  * It only PROJECTS the authoritative identity already chosen at intake — it
    never invents a contractor, never mutates financial values, never re-keys
    client_name.
  * Every backfill writes a single audit-timeline event for traceability.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from ..core.config import settings
from ..core.logging import get_logger
from ..core.security import require_api_key
from ..auth.dependencies import require_admin
from ..core import timeline as tl
from ..services import document_db as ddb
from ..services import proforma_invoice_link_db as pildb
from ..services.batch_service import get_output_dir

log = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/admin/contractor-projection",
    tags=["contractor-projection"],
)
_auth       = Depends(require_api_key)
_admin_auth = Depends(require_admin)


def _proforma_db_path() -> Path:
    return settings.storage_root / "proforma_links.db"


def _master_db_path() -> Path:
    return settings.storage_root / "master_data.sqlite"


def _safe_batch_id(batch_id: str) -> str:
    """Validate + return a batch_id safe for filesystem path joins.

    batch_id flows into ``get_output_dir`` (which mkdir's under storage_root).
    Reject path-traversal — matches the canonical guard used across the
    codebase (routes_dashboard / routes_agency), including the Windows
    backslash separator. Raises HTTP 400 on a bad value.
    """
    bid = (batch_id or "").strip()
    if not bid:
        raise HTTPException(status_code=400, detail="batch_id is required")
    if "/" in bid or "\\" in bid or ".." in bid:
        raise HTTPException(status_code=400, detail="Invalid batch_id")
    return bid


@router.post("/backfill/{batch_id}")
def backfill_contractor_projection(
    batch_id: str,
    _admin: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """Project contractor authority onto the sales chain for *batch_id* and
    re-materialise proforma drafts + blocked draft-birth records.

    Idempotent. Safe to re-run. Local-DB only — never calls wFirma / SMTP /
    DHL / booking. (Admin auth is enforced by the ``require_admin`` dependency
    in the signature, which also yields the operator identity for the audit
    actor — declared once to avoid a double dependency run.)
    """
    batch_id = _safe_batch_id(batch_id)
    actor = (
        str((_admin or {}).get("username") or (_admin or {}).get("id") or "operator")
        if isinstance(_admin, dict) else "operator"
    )

    # ── 1. Pure projection (fills empties; never changes client_name) ─────────
    try:
        projection = ddb.backfill_contractor_ids(batch_id)
    except Exception as exc:
        log.warning("[%s] contractor projection backfill failed: %s", batch_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"contractor projection failed: {exc}",
        )

    # Resolve the batch output dir once. When it does not exist (historical
    # batch with no outputs written), audit-timeline events cannot be recorded —
    # surfaced honestly via ``audit_skipped`` rather than a silent gap.
    output_dir = get_output_dir(batch_id)
    audit_available = output_dir.exists()
    if not audit_available:
        log.warning(
            "[%s] contractor backfill: batch output dir absent (%s) — "
            "sync/backfill timeline events skipped (audit_skipped=true)",
            batch_id, output_dir,
        )

    # ── 2. Re-run draft sync so recovered drafts + blocked records appear ─────
    sync_summary: Dict[str, Any] = {}
    try:
        audit_path = (output_dir / "audit.json") if audit_available else None
        from ..services.proforma_draft_sync import sync_draft_from_packing_upload
        sync_summary = sync_draft_from_packing_upload(
            batch_id=batch_id,
            operator="contractor_backfill",
            db_path=_proforma_db_path(),
            audit_path=audit_path,
            master_db_path=_master_db_path(),
        )
    except Exception as exc:
        log.warning("[%s] post-backfill draft sync failed (non-fatal): %s",
                    batch_id, exc)
        sync_summary = {"error": str(exc)}

    # ── 3. Audit trail (best-effort) ──────────────────────────────────────────
    if audit_available:
        try:
            tl.log_event(
                output_dir / "audit.json",
                "contractor_projection_backfill",
                "contractor_projection",
                actor=actor,
                detail={
                    "batch_id":   batch_id,
                    "projection": projection,
                    "sync": {
                        "created":       sync_summary.get("created"),
                        "synced":        sync_summary.get("synced"),
                        "birth_blocked": sync_summary.get("birth_blocked"),
                        "contractor_conflict": sync_summary.get("contractor_conflict"),
                    },
                },
            )
        except Exception as _aexc:  # pragma: no cover - audit best-effort
            log.debug("[%s] backfill audit log failed (non-fatal): %s", batch_id, _aexc)

    blocks = pildb.list_draft_birth_blocks(_proforma_db_path(), batch_id)
    # Honesty signal: a zero-projection result usually means the contractor was
    # never bound on shipment_documents at intake — backfill cannot invent it.
    projection_empty = (
        not projection.get("sales_documents_updated")
        and not projection.get("sales_lines_updated")
    )
    note = (
        "No rows projected — either already projected, or "
        "shipment_documents.client_contractor_id was never set at intake "
        "(re-intake with a contractor selection is required to repair)."
        if projection_empty else ""
    )
    return {
        "ok":         True,
        "batch_id":   batch_id,
        "projection": projection,
        "projection_empty": projection_empty,
        "audit_skipped": not audit_available,
        "note":       note,
        "sync":       sync_summary,
        "open_blocks": blocks,
    }


@router.get("/blocks/{batch_id}", dependencies=[_auth])
def list_blocks(batch_id: str, include_resolved: bool = False) -> Dict[str, Any]:
    """List draft-birth blocked records for a batch (open-only by default)."""
    batch_id = _safe_batch_id(batch_id)
    blocks: List[Dict[str, Any]] = pildb.list_draft_birth_blocks(
        _proforma_db_path(), batch_id, include_resolved=include_resolved,
    )
    return {
        "batch_id":         batch_id,
        "include_resolved": include_resolved,
        "count":            len(blocks),
        "blocks":           blocks,
    }
