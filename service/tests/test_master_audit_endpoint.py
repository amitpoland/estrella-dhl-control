"""test_master_audit_endpoint.py — GET /api/v1/master/audit query surface.

Phase 1: auth = _auth (same posture as existing master GETs). Phase 2 will
tighten to master_admin once role enforcement is enabled.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[1]
    repo_root   = here.parents[2]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from fastapi.testclient import TestClient

from app.core.config import settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "master_audit_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", False)
    import app.api.routes_master_data as md
    md._DB_PATH = tmp_path / "master_data.sqlite"
    from fastapi import FastAPI
    app = FastAPI()
    for r in (md.hs_router, md.units_router, md.audit_router):
        app.include_router(r)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _hdr(extra: dict | None = None) -> dict:
    h = {"X-API-Key": settings.api_key or "test-key"}
    if extra:
        h.update(extra)
    return h


def _seed(client) -> None:
    # HS codes must match ^[0-9]{4,12}$.
    for code in ("71131900", "71131910", "71131920"):
        client.put(f"/api/v1/hs-codes/{code}", json={"description_pl": code},
                   headers=_hdr())
    client.put("/api/v1/units/szt", json={"name_pl": "sztuka"}, headers=_hdr())


# ── Auth ────────────────────────────────────────────────────────────────────

def test_audit_endpoint_requires_auth(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "REALKEY")
    r = client.get("/api/v1/master/audit/")
    assert r.status_code == 401


# ── Filters ─────────────────────────────────────────────────────────────────

def test_audit_endpoint_lists_rows(client):
    _seed(client)
    r = client.get("/api/v1/master/audit/", headers=_hdr())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 4
    assert len(body["rows"]) == 4


def test_audit_endpoint_filter_entity(client):
    _seed(client)
    r = client.get("/api/v1/master/audit/?entity=hs_codes", headers=_hdr())
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    assert {row["entity"] for row in body["rows"]} == {"hs_codes"}


def test_audit_endpoint_filter_pk(client):
    _seed(client)
    r = client.get("/api/v1/master/audit/?entity=hs_codes&pk=71131910",
                   headers=_hdr())
    assert r.json()["count"] == 1
    assert r.json()["rows"][0]["pk"] == "71131910"


def test_audit_endpoint_filter_op(client):
    _seed(client)
    client.delete("/api/v1/hs-codes/71131900", headers=_hdr())
    r = client.get("/api/v1/master/audit/?op=delete", headers=_hdr())
    assert r.json()["count"] == 1
    assert r.json()["rows"][0]["op"] == "delete"


def test_audit_endpoint_pagination(client):
    _seed(client)
    p1 = client.get("/api/v1/master/audit/?limit=2&offset=0", headers=_hdr()).json()
    p2 = client.get("/api/v1/master/audit/?limit=2&offset=2", headers=_hdr()).json()
    assert p1["count"] == 2 and p2["count"] == 2
    assert {r["id"] for r in p1["rows"]}.isdisjoint({r["id"] for r in p2["rows"]})


def test_audit_endpoint_filter_actor(client):
    _seed(client)
    r = client.get("/api/v1/master/audit/?actor=apikey:unknown", headers=_hdr())
    # All Phase 1 writes from TestClient have no api_key_label middleware,
    # so they share the fallback actor.
    assert r.json()["count"] == 4


def test_audit_endpoint_returns_diff_for_update(client):
    client.put("/api/v1/hs-codes/71132100",
               json={"duty_rate_pct": "2.5", "active": True}, headers=_hdr())
    client.put("/api/v1/hs-codes/71132100",
               json={"duty_rate_pct": "2.5", "active": False}, headers=_hdr())
    r = client.get("/api/v1/master/audit/?entity=hs_codes&pk=71132100&op=update",
                   headers=_hdr())
    [row] = r.json()["rows"]
    assert row["diff_json"]["active"] == {"before": True, "after": False}
