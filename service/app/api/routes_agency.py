"""
routes_agency.py — External customs agency email pipeline.

POST /api/v1/agency/email-package/{batch_id}
    Build (but do not send) the agency clearance package.
    Persists package to audit["agency_reply_package"] + queues the email.

GET  /api/v1/agency/decision/{batch_id}
    Return the current clearance_decision for a batch.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..auth.dependencies import get_current_user, require_role
from ..core.config import settings
from ..services.clearance_path_alias import is_agency_clearance
from ..core.logging import get_logger
from ..core import timeline as tl
from ..utils.io import write_json_atomic

log = get_logger(__name__)

router   = APIRouter(prefix="/api/v1/agency", tags=["agency"])
_auth    = Depends(get_current_user)
_op_auth = Depends(require_role("admin", "logistics"))

_OUTPUTS = settings.storage_root / "outputs"


# ── Schemas ───────────────────────────────────────────────────────────────────

class AttachmentItem(BaseModel):
    label: str
    path:  str


class AgencyPackageResponse(BaseModel):
    ok:          bool = True
    batch_id:    str
    action:      str = "agency_email_queued"
    status:      str = "queued"
    to:          str               # comma-separated primary recipients
    to_list:     List[str] = []    # full TO list
    cc:          str               # comma-separated CC recipients
    cc_list:     List[str] = []    # full CC list
    subject:     str
    body_pl:     str
    body_en:     str
    attachments: List[AttachmentItem]
    missing:     List[str]
    queued:      bool
    email_id:    str
    errors:      List[str] = []
    warnings:    List[str] = []


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_audit(batch_id: str) -> dict | None:
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / batch_id / "audit.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return None


def _write_audit(batch_id: str, audit: dict) -> None:
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / batch_id / "audit.json"
        if p.exists():
            write_json_atomic(p, audit)
            return


def _audit_path(batch_id: str) -> Path | None:
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / batch_id / "audit.json"
        if p.exists():
            return p
    return None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/email-package/{batch_id}", response_model=AgencyPackageResponse, dependencies=[_op_auth])
async def build_agency_email_package(batch_id: str) -> AgencyPackageResponse:
    """
    Build the customs agency email package for a high-value shipment.

    Requirements:
    - clearance_decision must show external_agency_clearance path
    - Polish description must already be generated

    Queues the email and persists the package to audit["agency_reply_package"].
    Does NOT send — email goes to queue for admin review / MCP pickup.
    """
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    audit = _load_audit(batch_id)
    if audit is None:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found.")

    # ── Guard: must be agency clearance path ──────────────────────────────────
    from ..services.clearance_decision import build_clearance_decision, THRESHOLD_USD
    dec = audit.get("clearance_decision")
    if dec is None:
        # Compute on the fly for legacy batches
        dec = build_clearance_decision(audit)
        audit["clearance_decision"] = dec
        _write_audit(batch_id, audit)

    path = dec.get("clearance_path", "routing_pending")
    if path == "routing_pending":
        # routing_pending means the customs CIF is UNRESOLVED (cif_state unknown),
        # NOT that a raw invoice CIF literally equals 0 — a value can still resolve
        # from AWB Custom Val or the OCR/AI fallback. Report the resolver's honest
        # reason and next action instead of the misleading "invoice CIF is 0".
        from ..services.cif_authority import get_cif_authority
        _cif = get_cif_authority(audit)
        _gap = _cif.get("extraction_gap") or {}
        raise HTTPException(
            status_code=422,
            detail={
                "guard":      "clearance_path_unresolved",
                "error":     (
                    "Clearance path not yet determined — the customs CIF value is "
                    f"unresolved (cif_state={_cif.get('cif_state')}). "
                    + (_cif.get("blocker_reason") or "")
                ).strip(),
                "code":       "clearance_path_unresolved",
                "cif_state":  _cif.get("cif_state"),
                "cif_source": _cif.get("cif_source"),
                "hint":       _gap.get("next_action")
                              or "Re-process the batch with valid invoices, or "
                                 "confirm the AWB customs value, then retry.",
            },
        )
    if not is_agency_clearance(path):
        cif = dec.get("total_value_usd", 0)
        raise HTTPException(
            status_code=422,
            detail=(
                f"Agency email not required: shipment value ${cif:,.2f} ≤ ${THRESHOLD_USD:,.0f}. "
                f"This shipment uses carrier self-clearance (DHL description reply)."
            ),
        )

    # ── Build package ─────────────────────────────────────────────────────────
    from ..services.agency_email_builder import build_agency_package
    from ..services.email_service import queue_email

    try:
        pkg = build_agency_package(audit, batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agency package build failed: {exc}") from exc

    # ── Attachment physical file validation ──────────────────────────────────
    # (a) race-condition guard: files in attachments[] that vanished after builder ran
    _missing_files = [
        a["label"]
        for a in pkg.get("attachments", [])
        if not Path(a.get("path", "")).exists()
    ]
    # (b) builder-reported missing: mandatory files not found during build (e.g. polish desc)
    _builder_missing: List[str] = pkg.get("missing") or []

    _all_missing = _missing_files + _builder_missing
    if _all_missing:
        raise HTTPException(
            status_code=422,
            detail={
                "ok":     False,
                "guard":  "attachment_missing",
                "error":  "One or more required files not found on disk.",
                "missing": _all_missing,
                "hint":   "Re-generate missing files before building the agency email package.",
            },
        )

    # ── Queue email ───────────────────────────────────────────────────────────
    body_text = f"{pkg['body_pl']}\n\n---\n\n{pkg['body_en']}".strip()
    body_html = (
        f"<div style='font-family:sans-serif'>"
        f"<pre style='white-space:pre-wrap'>{pkg['body_pl']}</pre>"
        f"<hr/>"
        f"<pre style='white-space:pre-wrap'>{pkg['body_en']}</pre>"
        f"</div>"
    )
    # ── Validation guard: TO must be present ─────────────────────────────────
    if not pkg.get("to") or not pkg["to"].strip():
        raise HTTPException(
            status_code=422,
            detail={"guard": "missing_recipients", "error": "Agency email has no recipients (TO is empty)."},
        )

    email_id = queue_email(
        to          = pkg["to"],
        subject     = pkg["subject"],
        body_html   = body_html,
        body_text   = body_text,
        batch_id    = batch_id,
        cc          = pkg.get("cc", ""),
        from_address= pkg.get("from_address", ""),
        email_type  = pkg.get("email_type", "agency"),
        # Pass attachment metadata directly so the integrity guard fires
        # on the synchronous SMTP attempt inside queue_email() — before
        # this function writes audit["agency_reply_package"] to disk.
        attachments = pkg.get("attachments", []),
    )

    # ── Persist to audit ──────────────────────────────────────────────────────
    audit["agency_reply_package"] = {
        "to":          pkg["to"],
        "to_list":     pkg.get("to_list", []),
        "cc":          pkg.get("cc", ""),
        "cc_list":     pkg.get("cc_list", []),
        "subject":     pkg["subject"],
        "body_pl":     pkg["body_pl"],
        "body_en":     pkg["body_en"],
        "attachments": pkg["attachments"],
        "email_id":    email_id,
        "built_at":    datetime.now(timezone.utc).isoformat(),
        "status":      "queued",
    }
    audit["clearance_status"] = "agency_email_queued"
    _write_audit(batch_id, audit)

    # ── Timeline ──────────────────────────────────────────────────────────────
    ap = _audit_path(batch_id)
    if ap:
        tl.log_event(
            ap,
            tl.EV_AGENCY_EMAIL_SENT,
            trigger_source="dashboard",
            actor="admin",
            detail={
                "to":          pkg["to"],
                "cc":          pkg.get("cc", ""),
                "subject":     pkg["subject"],
                "email_id":    email_id,
                "attachments": len(pkg["attachments"]),
            },
        )

    return AgencyPackageResponse(
        batch_id    = batch_id,
        to          = pkg["to"],
        to_list     = pkg.get("to_list", []),
        cc          = pkg.get("cc", ""),
        cc_list     = pkg.get("cc_list", []),
        subject     = pkg["subject"],
        body_pl     = pkg["body_pl"],
        body_en     = pkg["body_en"],
        attachments = [AttachmentItem(**a) for a in pkg["attachments"]],
        missing     = pkg["missing"],
        queued      = True,
        email_id    = email_id,
    )


@router.get("/decision/{batch_id}", dependencies=[_auth])
def get_clearance_decision(batch_id: str) -> Dict[str, Any]:
    """Return the current clearance_decision for a batch (or compute it live)."""
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    audit = _load_audit(batch_id)
    if audit is None:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found.")

    from ..services.clearance_decision import build_clearance_decision
    dec = audit.get("clearance_decision") or build_clearance_decision(audit)
    return {"batch_id": batch_id, "clearance_decision": dec}
