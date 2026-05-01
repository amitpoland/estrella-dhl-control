"""
test_dhl_api_activation.py — DHL API activation and cache TTL tests.

Cases:
  1. API success → available=True, source=dhl_unified_api
  2. API failure → fallback fires (available=False, cowork_tracking_required=True)
  3. Cache hit within 15 min → source=cache, no API call
  4. Cache expired (>15 min) → API call made, cache refreshed
  5. status=active but no credentials → no_credentials base response
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_settings(**overrides):
    s = MagicMock()
    s.dhl_tracking_api_status = "active"
    s.dhl_tracking_api_key    = "test-key"
    s.dhl_tracking_api_secret = "test-secret"
    s.dhl_api_key             = None
    s.fedex_client_id         = None
    s.fedex_client_secret     = None
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _dhl_api_response(status: str = "delivered") -> dict:
    return {
        "shipments": [{
            "status": {"status": status, "description": status.title()},
            "events": [{
                "timestamp": "2026-04-28T10:00:00Z",
                "location":  {"address": {"addressLocality": "Warsaw", "countryCode": "PL"}},
            }],
            "origin":      {"address": {"addressLocality": "Mumbai",  "countryCode": "IN"}},
            "destination": {"address": {"addressLocality": "Warsaw",  "countryCode": "PL"}},
        }]
    }


def _mock_httpx_client(api_payload: dict):
    """Return a mock httpx.Client that succeeds for both token + tracking calls."""
    token_resp = MagicMock()
    token_resp.json.return_value = {"access_token": "tok-xyz"}
    token_resp.raise_for_status = MagicMock()

    track_resp = MagicMock()
    track_resp.json.return_value = api_payload
    track_resp.raise_for_status = MagicMock()

    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__  = MagicMock(return_value=False)
    client.post.return_value = token_resp
    client.get.return_value  = track_resp
    return client


def _call(tmp_path, refresh=False, **setting_overrides):
    mock_settings = _make_settings(**setting_overrides)
    import importlib
    import app.services.tracking_service as ts
    importlib.reload(ts)
    with patch("app.services.tracking_service.settings", mock_settings):
        return ts.get_tracking_status("1234567890", "DHL", tmp_path, refresh=refresh)


# ── Test 1: API success ───────────────────────────────────────────────────────

def test_api_success_returns_live_result(tmp_path):
    """status=active + credentials → available=True, source=dhl_unified_api."""
    mock_client = _mock_httpx_client(_dhl_api_response("delivered"))
    with patch("httpx.Client", return_value=mock_client):
        result = _call(tmp_path, refresh=True)

    assert result["available"] is True
    assert result["source"]    == "dhl_unified_api"
    assert result["status"]    == "delivered"
    assert result["tracking_no"] == "1234567890"
    assert result["carrier"]     == "DHL"


# ── Test 2: API failure → fallback ────────────────────────────────────────────

def test_api_failure_returns_fallback(tmp_path):
    """API raises exception → fallback (available=False, cowork_tracking_required=True).
    Unified API uses GET with DHL-API-Key header (no OAuth POST step).
    """
    failing_client = MagicMock()
    failing_client.__enter__ = MagicMock(return_value=failing_client)
    failing_client.__exit__  = MagicMock(return_value=False)
    failing_client.get.side_effect = Exception("connection refused")

    with patch("httpx.Client", return_value=failing_client):
        result = _call(tmp_path, refresh=True)

    assert result["available"] is False
    assert result["source"]    == "error"
    assert result["error"] is not None


# ── Test 3: Cache hit within 15 min ──────────────────────────────────────────

def test_cache_hit_within_ttl_skips_api(tmp_path):
    """If cache entry is < 15 min old, return cached result without API call."""
    from datetime import datetime, timezone

    # Pre-populate cache
    cached = {
        "1234567890": {
            "available":   True,
            "source":      "dhl_unified_api",
            "status":      "in_transit",
            "status_label": "In Transit",
            "cached_at":   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tracking_no": "1234567890",
            "carrier":     "DHL",
        }
    }
    (tmp_path / "tracking_cache.json").write_text(
        json.dumps(cached), encoding="utf-8"
    )

    with patch("httpx.Client") as mock_http:
        result = _call(tmp_path, refresh=False)

    assert result["source"]  == "cache"
    assert result["status"]  == "in_transit"
    mock_http.assert_not_called()


# ── Test 4: Cache expired > 15 min → API call ────────────────────────────────

def test_cache_expired_triggers_api_call(tmp_path):
    """Cache entry older than 15 min → ignored, live API call made."""
    # Stamp cached_at 20 minutes ago
    old_ts = "2026-04-28T00:00:00Z"   # fixed old timestamp
    cached = {
        "1234567890": {
            "available":   True,
            "source":      "dhl_unified_api",
            "status":      "in_transit",
            "cached_at":   old_ts,
            "tracking_no": "1234567890",
            "carrier":     "DHL",
        }
    }
    (tmp_path / "tracking_cache.json").write_text(
        json.dumps(cached), encoding="utf-8"
    )

    mock_client = _mock_httpx_client(_dhl_api_response("delivered"))
    with patch("httpx.Client", return_value=mock_client):
        result = _call(tmp_path, refresh=False)

    # Should NOT return the stale cache entry
    assert result["source"] != "cache"
    assert result["available"] is True
    assert result["status"] == "delivered"


# ── Test 5: status=active but no credentials → no_credentials ────────────────

def test_active_status_no_credentials_returns_base(tmp_path):
    """status=active but no credentials at all → base response (no_credentials)."""
    result = _call(
        tmp_path, refresh=True,
        dhl_tracking_api_status="active",
        dhl_tracking_api_key=None,
        dhl_tracking_api_secret=None,
        dhl_api_key=None,
    )
    assert result["available"] is False
    assert result["source"]    == "no_credentials"
