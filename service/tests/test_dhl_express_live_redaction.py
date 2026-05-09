"""
test_dhl_express_live_redaction.py — DL-F3.5b phase tests.

Pins two redaction guarantees the live adapter must hold before any
production cutover:

1. ``_summarise()`` strips sensitive keys from DHL response echoes
   before they reach operator-facing exception messages or shadow-log
   live_error_summary columns.
2. ``_parse_one_shipment()`` does NOT inline the full shipment dict
   into ``CarrierEvent.raw``. Only the parsed
   (awb, event_code, occurred_at, location, description) plus a
   minimal carrier identifier are persisted; PII (addresses, declared
   values, recipient names) stays in request memory only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.services.carrier.adapters import base as ab
from app.services.carrier.adapters.dhl_express_live import (
    DHLExpressLiveAdapter,
    _SENSITIVE_KEYS_LOWER,
)


_LIVE_FILE = (
    Path(__file__).resolve().parents[1]
    / "app" / "services" / "carrier" / "adapters" / "dhl_express_live.py"
)


@pytest.fixture(scope="module")
def live_src() -> str:
    return _LIVE_FILE.read_text(encoding="utf-8")


# ── _summarise() redaction ────────────────────────────────────────────────

def test_summarise_redacts_authorization_header():
    payload = {
        "detail": "request rejected",
        "echo": {
            "headers": {
                "Authorization": "Basic dXNlcjpwYXNzd29yZA==",
                "Content-Type": "application/json",
            },
        },
    }
    out = DHLExpressLiveAdapter._summarise(payload)
    assert "<redacted>" in out
    assert "dXNlcjpwYXNzd29yZA==" not in out
    assert "Content-Type" in out  # non-sensitive keys preserved


def test_summarise_redacts_account_number():
    payload = {"detail": "billing", "accountNumber": "123456789"}
    out = DHLExpressLiveAdapter._summarise(payload)
    assert "123456789" not in out
    assert "<redacted>" in out


def test_summarise_redacts_snake_case_account_number():
    payload = {"echo": {"account_number": "987654321"}}
    out = DHLExpressLiveAdapter._summarise(payload)
    assert "987654321" not in out


def test_summarise_redacts_password():
    payload = {"creds": {"password": "hunter2"}}
    out = DHLExpressLiveAdapter._summarise(payload)
    assert "hunter2" not in out


def test_summarise_redacts_secret():
    payload = {"webhook": {"secret": "secret-XYZ-do-not-leak"}}
    out = DHLExpressLiveAdapter._summarise(payload)
    assert "secret-XYZ-do-not-leak" not in out


def test_summarise_redacts_documentImages_base64():
    """PLT base64 lives under documentImages[].content. The
    "content" key is in the deny set; an entire documentImages list
    can be deeply nested and still must redact."""
    payload = {
        "echo": {
            "documentImages": [
                {"typeCode": "INV", "imageFormat": "PDF",
                 "content": "JVBERi0xLjQKJSDH...JVBERi-LONG-BASE64"},
            ],
        },
    }
    out = DHLExpressLiveAdapter._summarise(payload)
    assert "JVBERi-LONG-BASE64" not in out
    assert "<redacted>" in out


def test_summarise_redacts_signature_name():
    payload = {"signatureName": "Estrella Jewels"}
    out = DHLExpressLiveAdapter._summarise(payload)
    assert "Estrella Jewels" not in out


def test_summarise_preserves_non_sensitive_fields():
    payload = {
        "detail": "validation failed",
        "validationMessages": ["packageWeight is required"],
        "shipmentTrackingNumber": "1234567890",
    }
    out = DHLExpressLiveAdapter._summarise(payload)
    assert "validation failed" in out
    assert "packageWeight" in out
    assert "1234567890" in out


def test_summarise_truncates_long_summaries():
    payload = {"detail": "x" * 500}
    out = DHLExpressLiveAdapter._summarise(payload)
    assert len(out) == 200
    assert out.endswith("...")


def test_summarise_handles_lists_of_dicts():
    payload = [
        {"Authorization": "Basic LEAK"},
        {"normal": "value"},
    ]
    out = DHLExpressLiveAdapter._summarise(payload)
    assert "LEAK" not in out
    assert "<redacted>" in out
    assert "normal" in out


def test_summarise_handles_non_dict_payload():
    """Non-dict / non-list payloads (strings, numbers) pass through
    truncation without error."""
    out = DHLExpressLiveAdapter._summarise("plain error string")
    assert "plain error string" in out
    out2 = DHLExpressLiveAdapter._summarise(42)
    assert "42" in out2
    out3 = DHLExpressLiveAdapter._summarise(None)
    assert out3  # something stringifiable


def test_summarise_handles_deeply_nested_redaction():
    payload = {
        "a": {"b": {"c": {"Authorization": "Basic SHALLOW-OK"}}},
    }
    out = DHLExpressLiveAdapter._summarise(payload)
    assert "SHALLOW-OK" not in out


def test_summarise_recursion_bounded():
    """Construct a self-referential structure (via a placeholder).
    The scrubber's depth cap prevents unbounded recursion / overflow."""
    deep: dict = {}
    cur = deep
    for _ in range(20):
        cur["nested"] = {}
        cur = cur["nested"]
    # No exception
    out = DHLExpressLiveAdapter._summarise(deep)
    assert isinstance(out, str)


def test_sensitive_keys_constant_lowercase_only():
    """The deny set is compared lowercased; keys must therefore be
    lowercased in the constant."""
    for k in _SENSITIVE_KEYS_LOWER:
        assert k == k.lower()


# ── parse_one_shipment redaction ──────────────────────────────────────────

def _push_envelope_shipment(awb="1234", status_code="transit",
                              extra_pii=None):
    s = {
        "id":      awb,
        "service": "express",
        "status": {
            "timestamp":   "2026-04-12T10:15:00Z",
            "location":    "Warsaw",
            "statusCode":  status_code,
            "status":      "in transit",
            "description": "moving",
        },
    }
    if extra_pii:
        s.update(extra_pii)
    return s


def test_parse_webhook_event_does_not_persist_full_shipment_dict():
    adapter = DHLExpressLiveAdapter()  # parse-only (no creds)
    pii = {
        "recipientName": "Confidential Person",
        "recipientAddress": {
            "street": "123 Secret Lane",
            "city":   "PrivateCity",
        },
        "declaredValue": 999_999.99,
    }
    body = json.dumps(_push_envelope_shipment(extra_pii=pii)).encode()
    ev = adapter.parse_webhook_event(body)
    raw_json = json.dumps(ev.raw, default=str)
    # PII must NOT appear in the persisted raw
    assert "Confidential Person" not in raw_json
    assert "123 Secret Lane" not in raw_json
    assert "PrivateCity" not in raw_json
    assert "999999.99" not in raw_json
    assert "999_999.99" not in raw_json
    # The minimal subset is preserved on the dataclass fields
    assert ev.awb == "1234"
    assert ev.event_code == "transit"
    assert ev.location == "Warsaw"


def test_parse_webhook_event_raw_only_contains_safe_keys():
    adapter = DHLExpressLiveAdapter()
    body = json.dumps(_push_envelope_shipment()).encode()
    ev = adapter.parse_webhook_event(body)
    # raw is intentionally narrow now
    raw_keys = set(ev.raw.keys())
    assert "shipment" not in raw_keys, (
        "DL-F3.5b: full shipment dict must NOT be persisted on raw"
    )
    # Allowlist of keys the redacted raw may carry
    allowed = {"live", "carrier", "headers_seen", "service"}
    assert raw_keys.issubset(allowed), (
        f"raw carries unexpected keys: {raw_keys - allowed}"
    )


def test_parse_push_payload_drops_full_shipments_too():
    adapter = DHLExpressLiveAdapter()
    body = json.dumps({
        "shipments": [
            _push_envelope_shipment(awb="A", extra_pii={"recipientName": "Alice"}),
            _push_envelope_shipment(awb="B", extra_pii={"recipientName": "Bob"}),
        ],
    }).encode()
    events, dropped = adapter.parse_push_payload(body)
    assert dropped == 0
    assert len(events) == 2
    for ev in events:
        raw_json = json.dumps(ev.raw, default=str)
        assert "Alice" not in raw_json
        assert "Bob" not in raw_json


# ── Source-grep guards ────────────────────────────────────────────────────

def test_source_no_dict_shipment_persistence(live_src):
    """The pre-DL-F3.5b code wrote `dict(shipment)` into raw. Pin
    its absence so a future contributor cannot regress."""
    assert "dict(shipment)" not in live_src, (
        "DL-F3.5b: full shipment dict must NOT be inlined into "
        "CarrierEvent.raw — that's a PII leak path"
    )


def test_summarise_still_truncates(live_src):
    """The truncation behaviour is unchanged by DL-F3.5b — pin
    the 200-char cap survives the redaction rewrite."""
    assert "[:197]" in live_src
    assert "+ \"...\"" in live_src or "\"...\"" in live_src


def test_sensitive_keys_constant_present_at_module_level(live_src):
    assert "_SENSITIVE_KEYS_LOWER" in live_src
    assert "authorization" in live_src.lower()
    assert "accountnumber" in live_src.lower() or "account_number" in live_src
