"""
test_ai_dhl_followup_drafter.py — Unit tests for AI-assisted DHL follow-up body drafting.

6 scenarios:
  1. AI flag disabled → deterministic body returned, ai_used=False
  2. AI flag enabled, gateway returns valid body → ai_used=True, AWB preserved
  3. AI flag enabled, gateway returns None → fallback to deterministic, ai_used=False
  4. AI body missing AWB → validation rejects, fallback to deterministic, ai_used=False
  5. AI gateway raises exception → fallback, ai_used=False, no propagation
  6. HTML wrapper reconstructed correctly from AI-enhanced plain text

Active-shipment filter proof:
  - The drafter is PURE (no audit write, no state change).
  - The delivered guard is enforced upstream by queue_email (Lesson E property 3).
  - These tests verify the drafter itself: flag gate, gateway call, validation, fallback.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services.ai_dhl_followup_drafter import (  # noqa: E402
    enhance_email_body,
    _validate_ai_output,
    _text_to_html,
    _build_user_prompt,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────

_AWB = "1234567890"

_AUDIT = {
    "awb":       _AWB,
    "batch_id":  "batch_test_001",
    "clearance_decision": {"total_value_usd": 1000.0},
}

_PKG = {
    "from_address": "import@estrellajewels.eu",
    "email_type":   "dhl_followup",
    "to":           "odprawacelna@dhl.com",
    "to_list":      ["odprawacelna@dhl.com"],
    "cc":           "import@estrellajewels.eu",
    "cc_list":      ["import@estrellajewels.eu"],
    "subject":      f"URGENT follow-up #1 – DSK / customs documents required – AWB {_AWB}",
    "body_text":    (
        f"Dear DHL Poland team,\n\n"
        f"This is our 1st follow-up regarding AWB {_AWB}.\n"
        f"CIF value: USD 1,000.00\n\n"
        f"Please send the DSK / customs documents immediately.\n\n"
        f"Best regards,\nImport Department\n"
    ),
    "body_html":    "<div style='font-family:sans-serif'><pre>...original html...</pre></div>",
    "attachments":  [],
    "awb_attached": False,
    "ticket":       "",
    "followup_seq": 1,
}

_BATCH_ID = "batch_test_001"

_AI_ENHANCED_TEXT = (
    f"Dear DHL Poland team,\n\n"
    f"We urgently follow up regarding AWB {_AWB}. This is our first reminder.\n"
    f"CIF value: USD 1,000.00\n\n"
    f"Immediate attention is required — please send the DSK / customs documents without delay.\n\n"
    f"Best regards,\nImport Department\n"
)


# ── Test 1: AI flag disabled → deterministic body returned ───────────────────

def test_ai_flag_disabled_returns_deterministic_body():
    """When ai_advisory_llm_enabled=False the drafter must return the original body."""
    mock_settings = MagicMock()
    mock_settings.ai_advisory_llm_enabled = False
    mock_settings.ai_advisory_model = ""

    # Patch settings at the config module so the function's local import sees it.
    # Also patch ai_gateway to None to ensure the flag check short-circuits before
    # any gateway access.
    with patch("app.core.config.settings", mock_settings), \
         patch("app.services.ai_dhl_followup_drafter.ai_gateway", None):
        result = enhance_email_body(_AUDIT, _BATCH_ID, _PKG)

    assert result["ai_used"] is False
    assert result["model_used"] is None
    assert result["pkg_updates"]["body_text"] == _PKG["body_text"]
    assert result["pkg_updates"]["body_html"] == _PKG["body_html"]


# ── Test 2: AI available, returns valid body → ai_used=True, AWB preserved ──

def test_ai_enabled_returns_enhanced_body_with_awb():
    """When AI is enabled and gateway returns valid text containing AWB, use it."""
    mock_settings = MagicMock()
    mock_settings.ai_advisory_llm_enabled = True
    mock_settings.ai_advisory_model = "claude-haiku-4-5-20251001"

    mock_gw = MagicMock()
    mock_gw.is_available.return_value = True
    mock_gw.call.return_value = _AI_ENHANCED_TEXT

    with patch("app.core.config.settings", mock_settings), \
         patch("app.services.ai_dhl_followup_drafter.ai_gateway", mock_gw):
        result = enhance_email_body(_AUDIT, _BATCH_ID, _PKG)

    assert result["ai_used"] is True
    assert result["model_used"] == "claude-haiku-4-5-20251001"
    assert _AWB in result["pkg_updates"]["body_text"]
    # Service strips whitespace from AI output — compare stripped form
    assert result["pkg_updates"]["body_text"] == _AI_ENHANCED_TEXT.strip()
    # HTML must contain the (stripped) AI text
    assert _AI_ENHANCED_TEXT.strip() in result["pkg_updates"]["body_html"]
    assert "<pre" in result["pkg_updates"]["body_html"]
    # Verify gateway called with correct task_type
    call_kwargs = mock_gw.call.call_args[1]
    assert call_kwargs["task_type"] == "dhl_followup_draft"
    assert call_kwargs["service_name"] == "ai_dhl_followup_drafter"
    assert call_kwargs["object_id"] == _BATCH_ID


# ── Test 3: AI returns None → fallback to deterministic ──────────────────────

def test_ai_gateway_returns_none_falls_back_to_deterministic():
    """When gateway returns None (budget/CB/key), original body is used."""
    mock_settings = MagicMock()
    mock_settings.ai_advisory_llm_enabled = True
    mock_settings.ai_advisory_model = "claude-haiku-4-5-20251001"

    mock_gw = MagicMock()
    mock_gw.is_available.return_value = True
    mock_gw.call.return_value = None

    with patch("app.core.config.settings", mock_settings), \
         patch("app.services.ai_dhl_followup_drafter.ai_gateway", mock_gw):
        result = enhance_email_body(_AUDIT, _BATCH_ID, _PKG)

    assert result["ai_used"] is False
    assert result["pkg_updates"]["body_text"] == _PKG["body_text"]
    assert result["pkg_updates"]["body_html"] == _PKG["body_html"]


# ── Test 4: AI body missing AWB → validation rejects, fallback ───────────────

def test_ai_body_missing_awb_rejected_and_fallback():
    """If AI response omits the AWB number, validation must reject it and fall back."""
    body_without_awb = (
        "Dear DHL Poland team,\n\n"
        "Please send the customs documents immediately to complete clearance.\n\n"
        "Best regards,\nImport Department\nEstrella Jewels Sp. z o.o. Sp. k.\n"
    )
    assert _AWB not in body_without_awb, "Test data error: AWB must be absent"
    assert len(body_without_awb) >= 50, "Test data error: string must be >= 50 chars"

    mock_settings = MagicMock()
    mock_settings.ai_advisory_llm_enabled = True
    mock_settings.ai_advisory_model = "claude-haiku-4-5-20251001"

    mock_gw = MagicMock()
    mock_gw.is_available.return_value = True
    mock_gw.call.return_value = body_without_awb

    with patch("app.core.config.settings", mock_settings), \
         patch("app.services.ai_dhl_followup_drafter.ai_gateway", mock_gw):
        result = enhance_email_body(_AUDIT, _BATCH_ID, _PKG)

    assert result["ai_used"] is False
    assert result["pkg_updates"]["body_text"] == _PKG["body_text"]


# ── Test 5: AI gateway raises exception → fallback, no propagation ────────────

def test_ai_gateway_exception_falls_back_no_propagation():
    """If ai_gateway.call raises any exception, function must not propagate it."""
    mock_settings = MagicMock()
    mock_settings.ai_advisory_llm_enabled = True
    mock_settings.ai_advisory_model = "claude-haiku-4-5-20251001"

    mock_gw = MagicMock()
    mock_gw.is_available.return_value = True
    mock_gw.call.side_effect = RuntimeError("API connection refused")

    with patch("app.core.config.settings", mock_settings), \
         patch("app.services.ai_dhl_followup_drafter.ai_gateway", mock_gw):
        # Must NOT raise — fallback is silent
        result = enhance_email_body(_AUDIT, _BATCH_ID, _PKG)

    assert result["ai_used"] is False
    assert result["pkg_updates"]["body_text"] == _PKG["body_text"]


# ── Test 6: HTML wrapper correctly reconstructed from AI text ─────────────────

def test_html_wrapper_reconstructed_from_ai_enhanced_text():
    """The HTML body returned by drafter must correctly wrap the AI text."""
    # Use a string >= 50 chars (min floor) that also contains the AWB
    ai_text = (
        f"Dear DHL Poland,\n\n"
        f"Urgent follow-up regarding AWB {_AWB}. Please respond.\n\n"
        f"Best regards,\nImport Department\n"
    )
    assert len(ai_text) >= 50

    result_html = _text_to_html(ai_text)

    assert ai_text in result_html
    assert "<div" in result_html
    assert "<pre" in result_html
    assert "white-space:pre-wrap" in result_html

    # Verify the validate helper works on this string (AWB present, long enough)
    assert _validate_ai_output(ai_text, _AWB) is True
    # Missing AWB → rejected
    assert _validate_ai_output("No AWB here — but this string is definitely long enough.", _AWB) is False
    # Empty → rejected
    assert _validate_ai_output("", _AWB) is False
    # Too short → rejected (< 50 chars)
    assert _validate_ai_output("x" * 10, _AWB) is False


# ── Standalone validation unit tests ─────────────────────────────────────────

def test_validate_output_empty_string_rejected():
    assert _validate_ai_output("", "1234567890") is False


def test_validate_output_too_short_rejected():
    assert _validate_ai_output("Hi.", "1234567890") is False


def test_validate_output_awb_present_accepted():
    long_enough = "A" * 60 + " AWB 1234567890 is the reference."
    assert _validate_ai_output(long_enough, "1234567890") is True


def test_build_user_prompt_contains_awb():
    prompt = _build_user_prompt("Some body text here.", "9876543210", 2)
    assert "9876543210" in prompt
    assert "Follow-up number: 2" in prompt
    assert "Some body text here." in prompt
