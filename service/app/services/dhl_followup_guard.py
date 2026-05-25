"""dhl_followup_guard.py — Execution-time validation for DHL follow-up auto-send.

PR-B (operator directive 2026-05-26).  Pure validation layer.  No I/O, no
mutation.  Caller (`active_shipment_monitor._process_dhl_followup`) owns the
actual send + audit write; this module only decides whether the send is
permitted right now.

LESSON E COMPLIANCE
===================
This guard implements the five mandatory background-email properties:

1. Execution-time validation
   - flag gate (DHL_ORCH_AUTO_SEND_DHL_FOLLOWUP)
   - active-shipment check (delegates to orchestrator.is_active_shipment)
   - AWB / batch_id non-empty
   - recipient list non-empty AND primary address in canonical DHL_TO allow-list
   - package subject + body non-empty
   - attachment paths resolvable when present

2. Idempotency
   - build_followup_idempotency_key produces a deterministic key per
     scheduled SLA slot (batch_id|dhl_followup|next_followup_at)
   - caller checks audit.dhl_followup.sent_idempotency_keys before send

3. Terminal-state suppression — handled by caller via clearance_status +
   tracking.status checks; guard re-asserts via is_active_shipment.

4. Replay safety — caller MUST append idem key to audit and write atomically
   BEFORE calling send_queued_email so a crash between SMTP success and the
   write does not cause a duplicate on replay.

5. Environment isolation — enforced by email_sender._smtp_configured +
   settings.environment guard.

LESSON K COMPLIANCE
===================
This module is read/validate-only.  It does not call gh, Bash, sc.exe, or
any write-capable tool.  Pure function boundary; ALL persistence is owned
by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Maximum acceptable age of the per-batch ingest cycle timestamp before
# the system considers its "no DHL email yet" decision stale.  Set to
# 2× the ingest cooldown so a single missed cycle still leaves headroom.
INGEST_FRESHNESS_MAX_MIN = 180  # 3 hours


@dataclass
class FollowupGuardResult:
    ok:              bool
    reason:          str
    idempotency_key: str = ""
    primary_to:      str = ""
    cc_count:        int = 0
    attach_count:    int = 0
    sla_age_min:     Optional[int] = None
    ingest_age_min:  Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok":              self.ok,
            "reason":          self.reason,
            "idempotency_key": self.idempotency_key,
            "primary_to":      self.primary_to,
            "cc_count":        self.cc_count,
            "attach_count":    self.attach_count,
            "sla_age_min":     self.sla_age_min,
            "ingest_age_min":  self.ingest_age_min,
        }


def build_followup_idempotency_key(batch_id: str, audit: Dict[str, Any]) -> str:
    """Build the per-SLA-slot idempotency key.

    Deterministic on (batch_id, current next_followup_at).  When
    record_followup_sent advances next_followup_at, the next key naturally
    differs.  When two ticks land in the same SLA slot, both produce the
    same key — caller must dedupe via audit.dhl_followup.sent_idempotency_keys.
    """
    state   = audit.get("dhl_followup") or {}
    next_at = str(state.get("next_followup_at") or "").strip()
    bid     = str(batch_id or audit.get("batch_id") or "").strip()
    if not bid or not next_at:
        return ""
    return f"{bid}|dhl_followup|{next_at}"


def _parse_iso(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _age_minutes(ts: Optional[datetime], now: datetime) -> Optional[int]:
    if ts is None:
        return None
    try:
        return int((now - ts).total_seconds() / 60.0)
    except Exception:
        return None


def validate_followup_send_preconditions(
    audit:           Dict[str, Any],
    pkg:             Dict[str, Any],
    *,
    now:             Optional[datetime] = None,
    allowed_to:      Optional[List[str]] = None,
    flag_override:   Optional[bool] = None,
    require_fresh_ingest: bool = True,
) -> FollowupGuardResult:
    """Pre-send validation gate.

    Returns FollowupGuardResult.  On ok=False, caller MUST NOT send.
    Never raises.  Pure function — no I/O.

    Parameters
    ----------
    audit, pkg
        The shipment audit dict and the package emitted by
        ``dhl_followup_email_builder.build_dhl_followup_email``.
    now
        Override clock for tests.  Defaults to ``datetime.now(timezone.utc)``.
    allowed_to
        Override allow-list of primary TO addresses.  Defaults to the
        canonical ``email_routing.DHL_TO`` constant.
    flag_override
        Override the auto-send flag for tests.  Defaults to
        ``settings.dhl_orch_auto_send_dhl_followup``.
    require_fresh_ingest
        When True (default), reject sends whose per-batch
        ``email_ingestion.last_scan_at`` is missing or older than
        ``INGEST_FRESHNESS_MAX_MIN``.  Tests may set False to isolate
        other guard rules.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # ── 1. Flag gate ─────────────────────────────────────────────────────────
    if flag_override is None:
        try:
            from ..core.config import settings
            flag_on = bool(getattr(settings, "dhl_orch_auto_send_dhl_followup", False))
        except Exception:
            flag_on = False
    else:
        flag_on = bool(flag_override)
    if not flag_on:
        return FollowupGuardResult(ok=False, reason="auto_send_dhl_followup_flag_off")

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

    # ── 4. Recipient validation ──────────────────────────────────────────────
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
        # Fallback: parse comma-string from pkg.to
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
        # Cheap sanity check: subject should reference the AWB to avoid
        # cross-shipment confusion if the builder ever loses context.
        return FollowupGuardResult(ok=False, reason="awb_missing_from_subject")

    # Attachment paths — when present, must resolve to existing files.  Empty
    # attachments list is allowed (follow-up is intentionally lightweight).
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

    # ── 6. Fresh ingest evidence ─────────────────────────────────────────────
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

    # ── 7. Idempotency duplicate check ───────────────────────────────────────
    idem_key = build_followup_idempotency_key(batch_id, audit)
    if not idem_key:
        return FollowupGuardResult(
            ok=False, reason="cannot_build_idempotency_key",
            ingest_age_min=ingest_age,
        )
    state = audit.get("dhl_followup") or {}
    sent_keys = state.get("sent_idempotency_keys") or []
    if not isinstance(sent_keys, list):
        sent_keys = []
    if idem_key in sent_keys:
        return FollowupGuardResult(
            ok=False, reason="duplicate_idempotency_key",
            idempotency_key=idem_key, ingest_age_min=ingest_age,
        )

    # ── 8. SLA age for telemetry ─────────────────────────────────────────────
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
    idem_key: str,
    *,
    cap: int = 100,
) -> None:
    """Append the idem key to audit.dhl_followup.sent_idempotency_keys.

    Bounded list (most-recent ``cap`` keys retained).  Mutates audit in
    place.  Caller is responsible for atomic persistence — this function
    does no I/O.
    """
    if not idem_key:
        return
    state = audit.setdefault("dhl_followup", {})
    keys = state.get("sent_idempotency_keys") or []
    if not isinstance(keys, list):
        keys = []
    if idem_key in keys:
        return
    keys.append(idem_key)
    if len(keys) > cap:
        keys = keys[-cap:]
    state["sent_idempotency_keys"] = keys
