"""
test_tracking_guard.py — Hard-block tests for DHL Shipment Tracking API gate.

Cases:
  1. DHL_TRACKING_API_STATUS=pending  → available=False, no HTTP call
  2. No credentials                   → same fallback
  3. Credentials set but status=pending → same fallback (hard block fires first)
  4. Status=active + credentials      → proceeds to API call (call is mocked)

Run:
    pytest service/tests/test_tracking_guard.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_settings(**overrides):
    s = MagicMock()
    s.dhl_tracking_api_status = "pending"
    s.dhl_tracking_api_key    = None
    s.dhl_tracking_api_secret = None
    s.dhl_api_key             = None
    s.fedex_client_id         = None
    s.fedex_client_secret     = None
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _call(tracking_no: str = "1234567890", carrier: str = "DHL",
          cache_dir: Path = None, refresh: bool = False, **setting_overrides):
    # Use a unique tmp dir per call to prevent cache pollution between tests.
    if cache_dir is None:
        import tempfile
        cache_dir = Path(tempfile.mkdtemp(prefix="trk_guard_"))
    mock_settings = _make_settings(**setting_overrides)
    with patch("app.services.tracking_service.settings", mock_settings):
        from app.services import tracking_service
        # Reload to pick up patched settings reference
        import importlib
        importlib.reload(tracking_service)
        with patch("app.services.tracking_service.settings", mock_settings):
            return tracking_service.get_tracking_status(tracking_no, carrier, cache_dir, refresh=refresh)


# ── Case 1: status=pending, no credentials ────────────────────────────────────

def test_pending_status_returns_fallback_no_http():
    """DHL_TRACKING_API_STATUS=pending → available=False, no HTTP call made."""
    with patch("httpx.Client") as mock_http:
        result = _call(dhl_tracking_api_status="pending")

    assert result["available"] is False
    assert result["source"] == "api_pending"
    assert result["api_status"] == "pending"
    assert "tracking-id=1234567890" in result["tracking_url"]
    # No HTTP connection opened
    mock_http.assert_not_called()


# ── Case 2: no credentials ────────────────────────────────────────────────────

def test_no_credentials_returns_fallback():
    """All credential fields empty → available=False (pending fallback)."""
    with patch("httpx.Client") as mock_http:
        result = _call(
            dhl_tracking_api_status="pending",
            dhl_tracking_api_key=None,
            dhl_tracking_api_secret=None,
            dhl_api_key=None,
        )

    assert result["available"] is False
    assert result["source"] == "api_pending"
    mock_http.assert_not_called()


# ── Case 3: credentials present, status still pending ────────────────────────

def test_credentials_present_but_pending_still_blocked():
    """Credentials set but DHL_TRACKING_API_STATUS=pending → still blocked."""
    with patch("httpx.Client") as mock_http:
        result = _call(
            dhl_tracking_api_status="pending",
            dhl_tracking_api_key="test-key-1234",
            dhl_tracking_api_secret="test-secret-5678",
        )

    assert result["available"] is False
    assert result["source"] == "api_pending"
    mock_http.assert_not_called()


# ── Case 4: status=active → proceeds (mocked) ────────────────────────────────

def test_active_status_attempts_api_call():
    """DHL_TRACKING_API_STATUS=active + credentials → API call attempted."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "shipments": [{
            "status":      {"status": "delivered"},
            "events":      [{"timestamp": "2026-04-27T10:00:00Z", "location": {"address": {"addressLocality": "Warsaw", "countryCode": "PL"}}}],
            "origin":      {"address": {"addressLocality": "Mumbai", "countryCode": "IN"}},
            "destination": {"address": {"addressLocality": "Warsaw", "countryCode": "PL"}},
        }]
    }
    mock_response.raise_for_status = MagicMock()

    mock_token_resp = MagicMock()
    mock_token_resp.json.return_value = {"access_token": "test-token"}
    mock_token_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__  = MagicMock(return_value=False)
    mock_client.post.return_value = mock_token_resp
    mock_client.get.return_value  = mock_response

    with patch("httpx.Client", return_value=mock_client):
        result = _call(
            dhl_tracking_api_status="active",
            dhl_tracking_api_key="real-key-1234",
            dhl_tracking_api_secret="real-secret-5678",
            refresh=True,   # skip cache
        )

    assert result["available"] is True
    assert result["status"] == "delivered"
    assert result["source"] == "dhl_unified_api"


# ── Case 5: pending fallback shape is complete ────────────────────────────────

def test_pending_fallback_has_required_fields():
    """Fallback response contains all fields the UI expects."""
    result = _call(dhl_tracking_api_status="pending")

    required = ["available", "provider", "api_status", "reason",
                "tracking_url", "status", "last_update", "last_location"]
    for field in required:
        assert field in result, f"Missing field: {field}"

    assert result["provider"] == "dhl_unified_tracking"
    assert result["reason"]   == "DHL API not active (pending approval)"


# ── Case 6: no tracking number ───────────────────────────────────────────────

def test_empty_tracking_number_returns_error():
    result = _call(tracking_no="")
    assert result["available"] is False
    assert result["error"] is not None
