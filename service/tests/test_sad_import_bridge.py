"""
test_sad_import_bridge.py — SAD import state bridge after PZ processing.

Coverage
--------
Unit tests for _stamp_sad_imported():
  1. sets sad_imported = True after successful run
  2. sets sad_imported_ts (ISO format)
  3. emits zc429_received for ZC429 filename
  4. emits sad_uploaded for non-ZC429 filename
  5. idempotent — no overwrite if sad_imported_ts already set
  6. no duplicate event when event already in timeline

Integration: decision engine no longer proposes agency_followup when sad_imported_ts set:
  7. proposal_engine._sad_received() returns True → agency_sla proposal suppressed

Integration: dhl_readiness advances correctly after stamp:
  8. agency_forwarded batch advances to sad_received after zc429_received emitted
  9. pz_generated event still emitted (preserved)
"""
from __future__ import annotations

import json
import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core import timeline as tl
from app.core.config import settings


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_audit(batch_dir: Path, data: dict) -> Path:
    batch_dir.mkdir(parents=True, exist_ok=True)
    ap = batch_dir / "audit.json"
    ap.write_text(json.dumps(data), encoding="utf-8")
    return ap


def _read_audit(batch_dir: Path) -> dict:
    return json.loads((batch_dir / "audit.json").read_text(encoding="utf-8"))


def _ev(event: str, ts: str) -> dict:
    return {"event": event, "ts": ts, "trigger_source": "test", "actor": "test", "detail": {}}


T_AGENCY = "2026-01-10T14:00:00+00:00"


# Import under test
from app.api.routes_upload import _stamp_sad_imported


# ── 1. sad_imported = True ────────────────────────────────────────────────────

def test_stamp_sets_sad_imported_true(tmp_path):
    d = tmp_path / "outputs" / "B1"
    _write_audit(d, {"timeline": []})
    _stamp_sad_imported(d, "ZC429_26PL_001.pdf")
    assert _read_audit(d)["sad_imported"] is True


# ── 2. sad_imported_ts set and ISO format ─────────────────────────────────────

def test_stamp_sets_sad_imported_ts(tmp_path):
    d = tmp_path / "outputs" / "B2"
    _write_audit(d, {"timeline": []})
    _stamp_sad_imported(d, "ZC429_26PL_001.pdf")
    ts = _read_audit(d).get("sad_imported_ts")
    assert ts is not None
    # Must parse as ISO datetime
    datetime.datetime.fromisoformat(ts)


# ── 3. ZC429 filename → EV_ZC429_RECEIVED ────────────────────────────────────

def test_stamp_emits_zc429_received_for_zc429_file(tmp_path):
    d = tmp_path / "outputs" / "B3"
    _write_audit(d, {"timeline": []})
    _stamp_sad_imported(d, "ZC429_26PL44302D0009Y2R9_1_PL_0000416C.pdf")
    events = [e["event"] for e in _read_audit(d).get("timeline", [])]
    assert tl.EV_ZC429_RECEIVED in events
    assert tl.EV_SAD_UPLOADED not in events


# ── 4. Non-ZC429 filename → EV_SAD_UPLOADED ──────────────────────────────────

def test_stamp_emits_sad_uploaded_for_generic_sad(tmp_path):
    d = tmp_path / "outputs" / "B4"
    _write_audit(d, {"timeline": []})
    _stamp_sad_imported(d, "SAD_customs_clearance.pdf")
    events = [e["event"] for e in _read_audit(d).get("timeline", [])]
    assert tl.EV_SAD_UPLOADED in events
    assert tl.EV_ZC429_RECEIVED not in events


# ── 5. Idempotent — no overwrite if already set ───────────────────────────────

def test_stamp_idempotent_does_not_overwrite_existing_ts(tmp_path):
    d = tmp_path / "outputs" / "B5"
    original_ts = "2026-01-01T00:00:00+00:00"
    _write_audit(d, {"sad_imported_ts": original_ts, "timeline": []})
    _stamp_sad_imported(d, "ZC429_26PL_001.pdf")
    # Timestamp must not change
    assert _read_audit(d)["sad_imported_ts"] == original_ts


# ── 6. No duplicate event when already in timeline ───────────────────────────

def test_stamp_does_not_duplicate_existing_event(tmp_path):
    d = tmp_path / "outputs" / "B6"
    existing_ev = _ev(tl.EV_ZC429_RECEIVED, "2026-01-01T12:00:00+00:00")
    _write_audit(d, {"timeline": [existing_ev]})
    _stamp_sad_imported(d, "ZC429_26PL_001.pdf")
    events = [e["event"] for e in _read_audit(d).get("timeline", [])]
    assert events.count(tl.EV_ZC429_RECEIVED) == 1


# ── 7. proposal_engine: no agency_followup when sad_imported_ts set ───────────

def _ts_days_ago(days: float) -> str:
    dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    return dt.isoformat()


def test_no_agency_followup_when_sad_imported_ts_present():
    from app.agents.proposal_engine import generate
    audit = {
        "agency_reply_package": {"built_at": _ts_days_ago(5)},
        "sad_imported_ts":      "2026-01-15T10:00:00+00:00",
        "action_proposals":     [],
    }
    with patch("app.agents.proposal_engine._load_audit", return_value=audit), \
         patch("app.services.batch_readiness.get_batch_readiness",
               side_effect=Exception("not needed")):
        result = generate("B_SAD_IMP")
    agency_props = [p for p in result if p.get("type") == "agency_followup"]
    assert len(agency_props) == 0, (
        "agency_followup must not be proposed when sad_imported_ts is set"
    )


def test_no_agency_followup_when_sad_imported_true():
    from app.agents.proposal_engine import generate
    audit = {
        "agency_reply_package": {"built_at": _ts_days_ago(5)},
        "sad_imported":         True,
        "action_proposals":     [],
    }
    with patch("app.agents.proposal_engine._load_audit", return_value=audit), \
         patch("app.services.batch_readiness.get_batch_readiness",
               side_effect=Exception("not needed")):
        result = generate("B_SAD_IMP2")
    assert not any(p.get("type") == "agency_followup" for p in result)


# ── 8. dhl_readiness advances agency_forwarded → sad_received after stamp ─────

def test_dhl_readiness_advances_to_sad_received_after_stamp(tmp_path):
    from app.services import dhl_readiness as dr

    batch_id = "BRIDGE_DHL_TEST"
    d = tmp_path / "outputs" / batch_id
    # Start: agency_forwarded state (agency email sent, no SAD yet)
    _write_audit(d, {
        "timeline": [
            _ev(tl.EV_DHL_EMAIL_RECEIVED, "2026-01-10T08:00:00+00:00"),
            _ev(tl.EV_DSK_TRANSFER_SENT,  "2026-01-10T10:00:00+00:00"),
            _ev(tl.EV_CESJA_RECEIVED,      "2026-01-11T09:00:00+00:00"),
            _ev(tl.EV_AGENCY_EMAIL_SENT,   T_AGENCY),
        ]
    })

    with patch.object(settings, "storage_root", tmp_path):
        state_before = dr.get_dhl_readiness(batch_id)
    assert state_before["dhl_status"] == "agency_forwarded"

    # Run stamp with ZC429 file
    _stamp_sad_imported(d, "ZC429_26PL44302D0009Y2R9_1_PL_0000416C.pdf")

    with patch.object(settings, "storage_root", tmp_path):
        state_after = dr.get_dhl_readiness(batch_id)
    assert state_after["dhl_status"] == "sad_received", (
        f"Expected sad_received after stamp, got {state_after['dhl_status']}"
    )


# ── 9. pz_generated event is still emitted (preserved) ───────────────────────

def test_pz_generated_event_still_present_after_stamp(tmp_path):
    """_stamp_sad_imported must not remove or replace the pz_generated event."""
    d = tmp_path / "outputs" / "B9"
    existing_pz_ev = _ev(tl.EV_PZ_GENERATED, "2026-01-15T12:00:00+00:00")
    _write_audit(d, {"timeline": [existing_pz_ev]})
    _stamp_sad_imported(d, "ZC429_26PL_001.pdf")
    events = [e["event"] for e in _read_audit(d).get("timeline", [])]
    assert tl.EV_PZ_GENERATED in events, "pz_generated event must be preserved after stamp"
    assert tl.EV_ZC429_RECEIVED in events, "zc429_received must also be present"


# ── 10. Missing audit.json is handled silently ────────────────────────────────

def test_stamp_silent_on_missing_audit_file(tmp_path):
    """No audit.json → _stamp_sad_imported must not raise."""
    d = tmp_path / "outputs" / "B_MISSING"
    d.mkdir(parents=True, exist_ok=True)
    # audit.json intentionally absent
    _stamp_sad_imported(d, "ZC429_26PL_001.pdf")   # must not raise


# ── 11. Corrupt audit is handled silently ────────────────────────────────────

def test_stamp_silent_on_corrupt_audit(tmp_path):
    """Corrupt audit.json → _stamp_sad_imported must not raise."""
    d = tmp_path / "outputs" / "B_CORRUPT"
    d.mkdir(parents=True, exist_ok=True)
    (d / "audit.json").write_text("{not valid json{{", encoding="utf-8")
    _stamp_sad_imported(d, "ZC429_26PL_001.pdf")   # must not raise
