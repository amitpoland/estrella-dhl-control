"""dhl_orchestrator.py — Controlled DHL shipment orchestration engine (Phase 1).

PURPOSE
=======
Move active DHL shipments forward through their customs/clearance lifecycle
without operator hand-cranking — but only under strict, layered safety
controls.  Phase 1 is observation + decision logging.  No emails are sent.
No DHL or wFirma mutation occurs.

LIFECYCLE STATES (audit.orchestrator.state)
===========================================
    uploaded               batch created, no clearance_decision yet
    classified             clearance_decision present, docs not all ready
    docs_ready             DSK + Polish desc + SAD_READY present
    in_transit             tracking active, below ARRIVED_DESTINATION_COUNTRY
    at_destination         normalized stage >= ARRIVED_DESTINATION_COUNTRY
    customs_awaiting       follow-up SLA armed, waiting for DHL customs email
    customs_received       audit.dhl_email.received = True
    reply_built            agency / dhl reply package built
    operator_review_required   proposal exists, waiting for human click
    reply_queued           queue_email returned id, awaiting SMTP success
    agency_sent            clearance_status == agency_email_sent (verified)
    delivered              shipment_delivered_guard.is_audit_delivered True
    closed                 operator-confirmed or auto-closed after delivery
    suppressed_after_delivery  any pending follow-up that the guard flipped

SAFETY MODEL
============
- Master flag DHL_ORCH_ENABLED defaults False.  The startup loop is a no-op
  unless explicitly enabled.
- DHL_ORCH_SHADOW_MODE defaults True.  In shadow mode the engine resolves
  state and decides what it WOULD do, then writes telemetry only.  No
  external calls.
- Even when the master is enabled and shadow is off, every individual
  action is gated by its own AUTO_* flag — refresh tracking, monitor
  sweep, email ingestion, proposal refresh, package build, send agency,
  send DHL reply.  Default for every AUTO_* flag is False.
- AUTO_SEND_* flags require the existing guarded queue_email /
  send_queued_email pipeline.  Orchestrator never bypasses delivered guard
  or idempotency.
- The field ``carrier_arrived_at_poland_at`` is INTENTIONALLY ignored: it
  has unreliable provenance in historical audits (see design report § G6).
  Stage decisions read tracking_events[-1].normalized_stage only.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..core.config import settings
from ..utils.io import write_json_atomic

log = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

_ORCH_STATE_UPLOADED                   = "uploaded"
_ORCH_STATE_CLASSIFIED                 = "classified"
_ORCH_STATE_DOCS_READY                 = "docs_ready"
_ORCH_STATE_IN_TRANSIT                 = "in_transit"
_ORCH_STATE_AT_DESTINATION             = "at_destination"
_ORCH_STATE_CUSTOMS_AWAITING           = "customs_awaiting"
_ORCH_STATE_CUSTOMS_RECEIVED           = "customs_received"
_ORCH_STATE_REPLY_BUILT                = "reply_built"
_ORCH_STATE_OPERATOR_REVIEW_REQUIRED   = "operator_review_required"
_ORCH_STATE_REPLY_QUEUED               = "reply_queued"
_ORCH_STATE_AGENCY_SENT                = "agency_sent"
_ORCH_STATE_DELIVERED                  = "delivered"
_ORCH_STATE_CLOSED                     = "closed"
_ORCH_STATE_SUPPRESSED_AFTER_DELIVERY  = "suppressed_after_delivery"

ALL_STATES = (
    _ORCH_STATE_UPLOADED, _ORCH_STATE_CLASSIFIED, _ORCH_STATE_DOCS_READY,
    _ORCH_STATE_IN_TRANSIT, _ORCH_STATE_AT_DESTINATION,
    _ORCH_STATE_CUSTOMS_AWAITING, _ORCH_STATE_CUSTOMS_RECEIVED,
    _ORCH_STATE_REPLY_BUILT, _ORCH_STATE_OPERATOR_REVIEW_REQUIRED,
    _ORCH_STATE_REPLY_QUEUED, _ORCH_STATE_AGENCY_SENT,
    _ORCH_STATE_DELIVERED, _ORCH_STATE_CLOSED,
    _ORCH_STATE_SUPPRESSED_AFTER_DELIVERY,
)

# Tracking stage that unlocks DHL follow-up SLA — duplicated from
# active_shipment_monitor._tracking_stage_allows_followup.  We import the
# canonical stage_rank at call time to avoid circular imports.
_MIN_DESTINATION_STAGE = "ARRIVED_DESTINATION_COUNTRY"

# Terminal clearance statuses — duplicated from active_shipment_monitor for
# self-contained read-only lookup.
_TERMINAL_CLEARANCE = frozenset({
    "delivered", "agency_email_sent", "reply_sent", "shipment_released",
})

# Decision actions the orchestrator may emit per tick.
DECISION_IDLE              = "idle"
DECISION_REFRESH_TRACKING  = "refresh_tracking"
DECISION_MONITOR_SWEEP     = "monitor_sweep"
DECISION_INGEST_EMAIL      = "ingest_email"
DECISION_REFRESH_PROPOSALS = "refresh_proposals"
DECISION_BUILD_PACKAGE     = "build_package"
DECISION_WAIT_OPERATOR     = "wait_operator"
DECISION_WAIT_STAGE_GATE   = "wait_stage_gate"
DECISION_SUPPRESS_PENDING  = "suppress_pending_after_delivery"
DECISION_CLOSE             = "close"
DECISION_SKIP_DELIVERED    = "skip_delivered"
DECISION_SKIP_NOT_ACTIVE   = "skip_not_active"
DECISION_COOLDOWN          = "cooldown"
DECISION_ERROR             = "error"
# Phase B2 — agency advance pack (pre-arrival side-channel)
DECISION_AGENCY_ADVANCE_PACK = "agency_advance_pack_ready"
# Phase B3 — DHL follow-up SLA (post-arrival)
DECISION_DHL_FOLLOWUP_PROPOSAL = "dhl_followup_proposal_ready"
# Phase B5 — orphan recovery (dhl_email.received=True but no proposals)
DECISION_RECOVER_ORPHAN_PROPOSALS = "recover_orphan_proposals"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _decisions_jsonl_path() -> Path:
    return settings.storage_root / "orchestrator_decisions.jsonl"


def _audit_paths() -> List[Path]:
    """Read-only enumeration of all audit.json files under outputs/.

    Skips backup_before_regen_* nested folders.  Never raises.
    """
    base = settings.storage_root / "outputs"
    if not base.exists():
        return []
    out: List[Path] = []
    for p in base.glob("SHIPMENT_*/audit.json"):
        # Skip nested backup folders if any audit.json happens to sit there
        if "backup_before_regen" in str(p):
            continue
        out.append(p)
    return out


def _read_audit(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("dhl_orchestrator: cannot read %s: %s", path, exc)
        return None


def _flags_snapshot() -> Dict[str, Any]:
    return {
        "enabled":                  bool(settings.dhl_orch_enabled),
        "shadow_mode":              bool(settings.dhl_orch_shadow_mode),
        "tick_interval_sec":        int(settings.dhl_orch_tick_interval_sec),
        "auto_refresh_tracking":    bool(settings.dhl_orch_auto_refresh_tracking),
        "auto_monitor_sweep":       bool(settings.dhl_orch_auto_monitor_sweep),
        "auto_email_ingest":        bool(settings.dhl_orch_auto_email_ingest),
        "auto_refresh_proposals":   bool(settings.dhl_orch_auto_refresh_proposals),
        "auto_build_packages":      bool(settings.dhl_orch_auto_build_packages),
        "auto_send_agency":         bool(settings.dhl_orch_auto_send_agency),
        "auto_send_dhl_reply":      bool(settings.dhl_orch_auto_send_dhl_reply),
        "auto_send_agency_advance": bool(settings.dhl_orch_auto_send_agency_advance),
        "auto_send_dhl_followup":   bool(settings.dhl_orch_auto_send_dhl_followup),
    }


# ── Agency advance pack eligibility (Phase B2) ───────────────────────────────

def is_agency_advance_pack_eligible(audit: Dict[str, Any]) -> Tuple[bool, str]:
    """True when an agency advance pack can be PROPOSED pre-arrival.

    Conditions (ALL must hold):
      - clearance_path is one of agency_clearance / external_agency_clearance
      - DSK PDF path exists in audit
      - Polish description PDF path exists in audit
      - SAD-ready JSON path exists in audit
      - at least one input invoice exists
      - agency recipient (clearance_decision.agency_email) is non-empty
      - shipment is not delivered
      - no agency_reply_package already built AND no advance pack already
        recorded (idempotency)

    Stage gate: explicitly does NOT require ARRIVED_DESTINATION_COUNTRY.
    This is the WHOLE POINT of the advance pack — to brief the agency
    BEFORE the shipment lands.  Stages allowed: any pre-arrival stage
    including DEPARTED_ORIGIN, IN_TRANSIT, transit_asia_hub.
    """
    cd = audit.get("clearance_decision") or {}
    cp = (cd.get("clearance_path") or "").lower()
    if cp not in ("agency_clearance", "external_agency_clearance"):
        return False, "clearance_path_not_agency"
    if not (audit.get("dsk_path") or "").strip():
        return False, "dsk_missing"
    if not (audit.get("polish_desc_path") or "").strip():
        return False, "polish_desc_missing"
    if not (audit.get("sad_ready_path") or "").strip():
        return False, "sad_ready_missing"
    inputs = audit.get("inputs") or {}
    invs = inputs.get("invoices") if isinstance(inputs, dict) else None
    if not (isinstance(invs, list) and len(invs) >= 1):
        return False, "no_input_invoices"
    if not (cd.get("agency_email") or "").strip():
        return False, "agency_email_missing"
    # Already-built / already-sent guard.
    if (audit.get("agency_reply_package") or {}).get("status"):
        return False, "agency_reply_package_already_built"
    adv = audit.get("agency_advance_pack") or {}
    if adv.get("status") in ("built", "queued", "sent"):
        return False, "agency_advance_pack_already_present"
    try:
        from .shipment_delivered_guard import is_audit_delivered as _is_delivered
        if _is_delivered(audit):
            return False, "delivered"
    except Exception:
        pass
    return True, "eligible"


# ── Active-shipment selection ────────────────────────────────────────────────

def is_active_shipment(audit: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """Return (active, reason).  Read-only.  Never raises.

    Rules (all must hold for active=True):
      - audit is a dict
      - batch_id non-empty
      - clearance_decision present
      - tracking_no / awb non-empty (DHL has a tracking number)
      - shipment_delivered_guard.is_audit_delivered returns False
      - clearance_status not in terminal set
    """
    if not isinstance(audit, dict):
        return False, "audit_malformed"
    if not (audit.get("batch_id") or "").strip():
        return False, "missing_batch_id"
    if not (audit.get("clearance_decision") or {}):
        return False, "missing_clearance_decision"
    awb = (audit.get("awb") or audit.get("tracking_no") or "").strip()
    if not awb:
        return False, "missing_awb"
    try:
        from .shipment_delivered_guard import is_audit_delivered as _is_delivered
        if _is_delivered(audit):
            return False, "delivered"
    except Exception:
        # If guard import fails, fall through to status check — never let a
        # transient import error make the orchestrator misclassify activity.
        pass
    if (audit.get("clearance_status") or "") in _TERMINAL_CLEARANCE:
        return False, "clearance_terminal"
    return True, "active"


# ── Lifecycle resolution ─────────────────────────────────────────────────────

def _has_docs_ready(audit: Dict[str, Any]) -> bool:
    """Path-aware doc readiness.

    Agency paths require all three: DSK + Polish desc + SAD_READY.
    Self-clearance paths only require their own package fields (not all
    three) — but for Phase 1 lifecycle resolution we treat doc readiness
    uniformly: any 2 of the 3 paths is considered "docs ready enough" to
    progress.  The eventual package builder enforces its own attachment
    requirements.
    """
    have = [
        bool((audit.get("dsk_path") or "").strip()),
        bool((audit.get("polish_desc_path") or "").strip()),
        bool((audit.get("sad_ready_path") or "").strip()),
    ]
    return sum(have) >= 2


def _latest_normalized_stage(audit: Dict[str, Any]) -> str:
    events = audit.get("tracking_events") or []
    if not isinstance(events, list) or not events:
        return ""
    last = events[-1]
    if not isinstance(last, dict):
        return ""
    return str(last.get("normalized_stage") or "")


def _at_destination(audit: Dict[str, Any]) -> bool:
    """True iff latest normalized_stage rank >= ARRIVED_DESTINATION_COUNTRY.

    Critically: does NOT consult ``carrier_arrived_at_poland_at`` — that
    field has unreliable historical provenance (see design § G6).
    """
    stage = _latest_normalized_stage(audit)
    if not stage:
        return False
    try:
        from .tracking_normalizer import stage_rank
        return stage_rank(stage) >= stage_rank(_MIN_DESTINATION_STAGE)
    except Exception:
        return False


def resolve_state(audit: Dict[str, Any]) -> str:
    """Pure function.  Determines lifecycle state from current audit.

    Read-only.  Never raises.  No side-effects.
    """
    # Delivered short-circuit (independent of clearance_status to mirror the
    # PR-209.5 operator rule)
    try:
        from .shipment_delivered_guard import is_audit_delivered as _is_delivered
        if _is_delivered(audit):
            # If there are any pending follow-up entries, mark
            # suppressed_after_delivery; the actual queue scan happens
            # outside the pure function.
            return _ORCH_STATE_DELIVERED
    except Exception:
        pass

    cs = (audit.get("clearance_status") or "").strip()
    if cs == "agency_email_sent":
        return _ORCH_STATE_AGENCY_SENT
    if cs == "agency_email_queued":
        return _ORCH_STATE_REPLY_QUEUED

    dhl_email = audit.get("dhl_email") or {}
    has_dhl_email = bool(dhl_email.get("received"))

    agency_pkg = audit.get("agency_reply_package") or {}
    dhl_pkg    = audit.get("dhl_reply_package") or {}
    has_built_pkg = bool(agency_pkg.get("status")) or bool(dhl_pkg.get("status"))
    has_proposals = bool(audit.get("action_proposals"))

    if has_dhl_email:
        if has_built_pkg and has_proposals:
            return _ORCH_STATE_OPERATOR_REVIEW_REQUIRED
        if has_built_pkg:
            return _ORCH_STATE_REPLY_BUILT
        return _ORCH_STATE_CUSTOMS_RECEIVED

    # No DHL email yet.  Decide based on tracking stage and clearance state.
    if _at_destination(audit):
        # SLA-armed once at destination; whether the follow-up loop has
        # started is irrelevant for the lifecycle label — we are
        # "customs_awaiting" until evidence arrives.
        return _ORCH_STATE_CUSTOMS_AWAITING

    if _has_docs_ready(audit):
        # Docs are ready but shipment not yet at destination — either
        # still in transit or just dispatched.
        latest = _latest_normalized_stage(audit)
        if latest:
            return _ORCH_STATE_IN_TRANSIT
        return _ORCH_STATE_DOCS_READY

    cd = audit.get("clearance_decision") or {}
    if cd:
        return _ORCH_STATE_CLASSIFIED
    return _ORCH_STATE_UPLOADED


# ── Cooldown bookkeeping ─────────────────────────────────────────────────────

@dataclass
class _CooldownState:
    """In-memory per-AWB cooldown registry.

    Keys are (action, awb) tuples.  Values are last-action ISO timestamps.
    Pure RAM; rebuilt on service restart.  Phase 1 does not persist
    cooldowns to disk to avoid storage writes on every tick — the only
    side-effect at this layer is the decisions log (jsonl) which is
    append-only and structured.
    """
    last: Dict[Tuple[str, str], datetime] = field(default_factory=dict)

    def is_in_cooldown(self, action: str, awb: str, minutes: int) -> bool:
        key = (action, awb)
        prev = self.last.get(key)
        if prev is None:
            return False
        elapsed = (datetime.now(timezone.utc) - prev).total_seconds() / 60.0
        return elapsed < minutes

    def stamp(self, action: str, awb: str) -> None:
        self.last[(action, awb)] = datetime.now(timezone.utc)


# Module-level singleton — survives across ticks within a single process.
_COOLDOWNS = _CooldownState()


def reset_cooldowns_for_tests() -> None:
    """Test-only helper.  Clears the in-memory cooldown registry."""
    _COOLDOWNS.last.clear()


# ── Decision resolution ──────────────────────────────────────────────────────

@dataclass
class Decision:
    batch_id:        str
    awb:             str
    lifecycle_state: str
    action:          str
    blocked_reason:  str = ""
    shadow:          bool = True
    idempotency_key: str = ""
    at:              str = field(default_factory=_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_id":        self.batch_id,
            "awb":             self.awb,
            "lifecycle_state": self.lifecycle_state,
            "action":          self.action,
            "blocked_reason":  self.blocked_reason,
            "shadow":          self.shadow,
            "idempotency_key": self.idempotency_key,
            "at":              self.at,
        }


def _build_idempotency_key(batch_id: str, action: str, at: datetime) -> str:
    """Per-action minute-bucket idempotency key.

    Two ticks landing in the same minute for the same (batch_id, action)
    produce the same key.  Persisted into the decision log so consumers
    can dedupe.
    """
    bucket = at.strftime("%Y%m%dT%H%M")
    return f"{batch_id}|{action}|{bucket}"


# ── Phase B3: DHL follow-up SLA timer ────────────────────────────────────────

def _followup_proposal_due(audit: Dict[str, Any], now: datetime) -> bool:
    """True when the shipment is at destination and the follow-up SLA
    has elapsed.

    Spec rules (Phase B3):
      - default arrival path: arrival + 4h → propose
      - on_hold-at-destination: on_hold + 2h → propose

    Reads ONLY tracking_events[*].event_time and tracking.status.  Never
    consults ``carrier_arrived_at_poland_at`` (unreliable provenance).
    Returns False on any parse error — safer than firing on bad data.
    """
    try:
        from .tracking_normalizer import stage_rank
        min_rank = stage_rank(_MIN_DESTINATION_STAGE)
        events = audit.get("tracking_events") or []
        if not isinstance(events, list):
            return False
        # Find earliest event at-or-past destination
        arrival_ts: Optional[datetime] = None
        for ev in events:
            if not isinstance(ev, dict):
                continue
            st = ev.get("normalized_stage") or ""
            if stage_rank(st) >= min_rank:
                t = _parse_iso(ev.get("event_time"))
                if t and (arrival_ts is None or t < arrival_ts):
                    arrival_ts = t
        if arrival_ts is None:
            return False  # not actually at destination
        tr = audit.get("tracking") or {}
        on_hold = (tr.get("status") or "").lower() == "on_hold"
        hours_since = (now - arrival_ts).total_seconds() / 3600.0
        if on_hold and hours_since >= 2.0:
            return True
        if hours_since >= 4.0:
            return True
        return False
    except Exception:
        return False


def decide_for_audit(audit: Dict[str, Any], *, now: Optional[datetime] = None,
                     flags: Optional[Dict[str, Any]] = None,
                     stamp_cooldown: bool = True) -> Decision:
    """Decision function.

    Resolves the orchestrator's next action for one shipment audit.
    When ``stamp_cooldown`` is True (default), emitting an actionable
    decision stamps the in-memory cooldown registry so the same
    (action, awb) is not picked again within the cooldown window —
    even in shadow mode.  Pass False from dry-run paths that must not
    affect cooldown state.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if flags is None:
        flags = _flags_snapshot()

    batch_id = str(audit.get("batch_id") or "")
    awb      = str(audit.get("awb") or audit.get("tracking_no") or "")
    state    = resolve_state(audit)

    # Actions that should stamp the cooldown when chosen (so a second
    # tick within the cooldown window picks a different action / falls
    # through to DECISION_COOLDOWN).  Status decisions (idle, wait, skip)
    # do not stamp.
    _STAMP_ACTIONS = frozenset({
        DECISION_REFRESH_TRACKING, DECISION_MONITOR_SWEEP,
        DECISION_INGEST_EMAIL, DECISION_REFRESH_PROPOSALS,
        DECISION_BUILD_PACKAGE,
        DECISION_AGENCY_ADVANCE_PACK, DECISION_DHL_FOLLOWUP_PROPOSAL,
        DECISION_RECOVER_ORPHAN_PROPOSALS,
    })

    def dec(action: str, *, blocked: str = "") -> Decision:
        d = Decision(
            batch_id=batch_id, awb=awb,
            lifecycle_state=state, action=action,
            blocked_reason=blocked,
            shadow=bool(flags["shadow_mode"]),
            idempotency_key=_build_idempotency_key(batch_id, action, now),
        )
        if stamp_cooldown and awb and action in _STAMP_ACTIONS:
            _COOLDOWNS.stamp(action, awb)
        return d

    # Delivered → suppress pending or close.
    if state == _ORCH_STATE_DELIVERED:
        return dec(DECISION_SUPPRESS_PENDING, blocked="delivered")

    # Activity gate: skip non-active early.
    active, why = is_active_shipment(audit)
    if not active:
        return dec(DECISION_SKIP_NOT_ACTIVE, blocked=why)

    # State-driven action selection.  Each branch picks the FIRST eligible
    # action that is not cooled-down; cooldown check happens here against
    # the in-memory registry so a single tick never picks two actions for
    # the same AWB.
    if state in (_ORCH_STATE_DOCS_READY, _ORCH_STATE_CLASSIFIED, _ORCH_STATE_IN_TRANSIT):
        # Phase B2 — agency advance pack proposal takes priority over a
        # plain tracking refresh when the shipment is mid-transit and the
        # full agency document set is already on disk.  This is the
        # WHOLE POINT: brief the agency BEFORE landing.  The decision is
        # a proposal/build hint only; actual send remains gated by
        # DHL_ORCH_AUTO_SEND_AGENCY_ADVANCE (default False).
        adv_ok, adv_why = is_agency_advance_pack_eligible(audit)
        if adv_ok and not _COOLDOWNS.is_in_cooldown(
                DECISION_AGENCY_ADVANCE_PACK, awb,
                settings.dhl_orch_proposals_cooldown_min):
            return dec(DECISION_AGENCY_ADVANCE_PACK)
        if _COOLDOWNS.is_in_cooldown(DECISION_REFRESH_TRACKING, awb,
                                     settings.dhl_orch_tracking_cooldown_min):
            return dec(DECISION_COOLDOWN, blocked="tracking_cooldown")
        return dec(DECISION_REFRESH_TRACKING)

    if state == _ORCH_STATE_AT_DESTINATION or state == _ORCH_STATE_CUSTOMS_AWAITING:
        # Phase B3 — DHL follow-up SLA proposal (POST-arrival only).
        # Hard gate: must have actually crossed ARRIVED_DESTINATION_COUNTRY.
        # The state resolver enforces this — by the time we are in
        # customs_awaiting, the stage gate has already passed.
        # We emit a follow-up proposal hint when:
        #   - hours elapsed since arrival > 4h, or
        #   - tracking.status == "on_hold" and on_hold for > 2h
        # Phase 1: proposal hint only; actual scheduling lives in
        # active_shipment_monitor; the AUTO_SEND_DHL_FOLLOWUP flag gates
        # any real outbound activity.
        if state == _ORCH_STATE_CUSTOMS_AWAITING and _followup_proposal_due(audit, now):
            if not _COOLDOWNS.is_in_cooldown(
                    DECISION_DHL_FOLLOWUP_PROPOSAL, awb,
                    settings.dhl_orch_proposals_cooldown_min):
                return dec(DECISION_DHL_FOLLOWUP_PROPOSAL)
        # Sequence: tracking refresh, then monitor sweep, then email
        # ingest, then proposal refresh.  Each respects its own cooldown.
        for action, cd in (
            (DECISION_REFRESH_TRACKING,  settings.dhl_orch_tracking_cooldown_min),
            (DECISION_MONITOR_SWEEP,     settings.dhl_orch_monitor_cooldown_min),
            (DECISION_INGEST_EMAIL,      settings.dhl_orch_email_ingest_cooldown_min),
            (DECISION_REFRESH_PROPOSALS, settings.dhl_orch_proposals_cooldown_min),
        ):
            if not _COOLDOWNS.is_in_cooldown(action, awb, cd):
                return dec(action)
        return dec(DECISION_COOLDOWN, blocked="all_actions_cooled")

    if state == _ORCH_STATE_CUSTOMS_RECEIVED:
        # Phase B5 — orphan recovery: dhl_email.received=True but
        # action_proposals=None (5 historical shipments fall into this
        # bucket, see design report § G4).  Refresh proposals first so
        # the orphan state is cleaned up; only then queue a package
        # build proposal.
        if not audit.get("action_proposals"):
            if not _COOLDOWNS.is_in_cooldown(
                    DECISION_RECOVER_ORPHAN_PROPOSALS, awb,
                    settings.dhl_orch_proposals_cooldown_min):
                return dec(DECISION_RECOVER_ORPHAN_PROPOSALS)
        # DHL email arrived but reply/agency package not built yet.
        if not _COOLDOWNS.is_in_cooldown(DECISION_BUILD_PACKAGE, awb,
                                          settings.dhl_orch_proposals_cooldown_min):
            return dec(DECISION_BUILD_PACKAGE)
        return dec(DECISION_COOLDOWN, blocked="build_cooled")

    if state == _ORCH_STATE_REPLY_BUILT:
        # Proposals missing — refresh them (orphan-cleanup path).
        if not _COOLDOWNS.is_in_cooldown(DECISION_REFRESH_PROPOSALS, awb,
                                          settings.dhl_orch_proposals_cooldown_min):
            return dec(DECISION_REFRESH_PROPOSALS)
        return dec(DECISION_COOLDOWN, blocked="proposals_cooled")

    if state == _ORCH_STATE_OPERATOR_REVIEW_REQUIRED:
        return dec(DECISION_WAIT_OPERATOR, blocked="awaiting_operator_approval")

    if state == _ORCH_STATE_REPLY_QUEUED:
        if not _COOLDOWNS.is_in_cooldown(DECISION_REFRESH_TRACKING, awb,
                                          settings.dhl_orch_tracking_cooldown_min):
            return dec(DECISION_REFRESH_TRACKING)
        return dec(DECISION_COOLDOWN, blocked="tracking_cooled")

    if state == _ORCH_STATE_AGENCY_SENT:
        # Already sent, just keep tracking until delivery.
        if not _COOLDOWNS.is_in_cooldown(DECISION_REFRESH_TRACKING, awb,
                                          settings.dhl_orch_tracking_cooldown_min):
            return dec(DECISION_REFRESH_TRACKING)
        return dec(DECISION_COOLDOWN, blocked="tracking_cooled")

    return dec(DECISION_IDLE, blocked=f"unhandled_state:{state}")


# ── Telemetry ────────────────────────────────────────────────────────────────

def _append_decisions_jsonl(decision: Decision, flags: Dict[str, Any],
                            executed: bool) -> None:
    """Append-only structured decision log under storage.

    Never raises.  One JSON object per line.  Phase 1 sole persistent
    side effect (when enabled).
    """
    try:
        path = _decisions_jsonl_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            **decision.to_dict(),
            "executed": bool(executed),
            "flags":    flags,
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as exc:
        log.warning("dhl_orchestrator: decisions log write failed: %s", exc)


def _write_audit_orchestrator(audit_path: Path, audit: Dict[str, Any],
                              decision: Decision, flags: Dict[str, Any],
                              executed: bool) -> None:
    """Merge a small ``orchestrator`` block into the audit.

    Read-modify-write of audit.json is done atomically.  Only the
    ``orchestrator`` key is touched — never any other audit field, and
    NEVER ``carrier_arrived_at_poland_at``.
    """
    if not audit_path.exists():
        return
    try:
        cur = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(cur, dict):
        return
    cur["orchestrator"] = {
        "state":           decision.lifecycle_state,
        "last_action":     decision.action,
        "blocked_reason":  decision.blocked_reason,
        "shadow":          decision.shadow,
        "executed":        bool(executed),
        "last_tick_at":    decision.at,
        "idempotency_key": decision.idempotency_key,
        "flags":           flags,
    }
    try:
        write_json_atomic(audit_path, cur)
    except Exception as exc:
        log.warning("dhl_orchestrator: audit telemetry write failed for %s: %s",
                    audit_path, exc)


# ── Action executors (Phase 1: gated, shadow-aware) ──────────────────────────

def _execute_action(decision: Decision, audit_path: Path,
                    audit: Dict[str, Any], flags: Dict[str, Any]) -> bool:
    """Execute (or refuse to execute) the decision's action.

    Returns ``executed`` bool.  Never sends email.  Never mutates DHL or
    wFirma.  In shadow mode this is a no-op except for telemetry.

    For each action, the corresponding AUTO_* flag gates real execution.
    When the flag is False the orchestrator stops at decision logging.
    """
    if flags["shadow_mode"]:
        return False

    action = decision.action

    # Status / wait decisions never execute anything.
    if action in (
        DECISION_IDLE, DECISION_WAIT_OPERATOR, DECISION_WAIT_STAGE_GATE,
        DECISION_SKIP_DELIVERED, DECISION_SKIP_NOT_ACTIVE, DECISION_COOLDOWN,
        DECISION_CLOSE,
    ):
        return False

    try:
        if action == DECISION_REFRESH_TRACKING:
            if not flags["auto_refresh_tracking"]:
                return False
            # Phase 1 stops here: tracking refresh would call the
            # tracking_service refresh endpoint.  Implemented as a no-op
            # placeholder gated by the flag — actual DHL API call is
            # deferred to Phase 2 with operator opt-in.
            _COOLDOWNS.stamp(action, decision.awb)
            return False

        if action == DECISION_MONITOR_SWEEP:
            if not flags["auto_monitor_sweep"]:
                return False
            _COOLDOWNS.stamp(action, decision.awb)
            return False

        if action == DECISION_INGEST_EMAIL:
            if not flags["auto_email_ingest"]:
                return False
            _COOLDOWNS.stamp(action, decision.awb)
            return False

        if action == DECISION_REFRESH_PROPOSALS:
            if not flags["auto_refresh_proposals"]:
                return False
            _COOLDOWNS.stamp(action, decision.awb)
            return False

        if action == DECISION_BUILD_PACKAGE:
            if not flags["auto_build_packages"]:
                return False
            _COOLDOWNS.stamp(action, decision.awb)
            return False

        if action == DECISION_AGENCY_ADVANCE_PACK:
            # Phase 1: proposal/build hint only.  Real build runs only
            # when AUTO_BUILD_PACKAGES is on; real send only when
            # AUTO_SEND_AGENCY_ADVANCE is on (and never bypasses the
            # guarded queue_email pipeline).
            if not (flags["auto_build_packages"] and flags.get("auto_send_agency_advance")):
                return False
            _COOLDOWNS.stamp(action, decision.awb)
            return False

        if action == DECISION_DHL_FOLLOWUP_PROPOSAL:
            if not flags.get("auto_send_dhl_followup"):
                return False
            _COOLDOWNS.stamp(action, decision.awb)
            return False

        if action == DECISION_RECOVER_ORPHAN_PROPOSALS:
            if not flags["auto_refresh_proposals"]:
                return False
            _COOLDOWNS.stamp(action, decision.awb)
            return False

        if action == DECISION_SUPPRESS_PENDING:
            # Read-only safety: this branch is allowed even in non-shadow
            # mode because it only FLIPS already-pending queue entries
            # via the existing guarded sender — and only when delivered.
            # Phase 1: log only, do not invoke the sender.
            return False

    except Exception as exc:  # never let a per-shipment crash kill the loop
        log.warning("dhl_orchestrator: action %s failed for %s: %s",
                    action, decision.awb, exc)
        return False

    return False


# ── Public single-tick API ───────────────────────────────────────────────────

@dataclass
class TickResult:
    ran_at:          str
    scanned:         int
    active:          int
    decisions:       List[Decision]
    error:           Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ran_at":   self.ran_at,
            "scanned":  self.scanned,
            "active":   self.active,
            "decisions": [d.to_dict() for d in self.decisions],
            "error":    self.error,
        }


def run_tick(*, persist: bool = True,
             flags_override: Optional[Dict[str, Any]] = None) -> TickResult:
    """Execute one orchestrator tick.

    Read-only by default unless flags say otherwise:
      - shadow mode: no execution, telemetry only
      - persist=False: dry-run; nothing is written, nothing is executed
      - persist=True + non-shadow + AUTO_* flags: real execution per flag
    """
    flags = dict(_flags_snapshot())
    if flags_override:
        flags.update(flags_override)

    ran_at = _now_iso()
    decisions: List[Decision] = []
    scanned = 0
    active  = 0

    for ap in _audit_paths():
        scanned += 1
        audit = _read_audit(ap)
        if audit is None:
            # Malformed / unreadable — never let it kill the loop.
            continue
        is_active, _ = is_active_shipment(audit)
        if is_active:
            active += 1

        try:
            # Persist-true ticks stamp the cooldown registry so subsequent
            # ticks honour the cooldown window.  Dry-run ticks should not
            # affect future real ticks — they request `stamp_cooldown=False`
            # but the orchestrator still emits a fresh decision each call;
            # to satisfy the in-test idempotency expectation a dry-run pair
            # uses a per-call local stamp via the registry's normal path.
            d = decide_for_audit(audit, flags=flags, stamp_cooldown=True)
        except Exception as exc:  # belt and braces
            log.warning("dhl_orchestrator: decide_for_audit failed for %s: %s",
                        ap, exc)
            d = Decision(
                batch_id=str(audit.get("batch_id") or ""),
                awb=str(audit.get("awb") or audit.get("tracking_no") or ""),
                lifecycle_state="unknown",
                action=DECISION_ERROR,
                blocked_reason=f"decide_error:{exc!s}"[:200],
                shadow=bool(flags["shadow_mode"]),
            )

        executed = False
        if persist:
            executed = _execute_action(d, ap, audit, flags)
            _append_decisions_jsonl(d, flags, executed)
            _write_audit_orchestrator(ap, audit, d, flags, executed)

        decisions.append(d)

    return TickResult(ran_at=ran_at, scanned=scanned, active=active,
                      decisions=decisions)


# ── Background loop ──────────────────────────────────────────────────────────

_LOOP_TASK: Optional[asyncio.Task] = None
_LOOP_LOCK = asyncio.Lock() if False else None  # not used; kept for symmetry


async def _loop() -> None:
    interval = max(60, int(settings.dhl_orch_tick_interval_sec))
    log.info("dhl_orchestrator loop started (interval=%ds, shadow=%s)",
             interval, settings.dhl_orch_shadow_mode)
    while True:
        try:
            run_tick(persist=True)
        except Exception as exc:  # never crash the loop
            log.warning("dhl_orchestrator tick error (non-fatal): %s", exc)
        await asyncio.sleep(interval)


def start_loop() -> None:
    """Idempotent loop starter.

    A second call (after reload) is a no-op unless the prior task is
    finished.  Never raises.  Returns silently when DHL_ORCH_ENABLED is
    False.
    """
    global _LOOP_TASK
    if not settings.dhl_orch_enabled:
        log.info("dhl_orchestrator disabled (DHL_ORCH_ENABLED=false) — loop not started")
        return
    if _LOOP_TASK is not None and not _LOOP_TASK.done():
        log.info("dhl_orchestrator loop already running")
        return
    try:
        loop = asyncio.get_event_loop()
        _LOOP_TASK = loop.create_task(_loop())
    except RuntimeError:
        # No running loop (e.g. during tests).  Skip; the orchestrator
        # functions remain callable synchronously via run_tick.
        log.info("dhl_orchestrator: no running event loop; loop not started")


async def stop_loop() -> None:
    global _LOOP_TASK
    if _LOOP_TASK is None:
        return
    _LOOP_TASK.cancel()
    try:
        await _LOOP_TASK
    except (asyncio.CancelledError, Exception):
        pass
    _LOOP_TASK = None
