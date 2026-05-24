"""
test_phase2_advisory_llm.py -- Phase 2 advisory LLM service tests.

Validates:
  1. Feature flag gate: flag OFF -> deterministic path, llm_used=False
  2. Feature flag gate: flag ON + gateway returns text -> llm_used=True
  3. Gateway failure (None return) -> falls back to deterministic, llm_used=False
  4. Gateway exception -> falls back to deterministic, llm_used=False
  5. Advisory budget exhausted -> skips LLM path, deterministic fallback
  6. Cache: second call within TTL returns cached result, no second LLM call
  7. Cache: separate cache key per (batch_id, llm_enabled) state
  8. /status endpoint returns correct flag state
  9. /status endpoint reflects budget and gateway state
 10. Source-grep: ai_advisory.py calls ai_gateway, not anthropic directly
 11. Source-grep: routes_ai_advisory.py has no write verbs
 12. Source-grep: ai_advisory.py contains no forbidden write symbols (Phase 2 extension)
 13. response shape: Phase 2 result always includes generated_at, model_used, source
 14. response shape: llm_used=False result has model_used=None
 15. response shape: llm_used=True result has model_used set to model id
 16. Deterministic synthesise_explanation() still works unchanged
 17. Timeout / slow gateway: falls back gracefully (gateway returns None on timeout)
 18. Empty LLM response (whitespace): falls back to deterministic
 19. ai_advisory_llm_enabled=True but api key missing (gateway returns None): fallback
 20. advisory_class stays "R" in both LLM and deterministic paths
 21. No anthropic import in ai_advisory.py (gateway violation test)
 22. Budget guard: _advisory_budget_ok() returns False when spent >= budget
 23. Budget guard: _advisory_budget_ok() returns True when budget=0 (unlimited)
 24. Cache clear helper works
 25. /status endpoint is read-only (no write verbs in routes source)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ── Path constants ─────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE   = REPO_ROOT / "service" / "app"
ADVISORY_SERVICE_PATH = SERVICE / "services" / "ai_advisory.py"
ADVISORY_ROUTE_PATH   = SERVICE / "api" / "routes_ai_advisory.py"


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_readiness(*, blocked: bool = False) -> Dict[str, Any]:
    if blocked:
        return {
            "batch_id":  "BATCH_BLOCKED",
            "warehouse": {"status": "empty",   "ready": False, "message": "not scanned"},
            "sales":     {"status": "clean",   "ready": True,  "message": "linked"},
            "wfirma":    {"status": "blocked", "ready": False, "message": "customer auth gap"},
            "dhl":       {"status": "waiting", "ready": False, "sla_breach": False, "message": "awaiting SAD"},
            "overall":   {
                "ready_for_closure": False,
                "blocked_domains":   ["warehouse", "wfirma", "dhl"],
                "next_step":         "scan items into warehouse",
            },
        }
    return {
        "batch_id":  "BATCH_OK",
        "warehouse": {"status": "clean",   "ready": True,  "message": "all scanned"},
        "sales":     {"status": "clean",   "ready": True,  "message": "linked"},
        "wfirma":    {"status": "ready",   "ready": True,  "message": "ready"},
        "dhl":       {"status": "cleared", "ready": True,  "sla_breach": False, "message": "cleared"},
        "overall":   {"ready_for_closure": True, "blocked_domains": [], "next_step": "closure"},
    }


def _make_settings(*, llm_enabled: bool = False, budget: float = 1.0,
                   api_key: str = "sk-ant-test", ai_parser_enabled: bool = True) -> MagicMock:
    s = MagicMock()
    s.ai_advisory_llm_enabled        = llm_enabled
    s.ai_advisory_model               = "claude-haiku-4-5-20251001"
    s.ai_advisory_max_tokens_per_call = 500
    s.ai_advisory_budget_usd_per_day  = budget
    s.ai_advisory_cache_ttl_seconds   = 0   # disable cache by default in tests
    s.ai_parser_enabled               = ai_parser_enabled
    s.anthropic_api_key               = api_key
    s.api_key                         = ""  # dev mode auth bypass
    return s


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    from app.main import app
    return __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app)


# ── Helper ─────────────────────────────────────────────────────────────────────

def _stub(monkeypatch, *, readiness_blocked=False, llm_enabled=False,
          gateway_returns="LLM explanation text.", budget=1.0):
    """Patch readiness, settings, gateway, and ledger for advisory tests."""
    from app.services import ai_advisory as adv

    monkeypatch.setattr(adv, "get_batch_readiness",
                        lambda _: _make_readiness(blocked=readiness_blocked))
    adv.cache_clear()

    fake_settings = _make_settings(llm_enabled=llm_enabled, budget=budget)
    monkeypatch.setattr("app.services.ai_advisory.settings", fake_settings, raising=False)

    # Patch the lazy import inside explain_workflow_blockers
    config_mod = MagicMock()
    config_mod.settings = fake_settings

    mock_gw = MagicMock()
    mock_gw.call.return_value = gateway_returns

    mock_ledger = MagicMock()
    mock_ledger.get_daily_cost_usd.return_value = 0.0

    return fake_settings, mock_gw, mock_ledger, config_mod


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Feature flag OFF -> deterministic path
# ═══════════════════════════════════════════════════════════════════════════════

def test_flag_off_returns_deterministic_result(monkeypatch):
    from app.services import ai_advisory as adv
    adv.cache_clear()
    monkeypatch.setattr(adv, "get_batch_readiness", lambda _: _make_readiness(blocked=True))

    fake_s = _make_settings(llm_enabled=False)
    mock_gw = MagicMock()

    import importlib, sys
    with patch.dict(sys.modules, {"app.core.config": MagicMock(settings=fake_s)}):
        with patch("app.services.ai_advisory.ai_gateway", mock_gw, create=True):
            result = adv.explain_workflow_blockers("BATCH_BLOCKED")

    assert result["llm_used"] is False
    assert result["model_used"] is None
    assert result["source"] == "batch_readiness"
    assert result["advisory_class"] == "R"
    mock_gw.call.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Feature flag ON + gateway returns text -> llm_used=True
# ═══════════════════════════════════════════════════════════════════════════════

def test_flag_on_gateway_success_returns_llm_result(monkeypatch):
    from app.services import ai_advisory as adv
    adv.cache_clear()
    monkeypatch.setattr(adv, "get_batch_readiness", lambda _: _make_readiness(blocked=True))

    fake_s = _make_settings(llm_enabled=True)
    mock_gw = MagicMock()
    mock_gw.call.return_value = "LLM says: resolve customer gaps in wFirma."
    mock_ledger = MagicMock()
    mock_ledger.get_daily_cost_usd.return_value = 0.01

    import sys
    with patch.dict(sys.modules, {
        "app.core.config": MagicMock(settings=fake_s),
        "app.services.ai_call_ledger": mock_ledger,
    }):
        with patch("app.services.ai_advisory.ai_gateway", mock_gw, create=True):
            with patch("app.services.ai_advisory._advisory_budget_ok", return_value=True):
                result = adv.explain_workflow_blockers("BATCH_BLOCKED")

    assert result["llm_used"] is True
    assert result["model_used"] == "claude-haiku-4-5-20251001"
    assert result["source"] == "batch_readiness+llm"
    assert result["summary"] == "LLM says: resolve customer gaps in wFirma."
    assert result["advisory_class"] == "R"
    mock_gw.call.assert_called_once()
    call_kwargs = mock_gw.call.call_args[1]
    assert call_kwargs["task_type"] == "advisory_explanation"
    assert call_kwargs["service_name"] == "ai_advisory"
    assert call_kwargs["object_id"] == "BATCH_BLOCKED"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Gateway returns None -> deterministic fallback
# ═══════════════════════════════════════════════════════════════════════════════

def test_gateway_none_falls_back_to_deterministic(monkeypatch):
    from app.services import ai_advisory as adv
    adv.cache_clear()
    monkeypatch.setattr(adv, "get_batch_readiness", lambda _: _make_readiness(blocked=True))

    fake_s = _make_settings(llm_enabled=True)
    mock_gw = MagicMock()
    mock_gw.call.return_value = None  # gateway unavailable / CB open / key missing

    import sys
    with patch.dict(sys.modules, {"app.core.config": MagicMock(settings=fake_s)}):
        with patch("app.services.ai_advisory.ai_gateway", mock_gw, create=True):
            with patch("app.services.ai_advisory._advisory_budget_ok", return_value=True):
                result = adv.explain_workflow_blockers("BATCH_BLOCKED")

    assert result["llm_used"] is False
    assert result["model_used"] is None
    assert result["source"] == "batch_readiness"
    assert "BATCH_BLOCKED" in result["summary"]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Gateway raises exception -> deterministic fallback
# ═══════════════════════════════════════════════════════════════════════════════

def test_gateway_exception_falls_back_to_deterministic(monkeypatch):
    from app.services import ai_advisory as adv
    adv.cache_clear()
    monkeypatch.setattr(adv, "get_batch_readiness", lambda _: _make_readiness(blocked=False))

    fake_s = _make_settings(llm_enabled=True)
    mock_gw = MagicMock()
    mock_gw.call.side_effect = RuntimeError("simulated gateway crash")

    import sys
    with patch.dict(sys.modules, {"app.core.config": MagicMock(settings=fake_s)}):
        with patch("app.services.ai_advisory.ai_gateway", mock_gw, create=True):
            with patch("app.services.ai_advisory._advisory_budget_ok", return_value=True):
                result = adv.explain_workflow_blockers("BATCH_OK")

    assert result["llm_used"] is False
    assert result["source"] == "batch_readiness"
    assert "ready" in result["summary"].lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Budget exhausted -> skips LLM path
# ═══════════════════════════════════════════════════════════════════════════════

def test_budget_exhausted_skips_llm(monkeypatch):
    from app.services import ai_advisory as adv
    adv.cache_clear()
    monkeypatch.setattr(adv, "get_batch_readiness", lambda _: _make_readiness(blocked=True))

    fake_s = _make_settings(llm_enabled=True, budget=0.50)
    mock_gw = MagicMock()
    mock_gw.call.return_value = "LLM text"

    # Patch the method on the real module (not via sys.modules) so that
    # `from . import ai_call_ledger as ledger` inside _advisory_budget_ok()
    # picks up the patched value through the real package attribute.
    import sys
    with patch.dict(sys.modules, {"app.core.config": MagicMock(settings=fake_s)}):
        with patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=0.99):
            with patch("app.services.ai_advisory.ai_gateway", mock_gw, create=True):
                result = adv.explain_workflow_blockers("BATCH_BLOCKED")

    assert result["llm_used"] is False
    mock_gw.call.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Cache: second call within TTL returns cached result
# ═══════════════════════════════════════════════════════════════════════════════

def test_cache_second_call_returns_cached_no_llm_call(monkeypatch):
    from app.services import ai_advisory as adv
    adv.cache_clear()

    call_count = []
    monkeypatch.setattr(adv, "get_batch_readiness",
                        lambda _: (call_count.append(1), _make_readiness())[1])

    fake_s = _make_settings(llm_enabled=True)
    fake_s.ai_advisory_cache_ttl_seconds = 300  # cache enabled
    mock_gw = MagicMock()
    mock_gw.call.return_value = "cached LLM text"

    import sys
    with patch.dict(sys.modules, {"app.core.config": MagicMock(settings=fake_s)}):
        with patch("app.services.ai_advisory.ai_gateway", mock_gw, create=True):
            with patch("app.services.ai_advisory._advisory_budget_ok", return_value=True):
                r1 = adv.explain_workflow_blockers("BATCH_CACHE")
                r2 = adv.explain_workflow_blockers("BATCH_CACHE")

    assert r1["summary"] == r2["summary"]
    assert mock_gw.call.call_count == 1  # LLM called once only
    assert len(call_count) == 1          # readiness loaded once only


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Cache key includes llm_enabled state
# ═══════════════════════════════════════════════════════════════════════════════

def test_cache_key_differs_by_llm_flag(monkeypatch):
    from app.services import ai_advisory as adv
    adv.cache_clear()
    monkeypatch.setattr(adv, "get_batch_readiness", lambda _: _make_readiness(blocked=True))

    import sys
    mock_gw = MagicMock()
    mock_gw.call.return_value = "LLM result"

    fake_s_off = _make_settings(llm_enabled=False)
    fake_s_off.ai_advisory_cache_ttl_seconds = 300
    with patch.dict(sys.modules, {"app.core.config": MagicMock(settings=fake_s_off)}):
        with patch("app.services.ai_advisory.ai_gateway", mock_gw, create=True):
            r_off = adv.explain_workflow_blockers("BATCH_X")

    fake_s_on = _make_settings(llm_enabled=True)
    fake_s_on.ai_advisory_cache_ttl_seconds = 300
    with patch.dict(sys.modules, {"app.core.config": MagicMock(settings=fake_s_on)}):
        with patch("app.services.ai_advisory.ai_gateway", mock_gw, create=True):
            with patch("app.services.ai_advisory._advisory_budget_ok", return_value=True):
                r_on = adv.explain_workflow_blockers("BATCH_X")

    # Both cached independently -- sources differ
    assert r_off["source"] == "batch_readiness"
    assert r_on["source"] == "batch_readiness+llm"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. /status endpoint: flag state reflected
# ═══════════════════════════════════════════════════════════════════════════════

def test_status_endpoint_reflects_flag_state(client, monkeypatch):
    from app.core import config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings, "ai_advisory_llm_enabled", True, raising=False)
    monkeypatch.setattr(cfg_mod.settings, "ai_advisory_model", "claude-haiku-4-5-20251001", raising=False)
    monkeypatch.setattr(cfg_mod.settings, "ai_advisory_budget_usd_per_day", 2.0, raising=False)

    r = client.get("/api/v1/ai/advisory/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["ai_advisory_llm_enabled"] is True
    assert body["model"] == "claude-haiku-4-5-20251001"
    assert body["budget_usd_per_day"] == 2.0
    assert "generated_at" in body


# ═══════════════════════════════════════════════════════════════════════════════
# 9. /status endpoint: default flags show disabled
# ═══════════════════════════════════════════════════════════════════════════════

def test_status_endpoint_default_flags_disabled(client, monkeypatch):
    from app.core import config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings, "ai_advisory_llm_enabled", False, raising=False)

    r = client.get("/api/v1/ai/advisory/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ai_advisory_llm_enabled"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Source-grep: ai_advisory.py calls ai_gateway, not anthropic directly
# ═══════════════════════════════════════════════════════════════════════════════

def test_advisory_service_does_not_import_anthropic_directly():
    src = ADVISORY_SERVICE_PATH.read_text(encoding="utf-8")
    assert "import anthropic" not in src, (
        "ai_advisory.py must not import anthropic directly. "
        "All AI calls must route through ai_gateway.call(). "
        "Gateway-violation rule (ai_gateway.py FORBIDDEN comment)."
    )


def test_advisory_service_calls_ai_gateway_for_llm():
    src = ADVISORY_SERVICE_PATH.read_text(encoding="utf-8")
    assert "ai_gateway" in src, (
        "ai_advisory.py Phase 2 must import and call ai_gateway for LLM path."
    )
    assert "gw.call(" in src, (
        "ai_advisory.py must use gw.call() (ai_gateway) for LLM synthesis."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Source-grep: routes_ai_advisory.py has no write verbs
# ═══════════════════════════════════════════════════════════════════════════════

def test_routes_advisory_no_write_verbs():
    import ast
    src = ADVISORY_ROUTE_PATH.read_text(encoding="utf-8")
    for verb in ("router.post", "router.put", "router.delete", "router.patch"):
        assert verb not in src, (
            f"routes_ai_advisory.py declares @{verb} -- advisory class R is read-only"
        )
    assert "router.get" in src


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Source-grep: no forbidden symbols in Phase 2 advisory service
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("forbidden", [
    "wfirma_writer",
    "wfirma_create",
    "queue_email",
    "smtplib",
    "execute_action",
    "dhl_send",
    "dhl_orchestrator",
    "process_batch",
    "INSERT INTO",
    "DELETE FROM",
    "UPDATE ",
    ".commit(",
    ".write_text(",
])
def test_advisory_service_phase2_no_forbidden_symbols(forbidden: str):
    import ast
    src = ADVISORY_SERVICE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    # Strip docstrings (same technique as test_ai_advisory_no_writes.py)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef,
                              ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    executable = ast.unparse(tree)
    assert forbidden not in executable, (
        f"ai_advisory.py references forbidden symbol {forbidden!r} in Phase 2"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Response shape: Phase 2 result always includes generated_at, model_used, source
# ═══════════════════════════════════════════════════════════════════════════════

def test_result_shape_includes_phase2_fields(monkeypatch):
    from app.services import ai_advisory as adv
    adv.cache_clear()
    monkeypatch.setattr(adv, "get_batch_readiness", lambda _: _make_readiness())

    import sys
    fake_s = _make_settings(llm_enabled=False)
    with patch.dict(sys.modules, {"app.core.config": MagicMock(settings=fake_s)}):
        result = adv.explain_workflow_blockers("BATCH_SHAPE")

    for field in ("batch_id", "ready_for_closure", "blocked_domains", "next_step",
                  "blockers", "summary", "advisory_class", "source",
                  "llm_used", "model_used", "generated_at"):
        assert field in result, f"Phase 2 result missing field: {field!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# 14. model_used is None when llm_used=False
# ═══════════════════════════════════════════════════════════════════════════════

def test_model_used_is_none_when_deterministic(monkeypatch):
    from app.services import ai_advisory as adv
    adv.cache_clear()
    monkeypatch.setattr(adv, "get_batch_readiness", lambda _: _make_readiness())

    import sys
    fake_s = _make_settings(llm_enabled=False)
    with patch.dict(sys.modules, {"app.core.config": MagicMock(settings=fake_s)}):
        result = adv.explain_workflow_blockers("BATCH_MODEL_NONE")

    assert result["llm_used"] is False
    assert result["model_used"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# 15. model_used is set when llm_used=True
# ═══════════════════════════════════════════════════════════════════════════════

def test_model_used_set_when_llm_path_succeeds(monkeypatch):
    from app.services import ai_advisory as adv
    adv.cache_clear()
    monkeypatch.setattr(adv, "get_batch_readiness", lambda _: _make_readiness())

    fake_s = _make_settings(llm_enabled=True)
    mock_gw = MagicMock()
    mock_gw.call.return_value = "LLM output"

    import sys
    with patch.dict(sys.modules, {"app.core.config": MagicMock(settings=fake_s)}):
        with patch("app.services.ai_advisory.ai_gateway", mock_gw, create=True):
            with patch("app.services.ai_advisory._advisory_budget_ok", return_value=True):
                result = adv.explain_workflow_blockers("BATCH_MODEL_SET")

    assert result["llm_used"] is True
    assert result["model_used"] == "claude-haiku-4-5-20251001"


# ═══════════════════════════════════════════════════════════════════════════════
# 16. Deterministic synthesise_explanation() still works unchanged
# ═══════════════════════════════════════════════════════════════════════════════

def test_synthesise_explanation_deterministic_ready():
    from app.services.ai_advisory import synthesise_explanation
    result = synthesise_explanation(
        batch_id="B1",
        ready_for_closure=True,
        blockers=[],
        next_step="closure",
    )
    assert "B1" in result
    assert "ready" in result.lower()


def test_synthesise_explanation_deterministic_blocked():
    from app.services.ai_advisory import synthesise_explanation
    blockers = [
        {"domain": "warehouse", "status": "empty", "message": "not scanned",
         "why": "nothing scanned", "what_unblocks_it": "scan items"},
    ]
    result = synthesise_explanation(
        batch_id="B2",
        ready_for_closure=False,
        blockers=blockers,
        next_step="scan warehouse",
    )
    assert "B2" in result
    assert "warehouse" in result
    assert "Next step" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 17. Empty LLM response (whitespace) -> fallback to deterministic
# ═══════════════════════════════════════════════════════════════════════════════

def test_empty_llm_response_falls_back(monkeypatch):
    from app.services import ai_advisory as adv
    adv.cache_clear()
    monkeypatch.setattr(adv, "get_batch_readiness", lambda _: _make_readiness())

    fake_s = _make_settings(llm_enabled=True)
    mock_gw = MagicMock()
    mock_gw.call.return_value = "   "  # whitespace only

    import sys
    with patch.dict(sys.modules, {"app.core.config": MagicMock(settings=fake_s)}):
        with patch("app.services.ai_advisory.ai_gateway", mock_gw, create=True):
            with patch("app.services.ai_advisory._advisory_budget_ok", return_value=True):
                result = adv.explain_workflow_blockers("BATCH_EMPTY_LLM")

    assert result["llm_used"] is False
    assert result["source"] == "batch_readiness"


# ═══════════════════════════════════════════════════════════════════════════════
# 18. advisory_class stays "R" in both paths
# ═══════════════════════════════════════════════════════════════════════════════

def test_advisory_class_r_in_deterministic_path(monkeypatch):
    from app.services import ai_advisory as adv
    adv.cache_clear()
    monkeypatch.setattr(adv, "get_batch_readiness", lambda _: _make_readiness())

    import sys
    fake_s = _make_settings(llm_enabled=False)
    with patch.dict(sys.modules, {"app.core.config": MagicMock(settings=fake_s)}):
        result = adv.explain_workflow_blockers("BATCH_CLASS_R")

    assert result["advisory_class"] == "R"


def test_advisory_class_r_in_llm_path(monkeypatch):
    from app.services import ai_advisory as adv
    adv.cache_clear()
    monkeypatch.setattr(adv, "get_batch_readiness", lambda _: _make_readiness())

    fake_s = _make_settings(llm_enabled=True)
    mock_gw = MagicMock()
    mock_gw.call.return_value = "LLM output"

    import sys
    with patch.dict(sys.modules, {"app.core.config": MagicMock(settings=fake_s)}):
        with patch("app.services.ai_advisory.ai_gateway", mock_gw, create=True):
            with patch("app.services.ai_advisory._advisory_budget_ok", return_value=True):
                result = adv.explain_workflow_blockers("BATCH_CLASS_R_LLM")

    assert result["advisory_class"] == "R"


# ═══════════════════════════════════════════════════════════════════════════════
# 19. _advisory_budget_ok: returns False when spent >= budget
# ═══════════════════════════════════════════════════════════════════════════════

def test_budget_ok_false_when_spent_exceeds_budget(monkeypatch):
    """_advisory_budget_ok returns False when spent (0.75) exceeds budget (0.50)."""
    import sys
    from app.services import ai_advisory as adv

    fake_s = MagicMock()
    fake_s.ai_advisory_budget_usd_per_day = 0.50

    # Patch the ledger function on the already-imported real module so that
    # `from . import ai_call_ledger` inside _advisory_budget_ok gets the real
    # module but with get_daily_cost_usd replaced.
    with patch.dict(sys.modules, {"app.core.config": MagicMock(settings=fake_s)}):
        with patch("app.services.ai_call_ledger.get_daily_cost_usd", return_value=0.75):
            result = adv._advisory_budget_ok()
    assert result is False


def test_budget_ok_true_when_budget_is_zero(monkeypatch):
    """budget_usd_per_day=0 means unlimited — short-circuits before reading ledger."""
    import sys
    from app.services import ai_advisory as adv

    fake_s = MagicMock()
    fake_s.ai_advisory_budget_usd_per_day = 0  # unlimited

    # When budget <= 0, _advisory_budget_ok returns True without touching ledger.
    with patch.dict(sys.modules, {"app.core.config": MagicMock(settings=fake_s)}):
        result = adv._advisory_budget_ok()
    assert result is True


# ═══════════════════════════════════════════════════════════════════════════════
# 20. cache_clear helper empties cache
# ═══════════════════════════════════════════════════════════════════════════════

def test_cache_clear_empties_cache(monkeypatch):
    from app.services import ai_advisory as adv
    adv.cache_clear()

    monkeypatch.setattr(adv, "get_batch_readiness", lambda _: _make_readiness())
    load_count = []
    orig = adv.get_batch_readiness

    def _counting(bid):
        load_count.append(bid)
        return _make_readiness()

    monkeypatch.setattr(adv, "get_batch_readiness", _counting)

    import sys
    fake_s = _make_settings(llm_enabled=False)
    fake_s.ai_advisory_cache_ttl_seconds = 300

    with patch.dict(sys.modules, {"app.core.config": MagicMock(settings=fake_s)}):
        adv.explain_workflow_blockers("BATCH_CLEAR")
        assert len(load_count) == 1  # loaded once
        adv.cache_clear()
        adv.explain_workflow_blockers("BATCH_CLEAR")
        assert len(load_count) == 2  # loaded again after clear


# ═══════════════════════════════════════════════════════════════════════════════
# 21. Route test: workflow-blockers endpoint returns Phase 2 fields
# ═══════════════════════════════════════════════════════════════════════════════

def test_route_returns_phase2_fields_on_success(client, monkeypatch):
    from app.services import ai_advisory as adv
    adv.cache_clear()
    monkeypatch.setattr(adv, "get_batch_readiness", lambda _: _make_readiness())

    r = client.get("/api/v1/ai/advisory/workflow-blockers/BATCH_ROUTE_P2")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "generated_at" in body
    assert "model_used" in body
    assert "source" in body
    assert "llm_used" in body
    assert body["llm_used"] is False  # flag off by default in test env


# ═══════════════════════════════════════════════════════════════════════════════
# 22. Route test: /status is accessible
# ═══════════════════════════════════════════════════════════════════════════════

def test_status_route_accessible(client):
    r = client.get("/api/v1/ai/advisory/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "ai_advisory_llm_enabled" in body
    assert "gateway_available" in body
    assert "spent_usd_today" in body
    assert "budget_ok" in body


# ═══════════════════════════════════════════════════════════════════════════════
# 23. Phase 1 regression: existing behavior unchanged when flag is off
# ═══════════════════════════════════════════════════════════════════════════════

def test_phase1_regression_ready_batch(client, monkeypatch):
    from app.services import ai_advisory as adv
    adv.cache_clear()
    monkeypatch.setattr(adv, "get_batch_readiness", lambda _: _make_readiness(blocked=False))

    r = client.get("/api/v1/ai/advisory/workflow-blockers/BATCH_P1_REG")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["ready_for_closure"] is True
    assert body["blocked_domains"] == []
    assert body["llm_used"] is False
    assert body["advisory_class"] == "R"
    assert "BATCH_P1_REG" in body["summary"]


def test_phase1_regression_blocked_batch(client, monkeypatch):
    from app.services import ai_advisory as adv
    adv.cache_clear()
    monkeypatch.setattr(adv, "get_batch_readiness", lambda _: _make_readiness(blocked=True))

    r = client.get("/api/v1/ai/advisory/workflow-blockers/BATCH_P1_BLK")
    assert r.status_code == 200
    body = r.json()
    assert body["ready_for_closure"] is False
    assert len(body["blocked_domains"]) == 3
    assert body["llm_used"] is False
    for b in body["blockers"]:
        assert b["what_unblocks_it"]
        assert b["why"]


def test_phase1_regression_readiness_failure_returns_503(client, monkeypatch):
    from app.services import ai_advisory as adv
    adv.cache_clear()
    monkeypatch.setattr(adv, "get_batch_readiness",
                        lambda _: (_ for _ in ()).throw(RuntimeError("simulated")))

    r = client.get("/api/v1/ai/advisory/workflow-blockers/BATCH_FAIL")
    assert r.status_code == 503
    assert r.json()["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 24. gateway call params: correct task_type and complexity
# ═══════════════════════════════════════════════════════════════════════════════

def test_gateway_call_params_are_advisory_class(monkeypatch):
    from app.services import ai_advisory as adv
    adv.cache_clear()
    monkeypatch.setattr(adv, "get_batch_readiness", lambda _: _make_readiness(blocked=True))

    captured = {}
    def _mock_call(**kwargs):
        captured.update(kwargs)
        return "explanation from LLM"

    fake_s = _make_settings(llm_enabled=True)
    mock_gw = MagicMock()
    mock_gw.call.side_effect = _mock_call

    import sys
    with patch.dict(sys.modules, {"app.core.config": MagicMock(settings=fake_s)}):
        with patch("app.services.ai_advisory.ai_gateway", mock_gw, create=True):
            with patch("app.services.ai_advisory._advisory_budget_ok", return_value=True):
                adv.explain_workflow_blockers("BATCH_PARAMS")

    assert captured.get("task_type") == "advisory_explanation"
    assert captured.get("service_name") == "ai_advisory"
    assert captured.get("complexity") == "simple"
    assert captured.get("risk_level") == "low"
    assert captured.get("object_id") == "BATCH_PARAMS"


# ═══════════════════════════════════════════════════════════════════════════════
# 25. source field: "batch_readiness+llm" only when LLM succeeded
# ═══════════════════════════════════════════════════════════════════════════════

def test_source_field_correct_for_each_path(monkeypatch):
    from app.services import ai_advisory as adv
    adv.cache_clear()
    monkeypatch.setattr(adv, "get_batch_readiness", lambda _: _make_readiness())

    import sys

    # Deterministic path
    fake_s = _make_settings(llm_enabled=False)
    with patch.dict(sys.modules, {"app.core.config": MagicMock(settings=fake_s)}):
        r = adv.explain_workflow_blockers("BATCH_SRC_DET")
    assert r["source"] == "batch_readiness"
    adv.cache_clear()

    # LLM path (mocked success)
    fake_s2 = _make_settings(llm_enabled=True)
    mock_gw = MagicMock()
    mock_gw.call.return_value = "LLM text"
    with patch.dict(sys.modules, {"app.core.config": MagicMock(settings=fake_s2)}):
        with patch("app.services.ai_advisory.ai_gateway", mock_gw, create=True):
            with patch("app.services.ai_advisory._advisory_budget_ok", return_value=True):
                r2 = adv.explain_workflow_blockers("BATCH_SRC_LLM")
    assert r2["source"] == "batch_readiness+llm"
