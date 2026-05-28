"""test_role_gate.py — Phase 0 scaffolding tests for require_role_or_apikey.

Verifies the two-mode contract:

  master_role_enforcement = False  → behavior identical to require_api_key
  master_role_enforcement = True   → master_* role required (or admin API key)

The factory is NOT yet wired to any route. Tests build a minimal FastAPI
app inline so failure isolation is unambiguous.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[1]
    repo_root   = here.parents[2]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.role_gate import (
    MASTER_ADMIN, MASTER_EDITOR, MASTER_VIEWER, MASTER_ROLES,
    require_role_or_apikey,
)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _build_app() -> FastAPI:
    app = FastAPI()

    @app.put("/write", dependencies=[Depends(require_role_or_apikey(
        MASTER_ADMIN, MASTER_EDITOR))])
    def write_endpoint():
        return {"ok": True}

    @app.delete("/admin", dependencies=[Depends(require_role_or_apikey(
        MASTER_ADMIN))])
    def admin_endpoint():
        return {"ok": True}

    return app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "TESTKEY")
    return TestClient(_build_app())


# ── Factory-time guard ──────────────────────────────────────────────────────

def test_factory_rejects_unknown_role():
    with pytest.raises(ValueError) as exc:
        require_role_or_apikey("editor")   # legacy role name — not master_*
    assert "unknown master roles" in str(exc.value)


def test_canonical_role_constants():
    assert MASTER_ADMIN  == "master_admin"
    assert MASTER_EDITOR == "master_editor"
    assert MASTER_VIEWER == "master_viewer"
    assert MASTER_ROLES == frozenset({MASTER_ADMIN, MASTER_EDITOR, MASTER_VIEWER})


# ── Flag OFF (default) → degrades to require_api_key ────────────────────────

def test_flag_off_api_key_passes(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", False)
    r = client.put("/write", headers={"X-API-Key": "TESTKEY"})
    assert r.status_code == 200


def test_flag_off_wrong_api_key_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", False)
    r = client.put("/write", headers={"X-API-Key": "WRONG"})
    assert r.status_code == 401


def test_flag_off_no_credentials_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", False)
    r = client.put("/write")
    assert r.status_code == 401


def test_flag_off_api_key_disabled_passes(monkeypatch):
    """Dev posture: empty api_key → require_api_key returns early. The
    role gate must respect that to avoid breaking local dev."""
    monkeypatch.setattr(settings, "api_key", "")
    monkeypatch.setattr(settings, "master_role_enforcement", False)
    c = TestClient(_build_app())
    r = c.put("/write")
    assert r.status_code == 200


# ── Flag ON → role enforcement live ─────────────────────────────────────────

def test_flag_on_admin_api_key_passes(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    r = client.put("/write", headers={"X-API-Key": "TESTKEY"})
    assert r.status_code == 200


def test_flag_on_admin_api_key_reaches_admin_endpoint(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    r = client.delete("/admin", headers={"X-API-Key": "TESTKEY"})
    assert r.status_code == 200


def test_flag_on_no_credentials_returns_401(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    r = client.put("/write")
    assert r.status_code == 401


def test_flag_on_session_with_correct_role_passes(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u1", "role": "master_editor"}):
        r = client.put("/write", cookies={"pz_session": "fake"})
    assert r.status_code == 200


def test_flag_on_session_with_admin_role_passes_editor_endpoint(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    # When master_admin is in the allowed set, the master_admin user passes.
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u1", "role": "master_admin"}):
        r = client.put("/write", cookies={"pz_session": "fake"})
    assert r.status_code == 200


def test_flag_on_session_with_viewer_role_blocked_from_write(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u1", "role": "master_viewer"}):
        r = client.put("/write", cookies={"pz_session": "fake"})
    assert r.status_code == 403


def test_flag_on_session_with_legacy_admin_role_blocked(client, monkeypatch):
    """Operator instruction 2026-05-28: master roles are ISOLATED.
    Holding the legacy 'admin' role alone must NOT grant master writes."""
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u1", "role": "admin"}):
        r = client.put("/write", cookies={"pz_session": "fake"})
    assert r.status_code == 403


def test_flag_on_session_with_legacy_editor_role_blocked(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u1", "role": "editor"}):
        r = client.put("/write", cookies={"pz_session": "fake"})
    assert r.status_code == 403


def test_flag_on_session_expired_or_invalid_returns_401(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    # Session present but get_current_user_optional returns None
    # (expired / unapproved / inactive).
    with patch("app.core.role_gate.get_current_user_optional", return_value=None):
        r = client.put("/write", cookies={"pz_session": "expired"})
    assert r.status_code == 401


def test_flag_on_editor_blocked_from_admin_only_endpoint(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u1", "role": "master_editor"}):
        r = client.delete("/admin", cookies={"pz_session": "fake"})
    assert r.status_code == 403
