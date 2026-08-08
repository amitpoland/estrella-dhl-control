"""Behavioral tests for DHL Logistics Control Tower read-only projector."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services import dhl_logistics_projector as proj


def _audit(**kwargs):
    base = {
        "batch_id": "SHIPMENT_TEST_1",
        "awb": "1111111111",
        "clearance_decision": {"path": "agency"},
        "clearance_status": "dsk_generated",
        "timeline": [
            {"ts": "2026-08-01T08:00:00+00:00", "event": "batch_created"},
            {"ts": "2026-08-01T10:00:00+00:00", "event": "dhl_email_received"},
        ],
    }
    base.update(kwargs)
    return base


def test_pz_complete_does_not_imply_physical_delivery():
    completed_customs = _audit(
        timeline=[
            {"ts": "2026-08-01T08:00:00+00:00", "event": "batch_created"},
            {"ts": "2026-08-02T08:00:00+00:00", "event": "zc429_received"},
            {"ts": "2026-08-02T12:00:00+00:00", "event": "pz_generated"},
        ]
    )
    assert proj.classify_inbound(completed_customs) == "active"
    row = proj.project_inbound_row(completed_customs)
    assert row["classification"] == "active"
    assert row["customs_complete"] is True
    assert row["transport_status"] != "Delivered"


def test_classify_inbound_delivered_via_timeline():
    delivered = _audit(
        timeline=[
            {"ts": "2026-08-01T08:00:00+00:00", "event": "batch_created"},
            {"ts": "2026-08-03T08:00:00+00:00", "event": "carrier_delivered"},
        ]
    )
    assert proj.classify_inbound(delivered) == "delivered"


def test_classify_inbound_excluded_awb():
    assert proj.classify_inbound(_audit(awb="5665916826")) == "excluded"


def test_canonical_delivered_overrides_booking_complete(monkeypatch):
    delivered_at = datetime(2026, 8, 4, 14, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        proj,
        "_outbound_tracking_snapshot",
        lambda awb, batch_id: {
            "status": "delivered",
            "status_label": "Delivered",
            "last_event": "Delivered",
            "last_location": "Warsaw",
            "events": [
                {"description": "Shipment picked up", "timestamp": "2026-07-28T10:00:00+00:00"},
                {"description": "Delivered", "timestamp": delivered_at.isoformat()},
            ],
            "delivered_at": delivered_at,
            "picked_up_at": datetime(2026, 7, 28, 10, 0, tzinfo=timezone.utc),
            "departed_at": None,
            "expected_delivery": None,
            "exception": None,
            "received_by": None,
            "source": "tracking_cache",
        },
    )
    row = proj.project_outbound_row({
        "tracking_ref": "1645568956",
        "batch_id": "SHIPMENT_OUT",
        "client_ref": "Client X",
        "state": "complete",
        "created_at": "2026-07-27T08:00:00Z",
        "do_not_use": 0,
    })
    assert row["classification"] == "delivered"
    assert row["transport_status"] == "Delivered"
    assert row["current_status"] == "Delivered"
    assert row["booking_state"] == "complete"
    assert row["stage_age_hours"] is None
    assert row["total_elapsed_hours"] == pytest.approx(7 * 24 + 4, abs=0.1)


def test_delivered_stage_age_null_and_total_freezes():
    now = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    row = proj.project_inbound_row(
        _audit(
            timeline=[
                {"ts": "2026-07-27T08:00:00+00:00", "event": "batch_created"},
                {"ts": "2026-08-04T10:00:00+00:00", "event": "carrier_delivered"},
            ]
        ),
        now=now,
    )
    assert row["classification"] == "delivered"
    assert row["stage_age_hours"] is None
    assert row["booking_to_delivery_hours"] == pytest.approx(8 * 24 + 2, abs=0.1)


def test_completed_without_delivery_excluded_from_transit_average():
    pz_only = {
        "direction": "inbound",
        "classification": "active",
        "awb": "PZONLY0001",
        "created_at_utc": "2026-08-01T08:00:00+00:00",
        "delivered_at_utc": None,
        "pickup_at_utc": None,
        "total_elapsed_hours": 999.0,
        "data_quality": [],
        "milestones": [],
    }
    delivered_ok = {
        "direction": "inbound",
        "classification": "delivered",
        "awb": "DELIVERED01",
        "created_at_utc": "2026-08-01T08:00:00+00:00",
        "delivered_at_utc": "2026-08-03T08:00:00+00:00",
        "pickup_at_utc": "2026-08-01T09:00:00+00:00",
        "total_elapsed_hours": 47.0,
        "data_quality": [],
        "milestones": [],
    }
    valid, _excluded = proj._collect_transit_hours([pz_only, delivered_ok])
    assert valid == [47.0]


def test_invalid_delivery_before_created_excluded():
    row = {
        "direction": "inbound",
        "classification": "delivered",
        "awb": "8523214840",
        "created_at_utc": "2026-08-05T10:00:00+00:00",
        "delivered_at_utc": "2026-08-01T08:00:00+00:00",
        "pickup_at_utc": "2026-07-30T08:00:00+00:00",
        "total_elapsed_hours": 48.0,
        "data_quality": ["invalid_timestamp_order_delivery_before_created"],
        "milestones": [],
    }
    valid, excluded = proj._collect_transit_hours([row])
    assert valid == []
    assert any(e["awb"] == "8523214840" for e in excluded)


def test_no_movement_12h_needs_attention():
    now = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    created = (now - timedelta(hours=15)).isoformat()
    row = proj.project_outbound_row({
        "tracking_ref": "BOOKEDONLY1",
        "batch_id": "SHIPMENT_B",
        "client_ref": "Client B",
        "state": "complete",
        "created_at": created,
        "do_not_use": 0,
    }, now=now)
    assert "complete" not in row["transport_status"].lower()
    assert row["classification"] == "active"
    assert "no_carrier_movement_12h" in row["attention_reasons"]
    assert row["needs_attention"] is True


def test_main_status_never_exposes_booking_complete(monkeypatch):
    monkeypatch.setattr(
        proj,
        "_outbound_tracking_snapshot",
        lambda *a, **k: {
            "status": None, "events": [], "delivered_at": None, "picked_up_at": None,
            "departed_at": None, "expected_delivery": None, "exception": None,
            "last_event": None, "last_location": None, "received_by": None, "source": None,
        },
    )
    row = proj.project_outbound_row({
        "tracking_ref": "1645568956",
        "batch_id": "X",
        "client_ref": "C",
        "state": "complete",
        "created_at": "2026-08-01T08:00:00Z",
        "do_not_use": 0,
    })
    assert row["current_status"] == "Pickup pending"
    assert row["transport_status"] == "Pickup pending"


def test_fixed_transitions_do_not_mix_predecessors():
    rows = [
        {
            "direction": "inbound",
            "pickup_at_utc": "2026-08-01T08:00:00+00:00",
            "delivered_at_utc": "2026-08-03T08:00:00+00:00",
            "created_at_utc": "2026-08-01T06:00:00+00:00",
            "milestones": [
                {"stage_id": "arrived_pl", "timestamp_utc": "2026-08-01T20:00:00+00:00"},
                {"stage_id": "dhl_email", "timestamp_utc": "2026-08-01T22:00:00+00:00"},
                {"stage_id": "dsk", "timestamp_utc": "2026-08-02T10:00:00+00:00"},
            ],
        },
        {
            "direction": "inbound",
            "pickup_at_utc": "2026-08-01T08:00:00+00:00",
            "delivered_at_utc": None,
            "created_at_utc": "2026-08-01T06:00:00+00:00",
            "milestones": [
                {"stage_id": "dhl_email", "timestamp_utc": "2026-08-01T22:00:00+00:00"},
                {"stage_id": "dsk", "timestamp_utc": "2026-08-02T10:00:00+00:00"},
            ],
        },
    ]
    stats = proj._fixed_transition_analytics(rows, proj._INBOUND_FIXED_TRANSITIONS)
    assert stats["poland_to_dhl_email"]["n"] == 1
    assert stats["dhl_email_to_dsk"]["n"] == 2
    assert stats["origin_pickup_to_delivered"]["n"] == 1


def test_delivered_today_includes_inbound_and_outbound():
    today = datetime.now(timezone.utc).astimezone(proj.POLAND_TZ).date()
    delivered_dt = datetime(
        today.year, today.month, today.day, 10, 0, tzinfo=proj.POLAND_TZ
    ).astimezone(timezone.utc)
    rows = [
        {"direction": "inbound", "classification": "delivered", "delivered_at_utc": delivered_dt.isoformat(), "awb": "IN1"},
        {"direction": "outbound", "classification": "delivered", "delivered_at_utc": delivered_dt.isoformat(), "awb": "OUT1"},
        {"direction": "inbound", "classification": "delivered", "delivered_at_utc": (delivered_dt - timedelta(days=2)).isoformat(), "awb": "OLD"},
        {"direction": "inbound", "classification": "active", "delivered_at_utc": None, "awb": "ACT", "customs_complete": True},
    ]
    today_w = datetime.now(timezone.utc).astimezone(proj.POLAND_TZ).date()
    delivered_today = []
    for r in rows:
        if r["classification"] != "delivered":
            continue
        dts = proj._parse_iso(r.get("delivered_at_utc"))
        if dts and dts.astimezone(proj.POLAND_TZ).date() == today_w:
            delivered_today.append(r)
    assert {r["awb"] for r in delivered_today} == {"IN1", "OUT1"}


def test_no_second_tracker_poller_in_source():
    src = Path(proj.__file__).read_text(encoding="utf-8")
    # Must reuse cache helper; must not import/call live tracker API
    assert "select_cached_tracking_record" in src
    assert "from .tracking_service import get_tracking_status" not in src
    assert "tracking_service.get_tracking_status" not in src
    assert "queue_email" not in src
    assert "create_shipment(" not in src
    assert "INSERT " not in src.upper()
    assert "UPDATE " not in src.upper()


def test_inbound_outbound_awb_isolation():
    inbound = proj.project_inbound_row(_audit(awb="INBOUND1111"))
    outbound = proj.project_outbound_row({
        "tracking_ref": "OUTBOUND2222",
        "batch_id": "SHIPMENT_X",
        "client_ref": "Client A",
        "state": "complete",
        "created_at": "2026-08-05T10:00:00Z",
        "do_not_use": 0,
    })
    assert inbound["direction"] == "inbound"
    assert outbound["direction"] == "outbound"
    assert inbound["awb"] == "INBOUND1111"
    assert outbound["awb"] == "OUTBOUND2222"


def test_duration_and_timezone_fields():
    now = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    row = proj.project_inbound_row(
        _audit(
            timeline=[
                {"ts": "2026-08-08T08:00:00+00:00", "event": "batch_created"},
                {"ts": "2026-08-08T10:07:00+00:00", "event": "dhl_email_received"},
            ]
        ),
        now=now,
    )
    assert row["created_at_warsaw"] is not None
    assert row["milestones"]
    assert row["milestones"][1]["duration_from_previous_hours"] == pytest.approx(2.12, abs=0.02)
    assert row["stage_age_hours"] is not None
    assert row["transport_status"]


def test_missing_timestamps_do_not_invent_expected_delivery():
    row = proj.project_inbound_row(_audit())
    assert row["expected_delivery_utc"] is None
    assert row["received_by"] is None


def test_pz_complete_stays_in_active_filter(monkeypatch, tmp_path):
    audits = [
        _audit(awb="ACTIVE0001", batch_id="SHIPMENT_A"),
        _audit(
            awb="DONE000002",
            batch_id="SHIPMENT_B",
            timeline=[
                {"ts": "2026-08-01T08:00:00+00:00", "event": "batch_created"},
                {"ts": "2026-08-02T08:00:00+00:00", "event": "zc429_received"},
                {"ts": "2026-08-02T12:00:00+00:00", "event": "pz_generated"},
            ],
        ),
    ]
    monkeypatch.setattr(
        proj, "_audit_paths",
        lambda: [Path(f"virtual/{a['batch_id']}/audit.json") for a in audits],
    )
    monkeypatch.setattr(
        proj, "_read_audit",
        lambda path: next(a for a in audits if a["batch_id"] == path.parent.name),
    )
    monkeypatch.setattr(proj, "_carrier_db_path", lambda: tmp_path / "missing.db")
    active = proj.project_logistics(view="active", direction="inbound")
    awbs = {r["awb"] for r in active["rows"]}
    assert "ACTIVE0001" in awbs
    assert "DONE000002" in awbs
    delivered = proj.project_logistics(view="delivered", direction="inbound")
    assert "DONE000002" not in {r["awb"] for r in delivered["rows"]}


def test_exception_remains_visible_in_active():
    row = proj.project_outbound_row({
        "tracking_ref": "EXC3333333",
        "batch_id": "SHIPMENT_E",
        "client_ref": "Client E",
        "state": "failed",
        "error": "booking failed",
        "created_at": "2026-08-05T10:00:00Z",
        "do_not_use": 0,
    })
    assert row["classification"] == "exception"
    assert row["exception"]


def test_csv_export_includes_filters():
    rows = [proj.project_inbound_row(_audit())]
    body = proj.rows_to_logistics_csv(rows, filters={"direction": "inbound", "view": "active"})
    text = body.decode("utf-8-sig")
    assert text.startswith("# filters_applied:")
    assert "direction=inbound" in text
    assert "transport_status" in text
    assert "1111111111" in text


def test_routes_require_api_key(monkeypatch):
    from fastapi.testclient import TestClient
    from app.core.config import settings
    from app.main import app
    monkeypatch.setattr(settings, "api_key", "test-logistics-key-only")
    monkeypatch.setattr(settings, "environment", "prod")
    client = TestClient(app)
    assert client.get("/api/v1/dhl/logistics/projection").status_code == 401
    assert client.get("/api/v1/dhl/logistics/export/csv").status_code == 401
    r3 = client.get(
        "/api/v1/dhl/logistics/projection",
        headers={"X-API-Key": "test-logistics-key-only"},
    )
    assert r3.status_code == 200


def test_routes_registered():
    from app.main import app
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/v1/dhl/logistics/projection" in paths
    assert "/api/v1/dhl/logistics/export/csv" in paths
    assert "/api/v1/dhl/logistics/shipments/{awb}" in paths
