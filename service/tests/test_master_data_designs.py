"""B-MD2a — Designs master backend (MDOC-2026-05).

Tests the additive `designs` table in `master_data.sqlite`, the DAO in
`service/app/services/master_data_db.py`, and the 4 routes in
`service/app/api/routes_master_data.py::designs_router`.

Hard rule: `product_identity_engine` MUST NOT read this table. The
isolation contract lives in `test_master_data_hard_rules.py`.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.master_data_db import (
    init_db,
    validate_design, upsert_design, get_design, list_designs, delete_design,
)


# ── DAO tests ───────────────────────────────────────────────────────────────

def test_init_db_creates_designs_table_idempotent(tmp_path: Path):
    db = tmp_path / "md.sqlite"
    init_db(db)
    init_db(db)  # idempotent
    with sqlite3.connect(str(db)) as c:
        c.row_factory = sqlite3.Row
        tables = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()]
        assert "designs" in tables
        cols = [r[1] for r in c.execute("PRAGMA table_info(designs)").fetchall()]
        for expected in (
            "design_code", "display_name", "product_ref", "design_family",
            "collection", "metal", "stone_summary", "hs_code", "unit",
            "active", "notes", "created_at", "updated_at",
        ):
            assert expected in cols, f"Missing column: {expected}"


def test_designs_table_has_no_sql_fk_constraints(tmp_path: Path):
    """Hard rule: soft references only — no FK at the SQL level."""
    db = tmp_path / "md.sqlite"
    init_db(db)
    with sqlite3.connect(str(db)) as c:
        fks = c.execute("PRAGMA foreign_key_list(designs)").fetchall()
        assert fks == [], f"designs table must have ZERO FK constraints; got {fks}"


def test_validate_design_required_design_code():
    assert "design_code is required" in "; ".join(validate_design({}))
    assert validate_design({"design_code": "EJ-PD-001"}) == []


def test_validate_design_code_format():
    # Bad: starts with hyphen
    assert validate_design({"design_code": "-bad"}) != []
    # Bad: contains a space
    assert validate_design({"design_code": "bad code"}) != []
    # OK: letters, digits, slash, dot, underscore, hyphen
    assert validate_design({"design_code": "EJ-PD.001_a/b"}) == []


def test_validate_design_hs_code_format_when_set():
    # Empty hs_code allowed
    assert validate_design({"design_code": "x", "hs_code": ""}) == []
    # Bad: non-digits
    errs = validate_design({"design_code": "x", "hs_code": "abc"})
    assert any("hs_code" in e for e in errs)
    # OK: 6 digits
    assert validate_design({"design_code": "x", "hs_code": "711319"}) == []


def test_upsert_design_round_trip(tmp_path: Path):
    db = tmp_path / "md.sqlite"
    rec = upsert_design(db, {
        "design_code": "EJ-PD-001",
        "display_name": "Classic Pendant",
        "product_ref": "PROD-A-1",
        "design_family": "Pendant",
        "collection": "Classic",
        "metal": "Au18K",
        "stone_summary": "1x Diamond 0.20ct",
        "hs_code": "711319",
        "unit": "pcs",
        "active": True,
        "notes": "first design",
    })
    assert rec.design_code == "EJ-PD-001"
    assert rec.display_name == "Classic Pendant"
    assert rec.active is True
    fetched = get_design(db, "EJ-PD-001")
    assert fetched is not None
    assert fetched.metal == "Au18K"
    assert fetched.created_at == rec.created_at  # not mutated on first insert
    # Update path
    updated = upsert_design(db, {"design_code": "EJ-PD-001",
                                 "display_name": "Classic Pendant v2",
                                 "active": False})
    assert updated.display_name == "Classic Pendant v2"
    assert updated.active is False
    # created_at stable; updated_at advances or equals
    assert updated.created_at == rec.created_at


def test_list_designs_active_filter(tmp_path: Path):
    db = tmp_path / "md.sqlite"
    upsert_design(db, {"design_code": "A", "active": True})
    upsert_design(db, {"design_code": "B", "active": False})
    upsert_design(db, {"design_code": "C", "active": True})
    all_rows = list_designs(db)
    assert len(all_rows) == 3
    active_only = list_designs(db, active=True)
    assert {r.design_code for r in active_only} == {"A", "C"}
    inactive_only = list_designs(db, active=False)
    assert {r.design_code for r in inactive_only} == {"B"}


def test_list_designs_family_and_collection_filter(tmp_path: Path):
    db = tmp_path / "md.sqlite"
    upsert_design(db, {"design_code": "X1", "design_family": "Ring",   "collection": "Spring"})
    upsert_design(db, {"design_code": "X2", "design_family": "Ring",   "collection": "Autumn"})
    upsert_design(db, {"design_code": "X3", "design_family": "Pendant","collection": "Spring"})
    rings = list_designs(db, design_family="Ring")
    assert {r.design_code for r in rings} == {"X1", "X2"}
    spring = list_designs(db, collection="Spring")
    assert {r.design_code for r in spring} == {"X1", "X3"}


def test_delete_design(tmp_path: Path):
    db = tmp_path / "md.sqlite"
    upsert_design(db, {"design_code": "DEL-1"})
    assert get_design(db, "DEL-1") is not None
    assert delete_design(db, "DEL-1") is True
    assert get_design(db, "DEL-1") is None
    # Idempotent: delete-missing returns False, doesn't raise
    assert delete_design(db, "MISSING") is False


def test_get_design_missing_returns_none(tmp_path: Path):
    db = tmp_path / "md.sqlite"
    init_db(db)
    assert get_design(db, "NOPE") is None


def test_upsert_design_rejects_bad_code(tmp_path: Path):
    db = tmp_path / "md.sqlite"
    with pytest.raises(ValueError) as exc:
        upsert_design(db, {"design_code": "bad code"})
    assert "design_code" in str(exc.value)


# ── Route tests ─────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    """FastAPI TestClient with an isolated master_data.sqlite + no API key."""
    monkeypatch.setenv("API_KEY", "")  # disables auth dependency
    # Re-import the routes module so _DB_PATH binds to a temp path.
    import importlib
    from app.core import config as cfg_mod
    cfg_mod.settings.storage_root = tmp_path  # type: ignore[assignment]
    from app.api import routes_master_data
    importlib.reload(routes_master_data)
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(routes_master_data.designs_router)
    with TestClient(app) as c:
        yield c


def test_route_list_empty(client):
    r = client.get("/api/v1/designs/")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["count"] == 0
    assert body["designs"] == []


def test_route_put_get_delete(client):
    # PUT to create
    r = client.put("/api/v1/designs/EJ-RING-001", json={
        "display_name": "Solitaire",
        "design_family": "Ring",
        "metal": "Au14K",
        "active": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["design_code"] == "EJ-RING-001"
    assert body["display_name"] == "Solitaire"
    # GET one
    r = client.get("/api/v1/designs/EJ-RING-001")
    assert r.status_code == 200
    assert r.json()["metal"] == "Au14K"
    # LIST
    r = client.get("/api/v1/designs/")
    assert r.status_code == 200
    assert r.json()["count"] == 1
    # DELETE
    r = client.delete("/api/v1/designs/EJ-RING-001")
    assert r.status_code == 204
    r = client.get("/api/v1/designs/EJ-RING-001")
    assert r.status_code == 404


def test_route_put_validation_error(client):
    # Bad design_code (space)
    r = client.put("/api/v1/designs/bad code", json={})
    assert r.status_code == 422
    assert "validation_errors" in r.json()["detail"]


def test_route_get_missing_404(client):
    r = client.get("/api/v1/designs/NOPE")
    assert r.status_code == 404


def test_route_delete_missing_404(client):
    r = client.delete("/api/v1/designs/NOPE")
    assert r.status_code == 404


def test_route_list_filters(client):
    client.put("/api/v1/designs/A", json={"design_family": "Ring", "active": True})
    client.put("/api/v1/designs/B", json={"design_family": "Pendant", "active": False})
    r = client.get("/api/v1/designs/?active=true")
    assert {d["design_code"] for d in r.json()["designs"]} == {"A"}
    r = client.get("/api/v1/designs/?design_family=Pendant")
    assert {d["design_code"] for d in r.json()["designs"]} == {"B"}
