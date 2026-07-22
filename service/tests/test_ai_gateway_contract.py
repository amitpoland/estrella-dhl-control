"""
test_ai_gateway_contract.py — Gateway call contract, model selection,
circuit breaker, budget enforcement, and disabled-config behaviour.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _settings(enabled=True, api_key="sk-test-key-abc123456789", budget=0.0):
    s = MagicMock()
    s.ai_parser_enabled           = enabled
    s.anthropic_api_key           = api_key
    s.ai_gateway_daily_budget_usd  = budget
    s.ai_gateway_timeout_seconds   = 30
    s.ai_gateway_max_retries       = 3
    # Phase 3: CB settings wired from config (must be int/float, not MagicMock)
    s.ai_gateway_circuit_breaker_threshold = 5
    s.ai_gateway_circuit_breaker_reset_s   = 60
    s.storage_root                 = "/tmp/test_storage"
    # Phase 2B fields — explicitly False so MagicMock doesn't return truthy objects
    s.ai_cowork_enabled           = False
    s.ai_cowork_timeout_seconds   = 30
    s.ai_provider_preference      = "claude_cowork"
    s.ai_fallback_enabled         = False
    # Phase 3: cowork key (None by default — tests that need it set it explicitly)
    s.ai_cowork_api_key           = None
    return s


def _mock_response(text: str):
    response = MagicMock()
    response.content = [MagicMock(text=text)]
    response.usage   = MagicMock(input_tokens=100, output_tokens=50)
    return response


# ── Gate: disabled config → None ─────────────────────────────────────────────

def test_call_returns_none_when_disabled():
    from app.services import ai_gateway
    ai_gateway.reset_circuit_breaker()

    fake_settings = _settings(enabled=False)
    config_mod = MagicMock(); config_mod.settings = fake_settings
    mock_anthropic_cls = MagicMock()

    with patch.dict("sys.modules", {"app.core.config": config_mod,
                                    "anthropic": MagicMock(Anthropic=mock_anthropic_cls)}):
        result = ai_gateway.call(system="s", user="u", task_type="test", service_name="test")

    assert result is None
    mock_anthropic_cls.assert_not_called()


def test_call_returns_none_when_no_api_key():
    from app.services import ai_gateway
    ai_gateway.reset_circuit_breaker()

    fake_settings = _settings(api_key="")
    config_mod = MagicMock(); config_mod.settings = fake_settings
    mock_anthropic_cls = MagicMock()

    with patch.dict("sys.modules", {"app.core.config": config_mod,
                                    "anthropic": MagicMock(Anthropic=mock_anthropic_cls)}):
        result = ai_gateway.call(system="s", user="u", task_type="test", service_name="test")

    assert result is None
    mock_anthropic_cls.assert_not_called()


def test_disabled_flag_beats_valid_api_key():
    from app.services import ai_gateway
    ai_gateway.reset_circuit_breaker()

    fake_settings = _settings(enabled=False, api_key="sk-valid-key-1234567890")
    config_mod = MagicMock(); config_mod.settings = fake_settings
    mock_anthropic_cls = MagicMock()

    with patch.dict("sys.modules", {"app.core.config": config_mod,
                                    "anthropic": MagicMock(Anthropic=mock_anthropic_cls)}):
        result = ai_gateway.call(system="s", user="u", task_type="test", service_name="test")

    assert result is None
    mock_anthropic_cls.assert_not_called()


# ── Successful call path ──────────────────────────────────────────────────────

def test_call_returns_model_response_text():
    from app.services import ai_gateway
    ai_gateway.reset_circuit_breaker()

    fake_settings = _settings()
    config_mod = MagicMock(); config_mod.settings = fake_settings

    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_response('{"result": "ok"}')
    mock_anthropic = MagicMock(
        Anthropic=MagicMock(return_value=mock_client),
        RateLimitError=Exception,
        APIStatusError=Exception,
    )

    # #798: patch the ledger/redactor FUNCTIONS the gateway calls, on their real
    # modules — not the modules themselves. The gateway imports both lazily
    # (`from . import ai_call_ledger as ledger` / `ai_redactor as redactor`), and
    # the autouse _isolate_ai_gateway fixture evicts those submodules per test.
    # Swapping the module (attribute- or sys.modules-patch) is defeated the moment
    # anything re-imports the submodule and re-sets the package attribute (the
    # hasattr shortcut then skips sys.modules). Patching the functions is
    # immune to that: patch re-imports the real module and replaces the callable
    # the gateway actually invokes. prompt_hash / estimate_* stay real (pure).
    # anthropic is mocked, so nothing reaches the live API or needs a key.
    with patch.dict("sys.modules", {"app.core.config": config_mod, "anthropic": mock_anthropic}):
        with patch("app.services.ai_call_ledger.record") as mock_record, \
             patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=0.0), \
             patch("app.services.ai_redactor.redact_pair", return_value=("system", "user")):
            result = ai_gateway.call(
                system="system", user="user",
                task_type="test_task", service_name="test_svc",
            )

    assert result == '{"result": "ok"}'
    mock_client.messages.create.assert_called_once()
    mock_record.assert_called_once()


# ── Model selection ───────────────────────────────────────────────────────────

def test_model_selection_simple_returns_haiku():
    from app.services.ai_gateway import _select_model, _MODEL_HAIKU
    model, reason, esc = _select_model(
        task_type="simple_check", complexity="simple",
        risk_level="low", confidence_score=0.9,
        operator_override=None,
    )
    assert model == _MODEL_HAIKU
    assert esc is None


def test_model_selection_moderate_returns_sonnet():
    from app.services.ai_gateway import _select_model, _MODEL_SONNET
    model, reason, esc = _select_model(
        task_type="customs_extraction", complexity="moderate",
        risk_level="medium", confidence_score=0.8,
        operator_override=None,
    )
    assert model == _MODEL_SONNET


def test_model_selection_complex_returns_opus():
    from app.services.ai_gateway import _select_model, _MODEL_OPUS
    model, reason, esc = _select_model(
        task_type="cross_domain_analysis", complexity="complex",
        risk_level="high", confidence_score=0.4,
        operator_override=None,
    )
    assert model == _MODEL_OPUS
    assert esc is not None


def test_model_selection_low_confidence_escalates_to_opus():
    from app.services.ai_gateway import _select_model, _MODEL_OPUS
    model, reason, esc = _select_model(
        task_type="any", complexity="moderate",
        risk_level="low", confidence_score=0.2,
        operator_override=None,
    )
    assert model == _MODEL_OPUS


def test_model_selection_operator_override_respected():
    from app.services.ai_gateway import _select_model, _MODEL_OPUS
    model, reason, esc = _select_model(
        task_type="simple", complexity="simple",
        risk_level="low", confidence_score=1.0,
        operator_override=_MODEL_OPUS,
    )
    assert model == _MODEL_OPUS
    assert "operator_override" in reason


def test_model_selection_haiku_escalates_on_low_confidence():
    from app.services.ai_gateway import _select_model, _MODEL_SONNET
    model, reason, esc = _select_model(
        task_type="simple_check", complexity="simple",
        risk_level="low", confidence_score=0.5,
        operator_override=None,
    )
    assert model == _MODEL_SONNET
    assert esc is not None


# ── Circuit breaker ───────────────────────────────────────────────────────────

def test_circuit_breaker_opens_after_threshold():
    from app.services import ai_gateway
    ai_gateway.reset_circuit_breaker()

    for _ in range(ai_gateway._CB_THRESHOLD):
        ai_gateway._cb_record_failure()

    assert ai_gateway._cb_is_open() is True


def test_circuit_breaker_resets_on_success():
    from app.services import ai_gateway
    ai_gateway.reset_circuit_breaker()

    for _ in range(ai_gateway._CB_THRESHOLD):
        ai_gateway._cb_record_failure()

    ai_gateway._cb_record_success()
    assert ai_gateway._cb_is_open() is False


def test_circuit_breaker_half_open_after_reset_period():
    from app.services import ai_gateway
    ai_gateway.reset_circuit_breaker()

    for _ in range(ai_gateway._CB_THRESHOLD):
        ai_gateway._cb_record_failure()

    # Manually backdate the open timestamp
    with ai_gateway._CB_LOCK:
        ai_gateway._cb_open_since = time.monotonic() - ai_gateway._CB_RESET_AFTER_S - 1

    assert ai_gateway._cb_is_open() is False  # half-open allows attempt


def test_call_blocked_when_circuit_open():
    from app.services import ai_gateway
    ai_gateway.reset_circuit_breaker()

    for _ in range(ai_gateway._CB_THRESHOLD):
        ai_gateway._cb_record_failure()

    fake_settings = _settings()
    config_mod = MagicMock(); config_mod.settings = fake_settings
    mock_anthropic_cls = MagicMock()

    with patch.dict("sys.modules", {"app.core.config": config_mod,
                                    "anthropic": MagicMock(Anthropic=mock_anthropic_cls)}):
        result = ai_gateway.call(system="s", user="u", task_type="test", service_name="test")

    assert result is None
    mock_anthropic_cls.assert_not_called()
    ai_gateway.reset_circuit_breaker()


# ── Budget enforcement ────────────────────────────────────────────────────────

def test_call_blocked_when_budget_exhausted():
    from app.services import ai_gateway
    ai_gateway.reset_circuit_breaker()

    fake_settings = _settings(budget=1.0)
    config_mod = MagicMock(); config_mod.settings = fake_settings
    mock_anthropic_cls = MagicMock()

    # #798: patch the ledger function on the real module (module-swap is fragile
    # here — see test_call_returns_model_response_text). Budget check runs before
    # the client is built, so no redactor/anthropic mock is reached.
    with patch.dict("sys.modules", {"app.core.config": config_mod,
                                    "anthropic": MagicMock(Anthropic=mock_anthropic_cls)}):
        with patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=1.5):  # over budget
            result = ai_gateway.call(system="s", user="u", task_type="test", service_name="test")

    assert result is None
    mock_anthropic_cls.assert_not_called()


def test_call_allowed_when_budget_zero_unlimited():
    from app.services import ai_gateway
    ai_gateway.reset_circuit_breaker()

    fake_settings = _settings(budget=0.0)  # 0 = unlimited
    config_mod = MagicMock(); config_mod.settings = fake_settings

    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_response("ok")
    mock_anthropic = MagicMock(
        Anthropic=MagicMock(return_value=mock_client),
        RateLimitError=Exception,
        APIStatusError=Exception,
    )

    # #798: function-patch on the real modules (module-swap is fragile here).
    # budget=0 means unlimited, so the 999.0 daily cost must NOT block.
    with patch.dict("sys.modules", {"app.core.config": config_mod, "anthropic": mock_anthropic}):
        with patch("app.services.ai_call_ledger.record"), \
             patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=999.0), \
             patch("app.services.ai_redactor.redact_pair", return_value=("s", "u")):
            result = ai_gateway.call(system="s", user="u", task_type="test", service_name="test")

    assert result == "ok"


# ── Ledger is written ─────────────────────────────────────────────────────────

def test_ledger_record_called_on_success():
    from app.services import ai_gateway
    ai_gateway.reset_circuit_breaker()

    fake_settings = _settings()
    config_mod = MagicMock(); config_mod.settings = fake_settings

    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_response("response text")
    mock_anthropic = MagicMock(
        Anthropic=MagicMock(return_value=mock_client),
        RateLimitError=Exception,
        APIStatusError=Exception,
    )

    # #798: function-patch on the real modules; assert on the patched record.
    with patch.dict("sys.modules", {"app.core.config": config_mod, "anthropic": mock_anthropic}):
        with patch("app.services.ai_call_ledger.record") as mock_record, \
             patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=0.0), \
             patch("app.services.ai_redactor.redact_pair", return_value=("s", "u")):
            ai_gateway.call(system="s", user="u", task_type="t", service_name="svc")

    mock_record.assert_called_once()
    entry = mock_record.call_args[0][0]
    assert entry["success"] is True
    assert entry["service"] == "svc"
    assert entry["task_type"] == "t"


def test_ledger_record_called_on_failure():
    from app.services import ai_gateway
    ai_gateway.reset_circuit_breaker()

    fake_settings = _settings()
    config_mod = MagicMock(); config_mod.settings = fake_settings

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("API down")
    mock_anthropic = MagicMock(
        Anthropic=MagicMock(return_value=mock_client),
        RateLimitError=ConnectionError,  # won't match Exception("API down")
        APIStatusError=ConnectionError,
    )

    # #798: function-patch on the real modules; the API call raises, so the
    # failure path must still record (success=False).
    with patch.dict("sys.modules", {"app.core.config": config_mod, "anthropic": mock_anthropic}):
        with patch("app.services.ai_call_ledger.record") as mock_record, \
             patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=0.0), \
             patch("app.services.ai_redactor.redact_pair", return_value=("s", "u")):
            result = ai_gateway.call(system="s", user="u", task_type="t", service_name="svc",
                                     max_tokens=100)

    assert result is None
    mock_record.assert_called_once()
    entry = mock_record.call_args[0][0]
    assert entry["success"] is False


# ── is_available() ────────────────────────────────────────────────────────────

def test_is_available_false_when_disabled():
    from app.services import ai_gateway
    fake = _settings(enabled=False, api_key="sk-key")
    config_mod = MagicMock(); config_mod.settings = fake
    with patch.dict("sys.modules", {"app.core.config": config_mod}):
        assert ai_gateway.is_available() is False


def test_is_available_false_when_no_key():
    from app.services import ai_gateway
    fake = _settings(enabled=True, api_key="")
    config_mod = MagicMock(); config_mod.settings = fake
    with patch.dict("sys.modules", {"app.core.config": config_mod}):
        assert ai_gateway.is_available() is False


def test_is_available_true_when_enabled_with_key():
    from app.services import ai_gateway
    fake = _settings(enabled=True, api_key="sk-live-key-123456")
    config_mod = MagicMock(); config_mod.settings = fake
    with patch.dict("sys.modules", {"app.core.config": config_mod}):
        assert ai_gateway.is_available() is True
