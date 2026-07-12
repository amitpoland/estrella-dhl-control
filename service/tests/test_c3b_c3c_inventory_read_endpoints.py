"""test_c3b_c3c_inventory_read_endpoints.py — Phase-C Wave 2, slices C-3b/C-3c.

Read/list endpoints over the two evidence tables (backend only — UI wiring
is Wave 3):

  GET /api/v1/inventory/samples   (C-3b, sample_out_events)
  GET /api/v1/inventory/returns   (C-3c, returns_events)

Pins:
  1.  503 MIGRATION_PENDING before the draft migration is applied
  2.  empty register → ok=True, count=0
  3.  open sample listed with status='open'
  4.  paired return → status='returned' + returned_at/return_operator
  5.  status + recipient filters; invalid status → 400
  6.  returns: from_client is 'recorded'; to_producer is 'open' until the
      linked producer_restock event lands → 'resolved'
  7.  direction filter; invalid direction → 400
  8.  read-only guarantee: no inventory_state writes (source-grep — the
      routers never import transition(); single-writer discipline)
  9.  both GET routes registered on the production app
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_SVC = Path(__file__).resolve().parents[1]
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.core.security import require_api_key
from app.api.routes_inventory_sample import router as _sample_router
from app.api.routes_inventory_returns import router as _returns_router
from app.services import warehouse_db as wdb


_MIGRATIONS = _SVC / "app" / "db" / "migrations"


def _apply_draft(name: str, db_path: Path) -> None:
    """Load a .py.draft migration module and run upgrade(db_path)."""
    path = _MIGRATIONS / name
    loader = importlib.machinery.SourceFileLoader(name.replace(".", "_"), str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    mod.upgrade(db_path)


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    """Local app with both routers, auth overridden, warehouse.db at tmp.

    Schema-verified caches in warehouse_db are reset so per-test DBs are
    honestly re-checked (the module caches success globally).
    """
    db = tmp_path / "warehouse.db"
    wdb.init_warehouse_db(db)
    monkeypatch.setattr(wdb, "_sample_out_schema_verified", False, raising=False)
    monkeypatch.setattr(wdb, "_returns_schema_verified", False, raising=False)
    app = FastAPI()
    app.include_router(_sample_router)
    app.include_router(_returns_router)
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app), db


def _migrate_both(db: Path):
    _apply_draft("draft_20260512_122327_sample_out_events.py.draft", db)
    _apply_draft("draft_20260512_175238_returns_events.py.draft", db)


def _seed_sample_out(scan="S001", recipient="ACME Corp", **kw):
    return wdb.record_sample_out_event(
        scan_code=scan, direction="out", operator="alice",
        recipient_client_name=recipient, sample_reason="customer_review",
        expected_return_date="2099-01-01",
        idempotency_key=kw.pop("idempotency_key", str(uuid.uuid4())), **kw,
    )


# ── 1. migration gates ───────────────────────────────────────────────────────

def test_samples_503_before_migration(app_client):
    client, _ = app_client
    r = client.get("/api/v1/inventory/samples")
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "MIGRATION_PENDING"


def test_returns_503_before_migration(app_client):
    client, _ = app_client
    r = client.get("/api/v1/inventory/returns")
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "MIGRATION_PENDING"


# ── 2-5. sample register ─────────────────────────────────────────────────────

def test_samples_empty_register(app_client):
    client, db = app_client
    _migrate_both(db)
    r = client.get("/api/v1/inventory/samples")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "count": 0, "samples": []}


def test_open_sample_listed(app_client):
    client, db = app_client
    _migrate_both(db)
    _seed_sample_out(scan="S001")
    body = client.get("/api/v1/inventory/samples").json()
    assert body["count"] == 1
    rec = body["samples"][0]
    assert rec["scan_code"] == "S001"
    assert rec["status"] == "open"
    assert rec["recipient_client_name"] == "ACME Corp"
    assert rec["returned_at"] is None


def test_paired_return_marks_returned(app_client):
    client, db = app_client
    _migrate_both(db)
    out_evt = _seed_sample_out(scan="S002")
    wdb.record_sample_out_event(
        scan_code="S002", direction="return", operator="bob",
        idempotency_key=str(uuid.uuid4()),
        linked_origin_event_id=out_evt["id"],
    )
    body = client.get("/api/v1/inventory/samples").json()
    assert body["count"] == 1
    rec = body["samples"][0]
    assert rec["status"] == "returned"
    assert rec["returned_at"]
    assert rec["return_operator"] == "bob"


def test_sample_filters_and_validation(app_client):
    client, db = app_client
    _migrate_both(db)
    open_evt = _seed_sample_out(scan="S010", recipient="ACME Corp")
    closed = _seed_sample_out(scan="S011", recipient="Test Trading EOOD")
    wdb.record_sample_out_event(
        scan_code="S011", direction="return", operator="bob",
        idempotency_key=str(uuid.uuid4()),
        linked_origin_event_id=closed["id"],
    )
    opens = client.get("/api/v1/inventory/samples?status=open").json()
    assert [s["scan_code"] for s in opens["samples"]] == ["S010"]
    rets = client.get("/api/v1/inventory/samples?status=returned").json()
    assert [s["scan_code"] for s in rets["samples"]] == ["S011"]
    by_client = client.get("/api/v1/inventory/samples?recipient=trading").json()
    assert [s["scan_code"] for s in by_client["samples"]] == ["S011"]
    assert client.get("/api/v1/inventory/samples?status=bogus").status_code == 400
    assert open_evt["id"]  # silence unused warning


# ── 6-7. returns register ────────────────────────────────────────────────────

def test_returns_directions_and_resolution(app_client):
    client, db = app_client
    _migrate_both(db)
    wdb.record_returns_event(
        scan_code="R001", direction="from_client", operator="alice",
        source_holder_name="ACME Corp", return_reason="defect",
        idempotency_key=str(uuid.uuid4()),
    )
    tp = wdb.record_returns_event(
        scan_code="R002", direction="to_producer", operator="alice",
        producer_name="EJL Mumbai", return_reason="repair",
        idempotency_key=str(uuid.uuid4()),
    )
    body = client.get("/api/v1/inventory/returns").json()
    by_scan = {r["scan_code"]: r for r in body["returns"]}
    assert by_scan["R001"]["status"] == "recorded"
    assert by_scan["R002"]["status"] == "open"

    wdb.record_returns_event(
        scan_code="R002", direction="producer_restock", operator="bob",
        idempotency_key=str(uuid.uuid4()), linked_origin_event_id=tp["id"],
    )
    body = client.get("/api/v1/inventory/returns?direction=to_producer").json()
    assert body["count"] == 1
    assert body["returns"][0]["status"] == "resolved"
    assert body["returns"][0]["resolved_at"]

    opens = client.get("/api/v1/inventory/returns?status=open").json()
    assert opens["count"] == 0
    assert client.get(
        "/api/v1/inventory/returns?direction=sideways").status_code == 400
    assert client.get(
        "/api/v1/inventory/returns?status=bogus").status_code == 400


# ── 8. read-only guarantee ───────────────────────────────────────────────────

def test_read_routes_never_touch_inventory_state():
    """Single-writer discipline: the GET endpoints must not import or call
    transition() / inventory_state writers — they are pure projections."""
    for fname in ("routes_inventory_sample.py", "routes_inventory_returns.py"):
        src = (_SVC / "app" / "api" / fname).read_text(encoding="utf-8")
        get_part = src[src.index("# ── C-3"):]
        assert "transition(" not in get_part, f"{fname}: GET must be read-only"
        assert "UPDATE inventory_state" not in get_part
        assert "upsert" not in get_part, f"{fname}: GET must not write"


# ── 9. production registration ───────────────────────────────────────────────

def test_read_routes_registered_on_main_app():
    from app.main import app as prod_app
    paths = {r.path for r in prod_app.routes}
    assert "/api/v1/inventory/samples" in paths
    assert "/api/v1/inventory/returns" in paths
