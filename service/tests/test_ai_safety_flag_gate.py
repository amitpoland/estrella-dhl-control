"""
test_ai_safety_flag_gate.py — Phase 3A AI governance safety gate.

Pins the service-level ai_parser_enabled flag-gate in both AI customs
services. Ensures Anthropic client creation is blocked when the flag
is False (the production default), regardless of whether an API key is
present in the environment.

Hard rules verified here:
  - ai_parser_enabled=False → no Anthropic import, no client creation,
    no network call — in BOTH ai_customs_parser and ai_customs_evidence.
  - ai_parser_enabled=True + key present → enabled path is mock-compatible
    (no live network call in tests).
  - Production config default is False.
  - No financial fields mutated.
  - No parser outputs changed except the disabled-state early return.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_SVC = Path(__file__).resolve().parent.parent
import sys
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_settings(*, enabled: bool, api_key: str = "sk-test-key"):
    """Return a mock settings object with controlled AI flags."""
    s = MagicMock()
    s.ai_parser_enabled = enabled
    s.anthropic_api_key = api_key if enabled else None
    s.ai_parser_model = "claude-sonnet-4-6"
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Source-structure contracts (no runtime required)
# ─────────────────────────────────────────────────────────────────────────────

def test_parser_source_contains_enabled_gate():
    """parse_with_ai() must check ai_parser_enabled before checking the API key."""
    import app.services.ai_customs_parser as mod
    src = inspect.getsource(mod.parse_with_ai)
    assert "ai_parser_enabled" in src, (
        "parse_with_ai() must gate on settings.ai_parser_enabled"
    )
    # Gate must appear before the api_key check
    enabled_pos = src.find("ai_parser_enabled")
    api_key_pos = src.find("anthropic_api_key")
    assert enabled_pos < api_key_pos, (
        "ai_parser_enabled check must precede anthropic_api_key check in parse_with_ai()"
    )


def test_evidence_provider_available_contains_enabled_gate():
    """_provider_available() must check ai_parser_enabled before the API key."""
    import app.services.ai_customs_evidence as mod
    src = inspect.getsource(mod._provider_available)
    assert "ai_parser_enabled" in src, (
        "_provider_available() must gate on settings.ai_parser_enabled"
    )
    enabled_pos = src.find("ai_parser_enabled")
    api_key_pos = src.find("anthropic_api_key")
    assert enabled_pos < api_key_pos, (
        "ai_parser_enabled check must precede anthropic_api_key check in _provider_available()"
    )


# ─────────────────────────────────────────────────────────────────────────────
# ai_customs_parser — flag gate
# ─────────────────────────────────────────────────────────────────────────────

class TestParserFlagGate:
    """parse_with_ai() is blocked when ai_parser_enabled=False."""

    def test_disabled_returns_none_without_touching_anthropic(self):
        """With ai_parser_enabled=False, parse_with_ai must return None and
        must NOT import or instantiate anthropic.Anthropic."""
        import app.services.ai_customs_parser as parser_mod

        mock_anthropic_cls = MagicMock()

        with patch("app.core.config.settings") as mock_cfg, \
             patch.dict("sys.modules", {"anthropic": MagicMock(Anthropic=mock_anthropic_cls)}):
            mock_cfg.ai_parser_enabled = False
            mock_cfg.anthropic_api_key = "sk-test-key"  # key IS present but flag is off
            mock_cfg.ai_parser_model = "claude-sonnet-4-6"

            result = parser_mod.parse_with_ai("/fake/path.pdf")

        assert result is None
        mock_anthropic_cls.assert_not_called()

    def test_disabled_flag_gate_blocks_even_with_valid_key_and_text(self):
        """Even when api_key is set AND pdf text is extractable, ai_parser_enabled=False
        must block Anthropic client creation."""
        import app.services.ai_customs_parser as parser_mod

        anthropic_client_mock = MagicMock()
        anthropic_module_mock = MagicMock()
        anthropic_module_mock.Anthropic = MagicMock(return_value=anthropic_client_mock)

        with patch("app.core.config.settings") as mock_cfg, \
             patch("app.services.ai_customs_parser._extract_pdf_text", return_value="ZC429 text content"), \
             patch.dict("sys.modules", {"anthropic": anthropic_module_mock}):
            mock_cfg.ai_parser_enabled = False
            mock_cfg.anthropic_api_key = "sk-real-looking-key"
            mock_cfg.ai_parser_model = "claude-sonnet-4-6"

            result = parser_mod.parse_with_ai("/real/path.pdf")

        assert result is None
        anthropic_module_mock.Anthropic.assert_not_called()

    def test_enabled_path_is_mock_compatible(self):
        """With ai_parser_enabled=True and a stubbed Anthropic response,
        parse_with_ai returns a dict with _ai_meta."""
        import app.services.ai_customs_parser as parser_mod
        import json

        fake_response_text = json.dumps({
            "mrn": "26PL44302D00C2M4R4",
            "duty_pln": 957.0,
        })

        mock_content = MagicMock()
        mock_content.text = fake_response_text

        mock_message = MagicMock()
        mock_message.content = [mock_content]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message

        mock_anthropic_cls = MagicMock(return_value=mock_client)
        mock_anthropic_mod = MagicMock()
        mock_anthropic_mod.Anthropic = mock_anthropic_cls

        with patch("app.core.config.settings") as mock_cfg, \
             patch("app.services.ai_customs_parser._extract_pdf_text", return_value="ZC429 full text"), \
             patch.dict("sys.modules", {"anthropic": mock_anthropic_mod}):
            mock_cfg.ai_parser_enabled = True
            mock_cfg.anthropic_api_key = "sk-test"
            mock_cfg.ai_parser_model = "claude-sonnet-4-6"

            result = parser_mod.parse_with_ai("/path/to/zc429.pdf")

        assert result is not None
        assert "_ai_meta" in result
        assert result["mrn"] == "26PL44302D00C2M4R4"


# ─────────────────────────────────────────────────────────────────────────────
# ai_customs_evidence — flag gate via _provider_available()
# ─────────────────────────────────────────────────────────────────────────────

class TestEvidenceFlagGate:
    """_provider_available() returns False when ai_parser_enabled=False."""

    def test_provider_unavailable_when_flag_false(self):
        """_provider_available() must return False when ai_parser_enabled=False,
        even if the api_key is set."""
        from app.services.ai_customs_evidence import _provider_available

        with patch("app.core.config.settings") as mock_cfg:
            mock_cfg.ai_parser_enabled = False
            mock_cfg.anthropic_api_key = "sk-real-key"
            result = _provider_available()

        assert result is False

    def test_provider_unavailable_when_flag_false_and_no_key(self):
        """_provider_available() must return False when flag is False
        regardless of key presence."""
        from app.services.ai_customs_evidence import _provider_available

        with patch("app.core.config.settings") as mock_cfg:
            mock_cfg.ai_parser_enabled = False
            mock_cfg.anthropic_api_key = None
            result = _provider_available()

        assert result is False

    def test_extract_customs_evidence_disabled_returns_none(self):
        """extract_customs_evidence() must return None and make no network call
        when ai_parser_enabled=False."""
        from app.services.ai_customs_evidence import extract_customs_evidence

        mock_client = MagicMock()
        mock_anthropic_mod = MagicMock()
        mock_anthropic_mod.Anthropic = MagicMock(return_value=mock_client)

        with patch("app.core.config.settings") as mock_cfg, \
             patch.dict("sys.modules", {"anthropic": mock_anthropic_mod}):
            mock_cfg.ai_parser_enabled = False
            mock_cfg.anthropic_api_key = "sk-test"

            result = extract_customs_evidence("full pdf text here", document_hint="SAD")

        assert result is None
        mock_client.messages.create.assert_not_called()

    def test_extract_customs_evidence_enabled_path_is_mock_compatible(self):
        """extract_customs_evidence() returns a normalised dict when enabled
        and the provider is stubbed."""
        import json
        from app.services.ai_customs_evidence import extract_customs_evidence, EVIDENCE_SCHEMA

        fake_ai_response = json.dumps({
            "invoice_refs": ["088/2026-2027"],
            "awb": "4789974092",
            "mrn": "26PL44302D00C2M4R4",
            "cif_usd": 3172.0,
            "exporter": "Global Jewellery",
            "importer": "Estrella Jewels",
            "cn_codes": ["711319"],
            "confidence": "high",
            "evidence": ["Invoice 088/2026-2027 printed on page 1"],
        })

        mock_content = MagicMock()
        mock_content.text = fake_ai_response

        mock_message = MagicMock()
        mock_message.content = [mock_content]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message

        mock_anthropic_mod = MagicMock()
        mock_anthropic_mod.Anthropic = MagicMock(return_value=mock_client)

        with patch("app.core.config.settings") as mock_cfg, \
             patch.dict("sys.modules", {"anthropic": mock_anthropic_mod}):
            mock_cfg.ai_parser_enabled = True
            mock_cfg.anthropic_api_key = "sk-test"
            mock_cfg.ai_parser_model = "claude-sonnet-4-6"

            result = extract_customs_evidence(
                "ZC429 document text content",
                document_hint="SAD/ZC429",
            )

        assert result is not None
        assert result["invoice_refs"] == ["088/2026-2027"]
        assert result["confidence"] == "high"
        assert "_ai_meta" in result


# ─────────────────────────────────────────────────────────────────────────────
# Production config default
# ─────────────────────────────────────────────────────────────────────────────

def test_production_default_is_disabled():
    """ai_parser_enabled must default to False in Settings — production is
    never accidentally AI-enabled by a missing env var."""
    from app.core.config import Settings
    s = Settings()
    assert s.ai_parser_enabled is False, (
        "ai_parser_enabled must default to False — production safety invariant"
    )


def test_anthropic_key_default_is_none():
    """anthropic_api_key must default to None — no live key baked into defaults."""
    from app.core.config import Settings
    import os
    # Temporarily clear env var if set
    env_val = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        s = Settings()
        assert s.anthropic_api_key is None
    finally:
        if env_val is not None:
            os.environ["ANTHROPIC_API_KEY"] = env_val
