"""Behavioral tests for DHL Logistics Control Tower read-only projector."""
from __future__ import annotations

import json
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


def test_classify_inbound_carrier_nonterminal_blocks_timeline_delivered():
    """Tower must not label Delivered when carrier snapshot is non-terminal."""
    audit = _audit(
        timeline=[
            {"ts": "2026-08-01T08:00:00+00:00", "event": "batch_created"},
            {"ts": "2026-08-03T08:00:00+00:00", "event": "carrier_delivered"},
        ]
    )
    tracking = {
        "status": "in_transit",
        "source": "tracking_cache",
        "events": [{"description": "In transit", "timestamp": "2026-08-02T08:00:00+00:00"}],
        "delivered_at": None,
    }
    assert proj.classify_inbound(audit, tracking) == "active"


def test_dhl_email_kpi_prefers_received_at_not_discovery_timeline():
    audit = _audit(
        dhl_email={
            "received": True,
            "received_at": "2026-05-13T09:31:52.331000+00:00",
            "source": "email_evidence_v2",
        },
        timeline=[
            {"ts": "2026-05-13T07:16:37+00:00", "event": "carrier_arrived_poland"},
            {"ts": "2026-08-10T10:13:46.368566+00:00", "event": "dhl_email_received"},
            {"ts": "2026-08-10T10:14:00+00:00", "event": "dhl_inbox_scanned"},
        ],
    )
    row = proj.project_inbound_row(audit)
    assert row["dhl_email_kpi_at_utc"].startswith("2026-05-13T09:31:52")
    assert row["dhl_email_kpi_source"] == "audit.dhl_email.received_at"
    assert row["dhl_email_kpi_source_class"] == "AUTHORITATIVE_EVENT_TIME"
    assert row["dhl_email_kpi_exclude_reason"] is None
    email_ms = next(m for m in row["milestones"] if m["stage_id"] == "dhl_email")
    assert email_ms["timestamp_utc"].startswith("2026-05-13")
    assert email_ms["authority"] == "audit.dhl_email.received_at"


def test_dhl_inbox_scanned_cannot_satisfy_dhl_email_kpi():
    audit = _audit(
        dhl_email={},
        timeline=[
            {"ts": "2026-05-13T07:16:37+00:00", "event": "carrier_arrived_poland"},
            {"ts": "2026-08-10T10:14:00+00:00", "event": "dhl_inbox_scanned"},
        ],
    )
    row = proj.project_inbound_row(audit)
    assert row["dhl_email_kpi_at_utc"] is None
    assert row["dhl_email_kpi_exclude_reason"] == "missing_original_dhl_email_timestamp"
    assert "missing_original_dhl_email_timestamp" in row["data_quality"]
    assert not any(m["stage_id"] == "dhl_email" for m in row["milestones"])
    # Source map pins discovery as non-KPI
    assert proj.DHL_EMAIL_MILESTONE_SOURCE_MAP["timeline.dhl_inbox_scanned"] == (
        "DISCOVERY/BACKFILL_TIME"
    )
    assert "dhl_inbox_scanned" not in proj._INBOUND_MILESTONES[1][2]


def test_pickup_to_poland_excludes_delivered_before_poland():
    rows = [
        {
            "pickup_at_utc": "2026-02-10T14:32:00+00:00",
            "delivered_at_utc": "2026-02-13T15:09:00+00:00",
            "milestones": [
                {"stage_id": "arrived_pl", "timestamp_utc": "2026-05-17T17:30:12+00:00"},
            ],
        },
        {
            "pickup_at_utc": "2026-08-01T08:00:00+00:00",
            "delivered_at_utc": "2026-08-03T08:00:00+00:00",
            "milestones": [
                {"stage_id": "arrived_pl", "timestamp_utc": "2026-08-02T08:00:00+00:00"},
            ],
        },
    ]
    stats = proj._fixed_transition_analytics(rows, proj._INBOUND_FIXED_TRANSITIONS)
    pl = stats["origin_pickup_to_poland"]
    assert pl["n"] == 1
    assert pl["exclusion_reason_counts"]["lifecycle_mismatch_delivered_before_poland"] == 1


def test_poland_to_dhl_email_excludes_missing_original_timestamp():
    rows = [
        {
            "direction": "inbound",
            "dhl_email_kpi_at_utc": "2026-08-01T22:00:00+00:00",
            "dhl_email_kpi_exclude_reason": None,
            "milestones": [
                {"stage_id": "arrived_pl", "timestamp_utc": "2026-08-01T20:00:00+00:00"},
                {
                    "stage_id": "dhl_email",
                    "timestamp_utc": "2026-08-01T22:00:00+00:00",
                    "kpi_usable": True,
                },
            ],
        },
        {
            "direction": "inbound",
            "dhl_email_kpi_at_utc": None,
            "dhl_email_kpi_exclude_reason": "missing_original_dhl_email_timestamp",
            "milestones": [
                {"stage_id": "arrived_pl", "timestamp_utc": "2026-08-01T20:00:00+00:00"},
            ],
        },
    ]
    stats = proj._fixed_transition_analytics(rows, proj._INBOUND_FIXED_TRANSITIONS)
    pl = stats["poland_to_dhl_email"]
    assert pl["n"] == 1
    assert pl["exclusion_reason_counts"]["missing_original_dhl_email_timestamp"] == 1


def test_failed_tracking_cache_blocks_timeline_delivered(tmp_path, monkeypatch):
    """2824111912 class: cache exists but non-terminal → never Tower Delivered."""
    batch = "SHIPMENT_2824111912_TEST"
    awb = "2824111912"
    batch_dir = tmp_path / "outputs" / batch
    batch_dir.mkdir(parents=True)
    (batch_dir / "tracking_cache.json").write_text(
        json.dumps({
            awb: {
                "tracking_no": awb,
                "status": "unknown",
                "source": "error",
                "api_status": "failed",
                "events": [],
                "error": "401",
                "cached_at": "2026-05-06T09:48:14Z",
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(proj, "_storage_root", lambda: tmp_path)
    audit = _audit(
        awb=awb,
        batch_id=batch,
        timeline=[
            {"ts": "2026-04-26T23:53:04+00:00", "event": "batch_created"},
            {"ts": "2026-04-29T03:16:43+00:00", "event": "shipment_delivered"},
        ],
        dhl_email={
            "received": True,
            "received_at": "2026-03-12T07:55:42Z",
            "source": "active_shipment_monitor",
            "subject": "Fwd: [T#1WA2603100000499] Re:- Agencja Celna DHL - przesyłka numer: 2824221912",
        },
    )
    row = proj.project_inbound_row(audit)
    assert row["classification"] != "delivered"
    assert row["transport_status"] != "Delivered"
    assert "delivered_claim_without_carrier_terminal" in row["data_quality"]
    assert row["dhl_email_kpi_exclude_reason"] == "mismatched_awb_in_dhl_email_subject"
    assert not any(m["stage_id"] == "delivered" for m in row["milestones"])


def test_manual_admin_received_at_defers_to_email_evidence(monkeypatch):
    """2759203252 class: manual_admin apply-time is not original receipt."""
    monkeypatch.setattr(
        proj,
        "_email_evidence_dhl_request_ts",
        lambda awb: datetime(2026, 2, 18, 13, 53, 18, tzinfo=timezone.utc),
    )
    audit = _audit(
        awb="2759203252",
        dhl_email={
            "received": True,
            "received_at": "2026-05-01T12:57:12.475765+00:00",
            "source": "manual_admin",
            "subject": "[T#1WA2602160000033] - Agencja Celna DHL - przesyłka numer: 2759203252",
        },
        timeline=[
            {"ts": "2026-05-01T12:57:12+00:00", "event": "dhl_email_received"},
        ],
    )
    kpi = proj.resolve_dhl_email_kpi_timestamp(audit)
    assert kpi["kpi_usable"] is True
    assert kpi["source"] == "email_evidence.dhl_request.timestamp"
    assert kpi["timestamp"].isoformat().startswith("2026-02-18T13:53:18")


def test_pre_arrival_customs_contact_counts_as_zero_hours():
    rows = [
        {
            "awb": "8418664660",
            "pickup_at_utc": "2026-08-03T14:18:00+00:00",
            "delivered_at_utc": None,
            "dhl_email_kpi_at_utc": "2026-08-06T07:17:38+00:00",
            "dhl_email_subject": "T#1WA2608060000165 - Agencja Celna DHL - przesyłka numer: 8418664660",
            "milestones": [
                {"stage_id": "arrived_pl", "timestamp_utc": "2026-08-08T10:35:55+00:00"},
                {"stage_id": "dhl_email", "timestamp_utc": "2026-08-06T07:17:38+00:00", "kpi_usable": True},
            ],
        },
        {
            "awb": "8580992114",
            "pickup_at_utc": "2026-02-10T14:32:00+00:00",
            "delivered_at_utc": "2026-02-13T15:09:00+00:00",
            "dhl_email_kpi_at_utc": "2026-02-13T11:06:46+00:00",
            "dhl_email_subject": "",
            "milestones": [
                {"stage_id": "arrived_pl", "timestamp_utc": "2026-05-17T17:30:12+00:00"},
                {"stage_id": "dhl_email", "timestamp_utc": "2026-02-13T11:06:46+00:00", "kpi_usable": True},
            ],
        },
    ]
    stats = proj._fixed_transition_analytics(rows, proj._INBOUND_FIXED_TRANSITIONS)
    pl = stats["poland_to_dhl_email"]
    assert pl["n"] == 1
    assert pl["average"] == 0.0
    assert pl["exclusion_reason_counts"]["lifecycle_mismatch_email_vs_late_poland"] == 1


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
            dhl_email={
                "received": True,
                "received_at": "2026-08-08T10:07:00+00:00",
                "source": "email_evidence_v2",
            },
            timeline=[
                {"ts": "2026-08-08T08:00:00+00:00", "event": "batch_created"},
                {"ts": "2026-08-08T12:00:00+00:00", "event": "dhl_email_received"},
            ]
        ),
        now=now,
    )
    assert row["created_at_warsaw"] is not None
    assert row["milestones"]
    email_ms = next(m for m in row["milestones"] if m["stage_id"] == "dhl_email")
    created_ms = next(m for m in row["milestones"] if m["stage_id"] == "created")
    assert email_ms["authority"] == "audit.dhl_email.received_at"
    # KPI stamp is received_at (10:07), not discovery timeline (12:00)
    assert email_ms["timestamp_utc"].startswith("2026-08-08T10:07:00")
    assert created_ms["timestamp_utc"].startswith("2026-08-08T08:00:00")
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


def test_historical_unresolved_requires_full_combination(monkeypatch):
    """Stale + no movement + customs/PZ complete → residue; age alone does not."""
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    stale_created = (now - timedelta(days=95)).isoformat()
    monkeypatch.setattr(
        proj,
        "_inbound_tracking_snapshot",
        lambda *a, **k: {
            "status": None, "events": [], "delivered_at": None, "picked_up_at": None,
            "departed_at": None, "expected_delivery": None, "exception": None,
            "last_event": None, "last_location": None, "received_by": None, "source": None,
            "arrived_pl_at": None,
        },
    )
    residue = _audit(
        awb="OLDRESIDUE1",
        batch_id="SHIPMENT_RESIDUE",
        timeline=[
            {"ts": stale_created, "event": "batch_created"},
            {"ts": (now - timedelta(days=90)).isoformat(), "event": "zc429_received"},
            {"ts": (now - timedelta(days=89)).isoformat(), "event": "pz_generated"},
        ],
    )
    row = proj.project_inbound_row(residue, now=now)
    assert row["classification"] == "historical_unresolved"
    assert row["transport_status"] != "Delivered"
    assert row["needs_attention"] is False
    assert row["customs_complete"] is True

    # Age alone (customs not complete) must stay operational active.
    old_open = _audit(
        awb="OLDOPEN0001",
        batch_id="SHIPMENT_OLD_OPEN",
        timeline=[
            {"ts": stale_created, "event": "batch_created"},
            {"ts": (now - timedelta(days=94)).isoformat(), "event": "dhl_email_received"},
        ],
        clearance_status="dsk_generated",
    )
    open_row = proj.project_inbound_row(old_open, now=now)
    assert open_row["classification"] == "active"
    assert open_row["customs_complete"] is False


def test_movement_keeps_row_operational_not_historical(monkeypatch):
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    stale_created = (now - timedelta(days=95)).isoformat()
    monkeypatch.setattr(
        proj,
        "_inbound_tracking_snapshot",
        lambda *a, **k: {
            "status": "in_customs",
            "events": [
                {"description": "Arrived at facility", "timestamp": (now - timedelta(days=2)).isoformat()},
            ],
            "delivered_at": None,
            "picked_up_at": now - timedelta(days=3),
            "departed_at": now - timedelta(days=2),
            "expected_delivery": None,
            "exception": None,
            "last_event": "Customs clearance",
            "last_location": "PL",
            "received_by": None,
            "source": "tracking_cache",
            "arrived_pl_at": now - timedelta(days=2),
        },
    )
    row = proj.project_inbound_row(
        _audit(
            awb="5831878861",
            batch_id="SHIPMENT_LIVE",
            timeline=[
                {"ts": stale_created, "event": "batch_created"},
                {"ts": (now - timedelta(days=90)).isoformat(), "event": "pz_generated"},
            ],
        ),
        now=now,
    )
    assert row["classification"] == "active"
    assert row["transport_status"] == "In Customs"


def test_historical_excluded_from_active_and_attention_kpis(tmp_path, monkeypatch):
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    stale = (now - timedelta(days=98)).isoformat()
    fresh = (now - timedelta(days=3)).isoformat()
    monkeypatch.setattr(proj, "_now_utc", lambda: now)

    def _snap(awb, batch_id=None, audit=None):
        empty = {
            "status": None, "events": [], "delivered_at": None, "picked_up_at": None,
            "departed_at": None, "expected_delivery": None, "exception": None,
            "last_event": None, "last_location": None, "received_by": None, "source": None,
            "arrived_pl_at": None,
        }
        if awb == "5831878861":
            return {
                **empty,
                "status": "in_customs",
                "picked_up_at": now - timedelta(days=1),
                "events": [{"description": "In transit", "timestamp": fresh}],
                "last_event": "In customs",
                "source": "tracking_cache",
            }
        return empty

    monkeypatch.setattr(proj, "_inbound_tracking_snapshot", _snap)
    audits = [
        _audit(
            awb="5831878861",
            batch_id="SHIPMENT_OP",
            timeline=[
                {"ts": fresh, "event": "batch_created"},
                {"ts": fresh, "event": "dhl_email_received"},
            ],
        ),
        _audit(
            awb="OLDRESIDUE7",
            batch_id="SHIPMENT_HIST",
            timeline=[
                {"ts": stale, "event": "batch_created"},
                {"ts": (now - timedelta(days=90)).isoformat(), "event": "zc429_received"},
                {"ts": (now - timedelta(days=89)).isoformat(), "event": "pz_generated"},
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
    hist = proj.project_logistics(view="historical", direction="inbound")
    assert "5831878861" in {r["awb"] for r in active["rows"]}
    assert "OLDRESIDUE7" not in {r["awb"] for r in active["rows"]}
    assert "OLDRESIDUE7" in {r["awb"] for r in hist["rows"]}
    assert active["kpis"]["historical_unresolved"] == 1
    assert active["kpis"]["active_inbound"] == 1
    assert active["kpis"]["operational_active"] >= 1
    # Residue must not inflate Needs Attention
    assert all(r["awb"] != "OLDRESIDUE7" for r in active["rows"] if r.get("needs_attention"))


def test_historical_unresolved_uses_timeline_fallback_when_batch_created_missing(monkeypatch):
    """Missing batch_created must not strand customs-complete residue as Operational Active."""
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        proj,
        "_inbound_tracking_snapshot",
        lambda *a, **k: {
            "status": None, "events": [], "delivered_at": None, "picked_up_at": None,
            "departed_at": None, "expected_delivery": None, "exception": None,
            "last_event": None, "last_location": None, "received_by": None, "source": None,
            "arrived_pl_at": None,
        },
    )
    audit = {
        "batch_id": "SHIPMENT_6876258325_2026-04_871248dc",
        "awb": "6876258325",
        "clearance_status": "pz_generated",
        "timeline": [
            {"ts": "2026-04-27T09:24:44+00:00", "event": "shipment_rechecked"},
            {"ts": "2026-05-04T08:45:44+00:00", "event": "pz_generated"},
        ],
    }
    row = proj.project_inbound_row(audit, now=now)
    assert row["classification"] == "historical_unresolved"
    assert row["created_at_utc"] is not None
    assert row["needs_attention"] is False


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
