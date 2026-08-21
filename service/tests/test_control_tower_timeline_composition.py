"""The Control Tower drawer's timeline must not contradict its own headline.

The list row's ``milestones`` is the STAGE authority: fixed workflow slots that
drive stage classification and the duration KPIs. For an inbound leg
``_build_inbound_milestones`` maps only two carrier stages (arrived_pl,
delivered) into those slots and discards every intermediate checkpoint, while
the headline (``transport_status`` / ``current_location``) is derived from the
FULL carrier event stream. That is how the drawer could read
"At Destination - WARSZAWA - PL" above a timeline that stopped at PZ generation.

``project_shipment_detail`` therefore publishes the composed stream beside the
milestones, from the existing merge/dedup authority. These tests pin that the
composition reaches the detail payload AND that the stage authority is left
alone.
"""
from __future__ import annotations

AUDIT = {
    "batch_id": "SHIPMENT_CT_1",
    "awb": "6000000001",
    "timeline": [
        {"ts": "2026-08-18T08:00:00+00:00", "event": "batch_created",
         "trigger_source": "api", "actor": "operator"},
        {"ts": "2026-08-20T12:00:00+00:00", "event": "pz_generated",
         "trigger_source": "api", "actor": "operator"},
    ],
}

# The carrier movements that justify an "At Destination" headline, none of
# which _build_inbound_milestones keeps.
CARRIER_EVENTS = [
    {"event_time": "2026-08-18T20:55:00+00:00", "normalized_stage": "PICKED_UP",
     "description": "Shipment picked up", "location": "MUMBAI (BOMBAY) - IN",
     "carrier": "DHL", "source": "dhl_api"},
    {"event_time": "2026-08-19T13:52:16+00:00", "normalized_stage": "IN_TRANSIT",
     "description": "Arrived at DHL Sort Facility HONG KONG",
     "location": "HONG KONG - HK", "carrier": "DHL", "source": "dhl_api"},
    {"event_time": "2026-08-21T09:03:43+00:00",
     "normalized_stage": "ARRIVED_DESTINATION_COUNTRY",
     "description": "Processed at WARSAW-POLAND", "location": "WARSZAWA - PL",
     "carrier": "DHL", "source": "dhl_api"},
]


def _patch_sources(monkeypatch, *, carrier_events):
    from app.services import dhl_logistics_projector as proj
    from app.services import tracking_db as tdb
    monkeypatch.setattr(
        tdb, "get_events_for_batch", lambda bid, direction=None: carrier_events)
    monkeypatch.setattr(
        tdb, "get_events_for_awb", lambda awb, direction=None: [])
    return proj


def test_composed_stream_carries_the_carrier_movements(monkeypatch):
    proj = _patch_sources(monkeypatch, carrier_events=CARRIER_EVENTS)
    events = proj.assemble_shipment_timeline(AUDIT["batch_id"], AUDIT)

    labels = " | ".join(str(e.get("label") or "") for e in events)
    assert "Shipment picked up" in labels
    assert "HONG KONG" in labels
    assert "WARSAW" in labels

    # The workflow events survive alongside them — this is a merge, not a swap.
    assert any("pz" in str(e.get("event") or "").lower() for e in events)


def test_the_composed_stream_reaches_past_the_last_workflow_event(monkeypatch):
    """The exact contradiction: headline newer than the visible timeline."""
    proj = _patch_sources(monkeypatch, carrier_events=CARRIER_EVENTS)
    events = proj.assemble_shipment_timeline(AUDIT["batch_id"], AUDIT)

    newest_workflow = max(
        str(e["ts"]) for e in events if e["source"] == "audit_timeline")
    newest_overall = max(str(e["ts"]) for e in events)
    assert newest_overall > newest_workflow, (
        "composed stream must extend past the last workflow event when the "
        "carrier has reported later movement"
    )


def test_milestones_remain_the_narrow_stage_authority(monkeypatch):
    """Ranking the timeline must not silently re-point stage classification.

    _build_inbound_milestones keeps its fixed workflow slots; if this ever
    starts returning raw carrier checkpoints, stage classification and the
    duration KPIs change meaning without anyone deciding that.
    """
    proj = _patch_sources(monkeypatch, carrier_events=CARRIER_EVENTS)
    milestones = proj._build_inbound_milestones(AUDIT["timeline"], CARRIER_EVENTS)

    stage_ids = {m.get("stage_id") for m in milestones}
    assert stage_ids, "stage authority must still produce milestones"
    # Every milestone is a known workflow slot, never a raw carrier description.
    known = {m[0] for m in proj._INBOUND_MILESTONES}
    assert stage_ids <= known
    assert not any(
        "Sort Facility" in str(m.get("label") or "") for m in milestones)


def test_detail_payload_publishes_events_beside_milestones(monkeypatch):
    """project_shipment_detail must expose BOTH, not one instead of the other."""
    proj = _patch_sources(monkeypatch, carrier_events=CARRIER_EVENTS)

    monkeypatch.setattr(proj, "_audit_paths", lambda: [_FakePath()])
    monkeypatch.setattr(proj, "_read_audit", lambda p: dict(AUDIT))
    monkeypatch.setattr(proj, "_load_resolution_map", lambda: {})
    # No carrier row for this AWB — force the inbound branch.
    monkeypatch.setattr(proj, "_carrier_db_path", lambda: _MissingDb())

    row = proj.project_shipment_detail(AUDIT["awb"])
    assert row is not None
    assert "milestones" in row
    assert isinstance(row.get("events"), list) and row["events"], (
        "detail must carry the composed stream"
    )
    assert len(row["events"]) > len(row["milestones"])


class _FakePath:
    """Minimal stand-in for an audit path (only .parent.name is read)."""
    @property
    def parent(self):
        return self

    @property
    def name(self):
        return AUDIT["batch_id"]


class _MissingDb:
    """A carrier DB path that cannot resolve, so the inbound branch is taken."""
    def exists(self):
        return False

    def __str__(self):
        return "<missing>"

    def __fspath__(self):
        return "<missing>"
