"""Sanitize wFirma upstream failures for operator-facing HTTP details.

Never return third-party HTML/XML bodies or unbounded exception text to the
browser. Full diagnostics stay in server logs at the call site.
"""
from __future__ import annotations

import re
from typing import Tuple

_HTML_RE = re.compile(r"(?i)<!DOCTYPE|<html[\s>]|<head[\s>]|<body[\s>]")
_TAG_RE = re.compile(r"<[^>]+>")


def sanitize_wfirma_read_error(exc: BaseException) -> Tuple[str, str, bool]:
    """Return (code, operator_message, retryable).

    ``code`` is stable for UI branching; ``operator_message`` is human-readable
    and free of HTML / stack dumps.
    """
    raw = str(exc) if exc is not None else ""
    low = raw.lower()
    name = type(exc).__name__

    if isinstance(exc, ValueError) and ("not configured" in low or "credential" in low):
        return (
            "credentials_not_configured",
            "wFirma API credentials are not configured on this server. "
            "Retrying will not help until an operator configures them.",
            False,
        )

    if _HTML_RE.search(raw) or ("cloudflare" in low and "<" in raw):
        if "502" in raw or "bad gateway" in low:
            return (
                "upstream_502",
                "wFirma temporarily unavailable (HTTP 502). Wait a moment, then retry.",
                True,
            )
        if "503" in raw:
            return (
                "upstream_503",
                "wFirma temporarily unavailable (HTTP 503). Wait a moment, then retry.",
                True,
            )
        return (
            "upstream_html_error",
            "wFirma temporarily unavailable. Wait a moment, then retry.",
            True,
        )

    if "http 502" in low or " 502" in low:
        return (
            "upstream_502",
            "wFirma temporarily unavailable (HTTP 502). Wait a moment, then retry.",
            True,
        )
    if "http 503" in low:
        return (
            "upstream_503",
            "wFirma temporarily unavailable (HTTP 503). Wait about a minute, then retry.",
            True,
        )
    if isinstance(exc, (ConnectionError, TimeoutError)) or "timeout" in low:
        return (
            "upstream_unreachable",
            "wFirma is temporarily unreachable (network/timeout). Wait, then retry.",
            True,
        )

    cleaned = _TAG_RE.sub(" ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > 160:
        cleaned = cleaned[:157] + "…"
    if not cleaned:
        cleaned = f"wFirma read failed ({name}). Retry shortly."
        return ("upstream_error", cleaned, True)
    return ("upstream_error", f"wFirma read failed: {cleaned}", True)


def operator_detail_for_exc(exc: BaseException) -> str:
    """Single string suitable for FastAPI HTTPException.detail."""
    _code, message, _retry = sanitize_wfirma_read_error(exc)
    return message
