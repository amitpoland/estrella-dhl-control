"""
cowork_coordinator.py — Autonomous follow-up agent for customs workflow.

Responsibilities:
  - Iterate active batches and check their current workflow state
  - Send DHL follow-up if DSK has not been requested after arrival + 1 h
  - Trigger agency email pipeline when DSK is received
  - Send agency follow-up if SAD is missing after 3 h
  - Log all actions to timeline

Entry points:
  run_cowork_cycle()  — called by a background scheduler or CLI; single sweep
  schedule_tasks()    — pure function: returns task list for a given audit
  get_active_batches() — returns batch_ids of in-progress shipments

Cowork never sends directly — it calls email_service.queue_email() and writes
to audit.json.  All sends are picked up by MCP / admin review.

SAFETY: cowork only acts on confirmed state from audit.json.  It never calls
external APIs on its own (DHL tracking API is still pending) — it reads from
audit["tracking"] which is written by the tracking_service when active.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from ..core import timeline as tl
from ..services.clearance_path_alias import is_agency_clearance
from ..utils.batch_lock import batch_write_lock
from ..utils.io import write_json_atomic
from ..config.email_routing import DHL_TO, INTERNAL_CC, format_to, format_cc, primary

log = logging.getLogger(__name__)

_OUTPUTS = settings.storage_root / "outputs"

# ── Intelligence config + master loader ──────────────────────────────────────

_intel_config: Optional[Dict[str, Any]] = None
_intel_master: Optional[Dict[str, Any]] = None

def load_intelligence_master(force_reload: bool = False) -> Optional[Dict[str, Any]]:
    """
    Load intelligence_master.json (knowledge base from Task F docs). Cached.
    Returns None if master has not been built yet (run POST /api/v1/intelligence/build).
    """
    global _intel_master
    if _intel_master is not None and not force_reload:
        return _intel_master
    try:
        from ..services.intelligence_engine import load_master
        _intel_master = load_master(force_reload=force_reload)
        if _intel_master:
            log.info("[cowork] Intelligence master loaded (v%s, %d automation opps)",
                     _intel_master.get("version", "?"),
                     len(_intel_master.get("automation_opportunities", [])))
        else:
            log.debug("[cowork] Intelligence master not found — run POST /api/v1/intelligence/build")
    except Exception as exc:
        log.warning("[cowork] Could not load intelligence master: %s", exc)
    return _intel_master


def load_intelligence_config(force_reload: bool = False) -> Optional[Dict[str, Any]]:
    """
    Load intelligence config from storage (lazy, cached).
    Returns the suggested/activated config dict, or None if not available.
    """
    global _intel_config
    if _intel_config is not None and not force_reload:
        return _intel_config
    try:
        from ..services.intelligence_config_builder import load_config
        _intel_config = load_config()
        if _intel_config:
            log.info("[cowork] Intelligence config loaded (%d trusted senders)",
                     len(_intel_config.get("TRUSTED_CLEARANCE_SENDERS", [])))
        else:
            log.debug("[cowork] No intelligence config found — using defaults")
    except Exception as exc:
        log.warning("[cowork] Could not load intelligence config: %s", exc)
    return _intel_config

# ── Timing thresholds ─────────────────────────────────────────────────────────

_DSK_FOLLOWUP_HOURS   = 1    # after arrival: if DSK missing, follow up after this many hours
_SAD_FOLLOWUP_HOURS   = 3    # after agency email: follow up if SAD missing after this many hours

# Statuses that indicate the batch is still active (not closed/archived/exported)
_ACTIVE_STATUSES = {
    "processing",
    "awaiting_dhl_customs_email",
    "awaiting_dhl_email",
    "dhl_email_received",
    "polish_description_generated",
    "clearance_started",
    "dsk_generated",
    "reply_queued",
    "agency_email_queued",
}


# ── Task schema ───────────────────────────────────────────────────────────────

def schedule_tasks(audit: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Return a list of pending cowork tasks for the given audit.

    Tasks are advisory — the execution loop checks actual state before acting.
    """
    tasks: List[Dict[str, Any]] = []
    dec = audit.get("clearance_decision") or {}

    tasks.append({"type": "track_shipment", "priority": 1})

    if dec.get("require_dsk"):
        tasks.append({"type": "wait_for_dsk",          "priority": 2})
        tasks.append({"type": "followup_dhl_if_missing", "priority": 3})

    tasks.append({"type": "wait_for_sad",             "priority": 4})
    tasks.append({"type": "followup_agency_if_missing", "priority": 5})

    return tasks


# ── State readers ─────────────────────────────────────────────────────────────

def get_active_batches() -> List[str]:
    """Return batch IDs of non-archived, in-progress shipments."""
    batch_ids: List[str] = []
    if not _OUTPUTS.is_dir():
        return batch_ids
    for batch_dir in _OUTPUTS.iterdir():
        if not batch_dir.is_dir():
            continue
        audit_path = batch_dir / "audit.json"
        if not audit_path.exists():
            continue
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if audit.get("archived") or audit.get("exported"):
            continue
        status = audit.get("clearance_status") or audit.get("status") or ""
        if status in _ACTIVE_STATUSES or not status:
            batch_ids.append(batch_dir.name)
    return batch_ids


def load_audit(batch_id: str) -> Optional[Dict[str, Any]]:
    p = _OUTPUTS / batch_id / "audit.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_audit(batch_id: str, audit: Dict[str, Any]) -> None:
    p = _OUTPUTS / batch_id / "audit.json"
    if p.exists():
        write_json_atomic(p, audit)


def arrived_warehouse(audit: Dict[str, Any]) -> bool:
    """True if tracking confirms the shipment has arrived at Warsaw warehouse."""
    tr = audit.get("tracking") or {}
    return bool(tr.get("arrived_warehouse"))


def dsk_present(audit: Dict[str, Any]) -> bool:
    """True if DSK PDF has been generated for this batch."""
    return bool(audit.get("dsk_filename"))


def dsk_received(audit: Dict[str, Any]) -> bool:
    """
    True once the DSK transfer to DHL has been sent (clearance_status indicates it).
    We use the presence of 'dsk_transfer_queued' or dhl_reply_status='queued'
    with a DSK attachment.
    """
    return audit.get("clearance_status") in ("reply_queued", "reply_sent", "dsk_transfer_queued")


def sad_missing(audit: Dict[str, Any]) -> bool:
    """True if SAD / ZC429 has NOT yet been received (customs_declaration absent)."""
    cd = audit.get("customs_declaration") or {}
    return not cd.get("mrn")


def elapsed_hours(audit: Dict[str, Any], since_key: str = "clearance_updated_at") -> float:
    """
    Return elapsed hours since the given audit timestamp key.
    Falls back to 0.0 if key is absent or unparseable.
    """
    ts_str = audit.get(since_key)
    if not ts_str:
        return 0.0
    try:
        ts = datetime.fromisoformat(ts_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - ts
        return delta.total_seconds() / 3600.0
    except Exception:
        return 0.0


# ── Cowork action deduplication ──────────────────────────────────────────────

def _action_recent(state: Dict[str, Any], action: str, hours: float = 1.0) -> bool:
    """
    Return True if the given cowork action was recorded within `hours` ago.

    Reads from audit["cowork_last_actions"][action] — a dict of
    {action_name: ISO timestamp}.  Used to prevent the same action from
    being triggered twice within one hour (e.g. duplicate trigger_agency calls).
    """
    last_actions: Dict[str, str] = state.get("cowork_last_actions") or {}
    ts_str = last_actions.get(action)
    if not ts_str:
        return False
    try:
        ts = datetime.fromisoformat(ts_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
        return elapsed < hours
    except Exception:
        return False


def _record_action(state: Dict[str, Any], batch_id: str, action: str) -> None:
    """
    Record a cowork action timestamp in audit["cowork_last_actions"].
    Caller must call _save_audit after this.
    """
    state.setdefault("cowork_last_actions", {})[action] = (
        datetime.now(timezone.utc).isoformat()
    )


# ── Actions ───────────────────────────────────────────────────────────────────

def update_tracking(state: Dict[str, Any], batch_id: str) -> bool:
    """
    Update tracking data in audit.

    Priority:
      1. If DHL/FedEx API is active (status='active' + credentials): call the API.
      2. If API is pending or credentials missing: call tracking_service which
         returns a fallback with cowork_tracking_required=True — write that into
         audit["tracking"] so the dashboard and detect_triggers() see the signal.
      3. 1-hour dedup prevents re-running on every tight cycle.

    Returns True if state was updated.
    """
    tr = state.setdefault("tracking", {})
    if tr.get("status") == "delivered" or tr.get("arrived_warehouse"):
        return False  # already terminal

    # ── 1-hour dedup ──────────────────────────────────────────────────────────
    if _action_recent(state, "update_tracking", hours=1.0):
        return False

    awb     = state.get("tracking_no") or state.get("awb") or state.get("dhl_awb") or ""
    carrier = _detect_carrier(state)

    if not awb:
        return False

    try:
        from ..services.tracking_service import get_tracking_status
        from ..core.config import settings as _settings
        batch_dir = _OUTPUTS / batch_id
        result    = get_tracking_status(awb, carrier, cache_dir=batch_dir, refresh=False)
        state["tracking"] = result
        _record_action(state, batch_id, "update_tracking")
        return True
    except Exception as exc:
        log.warning("[cowork] update_tracking failed (non-fatal) for %s: %s", batch_id, exc)
        # Emit minimal cowork_tracking_required so the suggestion is still created
        if not tr.get("cowork_tracking_required"):
            from ..services.tracking_service import _dhl_tracking_url, _fedex_tracking_url
            tracking_url = (
                _fedex_tracking_url(awb) if carrier == "FEDEX"
                else _dhl_tracking_url(awb)
            )
            tr["cowork_tracking_required"] = True
            tr["cowork_tracking_reason"]   = f"tracking_service error: {exc}"
            tr["tracking_url"]             = tracking_url
            _record_action(state, batch_id, "update_tracking")
            return True
        return False


def send_followup_dhl(state: Dict[str, Any], batch_id: str) -> str | None:
    """
    Queue a DHL follow-up email asking for DSK status.
    Returns email_id or None if suppressed (already sent recently).
    """
    from ..services.email_service import queue_email

    last_followup = state.get("dhl_followup_sent_at")
    if last_followup:
        hrs = elapsed_hours(state, "dhl_followup_sent_at")
        if hrs < 24:
            log.debug("[cowork] DHL follow-up suppressed — sent %.1f h ago", hrs)
            return None

    awb = state.get("tracking_no") or state.get("awb") or ""
    subject = f"Re: DSK — AWB {awb}" if awb else "Re: DSK broker notification"
    body = (
        f"Szanowni Państwo,\n\n"
        f"Uprzejmie prosimy o potwierdzenie statusu powiadomienia brokera (DSK) "
        f"dla przesyłki AWB: {awb}.\n\n"
        f"Prosimy o odpowiedź.\n\nZ poważaniem,\nEstrella Jewels"
    )
    try:
        email_id = queue_email(
            to        = format_to(DHL_TO),
            subject   = subject,
            body_html = f"<pre>{body}</pre>",
            body_text = body,
            batch_id  = batch_id,
            cc        = format_cc(INTERNAL_CC),
        )
        state["dhl_followup_sent_at"] = datetime.now(timezone.utc).isoformat()
        state["dhl_followup_email_id"] = email_id
        _save_audit(batch_id, state)
        ap = _OUTPUTS / batch_id / "audit.json"
        tl.log_event(ap, tl.EV_DHL_FOLLOWUP_SENT, "cowork", "system",
                     detail={"email_id": email_id, "awb": awb, "to": format_to(DHL_TO)})
        log.info("[cowork] DHL follow-up queued — batch=%s email_id=%s", batch_id, email_id)
        return email_id
    except Exception as exc:
        log.error("[cowork] DHL follow-up failed for %s: %s", batch_id, exc)
        return None


def send_followup_agency(state: Dict[str, Any], batch_id: str) -> str | None:
    """
    Queue an agency follow-up asking for SAD status.
    Returns email_id or None if suppressed.
    """
    from ..services.email_service import queue_email
    from ..config.email_routing import AGENCY_TO, AGENCY_CC

    last_followup = state.get("agency_followup_sent_at")
    if last_followup:
        hrs = elapsed_hours(state, "agency_followup_sent_at")
        if hrs < 24:
            log.debug("[cowork] Agency follow-up suppressed — sent %.1f h ago", hrs)
            return None

    awb     = state.get("tracking_no") or state.get("awb") or ""
    dec     = state.get("clearance_decision") or {}
    # Spec v3 hard rule 7: agency follow-up reminders use the same recipient
    # layout as B1 and B4. TO contains Piotr + Ganther unless the audit's
    # clearance_decision carries a per-shipment agency override.
    _agency_to = dec.get("agency_email") or format_to(AGENCY_TO)
    to_addr = _agency_to
    cc_addr = format_cc(AGENCY_CC + INTERNAL_CC)
    subject = f"SAD/ZC429 — AWB {awb}" if awb else "SAD — status request"
    body = (
        f"Szanowni Państwo,\n\n"
        f"Uprzejmie prosimy o potwierdzenie statusu odprawy celnej "
        f"dla przesyłki AWB: {awb}.\n\n"
        f"Czy SAD/ZC429 został wystawiony?\n\n"
        f"Z poważaniem,\nEstrella Jewels"
    )
    try:
        email_id = queue_email(
            to        = to_addr,
            subject   = subject,
            body_html = f"<pre>{body}</pre>",
            body_text = body,
            batch_id  = batch_id,
            cc        = cc_addr,
        )
        state["agency_followup_sent_at"] = datetime.now(timezone.utc).isoformat()
        state["agency_followup_email_id"] = email_id
        _save_audit(batch_id, state)
        ap = _OUTPUTS / batch_id / "audit.json"
        tl.log_event(ap, tl.EV_AGENCY_FOLLOWUP_SENT, "cowork", "system",
                     detail={"email_id": email_id, "to": to_addr, "cc": cc_addr, "awb": awb})
        log.info("[cowork] Agency follow-up queued — batch=%s email_id=%s", batch_id, email_id)
        return email_id
    except Exception as exc:
        log.error("[cowork] Agency follow-up failed for %s: %s", batch_id, exc)
        return None


def trigger_agency(state: Dict[str, Any], batch_id: str) -> bool:
    """
    Trigger the agency email pipeline if not already sent.
    Returns True if triggered.
    """
    if state.get("agency_reply_package", {}).get("status") == "queued":
        return False  # already sent

    dec  = state.get("clearance_decision") or {}
    path = dec.get("clearance_path")
    if not is_agency_clearance(path):
        return False

    if not state.get("polish_desc_filename"):
        log.info("[cowork] Agency trigger deferred — Polish description not yet generated for %s", batch_id)
        return False

    # ── 1-hour dedup: skip if trigger_agency already ran recently ────────────
    if _action_recent(state, "trigger_agency", hours=1.0):
        log.debug("[cowork] trigger_agency suppressed — ran < 1 h ago for %s", batch_id)
        return False

    try:
        from ..services.agency_email_builder import build_agency_package
        from ..services.email_service import queue_email

        pkg = build_agency_package(state, batch_id)
        body_text = f"{pkg['body_pl']}\n\n---\n\n{pkg['body_en']}"
        email_id  = queue_email(
            to          = pkg["to"],
            subject     = pkg["subject"],
            body_html   = f"<pre>{body_text}</pre>",
            body_text   = body_text,
            batch_id    = batch_id,
            attachments = pkg.get("attachments", []),
        )
        state["agency_reply_package"] = {**pkg, "email_id": email_id, "status": "queued",
                                          "built_at": datetime.now(timezone.utc).isoformat()}
        state["clearance_status"] = "agency_email_queued"
        _record_action(state, batch_id, "trigger_agency")
        _save_audit(batch_id, state)
        ap = _OUTPUTS / batch_id / "audit.json"
        tl.log_event(ap, tl.EV_AGENCY_EMAIL_SENT, "cowork", "system",
                     detail={"email_id": email_id})
        return True
    except Exception as exc:
        log.error("[cowork] trigger_agency failed for %s: %s", batch_id, exc)
        return False


# ── Trigger detection (pure — no side effects) ───────────────────────────────

def detect_triggers(audit: Dict[str, Any], batch_id: str = "") -> List[Dict[str, Any]]:
    """
    Inspect the audit dict and return a list of suggested actions.

    SAFE: This function reads state only. It never writes to audit.json,
    never calls queue_email, and never modifies any external state.

    Each suggestion has the shape:
        {
          "trigger":    str,          # e.g. "DSK_MISSING", "DUTY_NOTE_DETECTED"
          "reason":     str,          # human-readable explanation
          "confidence": str,          # "high" | "medium" | "low"
          "action":     str,          # suggested human or system action
          "batch_id":   str,
          "awb":        str | None,
        }
    """
    suggestions: List[Dict[str, Any]] = []
    awb      = audit.get("awb") or audit.get("tracking_no") or audit.get("dhl_awb") or ""
    dec      = audit.get("clearance_decision") or {}
    cs       = audit.get("clearance_status") or audit.get("status") or ""
    # Read timeline once at the top — used by T2 fallback, T6 empty check, and SLA engine.
    timeline = audit.get("timeline") or []

    def _add(trigger: str, reason: str, confidence: str, action: str) -> None:
        suggestions.append({
            "trigger":    trigger,
            "reason":     reason,
            "confidence": confidence,
            "action":     action,
            "batch_id":   batch_id,
            "awb":        awb or None,
        })

    # ── T-track: Public tracking lookup required ─────────────────────────────
    # Fires when tracking_service returned cowork_tracking_required=True.
    # This means the DHL/FedEx API is not active and a human or browser-capable
    # Cowork agent should check the public tracking page and report back via
    # POST /api/v1/tracking/{awb}/cowork-result.
    tr = audit.get("tracking") or {}
    if tr.get("cowork_tracking_required") and not tr.get("cowork_result_received"):
        tracking_url = tr.get("tracking_url", "")
        carrier_name = tr.get("carrier") or "DHL/FedEx"
        reason_hint  = tr.get("cowork_tracking_reason") or "API pending"
        _add(
            "PUBLIC_TRACKING_LOOKUP_REQUIRED",
            f"{carrier_name} tracking API unavailable ({reason_hint}). "
            f"Public page check required for AWB {awb}.",
            "low",
            f"Open public tracking: {tracking_url} — then POST result to "
            f"/api/v1/tracking/{awb}/cowork-result.",
        )

    # ── T0: AWB missing — all automation blocked ──────────────────────────────
    if not awb or "awb_missing" in (audit.get("warnings") or []):
        _add(
            "AWB_MISSING",
            "Batch has no AWB/tracking number — all automation is blocked.",
            "high",
            "Manually set audit.awb or re-upload shipment with tracking number.",
        )
        return suggestions   # nothing else useful can be detected without AWB

    # ── T1: DSK missing after arrival ────────────────────────────────────────
    if dec.get("require_dsk") and arrived_warehouse(audit):
        if not dsk_present(audit):
            hrs = elapsed_hours(audit, "clearance_updated_at")
            _add(
                "DSK_MISSING",
                f"DSK required but not generated. {hrs:.1f}h since last clearance update.",
                "high" if hrs > _DSK_FOLLOWUP_HOURS else "medium",
                "Generate DSK via /api/v1/dhl/generate-description/{batch_id} or"
                " send follow-up to DHL.",
            )

    # ── T2: Duty note detected — payment pending ──────────────────────────────
    # Primary: direct timestamp field on audit.
    # Fallback: scan timeline for duty_note_received event (populated by email ingestion).
    # This bridges the gap when email_classifier has ingested the duty email but the
    # legacy timestamp field (duty_notice_received_at) has not been back-filled.
    duty_at = audit.get("duty_notice_received_at")
    if not duty_at:
        for ev in reversed(timeline):
            if ev.get("event") == "duty_note_received":
                duty_at = ev.get("ts")
                break
    if duty_at and not audit.get("duty_paid_signal_at"):
        try:
            ts = datetime.fromisoformat(duty_at)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            hrs = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
        except Exception:
            hrs = 0.0
        pln = audit.get("duty_amount_pln")
        pln_str = f"{pln} PLN" if pln else "amount unknown"
        _add(
            "DUTY_PAYMENT_PENDING",
            f"Duty notice received {hrs:.1f}h ago ({pln_str}), no payment confirmation yet.",
            "high" if hrs > 72 else "medium",
            "Confirm payment with accounts team (account@estrellajewels.eu). "
            "SLA: 72h warning, 7-day critical.",
        )

    # ── T3: SAD/ZC429 missing after agency email sent ────────────────────────
    if sad_missing(audit):
        agency_pkg = audit.get("agency_reply_package") or {}
        if agency_pkg.get("status") == "queued":
            hrs = elapsed_hours(audit, "clearance_updated_at")
            if hrs > _SAD_FOLLOWUP_HOURS:
                _add(
                    "SAD_DELAY",
                    f"Agency email sent but SAD/ZC429 not received after {hrs:.1f}h.",
                    "medium",
                    "Send follow-up email to ACS Spedycja (piotr@acspedycja.pl or"
                    " logistyka@acspedycja.pl).",
                )

    # ── T4: Cesja received — clearance clock should be running ───────────────
    cesja_status = audit.get("clearance_status") == "cesja_received"
    if cesja_status:
        hrs = elapsed_hours(audit, "clearance_updated_at")
        if hrs > 24:
            _add(
                "CLEARANCE_OVERDUE",
                f"Cesja received {hrs:.1f}h ago. No clearance signal. SLA = 24h.",
                "high",
                "Check with Ganther (ciagarlak@ganther.com.pl) for ACS clearance status.",
            )
        elif hrs > 6:
            _add(
                "CLEARANCE_SLOW",
                f"Cesja received {hrs:.1f}h ago. Typical clearance is 2–6h.",
                "low",
                "Monitor — may need follow-up if no clearance in next 18h.",
            )

    # ── T5: Clearance complete but Ganther relay not confirmed ───────────────
    cleared_statuses = {"cleared", "zc429_received", "pzc_received"}
    if cs in cleared_statuses:
        hrs = elapsed_hours(audit, "clearance_updated_at")
        if hrs > 8:
            _add(
                "GANTHER_RELAY_OVERDUE",
                f"Clearance confirmed {hrs:.1f}h ago. No Ganther PZC relay. SLA = 8h.",
                "medium",
                "Check with Ganther (ciagarlak@ganther.com.pl) if shipment has been released to DHL.",
            )

    # ── T6: Timeline empty or very short (data quality issue) ────────────────
    if len(timeline) == 0:
        _add(
            "TIMELINE_EMPTY",
            "No timeline events recorded for this batch.",
            "low",
            "Run scripts/backfill_awb_and_timeline.py to reconstruct minimal timeline.",
        )

    # ── Intelligence-layer enhanced triggers ──────────────────────────────────
    # These use the loaded intelligence config to enhance detection accuracy.
    suggestions.extend(_detect_intel_triggers(audit, batch_id))

    return suggestions


def _detect_carrier(audit: Dict[str, Any]) -> str:
    """Detect carrier from audit fields or AWB pattern."""
    import re as _re
    carrier = (audit.get("carrier") or "").upper()
    if carrier in ("DHL", "FEDEX"):
        return carrier
    awb = str(audit.get("awb") or audit.get("tracking_no") or "")
    if _re.fullmatch(r"\d{12}", awb):
        return "FEDEX"
    if _re.fullmatch(r"\d{10}", awb):
        return "DHL"
    return "DHL"


def _detect_intel_triggers(audit: Dict[str, Any], batch_id: str) -> List[Dict[str, Any]]:
    """
    Intelligence-enhanced trigger detection.

    Uses risk_detector + carrier awareness from intelligence config.
    SAFE: read-only, no writes, no emails.
    """
    suggestions: List[Dict[str, Any]] = []
    awb     = audit.get("awb") or audit.get("tracking_no") or ""
    carrier = _detect_carrier(audit)

    def _add_intel(trigger: str, reason: str, confidence: str, action: str) -> None:
        suggestions.append({
            "trigger":    trigger,
            "reason":     reason,
            "confidence": confidence,
            "action":     action,
            "batch_id":   batch_id,
            "awb":        awb or None,
            "source":     "intelligence_layer",
            "carrier":    carrier,
        })

    # ── T3: FedEx cesja not submitted (FedEx-specific) ────────────────────────
    if carrier == "FEDEX":
        fedex_arrival = audit.get("fedex_arrival_at")
        cesja_at      = audit.get("cesja_submitted_at")
        if fedex_arrival and not cesja_at:
            try:
                from datetime import datetime, timezone
                ts  = datetime.fromisoformat(fedex_arrival)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                hrs = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
            except Exception:
                hrs = 0.0
            if hrs > 24:
                _add_intel(
                    "DSK_MISSING_FEDEX",
                    f"FedEx shipment arrived {hrs:.1f}h ago. Cesja not submitted to pl-import@fedex.com.",
                    "high",
                    "Submit cesja form to pl-import@fedex.com immediately. "
                    "Ganther cannot file SAD without FedEx DSK.",
                )

    # ── T9: Duty routing gap (from VAT deferment or routing flags) ────────────
    if audit.get("vat_deferment_issue"):
        _add_intel(
            "VAT_DEFERMENT_GAP",
            "VAT deferment issue flagged in audit — clearance may be blocked.",
            "high",
            "Contact account@estrellajewels.eu to renew VAT deferment permission.",
        )

    # ── T12: FCA complication ─────────────────────────────────────────────────
    if audit.get("fca_complication"):
        _add_intel(
            "FCA_COMPLICATION",
            "FCA incoterms flagged — Ganther needs transport invoice.",
            "medium",
            "Request transport invoice from India shipper and send to Ganther.",
        )

    # ── Risk detector integration (timestamp-field based) ────────────────────
    try:
        from ..services.risk_detector import detect_sla_breach, detect_ganther_invoice_overdue
        for risk in detect_sla_breach(audit):
            _add_intel(
                risk["code"],
                risk["message"],
                "high" if risk["severity"] == "HIGH" else "medium",
                risk.get("detail", {}).get("action", "Investigate and resolve."),
            )
        for risk in detect_ganther_invoice_overdue(audit):
            _add_intel(
                risk["code"],
                risk["message"],
                "medium",
                "Review Ganther invoice and confirm payment with account@estrellajewels.eu.",
            )
    except Exception as exc:
        log.debug("[cowork] risk_detector error (non-fatal): %s", exc)

    # ── SLA engine integration (timeline-event based) ─────────────────────────
    try:
        timeline = audit.get("timeline") or []
        if timeline:
            from ..services.sla_engine import check_sla
            for sla_warn in check_sla(timeline, carrier=carrier, awb=awb, batch_id=batch_id):
                _add_intel(
                    sla_warn["code"],
                    sla_warn["message"],
                    "high" if sla_warn["severity"] == "HIGH" else "medium",
                    "Review clearance timeline and escalate if SLA is breached.",
                )
    except Exception as exc:
        log.debug("[cowork] sla_engine error (non-fatal): %s", exc)

    # ── Intelligence master: config enforcement ───────────────────────────────
    # Check timeline actor emails against master's known-actor list.
    # Flag any email that triggered a timeline event from an unrecognised sender.
    try:
        from ..services.intelligence_engine import load_master
        master = load_master()
        if master:
            known_emails: set = {
                a.get("email", "").lower()
                for a in (master.get("actor_discoveries") or [])
            }
            # Merge actors from intelligence_parser for completeness
            try:
                from ..services.intelligence_parser import _ACTORS as _known_actors
                for a in _known_actors:
                    known_emails.add(a.email.lower())
            except Exception:
                pass

            timeline_evts = audit.get("timeline") or []
            for ev in timeline_evts[-20:]:   # check only recent events
                actor = (ev.get("actor") or "").lower()
                detail = ev.get("detail") or {}
                src = (detail.get("trigger_source") or ev.get("trigger_source") or "")
                # Only flag events that came from email_classifier (real email senders)
                if src == "email_classifier" and actor and "@" in actor:
                    # Check exact address AND domain-pattern match
                    # (e.g. "ganther.com.pl" covers all @ganther.com.pl addresses)
                    actor_domain = actor.split("@")[-1]
                    if actor not in known_emails and actor_domain not in known_emails:
                        _add_intel(
                            "UNKNOWN_EMAIL_ACTOR",
                            f"Timeline event from unrecognised email actor: {actor}. "
                            f"Verify and add to trusted sender list if legitimate.",
                            "medium",
                            "Review sender in Zoho Mail inbox. If legitimate, add to "
                            "intelligence_parser._TRUSTED_CLEARANCE.",
                        )
                        break   # one warning per batch is enough
    except Exception as exc:
        log.debug("[cowork] intelligence_master actor-check error (non-fatal): %s", exc)

    # ── Intelligence master: carrier-rule cross-check ─────────────────────────
    try:
        from ..services.intelligence_engine import load_master
        master = load_master()
        if master and carrier == "FEDEX":
            # FedEx billing mode check — known issue from billing error AWB 882994160903
            fedex_rules = (master.get("carrier_rules") or {}).get("FEDEX") or {}
            billing = audit.get("fedex_billing_mode") or ""
            expected = fedex_rules.get("billing_mode", "sender_pays")
            if billing and billing.lower() != expected.lower():
                _add_intel(
                    "FEDEX_BILLING_MODE_MISMATCH",
                    f"FedEx billing mode '{billing}' expected '{expected}' — "
                    f"confirmed error pattern from AWB 882994160903.",
                    "medium",
                    "Verify FedEx billing mode is set to 'sender pays' with shipper.",
                )
    except Exception as exc:
        log.debug("[cowork] intelligence_master cross-check error (non-fatal): %s", exc)

    return suggestions


# ── Email ingestion hook (Zoho integration placeholder) ──────────────────────

def _scan_recent_emails_hook(
    batch_id: str,
    audit: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Zoho integration hook: scan for recent inbound emails related to this batch.

    PLACEHOLDER — returns empty list until Zoho MCP polling is wired in.

    Future production implementation will:
      1. Call ZohoMail via MCP to fetch recent emails for import@estrellajewels.eu
      2. Filter by AWB (or doc_no) matching this batch in subject/body
      3. Return email_obj dicts (sender, subject, body, attachments, email_id, received_at)
         for process_incoming_email()

    The hook is intentionally empty here so that:
      - test coverage can be added without real Zoho connectivity
      - the integration point is explicit and findable for future wiring
      - cowork runs safely without any network call until the hook is activated

    To activate: replace this function body with Zoho MCP calls, matching the
    email_obj schema expected by email_classifier.process_incoming_email().
    """
    return []


# ── Main execution loop ───────────────────────────────────────────────────────

def run_cowork_cycle(suggest_only: bool = False) -> Dict[str, Any]:
    """
    Single sweep of all active batches.  Safe to call on a cron schedule.
    Returns a summary dict for logging / health checks.

    suggest_only=True  — SAFE mode: detect triggers and return suggestions.
                         Reads audit.json only. Never sends emails, never
                         modifies audit, never calls queue_email.
                         Returns {"suggestions": [...], "batches_checked": n}

    suggest_only=False — EXECUTE mode (default): performs all cowork actions
                         (DHL follow-up, agency trigger, agency follow-up).
    """
    # ── SUGGEST-ONLY MODE — pure read, no side effects ────────────────────────
    if suggest_only:
        all_suggestions: List[Dict[str, Any]] = []
        checked = 0
        errors: List[str] = []

        for batch_id in get_active_batches():
            checked += 1
            try:
                state = load_audit(batch_id)
                if state is None:
                    continue
                sug = detect_triggers(state, batch_id)
                all_suggestions.extend(sug)
            except Exception as exc:
                log.error("[cowork][suggest] Error for %s: %s", batch_id, exc)
                errors.append(f"{batch_id}: {exc}")

        result: Dict[str, Any] = {
            "mode":            "suggest_only",
            "batches_checked": checked,
            "suggestions":     all_suggestions,
            "errors":          errors,
        }
        log.info("[cowork] Suggest-only sweep: %d batches, %d suggestions",
                 checked, len(all_suggestions))
        return result

    # ── EXECUTE MODE — performs real actions ──────────────────────────────────
    summary: Dict[str, Any] = {
        "mode":             "execute",
        "batches_checked":  0,
        "tracking_updated": 0,
        "dhl_followups":    0,
        "agency_triggered": 0,
        "agency_followups": 0,
        "errors":           [],
    }

    for batch_id in get_active_batches():
        summary["batches_checked"] += 1
        try:
            state = load_audit(batch_id)
            if state is None:
                continue

            # ── Guard: skip if AWB missing — automation blocked ────────────────
            if not state.get("awb") or "awb_missing" in (state.get("warnings") or []):
                log.debug("[cowork] Skipping %s — AWB missing", batch_id)
                continue

            # ── Per-batch write lock ───────────────────────────────────────────
            # Serialises all audit writes for this batch across concurrent cycles.
            # The initial load + AWB guard run outside the lock (cheap reads).
            # Re-read inside the lock to ensure atomic read-modify-write.
            with batch_write_lock(batch_id):
                state = load_audit(batch_id) or state

                # ── Email ingestion (BEFORE detect_triggers) ───────────────────
                # Process any new inbound emails and append events to the timeline
                # so that detect_triggers() sees the latest state this cycle.
                ap = _OUTPUTS / batch_id / "audit.json"
                ingested_count = 0
                for email_obj in _scan_recent_emails_hook(batch_id, state):
                    try:
                        from ..services.email_classifier import process_incoming_email
                        cls, ev = process_incoming_email(email_obj, ap)
                        if ev:
                            ingested_count += 1
                            log.info(
                                "[cowork] Email ingested: type=%s → event=%s batch=%s",
                                cls["type"], ev, batch_id,
                            )
                        elif cls.get("warnings"):
                            log.warning(
                                "[cowork] Email classified with warnings for %s: %s",
                                batch_id, cls["warnings"],
                            )
                    except Exception as exc:
                        log.warning("[cowork] Email ingestion failed (non-fatal) for %s: %s", batch_id, exc)

                # Re-read audit if emails were ingested (timeline may have changed)
                if ingested_count > 0:
                    state = load_audit(batch_id) or state

                # ── Detect triggers and generate action proposals ───────────────
                suggestions = detect_triggers(state, batch_id)
                if suggestions:
                    try:
                        from ..api.routes_action_proposals import generate_action_proposals
                        new_proposals = generate_action_proposals(state, batch_id, suggestions)
                        if new_proposals:
                            _save_audit(batch_id, state)
                            for prop in new_proposals:
                                tl.log_event(
                                    ap,
                                    tl.EV_ACTION_PROPOSAL_CREATED,
                                    "cowork",
                                    "system",
                                    detail={
                                        "proposal_id":   prop.get("proposal_id"),
                                        "proposal_type": prop.get("type"),
                                        "reason":        prop.get("reason", "")[:120],
                                    },
                                )
                            log.info(
                                "[cowork] Created %d proposal(s) for batch=%s",
                                len(new_proposals), batch_id,
                            )
                    except Exception as exc:
                        log.warning("[cowork] generate_action_proposals failed (non-fatal) for %s: %s",
                                    batch_id, exc)

                # ── 1. Tracking ────────────────────────────────────────────────
                if update_tracking(state, batch_id):
                    summary["tracking_updated"] += 1

                # ── 2. Post-arrival: DSK follow-up ────────────────────────────
                dec = state.get("clearance_decision") or {}
                if dec.get("require_dsk") and arrived_warehouse(state):
                    if not dsk_present(state):
                        if elapsed_hours(state, "clearance_updated_at") > _DSK_FOLLOWUP_HOURS:
                            if send_followup_dhl(state, batch_id):
                                summary["dhl_followups"] += 1

                # ── 3. DSK received → trigger agency ──────────────────────────
                if dsk_received(state) and is_agency_clearance(dec.get("clearance_path")):
                    if trigger_agency(state, batch_id):
                        summary["agency_triggered"] += 1

                # ── 4. SAD missing → agency follow-up ─────────────────────────
                if sad_missing(state):
                    agency_pkg = state.get("agency_reply_package") or {}
                    if agency_pkg.get("status") == "queued":
                        # Agency was notified; follow up after 3 h if SAD still missing
                        if elapsed_hours(state, "clearance_updated_at") > _SAD_FOLLOWUP_HOURS:
                            if send_followup_agency(state, batch_id):
                                summary["agency_followups"] += 1

        except Exception as exc:
            log.error("[cowork] Error processing batch %s: %s", batch_id, exc)
            summary["errors"].append(f"{batch_id}: {exc}")

    log.info("[cowork] Cycle complete — %s", summary)
    return summary
