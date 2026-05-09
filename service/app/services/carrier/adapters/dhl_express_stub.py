"""
dhl_express_stub.py — Fixture-only DHL Express adapter.

Purpose
-------
DL-B layer: a fully-canned adapter that satisfies
:class:`carrier.adapters.base.CarrierAdapter` without ever touching
the network. Lets DL-C wire read-only routes and the dashboard
surface, and DL-D build the coordinator + action proposals, with
zero live-DHL dependency. Once DL-F lands the live ``DHLExpressAdapter``
the stub stays in the codebase as a fixture for tests and dev runs.

Strict contract (enforced by source-grep test)
----------------------------------------------
* No HTTP client (``requests`` / ``httpx`` / ``urllib`` are NOT imported).
* No DHL SDK.
* No environment variable reads.
* No disk I/O.
* No background threads, no schedulers.
* Deterministic outputs: same input always produces the same AWB,
  same label bytes, same webhook parse.

What the stub does NOT do
-------------------------
* It does not validate addresses, postal codes, or HS codes.
* It does not enforce DHL business rules (max-pieces, weight caps,
  service-code availability per region). Those belong in the live
  adapter (DL-F) where the carrier returns the canonical error.
* It does not pretend to be slow — every call is synchronous and
  effectively free. Tests that need failure-injection should mock
  this adapter, not extend it.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping, Optional

from ..base import (
    CARRIER_DHL,
    CarrierEvent,
    CarrierShipmentRequest,
    RawCancelResponse,
    RawShipmentResponse,
)
from .base import CarrierResponseError

# ── Constants ────────────────────────────────────────────────────────────────

#: Lowercased label formats the stub knows how to fake. PNG is
#: deliberately excluded so callers learn early that the protocol does
#: not commit to PNG support — the live DHL adapter will negotiate
#: format on a per-account basis.
SUPPORTED_LABEL_FORMATS = frozenset({"pdf", "zpl"})

#: Webhook event codes the stub accepts. Anything outside this set is
#: passed through verbatim into ``CarrierEvent.event_code`` — the
#: coordinator's translation table is responsible for narrowing.
KNOWN_EVENT_CODES = frozenset({
    "label_created",
    "picked_up",
    "in_transit",
    "out_for_delivery",
    "delivered",
    "exception",
    "returned",
})


# ── Helpers ─────────────────────────────────────────────────────────────────

def _stub_awb(request: CarrierShipmentRequest) -> str:
    """Deterministic six-digit AWB derived from the request.

    Same ``(batch_id, reference, package count, first weight)`` always
    yields the same AWB. The collision space is 1e6, which is fine for
    a fixture adapter — production traffic will use the live adapter.
    """
    pkg_signature = ""
    if request.packages:
        first = request.packages[0]
        pkg_signature = (
            f"{first.weight_kg}|{first.length_cm}|"
            f"{first.width_cm}|{first.height_cm}"
        )
    seed = (
        f"{request.batch_id}|{request.reference}|"
        f"{len(request.packages)}|{pkg_signature}|{request.service_code}"
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    n = int(digest[:8], 16) % 1_000_000
    return f"DHLSTUB{n:06d}"


def _fake_pdf_bytes(awb: str) -> bytes:
    """Minimal byte sequence that begins with the PDF magic header.

    Not a parseable PDF — just enough so that downstream code that
    sniffs the first four bytes accepts the artefact and the label
    store hashes it identically each time per AWB.
    """
    body = f"% Fake DHL stub label for AWB={awb}\n% NOT A REAL PDF\n"
    return b"%PDF-1.4\n" + body.encode("utf-8") + b"%%EOF\n"


def _fake_zpl_bytes(awb: str) -> bytes:
    """Minimal ZPL label opening with ``^XA`` / closing with ``^XZ``."""
    body = (
        b"^XA"
        b"^FO50,50^A0N,40,40^FDDHL Stub^FS"
        b"^FO50,100^A0N,30,30^FDAWB " + awb.encode("ascii") + b"^FS"
        b"^XZ"
    )
    return body


# ── Adapter class ───────────────────────────────────────────────────────────

class DHLExpressStubAdapter:
    """Fixture-only ``CarrierAdapter`` for DHL Express.

    Public attribute :attr:`carrier` is set to :data:`CARRIER_DHL`
    so the coordinator can route inbound webhook events without
    instantiating the class.
    """

    carrier: str = CARRIER_DHL

    # ── create_shipment ─────────────────────────────────────────────────────

    def create_shipment(
        self,
        request: CarrierShipmentRequest,
    ) -> RawShipmentResponse:
        """Issue a fake AWB and return a fake PDF label.

        The returned ``raw`` dict is clearly marked ``stub: True`` so
        downstream evidence/lineage code can audit-trail that the
        artefact came from the stub adapter, never from the live
        carrier.
        """
        if not isinstance(request, CarrierShipmentRequest):
            raise CarrierResponseError(
                "DHLExpressStubAdapter.create_shipment expected "
                "CarrierShipmentRequest"
            )
        if not request.packages:
            raise CarrierResponseError(
                "DHLExpressStubAdapter: at least one package is required"
            )
        awb = _stub_awb(request)
        label_bytes = _fake_pdf_bytes(awb)
        return RawShipmentResponse(
            awb=awb,
            carrier=self.carrier,
            label_bytes=label_bytes,
            label_format="pdf",
            label_filename=f"{awb}.pdf",
            raw={
                "stub": True,
                "carrier": self.carrier,
                "awb": awb,
                "service_code": request.service_code,
                "reference": request.reference,
                "package_count": len(request.packages),
                "ship_to_country": request.ship_to.country,
                "ship_from_country": request.ship_from.country,
            },
        )

    # ── cancel_shipment ─────────────────────────────────────────────────────

    def cancel_shipment(
        self,
        awb: str,
        *,
        reason: str = "",
    ) -> RawCancelResponse:
        """Always-accept cancel for any non-empty AWB.

        The "void after handover" rule lives in the state engine, not
        here — the live carrier returns the same accept-or-reject
        signal regardless of when the operator clicked Void, so the
        stub mirrors that.
        """
        if not (awb or "").strip():
            raise CarrierResponseError(
                "DHLExpressStubAdapter.cancel_shipment: awb is required"
            )
        return RawCancelResponse(
            carrier=self.carrier,
            awb=awb,
            accepted=True,
            reason=reason or "stub-accepted",
            raw={"stub": True, "carrier": self.carrier, "awb": awb},
        )

    # ── fetch_label ─────────────────────────────────────────────────────────

    def fetch_label(
        self,
        awb: str,
        *,
        fmt: str = "pdf",
    ) -> bytes:
        """Re-fetch the canned label artefact for *awb* in *fmt*.

        Same AWB + same fmt always returns identical bytes. PNG is
        explicitly unsupported and raises :class:`CarrierResponseError`
        rather than returning a wrong-format payload.
        """
        if not (awb or "").strip():
            raise CarrierResponseError(
                "DHLExpressStubAdapter.fetch_label: awb is required"
            )
        fmt_norm = (fmt or "pdf").lower().strip()
        if fmt_norm not in SUPPORTED_LABEL_FORMATS:
            raise CarrierResponseError(
                f"DHLExpressStubAdapter: label format {fmt!r} is not "
                f"supported by the stub. Supported: "
                f"{sorted(SUPPORTED_LABEL_FORMATS)}"
            )
        if fmt_norm == "pdf":
            return _fake_pdf_bytes(awb)
        return _fake_zpl_bytes(awb)

    # ── parse_webhook_event ─────────────────────────────────────────────────

    def parse_webhook_event(
        self,
        body: bytes,
        headers: Optional[Mapping[str, str]] = None,
    ) -> CarrierEvent:
        """Parse a DHL Tracking-Unified-Push-shaped JSON body.

        Expected JSON shape (subset; live adapter will be stricter)::

            {
              "awb": "1234567890",
              "event_code": "in_transit",
              "occurred_at": "2026-04-12T10:15:00Z",
              "location": "Warsaw",
              "description": "Arrived at facility"
            }

        Raises :class:`CarrierResponseError` for:
          * empty / None body
          * non-JSON body
          * JSON that is not a dict
          * missing ``awb`` or ``event_code``

        Headers are accepted for API parity with the live adapter
        (where they carry the HMAC signature) and otherwise ignored.
        """
        if not body:
            raise CarrierResponseError(
                "DHLExpressStubAdapter.parse_webhook_event: empty body"
            )
        try:
            payload = json.loads(body)
        except (ValueError, TypeError) as exc:
            raise CarrierResponseError(
                f"DHLExpressStubAdapter: invalid JSON in webhook body: "
                f"{exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise CarrierResponseError(
                "DHLExpressStubAdapter: webhook body must be a JSON object, "
                f"got {type(payload).__name__}"
            )
        awb = (payload.get("awb") or "").strip()
        event_code = (payload.get("event_code") or "").strip()
        if not awb:
            raise CarrierResponseError(
                "DHLExpressStubAdapter: webhook payload missing 'awb'"
            )
        if not event_code:
            raise CarrierResponseError(
                "DHLExpressStubAdapter: webhook payload missing 'event_code'"
            )
        return CarrierEvent(
            carrier=self.carrier,
            awb=awb,
            event_code=event_code,
            occurred_at=(payload.get("occurred_at") or "").strip(),
            location=(payload.get("location") or "").strip(),
            description=(payload.get("description") or "").strip(),
            raw={
                "stub": True,
                "carrier": self.carrier,
                "headers_seen": bool(headers),
                "original": payload,
            },
        )

    # ── schedule_pickup ─────────────────────────────────────────────────────

    def schedule_pickup(
        self,
        awb: str,
        *,
        when_iso: str,
        location: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return a deterministic stub pickup confirmation."""
        if not (awb or "").strip():
            raise CarrierResponseError(
                "DHLExpressStubAdapter.schedule_pickup: awb is required"
            )
        if not (when_iso or "").strip():
            raise CarrierResponseError(
                "DHLExpressStubAdapter.schedule_pickup: when_iso is required"
            )
        # Confirmation number is a deterministic hash of (awb, when_iso)
        # so the same booking attempt yields the same number.
        seed = f"{awb}|{when_iso}".encode("utf-8")
        confirmation = "STUB-" + hashlib.sha256(seed).hexdigest()[:10].upper()
        return {
            "stub": True,
            "carrier": self.carrier,
            "awb": awb,
            "when_iso": when_iso,
            "location": dict(location) if location else {},
            "confirmation_number": confirmation,
        }
