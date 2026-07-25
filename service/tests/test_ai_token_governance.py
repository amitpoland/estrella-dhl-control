"""
test_ai_token_governance.py — Token budget policy enforcement tests.

Enforces docs/ai-governance/token-budget-policy.md and api-fallback-policy.md.
All tests are source-grep or config-inspection only — no live API calls.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE = REPO_ROOT / "docs" / "ai-governance"


# ── 1. Governance documents exist ────────────────────────────────────────────

def test_token_budget_policy_exists() -> None:
    assert (GOVERNANCE / "token-budget-policy.md").exists()


def test_api_fallback_policy_exists() -> None:
    assert (GOVERNANCE / "api-fallback-policy.md").exists()


def test_token_budget_policy_contains_required_rules() -> None:
    txt = (GOVERNANCE / "token-budget-policy.md").read_text(encoding="utf-8")
    for marker in (
        "Rule 1", "Rule 2", "Rule 6", "Rule 7", "Rule 8", "Rule 9",
        "Rule 10", "Rule 11", "Rule 12",
        "ai_fallback_enabled",
        "ai_advisory_max_tokens_per_call",
        "ai_advisory_budget_usd_per_day",
    ):
        assert marker in txt, f"token-budget-policy.md missing: {marker!r}"


# ── 2. Config defaults — all AI features disabled out of the box ─────────────

@pytest.fixture()
def clean_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    # Set ANTHROPIC_API_KEY to empty string — pydantic-settings reads .env files
    # directly, so delenv() is insufficient; setenv("", ...) forces empty override.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    for key in ("AI_ADVISORY_LLM_ENABLED", "AI_FALLBACK_ENABLED", "AI_PARSER_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    from app.core.config import Settings
    return Settings()


def test_ai_parser_disabled_by_default(clean_settings) -> None:
    assert clean_settings.ai_parser_enabled is False


def test_ai_advisory_llm_disabled_by_default(clean_settings) -> None:
    assert clean_settings.ai_advisory_llm_enabled is False


def test_ai_fallback_disabled_by_default(clean_settings) -> None:
    assert clean_settings.ai_fallback_enabled is False


def test_anthropic_api_key_absent_by_default(clean_settings) -> None:
    assert not clean_settings.anthropic_api_key


# ── 3. Budget config fields are present with sane defaults ───────────────────

def test_max_tokens_per_call_default(clean_settings) -> None:
    assert clean_settings.ai_advisory_max_tokens_per_call == 1000


def test_budget_usd_per_day_default(clean_settings) -> None:
    assert clean_settings.ai_advisory_budget_usd_per_day == 1.0


def test_cache_ttl_default(clean_settings) -> None:
    assert clean_settings.ai_advisory_cache_ttl_seconds == 300


def test_advisory_model_default_is_haiku(clean_settings) -> None:
    # Haiku is mandatory for cost control; opus requires operator approval.
    assert "haiku" in clean_settings.ai_advisory_model.lower()


# ── 4. Advisory route remains read-only (belt + suspenders) ─────────────────

def test_advisory_route_still_no_write_verbs() -> None:
    import ast
    path = REPO_ROOT / "service" / "app" / "api" / "routes_ai_advisory.py"
    src = ast.unparse(ast.parse(path.read_text(encoding="utf-8")))
    for verb in ("router.post", "router.put", "router.delete", "router.patch"):
        assert verb not in src


# ── 5. Advisory service still has no write imports ───────────────────────────

def test_advisory_service_no_write_imports() -> None:
    import ast, io, tokenize
    path = REPO_ROOT / "service" / "app" / "services" / "ai_advisory.py"
    raw = path.read_text(encoding="utf-8")
    # Strip all string literals and comments so docstring prose doesn't trigger.
    tokens = tokenize.generate_tokens(io.StringIO(raw).readline)
    names = [t.string for t in tokens
             if t.type == tokenize.NAME]
    name_str = " ".join(names)
    for forbidden in ("execute_action", "queue_email", "wfirma_create"):
        assert forbidden not in name_str, (
            f"ai_advisory.py executable code references {forbidden!r}"
        )


# ── 6. llm_used stays False — Phase 1 deterministic contract ─────────────────

def test_phase1_advisory_result_llm_used_false(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    from app.services import ai_advisory as adv
    monkeypatch.setattr(adv, "get_batch_readiness", lambda _: {
        "batch_id": "B", "warehouse": {"status": "clean", "ready": True, "message": ""},
        "sales": {"status": "clean", "ready": True, "message": ""},
        "wfirma": {"status": "ready", "ready": True, "message": ""},
        "dhl": {"status": "ok", "ready": True, "sla_breach": False, "message": ""},
        "overall": {"ready_for_closure": True, "blocked_domains": [], "next_step": ""},
    })
    result = adv.explain_workflow_blockers("B")
    assert result["llm_used"] is False
    assert result["advisory_class"] == "R"


# ── 7. hardcoded max_tokens in ai_customs_parser must not exceed policy cap ──

def test_ai_customs_parser_max_tokens_within_policy() -> None:
    """
    ai_customs_parser.py has a hardcoded max_tokens call.
    Policy T3 hard stop is 4000 tokens.
    """
    path = REPO_ROOT / "service" / "app" / "services" / "ai_customs_parser.py"
    src = path.read_text(encoding="utf-8")
    import re
    # Find all max_tokens=<int> assignments
    vals = [int(m) for m in re.findall(r"max_tokens\s*=\s*(\d+)", src)]
    assert vals, "ai_customs_parser.py must declare max_tokens"
    for v in vals:
        assert v <= 4000, (
            f"ai_customs_parser max_tokens={v} exceeds policy T3 hard stop of 4000"
        )


# ── 8. Governance docs not referencing V1 frozen files as AI targets ─────────

def test_capability_map_does_not_target_frozen_v1() -> None:
    txt = (GOVERNANCE / "ai-capability-map.md").read_text(encoding="utf-8")
    # Locate only the Phase 1 additions table — lines between the
    # "Phase 1 additions" header and the next "---" or "##" section break.
    start = txt.find("Phase 1 additions")
    if start == -1:
        return  # Table not present — nothing to check
    end_markers = [txt.find("\n---", start), txt.find("\n## ", start + 10)]
    end = min((m for m in end_markers if m != -1), default=len(txt))
    phase1_table = txt[start:end]
    for frozen in ("shipment-detail.html", "dashboard.html"):
        assert frozen not in phase1_table, (
            f"{frozen!r} must not appear as a Phase 1 AI insertion target"
        )
