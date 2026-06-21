"""
execution_engine.py — Centralized write-action execution layer.

All write actions flow through execute_action(). No action bypasses this module.

Architecture
------------
UI → POST /api/v1/execute/{action}
       → execution_engine.execute_action(action_type, batch_id, payload)
           → load readiness (batch / dhl / wfirma)
           → check idempotency (execution_log.json)
           → route to action handler
           → write execution log entry
           → return structured result

Supported actions
-----------------
wfirma_create     — create one wFirma reservation for a (batch_id, client_name) pair
closure_confirm   — apply final closure after ready_for_closure gate passes
dhl_send_reply    — build DHL customs reply package and queue via email_service

Safety rules
------------
- closure_confirm is the only write path to apply_closure — never called directly from UI
- dhl_send_reply only queues email — never sends directly via SMTP
- dhl_send_reply never sends with missing required attachments
- Never auto-executes in background
- Never writes to audit.json outside of action handlers — execution_log.json is separate
- All write actions require explicit readiness checks to pass first
- Unknown action_type always returns error; never falls through silently
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ..core.config import settings

log = logging.getLogger(__name__)


# ── Execution log path ────────────────────────────────────────────────────────

def _log_path() -> Path:
    """Return path to execution log. Evaluated at call time so tests can patch settings."""
    return settings.storage_root / "execution_log.json"


# ── Milestone skip helpers ────────────────────────────────────────────────────

def _load_audit_for_batch(batch_id: str) -> Optional[Dict[str, Any]]:
    """Load audit.json for batch from outputs/ or working/. Returns None on miss/error."""
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / batch_id / "audit.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception as exc:
                log.error("_load_audit_for_batch: parse error batch=%s: %s", batch_id, exc)
    return None


def _should_block_followup(audit: Dict[str, Any]) -> tuple[bool, str]:
    """
    Return (True, reason) when a shipment milestone makes a follow-up email redundant.

    Milestones checked (in priority order):
      customs_docs_received — SAD uploaded; DHL has already responded with docs
      pz_generated          — PZ document exists; customs flow is complete
      already_completed     — shipment closed

    Returns (False, "") when no milestone blocks execution.
    """
    if (audit.get("customs_docs") or {}).get("received"):
        return True, "customs_docs_received"
    if audit.get("pz_generated") or audit.get("pz_filename"):
        return True, "pz_generated"
    if audit.get("status") == "completed":
        return True, "already_completed"
    return False, ""


# ── Idempotency layer ─────────────────────────────────────────────────────────

def _load_log() -> list[Dict[str, Any]]:
    """Load existing execution log entries. Returns empty list on any read error."""
    p = _log_path()
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        log.error("execution_log read error: %s", exc)
    return []


def _save_log(entries: list[Dict[str, Any]]) -> bool:
    """
    Atomically write execution log.

    Returns True on success, False on any write error.  Callers must check the
    return value — a False result means the idempotency record was NOT persisted.
    """
    p = _log_path()
    tmp = p.with_suffix(".tmp")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write via temp-then-rename
        tmp.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
        return True
    except Exception as exc:
        log.error("execution_log write error: %s", exc)
        # Clean up the .tmp file so it does not persist on disk on failure.
        # On Windows, tmp.replace(p) can fail if execution_log.json is held open,
        # leaving a stale .tmp file. Ignore any error in the cleanup itself.
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def _entry_key(action_type: str, batch_id: str, payload: Optional[Dict]) -> str:
    """Build a deduplication key for an action+batch+payload combination."""
    payload = payload or {}
    # For wfirma_create, differentiate by client_name so multiple clients in one
    # batch can each be created exactly once.
    client_name = payload.get("client_name", "")
    return f"{action_type}::{batch_id}::{client_name}"


def already_executed(action_type: str, batch_id: str, payload: Optional[Dict] = None) -> bool:
    """
    Return True if a successful execution log entry exists for this
    (action_type, batch_id, payload) combination.

    Only entries with status="ok" are considered executed — failed attempts
    are retryable.
    """
    key = _entry_key(action_type, batch_id, payload)
    for entry in _load_log():
        if (
            entry.get("key") == key
            and entry.get("status") == "ok"
        ):
            return True
    return False


def log_execution(
    action_type: str,
    batch_id: str,
    result: Dict[str, Any],
    payload: Optional[Dict] = None,
) -> bool:
    """
    Append one execution log entry.

    Does NOT write to audit.json. The execution log is a separate append-only
    record of every action the engine processed.

    Returns True if the entry was persisted, False if the write failed.  A
    False return means the idempotency record was lost — callers should surface
    this in the response so operators can be alerted.
    """
    entries = _load_log()
    entry: Dict[str, Any] = {
        "key":         _entry_key(action_type, batch_id, payload),
        "action_type": action_type,
        "batch_id":    batch_id,
        "payload":     payload or {},
        "status":      "ok" if result.get("ok") else "failed",
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "result":      result,
    }
    entries.append(entry)
    written = _save_log(entries)
    if written:
        log.info(
            "execution_log entry written: action=%s batch=%s status=%s",
            action_type, batch_id, entry["status"],
        )
    else:
        log.error(
            "execution_log entry LOST (write failed): action=%s batch=%s status=%s",
            action_type, batch_id, entry["status"],
        )
    return written


# ── Batch ID validation ───────────────────────────────────────────────────────

_BATCH_ID_FORBIDDEN = ("..", "/", "\\")


def _validate_batch_id(batch_id: str) -> None:
    """
    Reject batch_id values that would cause path traversal.

    Called before idempotency check and before any file path construction.
    Raises ValueError — caller catches and returns invalid_batch_id response.
    """
    if not batch_id:
        raise ValueError("batch_id must not be empty")
    for fragment in _BATCH_ID_FORBIDDEN:
        if fragment in batch_id:
            raise ValueError(
                f"batch_id contains forbidden character sequence: {fragment!r}"
            )


# ── Block helper ──────────────────────────────────────────────────────────────

def block(reason: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a structured blocked-action response.

    *ctx* may be a readiness dict (batch / dhl / wfirma).
    next_step is extracted from ctx.overall.next_step when available.
    """
    next_step: Optional[str] = None
    if isinstance(ctx, dict):
        overall = ctx.get("overall")
        if isinstance(overall, dict):
            next_step = overall.get("next_step")
    return {
        "ok":        False,
        "status":    "blocked",
        "error":     "blocked",
        "reason":    reason,
        "next_step": next_step,
    }


# ── Action handlers ───────────────────────────────────────────────────────────

def _call_wfirma_create(
    batch_id: str, client_name: str, operator: str = "",
) -> Dict[str, Any]:
    """
    Invoke wfirma_reservation_create.create_one_reservation.
    Returns the raw result dict (ok / code / wfirma_reservation_id / error).

    ``operator`` attributes this automation-triggered live create; the service
    resolves a blank value to its attribution sentinel.
    """
    from .wfirma_reservation_create import create_one_reservation
    return create_one_reservation(batch_id, client_name, operator=operator)


def _call_closure_apply(batch_id: str, approved_by: str = "operator") -> Dict[str, Any]:
    """
    Invoke shipment_closure.closure_for_batch — the controlled write path.

    Called only from the closure_confirm branch after both readiness gates pass.
    Sets audit.status=completed and ready_for_accounting=True when all checklist
    items pass.  Idempotent: returns already_completed=True if already done.
    """
    from .shipment_closure import closure_for_batch
    return closure_for_batch(batch_id, approved_by=approved_by)


def _call_dhl_reply(batch_id: str) -> Dict[str, Any]:
    """
    Build and queue the DHL customs reply email.

    Loads batch audit, assembles the reply package via dhl_reply_builder,
    queues the email via email_service, then writes audit fields on success.

    Returns
    -------
    On success:
        {"ok": True, "queued": True, "email_id": str, "to": str, "subject": str}
    On failure:
        {"ok": False, "error": "audit_not_found"}                — no audit.json for batch
        {"ok": False, "error": "missing_required_attachments",   — required files not on disk
                      "missing": [...]}
        {"ok": False, "error": "email_queue_failed",             — queue_email raised
                      "detail": str}

    Rules
    -----
    - Never sends with missing required attachments
    - Never writes audit fields unless queue_email succeeds
    - Does not send email directly — only queues for MCP pickup
    """
    import json as _json
    from datetime import datetime, timezone
    from pathlib import Path as _Path

    from ..core import timeline as tl
    from .dhl_reply_builder import build_dhl_reply_package
    from . import email_service

    # ── Load audit ────────────────────────────────────────────────────────────
    audit: Optional[Dict[str, Any]] = None
    audit_path: Optional[_Path] = None
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / batch_id / "audit.json"
        if p.exists():
            try:
                audit = _json.loads(p.read_text(encoding="utf-8"))
                audit_path = p
            except Exception as exc:
                log.error("_call_dhl_reply: failed to parse audit batch=%s: %s", batch_id, exc)
            break

    if audit is None or audit_path is None:
        log.warning("_call_dhl_reply: audit not found for batch=%s", batch_id)
        return {"ok": False, "error": "audit_not_found", "batch_id": batch_id}

    # ── Secondary idempotency: audit flag ─────────────────────────────────────
    if audit.get("dhl_reply_sent"):
        log.info("_call_dhl_reply: already_sent (audit flag) batch=%s", batch_id)
        return {"ok": True, "status": "skipped", "reason": "already_sent"}

    # ── Build package ─────────────────────────────────────────────────────────
    try:
        package = build_dhl_reply_package(audit, batch_id)
    except Exception as exc:
        log.error("_call_dhl_reply: builder failed batch=%s: %s", batch_id, exc)
        return {"ok": False, "error": "builder_failed", "detail": str(exc)}

    # ── Guard: no missing required attachments ────────────────────────────────
    missing = package.get("missing") or []
    if missing:
        log.warning(
            "_call_dhl_reply: missing attachments batch=%s: %s", batch_id, missing
        )
        return {
            "ok":      False,
            "error":   "missing_required_attachments",
            "missing": missing,
            "batch_id": batch_id,
        }

    # ── Queue email ───────────────────────────────────────────────────────────
    try:
        email_id = email_service.queue_email(
            to           = package["to"],
            subject      = package["subject"],
            body_html    = package["body_html"],
            body_text    = package.get("body_text", ""),
            batch_id     = batch_id,
            cc           = package.get("cc", ""),
            from_address = package.get("from_address", ""),
            email_type   = package.get("email_type", "dhl_reply"),
            attachments  = package.get("attachments", []),
        )
    except Exception as exc:
        log.error("_call_dhl_reply: queue_email failed batch=%s: %s", batch_id, exc)
        return {"ok": False, "error": "email_queue_failed", "detail": str(exc)}

    # ── Write audit fields (only after queue success) ─────────────────────────
    now = datetime.now(timezone.utc).isoformat()
    try:
        audit["dhl_reply_sent"]     = True
        audit["dhl_reply_queued_at"] = now
        audit["dhl_reply_package"] = {
            "email_id":   email_id,
            "status":     "queued",
            "queued_at":  now,
            "to":         package["to"],
            "to_list":    package.get("to_list", []),
            "cc":         package.get("cc", ""),
            "cc_list":    package.get("cc_list", []),
            "subject":    package["subject"],
            "email_type": package.get("email_type", "dhl_reply"),
            "source":     "execution_engine",
        }
        tmp = audit_path.with_suffix(".tmp")
        tmp.write_text(
            _json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        tmp.replace(audit_path)
        log.info(
            "_call_dhl_reply: audit written batch=%s email_id=%s", batch_id, email_id
        )
    except Exception as exc:
        # Email already queued — audit write failure is non-fatal but must be logged
        log.error(
            "_call_dhl_reply: audit write failed batch=%s (email already queued): %s",
            batch_id, exc,
        )

    # ── Timeline event ────────────────────────────────────────────────────────
    try:
        tl.log_event(
            audit_path,
            tl.EV_DHL_FOLLOWUP_SENT,
            trigger_source="execution_engine",
            actor="system",
            detail={
                "email_id": email_id,
                "to":       package["to"],
                "subject":  package["subject"],
            },
        )
    except Exception as exc:
        log.warning("_call_dhl_reply: timeline event failed (non-fatal): %s", exc)

    return {
        "ok":       True,
        "queued":   True,
        "email_id": email_id,
        "to":       package["to"],
        "subject":  package["subject"],
        "batch_id": batch_id,
    }


# ── Main entry point ──────────────────────────────────────────────────────────

def execute_action(
    action_type: str,
    batch_id:    str,
    payload:     Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Execute one controlled write action.

    Parameters
    ----------
    action_type : str
        One of: "wfirma_create" | "closure_confirm" | "dhl_send_reply"
    batch_id : str
        The shipment batch this action applies to.
    payload : dict | None
        Action-specific parameters (e.g. {"client_name": "Acme"} for wfirma_create).

    Returns
    -------
    dict with at minimum:
        ok     : bool
        status : "executed" | "skipped" | "blocked" | "error"
    """
    payload = payload or {}

    # ── 0. VALIDATE BATCH ID ─────────────────────────────────────────────────
    try:
        _validate_batch_id(batch_id)
    except ValueError as exc:
        return {"ok": False, "error": "invalid_batch_id", "detail": str(exc)}

    log.info("execute_action: action=%s batch=%s", action_type, batch_id)

    # ── 1. CHECK IDEMPOTENCY ──────────────────────────────────────────────────
    # Must happen before readiness load: if the action was already executed,
    # we must return "skipped" even when readiness services are unavailable.
    if already_executed(action_type, batch_id, payload):
        log.info("execute_action skipped (already_executed): action=%s batch=%s",
                 action_type, batch_id)
        return {
            "ok":     True,
            "status": "skipped",
            "reason": "already_executed",
        }

    # ── 2. LOAD READINESS ────────────────────────────────────────────────────
    try:
        from .batch_readiness import get_batch_readiness
        from .dhl_readiness   import get_dhl_readiness
        from .wfirma_reservation import get_reservation_preview

        batch = get_batch_readiness(batch_id)
        dhl   = get_dhl_readiness(batch_id)
        wf    = get_reservation_preview(batch_id)
    except Exception as exc:
        log.error("execute_action readiness load failed: action=%s batch=%s err=%s",
                  action_type, batch_id, exc)
        return {
            "ok":    False,
            "error": "readiness_load_failed",
            "detail": str(exc),
        }

    # ── 3. ROUTE ACTION ───────────────────────────────────────────────────────

    if action_type == "wfirma_create":
        client_name: str = payload.get("client_name", "")
        if not client_name:
            return {"ok": False, "error": "missing_field", "field": "client_name"}

        if not wf.get("ready_to_create"):
            blocking = wf.get("blocking_reasons", [])
            reason = blocking[0] if blocking else "wfirma preview not ready"
            return block(reason, batch)

        operator = ((payload or {}).get("approved_by")
                    or (payload or {}).get("operator") or "").strip()
        result = _call_wfirma_create(batch_id, client_name, operator=operator)

    elif action_type == "closure_confirm":
        # Gate 1: batch-readiness (warehouse / sales / wFirma / DHL domains)
        overall = batch.get("overall", {})
        if not overall.get("ready_for_closure"):
            blocked_domains = overall.get("blocked_domains", [])
            reason = f"closure not ready — blocked domains: {', '.join(blocked_domains)}" \
                     if blocked_domains else "closure not ready"
            return block(reason, batch)

        # Gate 2: audit-field checklist (customs_docs / PZ / agency invoice / DHL invoice)
        _audit = _load_audit_for_batch(batch_id)
        if _audit is not None:
            from .shipment_closure import evaluate_closure as _evaluate_closure
            _eval = _evaluate_closure(_audit)
            if not _eval["ready"]:
                missing = _eval.get("missing", [])
                reason = (
                    f"closure not ready — missing audit fields: {', '.join(missing)}"
                    if missing
                    else "closure not ready — audit fields incomplete"
                )
                return block(reason, batch)

        approved_by = ((payload or {}).get("approved_by") or "").strip() or "operator"
        result = _call_closure_apply(batch_id, approved_by=approved_by)

    elif action_type == "dhl_send_reply":
        dhl_status = dhl.get("dhl_status", "")
        if dhl_status != "dhl_contacted":
            return block(
                f"wrong DHL state for reply: got '{dhl_status}', expected 'dhl_contacted'",
                dhl,
            )

        # Milestone skip — return BEFORE log_execution so idempotency key is not written
        _audit = _load_audit_for_batch(batch_id)
        if _audit is not None:
            _blocked, _reason = _should_block_followup(_audit)
            if _blocked:
                log.info(
                    "execute_action milestone_skip: action=%s batch=%s reason=%s",
                    action_type, batch_id, _reason,
                )
                return {
                    "ok":    True,
                    "status": "skipped",
                    "reason": _reason,
                    "stage":  "milestone_skip",
                }

        result = _call_dhl_reply(batch_id)

    else:
        return {
            "ok":    False,
            "error": "unknown_action",
            "action_type": action_type,
        }

    # ── 4. WRITE EXECUTION LOG ────────────────────────────────────────────────
    log_written = log_execution(action_type, batch_id, result, payload)

    # ── 5. RETURN ─────────────────────────────────────────────────────────────
    # Flatten inner result fields to the top level so callers (dashboard, tests)
    # can access wfirma_reservation_id / ready / checks directly without
    # changing all existing field reads.
    #
    # If the log write failed, surface log_write_failed=True so operators can
    # investigate.  The action itself still succeeded — do not change ok/status.
    response: Dict[str, Any] = {
        "ok":     result.get("ok", False),
        "status": "executed",
        **{k: v for k, v in result.items() if k != "ok"},
    }
    if not log_written:
        response["log_write_failed"] = True
    return response
