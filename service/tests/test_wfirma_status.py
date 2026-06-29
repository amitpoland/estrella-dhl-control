"""
Tests for GET /api/v1/webhooks/wfirma/status (Phase 2A.2).

Pattern: isolated FastAPI() + dependency_overrides.
No live DB, no live scheduler, no live wFirma API.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.routes_webhooks_wfirma_status import (
    router,
    _query_status,
    _build_service_block,
    _get_service_version,
    _uptime_seconds,
    TICK_INTERVAL_SECONDS,
)
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
    assert set(data.keys()) >= {"service", "queue", "snapshots", "recent_dead_letters"}


def test_status_service_keys():
    client = _app_authed()
    with patch("app.api.routes_webhooks_wfirma_status._get_proc_db_path", return_value=None):
        r = client.get("/api/v1/webhooks/wfirma/status")
    svc = r.json()["service"]
    assert "version" in svc
    assert "started_at" in svc
    assert "uptime_seconds" in svc
    assert "scheduler_running" in svc
    assert "last_tick_at" in svc
    assert "next_tick_at" in svc
    assert "tick_interval_seconds" in svc


def test_status_tick_interval_is_30():
    client = _app_authed()
    with patch("app.api.routes_webhooks_wfirma_status._get_proc_db_path", return_value=None):
        r = client.get("/api/v1/webhooks/wfirma/status")
    assert r.json()["service"]["tick_interval_seconds"] == 30


def test_status_queue_keys():
    client = _app_authed()
    with patch("app.api.routes_webhooks_wfirma_status._get_proc_db_path", return_value=None):
        r = client.get("/api/v1/webhooks/wfirma/status")
    queue = r.json()["queue"]
    assert set(queue.keys()) >= {"total", "received", "fetching", "retry_pending", "snapshotted", "dead_letter"}


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


# ── version priority chain ────────────────────────────────────────────────────


def test_version_reads_pz_version_env():
    with patch.dict(os.environ, {"PZ_VERSION": "abc12345"}):
        assert _get_service_version() == "abc12345"


def test_version_env_takes_priority_over_sha_file(tmp_path: Path):
    sha_file = tmp_path / "version.txt"
    sha_file.write_text("deadbeef11", encoding="utf-8")
    with patch("app.api.routes_webhooks_wfirma_status._SHA_FILE", sha_file), \
         patch.dict(os.environ, {"PZ_VERSION": "env-wins"}):
        assert _get_service_version() == "env-wins"


def test_version_reads_git_sha_txt_when_no_env(tmp_path: Path):
    sha_file = tmp_path / "version.txt"
    sha_file.write_text("abc1234567890", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PZ_VERSION"}
    with patch("app.api.routes_webhooks_wfirma_status._SHA_FILE", sha_file), \
         patch.dict(os.environ, env, clear=True):
        assert _get_service_version() == "abc1234567890"


def test_version_unknown_when_neither_env_nor_file():
    env = {k: v for k, v in os.environ.items() if k != "PZ_VERSION"}
    missing = Path("/nonexistent/version.txt")
    with patch("app.api.routes_webhooks_wfirma_status._SHA_FILE", missing), \
         patch.dict(os.environ, env, clear=True):
        assert _get_service_version() == "unknown"


def test_version_appears_in_response():
    client = _app_authed()
    with patch("app.api.routes_webhooks_wfirma_status._get_proc_db_path", return_value=None), \
         patch.dict(os.environ, {"PZ_VERSION": "c3f1229a"}):
        r = client.get("/api/v1/webhooks/wfirma/status")
    assert r.json()["service"]["version"] == "c3f1229a"


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
    assert result["queue"]["total"] == 3  # received + snapshotted + dead_letter
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


# ── build_service_block ───────────────────────────────────────────────────────


def test_build_service_block_shape():
    block = _build_service_block()
    assert set(block.keys()) >= {
        "version", "started_at", "uptime_seconds",
        "scheduler_running", "last_tick_at", "next_tick_at", "tick_interval_seconds",
    }


def test_build_service_block_tick_interval():
    block = _build_service_block()
    assert block["tick_interval_seconds"] == TICK_INTERVAL_SECONDS


def test_build_service_block_scheduler_running_type():
    block = _build_service_block()
    assert isinstance(block["scheduler_running"], bool)


# ── _uptime_seconds ───────────────────────────────────────────────────────────


def test_uptime_seconds_none_when_no_started_at():
    assert _uptime_seconds(None) is None


def test_uptime_seconds_returns_int_for_valid_timestamp():
    result = _uptime_seconds("2026-01-01T00:00:00+00:00")
    assert isinstance(result, int)
    assert result > 0


def test_uptime_seconds_recent_timestamp_is_small():
    from datetime import datetime, timezone, timedelta
    recent = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    result = _uptime_seconds(recent)
    assert result is not None
    assert 0 <= result <= 30  # allow a little clock slack


def test_uptime_seconds_returns_none_on_bad_input():
    assert _uptime_seconds("not-a-timestamp") is None
