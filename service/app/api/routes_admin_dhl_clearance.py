"""
routes_admin_dhl_clearance.py — Admin override route for W-5 P2 ignition (Model C).

Endpoints
=========
    POST /api/v1/admin/dhl-clearance/proactive-dispatch/{batch_id}
        Body: {force: bool=false, reason: str?, actor: str?}
        Invokes the P2 coordinator's dispatch_proactive() as the
        operator/Atlas-side ignition path. Sweep is the primary path
        (active_shipment_monitor); this route is the override / replay /
        rescue mechanism per ADR-019 Model C.

Auth
====
X-API-Key via require_api_key (canonical admin pattern, identical to
routes_admin_runtime_flags). NOT session-auth — this is an infrastructure
endpoint, not a user-facing one.

Force semantics (ADR-019 §"Truth table for triggered_by")
========================================================
    force=false (default): coordinator's idempotency rules apply; second
      call for an already-dispatched batch returns idempotent skip with
      `triggered_by="admin_override_normal"`.
    force=true: bypasses idempotency; re-emits dispatch; archives prior
      message_id into `audit.dhl_clearance.p2_dispatch_history[]`;
      requires `reason` (≥10 chars) AND `actor` (≥3 chars). WARNING-
      level audit emitted. `triggered_by="admin_override_force"`.

This route NEVER touches the per-phase lock from PR #57 (that lock is
for admin flag-flips). Per-batch concurrency between sweep + admin route
is handled by coordinator's idempotency check (the manifest-message_id
guard) plus the optional per-batch lock at the sweep substrate.

Audit events
============
    admin_dispatch_override — emitted on every POST (success or fail).
    Contains: actor, force, reason, batch_id, coordinator_status,
    coordinator_reason, message_id, triggered_by, timestamp.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel

from ..core.config import settings
from ..core.security import require_api_key
from ..services.dhl_clearance_coordinator import (
    DhlClearanceCoordinator,
    DispatchInput,
    OutOfScopeError,
    ForbiddenFlagCombination,
    ForceRequiresActor,
    CallerRejectsForce,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/dhl-clearance", tags=["admin"])
_auth = Depends(require_api_key)

# Operator accountability minimums per ADR-019.
_FORCE_REASON_MIN_CHARS: int = 10
_FORCE_ACTOR_MIN_CHARS:  int = 3

# Input-sanitisation caps for operator-supplied free text. Per security review:
# unbounded reason/actor lengths permit log-injection + audit-file bloat.
_FORCE_REASON_MAX_CHARS: int = 500
_FORCE_ACTOR_MAX_CHARS:  int = 64

# Path traversal guard: batch_id is used to construct file paths under
# storage_root/outputs/. Whitelist conservative character set matching
# the project's batch_id convention (alphanumerics + dash + underscore +
# period for trailing extension-less names). Anything outside this set
# (slashes, `..`, percent-encoded chars, control chars) is rejected.
_BATCH_ID_RE: re.Pattern = re.compile(r"^[A-Za-z0-9_\-]+$")


def _sanitise_free_text(s: str, max_chars: int) -> str:
    """Strip control chars (\\r, \\n, \\t, and 0x00-0x1F except space) and
    cap length. Preserves printable ASCII + non-ASCII unicode. Returns
    a trimmed string ready for audit log + structured logging without
    log-injection risk."""
    if not s:
        return ""
    # Strip control chars + ANSI escapes
    cleaned = "".join(ch for ch in s if ch == " " or (ord(ch) >= 0x20 and ord(ch) != 0x7F))
    cleaned = cleaned.strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
    return cleaned


# ── Audit log path resolution (same convention as runtime-flags) ─────────────

def _audit_path() -> Path:
    return settings.storage_root / "dhl_selfclearance_dispatch_admin_audit.jsonl"


def _ensure_audit_dir() -> None:
    _audit_path().parent.mkdir(parents=True, exist_ok=True)


def _append_audit(entry: Dict[str, Any]) -> None:
    _ensure_audit_dir()
    with _audit_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


# ── Templated error helper ───────────────────────────────────────────────────

def _error(
    *,
    status_code: int,
    detail:      str,
    error_code:  str,
    field:       Optional[str] = None,
    hint:        str = "",
    batch_id:    Optional[str] = None,
    actor:       Optional[str] = None,
    extra:       Optional[Dict[str, Any]] = None,
) -> HTTPException:
    """Tamper-evident audit-log + templated 4xx/5xx response."""
    audit_entry: Dict[str, Any] = {
        "event":      "admin_dispatch_override_rejected",
        "error_code": error_code,
        "field":      field,
        "batch_id":   batch_id,
        "actor":      actor or "",
        "timestamp":  int(time.time()),
        "status":     status_code,
    }
    if extra:
        audit_entry.update(extra)
    try:
        _append_audit(audit_entry)
    except Exception:  # pragma: no cover — best-effort
        log.warning("admin_dispatch_audit_write_failed error_code=%s", error_code)
    return HTTPException(
        status_code=status_code,
        detail={
            "detail":     detail,
            "error_code": error_code,
            "field":      field,
            "hint":       hint,
        },
    )


# ── Audit-loader for the target batch ────────────────────────────────────────

def _load_audit(batch_id: str) -> Dict[str, Any]:
    """Load audit.json for `batch_id`. Raises 404 if missing.

    Standard project convention: `storage_root/outputs/<batch_id>/audit.json`.
    """
    audit_path = settings.storage_root / "outputs" / batch_id / "audit.json"
    if not audit_path.exists():
        raise _error(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"audit.json not found for batch_id={batch_id!r}",
            error_code="AUDIT_NOT_FOUND",
            field="batch_id",
            hint="Verify the batch_id; check storage_root/outputs/.",
            batch_id=batch_id,
        )
    try:
        return json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _error(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="audit.json could not be read.",
            error_code="AUDIT_READ_FAILED",
            field="batch_id",
            hint="Inspect filesystem permissions and JSON validity.",
            batch_id=batch_id,
            extra={"exception_class": exc.__class__.__name__},
        )


def _save_audit(batch_id: str, audit: Dict[str, Any]) -> None:
    """Write audit.json back atomically (tmp + replace)."""
    audit_path = settings.storage_root / "outputs" / batch_id / "audit.json"
    tmp = audit_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(audit_path)


# ── Request shape ────────────────────────────────────────────────────────────

class ForceDispatchBody(BaseModel):
    force:  Optional[bool] = False
    reason: Optional[str]  = None
    actor:  Optional[str]  = None


# ── Route ────────────────────────────────────────────────────────────────────

@router.post(
    "/proactive-dispatch/{batch_id}",
    dependencies=[_auth],
)
def admin_proactive_dispatch(
    batch_id: str,
    body: ForceDispatchBody = Body(default_factory=ForceDispatchBody),
) -> Dict[str, Any]:
    """ADR-019 Model C admin override route for P2 proactive dispatch.

    Returns the coordinator's response dict (status / reason / message_id /
    content_sha256 / idempotent / triggered_by) on success. Raises 4xx with
    templated error on validation failure, 422 on Path B mistake, 409 on
    ADR-018 FORBIDDEN combination, 500 on coordinator/io failure.
    """
    batch_id = (batch_id or "").strip()
    if not batch_id:
        raise _error(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="batch_id path parameter is required.",
            error_code="MISSING_FIELD",
            field="batch_id",
            hint="POST to /proactive-dispatch/<batch_id>",
        )

    # Path-traversal guard: batch_id flows into a filesystem path
    # (storage_root/outputs/<batch_id>/audit.json). Reject anything
    # outside the conservative allowlist.
    if not _BATCH_ID_RE.match(batch_id):
        raise _error(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"batch_id contains characters outside the allowlist "
                f"[A-Za-z0-9_-]; rejected for filesystem-path safety."
            ),
            error_code="INVALID_BATCH_ID",
            field="batch_id",
            hint="Use only alphanumerics, dashes, and underscores.",
            batch_id=batch_id,
        )

    force  = bool(body.force)
    # Sanitise + cap operator-supplied free text. Strips control chars to
    # prevent log-injection; caps length to prevent audit-file bloat.
    reason = _sanitise_free_text(body.reason or "", _FORCE_REASON_MAX_CHARS)
    actor  = _sanitise_free_text(body.actor  or "", _FORCE_ACTOR_MAX_CHARS)

    # ── Force-path validation (ADR-019 Invariant 2) ──────────────────────────
    if force:
        if len(reason) < _FORCE_REASON_MIN_CHARS:
            raise _error(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"reason (min {_FORCE_REASON_MIN_CHARS} chars) is required "
                    f"when force=true."
                ),
                error_code="MISSING_REASON" if not reason else "REASON_TOO_SHORT",
                field="reason",
                hint=(
                    "Force-redispatch requires an operator-visible reason for "
                    "bypassing the per-batch idempotency check."
                ),
                batch_id=batch_id,
                actor=actor,
            )
        if len(actor) < _FORCE_ACTOR_MIN_CHARS:
            raise _error(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"actor (min {_FORCE_ACTOR_MIN_CHARS} chars) is required "
                    f"when force=true."
                ),
                error_code="MISSING_ACTOR" if not actor else "ACTOR_TOO_SHORT",
                field="actor",
                hint=(
                    "Force-redispatch requires identifiable operator identity."
                ),
                batch_id=batch_id,
            )

    # ── Load audit ───────────────────────────────────────────────────────────
    audit = _load_audit(batch_id)

    # AWB resolution — same fields the legacy resolver checks. Keep simple
    # here; F-IGN-4 follow-up will extract a shared helper.
    awb = (
        (audit.get("dhl_awb") or "").strip()
        or (audit.get("awb") or "").strip()
        or ((audit.get("batch_meta") or {}).get("awb") or "").strip()
        or (audit.get("tracking_no") or "").strip()
    )

    # ── State recovery for `dispatch_failed` (force=True only) ──────────────
    # gap-hunter F2: when state is `dispatch_failed` and operator hits the
    # admin route with `force=True`, recover to `awaiting_preemptive_send`
    # before the coordinator runs — otherwise coordinator dispatches but
    # `_advance_to_awaiting_poland_arrival` silently no-ops because the
    # current state is not `awaiting_preemptive_send`, leaving the state
    # stuck on `dispatch_failed` while the email IS sent.
    # Without force, the recovery does not fire — operator must explicitly
    # acknowledge the prior failure via reason+actor.
    current_state = (audit.get("dhl_clearance") or {}).get("state", "")
    if force and current_state == "dispatch_failed":
        try:
            from ..services import dhl_clearance_state_engine as state_engine
            from ..services import dhl_clearance_manifest as manifest
            manifest.init_manifest(audit)
            audit["dhl_clearance"]["state"] = state_engine.STATE_AWAITING_PREEMPTIVE_SEND
            audit["dhl_clearance"].setdefault("state_history", []).append({
                "from":   "dispatch_failed",
                "to":     state_engine.STATE_AWAITING_PREEMPTIVE_SEND,
                "reason": f"admin_force_retry by {actor}: {reason}",
                "actor":  actor,
                "at":     int(time.time()),
            })
        except Exception as exc:  # pragma: no cover — defensive
            log.error(
                "admin_dispatch_state_recovery_failed batch_id=%s reason=%s",
                batch_id, exc.__class__.__name__,
            )

    inp = DispatchInput(batch_id=batch_id, awb=awb, audit=audit)

    # ── Invoke coordinator ───────────────────────────────────────────────────
    coord = DhlClearanceCoordinator()
    try:
        result = coord.dispatch_proactive(
            inp,
            caller="admin_route",
            force=force,
            actor=actor or None,
        )
    except OutOfScopeError as exc:
        raise _error(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Shipment is not on Path A self-clearance flow.",
            error_code="OUT_OF_SCOPE",
            field="batch_id",
            hint="P2 dispatch is Path A only; Path B uses agency_clearance flow.",
            batch_id=batch_id,
            actor=actor,
            extra={"exception_class": exc.__class__.__name__},
        )
    except ForbiddenFlagCombination as exc:
        raise _error(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "ADR-018 FORBIDDEN flag combination "
                "(shadow_mode=False AND live_enabled=True). Cannot dispatch."
            ),
            error_code="FORBIDDEN_FLAG_COMBINATION",
            field=None,
            hint=(
                "Set dhl_selfclearance_p2_shadow_mode=true OR "
                "dhl_selfclearance_p2_live_enabled=false via /api/v1/admin/"
                "runtime-flags/self-clearance before retrying."
            ),
            batch_id=batch_id,
            actor=actor,
            extra={"exception_class": exc.__class__.__name__},
        )
    except (ForceRequiresActor, CallerRejectsForce) as exc:
        # Belt-and-braces: route layer validates actor + force-with-route earlier;
        # if coordinator raises one of these the route validation slipped.
        raise _error(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Coordinator rejected the force/caller combination.",
            error_code="FORCE_CONTRACT_VIOLATION",
            field="force",
            hint="Internal: route validation should have caught this earlier.",
            batch_id=batch_id,
            actor=actor,
            extra={"exception_class": exc.__class__.__name__},
        )
    except Exception as exc:
        log.error(
            "admin_dispatch_coordinator_failed batch_id=%s actor=%s reason=%s",
            batch_id, actor, exc.__class__.__name__,
        )
        raise _error(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Coordinator dispatch raised an unexpected exception.",
            error_code="COORDINATOR_FAILED",
            field=None,
            hint="Inspect service logs; retry not advised without operator review.",
            batch_id=batch_id,
            actor=actor,
            extra={"exception_class": exc.__class__.__name__},
        )

    # ── Persist audit mutations made by the coordinator ──────────────────────
    # gap-hunter F1: if `_save_audit` fails AFTER the coordinator has already
    # queued a real email (LIVE) or recorded a shadow dispatch, the in-memory
    # manifest.message_id never lands on disk. A later sweep (or admin retry)
    # would see no prior message_id and double-dispatch. Treat this as 500
    # so the operator KNOWS state diverged and investigates BEFORE retrying.
    # The admin audit JSONL still gets the rejection entry for forensic trail.
    try:
        _save_audit(batch_id, audit)
    except OSError as exc:
        log.error(
            "admin_dispatch_audit_save_failed batch_id=%s status=%s message_id=%s "
            "reason=%s — state DIVERGED, coordinator action persisted in-memory "
            "but NOT on disk; manual reconciliation required before any retry",
            batch_id, result.get("status"), result.get("message_id"),
            exc.__class__.__name__,
        )
        raise _error(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Audit save failed AFTER coordinator dispatched. State on "
                "disk does NOT reflect the dispatch. Manual reconciliation "
                "required — do NOT retry until inspected."
            ),
            error_code="AUDIT_SAVE_FAILED_POST_DISPATCH",
            field=None,
            hint=(
                "Check storage_root/outputs/<batch_id>/audit.json + "
                "email_queue.json + dhl_selfclearance_dispatch_admin_audit.jsonl "
                "for the in-flight message_id before any retry. The coordinator "
                "result is in this response's extra context."
            ),
            batch_id=batch_id,
            actor=actor,
            extra={
                "exception_class":     exc.__class__.__name__,
                "coordinator_status":  result.get("status"),
                "coordinator_message": result.get("message_id"),
                "triggered_by":        result.get("triggered_by"),
            },
        )

    # ── Audit log the override event ─────────────────────────────────────────
    audit_entry = {
        "event":              "admin_dispatch_override",
        "actor":              actor,
        "force":              force,
        "reason":             reason,
        "batch_id":           batch_id,
        "coordinator_status": result.get("status"),
        "coordinator_reason": result.get("reason"),
        "message_id":         result.get("message_id"),
        "content_sha256":     result.get("content_sha256"),
        "idempotent":         result.get("idempotent"),
        "triggered_by":       result.get("triggered_by"),
        "timestamp":          int(time.time()),
    }
    if force:
        audit_entry["log_level"] = "WARNING"
    try:
        _append_audit(audit_entry)
    except Exception:  # pragma: no cover — best-effort
        log.warning(
            "admin_dispatch_override_audit_write_failed batch_id=%s actor=%s",
            batch_id, actor,
        )
        result = {**result, "audit_write_failed": True}

    return result
