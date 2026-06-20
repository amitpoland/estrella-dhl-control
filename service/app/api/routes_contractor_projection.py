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

    # ── 1b. PR-3: canonicalize draft identity to the Customer-Master pick ─────
    # The operator's dropdown selection (client_contractor_id) WINS over a
    # parsed client_name. Rename/supersede existing EDITABLE drafts to the
    # canonical bill_to_name and migrate freight/insurance + reservation.
    # Canonical wins on collision; any dropped non-zero charge is DISCLOSED in
    # the response + log (never silent). Runs BEFORE the sync so the sync finds
    # the canonical draft and cannot spawn a duplicate parsed-name draft.
    from ..services import customer_master_db as _cmdb
    from ..services import proforma_service_charges_db as _psc
    from ..services import wfirma_db as _wfdb
    pf_db = _proforma_db_path()
    cm_path = settings.storage_root / "customer_master.sqlite"
    try:
        _psc.init(pf_db)  # shares proforma_links.db; idempotent
    except Exception:
        pass
    _canon_cache: Dict[str, str] = {}

    def _canonical(cid: str) -> str:
        cid = (cid or "").strip()
        if not cid or not cm_path.is_file():
            return ""
        if cid in _canon_cache:
            return _canon_cache[cid]
        nm = ""
        try:
            rec = _cmdb.get_customer(cm_path, cid)
            if rec is not None:
                nm = (getattr(rec, "bill_to_name", "") or "").strip()
        except Exception:
            nm = ""
        _canon_cache[cid] = nm
        return nm

    # Build old_name → {canonical} sets so an ambiguous name (the SAME parsed
    # client_name resolving to TWO different contractors/canonicals) is detected
    # and SKIPPED rather than silently last-writer-wins wrong-routed.
    name_to_canon: Dict[str, set] = {}
    try:
        for sd in (ddb.get_sales_documents(batch_id) or []):
            old_nm = str(sd.get("client_name") or "").strip()
            canon = _canonical(str(sd.get("client_contractor_id") or ""))
            if canon and old_nm and canon != old_nm:
                name_to_canon.setdefault(old_nm, set()).add(canon)
    except Exception as _rm_exc:
        log.warning("[%s] canonical rename-map build failed (non-fatal): %s",
                    batch_id, _rm_exc)

    rename_map: Dict[str, str] = {}
    ambiguous_renames: List[Dict[str, Any]] = []
    for old_nm, canon_set in name_to_canon.items():
        if len(canon_set) == 1:
            rename_map[old_nm] = next(iter(canon_set))
        else:
            ambiguous_renames.append({"old": old_nm, "canonicals": sorted(canon_set)})
            log.warning(
                "[%s] canonical migration SKIPPED ambiguous name %r → %s "
                "(same parsed name maps to >1 contractor) — operator must reconcile",
                batch_id, old_nm, sorted(canon_set),
            )

    migrations: List[Dict[str, Any]] = []
    dropped_charges: List[Dict[str, Any]] = []
    for old_nm, canon in rename_map.items():
        try:
            rep = pildb.migrate_draft_to_canonical_name(
                pf_db, batch_id, old_nm, canon,
                charge_move=_psc.move_charges_client_name,
                charge_drop=_psc.drop_charges_client_name,
                reservation_migrate=_wfdb.rename_reservation_draft_client,
                operator=actor,
            )
            migrations.append(rep)
            dropped_charges.extend(rep.get("dropped_charges") or [])
        except Exception as _mig_exc:
            log.warning("[%s] draft canonical migration failed (non-fatal) %s→%s: %s",
                        batch_id, old_nm, canon, _mig_exc)
    # Orphan disclosure: if a charge-migration callable failed mid-run, charges
    # can remain under an old (now superseded/renamed-away) name. Surface them so
    # "canonical wins" can never silently strand operator freight.
    orphan_charges: List[Dict[str, Any]] = []
    for old_nm in rename_map:
        try:
            residual = _psc.list_charges(batch_id, old_nm)
        except Exception:
            residual = []
        for c in residual:
            if float(c.get("amount") or 0) > 0:
                orphan_charges.append({**c, "old_client_name": old_nm,
                                       "reason": "migration_incomplete_residual"})
    if orphan_charges:
        log.warning("[%s] contractor backfill: %d residual non-zero charge(s) "
                    "still under old names after migration: %s",
                    batch_id, len(orphan_charges), orphan_charges)

    if dropped_charges:
        log.warning(
            "[%s] contractor backfill DROPPED %d non-zero charge(s) under old "
            "names (canonical-wins, operator-chosen): %s",
            batch_id, len(dropped_charges), dropped_charges,
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
                    "canonical_renames": [
                        {"old": m.get("old_client_name"),
                         "canonical": m.get("canonical_name"),
                         "action": m.get("action"),
                         "renamed": m.get("renamed"),
                         "superseded": m.get("superseded")}
                        for m in migrations
                    ],
                    "dropped_charges": dropped_charges,
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
        "canonical_renames": migrations,
        "ambiguous_renames": ambiguous_renames,
        "dropped_charges": dropped_charges,
        "orphan_charges": orphan_charges,
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
