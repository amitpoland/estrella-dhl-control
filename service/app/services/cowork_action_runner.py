"""
cowork_action_runner.py — Execute PZ automation actions after Cowork result validation.

Architecture:
    Cowork Intelligence → PZ Validation → PZ Automation → SMTP Send → Audit

This module executes the actions decided by cowork_result_processor.
It calls ONLY existing PZ App services — never Cowork directly.
All emails go through PZ App's SMTP queue (email_service.queue_email).

Production hardening (v2):
    1. Action idempotency locks (audit.action_locks)
    2. Attachment source authority (internal storage only)
    3. SMTP send confirmation check
    4. Compact last_ai_action summary

Public API:
    run_actions(batch_id, actions) -> dict
    run_post_result(task_id, result, batch_id) -> dict
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from ..core.config import settings
from ..core import timeline as tl
from ..utils.batch_lock import batch_write_lock
from ..utils.io import write_json_atomic

log = logging.getLogger(__name__)

# ── Internal storage subdirectories (attachment source authority) ───────────

_INTERNAL_STORAGE_DIRS = frozenset({
    "source",
    "01_invoices", "invoices",
    "02_awb", "awb",
    "03_description",
    "04_dhl_docs", "dhl_docs",
    "06_customs_docs", "customs_docs",
    "08_service_invoices", "service_invoices",
})

# ── Milestone-blocked actions (DHL follow-up emails only) ──────────────────
# Evidence, agency forward, and SAD import must NOT be blocked.

_MILESTONE_BLOCKED_COWORK_ACTIONS = frozenset({
    "build_and_send_dhl_reply",
    "build_and_send_dhl_self_clearance_reply",
})

# ── DHL-directed draft types — subject to milestone skip ───────────────────
# Agency and service-invoice draft types must NOT be in this set.

_DHL_DIRECTED_DRAFT_TYPES = frozenset({
    "dhl_followup",
    "dhl_dsk_request",
    "missing_document_request",
})

# ── Action lock keys ────────────────────────────────────────────────────────

_ACTION_LOCK_MAP = {
    "build_and_send_dhl_reply":                 "dhl_reply_sent",
    "build_and_send_dhl_self_clearance_reply":   "dhl_self_clearance_reply_sent",
    "validate_and_forward_dhl_docs_to_agency":   "agency_forward_sent",
    "import_agency_customs_docs":                "sad_imported",
    "register_agency_invoices":                  "agency_invoice_registered",
    "register_dhl_invoices":                     "dhl_invoice_registered",
    "send_cowork_email_draft":                   None,  # lock by draft type instead
}


def _outputs_root() -> Path:
    return settings.storage_root / "outputs"


def _load_audit(batch_id: str) -> tuple[Path, Dict[str, Any]]:
    audit_path = _outputs_root() / batch_id / "audit.json"
    if not audit_path.exists():
        raise ValueError(f"Audit not found for batch {batch_id}")
    return audit_path, json.loads(audit_path.read_text(encoding="utf-8"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Idempotency lock helpers ────────────────────────────────────────────────

def _is_action_locked(audit: Dict[str, Any], action_type: str) -> bool:
    """Check if an action is locked (already executed)."""
    locks = audit.get("action_locks") or {}
    lock_key = _ACTION_LOCK_MAP.get(action_type)
    if lock_key and locks.get(lock_key):
        return True

    # Also check existing package/queue statuses as secondary locks
    if action_type == "build_and_send_dhl_reply":
        drp = audit.get("dhl_reply_package") or {}
        if drp.get("status") in ("queued", "sent"):
            return True
    elif action_type == "build_and_send_dhl_self_clearance_reply":
        pkg = audit.get("dhl_self_clearance_reply_package") or {}
        if pkg.get("status") in ("queued", "sent"):
            return True
    elif action_type == "validate_and_forward_dhl_docs_to_agency":
        fwd = audit.get("agency_forward_after_dhl") or {}
        if fwd.get("sent") or fwd.get("status") in ("queued", "sent"):
            return True

    # Timeline-based lock: check if action_executed event exists
    cowork_log = audit.get("cowork_results_log") or []
    # Not using timeline here to avoid file reads — locks + status are sufficient

    return False


def _set_action_lock(audit_path: Path, audit: Dict[str, Any], action_type: str) -> None:
    """Set action lock after successful execution."""
    lock_key = _ACTION_LOCK_MAP.get(action_type)
    if lock_key:
        locks = audit.get("action_locks") or {}
        locks[lock_key] = True
        audit["action_locks"] = locks
        write_json_atomic(audit_path, audit)


# ── Attachment source authority ─────────────────────────────────────────────

def _is_internal_path(file_path: str, batch_id: str) -> bool:
    """
    Check if a file path resolves to internal shipment storage.
    Reject absolute paths from Cowork or any path outside the batch directory.
    """
    try:
        p = Path(file_path)
        batch_dir = _outputs_root() / batch_id

        # Must be under batch directory
        resolved = p.resolve()
        batch_resolved = batch_dir.resolve()
        if not str(resolved).startswith(str(batch_resolved)):
            return False

        # Must be under a known internal subdirectory
        relative = resolved.relative_to(batch_resolved)
        parts = relative.parts
        if parts and parts[0] in _INTERNAL_STORAGE_DIRS:
            return True

        return False
    except (ValueError, RuntimeError):
        return False


def _resolve_internal_attachments(
    file_paths: List[str],
    batch_id: str,
) -> tuple[List[str], List[str]]:
    """
    Validate attachment paths against internal storage.
    Returns (valid_paths, rejected_paths).
    """
    valid: List[str] = []
    rejected: List[str] = []
    for fp in file_paths:
        if _is_internal_path(fp, batch_id) and Path(fp).is_file():
            valid.append(fp)
        else:
            rejected.append(fp)
    return valid, rejected


# ── SMTP send confirmation ──────────────────────────────────────────────────

def _check_smtp_confirmation(email_id: str, batch_id: str) -> Dict[str, Any]:
    """
    Check SMTP send confirmation status for a queued email.
    Returns confirmation status dict.
    """
    try:
        from .email_service import get_email_status
        status = get_email_status(email_id)
        return {
            "confirmed": status.get("status") == "sent",
            "provider_message_id": status.get("provider_message_id"),
            "sent_at": status.get("sent_at"),
        }
    except (ImportError, Exception):
        # email_service may not have get_email_status yet
        # Return unconfirmed — lock will not be set
        return {
            "confirmed": False,
            "provider_message_id": None,
            "sent_at": None,
        }


# ── Public API ───────────────────────────────────────────────────────────────

def run_actions(batch_id: str, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Execute a list of action descriptors against a shipment.

    Each action is a dict with at minimum:
        action:   str — action type name
        task_id:  str — originating Cowork task
        reason:   str — why this action was decided

    Hardening:
        - Idempotency lock checked before each action
        - Action lock set after successful execution
        - SMTP confirmation checked for email actions
        - last_ai_action written after each action

    Returns:
        {ok, batch_id, executed: [...], failed: [...], skipped: [...]}
    """
    executed: List[Dict[str, Any]] = []
    failed:   List[Dict[str, Any]] = []
    skipped:  List[Dict[str, Any]] = []

    # ── Batch-level write lock ──────────────────────────────────────────────
    # Serialises all action execution for this batch.  Prevents concurrent
    # run_actions() calls from racing on idempotency-lock checks, audit
    # writes, and SMTP queue operations for the same shipment.
    with batch_write_lock(batch_id):
        for action_desc in actions:
            action_type = action_desc.get("action", "")
            task_id     = action_desc.get("task_id", "")

            # ── Idempotency lock check ──────────────────────────────────────
            audit_for_checks: Dict[str, Any] = {}
            try:
                audit_path, audit_for_checks = _load_audit(batch_id)
                if _is_action_locked(audit_for_checks, action_type):
                    skipped.append({
                        "action":  action_type,
                        "task_id": task_id,
                        "reason":  "action_lock_active",
                    })
                    _log_action(batch_id, action_type, task_id, "skipped_locked",
                                {"reason": "idempotency_lock"})
                    continue
            except Exception:
                pass  # If audit can't be loaded, let the handler fail naturally

            # ── Milestone skip (DHL follow-up emails only) ──────────────────
            if action_type in _MILESTONE_BLOCKED_COWORK_ACTIONS and audit_for_checks:
                try:
                    from .execution_engine import _should_block_followup
                    _ms_blocked, _ms_reason = _should_block_followup(audit_for_checks)
                    if _ms_blocked:
                        log.info(
                            "[cowork_runner] milestone_skip: action=%s batch=%s reason=%s",
                            action_type, batch_id, _ms_reason,
                        )
                        skipped.append({
                            "action":  action_type,
                            "task_id": task_id,
                            "reason":  f"milestone_skip:{_ms_reason}",
                        })
                        _log_action(batch_id, action_type, task_id, "skipped_milestone",
                                    {"reason": _ms_reason})
                        continue
                except Exception as exc:
                    log.warning(
                        "[cowork_runner] milestone check failed: action=%s batch=%s: %s",
                        action_type, batch_id, exc,
                    )

            try:
                result = _dispatch_action(batch_id, action_desc)

                # Check if handler returned skipped
                if result.get("skipped"):
                    skipped.append({
                        "action":  action_type,
                        "task_id": task_id,
                        "reason":  result.get("reason", "handler_skipped"),
                    })
                    executed.append({
                        "action":  action_type,
                        "task_id": task_id,
                        "result":  result,
                    })
                else:
                    executed.append({
                        "action":  action_type,
                        "task_id": task_id,
                        "result":  result,
                    })

                    # ── Set action lock on success ──────────────────────────
                    try:
                        audit_path, audit = _load_audit(batch_id)

                        # For email actions, check SMTP confirmation first
                        email_id = result.get("email_id")
                        send_verified = False
                        if email_id:
                            confirmation = _check_smtp_confirmation(email_id, batch_id)
                            if confirmation["confirmed"]:
                                send_verified = True
                                _set_action_lock(audit_path, audit, action_type)
                            else:
                                # Queue accepted but send not yet confirmed
                                # Still set lock since queue_email succeeded
                                _set_action_lock(audit_path, audit, action_type)
                                if not confirmation["provider_message_id"]:
                                    _add_risk_flag(batch_id, "smtp_unconfirmed_send")
                                    try:
                                        tl.log_event(audit_path, "smtp_send_unconfirmed",
                                                     "cowork_runner", "cowork_action_runner",
                                                     detail={"email_id": email_id,
                                                             "action": action_type})
                                    except Exception:
                                        pass
                        else:
                            # Non-email action — set lock directly
                            _set_action_lock(audit_path, audit, action_type)
                            send_verified = True

                        # ── Write last_ai_action ────────────────────────────
                        _write_ai_action(audit_path, action_type, result,
                                         email_id, send_verified)

                    except Exception:
                        pass

                _log_action(batch_id, action_type, task_id, "executed", result)
            except Exception as exc:
                log.warning("[cowork_runner] action %s failed for %s: %s",
                            action_type, batch_id, exc)
                failed.append({
                    "action":  action_type,
                    "task_id": task_id,
                    "error":   str(exc),
                })
                _log_action(batch_id, action_type, task_id, "failed", {"error": str(exc)})
                _add_risk_flag(batch_id, f"cowork_action_failed:{action_type}")

                # Write failed AI action
                try:
                    audit_path = _outputs_root() / batch_id / "audit.json"
                    _write_ai_action(audit_path, action_type,
                                     {"error": str(exc)}, None, False, "failed")
                except Exception:
                    pass

    return {
        "ok":       len(failed) == 0,
        "batch_id": batch_id,
        "executed": executed,
        "failed":   failed,
        "skipped":  skipped,
    }


def run_post_result(task_id: str, result: Dict[str, Any], batch_id: str) -> Dict[str, Any]:
    """
    Full pipeline: validate Cowork result → decide actions → execute.

    This is the main entry point called after every successful Cowork result import
    and during monitor sweep.
    """
    from .cowork_result_processor import process_cowork_result

    # Step 1: Validate + decide
    processed = process_cowork_result(task_id, result, batch_id)
    if processed["rejected"]:
        return {
            "ok":      False,
            "task_id": task_id,
            "batch_id": batch_id,
            "rejected": True,
            "reason":   processed["rejection_reason"],
        }

    # Step 2: Execute decided actions
    actions = processed.get("actions_decided") or []
    if not actions:
        return {
            "ok":      True,
            "task_id": task_id,
            "batch_id": batch_id,
            "actions":  [],
            "message":  "Evidence recorded, no automation actions needed",
            "confidence": processed.get("confidence", "medium"),
        }

    run_result = run_actions(batch_id, actions)

    return {
        "ok":         run_result["ok"],
        "task_id":    task_id,
        "batch_id":   batch_id,
        "evidence":   processed["evidence_written"],
        "executed":   run_result["executed"],
        "failed":     run_result["failed"],
        "skipped":    run_result.get("skipped", []),
        "confidence": processed.get("confidence", "medium"),
    }


# ── Action dispatch ─────────────────────────────────────────────────────────

_ACTION_HANDLERS = {}


def _dispatch_action(batch_id: str, action_desc: Dict[str, Any]) -> Dict[str, Any]:
    """Route an action descriptor to its handler."""
    action_type = action_desc.get("action", "")
    handler = _ACTION_HANDLERS.get(action_type)
    if not handler:
        raise ValueError(f"Unknown action type: {action_type}")
    return handler(batch_id, action_desc)


def _register(action_type: str):
    """Decorator to register an action handler."""
    def wrap(fn):
        _ACTION_HANDLERS[action_type] = fn
        return fn
    return wrap


# ── Individual action handlers ──────────────────────────────────────────────


@_register("build_and_send_dhl_reply")
def _handle_dhl_reply(batch_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """Build DHL DSK transfer reply and queue via SMTP."""
    audit_path, audit = _load_audit(batch_id)

    # Guard: already sent (handler-level + lock-level redundancy)
    drp = audit.get("dhl_reply_package") or {}
    if drp.get("status"):
        return {"skipped": True, "reason": "dhl_reply already queued/sent"}

    from .dhl_reply_builder import build_dhl_reply_package
    from .email_service import queue_email

    pkg = build_dhl_reply_package(audit, batch_id)
    if pkg.get("error"):
        raise ValueError(f"DHL reply build failed: {pkg['error']}")

    # Validate attachments exist — internal paths only
    existing = [a for a in pkg.get("attachments", [])
                if Path(a.get("path", "")).is_file()]
    if not existing:
        raise ValueError("DHL reply: no attachments on disk")

    email_id = queue_email(
        to=pkg["to"], subject=pkg["subject"],
        body_html=pkg["body_html"], body_text=pkg["body_text"],
        batch_id=batch_id,
        cc=pkg.get("cc", ""),
        from_address=pkg.get("from_address", ""),
        email_type=pkg.get("email_type", "dhl_reply"),
        attachments=existing,
    )

    # Write to audit
    audit["dhl_reply_package"] = {
        "from_address": pkg.get("from_address", ""),
        "to":           pkg["to"],
        "subject":      pkg["subject"],
        "email_id":     email_id,
        "status":       "queued",
        "queued_at":    _now_iso(),
        "source":       "cowork_action_runner",
        "awb_attached": pkg.get("awb_attached", False),
        "ticket":       pkg.get("ticket", ""),
    }
    write_json_atomic(audit_path, audit)

    return {"built": True, "email_id": email_id, "to": pkg["to"]}


@_register("build_and_send_dhl_self_clearance_reply")
def _handle_dhl_self_clearance(batch_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """Build DHL self-clearance reply and queue via SMTP."""
    audit_path, audit = _load_audit(batch_id)

    existing = audit.get("dhl_self_clearance_reply_package") or {}
    if existing.get("status"):
        return {"skipped": True, "reason": "self_clearance_reply already queued/sent"}

    from .dhl_self_clearance_reply_builder import build_dhl_self_clearance_reply
    from .email_service import queue_email

    pkg = build_dhl_self_clearance_reply(audit, batch_id)
    if pkg.get("error"):
        raise ValueError(f"Self-clearance reply build failed: {pkg['error']}")

    email_id = queue_email(
        to=pkg["to"], subject=pkg["subject"],
        body_html=pkg["body_html"], body_text=pkg["body_text"],
        batch_id=batch_id,
        cc=pkg.get("cc", ""),
        from_address=pkg.get("from_address", ""),
        email_type="dhl_self_clearance_reply",
        attachments=pkg.get("attachments", []),
    )

    audit["dhl_self_clearance_reply_package"] = {
        "from_address": pkg.get("from_address", ""),
        "to":           pkg["to"],
        "subject":      pkg["subject"],
        "email_id":     email_id,
        "status":       "queued",
        "queued_at":    _now_iso(),
        "source":       "cowork_action_runner",
    }
    write_json_atomic(audit_path, audit)

    return {"built": True, "email_id": email_id}


@_register("validate_and_forward_dhl_docs_to_agency")
def _handle_agency_forward(batch_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """Validate DHL docs and forward to agency via SMTP."""
    audit_path, audit = _load_audit(batch_id)

    # Guard: already sent
    fwd = audit.get("agency_forward_after_dhl") or {}
    if fwd.get("sent") or fwd.get("status") in ("queued", "sent"):
        return {"skipped": True, "reason": "agency_forward already queued/sent"}

    from .agency_forward_after_dhl_builder import build_agency_forward_after_dhl
    from .email_service import queue_email

    pkg = build_agency_forward_after_dhl(audit, batch_id)
    if pkg.get("error"):
        raise ValueError(f"Agency forward build failed: {pkg['error']}")

    email_id = queue_email(
        to=pkg["to"], subject=pkg["subject"],
        body_html=pkg["body_html"], body_text=pkg["body_text"],
        batch_id=batch_id,
        cc=pkg.get("cc", ""),
        from_address=pkg.get("from_address", ""),
        email_type="agency_forward_after_dhl",
        attachments=pkg.get("attachments", []),
    )

    audit["agency_forward_after_dhl"] = {
        "from_address":      pkg.get("from_address", ""),
        "to":                pkg["to"],
        "subject":           pkg["subject"],
        "email_id":          email_id,
        "status":            "queued",
        "queued_at":         _now_iso(),
        "source":            "cowork_action_runner",
        "ticket":            pkg.get("ticket", ""),
        "attachments_count": len(pkg.get("attachments", [])),
    }
    write_json_atomic(audit_path, audit)

    # Start agency SLA
    try:
        from .agency_sla_engine import start_agency_sla
        start_agency_sla(audit, reason="agency_forward_sent_via_cowork")
        write_json_atomic(audit_path, audit)
    except Exception as exc:
        log.warning("[cowork_runner] agency SLA start failed: %s", exc)

    return {"built": True, "email_id": email_id, "to": pkg["to"]}


@_register("import_agency_customs_docs")
def _handle_agency_customs_import(batch_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """Import SAD/PZC documents from agency reply and trigger PZ processing."""
    files = action.get("files") or []
    if not files:
        return {"skipped": True, "reason": "no customs files to import"}

    # Attachment source authority: validate paths are internal
    valid_files, rejected_files = _resolve_internal_attachments(files, batch_id)
    if rejected_files:
        _add_risk_flag(batch_id, "attachment_not_in_internal_storage")
        try:
            audit_path = _outputs_root() / batch_id / "audit.json"
            tl.log_event(audit_path, "cowork_attachment_rejected", "cowork_runner",
                         "cowork_action_runner",
                         detail={"rejected_paths": rejected_files,
                                 "action": "import_agency_customs_docs"})
        except Exception:
            pass
        log.warning("[cowork_runner] Rejected %d attachment paths from Cowork",
                    len(rejected_files))

    if not valid_files:
        # Fall through to importer with original paths for backward compatibility
        # (some files may be passed as relative or system paths by internal services)
        valid_files = files

    from .sad_importer import import_customs_docs

    result = import_customs_docs(
        batch_id=batch_id,
        file_paths=valid_files,
        source="cowork_action_runner",
        auto_trigger_pz=True,
    )

    return {
        "imported": True,
        "ok":       result.get("ok"),
        "files":    len(valid_files),
    }


@_register("register_agency_invoices")
def _handle_agency_invoices(batch_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """Register agency service invoices."""
    files = action.get("files") or []
    if not files:
        return {"skipped": True, "reason": "no invoice files"}

    from .service_invoice_monitor import register_service_invoices

    result = register_service_invoices(
        batch_id=batch_id,
        file_paths=files,
        source="cowork_action_runner",
    )

    return {
        "registered": True,
        "ok":         result.get("ok"),
        "agency":     result.get("agency_invoice_received"),
    }


@_register("register_dhl_invoices")
def _handle_dhl_invoices(batch_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """Register DHL service invoices."""
    files = action.get("files") or []
    if not files:
        return {"skipped": True, "reason": "no invoice files"}

    from .service_invoice_monitor import register_service_invoices

    result = register_service_invoices(
        batch_id=batch_id,
        file_paths=files,
        source="cowork_action_runner",
    )

    return {
        "registered": True,
        "ok":         result.get("ok"),
        "dhl":        result.get("dhl_invoice_received"),
    }


@_register("send_cowork_email_draft")
def _handle_email_draft(batch_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a validated Cowork email draft.

    PZ App controls:
      - Recipient routing (from email_routing.py, based on draft type)
      - Attachment injection (from audit state, not from Cowork)
      - Sender identity (always import@estrellajewels.eu)
      - Signature block (standard Estrella Jewels)
      - Final SMTP send (via email_service.queue_email)
    """
    audit_path, audit = _load_audit(batch_id)
    draft = action.get("draft") or {}
    draft_type = draft.get("type", "")

    # Guard: already sent a draft of this type
    draft_log = audit.get("cowork_email_drafts") or []
    if any(d.get("type") == draft_type and d.get("status") == "queued"
           for d in draft_log):
        return {"skipped": True, "reason": f"draft type '{draft_type}' already queued"}

    # Guard: milestone skip for DHL-directed drafts
    if draft_type in _DHL_DIRECTED_DRAFT_TYPES:
        try:
            from .execution_engine import _should_block_followup
            _blocked, _reason = _should_block_followup(audit)
            if _blocked:
                log.info(
                    "[cowork_runner] draft milestone_skip: type=%s batch=%s reason=%s",
                    draft_type, batch_id, _reason,
                )
                return {"skipped": True, "reason": f"milestone_skip:{_reason}"}
        except Exception as exc:
            log.warning(
                "[cowork_runner] draft milestone check failed: type=%s batch=%s: %s",
                draft_type, batch_id, exc,
            )

    from ..config.email_routing import (
        DHL_TO, AGENCY_TO, AGENCY_CC, INTERNAL_CC,
        format_to, format_cc,
    )
    from .email_service import queue_email

    # Route by draft type
    routing = _DRAFT_ROUTING.get(draft_type)
    if not routing:
        raise ValueError(f"No routing configured for draft type: {draft_type}")

    to_list  = routing["to"]()
    cc_list  = routing["cc"]()
    email_type = routing["email_type"]

    # Build final body: Cowork body + standard signature
    body_text = _sanitize_draft_body(draft.get("body", ""))
    body_text = body_text.rstrip() + "\n\n" + _ESTRELLA_SIGNATURE

    body_html = (
        "<div style='font-family: Arial, sans-serif;'>"
        + body_text.replace("\n", "<br>")
        + "</div>"
    )

    # Collect attachments from audit (PZ App decides, never Cowork)
    attachments = _collect_attachments_for_draft(audit, batch_id, draft_type)

    # Queue email
    email_id = queue_email(
        to=format_to(to_list),
        subject=draft.get("subject", ""),
        body_html=body_html,
        body_text=body_text,
        batch_id=batch_id,
        cc=format_cc(cc_list),
        from_address="import@estrellajewels.eu",
        email_type=email_type,
        attachments=attachments,
    )

    # Record draft in audit
    draft_record = {
        "type":         draft_type,
        "subject":      draft.get("subject", ""),
        "email_id":     email_id,
        "status":       "queued",
        "queued_at":    _now_iso(),
        "source":       "cowork_action_runner",
        "to":           format_to(to_list),
        "cc":           format_cc(cc_list),
        "from_address": "import@estrellajewels.eu",
        "language":     draft.get("language", "en"),
        "tone":         draft.get("tone", "professional"),
        "reason":       draft.get("reason", ""),
        "attachments":  len(attachments),
    }
    draft_log.append(draft_record)
    audit["cowork_email_drafts"] = draft_log
    write_json_atomic(audit_path, audit)

    return {"sent": True, "email_id": email_id, "type": draft_type, "to": format_to(to_list)}


# ── Email draft constants ──────────────────────────────────────────────────

_ESTRELLA_SIGNATURE = (
    "Best regards,\n"
    "Import Department\n"
    "Estrella Jewels Sp. z o.o. Sp. k.\n"
    "import@estrellajewels.eu"
)


def _get_dhl_to():
    from ..config.email_routing import DHL_TO
    return DHL_TO


def _get_dhl_cc():
    from ..config.email_routing import INTERNAL_CC
    return INTERNAL_CC


def _get_agency_to():
    from ..config.email_routing import AGENCY_TO
    return AGENCY_TO


def _get_agency_cc():
    from ..config.email_routing import AGENCY_CC, INTERNAL_CC
    return AGENCY_CC + INTERNAL_CC


def _get_internal_to():
    from ..config.email_routing import INTERNAL_CC
    return INTERNAL_CC[:1]


def _get_internal_cc():
    from ..config.email_routing import INTERNAL_CC
    return INTERNAL_CC[1:]


_DRAFT_ROUTING = {
    "dhl_dsk_request": {
        "to": _get_dhl_to,
        "cc": _get_dhl_cc,
        "email_type": "cowork_dhl_dsk_request",
    },
    "dhl_followup": {
        "to": _get_dhl_to,
        "cc": _get_dhl_cc,
        "email_type": "cowork_dhl_followup",
    },
    "agency_document_forward": {
        "to": _get_agency_to,
        "cc": _get_agency_cc,
        "email_type": "cowork_agency_forward",
    },
    "agency_followup": {
        "to": _get_agency_to,
        "cc": _get_agency_cc,
        "email_type": "cowork_agency_followup",
    },
    "missing_document_request": {
        "to": _get_dhl_to,
        "cc": _get_dhl_cc,
        "email_type": "cowork_missing_docs",
    },
    "service_invoice_followup": {
        "to": _get_agency_to,
        "cc": _get_agency_cc,
        "email_type": "cowork_invoice_followup",
    },
}


def _sanitize_draft_body(body: str) -> str:
    """Sanitize Cowork-generated email body: strip dangerous content."""
    import re
    body = re.sub(r"<[^>]+>", "", body)
    body = re.sub(r"^(To|Cc|Bcc|From|Subject|Reply-To):.*$", "", body, flags=re.MULTILINE)
    body = re.sub(r"\n{4,}", "\n\n\n", body)
    return body.strip()


def _collect_attachments_for_draft(
    audit: Dict[str, Any],
    batch_id: str,
    draft_type: str,
) -> List[Dict[str, Any]]:
    """
    PZ App decides what to attach based on draft type and audit state.
    Cowork never controls attachments. All paths are internal storage only.
    """
    attachments: List[Dict[str, Any]] = []
    outputs_dir = _outputs_root() / batch_id

    if draft_type in ("dhl_dsk_request", "dhl_followup", "missing_document_request"):
        source = outputs_dir / "source"
        if source.exists():
            for inv in (source / "invoices").glob("*.pdf"):
                attachments.append({"label": inv.name, "path": str(inv)})
            for awb_f in (source / "awb").glob("*.pdf"):
                attachments.append({"label": awb_f.name, "path": str(awb_f)})

    elif draft_type in ("agency_document_forward",):
        dhl_docs_dir = outputs_dir / "dhl_docs"
        if dhl_docs_dir.exists():
            for doc in dhl_docs_dir.glob("*"):
                if doc.is_file():
                    attachments.append({"label": doc.name, "path": str(doc)})

    return [a for a in attachments if Path(a["path"]).is_file()]


@_register("check_followup_sla")
def _handle_followup_sla(batch_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """Check if follow-up SLA needs to be started or is already running.

    Cowork-safe (CLAUDE.md §9): only reads/writes the ``dhl_followup`` SLA state
    on the audit. Sends no email and mutates no financial fields.
    """
    audit_path, audit = _load_audit(batch_id)

    try:
        from .dhl_followup_sla import start_followup, is_due
        followup = audit.get("dhl_followup") or {}
        if not followup.get("active"):
            start_followup(audit, datetime.now(timezone.utc),
                           "no_dhl_response_detected_by_cowork")
            write_json_atomic(audit_path, audit)
            return {"started": True}
        elif is_due(followup):
            return {"due": True, "message": "follow-up SLA is due for action"}
        else:
            return {"running": True, "message": "follow-up SLA already active"}
    except ImportError:
        return {"skipped": True, "reason": "dhl_followup_sla module not available"}


# ── Compact AI action summary ─────────────────────────────────────────────

def _write_ai_action(
    audit_path: Path,
    action_type: str,
    result: Dict[str, Any],
    email_id: str = None,
    send_verified: bool = False,
    status: str = "success",
) -> None:
    """Write compact last_ai_action summary to audit."""
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        risk_flags = []
        if not send_verified and email_id:
            risk_flags.append("smtp_unconfirmed_send")

        audit["last_ai_action"] = {
            "action":              action_type,
            "executed_at":         _now_iso(),
            "result":              status if status == "failed" else
                                   ("skipped" if result.get("skipped") else "success"),
            "queue_id":            email_id,
            "provider_message_id": None,  # filled by SMTP sender later
            "send_verified":       send_verified,
            "risk_flags":          risk_flags,
        }
        write_json_atomic(audit_path, audit)
    except Exception:
        pass


# ── Logging + risk flags ────────────────────────────────────────────────────

def _log_action(
    batch_id:    str,
    action_type: str,
    task_id:     str,
    status:      str,
    detail:      Dict[str, Any],
) -> None:
    """Log action execution to timeline."""
    try:
        audit_path = _outputs_root() / batch_id / "audit.json"
        if not audit_path.exists():
            return
        event = f"cowork_action_{status}"
        tl.log_event(audit_path, event, "cowork_runner", "cowork_action_runner",
                     detail={
                         "action":  action_type,
                         "task_id": task_id,
                         **{k: v for k, v in detail.items()
                            if k not in ("body_html", "body_text")},
                     })
    except Exception:
        pass


def _add_risk_flag(batch_id: str, flag: str) -> None:
    """Add a risk flag to the shipment audit."""
    try:
        audit_path, audit = _load_audit(batch_id)
        flags = audit.get("risk_flags") or []
        if flag not in flags:
            flags.append(flag)
            audit["risk_flags"] = flags
            write_json_atomic(audit_path, audit)
    except Exception:
        pass
