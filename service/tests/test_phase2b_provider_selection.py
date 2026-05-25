"""
test_phase2b_provider_selection.py — Provider-selection architecture (Phase 2B).

Tests:
  1. Provider constants and helper functions in ai_gateway.py
  2. _cowork_call() stub behaviour
  3. _is_cb_failure() — logical gates vs real failures
  4. call() with cowork-primary path (enabled, no fallback)
  5. call() with cowork-primary path (enabled, fallback to Anthropic)
  6. call() with direct Anthropic path (backward compatible)
  7. call() with cowork disabled, no API key → None immediately
  8. Ledger record includes provider_requested, provider_used, fallback_used
  9. Circuit breaker NOT tripped by logical gates
 10. /status endpoint returns 5 new provider fields
 11. Gateway violation rule: ai_call_ledger.py exempt from model-string test
 12. _migrate_schema() adds columns idempotently
 16. check_key_health() — returns None when admin key absent
 17. check_key_health() — returns status dict on Admin API success
 18. check_key_health() — error dict when Admin API call fails
 19. check_key_health() — TTL cache prevents duplicate calls
 20. is_available() — uses health check when admin key configured
 21. /status includes api_key_health field

All tests:
  - No external network calls
  - No writes to real wFirma/DHL/accounting systems
  - ai_call_ledger writes only when ledger is mocked
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call as mock_call

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services import ai_gateway


# ── Helpers ───────────────────────────────────────────────────────────────────

def _settings(**kwargs):
    """Build a MagicMock settings object with sane Phase-2B defaults."""
    s = MagicMock()
    s.ai_parser_enabled           = kwargs.get("ai_parser_enabled", True)
    s.anthropic_api_key           = kwargs.get("anthropic_api_key", "sk-test-key")
    s.ai_cowork_enabled           = kwargs.get("ai_cowork_enabled", False)
    s.ai_cowork_timeout_seconds   = kwargs.get("ai_cowork_timeout_seconds", 30)
    s.ai_provider_preference      = kwargs.get("ai_provider_preference", "claude_cowork")
    s.ai_fallback_enabled         = kwargs.get("ai_fallback_enabled", False)
    s.ai_gateway_daily_budget_usd = kwargs.get("ai_gateway_daily_budget_usd", 0.0)
    s.ai_gateway_max_retries      = kwargs.get("ai_gateway_max_retries", 0)
    s.ai_gateway_timeout_seconds  = kwargs.get("ai_gateway_timeout_seconds", 30)
    # Phase-3 field: separate cowork API key (None = fall back to anthropic_api_key)
    s.ai_cowork_api_key           = kwargs.get("ai_cowork_api_key", None)
    # Admin API key health (both None by default — graceful degradation path)
    s.anthropic_admin_api_key     = kwargs.get("anthropic_admin_api_key", None)
    s.anthropic_api_key_id        = kwargs.get("anthropic_api_key_id", None)
    return s


def _mock_redactor():
    r = MagicMock()
    r.redact_pair.return_value = ("clean_system", "clean_user")
    return r


def _mock_ledger():
    led = MagicMock()
    led.get_daily_cost_usd.return_value = 0.0
    led.prompt_hash.return_value = "deadbeef"
    led.estimate_tokens.return_value = 100
    led.estimate_cost.return_value = 0.001
    led.record.return_value = None
    return led


def _mock_anthropic_response(text: str = "ok"):
    resp = MagicMock()
    resp.content = [MagicMock(text=text)]
    resp.usage.input_tokens  = 50
    resp.usage.output_tokens = 20
    return resp


def _fake_anthropic_module(response=None, raise_exc=None):
    """Build a fake anthropic module stub for sys.modules injection."""
    mod = MagicMock()
    mod.RateLimitError   = type("RateLimitError",   (Exception,), {})
    mod.APIStatusError   = type("APIStatusError",   (Exception,), {})

    client_instance = MagicMock()
    if raise_exc is not None:
        client_instance.messages.create.side_effect = raise_exc
    else:
        client_instance.messages.create.return_value = response or _mock_anthropic_response()
    mod.Anthropic.return_value = client_instance
    return mod


# ── 1. Provider constants ─────────────────────────────────────────────────────

def test_provider_constants_defined():
    assert ai_gateway._PROVIDER_COWORK    == "claude_cowork"
    assert ai_gateway._PROVIDER_ANTHROPIC == "anthropic_api"


# ── 2. _cowork_call() signature (Phase 3: real call, no longer a stub) ─────────
# Note: Phase 2B had two tests here verifying stub (no-network, returns None) behavior.
# Phase 3 (PR #362) replaced the stub with a real Anthropic SDK call.
# The stub-behavior tests were removed; Phase 3 has 11 dedicated tests
# (test_phase3_cowork_provider.py) covering real _cowork_call() behavior.

def test_cowork_call_signature_accepts_required_kwargs():
    """_cowork_call() must accept the Phase-3 keyword arguments without TypeError."""
    # Call with an empty api_key so it returns immediately with no_api_key error.
    # Verifies the function exists with the Phase-3 5-tuple return type.
    text, in_t, out_t, cost, err = ai_gateway._cowork_call(
        system="sys", user="usr", selected_model="m", max_tokens=100, timeout_s=30,
        api_key="", max_retries=1, ledger=None,
    )
    assert text is None
    assert err is not None  # no_api_key or similar early-exit reason


# ── 3. _is_cb_failure() ───────────────────────────────────────────────────────

def test_cb_failure_none_is_not_failure():
    assert ai_gateway._is_cb_failure(None) is False


def test_cb_failure_logical_gates_not_failures():
    for gate in ("cowork_not_implemented", "budget_exhausted", "cb_open", "disabled", "ImportError"):
        assert ai_gateway._is_cb_failure(gate) is False, f"Expected {gate!r} not to trip CB"


def test_cb_failure_real_errors_are_failures():
    for err in ("RateLimitError", "APIStatusError", "Timeout", "ConnectionError"):
        assert ai_gateway._is_cb_failure(err) is True, f"Expected {err!r} to trip CB"


# ── 4. call() — cowork primary, fallback disabled ─────────────────────────────

def test_call_cowork_primary_stub_no_fallback_returns_none():
    """Cowork enabled, fallback disabled → None when cowork returns error."""
    # Phase 3: _cowork_call returns 5-tuple (text, in_tok, out_tok, cost, error)
    ai_gateway.reset_circuit_breaker()
    settings = _settings(ai_cowork_enabled=True, ai_fallback_enabled=False)

    with patch("app.core.config.settings", settings, create=True), \
         patch("app.services.ai_gateway._cowork_call",
               return_value=(None, 0, 0, 0.0, "cowork_bridge_unavailable")), \
         patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=0.0), \
         patch("app.services.ai_call_ledger.record"), \
         patch("app.services.ai_call_ledger.prompt_hash", return_value="h"), \
         patch("app.services.ai_call_ledger.estimate_tokens", return_value=10), \
         patch("app.services.ai_call_ledger.estimate_cost", return_value=0.0), \
         patch("app.services.ai_redactor.redact_pair", return_value=("sys", "usr")):

        result = ai_gateway.call(
            system="sys", user="usr", task_type="test",
            service_name="svc", object_id="obj1",
        )

    assert result is None


def _selective_import(settings, ledger, redactor):
    """Import hook that injects mocks for ai_call_ledger and ai_redactor."""
    real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def _hook(name, *args, **kwargs):
        return real_import(name, *args, **kwargs)

    return _hook


# ── Cleaner approach: patch the module-level imports directly ──────────────────

def _run_gateway_call(settings_obj, ledger_obj=None, redactor_obj=None, **call_kwargs):
    """Helper: run ai_gateway.call() with mocked settings, ledger, redactor."""
    if ledger_obj is None:
        ledger_obj = _mock_ledger()
    if redactor_obj is None:
        redactor_obj = _mock_redactor()

    ai_gateway.reset_circuit_breaker()

    with patch("app.services.ai_gateway.settings", settings_obj, create=True):
        # Patch the lazy imports inside call()
        with patch("app.services.ai_call_ledger.get_daily_cost_usd",
                   side_effect=ledger_obj.get_daily_cost_usd), \
             patch("app.services.ai_call_ledger.record",
                   side_effect=ledger_obj.record), \
             patch("app.services.ai_call_ledger.prompt_hash",
                   side_effect=ledger_obj.prompt_hash), \
             patch("app.services.ai_call_ledger.estimate_tokens",
                   side_effect=ledger_obj.estimate_tokens), \
             patch("app.services.ai_call_ledger.estimate_cost",
                   side_effect=ledger_obj.estimate_cost):

            # Patch the config import inside call()
            with patch("app.core.config.settings", settings_obj, create=True):
                result = ai_gateway.call(**{
                    "system": "sys_prompt",
                    "user": "usr_msg",
                    "task_type": "test_task",
                    "service_name": "test_svc",
                    **call_kwargs
                })

    return result


# ── 5. call() with cowork stub — no fallback ──────────────────────────────────

def test_call_cowork_stub_no_fallback():
    """With cowork enabled + fallback disabled, call() returns None when cowork fails."""
    # Phase 3: _cowork_call is real; mock it to return a failure 5-tuple so
    # the test stays deterministic without making real Anthropic API calls.
    ai_gateway.reset_circuit_breaker()
    settings = _settings(ai_cowork_enabled=True, ai_fallback_enabled=False)

    with patch("app.core.config.settings", settings), \
         patch("app.services.ai_gateway._cowork_call",
               return_value=(None, 0, 0, 0.0, "cowork_bridge_unavailable")), \
         patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=0.0), \
         patch("app.services.ai_call_ledger.record") as mock_record, \
         patch("app.services.ai_call_ledger.prompt_hash", return_value="hash123"), \
         patch("app.services.ai_call_ledger.estimate_tokens", return_value=50), \
         patch("app.services.ai_call_ledger.estimate_cost", return_value=0.001), \
         patch("app.services.ai_redactor.redact_pair", return_value=("sys", "usr")):

        result = ai_gateway.call(
            system="sys", user="usr", task_type="test", service_name="svc"
        )

    assert result is None
    # Ledger record must be called (provider_requested=claude_cowork, no fallback)
    assert mock_record.called
    ledger_entry = mock_record.call_args[0][0]
    assert ledger_entry["provider_requested"] == "claude_cowork"
    assert ledger_entry["provider_used"] is None
    assert ledger_entry["fallback_used"] == 0
    assert ledger_entry["success"] == 0


def test_call_cowork_stub_cb_not_incremented():
    """Cowork logical-gate error must NOT increment the Anthropic circuit breaker."""
    # Phase 3: mock _cowork_call to return a logical-gate error (not a network failure).
    # 'cowork_bridge_unavailable' is in _LOGICAL_GATES → _is_cb_failure() returns False.
    ai_gateway.reset_circuit_breaker()
    settings = _settings(ai_cowork_enabled=True, ai_fallback_enabled=False)

    with patch("app.core.config.settings", settings), \
         patch("app.services.ai_gateway._cowork_call",
               return_value=(None, 0, 0, 0.0, "cowork_bridge_unavailable")), \
         patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=0.0), \
         patch("app.services.ai_call_ledger.record"), \
         patch("app.services.ai_call_ledger.prompt_hash", return_value="h"), \
         patch("app.services.ai_call_ledger.estimate_tokens", return_value=10), \
         patch("app.services.ai_call_ledger.estimate_cost", return_value=0.0), \
         patch("app.services.ai_redactor.redact_pair", return_value=("s", "u")):

        # Call 6 times — cowork returns logical-gate failure every time
        for _ in range(6):
            ai_gateway.call(system="s", user="u", task_type="t", service_name="svc")

    # Anthropic CB should NOT be open (logical gate, not a network failure)
    assert not ai_gateway._cb_is_open(), "CB should NOT be open after cowork logical-gate failures"


# ── 6. call() with cowork + fallback → Anthropic succeeds ─────────────────────

def test_call_cowork_stub_fallback_to_anthropic():
    """Cowork enabled + fallback enabled → falls through to Anthropic when cowork fails."""
    # Phase 3: mock _cowork_call to return failure 5-tuple, then Anthropic fallback succeeds.
    ai_gateway.reset_circuit_breaker()
    settings = _settings(
        ai_cowork_enabled=True,
        ai_fallback_enabled=True,
        anthropic_api_key="sk-real",
    )

    ant_mod = _fake_anthropic_module(_mock_anthropic_response("advisory text from anthropic"))

    with patch("app.core.config.settings", settings), \
         patch("app.services.ai_gateway._cowork_call",
               return_value=(None, 0, 0, 0.0, "cowork_bridge_unavailable")), \
         patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=0.0), \
         patch("app.services.ai_call_ledger.record") as mock_record, \
         patch("app.services.ai_call_ledger.prompt_hash", return_value="h"), \
         patch("app.services.ai_call_ledger.estimate_tokens", return_value=50), \
         patch("app.services.ai_call_ledger.estimate_cost", return_value=0.001), \
         patch("app.services.ai_redactor.redact_pair", return_value=("sys", "usr")), \
         patch.dict(sys.modules, {"anthropic": ant_mod}):

        result = ai_gateway.call(
            system="sys", user="usr", task_type="test", service_name="svc"
        )

    assert result == "advisory text from anthropic"
    assert mock_record.called
    entry = mock_record.call_args[0][0]
    assert entry["provider_requested"] == "claude_cowork"
    assert entry["provider_used"] == "anthropic_api"
    assert entry["fallback_used"] == 1
    assert entry["success"] == 1


def test_call_cowork_fallback_no_api_key_returns_none():
    """Cowork enabled + fallback enabled but no API key → None."""
    ai_gateway.reset_circuit_breaker()
    settings = _settings(
        ai_cowork_enabled=True,
        ai_fallback_enabled=True,
        anthropic_api_key="",
    )

    with patch("app.core.config.settings", settings), \
         patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=0.0), \
         patch("app.services.ai_call_ledger.record") as mock_record, \
         patch("app.services.ai_call_ledger.prompt_hash", return_value="h"), \
         patch("app.services.ai_call_ledger.estimate_tokens", return_value=10), \
         patch("app.services.ai_call_ledger.estimate_cost", return_value=0.0), \
         patch("app.services.ai_redactor.redact_pair", return_value=("s", "u")):

        result = ai_gateway.call(
            system="s", user="u", task_type="t", service_name="svc"
        )

    assert result is None
    entry = mock_record.call_args[0][0]
    assert entry["fallback_used"] == 1
    assert entry["error_type"] == "no_api_key"
    assert entry["provider_used"] is None


# ── 7. call() — direct Anthropic path (backward compatible) ───────────────────

def test_call_direct_anthropic_path_cowork_disabled():
    """Cowork disabled → direct Anthropic path; provider_requested=anthropic_api."""
    ai_gateway.reset_circuit_breaker()
    settings = _settings(ai_cowork_enabled=False, anthropic_api_key="sk-key")
    ant_mod = _fake_anthropic_module(_mock_anthropic_response("direct result"))

    with patch("app.core.config.settings", settings), \
         patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=0.0), \
         patch("app.services.ai_call_ledger.record") as mock_record, \
         patch("app.services.ai_call_ledger.prompt_hash", return_value="h"), \
         patch("app.services.ai_call_ledger.estimate_tokens", return_value=50), \
         patch("app.services.ai_call_ledger.estimate_cost", return_value=0.001), \
         patch("app.services.ai_redactor.redact_pair", return_value=("sys", "usr")), \
         patch.dict(sys.modules, {"anthropic": ant_mod}):

        result = ai_gateway.call(
            system="sys", user="usr", task_type="test", service_name="svc"
        )

    assert result == "direct result"
    entry = mock_record.call_args[0][0]
    assert entry["provider_requested"] == "anthropic_api"
    assert entry["provider_used"] == "anthropic_api"
    assert entry["fallback_used"] == 0
    assert entry["success"] == 1


def test_call_direct_anthropic_failure_records_provider_used_none():
    """Direct Anthropic path that fails → provider_used=None in ledger."""
    ai_gateway.reset_circuit_breaker()
    settings = _settings(ai_cowork_enabled=False, anthropic_api_key="sk-key",
                         ai_gateway_max_retries=0)

    ant_mod = _fake_anthropic_module(raise_exc=Exception("APIError"))

    with patch("app.core.config.settings", settings), \
         patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=0.0), \
         patch("app.services.ai_call_ledger.record") as mock_record, \
         patch("app.services.ai_call_ledger.prompt_hash", return_value="h"), \
         patch("app.services.ai_call_ledger.estimate_tokens", return_value=10), \
         patch("app.services.ai_call_ledger.estimate_cost", return_value=0.0), \
         patch("app.services.ai_redactor.redact_pair", return_value=("s", "u")), \
         patch.dict(sys.modules, {"anthropic": ant_mod}):

        result = ai_gateway.call(
            system="s", user="u", task_type="t", service_name="svc"
        )

    assert result is None
    entry = mock_record.call_args[0][0]
    assert entry["provider_used"] is None
    assert entry["fallback_used"] == 0
    assert entry["success"] == 0


# ── 8. call() — no API key, no cowork → immediate None (no ledger write) ──────

def test_call_no_apikey_no_cowork_returns_none_no_ledger():
    """No API key and cowork disabled → gate out before reaching ledger write."""
    ai_gateway.reset_circuit_breaker()
    settings = _settings(ai_cowork_enabled=False, anthropic_api_key="")

    with patch("app.core.config.settings", settings), \
         patch("app.services.ai_call_ledger.record") as mock_record:

        result = ai_gateway.call(
            system="s", user="u", task_type="t", service_name="svc"
        )

    assert result is None
    assert not mock_record.called, "Ledger must not be written when gated out before model selection"


# ── 9. call() — ai_parser_enabled=False → None, no ledger ────────────────────

def test_call_parser_disabled_returns_none_no_ledger():
    ai_gateway.reset_circuit_breaker()
    settings = _settings(ai_parser_enabled=False)

    with patch("app.core.config.settings", settings), \
         patch("app.services.ai_call_ledger.record") as mock_record:

        result = ai_gateway.call(
            system="s", user="u", task_type="t", service_name="svc"
        )

    assert result is None
    assert not mock_record.called


# ── 10. is_available() — Phase 2B behaviour ───────────────────────────────────

def test_is_available_cowork_enabled_no_key():
    """Cowork enabled but no API key → is_available=False (Phase 3 fixed false-positive).

    Phase 2B had a false positive: cowork_enabled=True returned is_available=True
    even with no key. Phase 3 (PR #362) fixed this — now requires a real key.
    """
    settings = _settings(ai_parser_enabled=True, ai_cowork_enabled=True, anthropic_api_key="")
    with patch("app.core.config.settings", settings):
        assert ai_gateway.is_available() is False


def test_is_available_cowork_disabled_with_key():
    settings = _settings(ai_parser_enabled=True, ai_cowork_enabled=False, anthropic_api_key="sk-key")
    with patch("app.core.config.settings", settings):
        assert ai_gateway.is_available() is True


def test_is_available_cowork_disabled_no_key():
    settings = _settings(ai_parser_enabled=True, ai_cowork_enabled=False, anthropic_api_key="")
    with patch("app.core.config.settings", settings):
        assert ai_gateway.is_available() is False


def test_is_available_parser_disabled():
    settings = _settings(ai_parser_enabled=False, ai_cowork_enabled=True, anthropic_api_key="sk-key")
    with patch("app.core.config.settings", settings):
        assert ai_gateway.is_available() is False


# ── 11. /status endpoint — 5 new provider fields ─────────────────────────────

def test_advisory_status_returns_provider_fields():
    """GET /status must include all 5 Phase 2B provider fields."""
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app

    settings = _settings(
        ai_cowork_enabled=True,
        ai_fallback_enabled=True,
        ai_provider_preference="claude_cowork",
    )

    with patch("app.core.config.settings", settings), \
         patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=0.0), \
         patch("app.services.ai_gateway.is_available", return_value=True):

        client = TestClient(fastapi_app)
        resp = client.get(
            "/api/v1/ai/advisory/status",
            headers={"X-API-Key": ""},
        )

    # The endpoint may 401 if auth is enabled in test env — check both
    if resp.status_code == 401:
        pytest.skip("Auth enabled in test environment — skipping status field check")

    assert resp.status_code == 200
    body = resp.json()
    assert "cowork_enabled"      in body, "Missing cowork_enabled"
    assert "cowork_available"    in body, "Missing cowork_available"
    assert "fallback_enabled"    in body, "Missing fallback_enabled"
    assert "provider_preference" in body, "Missing provider_preference"
    assert "active_provider"     in body, "Missing active_provider"


def test_advisory_status_active_provider_logic():
    """active_provider computation: cowork_enabled + preference=claude_cowork → claude_cowork."""
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app

    settings_cowork_primary = _settings(
        ai_cowork_enabled=True,
        ai_provider_preference="claude_cowork",
    )

    with patch("app.core.config.settings", settings_cowork_primary), \
         patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=0.0), \
         patch("app.services.ai_gateway.is_available", return_value=True):

        client = TestClient(fastapi_app)
        resp = client.get("/api/v1/ai/advisory/status", headers={"X-API-Key": ""})

    if resp.status_code == 401:
        pytest.skip("Auth enabled in test env")

    body = resp.json()
    assert body["active_provider"] == "claude_cowork"
    assert body["cowork_enabled"]  is True
    assert body["fallback_enabled"] is False


def test_advisory_status_active_provider_anthropic_when_cowork_disabled():
    """active_provider = anthropic_api when cowork disabled and gateway available."""
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app

    settings_anthropic = _settings(ai_cowork_enabled=False)

    with patch("app.core.config.settings", settings_anthropic), \
         patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=0.0), \
         patch("app.services.ai_gateway.is_available", return_value=True):

        client = TestClient(fastapi_app)
        resp = client.get("/api/v1/ai/advisory/status", headers={"X-API-Key": ""})

    if resp.status_code == 401:
        pytest.skip("Auth enabled in test env")

    body = resp.json()
    assert body["active_provider"] == "anthropic_api"


# ── 12. Ledger migration — idempotent ─────────────────────────────────────────

def test_migrate_schema_idempotent():
    """_migrate_schema() must not raise when called twice on same DB."""
    import sqlite3
    from app.services.ai_call_ledger import _ensure_schema, _migrate_schema

    conn = sqlite3.connect(":memory:")
    _ensure_schema(conn)   # creates table + migrates
    _migrate_schema(conn)  # second run — must be no-op (no exception)
    conn.close()


def test_provider_columns_exist_after_migration():
    """After _ensure_schema, the three provider columns must exist."""
    import sqlite3
    from app.services.ai_call_ledger import _ensure_schema

    conn = sqlite3.connect(":memory:")
    _ensure_schema(conn)

    cursor = conn.execute("PRAGMA table_info(ai_calls)")
    columns = {row[1] for row in cursor.fetchall()}

    assert "provider_requested" in columns, "Missing provider_requested column"
    assert "provider_used"      in columns, "Missing provider_used column"
    assert "fallback_used"      in columns, "Missing fallback_used column"
    conn.close()


def test_legacy_ledger_record_works_without_provider_fields():
    """Old callers that don't pass provider fields must still insert cleanly."""
    import sqlite3
    from app.services import ai_call_ledger as ledger

    conn = sqlite3.connect(":memory:")
    from app.services.ai_call_ledger import _ensure_schema
    _ensure_schema(conn)
    conn.close()

    # record() internally opens its own connection — use a temp file DB path
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("app.services.ai_call_ledger._db_path", return_value=Path(tmpdir) / "test.db"):
            ledger.record({
                "service":        "test",
                "task_type":      "test",
                "selected_model": "test-model",
                "model_tier":     "haiku",
                "prompt_hash":    "abc",
                "success":        True,
                # No provider fields — backward-compat test
            })
            # Should not raise. Verify the record landed.
            import sqlite3 as sql
            conn2 = sql.connect(str(Path(tmpdir) / "test.db"))
            row = conn2.execute("SELECT provider_requested, provider_used, fallback_used FROM ai_calls").fetchone()
            assert row is not None
            assert row[0] is None   # provider_requested defaults to NULL
            assert row[1] is None   # provider_used defaults to NULL
            assert row[2] == 0      # fallback_used defaults to 0
            conn2.close()


# ── 13. Gateway violation rule — provider constants in gateway only ────────────

def test_provider_constants_only_in_gateway():
    """_PROVIDER_COWORK and _PROVIDER_ANTHROPIC are defined only in ai_gateway.py."""
    import re

    _APP = Path(__file__).resolve().parent.parent / "app"
    _GATEWAY = _APP / "services" / "ai_gateway.py"

    violations = []
    for py_file in _APP.rglob("*.py"):
        if py_file == _GATEWAY:
            continue
        text = py_file.read_text(encoding="utf-8", errors="replace")
        # Looking for literal constant *assignments* like _PROVIDER_COWORK = "..."
        # References/usages from imports are fine; only new constant definitions are violations
        if re.search(r'_PROVIDER_COWORK\s*=', text) or re.search(r'_PROVIDER_ANTHROPIC\s*=', text):
            violations.append(str(py_file))

    assert not violations, (
        "Provider constants _PROVIDER_COWORK / _PROVIDER_ANTHROPIC defined outside ai_gateway.py:\n"
        + "\n".join(violations)
    )


# ── 14. Config defaults are all OFF ──────────────────────────────────────────

def test_config_new_flags_default_off():
    """Phase 2B config flags must default to OFF/False."""
    from app.core.config import Settings

    s = Settings()
    assert s.ai_cowork_enabled         is False
    assert s.ai_cowork_timeout_seconds == 30
    assert s.ai_provider_preference    == "claude_cowork"
    # ai_fallback_enabled already existed — verify it stays False
    assert s.ai_fallback_enabled       is False


# ── 15. Circuit breaker: only real failures increment it ─────────────────────

def test_circuit_breaker_not_opened_by_cowork_stub():
    """Cowork logical-gate failures must NOT open the Anthropic circuit breaker.

    Phase 3: _cowork_call() is now a real Anthropic SDK call, so we mock it to
    return a logical-gate error ('cowork_bridge_unavailable').  _is_cb_failure()
    returns False for logical gates — the Anthropic CB must stay closed regardless
    of how many times the cowork path returns a logical-gate error.
    """
    ai_gateway.reset_circuit_breaker()
    settings = _settings(ai_cowork_enabled=True, ai_fallback_enabled=False)

    with patch("app.core.config.settings", settings), \
         patch("app.services.ai_gateway._cowork_call",
               return_value=(None, 0, 0, 0.0, "cowork_bridge_unavailable")), \
         patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=0.0), \
         patch("app.services.ai_call_ledger.record"), \
         patch("app.services.ai_call_ledger.prompt_hash", return_value="h"), \
         patch("app.services.ai_call_ledger.estimate_tokens", return_value=10), \
         patch("app.services.ai_call_ledger.estimate_cost", return_value=0.0), \
         patch("app.services.ai_redactor.redact_pair", return_value=("s", "u")):

        for _ in range(ai_gateway._CB_THRESHOLD + 2):
            ai_gateway.call(system="s", user="u", task_type="t", service_name="svc")

    assert not ai_gateway._cb_is_open()


# ── 16–21. Admin API key health check ────────────────────────────────────────

def _admin_settings(**kwargs):
    return _settings(
        anthropic_admin_api_key=kwargs.get("admin_key", "sk-admin-key"),
        anthropic_api_key_id=kwargs.get("key_id", "apikey_01TestKeyId"),
        **{k: v for k, v in kwargs.items() if k not in ("admin_key", "key_id")},
    )


def _mock_httpx_response(status_code=200, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {
        "id":               "apikey_01TestKeyId",
        "status":           "active",
        "name":             "Developer Key",
        "partial_key_hint": "sk-ant-api03-R2D...igAA",
        "expires_at":       None,
        "workspace_id":     "wrkspc_01Test",
        "type":             "api_key",
    }
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_check_key_health_returns_none_when_no_admin_key():
    """No admin key configured → check_key_health() returns None."""
    settings = _settings()  # anthropic_admin_api_key=None by default
    ai_gateway._KEY_HEALTH_CACHE.clear()

    with patch("app.core.config.settings", settings):
        result = ai_gateway.check_key_health()

    assert result is None


def test_check_key_health_returns_none_when_no_key_id():
    """Admin key present but key_id absent → check_key_health() returns None."""
    settings = _settings(anthropic_admin_api_key="sk-admin", anthropic_api_key_id=None)
    ai_gateway._KEY_HEALTH_CACHE.clear()

    with patch("app.core.config.settings", settings):
        result = ai_gateway.check_key_health()

    assert result is None


def test_check_key_health_success():
    """Admin API returns 200 → result dict with status, name, partial_key_hint."""
    settings = _admin_settings()
    ai_gateway._KEY_HEALTH_CACHE.clear()

    mock_resp = _mock_httpx_response()

    with patch("app.core.config.settings", settings), \
         patch("httpx.get", return_value=mock_resp) as mock_get:

        result = ai_gateway.check_key_health(force_refresh=True)

    assert result is not None
    assert result["status"] == "active"
    assert result["name"]   == "Developer Key"
    assert result["partial_key_hint"] == "sk-ant-api03-R2D...igAA"
    assert result["error"]  is None

    # Verify correct URL and headers were used
    call_kwargs = mock_get.call_args
    assert "apikey_01TestKeyId" in call_kwargs[0][0]
    assert call_kwargs[1]["headers"]["X-Api-Key"] == "sk-admin-key"
    assert call_kwargs[1]["headers"]["anthropic-version"] == "2023-06-01"


def test_check_key_health_api_error_returns_error_dict():
    """Admin API returns error → result dict with error set (no exception raised)."""
    settings = _admin_settings()
    ai_gateway._KEY_HEALTH_CACHE.clear()

    with patch("app.core.config.settings", settings), \
         patch("httpx.get", side_effect=Exception("connection refused")):

        result = ai_gateway.check_key_health(force_refresh=True)

    assert result is not None
    assert result["error"] is not None
    assert "connection refused" in result["error"]
    assert result["status"] is None


def test_check_key_health_ttl_cache():
    """Second call within TTL returns cached result without hitting the API again."""
    settings = _admin_settings()
    ai_gateway._KEY_HEALTH_CACHE.clear()

    mock_resp = _mock_httpx_response()

    with patch("app.core.config.settings", settings), \
         patch("httpx.get", return_value=mock_resp) as mock_get:

        result1 = ai_gateway.check_key_health(force_refresh=True)
        result2 = ai_gateway.check_key_health()  # should use cache

    assert result1 == result2
    assert mock_get.call_count == 1, "Admin API should be called only once (second call cached)"


def test_check_key_health_force_refresh_bypasses_cache():
    """force_refresh=True bypasses TTL cache and re-hits the Admin API."""
    settings = _admin_settings()
    ai_gateway._KEY_HEALTH_CACHE.clear()

    mock_resp = _mock_httpx_response()

    with patch("app.core.config.settings", settings), \
         patch("httpx.get", return_value=mock_resp) as mock_get:

        ai_gateway.check_key_health(force_refresh=True)
        ai_gateway.check_key_health(force_refresh=True)

    assert mock_get.call_count == 2


def test_is_available_uses_key_health_when_admin_configured():
    """is_available() returns False when Admin API says key is inactive."""
    settings = _admin_settings(anthropic_api_key="sk-key")
    ai_gateway._KEY_HEALTH_CACHE.clear()

    inactive_resp = _mock_httpx_response(json_body={
        "id": "apikey_01TestKeyId", "status": "expired",
        "name": "Old Key", "partial_key_hint": "sk-...",
        "expires_at": "2020-01-01T00:00:00Z", "workspace_id": None,
    })

    with patch("app.core.config.settings", settings), \
         patch("httpx.get", return_value=inactive_resp):

        available = ai_gateway.is_available()

    assert available is False, "is_available() should be False when key status=expired"


def test_is_available_true_when_admin_says_active():
    """is_available() returns True when Admin API says key is active."""
    settings = _admin_settings(anthropic_api_key="sk-key")
    ai_gateway._KEY_HEALTH_CACHE.clear()

    active_resp = _mock_httpx_response()  # status=active by default

    with patch("app.core.config.settings", settings), \
         patch("httpx.get", return_value=active_resp):

        available = ai_gateway.is_available()

    assert available is True


def test_is_available_falls_back_on_admin_api_error():
    """If Admin API call errors, is_available() falls back to key-non-empty check."""
    settings = _admin_settings(anthropic_api_key="sk-valid-key")
    ai_gateway._KEY_HEALTH_CACHE.clear()

    with patch("app.core.config.settings", settings), \
         patch("httpx.get", side_effect=Exception("timeout")):

        available = ai_gateway.is_available()

    # error path → health["error"] is set → falls back → key is non-empty → True
    assert available is True


def test_status_endpoint_includes_api_key_health_field():
    """/status returns api_key_health field (None when admin key not configured)."""
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app

    settings = _settings()  # no admin key

    with patch("app.core.config.settings", settings), \
         patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=0.0), \
         patch("app.services.ai_gateway.is_available", return_value=False), \
         patch("app.services.ai_gateway.check_key_health", return_value=None):

        client = TestClient(fastapi_app)
        resp = client.get("/api/v1/ai/advisory/status", headers={"X-API-Key": ""})

    if resp.status_code == 401:
        pytest.skip("Auth enabled in test env")

    assert resp.status_code == 200
    body = resp.json()
    assert "api_key_health" in body
    assert body["api_key_health"] is None


def test_status_endpoint_api_key_health_populated_when_admin_configured():
    """/status api_key_health populated with status dict when Admin API succeeds."""
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app

    settings = _admin_settings()
    health_data = {
        "status": "active", "name": "Developer Key",
        "partial_key_hint": "sk-ant-...AA",
        "expires_at": None, "workspace_id": "wrkspc_01Test",
        "checked_at": "2026-05-24T12:00:00Z", "error": None,
    }

    with patch("app.core.config.settings", settings), \
         patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=0.0), \
         patch("app.services.ai_gateway.is_available", return_value=True), \
         patch("app.services.ai_gateway.check_key_health", return_value=health_data):

        client = TestClient(fastapi_app)
        resp = client.get("/api/v1/ai/advisory/status", headers={"X-API-Key": ""})

    if resp.status_code == 401:
        pytest.skip("Auth enabled in test env")

    body = resp.json()
    assert body["api_key_health"]["status"] == "active"
    assert body["api_key_health"]["name"]   == "Developer Key"
    assert body["api_key_health"]["error"]  is None
