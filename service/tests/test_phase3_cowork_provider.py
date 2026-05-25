"""
test_phase3_cowork_provider.py — Phase 3 Cowork provider build tests.

Eleven scenarios covering:
  1.  Cowork CB isolated — Anthropic failures do not open Cowork CB
  2.  Anthropic CB isolated — Cowork failures do not open Anthropic CB
  3.  Cowork CB gates the cowork path
  4.  Cowork path success — 5-tuple unpacked, ledger records provider_used=claude_cowork
  5.  Fallback fires when cowork fails and fallback_enabled=True
  6.  No fallback when cowork fails and fallback_enabled=False
  7.  Fallback blocked by Anthropic CB when both CBs open
  8.  is_available() False when cowork_enabled=True but no key
  9.  is_available() True when cowork_enabled=True and cowork key set
  10. is_available() True when cowork_enabled=True and anthropic key set (key fall-through)
  11. cowork_bridge_unavailable and cowork_cb_open do not trip Anthropic CB (_is_cb_failure)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

import pytest


# ── Test helpers ──────────────────────────────────────────────────────────────

def _settings(
    *,
    enabled: bool = True,
    api_key: str = "sk-ant-test-abc123",
    cowork_enabled: bool = False,
    cowork_key: str = "",
    fallback_enabled: bool = False,
    budget: float = 0.0,
) -> MagicMock:
    s = MagicMock()
    s.ai_parser_enabled                    = enabled
    s.anthropic_api_key                    = api_key
    s.ai_cowork_api_key                    = cowork_key or None
    s.ai_cowork_enabled                    = cowork_enabled
    s.ai_cowork_timeout_seconds            = 10
    s.ai_provider_preference               = "claude_cowork"
    s.ai_fallback_enabled                  = fallback_enabled
    s.ai_gateway_daily_budget_usd          = budget
    s.ai_gateway_timeout_seconds           = 10
    s.ai_gateway_max_retries               = 1
    s.ai_gateway_circuit_breaker_threshold = 5
    s.ai_gateway_circuit_breaker_reset_s   = 60
    s.storage_root                         = "/tmp/test_phase3"
    return s


def _mock_anthropic_response(text: str = "advisory text") -> MagicMock:
    resp = MagicMock()
    resp.content = [MagicMock(text=text)]
    resp.usage   = MagicMock(input_tokens=80, output_tokens=40)
    return resp


def _mock_ledger() -> MagicMock:
    ledger = MagicMock()
    ledger.get_daily_cost_usd.return_value = 0.0
    ledger.estimate_cost.return_value      = 0.0001
    ledger.estimate_tokens.return_value    = 50
    ledger.prompt_hash.return_value        = "testhash"
    return ledger


# ── Scenario 1: Cowork CB isolated from Anthropic CB ─────────────────────────

def test_anthropic_failures_do_not_open_cowork_cb():
    """N Anthropic failures must NOT open the Cowork circuit breaker."""
    from app.services import ai_gateway
    ai_gateway.reset_circuit_breaker()
    ai_gateway.reset_cowork_circuit_breaker()

    for _ in range(ai_gateway._CB_THRESHOLD):
        ai_gateway._cb_record_failure()

    assert ai_gateway._cb_is_open() is True
    # Cowork CB must still be closed
    assert ai_gateway._cowork_cb_is_open() is False

    ai_gateway.reset_circuit_breaker()
    ai_gateway.reset_cowork_circuit_breaker()


# ── Scenario 2: Anthropic CB isolated from Cowork CB ─────────────────────────

def test_cowork_failures_do_not_open_anthropic_cb():
    """N Cowork failures must NOT open the Anthropic circuit breaker."""
    from app.services import ai_gateway
    ai_gateway.reset_circuit_breaker()
    ai_gateway.reset_cowork_circuit_breaker()

    for _ in range(ai_gateway._CB_THRESHOLD):
        ai_gateway._cowork_cb_record_failure()

    assert ai_gateway._cowork_cb_is_open() is True
    # Anthropic CB must still be closed
    assert ai_gateway._cb_is_open() is False

    ai_gateway.reset_circuit_breaker()
    ai_gateway.reset_cowork_circuit_breaker()


# ── Scenario 3: Cowork CB blocks the cowork path ─────────────────────────────

def test_cowork_cb_open_returns_error_type():
    """_cowork_call() returns cowork_cb_open when cowork CB is open."""
    from app.services import ai_gateway
    ai_gateway.reset_cowork_circuit_breaker()

    # Force cowork CB open
    for _ in range(ai_gateway._CB_THRESHOLD):
        ai_gateway._cowork_cb_record_failure()

    assert ai_gateway._cowork_cb_is_open() is True

    ledger = _mock_ledger()
    raw, tok_in, tok_out, cost, err = ai_gateway._cowork_call(
        api_key="sk-ant-test-key",
        system="sys", user="usr",
        selected_model="claude-haiku-4-5-20251001",
        max_tokens=100, max_retries=0, timeout_s=10,
        ledger=ledger,
    )

    assert raw is None
    assert err == "cowork_cb_open"

    ai_gateway.reset_cowork_circuit_breaker()


# ── Scenario 4: Cowork path success, ledger records claude_cowork ─────────────

def test_cowork_success_records_provider_used():
    """When cowork succeeds, call() records provider_used=claude_cowork in ledger."""
    from app.services import ai_gateway
    ai_gateway.reset_circuit_breaker()
    ai_gateway.reset_cowork_circuit_breaker()

    fake_settings = _settings(
        cowork_enabled=True, cowork_key="sk-ant-cowork-key",
        api_key="sk-ant-anthropic-key",
    )
    config_mod = MagicMock(); config_mod.settings = fake_settings

    mock_client_instance = MagicMock()
    mock_client_instance.messages.create.return_value = _mock_anthropic_response("cowork answer")
    mock_anthropic_cls = MagicMock(return_value=mock_client_instance)
    mock_anthropic_mod = MagicMock()
    mock_anthropic_mod.Anthropic = mock_anthropic_cls

    mock_redactor = MagicMock()
    mock_redactor.redact_pair.side_effect = lambda s, u: (s, u)

    with patch.dict("sys.modules", {
        "app.core.config": config_mod,
        "anthropic": mock_anthropic_mod,
        "app.services.ai_redactor": mock_redactor,
    }), \
    patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=0.0), \
    patch("app.services.ai_call_ledger.record") as mock_record, \
    patch("app.services.ai_call_ledger.estimate_tokens", return_value=50), \
    patch("app.services.ai_call_ledger.estimate_cost", return_value=0.0001), \
    patch("app.services.ai_call_ledger.prompt_hash", return_value="testhash"):
        result = ai_gateway.call(
            system="sys", user="usr",
            task_type="test", service_name="test_svc",
        )

    assert result == "cowork answer"
    # Verify ledger.record was called with provider_used=claude_cowork
    assert mock_record.called
    record_args = mock_record.call_args[0][0]
    assert record_args["provider_used"] == "claude_cowork"
    assert record_args["fallback_used"] is False
    assert record_args["success"] is True

    ai_gateway.reset_circuit_breaker()
    ai_gateway.reset_cowork_circuit_breaker()


# ── Scenario 5: Fallback fires when cowork fails and fallback_enabled=True ────

def test_fallback_fires_when_cowork_fails():
    """When cowork fails and fallback_enabled=True, Anthropic fallback is attempted."""
    from app.services import ai_gateway
    ai_gateway.reset_circuit_breaker()
    ai_gateway.reset_cowork_circuit_breaker()

    fake_settings = _settings(
        cowork_enabled=True, cowork_key="sk-ant-cowork-key",
        api_key="sk-ant-fallback-key", fallback_enabled=True,
    )
    config_mod = MagicMock(); config_mod.settings = fake_settings

    # First call (cowork): raises an exception → triggers cowork failure
    mock_client_cowork = MagicMock()
    mock_client_cowork.messages.create.side_effect = Exception("cowork api error")

    # Second call (fallback): succeeds
    mock_client_fallback = MagicMock()
    mock_client_fallback.messages.create.return_value = _mock_anthropic_response("fallback answer")

    # Same Anthropic() constructor is called for both — return different clients
    mock_anthropic_cls = MagicMock(side_effect=[mock_client_cowork, mock_client_fallback])
    mock_anthropic_mod = MagicMock()
    mock_anthropic_mod.Anthropic = mock_anthropic_cls

    mock_redactor = MagicMock()
    mock_redactor.redact_pair.side_effect = lambda s, u: (s, u)

    with patch.dict("sys.modules", {
        "app.core.config": config_mod,
        "anthropic": mock_anthropic_mod,
        "app.services.ai_redactor": mock_redactor,
    }), \
    patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=0.0), \
    patch("app.services.ai_call_ledger.record") as mock_record, \
    patch("app.services.ai_call_ledger.estimate_tokens", return_value=50), \
    patch("app.services.ai_call_ledger.estimate_cost", return_value=0.0001), \
    patch("app.services.ai_call_ledger.prompt_hash", return_value="testhash"):
        result = ai_gateway.call(
            system="sys", user="usr",
            task_type="test", service_name="test_svc",
        )

    assert result == "fallback answer"
    # fallback_used must be True
    record_args = mock_record.call_args[0][0]
    assert record_args["fallback_used"] is True
    assert record_args["provider_used"] == "anthropic_api"

    ai_gateway.reset_circuit_breaker()
    ai_gateway.reset_cowork_circuit_breaker()


# ── Scenario 6: No fallback when cowork fails and fallback_enabled=False ──────

def test_no_fallback_when_disabled():
    """When cowork fails and fallback_enabled=False, result is None (no Anthropic call)."""
    from app.services import ai_gateway
    ai_gateway.reset_circuit_breaker()
    ai_gateway.reset_cowork_circuit_breaker()

    fake_settings = _settings(
        cowork_enabled=True, cowork_key="sk-ant-cowork-key",
        api_key="sk-ant-fallback-key", fallback_enabled=False,
    )
    config_mod = MagicMock(); config_mod.settings = fake_settings

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("cowork api error")
    mock_anthropic_cls = MagicMock(return_value=mock_client)
    mock_anthropic_mod = MagicMock()
    mock_anthropic_mod.Anthropic = mock_anthropic_cls

    ledger = _mock_ledger()
    mock_redactor = MagicMock()
    mock_redactor.redact_pair.side_effect = lambda s, u: (s, u)

    with patch.dict("sys.modules", {
        "app.core.config": config_mod,
        "anthropic": mock_anthropic_mod,
        "app.services.ai_call_ledger": ledger,
        "app.services.ai_redactor": mock_redactor,
    }):
        result = ai_gateway.call(
            system="sys", user="usr",
            task_type="test", service_name="test_svc",
        )

    assert result is None

    ai_gateway.reset_circuit_breaker()
    ai_gateway.reset_cowork_circuit_breaker()


# ── Scenario 7: Fallback blocked when Anthropic CB is also open ───────────────

def test_fallback_blocked_when_anthropic_cb_open():
    """Even with fallback_enabled=True, if Anthropic CB is open, fallback must be blocked."""
    from app.services import ai_gateway
    ai_gateway.reset_circuit_breaker()
    ai_gateway.reset_cowork_circuit_breaker()

    # Open Anthropic CB
    for _ in range(ai_gateway._CB_THRESHOLD):
        ai_gateway._cb_record_failure()
    assert ai_gateway._cb_is_open() is True

    fake_settings = _settings(
        cowork_enabled=True, cowork_key="sk-ant-cowork-key",
        api_key="sk-ant-fallback-key", fallback_enabled=True,
    )
    config_mod = MagicMock(); config_mod.settings = fake_settings

    # Cowork client fails (so fallback path would be tried)
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("cowork down")
    mock_anthropic_cls = MagicMock(return_value=mock_client)
    mock_anthropic_mod = MagicMock()
    mock_anthropic_mod.Anthropic = mock_anthropic_cls

    mock_redactor = MagicMock()
    mock_redactor.redact_pair.side_effect = lambda s, u: (s, u)

    with patch.dict("sys.modules", {
        "app.core.config": config_mod,
        "anthropic": mock_anthropic_mod,
        "app.services.ai_redactor": mock_redactor,
    }), \
    patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=0.0), \
    patch("app.services.ai_call_ledger.record") as mock_record, \
    patch("app.services.ai_call_ledger.estimate_tokens", return_value=50), \
    patch("app.services.ai_call_ledger.estimate_cost", return_value=0.0001), \
    patch("app.services.ai_call_ledger.prompt_hash", return_value="testhash"):
        result = ai_gateway.call(
            system="sys", user="usr",
            task_type="test", service_name="test_svc",
        )

    assert result is None
    record_args = mock_record.call_args[0][0]
    assert record_args["error_type"] == "anthropic_cb_open"

    ai_gateway.reset_circuit_breaker()
    ai_gateway.reset_cowork_circuit_breaker()


# ── Scenario 8: is_available() False when cowork_enabled but no key ───────────

def test_is_available_false_cowork_no_key():
    """is_available() must return False when ai_cowork_enabled=True but no key present."""
    from app.services import ai_gateway

    fake_settings = MagicMock()
    fake_settings.ai_parser_enabled  = True
    fake_settings.ai_cowork_enabled  = True
    fake_settings.ai_cowork_api_key  = None
    fake_settings.anthropic_api_key  = ""  # also empty — no fallback key

    config_mod = MagicMock(); config_mod.settings = fake_settings

    with patch.dict("sys.modules", {"app.core.config": config_mod}):
        result = ai_gateway.is_available()

    assert result is False


# ── Scenario 9: is_available() True when cowork key set ──────────────────────

def test_is_available_true_cowork_key_set():
    """is_available() must return True when ai_cowork_enabled=True and ai_cowork_api_key set."""
    from app.services import ai_gateway

    fake_settings = MagicMock()
    fake_settings.ai_parser_enabled  = True
    fake_settings.ai_cowork_enabled  = True
    fake_settings.ai_cowork_api_key  = "sk-ant-cowork-key-xyz"
    fake_settings.anthropic_api_key  = ""
    # Disable admin key health check (no admin key configured)
    fake_settings.anthropic_admin_api_key = ""
    fake_settings.anthropic_api_key_id    = ""

    config_mod = MagicMock(); config_mod.settings = fake_settings

    with patch.dict("sys.modules", {"app.core.config": config_mod}):
        result = ai_gateway.is_available()

    assert result is True


# ── Scenario 10: is_available() True via anthropic_api_key fallthrough ─────

def test_is_available_true_cowork_falls_through_to_anthropic_key():
    """is_available() must return True when cowork_enabled=True but only anthropic_api_key set."""
    from app.services import ai_gateway

    fake_settings = MagicMock()
    fake_settings.ai_parser_enabled  = True
    fake_settings.ai_cowork_enabled  = True
    fake_settings.ai_cowork_api_key  = None   # no dedicated cowork key
    fake_settings.anthropic_api_key  = "sk-ant-shared-key"
    fake_settings.anthropic_admin_api_key = ""
    fake_settings.anthropic_api_key_id    = ""

    config_mod = MagicMock(); config_mod.settings = fake_settings

    with patch.dict("sys.modules", {"app.core.config": config_mod}):
        result = ai_gateway.is_available()

    assert result is True


# ── Scenario 11: cowork logical gate errors do not trip Anthropic CB ──────────

def test_is_cb_failure_cowork_logical_gates():
    """cowork_bridge_unavailable and cowork_cb_open must NOT count as CB failures."""
    from app.services import ai_gateway

    assert ai_gateway._is_cb_failure("cowork_bridge_unavailable") is False
    assert ai_gateway._is_cb_failure("cowork_cb_open")            is False
    assert ai_gateway._is_cb_failure("cowork_not_implemented")    is False
    # But real cowork errors should count
    assert ai_gateway._is_cb_failure("cowork_timeout")            is True
    assert ai_gateway._is_cb_failure("cowork_result_error")       is True
    assert ai_gateway._is_cb_failure("cowork_malformed_result")   is True
