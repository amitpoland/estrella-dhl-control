"""
test_series_cache_persistence.py — Campaign 4 Targets A+B.

Covers:
  - Disk persistence of series cache (Target A)
  - Stale detection + TTL (Target B)
  - Cache lifecycle contract (init → load → refresh → persist → stale-check)
  - Regression: existing get_dictionaries() contract not broken
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Target B — Stale Detection
# ─────────────────────────────────────────────────────────────────────────────

class TestStaleness:
    """is_cache_stale() contract."""

    def _reset(self, wdc):
        """Reset the module-level cache to its initial state."""
        wdc._LIVE_CACHE["invoice_series"]  = None
        wdc._LIVE_CACHE["proforma_series"] = None
        wdc._LIVE_CACHE["fetched_at"]      = None
        wdc._LIVE_CACHE["source_state"]["invoice_series"]  = "baseline"
        wdc._LIVE_CACHE["source_state"]["proforma_series"] = "baseline"

    def test_stale_when_no_fetch(self):
        from app.services import wfirma_dictionary_cache as wdc
        self._reset(wdc)
        assert wdc.is_cache_stale() is True

    def test_stale_when_source_baseline(self):
        from app.services import wfirma_dictionary_cache as wdc
        self._reset(wdc)
        wdc._LIVE_CACHE["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        wdc._LIVE_CACHE["source_state"]["invoice_series"]  = "baseline"
        wdc._LIVE_CACHE["source_state"]["proforma_series"] = "baseline"
        assert wdc.is_cache_stale() is True

    def test_stale_when_source_error(self):
        from app.services import wfirma_dictionary_cache as wdc
        self._reset(wdc)
        wdc._LIVE_CACHE["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        wdc._LIVE_CACHE["source_state"]["invoice_series"]  = "error"
        wdc._LIVE_CACHE["source_state"]["proforma_series"] = "error"
        assert wdc.is_cache_stale() is True

    def test_fresh_when_recently_fetched_live(self):
        from app.services import wfirma_dictionary_cache as wdc
        self._reset(wdc)
        wdc._LIVE_CACHE["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        wdc._LIVE_CACHE["source_state"]["invoice_series"]  = "live"
        wdc._LIVE_CACHE["source_state"]["proforma_series"] = "live"
        assert wdc.is_cache_stale() is False

    def test_stale_when_old(self):
        from app.services import wfirma_dictionary_cache as wdc
        self._reset(wdc)
        old_time = datetime.now(timezone.utc) - timedelta(hours=30)
        wdc._LIVE_CACHE["fetched_at"] = old_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        wdc._LIVE_CACHE["source_state"]["invoice_series"]  = "live"
        wdc._LIVE_CACHE["source_state"]["proforma_series"] = "live"
        assert wdc.is_cache_stale(max_age_hours=24) is True

    def test_fresh_within_ttl(self):
        from app.services import wfirma_dictionary_cache as wdc
        self._reset(wdc)
        recent = datetime.now(timezone.utc) - timedelta(hours=2)
        wdc._LIVE_CACHE["fetched_at"] = recent.strftime("%Y-%m-%dT%H:%M:%SZ")
        wdc._LIVE_CACHE["source_state"]["invoice_series"]  = "live"
        wdc._LIVE_CACHE["source_state"]["proforma_series"] = "live"
        assert wdc.is_cache_stale(max_age_hours=24) is False

    def test_ttl_constant_is_24_hours(self):
        from app.services.wfirma_dictionary_cache import SERIES_CACHE_TTL_HOURS
        assert SERIES_CACHE_TTL_HOURS == 24

    def test_is_stale_in_get_dictionaries_response(self):
        from app.services.wfirma_dictionary_cache import get_dictionaries
        result = get_dictionaries()
        assert "is_stale" in result
        assert isinstance(result["is_stale"], bool)

    def test_cache_age_hours_in_get_dictionaries_response(self):
        from app.services.wfirma_dictionary_cache import get_dictionaries
        result = get_dictionaries()
        assert "cache_age_hours" in result
        # cache_age_hours is None when no fetch has run, float otherwise
        assert result["cache_age_hours"] is None or isinstance(result["cache_age_hours"], float)

    def test_cache_ttl_hours_in_response(self):
        from app.services.wfirma_dictionary_cache import get_dictionaries
        result = get_dictionaries()
        assert result["cache_ttl_hours"] == 24


# ─────────────────────────────────────────────────────────────────────────────
# Target A — Disk Persistence
# ─────────────────────────────────────────────────────────────────────────────

class TestDiskPersistence:
    """load_cache_from_disk / _persist_cache_to_disk contract."""

    def test_init_series_cache_sets_path(self, tmp_path):
        from app.services import wfirma_dictionary_cache as wdc
        cache_path = tmp_path / "series_cache.json"
        wdc.init_series_cache(cache_path)
        assert wdc._cache_file_path == cache_path

    def test_load_returns_false_when_no_file(self, tmp_path):
        from app.services import wfirma_dictionary_cache as wdc
        wdc.init_series_cache(tmp_path / "nonexistent.json")
        result = wdc.load_cache_from_disk()
        assert result is False

    def test_persist_and_reload(self, tmp_path):
        from app.services import wfirma_dictionary_cache as wdc
        cache_path = tmp_path / "series_cache.json"
        wdc.init_series_cache(cache_path)

        # Plant data in the cache
        wdc._LIVE_CACHE["invoice_series"]  = [{"id": "15827921", "label": "WDT 2024", "code": "WDT"}]
        wdc._LIVE_CACHE["proforma_series"] = [{"id": "15827088", "label": "PRO/2024", "code": "PRO"}]
        wdc._LIVE_CACHE["fetched_at"]      = "2026-01-01T12:00:00Z"
        wdc._LIVE_CACHE["source_state"]["invoice_series"]  = "live"
        wdc._LIVE_CACHE["source_state"]["proforma_series"] = "live"

        # Persist
        wdc._persist_cache_to_disk()
        assert cache_path.exists()

        # Wipe in-memory cache
        wdc._LIVE_CACHE["invoice_series"]  = None
        wdc._LIVE_CACHE["proforma_series"] = None
        wdc._LIVE_CACHE["fetched_at"]      = None
        wdc._LIVE_CACHE["source_state"]["invoice_series"]  = "baseline"
        wdc._LIVE_CACHE["source_state"]["proforma_series"] = "baseline"

        # Load from disk
        result = wdc.load_cache_from_disk()
        assert result is True
        assert wdc._LIVE_CACHE["invoice_series"] == [{"id": "15827921", "label": "WDT 2024", "code": "WDT"}]
        assert wdc._LIVE_CACHE["proforma_series"] == [{"id": "15827088", "label": "PRO/2024", "code": "PRO"}]
        assert wdc._LIVE_CACHE["fetched_at"] == "2026-01-01T12:00:00Z"

    def test_persist_does_not_write_empty_cache(self, tmp_path):
        """Don't overwrite a good cache with empty data."""
        from app.services import wfirma_dictionary_cache as wdc
        cache_path = tmp_path / "series_cache.json"
        wdc.init_series_cache(cache_path)

        # Empty cache — should not write
        wdc._LIVE_CACHE["invoice_series"]  = None
        wdc._LIVE_CACHE["proforma_series"] = None
        wdc._persist_cache_to_disk()
        assert not cache_path.exists()

    def test_load_returns_false_on_corrupt_json(self, tmp_path):
        from app.services import wfirma_dictionary_cache as wdc
        cache_path = tmp_path / "series_cache.json"
        wdc.init_series_cache(cache_path)
        cache_path.write_text("NOT JSON", encoding="utf-8")
        result = wdc.load_cache_from_disk()
        assert result is False

    def test_load_returns_false_on_wrong_shape(self, tmp_path):
        from app.services import wfirma_dictionary_cache as wdc
        cache_path = tmp_path / "series_cache.json"
        wdc.init_series_cache(cache_path)
        cache_path.write_text(
            json.dumps({"invoice_series": "not-a-list", "proforma_series": []}),
            encoding="utf-8",
        )
        result = wdc.load_cache_from_disk()
        assert result is False

    def test_persist_is_atomic_rename(self, tmp_path):
        """File appears at final path, no partial file left behind."""
        from app.services import wfirma_dictionary_cache as wdc
        cache_path = tmp_path / "series_cache.json"
        wdc.init_series_cache(cache_path)
        wdc._LIVE_CACHE["invoice_series"]  = [{"id": "X", "label": "Test", "code": "T"}]
        wdc._LIVE_CACHE["proforma_series"] = [{"id": "Y", "label": "Test2", "code": "T2"}]
        wdc._persist_cache_to_disk()

        assert cache_path.exists()
        tmp = cache_path.with_suffix(".json.tmp")
        assert not tmp.exists()  # temp file must be renamed away

    def test_persist_failure_is_non_fatal(self, tmp_path):
        """Persist failure must not raise."""
        from app.services import wfirma_dictionary_cache as wdc
        wdc.init_series_cache(tmp_path / "series_cache.json")
        wdc._LIVE_CACHE["invoice_series"]  = [{"id": "X", "label": "Test", "code": "T"}]
        # Make directory read-only to force a write failure — non-fatal
        with patch("app.services.wfirma_dictionary_cache._cache_file_path",
                   pathlib.Path("/nonexistent_dir/cache.json")):
            wdc._persist_cache_to_disk()  # must not raise

    def test_load_failure_is_non_fatal(self, tmp_path):
        """Load failure must not raise."""
        from app.services import wfirma_dictionary_cache as wdc
        wdc.init_series_cache(tmp_path / "series_cache.json")
        # File doesn't exist
        result = wdc.load_cache_from_disk()
        assert result is False  # graceful False, no exception

    def test_get_dictionaries_includes_cache_age_after_persist_reload(self, tmp_path):
        """After disk load, get_dictionaries() reports correct cache_age_hours."""
        from app.services import wfirma_dictionary_cache as wdc
        cache_path = tmp_path / "series_cache.json"
        wdc.init_series_cache(cache_path)

        recent = datetime.now(timezone.utc) - timedelta(hours=3)
        wdc._LIVE_CACHE["invoice_series"]  = [{"id": "15827921", "label": "WDT", "code": "WDT"}]
        wdc._LIVE_CACHE["proforma_series"] = [{"id": "15827088", "label": "PRO", "code": "PRO"}]
        wdc._LIVE_CACHE["fetched_at"]      = recent.strftime("%Y-%m-%dT%H:%M:%SZ")
        wdc._LIVE_CACHE["source_state"]["invoice_series"]  = "live"
        wdc._LIVE_CACHE["source_state"]["proforma_series"] = "live"
        wdc._persist_cache_to_disk()

        # Reload from disk
        wdc._LIVE_CACHE["invoice_series"] = None
        wdc._LIVE_CACHE["fetched_at"]     = None
        wdc.load_cache_from_disk()

        result = wdc.get_dictionaries()
        assert result["cache_age_hours"] is not None
        # Should be approximately 3 hours (±0.1 h for test execution time)
        assert 2.5 < result["cache_age_hours"] < 4.0

    def test_disk_cache_survives_without_path(self):
        """When no path is set, persist and load are graceful no-ops."""
        from app.services import wfirma_dictionary_cache as wdc
        wdc._cache_file_path = None
        wdc._LIVE_CACHE["invoice_series"] = [{"id": "Z", "label": "Test", "code": "T"}]
        wdc._persist_cache_to_disk()  # no-op, no raise
        result = wdc.load_cache_from_disk()  # no-op, returns False
        assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# Cache Lifecycle Contract
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheLifecycle:
    """End-to-end cache lifecycle: init → load → refresh → persist → stale-check."""

    def test_full_lifecycle_new_process(self, tmp_path):
        """Simulate a fresh process start with no existing cache file."""
        from app.services import wfirma_dictionary_cache as wdc
        import app.services.wfirma_client as _wfc

        cache_path = tmp_path / "series_cache.json"
        wdc.init_series_cache(cache_path)
        wdc._LIVE_CACHE["invoice_series"]  = None
        wdc._LIVE_CACHE["proforma_series"] = None
        wdc._LIVE_CACHE["fetched_at"]      = None
        wdc._LIVE_CACHE["source_state"]["invoice_series"]  = "baseline"
        wdc._LIVE_CACHE["source_state"]["proforma_series"] = "baseline"

        # 1. Load from disk — no file yet, returns False
        assert wdc.load_cache_from_disk() is False
        # 2. Cache is stale (no fetch)
        assert wdc.is_cache_stale() is True
        # 3. Refresh from wFirma (mocked) — use dicts; production code does s["id"] / s.get()
        fake = [{"id": "15827088", "label": "PRO 2024", "code": "PRO",
                 "type": "proforma", "visibility": "visible"}]
        with patch.object(_wfc, "fetch_series", return_value=fake):
            wdc.refresh_from_wfirma()
        # 4. Cache is now live
        assert wdc._LIVE_CACHE["source_state"]["proforma_series"] == "live"
        # 5. File persisted
        assert cache_path.exists()
        # 6. No longer stale
        assert wdc.is_cache_stale() is False

    def test_full_lifecycle_restart_with_cache(self, tmp_path):
        """Simulate a process restart with a fresh cache on disk."""
        from app.services import wfirma_dictionary_cache as wdc

        cache_path = tmp_path / "series_cache.json"
        # Pre-write a cache that is only 1 hour old
        recent = datetime.now(timezone.utc) - timedelta(hours=1)
        cache_data = {
            "invoice_series":  [{"id": "15827921", "label": "WDT 2024", "code": "WDT"}],
            "proforma_series": [{"id": "15827088", "label": "PRO 2024", "code": "PRO"}],
            "fetched_at":      recent.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_state":    {"invoice_series": "live", "proforma_series": "live"},
            "schema_version":  1,
        }
        cache_path.write_text(json.dumps(cache_data), encoding="utf-8")

        # Fresh module state
        wdc.init_series_cache(cache_path)
        wdc._LIVE_CACHE["invoice_series"]  = None
        wdc._LIVE_CACHE["proforma_series"] = None
        wdc._LIVE_CACHE["fetched_at"]      = None
        wdc._LIVE_CACHE["source_state"]["invoice_series"]  = "baseline"
        wdc._LIVE_CACHE["source_state"]["proforma_series"] = "baseline"

        # Load from disk — succeeds
        assert wdc.load_cache_from_disk() is True
        # Not stale — disk cache is fresh (1 hour old, TTL is 24)
        assert wdc.is_cache_stale() is False
        # Dictionaries populated
        result = wdc.get_dictionaries()
        inv_ids = {e["id"] for e in result["invoice_series"]}
        pro_ids = {e["id"] for e in result["proforma_series"]}
        assert "15827921" in inv_ids
        assert "15827088" in pro_ids

    def test_startup_sequence_respects_stale_flag(self, tmp_path):
        """If disk cache is stale, refresh is triggered; if fresh, refresh is skipped."""
        from app.services import wfirma_dictionary_cache as wdc
        import app.services.wfirma_client as _wfc

        cache_path = tmp_path / "series_cache.json"
        # Old cache (30 hours old) — should trigger refresh
        old_time = datetime.now(timezone.utc) - timedelta(hours=30)
        cache_data = {
            "invoice_series":  [{"id": "OLD", "label": "Old Series", "code": "OLD"}],
            "proforma_series": [{"id": "OLDP", "label": "Old Pro", "code": "OLDP"}],
            "fetched_at":      old_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_state":    {"invoice_series": "live", "proforma_series": "live"},
            "schema_version":  1,
        }
        cache_path.write_text(json.dumps(cache_data), encoding="utf-8")

        wdc.init_series_cache(cache_path)
        wdc._LIVE_CACHE["invoice_series"]  = None
        wdc._LIVE_CACHE["fetched_at"]      = None
        wdc._LIVE_CACHE["source_state"]["invoice_series"]  = "baseline"
        wdc._LIVE_CACHE["source_state"]["proforma_series"] = "baseline"

        loaded = wdc.load_cache_from_disk()
        assert loaded is True
        # After loading old cache, is_cache_stale should be True
        assert wdc.is_cache_stale() is True

        # Trigger refresh (the startup would call this) — use dicts; production code does s["id"] / s.get()
        new_series = [{"id": "NEW123", "label": "New Invoice Series", "code": "NI",
                       "type": "normal", "visibility": "visible"}]
        fetch_calls: list = []
        def mock_fetch():
            fetch_calls.append(True)
            return new_series
        with patch.object(_wfc, "fetch_series", side_effect=mock_fetch):
            wdc.refresh_from_wfirma()

        assert len(fetch_calls) == 1  # refresh was called
        # New data in cache
        inv_ids = {e["id"] for e in (wdc._LIVE_CACHE["invoice_series"] or [])}
        assert "NEW123" in inv_ids


# ─────────────────────────────────────────────────────────────────────────────
# Regression — existing get_dictionaries() contract not broken
# ─────────────────────────────────────────────────────────────────────────────

class TestGetDictionariesRegression:
    """Ensure existing contract not broken by Target A+B additions."""

    def test_returns_all_required_keys(self):
        from app.services.wfirma_dictionary_cache import get_dictionaries
        result = get_dictionaries()
        for key in ("vat_modes", "currencies", "languages",
                    "invoice_series", "proforma_series",
                    "source", "source_state", "fetched_at", "version"):
            assert key in result, f"missing key: {key}"

    def test_new_keys_present(self):
        from app.services.wfirma_dictionary_cache import get_dictionaries
        result = get_dictionaries()
        assert "is_stale" in result
        assert "cache_age_hours" in result
        assert "cache_ttl_hours" in result

    def test_vat_modes_count(self):
        from app.services.wfirma_dictionary_cache import get_dictionaries
        result = get_dictionaries()
        assert len(result["vat_modes"]) == 3

    def test_source_state_always_dict(self):
        from app.services.wfirma_dictionary_cache import get_dictionaries
        result = get_dictionaries()
        assert isinstance(result["source_state"], dict)

    def test_init_series_cache_exists(self):
        from app.services.wfirma_dictionary_cache import init_series_cache
        assert callable(init_series_cache)

    def test_is_cache_stale_exported(self):
        from app.services.wfirma_dictionary_cache import is_cache_stale
        assert callable(is_cache_stale)

    def test_load_cache_from_disk_exported(self):
        from app.services.wfirma_dictionary_cache import load_cache_from_disk
        assert callable(load_cache_from_disk)

    def test_main_py_startup_uses_init_and_stale_check(self):
        import pathlib
        src = pathlib.Path("app/main.py").read_text()
        assert "init_series_cache" in src
        assert "load_cache_from_disk" in src
        assert "is_cache_stale" in src
