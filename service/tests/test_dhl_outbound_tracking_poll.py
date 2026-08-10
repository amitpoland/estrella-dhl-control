"""Outbound AWBs must enter the same get_tracking_status poll authority.

Inbound #1174 protections stay intact. Booking complete ≠ Delivered.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest


def _seed_carrier_db(db_path: Path, rows: list[dict]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS carrier_shipments (
            idempotency_key TEXT PRIMARY KEY,
            batch_id TEXT,
            mode TEXT,
            state TEXT,
            error TEXT,
            simulated INTEGER,
            created_at TEXT,
            updated_at TEXT,
            tracking_ref TEXT,
            do_not_use INTEGER DEFAULT 0,
            client_ref TEXT
        )
        """
    )
    for i, r in enumerate(rows):
        con.execute(
            "INSERT INTO carrier_shipments("
            "idempotency_key, batch_id, mode, state, simulated, created_at, updated_at,"
            "tracking_ref, do_not_use, client_ref) VALUES (?,?,?,?,0,?,?,?,?,?)",
            (
                r.get("idempotency_key") or f"k{i}",
                r["batch_id"],
                "live",
                r.get("state") or "complete",
                "2026-08-10T10:00:00Z",
                "2026-08-10T10:00:00Z",
                r["tracking_ref"],
                int(r.get("do_not_use") or 0),
                r.get("client_ref") or "Client",
            ),
        )
    con.commit()
    con.close()


def _write_cache(batch_dir: Path, awb: str, rec: dict) -> None:
    batch_dir.mkdir(parents=True, exist_ok=True)
    path = batch_dir / "tracking_cache.json"
    cache = {}
    if path.exists():
        cache = json.loads(path.read_text(encoding="utf-8"))
    cache[awb] = rec
    path.write_text(json.dumps(cache), encoding="utf-8")


def test_outbound_shipment_accepted_is_candidate(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as mon

    monkeypatch.setattr(mon.settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(mon.settings, "carrier_storage_root", tmp_path / "carrier", raising=False)
    db = tmp_path / "carrier" / "carrier_shipments.db"
    _seed_carrier_db(db, [{
        "tracking_ref": "1555081404",
        "batch_id": "SHIPMENT_OUT_1",
        "state": "complete",
    }])
    cands = mon.list_outbound_tracking_candidates()
    assert any(c["awb"] == "1555081404" for c in cands)


def test_outbound_processed_in_transit_is_polled(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as mon

    monkeypatch.setattr(mon.settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(mon.settings, "carrier_storage_root", tmp_path / "carrier", raising=False)
    monkeypatch.setattr(mon, "_all_audit_paths", lambda: [])
    monkeypatch.setattr(
        "app.services.email_ingestion_worker.run_ingestion_cycle",
        lambda: {"ok": True, "shipments": []},
    )
    _seed_carrier_db(tmp_path / "carrier" / "carrier_shipments.db", [{
        "tracking_ref": "1555081404",
        "batch_id": "SHIPMENT_OUT_1",
        "state": "complete",
    }])
    calls = []

    def _fake_poll(awb, *, batch_id, carrier="DHL"):
        calls.append({"awb": awb, "batch_id": batch_id})
        return {
            "status": "in_transit",
            "status_label": "In Transit",
            "source": "dhl_api",
            "events": [{"timestamp": "2026-08-10T17:59:00+02:00",
                        "description": "Processed at WARSAW",
                        "location": "WARSAW - PL"}],
            "cached_at": "2026-08-10T16:00:00+00:00",
            "tracking_last_success_at": "2026-08-10T16:00:00+00:00",
        }

    monkeypatch.setattr(mon, "_poll_awb_tracking", _fake_poll)
    out = mon.scan_active_shipments(force=True)
    assert calls and calls[0]["awb"] == "1555081404"
    assert out["outbound_tracking"]["polled"] == 1
    assert any(a.get("awb") == "1555081404" for a in out["actions"])


def test_outbound_exception_still_polled(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as mon

    monkeypatch.setattr(mon.settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(mon.settings, "carrier_storage_root", tmp_path / "carrier", raising=False)
    monkeypatch.setattr(mon, "_all_audit_paths", lambda: [])
    monkeypatch.setattr(
        "app.services.email_ingestion_worker.run_ingestion_cycle",
        lambda: {"ok": True, "shipments": []},
    )
    batch = "SHIPMENT_OUT_EXC"
    _seed_carrier_db(tmp_path / "carrier" / "carrier_shipments.db", [{
        "tracking_ref": "9998887776",
        "batch_id": batch,
        "state": "complete",
    }])
    _write_cache(tmp_path / "outputs" / batch, "9998887776", {
        "status": "exception",
        "status_label": "Exception",
        "events": [{"timestamp": "2026-08-09T10:00:00Z", "description": "On hold"}],
        "api_status": "ok",
        "cached_at": "2026-08-10T10:00:00+00:00",
    })
    calls = []
    monkeypatch.setattr(
        mon,
        "_poll_awb_tracking",
        lambda awb, *, batch_id, carrier="DHL": calls.append(awb) or {
            "status": "exception", "source": "cache",
        },
    )
    mon.scan_active_shipments(force=True)
    assert "9998887776" in calls


def test_outbound_delivered_excluded_next_sweep_zero_calls(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as mon

    monkeypatch.setattr(mon.settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(mon.settings, "carrier_storage_root", tmp_path / "carrier", raising=False)
    monkeypatch.setattr(mon, "_all_audit_paths", lambda: [])
    monkeypatch.setattr(
        "app.services.email_ingestion_worker.run_ingestion_cycle",
        lambda: {"ok": True, "shipments": []},
    )
    batch = "SHIPMENT_OUT_DEL"
    awb = "1111222233"
    _seed_carrier_db(tmp_path / "carrier" / "carrier_shipments.db", [{
        "tracking_ref": awb,
        "batch_id": batch,
        "state": "complete",
    }])
    calls = []

    def _fake_poll(tn, *, batch_id, carrier="DHL"):
        calls.append(tn)
        # Persist terminal delivery into cache (restart-safe)
        _write_cache(tmp_path / "outputs" / batch, tn, {
            "status": "delivered",
            "status_label": "Delivered",
            "events": [{"timestamp": "2026-08-10T18:00:00Z", "description": "Delivered"}],
            "api_status": "ok",
            "cached_at": "2026-08-10T18:00:00+00:00",
            "tracking_terminal": True,
        })
        return {
            "status": "delivered",
            "tracking_terminal": True,
            "source": "dhl_api",
            "cached_at": "2026-08-10T18:00:00+00:00",
        }

    monkeypatch.setattr(mon, "_poll_awb_tracking", _fake_poll)
    out1 = mon.scan_active_shipments(force=True)
    assert awb in calls
    assert out1["outbound_tracking"]["polled"] == 1

    calls.clear()
    out2 = mon.scan_active_shipments(force=True)
    assert awb not in calls
    assert out2["outbound_tracking"]["polled"] == 0
    assert out2["outbound_tracking"]["candidates"] == 0


def test_restart_delivered_remains_excluded(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as mon

    monkeypatch.setattr(mon.settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(mon.settings, "carrier_storage_root", tmp_path / "carrier", raising=False)
    batch = "SHIPMENT_OUT_DEL2"
    awb = "4444555566"
    _seed_carrier_db(tmp_path / "carrier" / "carrier_shipments.db", [{
        "tracking_ref": awb,
        "batch_id": batch,
        "state": "complete",
    }])
    _write_cache(tmp_path / "outputs" / batch, awb, {
        "status": "delivered",
        "events": [{"timestamp": "2026-08-01T12:00:00Z", "description": "Delivered"}],
        "api_status": "ok",
        "cached_at": "2026-08-01T12:00:00+00:00",
    })
    assert mon.is_carrier_tracking_terminal(awb, batch) is True
    assert not any(c["awb"] == awb for c in mon.list_outbound_tracking_candidates())


def test_booking_complete_not_delivered_still_candidate(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as mon

    monkeypatch.setattr(mon.settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(mon.settings, "carrier_storage_root", tmp_path / "carrier", raising=False)
    _seed_carrier_db(tmp_path / "carrier" / "carrier_shipments.db", [{
        "tracking_ref": "1555081404",
        "batch_id": "SHIPMENT_OUT_1",
        "state": "complete",  # booking complete — NOT carrier delivered
    }])
    assert any(c["awb"] == "1555081404" for c in mon.list_outbound_tracking_candidates())


def test_empty_not_found_cache_forces_refresh(tmp_path, monkeypatch):
    from app.services import tracking_service as ts

    bdir = tmp_path / "batch"
    bdir.mkdir()
    (bdir / "tracking_cache.json").write_text(
        json.dumps({
            "1555081404": {
                "status": "not_found",
                "source": "dhl_api_404",
                "events": [],
                "cached_at": "2026-08-10T16:38:19+00:00",  # "fresh" but empty
                "available": False,
            }
        }),
        encoding="utf-8",
    )
    called = {"n": 0}

    def _fake_dhl(_tn):
        called["n"] += 1
        return {
            "status": "in_transit",
            "status_label": "In Transit",
            "events": [{
                "timestamp": "2026-08-10T17:59:00+02:00",
                "description": "Processed at WARSAW",
                "location": "WARSAW - PL",
            }],
            "source": "dhl_unified_api",
            "last_location": "WARSAW - PL",
        }

    monkeypatch.setattr(ts, "_call_dhl", _fake_dhl)
    monkeypatch.setattr(ts.settings, "dhl_tracking_api_status", "active", raising=False)
    monkeypatch.setattr(ts.settings, "dhl_tracking_api_key", "k", raising=False)
    monkeypatch.setattr(ts.settings, "dhl_tracking_api_secret", "s", raising=False)

    result = ts.get_tracking_status(
        "1555081404", carrier="DHL", cache_dir=bdir, refresh=False,
    )
    assert called["n"] == 1, "empty not_found must not TTL-block refresh"
    assert result.get("status") == "in_transit"


def test_projector_skips_empty_not_found_cache(tmp_path, monkeypatch):
    from app.services import dhl_logistics_projector as proj

    monkeypatch.setattr(proj, "_storage_root", lambda: tmp_path)
    batch = "SHIPMENT_OUT_1"
    bdir = tmp_path / "outputs" / batch
    bdir.mkdir(parents=True)
    (bdir / "tracking_cache.json").write_text(
        json.dumps({
            "1555081404": {
                "status": "not_found",
                "source": "dhl_api_404",
                "events": [],
                "cached_at": "2026-08-10T16:38:19Z",
            }
        }),
        encoding="utf-8",
    )
    assert proj._cache_record_is_failed_empty(
        json.loads((bdir / "tracking_cache.json").read_text(encoding="utf-8"))["1555081404"]
    ) is True
