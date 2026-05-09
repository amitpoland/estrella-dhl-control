"""
test_dhl_express_shadow_paperless_trade.py — DL-F3 PLT shadow-mode
behaviour.

Required:
  * Shadow create with PLT path: live receives the path, stub ignores it.
  * Shadow log row carries live_paperless_trade_attached / size /
    sha256.
  * Shadow log row does NOT carry PDF bytes or base64.
  * Shadow create with bad PLT file: live records attached=0;
    operator-facing return is still stub.
  * Live PLT failure does not change the operator-facing return.
  * Strongest invariant: scan _attachments/ after a shadow PLT
    create and confirm no file matches the live PLT bytes (since
    shadow never persists live artefacts).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.carrier import carrier_coordinator as cc
from app.services.carrier import carrier_state_engine as cse
from app.services.carrier import carrier_shipment_db as csdb
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


# ── Fakes ──────────────────────────────────────────────────────────────────

class _FakeShadowStore:
    def __init__(self):
        self.rows = []
    def record_call_outcome(self, **kwargs):
        self.rows.append(kwargs)


class _FakeLiveWithPLT:
    """Behaves like the live adapter for our purposes — returns
    PLT metadata in raw and a clearly-distinct AWB."""

    carrier = CARRIER_DHL

    def __init__(self, *, plt_attached: bool, plt_size: int = 0,
                 plt_sha256: str = "", awb: str = "LIVE-PLT-1",
                 raise_exc: Exception = None):
        self._plt_attached = plt_attached
        self._plt_size     = plt_size
        self._plt_sha256   = plt_sha256
        self._awb          = awb
        self._exc          = raise_exc
        self.calls         = []

    def create_shipment(self, request):
        self.calls.append(("create", request.batch_id))
        if self._exc is not None:
            raise self._exc
        return RawShipmentResponse(
            awb=self._awb, carrier=self.carrier,
            label_bytes=b"%PDF-1.4 LIVE-LABEL-NEVER-PERSISTED",
            label_format="pdf",
            label_filename=f"{self._awb}.pdf",
            raw={
                "paperless_trade_requested":         bool(request.customs_invoice_pdf_path),
                "paperless_trade_attached":          self._plt_attached,
                "paperless_trade_document_sha256":   self._plt_sha256,
                "paperless_trade_document_filename": "live.pdf" if request.customs_invoice_pdf_path else "",
                "paperless_trade_document_size":     self._plt_size,
            },
        )

    def cancel_shipment(self, awb, *, reason=""):
        return RawCancelResponse(carrier=self.carrier, awb=awb,
                                  accepted=True, reason="fake")

    def fetch_label(self, awb, *, fmt="pdf"):
        return b"%PDF"

    def schedule_pickup(self, awb, *, when_iso, location=None):
        return {}

    def parse_webhook_event(self, body, headers=None):
        return CarrierEvent(
            carrier=self.carrier, awb="X", event_code="transit",
            occurred_at="2026-04-01T10:00:00Z",
        )


def _request(plt_path: str = ""):
    return CarrierShipmentRequest(
        batch_id="B-SH-PLT-1",
        ship_from=CarrierAddress(name="From", country="PL"),
        ship_to=CarrierAddress(name="To",   country="US"),
        packages=(PackageSpec(weight_kg=1, length_cm=1,
                               width_cm=1, height_cm=1),),
        service_code="P", reference="R-PLT",
        customs_invoice_pdf_path=plt_path,
    )


# ── 1. Shadow create with PLT — stub returned, live observed ───────────

def test_shadow_create_with_plt_returns_stub_records_live_metadata():
    store = _FakeShadowStore()
    sa = DHLExpressShadowAdapter(
        stub          = DHLExpressStubAdapter(),
        live          = _FakeLiveWithPLT(
            plt_attached=True,
            plt_sha256="e" * 64,
            plt_size=2048,
            awb="LIVE-PLT-9999",
        ),
        shadow_store  = store,
    )
    rsp = sa.create_shipment(_request("/storage/polish_descriptions/x.pdf"))
    # Operator sees stub
    assert rsp.awb.startswith("DHLSTUB")
    assert rsp.awb != "LIVE-PLT-9999"
    # Shadow row carries live PLT metadata
    assert len(store.rows) == 1
    row = store.rows[0]
    assert row["live_paperless_trade_attached"] is True
    assert row["live_paperless_trade_size"]     == 2048
    assert row["live_paperless_trade_sha256"]   == "e" * 64


# ── 2. Shadow row carries no PDF bytes ─────────────────────────────────

def test_shadow_row_does_not_carry_pdf_bytes_or_base64():
    """The shadow store's record_call_outcome accepts only a fixed
    set of kwargs. Verify our recorded kwargs do NOT include any
    bytes-carrying field."""
    store = _FakeShadowStore()
    sa = DHLExpressShadowAdapter(
        stub          = DHLExpressStubAdapter(),
        live          = _FakeLiveWithPLT(
            plt_attached=True, plt_sha256="f"*64, plt_size=999,
        ),
        shadow_store  = store,
    )
    sa.create_shipment(_request("/x.pdf"))
    row = store.rows[0]
    # No PDF or base64 fields anywhere
    forbidden = {"pdf", "pdf_bytes", "pdf_base64", "documentImages",
                 "label_bytes", "raw", "base64"}
    for key in row:
        assert key not in forbidden, (
            f"shadow row carries forbidden key {key!r}"
        )
    # And no value equals or contains a base64-shaped PLT payload
    for v in row.values():
        if isinstance(v, (bytes, bytearray)):
            pytest.fail(f"shadow row value is bytes: {v!r}")
        if isinstance(v, str) and len(v) > 200 and "PDF" in v:
            pytest.fail(f"shadow row carries a PDF-shaped string: {v[:60]!r}")


# ── 3. Shadow create with bad PLT file — live records attached=False ───

def test_shadow_create_with_failed_plt_records_attached_false():
    store = _FakeShadowStore()
    sa = DHLExpressShadowAdapter(
        stub          = DHLExpressStubAdapter(),
        live          = _FakeLiveWithPLT(
            plt_attached=False,    # validation failed inside live
            plt_size=0, plt_sha256="",
        ),
        shadow_store  = store,
    )
    rsp = sa.create_shipment(_request("/missing.pdf"))
    assert rsp.awb.startswith("DHLSTUB")
    row = store.rows[0]
    assert row["live_paperless_trade_attached"] is False
    assert row["live_paperless_trade_sha256"]   == ""


# ── 4. Live PLT failure does not change operator-facing return ────────

def test_live_plt_failure_does_not_propagate():
    from app.services.carrier.adapters.base import CarrierResponseError
    store = _FakeShadowStore()
    sa = DHLExpressShadowAdapter(
        stub          = DHLExpressStubAdapter(),
        live          = _FakeLiveWithPLT(
            plt_attached=False,
            raise_exc=CarrierResponseError("DHL down"),
        ),
        shadow_store  = store,
    )
    rsp = sa.create_shipment(_request("/x.pdf"))
    assert rsp.awb.startswith("DHLSTUB")
    # The shadow row records live as errored
    row = store.rows[0]
    assert row["live_status"] == "error"
    # PLT fields default to safe empties (no live result to extract from)
    assert row["live_paperless_trade_attached"] is False
    assert row["live_paperless_trade_size"]     == 0


# ── 5. Strongest invariant — live label bytes never on disk ──────────

def test_live_plt_label_bytes_never_persisted(tmp_path):
    """End-to-end: a real coordinator + real csdb wired with the
    shadow adapter where the live fake returns LIVE-LABEL-NEVER-
    PERSISTED bytes. Scan the label store afterwards."""
    coord = cc.CarrierCoordinator(
        db_path          = tmp_path / "carrier_shipments.db",
        label_store_root = tmp_path / "carrier_labels",
        adapter          = DHLExpressShadowAdapter(
            stub         = DHLExpressStubAdapter(),
            live         = _FakeLiveWithPLT(
                plt_attached=True, plt_sha256="g"*64, plt_size=10,
                awb="LIVE-PLT-INVAR",
            ),
            shadow_store = _FakeShadowStore(),
        ),
        actor            = "test-shadow-plt",
    )
    coord.create_shipment(batch_id="B-SH-INV", request=_request("/x.pdf"))

    attach_dir = tmp_path / "carrier_labels" / "_attachments"
    for f in attach_dir.iterdir():
        if f.is_file():
            assert b"LIVE-LABEL-NEVER-PERSISTED" not in f.read_bytes()

    # And no shipment row carries the live AWB
    rows = csdb.list_all()
    assert all(r["awb"] != "LIVE-PLT-INVAR" for r in rows)


# ── 6. Shadow row carries live duration_ms ────────────────────────────

def test_shadow_row_carries_live_duration_ms():
    store = _FakeShadowStore()
    sa = DHLExpressShadowAdapter(
        stub          = DHLExpressStubAdapter(),
        live          = _FakeLiveWithPLT(plt_attached=True),
        shadow_store  = store,
    )
    sa.create_shipment(_request("/x.pdf"))
    row = store.rows[0]
    assert "live_duration_ms" in row
    assert isinstance(row["live_duration_ms"], int)
