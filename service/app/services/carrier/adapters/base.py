"""
carrier.adapters.base — :class:`CarrierAdapter` Protocol and helpers.

The Protocol is :func:`runtime_checkable` so the coordinator (DL-D) can
verify at injection time that whatever adapter it has been given
actually exposes the five required methods. Methods are named after
operator-level intents, not HTTP verbs, so adapters can implement them
with whatever transport mechanism the carrier requires (REST, SOAP,
queue, scheduled poll).

Required methods
----------------
  create_shipment(request)   -> RawShipmentResponse
  cancel_shipment(awb, reason="")
                             -> RawCancelResponse
  fetch_label(awb, *, fmt="pdf")
                             -> bytes
  parse_webhook_event(body, headers=None)
                             -> CarrierEvent
  schedule_pickup(awb, *, when_iso, location=None)
                             -> dict (carrier-specific receipt; opaque to
                                       the coordinator at this layer)

Adapters MUST surface failures as raised exceptions; the coordinator
does not parse HTTP status codes from inside the adapter. A subclass
of :class:`CarrierAdapterError` is the expected vocabulary.

DL-A scope: Protocol declaration and exception hierarchy only. No DHL
implementation, no HTTP client, no environment variable lookup.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Protocol, runtime_checkable

from ..base import (
    CarrierEvent,
    CarrierShipmentRequest,
    RawCancelResponse,
    RawShipmentResponse,
)


# ── Adapter exceptions ──────────────────────────────────────────────────────

class CarrierAdapterError(RuntimeError):
    """Base class for any carrier-adapter failure.

    The coordinator catches this rather than the broad
    :class:`Exception` so that bugs in the adapter (TypeError, etc.)
    surface loudly during development.
    """


class CarrierAuthError(CarrierAdapterError):
    """Authentication / authorization failure (401/403)."""


class CarrierRateLimitError(CarrierAdapterError):
    """Carrier returned a rate-limit signal (429 or equivalent)."""


class CarrierTransportError(CarrierAdapterError):
    """Network / TLS / DNS failure before a response was received."""


class CarrierResponseError(CarrierAdapterError):
    """Carrier replied, but the response was malformed or rejected."""


# ── Protocol ────────────────────────────────────────────────────────────────

@runtime_checkable
class CarrierAdapter(Protocol):
    """The contract every concrete carrier (DHL/FedEx/UPS) must satisfy.

    Methods may be sync or async; this layer is sync because the
    coordinator runs in the FastAPI request thread today. DL-D may
    revisit if a carrier integration justifies async I/O.
    """

    #: Lowercase carrier identifier; one of :data:`KNOWN_CARRIERS` from
    #: ``carrier.base``. Adapters expose this as a class attribute so
    #: the coordinator can route events without instantiating.
    carrier: str

    def create_shipment(
        self,
        request: CarrierShipmentRequest,
    ) -> RawShipmentResponse:
        """Issue an AWB and return label bytes + raw response."""
        ...

    def cancel_shipment(
        self,
        awb: str,
        *,
        reason: str = "",
    ) -> RawCancelResponse:
        """Request a void/cancel from the carrier.

        Adapters MUST NOT enforce the "before handover" rule — that is
        the state engine's job. They just forward whatever the carrier
        decided.
        """
        ...

    def fetch_label(
        self,
        awb: str,
        *,
        fmt: str = "pdf",
    ) -> bytes:
        """Re-download a label after the original create_shipment.

        Used when the original response did not include a label (some
        carriers return it asynchronously) or when the operator
        requested a reprint in a different format.
        """
        ...

    def parse_webhook_event(
        self,
        body: bytes,
        headers: Optional[Mapping[str, str]] = None,
    ) -> CarrierEvent:
        """Validate signature (if any) and normalise into ``CarrierEvent``.

        Implementations MUST raise :class:`CarrierResponseError` (or
        :class:`CarrierAuthError` for signature failure) instead of
        returning a partially-populated event.
        """
        ...

    def schedule_pickup(
        self,
        awb: str,
        *,
        when_iso: str,
        location: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Book a courier pickup for *awb* at *when_iso*.

        Returns the carrier's confirmation payload. The shape is
        deliberately ``Dict[str, Any]`` at this layer — the
        coordinator is responsible for extracting any fields it needs
        and persisting them to the manifest.
        """
        ...
