"""
test_dhl_express_shadow_adapter.py — DL-F2 wrapper-adapter behaviour.

Required:
  * isinstance check vs CarrierAdapter Protocol.
  * create_shipment returns the stub's response when both succeed.
  * Live failure → returns stub, records live_only_error.
  * Stub failure → records stub_only_error AND re-raises stub error
    (even when live succeeded).
  * Live AWB never lands in carrier_shipment_db after a shadow create.
  * Live label bytes never reach carrier_label_store.
  * cancel returns stub even when live differs.
  * fetch_label returns stub bytes; live error recorded.
  * schedule_pickup returns stub dict.
  * Live CarrierRateLimitError → live_status="skipped".
  * Unexpected RuntimeError on live → caught, live_error_class="Exception".
  * Label-format mismatch → diff_outcome="shape_diff".
  * Cancel accepted mismatch → diff_outcome="shape_diff".
  * parse_webhook_event writes NO shadow row.
  * Constructor rejects non-Protocol stub/live with TypeError.
  * Source-grep guards.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.carrier import carrier_coordinator as cc
from app.services.carrier import carrier_shipment_db as csdb
from app.services.carrier import carrier_state_engine as cse
from app.services.carrier.adapters import base as ab
from app.services.carrier.adapters.dhl_express_shadow import (
    DHLExpressShadowAdapter,
)
from app.services.carrier.adapters.dhl_express_stub import (
    DHLExpressStubAdapter,
)
from app.services.carrier.base import (
    CARRIER_DHL,
    CarrierAddress,
    CarrierEvent,
    CarrierShipmentRequest,
    PackageSpec,
    RawCancelResponse,
    RawShipmentResponse,
)


_SHADOW_FILE = (
    Path(__file__).resolve().parents[1]
    / "app" / "services" / "carrier" / "adapters" / "dhl_express_shadow.py"
)


@pytest.fixture(scope="module")
def shadow_src() -> str:
    return _SHADOW_FILE.read_text(encoding="utf-8")


# ── In-memory shadow store double ──────────────────────────────────────────

class FakeShadowStore:
    """Captures rows so tests can assert without booting SQLite."""

    def __init__(self):
        self.rows: list = []
        self.fail_next: bool = False

    def record_call_outcome(self, **kwargs):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("simulated store failure")
        self.rows.append(kwargs)


# ── Fake live adapter that satisfies CarrierAdapter ───────────────────────

class _FakeLive:
    carrier = CARRIER_DHL

    def __init__(
        self, *,
        create_response=None, create_exc=None,
        cancel_response=None, cancel_exc=None,
        label_bytes=None, label_exc=None,
        pickup_response=None, pickup_exc=None,
        webhook_event=None, webhook_exc=None,
    ):
        self._cr  = create_response
        self._cre = create_exc
        self._cn  = cancel_response
        self._cne = cancel_exc
        self._lb  = label_bytes
        self._le  = label_exc
        self._pu  = pickup_response
        self._pue = pickup_exc
        self._wh  = webhook_event
        self._whe = webhook_exc
        self.calls = []

    def create_shipment(self, request):
        self.calls.append(("create", request))
        if self._cre is not None:
            raise self._cre
        return self._cr

    def cancel_shipment(self, awb, *, reason=""):
        self.calls.append(("cancel", awb, reason))
        if self._cne is not None:
            raise self._cne
        return self._cn

    def fetch_label(self, awb, *, fmt="pdf"):
        self.calls.append(("fetch", awb, fmt))
        if self._le is not None:
            raise self._le
        return self._lb or b""

    def schedule_pickup(self, awb, *, when_iso, location=None):
        self.calls.append(("pickup", awb, when_iso))
        if self._pue is not None:
            raise self._pue
        return self._pu or {}

    def parse_webhook_event(self, body, headers=None):
        self.calls.append(("webhook", body))
        if self._whe is not None:
            raise self._whe
        return self._wh


def _request(reference="R-1") -> CarrierShipmentRequest:
    return CarrierShipmentRequest(
        batch_id="B-1",
        ship_from=CarrierAddress(name="From", country="PL"),
        ship_to=CarrierAddress(name="To",   country="US"),
        packages=(PackageSpec(
            weight_kg=0.5, length_cm=15, width_cm=10, height_cm=5,
            declared_value=100.0, declared_currency="USD",
        ),),
        service_code="P", reference=reference,
    )


def _live_create_response(awb="LIVE-FAKE-9999",
                           label_bytes=b"%PDF-1.4 LIVE-LABEL-BYTES",
                           label_format="pdf") -> RawShipmentResponse:
    return RawShipmentResponse(
        awb=awb, carrier=CARRIER_DHL,
        label_bytes=label_bytes,
        label_format=label_format,
        label_filename=f"{awb}.{label_format}",
        raw={"live": True, "awb": awb},
    )


def _live_cancel_response(awb, accepted=True) -> RawCancelResponse:
    return RawCancelResponse(
        carrier=CARRIER_DHL, awb=awb, accepted=accepted,
        reason="live", raw={"live": True},
    )


# ── 1. Protocol ────────────────────────────────────────────────────────────

def test_shadow_satisfies_protocol():
    sa = DHLExpressShadowAdapter(
        stub=DHLExpressStubAdapter(),
        live=_FakeLive(create_response=_live_create_response()),
        shadow_store=FakeShadowStore(),
    )
    assert isinstance(sa, ab.CarrierAdapter)
    assert sa.carrier == CARRIER_DHL


def test_shadow_constructor_rejects_non_protocol_stub():
    class _Bad:
        carrier = "dhl"
    with pytest.raises(TypeError):
        DHLExpressShadowAdapter(
            stub=_Bad(),
            live=_FakeLive(create_response=_live_create_response()),
            shadow_store=FakeShadowStore(),
        )


def test_shadow_constructor_rejects_non_protocol_live():
    class _Bad:
        carrier = "dhl"
    with pytest.raises(TypeError):
        DHLExpressShadowAdapter(
            stub=DHLExpressStubAdapter(),
            live=_Bad(),
            shadow_store=FakeShadowStore(),
        )


# ── 2. Happy path returns stub ─────────────────────────────────────────────

def test_create_shipment_returns_stub_when_both_succeed():
    store = FakeShadowStore()
    live = _FakeLive(create_response=_live_create_response(awb="LIVE-9"))
    sa = DHLExpressShadowAdapter(
        stub=DHLExpressStubAdapter(), live=live, shadow_store=store,
    )
    rsp = sa.create_shipment(_request())
    assert rsp.awb.startswith("DHLSTUB")           # stub AWB shape
    assert rsp.awb != "LIVE-9"                     # NEVER live AWB
    assert rsp.label_bytes.startswith(b"%PDF")
    assert b"LIVE-LABEL-BYTES" not in rsp.label_bytes
    # One row recorded
    assert len(store.rows) == 1
    row = store.rows[0]
    assert row["method"] == "create_shipment"
    assert row["stub_status"] == "ok"
    assert row["live_status"] == "ok"
    assert row["diff_outcome"] == "match"
    assert row["stub_awb"].startswith("DHLSTUB")
    assert row["live_awb"] == "LIVE-9"


# ── 3. Live failure → returns stub + records live_only_error ──────────────

def test_create_live_failure_returns_stub_and_records():
    store = FakeShadowStore()
    live = _FakeLive(create_exc=ab.CarrierResponseError("DHL down"))
    sa = DHLExpressShadowAdapter(
        stub=DHLExpressStubAdapter(), live=live, shadow_store=store,
    )
    rsp = sa.create_shipment(_request())
    assert rsp.awb.startswith("DHLSTUB")
    assert len(store.rows) == 1
    row = store.rows[0]
    assert row["stub_status"] == "ok"
    assert row["live_status"] == "error"
    assert row["live_error_class"] == "CarrierResponseError"
    assert row["diff_outcome"] == "live_only_error"


# ── 4. Stub failure → records stub_only_error + re-raises ─────────────────

def test_create_stub_failure_re_raises():
    """Build a stub that always fails by passing a deliberately broken
    request; the stub adapter raises CarrierResponseError on empty
    packages."""
    store = FakeShadowStore()
    bad_req = CarrierShipmentRequest(
        batch_id="B", ship_from=CarrierAddress(name="x", country="PL"),
        ship_to=CarrierAddress(name="y", country="US"),
        packages=(),  # empty → stub raises
    )
    live = _FakeLive(create_response=_live_create_response())
    sa = DHLExpressShadowAdapter(
        stub=DHLExpressStubAdapter(), live=live, shadow_store=store,
    )
    with pytest.raises(ab.CarrierResponseError):
        sa.create_shipment(bad_req)
    # Row was still recorded — both observed
    assert len(store.rows) == 1
    row = store.rows[0]
    assert row["stub_status"] == "error"
    assert row["stub_error_class"] == "CarrierResponseError"
    assert row["live_status"] == "ok"     # we DID call live
    assert row["diff_outcome"] == "stub_only_error"


# ── 5. The strongest invariant: live AWB never in registry ────────────────

def test_live_awb_never_lands_in_carrier_shipment_db(tmp_path):
    """End-to-end: a real coordinator + real csdb wired with the
    shadow adapter must persist ONLY the stub's AWB."""
    coord = cc.CarrierCoordinator(
        db_path          = tmp_path / "carrier_shipments.db",
        label_store_root = tmp_path / "carrier_labels",
        adapter          = DHLExpressShadowAdapter(
            stub          = DHLExpressStubAdapter(),
            live          = _FakeLive(create_response=_live_create_response(
                awb="LIVE-FAKE-9999",
                label_bytes=b"%PDF-LIVE-LABEL-NEVER-PERSISTED",
            )),
            shadow_store  = FakeShadowStore(),
        ),
        actor            = "test-actor",
    )
    out = coord.create_shipment(batch_id="B-INV-1", request=_request())
    persisted_awb = out["shipment"]["awb"]
    assert persisted_awb.startswith("DHLSTUB")
    # Direct registry scan: NO row with the live AWB
    rows = csdb.list_all()
    assert all(r["awb"] != "LIVE-FAKE-9999" for r in rows)
    # And the stub AWB IS present
    assert csdb.get_by_awb(CARRIER_DHL, persisted_awb) is not None


# ── 6. Live label bytes never on disk ─────────────────────────────────────

def test_live_label_bytes_never_in_label_store(tmp_path):
    coord = cc.CarrierCoordinator(
        db_path          = tmp_path / "carrier_shipments.db",
        label_store_root = tmp_path / "carrier_labels",
        adapter          = DHLExpressShadowAdapter(
            stub          = DHLExpressStubAdapter(),
            live          = _FakeLive(create_response=_live_create_response(
                awb="LIVE-LABEL-1",
                label_bytes=b"%PDF-LIVE-LABEL-NEVER-PERSISTED",
            )),
            shadow_store  = FakeShadowStore(),
        ),
        actor            = "test-actor",
    )
    coord.create_shipment(batch_id="B-LBL-1", request=_request())
    attach_dir = tmp_path / "carrier_labels" / "_attachments"
    for f in attach_dir.iterdir():
        if f.is_file():
            assert b"LIVE-LABEL-NEVER-PERSISTED" not in f.read_bytes(), (
                f"live label bytes leaked into {f.name}"
            )


# ── 7. cancel returns stub even when live differs ─────────────────────────

def test_cancel_returns_stub_accepted_when_live_rejects():
    store = FakeShadowStore()
    live = _FakeLive(cancel_response=_live_cancel_response("X", accepted=False))
    sa = DHLExpressShadowAdapter(
        stub=DHLExpressStubAdapter(), live=live, shadow_store=store,
    )
    rsp = sa.cancel_shipment("DHLAWB-CANC", reason="op")
    # Stub always accepts
    assert rsp.accepted is True
    # Shadow row records the diff
    assert len(store.rows) == 1
    row = store.rows[0]
    assert row["stub_status"] == "ok"
    assert row["live_status"] == "ok"
    assert row["diff_outcome"] == "shape_diff"
    assert "accepted" in row["diff_notes"]


# ── 8. fetch_label returns stub bytes; live error recorded ────────────────

def test_fetch_label_returns_stub_bytes_when_live_fails():
    store = FakeShadowStore()
    live = _FakeLive(label_exc=ab.CarrierResponseError("404"))
    sa = DHLExpressShadowAdapter(
        stub=DHLExpressStubAdapter(), live=live, shadow_store=store,
    )
    out = sa.fetch_label("DHLSTUB000001", fmt="pdf")
    assert out.startswith(b"%PDF")
    assert len(store.rows) == 1
    row = store.rows[0]
    assert row["stub_status"] == "ok"
    assert row["live_status"] == "error"
    assert row["live_error_class"] == "CarrierResponseError"
    assert row["diff_outcome"] == "live_only_error"


def test_fetch_label_returns_stub_bytes_when_both_succeed():
    store = FakeShadowStore()
    live = _FakeLive(label_bytes=b"%PDF-LIVE")
    sa = DHLExpressShadowAdapter(
        stub=DHLExpressStubAdapter(), live=live, shadow_store=store,
    )
    out = sa.fetch_label("DHLSTUB000001", fmt="pdf")
    assert out.startswith(b"%PDF")
    assert b"LIVE" not in out             # stub bytes only
    row = store.rows[0]
    assert row["diff_outcome"] == "match"


# ── 9. schedule_pickup returns stub dict ──────────────────────────────────

def test_schedule_pickup_returns_stub_dict():
    store = FakeShadowStore()
    live = _FakeLive(pickup_response={
        "dispatchConfirmationNumbers": ["LIVE-PWP-1"],
    })
    sa = DHLExpressShadowAdapter(
        stub=DHLExpressStubAdapter(), live=live, shadow_store=store,
    )
    out = sa.schedule_pickup(
        "DHLSTUB000123", when_iso="2026-04-15T10:00:00Z",
    )
    assert out["stub"] is True
    assert out["confirmation_number"].startswith("STUB-")
    row = store.rows[0]
    assert row["method"] == "schedule_pickup"


# ── 10. Live CarrierRateLimitError → live_status=skipped ──────────────────

def test_live_rate_limit_records_skipped():
    store = FakeShadowStore()
    live = _FakeLive(create_exc=ab.CarrierRateLimitError("quota exhausted"))
    sa = DHLExpressShadowAdapter(
        stub=DHLExpressStubAdapter(), live=live, shadow_store=store,
    )
    rsp = sa.create_shipment(_request())
    assert rsp.awb.startswith("DHLSTUB")
    row = store.rows[0]
    assert row["live_status"] == "skipped"
    assert row["live_error_class"] == "CarrierRateLimitError"
    assert "live_skipped" in row["diff_notes"]


# ── 11. Unexpected RuntimeError on live → caught, class="Exception" ──────

def test_unexpected_live_exception_is_caught():
    store = FakeShadowStore()
    live = _FakeLive(create_exc=RuntimeError("kaboom"))
    sa = DHLExpressShadowAdapter(
        stub=DHLExpressStubAdapter(), live=live, shadow_store=store,
    )
    rsp = sa.create_shipment(_request())
    assert rsp.awb.startswith("DHLSTUB")
    row = store.rows[0]
    assert row["live_error_class"] == "Exception"
    assert "kaboom" in row["live_error_summary"]


# ── 12. label_format mismatch → shape_diff ────────────────────────────────

def test_create_label_format_mismatch_records_shape_diff():
    store = FakeShadowStore()
    live = _FakeLive(create_response=_live_create_response(label_format="zpl"))
    sa = DHLExpressShadowAdapter(
        stub=DHLExpressStubAdapter(), live=live, shadow_store=store,
    )
    sa.create_shipment(_request())
    row = store.rows[0]
    assert row["diff_outcome"] == "shape_diff"
    assert "label_format" in row["diff_notes"]


# ── 13. parse_webhook_event writes NO shadow row ──────────────────────────

def test_parse_webhook_event_writes_no_shadow_row():
    store = FakeShadowStore()
    fake_event = CarrierEvent(
        carrier=CARRIER_DHL, awb="X", event_code="transit",
        occurred_at="2026-04-01T10:00:00Z",
    )
    live = _FakeLive(webhook_event=fake_event)
    sa = DHLExpressShadowAdapter(
        stub=DHLExpressStubAdapter(), live=live, shadow_store=store,
    )
    out = sa.parse_webhook_event(b'{"awb": "X", "event_code": "transit"}')
    assert out is fake_event
    # Crucially: no shadow row written
    assert store.rows == []


# ── 14. Shadow store failure does not crash operator action ──────────────

def test_shadow_store_failure_swallowed():
    store = FakeShadowStore()
    store.fail_next = True
    live = _FakeLive(create_response=_live_create_response())
    sa = DHLExpressShadowAdapter(
        stub=DHLExpressStubAdapter(), live=live, shadow_store=store,
    )
    # Must NOT raise
    rsp = sa.create_shipment(_request())
    assert rsp.awb.startswith("DHLSTUB")


# ── 15. Source-grep guards ────────────────────────────────────────────────

@pytest.mark.parametrize("forbidden", [
    "import fastapi", "from fastapi",
    "import flask",   "from flask",
])
def test_shadow_source_no_web_framework(shadow_src, forbidden):
    assert forbidden not in shadow_src


def test_shadow_source_no_env_reads(shadow_src):
    for forbidden in ["os.environ", "os.getenv", "getenv("]:
        assert forbidden not in shadow_src


@pytest.mark.parametrize("forbidden", [
    "import requests", "from requests",
    "import httpx",    "from httpx",
    "import urllib",   "from urllib",
])
def test_shadow_source_no_http(shadow_src, forbidden):
    assert forbidden not in shadow_src


def test_shadow_source_no_print_or_log_authorization(shadow_src):
    leak_tokens = ("print(", "log.", "logger.")
    for line in shadow_src.splitlines():
        if "Authorization" not in line:
            continue
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith('"""'):
            continue
        for token in leak_tokens:
            assert token not in line, (
                f"shadow adapter leaks Authorization through {token!r}: "
                f"{line!r}"
            )


@pytest.mark.parametrize("forbidden", [
    "csdb.upsert_shipment",
    "csdb.record_transition",
    "carrier_shipment_db.upsert_shipment",
    "cls.save_attachment",
    "cls.write_manifest",
    "carrier_label_store.save_attachment",
])
def test_shadow_source_no_registry_or_label_writes(shadow_src, forbidden):
    """Pinned: shadow MUST NOT touch the operational registry or
    label store. Only dhl_shadow_db is its persistence target."""
    assert forbidden not in shadow_src, (
        f"dhl_express_shadow.py contains {forbidden!r} — shadow "
        f"writes go ONLY to dhl_shadow_db."
    )


# ── 16. Actor defaults to system:shadow ───────────────────────────────────

def test_actor_defaults_to_system_shadow():
    store = FakeShadowStore()
    live = _FakeLive(create_response=_live_create_response())
    sa = DHLExpressShadowAdapter(
        stub=DHLExpressStubAdapter(), live=live, shadow_store=store,
    )
    sa.create_shipment(_request())
    assert store.rows[0]["actor"] == "system:shadow"


def test_actor_override_lands_on_row():
    store = FakeShadowStore()
    live = _FakeLive(create_response=_live_create_response())
    sa = DHLExpressShadowAdapter(
        stub=DHLExpressStubAdapter(), live=live, shadow_store=store,
        actor="op-special",
    )
    sa.create_shipment(_request())
    assert store.rows[0]["actor"] == "op-special"


# ── 17. Read-through accessors ────────────────────────────────────────────

def test_shadow_exposes_stub_and_live_for_introspection():
    stub = DHLExpressStubAdapter()
    live = _FakeLive(create_response=_live_create_response())
    sa = DHLExpressShadowAdapter(
        stub=stub, live=live, shadow_store=FakeShadowStore(),
    )
    assert sa.stub is stub
    assert sa.live is live
