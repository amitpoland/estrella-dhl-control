"""
dhl_express_live.py — Parse-only DHL Express adapter.

DL-E1 scope
-----------
Parse-only. Takes the DHL Tracking-Unified-Push payload and turns it
into ``CarrierEvent`` instances. The send-side methods
(``create_shipment``, ``cancel_shipment``, ``fetch_label``,
``schedule_pickup``) are NOT implemented in this phase — calling
them raises :class:`NotImplementedError` with a "DL-F" pointer.

Contract
--------
* Implements the :class:`CarrierAdapter` Protocol surface (so the
  coordinator type-checks the same way it does for the stub).
* No HTTP client (``requests`` / ``httpx`` / ``urllib`` are NOT
  imported).
* No DHL SDK.
* No environment variable reads.
* No disk I/O.

Live HTTP client lands in DL-F. Splitting parse from transport here
means the webhook receiver can be tested end-to-end in DL-E1
without any network surface.

Push payload shape (subset DL-E1 parses)
----------------------------------------
::

    {
      "shipments": [{
        "id":      "<AWB>",
        "service": "express",
        "status":  {
          "timestamp":   "<ISO-8601>",
          "location":    "...",
          "statusCode":  "transit",
          "status":      "...",
          "description": "..."
        }
      }, ...]
    }

For each shipment we emit one ``CarrierEvent``. Shipments with
missing required fields (``id``, ``status.timestamp``, or
``status.statusCode``) are dropped from the output and the dropped
count is returned alongside the events.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..base import (
    CARRIER_DHL,
    CarrierEvent,
    CarrierShipmentRequest,
    RawCancelResponse,
    RawShipmentResponse,
)
from .base import CarrierResponseError


_NOT_IMPL_MSG = (
    "DHL Express live transport is not implemented in DL-E1 "
    "(parse-only). The live HTTP client lands in DL-F."
)


class DHLExpressLiveAdapter:
    """DHL Express adapter — parse-only for DL-E1.

    Public ``parse_push_payload`` method takes the DHL push envelope
    and returns a list of ``CarrierEvent`` instances. The
    Protocol-required ``parse_webhook_event`` method is provided for
    Protocol compatibility but only handles a single-shipment
    payload (test-friendly fallback); production code should use
    ``parse_push_payload``.
    """

    carrier: str = CARRIER_DHL

    # ── Send-side methods — all raise NotImplementedError in DL-E1 ─────────

    def create_shipment(
        self,
        request: CarrierShipmentRequest,
    ) -> RawShipmentResponse:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def cancel_shipment(
        self,
        awb: str,
        *,
        reason: str = "",
    ) -> RawCancelResponse:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def fetch_label(
        self,
        awb: str,
        *,
        fmt: str = "pdf",
    ) -> bytes:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def schedule_pickup(
        self,
        awb: str,
        *,
        when_iso: str,
        location: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError(_NOT_IMPL_MSG)

    # ── Parse a single-shipment webhook body ───────────────────────────────

    def parse_webhook_event(
        self,
        body: bytes,
        headers: Optional[Mapping[str, str]] = None,
    ) -> CarrierEvent:
        """Parse a single-shipment webhook body into one ``CarrierEvent``.

        Used for unit-test parity with the stub adapter; production
        DHL pushes carry a ``shipments[]`` array and should be parsed
        via :meth:`parse_push_payload`.

        Raises :class:`CarrierResponseError` for empty / non-JSON /
        non-object bodies and for shipments missing required fields.
        """
        payload = self._decode_object(body)
        # If the body has a shipments[] envelope, take the first row
        # and parse it. That keeps this method useful as a Protocol-
        # compatible fallback for tests.
        if "shipments" in payload:
            ships = payload.get("shipments") or []
            if not isinstance(ships, list) or not ships:
                raise CarrierResponseError(
                    "DHLExpressLiveAdapter: shipments[] is empty"
                )
            shipment = ships[0]
        else:
            shipment = payload
        ev = self._parse_one_shipment(shipment, raw_headers=bool(headers))
        if ev is None:
            raise CarrierResponseError(
                "DHLExpressLiveAdapter: shipment missing required fields "
                "(id / status.timestamp / status.statusCode)"
            )
        return ev

    # ── Parse a full DHL push envelope ────────────────────────────────────

    def parse_push_payload(
        self,
        body: bytes,
        headers: Optional[Mapping[str, str]] = None,
    ) -> Tuple[List[CarrierEvent], int]:
        """Parse the DHL push envelope into a list of ``CarrierEvent``.

        Returns ``(events, dropped_count)``. ``dropped_count`` is the
        number of shipments that lacked required fields and were
        skipped — the caller may surface this in a warning timeline
        event but should NOT 5xx (DHL retry-budget protection).

        Raises :class:`CarrierResponseError` for envelope-level
        failures (empty body, non-JSON, non-object, missing
        ``shipments`` array). Per-shipment validation failures are
        non-fatal.
        """
        payload = self._decode_object(body)
        ships = payload.get("shipments")
        if not isinstance(ships, list):
            raise CarrierResponseError(
                "DHLExpressLiveAdapter: payload missing 'shipments' array"
            )
        events: List[CarrierEvent] = []
        dropped = 0
        for shipment in ships:
            if not isinstance(shipment, dict):
                dropped += 1
                continue
            ev = self._parse_one_shipment(shipment, raw_headers=bool(headers))
            if ev is None:
                dropped += 1
                continue
            events.append(ev)
        return events, dropped

    # ── Internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _decode_object(body: bytes) -> Dict[str, Any]:
        """Decode and validate the top-level body shape."""
        if not body:
            raise CarrierResponseError(
                "DHLExpressLiveAdapter: empty webhook body"
            )
        try:
            payload = json.loads(body)
        except (ValueError, TypeError) as exc:
            raise CarrierResponseError(
                f"DHLExpressLiveAdapter: invalid JSON in webhook body: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise CarrierResponseError(
                "DHLExpressLiveAdapter: webhook body must be a JSON object, "
                f"got {type(payload).__name__}"
            )
        return payload

    @staticmethod
    def _parse_one_shipment(
        shipment: Dict[str, Any],
        *,
        raw_headers: bool,
    ) -> Optional[CarrierEvent]:
        """Convert one shipment dict into a ``CarrierEvent`` or None
        if required fields are missing."""
        awb = (shipment.get("id") or "").strip()
        status = shipment.get("status") or {}
        if not isinstance(status, dict):
            return None
        status_code = (status.get("statusCode") or "").strip()
        timestamp   = (status.get("timestamp")  or "").strip()
        if not awb or not status_code or not timestamp:
            return None
        location    = (status.get("location")    or "").strip()
        description = (
            status.get("description")
            or status.get("status")
            or ""
        ).strip()
        return CarrierEvent(
            carrier      = CARRIER_DHL,
            awb          = awb,
            event_code   = status_code,
            occurred_at  = timestamp,
            location     = location,
            description  = description,
            raw          = {
                "live":         True,
                "carrier":      CARRIER_DHL,
                "headers_seen": raw_headers,
                "shipment":     dict(shipment),
            },
        )
