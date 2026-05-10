"""
CarrierCoordinator — orchestrates shipment creation with idempotency.

Shadow-mode flow for create_shipment():
  1. compute_idempotency_key(request)
  2. shipment_db.get_shipment() — check cache
       COMPLETE  → return deterministic result (adapter is pure; no adapter call needed)
                   Actually: recompute via adapter (deterministic, zero cost) and return COMPLETE
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
from dataclasses import dataclass
from pathlib import Path

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
from .persistence.shipment_db import init_db as _init_shipment_db
from .persistence.shipment_db import insert_shipment as _db_insert
from .persistence.shipment_db import update_state as _db_update


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
            # Cache hit — adapter is deterministic so recompute in-memory,
            # then stamp the final state as COMPLETE.
            raw = self._adapter.create_shipment(request)
            return dataclasses.replace(raw, state=ShipmentState.COMPLETE)

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

        _db_update(self._config.shipment_db_path, key, ShipmentState.COMPLETE)

        return dataclasses.replace(raw_result, state=ShipmentState.COMPLETE)
