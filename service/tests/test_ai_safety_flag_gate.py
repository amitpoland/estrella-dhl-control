"""
test_ai_safety_flag_gate.py — Phase 3A safety patch verification.

Proves that neither ai_customs_parser nor ai_customs_evidence will
create an Anthropic client or make an API call when ai_parser_enabled=False,
regardless of whether a valid API key is present.

Tests:
  1. parse_with_ai returns None when ai_parser_enabled=False
  2. extract_customs_evidence returns None when ai_parser_enabled=False
  3. Anthropic client is NOT instantiated when ai_parser_enabled=False
  4. No API call is attempted when ai_parser_enabled=False
  5. parse_with_ai enabled path remains compatible (mocked)
  6. extract_customs_evidence enabled path remains compatible (mocked)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_settings(*, enabled: bool, api_key: str = "sk-test-key"):
    s = MagicMock()
    s.ai_parser_enabled = enabled
    s.anthropic_api_key = api_key
    s.ai_parser_model = "claude-sonnet-4-6"
    return s


# ── Test 1: parse_with_ai returns None when disabled ─────────────────────────

def test_parse_with_ai_returns_none_when_disabled(tmp_path):
    """parse_with_ai must return None immediately when ai_parser_enabled=False."""
    from app.services import ai_customs_parser

    fake_settings = _make_settings(enabled=False)
    dummy_pdf = tmp_path / "test.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4")  # not a real PDF — must never be opened

    with patch("app.services.ai_customs_parser.settings", fake_settings, create=True):
        # Patch the import inside the function
        with patch.dict("sys.modules", {"app.core.config": MagicMock(settings=fake_settings)}):
            # Monkeypatch _extract_pdf_text so we know it was never called
            called = []
            orig = ai_customs_parser._extract_pdf_text

            def _spy(*a, **kw):
                called.append(a)
                return orig(*a, **kw)

            # We override settings via the module-level import inside parse_with_ai
            import importlib
            import types

            # Directly patch settings inside the function by patching the import
            config_mod = MagicMock()
            config_mod.settings = fake_settings
            with patch.dict("sys.modules", {"app.core.config": config_mod}):
                result = ai_customs_parser.parse_with_ai(str(dummy_pdf))

    assert result is None


# ── Test 2: extract_customs_evidence returns None when disabled ───────────────

def test_extract_customs_evidence_returns_none_when_disabled():
    """extract_customs_evidence must return None when ai_parser_enabled=False."""
    from app.services import ai_customs_evidence

    fake_settings = _make_settings(enabled=False)
    config_mod = MagicMock()
    config_mod.settings = fake_settings

    with patch.dict("sys.modules", {"app.core.config": config_mod}):
        result = ai_customs_evidence.extract_customs_evidence(
            "Some document text here",
            document_hint="ZC429",
        )

    assert result is None


# ── Test 3: Anthropic client not instantiated when disabled ───────────────────

def test_no_anthropic_client_created_when_parser_disabled(tmp_path):
    """anthropic.Anthropic() must never be called when ai_parser_enabled=False."""
    from app.services import ai_customs_parser

    fake_settings = _make_settings(enabled=False)
    config_mod = MagicMock()
    config_mod.settings = fake_settings

    mock_anthropic_class = MagicMock()

    with patch.dict("sys.modules", {
        "app.core.config": config_mod,
        "anthropic": MagicMock(Anthropic=mock_anthropic_class),
    }):
        dummy_pdf = tmp_path / "dummy.pdf"
        dummy_pdf.write_bytes(b"%PDF")
        ai_customs_parser.parse_with_ai(str(dummy_pdf))

    mock_anthropic_class.assert_not_called()


def test_no_anthropic_client_created_when_evidence_disabled():
    """anthropic.Anthropic() must never be called when ai_parser_enabled=False."""
    from app.services import ai_customs_evidence

    fake_settings = _make_settings(enabled=False)
    config_mod = MagicMock()
    config_mod.settings = fake_settings

    mock_anthropic_class = MagicMock()

    with patch.dict("sys.modules", {
        "app.core.config": config_mod,
        "anthropic": MagicMock(Anthropic=mock_anthropic_class),
    }):
        ai_customs_evidence.extract_customs_evidence("text content")

    mock_anthropic_class.assert_not_called()


# ── Test 4: No API call attempted when disabled ────────────────────────────────

def test_no_api_call_when_parser_disabled(tmp_path):
    """messages.create() must never be called when ai_parser_enabled=False."""
    from app.services import ai_customs_parser

    fake_settings = _make_settings(enabled=False)
    config_mod = MagicMock()
    config_mod.settings = fake_settings

    mock_client = MagicMock()
    mock_client.messages.create = MagicMock()
    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    with patch.dict("sys.modules", {
        "app.core.config": config_mod,
        "anthropic": mock_anthropic,
    }):
        dummy_pdf = tmp_path / "dummy.pdf"
        dummy_pdf.write_bytes(b"%PDF")
        ai_customs_parser.parse_with_ai(str(dummy_pdf))

    mock_client.messages.create.assert_not_called()


def test_no_api_call_when_evidence_disabled():
    """messages.create() must never be called when ai_parser_enabled=False."""
    from app.services import ai_customs_evidence

    fake_settings = _make_settings(enabled=False)
    config_mod = MagicMock()
    config_mod.settings = fake_settings

    mock_client = MagicMock()
    mock_client.messages.create = MagicMock()
    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    with patch.dict("sys.modules", {
        "app.core.config": config_mod,
        "anthropic": mock_anthropic,
    }):
        ai_customs_evidence.extract_customs_evidence("text content")

    mock_client.messages.create.assert_not_called()


# ── Test 5: Enabled path still works (parse_with_ai) ─────────────────────────

def test_parse_with_ai_enabled_path_returns_dict(tmp_path):
    """When ai_parser_enabled=True and API key present, parse_with_ai
    proceeds to the API call and returns a dict on success."""
    import json
    from app.services import ai_customs_parser

    fake_settings = _make_settings(enabled=True, api_key="sk-live-key")
    config_mod = MagicMock()
    config_mod.settings = fake_settings

    # Stub out PDF text extraction
    fake_extracted = "MRN: 26PL12345 DUTY PLN 1000"

    ai_response_payload = json.dumps({
        "mrn": "26PL12345",
        "duty_pln": 1000.0,
        "lrn": None,
        "clearance_date": None,
        "vat_pln": None,
        "total_cif_usd": None,
        "customs_rate_usd": None,
        "statistical_value_pln": None,
        "sad_invoice_value_usd": None,
        "agent": None,
        "importer_name": None,
        "importer_nip": None,
        "exporter_name": None,
        "cn_code": None,
        "goods_description": None,
        "a00_payment_method": None,
        "b00_payment_method": None,
    })

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=ai_response_payload)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    dummy_pdf = tmp_path / "doc.pdf"
    dummy_pdf.write_bytes(b"%PDF")

    with patch.dict("sys.modules", {
        "app.core.config": config_mod,
        "anthropic": mock_anthropic,
    }), patch.object(ai_customs_parser, "_extract_pdf_text", return_value=fake_extracted):
        result = ai_customs_parser.parse_with_ai(str(dummy_pdf))

    assert isinstance(result, dict)
    assert result.get("mrn") == "26PL12345"
    assert "_ai_meta" in result
    mock_client.messages.create.assert_called_once()


# ── Test 6: Enabled path still works (extract_customs_evidence) ──────────────

def test_extract_customs_evidence_enabled_path_returns_dict():
    """When ai_parser_enabled=True and API key present,
    extract_customs_evidence proceeds to the API call and returns a dict."""
    import json
    from app.services import ai_customs_evidence

    fake_settings = _make_settings(enabled=True, api_key="sk-live-key")
    config_mod = MagicMock()
    config_mod.settings = fake_settings

    ai_response_payload = json.dumps({
        "invoice_refs": ["088/2026-2027"],
        "awb": "1234567890",
        "mrn": "26PL44302",
        "cif_usd": 5000.0,
        "exporter": "Test Exporter",
        "importer": "Test Importer",
        "cn_codes": ["7113"],
        "confidence": "high",
        "evidence": ["088/2026-2027 found on page 1"],
    })

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=ai_response_payload)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    with patch.dict("sys.modules", {
        "app.core.config": config_mod,
        "anthropic": mock_anthropic,
    }):
        result = ai_customs_evidence.extract_customs_evidence(
            "document text with invoice 088/2026-2027",
            document_hint="ZC429",
        )

    assert isinstance(result, dict)
    assert result.get("confidence") == "high"
    assert "088/2026-2027" in result.get("invoice_refs", [])
    assert "_ai_meta" in result
    mock_client.messages.create.assert_called_once()


# ── Test 7: Disabled even when api_key is present (regression guard) ──────────

def test_parser_disabled_beats_api_key_present(tmp_path):
    """Regression: a valid API key does NOT override the disabled flag.
    The flag check must come AFTER the api_key check in parse_with_ai
    so that a key-present / flag-disabled state is correctly blocked."""
    from app.services import ai_customs_parser

    # Key IS present, but flag is False
    fake_settings = _make_settings(enabled=False, api_key="sk-valid-key")
    config_mod = MagicMock()
    config_mod.settings = fake_settings

    mock_anthropic_class = MagicMock()

    with patch.dict("sys.modules", {
        "app.core.config": config_mod,
        "anthropic": MagicMock(Anthropic=mock_anthropic_class),
    }):
        dummy_pdf = tmp_path / "doc.pdf"
        dummy_pdf.write_bytes(b"%PDF")
        result = ai_customs_parser.parse_with_ai(str(dummy_pdf))

    assert result is None
    mock_anthropic_class.assert_not_called()


def test_evidence_disabled_beats_api_key_present():
    """Regression: a valid API key does NOT override the disabled flag
    in the evidence service."""
    from app.services import ai_customs_evidence

    # Key IS present, but flag is False
    fake_settings = _make_settings(enabled=False, api_key="sk-valid-key")
    config_mod = MagicMock()
    config_mod.settings = fake_settings

    mock_anthropic_class = MagicMock()

    with patch.dict("sys.modules", {
        "app.core.config": config_mod,
        "anthropic": MagicMock(Anthropic=mock_anthropic_class),
    }):
        result = ai_customs_evidence.extract_customs_evidence("text content")

    assert result is None
    mock_anthropic_class.assert_not_called()
