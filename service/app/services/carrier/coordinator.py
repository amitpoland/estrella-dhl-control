"""
CarrierCoordinator — orchestrates shipment creation with idempotency.

Shadow-mode flow for create_shipment():
  1. compute_idempotency_key(request)
  2. shipment_db.get_shipment() — check cache
       COMPLETE  → return the STORED result (tracking_ref persisted at COMPLETE).
                   The adapter is NEVER re-invoked for a completed key — the
                   live adapter would book a new DHL shipment (2026-07-06
                   duplicate-AWB incident).
       PENDING   → in-flight recovery: re-execute from step 5 (skip DB insert)
       FAILED    → raise CarrierGateError (explicit, not silently retried)
       not found → continue
  3. shipment_db.insert_shipment(PENDING)
  4. adapter.create_shipment(request)
  5. redact_response(raw_result_dict, mode=SHADOW)
  6. shadow_log_db.append_entry(redacted)
  7. shipment_db.update_state(COMPLETE)
  8. return COMPLETE result

Retry guarantee: a second call with the same request never reaches the adapter.
No live AWBs, no label bytes, no HTTP.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, Optional

from .factory import CarrierConfig, get_adapter
from .models.shipment import (
    CarrierGateError,
    ShipmentMode,
    ShipmentRequest,
    ShipmentResult,
    ShipmentState,
    compute_idempotency_key,
)
from .persistence.redactor import redact_response
from .persistence.shadow_log_db import append_entry as _shadow_log_append
from .persistence.shadow_log_db import init_db as _init_shadow_log
from .persistence.shipment_db import get_shipment as _db_get
from .persistence.shipment_db import get_shipment_by_batch_id as _db_get_by_batch
from .persistence.shipment_db import init_db as _init_shipment_db
from .persistence.shipment_db import insert_shipment as _db_insert
from .persistence.shipment_db import update_state as _db_update
from ...core.config import settings


# ── AWB stability predicate (read-only — added in W-5 / P0) ───────────────────
#
# The spec vocabulary {awb_issued, label_created, label_printed, handed_to_carrier}
# (ADR-013) does not exist 1:1 in the carrier ShipmentState enum, which holds
# {pending, submitted, complete, failed}. The mapping locked at P0 is:
#
#     awb_issued       → SUBMITTED (idempotency row + adapter response confirmed)
#     label_created    → SUBMITTED
#     label_printed    → SUBMITTED
#     handed_to_carrier→ COMPLETE  (full carrier-side close)
#
# Therefore the stable set is {SUBMITTED, COMPLETE}. PENDING (in-flight),
# FAILED (error), and not-found all return False.

_AWB_STABLE_STATES: FrozenSet[str] = frozenset({
    ShipmentState.SUBMITTED.value,
    ShipmentState.COMPLETE.value,
})


def is_state_stable(state: Optional[str]) -> bool:
    """Pure helper — True iff a carrier ShipmentState string is in the stable set."""
    if not state:
        return False
    return state in _AWB_STABLE_STATES


def is_awb_stable(
    awb:     str,
    *,
    db_path: Optional[Path] = None,
    state_override: Optional[str] = None,
) -> bool:
    """
    Read-only predicate: True iff *awb* corresponds to a carrier shipment whose
    current state is in {SUBMITTED, COMPLETE}.

    Resolution order:
        1. *state_override* (test injection / explicit caller)
        2. carrier shipment_db lookup by batch_id  (awb used as batch_id surrogate)
        3. False (unresolved)

    AWB→batch_id direct mapping does not exist in P0; P2 wires the proper
    resolver via the audit / tracking layer. P0 callers MAY pass
    state_override to test the mapping deterministically.

    NEVER mutates any state — purely read-only.
    """
    if state_override is not None:
        return is_state_stable(state_override)

    if not awb or db_path is None:
        return False

    row = _db_get_by_batch(db_path, awb)
    if not row:
        return False
    return is_state_stable(row.get("state"))


@dataclass
class CoordinatorConfig:
    """All coordinator dependencies are caller-provided paths and a CarrierConfig."""
    carrier_config: CarrierConfig
    shipment_db_path: Path
    shadow_log_db_path: Path


class CarrierCoordinator:

    def __init__(self, config: CoordinatorConfig) -> None:
        self._config = config
        self._adapter = get_adapter(config.carrier_config)
        _init_shipment_db(config.shipment_db_path)
        _init_shadow_log(config.shadow_log_db_path)

    # ── public ────────────────────────────────────────────────────────────────

    def create_shipment(self, request: ShipmentRequest) -> ShipmentResult:
        key = compute_idempotency_key(request)
        existing = _db_get(self._config.shipment_db_path, key)

        if existing:
            return self._handle_existing(request, key, existing)

        return self._execute(request, key, is_recovery=False)

    # ── private ───────────────────────────────────────────────────────────────

    def _handle_existing(
        self,
        request: ShipmentRequest,
        key: str,
        row: dict,
    ) -> ShipmentResult:
        state = ShipmentState(row["state"])

        if state == ShipmentState.COMPLETE:
            # Cache hit — return the STORED result. NEVER re-invoke the
            # adapter for a completed key: the live adapter would create a
            # brand-new DHL shipment (2026-07-06 duplicate-AWB incident —
            # 3 duplicate live AWBs booked by "deterministic recompute").
            return ShipmentResult(
                idempotency_key=key,
                mode=ShipmentMode(row["mode"]),
                state=ShipmentState.COMPLETE,
                tracking_ref=row.get("tracking_ref"),
                error=row.get("error"),
                simulated=bool(row.get("simulated")),
                service_product=row.get("service_product"),
                dimensions_json=row.get("dimensions_json"),
                replayed=True,
            )

        if state == ShipmentState.PENDING:
            # In-flight recovery: the pending row exists but completion never
            # ran (e.g. process crash after insert, before update_state).
            # Re-execute without re-inserting the row.
            return self._execute(request, key, is_recovery=True)

        if state == ShipmentState.FAILED:
            raise CarrierGateError(
                f"Shipment {key[:12]}… previously failed: "
                f"{row.get('error') or 'unknown error'}. "
                "Submit a new request with different parameters to retry."
            )

        raise CarrierGateError(
            f"Shipment {key[:12]}… is in unexpected state {row['state']!r}."
        )

    def _execute(
        self,
        request: ShipmentRequest,
        key: str,
        is_recovery: bool,
    ) -> ShipmentResult:
        if not is_recovery:
            # Write PENDING before the adapter call — crash-safe anchor.
            _db_insert(
                self._config.shipment_db_path,
                ShipmentResult(
                    idempotency_key=key,
                    mode=ShipmentMode.SHADOW,
                    state=ShipmentState.PENDING,
                    simulated=True,
                ),
                request.batch_id,
            )

        # Adapter call — pure, deterministic, no side effects.
        raw_result = self._adapter.create_shipment(request)

        # Build a safe request snapshot for the shadow log.
        log_request = {
            "batch_id": request.batch_id,
            "shipper_account": request.shipper_account,
            "weight_kg": request.weight_kg,
            "declared_value": request.declared_value,
            "currency": request.currency,
        }

        # Convert result to a plain dict (enum values as strings) for redaction.
        raw_response = {
            "idempotency_key": raw_result.idempotency_key,
            "mode": raw_result.mode.value,
            "state": raw_result.state.value,
            "tracking_ref": raw_result.tracking_ref,
            "error": raw_result.error,
            "simulated": raw_result.simulated,
        }
        redacted = redact_response(raw_response, ShipmentMode.SHADOW)

        _shadow_log_append(
            self._config.shadow_log_db_path,
            request.batch_id,
            key,
            log_request,
            redacted,
        )

        # Persist adapter-truth fields with COMPLETE so a replay can return
        # the stored result without touching the adapter (incident fix).
        _db_update(
            self._config.shipment_db_path,
            key,
            ShipmentState.COMPLETE,
            tracking_ref=raw_result.tracking_ref,
            mode=raw_result.mode,
            simulated=raw_result.simulated,
        )

        # Phase 5 — attach request dimensions so they are captured in the DB
        # via the COMPLETE result. service_product is adapter-provided (None
        # for shadow mode; Phase D live adapter will populate it).
        dimensions_json: Optional[str] = None
        try:
            if request.dimensions:
                dimensions_json = json.dumps(request.dimensions, ensure_ascii=False)
        except (TypeError, ValueError):
            pass

        complete = dataclasses.replace(
            raw_result,
            state=ShipmentState.COMPLETE,
            dimensions_json=dimensions_json,
        )

        # Register outbound tracking event if enabled (flag-gated, non-transactional)
        if (settings.outbound_tracking_registration_enabled
                and complete.tracking_ref
                and not complete.simulated):
            try:
                from ...services import tracking_db
                from datetime import datetime, timezone
                event_time = datetime.now(timezone.utc).isoformat()
                tracking_db.record_event(
                    batch_id=request.batch_id,
                    awb=complete.tracking_ref,
                    carrier=self._adapter.carrier_id if hasattr(self._adapter, 'carrier_id') else 'DHL',
                    stage="outbound_created",
                    status=complete.state.value,
                    event_time=event_time,
                    source="carrier_coordinator",
                    source_ref=complete.tracking_ref,
                    direction="outbound",
                )
            except Exception:
                import logging
                logging.getLogger(__name__).warning("outbound tracking registration failed", exc_info=True)

        # Update the DB row with the enriched fields now that we have them.
        from .persistence.shipment_db import update_shipment_fields as _db_update_fields
        try:
            _db_update_fields(
                self._config.shipment_db_path,
                key,
                service_product=complete.service_product,
                dimensions_json=complete.dimensions_json,
            )
        except Exception:
            pass  # best-effort — state already COMPLETE above

        return complete
