"""
test_ai_redactor.py — Unit tests for ai_redactor.py.

Verifies credential masking without touching customer/customs data.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services.ai_redactor import redact, redact_pair


# ── API key masking ───────────────────────────────────────────────────────────

def test_anthropic_key_masked():
    text = "My key is sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz12345"
    result = redact(text)
    assert "sk-ant-api03" not in result
    assert "[API_KEY]" in result


def test_generic_sk_key_masked():
    text = "OpenAI key: sk-AbCdEfGhIjKlMnOpQrStUvWxYz12345"
    result = redact(text)
    assert "AbCdEfGhIjKlMnOpQrStUvWxYz12345" not in result
    assert "[API_KEY]" in result


def test_bearer_token_masked():
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature"
    result = redact(text)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result
    assert "[TOKEN]" in result


# ── Credential assignment masking ─────────────────────────────────────────────

def test_password_assignment_masked():
    text = "password=SuperSecret123"
    result = redact(text)
    assert "SuperSecret123" not in result
    assert "[CREDENTIAL]" in result


def test_api_key_colon_assignment_masked():
    text = "api_key: sk_live_abcdefghijklmnop"
    result = redact(text)
    assert "sk_live_abcdefghijklmnop" not in result
    assert "[CREDENTIAL]" in result


def test_access_token_masked():
    text = "access_token=someVeryLongToken12345678"
    result = redact(text)
    assert "someVeryLongToken12345678" not in result
    assert "[CREDENTIAL]" in result


# ── Internal email masking ────────────────────────────────────────────────────

def test_internal_email_masked():
    text = "Sent by tejal@estrellajewels.eu for batch processing"
    result = redact(text)
    assert "tejal@estrellajewels.eu" not in result
    assert "[INTERNAL_EMAIL]" in result


def test_other_internal_domain_masked():
    text = "Contact admin@simpleks.eu for support"
    result = redact(text)
    assert "admin@simpleks.eu" not in result
    assert "[INTERNAL_EMAIL]" in result


# ── Customs data NOT masked ───────────────────────────────────────────────────

def test_mrn_not_masked():
    """MRN numbers must NOT be redacted — the AI needs them."""
    text = "MRN: 26PL44302D00A1J5R7"
    result = redact(text)
    assert "26PL44302D00A1J5R7" in result


def test_invoice_ref_not_masked():
    """Invoice refs must NOT be redacted — the AI needs them."""
    text = "Invoice reference: 088/2026-2027"
    result = redact(text)
    assert "088/2026-2027" in result


def test_cif_value_not_masked():
    """CIF values must NOT be redacted — the AI needs them."""
    text = "Total CIF value: USD 15000.00"
    result = redact(text)
    assert "15000.00" in result


def test_customer_company_not_masked():
    """Customer company names must NOT be redacted."""
    text = "Importer: DiamondGroup GmbH, Exporter: Estrella Jewels Ltd"
    result = redact(text)
    assert "DiamondGroup GmbH" in result


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_empty_string_safe():
    assert redact("") == ""


def test_none_like_empty_safe():
    assert redact("   ") == "   "


def test_idempotent():
    text = "password=secret123 sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWx"
    once = redact(text)
    twice = redact(once)
    assert once == twice


def test_redact_pair_returns_both():
    system = "password=abc12345678"
    user   = "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz12345"
    s, u = redact_pair(system, user)
    assert "abc12345678" not in s
    assert "AbCdEfGhIjKlMnOpQrStUvWxYz12345" not in u
