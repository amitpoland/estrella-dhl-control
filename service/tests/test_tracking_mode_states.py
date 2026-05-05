"""
test_tracking_mode_states.py — DHL tracking mode contract.

The legacy `api_status="pending"` string was replaced with three explicit
modes:
    disabled — no API key configured
    failed   — last live call errored
    active   — credentials present + status active

Plus the manual-update endpoint must:
    - persist `tracking.source = "manual"` and `tracking.updated_at`
    - flag `audit.tracking_complete = True` to advance the workflow
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services import tracking_service as ts  # noqa: E402
from app.services.tracking_service import (  # noqa: E402
    get_tracking_mode, _dhl_pending_fallback,
)
from app.core import config as cfg  # noqa: E402


# ── Mode helper ───────────────────────────────────────────────────────────────

class TestGetTrackingMode:
    def test_no_api_key_returns_disabled(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "dhl_api_key", "")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_key", "")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_secret", "")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_status", "active")
        assert get_tracking_mode() == "disabled"

    def test_status_failed_returns_failed(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "dhl_api_key", "k")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_status", "failed")
        assert get_tracking_mode() == "failed"

    def test_status_active_with_key_returns_active(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "dhl_api_key", "k")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_status", "active")
        assert get_tracking_mode() == "active"

    def test_legacy_pending_status_maps_to_disabled(self, monkeypatch):
        """The old 'pending' string must collapse to 'disabled' so the UI
        never shows the stuck pending state again."""
        monkeypatch.setattr(cfg.settings, "dhl_api_key", "k")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_status", "pending")
        assert get_tracking_mode() == "disabled"

    def test_explicit_disabled_returns_disabled(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "dhl_api_key", "k")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_status", "disabled")
        assert get_tracking_mode() == "disabled"


# ── Fallback dict shape ───────────────────────────────────────────────────────

class TestPendingFallbackShape:
    def test_disabled_mode_in_fallback(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cfg.settings, "dhl_api_key", "")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_status", "disabled")
        r = _dhl_pending_fallback("1234567890", cache_dir=tmp_path)
        assert r["api_status"] == "disabled"
        assert r["source"]     == "api_disabled"
        assert "disabled" in r["reason"].lower()

    def test_failed_mode_in_fallback(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cfg.settings, "dhl_api_key", "k")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_status", "failed")
        r = _dhl_pending_fallback("1234567890", cache_dir=tmp_path)
        assert r["api_status"] == "failed"
        assert r["source"]     == "api_failed"
        assert "retry" in r["reason"].lower() or "manual" in r["reason"].lower()

    def test_no_pending_string_anywhere(self, monkeypatch, tmp_path):
        """Stuck 'pending' literal must be gone from the fallback dict."""
        monkeypatch.setattr(cfg.settings, "dhl_api_key", "")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_status", "pending")
        r = _dhl_pending_fallback("1234567890", cache_dir=tmp_path)
        # The legacy "pending" string must not surface as api_status or source
        assert r["api_status"] != "pending"
        assert r["source"]    != "api_pending"


# ── Manual update endpoint advances workflow ──────────────────────────────────

class TestManualUpdateAdvancesWorkflow:
    def _setup(self, tmp_path, monkeypatch):
        out = tmp_path / "outputs"; out.mkdir()
        monkeypatch.setattr(cfg.settings, "storage_root", tmp_path)
        # routes_tracking imports _OUTPUTS at module load — patch directly
        from app.api import routes_tracking as rt
        monkeypatch.setattr(rt, "_OUTPUTS", out)
        return rt, out

    def test_manual_update_sets_source_and_updated_at(self, tmp_path, monkeypatch):
        rt, out = self._setup(tmp_path, monkeypatch)
        bdir = out / "SHIPMENT_TEST"; bdir.mkdir()
        (bdir / "audit.json").write_text(json.dumps({
            "batch_id": "SHIPMENT_TEST", "tracking_no": "X",
        }))
        body = rt.TrackingUpdateBody(
            status="delivered", last_event="Delivered",
            location="Warsaw", source="manual",
        )
        rt.update_tracking_for_batch("SHIPMENT_TEST", body)
        a = json.loads((bdir / "audit.json").read_text())
        assert a["tracking"]["source"]     == "manual"
        assert a["tracking"]["api_status"] == "manual"
        assert "updated_at" in a["tracking"] and a["tracking"]["updated_at"]
        assert a["tracking"]["available"]  is True

    def test_manual_update_advances_workflow(self, tmp_path, monkeypatch):
        rt, out = self._setup(tmp_path, monkeypatch)
        bdir = out / "SHIPMENT_T2"; bdir.mkdir()
        (bdir / "audit.json").write_text(json.dumps({"batch_id": "SHIPMENT_T2"}))
        body = rt.TrackingUpdateBody(
            status="in_transit", last_event="In transit", source="manual",
        )
        rt.update_tracking_for_batch("SHIPMENT_T2", body)
        a = json.loads((bdir / "audit.json").read_text())
        assert a["tracking_complete"]        is True
        assert a["tracking_complete_source"] == "manual"
        assert a["tracking_complete_at"]            # non-empty timestamp

    def test_manual_update_clears_cowork_required(self, tmp_path, monkeypatch):
        """After a manual update, the public-tracking-lookup task should
        no longer be required — cowork_tracking_required must be False."""
        rt, out = self._setup(tmp_path, monkeypatch)
        bdir = out / "SHIPMENT_T3"; bdir.mkdir()
        (bdir / "audit.json").write_text(json.dumps({
            "batch_id": "SHIPMENT_T3",
            "tracking": {"cowork_tracking_required": True},
        }))
        body = rt.TrackingUpdateBody(
            status="customs", last_event="In customs", source="operator",
        )
        rt.update_tracking_for_batch("SHIPMENT_T3", body)
        a = json.loads((bdir / "audit.json").read_text())
        assert a["tracking"]["cowork_tracking_required"] is False
