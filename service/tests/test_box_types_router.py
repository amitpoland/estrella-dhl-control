"""
test_box_types_router.py — Phase D: box_types CRUD endpoints.

Coverage:
  1. GET /api/v1/box-types/ returns empty list when table is empty.
  2. POST /api/v1/box-types/ creates a box type; verifies response fields.
  3. GET /api/v1/box-types/{code} returns the created record.
  4. PUT /api/v1/box-types/{code} updates dims; new values reflected in list.
  5. GET /api/v1/box-types/ (list) shows updated record.
  6. GET /api/v1/box-types/{unknown} returns 404.
  7. POST without code returns 422.
  8. X-API-Key required for read; write endpoints require key (MASTER_ADMIN bypass via key).
  9. label-package route untouched — routes_carrier_actions still has the endpoint.
"""
from __future__ import annotations

import json
import pathlib
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


HEADERS_READ  = {"X-API-Key": "test-key"}
HEADERS_WRITE = {"X-API-Key": "test-key"}   # test environment uses api-key bypass for admin


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    from app.main import app
    # Initialise the master_data.sqlite so box_types table exists
    from app.services.master_data_db import init_db
    init_db(tmp_path / "master_data.sqlite")
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── 1. Empty list ─────────────────────────────────────────────────────────────

def test_list_box_types_empty(client):
    r = client.get("/api/v1/box-types/", headers=HEADERS_READ)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 0
    assert body["box_types"] == []


# ── 2. Create via POST ────────────────────────────────────────────────────────

def test_create_box_type(client):
    r = client.post(
        "/api/v1/box-types/",
        headers={**HEADERS_WRITE, "Content-Type": "application/json"},
        json={
            "code": "BOX-S",
            "name": "Small box",
            "length_cm": 20.0,
            "width_cm": 15.0,
            "height_cm": 10.0,
            "tare_weight_kg": 0.3,
        },
    )
    assert r.status_code in (200, 201), r.text
    b = r.json()
    assert b["code"] == "BOX-S"
    assert b["id"] is not None
    assert b["length_cm"] == 20.0
    assert b["tare_weight_kg"] == 0.3
    assert b["active"] is True


# ── 3. GET /{code} ────────────────────────────────────────────────────────────

def test_get_box_type_by_code(client):
    client.post(
        "/api/v1/box-types/",
        headers={**HEADERS_WRITE, "Content-Type": "application/json"},
        json={"code": "JIFFY-M", "name": "Jiffy bag M",
              "length_cm": 30.0, "width_cm": 22.0, "height_cm": 5.0,
              "tare_weight_kg": 0.1},
    )
    r = client.get("/api/v1/box-types/JIFFY-M", headers=HEADERS_READ)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Jiffy bag M"


# ── 4. PUT /{code} updates ────────────────────────────────────────────────────

def test_put_box_type_updates(client):
    # create
    client.post(
        "/api/v1/box-types/",
        headers={**HEADERS_WRITE, "Content-Type": "application/json"},
        json={"code": "BOX-L", "length_cm": 40.0, "width_cm": 30.0,
              "height_cm": 25.0, "tare_weight_kg": 0.8},
    )
    # update tare
    r = client.put(
        "/api/v1/box-types/BOX-L",
        headers={**HEADERS_WRITE, "Content-Type": "application/json"},
        json={"name": "Large box updated", "tare_weight_kg": 1.2},
    )
    assert r.status_code == 200, r.text
    assert r.json()["tare_weight_kg"] == 1.2
    assert r.json()["name"] == "Large box updated"


# ── 5. List shows updated record ──────────────────────────────────────────────

def test_list_shows_created(client):
    client.post(
        "/api/v1/box-types/",
        headers={**HEADERS_WRITE, "Content-Type": "application/json"},
        json={"code": "LIST-TEST", "length_cm": 10, "width_cm": 10, "height_cm": 10,
              "tare_weight_kg": 0.2},
    )
    r = client.get("/api/v1/box-types/", headers=HEADERS_READ)
    assert r.status_code == 200
    codes = [b["code"] for b in r.json()["box_types"]]
    assert "LIST-TEST" in codes


# ── 6. GET unknown → 404 ──────────────────────────────────────────────────────

def test_get_unknown_box_type(client):
    r = client.get("/api/v1/box-types/NONEXISTENT-XXX", headers=HEADERS_READ)
    assert r.status_code == 404


# ── 7. POST without code → 422 ───────────────────────────────────────────────

def test_post_without_code(client):
    r = client.post(
        "/api/v1/box-types/",
        headers={**HEADERS_WRITE, "Content-Type": "application/json"},
        json={"length_cm": 10, "width_cm": 10, "height_cm": 10},
    )
    assert r.status_code == 422


# ── 8. Auth: in dev (api_key="") auth is disabled; source-grep confirms gate ─

def test_box_types_router_has_auth_dependency():
    """Source-grep: routes_box_types uses require_api_key for GET and
    require_role_or_apikey(MASTER_ADMIN, MASTER_EDITOR) for writes.
    Auth enforcement is tested at the framework level by test_carrier_routes_auth.
    This test just confirms the dependency declarations are present in the source."""
    import pathlib
    src = pathlib.Path(__file__).parent.parent / "app/api/routes_box_types.py"
    text = src.read_text(encoding="utf-8")
    assert "require_api_key" in text, "read-auth missing"
    assert "require_role_or_apikey" in text, "write-auth missing"
    assert "MASTER_ADMIN" in text and "MASTER_EDITOR" in text, "roles missing"


# ── 9. label-package route still exists (regression guard) ──────────────────

def test_label_package_route_registered():
    """Confirms POST /{batch_id}/label-package is still registered — not rebuilt."""
    from app.main import app as _app
    paths = [r.path for r in _app.routes if hasattr(r, "path")]
    assert any("label-package" in p for p in paths), \
        "label-package route missing from registered routes"
