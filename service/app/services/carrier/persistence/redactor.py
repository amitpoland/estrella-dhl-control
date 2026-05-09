"""
CarrierResponseRedactor — strips sensitive fields from DHL API payloads
before any persistence.

Rules (applied in order, recursively through dicts and lists):
  1. Remove keys whose names indicate binary/label content:
       labelData, pdfData, shipmentLabel, labelImage, content
       and any key ending in 'Data', 'Bytes', or 'Base64'.
  2. Remove keys that look like credentials:
       apiKey, api_key, password, secret, token, accessToken,
       access_token, clientSecret, client_secret.
  3. In LIVE mode only — remove DHL tracking identifiers:
       trackingNumber, awbNumber, shipmentTrackingNumber,
       masterTrackingNumber, pieceTrackingNumber.
       These must never appear in the shadow log.

Pure function — no I/O, no side effects, no imports from app services.
"""
from __future__ import annotations

import copy
from typing import Any

from ..models.shipment import ShipmentMode

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


def _is_binary_key(key: str) -> bool:
    if key in _BINARY_KEYS:
        return True
    return any(key.endswith(suffix) for suffix in _BINARY_SUFFIXES)


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


def redact_response(payload: dict, mode: ShipmentMode) -> dict:
    """
    Return a deep copy of payload with sensitive fields replaced.

    Always strips binary and credential fields.
    In LIVE mode, also strips DHL tracking identifiers.
    """
    return _redact_node(copy.deepcopy(payload), mode)
