"""
Phase 3B — business API tests.

Coverage:
  - GET /api/v1/wfirma/contractors/scan/status
      returns 401 without API key
      returns 200 + canonical 11-field shape from empty DB
      reflects last-scan counts after a scan has run

  - POST /api/v1/wfirma/contractors/scan
      returns 401 without API key
      calls scan_contractors_into_master() (same shared function as scheduler)
      writes customer_master rows via the scan
      writes contractor_poll_state (started + completed)
      returns canonical 11-field status in response
      bypasses cooldown — runs even when last scan was recent

  - Shared-function assertion (critical):
      POST endpoint and scheduler tick both import scan_contractors_into_master
      from the same module (wfirma_contractor_poll_processor).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings


# ── helpers ────────────────────────────────────────────────────────────────────

def _key():
    return {"X-API-Key": settings.api_key or "test-key"}


def _make_contractor(wfirma_id: str = "101", name: str = "Test Co", country: str = "PL"):
    from app.services.wfirma_client import WFirmaContractor
    return WFirmaContractor(
        wfirma_id=wfirma_id, name=name, nip="1234567890", country=country,
        zip="00-001", city="Warsaw", email="", phone="", mobile="",
        street="", account_payments="", payment_method="transfer", payment_term="14",
    )


def _cm_count(db: Path) -> int:
    with sqlite3.connect(str(db)) as conn:
        return conn.execute("SELECT COUNT(*) FROM customer_master").fetchone()[0]


# ── fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def dbs(tmp_path):
    """Initialize both DBs and return their paths."""
    from app.services.wfirma_contractor_poll_db import init_contractor_poll_db
    from app.services.customer_master_db import init_db as init_cm_db

    poll_db = tmp_path / "contractor_poll.db"
    cm_db   = tmp_path / "customer_master.sqlite"
    init_contractor_poll_db(poll_db)
    init_cm_db(cm_db)
    return poll_db, cm_db


@pytest.fixture()
def client(dbs):
    poll_db, cm_db = dbs
    with patch("app.api.routes_wfirma_contractors._POLL_DB", poll_db), \
         patch("app.api.routes_wfirma_contractors._CM_DB",   cm_db), \
         patch.object(settings, "api_key", "test-key"):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c, poll_db, cm_db


# ── Auth gate ──────────────────────────────────────────────────────────────────

class TestAuthGate:
    def test_status_requires_api_key(self, tmp_path):
        poll_db = tmp_path / "contractor_poll.db"
        cm_db   = tmp_path / "customer_master.sqlite"
        with patch.object(settings, "storage_root", tmp_path), \
             patch("app.api.routes_wfirma_contractors._POLL_DB", poll_db), \
             patch("app.api.routes_wfirma_contractors._CM_DB",   cm_db), \
             patch.object(settings, "api_key", "secret"):
            with TestClient(app) as c:
                r = c.get("/api/v1/wfirma/contractors/scan/status")
        assert r.status_code == 401

    def test_scan_requires_api_key(self, tmp_path):
        poll_db = tmp_path / "contractor_poll.db"
        cm_db   = tmp_path / "customer_master.sqlite"
        with patch.object(settings, "storage_root", tmp_path), \
             patch("app.api.routes_wfirma_contractors._POLL_DB", poll_db), \
             patch("app.api.routes_wfirma_contractors._CM_DB",   cm_db), \
             patch.object(settings, "api_key", "secret"):
            with TestClient(app) as c:
                r = c.post("/api/v1/wfirma/contractors/scan")
        assert r.status_code == 401


# ── GET status ─────────────────────────────────────────────────────────────────

class TestGetScanStatus:
    def test_empty_db_returns_canonical_shape(self, client):
        c, _, _ = client
        r = c.get("/api/v1/wfirma/contractors/scan/status", headers=_key())
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True
        scan = d["scan"]
        # All 11 canonical fields must be present
        for field in (
            "healthy", "running", "last_started_at", "last_completed_at",
            "duration_ms", "processed", "created", "updated", "skipped",
            "errors", "last_error",
        ):
            assert field in scan, f"missing field: {field}"

    def test_empty_db_healthy_not_running(self, client):
        c, _, _ = client
        r = c.get("/api/v1/wfirma/contractors/scan/status", headers=_key())
        scan = r.json()["scan"]
        assert scan["healthy"] is True
        assert scan["running"] is False
        assert scan["processed"] == 0
        assert scan["created"] == 0
        assert scan["errors"] == 0
        assert scan["last_error"] is None

    def test_reflects_last_scan_counts(self, client, dbs):
        poll_db, _ = dbs
        from app.services.wfirma_contractor_poll_db import mark_scan_completed
        mark_scan_completed(poll_db, "2026-06-30T10:00:00+00:00",
                            contractor_count=50, new_count=5, updated_count=10)
        c, _, _ = client
        r = c.get("/api/v1/wfirma/contractors/scan/status", headers=_key())
        scan = r.json()["scan"]
        assert scan["processed"] == 50
        assert scan["created"] == 5
        assert scan["updated"] == 10
        assert scan["skipped"] == 35
        assert scan["errors"] == 0
        assert scan["healthy"] is True

    def test_error_state_surfaces_in_status(self, client, dbs):
        poll_db, _ = dbs
        from app.services.wfirma_contractor_poll_db import mark_scan_completed
        mark_scan_completed(poll_db, "2026-06-30T10:00:00+00:00",
                            contractor_count=5, new_count=0, updated_count=0,
                            error="wFirma API 502")
        c, _, _ = client
        r = c.get("/api/v1/wfirma/contractors/scan/status", headers=_key())
        scan = r.json()["scan"]
        assert scan["healthy"] is False
        assert scan["errors"] == 1
        assert "502" in scan["last_error"]


# ── POST scan ──────────────────────────────────────────────────────────────────

class TestPostScanTrigger:
    def test_returns_200_and_canonical_shape(self, client):
        c, _, _ = client
        with patch("app.services.wfirma_client.list_contractors_page",
                   return_value=[]):
            r = c.post("/api/v1/wfirma/contractors/scan", headers=_key())
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True
        scan = d["scan"]
        for field in (
            "healthy", "running", "last_started_at", "last_completed_at",
            "duration_ms", "processed", "created", "updated", "skipped",
            "errors", "last_error",
        ):
            assert field in scan, f"missing field: {field}"

    def test_calls_shared_scan_function_writes_customer_master(self, client, dbs):
        """POST endpoint uses scan_contractors_into_master() — same as the scheduler."""
        _, cm_db = dbs
        c, _, _ = client
        contractors = [_make_contractor("C1", "Firma Alpha", "PL"),
                       _make_contractor("C2", "Firma Beta",  "DE")]
        with patch("app.services.wfirma_client.list_contractors_page",
                   side_effect=[contractors, []]):
            r = c.post("/api/v1/wfirma/contractors/scan", headers=_key())
        assert r.status_code == 200
        assert _cm_count(cm_db) == 2
        scan = r.json()["scan"]
        assert scan["created"] == 2
        assert scan["processed"] == 2

    def test_scan_updates_poll_state_db(self, client, dbs):
        poll_db, _ = dbs
        c, _, _ = client
        with patch("app.services.wfirma_client.list_contractors_page",
                   return_value=[]):
            c.post("/api/v1/wfirma/contractors/scan", headers=_key())
        from app.services.wfirma_contractor_poll_db import get_scan_state
        state = get_scan_state(poll_db)
        assert state["last_scan_started_at"] is not None
        assert state["last_scan_completed_at"] is not None

    def test_bypasses_cooldown_runs_even_when_recent(self, client, dbs):
        """Manual trigger ignores the 6-hour cooldown."""
        poll_db, _ = dbs
        from app.services.wfirma_contractor_poll_db import mark_scan_completed
        mark_scan_completed(poll_db, "2026-06-30T09:59:00+00:00",
                            contractor_count=10, new_count=2, updated_count=8)
        c, _, _ = client
        contractors = [_make_contractor("C99", "New Corp", "SK")]
        with patch("app.services.wfirma_client.list_contractors_page",
                   side_effect=[contractors, []]):
            r = c.post("/api/v1/wfirma/contractors/scan", headers=_key())
        assert r.status_code == 200
        # scan ran despite recent prior scan
        scan = r.json()["scan"]
        assert scan["created"] == 1

    def test_scan_error_reflected_in_response(self, client):
        c, _, _ = client
        with patch("app.services.wfirma_client.list_contractors_page",
                   side_effect=RuntimeError("wFirma down")):
            r = c.post("/api/v1/wfirma/contractors/scan", headers=_key())
        assert r.status_code == 200
        scan = r.json()["scan"]
        assert scan["healthy"] is False
        assert scan["errors"] == 1
        assert "wFirma down" in scan["last_error"]

    def test_status_after_scan_reflects_new_counts(self, client, dbs):
        """GET status after POST scan shows same counts as scan response."""
        c, _, _ = client
        contractors = [_make_contractor("C1", "Alpha", "PL")]
        with patch("app.services.wfirma_client.list_contractors_page",
                   side_effect=[contractors, []]):
            scan_resp = c.post("/api/v1/wfirma/contractors/scan", headers=_key())
        status_resp = c.get("/api/v1/wfirma/contractors/scan/status", headers=_key())
        assert scan_resp.json()["scan"]["created"] == status_resp.json()["scan"]["created"]
        assert scan_resp.json()["scan"]["processed"] == status_resp.json()["scan"]["processed"]


# ── Shared-function assertion ──────────────────────────────────────────────────

class TestSharedFunctionAssert:
    def test_api_and_scheduler_import_same_scan_function(self):
        """Both the API route and the scheduler tick call scan_contractors_into_master
        from the same module — never duplicate logic."""
        import app.api.routes_wfirma_contractors as route_mod
        import app.services.wfirma_webhook_scheduler as sched_mod
        import app.services.wfirma_contractor_poll_processor as proc_mod

        # API uses lazy imports inside the function — verify the module path
        import inspect
        source = inspect.getsource(route_mod.trigger_contractor_scan)
        assert "scan_contractors_into_master" in source
        assert "wfirma_contractor_poll_processor" in source

        # Scheduler tick also calls scan_contractors_into_master from the same module
        sched_source = inspect.getsource(sched_mod._run_contractor_poll_tick)
        assert "scan_contractors_into_master" in sched_source
        assert "wfirma_contractor_poll_processor" in sched_source

        # The function itself exists in the processor module
        assert hasattr(proc_mod, "scan_contractors_into_master")
        assert callable(proc_mod.scan_contractors_into_master)
