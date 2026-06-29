"""
Tests for GET /api/v1/webhooks/wfirma/status (Phase 2A.2).

Pattern: isolated FastAPI() + dependency_overrides.
No live DB, no live scheduler, no live wFirma API.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.routes_webhooks_wfirma_status import router, _query_status
from app.auth.dependencies import get_current_user
from app.services.wfirma_processing_db import (
    init_db,
    ensure_processing_row,
    set_state,
    mark_dead_letter,
    insert_snapshot,
)

_NOW = "2026-06-29T10:00:00+00:00"
_USER = {"id": 1, "username": "admin", "role": "admin", "is_active": True, "is_approved": True}


# ── app factories ─────────────────────────────────────────────────────────────


def _app_authed() -> TestClient:
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def _app_unauthed() -> TestClient:
    app = FastAPI()

    def _deny():
        raise HTTPException(status_code=401, detail="Not authenticated")

    app.dependency_overrides[get_current_user] = _deny
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


# ── auth ──────────────────────────────────────────────────────────────────────


def test_status_requires_auth():
    client = _app_unauthed()
    r = client.get("/api/v1/webhooks/wfirma/status")
    assert r.status_code == 401


def test_status_accepts_authenticated_user():
    client = _app_authed()
    with patch("app.api.routes_webhooks_wfirma_status._get_proc_db_path", return_value=None):
        r = client.get("/api/v1/webhooks/wfirma/status")
    assert r.status_code == 200


# ── JSON structure ────────────────────────────────────────────────────────────


def test_status_response_has_required_top_level_keys():
    client = _app_authed()
    with patch("app.api.routes_webhooks_wfirma_status._get_proc_db_path", return_value=None):
        r = client.get("/api/v1/webhooks/wfirma/status")
    data = r.json()
    assert set(data.keys()) >= {"scheduler", "queue", "snapshots", "recent_dead_letters"}


def test_status_scheduler_keys():
    client = _app_authed()
    with patch("app.api.routes_webhooks_wfirma_status._get_proc_db_path", return_value=None):
        r = client.get("/api/v1/webhooks/wfirma/status")
    sched = r.json()["scheduler"]
    assert "running" in sched
    assert "last_tick" in sched
    assert "next_tick" in sched


def test_status_queue_keys():
    client = _app_authed()
    with patch("app.api.routes_webhooks_wfirma_status._get_proc_db_path", return_value=None):
        r = client.get("/api/v1/webhooks/wfirma/status")
    queue = r.json()["queue"]
    assert set(queue.keys()) >= {"received", "fetching", "retry_pending", "snapshotted", "dead_letter"}


def test_status_snapshots_keys():
    client = _app_authed()
    with patch("app.api.routes_webhooks_wfirma_status._get_proc_db_path", return_value=None):
        r = client.get("/api/v1/webhooks/wfirma/status")
    snaps = r.json()["snapshots"]
    assert "total" in snaps
    assert "latest_snapshot_at" in snaps


def test_status_recent_dead_letters_is_list():
    client = _app_authed()
    with patch("app.api.routes_webhooks_wfirma_status._get_proc_db_path", return_value=None):
        r = client.get("/api/v1/webhooks/wfirma/status")
    assert isinstance(r.json()["recent_dead_letters"], list)


# ── no-db fallback ────────────────────────────────────────────────────────────


def test_status_returns_zeros_when_db_not_initialised():
    client = _app_authed()
    with patch("app.api.routes_webhooks_wfirma_status._get_proc_db_path", return_value=None):
        r = client.get("/api/v1/webhooks/wfirma/status")
    data = r.json()
    assert data["queue"]["received"] == 0
    assert data["snapshots"]["total"] == 0
    assert data["recent_dead_letters"] == []


# ── query_status with real data ───────────────────────────────────────────────


def _seed_db(db: Path) -> None:
    """Seed a test processing DB with known state."""
    init_db(db)
    ensure_processing_row(db, "evt-recv", "OBJ-1", _NOW)
    ensure_processing_row(db, "evt-snap", "OBJ-2", _NOW)
    set_state(db, "evt-snap", "SNAPSHOTTED", extra={"snapshotted_at": _NOW})
    ensure_processing_row(db, "evt-dl", "OBJ-3", _NOW)
    mark_dead_letter(db, "evt-dl", _NOW)
    # Insert a snapshot for evt-snap
    insert_snapshot(
        db,
        snapshot_id="snap-001",
        event_id="evt-snap",
        object_id="OBJ-2",
        fetched_at=_NOW,
        raw_xml="<api></api>",
        parsed={"invoice_number": "FV/1/2026"},
        raw_payload="{}",
    )


def test_query_status_state_counts(tmp_path: Path):
    db = tmp_path / "proc.db"
    _seed_db(db)
    result = _query_status(db)
    assert result["queue"]["received"] == 1
    assert result["queue"]["snapshotted"] == 1
    assert result["queue"]["dead_letter"] == 1
    assert result["snapshots"]["total"] == 1


def test_query_status_latest_snapshot_at(tmp_path: Path):
    db = tmp_path / "proc.db"
    _seed_db(db)
    result = _query_status(db)
    assert result["snapshots"]["latest_snapshot_at"] == _NOW


def test_query_status_dead_letters_list(tmp_path: Path):
    db = tmp_path / "proc.db"
    _seed_db(db)
    result = _query_status(db)
    dl = result["recent_dead_letters"]
    assert len(dl) == 1
    assert dl[0]["event_id"] == "evt-dl"
    assert dl[0]["object_id"] == "OBJ-3"
    assert "retry_count" in dl[0]
    assert "last_error" in dl[0]


def test_query_status_empty_db(tmp_path: Path):
    db = tmp_path / "empty.db"
    init_db(db)
    result = _query_status(db)
    assert result["queue"]["received"] == 0
    assert result["snapshots"]["total"] == 0
    assert result["recent_dead_letters"] == []


def test_query_status_dead_letters_capped_at_five(tmp_path: Path):
    db = tmp_path / "proc.db"
    init_db(db)
    for i in range(7):
        eid = f"evt-dl-{i}"
        ensure_processing_row(db, eid, f"OBJ-{i}", _NOW)
        mark_dead_letter(db, eid, _NOW)
    result = _query_status(db)
    assert len(result["recent_dead_letters"]) == 5


# ── scheduler status ──────────────────────────────────────────────────────────


def test_get_scheduler_status_returns_dict():
    from app.services.wfirma_webhook_scheduler import get_scheduler_status
    status = get_scheduler_status()
    assert isinstance(status, dict)
    assert "running" in status
    assert "last_tick" in status
    assert "next_tick" in status


def test_get_scheduler_status_not_running_by_default():
    from app.services import wfirma_webhook_scheduler as sched
    original = sched._scheduler
    sched._scheduler = None
    try:
        status = sched.get_scheduler_status()
        assert status["running"] is False
    finally:
        sched._scheduler = original


def test_last_tick_updates_on_tick(tmp_path: Path):
    import app.services.wfirma_webhook_scheduler as sched

    orig_events = sched._events_db_path
    orig_proc = sched._proc_db_path
    orig_tick = sched._last_tick_at

    events_db = tmp_path / "events.db"
    proc_db = tmp_path / "proc.db"

    with sqlite3.connect(str(events_db)) as conn:
        conn.execute(
            "CREATE TABLE wfirma_webhook_events "
            "(event_id TEXT PRIMARY KEY, event_type TEXT, payload_json TEXT, received_at TEXT)"
        )
    init_db(proc_db)

    sched._events_db_path = events_db
    sched._proc_db_path = proc_db
    sched._last_tick_at = None

    try:
        sched._run_processing_tick()
        assert sched._last_tick_at is not None
    finally:
        sched._events_db_path = orig_events
        sched._proc_db_path = orig_proc
        sched._last_tick_at = orig_tick
