"""
test_tracking_terminal.py — Terminal-state tracking lock.

Once a shipment is delivered (or has a delivery proof PDF on disk), no further
DHL/FedEx API calls are made. Cached snapshot is the source of truth. Protects
the 250-call/day DHL quota.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _settings_active(monkeypatch):
    """Mock settings so DHL API is 'active' and creds are present."""
    s = MagicMock()
    s.dhl_tracking_api_status = "active"
    s.dhl_tracking_api_key    = "test-key"
    s.dhl_tracking_api_secret = "test-secret"
    s.dhl_api_key             = None
    s.fedex_client_id         = None
    s.fedex_client_secret     = None
    monkeypatch.setattr("app.services.tracking_service.settings", s)


def _cache_with(tmp_path: Path, tracking_no: str, payload: dict) -> Path:
    """Write tracking_cache.json with one entry."""
    (tmp_path / "tracking_cache.json").write_text(
        json.dumps({tracking_no: payload}, ensure_ascii=False), encoding="utf-8"
    )
    return tmp_path


# ── Rule 1: status=delivered → no API call ───────────────────────────────────

def test_delivered_status_skips_api(tmp_path, monkeypatch):
    _settings_active(monkeypatch)
    _cache_with(tmp_path, "1234567890", {
        "tracking_no": "1234567890",
        "carrier":     "DHL",
        "status":      "delivered",
        "status_label": "Delivered",
        "cached_at":   "2026-04-01T10:00:00Z",
        "available":   True,
    })
    from app.services import tracking_service as ts
    with patch("httpx.Client") as mock_client:
        result = ts.get_tracking_status("1234567890", "DHL", tmp_path, refresh=True)
    # API must NOT have been called
    mock_client.assert_not_called()
    assert result["status"] == "delivered"
    assert result["tracking_terminal"] is True
    assert result["tracking_terminal_reason"] == "status_delivered"
    assert result["source"] == "cache"


def test_returned_status_also_terminal(tmp_path, monkeypatch):
    _settings_active(monkeypatch)
    _cache_with(tmp_path, "9999999999", {"tracking_no": "9999999999", "carrier": "DHL", "status": "returned", "cached_at": "2026-04-01T10:00:00Z"})
    from app.services import tracking_service as ts
    with patch("httpx.Client") as mock_client:
        result = ts.get_tracking_status("9999999999", "DHL", tmp_path, refresh=True)
    mock_client.assert_not_called()
    assert result["tracking_terminal"] is True


# ── Rule 2: delivery proof PDF → no API call ─────────────────────────────────

def test_delivery_proof_pdf_skips_api(tmp_path, monkeypatch):
    _settings_active(monkeypatch)
    # No cached entry, but POD PDF on disk
    (tmp_path / "POD_1234567890.pdf").write_bytes(b"%PDF-1.4 fake")
    from app.services import tracking_service as ts
    with patch("httpx.Client") as mock_client:
        result = ts.get_tracking_status("5555555555", "DHL", tmp_path, refresh=True)
    mock_client.assert_not_called()
    assert result["tracking_terminal"] is True
    assert result["tracking_terminal_reason"] == "delivery_proof_present"
    assert result["status"] == "delivered"


def test_delivery_proof_alt_filename_also_works(tmp_path, monkeypatch):
    _settings_active(monkeypatch)
    (tmp_path / "DELIVERY_PROOF.pdf").write_bytes(b"%PDF-1.4 fake")
    from app.services import tracking_service as ts
    with patch("httpx.Client") as mock_client:
        ts.get_tracking_status("777", "DHL", tmp_path, refresh=True)
    mock_client.assert_not_called()


# ── Rule 3: active status → DOES refresh on refresh=True ─────────────────────

def test_in_transit_status_still_refreshes(tmp_path, monkeypatch):
    _settings_active(monkeypatch)
    _cache_with(tmp_path, "1234567890", {
        "tracking_no": "1234567890",
        "carrier":     "DHL",
        "status":      "in_transit",
        "cached_at":   "2026-04-01T10:00:00Z",
    })
    # Mock httpx to return a "delivered" live response
    from app.services import tracking_service as ts
    track_resp = MagicMock()
    track_resp.json.return_value = {"shipments": [{
        "status":      {"status": "delivered", "description": "Delivered"},
        "events":      [{"timestamp": "2026-04-28T10:00:00Z", "description": "Delivered",
                          "location": {"address": {"addressLocality": "Warsaw", "countryCode": "PL"}}}],
        "origin":      {"address": {"addressLocality": "Mumbai", "countryCode": "IN"}},
        "destination": {"address": {"addressLocality": "Warsaw", "countryCode": "PL"}},
    }]}
    track_resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__  = MagicMock(return_value=False)
    client.get.return_value = track_resp
    with patch("httpx.Client", return_value=client):
        result = ts.get_tracking_status("1234567890", "DHL", tmp_path, refresh=True)
    # API WAS called
    client.get.assert_called()
    # Result is fresh delivered
    assert result["status"] == "delivered"
    # Now flagged terminal because the new status is delivered
    assert result["tracking_terminal"] is True


# ── Rule 4: UI exposed flags ─────────────────────────────────────────────────

def test_active_status_marked_terminal_false(tmp_path, monkeypatch):
    _settings_active(monkeypatch)
    _cache_with(tmp_path, "1234567890", {
        "tracking_no": "1234567890",
        "carrier":     "DHL",
        "status":      "in_transit",
        "cached_at":   "2999-01-01T00:00:00Z",   # always fresh
    })
    from app.services import tracking_service as ts
    with patch("httpx.Client") as mock_client:
        result = ts.get_tracking_status("1234567890", "DHL", tmp_path, refresh=False)
    mock_client.assert_not_called()
    assert result["status"] == "in_transit"
    assert result["tracking_terminal"] is False


def test_terminal_set_returns_expected_keys():
    from app.services.tracking_service import TERMINAL_STATUSES
    assert "delivered" in TERMINAL_STATUSES
    assert "returned"  in TERMINAL_STATUSES
    assert "cancelled" in TERMINAL_STATUSES
    assert "in_transit" not in TERMINAL_STATUSES
    assert "out_for_delivery" not in TERMINAL_STATUSES
