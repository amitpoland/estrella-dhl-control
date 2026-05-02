"""
routes_tracking.py — Live DHL / FedEx tracking status endpoints.

GET  /api/v1/tracking/{tracking_no}          — return (cached) status
POST /api/v1/tracking/{tracking_no}/refresh  — force API refresh + patch audit.json
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from ..auth.dependencies import get_current_user
from ..core import timeline as tl
from ..core.config import settings
from ..services.tracking_service import get_tracking_status
from ..utils.batch_lock import batch_write_lock
from ..utils.io import write_json_atomic

router = APIRouter(prefix="/api/v1/tracking", tags=["tracking"])
_auth  = Depends(get_current_user)

_OUTPUTS = settings.storage_root / "outputs"


def _resolve_cache_dir(batch_id: str) -> Path:
    """
    Return the cache directory for the given batch_id.
    If batch_id is provided the cache lives inside the batch output folder;
    otherwise a shared tracking/ folder is used.
    """
    if batch_id:
        if "/" in batch_id or ".." in batch_id:
            raise HTTPException(status_code=400, detail="Invalid batch_id.")
        return _OUTPUTS / batch_id
    fallback = settings.storage_root / "tracking"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _auto_carrier(tracking_no: str) -> str:
    """Detect carrier from tracking number digit length."""
    digits = re.sub(r"[^\d]", "", tracking_no)
    n = len(digits)
    if n == 10:
        return "DHL"
    if n in (12, 15, 20):
        return "FedEx"
    return "Unknown"


# ── GET /api/v1/tracking/{tracking_no} ───────────────────────────────────────

@router.get("/{tracking_no}", dependencies=[_auth])
def get_tracking(
    tracking_no: str,
    carrier:  str  = Query(default=""),
    batch_id: str  = Query(default=""),
    refresh:  bool = Query(default=False),
) -> Dict[str, Any]:
    """
    Return tracking status. Never raises — returns fallback dict on any error.
    When DHL_TRACKING_API_STATUS != 'active', returns pending fallback immediately.
    """
    try:
        effective_carrier = carrier.strip() or _auto_carrier(tracking_no)
        cache_dir         = _resolve_cache_dir(batch_id)
        return get_tracking_status(tracking_no, effective_carrier, cache_dir, refresh=refresh)
    except Exception as exc:
        return {
            "tracking_no": tracking_no,
            "carrier":     carrier or "Unknown",
            "available":   False,
            "source":      "error",
            "error":       str(exc),
            "tracking_url": "",
        }


# ── POST /api/v1/tracking/{tracking_no}/refresh ───────────────────────────────

@router.post("/{tracking_no}/refresh", dependencies=[_auth])
def refresh_tracking(
    tracking_no: str,
    carrier:  str = Query(default=""),
    batch_id: str = Query(default=""),
) -> Dict[str, Any]:
    """
    Force-refresh tracking status. Never raises — returns fallback dict on any error.
    When DHL_TRACKING_API_STATUS != 'active', returns pending fallback immediately.
    """
    try:
        effective_carrier = carrier.strip() or _auto_carrier(tracking_no)
        cache_dir         = _resolve_cache_dir(batch_id)
        result            = get_tracking_status(
            tracking_no, effective_carrier, cache_dir, refresh=True
        )
    except Exception as exc:
        return {
            "tracking_no": tracking_no,
            "carrier":     carrier or "Unknown",
            "available":   False,
            "source":      "error",
            "error":       str(exc),
            "tracking_url": "",
        }

    # Patch audit.json if batch_id is given
    if batch_id:
        audit_path = _OUTPUTS / batch_id / "audit.json"
        if audit_path.exists():
            try:
                with batch_write_lock(batch_id):
                    audit = json.loads(audit_path.read_text(encoding="utf-8"))
                    audit["tracking"] = result
                    write_json_atomic(audit_path, audit)
            except Exception:
                pass  # audit patch is best-effort; don't fail the response

    return result


# ── POST /api/v1/tracking/{batch_id}/update ──────────────────────────────────

class TrackingUpdateBody(BaseModel):
    """
    Body for updating tracking data on a known batch.

    Used by Cowork agent, operator, or the Proposals "Mark as Done" flow.
    Simpler than CoworkTrackingResult — batch is identified by ID, not AWB scan.
    """
    status:       str
    last_event:   str
    location:     str = ""
    event_time:   Optional[str] = None
    source:       str = "cowork"
    note:         Optional[str] = None
    proposal_id:  Optional[str] = None   # if closing a tracking_lookup proposal


@router.post("/batch/{batch_id}/update", dependencies=[_auth])
def update_tracking_for_batch(
    batch_id: str,
    body:     TrackingUpdateBody,
) -> Dict[str, Any]:
    """
    Write a tracking update for a specific batch.

    Writes to audit.tracking, clears cowork_tracking_required, logs
    EV_TRACKING_UPDATED.  If proposal_id is supplied, marks that
    tracking_lookup proposal as 'done'.

    Safety: never touches clearance_decision. Never sends emails.
    """
    import time as _time

    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    audit_path = _OUTPUTS / batch_id / "audit.json"
    if not audit_path.exists():
        raise HTTPException(status_code=404, detail=f"Batch {batch_id!r} not found.")

    with batch_write_lock(batch_id):
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not read audit: {exc}")

        # ── Patch tracking block ──────────────────────────────────────────────
        tr = audit.setdefault("tracking", {})
        tr.update({
            "status":                   body.status,
            "status_label":             body.status.replace("_", " ").title(),
            "last_event":               body.last_event,
            "last_location":            body.location,
            "last_update":              body.event_time,
            "source":                   body.source,
            "available":                True,
            "cowork_result_received":   True,
            "cowork_tracking_required": False,
            "cowork_result_at":         _time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        if body.note:
            tr["cowork_result_note"] = body.note
        if body.status in ("delivered", "out_for_delivery"):
            tr["arrived_warehouse"] = True

        # ── Close linked tracking_lookup proposal if supplied ─────────────────
        if body.proposal_id:
            for prop in (audit.get("action_proposals") or []):
                if (prop.get("proposal_id") == body.proposal_id
                        and prop.get("type") == "tracking_lookup"):
                    prop["status"] = "done"
                    prop["done_at"] = _time.strftime("%Y-%m-%dT%H:%M:%SZ")
                    prop["done_source"] = body.source
                    break

        write_json_atomic(audit_path, audit)

    # ── Timeline ──────────────────────────────────────────────────────────────
    tl.log_event(
        audit_path,
        tl.EV_TRACKING_UPDATED,
        "tracking_update",
        actor=body.source,
        detail={
            "batch_id":   batch_id,
            "status":     body.status,
            "last_event": body.last_event,
            "location":   body.location,
            "event_time": body.event_time,
            "source":     body.source,
            "proposal_id": body.proposal_id,
        },
    )

    return {
        "ok":       True,
        "batch_id": batch_id,
        "status":   body.status,
        "written":  True,
    }


# ── POST /api/v1/tracking/{awb}/cowork-result ─────────────────────────────────

class CoworkTrackingResult(BaseModel):
    """
    Body for reporting a public tracking result (from Cowork agent or operator).

    Fields:
      status        — normalised status string: "in_transit" | "delivered" |
                      "out_for_delivery" | "exception" | "customs" | "unknown"
      last_event    — human-readable description of the most recent event
      last_location — city / country code, e.g. "WARSAW - PL"
      event_time    — ISO 8601 timestamp of the most recent event (optional)
      source        — who/what provided this result
      batch_id      — optional; used to resolve the audit path when AWB lookup is ambiguous
      note          — optional free-text operator note
    """
    status:        str
    last_event:    str
    last_location: str = ""
    event_time:    Optional[str] = None
    source:        str = "cowork_public_tracking"
    batch_id:      Optional[str] = None
    note:          Optional[str] = None


@router.post("/{awb}/cowork-result", dependencies=[_auth])
def submit_cowork_tracking_result(
    awb:  str,
    body: CoworkTrackingResult,
) -> Dict[str, Any]:
    """
    Accept a public tracking result reported by Cowork agent or operator.

    Writes the result to audit.tracking, clears cowork_tracking_required,
    and logs EV_TRACKING_PUBLIC_LOOKUP to the timeline.

    Safety: never triggers emails, never modifies clearance state.
    Only updates tracking evidence and clears the lookup task.
    """
    import time as _time

    batch_id  = body.batch_id or ""
    audit_path: Optional[Any] = None

    # ── Resolve audit.json from batch_id or AWB scan ──────────────────────────
    if batch_id:
        if "/" in batch_id or ".." in batch_id:
            raise HTTPException(status_code=400, detail="Invalid batch_id.")
        p = _OUTPUTS / batch_id / "audit.json"
        if p.exists():
            audit_path = p
    else:
        # Scan all active batches for this AWB
        if _OUTPUTS.is_dir():
            for batch_dir in _OUTPUTS.iterdir():
                if not batch_dir.is_dir():
                    continue
                ap = batch_dir / "audit.json"
                if not ap.exists():
                    continue
                try:
                    a = json.loads(ap.read_text(encoding="utf-8"))
                    if (a.get("awb") == awb or a.get("tracking_no") == awb
                            or a.get("dhl_awb") == awb):
                        audit_path = ap
                        batch_id = batch_dir.name
                        break
                except Exception:
                    continue

    if audit_path is None:
        raise HTTPException(
            status_code=404,
            detail=f"No batch found for AWB {awb!r}. "
                   "Provide batch_id in body or ensure the batch exists.",
        )

    # ── Load → patch tracking block → save (under per-batch lock) ───────────
    with batch_write_lock(batch_id):
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not read audit: {exc}")

        tr = audit.setdefault("tracking", {})
        tr.update({
            "status":                  body.status,
            "status_label":            body.status.replace("_", " ").title(),
            "last_event":              body.last_event,
            "last_location":           body.last_location,
            "last_update":             body.event_time,
            "source":                  body.source,
            "available":               True,
            "cowork_result_received":  True,
            "cowork_tracking_required": False,   # ← clear the lookup task
            "cowork_result_at":        _time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        if body.note:
            tr["cowork_result_note"] = body.note

        # Also update arrived_warehouse if status signals delivery/warehouse arrival
        if body.status in ("delivered", "out_for_delivery"):
            tr["arrived_warehouse"] = True

        write_json_atomic(audit_path, audit)

    # ── Timeline event ────────────────────────────────────────────────────────
    tl.log_event(
        audit_path,
        tl.EV_TRACKING_PUBLIC_LOOKUP,
        "cowork_result",
        actor=body.source,
        detail={
            "awb":          awb,
            "status":       body.status,
            "last_event":   body.last_event,
            "last_location": body.last_location,
            "event_time":   body.event_time,
            "source":       body.source,
            "note":         body.note,
        },
    )

    return {
        "ok":       True,
        "awb":      awb,
        "batch_id": batch_id,
        "status":   body.status,
        "written":  True,
    }


@router.get("/shipment/{batch_id}/timeline", dependencies=[_auth])
def get_shipment_timeline(batch_id: str) -> dict:
    """Return the event timeline for a shipment batch."""
    from ..core.timeline import get_timeline
    from ..services.batch_service import get_output_dir
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    audit_path = get_output_dir(batch_id) / "audit.json"
    if not audit_path.exists():
        raise HTTPException(status_code=404, detail="Shipment not found.")
    return {"batch_id": batch_id, "timeline": get_timeline(audit_path)}
