"""
Phase B + E tests — CarrierResponseRedactor.

Phase B: labelData, pdfData, credentials, live AWB stripping, recursion, immutability.
Phase E: fail-loud hardening — RedactionError on suspicious large binary remnants.
"""
import base64
import os

import pytest

from app.services.carrier.models.shipment import ShipmentMode
from app.services.carrier.persistence.redactor import (
    RedactionError,
    _is_suspicious_large_string,
    redact_response,
)


# ── binary field stripping (both modes) ──────────────────────────────────────


def test_label_data_stripped_shadow():
    payload = {"labelData": "base64==", "status": "ok"}
    result = redact_response(payload, ShipmentMode.SHADOW)
    assert result["labelData"] == "[REDACTED:binary]"
    assert result["status"] == "ok"


def test_label_data_stripped_live():
    payload = {"labelData": "base64=="}
    result = redact_response(payload, ShipmentMode.LIVE)
    assert result["labelData"] == "[REDACTED:binary]"


def test_pdf_data_stripped():
    payload = {"pdfData": "abc123", "other": "keep"}
    result = redact_response(payload, ShipmentMode.SHADOW)
    assert result["pdfData"] == "[REDACTED:binary]"
    assert result["other"] == "keep"


def test_shipment_label_stripped():
    payload = {"shipmentLabel": "bytes"}
    assert redact_response(payload, ShipmentMode.SHADOW)["shipmentLabel"] == "[REDACTED:binary]"


def test_label_image_stripped():
    payload = {"labelImage": "bytes"}
    assert redact_response(payload, ShipmentMode.SHADOW)["labelImage"] == "[REDACTED:binary]"


def test_dynamic_suffix_data_stripped():
    payload = {"someFieldData": "bytes", "otherBytes": "raw", "thirdBase64": "=="}
    result = redact_response(payload, ShipmentMode.SHADOW)
    assert result["someFieldData"] == "[REDACTED:binary]"
    assert result["otherBytes"] == "[REDACTED:binary]"
    assert result["thirdBase64"] == "[REDACTED:binary]"


# ── credential stripping (both modes) ────────────────────────────────────────


def test_api_key_stripped():
    payload = {"apiKey": "secret123", "endpoint": "https://example.com"}
    result = redact_response(payload, ShipmentMode.SHADOW)
    assert result["apiKey"] == "[REDACTED:credential]"
    assert result["endpoint"] == "https://example.com"


def test_password_stripped():
    assert redact_response({"password": "pw"}, ShipmentMode.SHADOW)["password"] == "[REDACTED:credential]"


def test_token_stripped():
    assert redact_response({"token": "tok"}, ShipmentMode.LIVE)["token"] == "[REDACTED:credential]"


def test_access_token_variants_stripped():
    payload = {"accessToken": "t1", "access_token": "t2"}
    result = redact_response(payload, ShipmentMode.SHADOW)
    assert result["accessToken"] == "[REDACTED:credential]"
    assert result["access_token"] == "[REDACTED:credential]"


# ── live AWB stripping (live mode only) ──────────────────────────────────────


def test_tracking_number_stripped_in_live():
    payload = {"trackingNumber": "1234567890", "status": "ok"}
    result = redact_response(payload, ShipmentMode.LIVE)
    assert result["trackingNumber"] == "[REDACTED:live-awb]"
    assert result["status"] == "ok"


def test_awb_number_stripped_in_live():
    assert redact_response({"awbNumber": "AWB-X"}, ShipmentMode.LIVE)["awbNumber"] == "[REDACTED:live-awb]"


def test_shipment_tracking_number_stripped_in_live():
    key = "shipmentTrackingNumber"
    assert redact_response({key: "X"}, ShipmentMode.LIVE)[key] == "[REDACTED:live-awb]"


def test_tracking_number_preserved_in_shadow():
    """Shadow refs are simulated — they are safe to log."""
    payload = {"trackingNumber": "SIM-0001"}
    result = redact_response(payload, ShipmentMode.SHADOW)
    assert result["trackingNumber"] == "SIM-0001"


def test_awb_number_preserved_in_shadow():
    payload = {"awbNumber": "SIM-AWB-001"}
    result = redact_response(payload, ShipmentMode.SHADOW)
    assert result["awbNumber"] == "SIM-AWB-001"


# ── recursion ─────────────────────────────────────────────────────────────────


def test_nested_dict_redacted():
    payload = {"shipment": {"labelData": "bytes", "weight": 1.5}}
    result = redact_response(payload, ShipmentMode.SHADOW)
    assert result["shipment"]["labelData"] == "[REDACTED:binary]"
    assert result["shipment"]["weight"] == 1.5


def test_list_of_dicts_redacted():
    payload = {"pieces": [{"labelData": "b1"}, {"labelData": "b2"}]}
    result = redact_response(payload, ShipmentMode.SHADOW)
    for piece in result["pieces"]:
        assert piece["labelData"] == "[REDACTED:binary]"


def test_deeply_nested_live_awb_stripped():
    payload = {"data": {"shipment": {"trackingNumber": "AWB-REAL"}}}
    result = redact_response(payload, ShipmentMode.LIVE)
    assert result["data"]["shipment"]["trackingNumber"] == "[REDACTED:live-awb]"


# ── immutability ──────────────────────────────────────────────────────────────


def test_original_payload_not_mutated():
    """redact_response must return a deep copy, not modify in place."""
    payload = {"labelData": "bytes", "status": "ok"}
    original_label = payload["labelData"]
    redact_response(payload, ShipmentMode.SHADOW)
    assert payload["labelData"] == original_label


def test_non_sensitive_fields_unchanged():
    payload = {"carrier": "DHL", "weight": 2.3, "currency": "EUR", "count": 5}
    result = redact_response(payload, ShipmentMode.LIVE)
    assert result == payload


# ── Phase E: _is_suspicious_large_string unit tests ──────────────────────────


def _large_b64(byte_count: int = 1024) -> str:
    """Return a base64 string derived from random bytes (always >= 512 chars)."""
    return base64.b64encode(os.urandom(byte_count)).decode()


def test_suspicious_large_b64_detected():
    assert _is_suspicious_large_string(_large_b64(1024)) is True


def test_suspicious_short_b64_not_detected():
    # 8 chars — well under _MIN_SUSPICIOUS_LEN
    assert _is_suspicious_large_string("abc123==") is False


def test_suspicious_pdf_header_detected_regardless_of_length():
    assert _is_suspicious_large_string("%PDF-1.4 short") is True


def test_suspicious_pdf_header_detected_in_long_string():
    assert _is_suspicious_large_string("%PDF-1.4" + "x" * 600) is True


def test_normal_text_not_suspicious():
    text = "This is a perfectly normal description with spaces, punctuation, and unicode: ę ó ą."
    assert _is_suspicious_large_string(text) is False


def test_long_text_with_spaces_not_suspicious():
    # A long string full of spaces and common chars — low base64 ratio
    text = ("The quick brown fox jumps over the lazy dog. " * 20)
    assert _is_suspicious_large_string(text) is False


def test_url_not_suspicious():
    url = "https://express.api.dhl.com/shipments/tracking?awb=1234567890&lang=en" * 3
    assert _is_suspicious_large_string(url) is False


def test_long_base64_just_over_threshold_detected():
    # Exactly 513 chars of base64 alphabet chars (over _MIN_SUSPICIOUS_LEN=512)
    value = "A" * 513
    assert _is_suspicious_large_string(value) is True


def test_long_base64_just_under_threshold_not_detected():
    # 511 chars — one under the threshold
    value = "A" * 511
    assert _is_suspicious_large_string(value) is False


# ── Phase E: redact_response fail-loud on unknown binary fields ───────────────


def test_unknown_field_with_large_b64_raises_redaction_error():
    """Defense-in-depth: unknown DHL field name carrying label bytes must raise."""
    payload = {"status": "ok", "dhlEncodedDocument": _large_b64()}
    with pytest.raises(RedactionError):
        redact_response(payload, ShipmentMode.SHADOW)


def test_unknown_field_with_large_b64_raises_in_live_mode():
    payload = {"responseCode": "200", "newDhlBinaryField": _large_b64()}
    with pytest.raises(RedactionError):
        redact_response(payload, ShipmentMode.LIVE)


def test_pdf_header_in_unknown_field_raises():
    payload = {"documentContent": "%PDF-1.4 binary content here and more bytes"}
    with pytest.raises(RedactionError):
        redact_response(payload, ShipmentMode.SHADOW)


def test_redaction_error_message_contains_field_path():
    payload = {"outer": {"inner": {"unknownBlobField": _large_b64()}}}
    with pytest.raises(RedactionError) as exc:
        redact_response(payload, ShipmentMode.SHADOW)
    assert "outer" in str(exc.value) or "inner" in str(exc.value) or "unknownBlobField" in str(exc.value)


def test_redaction_error_message_does_not_contain_blob_value():
    """Error must never echo the binary content back — it could be huge."""
    blob = _large_b64(512)
    payload = {"escapedBlob": blob}
    with pytest.raises(RedactionError) as exc:
        redact_response(payload, ShipmentMode.SHADOW)
    assert blob not in str(exc.value)


def test_unknown_b64_in_nested_list_raises():
    payload = {"pieces": [{"pieceLabelEncoded": _large_b64()}]}
    with pytest.raises(RedactionError):
        redact_response(payload, ShipmentMode.SHADOW)


def test_unknown_b64_deeply_nested_raises():
    payload = {"shipment": {"label": {"rawEncodedBlob": _large_b64()}}}
    with pytest.raises(RedactionError):
        redact_response(payload, ShipmentMode.SHADOW)


# ── Phase E: known keys strip before validation (no false RedactionError) ─────


def test_known_label_data_with_large_b64_does_not_raise():
    """labelData is stripped before validation — no RedactionError expected."""
    payload = {"labelData": _large_b64(), "status": "ok"}
    result = redact_response(payload, ShipmentMode.SHADOW)
    assert result["labelData"] == "[REDACTED:binary]"


def test_known_pdf_data_with_large_b64_does_not_raise():
    payload = {"pdfData": _large_b64()}
    result = redact_response(payload, ShipmentMode.SHADOW)
    assert result["pdfData"] == "[REDACTED:binary]"


def test_suffix_matched_large_b64_does_not_raise():
    """someNewFieldData matches the *Data suffix — stripped before validation."""
    payload = {"someNewFieldData": _large_b64()}
    result = redact_response(payload, ShipmentMode.SHADOW)
    assert result["someNewFieldData"] == "[REDACTED:binary]"


def test_suffix_bytes_large_b64_does_not_raise():
    payload = {"rawBinaryBytes": _large_b64()}
    result = redact_response(payload, ShipmentMode.SHADOW)
    assert result["rawBinaryBytes"] == "[REDACTED:binary]"


def test_credential_with_large_b64_does_not_raise():
    """token is a credential key — stripped before validation."""
    payload = {"token": _large_b64()}
    result = redact_response(payload, ShipmentMode.SHADOW)
    assert result["token"] == "[REDACTED:credential]"


def test_live_tracking_key_with_long_value_does_not_raise():
    """trackingNumber is stripped in live mode before validation."""
    # A tracking number won't realistically be huge, but confirm order of operations.
    payload = {"trackingNumber": "A" * 600}
    result = redact_response(payload, ShipmentMode.LIVE)
    assert result["trackingNumber"] == "[REDACTED:live-awb]"


# ── Phase E: persistence safety — no binary in normal shadow log payloads ─────


def test_typical_shadow_response_passes_validation():
    """A real-world-shaped shadow response must pass without RedactionError."""
    payload = {
        "idempotency_key": "a" * 64,      # hex string, not base64 — ratio check passes
        "mode": "shadow",
        "state": "submitted",
        "tracking_ref": "SIM-ABCD1234",
        "error": None,
        "simulated": True,
    }
    result = redact_response(payload, ShipmentMode.SHADOW)
    assert result["mode"] == "shadow"


def test_hex_idempotency_key_does_not_trigger_validation():
    """64-char hex strings are in base64 alphabet but under the threshold (64 < 512)."""
    key = "a" * 64
    assert _is_suspicious_large_string(key) is False
