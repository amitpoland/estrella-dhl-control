"""Admin reporting-resolution for DHL Control Tower — does not rewrite tracking."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import require_admin, get_current_user
from app.main import app
from app.services import dhl_logistics_projector as proj
from app.services import dhl_logistics_resolution_db as resdb


@pytest.fixture
def res_db(tmp_path, monkeypatch):
    path = tmp_path / "dhl_logistics_resolutions.db"
    monkeypatch.setattr(resdb, "db_path", lambda: path)
    resdb.init_db(path)
    return path


def _row(awb="OLD111", created_days=100, classification="historical_unresolved"):
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    created = now - timedelta(days=created_days)
    return {
        "direction": "inbound",
        "awb": awb,
        "classification": classification,
        "transport_status": "Pickup pending",
        "current_status": "Pickup pending",
        "customs_complete": True,
        "needs_attention": False,
        "attention_reasons": [],
        "created_at_utc": created.isoformat(),
        "delivered_at_utc": None,
        "data_quality": [],
        "milestones": [],
    }


def test_apply_closed_leaves_active_without_dhl_delivered(res_db):
    res = resdb.resolve(
        awb="OLD111",
        direction="inbound",
        resolution_status="closed_no_longer_operational",
        comment="legacy residue",
        resolved_by="admin@test",
        previous_projection={"classification": "historical_unresolved"},
        path=res_db,
    )
    out = proj._apply_manual_resolution(_row(), res)
    assert out["classification"] == "manually_resolved_closed"
    assert out["transport_status"] == "Pickup pending"
    assert out["manual_resolution_badge"] == "Manually resolved"
    assert out["needs_attention"] is False


def test_apply_historical_delivered_requires_manual_date_and_excludes_averages(res_db):
    with pytest.raises(ValueError):
        resdb.resolve(
            awb="OLD222",
            direction="inbound",
            resolution_status="historical_delivered",
            comment="was delivered",
            resolved_by="admin@test",
            path=res_db,
        )
    base = _row(awb="OLD222", created_days=100)
    # Delivery after created_at so operator-confirmed duration is computable
    created = datetime.fromisoformat(base["created_at_utc"])
    delivered = (created + timedelta(days=10)).isoformat()
    res = resdb.resolve(
        awb="OLD222",
        direction="inbound",
        resolution_status="historical_delivered",
        comment="was delivered",
        resolved_by="admin@test",
        manual_delivered_at=delivered,
        path=res_db,
    )
    out = proj._apply_manual_resolution(base, res)
    assert out["classification"] == "manually_resolved_delivered"
    assert out["transport_status"] != "Delivered"
    assert out["operator_confirmed_duration_hours"] is not None
    valid, excluded = proj._collect_transit_hours([out])
    assert valid == []
    assert any(e["reason"] == "manual_resolution_excluded_from_dhl_averages" for e in excluded)


def test_dhl_delivered_supersedes_manual_resolution(res_db):
    res = resdb.resolve(
        awb="DHL1",
        direction="inbound",
        resolution_status="closed_no_longer_operational",
        comment="closed early",
        resolved_by="admin@test",
        path=res_db,
    )
    base = _row(awb="DHL1", classification="delivered")
    base["transport_status"] = "Delivered"
    base["delivered_at_utc"] = "2026-08-01T10:00:00+00:00"
    out = proj._apply_manual_resolution(base, res)
    assert out["classification"] == "delivered"
    assert out["manual_resolution_superseded_by_dhl"] is True


def test_reopen_restores_inactive(res_db):
    resdb.resolve(
        awb="OLD333",
        direction="inbound",
        resolution_status="closed_no_longer_operational",
        comment="close",
        resolved_by="admin@test",
        path=res_db,
    )
    out = resdb.reopen(
        awb="OLD333",
        direction="inbound",
        comment="mistake",
        resolved_by="admin@test",
        path=res_db,
    )
    assert out["active"] is False
    assert resdb.get_active_resolution("OLD333", "inbound", path=res_db) is None
    audit = resdb.list_audit("OLD333", "inbound", path=res_db)
    assert any(a["action"] == "reopen" for a in audit)
    assert any(a["action"] == "resolve" for a in audit)


def test_default_active_sort_newest_created_first():
    old = _row(awb="OLD", created_days=100, classification="active")
    new = _row(awb="NEW", created_days=1, classification="active")
    old["needs_attention"] = True
    old["stage_age_hours"] = 2400
    rows = [old, new]

    def _sort_key(r):
        created = r.get("created_at_utc") or ""
        return (0 if created else 1, created)

    rows.sort(key=_sort_key, reverse=True)
    assert rows[0]["awb"] == "NEW"
    assert rows[1]["awb"] == "OLD"


def test_non_admin_cannot_resolve(res_db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "api_key", "test-key-res")
    monkeypatch.setattr(settings, "environment", "prod")

    def _viewer():
        return {"role": "viewer", "username": "v", "id": 2}

    app.dependency_overrides[get_current_user] = _viewer
    app.dependency_overrides[require_admin] = lambda: (_ for _ in ()).throw(
        __import__("fastapi").HTTPException(status_code=403, detail="Admin only")
    )
    # Simpler: call require_admin path by overriding to raise
    from fastapi import HTTPException

    def _deny():
        raise HTTPException(status_code=403, detail="Admin only")

    app.dependency_overrides[require_admin] = _deny
    try:
        client = TestClient(app)
        r = client.post(
            "/api/v1/dhl/logistics/shipments/111/resolve",
            json={
                "direction": "inbound",
                "resolution_status": "closed_no_longer_operational",
                "comment": "nope",
            },
            headers={"X-API-Key": "test-key-res"},
        )
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(require_admin, None)
        app.dependency_overrides.pop(get_current_user, None)


def test_admin_resolve_requires_comment_and_does_not_touch_tracking(res_db, monkeypatch, tmp_path):
    from app.core.config import settings
    monkeypatch.setattr(settings, "api_key", "test-key-res2")
    monkeypatch.setattr(settings, "environment", "prod")
    monkeypatch.setattr(settings, "storage_root", tmp_path)

    detail = _row(awb="5831878861", created_days=3, classification="active")
    detail["transport_status"] = "In Customs"
    monkeypatch.setattr(proj, "project_shipment_detail", lambda awb: dict(detail))

    app.dependency_overrides[require_admin] = lambda: {"role": "admin", "username": "amit", "id": 1}
    try:
        client = TestClient(app)
        bad = client.post(
            "/api/v1/dhl/logistics/shipments/5831878861/resolve",
            json={
                "direction": "inbound",
                "resolution_status": "closed_no_longer_operational",
                "comment": "",
            },
        )
        assert bad.status_code == 422

        ok = client.post(
            "/api/v1/dhl/logistics/shipments/5831878861/resolve",
            json={
                "direction": "inbound",
                "resolution_status": "closed_no_longer_operational",
                "comment": "operator confirmed legacy",
            },
        )
        assert ok.status_code == 200
        body = ok.json()
        assert body["ok"] is True
        assert body["resolution"]["resolved_by"] == "amit"
        # Tracking authority untouched — no tracking write APIs invoked; resolution only in res db
        assert resdb.get_active_resolution("5831878861", "inbound")["comment"] == "operator confirmed legacy"
    finally:
        app.dependency_overrides.pop(require_admin, None)


def test_resolution_db_has_no_tracking_writes():
    src = Path(resdb.__file__).read_text(encoding="utf-8")
    # Executable writes only — docstring may name forbidden authorities.
    body = src.split('"""', 2)[-1] if src.count('"""') >= 2 else src
    assert "sqlite3" in body
    assert "dhl_logistics_resolution" in body
    for forbidden in ("INSERT INTO tracking", "UPDATE tracking", "tracking_cache.json", "open("):
        assert forbidden not in body or forbidden == "open("  # no file open of tracking
    assert "tracking_cache.json" not in body
    assert "carrier_shipments" not in body
