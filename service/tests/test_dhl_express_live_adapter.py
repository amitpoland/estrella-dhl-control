"""
test_dhl_express_live_adapter.py — DL-F1 live-adapter HTTP behaviour
tests (mocked HTTP only).

Required:
  * create_shipment happy path with fake client returns
    RawShipmentResponse.
  * create_shipment sends Basic auth.
  * create_shipment maps fields into DHL body.
  * create_shipment decodes PDF label.
  * Missing tracking number / missing label content raises
    CarrierResponseError.
  * 401 / 403 raise CarrierAuthError.
  * 429 raises CarrierRateLimitError.
  * Transport exception raises CarrierTransportError after retry budget.
  * 5xx retries then raises CarrierResponseError.
  * cancel 200/204 accepted=True.
  * cancel 409 accepted=False.
  * fetch_label PDF / ZPL return decoded bytes.
  * fetch_label PNG raises CarrierResponseError.
  * schedule_pickup returns confirmation dict.
  * Source-grep proves no os.environ / requests / urllib reads.
  * Source-grep proves Authorization header is not printed/logged.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest

from app.services.carrier.adapters import base as ab
from app.services.carrier.adapters.dhl_express_live import (
    DHLExpressLiveAdapter,
)
from app.services.carrier.base import (
    CARRIER_DHL,
    CarrierAddress,
    CarrierShipmentRequest,
    PackageSpec,
    RawCancelResponse,
    RawShipmentResponse,
)


_LIVE_FILE = (
    Path(__file__).resolve().parents[1]
    / "app" / "services" / "carrier" / "adapters" / "dhl_express_live.py"
)


@pytest.fixture(scope="module")
def live_src() -> str:
    return _LIVE_FILE.read_text(encoding="utf-8")


# ── Fake HTTP client + response ────────────────────────────────────────────

class FakeResponse:
    """Minimal httpx.Response surface used by tests."""

    def __init__(
        self, status_code: int, body=None, headers=None, text=None,
    ):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self.text = text if text is not None else (
            "" if body is None else __import__("json").dumps(body)
        )

    def json(self):
        if self._body is None:
            raise ValueError("no JSON body")
        return self._body


class FakeClient:
    """Test double for httpx.Client.

    queue items can be:
      * FakeResponse — returned in order
      * Exception — raised when the call lands
    """

    def __init__(self, queue):
        self._queue = list(queue)
        self.calls = []

    def request(self, method, url, *, json=None, params=None,
                auth=None, timeout=None):
        self.calls.append({
            "method": method, "url": url,
            "json": json, "params": params,
            "auth": auth, "timeout": timeout,
        })
        if not self._queue:
            raise RuntimeError(
                f"FakeClient queue exhausted; last call={self.calls[-1]!r}"
            )
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# ── Helpers to build request payloads ──────────────────────────────────────

def _addr(country="PL"):
    return CarrierAddress(
        name="Estrella", company="Estrella", street_1="ul. M. 1",
        city="Warsaw", postal_code="00-001", country=country,
    )


def _shipment_request():
    return CarrierShipmentRequest(
        batch_id="B-LIVE-1",
        ship_from=_addr("PL"), ship_to=_addr("US"),
        packages=(PackageSpec(
            weight_kg=0.5, length_cm=15, width_cm=10, height_cm=5,
            declared_value=999.0, declared_currency="USD",
            description="Test pendant",
        ),),
        service_code="P", reference="R-LIVE-1",
    )


def _make_adapter(http_client, *, daily_limit=500, sleep=None,
                  max_retries=3) -> DHLExpressLiveAdapter:
    return DHLExpressLiveAdapter(
        base_url="https://example.test/mydhlapi",
        username="u", password="p", account_number="ACC-1",
        http_client=http_client,
        sleep=sleep or (lambda _s: None),
        daily_limit=daily_limit,
        max_retries=max_retries,
    )


def _label_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n% live-adapter test\n%%EOF\n"


def _label_zpl_bytes() -> bytes:
    return b"^XA^FO50,50^A0N,30,30^FDtest^FS^XZ"


def _create_shipment_response(awb="1234567890",
                               label_bytes=None) -> dict:
    label_bytes = label_bytes or _label_pdf_bytes()
    return {
        "shipmentTrackingNumber": awb,
        "documents": [{
            "imageFormat": "PDF",
            "content":     base64.b64encode(label_bytes).decode("ascii"),
        }],
        "packages": [{"trackingNumber": awb + "-1"}],
    }


# ── 1-5. create_shipment ───────────────────────────────────────────────────

def test_create_shipment_happy_path_returns_raw_shipment_response():
    fake = FakeClient([FakeResponse(201, _create_shipment_response())])
    adapter = _make_adapter(fake)
    rsp = adapter.create_shipment(_shipment_request())
    assert isinstance(rsp, RawShipmentResponse)
    assert rsp.carrier == CARRIER_DHL
    assert rsp.awb == "1234567890"
    assert rsp.label_format == "pdf"
    assert rsp.label_filename == "1234567890.pdf"
    assert rsp.label_bytes.startswith(b"%PDF")
    assert rsp.raw["shipmentTrackingNumber"] == "1234567890"


def test_create_shipment_sends_basic_auth_tuple():
    fake = FakeClient([FakeResponse(201, _create_shipment_response())])
    adapter = _make_adapter(fake)
    adapter.create_shipment(_shipment_request())
    call = fake.calls[0]
    assert call["auth"] == ("u", "p")
    assert call["method"] == "POST"
    assert call["url"].endswith("/shipments")
    # Bonus: timeout was set
    assert call["timeout"] == 4.0


def test_create_shipment_maps_request_fields_into_dhl_body():
    fake = FakeClient([FakeResponse(201, _create_shipment_response())])
    adapter = _make_adapter(fake)
    adapter.create_shipment(_shipment_request())
    body = fake.calls[0]["json"]
    assert body["productCode"] == "P"
    assert body["accounts"][0]["number"] == "ACC-1"
    assert body["customerDetails"]["shipperDetails"]["postalAddress"]["countryCode"] == "PL"
    assert body["customerDetails"]["receiverDetails"]["postalAddress"]["countryCode"] == "US"
    refs = {r["value"] for r in body["customerReferences"]}
    assert "B-LIVE-1" in refs
    assert "R-LIVE-1" in refs


def test_create_shipment_decodes_pdf_label():
    payload = _create_shipment_response(label_bytes=b"%PDF-1.4 fake")
    fake = FakeClient([FakeResponse(201, payload)])
    adapter = _make_adapter(fake)
    rsp = adapter.create_shipment(_shipment_request())
    assert rsp.label_bytes == b"%PDF-1.4 fake"


def test_create_shipment_missing_tracking_number_raises():
    payload = {"documents": [{"imageFormat": "PDF",
                              "content": base64.b64encode(b"%PDF").decode()}]}
    fake = FakeClient([FakeResponse(201, payload)])
    adapter = _make_adapter(fake)
    with pytest.raises(ab.CarrierResponseError):
        adapter.create_shipment(_shipment_request())


def test_create_shipment_missing_documents_raises():
    payload = {"shipmentTrackingNumber": "AAA"}
    fake = FakeClient([FakeResponse(201, payload)])
    adapter = _make_adapter(fake)
    with pytest.raises(ab.CarrierResponseError):
        adapter.create_shipment(_shipment_request())


def test_create_shipment_empty_label_content_raises():
    payload = {"shipmentTrackingNumber": "AAA",
                "documents": [{"imageFormat": "PDF", "content": ""}]}
    fake = FakeClient([FakeResponse(201, payload)])
    adapter = _make_adapter(fake)
    with pytest.raises(ab.CarrierResponseError):
        adapter.create_shipment(_shipment_request())


def test_create_shipment_non_base64_label_raises():
    payload = {"shipmentTrackingNumber": "AAA",
                "documents": [{"imageFormat": "PDF", "content": "***not-b64***"}]}
    fake = FakeClient([FakeResponse(201, payload)])
    adapter = _make_adapter(fake)
    with pytest.raises(ab.CarrierResponseError):
        adapter.create_shipment(_shipment_request())


# ── 6-10. Error mapping ───────────────────────────────────────────────────

def test_401_raises_carrier_auth_error():
    fake = FakeClient([FakeResponse(401, {"detail": "bad creds"})])
    adapter = _make_adapter(fake)
    with pytest.raises(ab.CarrierAuthError):
        adapter.create_shipment(_shipment_request())


def test_403_raises_carrier_auth_error():
    fake = FakeClient([FakeResponse(403, {"detail": "forbidden"})])
    adapter = _make_adapter(fake)
    with pytest.raises(ab.CarrierAuthError):
        adapter.create_shipment(_shipment_request())


def test_429_raises_carrier_rate_limit_error_after_retries():
    fake = FakeClient([
        FakeResponse(429, {"detail": "slow down"}, headers={"Retry-After": "0"}),
        FakeResponse(429, {"detail": "slow down"}, headers={"Retry-After": "0"}),
        FakeResponse(429, {"detail": "slow down"}, headers={"Retry-After": "0"}),
        FakeResponse(429, {"detail": "slow down"}, headers={"Retry-After": "0"}),
    ])
    adapter = _make_adapter(fake, max_retries=3)
    with pytest.raises(ab.CarrierRateLimitError):
        adapter.create_shipment(_shipment_request())
    # 4 attempts: 1 initial + 3 retries
    assert len(fake.calls) == 4


def test_429_succeeds_after_retry_window():
    fake = FakeClient([
        FakeResponse(429, {}, headers={"Retry-After": "0"}),
        FakeResponse(201, _create_shipment_response()),
    ])
    adapter = _make_adapter(fake, max_retries=3)
    rsp = adapter.create_shipment(_shipment_request())
    assert rsp.awb == "1234567890"


def test_transport_exception_after_retry_budget():
    fake = FakeClient([
        ConnectionError("net down"),
        ConnectionError("net down"),
        ConnectionError("net down"),
        ConnectionError("net down"),
    ])
    adapter = _make_adapter(fake, max_retries=3)
    with pytest.raises(ab.CarrierTransportError):
        adapter.create_shipment(_shipment_request())


def test_5xx_retries_then_raises_carrier_response_error():
    fake = FakeClient([
        FakeResponse(500, {"detail": "boom"}),
        FakeResponse(503, {"detail": "boom"}),
        FakeResponse(502, {"detail": "boom"}),
        FakeResponse(500, {"detail": "boom"}),
    ])
    adapter = _make_adapter(fake, max_retries=3)
    with pytest.raises(ab.CarrierResponseError):
        adapter.create_shipment(_shipment_request())


def test_5xx_succeeds_after_retry_window():
    fake = FakeClient([
        FakeResponse(500, {}),
        FakeResponse(503, {}),
        FakeResponse(201, _create_shipment_response()),
    ])
    adapter = _make_adapter(fake, max_retries=3)
    rsp = adapter.create_shipment(_shipment_request())
    assert rsp.awb == "1234567890"


def test_4xx_other_than_auth_or_rate_limit_raises_response_error():
    fake = FakeClient([FakeResponse(400, {"detail": "bad request"})])
    adapter = _make_adapter(fake)
    with pytest.raises(ab.CarrierResponseError):
        adapter.create_shipment(_shipment_request())


# ── 11-13. Cancel ────────────────────────────────────────────────────────

def test_cancel_200_returns_accepted_true():
    fake = FakeClient([FakeResponse(200, {"deleted": True})])
    adapter = _make_adapter(fake)
    rsp = adapter.cancel_shipment("DHLAWB1", reason="operator-cancel")
    assert isinstance(rsp, RawCancelResponse)
    assert rsp.accepted is True
    assert rsp.awb == "DHLAWB1"
    # DELETE method, awb in path, requestorName in params
    call = fake.calls[0]
    assert call["method"] == "DELETE"
    assert call["url"].endswith("/shipments/DHLAWB1")
    assert call["params"]["requestorName"] == "operator-cancel"


def test_cancel_204_returns_accepted_true_with_empty_body():
    fake = FakeClient([FakeResponse(204, None)])
    adapter = _make_adapter(fake)
    rsp = adapter.cancel_shipment("DHLAWB2")
    assert rsp.accepted is True


def test_cancel_409_returns_accepted_false_no_exception():
    fake = FakeClient([FakeResponse(409, {"detail": "in-transit",
                                            "title": "conflict"})])
    adapter = _make_adapter(fake)
    rsp = adapter.cancel_shipment("DHLAWB3")
    assert rsp.accepted is False
    assert "in-transit" in rsp.reason or "conflict" in rsp.reason


def test_cancel_404_returns_accepted_false_no_exception():
    fake = FakeClient([FakeResponse(404, {"detail": "not found"})])
    adapter = _make_adapter(fake)
    rsp = adapter.cancel_shipment("DHLAWB4")
    assert rsp.accepted is False


def test_cancel_500_after_retry_raises():
    fake = FakeClient([
        FakeResponse(500, {}), FakeResponse(500, {}),
        FakeResponse(500, {}), FakeResponse(500, {}),
    ])
    adapter = _make_adapter(fake, max_retries=3)
    with pytest.raises(ab.CarrierResponseError):
        adapter.cancel_shipment("DHLAWB5")


# ── 14-16. fetch_label ───────────────────────────────────────────────────

def test_fetch_label_pdf_returns_bytes_starting_pdf():
    payload = {"documents": [{
        "imageFormat": "PDF",
        "content":     base64.b64encode(_label_pdf_bytes()).decode(),
    }]}
    fake = FakeClient([FakeResponse(200, payload)])
    adapter = _make_adapter(fake)
    out = adapter.fetch_label("DHLAWB1", fmt="pdf")
    assert out.startswith(b"%PDF")
    # Verified the request shape too
    call = fake.calls[0]
    assert call["method"] == "GET"
    assert call["url"].endswith("/shipments/DHLAWB1/image")
    assert call["params"]["typeCode"] == "label"
    assert call["params"]["imageFormat"] == "PDF"


def test_fetch_label_zpl_returns_bytes_starting_xa():
    payload = {"documents": [{
        "imageFormat": "ZPL",
        "content":     base64.b64encode(_label_zpl_bytes()).decode(),
    }]}
    fake = FakeClient([FakeResponse(200, payload)])
    adapter = _make_adapter(fake)
    out = adapter.fetch_label("DHLAWB1", fmt="zpl")
    assert out.startswith(b"^XA")


@pytest.mark.parametrize("bad_fmt", ["png", "tiff", "jpg", "weird"])
def test_fetch_label_unsupported_format_raises(bad_fmt):
    fake = FakeClient([])
    adapter = _make_adapter(fake)
    with pytest.raises(ab.CarrierResponseError):
        adapter.fetch_label("DHLAWB1", fmt=bad_fmt)
    # No HTTP call made
    assert fake.calls == []


def test_fetch_label_404_raises():
    fake = FakeClient([FakeResponse(404, {"detail": "label gone"})])
    adapter = _make_adapter(fake)
    with pytest.raises(ab.CarrierResponseError):
        adapter.fetch_label("DHLAWB1", fmt="pdf")


def test_fetch_label_blank_awb_raises():
    fake = FakeClient([])
    adapter = _make_adapter(fake)
    with pytest.raises(ab.CarrierResponseError):
        adapter.fetch_label("", fmt="pdf")


# ── 17. schedule_pickup ──────────────────────────────────────────────────

def test_schedule_pickup_returns_confirmation_dict():
    payload = {
        "dispatchConfirmationNumbers": ["PWP-12345"],
        "readyByTime": "2026-04-15T10:00:00",
    }
    fake = FakeClient([FakeResponse(201, payload)])
    adapter = _make_adapter(fake)
    out = adapter.schedule_pickup(
        "DHLAWB1",
        when_iso="2026-04-15T10:00:00",
        location={"address": "ul. M. 1, Warsaw"},
    )
    assert out["dispatchConfirmationNumbers"] == ["PWP-12345"]
    call = fake.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/pickups")
    assert call["json"]["consignmentNumber"] == "DHLAWB1"
    assert call["json"]["pickupAddress"]["address"] == "ul. M. 1, Warsaw"


def test_schedule_pickup_blank_awb_raises():
    fake = FakeClient([])
    adapter = _make_adapter(fake)
    with pytest.raises(ab.CarrierResponseError):
        adapter.schedule_pickup("", when_iso="2026-04-15T10:00:00")


def test_schedule_pickup_blank_when_raises():
    fake = FakeClient([])
    adapter = _make_adapter(fake)
    with pytest.raises(ab.CarrierResponseError):
        adapter.schedule_pickup("DHLAWB1", when_iso="")


# ── Source-grep guards ──────────────────────────────────────────────────

@pytest.mark.parametrize("forbidden", [
    "os.environ", "os.getenv", "getenv(",
])
def test_live_adapter_source_no_env_reads(live_src, forbidden):
    assert forbidden not in live_src, (
        f"dhl_express_live.py contains {forbidden!r} — credentials "
        f"must arrive only via the constructor."
    )


@pytest.mark.parametrize("forbidden", [
    "import requests", "from requests",
    "import urllib", "from urllib",
])
def test_live_adapter_source_no_requests_or_urllib(live_src, forbidden):
    assert forbidden not in live_src, (
        f"dhl_express_live.py contains {forbidden!r} — only httpx is "
        f"the documented HTTP client for this adapter."
    )


def test_live_adapter_does_not_print_or_log_authorization(live_src):
    """Pinned by DL-F1 spec rule 31. Authorization header is built
    (via httpx auth tuple) but must never be printed or logged.

    We scan every line for "Authorization" and reject any line that
    also references print(/log./logger. — that's the concrete leak
    vector we care about. The class-level type-hint and the auth
    tuple itself never carry the literal token "Authorization", so
    a clean implementation passes.
    """
    leak_callsite_tokens = ("print(", "log.", "logger.")
    for line in live_src.splitlines():
        if "Authorization" not in line:
            continue
        # Comments are fine — DL-F1 docstring may discuss the header.
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith('"""'):
            continue
        # Module docstring lines mentioning Authorization for design
        # rationale don't have leak-callsite tokens, so the next test
        # passes them through.
        for token in leak_callsite_tokens:
            assert token not in line, (
                f"dhl_express_live.py contains a leak vector: line "
                f"references {token!r} alongside 'Authorization'.\n"
                f"line: {line!r}"
            )


def test_live_adapter_quota_helper_imported(live_src):
    """Sanity: the adapter actually wires the quota helper, not just
    declares the field."""
    assert "from .dhl_express_quota import DHLDailyQuota" in live_src
    assert "self._quota.consume_or_raise()" in live_src


# ── DL-F3 — Paperless Trade live-adapter behaviour ──────────────────────

def _shipment_request_with_plt(pdf_path: str):
    """Reuse the helper from this file with a PLT path supplied."""
    return CarrierShipmentRequest(
        batch_id="B-LIVE-PLT",
        ship_from=_addr("PL"), ship_to=_addr("US"),
        packages=(PackageSpec(
            weight_kg=0.5, length_cm=15, width_cm=10, height_cm=5,
            declared_value=100.0, declared_currency="USD",
        ),),
        service_code="P", reference="R-LIVE-PLT",
        customs_invoice_pdf_path=pdf_path,
    )


def _write_pdf(tmp_path, name: str, content: bytes):
    p = tmp_path / name
    p.write_bytes(content)
    return p


def _make_plt_adapter(http_client, *, plt_enabled: bool = True):
    return DHLExpressLiveAdapter(
        base_url="https://example.test/mydhlapi",
        username="u", password="p", account_number="ACC-1",
        http_client=http_client,
        sleep=lambda _s: None,
        max_retries=3,
        paperless_trade_enabled=plt_enabled,
    )


def test_create_shipment_with_valid_plt_records_metadata_in_raw(tmp_path):
    pdf_bytes = b"%PDF-1.4\ndl-f3 valid plt content\n%%EOF\n"
    pdf_path = _write_pdf(tmp_path, "ok.pdf", pdf_bytes)

    fake = FakeClient([FakeResponse(201, _create_shipment_response())])
    adapter = _make_plt_adapter(fake)
    rsp = adapter.create_shipment(_shipment_request_with_plt(str(pdf_path)))

    raw = rsp.raw
    assert raw["paperless_trade_requested"] is True
    assert raw["paperless_trade_attached"]  is True
    assert raw["paperless_trade_reason"]    == "ok"
    assert raw["paperless_trade_document_filename"] == "ok.pdf"
    assert raw["paperless_trade_document_size"]     == len(pdf_bytes)
    import hashlib
    assert raw["paperless_trade_document_sha256"] == \
        hashlib.sha256(pdf_bytes).hexdigest()


def test_create_shipment_with_oversize_plt_skips_attachment(tmp_path):
    big_pdf = b"%PDF-1.4\n" + (b"X" * (5 * 1024 * 1024 + 1)) + b"\n%%EOF\n"
    pdf_path = _write_pdf(tmp_path, "big.pdf", big_pdf)

    fake = FakeClient([FakeResponse(201, _create_shipment_response())])
    adapter = _make_plt_adapter(fake)
    rsp = adapter.create_shipment(_shipment_request_with_plt(str(pdf_path)))

    assert rsp.raw["paperless_trade_attached"] is False
    assert rsp.raw["paperless_trade_reason"]   == "oversize"
    # And the request body must NOT carry documentImages
    body = fake.calls[0]["json"]
    assert "documentImages" not in body
    assert "exportDeclaration" not in body["content"]


def test_create_shipment_with_bad_magic_skips_attachment(tmp_path):
    not_pdf = b"\x89PNG\r\n\x1a\n" + b"actually a png"
    pdf_path = _write_pdf(tmp_path, "fake.pdf", not_pdf)

    fake = FakeClient([FakeResponse(201, _create_shipment_response())])
    adapter = _make_plt_adapter(fake)
    rsp = adapter.create_shipment(_shipment_request_with_plt(str(pdf_path)))

    assert rsp.raw["paperless_trade_attached"] is False
    assert rsp.raw["paperless_trade_reason"]   == "not_pdf"
    assert "documentImages" not in fake.calls[0]["json"]


def test_create_shipment_with_missing_plt_file_skips_attachment(tmp_path):
    fake = FakeClient([FakeResponse(201, _create_shipment_response())])
    adapter = _make_plt_adapter(fake)
    rsp = adapter.create_shipment(_shipment_request_with_plt(
        str(tmp_path / "missing.pdf"),
    ))
    assert rsp.raw["paperless_trade_attached"] is False
    assert rsp.raw["paperless_trade_reason"]   == "file_not_found"


def test_create_shipment_with_plt_flag_disabled_skips_attachment(tmp_path):
    pdf_path = _write_pdf(tmp_path, "ok.pdf", b"%PDF-1.4 valid\n%%EOF\n")

    fake = FakeClient([FakeResponse(201, _create_shipment_response())])
    adapter = _make_plt_adapter(fake, plt_enabled=False)
    rsp = adapter.create_shipment(_shipment_request_with_plt(str(pdf_path)))

    assert rsp.raw["paperless_trade_requested"] is True
    assert rsp.raw["paperless_trade_attached"]  is False
    assert rsp.raw["paperless_trade_reason"]    == "flag_disabled"
    assert "documentImages" not in fake.calls[0]["json"]


def test_create_shipment_without_plt_path_records_not_requested():
    """Default path: no PLT field on the request → adapter records
    requested=False / attached=False / reason=not_requested."""
    fake = FakeClient([FakeResponse(201, _create_shipment_response())])
    adapter = _make_plt_adapter(fake)
    rsp = adapter.create_shipment(_shipment_request())  # no PLT path
    assert rsp.raw["paperless_trade_requested"] is False
    assert rsp.raw["paperless_trade_attached"]  is False
    assert rsp.raw["paperless_trade_reason"]    == "not_requested"


def test_pdf_bytes_never_appear_in_response_raw(tmp_path):
    """Strongest invariant — the source PDF bytes never land in
    RawShipmentResponse.raw. Only sha256 + size + boolean + filename."""
    sentinel = b"%PDF-1.4 SECRET-PLT-BODY-DO-NOT-LEAK"
    pdf_path = _write_pdf(tmp_path, "secret.pdf", sentinel + b"\n%%EOF\n")

    fake = FakeClient([FakeResponse(201, _create_shipment_response())])
    adapter = _make_plt_adapter(fake)
    rsp = adapter.create_shipment(_shipment_request_with_plt(str(pdf_path)))

    import json as _json
    serialised = _json.dumps(rsp.raw, default=str)
    assert "SECRET-PLT-BODY" not in serialised


def test_live_adapter_source_no_print_log_documentImages(live_src):
    """Extends the Authorization-leak guard to the new PLT
    base64 carrier field name."""
    leak_tokens = ("print(", "log.", "logger.")
    for line in live_src.splitlines():
        if "documentImages" not in line:
            continue
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith('"""'):
            continue
        for token in leak_tokens:
            assert token not in line, (
                f"live adapter leaks documentImages through {token!r}: {line!r}"
            )
