"""
test_series_refresh_scheduled_status.py — scheduled series refresh + four-questions status.

Covers the systemic-issue repair for the in-process-only dictionary cache:
  - refresh_from_wfirma() records four-questions run status (any trigger)
  - get_refresh_status() canonical shape (docs/patterns/status-endpoint.md)
  - last-known-good preservation: a failed refresh never wipes a live catalog
  - should_attempt_scheduled_refresh() staleness + cooldown gate
  - wfirma_webhook_scheduler._run_series_refresh_tick() wiring:
    flag-gated, cooldown-gated, failure-isolated
  - route + startup wiring (source-grep pins)
"""
from __future__ import annotations

import pathlib
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

# Anchor source-grep pins to this file, not the CWD, so the suite passes
# regardless of where pytest is invoked from.
_SVC_ROOT = pathlib.Path(__file__).resolve().parents[1]   # …/service/


def _reset(wdc, tmp_path=None):
    """Reset module-level cache + refresh status to a pristine state."""
    wdc._cache_file_path = (tmp_path / "series_cache.json") if tmp_path else None
    wdc._LIVE_CACHE["invoice_series"]  = None
    wdc._LIVE_CACHE["proforma_series"] = None
    wdc._LIVE_CACHE["fetched_at"]      = None
    wdc._LIVE_CACHE["source_state"]["invoice_series"]  = "baseline"
    wdc._LIVE_CACHE["source_state"]["proforma_series"] = "baseline"
    wdc._REFRESH_STATUS.update({
        "last_started_at":   None,
        "last_completed_at": None,
        "last_trigger":      None,
        "duration_ms":       None,
        "processed":         0,
        "created":           0,
        "updated":           0,
        "skipped":           0,
        "errors":            0,
        "last_error":        None,
    })


_FIXTURE_SERIES = [
    {"id": "15827082", "label": "FV 2024",   "code": "FV",  "type": "normal",   "visibility": "visible"},
    {"id": "15827085", "label": "MAR 2024",  "code": "MAR", "type": "margin",   "visibility": "visible"},
    {"id": "15827088", "label": "PRO 2024",  "code": "PRO", "type": "proforma", "visibility": "visible"},
    {"id": "15827091", "label": "OFF 2024",  "code": "OFF", "type": "offer",    "visibility": "visible"},
    {"id": "HIDDEN-1", "label": "Hidden",    "code": "H",   "type": "normal",   "visibility": "hidden"},
]


# ─────────────────────────────────────────────────────────────────────────────
# Canonical status shape
# ─────────────────────────────────────────────────────────────────────────────

class TestRefreshStatusShape:
    """get_refresh_status() — canonical four-questions contract."""

    CANONICAL_KEYS = (
        "healthy", "running", "last_started_at", "last_completed_at",
        "duration_ms", "processed", "created", "updated", "skipped",
        "errors", "last_error",
    )

    def test_canonical_keys_present(self):
        from app.services import wfirma_dictionary_cache as wdc
        _reset(wdc)
        status = wdc.get_refresh_status()
        for key in self.CANONICAL_KEYS:
            assert key in status, f"missing canonical key: {key}"

    def test_capability_extras_present(self):
        from app.services import wfirma_dictionary_cache as wdc
        _reset(wdc)
        status = wdc.get_refresh_status()
        for key in ("fetched_at", "source_state", "is_stale",
                    "cache_ttl_hours", "retry_cooldown_minutes", "last_trigger"):
            assert key in status, f"missing capability key: {key}"

    def test_pristine_state_types(self):
        from app.services import wfirma_dictionary_cache as wdc
        _reset(wdc)
        status = wdc.get_refresh_status()
        assert status["healthy"] is False        # baseline cache = stale
        assert status["running"] is False
        assert status["last_started_at"] is None
        assert status["last_completed_at"] is None
        assert status["last_error"] is None
        assert status["errors"] == 0
        assert status["is_stale"] is True

    def test_never_raises(self):
        from app.services import wfirma_dictionary_cache as wdc
        _reset(wdc)
        assert isinstance(wdc.get_refresh_status(), dict)

    def test_running_derived_from_timestamps(self):
        """running = last_started_at > last_completed_at (canonical derivation)."""
        from app.services import wfirma_dictionary_cache as wdc
        _reset(wdc)
        wdc._REFRESH_STATUS["last_started_at"]   = "2026-07-16T10:00:05Z"
        wdc._REFRESH_STATUS["last_completed_at"] = "2026-07-16T10:00:01Z"
        assert wdc.get_refresh_status()["running"] is True
        wdc._REFRESH_STATUS["last_completed_at"] = "2026-07-16T10:00:06Z"
        assert wdc.get_refresh_status()["running"] is False

    def test_running_true_when_started_but_never_completed(self):
        from app.services import wfirma_dictionary_cache as wdc
        _reset(wdc)
        wdc._REFRESH_STATUS["last_started_at"] = "2026-07-16T10:00:05Z"
        assert wdc.get_refresh_status()["running"] is True


# ─────────────────────────────────────────────────────────────────────────────
# refresh_from_wfirma() records the run
# ─────────────────────────────────────────────────────────────────────────────

class TestRefreshRecordsStatus:

    def test_successful_run_records_counts(self, tmp_path):
        from app.services import wfirma_dictionary_cache as wdc
        import app.services.wfirma_client as _wfc
        _reset(wdc, tmp_path)
        with patch.object(_wfc, "fetch_series", return_value=list(_FIXTURE_SERIES)):
            wdc.refresh_from_wfirma()
        status = wdc.get_refresh_status()
        assert status["processed"] == 5           # all rows returned by wFirma
        assert status["updated"]   == 3           # FV + MAR (invoice) + PRO (proforma)
        assert status["skipped"]   == 2           # hidden + offer
        assert status["created"]   == 0
        assert status["errors"]    == 0
        assert status["last_error"] is None
        assert status["healthy"] is True
        assert status["running"] is False
        assert isinstance(status["duration_ms"], int)
        assert status["duration_ms"] >= 0
        assert status["last_started_at"] is not None
        assert status["last_completed_at"] is not None

    def test_default_trigger_is_api(self, tmp_path):
        from app.services import wfirma_dictionary_cache as wdc
        import app.services.wfirma_client as _wfc
        _reset(wdc, tmp_path)
        with patch.object(_wfc, "fetch_series", return_value=list(_FIXTURE_SERIES)):
            wdc.refresh_from_wfirma()
        assert wdc.get_refresh_status()["last_trigger"] == "api"

    @pytest.mark.parametrize("trigger", ["startup", "scheduler", "api"])
    def test_trigger_recorded(self, tmp_path, trigger):
        from app.services import wfirma_dictionary_cache as wdc
        import app.services.wfirma_client as _wfc
        _reset(wdc, tmp_path)
        with patch.object(_wfc, "fetch_series", return_value=list(_FIXTURE_SERIES)):
            wdc.refresh_from_wfirma(trigger=trigger)
        assert wdc.get_refresh_status()["last_trigger"] == trigger

    def test_exception_recorded_not_raised(self, tmp_path):
        from app.services import wfirma_dictionary_cache as wdc
        import app.services.wfirma_client as _wfc
        _reset(wdc, tmp_path)
        with patch.object(_wfc, "fetch_series",
                          side_effect=RuntimeError("connection refused")):
            result = wdc.refresh_from_wfirma(trigger="scheduler")   # must not raise
        assert isinstance(result, dict)
        status = wdc.get_refresh_status()
        assert status["errors"] == 1
        assert "connection refused" in status["last_error"]
        assert status["healthy"] is False
        assert status["updated"] == 0

    def test_empty_result_recorded_as_error(self, tmp_path):
        from app.services import wfirma_dictionary_cache as wdc
        import app.services.wfirma_client as _wfc
        _reset(wdc, tmp_path)
        with patch.object(_wfc, "fetch_series", return_value=[]):
            wdc.refresh_from_wfirma()
        status = wdc.get_refresh_status()
        assert status["errors"] == 1
        assert status["last_error"] is not None
        assert status["source_state"]["invoice_series"] == "error"

    def test_success_clears_previous_error(self, tmp_path):
        from app.services import wfirma_dictionary_cache as wdc
        import app.services.wfirma_client as _wfc
        _reset(wdc, tmp_path)
        with patch.object(_wfc, "fetch_series", side_effect=RuntimeError("boom")):
            wdc.refresh_from_wfirma()
        assert wdc.get_refresh_status()["last_error"] is not None
        with patch.object(_wfc, "fetch_series", return_value=list(_FIXTURE_SERIES)):
            wdc.refresh_from_wfirma()
        status = wdc.get_refresh_status()
        assert status["last_error"] is None
        assert status["errors"] == 0
        assert status["healthy"] is True

    def test_errors_field_is_per_run_not_cumulative(self, tmp_path):
        """errors reflects the LAST run (0 or 1) — never accumulates."""
        from app.services import wfirma_dictionary_cache as wdc
        import app.services.wfirma_client as _wfc
        _reset(wdc, tmp_path)
        with patch.object(_wfc, "fetch_series", side_effect=RuntimeError("fail1")):
            wdc.refresh_from_wfirma()
        with patch.object(_wfc, "fetch_series", side_effect=RuntimeError("fail2")):
            wdc.refresh_from_wfirma()
        status = wdc.get_refresh_status()
        assert status["errors"] == 1
        assert "fail2" in status["last_error"]

    def test_refresh_idempotent_on_same_data(self, tmp_path):
        """Two refreshes with identical wFirma data: identical counts, no
        catalog growth (the cache is replaced, never appended to)."""
        from app.services import wfirma_dictionary_cache as wdc
        import app.services.wfirma_client as _wfc
        _reset(wdc, tmp_path)
        with patch.object(_wfc, "fetch_series", return_value=list(_FIXTURE_SERIES)):
            first  = wdc.refresh_from_wfirma()
            status1 = wdc.get_refresh_status()
            second = wdc.refresh_from_wfirma()
            status2 = wdc.get_refresh_status()
        assert status2["processed"] == status1["processed"]
        assert status2["updated"]   == status1["updated"]
        assert status2["skipped"]   == status1["skipped"]
        assert len(second["invoice_series"])  == len(first["invoice_series"])
        assert len(second["proforma_series"]) == len(first["proforma_series"])


# ─────────────────────────────────────────────────────────────────────────────
# Last-known-good preservation on failed refresh
# ─────────────────────────────────────────────────────────────────────────────

class TestLastKnownGoodPreserved:

    def _seed_live(self, wdc, hours_old: float = 1.0):
        old = datetime.now(timezone.utc) - timedelta(hours=hours_old)
        wdc._LIVE_CACHE["invoice_series"]  = [{"id": "KEEP-1", "label": "Keep FV",  "code": "FV"}]
        wdc._LIVE_CACHE["proforma_series"] = [{"id": "KEEP-2", "label": "Keep PRO", "code": "PRO"}]
        wdc._LIVE_CACHE["fetched_at"]      = old.strftime("%Y-%m-%dT%H:%M:%SZ")
        wdc._LIVE_CACHE["source_state"]["invoice_series"]  = "live"
        wdc._LIVE_CACHE["source_state"]["proforma_series"] = "live"

    def test_failed_refresh_keeps_live_entries(self, tmp_path):
        """A wFirma outage during a scheduled refresh must NOT wipe a good
        catalog — the convert modal's series names and the proforma-type-
        series hard block keep working from last-known-good data."""
        from app.services import wfirma_dictionary_cache as wdc
        import app.services.wfirma_client as _wfc
        _reset(wdc, tmp_path)
        self._seed_live(wdc)
        with patch.object(_wfc, "fetch_series", side_effect=RuntimeError("outage")):
            merged = wdc.refresh_from_wfirma(trigger="scheduler")
        inv_ids = {e["id"] for e in merged["invoice_series"]}
        pro_ids = {e["id"] for e in merged["proforma_series"]}
        assert "KEEP-1" in inv_ids
        assert "KEEP-2" in pro_ids
        # ...but the error is not hidden:
        assert merged["source_state"]["invoice_series"] == "error"
        assert wdc.get_refresh_status()["last_error"] is not None

    def test_failed_refresh_does_not_bump_fetched_at(self, tmp_path):
        """fetched_at must keep the age of the data actually served."""
        from app.services import wfirma_dictionary_cache as wdc
        import app.services.wfirma_client as _wfc
        _reset(wdc, tmp_path)
        self._seed_live(wdc, hours_old=5.0)
        before = wdc._LIVE_CACHE["fetched_at"]
        with patch.object(_wfc, "fetch_series", return_value=[]):
            wdc.refresh_from_wfirma()
        assert wdc._LIVE_CACHE["fetched_at"] == before

    def test_failed_refresh_with_no_prior_data_serves_baseline(self, tmp_path):
        """Pre-existing contract: with no prior live data, error state +
        baseline placeholder (UI never sees an empty dropdown)."""
        from app.services import wfirma_dictionary_cache as wdc
        import app.services.wfirma_client as _wfc
        _reset(wdc, tmp_path)
        with patch.object(_wfc, "fetch_series", return_value=[]):
            merged = wdc.refresh_from_wfirma()
        assert merged["source_state"]["invoice_series"] == "error"
        assert len(merged["invoice_series"])  >= 1
        assert len(merged["proforma_series"]) >= 1

    def test_failed_refresh_does_not_persist_to_disk(self, tmp_path):
        """Only live fetches persist — the disk snapshot stays last-good."""
        from app.services import wfirma_dictionary_cache as wdc
        import app.services.wfirma_client as _wfc
        _reset(wdc, tmp_path)
        with patch.object(_wfc, "fetch_series", side_effect=RuntimeError("boom")):
            wdc.refresh_from_wfirma()
        assert not (tmp_path / "series_cache.json").exists()

    def test_unavailable_path_does_not_preserve_prior_entries(self, tmp_path):
        """Semantic pin: 'unavailable' is an AUTHORITATIVE answer — wFirma
        returned a catalog containing no invoice/proforma-type series — so
        prior live entries are correctly replaced, not preserved. Only the
        'error' outcome (fetch failed / no rows) keeps last-known-good.
        If a future change extends preservation to the unavailable path,
        that is a semantics change and this pin must be consciously updated."""
        from app.services import wfirma_dictionary_cache as wdc
        import app.services.wfirma_client as _wfc
        _reset(wdc, tmp_path)
        self._seed_live(wdc)
        offer_only = [{"id": "O1", "label": "Oferta", "code": "OFF",
                       "type": "offer", "visibility": "visible"}]
        with patch.object(_wfc, "fetch_series", return_value=offer_only):
            merged = wdc.refresh_from_wfirma(trigger="scheduler")
        assert merged["source_state"]["invoice_series"] == "unavailable"
        inv_ids = {e["id"] for e in merged["invoice_series"]}
        assert "KEEP-1" not in inv_ids


# ─────────────────────────────────────────────────────────────────────────────
# Scheduled-refresh gate (staleness + cooldown)
# ─────────────────────────────────────────────────────────────────────────────

class TestScheduledRefreshGate:

    def test_cooldown_constant(self):
        from app.services.wfirma_dictionary_cache import (
            SERIES_REFRESH_RETRY_COOLDOWN_MINUTES,
        )
        assert SERIES_REFRESH_RETRY_COOLDOWN_MINUTES == 30

    def test_fresh_cache_no_attempt(self):
        from app.services import wfirma_dictionary_cache as wdc
        _reset(wdc)
        wdc._LIVE_CACHE["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        wdc._LIVE_CACHE["source_state"]["invoice_series"]  = "live"
        wdc._LIVE_CACHE["source_state"]["proforma_series"] = "live"
        assert wdc.should_attempt_scheduled_refresh() is False

    def test_stale_never_attempted_fires(self):
        from app.services import wfirma_dictionary_cache as wdc
        _reset(wdc)
        assert wdc.should_attempt_scheduled_refresh() is True

    def test_stale_recent_attempt_cooldown_blocks(self):
        from app.services import wfirma_dictionary_cache as wdc
        _reset(wdc)
        recent = datetime.now(timezone.utc) - timedelta(minutes=5)
        wdc._REFRESH_STATUS["last_started_at"] = recent.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert wdc.should_attempt_scheduled_refresh() is False

    def test_stale_old_attempt_fires(self):
        from app.services import wfirma_dictionary_cache as wdc
        _reset(wdc)
        old = datetime.now(timezone.utc) - timedelta(minutes=45)
        wdc._REFRESH_STATUS["last_started_at"] = old.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert wdc.should_attempt_scheduled_refresh() is True

    def test_malformed_attempt_timestamp_fails_open_to_attempt(self):
        from app.services import wfirma_dictionary_cache as wdc
        _reset(wdc)
        wdc._REFRESH_STATUS["last_started_at"] = "not-a-timestamp"
        assert wdc.should_attempt_scheduled_refresh() is True

    def test_attempt_at_exact_cooldown_fires(self):
        """Boundary: age >= cooldown fires (30 min ago → attempt)."""
        from app.services import wfirma_dictionary_cache as wdc
        _reset(wdc)
        exact = datetime.now(timezone.utc) - timedelta(minutes=30)
        wdc._REFRESH_STATUS["last_started_at"] = exact.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert wdc.should_attempt_scheduled_refresh() is True

    def test_attempt_just_inside_cooldown_blocks(self):
        """Boundary: 29 minutes ago is still inside the 30-min cooldown."""
        from app.services import wfirma_dictionary_cache as wdc
        _reset(wdc)
        almost = datetime.now(timezone.utc) - timedelta(minutes=29)
        wdc._REFRESH_STATUS["last_started_at"] = almost.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert wdc.should_attempt_scheduled_refresh() is False

    def test_fresh_cache_short_circuits_even_with_old_attempt(self):
        """Staleness is checked first: a fresh cache never re-polls, no
        matter how old the last attempt is."""
        from app.services import wfirma_dictionary_cache as wdc
        _reset(wdc)
        wdc._LIVE_CACHE["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        wdc._LIVE_CACHE["source_state"]["invoice_series"]  = "live"
        wdc._LIVE_CACHE["source_state"]["proforma_series"] = "live"
        old = datetime.now(timezone.utc) - timedelta(hours=5)
        wdc._REFRESH_STATUS["last_started_at"] = old.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert wdc.should_attempt_scheduled_refresh() is False

    def test_mixed_source_state_is_not_stale_within_ttl(self):
        """Pre-existing is_cache_stale semantics pinned: staleness by state
        requires BOTH dictionaries in baseline/error; one live dictionary
        within TTL keeps the cache fresh (partial recovery is honored)."""
        from app.services import wfirma_dictionary_cache as wdc
        _reset(wdc)
        wdc._LIVE_CACHE["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        wdc._LIVE_CACHE["source_state"]["invoice_series"]  = "live"
        wdc._LIVE_CACHE["source_state"]["proforma_series"] = "baseline"
        assert wdc.is_cache_stale() is False
        assert wdc.should_attempt_scheduled_refresh() is False


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler tick wiring
# ─────────────────────────────────────────────────────────────────────────────

class TestSchedulerTick:

    def test_flag_disabled_no_refresh(self):
        from app.services import wfirma_dictionary_cache as wdc
        from app.services import wfirma_webhook_scheduler as sched
        from app.core.config import settings
        _reset(wdc)
        with patch.object(settings, "series_bootstrap_enabled", False), \
             patch.object(wdc, "refresh_from_wfirma") as mock_refresh:
            sched._run_series_refresh_tick()
        mock_refresh.assert_not_called()

    def test_due_refresh_fires_with_scheduler_trigger(self):
        from app.services import wfirma_dictionary_cache as wdc
        from app.services import wfirma_webhook_scheduler as sched
        from app.core.config import settings
        _reset(wdc)   # stale + never attempted → due
        with patch.object(settings, "series_bootstrap_enabled", True), \
             patch.object(wdc, "refresh_from_wfirma",
                          return_value=wdc.get_dictionaries()) as mock_refresh:
            sched._run_series_refresh_tick()
        mock_refresh.assert_called_once_with(trigger="scheduler")

    def test_not_due_no_refresh(self):
        from app.services import wfirma_dictionary_cache as wdc
        from app.services import wfirma_webhook_scheduler as sched
        from app.core.config import settings
        _reset(wdc)
        wdc._LIVE_CACHE["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        wdc._LIVE_CACHE["source_state"]["invoice_series"]  = "live"
        wdc._LIVE_CACHE["source_state"]["proforma_series"] = "live"
        with patch.object(settings, "series_bootstrap_enabled", True), \
             patch.object(wdc, "refresh_from_wfirma") as mock_refresh:
            sched._run_series_refresh_tick()
        mock_refresh.assert_not_called()

    def test_refresh_exception_is_isolated(self):
        """A blow-up inside the refresh must never escape the tick step."""
        from app.services import wfirma_dictionary_cache as wdc
        from app.services import wfirma_webhook_scheduler as sched
        from app.core.config import settings
        _reset(wdc)
        with patch.object(settings, "series_bootstrap_enabled", True), \
             patch.object(wdc, "refresh_from_wfirma",
                          side_effect=RuntimeError("boom")):
            sched._run_series_refresh_tick()   # must not raise

    def test_tick_runs_before_events_db_guard(self):
        """Source pin: step 0 fires even when webhook storage is broken."""
        src = (_SVC_ROOT / "app/services/wfirma_webhook_scheduler.py").read_text(
            encoding="utf-8")
        call_pos  = src.index("_run_series_refresh_tick()")
        guard_pos = src.index("if _events_db_path is None or _proc_db_path is None:")
        assert call_pos < guard_pos


# ─────────────────────────────────────────────────────────────────────────────
# Status endpoint — HTTP contract
# ─────────────────────────────────────────────────────────────────────────────

def _make_client(auth: bool = True):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import routes_customer_master
    from app.core import security as core_security

    app = FastAPI()
    app.include_router(routes_customer_master.router)
    if auth:
        app.dependency_overrides[core_security.require_api_key] = lambda: True
    return TestClient(app, raise_server_exceptions=False)


class TestStatusEndpointHttp:

    def test_status_endpoint_returns_full_shape(self):
        from app.services import wfirma_dictionary_cache as wdc
        _reset(wdc)
        client = _make_client()
        r = client.get("/api/v1/customer-master/dictionaries/status")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/json")
        body = r.json()
        for key in ("healthy", "running", "last_started_at", "last_completed_at",
                    "duration_ms", "processed", "created", "updated", "skipped",
                    "errors", "last_error", "last_trigger", "fetched_at",
                    "source_state", "is_stale", "cache_ttl_hours",
                    "retry_cooldown_minutes"):
            assert key in body, f"missing key: {key}"

    def test_status_endpoint_reflects_completed_run(self, tmp_path):
        from app.services import wfirma_dictionary_cache as wdc
        import app.services.wfirma_client as _wfc
        _reset(wdc, tmp_path)
        with patch.object(_wfc, "fetch_series", return_value=list(_FIXTURE_SERIES)):
            wdc.refresh_from_wfirma(trigger="scheduler")
        body = _make_client().get(
            "/api/v1/customer-master/dictionaries/status").json()
        assert body["healthy"] is True
        assert body["running"] is False
        assert body["processed"] == 5
        assert body["last_trigger"] == "scheduler"

    def test_status_endpoint_requires_auth(self):
        """With an API key configured and no credentials supplied, the
        endpoint must reject (dev mode with no key configured fails open
        by design — pin a key so the guard actually enforces)."""
        from app.core.config import settings
        client = _make_client(auth=False)
        with patch.object(settings, "api_key", "test-key-for-auth-pin"):
            r = client.get("/api/v1/customer-master/dictionaries/status")
        assert r.status_code in (401, 403)

    def test_status_endpoint_not_shadowed_by_contractor_id_route(self):
        """'dictionaries' must never be routed as a contractor_id."""
        client = _make_client()
        r = client.get("/api/v1/customer-master/dictionaries/status")
        assert r.status_code == 200, \
            "status route must not collide with /{contractor_id}"


# ─────────────────────────────────────────────────────────────────────────────
# Route + startup wiring (source-grep pins)
# ─────────────────────────────────────────────────────────────────────────────

class TestWiringPins:

    def test_status_route_declared_and_wired(self):
        src = (_SVC_ROOT / "app/api/routes_customer_master.py").read_text(
            encoding="utf-8")
        assert '@router.get("/dictionaries/status"' in src
        assert "get_refresh_status()" in src
        # Must be declared BEFORE the /{contractor_id} catch-all.
        assert src.index('@router.get("/dictionaries/status"') < \
               src.index('@router.get("/{contractor_id}"')

    def test_startup_passes_startup_trigger(self):
        src = (_SVC_ROOT / "app/main.py").read_text(encoding="utf-8")
        assert 'refresh_from_wfirma(trigger="startup")' in src

    def test_refresh_route_unchanged_zero_arg_call(self):
        """The operator Run-Now route keeps the shared function with its
        default trigger (existing pin: exact string wdc.refresh_from_wfirma())."""
        src = (_SVC_ROOT / "app/api/routes_customer_master.py").read_text(
            encoding="utf-8")
        assert "wdc.refresh_from_wfirma()" in src

    def test_no_new_wfirma_write_calls(self):
        """Hard rule: the scheduled path stays read-only against wFirma."""
        for rel in ("app/services/wfirma_dictionary_cache.py",
                    "app/services/wfirma_webhook_scheduler.py"):
            src = (_SVC_ROOT / rel).read_text(encoding="utf-8")
            for forbidden in ("create_customer(", "create_contractor(",
                              "create_invoice(", "create_pz("):
                assert forbidden not in src, f"{forbidden} found in {rel}"
