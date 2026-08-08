"""
dhl_logistics_projector.py — Read-only DHL Logistics Control Tower projection.

PURE READ ONLY. No writes. No workflow mutation. No second tracker.

Aggregates existing authorities into one direction-aware logistics shape:

  Inbound  → batch audit timeline + dhl_readiness + tracking (inbound)
  Outbound → carrier_shipments + tracking_db/cache + delivery_confirmation_*

Does NOT persist duplicate business truth. Does NOT change
dhl_orchestrator.is_active_shipment (follow-up automation stays on its own
predicate). Control Tower "Active" uses logistics terminal rules so customs/PZ
completed residue does not inflate Active counts.

Timezone: UTC internally; operator-facing display fields use Europe/Warsaw.
"""
from __future__ import annotations

import json
import logging
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
    POLAND_TZ = ZoneInfo("Europe/Warsaw")
except Exception:  # pragma: no cover — Windows without tzdata
    POLAND_TZ = datetime.now().astimezone().tzinfo  # type: ignore[assignment]

# Hardcoded Lane A/B denylist — same literal as routes_dhl_clearance (no new authority).
_EXCLUDED_AWBS = frozenset({"5665916826"})

# Timeline events that mean physical delivery for logistics classification
# (broader than shipment_delivered_guard — covers older audits with timeline-only signals).
_DELIVERED_TIMELINE_EVENTS = frozenset({
    "carrier_delivered",
    "shipment_delivered",
})

# Ordered inbound logistics milestones (only real timeline / audit authorities).
# Each entry: (stage_id, label, event_names_tuple)
_INBOUND_MILESTONES: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("created", "Created / booked", ("batch_created", "awb_uploaded")),
    ("dhl_email", "DHL email received", ("dhl_email_received", "clearance_started", "dhl_inbox_scanned")),
    ("polish_desc", "Polish description", ("description_ready",)),
    ("dsk", "DSK generated / sent", ("dsk_generated", "dsk_transfer_sent")),
    ("dsk_received", "DSK / cesja received", ("dsk_received", "cesja_received")),
    ("agency", "Agency forwarded", ("agency_email_sent", "agency_followup_sent")),
    ("sad", "SAD / ZC429 / PZC", ("sad_uploaded", "zc429_received", "pzc_received", "sad_received", "duty_note_received")),
    ("customs_cleared", "Customs cleared", ("ganther_pzc_sent", "payment_confirmed", "ganther_invoice_received")),
    ("pz", "PZ generated", ("pz_generated",)),
    ("arrived_pl", "Arrived Poland", ("carrier_arrived_poland", "shipment_arrived_warsaw")),
    ("delivered", "Delivered", ("carrier_delivered", "shipment_delivered")),
)

# Preferred display order for inbound stage ribbon (physical → customs → warehouse).
_INBOUND_DISPLAY_ORDER = (
    "created", "arrived_pl", "dhl_email", "polish_desc", "dsk", "dsk_received",
    "agency", "sad", "customs_cleared", "pz", "delivered",
)

# Outbound tracking normalized stages we surface when present.
_OUTBOUND_STAGE_LABELS = {
    "SHIPMENT_CREATED": "Created",
    "PICKED_UP": "Picked up",
    "DEPARTED_ORIGIN": "Departed origin",
    "IN_TRANSIT": "In transit",
    "ARRIVED_DESTINATION_COUNTRY": "Arrived destination",
    "OUT_FOR_DELIVERY": "Out for delivery",
    "DELIVERED": "Delivered",
    "EXCEPTION": "Exception",
    "CLOSED": "Closed",
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _to_warsaw_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    try:
        return dt.astimezone(POLAND_TZ).isoformat()
    except Exception:
        return dt.isoformat()


def _hours_between(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
    if a is None or b is None:
        return None
    secs = (b - a).total_seconds()
    if secs < 0:
        return None
    return round(secs / 3600.0, 2)


def _fmt_duration(hours: Optional[float]) -> Optional[str]:
    if hours is None or hours < 0:
        return None
    total_m = int(round(hours * 60))
    d, rem = divmod(total_m, 60 * 24)
    h, m = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h or d:
        parts.append(f"{h}h")
    parts.append(f"{m}m")
    return " ".join(parts)


def _storage_root() -> Path:
    from ..core.config import settings
    return Path(settings.storage_root)


def _carrier_db_path() -> Path:
    from ..core.config import settings
    root = settings.carrier_storage_root or (_storage_root() / "carrier")
    return Path(root) / "carrier_shipments.db"


def _delivery_db_path() -> Path:
    return _storage_root() / "delivery_confirmations.db"


def _audit_paths() -> List[Path]:
    base = _storage_root() / "outputs"
    if not base.exists():
        return []
    out: List[Path] = []
    for p in base.glob("SHIPMENT_*/audit.json"):
        if "backup_before_regen" in str(p):
            continue
        out.append(p)
    return out


def _read_audit(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as exc:
        log.warning("logistics_projector: cannot read %s: %s", path, exc)
        return None


def _awb_of(audit: Dict[str, Any]) -> str:
    return str(audit.get("awb") or audit.get("tracking_no") or "").strip()


def _party_inbound(audit: Dict[str, Any]) -> str:
    for key in ("supplier", "exporter", "shipper", "supplier_name"):
        v = audit.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            name = v.get("name") or v.get("company") or ""
            if str(name).strip():
                return str(name).strip()
    return ""


def _first_timeline_ts(timeline: List[Dict[str, Any]], names: Tuple[str, ...]) -> Optional[datetime]:
    want = set(names)
    for ev in timeline:
        if not isinstance(ev, dict):
            continue
        if ev.get("event") in want:
            return _parse_iso(ev.get("ts"))
    return None


def _timeline_has(timeline: List[Dict[str, Any]], names) -> bool:
    want = set(names)
    return any(isinstance(e, dict) and e.get("event") in want for e in timeline)


def _is_physically_delivered(audit: Dict[str, Any], timeline: List[Dict[str, Any]]) -> bool:
    try:
        from .shipment_delivered_guard import is_audit_delivered
        if is_audit_delivered(audit):
            return True
    except Exception:
        pass
    if _timeline_has(timeline, _DELIVERED_TIMELINE_EVENTS):
        return True
    tr = audit.get("tracking") or {}
    if isinstance(tr, dict) and str(tr.get("status") or "").strip().lower() == "delivered":
        return True
    return False


def _is_customs_or_pz_complete(audit: Dict[str, Any], timeline: List[Dict[str, Any]]) -> bool:
    try:
        from .active_shipment_monitor import _is_customs_complete
        if _is_customs_complete(audit):
            return True
    except Exception:
        pass
    if _timeline_has(timeline, ("pz_generated",)):
        return True
    try:
        from .dhl_readiness import compute_dhl_readiness
        if compute_dhl_readiness(audit).get("dhl_status") == "customs_cleared":
            return True
    except Exception:
        pass
    return False


def classify_inbound(audit: Dict[str, Any]) -> str:
    """Return logistics classification for an inbound shipment.

    Values: active | delivered | completed | excluded | unknown
    """
    awb = _awb_of(audit)
    if not awb:
        return "unknown"
    if awb in _EXCLUDED_AWBS:
        return "excluded"
    timeline = audit.get("timeline") or []
    if not isinstance(timeline, list):
        timeline = []
    if _is_physically_delivered(audit, timeline):
        return "delivered"
    if _is_customs_or_pz_complete(audit, timeline):
        return "completed"
    if not (audit.get("clearance_decision") or audit.get("tracking") or timeline):
        return "unknown"
    return "active"


def _build_inbound_milestones(
    timeline: List[Dict[str, Any]],
    tracking_events: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build chronological milestone list with durations (real timestamps only)."""
    reached: Dict[str, datetime] = {}
    sources: Dict[str, str] = {}

    for stage_id, _label, names in _INBOUND_MILESTONES:
        ts = _first_timeline_ts(timeline, names)
        if ts is not None:
            reached[stage_id] = ts
            sources[stage_id] = "audit.timeline"

    for tev in tracking_events:
        if not isinstance(tev, dict):
            continue
        stage = str(tev.get("normalized_stage") or tev.get("stage") or "").upper()
        ts = _parse_iso(tev.get("event_time") or tev.get("timestamp"))
        if ts is None:
            continue
        if stage in ("ARRIVED_DESTINATION_COUNTRY",) and "arrived_pl" not in reached:
            reached["arrived_pl"] = ts
            sources["arrived_pl"] = "tracking_db"
        if stage in ("DELIVERED", "CLOSED") and "delivered" not in reached:
            reached["delivered"] = ts
            sources["delivered"] = "tracking_db"

    ordered_ids = [s for s in _INBOUND_DISPLAY_ORDER if s in reached]
    ordered_ids.sort(key=lambda sid: reached[sid])

    milestones: List[Dict[str, Any]] = []
    prev_ts: Optional[datetime] = None
    label_map = {sid: lab for sid, lab, _ in _INBOUND_MILESTONES}
    for sid in ordered_ids:
        ts = reached[sid]
        dur = _hours_between(prev_ts, ts)
        milestones.append({
            "stage_id": sid,
            "label": label_map.get(sid, sid),
            "timestamp_utc": ts.isoformat(),
            "timestamp_warsaw": _to_warsaw_iso(ts),
            "duration_from_previous_hours": dur,
            "duration_from_previous_human": _fmt_duration(dur),
            "authority": sources.get(sid, "audit.timeline"),
            "location": None,
        })
        prev_ts = ts
    return milestones


def _current_stage_from_milestones(
    milestones: List[Dict[str, Any]],
    classification: str,
) -> Tuple[str, Optional[datetime]]:
    if not milestones:
        return ("unknown", None)
    last = milestones[-1]
    return (last["stage_id"], _parse_iso(last.get("timestamp_utc")))


def _inbound_exception(audit: Dict[str, Any], timeline: List[Dict[str, Any]]) -> Optional[str]:
    tr = audit.get("tracking") or {}
    if isinstance(tr, dict):
        st = str(tr.get("status") or "").lower()
        if st in ("exception", "on_hold"):
            return st
    for ev in reversed(timeline):
        if not isinstance(ev, dict):
            continue
        name = str(ev.get("event") or "")
        if name in ("pz_blocked", "error", "dhl_followup_send_failed"):
            return name
    return None


def _inbound_gaps(audit: Dict[str, Any], milestones: List[Dict[str, Any]]) -> List[str]:
    gaps = [
        "estimated_delivery_not_in_tracking_service",
        "received_by_pod_signatory_not_parsed",
    ]
    if not any(m["stage_id"] == "arrived_pl" for m in milestones):
        gaps.append("india_pickup_or_poland_arrival_timestamp_missing")
    return gaps


def project_inbound_row(audit: Dict[str, Any], *, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Project one inbound logistics row from a batch audit. None if no AWB."""
    awb = _awb_of(audit)
    if not awb:
        return None
    now = now or _now_utc()
    timeline = audit.get("timeline") or []
    if not isinstance(timeline, list):
        timeline = []
    batch_id = str(audit.get("batch_id") or "").strip()

    tracking_events: List[Dict[str, Any]] = []
    try:
        from . import tracking_db as tdb
        if batch_id:
            tracking_events = tdb.get_events_for_batch(batch_id, direction="inbound") or []
    except Exception as exc:
        log.debug("logistics_projector: tracking_db inbound read failed: %s", exc)

    for ev in (audit.get("tracking_events") or []):
        if isinstance(ev, dict):
            tracking_events.append(ev)

    classification = classify_inbound(audit)
    milestones = _build_inbound_milestones(timeline, tracking_events)
    stage_id, stage_started = _current_stage_from_milestones(milestones, classification)

    created_at = _first_timeline_ts(timeline, ("batch_created", "awb_uploaded"))
    if created_at is None:
        created_at = _parse_iso(audit.get("created_at"))

    delivered_at = None
    for m in milestones:
        if m["stage_id"] == "delivered":
            delivered_at = _parse_iso(m.get("timestamp_utc"))
            break
    if delivered_at is None and classification == "delivered":
        delivered_at = _first_timeline_ts(timeline, tuple(_DELIVERED_TIMELINE_EVENTS))

    total_end = delivered_at or now
    total_hours = _hours_between(created_at, total_end)
    stage_age = _hours_between(stage_started, now) if classification == "active" else None

    tr = audit.get("tracking") if isinstance(audit.get("tracking"), dict) else {}
    current_status = (
        (tr or {}).get("status")
        or audit.get("clearance_status")
        or classification
    )
    current_location = (tr or {}).get("last_location") or (tr or {}).get("location")

    try:
        from .dhl_readiness import compute_dhl_readiness
        dhl_status = compute_dhl_readiness(audit).get("dhl_status")
    except Exception:
        dhl_status = None

    label_map = {sid: lab for sid, lab, _ in _INBOUND_MILESTONES}
    attention_reasons: List[str] = []
    exc = _inbound_exception(audit, timeline)
    if exc:
        attention_reasons.append(f"exception:{exc}")
    if classification == "active" and stage_age is not None and stage_age > 72:
        attention_reasons.append("stage_age_above_72h")
    if classification == "active" and dhl_status in ("dhl_replied", "agency_forwarded"):
        attention_reasons.append(f"waiting:{dhl_status}")

    return {
        "direction": "inbound",
        "classification": classification,
        "batch_id": batch_id or None,
        "awb": awb,
        "party": _party_inbound(audit),
        "party_role": "supplier",
        "carrier": "DHL",
        "created_at_utc": created_at.isoformat() if created_at else None,
        "created_at_warsaw": _to_warsaw_iso(created_at),
        "pickup_at_utc": None,
        "pickup_at_warsaw": None,
        "expected_delivery_utc": None,
        "expected_delivery_warsaw": None,
        "current_status": current_status,
        "current_location": current_location,
        "current_stage": stage_id,
        "current_stage_label": label_map.get(stage_id, stage_id),
        "stage_started_at_utc": stage_started.isoformat() if stage_started else None,
        "stage_started_at_warsaw": _to_warsaw_iso(stage_started),
        "stage_age_hours": stage_age,
        "stage_age_human": _fmt_duration(stage_age),
        "total_elapsed_hours": total_hours,
        "total_elapsed_human": _fmt_duration(total_hours),
        "delivered_at_utc": delivered_at.isoformat() if delivered_at else None,
        "delivered_at_warsaw": _to_warsaw_iso(delivered_at),
        "received_by": None,
        "exception": exc,
        "attention_reasons": attention_reasons,
        "needs_attention": bool(attention_reasons) and classification == "active",
        "customs_pipeline_status": dhl_status,
        "clearance_status": audit.get("clearance_status"),
        "milestones": milestones,
        "latest_event": (milestones[-1]["label"] if milestones else None),
        "latest_event_at_warsaw": (milestones[-1].get("timestamp_warsaw") if milestones else None),
        "dhl_email_requested": None,
        "dhl_sms_requested": None,
        "estrella_delivery_confirmation": None,
        "customer_response": None,
        "destination_country": "PL",
        "destination_city": None,
        "draft_id": None,
        "orch_active": None,
        "data_gaps": _inbound_gaps(audit, milestones),
    }


def _outbound_tracking_snapshot(awb: str, batch_id: str) -> Dict[str, Any]:
    """Best-effort read of tracking without live DHL poll (cache / tracking_db only)."""
    out: Dict[str, Any] = {
        "status": None,
        "last_event": None,
        "last_location": None,
        "events": [],
        "delivered_at": None,
        "picked_up_at": None,
        "expected_delivery": None,
        "received_by": None,
        "exception": None,
    }
    try:
        from . import tracking_db as tdb
        events = tdb.get_events_for_awb(awb, direction="outbound") or []
        if not events and batch_id:
            events = tdb.get_events_for_batch(batch_id, direction="outbound") or []
        out["events"] = events
        if events:
            last = events[-1]
            out["status"] = last.get("status") or last.get("normalized_stage")
            out["last_event"] = last.get("description") or last.get("stage")
            out["last_location"] = last.get("location")
            for ev in events:
                stage = str(ev.get("normalized_stage") or ev.get("stage") or "").upper()
                ts = _parse_iso(ev.get("event_time") or ev.get("timestamp"))
                if stage in ("PICKED_UP", "SHIPMENT_PICKED_UP") and out["picked_up_at"] is None:
                    out["picked_up_at"] = ts
                if stage in ("DELIVERED", "CLOSED"):
                    out["delivered_at"] = ts
                    out["status"] = "delivered"
                if stage == "EXCEPTION":
                    out["exception"] = ev.get("description") or "exception"
    except Exception as exc:
        log.debug("logistics_projector: outbound tracking_db failed: %s", exc)

    # Do NOT call live MyDHL from this projector — reporting must stay read-only
    # and must not create a second tracker poll path. tracking_db + audit events only.
    return out


def _delivery_confirmation_state(awb: str) -> Dict[str, Any]:
    """Read Estrella delivery-confirmation authority (PR #1150). No writes."""
    result = {
        "estrella_delivery_confirmation": None,
        "customer_response": None,
        "notification_status": None,
        "receipt_used_at": None,
    }
    db = _delivery_db_path()
    if not db.exists():
        return result
    try:
        from . import delivery_confirmation_db as dcdb
        notif = dcdb.get_notification_by_awb(db, awb)
        receipt = dcdb.get_receipt_for_awb(db, awb)
        if notif:
            result["notification_status"] = notif.get("status")
            result["estrella_delivery_confirmation"] = notif.get("status")
        if receipt:
            used = receipt.get("used_at")
            result["receipt_used_at"] = used
            result["customer_response"] = "received" if used else "pending"
    except Exception as exc:
        log.debug("logistics_projector: delivery_confirmation read failed: %s", exc)
    return result


def classify_outbound(row: Dict[str, Any], tracking: Dict[str, Any]) -> str:
    """Classify an outbound carrier_shipments row for logistics Active/Delivered.

    Note: carrier_shipments.state ``complete`` means *booking created successfully*
    (AWB issued) — NOT physical delivery. Physical delivery comes only from
    tracking evidence (delivered_at / status=delivered).
    """
    if int(row.get("do_not_use") or 0) == 1:
        return "excluded"
    if tracking.get("delivered_at") or str(tracking.get("status") or "").lower() == "delivered":
        return "delivered"
    state = str(row.get("state") or "")
    if state == "failed":
        return "exception"
    # pending/submitted/complete = booking lifecycle; still logistics-active until delivered
    if state in ("complete", "submitted", "pending") and row.get("tracking_ref"):
        return "active"
    return "unknown"


def project_outbound_row(row: Dict[str, Any], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or _now_utc()
    awb = str(row.get("tracking_ref") or "").strip()
    batch_id = str(row.get("batch_id") or "").strip()
    client = str(row.get("client_ref") or "").strip()
    created_at = _parse_iso(row.get("created_at"))
    tracking = _outbound_tracking_snapshot(awb, batch_id)
    classification = classify_outbound(row, tracking)
    conf = _delivery_confirmation_state(awb)

    pickup_at = tracking.get("picked_up_at") or created_at
    delivered_at = tracking.get("delivered_at")
    total_end = delivered_at or now
    total_hours = _hours_between(pickup_at or created_at, total_end)

    events = tracking.get("events") or []
    current_stage = "booked"
    stage_started = created_at
    if events:
        last = events[-1]
        current_stage = str(last.get("normalized_stage") or last.get("stage") or "in_transit")
        stage_started = _parse_iso(last.get("event_time") or last.get("timestamp")) or stage_started
    if classification == "delivered":
        current_stage = "DELIVERED"
        stage_started = delivered_at or stage_started

    stage_age = _hours_between(stage_started, now) if classification == "active" else None
    stage_label = _OUTBOUND_STAGE_LABELS.get(current_stage.upper(), current_stage)

    milestones: List[Dict[str, Any]] = []
    if created_at:
        milestones.append({
            "stage_id": "booked",
            "label": "Booking created",
            "timestamp_utc": created_at.isoformat(),
            "timestamp_warsaw": _to_warsaw_iso(created_at),
            "duration_from_previous_hours": None,
            "duration_from_previous_human": None,
            "authority": "carrier_shipments",
            "location": None,
        })
    prev = created_at
    for ev in events:
        if not isinstance(ev, dict):
            continue
        ts = _parse_iso(ev.get("event_time") or ev.get("timestamp"))
        if ts is None:
            continue
        stage = str(ev.get("normalized_stage") or ev.get("stage") or "event")
        dur = _hours_between(prev, ts)
        milestones.append({
            "stage_id": stage,
            "label": _OUTBOUND_STAGE_LABELS.get(stage.upper(), ev.get("description") or stage),
            "timestamp_utc": ts.isoformat(),
            "timestamp_warsaw": _to_warsaw_iso(ts),
            "duration_from_previous_hours": dur,
            "duration_from_previous_human": _fmt_duration(dur),
            "authority": "tracking_db",
            "location": ev.get("location"),
        })
        prev = ts

    attention: List[str] = []
    if tracking.get("exception"):
        attention.append("carrier_exception")
    # Stage-age attention only when we have real transit evidence — bare
    # "booked" with no tracking events is incomplete evidence, not a delay signal.
    has_transit_evidence = bool(events) or (
        str(tracking.get("status") or "").lower() not in ("", "none", "unknown")
        and classification == "active"
    )
    if (
        classification == "active"
        and has_transit_evidence
        and current_stage.upper() not in ("BOOKED",)
        and stage_age is not None
        and stage_age > 72
    ):
        attention.append("stage_age_above_72h")
    if "COLLECTION" in str(tracking.get("status") or "").upper() or "READY" in str(tracking.get("last_event") or "").upper():
        attention.append("ready_for_collection_or_missed")

    return {
        "direction": "outbound",
        "classification": classification,
        "batch_id": batch_id or None,
        "awb": awb,
        "party": client,
        "party_role": "customer",
        "carrier": "DHL",
        "created_at_utc": created_at.isoformat() if created_at else None,
        "created_at_warsaw": _to_warsaw_iso(created_at),
        "pickup_at_utc": pickup_at.isoformat() if isinstance(pickup_at, datetime) else None,
        "pickup_at_warsaw": _to_warsaw_iso(pickup_at) if isinstance(pickup_at, datetime) else None,
        "expected_delivery_utc": (
            tracking["expected_delivery"].isoformat()
            if isinstance(tracking.get("expected_delivery"), datetime) else None
        ),
        "expected_delivery_warsaw": (
            _to_warsaw_iso(tracking.get("expected_delivery"))
            if isinstance(tracking.get("expected_delivery"), datetime) else None
        ),
        "current_status": tracking.get("status") or row.get("state"),
        "current_location": tracking.get("last_location"),
        "current_stage": current_stage,
        "current_stage_label": stage_label,
        "stage_started_at_utc": stage_started.isoformat() if stage_started else None,
        "stage_started_at_warsaw": _to_warsaw_iso(stage_started),
        "stage_age_hours": stage_age,
        "stage_age_human": _fmt_duration(stage_age),
        "total_elapsed_hours": total_hours,
        "total_elapsed_human": _fmt_duration(total_hours),
        "delivered_at_utc": delivered_at.isoformat() if isinstance(delivered_at, datetime) else None,
        "delivered_at_warsaw": _to_warsaw_iso(delivered_at) if isinstance(delivered_at, datetime) else None,
        "received_by": tracking.get("received_by"),
        "exception": tracking.get("exception") or (row.get("error") if classification == "exception" else None),
        "attention_reasons": attention,
        "needs_attention": bool(attention) and classification in ("active", "exception"),
        "customs_pipeline_status": None,
        "clearance_status": None,
        "milestones": milestones,
        "latest_event": tracking.get("last_event") or (milestones[-1]["label"] if milestones else None),
        "latest_event_at_warsaw": milestones[-1].get("timestamp_warsaw") if milestones else None,
        "dhl_email_requested": None,
        "dhl_sms_requested": None,
        "estrella_delivery_confirmation": conf.get("estrella_delivery_confirmation"),
        "customer_response": conf.get("customer_response"),
        "destination_country": None,
        "destination_city": None,
        "draft_id": None,
        "orch_active": False,
        "do_not_use": bool(int(row.get("do_not_use") or 0)),
        "booking_state": row.get("state"),
        "data_gaps": [
            "mydhl_shipmentNotification_request_not_persisted",
            "estimated_delivery_not_in_tracking_service",
            "received_by_pod_signatory_not_parsed",
        ],
    }


def _percentile(values: List[float], p: float) -> Optional[float]:
    if len(values) < 3:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return round(ordered[int(k)], 2)
    return round(ordered[f] + (ordered[c] - ordered[f]) * (k - f), 2)


def _cohort_stats(hours_list: List[float]) -> Dict[str, Any]:
    clean = [h for h in hours_list if h is not None and h >= 0]
    if len(clean) < 3:
        return {
            "n": len(clean),
            "average": round(statistics.mean(clean), 2) if clean else None,
            "median": None,
            "p90": None,
            "sufficient": False,
        }
    return {
        "n": len(clean),
        "average": round(statistics.mean(clean), 2),
        "median": round(statistics.median(clean), 2),
        "p90": _percentile(clean, 90),
        "sufficient": True,
    }


def _stage_duration_analytics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    buckets: Dict[str, List[float]] = {}
    for r in rows:
        for m in r.get("milestones") or []:
            dur = m.get("duration_from_previous_hours")
            if dur is None:
                continue
            sid = str(m.get("stage_id") or "unknown")
            buckets.setdefault(sid, []).append(float(dur))
    return {sid: _cohort_stats(vals) for sid, vals in buckets.items()}


def project_logistics(
    *,
    direction: str = "all",
    view: str = "active",
    q: Optional[str] = None,
    stage: Optional[str] = None,
    needs_attention_only: bool = False,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the full Control Tower projection (read-only)."""
    now = _now_utc()
    inbound_rows: List[Dict[str, Any]] = []
    outbound_rows: List[Dict[str, Any]] = []

    for path in _audit_paths():
        audit = _read_audit(path)
        if not audit:
            continue
        if not audit.get("batch_id"):
            audit = dict(audit)
            audit["batch_id"] = path.parent.name
        row = project_inbound_row(audit, now=now)
        if row is None:
            continue
        try:
            from .dhl_orchestrator import is_active_shipment
            orch_active, _ = is_active_shipment(audit)
            row["orch_active"] = bool(orch_active)
        except Exception:
            row["orch_active"] = None
        inbound_rows.append(row)

    try:
        from .carrier.persistence import shipment_db as csdb
        for crow in csdb.list_tracked_shipments(_carrier_db_path()):
            outbound_rows.append(project_outbound_row(crow, now=now))
    except Exception as exc:
        log.warning("logistics_projector: outbound list failed: %s", exc)

    all_rows = inbound_rows + outbound_rows

    active_in = [r for r in inbound_rows if r["classification"] == "active"]
    active_out = [r for r in outbound_rows if r["classification"] == "active"]
    attention = [r for r in all_rows if r.get("needs_attention")]
    delivered_today = []
    today_w = now.astimezone(POLAND_TZ).date()
    for r in all_rows:
        if r["classification"] != "delivered":
            continue
        dts = _parse_iso(r.get("delivered_at_utc"))
        if dts and dts.astimezone(POLAND_TZ).date() == today_w:
            delivered_today.append(r)

    in_delivered_hours = [
        r["total_elapsed_hours"] for r in inbound_rows
        if r["classification"] in ("delivered", "completed") and r.get("total_elapsed_hours") is not None
    ]
    out_delivered_hours = [
        r["total_elapsed_hours"] for r in outbound_rows
        if r["classification"] == "delivered" and r.get("total_elapsed_hours") is not None
    ]
    in_stats = _cohort_stats([h for h in in_delivered_hours if isinstance(h, (int, float))])
    out_stats = _cohort_stats([h for h in out_delivered_hours if isinstance(h, (int, float))])

    direction = (direction or "all").lower()
    view = (view or "active").lower()
    rows = list(all_rows)
    if direction == "inbound":
        rows = [r for r in rows if r["direction"] == "inbound"]
    elif direction == "outbound":
        rows = [r for r in rows if r["direction"] == "outbound"]

    if view == "active":
        rows = [r for r in rows if r["classification"] in ("active", "exception")]
    elif view == "delivered":
        rows = [r for r in rows if r["classification"] in ("delivered", "completed")]
    elif view == "attention":
        rows = [r for r in rows if r.get("needs_attention")]

    if needs_attention_only:
        rows = [r for r in rows if r.get("needs_attention")]

    if stage:
        stage_l = stage.lower()
        rows = [
            r for r in rows
            if stage_l in str(r.get("current_stage") or "").lower()
            or stage_l in str(r.get("current_stage_label") or "").lower()
            or stage_l in str(r.get("current_status") or "").lower()
        ]

    if q:
        ql = q.lower().strip()
        rows = [
            r for r in rows
            if ql in str(r.get("awb") or "").lower()
            or ql in str(r.get("party") or "").lower()
            or ql in str(r.get("batch_id") or "").lower()
        ]

    df = _parse_iso(date_from) if date_from else None
    dt = _parse_iso(date_to) if date_to else None
    if df or dt:
        filtered = []
        for r in rows:
            created = _parse_iso(r.get("created_at_utc"))
            if created is None:
                continue
            if df and created < df:
                continue
            if dt and created > dt:
                continue
            filtered.append(r)
        rows = filtered

    def _sort_key(r: Dict[str, Any]):
        return (
            0 if r.get("needs_attention") else 1,
            -(r.get("stage_age_hours") or 0),
            r.get("created_at_utc") or "",
        )

    rows.sort(key=_sort_key)

    orch_active_count = sum(1 for r in inbound_rows if r.get("orch_active"))
    orch_active_but_completed = sum(
        1 for r in inbound_rows
        if r.get("orch_active") and r["classification"] in ("completed", "delivered")
    )

    analytics = {
        "inbound_transit_hours": in_stats,
        "outbound_transit_hours": out_stats,
        "stage_duration_samples": _stage_duration_analytics(inbound_rows + outbound_rows),
        "population_notes": {
            "active_inbound": "classification==active (not orch is_active_shipment)",
            "active_outbound": "carrier_shipments with tracking_ref, not delivered, not do_not_use",
            "avg_inbound_transit": "delivered+completed inbound with measurable created→end hours; n>=3 for median/p90",
            "avg_outbound_transit": "delivered outbound with measurable pickup/created→delivered; n>=3 for median/p90",
            "orch_residue": (
                f"{orch_active_but_completed} of {orch_active_count} orch-active inbound "
                "rows are logistics completed/delivered (reporting defect if shown as Active)"
            ),
        },
    }

    kpis = {
        "active_inbound": len(active_in),
        "active_outbound": len(active_out),
        "needs_attention": len(attention),
        "delivered_today": len(delivered_today),
        "avg_inbound_transit_hours": in_stats.get("average"),
        "avg_outbound_transit_hours": out_stats.get("average"),
        "inbound_transit_median_hours": in_stats.get("median"),
        "outbound_transit_median_hours": out_stats.get("median"),
        "orch_active_inbound": orch_active_count,
        "orch_active_but_logistics_terminal": orch_active_but_completed,
    }

    return {
        "generated_at_utc": now.isoformat(),
        "generated_at_warsaw": _to_warsaw_iso(now),
        "timezone": "Europe/Warsaw",
        "kpis": kpis,
        "analytics": analytics,
        "rows": rows,
        "count": len(rows),
        "filters_applied": {
            "direction": direction,
            "view": view,
            "q": q,
            "stage": stage,
            "needs_attention_only": needs_attention_only,
            "date_from": date_from,
            "date_to": date_to,
        },
        "authority": {
            "page": "presentation_analytics_only",
            "inbound": "audit.timeline + dhl_readiness + tracking inbound",
            "outbound": "carrier_shipments + tracking + delivery_confirmation",
            "no_writes": True,
        },
        "data_gaps": [
            "estimated_delivery_not_parsed_from_mydhl",
            "received_by_pod_signatory_not_in_tracking_service",
            "mydhl_shipmentNotification_not_persisted_on_booking_row",
            "inbound_india_pickup_timestamp_often_absent",
        ],
    }


def project_shipment_detail(awb: str) -> Optional[Dict[str, Any]]:
    """Return one shipment projection + full timeline by AWB (inbound or outbound).

    Looks up only the matching audit / carrier row — does not rescan the full
    Control Tower population on every drawer open.
    """
    awb = (awb or "").strip()
    if not awb:
        return None

    # Outbound first — AWB uniqueness is tracking_ref in carrier_shipments.
    try:
        from .carrier.persistence import shipment_db as csdb
        crow = csdb.get_shipment_by_tracking_ref(_carrier_db_path(), awb)
        if crow:
            return project_outbound_row(crow)
    except Exception as exc:
        log.debug("logistics_projector: detail outbound lookup failed: %s", exc)

    # Inbound — scan audits for matching AWB only (stop at first hit).
    for path in _audit_paths():
        audit = _read_audit(path)
        if not audit:
            continue
        if _awb_of(audit) != awb:
            continue
        if not audit.get("batch_id"):
            audit = dict(audit)
            audit["batch_id"] = path.parent.name
        return project_inbound_row(audit)
    return None


LOGISTICS_CSV_COLUMNS = [
    "direction", "party", "awb", "created_at_warsaw", "pickup_at_warsaw",
    "current_stage_label", "stage_age_hours", "total_elapsed_hours",
    "expected_delivery_warsaw", "delivered_at_warsaw", "exception",
    "classification", "batch_id", "current_status",
]


def rows_to_logistics_csv(rows: List[Dict[str, Any]]) -> bytes:
    from . import master_csv
    slim = [{c: r.get(c) for c in LOGISTICS_CSV_COLUMNS} for r in rows]
    return master_csv.rows_to_csv(slim, LOGISTICS_CSV_COLUMNS)
