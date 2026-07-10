"""test_defect1_sample_schema_guard.py — DEFECT-1 (POST-RELEASE STABILIZATION-1).

Production incident 2026-07-10: GET /api/v1/inventory/samples returned a raw
500 ("sqlite3.OperationalError: no such column: o.occurred_at") because the
live sample_out_events table carries the PRE-Phase-C column generation
(action/event_time/note/origin_sample_event_id) while the C-3b read register
queries the current generation (direction/occurred_at/notes/
linked_origin_event_id). ensure_sample_out_schema() passed on the stale table
because it checked only table+index EXISTENCE.

Pins: a stale-generation table (replicating the exact production shape) makes
the guard return False and the route answer 503 MIGRATION_PENDING — never a
500; the current-generation table (canonical draft migration) passes and the
register works; False results are never cached, so applying the migration
heals without a restart.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_SVC = Path(__file__).resolve().parents[1]
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.core.security import require_api_key
from app.api.routes_inventory_sample import router as _sample_router
from app.services import warehouse_db as wdb

_MIGRATIONS = _SVC / "app" / "db" / "migrations"


def _apply_draft_migration(db_path: Path) -> None:
    name = "draft_20260512_122327_sample_out_events.py.draft"
    loader = importlib.machinery.SourceFileLoader(name.replace(".", "_"),
                                                  str(_MIGRATIONS / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    mod.upgrade(db_path)


def _create_production_stale_shape(db_path: Path) -> None:
    """Replicate the EXACT table+index production carried on 2026-07-10
    (PRAGMA dump from C:\\PZ\\storage\\warehouse.db): old column generation
    plus an idempotency index under the name the old guard looked for."""
    con = sqlite3.connect(str(db_path))
    con.execute("""
        CREATE TABLE sample_out_events (
            id                     TEXT PRIMARY KEY,
            scan_code              TEXT,
            action                 TEXT,
            recipient_client_name  TEXT,
            recipient_client_id    TEXT,
            sample_reason          TEXT,
            expected_return_date   TEXT,
            actual_return_date     TEXT,
            operator               TEXT,
            event_time             TEXT,
            note                   TEXT,
            idempotency_key        TEXT,
            origin_sample_event_id TEXT,
            status                 TEXT,
            created_at             TEXT
        )""")
    con.execute(
        "CREATE UNIQUE INDEX idx_sample_out_idempotency "
        "ON sample_out_events (scan_code, idempotency_key) "
        "WHERE idempotency_key != ''")
    con.commit()
    con.close()


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    db = tmp_path / "warehouse.db"
    wdb.init_warehouse_db(db)
    monkeypatch.setattr(wdb, "_sample_out_schema_verified", False, raising=False)
    app = FastAPI()
    app.include_router(_sample_router)
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app, raise_server_exceptions=False), db


class TestStaleGenerationGuard:
    def test_stale_table_fails_guard(self, app_client):
        _, db = app_client
        _create_production_stale_shape(db)
        assert wdb.ensure_sample_out_schema() is False

    def test_stale_table_route_returns_503_not_500(self, app_client):
        """THE DEFECT-1 PIN: the exact production shape must produce the
        designed 503 MIGRATION_PENDING, never a raw 500."""
        client, db = app_client
        _create_production_stale_shape(db)
        r = client.get("/api/v1/inventory/samples")
        assert r.status_code == 503, f"expected 503, got {r.status_code}"
        assert r.json()["detail"]["code"] == "MIGRATION_PENDING"

    def test_missing_table_still_fails_guard(self, app_client):
        assert wdb.ensure_sample_out_schema() is False

    def test_current_generation_passes_and_register_works(self, app_client):
        client, db = app_client
        _apply_draft_migration(db)
        assert wdb.ensure_sample_out_schema() is True
        r = client.get("/api/v1/inventory/samples")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "count": 0, "samples": []}

    def test_false_never_cached_migration_heals_without_restart(self, app_client):
        client, db = app_client
        _create_production_stale_shape(db)
        assert wdb.ensure_sample_out_schema() is False
        # heal in place: drop stale generation (0 rows, mirroring production)
        # and apply the canonical migration — next call must pass with no
        # cache reset and no process restart.
        con = sqlite3.connect(str(db))
        con.execute("DROP INDEX idx_sample_out_idempotency")
        con.execute("DROP TABLE sample_out_events")
        con.commit()
        con.close()
        _apply_draft_migration(db)
        assert wdb.ensure_sample_out_schema() is True
        assert client.get("/api/v1/inventory/samples").status_code == 200

    def test_required_columns_match_canonical_migration(self, tmp_path):
        """The guard's column set must stay in sync with the canonical DDL —
        if the draft migration evolves, this pin forces the guard along."""
        db = tmp_path / "canon.db"
        _apply_draft_migration(db)
        con = sqlite3.connect(str(db))
        cols = {r[1] for r in con.execute("PRAGMA table_info(sample_out_events)")}
        con.close()
        assert wdb._SAMPLE_OUT_REQUIRED_COLUMNS == frozenset(cols)
