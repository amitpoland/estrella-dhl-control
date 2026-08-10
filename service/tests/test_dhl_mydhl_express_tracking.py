"""MyDHL Express is the primary DHL tracking authority for Express AWBs.

Unified Tracking remains controlled fallback on genuine outage only.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest


MYDHL_BODY = {
    "shipments": [
        {
            "shipmentTrackingNumber": "1555081404",
            "status": "Success",
            "estimatedDeliveryDate": "2026-08-11T23:59:00",
            "shipperDetails": {
                "postalAddress": {"cityName": "Warszawa", "countryCode": "PL"}
            },
            "receiverDetails": {
                "postalAddress": {"cityName": "Prague", "countryCode": "CZ"}
            },
            "events": [
                {
                    "date": "2026-08-10",
                    "time": "15:49:18",
                    "typeCode": "SA",
                    "description": "Shipment Accepted",
                    "serviceArea": [{"code": "WAW", "description": "Warsaw-PL"}],
                },
                {
                    "date": "2026-08-10",
                    "time": "17:59:00",
                    "typeCode": "PL",
                    "description": "Processed at WARSAW-POLAND",
                    "serviceArea": [{"code": "WAW", "description": "Warsaw-PL"}],
                },
                {
                    "date": "2026-08-10",
                    "time": "22:05:58",
                    "typeCode": "DF",
                    "description": "Shipment has departed from a DHL facility WARSAW-POLAND",
                    "serviceArea": [{"code": "WAW", "description": "Warsaw-PL"}],
                },
            ],
        }
    ]
}


def test_normalise_mydhl_events_location_and_order():
    from app.services.tracking_service import (
        _derive_status_from_events,
        _normalise_dhl_events,
    )

    events = _normalise_dhl_events(MYDHL_BODY["shipments"][0]["events"])
    assert len(events) == 3
    assert events[0]["description"] == "Shipment Accepted"
    assert "WARSAW" in events[1]["location"]
    assert events[-1]["timestamp"].startswith("2026-08-10T22:05:58")
    status, label = _derive_status_from_events(events)
    assert status == "in_transit"
    assert "Transit" in label or "transit" in label.lower() or label == "In Transit"


def test_call_dhl_prefers_mydhl_over_unified(monkeypatch):
    from app.services import tracking_service as ts

    monkeypatch.setattr(ts.settings, "dhl_tracking_api_status", "active", raising=False)
    monkeypatch.setattr(ts.settings, "dhl_express_api_key", "ek", raising=False)
    monkeypatch.setattr(ts.settings, "dhl_express_api_secret", "es", raising=False)
    monkeypatch.setattr(ts.settings, "dhl_tracking_api_key", "uk", raising=False)
    monkeypatch.setattr(ts.settings, "dhl_tracking_api_secret", "us", raising=False)

    calls = {"mydhl": 0, "unified": 0}

    def _mydhl(awb):
        calls["mydhl"] += 1
        return {
            "status": "in_transit",
            "status_label": "In Transit",
            "source": "dhl_mydhl_express",
            "tracking_provider": "mydhl_express",
            "last_http_status": 200,
            "events": [{"timestamp": "2026-08-10T17:59:00", "description": "Processed at WARSAW", "location": "WARSAW - PL", "status": "PL"}],
            "events_count": 1,
            "last_location": "WARSAW - PL",
            "last_event": "Processed at WARSAW",
        }

    def _unified(awb):
        calls["unified"] += 1
        raise AssertionError("Unified must not run when MyDHL succeeds")

    monkeypatch.setattr(ts, "_call_dhl_mydhl_express", _mydhl)
    monkeypatch.setattr(ts, "_call_dhl_unified", _unified)
    out = ts._call_dhl("1555081404")
    assert calls == {"mydhl": 1, "unified": 0}
    assert out["tracking_provider"] == "mydhl_express"
    assert out["last_location"] == "WARSAW - PL"


def test_unified_fallback_only_on_outage(monkeypatch):
    from app.services import tracking_service as ts

    monkeypatch.setattr(ts.settings, "dhl_tracking_api_status", "active", raising=False)
    monkeypatch.setattr(ts.settings, "dhl_express_api_key", "ek", raising=False)
    monkeypatch.setattr(ts.settings, "dhl_express_api_secret", "es", raising=False)
    monkeypatch.setattr(ts.settings, "dhl_tracking_api_key", "uk", raising=False)

    def _boom(_awb):
        raise RuntimeError("DHL API 503: upstream unavailable")

    def _unified(_awb):
        return {
            "status": "in_transit",
            "source": "dhl_unified_api",
            "events": [],
            "events_count": 0,
            "last_event": "",
        }

    monkeypatch.setattr(ts, "_call_dhl_mydhl_express", _boom)
    monkeypatch.setattr(ts, "_call_dhl_unified", _unified)
    out = ts._call_dhl("1555081404")
    assert out["tracking_provider"] == "unified_fallback"


def test_mydhl_404_does_not_fallback_to_unified(monkeypatch):
    from app.services import tracking_service as ts
    from app.services.carrier.models.shipment import CarrierGateError

    monkeypatch.setattr(ts.settings, "dhl_tracking_api_status", "active", raising=False)
    monkeypatch.setattr(ts.settings, "dhl_express_api_key", "ek", raising=False)
    monkeypatch.setattr(ts.settings, "dhl_express_api_secret", "es", raising=False)
    monkeypatch.setattr(ts.settings, "dhl_tracking_api_key", "uk", raising=False)

    def _miss(_awb):
        raise CarrierGateError("DHL API 404: Not Found")

    monkeypatch.setattr(ts, "_call_dhl_mydhl_express", _miss)
    monkeypatch.setattr(
        ts,
        "_call_dhl_unified",
        lambda _a: (_ for _ in ()).throw(AssertionError("no unified on 404")),
    )
    with pytest.raises(CarrierGateError):
        ts._call_dhl("1555081404")


def test_get_tracking_status_mydhl_writes_cache_with_diagnostics(tmp_path, monkeypatch):
    from app.services import tracking_service as ts

    monkeypatch.setattr(ts.settings, "dhl_tracking_api_status", "active", raising=False)
    monkeypatch.setattr(ts.settings, "dhl_express_api_key", "ek", raising=False)
    monkeypatch.setattr(ts.settings, "dhl_express_api_secret", "es", raising=False)
    monkeypatch.setattr(ts.settings, "dhl_tracking_api_key", "", raising=False)
    monkeypatch.setattr(ts.settings, "dhl_api_key", "", raising=False)

    def _fake_fetch(ref, **kwargs):
        assert ref == "1555081404"
        return MYDHL_BODY, {
            "tracking_provider": "mydhl_express",
            "last_http_status": 200,
            "rate_limited": False,
            "retry_after": None,
        }

    monkeypatch.setattr(
        "app.services.carrier.adapters.live.fetch_express_tracking",
        _fake_fetch,
    )
    cache_dir = tmp_path / "batch"
    cache_dir.mkdir()
    result = ts.get_tracking_status("1555081404", "DHL", cache_dir, refresh=True)
    assert result["available"] is True
    assert result["tracking_provider"] == "mydhl_express"
    assert result["last_http_status"] == 200
    assert result["rate_limited"] is False
    assert result["status"] == "in_transit"
    assert "WARSAW" in (result.get("last_location") or "")
    assert any("Processed at WARSAW" in (e.get("description") or "") for e in result["events"])
    assert any("departed" in (e.get("description") or "").lower() for e in result["events"])
    cached = json.loads((cache_dir / "tracking_cache.json").read_text(encoding="utf-8"))
    assert cached["1555081404"]["tracking_provider"] == "mydhl_express"
    assert cached["1555081404"]["events_count"] == 3


def test_unified_404_does_not_wipe_mydhl_cache(tmp_path, monkeypatch):
    from app.services import tracking_service as ts

    monkeypatch.setattr(ts.settings, "dhl_tracking_api_status", "active", raising=False)
    monkeypatch.setattr(ts.settings, "dhl_express_api_key", "ek", raising=False)
    monkeypatch.setattr(ts.settings, "dhl_express_api_secret", "es", raising=False)
    monkeypatch.setattr(ts.settings, "dhl_tracking_api_key", "uk", raising=False)

    cache_dir = tmp_path / "batch"
    cache_dir.mkdir()
    good = {
        "tracking_no": "1555081404",
        "carrier": "DHL",
        "status": "in_transit",
        "status_label": "In Transit",
        "source": "dhl_mydhl_express",
        "tracking_provider": "mydhl_express",
        "api_status": "ok",
        "available": True,
        "events": [
            {
                "timestamp": "2026-08-10T17:59:00",
                "location": "WARSAW - PL",
                "status": "PL",
                "description": "Processed at WARSAW-POLAND",
            }
        ],
        "cached_at": "2026-08-10T10:00:00Z",
        "tracking_last_success_at": "2026-08-10T10:00:00Z",
    }
    (cache_dir / "tracking_cache.json").write_text(
        json.dumps({"1555081404": good}), encoding="utf-8"
    )

    def _fail(_awb):
        raise RuntimeError("DHL API 503: boom")

    def _unified_404(_awb):
        raise httpx.HTTPStatusError(
            "Not Found",
            request=MagicMock(),
            response=MagicMock(status_code=404, text="not found"),
        )

    monkeypatch.setattr(ts, "_call_dhl_mydhl_express", _fail)
    monkeypatch.setattr(ts, "_call_dhl_unified", _unified_404)
    # Force refresh past TTL
    result = ts.get_tracking_status("1555081404", "DHL", cache_dir, refresh=True)
    assert result.get("tracking_stale") is True or result.get("source") == "cache_stale"
    assert len(result.get("events") or []) == 1
    assert "WARSAW" in (result["events"][0].get("location") or "")


def test_fetch_express_tracking_builds_canonical_url(monkeypatch):
    from app.services.carrier.adapters import live as live_mod

    captured = {}

    class _Resp:
        status_code = 200
        headers = {}
        is_success = True

        def json(self):
            return MYDHL_BODY

    class _Client:
        def __init__(self, *a, **k):
            captured["auth"] = k.get("auth")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None):
            captured["url"] = url
            captured["params"] = params
            return _Resp()

    monkeypatch.setattr(live_mod.httpx, "Client", _Client)
    data, meta = live_mod.fetch_express_tracking(
        "1555081404",
        api_key="k",
        api_secret="s",
        api_url="https://express.api.dhl.com",
        use_sandbox=False,
    )
    assert data["shipments"][0]["shipmentTrackingNumber"] == "1555081404"
    assert captured["url"].endswith("/mydhlapi/shipments/1555081404/tracking")
    assert captured["params"]["trackingView"] == "all-checkpoints"
    assert meta["tracking_provider"] == "mydhl_express"
    assert meta["last_http_status"] == 200
