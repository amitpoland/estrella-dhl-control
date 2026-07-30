"""
test_tracking_cache_inner_record.py — AWB-keyed tracking_cache.json read fix.

tracking_cache.json is keyed by tracking number at the OUTER level:

    { "<awb>": { "status", "last_event", "source", ... }, ... }

Two production read paths previously called ``.get("status")`` on the OUTER
dict, so the tracking status was ALWAYS "" — a silent failure (no crash) that
left ``tracking_available`` / the ``tracking_refresh`` diagnostics stuck at the
empty/blocked state regardless of the real shipment status. These tests pin the
corrected AWB → inner-record lookup at both read sites:

  1. app.api.routes_dashboard.action_diagnostics
  2. app.services.batch_state_normalizer.normalize_batch_state

plus the two shared helpers that back them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services.tracking_service import (  # noqa: E402
    resolve_batch_tracking_no,
    select_cached_tracking_record,
)
from app.services.batch_state_normalizer import normalize_batch_state  # noqa: E402


def _record(status: str = "in_transit") -> dict:
    return {
        "tracking_no":  "1234567890",
        "carrier":      "DHL",
        "status":       status,
        "status_label": "In Transit",
        "source":       "dhl_unified_api",
        "last_event":   {"description": "Processed at DHL facility"},
        "available":    True,
    }


# ── Pure helper: select_cached_tracking_record ───────────────────────────────

def test_select_by_tracking_no():
    cache = {"1234567890": _record()}
    assert select_cached_tracking_record(cache, "1234567890")["status"] == "in_transit"


def test_outer_dict_has_no_top_level_status():
    """The regression itself: the AWB-keyed outer dict has no top-level status."""
    cache = {"1234567890": _record()}
    assert cache.get("status", "") == ""                       # the old buggy read
    assert select_cached_tracking_record(cache, "1234567890")["status"] == "in_transit"


def test_select_single_entry_fallback_when_awb_unknown():
    cache = {"9999999999": _record("delivered")}
    assert select_cached_tracking_record(cache, "")["status"] == "delivered"


def test_select_multi_entry_no_awb_returns_empty():
    cache = {"111": _record("in_transit"), "222": _record("delivered")}
    assert select_cached_tracking_record(cache, "") == {}       # cannot disambiguate


def test_select_multi_entry_picks_matching_awb():
    cache = {"111": _record("in_transit"), "222": _record("delivered")}
    assert select_cached_tracking_record(cache, "222")["status"] == "delivered"


def test_select_legacy_flat_record():
    """Legacy cache where the top level is itself the record."""
    flat = _record("out_for_delivery")
    assert select_cached_tracking_record(flat, "1234567890")["status"] == "out_for_delivery"


def test_select_empty_or_bad_input():
    assert select_cached_tracking_record({}, "x") == {}
    assert select_cached_tracking_record(None, "x") == {}
    assert select_cached_tracking_record([], "x") == {}


# ── Pure helper: resolve_batch_tracking_no ───────────────────────────────────

def test_resolve_from_audit_tracking_no():
    assert resolve_batch_tracking_no({"tracking_no": "AAA"}, "") == "AAA"


def test_resolve_from_audit_awb():
    assert resolve_batch_tracking_no({"awb": "BBB"}, "") == "BBB"


def test_resolve_from_shipment_batch_id():
    assert resolve_batch_tracking_no({}, "SHIPMENT_9158478722_2026-06_924c4e59") == "9158478722"


def test_resolve_prefers_audit_over_batch_id():
    assert resolve_batch_tracking_no({"tracking_no": "AAA"}, "SHIPMENT_BBB_x_y") == "AAA"


def test_resolve_none_when_unresolvable():
    assert resolve_batch_tracking_no({}, "TEST_EMPTY") == ""


# ── Site 2: batch_state_normalizer reads the inner record ────────────────────

def test_normalizer_reads_inner_record_status(tmp_path):
    batch_id = "SHIPMENT_1234567890_2026-04_deadbeef"
    bdir = tmp_path / batch_id
    bdir.mkdir()
    (bdir / "tracking_cache.json").write_text(
        json.dumps({"1234567890": _record("in_transit")}), encoding="utf-8"
    )
    audit = {"batch_id": batch_id, "tracking_no": "1234567890", "inputs": {}}
    state = normalize_batch_state(audit, bdir)
    # Silent-failure pin: with an AWB-keyed cache, tracking must register.
    assert state.tracking_available is True
    assert state.tracking_404_nonblocking is False


def test_normalizer_awb_from_batch_id_only(tmp_path):
    """audit lacks tracking_no; AWB derived from the SHIPMENT_ id resolves the record."""
    batch_id = "SHIPMENT_1234567890_2026-04_deadbeef"
    bdir = tmp_path / batch_id
    bdir.mkdir()
    (bdir / "tracking_cache.json").write_text(
        json.dumps({"1234567890": _record("in_transit")}), encoding="utf-8"
    )
    audit = {"batch_id": batch_id, "inputs": {}}
    state = normalize_batch_state(audit, bdir)
    assert state.tracking_available is True


def test_normalizer_not_found_stays_nonblocking(tmp_path):
    batch_id = "SHIPMENT_1234567890_2026-04_deadbeef"
    bdir = tmp_path / batch_id
    bdir.mkdir()
    rec = {**_record(), "status": "not_found", "source": "dhl_api_404"}
    (bdir / "tracking_cache.json").write_text(
        json.dumps({"1234567890": rec}), encoding="utf-8"
    )
    audit = {"batch_id": batch_id, "tracking_no": "1234567890", "inputs": {}}
    state = normalize_batch_state(audit, bdir)
    assert state.tracking_404_nonblocking is True
    assert state.tracking_available is False


def test_normalizer_no_cache_falls_back_to_audit_tracking(tmp_path):
    """With no cache file, audit.tracking is still honoured (regression guard)."""
    batch_id = "SHIPMENT_1234567890_2026-04_deadbeef"
    bdir = tmp_path / batch_id
    bdir.mkdir()
    audit = {
        "batch_id": batch_id,
        "tracking_no": "1234567890",
        "tracking": {"status": "in_transit", "source": "dhl_unified_api"},
        "inputs": {},
    }
    state = normalize_batch_state(audit, bdir)
    assert state.tracking_available is True


# ── Site 1: action_diagnostics reads the inner record ────────────────────────

def test_action_diagnostics_reads_inner_record(tmp_path, monkeypatch):
    from app.api import routes_dashboard as rd

    monkeypatch.setattr(rd, "_OUTPUTS", tmp_path)
    batch_id = "SHIPMENT_1234567890_2026-04_deadbeef"
    bdir = tmp_path / batch_id
    bdir.mkdir()
    audit = {
        "batch_id": batch_id,
        "tracking_no": "1234567890",
        "status": "ready",
        "inputs": {},
    }
    (bdir / "audit.json").write_text(json.dumps(audit))
    (bdir / "tracking_cache.json").write_text(
        json.dumps({"1234567890": _record("in_transit")}), encoding="utf-8"
    )

    with patch("app.api.routes_dashboard._OUTPUTS", tmp_path), \
         patch("app.services.email_service.get_all_emails", return_value=[]):
        result = rd.action_diagnostics(batch_id)

    trk = result["actions"]["tracking_refresh"]
    assert trk["tracking_status"] == "in_transit"   # not "" — the bug
    assert trk["source"] == "dhl_unified_api"


def test_action_diagnostics_awb_from_batch_id_only(tmp_path, monkeypatch):
    """audit has no tracking_no; AWB comes from the SHIPMENT_ batch id."""
    from app.api import routes_dashboard as rd

    monkeypatch.setattr(rd, "_OUTPUTS", tmp_path)
    batch_id = "SHIPMENT_1234567890_2026-04_deadbeef"
    bdir = tmp_path / batch_id
    bdir.mkdir()
    audit = {"batch_id": batch_id, "status": "ready", "inputs": {}}
    (bdir / "audit.json").write_text(json.dumps(audit))
    (bdir / "tracking_cache.json").write_text(
        json.dumps({"1234567890": _record("delivered")}), encoding="utf-8"
    )

    with patch("app.api.routes_dashboard._OUTPUTS", tmp_path), \
         patch("app.services.email_service.get_all_emails", return_value=[]):
        result = rd.action_diagnostics(batch_id)

    assert result["actions"]["tracking_refresh"]["tracking_status"] == "delivered"
