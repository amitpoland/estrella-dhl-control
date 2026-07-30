"""
test_cliq_service.py — Cliq channel OAuth token hardening tests.

Verifies:
  - Cached token is reused without triggering refresh
  - Successful refresh updates _access_token via the lock
  - Refresh failure returns empty string safely
  - Refresh error logging does NOT expose full response body
  - Token values are NEVER logged in plaintext
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


def _run(coro):
    """Run an async coroutine synchronously (no pytest-asyncio needed).

    Uses a dedicated fresh event loop per call so it stays robust even after
    another test module called asyncio.run() (which sets the current loop to
    None). The autouse fixture resets cliq_service._token_lock so the module's
    lazily-created asyncio.Lock re-binds to this loop rather than a closed one.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _reset_token():
    """Clear the module-level cached token between tests."""
    from app.services import cliq_service
    cliq_service._access_token = ""


def _make_settings(**kw):
    s = MagicMock()
    s.cliq_bot_token     = kw.get("cliq_bot_token", "")
    s.cliq_refresh_token = kw.get("cliq_refresh_token", "")
    s.cliq_client_id     = kw.get("cliq_client_id", "")
    s.cliq_client_secret = kw.get("cliq_client_secret", "")
    s.cliq_webhook_url   = kw.get("cliq_webhook_url", "")
    s.cliq_channel_api_url     = kw.get("cliq_channel_api_url", "")
    s.cliq_channel_webhook_url = kw.get("cliq_channel_webhook_url", "")
    return s


def _mock_httpx_response(status_code=200, json_data=None):
    """httpx.Response — json() and raise_for_status() are sync methods."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


def _mock_sync_client(resp=None, exc=None):
    """Build a mock httpx.Client SYNC context manager.

    Since the stuck-OPEN circuit-breaker fix, _refresh_access_token routes its
    POST through CircuitBreaker.call() via asyncio.to_thread using a synchronous
    httpx.Client (the breaker itself is synchronous). post() is therefore a sync
    MagicMock; the response object is a MagicMock with sync json()/raise_for_status().
    """
    mock_client = MagicMock()
    if exc:
        mock_client.post = MagicMock(side_effect=exc)
    else:
        mock_client.post = MagicMock(return_value=resp)
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    return mock_client


@pytest.fixture(autouse=True)
def _isolate_cliq_breaker():
    """Reset the zoho_cliq circuit before/after each test and neutralise the
    breaker's retry sleeps.

    Token refresh now flows through CircuitBreaker.call(); without this fixture
    a failure test would leak breaker failure-count into later tests and the
    breaker's real time.sleep() retry backoff would add seconds to the suite.
    """
    from app.core.circuit_breaker import get_circuit_breaker
    from app.services import cliq_service
    # Drop the lazily-created module-global asyncio.Lock so it re-binds to this
    # test's fresh event loop (see _run). Reusing a Lock bound to a closed loop
    # from a prior test raises "bound to a different event loop".
    cliq_service._token_lock = None
    cliq_service._access_token = ""
    get_circuit_breaker("zoho_cliq").force_close()
    with patch("app.core.circuit_breaker.time.sleep", lambda *_a, **_k: None):
        yield
    cliq_service._token_lock = None
    cliq_service._access_token = ""
    get_circuit_breaker("zoho_cliq").force_close()


# ── 1. Cached token returned without refresh ────────────────────────────────

def test_get_access_token_returns_cached():
    """When _access_token is already set, return it without reading settings."""
    _reset_token()
    from app.services import cliq_service
    cliq_service._access_token = "cached-token-xyz"

    s = _make_settings()
    with patch("app.services.cliq_service.settings", s):
        tok = _run(cliq_service._get_access_token())

    assert tok == "cached-token-xyz"
    _reset_token()


def test_get_access_token_populates_from_settings_on_first_call():
    """When _access_token is empty, populate from settings.cliq_bot_token."""
    _reset_token()
    from app.services import cliq_service

    s = _make_settings(cliq_bot_token="initial-from-settings")
    with patch("app.services.cliq_service.settings", s):
        tok = _run(cliq_service._get_access_token())

    assert tok == "initial-from-settings"
    _reset_token()


# ── 2. Successful refresh updates _access_token ─────────────────────────────

def test_refresh_updates_access_token():
    """A successful OAuth refresh stores the new token in _access_token."""
    _reset_token()
    from app.services import cliq_service

    s = _make_settings(
        cliq_refresh_token="rt", cliq_client_id="cid", cliq_client_secret="csec",
    )
    mock_resp = _mock_httpx_response(200, {"access_token": "fresh-token-001"})
    mock_client = _mock_sync_client(resp=mock_resp)

    with patch("app.services.cliq_service.settings", s), \
         patch("httpx.Client", return_value=mock_client):
        tok = _run(cliq_service._refresh_access_token())

    assert tok == "fresh-token-001"
    assert cliq_service._access_token == "fresh-token-001"
    _reset_token()


# ── 3. Refresh failure returns empty string ──────────────────────────────────

def test_refresh_failure_returns_empty():
    """When OAuth refresh raises an exception, return empty string safely."""
    _reset_token()
    from app.services import cliq_service

    s = _make_settings(
        cliq_refresh_token="rt", cliq_client_id="cid", cliq_client_secret="csec",
    )
    mock_client = _mock_sync_client(exc=Exception("connection timeout"))

    with patch("app.services.cliq_service.settings", s), \
         patch("httpx.Client", return_value=mock_client):
        tok = _run(cliq_service._refresh_access_token())

    assert tok == ""
    assert cliq_service._access_token == ""
    _reset_token()


def test_refresh_missing_creds_returns_empty():
    """When OAuth credentials are not configured, return empty string."""
    _reset_token()
    from app.services import cliq_service

    s = _make_settings()  # no refresh creds
    with patch("app.services.cliq_service.settings", s):
        tok = _run(cliq_service._refresh_access_token())

    assert tok == ""
    _reset_token()


# ── 4. Refresh error logging does NOT expose full response body ──────────────

def test_refresh_error_log_does_not_contain_full_body(caplog):
    """When refresh returns no access_token, the error log must NOT dump the full response."""
    _reset_token()
    from app.services import cliq_service

    s = _make_settings(
        cliq_refresh_token="rt", cliq_client_id="cid", cliq_client_secret="csec",
    )
    error_body = {
        "error": "invalid_code",
        "refresh_token": "LEAKED_REFRESH_DO_NOT_LOG",
        "secret_field": "LEAKED_SECRET_DO_NOT_LOG",
    }
    mock_resp = _mock_httpx_response(200, error_body)
    mock_resp.raise_for_status = MagicMock()  # 200 doesn't raise
    mock_client = _mock_sync_client(resp=mock_resp)

    with caplog.at_level(logging.DEBUG, logger="app.services.cliq_service"), \
         patch("app.services.cliq_service.settings", s), \
         patch("httpx.Client", return_value=mock_client):
        tok = _run(cliq_service._refresh_access_token())

    assert tok == ""

    full_log = "\n".join(rec.getMessage() for rec in caplog.records)
    # The safe field "invalid_code" SHOULD appear (that's what we log)
    assert "invalid_code" in full_log
    # The dangerous fields must NOT appear
    assert "LEAKED_REFRESH_DO_NOT_LOG" not in full_log
    assert "LEAKED_SECRET_DO_NOT_LOG" not in full_log
    _reset_token()


# ── 5. Tokens never logged in plaintext on success ──────────────────────────

def test_tokens_never_logged_on_success(caplog):
    """After a successful refresh, no token value appears in log output."""
    _reset_token()
    from app.services import cliq_service

    secret_token = "SECRET_ACCESS_TOKEN_MUST_NOT_LEAK"
    s = _make_settings(
        cliq_refresh_token="SECRET_REFRESH_MUST_NOT_LEAK",
        cliq_client_id="SECRET_CLIENT_ID_MUST_NOT_LEAK",
        cliq_client_secret="SECRET_CLIENT_SECRET_MUST_NOT_LEAK",
    )
    mock_resp = _mock_httpx_response(200, {"access_token": secret_token})
    mock_client = _mock_sync_client(resp=mock_resp)

    with caplog.at_level(logging.DEBUG, logger="app.services.cliq_service"), \
         patch("app.services.cliq_service.settings", s), \
         patch("httpx.Client", return_value=mock_client):
        tok = _run(cliq_service._refresh_access_token())

    assert tok == secret_token

    full_log = "\n".join(rec.getMessage() for rec in caplog.records)
    assert secret_token not in full_log
    assert "SECRET_REFRESH_MUST_NOT_LEAK" not in full_log
    assert "SECRET_CLIENT_ID_MUST_NOT_LEAK" not in full_log
    assert "SECRET_CLIENT_SECRET_MUST_NOT_LEAK" not in full_log
    _reset_token()


# ── 6. Refresh response missing access_token logs only safe error key ────────

def test_refresh_missing_token_logs_error_key_only(caplog):
    """When access_token is absent, log only data.get('error'), not the whole dict."""
    _reset_token()
    from app.services import cliq_service

    s = _make_settings(
        cliq_refresh_token="rt", cliq_client_id="cid", cliq_client_secret="csec",
    )
    mock_resp = _mock_httpx_response(200, {"error": "access_denied"})
    mock_resp.raise_for_status = MagicMock()
    mock_client = _mock_sync_client(resp=mock_resp)

    with caplog.at_level(logging.DEBUG, logger="app.services.cliq_service"), \
         patch("app.services.cliq_service.settings", s), \
         patch("httpx.Client", return_value=mock_client):
        tok = _run(cliq_service._refresh_access_token())

    assert tok == ""
    full_log = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "access_denied" in full_log
    _reset_token()
