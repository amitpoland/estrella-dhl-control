"""Regression: the tracking response ``last_event`` must be a render-safe STRING.

Origin: production React error #31 — "Objects are not valid as a React child
(found: object with keys {timestamp, location, status, description})" on the V2
shipment-detail Tracking card.

Two independent delivery paths for the malformed value were established:

  1. FRESH  — the DHL response builders (_call_dhl_legacy / _call_dhl_unified)
     returned the raw normalised event dict as ``last_event``.
  2. CACHED — the on-disk tracking cache stores the full response dict and
     re-emits a stored object-form ``last_event`` unchanged on a cache hit.

Contract (routes_tracking.TrackingResponse.last_event: str; tracking_patch
apply_tracking_update last_event: str) + the V2 renderer both expect a string.

Fix under test:
  * backend authority: one shared ``_event_summary`` serializer, used by both
    DHL builders (primary fix — fresh responses).
  * frontend compatibility: ``_eventText`` guard at the Latest-event render
    boundary only (required for already-cached object payloads).

These tests demonstrate BEHAVIOUR (helper + mocked builders + cache read +
executable JS guard), not merely source text; a source-contract grep remains
as an extra guard.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services import tracking_service as ts

_SRC = Path(ts.__file__).read_text(encoding="utf-8")
_STATIC_V2 = Path(ts.__file__).resolve().parents[1] / "static" / "v2"
_JSX = (_STATIC_V2 / "shipment-detail-page.jsx").read_text(encoding="utf-8")


# ── Step 4 — backend summary helper behaviour ────────────────────────────────

def test_summary_prefers_description():
    ev = {"timestamp": "t", "location": "WARSAW - PL", "status": "In transit",
          "description": "Shipment processed"}
    assert ts._event_summary(ev) == "Shipment processed"
    assert isinstance(ts._event_summary(ev), str)


def test_summary_falls_back_to_status_when_no_description():
    assert ts._event_summary({"status": "Delivered", "description": ""}) == "Delivered"


def test_summary_falls_back_to_location_when_no_description_or_status():
    ev = {"location": "WARSAW - PL", "status": "", "description": ""}
    assert ts._event_summary(ev) == "WARSAW - PL"


def test_summary_empty_dict_is_empty_string():
    assert ts._event_summary({}) == ""


def test_summary_none_is_empty_string():
    assert ts._event_summary(None) == ""


def test_summary_passes_through_existing_string():
    assert ts._event_summary("Shipment departed") == "Shipment departed"


def test_summary_coerces_unexpected_scalar_to_string():
    assert ts._event_summary(1234) == "1234"
    assert isinstance(ts._event_summary(1234), str)


def test_summary_always_returns_str():
    for v in ({}, None, "x", 7, [], {"description": {"nested": 1}}):
        assert isinstance(ts._event_summary(v), str)


# ── Step 5 — full response builders return a string, events stay structured ──

_CANNED_DHL = {
    "shipments": [{
        # DHL returns newest-first; the builder sorts ASC, so the WARSAW event
        # (later timestamp) becomes events[-1] / last_event.
        "events": [
            {"timestamp": "2026-07-29T12:00:00",
             "location": {"address": {"addressLocality": "Warsaw", "countryCode": "PL"}},
             "status": "transit", "description": "Shipment processed at facility"},
            {"timestamp": "2026-07-28T09:00:00",
             "location": {"address": {"addressLocality": "Mumbai", "countryCode": "IN"}},
             "status": "picked_up", "description": "Shipment picked up"},
        ],
        "origin": {"address": {"addressLocality": "Mumbai", "countryCode": "IN"}},
        "destination": {"address": {"addressLocality": "Warsaw", "countryCode": "PL"}},
        "status": {"status": "transit", "description": "In transit"},
    }]
}


class _FakeResp:
    def __init__(self, data): self._data = data
    def raise_for_status(self): return None
    def json(self): return self._data


class _FakeClient:
    """Stand-in for httpx.Client — proves NO real network call is made."""
    used = False
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def get(self, *a, **k):
        _FakeClient.used = True
        return _FakeResp(_CANNED_DHL)


@pytest.mark.parametrize("builder_name", ["_call_dhl_legacy", "_call_dhl_unified"])
def test_builders_emit_string_last_event_and_keep_events_structured(builder_name, monkeypatch):
    monkeypatch.setattr(ts.settings, "dhl_tracking_api_status", "active", raising=False)
    monkeypatch.setattr(ts.settings, "dhl_api_key", "x", raising=False)
    monkeypatch.setattr(ts.settings, "dhl_tracking_api_key", "x", raising=False)
    monkeypatch.setattr(ts.httpx, "Client", _FakeClient)
    _FakeClient.used = False

    payload = getattr(ts, builder_name)("1234567890")

    # last_event is a render-safe STRING (the newest event's description).
    assert isinstance(payload["last_event"], str)
    assert payload["last_event"] == "Shipment processed at facility"
    # events remain a structured list of dicts — NOT flattened.
    assert isinstance(payload["events"], list)
    assert isinstance(payload["events"][0], dict)
    assert set(payload["events"][0]) == {"timestamp", "location", "status", "description"}
    # Invariants unchanged by the fix (only the last_event VALUE type changed).
    assert payload["events_count"] == 2
    assert payload["last_location"] == "WARSAW - PL"
    assert payload["last_update"] == "2026-07-29T12:00:00"
    # Status / delivery-label flags remain present and string-typed.
    assert isinstance(payload["status"], str) and payload["status"]
    assert isinstance(payload["status_label"], str) and payload["status_label"]
    assert payload["source"] in ("dhl_api", "dhl_unified_api")
    # Network seam was the fake, not a real socket.
    assert _FakeClient.used is True


# ── Step 7 — cached object-form last_event reaches the response UNCHANGED ─────
# (documents why the frontend guard is required; the hotfix does NOT mutate cache)

def test_cached_object_last_event_is_not_sanitised_on_read(tmp_path, monkeypatch):
    monkeypatch.setattr(ts.settings, "dhl_tracking_api_status", "active", raising=False)
    obj = {"timestamp": "2026-07-29T12:00:00", "location": "WARSAW - PL",
           "status": "In transit", "description": "Shipment processed"}
    cache = {"1234567890": {
        "status": "delivered",               # terminal → returned verbatim, no network
        "last_event": obj,                   # legacy object-form, as old code wrote it
        "cached_at": "2026-07-29T12:00:00+00:00",
        "available": True,
    }}
    (tmp_path / "tracking_cache.json").write_text(json.dumps(cache), encoding="utf-8")

    result = ts.get_tracking_status("1234567890", "DHL", tmp_path)

    assert result["source"] == "cache"
    # The cache read does NOT sanitise last_event — the object survives to the
    # frontend. This is the exact vector the frontend _eventText guard defends.
    assert isinstance(result["last_event"], dict)


# ── Step 6 — frontend compatibility guard resolves the cached object to text ──

def test_render_routes_last_event_through_compat_helper():
    assert "_dash(_eventText(tracking.last_event))" in _JSX, (
        "the Latest-event row must pass tracking.last_event through _eventText"
    )


def test_dash_helper_is_not_a_global_object_stringifier():
    # _dash must stay the null/undefined/'' helper — never a global object coercer.
    assert "function _dash(v) { return (v === null || v === undefined || v === '') ? '—' : v; }" in _JSX
    dash_line = next(l for l in _JSX.splitlines() if l.startswith("function _dash("))
    assert "typeof" not in dash_line and "object" not in dash_line


def test_event_text_guard_resolves_object_to_text_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available for executable JS verification")
    m = re.search(r"function _eventText\(v\) \{.*?\n\}", _JSX, re.S)
    assert m, "_eventText helper not found in shipment-detail-page.jsx"
    script = m.group(0) + """
const obj = { timestamp: "t", location: "Warsaw", status: "In transit", description: "Shipment processed" };
if (_eventText(obj) !== "Shipment processed") { console.error("desc"); process.exit(1); }
if (_eventText({ status: "In transit", location: "Warsaw" }) !== "In transit") { console.error("status"); process.exit(1); }
if (_eventText({ location: "Warsaw" }) !== "Warsaw") { console.error("loc"); process.exit(1); }
if (_eventText("already a string") !== "already a string") { console.error("str"); process.exit(1); }
console.log("OK");
"""
    proc = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0 and "OK" in proc.stdout, proc.stderr


# ── Extra source-contract guard (defence in depth, not the only proof) ───────

def test_no_dhl_builder_returns_the_raw_event_dict():
    """No DHL tracking response builder may bind the raw event dict to
    last_event — both must route through _event_summary (contract: str)."""
    # Scope to the two DHL builder bodies (avoid the intelligence/patch authorities
    # which are separately typed/consumed).
    for fn in ("_call_dhl_legacy", "_call_dhl_unified"):
        start = _SRC.index(f"def {fn}(")
        end = _SRC.index("\ndef ", start + 1)
        body = _SRC[start:end]
        assert re.search(r'"last_event"\s*:\s*last_event\s*,', body) is None, (
            f"{fn} still emits the raw event dict as last_event"
        )
        assert "_event_summary(last_event)" in body
