"""One chronological, source-attributed stream per shipment.

The unified timeline owns no facts. It reads the workflow timeline and the
carrier event stores and orders them; the normalised store (tracking_db) wins
over the raw carrier cache so no event is listed twice.
"""
from __future__ import annotations

import json


AUDIT = {
    "batch_id": "SHIPMENT_TL_1",
    "awb": "7777777777",
    "timeline": [
        {"ts": "2026-08-10T08:00:00+00:00", "event": "processing_started",
         "trigger_source": "api", "actor": "operator"},
        {"ts": "2026-08-12T09:00:00+00:00", "event": "pz_document_generated",
         "trigger_source": "api", "actor": "operator"},
    ],
}

DB_EVENTS = [
    {"event_time": "2026-08-11T07:30:00+00:00", "normalized_stage": "PICKED_UP",
     "description": "Shipment picked up", "location": "Mumbai", "carrier": "DHL",
     "source": "dhl_api"},
    {"event_time": "2026-08-13T18:00:00+00:00", "normalized_stage": "DELIVERED",
     "description": "Delivered", "location": "Warsaw", "carrier": "DHL",
     "source": "dhl_api"},
]


def test_timeline_is_chronological_and_source_attributed(monkeypatch):
    from app.services import dhl_logistics_projector as proj
    from app.services import tracking_db as tdb

    monkeypatch.setattr(tdb, "get_events_for_batch", lambda bid, direction=None: DB_EVENTS)
    monkeypatch.setattr(tdb, "get_events_for_awb", lambda awb, direction=None: [])

    out = proj.assemble_shipment_timeline("SHIPMENT_TL_1", AUDIT)

    assert [r["ts"] for r in out] == sorted(r["ts"] for r in out)
    assert [r["source"] for r in out] == [
        "audit_timeline", "tracking_db", "audit_timeline", "tracking_db",
    ]
    assert out[1]["location"] == "Mumbai"
    assert out[1]["label"] == "Shipment picked up"


def test_tracking_db_suppresses_the_raw_cache(monkeypatch):
    """The normalised store wins — the cache is a fallback, never an addition."""
    from app.services import dhl_logistics_projector as proj
    from app.services import tracking_db as tdb

    monkeypatch.setattr(tdb, "get_events_for_batch", lambda bid, direction=None: DB_EVENTS)
    monkeypatch.setattr(tdb, "get_events_for_awb", lambda awb, direction=None: [])

    def _boom(awb, batch_id):
        raise AssertionError("cache must not be read when tracking_db has events")

    monkeypatch.setattr(proj, "_outbound_tracking_snapshot", _boom)
    out = proj.assemble_shipment_timeline("SHIPMENT_TL_1", AUDIT)
    assert sum(1 for r in out if r["source"] == "tracking_cache") == 0
    assert sum(1 for r in out if r["source"] == "tracking_db") == 2


def test_falls_back_to_cache_when_tracking_db_is_empty(monkeypatch):
    from app.services import dhl_logistics_projector as proj
    from app.services import tracking_db as tdb

    monkeypatch.setattr(tdb, "get_events_for_batch", lambda bid, direction=None: [])
    monkeypatch.setattr(tdb, "get_events_for_awb", lambda awb, direction=None: [])
    monkeypatch.setattr(
        proj, "_outbound_tracking_snapshot",
        lambda awb, batch_id: {"events": [
            {"timestamp": "2026-08-11T07:30:00+00:00", "description": "Picked up",
             "location": "Mumbai"},
        ]},
    )
    out = proj.assemble_shipment_timeline("SHIPMENT_TL_1", AUDIT)
    cache_rows = [r for r in out if r["source"] == "tracking_cache"]
    assert len(cache_rows) == 1
    assert cache_rows[0]["label"] == "Picked up"


def test_duplicate_events_in_the_same_minute_collapse(monkeypatch):
    from app.services import dhl_logistics_projector as proj
    from app.services import tracking_db as tdb

    dupes = DB_EVENTS + [dict(DB_EVENTS[0], event_time="2026-08-11T07:30:41+00:00")]
    monkeypatch.setattr(tdb, "get_events_for_batch", lambda bid, direction=None: dupes)
    monkeypatch.setattr(tdb, "get_events_for_awb", lambda awb, direction=None: [])
    out = proj.assemble_shipment_timeline("SHIPMENT_TL_1", AUDIT)
    assert sum(1 for r in out if r["event"] == "PICKED_UP") == 1


def test_events_without_a_timestamp_are_dropped(monkeypatch):
    from app.services import dhl_logistics_projector as proj
    from app.services import tracking_db as tdb

    monkeypatch.setattr(
        tdb, "get_events_for_batch",
        lambda bid, direction=None: [{"normalized_stage": "PICKED_UP", "description": "x"}],
    )
    monkeypatch.setattr(tdb, "get_events_for_awb", lambda awb, direction=None: [])
    out = proj.assemble_shipment_timeline("SHIPMENT_TL_1", AUDIT)
    assert all(r["ts"] for r in out)
    assert all(r["source"] == "audit_timeline" for r in out)


def test_endpoint_returns_unified_timeline_additively(tmp_path, monkeypatch):
    """The existing `timeline` key must keep its exact contract."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import routes_tracking as rt
    from app.auth.dependencies import get_current_user
    from app.services import batch_service, tracking_db as tdb

    d = tmp_path / "SHIPMENT_TL_1"
    d.mkdir(parents=True)
    (d / "audit.json").write_text(json.dumps(AUDIT), encoding="utf-8")
    monkeypatch.setattr(batch_service, "get_output_dir", lambda bid: tmp_path / bid)
    monkeypatch.setattr(tdb, "get_events_for_batch", lambda bid, direction=None: DB_EVENTS)
    monkeypatch.setattr(tdb, "get_events_for_awb", lambda awb, direction=None: [])

    app = FastAPI()
    app.include_router(rt.router)
    app.dependency_overrides[get_current_user] = lambda: {"role": "logistics"}
    try:
        r = TestClient(app).get("/api/v1/tracking/shipment/SHIPMENT_TL_1/timeline")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert r.status_code == 200
    body = r.json()
    assert body["timeline"] == AUDIT["timeline"]
    assert len(body["unified_timeline"]) == 4
    assert {row["source"] for row in body["unified_timeline"]} == {
        "audit_timeline", "tracking_db",
    }


# ── Frontend contract pins (source-grep) ─────────────────────────────────────

from pathlib import Path

_V2 = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"


def test_unified_timeline_is_one_shared_renderer():
    """One renderer in the shared primitives file — not a copy per page."""
    src = (_V2 / "components.jsx").read_text(encoding="utf-8")
    assert "function UnifiedTimeline(" in src
    assert 'data-testid="unified-timeline"' in src
    assert 'data-testid="unified-timeline-event"' in src
    assert 'data-testid="unified-timeline-empty"' in src
    for tag in ("audit_timeline", "tracking_db", "tracking_cache"):
        assert tag in src, tag
    assert "UnifiedTimeline," in src.split("Object.assign(window", 1)[1], "not exported"


def test_both_pages_render_the_shared_unified_timeline():
    for name in ("shipping-ops.jsx", "shipment-detail-page.jsx"):
        src = (_V2 / name).read_text(encoding="utf-8")
        # reuses the existing transport wrapper — no second API layer
        assert "PzApi.getShipmentTimeline" in src, name
        assert "unified_timeline" in src, name
        assert "<UnifiedTimeline events={unified} />" in src, name
        assert "function UnifiedTimeline(" not in src, f"{name} redefines the renderer"


def test_existing_timeline_views_are_kept_not_replaced():
    """Lesson M: the unified stream is additive, it removes no capability."""
    ops = (_V2 / "shipping-ops.jsx").read_text(encoding="utf-8")
    assert 'data-testid="ship-ops-timeline-event"' in ops
    detail = (_V2 / "shipment-detail-page.jsx").read_text(encoding="utf-8")
    assert 'data-testid="timeline-milestones"' in detail
    assert 'data-testid="timeline-event-done"' in detail
