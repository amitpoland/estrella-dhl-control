"""Tests for DHL Logistics Control Tower read-only projector."""
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


def test_classify_inbound_active_vs_completed_by_customs():
    active = _audit()
    assert proj.classify_inbound(active) == "active"

    completed = _audit(
        timeline=[
            {"ts": "2026-08-01T08:00:00+00:00", "event": "batch_created"},
            {"ts": "2026-08-02T08:00:00+00:00", "event": "zc429_received"},
            {"ts": "2026-08-02T12:00:00+00:00", "event": "pz_generated"},
        ]
    )
    assert proj.classify_inbound(completed) == "completed"


def test_classify_inbound_delivered_via_timeline():
    delivered = _audit(
        timeline=[
            {"ts": "2026-08-01T08:00:00+00:00", "event": "batch_created"},
            {"ts": "2026-08-03T08:00:00+00:00", "event": "carrier_delivered"},
        ]
    )
    assert proj.classify_inbound(delivered) == "delivered"


def test_classify_inbound_excluded_awb():
    a = _audit(awb="5665916826")
    assert proj.classify_inbound(a) == "excluded"


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
    assert inbound["awb"] != outbound["awb"]
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
    assert "+02:00" in row["created_at_warsaw"] or "+01:00" in row["created_at_warsaw"]
    assert row["milestones"]
    # second milestone should carry duration from previous
    assert row["milestones"][1]["duration_from_previous_hours"] == pytest.approx(2.12, abs=0.02)
    assert row["stage_age_hours"] is not None


def test_missing_timestamps_do_not_invent_expected_delivery():
    row = proj.project_inbound_row(_audit())
    assert row["expected_delivery_utc"] is None
    assert row["received_by"] is None
    assert row["pickup_at_utc"] is None


def test_delivered_leaves_active_filter(monkeypatch, tmp_path):
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

    def fake_paths():
        return [Path(f"virtual/{a['batch_id']}/audit.json") for a in audits]

    def fake_read(path: Path):
        bid = path.parent.name
        return next(a for a in audits if a["batch_id"] == bid)

    monkeypatch.setattr(proj, "_audit_paths", fake_paths)
    monkeypatch.setattr(proj, "_read_audit", fake_read)
    monkeypatch.setattr(proj, "_carrier_db_path", lambda: tmp_path / "missing.db")

    active = proj.project_logistics(view="active", direction="inbound")
    awbs = {r["awb"] for r in active["rows"]}
    assert "ACTIVE0001" in awbs
    assert "DONE000002" not in awbs

    delivered = proj.project_logistics(view="delivered", direction="inbound")
    dawbs = {r["awb"] for r in delivered["rows"]}
    assert "DONE000002" in dawbs
    assert "ACTIVE0001" not in dawbs


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


def test_stale_orch_active_not_blindly_active():
    """Customs/PZ complete must classify completed even if orch would call active."""
    stale = _audit(
        awb="5378819972",
        clearance_status="dsk_generated",
        timeline=[
            {"ts": "2026-04-28T08:00:00+00:00", "event": "batch_created"},
            {"ts": "2026-05-01T08:00:00+00:00", "event": "sad_uploaded"},
            {"ts": "2026-05-02T08:00:00+00:00", "event": "pz_generated"},
        ],
    )
    assert proj.classify_inbound(stale) == "completed"


def test_no_write_surface_in_module_source():
    src = Path(proj.__file__).read_text(encoding="utf-8")
    # Projector must remain read-only — no queue_email / create_shipment calls.
    assert "queue_email" not in src
    assert "create_shipment(" not in src
    assert "robocopy" not in src.lower()
    assert "INSERT " not in src.upper()
    assert "UPDATE " not in src.upper()
    assert ".write_text(" not in src


def test_csv_export_columns():
    rows = [proj.project_inbound_row(_audit())]
    body = proj.rows_to_logistics_csv(rows)
    text = body.decode("utf-8-sig")
    assert "direction" in text
    assert "1111111111" in text


def test_routes_require_api_key(monkeypatch):
    """When API_KEY is configured, unauthenticated GETs must 401 (Lesson O)."""
    from fastapi.testclient import TestClient
    from app.core.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "api_key", "test-logistics-key-only")
    monkeypatch.setattr(settings, "environment", "prod")
    client = TestClient(app)
    r = client.get("/api/v1/dhl/logistics/projection")
    assert r.status_code == 401
    r2 = client.get("/api/v1/dhl/logistics/export/csv")
    assert r2.status_code == 401
    # Valid key succeeds (projection may be empty but auth must pass).
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
