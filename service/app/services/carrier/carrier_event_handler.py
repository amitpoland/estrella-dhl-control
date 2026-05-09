"""
carrier_event_handler.py — Webhook event execution engine.

DL-E1 scope
-----------
Consumes ``CarrierEvent`` instances (already parsed by an adapter)
and decides what happens next:

  1. Compute a deterministic event_id from
     ``sha256(carrier|awb|status_code|occurred_at)``.
  2. Insert the event row via ``carrier_event_db.insert_event_or_ignore``.
     If the insert was a no-op (duplicate id), return outcome=deduped.
  3. Look up the shipment row in ``carrier_shipment_db`` by (carrier,
     awb). If absent → outcome=no_shipment, HTTP 200 from caller.
  4. Translate the statusCode via ``carrier_event_translator``.
  5. If the translation is an exception or unknown → call
     ``coordinator.record_exception`` (no state change, just a
     manifest message), mark outcome=ignored.
  6. Otherwise validate the move via ``carrier_state_engine`` and call
     the matching coordinator method. If the engine refuses (out-of-
     order replay), mark outcome=ignored.
  7. Mark outcome=applied on success and return the coordinator's
     result.

Hard rules
----------
* No FastAPI / Flask / web-framework imports.
* No HTTP client imports (requests / httpx / urllib).
* No live DHL adapter import (the handler is adapter-agnostic; the
  events arrive already parsed).
* Never raises for accepted-but-ignored events. The webhook layer
  must reply 2xx to DHL; only DB-write failures or programmer bugs
  bubble up.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional

from . import carrier_event_db as ced
from . import carrier_event_translator as cet
from . import carrier_shipment_db as csdb
from . import carrier_state_engine as cse
from .base import CarrierEvent
from .carrier_coordinator import (
    CarrierCoordinator,
    CarrierCoordinatorError,
)


# ── Outcome constants ───────────────────────────────────────────────────────

OUTCOME_APPLIED:        str = "applied"
OUTCOME_DEDUPED:        str = "deduped"
OUTCOME_IGNORED:        str = "ignored"
OUTCOME_NO_SHIPMENT:    str = "no_shipment"
OUTCOME_INGEST_FAILED:  str = "ingest_failed"


class CarrierEventHandler:
    """Execute one webhook event end-to-end.

    Construction
    ------------
    ``coordinator`` is an already-built :class:`CarrierCoordinator`
    bound to the same DB + label store as the events module. The
    handler does NOT instantiate the coordinator itself — the
    factory lives in the route layer (rule 9 from DL-D5).

    ``db_path`` is the carrier_event_db path. The handler binds it
    on construction; the route layer is responsible for ensuring
    main.py has called ``ced.init_db`` once at startup.
    """

    def __init__(
        self,
        *,
        coordinator: CarrierCoordinator,
        db_path:     Path,
    ) -> None:
        if coordinator is None:
            raise ValueError("coordinator is required")
        self._coord = coordinator
        self._db_path = Path(db_path)
        ced.init_db(self._db_path)

    # ── Public entry point ──────────────────────────────────────────────────

    def handle_event(self, event: CarrierEvent) -> Dict[str, Any]:
        """Process one event. Always returns a dict; never raises for
        accepted-but-ignored cases.

        Return shape::

            {
              "event_id":   str,
              "outcome":    str,                 # see OUTCOME_*
              "reason":     Optional[str],       # human-readable why
              "shipment_id": Optional[str],
              "result":     Optional[dict],      # coordinator return
              "unknown_status_code": bool,       # True for unmapped codes
            }
        """
        event_id = ced.compute_event_id(
            carrier     = event.carrier,
            awb         = event.awb,
            status_code = event.event_code,
            occurred_at = event.occurred_at,
        )

        # 1. INSERT OR IGNORE — duplicate event ids are no-ops.
        raw_payload = self._serialise_event(event)
        inserted = ced.insert_event_or_ignore(
            event_id    = event_id,
            carrier     = event.carrier,
            awb         = event.awb,
            status_code = event.event_code,
            occurred_at = event.occurred_at,
            raw_json    = raw_payload,
        )
        if not inserted:
            return self._make_result(
                event_id=event_id,
                outcome=OUTCOME_DEDUPED,
                reason="duplicate event id",
            )

        # 2. Look up the shipment row.
        row = csdb.get_by_awb(event.carrier, event.awb)
        if row is None:
            ced.mark_outcome(event_id, OUTCOME_NO_SHIPMENT)
            return self._make_result(
                event_id=event_id,
                outcome=OUTCOME_NO_SHIPMENT,
                reason=f"no carrier shipment for {event.carrier!r}/{event.awb!r}",
            )

        # 3. Translate statusCode → (target state, coordinator method).
        translation = cet.translate(event)

        # 4. Exception / unknown — no state change. Append a manifest
        #    message via record_exception and mark ignored.
        if translation.target_state is None:
            return self._dispatch_exception(
                event=event,
                translation=translation,
                event_id=event_id,
                row=row,
            )

        # 5. State-engine legality check before the coordinator call.
        #    The coordinator validates again (defense-in-depth) but we
        #    short-circuit here so out-of-order replays do not raise
        #    inside the coordinator's lock.
        if not cse.can_transition(row["state"], translation.target_state):
            ced.mark_outcome(
                event_id, OUTCOME_IGNORED, shipment_id=row["id"],
            )
            return self._make_result(
                event_id=event_id,
                outcome=OUTCOME_IGNORED,
                reason=(
                    f"illegal carrier transition "
                    f"{row['state']!r} → {translation.target_state!r}"
                ),
                shipment_id=row["id"],
            )

        # 6. Apply the transition through the coordinator.
        return self._dispatch_state_change(
            event=event,
            translation=translation,
            event_id=event_id,
            row=row,
        )

    # ── Internal helpers ────────────────────────────────────────────────────

    def _dispatch_exception(
        self,
        *,
        event:       CarrierEvent,
        translation: cet.Translation,
        event_id:    str,
        row:         Dict[str, Any],
    ) -> Dict[str, Any]:
        """Call coordinator.record_exception and mark outcome=ignored."""
        try:
            self._coord.record_exception(
                carrier      = event.carrier,
                awb          = event.awb,
                reason       = (
                    event.description or event.event_code
                    or "carrier-exception"
                ),
                status_code  = event.event_code,
                location     = event.location,
                description  = event.description,
            )
        except (ValueError, CarrierCoordinatorError) as exc:
            ced.mark_outcome(
                event_id, OUTCOME_IGNORED, shipment_id=row["id"],
            )
            return self._make_result(
                event_id=event_id,
                outcome=OUTCOME_IGNORED,
                reason=str(exc),
                shipment_id=row["id"],
                unknown_status_code=translation.unknown,
            )
        ced.mark_outcome(event_id, OUTCOME_IGNORED, shipment_id=row["id"])
        return self._make_result(
            event_id=event_id,
            outcome=OUTCOME_IGNORED,
            reason=(
                "unknown_status_code" if translation.unknown
                else "informational exception"
            ),
            shipment_id=row["id"],
            unknown_status_code=translation.unknown,
        )

    def _dispatch_state_change(
        self,
        *,
        event:       CarrierEvent,
        translation: cet.Translation,
        event_id:    str,
        row:         Dict[str, Any],
    ) -> Dict[str, Any]:
        """Call the matching coordinator method for a real state change."""
        method = getattr(self._coord, translation.coordinator_method)
        try:
            outcome = method(
                carrier = event.carrier,
                awb     = event.awb,
                reason  = (
                    event.description
                    or f"carrier-event:{event.event_code}"
                ),
            )
        except (ValueError, CarrierCoordinatorError) as exc:
            # State engine rejected at coordinator layer (race window)
            # — treat as ignored, never raise.
            ced.mark_outcome(
                event_id, OUTCOME_IGNORED, shipment_id=row["id"],
            )
            return self._make_result(
                event_id=event_id,
                outcome=OUTCOME_IGNORED,
                reason=str(exc),
                shipment_id=row["id"],
            )
        ced.mark_outcome(event_id, OUTCOME_APPLIED, shipment_id=row["id"])
        return self._make_result(
            event_id=event_id,
            outcome=OUTCOME_APPLIED,
            reason=None,
            shipment_id=row["id"],
            result=outcome,
        )

    @staticmethod
    def _serialise_event(event: CarrierEvent) -> str:
        """JSON-serialise a CarrierEvent for the raw_json column.

        The event's ``raw`` may carry adapter metadata (live=True
        marker, headers_seen flag, full DHL shipment dict). We persist
        the whole thing so the audit trail can reconstruct the
        original signal.
        """
        try:
            return json.dumps(asdict(event), default=str, sort_keys=True)
        except Exception:
            return json.dumps({
                "carrier":     event.carrier,
                "awb":         event.awb,
                "event_code":  event.event_code,
                "occurred_at": event.occurred_at,
            }, sort_keys=True)

    @staticmethod
    def _make_result(
        *,
        event_id:             str,
        outcome:              str,
        reason:               Optional[str] = None,
        shipment_id:          Optional[str] = None,
        result:               Optional[Dict[str, Any]] = None,
        unknown_status_code:  bool = False,
    ) -> Dict[str, Any]:
        return {
            "event_id":            event_id,
            "outcome":             outcome,
            "reason":              reason,
            "shipment_id":         shipment_id,
            "result":              result,
            "unknown_status_code": unknown_status_code,
        }
