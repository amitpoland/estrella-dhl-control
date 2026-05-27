"""
test_dhl_sad_followup_phase.py — Regression coverage for the SAD-phase
follow-up surface (AWB 9198333502 incident, 2026-05-27).

Workflow class (Lesson I): the DHL follow-up SLA was single-phase. Once
DHL responded with DSK, the SLA stopped (stop_reason=dhl_email_received)
and the projector surfaced "Stopped" + empty next_due. When the customs
agency still owed us a SAD/ZC429 this looked like Automatic mode silently
doing nothing.

The SAD phase is a PURE DERIVATION over existing audit fields. It writes
nothing, queues nothing, sends nothing. The projector surfaces:
  - Eligible when DSK was received > SAD_FOLLOWUP_WAIT_HOURS ago and SAD
    is not yet received
  - Monitoring (with a future next_due) when DSK was received recently
  - The dhl-phase status otherwise

These tests confirm the projector exposes that truth to the V2 page.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services import dhl_followup_status_projector as proj  # noqa: E402
from app.services import dhl_followup_sla as sla                 # noqa: E402


_NOW = datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc)


def _audit_dsk_no_sad(
    *,
    awb:              str,
    dsk_received_at:  str,
    customs_received: bool = False,
    sad_filename:     str = "",
    stopped:          bool = True,
) -> dict:
    """Build a synthetic audit that matches the AWB 9198333502 shape:
    DSK received, no SAD, dhl_followup stopped with dhl_email_received."""
    return {
        "batch_id":             f"SHIPMENT_{awb}_2026-05_aaaa",
        "awb":                  awb,
        "tracking_no":          awb,
        "clearance_decision":   {"clearance_path": "external_agency_clearance"},
        "clearance_status":     "dhl_email_received",
        "dsk_received":         True,
        "dsk_received_at":      dsk_received_at,
        "customs_docs":         {"received": customs_received},
        "sad_filename":         sad_filename,
        "dhl_followup": {
            "active":     False,
            "stopped_at": dsk_received_at if stopped else None,
            "stop_reason": "dhl_email_received" if stopped else None,
        },
        "followup":             {"mode": "automatic"},
        "timeline":             [],
        "email_ingestion":      {"last_scan_at": dsk_received_at},
    }


@pytest.fixture
def patched_projector(monkeypatch):
    audits: list[dict] = []

    def _fake_paths():
        return [Path(f"/synth/audit_{i}.json") for i, _ in enumerate(audits)]

    def _fake_read(p):
        idx = int(str(p).rsplit("_", 1)[-1].split(".")[0])
        return audits[idx]

    def _fake_active(audit):
        if audit.get("clearance_status") in ("delivered",):
            return False, "delivered"
        return True, "active"

    monkeypatch.setattr(proj, "_audit_paths", _fake_paths)
    monkeypatch.setattr(proj, "_read_audit",  _fake_read)
    monkeypatch.setattr(proj, "_is_active",   _fake_active)
    monkeypatch.setattr(proj, "_flag_on",     lambda: True)
    return audits


# ── Pure-derivation tests (no projector) ────────────────────────────────────

def test_sad_phase_eligible_when_dsk_aged_past_threshold():
    """AWB 9198333502 case: DSK received yesterday, SAD missing, mode Auto."""
    dsk_ts = "2026-05-26T08:00:00+02:00"  # > 4h ago vs _NOW
    audit  = _audit_dsk_no_sad(awb="9198333502", dsk_received_at=dsk_ts)
    out    = sla.derive_sad_followup_status(audit, now=_NOW)
    assert out["phase"]       == "sad_followup"
    assert out["status"]      == sla.SAD_PHASE_ELIGIBLE
    assert out["eligible"]    is True
    assert out["waiting_for"] == "customs_agency"
    assert out["next_due_at"] is not None
    assert out["reason"]      == "dsk_received_sad_pending"


def test_sad_phase_monitoring_when_dsk_recent():
    """DSK received 30 min ago — still within the SAD-phase wait."""
    dsk_ts = (_NOW - timedelta(minutes=30)).isoformat()
    audit  = _audit_dsk_no_sad(awb="9198333502", dsk_received_at=dsk_ts)
    out    = sla.derive_sad_followup_status(audit, now=_NOW)
    assert out["phase"]    == "sad_followup"
    assert out["status"]   == sla.SAD_PHASE_MONITORING
    assert out["eligible"] is False
    assert out["next_due_at"] is not None  # future ts


def test_sad_phase_stopped_when_sad_received():
    """SAD/ZC429 already in → SAD phase is terminal."""
    audit = _audit_dsk_no_sad(
        awb="9198333502",
        dsk_received_at="2026-05-26T08:00:00+02:00",
        customs_received=True,
    )
    out = sla.derive_sad_followup_status(audit, now=_NOW)
    assert out["phase"]  == "none"
    assert out["status"] == sla.SAD_PHASE_RECEIVED
    assert out["reason"] == "customs_docs_received"


def test_sad_phase_none_when_no_dsk():
    """No DSK evidence → SAD phase does not apply; caller falls back."""
    audit = {"awb": "abc", "dsk_received": False, "customs_docs": {}}
    out = sla.derive_sad_followup_status(audit, now=_NOW)
    assert out["phase"]    == "none"
    assert out["status"]   == sla.SAD_PHASE_NONE
    assert out["reason"]   == "no_dsk_evidence"
    assert out["eligible"] is False


def test_sad_phase_reads_timeline_dsk_event():
    """When the audit lacks dsk_received_at but the timeline has the event,
    the derivation still resolves the DSK timestamp."""
    dsk_ts = "2026-05-26T08:00:00+00:00"
    audit  = {
        "awb": "9198333502",
        "dsk_received": True,
        "customs_docs": {"received": False},
        "timeline": [
            {"event": "dsk_received", "ts": dsk_ts, "actor": "monitor"},
        ],
    }
    out = sla.derive_sad_followup_status(audit, now=_NOW)
    assert out["phase"]    == "sad_followup"
    assert out["eligible"] is True


# ── Projector integration tests ─────────────────────────────────────────────

def test_projector_surfaces_sad_eligible_when_dhl_stopped(patched_projector):
    """The AWB 9198333502 row must not silently show Stopped or Waiting —
    it must show Eligible (or Monitoring) for the SAD phase."""
    audit = _audit_dsk_no_sad(
        awb="9198333502",
        dsk_received_at="2026-05-26T08:00:00+02:00",
    )
    patched_projector.append(audit)

    rows = proj.project_shipment_rows(now=_NOW)
    assert len(rows) == 1
    row = rows[0]
    assert row["awb"]                == "9198333502"
    assert row["mode"]               == "Auto"
    assert row["status"]             == proj.ST_ELIGIBLE
    assert row["phase"]              == "sad_followup"
    assert row["next_due_at"]        is not None
    assert row["waiting_for"]        == "customs_agency"
    assert row["dsk_received_at"]    is not None
    assert row["sad_followup_reason"] == "dsk_received_sad_pending"


def test_projector_stays_dhl_phase_when_no_dsk(patched_projector):
    """Without DSK evidence, the row uses the dhl-phase status as before."""
    audit = {
        "batch_id":           "SHIPMENT_42_2026-05",
        "awb":                "42",
        "tracking_no":        "42",
        "clearance_decision": {"clearance_path": "self_clearance"},
        "clearance_status":   "in_progress",
        "dhl_followup":       {"active": True, "next_followup_at": _NOW.isoformat()},
        "followup":           {"mode": "manual"},
        "timeline":           [],
    }
    patched_projector.append(audit)

    rows = proj.project_shipment_rows(now=_NOW)
    assert rows[0]["phase"]              == "dhl_followup"
    assert rows[0]["sad_followup_reason"] in (None, "no_dsk_evidence")


def test_projector_shows_stopped_when_sad_received(patched_projector):
    """SAD already received → SAD phase done; row falls back to dhl-stopped."""
    audit = _audit_dsk_no_sad(
        awb="9198333502",
        dsk_received_at="2026-05-26T08:00:00+02:00",
        customs_received=True,
    )
    patched_projector.append(audit)

    rows = proj.project_shipment_rows(now=_NOW)
    assert rows[0]["status"] == proj.ST_STOPPED
    assert rows[0]["phase"]  == "dhl_followup"


def test_automation_status_eligible_count_includes_sad_phase(patched_projector):
    """The top card's eligible_now must count SAD-phase eligible rows so
    the dashboard's traffic light reflects the real backlog."""
    audit = _audit_dsk_no_sad(
        awb="9198333502",
        dsk_received_at="2026-05-26T08:00:00+02:00",
    )
    patched_projector.append(audit)

    card = proj.project_automation_status(now=_NOW)
    assert card["status_label"] == "ACTIVE"
    assert card["eligible_now"] >= 1
    assert card["traffic_light"]["ready"] >= 1
