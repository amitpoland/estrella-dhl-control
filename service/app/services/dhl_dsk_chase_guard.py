"""dhl_dsk_chase_guard.py — Execution-time validation for the post-DSK-reply chase.

Parallel to dhl_followup_guard but for the NEW Phase-B5 DSK-chase pipeline. It
is deliberately a separate module so the pre-T# follow-up guard is never
overloaded or regressed. It REUSES the low-level helpers + result dataclass from
dhl_followup_guard, but:
  - gates on ``DHL_ORCH_AUTO_SEND_DSK_CHASE`` (separate emergency switch)
  - reads idempotency / sent-keys / trigger from ``audit["dhl_dsk_chase"]``
  - shares the per-shipment ``followup.mode`` authority (one shipment-level
    enrol-one switch governs both DHL chase phases)

LESSON E COMPLIANCE — implements all five background-email properties:
  1. execution-time validation (flag, mode, active, recipient, package, ingest)
  2. idempotency (deterministic per-slot key; caller dedupes via sent keys)
  3. terminal-state suppression (active check + caller stop conditions)
  4. replay safety (caller writes the idem key BEFORE send)
  5. environment isolation (email_sender._smtp_configured + ENV guard)

LESSON K COMPLIANCE — read/validate-only. No gh, Bash, sc.exe, robocopy, or any
write-capable tool. Pure function boundary; ALL persistence is owned by the
caller (active_shipment_monitor._process_dsk_chase).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Reuse the result type + low-level helpers + freshness constant (single source).
from .dhl_followup_guard import (
    FollowupGuardResult,
    INGEST_FRESHNESS_MAX_MIN,
    _parse_iso,
    _age_minutes,
)

STATE_KEY = "dhl_dsk_chase"


def build_dsk_chase_idempotency_key(batch_id: str, audit: Dict[str, Any]) -> str:
    """Per-slot idempotency key: ``{batch_id}|dhl_dsk_chase|{next_followup_at}``.

    Deterministic on (batch_id, current next_followup_at). When
    record_dsk_chase_sent advances next_followup_at, the next key differs.
    """
    state   = audit.get(STATE_KEY) or {}
    next_at = str(state.get("next_followup_at") or "").strip()
    bid     = str(batch_id or audit.get("batch_id") or "").strip()
    if not bid or not next_at:
        return ""
    return f"{bid}|dhl_dsk_chase|{next_at}"


def validate_dsk_chase_send_preconditions(
    audit:           Dict[str, Any],
    pkg:             Dict[str, Any],
    *,
    now:             Optional[datetime] = None,
    allowed_to:      Optional[List[str]] = None,
    flag_override:   Optional[bool] = None,
    require_fresh_ingest: bool = True,
) -> FollowupGuardResult:
    """Pre-send validation gate for the DSK chase. Never raises; pure function.

    On ok=False the caller MUST NOT send.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # ── 1. Flag gate (separate from the pre-T# follow-up flag) ───────────────
    if flag_override is None:
        try:
            from ..core.config import settings
            flag_on = bool(getattr(settings, "dhl_orch_auto_send_dsk_chase", False))
        except Exception:
            flag_on = False
    else:
        flag_on = bool(flag_override)
    if not flag_on:
        return FollowupGuardResult(ok=False, reason="auto_send_dsk_chase_flag_off")

    # ── 1.5. Shipment-level mode authority (shared with follow-up) ───────────
    try:
        from .dhl_followup_mode import get_mode
        mode = get_mode(audit)
    except Exception as exc:
        return FollowupGuardResult(ok=False, reason=f"mode_check_error:{exc!s}"[:120])
    if mode != "automatic":
        return FollowupGuardResult(ok=False, reason="manual_mode")

    # ── 2. Active shipment ───────────────────────────────────────────────────
    try:
        from .dhl_orchestrator import is_active_shipment
        active, why = is_active_shipment(audit)
    except Exception as exc:
        return FollowupGuardResult(ok=False, reason=f"active_check_error:{exc!s}"[:120])
    if not active:
        return FollowupGuardResult(ok=False, reason=f"not_active:{why}")

    # ── 3. AWB + batch_id non-empty ──────────────────────────────────────────
    awb = str(audit.get("awb") or audit.get("tracking_no") or "").strip()
    if not awb:
        return FollowupGuardResult(ok=False, reason="missing_awb")
    batch_id = str(audit.get("batch_id") or "").strip()
    if not batch_id:
        return FollowupGuardResult(ok=False, reason="missing_batch_id")

    # ── 4. Recipient validation — primary TO must be in canonical DHL_TO ─────
    if allowed_to is None:
        try:
            from ..config.email_routing import DHL_TO as _DEFAULT_DHL_TO
            allowed_to = list(_DEFAULT_DHL_TO)
        except Exception:
            allowed_to = []
    allowed_set = {a.strip().lower() for a in (allowed_to or []) if a}
    if not allowed_set:
        return FollowupGuardResult(ok=False, reason="recipient_allowlist_empty")

    to_list_raw = pkg.get("to_list")
    if not to_list_raw:
        to_str = str(pkg.get("to") or "")
        to_list_raw = [s.strip() for s in to_str.split(",") if s.strip()]
    if not to_list_raw:
        return FollowupGuardResult(ok=False, reason="empty_recipient_list")
    primary = str(to_list_raw[0]).strip().lower()
    if not primary:
        return FollowupGuardResult(ok=False, reason="empty_primary_recipient")
    if primary not in allowed_set:
        return FollowupGuardResult(ok=False, reason=f"unsafe_recipient:{primary}"[:120])

    # ── 5. Package validation ────────────────────────────────────────────────
    if not str(pkg.get("subject") or "").strip():
        return FollowupGuardResult(ok=False, reason="empty_subject")
    if not (str(pkg.get("body_text") or "").strip() or str(pkg.get("body_html") or "").strip()):
        return FollowupGuardResult(ok=False, reason="empty_body")
    if awb not in str(pkg.get("subject") or ""):
        return FollowupGuardResult(ok=False, reason="awb_missing_from_subject")

    attachments = pkg.get("attachments") or []
    if not isinstance(attachments, list):
        return FollowupGuardResult(ok=False, reason="attachments_malformed")
    for att in attachments:
        if not isinstance(att, dict):
            return FollowupGuardResult(ok=False, reason="attachment_entry_malformed")
        ap = (att.get("path") or "").strip()
        if not ap:
            return FollowupGuardResult(ok=False, reason="attachment_path_empty")
        if not Path(ap).is_file():
            return FollowupGuardResult(ok=False, reason=f"attachment_missing:{Path(ap).name}"[:120])

    # ── 6. Fresh ingest evidence (stale "no docs yet" decision is unsafe) ────
    ingest_age: Optional[int] = None
    if require_fresh_ingest:
        ei = audit.get("email_ingestion") or {}
        last_scan_dt = _parse_iso(ei.get("last_scan_at"))
        ingest_age = _age_minutes(last_scan_dt, now)
        if last_scan_dt is None:
            return FollowupGuardResult(ok=False, reason="ingest_never_run")
        if ingest_age is not None and ingest_age > INGEST_FRESHNESS_MAX_MIN:
            return FollowupGuardResult(
                ok=False,
                reason=f"stale_ingest:{ingest_age}m_over_{INGEST_FRESHNESS_MAX_MIN}m",
                ingest_age_min=ingest_age,
            )

    # ── 7. Idempotency duplicate check (dhl_dsk_chase slot) ──────────────────
    idem_key = build_dsk_chase_idempotency_key(batch_id, audit)
    if not idem_key:
        return FollowupGuardResult(ok=False, reason="cannot_build_idempotency_key",
                                   ingest_age_min=ingest_age)
    state = audit.get(STATE_KEY) or {}
    sent_keys = state.get("sent_idempotency_keys") or []
    if not isinstance(sent_keys, list):
        sent_keys = []
    if idem_key in sent_keys:
        return FollowupGuardResult(ok=False, reason="duplicate_idempotency_key",
                                   idempotency_key=idem_key, ingest_age_min=ingest_age)

    # ── 8. SLA age + recipient counts for telemetry ──────────────────────────
    sla_age: Optional[int] = None
    trig_dt = _parse_iso(state.get("trigger_time"))
    if trig_dt:
        sla_age = _age_minutes(trig_dt, now)

    cc_raw = pkg.get("cc_list") or []
    if not cc_raw:
        cc_str = str(pkg.get("cc") or "")
        cc_raw = [s.strip() for s in cc_str.split(",") if s.strip()]

    return FollowupGuardResult(
        ok=True,
        reason="ok",
        idempotency_key=idem_key,
        primary_to=primary,
        cc_count=len(cc_raw),
        attach_count=len(attachments),
        sla_age_min=sla_age,
        ingest_age_min=ingest_age,
    )


def record_idempotency_key_into_audit(
    audit: Dict[str, Any],
    key:   str,
    cap:   int = 100,
) -> None:
    """Append the idem key to ``audit[dhl_dsk_chase].sent_idempotency_keys``.

    Bounded (most-recent ``cap`` retained). Mutates audit in place; caller
    persists. MUST be called + persisted BEFORE send_queued_email (replay
    safety, Lesson E §4).
    """
    if not key:
        return
    state = audit.setdefault(STATE_KEY, {})
    keys = state.get("sent_idempotency_keys")
    if not isinstance(keys, list):
        keys = []
    if key not in keys:
        keys.append(key)
    if len(keys) > cap:
        keys = keys[-cap:]
    state["sent_idempotency_keys"] = keys
    audit[STATE_KEY] = state
