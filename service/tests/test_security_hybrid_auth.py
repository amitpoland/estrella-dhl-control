"""Hybrid auth guard tests for require_api_key.

Matrix:
- settings.api_key == ""                    → pass-through (current prod)
- settings.api_key != "" + valid header     → 200
- settings.api_key != "" + valid cookie     → 200
- settings.api_key != "" + neither          → 401
- settings.api_key != "" + bad header       → 401
- settings.api_key != "" + bad cookie       → 401
- settings.api_key != "" + both valid       → 200
- source uses hmac.compare_digest (no `==` on the key)

Implementation note:
require_api_key lazy-imports get_current_user_optional inside the
function (circular-import guard). FastAPI dependency_overrides won't
hook a direct (non-Depends) call, so the cookie path is stubbed by
monkeypatching auth.dependencies.get_current_user_optional at the
module attribute. The lazy import inside require_api_key picks up
the patched callable.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.core import security as security_module
from app.core.security import require_api_key
from app.auth import dependencies as auth_deps


def _probe_client() -> TestClient:
    app = FastAPI()

    @app.get("/probe")
    def probe(_auth: None = Depends(require_api_key)):
        return {"ok": True}

    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_api_key(monkeypatch):
    monkeypatch.setattr(security_module.settings, "api_key", "")
    yield


def _patch_cookie_validator(monkeypatch, user_or_none):
    """Replace get_current_user_optional with a stub that returns
    `user_or_none` for any non-empty pz_session, and None otherwise.
    Patches the module attribute so the lazy import inside
    require_api_key picks up the stub.
    """
    def _stub(pz_session=None):
        if not pz_session:
            return None
        return user_or_none

    monkeypatch.setattr(auth_deps, "get_current_user_optional", _stub)


# ─────────────────────────────────────────────────────────────────────────
# Test 1: empty api_key passes through (current prod posture preserved)
# ─────────────────────────────────────────────────────────────────────────

def test_empty_api_key_passes_through_no_auth(monkeypatch):
    monkeypatch.setattr(security_module.settings, "api_key", "")
    client = _probe_client()
    r = client.get("/probe")
    assert r.status_code == 200, r.text


# ─────────────────────────────────────────────────────────────────────────
# Test 2: valid X-API-Key header passes when key is configured
# ─────────────────────────────────────────────────────────────────────────

def test_nonempty_api_key_valid_header_passes(monkeypatch):
    monkeypatch.setattr(security_module.settings, "api_key", "prod-key")
    _patch_cookie_validator(monkeypatch, None)
    client = _probe_client()
    r = client.get("/probe", headers={"X-API-Key": "prod-key"})
    assert r.status_code == 200, r.text


# ─────────────────────────────────────────────────────────────────────────
# Test 3: valid pz_session cookie passes
# ─────────────────────────────────────────────────────────────────────────

def test_nonempty_api_key_valid_cookie_passes(monkeypatch):
    monkeypatch.setattr(security_module.settings, "api_key", "prod-key")
    _patch_cookie_validator(monkeypatch, {"id": "u1", "role": "viewer"})
    client = _probe_client()
    client.cookies.set("pz_session", "anything")
    r = client.get("/probe")
    assert r.status_code == 200, r.text


# ─────────────────────────────────────────────────────────────────────────
# Test 4: no auth at all → 401
# ─────────────────────────────────────────────────────────────────────────

def test_nonempty_api_key_no_auth_rejects(monkeypatch):
    monkeypatch.setattr(security_module.settings, "api_key", "prod-key")
    _patch_cookie_validator(monkeypatch, None)
    client = _probe_client()
    r = client.get("/probe")
    assert r.status_code == 401, r.text


# ─────────────────────────────────────────────────────────────────────────
# Test 5: bad header rejects
# ─────────────────────────────────────────────────────────────────────────

def test_nonempty_api_key_bad_header_rejects(monkeypatch):
    monkeypatch.setattr(security_module.settings, "api_key", "prod-key")
    _patch_cookie_validator(monkeypatch, None)
    client = _probe_client()
    r = client.get("/probe", headers={"X-API-Key": "wrong-key"})
    assert r.status_code == 401, r.text


# ─────────────────────────────────────────────────────────────────────────
# Test 6: bad cookie rejects
# ─────────────────────────────────────────────────────────────────────────

def test_nonempty_api_key_bad_cookie_rejects(monkeypatch):
    monkeypatch.setattr(security_module.settings, "api_key", "prod-key")
    _patch_cookie_validator(monkeypatch, None)
    client = _probe_client()
    client.cookies.set("pz_session", "this.is.not-a-valid-jwt")
    r = client.get("/probe")
    assert r.status_code == 401, r.text


# ─────────────────────────────────────────────────────────────────────────
# Test 7: both valid → 200
# ─────────────────────────────────────────────────────────────────────────

def test_nonempty_api_key_both_valid_passes(monkeypatch):
    monkeypatch.setattr(security_module.settings, "api_key", "prod-key")
    _patch_cookie_validator(monkeypatch, {"id": "u1", "role": "viewer"})
    client = _probe_client()
    client.cookies.set("pz_session", "anything")
    r = client.get("/probe", headers={"X-API-Key": "prod-key"})
    assert r.status_code == 200, r.text


# ─────────────────────────────────────────────────────────────────────────
# Test 8: source uses constant-time comparison (regression guard)
# ─────────────────────────────────────────────────────────────────────────

def test_constant_time_compare_used():
    src = inspect.getsource(require_api_key)
    assert "compare_digest" in src, (
        "require_api_key must use hmac.compare_digest (or secrets.compare_digest) "
        "for the X-API-Key comparison — never raw `==` on the secret."
    )
    naive_eq_patterns = [
        "key == settings.api_key",
        "key==settings.api_key",
        "settings.api_key == key",
    ]
    for pat in naive_eq_patterns:
        assert pat not in src, (
            f"Naive equality `{pat}` detected; use hmac.compare_digest instead."
        )
