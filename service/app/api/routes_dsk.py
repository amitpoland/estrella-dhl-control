"""
routes_dsk.py — DSK Broker Notification PDF API endpoints.

POST /api/v1/dsk/generate            — generate DSK PDF for a DHL shipment
GET  /api/v1/dsk/download/{filename} — download a generated DSK PDF
POST /api/v1/dsk/email-package       — build email package for a batch (does NOT send)
GET  /api/v1/dsk/audit-log           — return dsk_audit_log.json sorted newest first
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ..core.config import settings
from ..core.logging import get_logger
from ..core.security import require_api_key
from ..auth.dependencies import require_role
from ..core.guards import guard_dhl_requires_email
from ..core import timeline as tl
from ..utils.io import write_json_atomic

log      = get_logger(__name__)

router   = APIRouter(prefix="/api/v1/dsk", tags=["dsk"])
_auth    = Depends(require_api_key)
_op_auth = Depends(require_role("admin", "logistics"))

# ── Output directory ──────────────────────────────────────────────────────────
_DSK_OUTPUT_DIR = (
    Path(os.environ.get("APPDATA", ""))
    / "estrellajewels" / "storage" / "dsk_outputs"
    if os.name == "nt"
    else Path.home() / "Library" / "Application Support" / "estrellajewels" / "storage" / "dsk_outputs"
)
# Fall back to storage_root if home-based path is unavailable
if not _DSK_OUTPUT_DIR.parent.exists():
    _DSK_OUTPUT_DIR = settings.storage_root / "dsk_outputs"

_DSK_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Template path ─────────────────────────────────────────────────────────────
# Prefer the copy deployed alongside the app (venv site-packages) — always
# accessible by the launchd service even when Downloads/ is sandboxed.
# Fall back to engine_dir copy if the bundled one is somehow missing.
_VENV_SITE = Path(__file__).parent.parent.parent  # app/api/routes_dsk.py → site-packages/
_DSK_TEMPLATE = _VENV_SITE / "dsk_template.pdf"
if not _DSK_TEMPLATE.is_file():
    _DSK_TEMPLATE = settings.engine_dir / "dsk_template.pdf"


# ── Schemas ───────────────────────────────────────────────────────────────────

class DskRequest(BaseModel):
    awb:             str
    value_usd:       Optional[float] = None   # May be omitted; backend derives from audit if absent
    carrier:         str              = "DHL"
    broker_required: bool             = True
    date_override:   Optional[str]    = None   # DD-MM-YYYY
    batch_id:        Optional[str]    = None


class DskResponse(BaseModel):
    generated:         bool
    filename:          Optional[str] = None
    download_url:      Optional[str] = None
    awb_clean:         Optional[str] = None
    awb_formatted:     Optional[str] = None
    date:              Optional[str] = None
    skip_reason:       Optional[str] = None
    message:           Optional[str] = None
    file_hash_sha256:  Optional[str] = None
    version:           Optional[int] = None
    regenerated:       Optional[bool] = None


class EmailPackageRequest(BaseModel):
    batch_id: str
    awb:      str


class AttachmentItem(BaseModel):
    label: str
    path:  str


class EmailPackageResponse(BaseModel):
    to:          str
    cc:          str
    subject:     str
    body_pl:     str
    body_en:     str
    attachments: List[AttachmentItem]
    missing:     List[str]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _skip_message(skip_reason: str, value_usd: float) -> str:
    if skip_reason == "carrier_not_dhl":
        return "DSK not generated: carrier is not DHL"
    if skip_reason in ("value_below_threshold", "value_below_threshold_no_broker_flag"):
        return f"DSK not generated: shipment value ${value_usd:,.0f} ≤ $2500 threshold and broker_required is not set"
    if skip_reason == "broker_not_required":
        return "DSK not generated: broker not required for this shipment"
    return f"DSK not generated: {skip_reason}"


def _resolve_batch_storage_dir(batch_id: str) -> Optional[Path]:
    """
    Resolve the batch storage directory from batch_id.
    Looks in $STORAGE_ROOT/outputs/<batch_id>/
    """
    storage_root = getattr(settings, "storage_root", None)
    if storage_root is None:
        return None
    candidate = Path(storage_root) / "outputs" / batch_id
    return candidate if candidate.is_dir() else None


def _find_dsk_file(awb: str) -> Optional[Path]:
    """
    Find the most recent DSK PDF in _DSK_OUTPUT_DIR matching DSK_<AWB_CLEAN>_*.pdf
    """
    awb_clean = re.sub(r"\s+", "", awb)
    matches = sorted(_DSK_OUTPUT_DIR.glob(f"DSK_{awb_clean}_*.pdf"))
    # Return the canonical (non-versioned) file if present, else latest versioned
    canonical = _DSK_OUTPUT_DIR / f"DSK_{awb_clean}_*.pdf"
    # Prefer files without _v suffix
    non_versioned = [p for p in matches if not re.search(r"_v\d+\.pdf$", p.name)]
    if non_versioned:
        return non_versioned[-1]
    return matches[-1] if matches else None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/generate", response_model=DskResponse, dependencies=[_auth, _op_auth])
async def generate_dsk_endpoint(body: DskRequest) -> DskResponse:
    """
    Generate a DSK broker notification PDF for a DHL shipment.

    Trigger conditions:
    - carrier == "DHL" (case-insensitive)
    - value_usd > 2500  OR  broker_required == True
    """
    # Guard: if batch_id provided, DHL email must exist before DSK can be generated
    _resolved_audit: Optional[dict] = None
    if body.batch_id:
        _batch_dir = _resolve_batch_storage_dir(body.batch_id)
        if _batch_dir:
            _guard_audit_path = _batch_dir / "audit.json"
            if _guard_audit_path.exists():
                _resolved_audit = json.loads(_guard_audit_path.read_text(encoding="utf-8"))
                _dsk_adv = guard_dhl_requires_email(_resolved_audit)
                if _dsk_adv:
                    from ..pipelines.pz import _advisory_to_action_proposal, _write_advisory_proposal
                    _dsk_prop = _advisory_to_action_proposal(
                        _dsk_adv,
                        _resolved_audit.get("batch_id", body.batch_id or ""),
                        "dsk_endpoint",
                    )
                    _write_advisory_proposal(_guard_audit_path, _dsk_prop)

    # ── Derive value_usd from audit if not supplied in payload ────────────────
    value_usd  = body.value_usd or 0.0
    value_source = "payload"
    if not value_usd and _resolved_audit:
        _ver = _resolved_audit.get("verification") or {}
        _it  = _resolved_audit.get("invoice_totals") or {}
        if _ver.get("invoice_cif_total_usd"):
            value_usd    = float(_ver["invoice_cif_total_usd"])
            value_source = "audit.verification"
        elif _it.get("total_cif_usd"):
            value_usd    = float(_it["total_cif_usd"])
            value_source = "audit.invoice_totals"
    if not value_usd:
        raise HTTPException(
            status_code=422,
            detail="Missing CIF value — run Recheck or upload valid invoices first",
        )
    log.info("[DSK] [%s] value_usd=%.2f source=%s", body.batch_id or "?", value_usd, value_source)

    try:
        import sys
        _engine_dir = str(settings.engine_dir)
        if _engine_dir not in sys.path:
            sys.path.insert(0, _engine_dir)

        import dsk_generator as _dsk

        result = _dsk.generate_dsk(
            awb             = body.awb,
            value_usd       = value_usd,
            carrier         = body.carrier,
            broker_required = body.broker_required,
            output_dir      = str(_DSK_OUTPUT_DIR),
            template_path   = str(_DSK_TEMPLATE) if _DSK_TEMPLATE.is_file() else None,
            date_override   = body.date_override,
        )

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DSK generation error: {exc}") from exc

    if not result.get("generated"):
        skip = result.get("skip_reason", "unknown")
        return DskResponse(
            generated   = False,
            skip_reason = skip,
            message     = _skip_message(skip, value_usd),
        )

    filename = result["filename"]
    download_url = f"/api/v1/dsk/download/{filename}"

    # Write DSK result into batch audit.json and log timeline event
    if body.batch_id:
        _batch_dir = _resolve_batch_storage_dir(body.batch_id)
        if _batch_dir:
            _audit_path = _batch_dir / "audit.json"
            if _audit_path.exists():
                try:
                    _audit = json.loads(_audit_path.read_text(encoding="utf-8"))
                    _audit["dsk_filename"]   = filename
                    # Phase 3.2.1 — B2 observer reads audit["dsk_path"] to
                    # locate the file for attachment. Write the full path
                    # alongside the filename. Null-safe: if the generator
                    # returned no output_path (skip/failure), leave the
                    # field absent so the B2 observer's gate skips silently.
                    _output_path = result.get("output_path")
                    if _output_path:
                        _audit["dsk_path"] = str(_output_path)
                    _audit["dsk_status"]     = "generated"
                    _audit["clearance_status"] = "dsk_generated"
                    # F3-FIX: write canonical pointer that _compute_dhl_action_state reads.
                    # dashboard reads audit["customs_package_generated_at"]; dsk_meta.generated_at
                    # alone is not enough — write both so legacy and new paths agree.
                    _now_iso = datetime.now(timezone.utc).isoformat()
                    _audit["customs_package_generated_at"] = _now_iso
                    _audit["dsk_meta"] = {
                        "value_usd":    value_usd,
                        "value_source": value_source,
                        "generated_at": _now_iso,
                    }
                    write_json_atomic(_audit_path, _audit)
                    tl.log_event(
                        _audit_path,
                        tl.EV_DSK_GENERATED,
                        trigger_source="dashboard",
                        actor="admin",
                        detail={"filename": filename, "awb": body.awb},
                    )
                except Exception as _e:
                    log.warning("DSK audit update failed (non-fatal): %s", _e)

    return DskResponse(
        generated        = True,
        filename         = filename,
        download_url     = download_url,
        awb_clean        = result["awb_clean"],
        awb_formatted    = result["awb_formatted"],
        date             = result["date"],
        file_hash_sha256 = result.get("file_hash_sha256"),
        version          = result.get("version"),
        regenerated      = result.get("regenerated"),
    )


@router.get("/download/{filename}", dependencies=[_auth])
async def download_dsk(filename: str) -> FileResponse:
    """Download a generated DSK PDF by filename."""
    # Security: no path traversal
    if "/" in filename or ".." in filename or not filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Invalid filename.")

    file_path = _DSK_OUTPUT_DIR / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"DSK file not found: {filename}")

    return FileResponse(
        path                = str(file_path),
        media_type          = "application/pdf",
        filename            = filename,
        headers             = {"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/email-package", response_model=EmailPackageResponse, dependencies=[_auth, _op_auth])
async def build_email_package_endpoint(body: EmailPackageRequest) -> EmailPackageResponse:
    """
    Build a DHL broker email package for a batch.

    Resolves batch storage directory, finds DSK PDF, scans for invoice + AWB PDFs,
    and returns a structured email package dict.

    Does NOT send the email — returns data for the dashboard to display and
    for the user to trigger send manually.
    """
    try:
        import sys
        _engine_dir = str(settings.engine_dir)
        if _engine_dir not in sys.path:
            sys.path.insert(0, _engine_dir)

        import dsk_generator as _dsk

        # Resolve batch storage directory
        batch_dir = _resolve_batch_storage_dir(body.batch_id)
        if batch_dir is None:
            raise HTTPException(
                status_code=404,
                detail=f"Batch storage directory not found for batch_id: {body.batch_id}",
            )

        # Guard: DHL action requires email receipt
        _audit_path_dsk = batch_dir / "audit.json"
        if _audit_path_dsk.exists():
            try:
                _audit_for_guard = json.loads(_audit_path_dsk.read_text(encoding="utf-8"))
                _dsk2_adv = guard_dhl_requires_email(_audit_for_guard)
                if _dsk2_adv:
                    from ..pipelines.pz import _advisory_to_action_proposal, _write_advisory_proposal
                    _dsk2_prop = _advisory_to_action_proposal(
                        _dsk2_adv,
                        _audit_for_guard.get("batch_id", body.batch_id or ""),
                        "dsk_send_endpoint",
                    )
                    _write_advisory_proposal(_audit_path_dsk, _dsk2_prop)
            except HTTPException:
                raise
            except Exception:
                pass  # audit unreadable — proceed

        # Find DSK file
        dsk_path = _find_dsk_file(body.awb)

        # Build email package
        package = _dsk.build_dhl_email_package(
            batch_storage_dir = str(batch_dir),
            awb               = body.awb,
            dsk_path          = str(dsk_path) if dsk_path else None,
        )

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Email package error: {exc}") from exc

    # Persist the built reply_package into audit.json so send-reply can find it
    _audit_path_pkg = _resolve_batch_storage_dir(body.batch_id)
    if _audit_path_pkg:
        _ap = _audit_path_pkg / "audit.json"
        if _ap.exists():
            try:
                _aud = json.loads(_ap.read_text(encoding="utf-8"))
                _aud["reply_package"] = {
                    "to":          package["to"],
                    "cc":          package.get("cc", ""),
                    "subject":     package["subject"],
                    "body_pl":     package["body_pl"],
                    "body_en":     package["body_en"],
                    "attachments": [
                        {"label": a["label"], "path": a["path"]}
                        for a in package.get("attachments", [])
                    ],
                    "built_at":    __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
                }
                write_json_atomic(_ap, _aud)
            except Exception as _ep:
                log.warning("email-package: could not persist reply_package to audit: %s", _ep)

    return EmailPackageResponse(
        to          = package["to"],
        cc          = package["cc"],
        subject     = package["subject"],
        body_pl     = package["body_pl"],
        body_en     = package["body_en"],
        attachments = [AttachmentItem(**a) for a in package["attachments"]],
        missing     = package["missing"],
    )


@router.get("/audit-log", dependencies=[_auth])
async def get_audit_log() -> JSONResponse:
    """
    Return the DSK audit log (dsk_audit_log.json) sorted newest first.
    Returns an empty list if no log exists yet.
    """
    log_path = _DSK_OUTPUT_DIR / "dsk_audit_log.json"

    if not log_path.is_file():
        return JSONResponse(content=[])

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            entries = json.load(f)
        if not isinstance(entries, list):
            entries = []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read audit log: {exc}") from exc

    # Sort newest first by generated_at (ISO string sort works for UTC timestamps)
    entries_sorted = sorted(
        entries,
        key=lambda e: e.get("generated_at", ""),
        reverse=True,
    )

    return JSONResponse(content=entries_sorted)
