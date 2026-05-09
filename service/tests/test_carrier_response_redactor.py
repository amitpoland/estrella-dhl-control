"""
Phase B tests — CarrierResponseRedactor.

Verifies that labelData, pdfData, credentials, and (in live mode)
tracking identifiers are stripped. Also verifies:
- deep copy semantics (original payload not mutated)
- recursive redaction through nested dicts and lists
- shadow mode preserves tracking refs (they are simulated, not real)
"""
import pytest

from app.services.carrier.models.shipment import ShipmentMode
from app.services.carrier.persistence.redactor import redact_response


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
