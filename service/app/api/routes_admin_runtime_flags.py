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
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterator, Optional, Tuple

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

    ADR-018 §a — startup-time enforcement
    =====================================
    After the per-flag replay, this function walks every P2/P3/P4/P5 phase
    pair and checks the resulting (shadow_mode, live_enabled) combined
    state. If a phase ended up in the FORBIDDEN combination
    (shadow_mode=False, live_enabled=True) — whether due to a hand-edited
    JSON store, a pre-validator-era persisted file, or a future race
    condition that bypassed the runtime gate — the function:
      1. logs CRITICAL
      2. forces the affected phase to a safe DORMANT state
         (shadow_mode=False, live_enabled=False)
      3. records a `runtime_flags_startup_forbidden_combo_repaired` audit entry
    The phase remains DORMANT until an operator restores it via the admin
    endpoint, which itself enforces ADR-018 Invariant 1.

    This closes the boot-replay auth-bypass surface for the combined-state
    rule (gap-hunter F1 / security AUTH-BYPASS finding on the original PR).
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

    # ── ADR-018 §a startup enforcement (post-replay sweep) ───────────────
    repaired = _enforce_startup_combined_states()
    if repaired:
        log.critical(
            "runtime_flags_startup_forbidden_combo_repaired phases=%s",
            sorted(repaired.keys()),
        )
    return applied


def _enforce_startup_combined_states() -> Dict[str, Dict[str, bool]]:
    """ADR-018 §a — walk P2/P3/P4/P5 after boot-replay; if any phase landed
    in the FORBIDDEN combined state, force it to DORMANT and audit the
    repair. Returns {phase: {prior_shadow, prior_live}} for repaired phases.

    Reuses `_enforce_flag_combination` (single source of truth) — does not
    re-implement the (False, True) check.
    """
    repaired: Dict[str, Dict[str, bool]] = {}
    for phase in ("p2", "p3", "p4", "p5"):
        shadow_attr = f"dhl_selfclearance_{phase}_shadow_mode"
        live_attr   = f"dhl_selfclearance_{phase}_live_enabled"
        prior_shadow = bool(getattr(settings, shadow_attr, False))
        prior_live   = bool(getattr(settings, live_attr,   False))
        try:
            _enforce_flag_combination(
                phase,
                shadow_mode=prior_shadow,
                live_enabled=prior_live,
            )
        except ForbiddenFlagCombination:
            # Force DORMANT (safe default per ADR-018 §a).
            try:
                setattr(settings, shadow_attr, False)
                setattr(settings, live_attr,   False)
            except Exception:  # pragma: no cover — defensive
                log.error(
                    "startup_forbidden_combo_repair_setattr_failed phase=%s",
                    phase,
                )
                continue
            try:
                _append_audit({
                    "event":          "runtime_flags_startup_forbidden_combo_repaired",
                    "phase":          phase,
                    "prior_shadow":   prior_shadow,
                    "prior_live":     prior_live,
                    "forced_shadow":  False,
                    "forced_live":    False,
                    "timestamp":      int(time.time()),
                    "reason":         "ADR-018 Invariant 1 violation detected at startup",
                })
            except Exception:  # pragma: no cover — best-effort
                log.warning("startup_forbidden_combo_audit_write_failed phase=%s", phase)
            repaired[phase] = {"prior_shadow": prior_shadow, "prior_live": prior_live}
    return repaired


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
    extra_audit_context: Optional[Dict[str, Any]] = None,
) -> HTTPException:
    # Tamper-evidence: record validation rejections in the audit trail so
    # repeated probing on the admin surface is observable. Audit-log write
    # failure is swallowed to log.warning — never blocks the 4xx response.
    #
    # `extra_audit_context` carries error-specific forensic detail (e.g.
    # FORBIDDEN_FLAG_COMBINATION attaches phase + attempted/current/resulting
    # shadow+live values). Append-only JSONL is backwards-compatible with
    # extra fields; readers ignore unknown keys.
    audit_entry: Dict[str, Any] = {
        "event":      "admin_runtime_flag_rejected",
        "error_code": error_code,
        "field":      field,
        "flag_name":  flag_name,
        "actor":      actor or "",
        "timestamp":  int(time.time()),
        "status":     status_code,
    }
    if extra_audit_context:
        audit_entry.update(extra_audit_context)
    try:
        _append_audit(audit_entry)
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

# IMPORTANT — phase-coverage binding rule:
# The character class [2-5] must match the phases declared in `_ALLOWED_FLAGS`
# above (currently p2, p3, p4, p5). If a future ADR-018 amendment introduces
# a new phase pair (e.g. p6_shadow_mode / p6_live_enabled), BOTH this regex
# AND `_ALLOWED_FLAGS` must be updated in the same PR — otherwise the new
# phase silently escapes the combined-state gate and FORBIDDEN combinations
# would be accepted by the admin endpoint. See gap-hunter F7 disposition.
_PHASE_PAIR_RE = re.compile(
    r"^dhl_selfclearance_(p[2-5])_(shadow_mode|live_enabled)$"
)


# ── Per-phase concurrency lock (Issue #48) ───────────────────────────────────
#
# Closes the gap-hunter F2 / security-write-action CONCURRENCY race: two
# concurrent admin POSTs against the same phase could both pass the
# combined-state gate based on stale current state, then both mutate
# settings to a FORBIDDEN combination.
#
# Design:
# - 4 locks total (one per phase pair P2/P3/P4/P5). Per-phase granularity
#   chosen over global lock so an operator flipping P2 does not block
#   another inspecting/flipping P4. Per-flag granularity rejected as
#   complexity without operational value (the FORBIDDEN-state invariant
#   is per-phase, so the lock scope must be per-phase).
# - Lock scope: covers the entire read-current → validate-resulting →
#   setattr → persist → audit-flipped atomic sequence.
# - Acquisition timeout: 5 seconds. On timeout: 503 LOCK_ACQUISITION_TIMEOUT.
# - In-memory only (NOT persisted). Service restart resets to unlocked,
#   which is correct because boot-replay validates combined state via
#   _enforce_startup_combined_states() before any traffic arrives.
# - GET endpoint does NOT acquire the lock (read-only; eventually
#   consistent is acceptable for the operator dashboard).
# - Boot-replay is single-threaded and runs before the route is mounted,
#   so it never contends for the lock.
# - threading.Lock chosen over asyncio.Lock because FastAPI runs sync
#   def handlers in a starlette threadpool. The current POST handler is
#   sync def; switching to async would require broader refactor.

LOCK_ACQUISITION_TIMEOUT_SECONDS: float = 5.0

_PHASE_LOCKS: Dict[str, threading.Lock] = {
    "p2": threading.Lock(),
    "p3": threading.Lock(),
    "p4": threading.Lock(),
    "p5": threading.Lock(),
}


@contextmanager
def _acquire_phase_lock(
    phase: Optional[str],
    *,
    flag_name: str,
    actor: str,
) -> Iterator[None]:
    """Context manager that acquires the per-phase lock for the
    read-validate-write atomic sequence. For non-phase flags (`phase is
    None`), is a no-op — those flags do not participate in ADR-018's
    combined-state invariant.

    On acquisition timeout: appends `admin_runtime_flag_lock_timeout`
    audit entry and raises HTTPException(503) with templated error.

    Always releases lock on exit (success OR exception) — `finally`
    block ensures cleanup even if validation raises FORBIDDEN_FLAG_COMBINATION
    or any downstream exception.
    """
    if phase is None or phase not in _PHASE_LOCKS:
        yield
        return

    lock = _PHASE_LOCKS[phase]
    acquired_at = time.time()
    acquired = lock.acquire(timeout=LOCK_ACQUISITION_TIMEOUT_SECONDS)

    if not acquired:
        # Tamper-evidence + operator-forensics: record the timeout so
        # repeated lock contention on a single phase is observable.
        try:
            _append_audit({
                "event":           "admin_runtime_flag_lock_timeout",
                "phase":           phase,
                "flag_name":       flag_name,
                "actor":           actor or "",
                "timestamp":       int(time.time()),
                "timeout_seconds": LOCK_ACQUISITION_TIMEOUT_SECONDS,
            })
        except Exception:  # pragma: no cover — best-effort
            log.warning("lock_timeout_audit_write_failed phase=%s", phase)
        raise _error(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Could not acquire phase lock for {phase!r} within "
                f"{LOCK_ACQUISITION_TIMEOUT_SECONDS}s."
            ),
            error_code="LOCK_ACQUISITION_TIMEOUT",
            field="flag_name",
            hint=(
                "Another operator is updating this phase; retry in a moment."
            ),
            flag_name=flag_name,
            actor=actor,
            extra_audit_context={
                "phase":           phase,
                "timeout_seconds": LOCK_ACQUISITION_TIMEOUT_SECONDS,
            },
        )

    # Acquisition succeeded — record for forensic completeness.
    try:
        _append_audit({
            "event":      "admin_runtime_flag_lock_acquired",
            "phase":      phase,
            "flag_name":  flag_name,
            "actor":      actor or "",
            "timestamp":  int(acquired_at),
        })
    except Exception:  # pragma: no cover
        log.warning("lock_acquired_audit_write_failed phase=%s", phase)

    try:
        yield
    finally:
        lock.release()
        try:
            _append_audit({
                "event":            "admin_runtime_flag_lock_released",
                "phase":            phase,
                "flag_name":        flag_name,
                "actor":            actor or "",
                "timestamp":        int(time.time()),
                "held_seconds":     round(time.time() - acquired_at, 3),
            })
        except Exception:  # pragma: no cover
            log.warning("lock_released_audit_write_failed phase=%s", phase)


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

    # Defensive: the call order in post_self_clearance_flag is
    # _coerce_and_validate (enforces isinstance(value, bool) for bool flags)
    # → _enforce_resulting_combined_state. Guard against a future refactor
    # that reorders these and lets a non-bool slip through (gap-hunter F10).
    if not isinstance(new_value, bool):
        return  # caller's type-validator should have rejected; fail-closed by skipping

    phase, dimension = parsed
    shadow_attr = f"dhl_selfclearance_{phase}_shadow_mode"
    live_attr   = f"dhl_selfclearance_{phase}_live_enabled"

    current_shadow = bool(getattr(settings, shadow_attr, False))
    current_live   = bool(getattr(settings, live_attr,   False))

    if dimension == "shadow_mode":
        resulting_shadow = new_value
        resulting_live   = current_live
    else:  # live_enabled
        resulting_shadow = current_shadow
        resulting_live   = new_value

    try:
        # Keyword arguments at call site — protects against silent
        # parameter-reorder breakage in future coordinator-helper changes
        # (integration-boundary forward-compat note).
        _enforce_flag_combination(
            phase,
            shadow_mode=resulting_shadow,
            live_enabled=resulting_live,
        )
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
            # Forensic context — captures full attempted state transition
            # so an operator tracing probing patterns has enough to act
            # (gap-hunter F5 / security AUDIT-TRACE-COMPLETENESS finding).
            extra_audit_context={
                "phase":            phase,
                "dimension":        dimension,
                "attempted_value":  new_value,
                "current_shadow":   current_shadow,
                "current_live":     current_live,
                "resulting_shadow": resulting_shadow,
                "resulting_live":   resulting_live,
            },
        )


# ── Request shape ────────────────────────────────────────────────────────────

class FlagFlipBody(BaseModel):
    flag_name: str
    value:     Any
    actor:     str
    reason:    Optional[str] = None


# ── Routes ───────────────────────────────────────────────────────────────────

def _classify_phase_state(shadow_mode: bool, live_enabled: bool) -> str:
    """Map a (shadow_mode, live_enabled) pair to its ADR-018 truth-table
    label: DORMANT / SHADOW / LIVE / FORBIDDEN. Used by GET endpoint for
    operator readability under kill-switch time pressure (gap-hunter F3)."""
    if not shadow_mode and not live_enabled:
        return "DORMANT"
    if shadow_mode and not live_enabled:
        return "SHADOW"
    if shadow_mode and live_enabled:
        return "LIVE"
    return "FORBIDDEN"  # (False, True) — should never persist; surfaces drift


@router.get("/self-clearance", dependencies=[_auth])
def get_self_clearance_flags() -> Dict[str, Any]:
    """
    Return the current live values of all self-clearance flags. Reflects
    in-memory `settings` (the source of truth after any restartless flip).

    Includes a derived `phases` block per ADR-018 truth table — each
    phase pair (P2/P3/P4/P5) is classified DORMANT/SHADOW/LIVE/FORBIDDEN.
    Operators get a readable label without having to mentally evaluate
    the (shadow, live) tuple under time pressure.
    """
    # Flat flag map at top level (backwards-compatible with existing readers).
    payload: Dict[str, Any] = {
        name: getattr(settings, name, None) for name in sorted(ALLOWED_FLAG_NAMES)
    }
    # Adjunct phase-state classification — keyed `_phases` (leading underscore
    # so it cannot collide with any current or future flag name in
    # `_ALLOWED_FLAGS`, which are all `dhl_selfclearance_*`).
    phases: Dict[str, Dict[str, Any]] = {}
    for phase in ("p2", "p3", "p4", "p5"):
        shadow = bool(getattr(settings, f"dhl_selfclearance_{phase}_shadow_mode", False))
        live   = bool(getattr(settings, f"dhl_selfclearance_{phase}_live_enabled", False))
        phases[phase] = {
            "shadow_mode":  shadow,
            "live_enabled": live,
            "state":        _classify_phase_state(shadow, live),
        }
    payload["_phases"] = phases
    return payload


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

    # Determine which (if any) phase pair this flag belongs to. Used to
    # decide whether the per-phase concurrency lock applies (Issue #48).
    parsed_pair = _parse_phase_pair(flag_name)
    phase_for_lock: Optional[str] = parsed_pair[0] if parsed_pair else None

    # Per-phase atomic block (Issue #48). Lock scope covers the entire
    # read-validate-write sequence: combined-state check reads current
    # settings; setattr mutates them; store + audit persist them.
    # Without the lock, two concurrent POSTs against the same phase
    # could both pass the gate based on stale state and produce a
    # FORBIDDEN combination. For non-phase flags, the context manager
    # is a no-op.
    with _acquire_phase_lock(
        phase_for_lock,
        flag_name=flag_name,
        actor=actor,
    ):
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
