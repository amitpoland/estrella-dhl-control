"""
test_dhl_express_live_adapter_retry.py — DL-F1 retry / quota tests.

Required:
  * 429 retry sequence backs off correctly (sleep is invoked).
  * Transport-error retry budget is bounded; raises after.
  * Daily counter resets on UTC midnight (injected clock).
  * Daily counter exhaustion raises CarrierRateLimitError without an
    HTTP call.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.services.carrier.adapters import base as ab
from app.services.carrier.adapters.dhl_express_live import (
    DHLExpressLiveAdapter,
)
from app.services.carrier.adapters.dhl_express_quota import DHLDailyQuota
from app.services.carrier.base import (
    CarrierAddress, CarrierShipmentRequest, PackageSpec,
)


class FakeResponse:
    def __init__(self, status_code, body=None, headers=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self.text = "" if body is None else __import__("json").dumps(body)
    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


class FakeClient:
    def __init__(self, queue):
        self._queue = list(queue)
        self.calls = []
    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if not self._queue:
            raise RuntimeError("FakeClient queue exhausted")
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _addr(country="PL"):
    return CarrierAddress(name="x", street_1="x", city="x",
                           postal_code="0", country=country)


def _req():
    return CarrierShipmentRequest(
        batch_id="B-RETRY", ship_from=_addr("PL"), ship_to=_addr("US"),
        packages=(PackageSpec(weight_kg=1, length_cm=1, width_cm=1,
                               height_cm=1),),
        service_code="P",
    )


def _make_adapter(fake, *, sleep, daily_limit=500, max_retries=3,
                  clock=None) -> DHLExpressLiveAdapter:
    return DHLExpressLiveAdapter(
        base_url="https://example.test/mydhlapi",
        username="u", password="p", account_number="ACC",
        http_client=fake,
        sleep=sleep,
        daily_limit=daily_limit,
        max_retries=max_retries,
        clock=clock,
    )


def _create_response(awb="W"):
    import base64
    return {
        "shipmentTrackingNumber": awb,
        "documents": [{
            "imageFormat": "PDF",
            "content":     base64.b64encode(b"%PDF").decode(),
        }],
    }


# ── 429 retry sequence ─────────────────────────────────────────────────────

def test_429_retry_sequence_invokes_sleep():
    sleeps = []
    fake = FakeClient([
        FakeResponse(429, headers={"Retry-After": "0"}),
        FakeResponse(429, headers={"Retry-After": "0"}),
        FakeResponse(201, _create_response()),
    ])
    adapter = _make_adapter(fake, sleep=sleeps.append, max_retries=3)
    rsp = adapter.create_shipment(_req())
    assert rsp.awb == "W"
    # Sleep was called twice (once per retry before the 201 succeeded)
    assert len(sleeps) == 2


def test_429_retry_after_header_drives_sleep_duration():
    """Adapter uses the Retry-After header value when present."""
    sleeps = []
    fake = FakeClient([
        FakeResponse(429, headers={"Retry-After": "2.5"}),
        FakeResponse(201, _create_response()),
    ])
    adapter = _make_adapter(fake, sleep=sleeps.append, max_retries=3)
    adapter.create_shipment(_req())
    assert sleeps == [2.5]


def test_429_retry_after_missing_falls_back_to_one_second():
    sleeps = []
    fake = FakeClient([
        FakeResponse(429, headers={}),
        FakeResponse(201, _create_response()),
    ])
    adapter = _make_adapter(fake, sleep=sleeps.append, max_retries=3)
    adapter.create_shipment(_req())
    assert sleeps == [1.0]


def test_429_retry_after_malformed_falls_back_to_one_second():
    sleeps = []
    fake = FakeClient([
        FakeResponse(429, headers={"Retry-After": "definitely-not-a-number"}),
        FakeResponse(201, _create_response()),
    ])
    adapter = _make_adapter(fake, sleep=sleeps.append, max_retries=3)
    adapter.create_shipment(_req())
    assert sleeps == [1.0]


# ── Transport-error retry budget ──────────────────────────────────────────

def test_transport_retry_budget_invokes_sleep_3_times_then_raises():
    sleeps = []
    fake = FakeClient([
        ConnectionError("net 1"),
        ConnectionError("net 2"),
        ConnectionError("net 3"),
        ConnectionError("net 4"),
    ])
    adapter = _make_adapter(fake, sleep=sleeps.append, max_retries=3)
    with pytest.raises(ab.CarrierTransportError):
        adapter.create_shipment(_req())
    # 4 attempts, 3 retries → sleep called 3 times
    assert len(sleeps) == 3


def test_transport_succeeds_within_retry_budget():
    sleeps = []
    fake = FakeClient([
        ConnectionError("net 1"),
        FakeResponse(201, _create_response()),
    ])
    adapter = _make_adapter(fake, sleep=sleeps.append, max_retries=3)
    rsp = adapter.create_shipment(_req())
    assert rsp.awb == "W"
    assert len(sleeps) == 1


# ── Daily quota ──────────────────────────────────────────────────────────

def test_quota_resets_on_utc_date_change():
    today = date(2026, 4, 1)
    fake_today = [today]

    quota = DHLDailyQuota(
        daily_limit=2,
        clock=lambda: fake_today[0],
    )
    quota.consume_or_raise()
    quota.consume_or_raise()
    # Day 1 exhausted
    with pytest.raises(ab.CarrierRateLimitError):
        quota.consume_or_raise()

    # Roll the clock to day 2
    fake_today[0] = today + timedelta(days=1)
    # Should be allowed again
    quota.consume_or_raise()
    quota.consume_or_raise()
    with pytest.raises(ab.CarrierRateLimitError):
        quota.consume_or_raise()


def test_quota_remaining_today_counts_correctly():
    today = date(2026, 4, 1)
    quota = DHLDailyQuota(daily_limit=5, clock=lambda: today)
    assert quota.remaining_today() == 5
    quota.consume_or_raise()
    assert quota.remaining_today() == 4
    for _ in range(4):
        quota.consume_or_raise()
    assert quota.remaining_today() == 0


def test_quota_rejects_zero_or_negative_limit():
    with pytest.raises(ValueError):
        DHLDailyQuota(daily_limit=0)
    with pytest.raises(ValueError):
        DHLDailyQuota(daily_limit=-5)


def test_quota_exhaustion_raises_without_http_call():
    today = date(2026, 4, 1)
    fake = FakeClient([])  # no responses queued
    adapter = _make_adapter(
        fake, sleep=lambda _s: None,
        daily_limit=1, clock=lambda: today,
    )
    # First call: exhaust the quota (would need an HTTP response — but
    # that's not the failure mode we're testing).
    fake_with_one = FakeClient([FakeResponse(201, _create_response())])
    adapter._client = fake_with_one  # swap to a queue with one response

    rsp = adapter.create_shipment(_req())
    assert rsp.awb == "W"
    assert len(fake_with_one.calls) == 1

    # Now: daily quota has been consumed. Next call must NOT make an
    # HTTP request — it must raise immediately.
    fake_empty = FakeClient([])
    adapter._client = fake_empty
    with pytest.raises(ab.CarrierRateLimitError):
        adapter.create_shipment(_req())
    assert fake_empty.calls == []


def test_quota_exhaustion_message_names_quota():
    today = date(2026, 4, 1)
    quota = DHLDailyQuota(daily_limit=1, clock=lambda: today)
    quota.consume_or_raise()
    with pytest.raises(ab.CarrierRateLimitError) as exc:
        quota.consume_or_raise()
    msg = str(exc.value).lower()
    assert "quota" in msg
    assert "exhausted" in msg
