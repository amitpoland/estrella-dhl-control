"""
routes_admin_runtime_flags.py — Admin endpoint for restartless DHL
self-clearance flag flips (W-5 / P0).

Endpoints
=========
    POST /api/v1/admin/runtime-flags/self-clearance
        body: {"flag_name": <str>, "value": <bool|int|float|str>, "actor": <str>,
               "reason": <optional str>}
        Flips the named flag in-memory + persists to a runtime-flag JSON store.
        Audit-logged. NEVER raw exception strings — every error path is
        templated per engineering_discipline_rules memory.

    GET  /api/v1/admin/runtime-flags/self-clearance
        Returns the full current flag map (live values).

Auth
====
X-API-Key via require_api_key (PR #23 hybrid auth seam). No browser UI.

Allowed flags (P0)
==================
Exactly the canonical set locked in 01_P0_FOUNDATION.md §"Config keys to add":
    dhl_selfclearance_p2_live_enabled         (bool)
    dhl_selfclearance_p2_shadow_mode          (bool)
    dhl_selfclearance_p3_live_enabled         (bool)
    dhl_selfclearance_p3_shadow_mode          (bool)
    dhl_selfclearance_p3_tracker_paused       (bool)
    dhl_selfclearance_p4_live_enabled         (bool)
    dhl_selfclearance_p4_shadow_mode          (bool)
    dhl_selfclearance_p5_live_enabled         (bool)
    dhl_selfclearance_p5_shadow_mode          (bool)
    dhl_selfclearance_p5_pz_trigger_enabled   (bool)
    dhl_selfclearance_p4_classifier_min_confidence  (float)
    dhl_selfclearance_p5_classifier_min_confidence  (float)
    dhl_selfclearance_followup_working_interval_sec  (int)
    dhl_selfclearance_followup_offhours_interval_sec (int)
    dhl_selfclearance_followup_working_hours_window  (str)
    dhl_selfclearance_followup_livelock_budget_hours (int)
    dhl_selfclearance_value_threshold_usd            (int)

Any other flag name → 400 templated error.

Restartless reload
==================
After a successful flip, the in-memory `settings` object is updated via
setattr() — subsequent code paths consulting `settings.<flag_name>` see the
new value within one read cycle without restart. The flag store JSON is
persisted under storage_root for crash-safe replay.

Error templating (engineering_discipline_rules memory)
======================================================
Every error response uses this shape:
    {
        "detail":     "<one-line human message>",
        "error_code": "<machine-readable code>",
        "field":      "<offending body field>" | null,
        "hint":       "<remediation hint>"
    }
Raw exception strings NEVER leak — exceptions are caught and templated.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, FrozenSet, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel

from ..core.config import settings
from ..core.security import require_api_key
from ..services.dhl_clearance_coordinator import (
    ForbiddenFlagCombination,
    _enforce_flag_combination,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/runtime-flags", tags=["admin"])

# Reused auth seam (one-liner — applied to every route below).
_auth = Depends(require_api_key)


# ── Allowed flag map (frozen at P0) ──────────────────────────────────────────
# value: expected python type for validation. tuple of types allowed.

_ALLOWED_FLAGS: Dict[str, tuple] = {
    "dhl_selfclearance_p2_live_enabled":        (bool,),
    "dhl_selfclearance_p2_shadow_mode":         (bool,),
    "dhl_selfclearance_p3_live_enabled":        (bool,),
    "dhl_selfclearance_p3_shadow_mode":         (bool,),
    "dhl_selfclearance_p3_tracker_paused":      (bool,),
    "dhl_selfclearance_p4_live_enabled":        (bool,),
    "dhl_selfclearance_p4_shadow_mode":         (bool,),
    "dhl_selfclearance_p5_live_enabled":        (bool,),
    "dhl_selfclearance_p5_shadow_mode":         (bool,),
    "dhl_selfclearance_p5_pz_trigger_enabled":  (bool,),
    "dhl_selfclearance_p4_classifier_min_confidence": (float, int),
    "dhl_selfclearance_p5_classifier_min_confidence": (float, int),
    "dhl_selfclearance_followup_working_interval_sec":  (int,),
    "dhl_selfclearance_followup_offhours_interval_sec": (int,),
    "dhl_selfclearance_followup_working_hours_window":  (str,),
    "dhl_selfclearance_followup_livelock_budget_hours": (int,),
    "dhl_selfclearance_value_threshold_usd":            (int,),
}

ALLOWED_FLAG_NAMES: FrozenSet[str] = frozenset(_ALLOWED_FLAGS.keys())


# ── Persistence: runtime-flag store JSON ─────────────────────────────────────

def _store_path() -> Path:
    return settings.storage_root / "dhl_selfclearance_runtime_flags.json"


def _audit_path() -> Path:
    return settings.storage_root / "dhl_selfclearance_runtime_flags_audit.jsonl"


def _ensure_store_dir() -> None:
    _store_path().parent.mkdir(parents=True, exist_ok=True)


def _load_store() -> Dict[str, Any]:
    p = _store_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def load_persisted_flags_into_settings() -> Dict[str, Any]:
    """
    Boot-time replay of the persisted runtime-flag JSON store onto in-memory
    `settings`. Called from main.py's lifespan startup so that NSSM restarts
    do not silently revert operator-set flags to env defaults.

    Returns a dict of {flag_name: applied_value} for every entry that
    survived validation. Invalid / unknown entries are skipped (logged).

    Safe to call multiple times — `settings.<name> = value` is idempotent.
    """
    applied: Dict[str, Any] = {}
    store = _load_store()
    if not store:
        return applied
    for name, value in store.items():
        if name not in _ALLOWED_FLAGS:
            log.warning("runtime_flag_store_unknown_flag flag=%s (skipped)", name)
            continue
        try:
            coerced = _coerce_value_no_http(name, value)
        except ValueError as exc:
            log.warning(
                "runtime_flag_store_invalid_value flag=%s reason=%s",
                name, str(exc),
            )
            continue
        try:
            setattr(settings, name, coerced)
            applied[name] = coerced
        except Exception:  # pragma: no cover — defensive
            log.warning("runtime_flag_store_setattr_failed flag=%s", name)
    if applied:
        log.info("runtime_flags_restored_from_store count=%d", len(applied))
    return applied


def _coerce_value_no_http(flag_name: str, value: Any) -> Any:
    """Same validation rules as _coerce_and_validate but raises ValueError
    instead of HTTPException — used by startup replay."""
    if flag_name not in _ALLOWED_FLAGS:
        raise ValueError(f"unknown flag {flag_name!r}")
    expected = _ALLOWED_FLAGS[flag_name]
    if bool in expected:
        if isinstance(value, bool):
            return value
        raise ValueError("expected bool")
    if int in expected and not (float in expected):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("expected int")
        return int(value)
    if float in expected:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("expected number")
        return float(value)
    if str in expected:
        if not isinstance(value, str):
            raise ValueError("expected str")
        return value
    raise ValueError("no validator for flag")


def _save_store(flag_map: Dict[str, Any]) -> None:
    _ensure_store_dir()
    tmp = _store_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(flag_map, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(_store_path())


def _append_audit(entry: Dict[str, Any]) -> None:
    _ensure_store_dir()
    line = json.dumps(entry, sort_keys=True)
    with _audit_path().open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


# ── Error templating ─────────────────────────────────────────────────────────

def _error(
    *,
    status_code: int,
    detail:      str,
    error_code:  str,
    field:       Optional[str] = None,
    hint:        str = "",
    flag_name:   Optional[str] = None,
    actor:       Optional[str] = None,
) -> HTTPException:
    # Tamper-evidence: record validation rejections in the audit trail so
    # repeated probing on the admin surface is observable. Audit-log write
    # failure is swallowed to log.warning — never blocks the 4xx response.
    try:
        _append_audit({
            "event":      "admin_runtime_flag_rejected",
            "error_code": error_code,
            "field":      field,
            "flag_name":  flag_name,
            "actor":      actor or "",
            "timestamp":  int(time.time()),
            "status":     status_code,
        })
    except Exception:  # pragma: no cover — best-effort tamper-evidence
        log.warning("rejected_audit_write_failed error_code=%s", error_code)
    return HTTPException(
        status_code=status_code,
        detail={
            "detail":     detail,
            "error_code": error_code,
            "field":      field,
            "hint":       hint,
        },
    )


# ── Validation ───────────────────────────────────────────────────────────────

def _coerce_and_validate(flag_name: str, value: Any) -> Any:
    """
    Validate that *value* matches the allowed type for *flag_name*. Returns
    the coerced value. Raises HTTPException(400) on failure.
    """
    if flag_name not in _ALLOWED_FLAGS:
        raise _error(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Flag {flag_name!r} is not in the allowed set.",
            error_code="UNKNOWN_FLAG",
            field="flag_name",
            hint=f"Allowed flags: {sorted(ALLOWED_FLAG_NAMES)}",
        )
    expected = _ALLOWED_FLAGS[flag_name]

    # bool must be checked before int (Python: True isinstance int → True)
    if bool in expected:
        if isinstance(value, bool):
            return value
        raise _error(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Flag {flag_name!r} expects a boolean.",
            error_code="WRONG_TYPE",
            field="value",
            hint="Send true or false (JSON boolean).",
        )

    if int in expected and not (float in expected):
        if isinstance(value, bool):
            raise _error(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Flag {flag_name!r} expects an integer, not boolean.",
                error_code="WRONG_TYPE",
                field="value",
                hint="Send an integer.",
            )
        if isinstance(value, int):
            return int(value)
        raise _error(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Flag {flag_name!r} expects an integer.",
            error_code="WRONG_TYPE",
            field="value",
            hint="Send an integer.",
        )

    if float in expected:
        if isinstance(value, bool):
            raise _error(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Flag {flag_name!r} expects a number, not boolean.",
                error_code="WRONG_TYPE",
                field="value",
                hint="Send a numeric value (integer or float).",
            )
        if isinstance(value, (int, float)):
            return float(value)
        raise _error(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Flag {flag_name!r} expects a number.",
            error_code="WRONG_TYPE",
            field="value",
            hint="Send a numeric value (integer or float).",
        )

    if str in expected:
        if isinstance(value, str):
            return value
        raise _error(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Flag {flag_name!r} expects a string.",
            error_code="WRONG_TYPE",
            field="value",
            hint="Send a string.",
        )

    # Unreachable in practice
    raise _error(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Flag {flag_name!r} has no validator.",
        error_code="VALIDATOR_MISSING",
        field="flag_name",
        hint="Internal mapping bug — report to engineering.",
    )


# ── ADR-018 combined-state validator (resulting state, not POST diff alone) ──
#
# ADR-018 §"Runtime enforcement recommendations" b: the admin runtime-flags
# endpoint POST handler validates the RESULTING state across both dimensions
# (shadow_mode, live_enabled) for the affected phase, computed from
# (current_settings ∪ POST_diff). Single-field validation alone is insufficient.
#
# Coverage: ALL DHL self-clearance phase pairs — P2, P3, P4, P5. Not just P2
# merely because P2 is the only currently wired coordinator path.
#
# Single source of truth: this module imports `_enforce_flag_combination` from
# `dhl_clearance_coordinator` and reuses it. Truth-table logic is NOT
# re-implemented here. Any future ADR-018 amendment to the (False, True)
# rejection rule lands in one place — the coordinator helper — and propagates
# automatically to this admin route.

_PHASE_PAIR_RE = re.compile(
    r"^dhl_selfclearance_(p[2-5])_(shadow_mode|live_enabled)$"
)


def _parse_phase_pair(flag_name: str) -> Optional[Tuple[str, str]]:
    """If `flag_name` belongs to a phase-pair flag (shadow_mode or live_enabled
    for any of p2/p3/p4/p5), return (phase, dimension). Else None."""
    m = _PHASE_PAIR_RE.match(flag_name)
    if not m:
        return None
    return m.group(1), m.group(2)


def _enforce_resulting_combined_state(
    *,
    flag_name: str,
    new_value: Any,
    actor: Optional[str],
) -> None:
    """Validate the RESULTING (shadow_mode, live_enabled) state for the
    affected phase, computed as (current_settings ∪ POST_diff).

    Reuses `_enforce_flag_combination` from the coordinator — single source
    of truth for ADR-018 Invariant 1.

    No-ops for non-phase-pair flags (e.g. tracker_paused, classifier_min_*).
    Raises HTTPException(400) with templated error on FORBIDDEN combination.
    """
    parsed = _parse_phase_pair(flag_name)
    if parsed is None:
        return  # not a phase-pair flag — combined-state rule does not apply

    phase, dimension = parsed
    shadow_attr = f"dhl_selfclearance_{phase}_shadow_mode"
    live_attr   = f"dhl_selfclearance_{phase}_live_enabled"

    current_shadow = bool(getattr(settings, shadow_attr, False))
    current_live   = bool(getattr(settings, live_attr,   False))

    if dimension == "shadow_mode":
        resulting_shadow = bool(new_value)
        resulting_live   = current_live
    else:  # live_enabled
        resulting_shadow = current_shadow
        resulting_live   = bool(new_value)

    try:
        _enforce_flag_combination(phase, resulting_shadow, resulting_live)
    except ForbiddenFlagCombination:
        # Never leak the raw exception message — template it. Per Lesson A
        # backend-safety follow-up: use exception class context, not str(exc).
        raise _error(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Resulting state for phase {phase!r} would be FORBIDDEN: "
                f"shadow_mode={resulting_shadow}, live_enabled={resulting_live}."
            ),
            error_code="FORBIDDEN_FLAG_COMBINATION",
            field="value",
            hint=(
                f"ADR-018 Invariant 1: live_enabled=True requires "
                f"shadow_mode=True. Current state for {phase}: "
                f"shadow_mode={current_shadow}, live_enabled={current_live}. "
                f"Set {shadow_attr}=true before enabling live."
            ),
            flag_name=flag_name,
            actor=actor,
        )


# ── Request shape ────────────────────────────────────────────────────────────

class FlagFlipBody(BaseModel):
    flag_name: str
    value:     Any
    actor:     str
    reason:    Optional[str] = None


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/self-clearance", dependencies=[_auth])
def get_self_clearance_flags() -> Dict[str, Any]:
    """
    Return the current live values of all self-clearance flags. Reflects
    in-memory `settings` (the source of truth after any restartless flip).
    """
    return {name: getattr(settings, name, None) for name in sorted(ALLOWED_FLAG_NAMES)}


@router.post("/self-clearance", dependencies=[_auth])
def post_self_clearance_flag(body: FlagFlipBody = Body(...)) -> Dict[str, Any]:
    """
    Flip a single self-clearance flag. Audit-logged. Restartless.
    """
    flag_name = (body.flag_name or "").strip()
    actor     = (body.actor or "").strip()

    if not flag_name:
        raise _error(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="flag_name is required.",
            error_code="MISSING_FIELD",
            field="flag_name",
            hint="Send flag_name in the request body.",
        )
    if not actor:
        raise _error(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="actor is required for audit.",
            error_code="MISSING_FIELD",
            field="actor",
            hint='Send actor in the request body (e.g. "amit", "tejal").',
        )

    new_value = _coerce_and_validate(flag_name, body.value)

    # ADR-018 combined-state gate — validate RESULTING (shadow_mode,
    # live_enabled) state across both dimensions for any P2/P3/P4/P5 phase
    # pair flag, computed from (current_settings ∪ POST_diff). Single-field
    # validation alone is insufficient. No-op for non-phase-pair flags.
    _enforce_resulting_combined_state(
        flag_name=flag_name,
        new_value=new_value,
        actor=actor,
    )

    old_value = getattr(settings, flag_name, None)

    # In-memory restartless reload — every consumer of settings sees the
    # new value within one read cycle.
    try:
        setattr(settings, flag_name, new_value)
    except Exception:
        # NEVER leak the raw exception — template it.
        raise _error(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="In-memory settings refresh failed.",
            error_code="SETTINGS_REFRESH_FAILED",
            field="flag_name",
            hint="Retry; if persistent, contact engineering.",
        )

    # Persist to flag store and audit log (both crash-safe).
    try:
        store = _load_store()
        store[flag_name] = new_value
        _save_store(store)
    except OSError:
        # Rollback in-memory change to keep persisted state consistent.
        try:
            setattr(settings, flag_name, old_value)
        except Exception:
            pass
        raise _error(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Flag store write failed.",
            error_code="STORE_WRITE_FAILED",
            field="flag_name",
            hint="Check filesystem permissions on storage_root.",
        )

    ts = int(time.time())
    audit_entry = {
        "event":      "admin_runtime_flag_flipped",
        "actor":      actor,
        "flag_name":  flag_name,
        "old_value":  old_value,
        "new_value":  new_value,
        "timestamp":  ts,
        "reason":     body.reason or "",
    }
    audit_write_failed = False
    try:
        _append_audit(audit_entry)
    except OSError:
        # Surface so caller can re-emit. State already mutated + persisted;
        # rolling back here would create more drift than it would fix.
        audit_write_failed = True
        log.warning("audit_log_write_failed flag=%s actor=%s", flag_name, actor)

    return {
        "status":             "ok",
        "flag_name":          flag_name,
        "old_value":          old_value,
        "new_value":          new_value,
        "audit_at":           ts,
        "audit_write_failed": audit_write_failed,
    }
