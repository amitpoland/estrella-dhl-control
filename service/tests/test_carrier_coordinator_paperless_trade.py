"""
test_carrier_coordinator_paperless_trade.py — DL-F3 manifest +
event_code coverage for the carrier coordinator.

Required:
  * Coordinator.create_shipment with PLT-attached request writes
    paperless_trade_attached=True + sha256 + filename to the
    manifest.
  * Coordinator.create_shipment with PLT-flag-off (live adapter
    constructed without paperless_trade_enabled=True) records
    requested=True + attached=False; manifest reason is implicit
    via raw.
  * Manifest event_code on the per-AWB messages dir is
    "shipment_created_with_paperless_trade" only when attached.
  * The coordinator does NOT persist the source PDF bytes anywhere.
    Pinned by scanning _attachments/ contents after a PLT shipment.

Use a fake live-style adapter (satisfying CarrierAdapter Protocol)
that returns a synthetic RawShipmentResponse with controllable
paperless_trade_* keys in raw. NO real HTTP. NO real DHL.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import pytest

from app.services.carrier import carrier_coordinator as cc
from app.services.carrier import carrier_state_engine as cse
from app.services.carrier import carrier_shipment_db as csdb
from app.services.carrier.base import (
    CARRIER_DHL,
    CarrierAddress,
    CarrierEvent,
    CarrierShipmentRequest,
    PackageSpec,
    RawCancelResponse,
    RawShipmentResponse,
)


# ── Fake live-style adapter ────────────────────────────────────────────────

class _FakeAdapter:
    """Custom adapter returning controllable PLT metadata in raw."""

    carrier = CARRIER_DHL

    def __init__(self, *, plt_attached: bool, plt_sha256: str = "",
                 plt_filename: str = "", plt_size: int = 0,
                 plt_reason: str = "ok"):
        self._plt_attached = plt_attached
        self._plt_sha256   = plt_sha256
        self._plt_filename = plt_filename
        self._plt_size     = plt_size
        self._plt_reason   = plt_reason
        self._counter      = 0

    def create_shipment(self, request):
        self._counter += 1
        awb = f"FAKE-AWB-{self._counter:03d}"
        return RawShipmentResponse(
            awb=awb, carrier=self.carrier,
            label_bytes=b"%PDF-1.4 fake-stub-style label\n%%EOF\n",
            label_format="pdf",
            label_filename=f"{awb}.pdf",
            raw={
                "shipmentTrackingNumber": awb,
                "paperless_trade_requested": bool(request.customs_invoice_pdf_path),
                "paperless_trade_attached":          self._plt_attached,
                "paperless_trade_reason":            self._plt_reason,
                "paperless_trade_document_sha256":   self._plt_sha256,
                "paperless_trade_document_filename": self._plt_filename,
                "paperless_trade_document_size":     self._plt_size,
            },
        )

    def cancel_shipment(self, awb, *, reason=""):
        return RawCancelResponse(carrier=self.carrier, awb=awb,
                                  accepted=True, reason="fake")

    def fetch_label(self, awb, *, fmt="pdf"):
        return b"%PDF"

    def schedule_pickup(self, awb, *, when_iso, location=None):
        return {"confirmation": "FAKE"}

    def parse_webhook_event(self, body, headers=None):
        return CarrierEvent(
            carrier=self.carrier, awb="X", event_code="transit",
            occurred_at="2026-04-01T10:00:00Z",
        )


def _request(plt_path: str = ""):
    return CarrierShipmentRequest(
        batch_id="B-PLT-1",
        ship_from=CarrierAddress(name="From", country="PL"),
        ship_to=CarrierAddress(name="To",   country="US"),
        packages=(PackageSpec(weight_kg=1, length_cm=1,
                               width_cm=1, height_cm=1),),
        service_code="P",
        reference="R-PLT-1",
        customs_invoice_pdf_path=plt_path,
    )


def _make_coord(tmp_path, adapter):
    return cc.CarrierCoordinator(
        db_path          = tmp_path / "carrier_shipments.db",
        label_store_root = tmp_path / "carrier_labels",
        adapter          = adapter,
        actor            = "test-plt",
    )


# ── 1. PLT attached writes manifest with all four fields ──────────────────

def test_plt_attached_writes_full_manifest_metadata(tmp_path):
    coord = _make_coord(tmp_path, _FakeAdapter(
        plt_attached=True,
        plt_sha256="a" * 64,
        plt_filename="invoice.pdf",
        plt_size=1234,
    ))
    out = coord.create_shipment(
        batch_id="B-A",
        request=_request("/storage/polish_descriptions/invoice.pdf"),
    )
    import json as _json
    manifest_path = Path(out["manifest_path"])
    assert manifest_path.is_file()
    payload = _json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["paperless_trade_requested"]         is True
    assert payload["paperless_trade_attached"]          is True
    assert payload["paperless_trade_document_sha256"]   == "a" * 64
    assert payload["paperless_trade_document_filename"] == "invoice.pdf"


# ── 2. PLT requested but not attached (e.g. flag-off) ───────────────────

def test_plt_requested_but_not_attached_records_requested_true_attached_false(tmp_path):
    """Adapter behaves as if its plt_enabled flag was False — even
    with a path supplied, attached stays False."""
    coord = _make_coord(tmp_path, _FakeAdapter(
        plt_attached=False,
        plt_filename="invoice.pdf",
        plt_reason="flag_disabled",
    ))
    out = coord.create_shipment(
        batch_id="B-FLAG",
        request=_request("/storage/polish_descriptions/invoice.pdf"),
    )
    import json as _json
    payload = _json.loads(Path(out["manifest_path"]).read_text("utf-8"))
    assert payload["paperless_trade_requested"]         is True
    assert payload["paperless_trade_attached"]          is False
    assert payload["paperless_trade_document_sha256"]   == ""


# ── 3. PLT not requested at all (request has no path) ───────────────────

def test_plt_not_requested_writes_false_manifest(tmp_path):
    coord = _make_coord(tmp_path, _FakeAdapter(plt_attached=False))
    out = coord.create_shipment(batch_id="B-NO", request=_request(""))
    import json as _json
    payload = _json.loads(Path(out["manifest_path"]).read_text("utf-8"))
    assert payload["paperless_trade_requested"]         is False
    assert payload["paperless_trade_attached"]          is False


# ── 4. event_code branches on attached ─────────────────────────────────

def test_event_code_with_paperless_trade_when_attached(tmp_path):
    coord = _make_coord(tmp_path, _FakeAdapter(
        plt_attached=True, plt_filename="invoice.pdf",
        plt_sha256="b" * 64, plt_size=999,
    ))
    out = coord.create_shipment(
        batch_id="B-EV-Y",
        request=_request("/path/invoice.pdf"),
    )
    awb = out["shipment"]["awb"]
    msgs = list((tmp_path / "carrier_labels" / "_by_awb" / awb / "messages").glob("*.json"))
    assert msgs
    import json as _json
    bodies = [_json.loads(m.read_text("utf-8")) for m in msgs]
    create_msg = next(b for b in bodies if b["event_code"]
                       == "shipment_created_with_paperless_trade")
    assert create_msg["paperless_trade_attached"] is True
    assert create_msg["paperless_trade_document_sha256"] == "b" * 64


def test_event_code_default_when_not_attached(tmp_path):
    coord = _make_coord(tmp_path, _FakeAdapter(plt_attached=False))
    out = coord.create_shipment(
        batch_id="B-EV-N",
        request=_request(""),
    )
    awb = out["shipment"]["awb"]
    msgs = list((tmp_path / "carrier_labels" / "_by_awb" / awb / "messages").glob("*.json"))
    import json as _json
    bodies = [_json.loads(m.read_text("utf-8")) for m in msgs]
    create_msg = next(b for b in bodies if b["event_code"]
                       == "shipment_created")
    assert create_msg["paperless_trade_attached"] is False


# ── 5. PDF bytes never persist on disk ───────────────────────────────────

def test_pdf_bytes_never_persisted_to_label_store(tmp_path):
    """Strongest invariant: the source PDF bytes (NOT just the label)
    must never appear under _attachments/. The fake adapter's `raw`
    carries metadata only; the coordinator only writes the label
    artefact (not the customs PDF)."""
    sentinel = b"%PDF-1.4 SECRET-PLT-CONTENTS-MUST-NEVER-LEAK"
    pdf_path = tmp_path / "secret.pdf"
    pdf_path.write_bytes(sentinel + b"\n%%EOF\n")

    coord = _make_coord(tmp_path, _FakeAdapter(
        plt_attached=True,
        plt_sha256="c" * 64,
        plt_filename="secret.pdf",
        plt_size=len(sentinel),
    ))
    coord.create_shipment(
        batch_id="B-INV", request=_request(str(pdf_path)),
    )

    attach_dir = tmp_path / "carrier_labels" / "_attachments"
    for f in attach_dir.iterdir():
        if f.is_file():
            assert b"SECRET-PLT-CONTENTS" not in f.read_bytes(), (
                f"PDF sentinel leaked into label-store file {f.name}"
            )

    # And no manifest file carries the sentinel either
    by_awb = tmp_path / "carrier_labels" / "_by_awb"
    for sub in by_awb.iterdir():
        for f in sub.rglob("*"):
            if f.is_file():
                assert b"SECRET-PLT-CONTENTS" not in f.read_bytes(), (
                    f"PDF sentinel leaked into manifest file {f}"
                )


# ── 6. Existing coordinator invariants still hold ───────────────────────

def test_two_transitions_still_recorded_with_plt(tmp_path):
    coord = _make_coord(tmp_path, _FakeAdapter(plt_attached=True,
                                                  plt_sha256="d" * 64,
                                                  plt_filename="x.pdf",
                                                  plt_size=100))
    out = coord.create_shipment(
        batch_id="B-T", request=_request("/x.pdf"),
    )
    transitions = csdb.get_transitions(out["shipment"]["id"])
    moves = [(t["from_state"], t["to_state"]) for t in transitions]
    assert moves == [
        (cse.PRE_AWB,    cse.AWB_ISSUED),
        (cse.AWB_ISSUED, cse.LABEL_CREATED),
    ]
