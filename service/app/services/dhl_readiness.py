"""
dhl_readiness.py — Read-only DHL customs pipeline state reconstruction.

Reconstructs the 7-stage DHL clearance pipeline from the per-batch
audit.json timeline and (optionally) the tracking_db events.
No writes, no side effects.

Pipeline states (ordered, lowest → highest):
  awaiting_start   — no DHL activity recorded for this batch
  dhl_contacted    — DHL sent initial customs-hold email (dhl_email_received)
  dhl_replied      — we sent our DSK reply to DHL (dsk_transfer_sent)
  dsk_received     — DHL sent back cesja / DSK documents (cesja_received)
  agency_forwarded — we forwarded customs package to agency (agency_email_sent)
  sad_received     — agency provided SAD / ZC429 / PZC documents
  customs_cleared  — customs clearance confirmed (ganther / payment)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core import timeline as tl
from ..services import tracking_db as tdb
from ..core.config import settings


# ── Pipeline state ordering ────────────────────────────────────────────────────

_STATES = [
    "awaiting_start",
    "dhl_contacted",
    "dhl_replied",
    "dsk_received",
    "agency_forwarded",
    "sad_received",
    "customs_cleared",
]
_STATE_RANK: Dict[str, int] = {s: i for i, s in enumerate(_STATES)}

# ── Event → minimum pipeline state reached ────────────────────────────────────
# If this event appears in the timeline, we are AT LEAST at the mapped state.

_EVENT_STATE_MAP: Dict[str, str] = {
    # dhl_contacted
    tl.EV_DHL_EMAIL_RECEIVED:      "dhl_contacted",
    tl.EV_CLEARANCE_STARTED:       "dhl_contacted",
    tl.EV_DHL_INBOX_SCANNED:       "dhl_contacted",
    # dhl_replied — we sent our DSK back to DHL
    tl.EV_DSK_TRANSFER_SENT:       "dhl_replied",
    tl.EV_DHL_FOLLOWUP_SENT:       "dhl_replied",
    # dsk_received — DHL returned cesja / DSK auth documents
    tl.EV_CESJA_RECEIVED:          "dsk_received",
    tl.EV_DSK_RECEIVED:            "dsk_received",
    # agency_forwarded
    tl.EV_AGENCY_EMAIL_SENT:       "agency_forwarded",
    tl.EV_AGENCY_FOLLOWUP_SENT:    "agency_forwarded",
    # sad_received
    tl.EV_ZC429_RECEIVED:          "sad_received",
    tl.EV_PZC_RECEIVED:            "sad_received",
    tl.EV_SAD_UPLOADED:            "sad_received",
    # customs_cleared
    tl.EV_GANTHER_PZC_SENT:        "customs_cleared",
    tl.EV_PAYMENT_CONFIRMED:       "customs_cleared",
    tl.EV_GANTHER_INVOICE:         "customs_cleared",
    tl.EV_DUTY_NOTE_RECEIVED:      "sad_received",   # duty note → SAD stage confirmed
}

# ── SLA: outbound events (we sent something — waiting for a reply) ─────────────

_OUTBOUND_EVENTS = frozenset({
    tl.EV_DSK_TRANSFER_SENT,
    tl.EV_AGENCY_EMAIL_SENT,
    tl.EV_DHL_FOLLOWUP_SENT,
    tl.EV_AGENCY_FOLLOWUP_SENT,
    tl.EV_EMAIL_SENT,
    tl.EV_EMAIL_QUEUED,
})

# ── SLA: inbound / response events (we received something from the other side) ─

_INBOUND_EVENTS = frozenset({
    tl.EV_DHL_EMAIL_RECEIVED,
    tl.EV_CESJA_RECEIVED,
    tl.EV_DSK_RECEIVED,
    tl.EV_ZC429_RECEIVED,
    tl.EV_PZC_RECEIVED,
    tl.EV_DUTY_NOTE_RECEIVED,
    tl.EV_PAYMENT_CONFIRMED,
    tl.EV_GANTHER_PZC_SENT,
    tl.EV_GANTHER_INVOICE,
})

SLA_DAYS = 3

# ── Next action lookup ─────────────────────────────────────────────────────────

_NEXT_ACTION: Dict[str, Optional[str]] = {
    "awaiting_start":   "Send initial DHL DSK request",
    "dhl_contacted":    "Send DSK reply to DHL",
    "dhl_replied":      "Await DHL cesja / DSK authorization documents",
    "dsk_received":     "Forward DSK documents to customs agency",
    "agency_forwarded": "Await SAD / ZC429 / PZC from customs agency",
    "sad_received":     "Process customs documents and generate PZ",
    "customs_cleared":  None,
}


# ── Internal helpers ───────────────────────────────────────────────────────────

def _load_timeline(batch_id: str) -> List[Dict[str, Any]]:
    """Load audit.json["timeline"] for a batch. Returns [] if not found or unreadable."""
    audit_path: Path = settings.storage_root / "outputs" / batch_id / "audit.json"
    if not audit_path.exists():
        return []
    try:
        with audit_path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("timeline", [])
    except Exception:
        return []


def _load_audit_dict(batch_id: str) -> Dict[str, Any]:
    """Load the full audit.json. Returns {} on any failure."""
    audit_path: Path = settings.storage_root / "outputs" / batch_id / "audit.json"
    if not audit_path.exists():
        return {}
    try:
        with audit_path.open(encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:
        return {}


def _parse_ts(ts_str: Optional[str]) -> Optional[datetime]:
    """Parse an ISO timestamp string to a timezone-aware datetime. Returns None on failure."""
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _first_ts(events: List[Dict[str, Any]], *event_names: str) -> Optional[str]:
    """Return the timestamp of the first event whose name is in *event_names*."""
    target = set(event_names)
    for ev in events:
        if ev.get("event") in target:
            return ev.get("ts")
    return None


# ── Public API ─────────────────────────────────────────────────────────────────

def compute_dhl_readiness(audit: Dict[str, Any]) -> Dict[str, Any]:
    """Pure compute over a passed-in audit dict — never reads disk.

    Used by tests and by callers that already hold the audit in memory.
    Encodes the same compatibility rule as the disk-based variant:
    ``customs_declaration.received=True`` OR a populated
    ``customs_declaration.mrn`` is sufficient to flip the dhl pipeline
    into the ``sad_received`` state, even when the timeline is silent.
    """
    timeline = audit.get("timeline") or []
    cd       = audit.get("customs_declaration") or {}

    best_state = "awaiting_start"
    best_rank  = 0
    sad_received_ts: Optional[str] = None

    for ev in timeline:
        name = ev.get("event", "")
        ts   = ev.get("ts", "")
        if name in _EVENT_STATE_MAP:
            mapped = _EVENT_STATE_MAP[name]
            rank   = _STATE_RANK.get(mapped, 0)
            if rank > best_rank:
                best_state = mapped
                best_rank  = rank
        if name in (tl.EV_ZC429_RECEIVED, tl.EV_PZC_RECEIVED,
                    tl.EV_SAD_UPLOADED, tl.EV_DUTY_NOTE_RECEIVED):
            if sad_received_ts is None:
                sad_received_ts = ts

    if sad_received_ts is None:
        if cd.get("received") is True or (cd.get("mrn") or "").strip():
            sad_received_ts = (
                cd.get("received_at")
                or cd.get("clearance_date")
                or audit.get("timestamp")
                or ""
            ) or None
            if best_rank < _STATE_RANK.get("sad_received", 0):
                best_state = "sad_received"
                best_rank  = _STATE_RANK.get("sad_received", 0)

    return {
        "batch_id":      audit.get("batch_id"),
        "dhl_status":    best_state,
        "sad_received":  sad_received_ts,
        "awb":           audit.get("awb") or audit.get("tracking_no"),
    }


def get_dhl_readiness(batch_id: str) -> Dict[str, Any]:
    """
    Reconstruct the DHL customs pipeline state for *batch_id*.

    Reads from:
    - ``audit.json["timeline"]`` (primary pipeline markers)
    - ``tracking_db.shipment_tracking_events`` (AWB / carrier metadata)

    Pure read-only: never writes, never triggers side effects.
    """
    timeline: List[Dict[str, Any]] = _load_timeline(batch_id)
    tracking: List[Dict[str, Any]] = tdb.get_events_for_batch(batch_id)
    audit:    Dict[str, Any]       = _load_audit_dict(batch_id)

    # ── Extract AWB / carrier from tracking_db first, fall back to timeline ────
    awb: Optional[str] = None
    carrier: Optional[str] = None
    for row in tracking:
        awb = awb or (row.get("awb") or None)
        carrier = carrier or (row.get("carrier") or None)
        if awb and carrier:
            break
    if not awb or not carrier:
        for ev in timeline:
            detail = ev.get("detail") or {}
            if isinstance(detail, dict):
                awb = awb or detail.get("awb") or None
                carrier = carrier or detail.get("carrier") or None

    # ── Walk timeline events — determine state + collect milestones ────────────
    best_state = "awaiting_start"
    best_rank  = 0

    dhl_initial_sent:    Optional[str] = None  # first outbound we sent to DHL
    dhl_reply_received:  Optional[str] = None  # DHL's first reply to us
    dsk_docs_received:   Optional[str] = None  # DHL cesja / DSK auth docs
    agency_forwarded_ts: Optional[str] = None
    sad_received_ts:     Optional[str] = None
    customs_cleared_ts:  Optional[str] = None

    last_outbound_ts:    Optional[str] = None
    last_outbound_event: Optional[str] = None
    last_inbound_ts:     Optional[str] = None
    last_inbound_from:   Optional[str] = None

    for ev in timeline:
        event_name = ev.get("event", "")
        ts_str     = ev.get("ts", "")
        detail     = ev.get("detail") or {}

        # ── State advancement ──────────────────────────────────────────────────
        if event_name in _EVENT_STATE_MAP:
            mapped = _EVENT_STATE_MAP[event_name]
            rank   = _STATE_RANK.get(mapped, 0)
            if rank > best_rank:
                best_state = mapped
                best_rank  = rank

        # ── Milestone timestamps (first occurrence wins) ───────────────────────
        if event_name == tl.EV_DHL_EMAIL_RECEIVED and dhl_reply_received is None:
            dhl_reply_received = ts_str          # DHL's first inbound to us

        if event_name in (tl.EV_DSK_TRANSFER_SENT, tl.EV_DHL_FOLLOWUP_SENT):
            if dhl_initial_sent is None:
                dhl_initial_sent = ts_str        # first outbound we sent TO DHL

        if event_name in (tl.EV_CESJA_RECEIVED, tl.EV_DSK_RECEIVED):
            if dsk_docs_received is None:
                dsk_docs_received = ts_str

        if event_name == tl.EV_AGENCY_EMAIL_SENT and agency_forwarded_ts is None:
            agency_forwarded_ts = ts_str

        if event_name in (tl.EV_ZC429_RECEIVED, tl.EV_PZC_RECEIVED, tl.EV_SAD_UPLOADED,
                          tl.EV_DUTY_NOTE_RECEIVED):
            if sad_received_ts is None:
                sad_received_ts = ts_str

        if event_name in (tl.EV_GANTHER_PZC_SENT, tl.EV_PAYMENT_CONFIRMED,
                          tl.EV_GANTHER_INVOICE):
            if customs_cleared_ts is None:
                customs_cleared_ts = ts_str

        # ── SLA tracking: last outbound ────────────────────────────────────────
        if event_name in _OUTBOUND_EVENTS:
            if last_outbound_ts is None or ts_str > last_outbound_ts:
                last_outbound_ts    = ts_str
                last_outbound_event = event_name

        # ── SLA tracking: last inbound ─────────────────────────────────────────
        if event_name in _INBOUND_EVENTS:
            if last_inbound_ts is None or ts_str > last_inbound_ts:
                last_inbound_ts   = ts_str
                detail_from       = (
                    detail.get("sender")
                    or detail.get("from")
                    or ev.get("actor")
                    or None
                )
                last_inbound_from = detail_from

    # ── SLA breach calculation ─────────────────────────────────────────────────
    sla_breach              = False
    sla_breach_reason:       Optional[str] = None
    days_since_last_outbound: Optional[float] = None

    if last_outbound_ts:
        out_dt = _parse_ts(last_outbound_ts)
        if out_dt:
            now = datetime.now(timezone.utc)
            days_since_last_outbound = round(
                (now - out_dt).total_seconds() / 86400, 2
            )
            in_dt = _parse_ts(last_inbound_ts)
            inbound_after_outbound = in_dt is not None and in_dt > out_dt
            if not inbound_after_outbound and days_since_last_outbound > SLA_DAYS:
                sla_breach = True
                sla_breach_reason = (
                    f"No response received after {days_since_last_outbound:.1f} day(s) "
                    f"(SLA: {SLA_DAYS} days) — last outbound: "
                    f"{last_outbound_event or 'unknown'}"
                )

    # ── Compatibility belt — `customs_declaration` block can mark SAD ──────────
    # received via either:
    #   (a) the new dhl_zc429_intake path (customs_declaration.received=True), or
    #   (b) the legacy SAD-PDF-parser path (customs_declaration.mrn populated).
    # When the timeline did not emit a zc429_received / sad_uploaded /
    # pzc_received event but the audit nonetheless carries one of those
    # signals, treat the shipment as having reached sad_received so the
    # dashboard chip and PZ readiness reflect reality.
    if sad_received_ts is None:
        cd = audit.get("customs_declaration") or {}
        if cd.get("received") is True or (cd.get("mrn") or "").strip():
            sad_received_ts = (
                cd.get("received_at")
                or cd.get("clearance_date")
                or audit.get("timestamp")
                or ""
            ) or None
            if best_rank < _STATE_RANK.get("sad_received", 0):
                best_state = "sad_received"
                best_rank  = _STATE_RANK.get("sad_received", 0)

    # ── Downstream-evidence override (SAD received / PZ generated) ────────────
    # The SLA-breach signal is meaningful ONLY while we're still waiting on
    # DHL/agency to respond. Once SAD is in hand or the wFirma PZ has been
    # generated, "no DHL response" is no longer the actionable next step —
    # surfacing it would mask the real remaining work (customs clearance
    # confirmation, Proforma issuance, etc.).
    #
    # Likewise, the "Process customs documents and generate PZ" hint that
    # sits at `sad_received` becomes stale the moment a wFirma PZ exists.
    # We override the next-action to None in that case so the dashboard's
    # next-step picker advances to the next real blocker.
    wfirma_export = (audit.get("wfirma_export") or {})
    wfirma_pz_doc_id     = (wfirma_export.get("wfirma_pz_doc_id")     or "").strip()
    wfirma_pz_fullnumber = (wfirma_export.get("wfirma_pz_fullnumber") or "").strip()
    pz_generated         = bool(wfirma_pz_doc_id or wfirma_pz_fullnumber)

    if (sad_received_ts or pz_generated) and sla_breach:
        # We are no longer waiting on DHL — suppress the SLA breach
        # signal but record why so callers can audit the suppression.
        sla_breach        = False
        sla_breach_reason = (
            "suppressed: SAD received" if sad_received_ts and not pz_generated
            else "suppressed: wFirma PZ generated"
        )

    next_action = _NEXT_ACTION.get(best_state)
    if pz_generated and best_state == "sad_received":
        next_action = None

    # ── Missing documents (what we've asked for but haven't received) ──────────
    missing_documents: List[str] = []
    if best_state == "dhl_replied" and not dsk_docs_received:
        missing_documents.append("DHL cesja / DSK authorization documents")
    if best_state == "agency_forwarded" and not sad_received_ts:
        missing_documents.append("SAD / ZC429 / PZC from customs agency")

    return {
        "batch_id":                 batch_id,
        "dhl_status":               best_state,
        "awb":                      awb,
        "carrier":                  carrier,
        "dhl_initial_sent":         dhl_initial_sent,
        "dhl_reply_received":       dhl_reply_received,
        "dsk_docs_received":        dsk_docs_received,
        "agency_forwarded":         agency_forwarded_ts,
        "sad_received":             sad_received_ts,
        "customs_cleared":          customs_cleared_ts,
        "last_email_sent_at":       last_outbound_ts,
        "last_email_sent_type":     last_outbound_event,
        "last_email_received_at":   last_inbound_ts,
        "last_email_received_from": last_inbound_from,
        "days_since_last_outbound": days_since_last_outbound,
        "sla_breach":               sla_breach,
        "sla_breach_reason":        sla_breach_reason,
        "next_required_action":     next_action,
        "missing_documents":        missing_documents,
        "pz_generated":             pz_generated,
    }
