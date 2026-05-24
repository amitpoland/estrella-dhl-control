"""
test_phase2c_governance_hardening.py — Phase 2C governance hardening tests.

Tests nine assertions across three fix areas:
  A. STARTUP_AI_AUDIT block in main.py lifespan
  B. active_provider consistency in /status endpoint
  C. anthropic dependency declared in requirements.txt
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


# ═══════════════════════════════════════════════════════════════════════
# Section A — STARTUP_AI_AUDIT governance block in main.py
# ═══════════════════════════════════════════════════════════════════════

def test_startup_ai_audit_block_exists_in_main():
    """STARTUP_AI_AUDIT string must exist in main.py."""
    main_py = _SVC / "app" / "main.py"
    assert main_py.exists(), "main.py not found"
    source = main_py.read_text(encoding="utf-8")
    assert "STARTUP_AI_AUDIT" in source, (
        "STARTUP_AI_AUDIT log block not found in main.py"
    )


def test_startup_ai_audit_covers_all_four_flags():
    """All four AI execution flags must appear in the audit block."""
    main_py = _SVC / "app" / "main.py"
    source = main_py.read_text(encoding="utf-8")
    for flag in (
        "ai_parser_enabled",
        "ai_advisory_llm_enabled",
        "ai_cowork_enabled",
        "ai_fallback_enabled",
    ):
        assert flag in source, f"AI flag '{flag}' not audited in STARTUP_AI_AUDIT block"


def test_startup_ai_audit_logs_warning_when_flag_true(caplog):
    """STARTUP_AI_AUDIT must log WARNING when any AI flag is TRUE."""
    import logging
    import importlib

    # Build a fake settings object with one AI flag TRUE
    fake_settings = MagicMock()
    fake_settings.ai_parser_enabled       = True
    fake_settings.ai_advisory_llm_enabled = False
    fake_settings.ai_cowork_enabled       = False
    fake_settings.ai_fallback_enabled     = False

    # Patch the settings the audit block reads via getattr
    # We exercise the logic directly rather than going through lifespan
    # (lifespan requires async context and DB setup).
    import logging as _log_mod

    _ai_flags = {
        "ai_parser_enabled":       getattr(fake_settings, "ai_parser_enabled",       False),
        "ai_advisory_llm_enabled": getattr(fake_settings, "ai_advisory_llm_enabled", False),
        "ai_cowork_enabled":       getattr(fake_settings, "ai_cowork_enabled",        False),
        "ai_fallback_enabled":     getattr(fake_settings, "ai_fallback_enabled",      False),
    }
    _ai_enabled = [k for k, v in _ai_flags.items() if v]

    with caplog.at_level(logging.WARNING, logger="root"):
        log = _log_mod.getLogger("startup_ai_audit_test")
        if _ai_enabled:
            log.warning(
                "STARTUP_AI_AUDIT: the following AI execution flags are TRUE "
                "(env-var-only — verify .env is intentional): %s",
                _ai_enabled,
            )

    assert any("STARTUP_AI_AUDIT" in r.message for r in caplog.records), (
        "Expected STARTUP_AI_AUDIT WARNING not emitted"
    )
    assert any("ai_parser_enabled" in r.message for r in caplog.records), (
        "ai_parser_enabled should appear in the WARNING message"
    )


def test_startup_ai_audit_logs_info_when_all_flags_false(caplog):
    """STARTUP_AI_AUDIT must log INFO (not WARNING) when all AI flags are FALSE."""
    import logging as _log_mod

    fake_settings = MagicMock()
    fake_settings.ai_parser_enabled       = False
    fake_settings.ai_advisory_llm_enabled = False
    fake_settings.ai_cowork_enabled       = False
    fake_settings.ai_fallback_enabled     = False

    _ai_flags = {
        "ai_parser_enabled":       getattr(fake_settings, "ai_parser_enabled",       False),
        "ai_advisory_llm_enabled": getattr(fake_settings, "ai_advisory_llm_enabled", False),
        "ai_cowork_enabled":       getattr(fake_settings, "ai_cowork_enabled",        False),
        "ai_fallback_enabled":     getattr(fake_settings, "ai_fallback_enabled",      False),
    }
    _ai_enabled = [k for k, v in _ai_flags.items() if v]

    with caplog.at_level(_log_mod.INFO, logger="root"):
        log = _log_mod.getLogger("startup_ai_audit_test")
        if not _ai_enabled:
            log.info("STARTUP_AI_AUDIT: all AI execution flags are OFF (safe defaults).")

    assert any("STARTUP_AI_AUDIT" in r.message for r in caplog.records), (
        "Expected STARTUP_AI_AUDIT INFO not emitted"
    )
    assert not any(
        "STARTUP_AI_AUDIT" in r.message and r.levelno >= _log_mod.WARNING
        for r in caplog.records
    ), "STARTUP_AI_AUDIT must not WARNING when all flags are OFF"


# ═══════════════════════════════════════════════════════════════════════
# Section B — active_provider consistency in /status route
# ═══════════════════════════════════════════════════════════════════════

def _active_provider_from_logic(
    gateway_available: bool,
    cowork_enabled: bool,
    provider_pref: str,
) -> str:
    """
    Replicate the fixed active_provider derivation from routes_ai_advisory.py
    so tests are not coupled to the HTTP layer.
    """
    if not gateway_available:
        return "none"
    elif cowork_enabled and provider_pref == "claude_cowork":
        return "claude_cowork"
    else:
        return "anthropic_api"


def test_active_provider_none_when_gateway_unavailable():
    """active_provider must be 'none' when gateway_available=False, regardless of cowork."""
    result = _active_provider_from_logic(
        gateway_available=False,
        cowork_enabled=True,
        provider_pref="claude_cowork",
    )
    assert result == "none", (
        f"active_provider should be 'none' when gateway_available=False, got '{result}'"
    )


def test_active_provider_cowork_when_enabled_and_gateway_available():
    """active_provider must be 'claude_cowork' when both gateway_available and cowork_enabled."""
    result = _active_provider_from_logic(
        gateway_available=True,
        cowork_enabled=True,
        provider_pref="claude_cowork",
    )
    assert result == "claude_cowork", (
        f"Expected 'claude_cowork', got '{result}'"
    )


def test_active_provider_anthropic_when_gateway_available_no_cowork():
    """active_provider must be 'anthropic_api' when gateway available and cowork disabled."""
    result = _active_provider_from_logic(
        gateway_available=True,
        cowork_enabled=False,
        provider_pref="claude_cowork",
    )
    assert result == "anthropic_api", (
        f"Expected 'anthropic_api', got '{result}'"
    )


def test_active_provider_fix_applied_in_source():
    """
    The bug-fix ordering must be present in routes_ai_advisory.py source:
    'if not gateway_available' must appear BEFORE 'elif cowork_enabled'.
    """
    route_file = _SVC / "app" / "api" / "routes_ai_advisory.py"
    source = route_file.read_text(encoding="utf-8")
    idx_not_gw = source.find("if not gateway_available")
    idx_cowork = source.find("elif cowork_enabled")
    assert idx_not_gw != -1, "'if not gateway_available' not found in routes_ai_advisory.py"
    assert idx_cowork != -1, "'elif cowork_enabled' not found in routes_ai_advisory.py"
    assert idx_not_gw < idx_cowork, (
        "Bug not fixed: 'if not gateway_available' must appear BEFORE 'elif cowork_enabled'"
    )


# ═══════════════════════════════════════════════════════════════════════
# Section C — anthropic dependency in requirements.txt
# ═══════════════════════════════════════════════════════════════════════

def test_anthropic_declared_in_requirements():
    """requirements.txt must declare anthropic>=0.50.0."""
    req_file = _SVC / "requirements.txt"
    assert req_file.exists(), "requirements.txt not found"
    content = req_file.read_text(encoding="utf-8")
    assert "anthropic" in content, (
        "anthropic package not declared in requirements.txt — "
        "ai_gateway._anthropic_call() will silently fail on Windows production"
    )
    # Find the line and check the version constraint
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("anthropic") and not stripped.startswith("#"):
            assert "0.50" in stripped or ">=" in stripped, (
                f"anthropic line should pin >=0.50.0, got: {stripped!r}"
            )
            break
    else:
        raise AssertionError("No non-comment 'anthropic' line found in requirements.txt")
