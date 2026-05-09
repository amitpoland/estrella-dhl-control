"""
DhlExpressLiveAdapter — gate-blocked stub for Phase C.

The live adapter enforces two guards before any API interaction:
  1. Allowlist check  — batch_id must be in carrier_live_allowlist
  2. Credential check — api_key + api_secret must both be set

Both checks raise typed exceptions so the caller gets precise failure
reasons rather than generic HTTP errors.

Phase C invariant: no HTTP call is reachable. The actual DHL Express
API integration (httpx call + idempotency write + label handling) is
deferred to Phase D. Any call that passes both guards raises
NotImplementedError to make the Phase D boundary explicit.

This class never logs or surfaces api_key/api_secret values.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .base import AbstractCarrierAdapter
from ..models.shipment import (
    CarrierAllowlistError,
    CarrierConfigError,
    ShipmentRequest,
    ShipmentResult,
)

if TYPE_CHECKING:
    from ..factory import CarrierConfig


class DhlExpressLiveAdapter(AbstractCarrierAdapter):

    def __init__(self, config: "CarrierConfig") -> None:
        self._config = config
        self._allowlist: frozenset[str] = frozenset(
            b.strip() for b in config.live_allowlist.split(",") if b.strip()
        )

    # ── public interface ──────────────────────────────────────────────────────

    def create_shipment(self, request: ShipmentRequest) -> ShipmentResult:
        self._check_allowlist(request.batch_id)
        self._check_credentials()
        raise NotImplementedError(
            "DHL Express live API integration not yet implemented. "
            "Phase D will add the httpx call, idempotency write, and label handling."
        )

    def get_shipment(self, tracking_ref: str) -> ShipmentResult:
        self._check_credentials()
        raise NotImplementedError(
            "DHL Express live API integration not yet implemented. "
            "Phase D will add the httpx call and response mapping."
        )

    # ── private guards ────────────────────────────────────────────────────────

    def _check_allowlist(self, batch_id: str) -> None:
        if not self._allowlist:
            raise CarrierAllowlistError(
                "carrier_live_allowlist is empty — live calls require at least one "
                "batch_id in CARRIER_LIVE_ALLOWLIST."
            )
        if batch_id not in self._allowlist:
            raise CarrierAllowlistError(
                f"batch_id {batch_id!r} is not in carrier_live_allowlist. "
                "Add it to CARRIER_LIVE_ALLOWLIST to permit a live call."
            )

    def _check_credentials(self) -> None:
        if not self._config.api_key or not self._config.api_secret:
            raise CarrierConfigError(
                "DHL Express live mode requires both DHL_EXPRESS_API_KEY and "
                "DHL_EXPRESS_API_SECRET to be set."
            )
