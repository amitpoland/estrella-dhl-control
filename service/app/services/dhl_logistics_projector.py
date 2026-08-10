"""
dhl_logistics_projector.py — Read-only DHL Logistics Control Tower projection.

PURE READ ONLY. No writes. No workflow mutation. No second tracker / live MyDHL poll.

Aggregates existing authorities into one direction-aware logistics shape:

  Inbound  → batch audit timeline + tracking_cache + tracking_db (inbound)
  Outbound → carrier_shipments + tracking_cache (canonical, same as EJOutboundTrackingCard)
             + delivery_confirmation_*

Transport / customs / business-workflow are separate dimensions.
Main Status = transport_status. Booking state ``complete`` ≠ Delivered.
Customs/PZ complete does NOT remove an Active physical shipment.

Timezone: UTC internally; operator-facing display fields use Europe/Warsaw.
"""
from __future__ import annotations

import json
import logging
import math
import re
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


def _earliest_timeline_ts(timeline: List[Dict[str, Any]]) -> Optional[datetime]:
    earliest: Optional[datetime] = None
    for ev in timeline:
        if not isinstance(ev, dict):
            continue
        ts = _parse_iso(ev.get("ts"))
        if ts is None:
            continue
        if earliest is None or ts < earliest:
            earliest = ts
    return earliest


def _batch_id_month_start(batch_id: str) -> Optional[datetime]:
    """Parse SHIPMENT_<awb>_YYYY-MM_<hash> → first day of that month (UTC)."""
    m = re.search(r"_(\d{4})-(\d{2})_", str(batch_id or ""))
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), 1, tzinfo=timezone.utc)
    except Exception:
        return None


def _resolve_created_at(
    audit: Dict[str, Any],
    timeline: List[Dict[str, Any]],
    batch_id: str,
) -> Optional[datetime]:
    """Best-effort created anchor for age / residue — never invents delivery."""
    created = _first_timeline_ts(timeline, ("batch_created", "awb_uploaded"))
    if created is None:
        created = _parse_iso(audit.get("created_at"))
    if created is None:
        created = _earliest_timeline_ts(timeline)
    if created is None:
        created = _batch_id_month_start(batch_id)
    return created


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

    tracking = _inbound_tracking_snapshot(awb, batch_id, audit)
    tracking_events = list(tracking.get("events") or [])
    for ev in (audit.get("tracking_events") or []):
        if isinstance(ev, dict):
            tracking_events.append(ev)

    classification = classify_inbound(audit, tracking)
    customs_complete = _is_customs_or_pz_complete(audit, timeline)
    milestones = _build_inbound_milestones(timeline, tracking_events)
    # Inject cache-derived Poland arrival / delivered into milestones if missing
    if tracking.get("arrived_pl_at") and not any(m["stage_id"] == "arrived_pl" for m in milestones):
        milestones.append({
            "stage_id": "arrived_pl",
            "label": "Arrived Poland",
            "timestamp_utc": tracking["arrived_pl_at"].isoformat(),
            "timestamp_warsaw": _to_warsaw_iso(tracking["arrived_pl_at"]),
            "duration_from_previous_hours": None,
            "duration_from_previous_human": None,
            "authority": tracking.get("source") or "tracking_cache",
            "location": tracking.get("last_location"),
        })
        milestones.sort(key=lambda m: m.get("timestamp_utc") or "")
    if tracking.get("delivered_at") and not any(m["stage_id"] == "delivered" for m in milestones):
        milestones.append({
            "stage_id": "delivered",
            "label": "Delivered",
            "timestamp_utc": tracking["delivered_at"].isoformat(),
            "timestamp_warsaw": _to_warsaw_iso(tracking["delivered_at"]),
            "duration_from_previous_hours": None,
            "duration_from_previous_human": None,
            "authority": tracking.get("source") or "tracking_cache",
            "location": tracking.get("last_location"),
        })
        milestones.sort(key=lambda m: m.get("timestamp_utc") or "")

    stage_id, stage_started = _current_stage_from_milestones(milestones, classification)

    created_at = _resolve_created_at(audit, timeline, batch_id)

    delivered_at = tracking.get("delivered_at")
    if delivered_at is None:
        for m in milestones:
            if m["stage_id"] == "delivered":
                delivered_at = _parse_iso(m.get("timestamp_utc"))
                break
    if delivered_at is None and classification == "delivered":
        delivered_at = _first_timeline_ts(timeline, tuple(_DELIVERED_TIMELINE_EVENTS))

    pickup_at = tracking.get("picked_up_at")
    # Total transit: preferential pickup → delivered; freeze at delivery; — if delivered w/o ts
    booking_age_hours = _hours_between(created_at, delivered_at or now)
    if classification == "delivered":
        if delivered_at and (pickup_at or created_at):
            total_hours = _hours_between(pickup_at or created_at, delivered_at)
            # Reject inverted chronology
            if total_hours is None:
                total_hours = None
        else:
            total_hours = None  # delivered without trustworthy end/start → —
        stage_age = None
    else:
        start = pickup_at  # do not silently use booking as pickup for transit
        total_hours = _hours_between(start, now) if start else None
        stage_age = _hours_between(stage_started, now) if stage_started else (
            _hours_between(created_at, now) if created_at else None
        )

    booking_to_delivery = _hours_between(created_at, delivered_at) if delivered_at else None

    has_movement = _has_physical_movement(tracking)
    transport_status = _transport_status_label(
        tracking.get("status"), has_awb=bool(awb), has_movement=has_movement
    )
    if classification == "delivered":
        transport_status = "Delivered"
    elif classification == "exception":
        transport_status = "Exception"

    # Historical Unresolved residue — after transport truth is known; does not invent Delivered.
    if _is_historical_unresolved(
        classification=classification,
        customs_complete=customs_complete,
        has_movement=has_movement,
        created_at=created_at,
        delivered_at=delivered_at if isinstance(delivered_at, datetime) else None,
        now=now,
    ):
        classification = "historical_unresolved"

    try:
        from .dhl_readiness import compute_dhl_readiness
        dhl_status = compute_dhl_readiness(audit).get("dhl_status")
    except Exception:
        dhl_status = None
    customs_status = dhl_status or audit.get("clearance_status") or (
        "customs_complete" if customs_complete else "customs_open"
    )

    conf = _delivery_confirmation_state(awb)
    business_workflow_status = None
    if classification == "delivered":
        if conf.get("customer_response") == "received":
            business_workflow_status = "customer_confirmed"
        elif conf.get("estrella_delivery_confirmation"):
            business_workflow_status = "confirmation_sent"
        else:
            business_workflow_status = "delivered"

    attention_reasons: List[str] = []
    data_quality: List[str] = []
    # Carrier exception text only when CURRENT transport status is exceptional.
    # Workflow timeline errors (pz_blocked, etc.) are separate attention — not Exception.
    st_now = str(tracking.get("status") or "").lower()
    exc = None
    if st_now in ("exception", "failure", "on_hold"):
        exc = tracking.get("exception") or st_now
        attention_reasons.append(f"exception:{exc}")
    wf_exc = _inbound_exception(audit, timeline)
    if wf_exc and wf_exc not in ("exception", "on_hold"):
        attention_reasons.append(f"workflow:{wf_exc}")
    if tracking.get("tracking_stale") or tracking.get("refresh_error"):
        attention_reasons.append("tracking_stale")
        data_quality.append("tracking_stale")
    # Operational attention only — historical residue is audit/reporting, not Needs Attention.
    if classification == "active" and not has_movement and created_at:
        age = _hours_between(created_at, now)
        if age is not None and age >= NO_MOVEMENT_ATTENTION_HOURS:
            attention_reasons.append("no_carrier_movement_12h")
    last_blob = " ".join(
        str(x or "") for x in (tracking.get("status"), tracking.get("last_event"))
    ).upper()
    if classification in ("active", "exception") and any(
        k in last_blob for k in ("READY FOR COLLECTION", "MISSED", "ATTEMPTED", "COLLECTION")
    ):
        attention_reasons.append("missed_delivery_or_ready_for_collection")
    if classification == "delivered" and delivered_at is None:
        data_quality.append("delivered_without_timestamp")
    if delivered_at and created_at and delivered_at < created_at:
        data_quality.append("invalid_timestamp_order_delivery_before_created")
        total_hours = None
        booking_to_delivery = None
    if not tracking.get("events") and not tracking.get("status"):
        data_quality.append("tracking_evidence_missing")
    party = _party_inbound(audit)
    if not party:
        data_quality.append("missing_party_identity")

    # Stage age follows transport evidence, not the latest customs milestone.
    transport_stage_started = None
    if classification == "active":
        if tracking_events:
            last_ev = tracking_events[-1]
            transport_stage_started = _parse_iso(
                last_ev.get("event_time") or last_ev.get("timestamp") or last_ev.get("date")
            )
        if transport_stage_started is None:
            transport_stage_started = pickup_at or tracking.get("arrived_pl_at") or created_at
        stage_age = _hours_between(transport_stage_started, now) if transport_stage_started else stage_age
        stage_started = transport_stage_started or stage_started
    elif classification == "historical_unresolved":
        # Keep age visible for audit; stage is frozen reporting residue, not operational stage age growth semantics
        stage_age = _hours_between(created_at, now) if created_at else stage_age

    return {
        "direction": "inbound",
        "classification": classification,
        "transport_status": transport_status,
        "customs_status": customs_status,
        "customs_complete": customs_complete,
        "business_workflow_status": business_workflow_status,
        "batch_id": batch_id or None,
        "awb": awb,
        "party": party,
        "party_role": "supplier",
        "carrier": "DHL",
        "created_at_utc": created_at.isoformat() if created_at else None,
        "created_at_warsaw": _to_warsaw_iso(created_at),
        "pickup_at_utc": pickup_at.isoformat() if isinstance(pickup_at, datetime) else None,
        "pickup_at_warsaw": _to_warsaw_iso(pickup_at) if isinstance(pickup_at, datetime) else None,
        "expected_delivery_utc": None,
        "expected_delivery_warsaw": None,
        "current_status": transport_status,
        "current_location": tracking.get("last_location"),
        "current_stage": transport_status.lower().replace(" ", "_"),
        "current_stage_label": transport_status,
        "stage_started_at_utc": stage_started.isoformat() if stage_started and classification == "active" else None,
        "stage_started_at_warsaw": _to_warsaw_iso(stage_started) if classification == "active" else None,
        "stage_age_hours": stage_age,
        "stage_age_human": _fmt_duration(stage_age),
        "total_elapsed_hours": total_hours,
        "total_elapsed_human": _fmt_duration(total_hours),
        "booking_age_hours": booking_age_hours,
        "booking_age_human": _fmt_duration(booking_age_hours),
        "booking_to_delivery_hours": booking_to_delivery,
        "booking_to_delivery_human": _fmt_duration(booking_to_delivery),
        "pickup_is_authoritative": pickup_at is not None,
        "delivered_at_utc": delivered_at.isoformat() if isinstance(delivered_at, datetime) else None,
        "delivered_at_warsaw": _to_warsaw_iso(delivered_at) if isinstance(delivered_at, datetime) else None,
        "received_by": None,
        "exception": exc,
        "attention_reasons": attention_reasons,
        "tracking_stale": bool(tracking.get("tracking_stale")),
        "tracking_last_checked_at": tracking.get("tracking_last_checked_at"),
        "tracking_last_success_at": tracking.get("tracking_last_success_at"),
        "tracking_refresh_error": tracking.get("refresh_error"),
        "tracking_source": tracking.get("source"),
        "needs_attention": bool(attention_reasons) and classification in ("active", "exception"),
        "customs_pipeline_status": dhl_status,
        "clearance_status": audit.get("clearance_status"),
        "milestones": milestones,
        "latest_event": (milestones[-1]["label"] if milestones else tracking.get("last_event")),
        "latest_event_at_warsaw": (milestones[-1].get("timestamp_warsaw") if milestones else None),
        "dhl_email_requested": None,
        "dhl_sms_requested": None,
        "estrella_delivery_confirmation": conf.get("estrella_delivery_confirmation"),
        "customer_response": conf.get("customer_response"),
        "destination_country": "PL",
        "destination_city": None,
        "draft_id": None,
        "orch_active": None,
        "data_gaps": _inbound_gaps(audit, milestones),
        "data_quality": data_quality,
        "tracking_source": tracking.get("source"),
    }


def _event_time_key(ev: Dict[str, Any]) -> str:
    return str(
        ev.get("timestamp")
        or ev.get("event_time")
        or ev.get("date")
        or ev.get("time")
        or ""
    )


def _apply_latest_carrier_authority(out: Dict[str, Any], events: List[Any]) -> None:
    """Set transport status/location/exception/delivered_at from carrier events.

    Permanent rules:
      * Delivered only from explicit delivery evidence (sticky across stream).
      * Current status + location come from the LATEST event by timestamp.
      * Historical EXCEPTION / clearance text never latches as current Exception
        after newer movement.
      * Customs stages map to In Customs — not Exception, not Delivered.
    """
    ordered = [
        e for e in events
        if isinstance(e, dict)
    ]
    if not ordered:
        return
    ordered = sorted(ordered, key=_event_time_key)

    try:
        from .tracking_service import _derive_status_from_events
        status_key, status_label = _derive_status_from_events(ordered)
    except Exception:
        status_key, status_label = "in_transit", "In Transit"

    # Sticky delivered_at from any delivery event
    for ev in ordered:
        stage = str(ev.get("normalized_stage") or ev.get("stage") or "").upper()
        blob = " ".join(
            str(ev.get(k) or "") for k in ("description", "raw_description", "status", "statusCode")
        ).lower()
        ts = _parse_iso(ev.get("timestamp") or ev.get("event_time") or ev.get("date"))
        if stage in ("DELIVERED", "CLOSED") or (
            "delivered" in blob and "not delivered" not in blob
        ):
            out["delivered_at"] = ts or out.get("delivered_at")
            status_key, status_label = "delivered", "Delivered"
        if ts and ("picked up" in blob or stage in ("PICKED_UP", "SHIPMENT_PICKED_UP")):
            if out.get("picked_up_at") is None:
                out["picked_up_at"] = ts
        if ts and ("departed" in blob or stage in ("DEPARTED_ORIGIN", "DEPARTED_ORIGIN_HUB")):
            if out.get("departed_at") is None:
                out["departed_at"] = ts

    latest = ordered[-1]
    out["status"] = status_key
    out["status_label"] = status_label
    out["last_event"] = (
        latest.get("description")
        or latest.get("raw_description")
        or latest.get("status")
        or latest.get("stage")
        or out.get("last_event")
    )
    loc = latest.get("location") or latest.get("loc")
    if loc:
        out["last_location"] = loc
    # Exception text only when CURRENT transport status is exceptional
    if status_key in ("exception", "failure", "on_hold"):
        out["exception"] = (
            latest.get("description")
            or latest.get("raw_description")
            or status_label
        )
    else:
        out["exception"] = None
    if status_key == "delivered" and out.get("delivered_at") is None:
        out["delivered_at"] = _parse_iso(
            latest.get("timestamp") or latest.get("event_time") or latest.get("date")
        )


def _cache_record_is_failed_empty(rec: Dict[str, Any]) -> bool:
    """True when a failed/404 refresh left no usable carrier events."""
    if not isinstance(rec, dict):
        return True
    if rec.get("api_status") == "failed" and not (rec.get("events") or []):
        return True
    st = str(rec.get("status") or "").lower()
    if st in ("unknown", "", "not_found") and not (rec.get("events") or []):
        return True
    if (
        st in ("unknown", "")
        and not (rec.get("events") or [])
        and rec.get("source") in ("error", "cache_stale", "dhl_api_404")
    ):
        return True
    return False


def _outbound_tracking_snapshot(awb: str, batch_id: str) -> Dict[str, Any]:
    """Best-effort read of tracking WITHOUT live MyDHL poll.

    Authority order (same truth EJOutboundTrackingCard uses when cache is warm):
      1. per-batch tracking_cache.json via select_cached_tracking_record
         (skip failed-empty records — fall through to tracking_db)
      2. tracking_db events for the AWB (any direction — writers often omit outbound)
    Never call get_tracking_status(..., refresh=True) from this projector.
    Transport status/location always re-derived from latest carrier event.
    """
    out: Dict[str, Any] = {
        "status": None,
        "status_label": None,
        "last_event": None,
        "last_location": None,
        "events": [],
        "delivered_at": None,
        "picked_up_at": None,
        "departed_at": None,
        "expected_delivery": None,
        "received_by": None,
        "exception": None,
        "source": None,
        "tracking_stale": False,
        "tracking_last_checked_at": None,
        "tracking_last_success_at": None,
        "refresh_error": None,
    }

    # --- 1) Canonical cached snapshot (primary for outbound delivery) ---
    skipped_failed_cache = False
    if batch_id:
        try:
            from .tracking_service import (
                _load_cache,
                select_cached_tracking_record,
            )
            cache_dir = _storage_root() / "outputs" / batch_id
            if (cache_dir / "tracking_cache.json").exists():
                rec = select_cached_tracking_record(_load_cache(cache_dir), awb)
                if rec and _cache_record_is_failed_empty(rec):
                    skipped_failed_cache = True
                    out["tracking_stale"] = True
                    out["refresh_error"] = rec.get("refresh_error") or rec.get("error")
                    out["tracking_last_checked_at"] = (
                        rec.get("tracking_last_checked_at") or rec.get("cached_at")
                    )
                elif rec and not _cache_record_is_failed_empty(rec):
                    out["source"] = "tracking_cache"
                    out["tracking_last_checked_at"] = (
                        rec.get("tracking_last_checked_at") or rec.get("cached_at")
                    )
                    out["tracking_last_success_at"] = rec.get("tracking_last_success_at")
                    out["refresh_error"] = rec.get("refresh_error") or (
                        rec.get("error") if rec.get("api_status") == "failed" else None
                    )
                    if rec.get("tracking_stale") or rec.get("api_status") == "failed":
                        out["tracking_stale"] = True
                    cache_events = list(rec.get("events") or [])
                    out["events"] = cache_events
                    if cache_events:
                        _apply_latest_carrier_authority(out, cache_events)
                    else:
                        # Legacy cache with status only — still not invent Delivered
                        out["status"] = rec.get("status")
                        out["status_label"] = rec.get("status_label")
                        out["last_location"] = (
                            rec.get("last_location") or rec.get("location")
                        )
                    for key in ("estimated_delivery", "estimatedDeliveryDate", "expected_delivery"):
                        if rec.get(key):
                            out["expected_delivery"] = _parse_iso(rec.get(key))
                            break
        except Exception as exc:
            log.debug("logistics_projector: tracking_cache read failed: %s", exc)

    # --- 2) tracking_db secondary (do not force direction=outbound) ---
    try:
        from . import tracking_db as tdb
        events = tdb.get_events_for_awb(awb) or []
        if events:
            if not out["events"]:
                out["events"] = events
                out["source"] = out["source"] or "tracking_db"
                if skipped_failed_cache:
                    out["tracking_stale"] = True
                _apply_latest_carrier_authority(out, events)
            else:
                # Enrich pickup/delivery timestamps only — never latch historical
                # EXCEPTION stages over the cache-derived current status.
                for ev in events:
                    if not isinstance(ev, dict):
                        continue
                    stage = str(ev.get("normalized_stage") or ev.get("stage") or "").upper()
                    ts = _parse_iso(ev.get("event_time") or ev.get("timestamp"))
                    if stage in ("PICKED_UP", "SHIPMENT_PICKED_UP") and out["picked_up_at"] is None:
                        out["picked_up_at"] = ts
                    if stage in ("DEPARTED_ORIGIN",) and out["departed_at"] is None:
                        out["departed_at"] = ts
                    if stage in ("DELIVERED", "CLOSED"):
                        out["delivered_at"] = ts or out["delivered_at"]
                        out["status"] = "delivered"
                        out["status_label"] = "Delivered"
                        out["exception"] = None
    except Exception as exc:
        log.debug("logistics_projector: tracking_db read failed: %s", exc)

    # Do NOT call live MyDHL from this projector — reporting must stay read-only
    # and must not create a second tracker poll path.
    return out


def _inbound_tracking_snapshot(awb: str, batch_id: str, audit: Dict[str, Any]) -> Dict[str, Any]:
    """Inbound transport evidence from audit.tracking + batch tracking_cache + tracking_db."""
    out: Dict[str, Any] = {
        "status": None,
        "status_label": None,
        "last_location": None,
        "delivered_at": None,
        "picked_up_at": None,
        "arrived_pl_at": None,
        "events": [],
        "exception": None,
        "source": None,
        "tracking_stale": False,
        "tracking_last_checked_at": None,
        "tracking_last_success_at": None,
        "refresh_error": None,
    }
    tr = audit.get("tracking") if isinstance(audit.get("tracking"), dict) else {}
    if tr and not _cache_record_is_failed_empty(tr):
        out["status"] = tr.get("status")
        out["status_label"] = tr.get("status_label")
        out["last_location"] = tr.get("last_location") or tr.get("location")
        out["source"] = "audit.tracking"
        out["tracking_stale"] = bool(tr.get("tracking_stale"))
        out["tracking_last_checked_at"] = tr.get("tracking_last_checked_at") or tr.get("cached_at")
        out["tracking_last_success_at"] = tr.get("tracking_last_success_at")
        if str(tr.get("status") or "").lower() == "delivered":
            out["delivered_at"] = _parse_iso(tr.get("delivered_at") or tr.get("updated_at"))

    # Prefer cache (canonical) over audit.tracking when present and not failed-empty
    cache_snap = _outbound_tracking_snapshot(awb, batch_id)  # same cache reader
    if cache_snap.get("events") or (
        cache_snap.get("status") and not _cache_record_is_failed_empty(cache_snap)
    ):
        for k in (
            "status", "status_label", "last_location", "delivered_at", "picked_up_at",
            "events", "exception", "source", "tracking_stale",
            "tracking_last_checked_at", "tracking_last_success_at", "refresh_error",
        ):
            if cache_snap.get(k) is not None:
                out[k] = cache_snap.get(k)
        # Poland arrival from cache events
        for ev in cache_snap.get("events") or []:
            if not isinstance(ev, dict):
                continue
            blob = " ".join(str(ev.get(k) or "") for k in ("description", "location", "status")).lower()
            ts = _parse_iso(ev.get("timestamp") or ev.get("event_time"))
            if ts and ("poland" in blob or "warsaw" in blob or "pl-" in blob or blob.endswith(" pl")):
                if out["arrived_pl_at"] is None:
                    out["arrived_pl_at"] = ts

    try:
        from . import tracking_db as tdb
        if batch_id:
            db_events = tdb.get_events_for_batch(batch_id, direction="inbound") or []
            if not out["events"] and db_events:
                out["events"] = db_events
                out["source"] = out["source"] or "tracking_db"
                _apply_latest_carrier_authority(out, db_events)
            for ev in db_events:
                stage = str(ev.get("normalized_stage") or ev.get("stage") or "").upper()
                ts = _parse_iso(ev.get("event_time") or ev.get("timestamp"))
                if stage in ("ARRIVED_DESTINATION_COUNTRY",) and out["arrived_pl_at"] is None:
                    out["arrived_pl_at"] = ts
                if stage in ("DELIVERED", "CLOSED"):
                    out["delivered_at"] = ts or out["delivered_at"]
                    out["status"] = "delivered"
                    out["status_label"] = "Delivered"
                    out["exception"] = None
                if stage in ("PICKED_UP",) and out["picked_up_at"] is None:
                    out["picked_up_at"] = ts
    except Exception as exc:
        log.debug("logistics_projector: inbound tracking_db failed: %s", exc)

    # When cache was wiped by a failed refresh (429), recover from audit.tracking_events.
    # This is the same carrier evidence the normalizer already persisted — not a second poller.
    if not out["events"]:
        audit_events = [
            e for e in (audit.get("tracking_events") or [])
            if isinstance(e, dict)
        ]
        if audit_events:
            out["events"] = audit_events
            out["source"] = out["source"] or "audit.tracking_events"
            out["tracking_stale"] = True
            _apply_latest_carrier_authority(out, audit_events)

    return out


def _transport_status_label(status: Optional[str], *, has_awb: bool, has_movement: bool) -> str:
    """Human transport status for the main table — never booking 'complete'."""
    s = str(status or "").strip().lower().replace("-", "_").replace(" ", "_")
    if s in ("delivered",):
        return "Delivered"
    if s in ("returned", "cancelled"):
        return s.replace("_", " ").title()
    if s in ("exception", "failure", "on_hold"):
        return "Exception" if s != "on_hold" else "On Hold"
    if s in ("out_for_delivery",):
        return "Out for Delivery"
    if s in ("at_destination", "arrived_destination", "cleared"):
        return "At Destination"
    if s in ("in_customs", "customs"):
        return "In Customs"
    if s in ("in_transit", "transit", "departed"):
        return "In Transit"
    if s in ("picked_up", "pickup"):
        return "Picked up"
    if has_movement:
        return "In Transit"
    if has_awb:
        return "Pickup pending"
    return "Booked"


NO_MOVEMENT_ATTENTION_HOURS = 12.0

# Historical Unresolved / data residue — NOT Delivered, NOT deleted.
# Requires ALL of: no Delivered evidence, no physical carrier movement,
# customs/PZ complete, and created age well beyond operational handling.
# Age alone never classifies residue.
HISTORICAL_UNRESOLVED_HOURS = 30.0 * 24.0  # 30 days


def _is_historical_unresolved(
    *,
    classification: str,
    customs_complete: bool,
    has_movement: bool,
    created_at: Optional[datetime],
    delivered_at: Optional[datetime],
    now: datetime,
) -> bool:
    """True when an inbound row is stale customs-complete residue without transport progress.

    Does not invent Delivered. Does not change transport_status labels.
    """
    if classification != "active":
        return False
    if delivered_at is not None:
        return False
    if has_movement:
        return False
    if not customs_complete:
        return False
    age_h = _hours_between(created_at, now)
    if age_h is None or age_h < HISTORICAL_UNRESOLVED_HOURS:
        return False
    return True


def _has_physical_movement(tracking: Dict[str, Any]) -> bool:
    if tracking.get("picked_up_at") or tracking.get("departed_at") or tracking.get("delivered_at"):
        return True
    st = str(tracking.get("status") or "").lower()
    if st in ("", "unknown", "not_found", "none", "pending", "booked"):
        return False
    if st in ("delivered", "in_transit", "out_for_delivery", "picked_up", "in_customs",
              "at_destination", "cleared", "exception", "on_hold"):
        return True
    # Events with real carrier progress
    for ev in tracking.get("events") or []:
        if not isinstance(ev, dict):
            continue
        blob = " ".join(str(ev.get(k) or "") for k in ("description", "status", "normalized_stage")).lower()
        if any(k in blob for k in ("picked up", "departed", "transit", "delivered", "customs", "arrived")):
            return True
    return False


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


def classify_inbound(audit: Dict[str, Any], tracking: Optional[Dict[str, Any]] = None) -> str:
    """Transport-based classification for inbound Active/Delivered filters.

    customs/PZ completion is NOT a transport terminal — it is a separate customs_status.
    Exception requires CURRENT transport status — never a historical latch field.
    """
    awb = _awb_of(audit)
    if not awb:
        return "unknown"
    if awb in _EXCLUDED_AWBS:
        return "excluded"
    timeline = audit.get("timeline") or []
    if not isinstance(timeline, list):
        timeline = []
    tracking = tracking or {}
    st = str(tracking.get("status") or "").lower()
    if tracking.get("delivered_at") or st == "delivered" or _is_physically_delivered(audit, timeline):
        return "delivered"
    if st in ("exception", "failure", "on_hold"):
        return "exception"
    if not (audit.get("clearance_decision") or audit.get("tracking") or timeline or tracking.get("events")):
        return "unknown"
    return "active"


def classify_outbound(row: Dict[str, Any], tracking: Dict[str, Any]) -> str:
    """Classify outbound for logistics Active/Delivered.

    carrier_shipments.state ``complete`` = booking done, NOT physical delivery.
    """
    if int(row.get("do_not_use") or 0) == 1:
        return "excluded"
    st = str(tracking.get("status") or "").lower()
    if tracking.get("delivered_at") or st == "delivered":
        return "delivered"
    if st in ("returned", "cancelled"):
        return "delivered"  # terminal non-active
    state = str(row.get("state") or "")
    if state == "failed" or st in ("exception", "failure", "on_hold"):
        return "exception"
    if row.get("tracking_ref"):
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

    # Never treat booking created_at as pickup — pickup must be authoritative.
    pickup_at = tracking.get("picked_up_at")
    departed_at = tracking.get("departed_at")
    delivered_at = tracking.get("delivered_at")
    has_movement = _has_physical_movement(tracking)
    events = tracking.get("events") or []

    booking_age_hours = _hours_between(created_at, delivered_at or now)
    booking_to_delivery = _hours_between(created_at, delivered_at) if delivered_at else None

    data_quality: List[str] = []
    if classification == "delivered" and delivered_at is None:
        data_quality.append("delivered_without_timestamp")
    if delivered_at and created_at and delivered_at < created_at:
        data_quality.append("invalid_timestamp_order_delivery_before_created")

    if classification == "delivered":
        if delivered_at and pickup_at and delivered_at >= pickup_at:
            total_hours = _hours_between(pickup_at, delivered_at)
        elif delivered_at and created_at and delivered_at >= created_at and pickup_at is None:
            # Prefer pickup; without pickup leave total as — and expose booking_to_delivery
            total_hours = None
        else:
            total_hours = None
        stage_age = None
        stage_started = delivered_at
    else:
        total_hours = _hours_between(pickup_at, now) if pickup_at else None
        stage_started = created_at
        if events:
            last = events[-1]
            stage_started = _parse_iso(last.get("event_time") or last.get("timestamp") or last.get("date")) or stage_started
        elif pickup_at:
            stage_started = pickup_at
        stage_age = _hours_between(stage_started, now) if stage_started else None

    if "invalid_timestamp_order_delivery_before_created" in data_quality:
        total_hours = None
        booking_to_delivery = None

    transport_status = _transport_status_label(
        tracking.get("status"), has_awb=bool(awb), has_movement=has_movement
    )
    if classification == "delivered":
        transport_status = "Delivered"
    elif classification == "exception":
        transport_status = "Exception"
    # Never surface carrier booking state "complete" as transport status
    booking_state = str(row.get("state") or "")
    if transport_status.lower() in ("complete", "completed") or (
        not tracking.get("status") and booking_state == "complete" and classification != "delivered"
    ):
        transport_status = "Pickup pending" if awb and not has_movement else transport_status

    business_workflow_status = None
    if classification == "delivered":
        if conf.get("customer_response") == "received":
            business_workflow_status = "customer_confirmed"
        elif conf.get("estrella_delivery_confirmation"):
            business_workflow_status = "confirmation_sent"
        else:
            business_workflow_status = "delivered"

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
        ts = _parse_iso(ev.get("event_time") or ev.get("timestamp") or ev.get("date"))
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
            "authority": tracking.get("source") or "tracking_cache",
            "location": ev.get("location"),
        })
        prev = ts

    attention: List[str] = []
    if tracking.get("exception"):
        attention.append("carrier_exception")
    if classification == "active" and not has_movement and created_at:
        age = _hours_between(created_at, now)
        if age is not None and age >= NO_MOVEMENT_ATTENTION_HOURS:
            attention.append("no_carrier_movement_12h")
    last_blob = " ".join(
        str(x or "") for x in (tracking.get("status"), tracking.get("last_event"))
    ).upper()
    if any(k in last_blob for k in ("READY FOR COLLECTION", "MISSED", "ATTEMPTED", "COLLECTION")):
        attention.append("missed_delivery_or_ready_for_collection")
    eta = tracking.get("expected_delivery")
    if (
        classification == "active"
        and isinstance(eta, datetime)
        and eta < now
    ):
        attention.append("expected_delivery_passed")

    if not tracking.get("events") and not tracking.get("status"):
        data_quality.append("tracking_evidence_missing")
    if not client:
        data_quality.append("missing_party_identity")

    first_movement = pickup_at or departed_at
    if events and first_movement is None:
        for ev in events:
            ts = _parse_iso(ev.get("event_time") or ev.get("timestamp") or ev.get("date"))
            if ts:
                first_movement = ts
                break

    return {
        "direction": "outbound",
        "classification": classification,
        "transport_status": transport_status,
        "customs_status": None,
        "customs_complete": False,
        "business_workflow_status": business_workflow_status,
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
            eta.isoformat() if isinstance(eta, datetime) else None
        ),
        "expected_delivery_warsaw": (
            _to_warsaw_iso(eta) if isinstance(eta, datetime) else None
        ),
        "current_status": transport_status,
        "current_location": tracking.get("last_location"),
        "current_stage": transport_status.lower().replace(" ", "_"),
        "current_stage_label": transport_status,
        "stage_started_at_utc": (
            stage_started.isoformat() if stage_started and classification == "active" else None
        ),
        "stage_started_at_warsaw": _to_warsaw_iso(stage_started) if classification == "active" else None,
        "stage_age_hours": stage_age,
        "stage_age_human": _fmt_duration(stage_age),
        "total_elapsed_hours": total_hours,
        "total_elapsed_human": _fmt_duration(total_hours),
        "booking_age_hours": booking_age_hours,
        "booking_age_human": _fmt_duration(booking_age_hours),
        "booking_to_delivery_hours": booking_to_delivery,
        "booking_to_delivery_human": _fmt_duration(booking_to_delivery),
        "pickup_is_authoritative": pickup_at is not None,
        "first_movement_at_utc": first_movement.isoformat() if isinstance(first_movement, datetime) else None,
        "departed_at_utc": departed_at.isoformat() if isinstance(departed_at, datetime) else None,
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
        "booking_state": booking_state,
        "data_gaps": [
            "mydhl_shipmentNotification_request_not_persisted",
            "estimated_delivery_not_in_tracking_service",
            "received_by_pod_signatory_not_parsed",
        ],
        "data_quality": data_quality,
        "tracking_source": tracking.get("source"),
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
    if not clean:
        return {
            "n": 0,
            "average": None,
            "average_human": None,
            "median": None,
            "median_human": None,
            "typical_human": None,
            "p90": None,
            "p90_human": None,
            "sufficient": False,
        }
    avg = round(statistics.mean(clean), 2)
    med = round(statistics.median(clean), 2) if len(clean) >= 3 else None
    p90 = _percentile(clean, 90)
    return {
        "n": len(clean),
        "average": avg,
        "average_human": _fmt_duration(avg),
        "median": med,
        "median_human": _fmt_duration(med),
        "typical_human": _fmt_duration(med if med is not None else avg),
        "p90": p90,
        "p90_human": _fmt_duration(p90),
        "sufficient": len(clean) >= 3,
    }


def _milestone_ts(row: Dict[str, Any], stage_id: str) -> Optional[datetime]:
    for m in row.get("milestones") or []:
        if str(m.get("stage_id") or "") == stage_id:
            return _parse_iso(m.get("timestamp_utc"))
    return None


# Fixed transition pairs — both endpoints must exist with valid chronology.
_INBOUND_FIXED_TRANSITIONS: Tuple[Tuple[str, str, str], ...] = (
    ("origin_pickup_to_poland", "Origin pickup → Poland arrival", "pickup|arrived_pl"),
    ("poland_to_dhl_email", "Poland arrival → DHL email", "arrived_pl|dhl_email"),
    ("dhl_email_to_dsk", "DHL email → DSK", "dhl_email|dsk"),
    ("dsk_to_agency_sad", "DSK → Agency/SAD", "dsk|sad"),
    ("sad_to_customs_cleared", "SAD → Customs cleared", "sad|customs_cleared"),
    ("customs_cleared_to_pz", "Customs cleared → PZ", "customs_cleared|pz"),
    ("origin_pickup_to_delivered", "Origin pickup → Delivered", "pickup|delivered"),
)

_OUTBOUND_FIXED_TRANSITIONS: Tuple[Tuple[str, str, str], ...] = (
    ("booking_to_first_movement", "Booking → first carrier movement", "booked|first_movement"),
    ("pickup_to_delivery", "Pickup → delivery", "pickup|delivered"),
    ("departure_to_delivery", "Departure → delivery", "departed|delivered"),
)


def _row_timestamp_map(row: Dict[str, Any]) -> Dict[str, Optional[datetime]]:
    """Exact named timestamps for fixed transitions (no predecessor mixing)."""
    pickup = _parse_iso(row.get("pickup_at_utc"))
    delivered = _parse_iso(row.get("delivered_at_utc"))
    created = _parse_iso(row.get("created_at_utc"))
    departed = _parse_iso(row.get("departed_at_utc"))
    first_movement = _parse_iso(row.get("first_movement_at_utc")) or pickup or departed
    return {
        "pickup": pickup,
        "delivered": delivered,
        "booked": created,
        "first_movement": first_movement,
        "departed": departed,
        "arrived_pl": _milestone_ts(row, "arrived_pl"),
        "dhl_email": _milestone_ts(row, "dhl_email"),
        "dsk": _milestone_ts(row, "dsk") or _milestone_ts(row, "dsk_received"),
        "sad": _milestone_ts(row, "sad") or _milestone_ts(row, "agency"),
        "customs_cleared": _milestone_ts(row, "customs_cleared"),
        "pz": _milestone_ts(row, "pz"),
    }


def _fixed_transition_analytics(
    rows: List[Dict[str, Any]],
    specs: Tuple[Tuple[str, str, str], ...],
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, label, pair in specs:
        start_key, end_key = pair.split("|", 1)
        samples: List[float] = []
        for r in rows:
            tsmap = _row_timestamp_map(r)
            a = tsmap.get(start_key)
            b = tsmap.get(end_key)
            hours = _hours_between(a, b)
            if hours is None:
                continue
            samples.append(hours)
        stats = _cohort_stats(samples)
        out[key] = {
            "id": key,
            "label": label,
            "start_key": start_key,
            "end_key": end_key,
            **stats,
        }
    return out


def _apply_manual_resolution(
    row: Dict[str, Any],
    resolution: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Overlay admin reporting resolution. Never invents DHL Delivered evidence.

    Precedence: canonical DHL Delivered > active manual resolution > normal projection.
    """
    row["manual_resolution"] = None
    row["manual_resolution_badge"] = None
    row["manual_resolution_superseded_by_dhl"] = False
    row["operator_confirmed_duration_hours"] = None
    row["operator_confirmed_duration_human"] = None
    if not resolution or not resolution.get("active"):
        return row

    snap = {
        "resolution_status": resolution.get("resolution_status"),
        "resolved_at": resolution.get("resolved_at"),
        "resolved_by": resolution.get("resolved_by"),
        "comment": resolution.get("comment"),
        "manual_delivered_at": resolution.get("manual_delivered_at"),
        "manual_location": resolution.get("manual_location"),
        "active": True,
    }
    row["manual_resolution"] = snap

    # Canonical DHL Delivered always wins for classification / Delivered badge.
    if row.get("classification") == "delivered":
        row["manual_resolution_superseded_by_dhl"] = True
        row["manual_resolution_badge"] = "Manually resolved (DHL evidence now present)"
        return row

    status = str(resolution.get("resolution_status") or "")
    row["manual_resolution_badge"] = "Manually resolved"
    row["needs_attention"] = False
    row["attention_reasons"] = []

    if status == "historical_delivered":
        row["classification"] = "manually_resolved_delivered"
        # Keep transport_status as carrier truth; do not show plain "Delivered".
        row["current_status"] = "Manually resolved"
        row["current_stage_label"] = "Manually resolved"
        row["reporting_status"] = "Manually resolved — historical delivery confirmed"
        man_del = _parse_iso(resolution.get("manual_delivered_at"))
        created = _parse_iso(row.get("created_at_utc"))
        if man_del and created:
            hours = _hours_between(created, man_del)
            row["operator_confirmed_duration_hours"] = hours
            row["operator_confirmed_duration_human"] = _fmt_duration(hours)
        if resolution.get("manual_location"):
            row["current_location"] = resolution.get("manual_location")
    elif status == "closed_no_longer_operational":
        row["classification"] = "manually_resolved_closed"
        row["current_status"] = "Manually resolved"
        row["current_stage_label"] = "Manually resolved"
        row["reporting_status"] = "Manually resolved — closed / no longer operational"
    return row


def _load_resolution_map() -> Dict[Tuple[str, str], Dict[str, Any]]:
    try:
        from . import dhl_logistics_resolution_db as resdb
        out: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for r in resdb.list_active_resolutions():
            key = (str(r.get("direction") or ""), str(r.get("awb") or ""))
            out[key] = r
        return out
    except Exception as exc:
        log.warning("logistics_projector: resolution load failed: %s", exc)
        return {}


def _collect_transit_hours(rows: List[Dict[str, Any]]) -> Tuple[List[float], List[Dict[str, Any]]]:
    """Valid pickup→delivered (or authoritative total) samples + DQ exclusions.

    Manual/operator-confirmed durations are excluded from canonical DHL averages.
    """
    valid: List[float] = []
    excluded: List[Dict[str, Any]] = []
    for r in rows:
        # Operator-confirmed / non-DHL paths never enter canonical averages.
        if r.get("classification") == "manually_resolved_delivered":
            excluded.append({
                "awb": r.get("awb"),
                "reason": "manual_resolution_excluded_from_dhl_averages",
                "direction": r.get("direction"),
            })
            continue
        if r.get("classification") != "delivered":
            continue
        dq = list(r.get("data_quality") or [])
        delivered = _parse_iso(r.get("delivered_at_utc"))
        pickup = _parse_iso(r.get("pickup_at_utc"))
        created = _parse_iso(r.get("created_at_utc"))
        total = r.get("total_elapsed_hours")
        start = pickup
        # Inbound may lack pickup — allow first movement / arrived_pl as transport start
        if start is None and r.get("direction") == "inbound":
            start = _milestone_ts(r, "arrived_pl") or _parse_iso(r.get("first_movement_at_utc"))
        if delivered is None:
            excluded.append({"awb": r.get("awb"), "reason": "delivered_without_timestamp", "direction": r.get("direction")})
            continue
        if start is None:
            excluded.append({"awb": r.get("awb"), "reason": "missing_transport_start", "direction": r.get("direction")})
            continue
        hours = _hours_between(start, delivered)
        if hours is None:
            excluded.append({
                "awb": r.get("awb"),
                "reason": "invalid_chronology_or_negative",
                "direction": r.get("direction"),
                "data_quality": dq,
            })
            continue
        if created and delivered < created:
            excluded.append({
                "awb": r.get("awb"),
                "reason": "delivery_before_created",
                "direction": r.get("direction"),
            })
            continue
        # Prefer row total when it already encodes pickup→delivered; else use computed
        if isinstance(total, (int, float)) and total >= 0:
            valid.append(float(total))
        else:
            valid.append(hours)
    return valid, excluded


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
    resolution_map = _load_resolution_map()

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
        key = (row.get("direction") or "", row.get("awb") or "")
        inbound_rows.append(_apply_manual_resolution(row, resolution_map.get(key)))

    try:
        from .carrier.persistence import shipment_db as csdb
        for crow in csdb.list_tracked_shipments(_carrier_db_path()):
            row = project_outbound_row(crow, now=now)
            key = (row.get("direction") or "", row.get("awb") or "")
            outbound_rows.append(_apply_manual_resolution(row, resolution_map.get(key)))
    except Exception as exc:
        log.warning("logistics_projector: outbound list failed: %s", exc)

    all_rows = inbound_rows + outbound_rows

    active_in = [r for r in inbound_rows if r["classification"] == "active"]
    active_out = [r for r in outbound_rows if r["classification"] == "active"]
    historical = [r for r in all_rows if r["classification"] == "historical_unresolved"]
    resolved_closed = [r for r in all_rows if r["classification"] == "manually_resolved_closed"]
    manually_delivered = [r for r in all_rows if r["classification"] == "manually_resolved_delivered"]
    # Operational attention only (excludes historical residue + manual resolutions)
    attention = [
        r for r in all_rows
        if r.get("needs_attention") and r["classification"] in ("active", "exception")
    ]
    delivered_today = []
    today_w = now.astimezone(POLAND_TZ).date()
    for r in all_rows:
        if r["classification"] != "delivered":
            continue
        dts = _parse_iso(r.get("delivered_at_utc"))
        if dts and dts.astimezone(POLAND_TZ).date() == today_w:
            delivered_today.append(r)

    in_hours, in_excluded = _collect_transit_hours(inbound_rows)
    out_hours, out_excluded = _collect_transit_hours(outbound_rows)
    in_stats = _cohort_stats(in_hours)
    out_stats = _cohort_stats(out_hours)

    data_quality_summary = {
        "tracking_evidence_missing": 0,
        "invalid_timestamp_order": 0,
        "delivered_without_timestamp": 0,
        "missing_party_identity": 0,
    }
    for r in all_rows:
        for flag in r.get("data_quality") or []:
            if flag == "tracking_evidence_missing":
                data_quality_summary["tracking_evidence_missing"] += 1
            elif "invalid_timestamp_order" in flag or flag == "delivery_before_created":
                data_quality_summary["invalid_timestamp_order"] += 1
            elif flag == "delivered_without_timestamp":
                data_quality_summary["delivered_without_timestamp"] += 1
            elif flag == "missing_party_identity":
                data_quality_summary["missing_party_identity"] += 1

    direction = (direction or "all").lower()
    view = (view or "active").lower()
    rows = list(all_rows)
    if direction == "inbound":
        rows = [r for r in rows if r["direction"] == "inbound"]
    elif direction == "outbound":
        rows = [r for r in rows if r["direction"] == "outbound"]

    if view == "active":
        # Operational active + live exceptions — residue + manual resolutions excluded
        rows = [r for r in rows if r["classification"] in ("active", "exception")]
    elif view == "delivered":
        # DHL Delivered + admin historical-delivery confirmation (badge differs)
        rows = [
            r for r in rows
            if r["classification"] in ("delivered", "manually_resolved_delivered")
        ]
    elif view == "attention":
        rows = [r for r in rows if r.get("needs_attention") and r["classification"] in ("active", "exception")]
    elif view in ("historical", "unresolved", "historical_unresolved"):
        rows = [r for r in rows if r["classification"] == "historical_unresolved"]
    elif view in ("resolved", "resolved_history"):
        rows = [r for r in rows if r["classification"] == "manually_resolved_closed"]

    if needs_attention_only:
        rows = [r for r in rows if r.get("needs_attention") and r["classification"] in ("active", "exception")]

    if stage:
        stage_l = stage.lower()
        rows = [
            r for r in rows
            if stage_l in str(r.get("current_stage") or "").lower()
            or stage_l in str(r.get("current_stage_label") or "").lower()
            or stage_l in str(r.get("transport_status") or "").lower()
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

    # Default: newest operational shipment first (created_at DESC).
    # Needs Attention uses the same newest-created rule so 100d rows do not pin the top.
    def _sort_key(r: Dict[str, Any]):
        created = r.get("created_at_utc") or ""
        return (0 if created else 1, created)

    rows.sort(key=_sort_key, reverse=True)

    orch_active_count = sum(1 for r in inbound_rows if r.get("orch_active"))
    customs_complete_still_active = sum(
        1 for r in inbound_rows
        if r.get("customs_complete") and r["classification"] == "active"
    )

    analytics = {
        "inbound_transit_hours": in_stats,
        "outbound_transit_hours": out_stats,
        "fixed_transitions_inbound": _fixed_transition_analytics(inbound_rows, _INBOUND_FIXED_TRANSITIONS),
        "fixed_transitions_outbound": _fixed_transition_analytics(outbound_rows, _OUTBOUND_FIXED_TRANSITIONS),
        "data_quality_excluded": {
            "inbound_transit": in_excluded,
            "outbound_transit": out_excluded,
            "counts": {
                "inbound": len(in_excluded),
                "outbound": len(out_excluded),
            },
        },
        "data_quality_summary": data_quality_summary,
        "population_notes": {
            "active_inbound": "operational transport-active (excludes historical_unresolved residue)",
            "active_outbound": "carrier AWB present, tracking not Delivered; booking state=complete is NOT delivered",
            "historical_unresolved": (
                "customs/PZ complete + no physical movement + no Delivered evidence "
                f"+ created age ≥ {HISTORICAL_UNRESOLVED_HOURS / 24.0:.0f}d — audit/reporting only"
            ),
            "avg_inbound_transit": "only physically delivered with valid start→delivered chronology",
            "avg_outbound_transit": "only physically delivered with authoritative pickup→delivered",
            "customs_complete_still_active": customs_complete_still_active,
        },
    }

    operational_active = len(active_in) + len(active_out)
    # Include live exceptions in operational active KPI (still need operator eyes)
    operational_exceptions = sum(1 for r in all_rows if r["classification"] == "exception")
    kpis = {
        "operational_active": operational_active + operational_exceptions,
        "active_inbound": len(active_in),
        "active_outbound": len(active_out),
        "operational_exceptions": operational_exceptions,
        "historical_unresolved": len(historical),
        "resolved_history": len(resolved_closed),
        "manually_resolved_delivered": len(manually_delivered),
        "needs_attention": len(attention),
        "delivered_today": len(delivered_today),
        "avg_inbound_transit_hours": in_stats.get("average"),
        "avg_inbound_transit_human": in_stats.get("average_human"),
        "avg_outbound_transit_hours": out_stats.get("average"),
        "avg_outbound_transit_human": out_stats.get("average_human"),
        "inbound_transit_median_hours": in_stats.get("median"),
        "outbound_transit_median_hours": out_stats.get("median"),
        "inbound_transit_n": in_stats.get("n"),
        "outbound_transit_n": out_stats.get("n"),
        "orch_active_inbound": orch_active_count,
        "customs_complete_still_active": customs_complete_still_active,
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
            "inbound": "audit.timeline + tracking_cache + tracking_db (read-only)",
            "outbound": "carrier_shipments + tracking_cache (canonical) + delivery_confirmation",
            "tracking": "select_cached_tracking_record / tracking_cache.json — no live MyDHL poll",
            "projection_reads_only": True,
            "manual_resolution_authority": "dhl_logistics_resolutions.db (reporting only)",
            "no_second_poller": True,
            "manual_resolution_never_rewrites_tracking": True,
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
            row = project_outbound_row(crow)
            key = (row.get("direction") or "", row.get("awb") or "")
            return _apply_manual_resolution(row, _load_resolution_map().get(key))
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
        row = project_inbound_row(audit)
        if row is None:
            return None
        key = (row.get("direction") or "", row.get("awb") or "")
        return _apply_manual_resolution(row, _load_resolution_map().get(key))
    return None


LOGISTICS_CSV_COLUMNS = [
    "direction", "party", "awb", "created_at_warsaw", "pickup_at_warsaw",
    "transport_status", "customs_status", "current_location",
    "stage_age_hours", "total_elapsed_hours", "booking_to_delivery_hours",
    "expected_delivery_warsaw", "delivered_at_warsaw", "exception",
    "classification", "needs_attention", "attention_reasons",
    "batch_id", "booking_state", "data_quality",
]


def rows_to_logistics_csv(rows: List[Dict[str, Any]], filters: Optional[Dict[str, Any]] = None) -> bytes:
    from . import master_csv
    slim = []
    for r in rows:
        item = {c: r.get(c) for c in LOGISTICS_CSV_COLUMNS}
        if isinstance(item.get("attention_reasons"), list):
            item["attention_reasons"] = "|".join(str(x) for x in item["attention_reasons"])
        if isinstance(item.get("data_quality"), list):
            item["data_quality"] = "|".join(str(x) for x in item["data_quality"])
        slim.append(item)
    body = master_csv.rows_to_csv(slim, LOGISTICS_CSV_COLUMNS)
    # Prepend filter provenance so export parity with UI is auditable
    if filters:
        filt_line = "# filters_applied: " + "; ".join(f"{k}={v}" for k, v in filters.items()) + "\r\n"
        return filt_line.encode("utf-8") + body
    return body
