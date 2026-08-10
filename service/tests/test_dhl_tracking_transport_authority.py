"""DHL tracking = sole transport / Delivered authority.

Customs (SAD) and business (PZ) must never invent Delivered or latch old
Exception over newer carrier movement. Failed API refresh must not wipe
successful carrier evidence. Polling continues until carrier delivery.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.dhl_logistics_projector import (
    classify_inbound,
    project_inbound_row,
    _apply_latest_carrier_authority,
    _outbound_tracking_snapshot,
)
from app.services.tracking_service import (
    _derive_status_from_events,
    get_tracking_status,
)


def _ev(ts: str, loc: str, desc: str, stage: str | None = None) -> dict:
    d = {
        "timestamp": ts,
        "event_time": ts,
        "location": loc,
        "description": desc,
        "status": desc,
    }
    if stage:
        d["normalized_stage"] = stage
        d["stage"] = stage
    return d


def test_customs_complete_dhl_in_transit_stays_in_transit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.dhl_logistics_projector._storage_root",
        lambda: tmp_path,
    )
    batch = "SHIPMENT_AUTH_CUSTOMS_PZ"
    bdir = tmp_path / "outputs" / batch
    bdir.mkdir(parents=True)
    events = [
        _ev("2026-08-08T10:00:00+02:00", "WARSAW - PL", "Processed for clearance"),
        _ev("2026-08-09T12:00:00+02:00", "WARSAW - PL", "Departed Facility"),
    ]
    (bdir / "tracking_cache.json").write_text(
        json.dumps({
            "111": {
                "status": "in_transit",
                "status_label": "In Transit",
                "events": events,
                "api_status": "ok",
                "cached_at": "2026-08-10T12:00:00+00:00",
            }
        }),
        encoding="utf-8",
    )
    audit = {
        "batch_id": batch,
        "awb": "111",
        "clearance_status": "sad_received",
        "timeline": [
            {"event": "sad_received", "ts": "2026-08-08T08:00:00Z"},
            {"event": "pz_generated", "ts": "2026-08-08T09:00:00Z"},
        ],
        "tracking": {"status": "unknown"},
    }
    row = project_inbound_row(audit)
    assert row is not None
    assert row["classification"] == "active"
    assert row["transport_status"] != "Delivered"
    assert row["customs_complete"] is True
    assert "Delivered" != row["transport_status"]
    key, _ = _derive_status_from_events(events)
    assert key == "in_transit"


def test_pz_generated_does_not_mark_delivered():
    audit = {
        "batch_id": "B1",
        "awb": "222",
        "timeline": [{"event": "pz_generated"}],
        "tracking": {"status": "in_transit", "events": [
            _ev("2026-08-09T12:00:00Z", "WARSAW - PL", "In transit"),
        ]},
    }
    tracking = {
        "status": "in_transit",
        "events": audit["tracking"]["events"],
        "delivered_at": None,
        "exception": None,
    }
    assert classify_inbound(audit, tracking) == "active"


def test_old_exception_newer_movement_wins():
    out: dict = {
        "status": None,
        "status_label": None,
        "exception": "old",
        "delivered_at": None,
        "picked_up_at": None,
        "departed_at": None,
        "last_event": None,
        "last_location": None,
    }
    events = [
        _ev("2026-08-08T10:00:00Z", "WARSAW - PL", "Processed for clearance", "EXCEPTION"),
        _ev("2026-08-09T12:00:00Z", "LEIPZIG - DE", "Departed Facility", "DEPARTED_ORIGIN_HUB"),
    ]
    _apply_latest_carrier_authority(out, events)
    assert out["status"] == "in_transit"
    assert out["exception"] is None
    assert out["last_location"] == "LEIPZIG - DE"


def test_dhl_delivered_sets_delivered_and_freezes():
    events = [
        _ev("2026-08-01T10:00:00Z", "MUMBAI - IN", "Picked up", "PICKED_UP"),
        _ev("2026-08-05T14:00:00Z", "WARSAW - PL", "Delivered", "DELIVERED"),
    ]
    key, label = _derive_status_from_events(events)
    assert key == "delivered" and label == "Delivered"
    out: dict = {
        "status": None, "status_label": None, "exception": "x",
        "delivered_at": None, "picked_up_at": None, "departed_at": None,
        "last_event": None, "last_location": None,
    }
    _apply_latest_carrier_authority(out, events)
    assert out["status"] == "delivered"
    assert out["delivered_at"] is not None
    assert out["exception"] is None


def test_no_delivery_evidence_never_delivered():
    events = [
        _ev("2026-08-08T10:00:00Z", "WARSAW - PL", "Clearance processing complete"),
        _ev("2026-08-09T09:00:00Z", "WARSAW - PL", "Awaiting collection"),
    ]
    key, _ = _derive_status_from_events(events)
    assert key != "delivered"
    assert classify_inbound(
        {"awb": "333", "timeline": [{"event": "sad_received"}, {"event": "pz_generated"}]},
        {"status": key, "events": events, "delivered_at": None},
    ) != "delivered"


def test_failed_refresh_preserves_prior_events(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.tracking_service.settings.storage_root",
        tmp_path,
        raising=False,
    )
    # Minimal: write prior cache then force API failure
    bdir = tmp_path / "batch"
    bdir.mkdir()
    prior_events = [
        _ev("2026-08-09T12:00:00Z", "WARSAW - PL", "Departed Facility"),
    ]
    (bdir / "tracking_cache.json").write_text(
        json.dumps({
            "9998887776": {
                "status": "in_transit",
                "status_label": "In Transit",
                "events": prior_events,
                "api_status": "ok",
                "source": "dhl_api",
                "cached_at": "2026-08-10T10:00:00+00:00",
                "tracking_last_success_at": "2026-08-10T10:00:00+00:00",
            }
        }),
        encoding="utf-8",
    )

    def _boom(_tn):
        raise RuntimeError("429 Too Many Requests")

    monkeypatch.setattr("app.services.tracking_service._call_dhl", _boom)
    monkeypatch.setattr(
        "app.services.tracking_service.settings.dhl_tracking_api_status",
        "active",
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.tracking_service.settings.dhl_tracking_api_key",
        "k",
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.tracking_service.settings.dhl_tracking_api_secret",
        "s",
        raising=False,
    )

    result = get_tracking_status(
        "9998887776", carrier="DHL", cache_dir=bdir, refresh=True,
    )
    assert result.get("events"), "prior events must survive 429"
    assert result.get("status") == "in_transit"
    assert result.get("tracking_stale") is True
    assert result.get("api_status") == "failed"
    assert result.get("source") == "cache_stale"
    # Idempotent second refresh still preserves
    result2 = get_tracking_status(
        "9998887776", carrier="DHL", cache_dir=bdir, refresh=True,
    )
    assert result2.get("events")
    assert result2.get("status") == "in_transit"


def test_failed_empty_cache_falls_through_to_db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.dhl_logistics_projector._storage_root",
        lambda: tmp_path,
    )
    batch = "SHIPMENT_AUTH_FALLTHROUGH"
    bdir = tmp_path / "outputs" / batch
    bdir.mkdir(parents=True)
    (bdir / "tracking_cache.json").write_text(
        json.dumps({
            "555": {
                "status": "unknown",
                "events": [],
                "api_status": "failed",
                "source": "error",
                "cached_at": "2026-08-10T13:00:00+00:00",
            }
        }),
        encoding="utf-8",
    )
    db_events = [
        _ev("2026-08-08T10:00:00Z", "MUMBAI - IN", "Processed for clearance", "EXCEPTION"),
        _ev("2026-08-10T12:00:00Z", "WARSAW - PL", "Customs status updated", "CUSTOMS_UNDER_REVIEW"),
    ]

    class _FakeTdb:
        @staticmethod
        def get_events_for_awb(awb):
            return db_events if awb == "555" else []

        @staticmethod
        def get_events_for_batch(batch_id, direction="inbound"):
            return db_events

    monkeypatch.setattr(
        "app.services.dhl_logistics_projector.tracking_db",
        _FakeTdb,
        raising=False,
    )
    with patch.dict("sys.modules", {}):
        # Patch import inside snapshot
        import app.services.dhl_logistics_projector as proj
        monkeypatch.setattr(proj, "tracking_db", _FakeTdb, raising=False)
        # tracking_db imported as `from . import tracking_db`
        import app.services as svc_pkg
        monkeypatch.setattr(
            "app.services.tracking_db.get_events_for_awb",
            lambda awb: db_events if awb == "555" else [],
            raising=False,
        )
        monkeypatch.setattr(
            "app.services.tracking_db.get_events_for_batch",
            lambda batch_id, direction="inbound": db_events,
            raising=False,
        )

    snap = _outbound_tracking_snapshot("555", batch)
    assert snap["events"], "DB events must win over failed-empty cache"
    assert snap["status"] != "exception"
    assert snap["status"] in ("in_customs", "in_transit")
    assert snap["exception"] is None


def test_monitor_refreshes_tracking_when_not_delivered(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as mon

    batch = "SHIPMENT_AUTH_POLL"
    bdir = tmp_path / "outputs" / batch
    bdir.mkdir(parents=True)
    audit = {
        "batch_id": batch,
        "awb": "4444333322",
        "clearance_status": "sad_received",
        "carrier": "DHL",
        "timeline": [{"event": "sad_received"}, {"event": "pz_generated"}],
        "tracking": {"status": "in_transit"},
    }
    (bdir / "audit.json").write_text(json.dumps(audit), encoding="utf-8")

    monkeypatch.setattr(mon, "_all_audit_paths", lambda: [bdir / "audit.json"])
    monkeypatch.setattr(mon, "_is_active", lambda a: True)
    monkeypatch.setattr(mon.settings, "storage_root", tmp_path, raising=False)

    calls = []

    def _fake_gts(tn, carrier="DHL", cache_dir=None, refresh=False):
        calls.append({"tn": tn, "refresh": refresh, "cache_dir": str(cache_dir)})
        return {
            "status": "in_transit",
            "source": "cache",
            "api_status": "ok",
            "tracking_stale": False,
            "cached_at": "2026-08-10T12:00:00+00:00",
            "tracking_last_checked_at": "2026-08-10T12:00:00+00:00",
            "tracking_last_success_at": "2026-08-10T12:00:00+00:00",
        }

    monkeypatch.setattr(
        "app.services.tracking_service.get_tracking_status",
        _fake_gts,
    )
    # Avoid heavy email/ingestion side paths
    monkeypatch.setattr(
        mon,
        "run_ingestion_cycle",
        lambda: {"ok": True, "shipments": []},
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.email_ingestion_worker.run_ingestion_cycle",
        lambda: {"ok": True, "shipments": []},
    )
    monkeypatch.setattr(
        "app.services.email_intelligence_store.find_existing_email_context",
        lambda audit: None,
    )

    # Short-circuit remainder of scan loop after tracking refresh by making
    # subsequent steps cheap (detect_tracking_triggers etc. still run).
    monkeypatch.setattr(
        "app.services.tracking_intelligence.detect_tracking_triggers",
        lambda *a, **k: [],
    )

    out = mon.scan_active_shipments(force=True)
    assert calls, "non-delivered active AWB must invoke get_tracking_status"
    assert calls[0]["tn"] == "4444333322"
    assert calls[0]["refresh"] is False
    assert any(a.get("tracking_refresh") for a in out.get("actions") or [])
