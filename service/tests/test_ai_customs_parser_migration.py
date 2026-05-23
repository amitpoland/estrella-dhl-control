"""
test_ai_customs_parser_migration.py — Verifies ai_customs_parser.py uses ai_gateway,
not the Anthropic SDK directly.

Patching strategy: ai_customs_parser.parse_with_ai() does `from . import ai_gateway`
inside the function body. Python resolves that by looking up the attribute on the
parent package object (app.services.ai_gateway). We patch that attribute with
patch("app.services.ai_gateway", mock) so that the local-import inside the function
gets our mock.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

import pytest


def _settings(enabled=True, api_key="sk-test-key-abc123456789"):
    s = MagicMock()
    s.ai_parser_enabled  = enabled
    s.anthropic_api_key  = api_key
    s.storage_root       = "/tmp/test_storage"
    return s


def _config_mod(enabled=True, api_key="sk-test-key-abc123456789"):
    m = MagicMock()
    m.settings = _settings(enabled=enabled, api_key=api_key)
    return m


# ── Gate: disabled → None without AI call ────────────────────────────────────

def test_parse_returns_none_when_disabled():
    """When ai_parser_enabled=False, parse_with_ai must return None immediately."""
    from app.services import ai_customs_parser

    mock_gateway = MagicMock()
    mock_gateway.call.return_value = None

    with patch.dict("sys.modules", {"app.core.config": _config_mod(enabled=False)}):
        with patch("app.services.ai_gateway", mock_gateway, create=True):
            result = ai_customs_parser.parse_with_ai("/fake/file.pdf")

    assert result is None
    mock_gateway.call.assert_not_called()


def test_parse_returns_none_when_no_api_key():
    """When anthropic_api_key is empty, parse_with_ai must return None."""
    from app.services import ai_customs_parser

    mock_gateway = MagicMock()

    with patch.dict("sys.modules", {"app.core.config": _config_mod(api_key="")}):
        with patch("app.services.ai_gateway", mock_gateway, create=True):
            result = ai_customs_parser.parse_with_ai("/fake/file.pdf")

    assert result is None
    mock_gateway.call.assert_not_called()


# ── Happy path: gateway called with correct arguments ────────────────────────

def test_parse_calls_gateway_with_customs_extraction_task_type():
    """parse_with_ai must call ai_gateway.call(task_type='customs_extraction')."""
    from app.services import ai_customs_parser

    mock_gateway = MagicMock()
    mock_gateway.call.return_value = '{"mrn": "26PL44302D00A1J5R7", "duty_pln": 150.0}'

    with patch.dict("sys.modules", {"app.core.config": _config_mod()}):
        with patch("app.services.ai_gateway", mock_gateway, create=True):
            with patch("app.services.ai_customs_parser._extract_pdf_text", return_value="PDF text"):
                result = ai_customs_parser.parse_with_ai("/fake/file.pdf")

    assert mock_gateway.call.call_count == 1
    call_kwargs = mock_gateway.call.call_args[1]
    assert call_kwargs["task_type"] == "customs_extraction"
    assert call_kwargs["service_name"] == "ai_customs_parser"


def test_parse_calls_gateway_with_correct_complexity():
    """parse_with_ai must pass complexity='moderate' and risk_level='medium'."""
    from app.services import ai_customs_parser

    mock_gateway = MagicMock()
    mock_gateway.call.return_value = '{"mrn": null}'

    with patch.dict("sys.modules", {"app.core.config": _config_mod()}):
        with patch("app.services.ai_gateway", mock_gateway, create=True):
            with patch("app.services.ai_customs_parser._extract_pdf_text", return_value="content"):
                ai_customs_parser.parse_with_ai("/fake/ZC429.pdf")

    call_kwargs = mock_gateway.call.call_args[1]
    assert call_kwargs["complexity"] == "moderate"
    assert call_kwargs["risk_level"] == "medium"


def test_parse_passes_filename_as_object_id():
    """parse_with_ai must pass the PDF filename (not full path) as object_id."""
    from app.services import ai_customs_parser

    mock_gateway = MagicMock()
    mock_gateway.call.return_value = '{"mrn": null}'

    with patch.dict("sys.modules", {"app.core.config": _config_mod()}):
        with patch("app.services.ai_gateway", mock_gateway, create=True):
            with patch("app.services.ai_customs_parser._extract_pdf_text", return_value="content"):
                ai_customs_parser.parse_with_ai("/path/to/docs/ZC429_test.pdf")

    call_kwargs = mock_gateway.call.call_args[1]
    assert call_kwargs["object_id"] == "ZC429_test.pdf"


# ── Gateway returns None → parse returns None ─────────────────────────────────

def test_parse_returns_none_when_gateway_returns_none():
    """If ai_gateway.call() returns None, parse_with_ai must return None."""
    from app.services import ai_customs_parser

    mock_gateway = MagicMock()
    mock_gateway.call.return_value = None

    with patch.dict("sys.modules", {"app.core.config": _config_mod()}):
        with patch("app.services.ai_gateway", mock_gateway, create=True):
            with patch("app.services.ai_customs_parser._extract_pdf_text", return_value="content"):
                result = ai_customs_parser.parse_with_ai("/fake/file.pdf")

    assert result is None


# ── Response parsing ──────────────────────────────────────────────────────────

def test_parse_attaches_ai_meta_on_success():
    """On success, parse_with_ai must attach _ai_meta to the result dict."""
    from app.services import ai_customs_parser

    valid_json = '{"mrn": "26PL44302D00A1J5R7", "duty_pln": 150.0, "vat_pln": 345.0}'
    mock_gateway = MagicMock()
    mock_gateway.call.return_value = valid_json

    with patch.dict("sys.modules", {"app.core.config": _config_mod()}):
        with patch("app.services.ai_gateway", mock_gateway, create=True):
            with patch("app.services.ai_customs_parser._extract_pdf_text", return_value="content"):
                result = ai_customs_parser.parse_with_ai("/fake/file.pdf")

    assert result is not None
    assert "_ai_meta" in result
    assert "confidence" in result["_ai_meta"]
    assert "fields_extracted" in result["_ai_meta"]


def test_parse_handles_markdown_wrapped_json():
    """parse_with_ai must strip ```json ... ``` wrapping from LLM output."""
    from app.services import ai_customs_parser

    wrapped = '```json\n{"mrn": "26PL44302D00A1J5R7"}\n```'
    mock_gateway = MagicMock()
    mock_gateway.call.return_value = wrapped

    with patch.dict("sys.modules", {"app.core.config": _config_mod()}):
        with patch("app.services.ai_gateway", mock_gateway, create=True):
            with patch("app.services.ai_customs_parser._extract_pdf_text", return_value="content"):
                result = ai_customs_parser.parse_with_ai("/fake/file.pdf")

    assert result is not None
    assert result["mrn"] == "26PL44302D00A1J5R7"


def test_parse_returns_none_when_no_pdf_text():
    """If PDF text extraction returns None, parse_with_ai must return None."""
    from app.services import ai_customs_parser

    mock_gateway = MagicMock()

    with patch.dict("sys.modules", {"app.core.config": _config_mod()}):
        with patch("app.services.ai_gateway", mock_gateway, create=True):
            with patch("app.services.ai_customs_parser._extract_pdf_text", return_value=None):
                result = ai_customs_parser.parse_with_ai("/fake/file.pdf")

    assert result is None
    mock_gateway.call.assert_not_called()
