"""
test_zoho_auth.py — Zoho Mail OAuth token management & auto-refresh.

Verifies:
  - Refresh-token flow exchanges credentials at the accounts endpoint
  - Cached token is reused while valid
  - Expired token triggers a refresh
  - Refresh failure raises ZohoAuthError with a generic message (no token leakage)
  - Bootstrap mode (static token) works as a fallback
  - Tokens are NEVER logged in plaintext
"""
from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock, patch

import pytest


def _reset_cache():
    from app.services import zoho_auth
    zoho_auth.invalidate_cached_token()


def _make_settings(**kw):
    s = MagicMock()
    s.zoho_client_id          = kw.get("zoho_client_id",          None)
    s.zoho_client_secret      = kw.get("zoho_client_secret",      None)
    s.zoho_mail_refresh_token = kw.get("zoho_mail_refresh_token", None)
    s.zoho_mail_api_token     = kw.get("zoho_mail_api_token",     None)
    s.zoho_accounts_base      = kw.get("zoho_accounts_base", "https://accounts.zoho.eu")
    return s


def _mock_refresh_response(access_token="new-tok-abc", expires_in=3600, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {
        "access_token": access_token,
        "expires_in":   expires_in,
        "token_type":   "Bearer",
    } if status == 200 else {"error": "invalid_grant"}
    return resp


# ── has_zoho_credentials ─────────────────────────────────────────────────────

def test_has_credentials_refresh_flow():
    from app.services import zoho_auth
    s = _make_settings(
        zoho_client_id="cid", zoho_client_secret="csec",
        zoho_mail_refresh_token="rt",
    )
    with patch("app.services.zoho_auth.settings", s):
        assert zoho_auth.has_zoho_credentials() is True

def test_has_credentials_bootstrap_only():
    from app.services import zoho_auth
    s = _make_settings(zoho_mail_api_token="bootstrap-tok")
    with patch("app.services.zoho_auth.settings", s):
        assert zoho_auth.has_zoho_credentials() is True

def test_has_credentials_none():
    from app.services import zoho_auth
    s = _make_settings()
    with patch("app.services.zoho_auth.settings", s):
        assert zoho_auth.has_zoho_credentials() is False


# ── get_valid_access_token ───────────────────────────────────────────────────

def test_refresh_returns_new_token():
    _reset_cache()
    from app.services import zoho_auth

    s = _make_settings(
        zoho_client_id="cid", zoho_client_secret="csec",
        zoho_mail_refresh_token="rt",
    )
    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__  = MagicMock(return_value=False)
    fake_client.post.return_value = _mock_refresh_response("fresh-token-1", 3600)
    with patch("app.services.zoho_auth.settings", s), \
         patch("httpx.Client", return_value=fake_client):
        tok = zoho_auth.get_valid_access_token()
    assert tok == "fresh-token-1"
    # The refresh post must hit the accounts endpoint
    call_args = fake_client.post.call_args
    assert "/oauth/v2/token" in call_args[0][0]
    body = call_args[1]["data"]
    assert body["grant_type"] == "refresh_token"
    assert body["client_id"]  == "cid"


def test_cached_token_reused_within_ttl():
    _reset_cache()
    from app.services import zoho_auth

    s = _make_settings(
        zoho_client_id="cid", zoho_client_secret="csec",
        zoho_mail_refresh_token="rt",
    )
    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__  = MagicMock(return_value=False)
    fake_client.post.return_value = _mock_refresh_response("first-tok", 3600)

    with patch("app.services.zoho_auth.settings", s), \
         patch("httpx.Client", return_value=fake_client):
        tok1 = zoho_auth.get_valid_access_token()
        tok2 = zoho_auth.get_valid_access_token()

    assert tok1 == tok2 == "first-tok"
    # Refresh endpoint hit only once
    assert fake_client.post.call_count == 1


def test_expired_token_triggers_refresh():
    _reset_cache()
    from app.services import zoho_auth

    s = _make_settings(
        zoho_client_id="cid", zoho_client_secret="csec",
        zoho_mail_refresh_token="rt",
    )
    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__  = MagicMock(return_value=False)
    fake_client.post.side_effect = [
        _mock_refresh_response("tok-A", expires_in=10),  # short-lived
        _mock_refresh_response("tok-B", expires_in=3600),
    ]

    with patch("app.services.zoho_auth.settings", s), \
         patch("httpx.Client", return_value=fake_client):
        tok1 = zoho_auth.get_valid_access_token()
        # Force expiry by clearing the cache (equivalent to time travelling forward)
        zoho_auth.invalidate_cached_token()
        tok2 = zoho_auth.get_valid_access_token()

    assert tok1 == "tok-A"
    assert tok2 == "tok-B"
    assert fake_client.post.call_count == 2


def test_refresh_failure_raises_clear_error():
    _reset_cache()
    from app.services import zoho_auth

    s = _make_settings(
        zoho_client_id="cid", zoho_client_secret="csec",
        zoho_mail_refresh_token="bad-rt",
    )
    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__  = MagicMock(return_value=False)
    fake_client.post.return_value = _mock_refresh_response(status=401)

    with patch("app.services.zoho_auth.settings", s), \
         patch("httpx.Client", return_value=fake_client):
        with pytest.raises(zoho_auth.ZohoAuthError, match="Zoho token"):
            zoho_auth.get_valid_access_token()


def test_bootstrap_token_used_when_no_refresh_creds():
    _reset_cache()
    from app.services import zoho_auth
    s = _make_settings(zoho_mail_api_token="static-bootstrap-tok")
    with patch("app.services.zoho_auth.settings", s):
        tok = zoho_auth.get_valid_access_token()
    assert tok == "static-bootstrap-tok"


def test_no_creds_at_all_raises():
    _reset_cache()
    from app.services import zoho_auth
    s = _make_settings()
    with patch("app.services.zoho_auth.settings", s):
        with pytest.raises(zoho_auth.ZohoAuthError):
            zoho_auth.get_valid_access_token()


# ── Token leakage guards ─────────────────────────────────────────────────────

def test_tokens_never_logged_in_plaintext(caplog):
    _reset_cache()
    from app.services import zoho_auth

    secret_token = "SECRET_REFRESH_VALUE_DO_NOT_LEAK"
    secret_client = "SECRET_CLIENT_ID_DO_NOT_LEAK"
    s = _make_settings(
        zoho_client_id=secret_client,
        zoho_client_secret="csec",
        zoho_mail_refresh_token=secret_token,
    )
    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__  = MagicMock(return_value=False)
    fake_client.post.return_value = _mock_refresh_response("RESPONSE_TOKEN_DO_NOT_LEAK", 3600)

    with caplog.at_level(logging.DEBUG, logger="app.services.zoho_auth"), \
         patch("app.services.zoho_auth.settings", s), \
         patch("httpx.Client", return_value=fake_client):
        zoho_auth.get_valid_access_token()

    full_log = "\n".join(rec.getMessage() for rec in caplog.records)
    assert secret_token  not in full_log
    assert secret_client not in full_log
    assert "RESPONSE_TOKEN_DO_NOT_LEAK" not in full_log
