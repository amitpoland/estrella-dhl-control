"""Regression: a non-ASCII X-API-Key must yield 401, never a 500.

Root cause (production traceback 2026-06-11 14:33, pz_stderr):
    File "app/core/security.py", line 26, in require_api_key
        if key is not None and hmac.compare_digest(key, settings.api_key):
    TypeError: comparing strings with non-ASCII characters is not supported

hmac.compare_digest raises TypeError on `str` operands that contain non-ASCII
characters. The previous code passed the raw header `str` straight in, so any
request carrying a non-ASCII X-API-Key (e.g. a key corrupted with a Polish
character, smart-quote, or non-breaking space) produced an unhandled 500 — and
on at least one occasion took the worker down. A malformed credential is an
AUTH FAILURE (401), not a server error.

Fix: encode both operands to UTF-8 bytes before compare_digest. compare_digest
accepts arbitrary bytes and stays constant-time.

This file pins the contract at BOTH guard call sites and via source-grep so a
revert to raw-str comparison fails CI.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.core import security as security_module
from app.core.security import require_api_key, require_api_key_privileged
from app.auth import dependencies as auth_deps

# A representative non-ASCII key. Must be latin-1-encodable so the test HTTP
# client can actually transmit it as a header value (HTTP header values are
# latin-1 per RFC; httpx rejects anything outside that range). é (U+00E9) and
# ñ (U+00F1) are latin-1 yet non-ASCII (>127) — exactly the codepoints that made
# hmac.compare_digest raise TypeError pre-fix. This mirrors the real production
# trigger: UTF-8 key bytes decoded latin-1 by the server into a >127 str.
NON_ASCII_KEY = "wrong-kéy-señor"


def _probe_client(dep) -> TestClient:
    app = FastAPI()

    @app.get("/probe")
    def probe(_auth: None = Depends(dep)):
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False)


def _patch_cookie_validator(monkeypatch, user_or_none):
    def _stub(pz_session=None):
        return None if not pz_session else user_or_none

    monkeypatch.setattr(auth_deps, "get_current_user_optional", _stub)


# ─────────────────────────────────────────────────────────────────────────
# require_api_key — non-ASCII header must be 401, not 500
# ─────────────────────────────────────────────────────────────────────────

def test_require_api_key_non_ascii_key_raises_401_not_typeerror(monkeypatch):
    # Direct dependency-function call: faithful unit test of the compare_digest
    # path (httpx will not transmit a non-ASCII header value, so the route-level
    # reproduction uses raw bytes — see the end-to-end test below). Pre-fix this
    # raised TypeError; post-fix it must raise HTTPException(401).
    monkeypatch.setattr(security_module.settings, "api_key", "prod-key")
    _patch_cookie_validator(monkeypatch, None)
    with pytest.raises(HTTPException) as exc:
        require_api_key(key=NON_ASCII_KEY, pz_session=None)
    assert exc.value.status_code == 401


def test_require_api_key_non_ascii_header_end_to_end_is_401_not_500(monkeypatch):
    # End-to-end through the ASGI stack. The header is injected as raw latin-1
    # BYTES so Starlette decodes it into a >127 str — exactly what uvicorn did in
    # production. Pre-fix this returned 500 (TypeError); post-fix 401.
    monkeypatch.setattr(security_module.settings, "api_key", "prod-key")
    _patch_cookie_validator(monkeypatch, None)
    client = _probe_client(require_api_key)
    r = client.get("/probe", headers={"X-API-Key": NON_ASCII_KEY.encode("latin-1")})
    assert r.status_code != 500, (
        f"non-ASCII X-API-Key produced {r.status_code} (regression: TypeError "
        f"in hmac.compare_digest leaked as 500). Body: {r.text}"
    )
    assert r.status_code == 401, r.text


def test_require_api_key_valid_key_still_passes_after_fix(monkeypatch):
    monkeypatch.setattr(security_module.settings, "api_key", "prod-key")
    _patch_cookie_validator(monkeypatch, None)
    client = _probe_client(require_api_key)
    r = client.get("/probe", headers={"X-API-Key": "prod-key"})
    assert r.status_code == 200, r.text


def test_require_api_key_non_ascii_settings_key_does_not_500(monkeypatch):
    # Defensive: even if the CONFIGURED key were non-ASCII, a mismatching ASCII
    # header must 401, not 500.
    monkeypatch.setattr(security_module.settings, "api_key", "kłucz-produkcyjny")
    _patch_cookie_validator(monkeypatch, None)
    client = _probe_client(require_api_key)
    r = client.get("/probe", headers={"X-API-Key": "prod-key"})
    assert r.status_code != 500, r.text
    assert r.status_code == 401, r.text


# ─────────────────────────────────────────────────────────────────────────
# require_api_key_privileged — same guarantee
# ─────────────────────────────────────────────────────────────────────────

def test_require_api_key_privileged_non_ascii_key_raises_401_not_typeerror(monkeypatch):
    monkeypatch.setattr(security_module.settings, "api_key", "prod-key")
    _patch_cookie_validator(monkeypatch, None)
    with pytest.raises(HTTPException) as exc:
        require_api_key_privileged(key=NON_ASCII_KEY, pz_session=None)
    assert exc.value.status_code == 401


def test_require_api_key_privileged_valid_key_still_passes(monkeypatch):
    monkeypatch.setattr(security_module.settings, "api_key", "prod-key")
    _patch_cookie_validator(monkeypatch, None)
    client = _probe_client(require_api_key_privileged)
    r = client.get("/probe", headers={"X-API-Key": "prod-key"})
    assert r.status_code == 200, r.text


# ─────────────────────────────────────────────────────────────────────────
# Source-grep pins — revert to raw-str compare must fail CI
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fn", [require_api_key, require_api_key_privileged])
def test_compare_digest_encodes_to_bytes(fn):
    src = inspect.getsource(fn)
    assert "compare_digest" in src, f"{fn.__name__} must use hmac.compare_digest"
    assert ".encode(" in src, (
        f"{fn.__name__} must encode operands to bytes before compare_digest "
        f"(raw str raises TypeError on non-ASCII keys → 500). Regression guard."
    )
    # The exact vulnerable pattern (raw str args) must not reappear.
    assert "compare_digest(key, settings.api_key)" not in src, (
        f"{fn.__name__} reverted to raw-str compare_digest — non-ASCII keys "
        f"will 500 again."
    )
