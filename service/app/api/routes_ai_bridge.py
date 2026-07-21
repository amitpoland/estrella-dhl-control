"""
routes_ai_bridge.py — AI Bridge REST endpoints.

Provides a file-based coordination layer so external AI tools (Claude Cowork,
ChatGPT, etc.) can assist with shipment processing without direct access to
the production engine or financial data.

Endpoints:
  POST /api/v1/ai-bridge/tasks/{batch_id}     — create task file
  GET  /api/v1/ai-bridge/tasks                — list pending tasks
  GET  /api/v1/ai-bridge/tasks/{task_id}      — read a specific task
  POST /api/v1/ai-bridge/results/{task_id}    — import result from external AI

Safety constraints:
  - FORBIDDEN_FIELDS are checked on every import — any result touching those
    fields is rejected and archived to errors/
  - Only allowed audit keys per task_type may be written
  - No financial recalculation happens here; the Python engine stays canonical
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth.dependencies import get_current_user
from ..core import timeline as tl
from ..core.config import settings
from ..services.ai_bridge import (
    FORBIDDEN_FIELDS,
    TASK_TEMPLATES,
    create_task,
    get_task,
    import_result,
    list_tasks,
)
from ..services.tracking_patch import apply_tracking_update, close_tracking_proposal
from ..utils.batch_lock import batch_write_lock
from ..utils.io import write_json_atomic

router = APIRouter(prefix="/api/v1/ai-bridge", tags=["ai_bridge"])
_auth  = Depends(get_current_user)

_OUTPUTS = settings.storage_root / "outputs"

# Roles permitted to close the tracking workflow checkpoint. Mirrors
# routes_tracking._op_auth = require_role("admin", "logistics") -- the authority
# that owned audit.tracking_complete before the write paths were consolidated.
_OPERATOR_ROLES = frozenset({"admin", "logistics"})


def _may_close_checkpoint(user: Any) -> bool:
    """True only for an operator-role caller. Fail-closed on anything else.

    `user` is normally the dict from get_current_user. It is deliberately NOT
    assumed to be one: when this route function is called directly in Python
    (as several tests do) the parameter default is a FastAPI ``Depends`` object,
    and ``.get`` on it would raise AttributeError -- swallowed whole by the
    caller's ``except Exception: pass``, silently skipping the entire tracking
    patch. Anything that is not a dict yields False: evidence is still recorded,
    the workflow checkpoint simply is not closed.
    """
    if not isinstance(user, dict):
        return False
    return user.get("role") in _OPERATOR_ROLES


# ── Request / Response models ──────────────────────────────────────────────────

class CreateTaskBody(BaseModel):
    task_type: str
    payload:   Dict[str, Any] = {}
    note:      Optional[str] = None


class ImportResultBody(BaseModel):
    """
    Result submitted by an external AI tool.

    Fields:
      task_id     — must match the task being closed
      result_data — keys to write into audit (only allowed keys per task_type)
      summary     — human-readable summary of what was done
      source      — who/what produced the result (e.g. "claude_cowork")
      proposal_id — optional: if closing a tracking_lookup proposal, pass its ID
    """
    task_id:     str
    result_data: Dict[str, Any] = {}
    summary:     str = ""
    source:      str = "ai_bridge"
    proposal_id: Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _load_audit(batch_id: str) -> tuple[Path, Dict[str, Any]]:
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    audit_path = _OUTPUTS / batch_id / "audit.json"
    if not audit_path.exists():
        raise HTTPException(status_code=404, detail=f"Batch {batch_id!r} not found.")
    try:
        return audit_path, json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not read audit: {exc}")


# ── POST /api/v1/ai-bridge/tasks/{batch_id} ───────────────────────────────────

@router.post("/tasks/{batch_id}", dependencies=[_auth])
def create_bridge_task(
    batch_id: str,
    body:     CreateTaskBody,
) -> Dict[str, Any]:
    """
    Create a task file for an external AI tool.

    The task is written to ai_bridge/tasks/<task_id>.json with full
    instructions, result schema, and payload context.  The external AI
    reads this file, performs the task, then writes a result file that
    can be imported via POST /results/{task_id}.
    """
    if body.task_type not in TASK_TEMPLATES:
        raise HTTPException(
            status_code=422,
            detail={
                "code":    "unknown_task_type",
                "message": f"Unknown task_type {body.task_type!r}.",
                "allowed": sorted(TASK_TEMPLATES),
            },
        )

    # Load audit to enrich payload with batch context
    audit_path, audit = _load_audit(batch_id)

    # Auto-enrich payload with useful audit fields (safe, non-financial)
    enriched_payload = {
        "batch_id":   batch_id,
        "awb":        audit.get("awb") or audit.get("tracking_no") or "",
        "carrier":    audit.get("carrier") or "",
        "status":     audit.get("status") or "",
    }
    # Add tracking info for tracking_lookup tasks
    if body.task_type == "tracking_lookup":
        tr = audit.get("tracking") or {}
        enriched_payload["tracking_url"]    = tr.get("tracking_url") or ""
        enriched_payload["current_status"]  = tr.get("status") or "unknown"

    # Merge caller payload (caller can override)
    enriched_payload.update(body.payload)

    try:
        task = create_task(
            batch_id  = batch_id,
            task_type = body.task_type,
            payload   = enriched_payload,
            note      = body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Log timeline event
    tl.log_event(
        audit_path,
        tl.EV_AI_BRIDGE_TASK_CREATED,
        "ai_bridge",
        actor="admin",
        detail={
            "task_id":   task["task_id"],
            "task_type": body.task_type,
            "batch_id":  batch_id,
        },
    )

    return {
        "ok":       True,
        "task_id":  task["task_id"],
        "task_type": body.task_type,
        "batch_id": batch_id,
        "task":     task,
    }


# ── GET /api/v1/ai-bridge/tasks ───────────────────────────────────────────────

@router.get("/tasks", dependencies=[_auth])
def list_bridge_tasks(status: str = "pending") -> Dict[str, Any]:
    """
    List AI bridge tasks.

    Query params:
      status — "pending" (default) | "processed"
    """
    tasks = list_tasks(status=status)
    return {
        "status": status,
        "count":  len(tasks),
        "tasks":  tasks,
    }


# ── GET /api/v1/ai-bridge/tasks/{task_id} ────────────────────────────────────

@router.get("/tasks/{task_id}", dependencies=[_auth])
def get_bridge_task(task_id: str) -> Dict[str, Any]:
    """Return a specific task file."""
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found.")
    return task


# ── POST /api/v1/ai-bridge/results/{task_id} ─────────────────────────────────

@router.post("/results/{task_id}", dependencies=[_auth])
def import_bridge_result(
    task_id: str,
    body:    ImportResultBody,
    user:    Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Import a result from an external AI tool.

    Safety:
      - Forbidden fields are rejected (financial / customs data)
      - Only allowed audit keys per task_type may be written
      - If proposal_id is supplied and task_type == tracking_lookup,
        the linked proposal is closed (status=done) after result import

    On success: result is applied to audit, task moved to processed/.
    On failure: result archived to errors/, 422 returned.
    """
    import time as _time

    # Verify task_id matches body.task_id
    if body.task_id != task_id:
        raise HTTPException(
            status_code=422,
            detail=f"URL task_id {task_id!r} does not match body.task_id {body.task_id!r}.",
        )

    # Load task
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found.")

    batch_id = task.get("batch_id", "")
    audit_path, audit = _load_audit(batch_id)

    # Build result dict for import_result()
    result = {
        "task_id":     task_id,
        "result_data": body.result_data,
        "summary":     body.summary,
        "source":      body.source,
        "submitted_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    try:
        outcome = import_result(
            task_id    = task_id,
            result     = result,
            audit      = audit,
            audit_path = audit_path,
        )
    except ValueError as exc:
        # ── Safety logging: append rejection to audit["ai_bridge_errors"] ────
        try:
            _current = json.loads(audit_path.read_text(encoding="utf-8"))
            _errs = _current.setdefault("ai_bridge_errors", [])
            _errs.append({
                "task_id":   task_id,
                "task_type": task.get("task_type"),
                "reason":    str(exc),
                "timestamp": _time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source":    body.source,
            })
            write_json_atomic(audit_path, _current)
        except Exception:
            pass  # safety logging is best-effort
        raise HTTPException(status_code=422, detail=str(exc))

    # If it's an email_scan result, log inbox-scan + auto-apply DHL detection
    if task.get("task_type") == "email_scan":
        try:
            scan_results = (body.result_data or {}).get("email_scan_results") or {}
            matched_n    = int(scan_results.get("matched", 0) or 0)
            unreliable   = bool(scan_results.get("search_unreliable", False))
            # Connector mismatch is a stronger form of unreliable
            if scan_results.get("connector_mismatch"):
                unreliable = True

            # ── Persist into email intelligence store (always, even if 0) ─────
            try:
                from ..services.email_intelligence_store import save_email_scan_result
                _audit_for_store = json.loads(audit_path.read_text(encoding="utf-8"))
                # Annotate source from the bridge envelope
                if body.source and "source" not in scan_results:
                    scan_results["source"] = body.source
                save_email_scan_result(scan_results, _audit_for_store)
            except Exception:
                pass  # storage is best-effort — never blocks audit update

            # ── 0. Unreliable-zero-result guard ───────────────────────────────
            # If matched==0 but Cowork explicitly flagged search_unreliable
            # (or returned no diagnostic confirming the full term list was
            # searched), record a risk flag and do NOT change clearance state.
            from datetime import datetime, timezone
            if matched_n == 0 and unreliable:
                try:
                    _cur = json.loads(audit_path.read_text(encoding="utf-8"))
                    _cur["email_search_risk"]        = True
                    _cur["email_search_risk_reason"] = (
                        scan_results.get("zero_result_reason")
                        or "Cowork returned 0 despite AWB/invoice identifiers"
                    )
                    _cur["email_search_risk_at"]     = _time.strftime("%Y-%m-%dT%H:%M:%SZ")
                    write_json_atomic(audit_path, _cur)
                except Exception:
                    pass
                tl.log_event(
                    audit_path,
                    "email_scan_unreliable",
                    "ai_bridge",
                    actor=body.source,
                    detail={
                        "task_id":           task_id,
                        "searched":          scan_results.get("searched", {}),
                        "zero_result_reason": scan_results.get("zero_result_reason", ""),
                    },
                )

            # ── 1. Always log the scan event (matched > 0) ────────────────────
            if matched_n > 0:
                emails_preview = [
                    {
                        "subject":        e.get("subject", ""),
                        "from":           e.get("from", ""),
                        "received_at":    e.get("received_at", ""),
                        "ticket":         e.get("ticket", ""),
                        "awb":            e.get("awb", ""),
                        "matched_fields": e.get("matched_fields", []),
                        "detected_type":  e.get("detected_type", "") or e.get("classification", ""),
                    }
                    for thread in (scan_results.get("threads") or [{}])[:3]
                    for e in (thread.get("emails") or [])[:3]
                ] or [
                    # fallback: legacy flat emails[] shape
                    {
                        "subject":        e.get("subject", ""),
                        "from":           e.get("from", ""),
                        "received_at":    e.get("received_at", ""),
                        "ticket":         e.get("ticket", ""),
                        "awb":            e.get("awb", ""),
                        "matched_fields": e.get("matched_fields", []),
                        "detected_type":  e.get("detected_type", ""),
                    }
                    for e in (scan_results.get("emails") or [])[:3]
                ]
                tl.log_event(
                    audit_path,
                    tl.EV_DHL_INBOX_SCANNED,
                    "ai_bridge",
                    actor=body.source,
                    detail={
                        "scanned":        matched_n,
                        "matched":        matched_n,
                        "scan_method":    "ai_bridge",
                        "search_mode":    "awb_targeted",
                        "awb_used":       scan_results.get("awb", ""),
                        "task_id":        task_id,
                        "confidence":     scan_results.get("confidence", ""),
                        "recommended_next_action": scan_results.get("recommended_next_action", ""),
                        "emails_preview": emails_preview,
                    },
                )

            # ── 2. Auto-apply DHL detection from derived_events ───────────────
            # Only when:
            #   - derived_events contains dhl_customs_email_received
            #   - audit.clearance_status is NOT already advanced past dhl_email_received
            from datetime import datetime, timezone
            _STATUS_ORDER = {
                "":                              0,
                "draft":                         0,
                "awaiting_dhl_customs_email":    1,
                "dhl_email_received":            2,
                "polish_description_generated":  3,
                "dsk_generated":                 3,
                "agency_email_sent":             4,
                "delivered":                     5,
            }
            current = json.loads(audit_path.read_text(encoding="utf-8"))
            current_status = current.get("clearance_status", "")
            current_rank   = _STATUS_ORDER.get(current_status, 0)

            derived = scan_results.get("derived_events") or []
            dhl_event = next(
                (e for e in derived if e.get("event") == "dhl_customs_email_received"),
                None,
            )
            # Write dhl_email evidence ALWAYS when detected — informational
            # metadata. Status advance is rank-guarded separately so we never
            # downgrade a more-advanced clearance state.
            if dhl_event:
                from ..config.email_routing import is_dsk_source
                now_iso = _time.strftime("%Y-%m-%dT%H:%M:%SZ")
                sender  = dhl_event.get("source_email_from", "")
                received_at = dhl_event.get("timestamp") or now_iso
                current["dhl_email"] = {
                    "received":     True,
                    "source":       "ai_bridge_cowork",
                    "sender":       sender,
                    "subject":      dhl_event.get("source_email_subject", ""),
                    "ticket":       dhl_event.get("ticket", ""),
                    "request_type": dhl_event.get("request_type", "unknown"),
                    "received_at":  received_at,
                    "confidence":   dhl_event.get("confidence", ""),
                    "applied_via_task_id": task_id,
                }
                if dhl_event.get("ticket"):
                    current["dhl_ticket"] = dhl_event["ticket"]
                if is_dsk_source(sender):
                    current["dsk_received"]    = True
                    current["dsk_source"]      = sender
                    current["dsk_received_at"] = received_at
                if current_rank < _STATUS_ORDER["dhl_email_received"]:
                    current["clearance_status"]      = "dhl_email_received"
                    current["clearance_updated_at"]  = now_iso
                write_json_atomic(audit_path, current)
                tl.log_event(
                    audit_path,
                    "dhl_customs_email_received",
                    "ai_bridge",
                    actor=body.source,
                    detail={
                        "auto_applied":     True,
                        "source_subject":   dhl_event.get("source_email_subject", ""),
                        "source_from":      sender,
                        "ticket":           dhl_event.get("ticket", ""),
                        "task_id":          task_id,
                        "advanced_status":  current_rank < _STATUS_ORDER["dhl_email_received"],
                    },
                )

            # ── 3. Agency pre-clearance event (OUTGOING Estrella → agency) ───
            # This is NOT a DHL email — it's the operator's own outbound to
            # Ganther/ACS asking them to pre-arrange clearance. Does NOT
            # advance clearance_status to dhl_email_received.
            preclearance_sent = next(
                (e for e in derived if e.get("event") == "agency_preclearance_sent"),
                None,
            )
            preclearance_ack = next(
                (e for e in derived if e.get("event") == "agency_acknowledged"),
                None,
            )
            if preclearance_sent or preclearance_ack:
                _now = _time.strftime("%Y-%m-%dT%H:%M:%SZ")
                _cur = json.loads(audit_path.read_text(encoding="utf-8"))
                _pre = _cur.get("agency_preclearance") or {}
                if preclearance_sent:
                    _pre.update({
                        "source":     "ai_bridge_cowork",
                        "sent_at":    preclearance_sent.get("timestamp") or _now,
                        "subject":    preclearance_sent.get("source_email_subject", ""),
                        "from":       preclearance_sent.get("source_email_from", ""),
                        "confidence": preclearance_sent.get("confidence", ""),
                        "applied_via_task_id": task_id,
                    })
                if preclearance_ack:
                    _pre["acknowledgement"] = {
                        "from":       preclearance_ack.get("source_email_from", ""),
                        "subject":    preclearance_ack.get("source_email_subject", ""),
                        "timestamp":  preclearance_ack.get("timestamp") or _now,
                        "confidence": preclearance_ack.get("confidence", ""),
                    }
                _cur["agency_preclearance"] = _pre
                write_json_atomic(audit_path, _cur)

            # ── 4. Other derived events (forwards, agency replies, etc.) ─────
            # Agency pre-clearance events are still logged here; the dedicated
            # handler above just persists the structured field on top.
            for e in derived:
                ev_type = e.get("event")
                if ev_type and ev_type != "dhl_customs_email_received":
                    tl.log_event(
                        audit_path,
                        ev_type,
                        "ai_bridge",
                        actor=body.source,
                        detail={
                            "auto_logged":    True,
                            "source_subject": e.get("source_email_subject", ""),
                            "source_from":    e.get("source_email_from", ""),
                            "task_id":        task_id,
                        },
                    )
        except Exception:
            pass  # timeline write is best-effort

    # If it's a tracking_lookup result, also update cowork flags
    if task.get("task_type") == "tracking_lookup":
        # result_data may be {"tracking": {...}} or directly {"status": ...}
        rd_raw = body.result_data
        rd = rd_raw.get("tracking") if isinstance(rd_raw.get("tracking"), dict) else rd_raw
        if rd.get("status"):
            # Re-read audit (import_result already wrote it) to patch tracking.
            #
            # Under batch_write_lock: this is a read-modify-write of audit.json
            # and previously ran unlocked, so a concurrent writer — e.g. an
            # operator on /tracking/batch/{id}/update — could have its changes
            # silently overwritten. import_result does not take the lock itself
            # and batch_write_lock is not reentrant, so acquiring it here is safe.
            #
            # The patch is shared with routes_tracking via
            # services/tracking_patch.py. These were separate hand-written
            # copies and drifted: this one never gained api_status, updated_at
            # or the top-level tracking_complete keys, so a lookup closed
            # through the bridge still showed as "tracking required" and was
            # reverted by the next re-process.
            try:
                with batch_write_lock(batch_id):
                    audit = json.loads(audit_path.read_text(encoding="utf-8"))
                    now = apply_tracking_update(
                        audit,
                        status     = rd["status"],
                        source     = body.source,
                        last_event = rd.get("last_event", ""),
                        location   = rd.get("location", ""),
                        event_time = rd.get("event_time"),
                        advance_workflow = _may_close_checkpoint(user),
                    )

                    if body.proposal_id:
                        close_tracking_proposal(
                            audit, body.proposal_id, body.source, now)

                    write_json_atomic(audit_path, audit)
            except Exception:
                pass  # tracking patch is best-effort — import already succeeded

    # Log timeline
    tl.log_event(
        audit_path,
        tl.EV_AI_BRIDGE_RESULT_RECEIVED,
        "ai_bridge",
        actor=body.source,
        detail={
            "task_id":      task_id,
            "task_type":    task.get("task_type"),
            "batch_id":     batch_id,
            "applied_keys": outcome.get("applied_keys"),
            "summary":      body.summary,
            "proposal_id":  body.proposal_id,
        },
    )

    return {
        "ok":          True,
        "task_id":     task_id,
        "batch_id":    batch_id,
        "applied_keys": outcome.get("applied_keys"),
        "summary":     body.summary,
    }


# ── GET /api/v1/ai-bridge/errors ─────────────────────────────────────────────

@router.get("/errors", dependencies=[_auth])
def list_bridge_errors() -> Dict[str, Any]:
    """List rejected result files (from ai_bridge/errors/)."""
    from ..services.ai_bridge import _errors_dir
    errors: List[Dict[str, Any]] = []
    for p in sorted(_errors_dir().glob("*.json")):
        try:
            errors.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return {"count": len(errors), "errors": errors}


# ── GET /api/v1/ai-bridge/results/{task_id} ──────────────────────────────────

@router.get("/results/{task_id}", dependencies=[_auth])
def get_bridge_result(task_id: str) -> Dict[str, Any]:
    """
    Read a processed result file for preview (read-only).

    Checks processed/ first, then errors/ if not found.
    """
    from ..services.ai_bridge import _processed_dir, _errors_dir
    for folder in (_processed_dir(), _errors_dir()):
        p = folder / f"{task_id}_result.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))
        # also check without _result suffix (error archive uses just task_id.json)
        p2 = folder / f"{task_id}.json"
        if p2.exists():
            try:
                return json.loads(p2.read_text(encoding="utf-8"))
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))
    raise HTTPException(status_code=404, detail=f"No result found for task {task_id!r}.")


# ── GET /api/v1/ai-bridge/templates ──────────────────────────────────────────

@router.get("/templates", dependencies=[_auth])
def list_task_templates() -> Dict[str, Any]:
    """List all available task types with their schemas."""
    return {
        "count":     len(TASK_TEMPLATES),
        "templates": {
            k: {
                "description":   v["description"],
                "result_schema": v["result_schema"],
            }
            for k, v in TASK_TEMPLATES.items()
        },
    }
