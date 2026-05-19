"""
tracking_service.py — Live DHL / FedEx shipment tracking.

Responsibilities:
- Call DHL or FedEx API to fetch current tracking status
- Cache results per tracking number in tracking_cache.json inside the batch folder
- Never recompute landed cost — pure status/location data only

DHL API gate:
- When dhl_tracking_api_status != "active", ALL DHL API calls are hard-blocked.
- The fallback is returned immediately — no HTTP request is attempted.
- TODO: When DHL approves the API app, set DHL_TRACKING_API_STATUS=active in .env.
"""
from __future__ import annotations

import json
import logging
import os as _os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from ..core.config import settings

log = logging.getLogger(__name__)

# ── Status colour map (exported for templates) ────────────────────────────────

STATUS_COLORS: Dict[str, str] = {
    "delivered":        "#16a34a",
    "in_transit":       "#2563eb",
    "out_for_delivery": "#d97706",
    "exception":        "#dc2626",
    "unknown":          "#6b7280",
}

# ── Terminal status set ───────────────────────────────────────────────────────
# Once a shipment hits one of these statuses, no further DHL/FedEx API calls
# are made — the cached result is the source of truth.
# Protects the 250 calls/day DHL quota.

TERMINAL_STATUSES: frozenset = frozenset({
    "delivered",
    "returned",
    "cancelled",
})


def _delivery_proof_present(cache_dir: Optional[Path]) -> bool:
    """
    True if a delivery-proof PDF exists in the batch folder.

    Looks for any file named POD*.pdf, DELIVERY_PROOF*.pdf, or PROOF_OF_DELIVERY*.pdf
    in cache_dir or its parent (batch root).
    """
    if cache_dir is None:
        return False
    candidates = [cache_dir, cache_dir.parent] if cache_dir != cache_dir.parent else [cache_dir]
    patterns = ["POD*.pdf", "DELIVERY_PROOF*.pdf", "PROOF_OF_DELIVERY*.pdf"]
    for d in candidates:
        try:
            for pat in patterns:
                if any(d.glob(pat)):
                    return True
        except Exception:
            continue
    return False

# ── DHL status mapping ────────────────────────────────────────────────────────

_DHL_STATUS_MAP: Dict[str, tuple[str, str]] = {
    "delivered":        ("delivered",        "Delivered"),
    "in-transit":       ("in_transit",       "In Transit"),
    "out-for-delivery": ("out_for_delivery", "Out for Delivery"),
    "failure":          ("exception",        "Exception"),
    "exception":        ("exception",        "Exception"),
}

# Event-description keyword priority for derived status. The HIGHEST priority
# matched description across the full event stream wins — so a "Delivered"
# event anywhere overrides a later "still in transit" summary.
# Order matters: most-final state first.
_DHL_EVENT_PRIORITY: list[tuple[str, str, str]] = [
    # (lower-cased substring, status_key, status_label)
    ("delivered",                      "delivered",        "Delivered"),
    ("with delivery courier",          "out_for_delivery", "Out for Delivery"),
    ("out for delivery",               "out_for_delivery", "Out for Delivery"),
    ("delivery in progress",           "out_for_delivery", "Out for Delivery"),
    ("clearance processing complete",  "cleared",          "Cleared"),
    ("customs status updated",         "cleared",          "Cleared"),
    ("released by customs",            "cleared",          "Cleared"),
    ("on hold",                        "on_hold",          "On Hold"),
    ("clearance event",                "in_customs",       "In Customs"),
    ("customs",                        "in_customs",       "In Customs"),
    ("arrived at destination",         "at_destination",   "At Destination"),
    ("departed",                       "in_transit",       "In Transit"),
    ("in transit",                     "in_transit",       "In Transit"),
    ("processed at",                   "in_transit",       "In Transit"),
    ("picked up",                      "picked_up",        "Picked Up"),
]


def _derive_status_from_events(events: list[dict]) -> tuple[str, str]:
    """
    Derive a status (key, label) from the full DHL event stream by description
    priority — final states (Delivered) outrank earlier ones (In Transit).

    Each event dict should have a 'description' (or 'status') field.
    Returns ("in_transit", "In Transit") as a safe default.
    """
    if not events:
        return ("in_transit", "In Transit")
    # Concat every event's description+status into one searchable lower-case blob
    descs = []
    for ev in events:
        for k in ("description", "status", "statusCode"):
            v = ev.get(k)
            if isinstance(v, str) and v.strip():
                descs.append(v.lower())
    blob = " | ".join(descs)
    if not blob:
        return ("in_transit", "In Transit")
    for kw, key, label in _DHL_EVENT_PRIORITY:
        if kw in blob:
            return (key, label)
    return ("in_transit", "In Transit")


def _normalise_dhl_events(raw_events: list[dict]) -> list[dict]:
    """
    Convert DHL's raw events into a flat, sorted-ASC list with consistent fields.

    Output shape per event:
      {timestamp, location, status, description}
    """
    out: list[dict] = []
    for ev in raw_events or []:
        addr = (ev.get("location") or {}).get("address") or {}
        city = addr.get("addressLocality") or ""
        cc   = addr.get("countryCode") or ""
        loc  = f"{city.upper()} - {cc.upper()}" if city and cc else (city.upper() or cc.upper())
        out.append({
            "timestamp":   ev.get("timestamp", ""),
            "location":    loc,
            "status":      ev.get("status", "") or ev.get("statusCode", ""),
            "description": ev.get("description", ""),
        })
    # DHL returns newest-first; sort ASC for chronological reading
    out.sort(key=lambda e: e.get("timestamp") or "")
    return out

# ── FedEx status mapping ──────────────────────────────────────────────────────

_FEDEX_STATUS_MAP: Dict[str, tuple[str, str]] = {
    "DL":               ("delivered",        "Delivered"),
    "Delivered":        ("delivered",        "Delivered"),
    "IT":               ("in_transit",       "In Transit"),
    "In transit":       ("in_transit",       "In Transit"),
    "OD":               ("out_for_delivery", "Out for Delivery"),
    "On FedEx vehicle": ("out_for_delivery", "Out for Delivery"),
    "DE":               ("exception",        "Exception"),
}


# ── Security helpers ──────────────────────────────────────────────────────────

def _mask(value: Optional[str]) -> str:
    """Mask a credential for safe logging: show first 4 chars only."""
    if not value:
        return "<not set>"
    return value[:4] + "****"


# ── Date formatting ───────────────────────────────────────────────────────────

def format_last_update(dt_str: Optional[str]) -> str:
    """
    Parse an ISO 8601 datetime string and return a human-readable label.
    Example output: 'Wednesday, 25 February 2026 at 14:41 (UTC +01:00)'
    Uses only stdlib. Handles both offset-aware and offset-naive datetimes.
    """
    if not dt_str:
        return ""
    try:
        s = dt_str.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)

        day_name  = dt.strftime("%A")
        date_part = dt.strftime("%-d %B %Y")
        time_part = dt.strftime("%H:%M")

        if dt.tzinfo is not None:
            offset_secs = int(dt.utcoffset().total_seconds())  # type: ignore[union-attr]
            sign        = "+" if offset_secs >= 0 else "-"
            abs_secs    = abs(offset_secs)
            h, m        = divmod(abs_secs // 60, 60)
            tz_label    = f"UTC {sign}{h:02d}:{m:02d}"
        else:
            tz_label = "UTC"

        return f"{day_name}, {date_part} at {time_part} ({tz_label})"
    except Exception:
        return dt_str


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _load_cache(cache_dir: Path) -> Dict[str, Any]:
    cache_file = cache_dir / "tracking_cache.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache_dir: Path, cache: Dict[str, Any]) -> None:
    """Atomic write via tmp-then-rename to prevent corrupt cache on crash/kill."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "tracking_cache.json"
    tmp_file   = cache_dir / "tracking_cache.json.tmp"
    tmp_file.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    _os.replace(str(tmp_file), str(cache_file))


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── DHL tracking URL ──────────────────────────────────────────────────────────

def _dhl_tracking_url(tracking_no: str) -> str:
    return (
        f"https://www.dhl.com/pl-en/home/tracking/tracking-express.html"
        f"?tracking-id={tracking_no}"
    )


# ── Email-inferred arrival helper ────────────────────────────────────────────

def _infer_from_audit(cache_dir: Path) -> Dict[str, Any]:
    """
    Read the batch's audit.json (if cache_dir is inside a batch folder) and
    extract email-inferred timestamps from the timeline and clearance fields.

    Returns a dict with optional fields:
      arrival_poland       — inferred from cesja_received or dhl_email_received ts
      customs_started      — inferred from cesja_received ts
      customs_completed    — inferred from zc429_received or pzc_received ts
      shipment_released    — inferred from ganther_pzc_sent ts
      duty_notice_at       — inferred from duty_note_received ts
      payment_confirmed_at — inferred from payment_confirmed ts
      inferred_status      — "cleared" | "released" | "duty_paid" | "customs" | "transit"

    All timestamps are ISO strings. Fields are omitted if not available.
    No API calls are made.
    """
    # cache_dir is typically batch_dir/ — audit.json is one level up or same level
    candidates = [
        cache_dir / "audit.json",
        cache_dir.parent / "audit.json",
    ]
    audit: Dict[str, Any] = {}
    for p in candidates:
        if p.exists():
            try:
                audit = json.loads(p.read_text(encoding="utf-8"))
                break
            except Exception:
                pass

    if not audit:
        return {}

    # Map timeline events to inferred timestamps
    timeline = audit.get("timeline") or []
    ts_map: Dict[str, str] = {}
    for ev in timeline:
        evt = ev.get("event", "")
        ts  = ev.get("ts", "")
        if evt and ts and evt not in ts_map:        # keep first occurrence
            ts_map[evt] = ts

    result: Dict[str, Any] = {}

    # Arrival at Poland customs warehouse ← cesja or DHL email
    for sig in ("cesja_received", "dhl_email_received", "dhl_precheck_completed"):
        if sig in ts_map:
            result["arrival_poland"]  = ts_map[sig]
            result["customs_started"] = ts_map[sig]
            break

    # Customs cleared ← ZC429 or PZC
    for sig in ("zc429_received", "pzc_received"):
        if sig in ts_map:
            result["customs_completed"] = ts_map[sig]
            break

    # Shipment released by Ganther
    if "ganther_pzc_sent" in ts_map:
        result["shipment_released"] = ts_map["ganther_pzc_sent"]

    # Duty
    if "duty_note_received" in ts_map:
        result["duty_notice_at"] = ts_map["duty_note_received"]
        # Also pick up duty PLN amount if stored in audit
        duty_pln = audit.get("duty_amount_pln")
        if duty_pln:
            result["duty_amount_pln"] = duty_pln

    if "payment_confirmed" in ts_map:
        result["payment_confirmed_at"] = ts_map["payment_confirmed"]

    # Derive inferred_status (highest milestone reached)
    if "payment_confirmed" in ts_map:
        result["inferred_status"] = "duty_paid"
    elif "ganther_pzc_sent" in ts_map:
        result["inferred_status"] = "released"
    elif "zc429_received" in ts_map or "pzc_received" in ts_map:
        result["inferred_status"] = "cleared"
    elif "cesja_received" in ts_map or "dhl_email_received" in ts_map:
        result["inferred_status"] = "customs"
    else:
        result["inferred_status"] = "transit"

    return result


# ── DHL pending fallback ──────────────────────────────────────────────────────

def _resolve_dhl_credentials() -> tuple:
    """Return (api_key, api_secret) treating canonical + alias env names equally.

    Canonical: DHL_TRACKING_API_KEY / DHL_TRACKING_API_SECRET (Settings fields).
    Aliases:   DHL_CLIENT_ID / DHL_CLIENT_SECRET (read directly from os.environ
               so existing operator .env files using OAuth-style names work
               without renaming).
    Legacy:    DHL_API_KEY (single legacy header credential).

    No values are returned to callers — only used internally to compute mode.
    """
    import os
    canonical_key = (settings.dhl_tracking_api_key or "").strip()
    canonical_sec = (settings.dhl_tracking_api_secret or "").strip()
    alias_key     = (os.environ.get("DHL_CLIENT_ID")     or "").strip()
    alias_sec     = (os.environ.get("DHL_CLIENT_SECRET") or "").strip()
    legacy_key    = (settings.dhl_api_key or "").strip()
    api_key    = canonical_key or alias_key or legacy_key
    api_secret = canonical_sec or alias_sec
    return api_key, api_secret


def get_tracking_mode() -> str:
    """Return the canonical DHL tracking mode for the dashboard.

    Modes:
        ``disabled`` — credentials missing AND/OR status not "active".
        ``failed``   — last live call errored (status was active but request raised).
        ``active``   — credentials present + status flagged active.

    Credential aliases supported:
        DHL_TRACKING_API_KEY / DHL_TRACKING_API_SECRET   (canonical)
        DHL_CLIENT_ID / DHL_CLIENT_SECRET                (OAuth-style alias)
        DHL_API_KEY                                       (legacy header-only)

    The function reads only ``settings`` + ``os.environ`` (no I/O) so the
    dashboard can call it on every render without rate concerns.
    """
    status = (settings.dhl_tracking_api_status or "").strip().lower()
    api_key, _ = _resolve_dhl_credentials()
    if not api_key or status == "disabled":
        return "disabled"
    if status == "failed":
        return "failed"
    if status == "active":
        return "active"
    # Anything else (e.g. legacy "pending") is treated as disabled.
    return "disabled"


def _dhl_pending_fallback(tracking_no: str, cache_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Standard fallback returned whenever dhl_tracking_api_status != 'active'.
    No HTTP request is made. Shape is fixed so the UI can render deterministically.

    When cache_dir is provided (batch folder), enriches the response with
    email-inferred timestamps from the batch audit.json timeline — so the
    dashboard can show real progress even without the DHL API.

    Sets cowork_tracking_required=True so cowork_coordinator can create a
    public_tracking_lookup suggestion task for operator or Cowork agent.
    """
    inferred: Dict[str, Any] = {}
    if cache_dir is not None:
        try:
            inferred = _infer_from_audit(cache_dir)
        except Exception:
            pass   # always non-fatal

    # Derive a better status label if we have inferred data
    _inferred_status = inferred.get("inferred_status", "transit")
    _status_label_map = {
        "duty_paid": "Duty Paid",
        "released":  "Released by Forwarder",
        "cleared":   "Customs Cleared",
        "customs":   "In Customs",
        "transit":   "In Transit",
    }
    _mode = get_tracking_mode()        # 'disabled' | 'failed' | 'active'
    _source = "email_inferred" if inferred else f"api_{_mode}"
    _reason_map = {
        "disabled": "DHL API disabled — no credentials. Use fallback / manual.",
        "failed":   "DHL API failed — retry or use manual.",
        "active":   "DHL API active.",
    }

    return {
        "tracking_no":   tracking_no,
        "carrier":       "DHL",
        "provider":      "dhl_unified_tracking",
        "available":     False,
        "api_status":    _mode,
        "reason":        _reason_map.get(_mode, "DHL API unavailable."),
        "status":        _inferred_status if inferred else "unknown",
        "status_label":  _status_label_map.get(_inferred_status, "Pending"),
        "last_update":   inferred.get("customs_completed") or inferred.get("arrival_poland"),
        "last_location": "Warsaw Customs (inferred)" if inferred else None,
        "origin":        "",
        "destination":   "Warsaw, PL",
        "tracking_url":  _dhl_tracking_url(tracking_no),
        "source":        _source,
        "cached_at":     None,
        "error":         None,
        # ── Cowork fallback task signal ──────────────────────────────────────
        # When True, cowork_coordinator should create a PUBLIC_TRACKING_LOOKUP_REQUIRED
        # suggestion so the operator or a browser-capable Cowork agent can check the
        # public DHL tracking page and report the result via POST /api/v1/tracking/{awb}/cowork-result.
        "cowork_tracking_required": True,
        "cowork_tracking_reason":   "API pending; public tracking lookup required",
        # Email-inferred milestone timestamps (all optional, absent if not yet reached)
        "email_inferred": inferred if inferred else None,
    }


# ── DHL API callers ───────────────────────────────────────────────────────────

def _call_dhl_legacy(tracking_no: str) -> Dict[str, Any]:
    """Legacy DHL API call using DHL-API-Key header."""
    # Hard block — must never be reached when status != active
    if settings.dhl_tracking_api_status != "active":
        raise RuntimeError(
            f"DHL API call blocked: status={settings.dhl_tracking_api_status}"
        )
    url = f"https://api-eu.dhl.com/track/shipments?trackingNumber={tracking_no}"
    with httpx.Client(timeout=10) as client:
        resp = client.get(url, headers={"DHL-API-Key": settings.dhl_api_key or ""})
        resp.raise_for_status()
        data = resp.json()

    shipment   = data["shipments"][0]
    raw_events = shipment.get("events", []) or []
    events     = _normalise_dhl_events(raw_events)

    status_key, status_label = _derive_status_from_events(raw_events)
    if status_key == "in_transit":
        raw_status = (
            shipment.get("status", {}).get("status", "")
            or shipment.get("status", {}).get("description", "")
        ).lower()
        mapped = _DHL_STATUS_MAP.get(raw_status)
        if mapped:
            status_key, status_label = mapped

    last_event = events[-1] if events else {}

    def _loc(obj: Dict[str, Any]) -> str:
        addr = obj.get("address", {})
        city = addr.get("addressLocality", "")
        cc   = addr.get("countryCode", "")
        return f"{city.upper()} - {cc.upper()}" if city and cc else city.upper() or cc.upper()

    return {
        "status":              status_key,
        "status_label":        status_label,
        "last_update":         last_event.get("timestamp"),
        "last_update_display": format_last_update(last_event.get("timestamp")),
        "last_location":       last_event.get("location") or _loc(shipment.get("destination", {})),
        "origin":              _loc(shipment.get("origin", {})),
        "destination":         _loc(shipment.get("destination", {})),
        "source":              "dhl_api",
        "events":              events,
        "events_count":        len(events),
        "last_event":          last_event,
    }


def _call_dhl_unified(tracking_no: str) -> Dict[str, Any]:
    """
    DHL Shipment Tracking — Unified API (direct API key, no OAuth).

    The DHL Tracking Unified API authenticates via DHL-API-Key header —
    not OAuth2. The API Key from the Developer Portal is used directly.
    DHL_TRACKING_API_KEY = the API key shown in the portal credential.

    Only reached when dhl_tracking_api_status == 'active'.
    """
    # Hard block — defense-in-depth
    if settings.dhl_tracking_api_status != "active":
        raise RuntimeError(
            f"DHL Unified API call blocked: status={settings.dhl_tracking_api_status}"
        )

    log.debug("[DHL] Unified API call — key=%s", _mask(settings.dhl_tracking_api_key))

    with httpx.Client(timeout=12) as client:
        track_resp = client.get(
            f"https://api-eu.dhl.com/track/shipments?trackingNumber={tracking_no}",
            headers={"DHL-API-Key": settings.dhl_tracking_api_key or ""},
        )
        track_resp.raise_for_status()
        data = track_resp.json()

    shipment   = data["shipments"][0]
    raw_events = shipment.get("events", []) or []
    events     = _normalise_dhl_events(raw_events)   # sorted ASC

    # ── Status: derive from event priority FIRST, fall back to summary field ──
    status_key, status_label = _derive_status_from_events(raw_events)
    if status_key == "in_transit":
        # If event scan found nothing definitive, try DHL's own summary field
        raw_status = (
            shipment.get("status", {}).get("status", "")
            or shipment.get("status", {}).get("description", "")
        ).lower()
        mapped = _DHL_STATUS_MAP.get(raw_status)
        if mapped:
            status_key, status_label = mapped

    last_event = events[-1] if events else {}

    def _loc(obj: Dict[str, Any]) -> str:
        addr = obj.get("address", {})
        city = addr.get("addressLocality", "")
        cc   = addr.get("countryCode", "")
        return f"{city.upper()} - {cc.upper()}" if city and cc else city.upper() or cc.upper()

    return {
        "status":              status_key,
        "status_label":        status_label,
        "last_update":         last_event.get("timestamp"),
        "last_update_display": format_last_update(last_event.get("timestamp")),
        "last_location":       last_event.get("location") or _loc(shipment.get("destination", {})),
        "origin":              _loc(shipment.get("origin", {})),
        "destination":         _loc(shipment.get("destination", {})),
        "source":              "dhl_unified_api",
        "events":              events,
        "events_count":        len(events),
        "last_event":          last_event,
    }


def _call_dhl(tracking_no: str) -> Dict[str, Any]:
    """
    Route DHL tracking to the right caller.
    This function is only reached when dhl_tracking_api_status == 'active'.
    Both callers enforce their own hard block as defense-in-depth.
    """
    # Primary gate — must be active to reach this function
    if settings.dhl_tracking_api_status != "active":
        raise RuntimeError(
            f"_call_dhl reached with status={settings.dhl_tracking_api_status} — "
            "this is a bug; pending block should have fired earlier"
        )

    has_unified = (
        settings.dhl_tracking_api_key and settings.dhl_tracking_api_secret
    )
    if has_unified:
        return _call_dhl_unified(tracking_no)
    return _call_dhl_legacy(tracking_no)


# ── FedEx API ─────────────────────────────────────────────────────────────────

def _fedex_tracking_url(tracking_no: str) -> str:
    return f"https://www.fedex.com/en-pl/tracking.html?trknbr={tracking_no}"


def _fedex_pending_fallback(tracking_no: str, cache_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Fallback returned for FedEx when credentials are not configured.
    Mirrors the DHL pending fallback shape so the UI renders consistently.
    """
    inferred: Dict[str, Any] = {}
    if cache_dir is not None:
        try:
            inferred = _infer_from_audit(cache_dir)
        except Exception:
            pass

    _inferred_status = inferred.get("inferred_status", "transit")
    _status_label_map = {
        "duty_paid": "Duty Paid",
        "released":  "Released by Forwarder",
        "cleared":   "Customs Cleared",
        "customs":   "In Customs",
        "transit":   "In Transit",
    }
    _source = "email_inferred" if inferred else "no_credentials"

    return {
        "tracking_no":   tracking_no,
        "carrier":       "FedEx",
        "provider":      "fedex_api",
        "available":     False,
        "api_status":    "no_credentials",
        "reason":        "FedEx API credentials not configured",
        "status":        _inferred_status if inferred else "unknown",
        "status_label":  _status_label_map.get(_inferred_status, "Pending"),
        "last_update":   inferred.get("customs_completed") or inferred.get("arrival_poland"),
        "last_location": "Warsaw Customs (inferred)" if inferred else None,
        "origin":        "",
        "destination":   "Warsaw, PL",
        "tracking_url":  _fedex_tracking_url(tracking_no),
        "source":        _source,
        "cached_at":     None,
        "error":         None,
        "cowork_tracking_required": True,
        "cowork_tracking_reason":   "FedEx API credentials not configured; public tracking lookup required",
        "email_inferred": inferred if inferred else None,
    }


def _call_fedex(tracking_no: str) -> Dict[str, Any]:
    with httpx.Client(timeout=10) as client:
        token_resp = client.post(
            "https://apis.fedex.com/oauth/token",
            content=(
                f"grant_type=client_credentials"
                f"&client_id={settings.fedex_client_id}"
                f"&client_secret={settings.fedex_client_secret}"
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        token_resp.raise_for_status()
        token = token_resp.json()["access_token"]

        track_resp = client.post(
            "https://apis.fedex.com/track/v1/trackingnumbers",
            json={
                "trackingInfo": [
                    {"trackingNumberInfo": {"trackingNumber": tracking_no}}
                ],
                "includeDetailedScans": True,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        track_resp.raise_for_status()
        data = track_resp.json()

    result = data["output"]["completeTrackResults"][0]["trackResults"][0]
    scans  = result.get("scanEvents", [])
    ev0    = scans[0] if scans else {}

    derived = ev0.get("derivedStatus", "")
    status_key, status_label = _FEDEX_STATUS_MAP.get(
        derived, ("in_transit", "In Transit")
    )

    date_str = ev0.get("date", "")
    time_str = ev0.get("time", "")
    last_update = f"{date_str}T{time_str}" if date_str and time_str else (date_str or None)

    loc  = ev0.get("scanLocation", {})
    city = loc.get("city", "")
    cc   = loc.get("countryCode", "")
    last_location = f"{city.upper()} - {cc.upper()}" if city and cc else city.upper() or cc.upper()

    return {
        "status":              status_key,
        "status_label":        status_label,
        "last_update":         last_update,
        "last_update_display": format_last_update(last_update),
        "last_location":       last_location,
        "origin":              "",
        "destination":         "",
        "source":              "fedex_api",
    }


# ── Public entry point ────────────────────────────────────────────────────────

def get_tracking_status(
    tracking_no: str,
    carrier: str,
    cache_dir: Path,
    refresh: bool = False,
) -> Dict[str, Any]:
    """
    Fetch (or return cached) tracking status for a shipment.

    Returns a dict — never raises. All errors are captured as available=False.

    DHL hard block:
      If dhl_tracking_api_status != 'active', the pending fallback is returned
      immediately — before cache lookup, before credential check, before any
      HTTP connection is opened.
    """
    tracking_no = (tracking_no or "").strip()
    carrier     = (carrier or "Unknown").strip()

    if not tracking_no:
        return {
            "tracking_no": tracking_no,
            "carrier":     carrier,
            "available":   False,
            "source":      "no_tracking_number",
            "error":       "No tracking number provided",
            "tracking_url": "",
        }

    # ── HARD BLOCK — DHL API must be active to proceed ────────────────────────
    # This check runs before cache, before credentials, before any I/O.
    # No code path below this point can reach a DHL HTTP call when pending.
    if carrier == "DHL" and settings.dhl_tracking_api_status != "active":
        log.debug(
            "[DHL tracking] hard block — status=%s, returning pending fallback for %s",
            settings.dhl_tracking_api_status,
            tracking_no,
        )
        return _dhl_pending_fallback(tracking_no, cache_dir=cache_dir)

    # ── Derive carrier-specific tracking URL ──────────────────────────────────
    if carrier == "DHL":
        tracking_url = _dhl_tracking_url(tracking_no)
    elif carrier == "FedEx":
        tracking_url = _fedex_tracking_url(tracking_no)
    else:
        tracking_url = ""

    base: Dict[str, Any] = {
        "tracking_no":         tracking_no,
        "carrier":             carrier,
        "status":              "unknown",
        "status_label":        "Open Tracking",
        "last_update":         None,
        "last_update_display": "",
        "last_location":       "",
        "origin":              "",
        "destination":         "",
        "tracking_url":        tracking_url,
        "source":              "no_credentials",
        "api_status":          None,
        "available":           False,
        "cached_at":           None,
        "error":               None,
    }

    # ── Terminal-state short-circuit ──────────────────────────────────────────
    # If the cached entry is "delivered" / "returned" / "cancelled", no further
    # API calls are ever made for this AWB — even when refresh=True. The
    # cached snapshot is the source of truth. Likewise if a delivery-proof
    # PDF exists in the batch folder.
    cache_for_terminal = _load_cache(cache_dir)
    if tracking_no in cache_for_terminal:
        hit = cache_for_terminal[tracking_no]
        if hit.get("status") in TERMINAL_STATUSES:
            log.debug("[tracking] terminal status=%s for %s — skipping API",
                      hit.get("status"), tracking_no)
            hit["source"] = "cache"
            hit["tracking_terminal"] = True
            hit["tracking_terminal_reason"] = f"status_{hit.get('status')}"
            return hit
    if _delivery_proof_present(cache_dir):
        log.debug("[tracking] delivery proof PDF present for %s — skipping API", tracking_no)
        # Build a minimal terminal response from cache (or base)
        result = (cache_for_terminal.get(tracking_no) or {}).copy() or {**base}
        result["status"]                   = "delivered"
        result["status_label"]             = "Delivered"
        result["available"]                = True
        result["tracking_terminal"]        = True
        result["tracking_terminal_reason"] = "delivery_proof_present"
        result["source"]                   = result.get("source") or "delivery_proof"
        result["tracking_url"]             = tracking_url
        return result

    # ── Cache read (only for active API paths) ────────────────────────────────
    _CACHE_TTL = 15 * 60  # 15 minutes — rate limit is 250 calls/day
    if not refresh:
        cache = cache_for_terminal
        if tracking_no in cache:
            hit = cache[tracking_no]
            cached_at = hit.get("cached_at")
            fresh = False
            if cached_at:
                try:
                    age = (
                        datetime.now(timezone.utc)
                        - datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
                    ).total_seconds()
                    fresh = age < _CACHE_TTL
                except Exception:
                    fresh = True  # unparseable timestamp → treat as fresh
            else:
                fresh = True  # no timestamp → treat as fresh (legacy entry)
            if fresh:
                hit["source"] = "cache"
                # Mark terminal=False explicitly so UI knows refresh button OK
                hit["tracking_terminal"] = hit.get("status") in TERMINAL_STATUSES
                return hit
            log.debug("[tracking] cache expired for %s (age %.0fs) — refreshing", tracking_no, age if cached_at else -1)

    # ── Credential check ──────────────────────────────────────────────────────
    if carrier == "FedEx" and (
        not settings.fedex_client_id or not settings.fedex_client_secret
    ):
        return _fedex_pending_fallback(tracking_no, cache_dir=cache_dir)

    if carrier not in ("DHL", "FedEx"):
        base["source"] = "no_credentials"
        return base

    # ── DHL: check at least one credential path is available ─────────────────
    if carrier == "DHL":
        has_unified = bool(settings.dhl_tracking_api_key and settings.dhl_tracking_api_secret)
        has_legacy  = bool(settings.dhl_api_key)
        if not has_unified and not has_legacy:
            base["source"] = "no_credentials"
            return base

    # ── Live API call ─────────────────────────────────────────────────────────
    cached_at = _now_utc_iso()
    try:
        if carrier == "DHL":
            api_result = _call_dhl(tracking_no)
        else:
            api_result = _call_fedex(tracking_no)

        result: Dict[str, Any] = {
            **base,
            **api_result,
            "tracking_url": tracking_url,
            "available":    True,
            "cached_at":    cached_at,
            "error":        None,
        }
        # Flag terminal so UI hides the refresh button and future calls skip
        if result.get("status") in TERMINAL_STATUSES:
            result["tracking_terminal"]        = True
            result["tracking_terminal_reason"] = f"status_{result['status']}"
        else:
            result["tracking_terminal"]        = False
    except Exception as exc:
        exc_str = str(exc)
        # Fix 1: DHL API 404 is non-blocking — shipment may be pre-scan or
        # not yet registered.  Return a specific not_found state that leaves
        # all other batch actions (PZ, customs, email) fully enabled.
        is_404 = ("404" in exc_str) or ("Not Found" in exc_str) or (
            hasattr(exc, "response") and getattr(exc.response, "status_code", 0) == 404
        )
        if is_404 and carrier == "DHL":
            log.info(
                "[tracking] DHL API 404 for %s — non-blocking, returning not_found state",
                tracking_no,
            )
            result = {
                **base,
                "status":       "not_found",
                "status_label": "Not Found",
                "source":       "dhl_api_404",
                "available":    False,
                "cached_at":    cached_at,
                "error":        None,   # not a fatal error — do not surface as error
                "tracking_url": tracking_url,
                "tracking_terminal": False,
                # Dashboard amber notice: public tracking may work
                "not_found_advisory": (
                    "DHL tracking not available (API 404). "
                    "Public DHL tracking may work."
                ),
            }
        else:
            log.warning("[tracking] API call failed for %s/%s: %s", carrier, tracking_no, exc)
            result = {
                **base,
                # Surface the live-call failure as the canonical "failed" mode
                # so the dashboard can render the retry/manual prompt.
                "api_status": "failed",
                "source":    "error",
                "available": False,
                "cached_at": cached_at,
                "error":     exc_str,
            }

    # ── Normalize and persist events to audit.tracking_events ────────────────
    # Best-effort: never fails the response if audit write is unavailable.
    #
    # Lock invariant (locked invariant F — tracking→Intelligence integration):
    #   The milestone append + audit persist must execute under the per-batch
    #   advisory write lock. The whole load → append → apply_workflow_progression
    #   → write_json_atomic block runs inside batch_write_lock(_bid).
    #
    #   This delivers the same exactly-once milestone guarantee that
    #   apply_workflow_progression_locked() promises. We do NOT call that
    #   wrapper directly here because:
    #     (a) it re-reads audit.json from disk and would discard the events
    #         we just appended in-memory, and
    #     (b) fcntl.flock is not reentrant from a separate fd in the same
    #         process — calling the locked wrapper inside another lock would
    #         deadlock.
    #   Wrapping the existing block with batch_write_lock + plain
    #   apply_workflow_progression() is the structurally correct realization
    #   of the lock invariant for this call site.
    if result.get("available") and result.get("events"):
        try:
            from .tracking_normalizer import (
                normalize_dhl_events_batch, append_tracking_events,
                apply_workflow_progression,
            )
            from ..utils.batch_lock import batch_write_lock
            from ..utils.io import write_json_atomic
            # Resolve audit.json — typically in cache_dir or its parent
            _audit_path = None
            for _p in (cache_dir / "audit.json", cache_dir.parent / "audit.json"):
                if _p.exists():
                    _audit_path = _p
                    break
            if _audit_path is not None:
                _bid = _audit_path.parent.name
                try:
                    with batch_write_lock(_bid):
                        try:
                            _audit = json.loads(_audit_path.read_text(encoding="utf-8"))
                        except Exception:
                            _audit = None
                        if _audit is not None:
                            _awb = _audit.get("awb") or _audit.get("tracking_no") or tracking_no
                            _norm = normalize_dhl_events_batch(
                                result["events"], awb=_awb, batch_id=_bid,
                            )
                            _audit, _added = append_tracking_events(_audit, _norm)
                            if _added:
                                _audit = apply_workflow_progression(_audit)
                                write_json_atomic(_audit_path, _audit)
                                # Tracking DB write — kept inside the lock so
                                # the DB and audit.json stay consistent. The
                                # DB has its own threading.Lock; nesting the
                                # advisory file lock around it is safe.
                                try:
                                    from . import tracking_db as tdb
                                    tdb.record_events_batch(_norm)
                                except Exception as _db_exc:
                                    log.debug("[tracking] DB write failed: %s", _db_exc)
                except TimeoutError as _tlk:
                    log.warning(
                        "[tracking] could not acquire batch lock for %s: %s",
                        _bid, _tlk,
                    )
        except Exception as _exc:
            log.debug("[tracking] event normalization failed: %s", _exc)

    # ── Attach tracking intelligence (advisory; does not mutate audit) ───────
    try:
        from .tracking_intelligence import evaluate_tracking_intelligence
        # Try to load batch audit from cache_dir parent for cross-refs
        audit_for_ti: Optional[Dict[str, Any]] = None
        try:
            audit_path = (cache_dir / "audit.json")
            if audit_path.exists():
                audit_for_ti = json.loads(audit_path.read_text(encoding="utf-8"))
        except Exception:
            audit_for_ti = None
        result["intelligence"] = evaluate_tracking_intelligence(
            result.get("events") or [], audit=audit_for_ti,
        )
    except Exception as exc:
        log.debug("[tracking] intelligence evaluation failed: %s", exc)

    # ── Save to cache ─────────────────────────────────────────────────────────
    try:
        cache = _load_cache(cache_dir)
        cache[tracking_no] = result
        _save_cache(cache_dir, cache)
    except Exception:
        pass  # cache write failure is non-fatal

    return result
