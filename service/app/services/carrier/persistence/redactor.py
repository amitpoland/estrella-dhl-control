"""
CarrierResponseRedactor — strips sensitive fields from DHL API payloads
before any persistence, then validates the result is free of binary remnants.

Strip rules (applied recursively through dicts and lists):
  1. Keys indicating binary/label content:
       labelData, pdfData, shipmentLabel, labelImage, content
       and any key ending in 'Data', 'Bytes', or 'Base64'.
  2. Keys indicating credentials:
       apiKey, api_key, password, secret, token, accessToken,
       access_token, clientSecret, client_secret, refreshToken, refresh_token.
  3. LIVE mode only — DHL tracking identifiers:
       trackingNumber, awbNumber, shipmentTrackingNumber,
       masterTrackingNumber, pieceTrackingNumber.

Post-strip validation (defense-in-depth):
  After stripping, every remaining string value is scanned. Any value that
  is suspiciously long (>= _MIN_SUSPICIOUS_LEN chars) AND consists of
  >= _BASE64_RATIO_THRESHOLD base64 characters — or that starts with the
  PDF magic header — raises RedactionError. This catches unknown DHL field
  names that slip through the key-based strip rules.

Pure function — no I/O, no side effects, no imports from app services.
"""
from __future__ import annotations

import copy
from typing import Any

from ..models.shipment import ShipmentMode

# ── strip tables ──────────────────────────────────────────────────────────────

_BINARY_KEYS: frozenset[str] = frozenset(
    {
        "labelData",
        "pdfData",
        "shipmentLabel",
        "labelImage",
        "content",
    }
)

_BINARY_SUFFIXES: tuple[str, ...] = ("Data", "Bytes", "Base64")

_CREDENTIAL_KEYS: frozenset[str] = frozenset(
    {
        "apiKey",
        "api_key",
        "password",
        "secret",
        "token",
        "accessToken",
        "access_token",
        "clientSecret",
        "client_secret",
        "refreshToken",
        "refresh_token",
    }
)

_LIVE_TRACKING_KEYS: frozenset[str] = frozenset(
    {
        "trackingNumber",
        "awbNumber",
        "shipmentTrackingNumber",
        "masterTrackingNumber",
        "pieceTrackingNumber",
    }
)

# ── post-strip validation constants ───────────────────────────────────────────

# Strings shorter than this are never suspicious regardless of content.
_MIN_SUSPICIOUS_LEN: int = 512

# If >= this fraction of characters are base64-valid, the string is binary-like.
_BASE64_RATIO_THRESHOLD: float = 0.95

# Characters valid in standard and URL-safe base64 (including padding).
_BASE64_ALPHABET: frozenset[str] = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=_-"
)

# PDF magic bytes (ASCII).
_PDF_HEADER: str = "%PDF-"


# ── public exceptions ─────────────────────────────────────────────────────────


class RedactionError(Exception):
    """
    Raised when a suspicious binary or credential value survives redaction.

    This indicates either a new DHL field name not in the strip tables, or
    a structural change in the DHL API response. The payload must NOT be
    persisted. Callers should log the error and discard the payload.
    """


# ── private helpers ───────────────────────────────────────────────────────────


def _is_binary_key(key: str) -> bool:
    if key in _BINARY_KEYS:
        return True
    return any(key.endswith(suffix) for suffix in _BINARY_SUFFIXES)


def _is_suspicious_large_string(value: str) -> bool:
    """Return True if the string looks like unredacted binary data."""
    if value.startswith(_PDF_HEADER):
        return True
    if len(value) < _MIN_SUSPICIOUS_LEN:
        return False
    base64_count = sum(1 for c in value if c in _BASE64_ALPHABET)
    return (base64_count / len(value)) >= _BASE64_RATIO_THRESHOLD


def _redact_node(node: Any, mode: ShipmentMode) -> Any:
    if isinstance(node, dict):
        out: dict = {}
        for k, v in node.items():
            if _is_binary_key(k):
                out[k] = "[REDACTED:binary]"
            elif k in _CREDENTIAL_KEYS:
                out[k] = "[REDACTED:credential]"
            elif mode == ShipmentMode.LIVE and k in _LIVE_TRACKING_KEYS:
                out[k] = "[REDACTED:live-awb]"
            else:
                out[k] = _redact_node(v, mode)
        return out
    if isinstance(node, list):
        return [_redact_node(item, mode) for item in node]
    return node


def _validate_no_binary_remnants(node: Any, path: str = "$") -> None:
    """
    Recursively scan a post-redaction payload for suspicious values.
    Raises RedactionError if any string looks like unredacted binary data.
    """
    if isinstance(node, dict):
        for k, v in node.items():
            _validate_no_binary_remnants(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _validate_no_binary_remnants(item, f"{path}[{i}]")
    elif isinstance(node, str):
        if _is_suspicious_large_string(node):
            raise RedactionError(
                f"Suspicious binary-like value detected at {path} "
                f"(length={len(node)}). A DHL API field name may be missing "
                "from the redactor strip tables. Do not persist this payload."
            )


# ── public API ────────────────────────────────────────────────────────────────


def redact_response(payload: dict, mode: ShipmentMode) -> dict:
    """
    Return a deep-copied payload with all sensitive fields replaced.

    Always strips binary and credential fields.
    In LIVE mode, also strips DHL tracking identifiers.

    Raises RedactionError if a suspicious large binary-like string survives
    stripping (defense-in-depth against unknown DHL field names).
    """
    result = _redact_node(copy.deepcopy(payload), mode)
    _validate_no_binary_remnants(result)
    return result
