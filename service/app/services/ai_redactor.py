"""
ai_redactor.py — Strip credentials and secrets from AI prompt text.

Applied by ai_gateway.py before every external API call.
Pure function — no I/O, no network, no side effects.

Scope: credentials / tokens that must never leave the application boundary.
Not in scope: customer business names, invoice refs, MRN/AWB values — those
are the content the AI must analyse and must not be redacted.
"""
from __future__ import annotations

import re
from typing import List, Tuple

# Each rule: (compiled_pattern, replacement_string)
_RULES: List[Tuple[re.Pattern, str]] = [
    # Anthropic API keys  sk-ant-api03-…
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}", re.ASCII), "[API_KEY]"),
    # Generic sk- keys (OpenAI, etc.)
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b", re.ASCII), "[API_KEY]"),
    # Bearer authorization tokens
    (re.compile(r"Bearer\s+[A-Za-z0-9_\-\.=+/]{20,}", re.IGNORECASE), "Bearer [TOKEN]"),
    # Inline credential assignments  password=secret123  api_key: abc
    (
        re.compile(
            r"(?i)(?:password|passwd|api[_\-]?key|apikey|secret|access[_\-]token"
            r"|refresh[_\-]token|client[_\-]secret)\s*[=:]\s*\S{8,}"
        ),
        "[CREDENTIAL]",
    ),
    # Internal Estrella staff email addresses
    (re.compile(r"\b[a-zA-Z0-9._%+\-]+@(?:estrellajewels|stellajewels|simpleks|brainportal)\.(?:eu|com|pl)\b", re.IGNORECASE), "[INTERNAL_EMAIL]"),
]


def redact(text: str) -> str:
    """Return a copy of *text* with credential patterns masked.

    Idempotent — applying twice produces the same result.
    Never raises — on any error returns the original text unchanged.
    """
    if not text:
        return text
    try:
        for pattern, replacement in _RULES:
            text = pattern.sub(replacement, text)
        return text
    except Exception:
        return text


def redact_pair(system: str, user: str) -> tuple[str, str]:
    """Redact both system and user prompt strings and return the pair."""
    return redact(system), redact(user)
