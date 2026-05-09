"""
test_dhl_express_stub_adapter.py — DL-B fixture-only DHL adapter tests.

Required coverage:
  1. Adapter satisfies ``isinstance(adapter, CarrierAdapter)``.
  2. ``create_shipment`` returns deterministic AWB and raw response
     with ``stub: True``.
  3. ``fetch_label(..., "PDF")`` returns bytes starting ``%PDF``.
  4. ``fetch_label(..., "ZPL")`` returns bytes starting ``^XA``.
  5. Unsupported format fails explicitly via ``CarrierResponseError``.
  6. ``cancel_shipment`` returns successful ``RawCancelResponse``.
  7. ``parse_webhook_event`` maps JSON body into ``CarrierEvent``.
  8. Invalid webhook body deterministically raises
     ``CarrierResponseError``.
  9. ``schedule_pickup`` returns stub pickup metadata.
  10. Source-grep proves the stub file does not import ``requests``,
      ``httpx``, ``urllib``, or read ``os.environ``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.services.carrier import base as cb
from app.services.carrier.adapters import base as ab
from app.services.carrier.adapters.dhl_express_stub import (
    DHLExpressStubAdapter,
    SUPPORTED_LABEL_FORMATS,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def adapter() -> DHLExpressStubAdapter:
    return DHLExpressStubAdapter()


@pytest.fixture()
def sample_request() -> cb.CarrierShipmentRequest:
    addr_from = cb.CarrierAddress(
        name="Estrella Jewels",
        company="Estrella Jewels",
        street_1="ul. Marszalkowska 1",
        city="Warsaw",
        postal_code="00-001",
        country="PL",
    )
    addr_to = cb.CarrierAddress(
        name="John Doe",
        street_1="123 Main St",
        city="New York",
        postal_code="10001",
        country="US",
    )
    pkg = cb.PackageSpec(
        weight_kg=0.25,
        length_cm=15.0,
        width_cm=10.0,
        height_cm=5.0,
        declared_value=999.0,
        declared_currency="USD",
        description="Diamond pendant",
    )
    return cb.CarrierShipmentRequest(
        batch_id="BATCH-DL-B-001",
        ship_from=addr_from,
        ship_to=addr_to,
        packages=(pkg,),
        service_code="EXPRESS_WORLDWIDE",
        reference="OPERATOR-REF-42",
    )


# ── 1. Protocol satisfaction ────────────────────────────────────────────────

def test_stub_adapter_satisfies_protocol(adapter):
    assert isinstance(adapter, ab.CarrierAdapter)
    assert adapter.carrier == cb.CARRIER_DHL


# ── 2. create_shipment determinism ──────────────────────────────────────────

def test_create_shipment_returns_stub_response(adapter, sample_request):
    rsp = adapter.create_shipment(sample_request)
    assert isinstance(rsp, cb.RawShipmentResponse)
    assert rsp.carrier == cb.CARRIER_DHL
    assert rsp.label_format == "pdf"
    assert rsp.awb.startswith("DHLSTUB")
    assert len(rsp.awb) == len("DHLSTUB000000")
    # Deterministic AWB digits
    assert re.fullmatch(r"DHLSTUB\d{6}", rsp.awb)
    # raw response is clearly a stub
    assert rsp.raw.get("stub") is True
    assert rsp.raw.get("carrier") == cb.CARRIER_DHL
    assert rsp.raw.get("awb") == rsp.awb
    # Label bytes are present and shaped like a PDF
    assert rsp.label_bytes.startswith(b"%PDF")
    assert rsp.label_filename == f"{rsp.awb}.pdf"


def test_create_shipment_is_deterministic(adapter, sample_request):
    rsp_a = adapter.create_shipment(sample_request)
    rsp_b = adapter.create_shipment(sample_request)
    assert rsp_a.awb == rsp_b.awb
    assert rsp_a.label_bytes == rsp_b.label_bytes


def test_create_shipment_different_inputs_yield_different_awb(
    adapter, sample_request
):
    other = cb.CarrierShipmentRequest(
        batch_id="BATCH-OTHER",
        ship_from=sample_request.ship_from,
        ship_to=sample_request.ship_to,
        packages=sample_request.packages,
        service_code=sample_request.service_code,
        reference="DIFFERENT-REF",
    )
    a = adapter.create_shipment(sample_request)
    b = adapter.create_shipment(other)
    assert a.awb != b.awb


def test_create_shipment_rejects_empty_packages(adapter, sample_request):
    empty = cb.CarrierShipmentRequest(
        batch_id=sample_request.batch_id,
        ship_from=sample_request.ship_from,
        ship_to=sample_request.ship_to,
        packages=(),
    )
    with pytest.raises(ab.CarrierResponseError):
        adapter.create_shipment(empty)


def test_create_shipment_rejects_wrong_input_type(adapter):
    with pytest.raises(ab.CarrierResponseError):
        adapter.create_shipment({"batch_id": "X"})  # type: ignore[arg-type]


# ── 3-5. fetch_label ────────────────────────────────────────────────────────

def test_fetch_label_pdf_starts_with_magic(adapter):
    bytes_ = adapter.fetch_label("DHLSTUB000123", fmt="PDF")
    assert bytes_.startswith(b"%PDF")


def test_fetch_label_zpl_starts_with_xa(adapter):
    bytes_ = adapter.fetch_label("DHLSTUB000123", fmt="ZPL")
    assert bytes_.startswith(b"^XA")
    assert bytes_.endswith(b"^XZ")
    # AWB embedded in the label so it's clearly not a static fixture
    assert b"DHLSTUB000123" in bytes_


def test_fetch_label_default_format_is_pdf(adapter):
    bytes_ = adapter.fetch_label("DHLSTUB000123")
    assert bytes_.startswith(b"%PDF")


def test_fetch_label_unsupported_format_raises(adapter):
    with pytest.raises(ab.CarrierResponseError) as exc:
        adapter.fetch_label("DHLSTUB000123", fmt="png")
    msg = str(exc.value).lower()
    assert "png" in msg or "not supported" in msg


def test_fetch_label_supported_formats_constant():
    assert SUPPORTED_LABEL_FORMATS == frozenset({"pdf", "zpl"})
    # PNG must NOT be in the supported set per DL-B contract
    assert "png" not in SUPPORTED_LABEL_FORMATS


def test_fetch_label_blank_awb_raises(adapter):
    with pytest.raises(ab.CarrierResponseError):
        adapter.fetch_label("", fmt="pdf")


def test_fetch_label_is_deterministic_per_awb(adapter):
    a = adapter.fetch_label("DHLSTUB777777", fmt="pdf")
    b = adapter.fetch_label("DHLSTUB777777", fmt="pdf")
    assert a == b


# ── 6. cancel_shipment ──────────────────────────────────────────────────────

def test_cancel_shipment_accepts_normal_awb(adapter):
    rsp = adapter.cancel_shipment("DHLSTUB000123", reason="operator-cancel")
    assert isinstance(rsp, cb.RawCancelResponse)
    assert rsp.accepted is True
    assert rsp.carrier == cb.CARRIER_DHL
    assert rsp.awb == "DHLSTUB000123"
    assert rsp.raw.get("stub") is True


def test_cancel_shipment_default_reason(adapter):
    rsp = adapter.cancel_shipment("DHLSTUB000123")
    assert rsp.accepted is True
    assert rsp.reason  # non-empty


def test_cancel_shipment_blank_awb_raises(adapter):
    with pytest.raises(ab.CarrierResponseError):
        adapter.cancel_shipment("")


# ── 7. parse_webhook_event success ──────────────────────────────────────────

def test_parse_webhook_event_full_payload(adapter):
    body = json.dumps({
        "awb": "1234567890",
        "event_code": "in_transit",
        "occurred_at": "2026-04-12T10:15:00Z",
        "location": "Warsaw",
        "description": "Arrived at facility",
    }).encode("utf-8")
    ev = adapter.parse_webhook_event(body)
    assert isinstance(ev, cb.CarrierEvent)
    assert ev.carrier == cb.CARRIER_DHL
    assert ev.awb == "1234567890"
    assert ev.event_code == "in_transit"
    assert ev.occurred_at == "2026-04-12T10:15:00Z"
    assert ev.location == "Warsaw"
    assert ev.description == "Arrived at facility"
    assert ev.raw.get("stub") is True
    assert ev.raw.get("original")["awb"] == "1234567890"


def test_parse_webhook_event_minimal_payload(adapter):
    body = json.dumps({
        "awb": "1234567890",
        "event_code": "delivered",
    }).encode("utf-8")
    ev = adapter.parse_webhook_event(body)
    assert ev.event_code == "delivered"
    assert ev.location == ""
    assert ev.description == ""
    assert ev.occurred_at == ""


def test_parse_webhook_event_headers_visibility(adapter):
    body = json.dumps({"awb": "X", "event_code": "delivered"}).encode("utf-8")
    ev_with = adapter.parse_webhook_event(body, headers={"x-sig": "abc"})
    ev_without = adapter.parse_webhook_event(body)
    assert ev_with.raw["headers_seen"] is True
    assert ev_without.raw["headers_seen"] is False


# ── 8. parse_webhook_event invalid bodies ───────────────────────────────────

@pytest.mark.parametrize("bad_body", [
    b"",
    b"not json",
    b"<xml>not json</xml>",
])
def test_parse_webhook_event_invalid_raises(adapter, bad_body):
    with pytest.raises(ab.CarrierResponseError):
        adapter.parse_webhook_event(bad_body)


def test_parse_webhook_event_array_raises(adapter):
    with pytest.raises(ab.CarrierResponseError) as exc:
        adapter.parse_webhook_event(b"[]")
    assert "object" in str(exc.value).lower()


def test_parse_webhook_event_missing_awb_raises(adapter):
    body = json.dumps({"event_code": "delivered"}).encode("utf-8")
    with pytest.raises(ab.CarrierResponseError) as exc:
        adapter.parse_webhook_event(body)
    assert "awb" in str(exc.value).lower()


def test_parse_webhook_event_missing_event_code_raises(adapter):
    body = json.dumps({"awb": "1234567890"}).encode("utf-8")
    with pytest.raises(ab.CarrierResponseError) as exc:
        adapter.parse_webhook_event(body)
    assert "event_code" in str(exc.value).lower()


def test_parse_webhook_event_none_body_raises(adapter):
    with pytest.raises(ab.CarrierResponseError):
        adapter.parse_webhook_event(None)  # type: ignore[arg-type]


# ── 9. schedule_pickup ──────────────────────────────────────────────────────

def test_schedule_pickup_returns_stub_metadata(adapter):
    result = adapter.schedule_pickup(
        "DHLSTUB000123",
        when_iso="2026-04-13T14:00:00Z",
        location={"address": "ul. Marszalkowska 1, Warsaw"},
    )
    assert result["stub"] is True
    assert result["carrier"] == cb.CARRIER_DHL
    assert result["awb"] == "DHLSTUB000123"
    assert result["when_iso"] == "2026-04-13T14:00:00Z"
    assert result["confirmation_number"].startswith("STUB-")
    assert result["location"] == {"address": "ul. Marszalkowska 1, Warsaw"}


def test_schedule_pickup_is_deterministic(adapter):
    a = adapter.schedule_pickup("DHLSTUB000123", when_iso="2026-04-13T14:00:00Z")
    b = adapter.schedule_pickup("DHLSTUB000123", when_iso="2026-04-13T14:00:00Z")
    assert a["confirmation_number"] == b["confirmation_number"]


def test_schedule_pickup_blank_awb_raises(adapter):
    with pytest.raises(ab.CarrierResponseError):
        adapter.schedule_pickup("", when_iso="2026-04-13T14:00:00Z")


def test_schedule_pickup_blank_when_raises(adapter):
    with pytest.raises(ab.CarrierResponseError):
        adapter.schedule_pickup("DHLSTUB000123", when_iso="")


def test_schedule_pickup_no_location(adapter):
    result = adapter.schedule_pickup(
        "DHLSTUB000123", when_iso="2026-04-13T14:00:00Z",
    )
    assert result["location"] == {}


# ── 10. Source-grep: no HTTP / no env reads ────────────────────────────────

_STUB_PATH = (
    Path(__file__).resolve().parents[1]
    / "app" / "services" / "carrier" / "adapters" / "dhl_express_stub.py"
)


@pytest.fixture(scope="module")
def stub_src() -> str:
    return _STUB_PATH.read_text(encoding="utf-8")


@pytest.mark.parametrize("forbidden", [
    "import requests",
    "from requests",
    "import httpx",
    "from httpx",
    "import urllib",
    "from urllib",
    # DHL SDKs (no widely-used official Python SDK, but defend against
    # a future common name landing without review):
    "import dhl",
    "from dhl",
])
def test_stub_does_not_import_http_clients(stub_src, forbidden):
    assert forbidden not in stub_src, (
        f"DHLExpressStubAdapter source must not contain {forbidden!r}. "
        f"The stub is fixture-only by contract."
    )


@pytest.mark.parametrize("forbidden", [
    "os.environ",
    "os.getenv",
    "getenv(",
])
def test_stub_does_not_read_env(stub_src, forbidden):
    assert forbidden not in stub_src, (
        f"DHLExpressStubAdapter source must not read environment "
        f"variables ({forbidden!r}). Credentials and config belong in "
        f"the live adapter, not the stub."
    )


def test_stub_does_not_touch_disk(stub_src):
    """The stub must not open files on disk. Check for the obvious
    Python file-I/O entry points in the source."""
    for forbidden in [
        "open(",
        "Path(",
        ".write_text(", ".write_bytes(",
        ".read_text(", ".read_bytes(",
        "tempfile",
    ]:
        assert forbidden not in stub_src, (
            f"DHLExpressStubAdapter source must not touch disk "
            f"({forbidden!r})."
        )
