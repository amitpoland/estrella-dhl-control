"""
test_ai_customs_evidence_migration.py — Verifies ai_customs_evidence.py uses ai_gateway,
not the Anthropic SDK directly.

Patching strategy: extract_customs_evidence() does `from . import ai_gateway` inside
the function body. We patch the parent package attribute with
patch("app.services.ai_gateway", mock_gateway, create=True) so the local import gets our mock.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

import pytest

_SAMPLE_PDF_TEXT = "MRN: 26PL44302D00A1J5R7 Duty: 150.00 PLN Importer: Test Co"


# ── Gate: provider unavailable → None ────────────────────────────────────────

def test_evidence_returns_none_when_provider_unavailable():
    """When _provider_available() is False, extract_customs_evidence must return None."""
    from app.services import ai_customs_evidence

    mock_gateway = MagicMock()

    with patch("app.services.ai_customs_evidence._provider_available", return_value=False):
        with patch("app.services.ai_gateway", mock_gateway, create=True):
            result = ai_customs_evidence.extract_customs_evidence(_SAMPLE_PDF_TEXT)

    assert result is None
    mock_gateway.call.assert_not_called()


def test_evidence_returns_none_on_empty_pdf_text():
    """Empty pdf_text must return None without calling the gateway."""
    from app.services import ai_customs_evidence

    mock_gateway = MagicMock()

    with patch("app.services.ai_customs_evidence._provider_available", return_value=True):
        with patch("app.services.ai_gateway", mock_gateway, create=True):
            result = ai_customs_evidence.extract_customs_evidence("")

    assert result is None
    mock_gateway.call.assert_not_called()


# ── Happy path: gateway called with correct arguments ────────────────────────

def test_evidence_calls_gateway_with_evidence_recovery_task_type():
    """extract_customs_evidence must call ai_gateway.call(task_type='evidence_recovery')."""
    from app.services import ai_customs_evidence

    valid_response = '{"awb": "1234567890", "mrn": null, "clearance_date": null}'
    mock_gateway = MagicMock()
    mock_gateway.call.return_value = valid_response

    with patch("app.services.ai_customs_evidence._provider_available", return_value=True):
        with patch("app.services.ai_gateway", mock_gateway, create=True):
            result = ai_customs_evidence.extract_customs_evidence(_SAMPLE_PDF_TEXT)

    assert mock_gateway.call.call_count == 1
    call_kwargs = mock_gateway.call.call_args[1]
    assert call_kwargs["task_type"] == "evidence_recovery"
    assert call_kwargs["service_name"] == "ai_customs_evidence"


def test_evidence_calls_gateway_with_correct_complexity():
    """extract_customs_evidence must pass complexity='moderate' and risk_level='medium'."""
    from app.services import ai_customs_evidence

    mock_gateway = MagicMock()
    mock_gateway.call.return_value = '{"awb": null}'

    with patch("app.services.ai_customs_evidence._provider_available", return_value=True):
        with patch("app.services.ai_gateway", mock_gateway, create=True):
            ai_customs_evidence.extract_customs_evidence(_SAMPLE_PDF_TEXT)

    call_kwargs = mock_gateway.call.call_args[1]
    assert call_kwargs["complexity"] == "moderate"
    assert call_kwargs["risk_level"] == "medium"


# ── Gateway returns None → evidence returns None ──────────────────────────────

def test_evidence_returns_none_when_gateway_returns_none():
    """If ai_gateway.call() returns None, extract_customs_evidence must return None."""
    from app.services import ai_customs_evidence

    mock_gateway = MagicMock()
    mock_gateway.call.return_value = None

    with patch("app.services.ai_customs_evidence._provider_available", return_value=True):
        with patch("app.services.ai_gateway", mock_gateway, create=True):
            result = ai_customs_evidence.extract_customs_evidence(_SAMPLE_PDF_TEXT)

    assert result is None


# ── Response structure ────────────────────────────────────────────────────────

def test_evidence_attaches_ai_meta_on_success():
    """On success, extract_customs_evidence must attach _ai_meta to the result dict."""
    from app.services import ai_customs_evidence

    valid_json = '{"awb": "1234567890", "mrn": "26PL44302D00A1J5R7", "clearance_date": "2026-05-01"}'
    mock_gateway = MagicMock()
    mock_gateway.call.return_value = valid_json

    with patch("app.services.ai_customs_evidence._provider_available", return_value=True):
        with patch("app.services.ai_gateway", mock_gateway, create=True):
            result = ai_customs_evidence.extract_customs_evidence(_SAMPLE_PDF_TEXT)

    assert result is not None
    assert "_ai_meta" in result


def test_evidence_returns_none_on_invalid_json():
    """If gateway returns unparseable text, extract_customs_evidence must return None."""
    from app.services import ai_customs_evidence

    mock_gateway = MagicMock()
    mock_gateway.call.return_value = "not json at all"

    with patch("app.services.ai_customs_evidence._provider_available", return_value=True):
        with patch("app.services.ai_gateway", mock_gateway, create=True):
            result = ai_customs_evidence.extract_customs_evidence(_SAMPLE_PDF_TEXT)

    assert result is None


def test_evidence_truncates_large_pdf_text():
    """Large pdf_text must be truncated before being sent to the gateway."""
    from app.services import ai_customs_evidence

    large_text = "A" * 20000  # well above default max_text_chars=6000
    mock_gateway = MagicMock()
    mock_gateway.call.return_value = '{"awb": null}'

    with patch("app.services.ai_customs_evidence._provider_available", return_value=True):
        with patch("app.services.ai_gateway", mock_gateway, create=True):
            ai_customs_evidence.extract_customs_evidence(large_text)

    assert mock_gateway.call.call_count == 1
    call_kwargs = mock_gateway.call.call_args[1]
    sent_user = call_kwargs.get("user", "")
    # 20000 chars truncated to 6000 + prompt overhead — total must be below 20000
    assert len(sent_user) < 20000
