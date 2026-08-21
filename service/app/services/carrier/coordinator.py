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
  5. shipment_db.update_state(COMPLETE, tracking_ref) — adapter truth is
     persisted BEFORE any audit work, so a failure in step 6/7 can never
     leave a real AWB behind a PENDING row that a retry would re-book.
  6. redact_response(raw_result_dict, mode=SHADOW)
  7. shadow_log_db.append_entry(redacted)
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
    CarrierProviderStateUnknownError,
    ShipmentMode,
    ShipmentRequest,
    ShipmentResult,
    ShipmentState,
    compute_external_idempotency_key,
    compute_idempotency_key,
    normalize_tracking_ref,
)
from .persistence.redactor import redact_response
from .persistence.shadow_log_db import append_entry as _shadow_log_append
from .persistence.shadow_log_db import init_db as _init_shadow_log
from .persistence.shipment_db import get_shipment as _db_get
from .persistence.shipment_db import get_shipment_by_batch_id as _db_get_by_batch
from .persistence.shipment_db import get_shipment_for_draft as _db_get_for_draft
from .persistence.shipment_db import init_db as _init_shipment_db
from .persistence.shipment_db import insert_shipment as _db_insert
from .persistence.shipment_db import update_state as _db_update
from .persistence.shipment_db import persist_notification_audit as _db_persist_notify
from .persistence.shipment_db import EXTERNAL_PROVIDERS, PROVIDER_DHL, PROVIDER_OTHER
from .persistence.shipment_db import is_valid_provider_code, normalize_provider_code
from .notification_audit import build_notification_audit
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


def _mask_account(number: Optional[str]) -> Optional[str]:
    """Last four digits only, for the billing audit record.

    Same shape AccountChoice.masked renders, so the stored row and the operator
    screen read alike. None stays None: a sender-paid booking has no separate
    payer account, and writing the shipper's number here would invent one.
    """
    tail = (number or "").strip()[-4:]
    return f"•••• {tail}" if tail else None


class CarrierCoordinator:

    def __init__(self, config: CoordinatorConfig) -> None:
        self._config = config
        # Adapter is resolved per booking from the selected provider.
        # Binding DHL at init would silently ignore FedEx/UPS selection.
        self._adapter = None
        _init_shipment_db(config.shipment_db_path)
        _init_shadow_log(config.shadow_log_db_path)

    def _adapter_for(self, provider: str):
        return get_adapter(self._config.carrier_config, provider)

    # ── public ────────────────────────────────────────────────────────────────

    def create_shipment(
        self,
        request: ShipmentRequest,
        *,
        operator: Optional[str] = None,
        provider: str = PROVIDER_DHL,
    ) -> ShipmentResult:
        """Create (or idempotently replay) a shipment.

        operator (keyword-only) is the X-Operator attribution recorded as the
        booker. It is persisted ONLY on a first, real booking; an idempotent
        replay preserves and returns the ORIGINAL booker instead of overwriting
        it with whoever triggered the replay. None keeps the pre-attribution
        behaviour unchanged.
        """
        provider = normalize_provider_code(provider) or PROVIDER_DHL
        self._adapter = self._adapter_for(provider)
        key = compute_idempotency_key(request)
        existing = _db_get(self._config.shipment_db_path, key)

        if existing:
            return self._handle_existing(
                request, key, existing, operator=operator, provider=provider,
            )

        return self._execute(
            request, key, is_recovery=False, operator=operator, provider=provider,
        )

    # ── private ───────────────────────────────────────────────────────────────

    def _handle_existing(
        self,
        request: ShipmentRequest,
        key: str,
        row: dict,
        *,
        operator: Optional[str] = None,
        provider: str = PROVIDER_DHL,
    ) -> ShipmentResult:
        state = ShipmentState(row["state"])

        if state == ShipmentState.COMPLETE:
            # Cache hit — return the STORED result. NEVER re-invoke the
            # adapter for a completed key: the live adapter would create a
            # brand-new DHL shipment (2026-07-06 duplicate-AWB incident —
            # 3 duplicate live AWBs booked by "deterministic recompute").
            # booked_by is read from the stored row, not the current caller:
            # a replay must report the ORIGINAL booker for audit integrity.
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
                booked_by=row.get("booked_by"),
            )

        if state == ShipmentState.PENDING:
            # In-flight recovery: the pending row exists but completion never
            # ran (e.g. process crash after insert, before update_state).
            # Re-execute without re-inserting the row. The original booker was
            # captured at the first insert; the current caller's operator is
            # forwarded but _execute always restores booked_by from the stored
            # row, so the original attribution wins.
            return self._execute(
                request, key, is_recovery=True, operator=operator, provider=provider,
            )

        if state == ShipmentState.FAILED:
            raise CarrierGateError(
                f"Shipment {key[:12]}… previously failed: "
                f"{row.get('error') or 'unknown error'}. "
                "Resolve the recorded cause before retrying. If the provider "
                "state is unknown, reconcile at the carrier first — changing "
                "parameters books a NEW shipment, it does not retry this one."
            )

        raise CarrierGateError(
            f"Shipment {key[:12]}… is in unexpected state {row['state']!r}."
        )

    def _execute(
        self,
        request: ShipmentRequest,
        key: str,
        is_recovery: bool,
        *,
        operator: Optional[str] = None,
        provider: str = PROVIDER_DHL,
    ) -> ShipmentResult:
        if self._adapter is None:
            self._adapter = self._adapter_for(provider)
        if not is_recovery:
            # Write PENDING before the adapter call — crash-safe anchor.
            # operator is written here (and only here) as booked_by.
            _db_insert(
                self._config.shipment_db_path,
                ShipmentResult(
                    idempotency_key=key,
                    mode=ShipmentMode.SHADOW,
                    state=ShipmentState.PENDING,
                    simulated=True,
                ),
                request.batch_id,
                getattr(request, "client_ref", None),
                operator=operator,
                provider=provider,
                # Recorded from the request the resolver produced, so the row
                # states who was billed for THIS booking. Masked to the last
                # four: enough to reconcile a DHL invoice, never a credential.
                transport_payer=getattr(request, "transport_payer", None),
                billing_account_masked=_mask_account(
                    getattr(request, "billing_account", None)),
            )

        # Adapter call — THE external provider write. Once this returns,
        # a real, chargeable AWB may already exist at the carrier.
        try:
            raw_result = self._adapter.create_shipment(request)
        except CarrierProviderStateUnknownError as exc:
            # The request reached the carrier but the reply was lost, so a real
            # AWB may exist with no tracking_ref to record. Park the key in a
            # TERMINAL state: _handle_existing refuses FAILED, where PENDING
            # would re-enter _execute and book a SECOND chargeable shipment.
            _db_update(
                self._config.shipment_db_path,
                key,
                ShipmentState.FAILED,
                error=str(exc),
            )
            raise

        # Persist adapter truth FIRST — nothing may run between the provider
        # write and this update. Everything below is audit enrichment that can
        # raise (sqlite lock, disk, redaction); if the row were still PENDING at
        # that moment, _handle_existing would re-enter _execute on the operator's
        # retry and book a SECOND live AWB for a shipment DHL already created.
        # Recording the tracking_ref here turns that retry into a replay.
        _db_update(
            self._config.shipment_db_path,
            key,
            ShipmentState.COMPLETE,
            tracking_ref=raw_result.tracking_ref,
            mode=raw_result.mode,
            simulated=raw_result.simulated,
        )

        # Build a safe request snapshot for the shadow log. operator is part of
        # the booking-attribution audit trail, so it rides along here too.
        # MyDHL shipmentNotification audit is masks-only (never raw email/phone).
        notify_audit = build_notification_audit(request.recipient_address)
        log_request = {
            "batch_id": request.batch_id,
            "shipper_account": request.shipper_account,
            "weight_kg": request.weight_kg,
            "declared_value": request.declared_value,
            "currency": request.currency,
            "operator": operator,
            "dhl_notify_audit": {
                k: notify_audit[k]
                for k in (
                    "dhl_notify_email_requested",
                    "dhl_notify_sms_requested",
                    "dhl_notify_email_masked",
                    "dhl_notify_sms_masked",
                    "dhl_notify_recipient_source",
                    "dhl_notify_provider",
                    "dhl_notify_requested_at",
                    "type_codes",
                )
                if k in notify_audit
            },
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

        # Audit enrichment, AFTER the COMPLETE write. The booking is already
        # real and its tracking_ref is already persisted; a locked sqlite file
        # here must not surface as an HTTP 500 that hides a booked AWB from the
        # operator. Log loudly and return the booking.
        try:
            _shadow_log_append(
                self._config.shadow_log_db_path,
                request.batch_id,
                key,
                log_request,
                redacted,
            )
            # Booking-time MyDHL shipmentNotification audit (masks only). First
            # COMPLETE write wins — idempotent replay preserves the original stamp.
            _db_persist_notify(self._config.shipment_db_path, key, notify_audit)
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "carrier audit write failed after COMPLETE for key %s", key[:12]
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

        # Multi-package split, when the operator entered one. Stays NULL for a
        # single-package booking — an absent split is not a parcel count of 1
        # measured in the warehouse, it is simply no split.
        packages_json: Optional[str] = None
        try:
            if getattr(request, "packages", None):
                packages_json = json.dumps(request.packages, ensure_ascii=False)
        except (TypeError, ValueError):
            pass

        # Report the PERSISTED booker on the result. For a fresh booking this
        # is the operator just inserted; for a crash-recovery replay it is the
        # ORIGINAL booker recorded at the first insert (this call skipped the
        # insert). Reading it back keeps the two paths honest and identical.
        # The fallback is None (honest-missing) — never the current caller — so
        # a failed read on a recovery path cannot mis-attribute to the replayer.
        booked_by = None
        try:
            _row = _db_get(self._config.shipment_db_path, key)
            if _row is not None:
                booked_by = _row.get("booked_by")
        except Exception:
            pass

        complete = dataclasses.replace(
            raw_result,
            state=ShipmentState.COMPLETE,
            dimensions_json=dimensions_json,
            booked_by=booked_by,
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
                    carrier=provider or (
                        self._adapter.carrier_id if hasattr(self._adapter, 'carrier_id') else 'DHL'
                    ),
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
        # weight/value/currency/box come from the request so the Logistics tab
        # can show the real shipment summary without re-deriving it.
        from .persistence.shipment_db import update_shipment_fields as _db_update_fields
        try:
            _db_update_fields(
                self._config.shipment_db_path,
                key,
                service_product=complete.service_product,
                dimensions_json=complete.dimensions_json,
                weight_kg=request.weight_kg,
                declared_value=request.declared_value,
                currency=request.currency,
                box_type_code=request.box_type_code,
                carrier_transaction_id=getattr(complete, "carrier_transaction_id", None),
                packages_json=packages_json,
            )
        except Exception:
            pass  # best-effort — state already COMPLETE above

        return complete


def register_external_shipment(
    db_path: Path,
    *,
    batch_id: str,
    provider: str,
    tracking_ref: str,
    client_ref: Optional[str] = None,
    operator: Optional[str] = None,
    service_product: Optional[str] = None,
    master_data_db_path: Optional[Path] = None,
) -> ShipmentResult:
    """Register a customer-arranged external shipment. Never calls a carrier API.

    Writes the existing ``carrier_shipments`` row (mode=external, state=complete)
    with provider + tracking_ref. DHL is rejected — it stays on create_shipment.

    Provider vocabulary:
      • legacy FEDEX / UPS / OTHER always accepted
      • any *active* Carrier Master ``carrier_code`` accepted when
        ``master_data_db_path`` is supplied (no new carrier table)
      • CM codes outside FEDEX/UPS/OTHER are stored as OTHER (closed DB vocab)
    """
    _init_shipment_db(db_path)

    p = normalize_provider_code(provider)
    if p == PROVIDER_DHL:
        raise CarrierGateError(
            "DHL shipments must be created through the existing booking path."
        )
    allowed = set(EXTERNAL_PROVIDERS)
    if master_data_db_path is not None:
        try:
            from ..master_data_db import list_carrier_configs
            for cfg in list_carrier_configs(Path(master_data_db_path), active=True):
                code = normalize_provider_code(getattr(cfg, "carrier_code", "") or "")
                if code and code != PROVIDER_DHL and is_valid_provider_code(code):
                    allowed.add(code)
        except Exception:
            # Master read failure must not widen vocabulary — fall back to legacy set.
            pass
    if p not in allowed or not is_valid_provider_code(p):
        raise CarrierGateError(
            f"Unknown carrier provider {p!r}; expected one of {sorted(allowed)}"
        )
    # Idempotency key keeps the operator/CM code; row storage stays closed.
    store_provider = p if p in EXTERNAL_PROVIDERS else PROVIDER_OTHER

    ref = normalize_tracking_ref(tracking_ref)
    if not ref:
        raise CarrierGateError("tracking_ref is required")

    scoped = (client_ref or "").strip() or None
    key = compute_external_idempotency_key(
        batch_id=batch_id,
        provider=p,
        tracking_ref=ref,
        client_ref=scoped,
    )
    existing = _db_get(db_path, key)
    if existing:
        return _complete_or_replay_external(
            db_path, key, existing, ref, operator=operator,
        )

    other = _db_get_for_draft(
        db_path, batch_id, scoped, allow_single_client_fallback=True,
    )
    if other and other.get("idempotency_key") != key:
        other_state = other.get("state") or ""
        if other_state in ("complete", "submitted", "pending"):
            raise CarrierGateError(
                "A shipment already exists for this draft; "
                "refusing a second outbound registration."
            )

    _db_insert(
        db_path,
        ShipmentResult(
            idempotency_key=key,
            mode=ShipmentMode.EXTERNAL,
            state=ShipmentState.PENDING,
            simulated=False,
            service_product=service_product,
        ),
        batch_id,
        scoped,
        operator=operator,
        provider=store_provider,
    )
    _db_update(
        db_path,
        key,
        ShipmentState.COMPLETE,
        tracking_ref=ref,
        mode=ShipmentMode.EXTERNAL,
        simulated=False,
    )
    if service_product:
        from .persistence.shipment_db import update_shipment_fields as _db_update_fields
        _db_update_fields(db_path, key, service_product=service_product)

    row = _db_get(db_path, key) or {}
    return ShipmentResult(
        idempotency_key=key,
        mode=ShipmentMode.EXTERNAL,
        state=ShipmentState.COMPLETE,
        tracking_ref=ref,
        simulated=False,
        service_product=row.get("service_product") or service_product,
        booked_by=row.get("booked_by"),
        replayed=False,
    )


def _complete_or_replay_external(
    db_path: Path,
    key: str,
    row: dict,
    tracking_ref: str,
    *,
    operator: Optional[str] = None,
) -> ShipmentResult:
    """Replay COMPLETE; finish a crashed PENDING; refuse FAILED. No adapter."""
    del operator  # attribution is frozen at insert; replay must not overwrite.
    state = ShipmentState(row["state"])
    if state == ShipmentState.COMPLETE:
        return ShipmentResult(
            idempotency_key=key,
            mode=ShipmentMode(row["mode"]),
            state=ShipmentState.COMPLETE,
            tracking_ref=row.get("tracking_ref") or tracking_ref,
            error=row.get("error"),
            simulated=bool(row.get("simulated")),
            service_product=row.get("service_product"),
            replayed=True,
            booked_by=row.get("booked_by"),
        )
    if state == ShipmentState.PENDING:
        _db_update(
            db_path,
            key,
            ShipmentState.COMPLETE,
            tracking_ref=tracking_ref,
            mode=ShipmentMode.EXTERNAL,
            simulated=False,
        )
        stored = _db_get(db_path, key) or row
        return ShipmentResult(
            idempotency_key=key,
            mode=ShipmentMode.EXTERNAL,
            state=ShipmentState.COMPLETE,
            tracking_ref=tracking_ref,
            simulated=False,
            service_product=stored.get("service_product"),
            booked_by=stored.get("booked_by"),
            replayed=False,
        )
    if state == ShipmentState.FAILED:
        raise CarrierGateError(
            f"Shipment {key[:12]}… previously failed: "
            f"{row.get('error') or 'unknown error'}. "
            "Resolve the recorded cause before retrying. If the provider "
            "state is unknown, reconcile at the carrier first — changing "
            "parameters books a NEW shipment, it does not retry this one."
        )
    raise CarrierGateError(
        f"Shipment {key[:12]}… is in unexpected state {row['state']!r}."
    )
