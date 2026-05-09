"""
carrier_coordinator.py — DL-D1 skeleton.

Orchestrates the outbound shipment lifecycle on top of:
  * the carrier state engine (legality validation),
  * the carrier shipment DB (persistence + transition history),
  * the carrier label store (content-addressed evidence),
  * an injected ``CarrierAdapter`` (DHL/FedEx/UPS / stub).

DL-D1 scope
-----------
Coordinator-only plumbing. No HTTP write routes, no action proposals,
no inventory-state coupling, no closure-gate integration. Those land
in DL-D2/3/4.

Hard rules (also enforced by source-grep tests)
-----------------------------------------------
* No global adapter singleton — every coordinator carries its own
  injected adapter.
* No environment-variable reads. All config arrives via __init__.
* No FastAPI imports.
* No imports from the action-proposal route layer (DL-D2 boundary).
* No outbound HTTP except via the injected adapter.
* No global instantiation of any concrete adapter — the type-hint is
  the Protocol, never the stub class.

Contract
--------
``CarrierCoordinator`` is constructed with four explicit dependencies
(``db_path``, ``label_store_root``, ``adapter``, ``actor``) and exposes
four lifecycle methods that mutate the registry only through the state
engine:

  * ``create_shipment(batch_id, request, reason=None)``
  * ``cancel_shipment(carrier, awb, reason=None)``
  * ``mark_label_printed(carrier, awb, reason=None)``
  * ``mark_handed_to_carrier(carrier, awb, reason=None)``

Every state mutation passes through ``carrier_state_engine.transition``
before any DB row is written. The DB layer is dumb persistence; the
state engine is the single source of truth on legality.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import carrier_label_store as cls
from . import carrier_shipment_db as csdb
from . import carrier_state_engine as cse
from .adapters.base import CarrierAdapter
from .base import CarrierShipmentRequest, RawShipmentResponse


# ── Module-level error class ────────────────────────────────────────────────

class CarrierCoordinatorError(RuntimeError):
    """Raised for coordinator-layer errors (shipment-not-found,
    illegal-state etc.). State-engine illegal-transition errors stay
    as ``ValueError`` so callers see the carrier-state-engine message
    verbatim."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Coordinator ─────────────────────────────────────────────────────────────

class CarrierCoordinator:
    """Single orchestration entry point for outbound shipments.

    Construction
    ------------
    ``db_path``         path to the carrier_shipments.db SQLite file.
    ``label_store_root`` directory under which the content-addressed
                        label store lives.
    ``adapter``         a concrete ``CarrierAdapter`` (DHL Express
                        stub in dev/test; live DHL in DL-F).
    ``actor``           identity attached to every transition row,
                        defaults to ``"system"``.

    Constructing a coordinator is the only place that calls
    ``init_db`` / ``init_store`` for the carrier modules. Tests that
    need a fresh DB and label store should construct a coordinator
    against ``tmp_path`` instead of poking the singletons by hand.
    """

    def __init__(
        self,
        *,
        db_path:          Path,
        label_store_root: Path,
        adapter:          CarrierAdapter,
        actor:            str = "system",
    ) -> None:
        if adapter is None:
            raise ValueError("adapter is required")
        if not isinstance(adapter, CarrierAdapter):
            raise TypeError(
                "adapter does not satisfy CarrierAdapter Protocol"
            )
        self._db_path: Path          = Path(db_path)
        self._label_root: Path       = Path(label_store_root)
        self._adapter: CarrierAdapter = adapter
        self._actor: str             = actor or "system"

        # Singleton modules use module-level state; bind them to this
        # coordinator's paths. Instantiating two coordinators with
        # different paths in the same process is a programming error
        # — main.py constructs exactly one.
        csdb.init_db(self._db_path)
        cls.init_store(self._label_root)

    # ── create_shipment ─────────────────────────────────────────────────────

    def create_shipment(
        self,
        *,
        batch_id: str,
        request:  CarrierShipmentRequest,
        reason:   Optional[str] = None,
    ) -> Dict[str, Any]:
        """End-to-end shipment creation.

        Flow:
          1. Adapter issues the AWB and returns label bytes.
          2. Validate ``pre_awb → awb_issued`` and
             ``awb_issued → label_created`` via the state engine
             (no row is touched if either move is illegal).
          3. Save the label artefact (content-addressed; same bytes
             dedupe on disk).
          4. Write the manifest with request/response metadata.
          5. Upsert the registry row at ``label_created``.
          6. Append two transitions to the history table.

        Returns
        -------
        ``{"shipment": <row>, "label_sha256": str, "manifest_path": str,
           "transitions": [<row>, <row>], "raw_response": {...}}``
        """
        if not isinstance(request, CarrierShipmentRequest):
            raise TypeError("request must be a CarrierShipmentRequest")
        if not (batch_id or "").strip():
            raise ValueError("batch_id is required")

        # 1. adapter call (only network/HTTP boundary)
        rsp: RawShipmentResponse = self._adapter.create_shipment(request)
        if not rsp.awb or not rsp.carrier:
            raise CarrierCoordinatorError(
                "adapter returned response with empty awb or carrier"
            )

        # 2. validate the two transitions BEFORE any persistence —
        # if either is illegal, fail fast and leave no state behind.
        # (For a fresh shipment both moves are always legal, but we
        # still call the state engine so the source of truth on
        # legality is one place.)
        cse.transition(cse.PRE_AWB, cse.AWB_ISSUED)
        cse.transition(cse.AWB_ISSUED, cse.LABEL_CREATED)

        # 3. save label artefact (content-addressed; idempotent)
        artefact = cls.save_attachment(
            rsp.label_bytes,
            suffix=rsp.label_format or "pdf",
        )

        # 4. write manifest with request/response metadata
        manifest = {
            "carrier":        rsp.carrier,
            "awb":            rsp.awb,
            "batch_id":       batch_id,
            "state":          cse.LABEL_CREATED,
            "label_sha256":   artefact.sha256,
            "label_format":   rsp.label_format or "",
            "label_filename": rsp.label_filename or "",
            "label_path":     artefact.path,
            "actor":          self._actor,
            "reason":         reason or "",
            "request": {
                "batch_id":          request.batch_id,
                "service_code":      request.service_code,
                "reference":         request.reference,
                "package_count":     len(request.packages),
                "ship_from_country": request.ship_from.country,
                "ship_to_country":   request.ship_to.country,
            },
            "response": {
                "raw":            dict(rsp.raw or {}),
                "label_format":   rsp.label_format,
                "label_filename": rsp.label_filename,
            },
            "lifecycle": {
                "created_at":  _now(),
                "actor":       self._actor,
            },
        }
        manifest_path = cls.write_manifest(rsp.awb, manifest)

        # 5. upsert registry row at the final state
        row = csdb.upsert_shipment(
            carrier       = rsp.carrier,
            awb           = rsp.awb,
            state         = cse.LABEL_CREATED,
            batch_id      = batch_id,
            label_sha256  = artefact.sha256,
            manifest_path = str(manifest_path),
        )

        # 6. append the two transitions chronologically
        t1 = csdb.record_transition(
            shipment_id = row["id"],
            from_state  = cse.PRE_AWB,
            to_state    = cse.AWB_ISSUED,
            reason      = reason or "create_shipment:adapter_returned_awb",
            actor       = self._actor,
        )
        t2 = csdb.record_transition(
            shipment_id = row["id"],
            from_state  = cse.AWB_ISSUED,
            to_state    = cse.LABEL_CREATED,
            reason      = reason or "create_shipment:label_persisted",
            actor       = self._actor,
        )

        # Append a stub message into the AWB log so the manifest dir
        # contains a verifiable trace of the creation event.
        cls.append_message(rsp.awb, {
            "event_code":   "shipment_created",
            "from_state":   "",
            "to_state":     cse.LABEL_CREATED,
            "label_sha256": artefact.sha256,
            "actor":        self._actor,
            "reason":       reason or "",
        })

        return {
            "shipment":      row,
            "label_sha256":  artefact.sha256,
            "manifest_path": str(manifest_path),
            "transitions":   [t1, t2],
            "raw_response":  dict(rsp.raw or {}),
        }

    # ── cancel_shipment ─────────────────────────────────────────────────────

    def cancel_shipment(
        self,
        *,
        carrier: str,
        awb:     str,
        reason:  Optional[str] = None,
    ) -> Dict[str, Any]:
        """Void a shipment that has not yet been handed to the carrier.

        State engine's "void after handover" rule fires automatically
        — if the shipment is at ``handed_to_carrier`` or beyond, the
        coordinator surfaces the named ``ValueError`` from
        ``cse.transition`` instead of silently no-op'ing.
        """
        row = self._require_row(carrier, awb)
        current = row["state"]
        # State engine raises ValueError with the named carrier rule
        # when this transition is illegal — let that bubble up.
        cse.transition(current, cse.VOIDED)

        adapter_rsp = self._adapter.cancel_shipment(
            awb,
            reason=reason or "operator-cancel",
        )

        updated = self._apply_transition(
            row=row,
            to_state=cse.VOIDED,
            reason=reason or "operator-cancel",
            event_code="shipment_voided",
            extra_message={
                "adapter_accepted": bool(adapter_rsp.accepted),
                "adapter_reason":   adapter_rsp.reason,
            },
        )
        return {
            "shipment":           updated["shipment"],
            "transition":         updated["transition"],
            "adapter_accepted":   bool(adapter_rsp.accepted),
            "adapter_reason":     adapter_rsp.reason,
        }

    # ── mark_label_printed ──────────────────────────────────────────────────

    def mark_label_printed(
        self,
        *,
        carrier: str,
        awb:     str,
        reason:  Optional[str] = None,
    ) -> Dict[str, Any]:
        """Operator confirmed the label printed cleanly.

        Rejects unless current state is exactly ``label_created`` —
        all other moves to ``label_printed`` would skip evidence.
        """
        row = self._require_row(carrier, awb)
        if row["state"] != cse.LABEL_CREATED:
            raise ValueError(
                f"mark_label_printed requires state {cse.LABEL_CREATED!r}, "
                f"got {row['state']!r}"
            )
        cse.transition(cse.LABEL_CREATED, cse.LABEL_PRINTED)
        return self._apply_transition(
            row=row,
            to_state=cse.LABEL_PRINTED,
            reason=reason or "operator-confirmed-print",
            event_code="label_printed",
        )

    # ── mark_handed_to_carrier ──────────────────────────────────────────────

    def mark_handed_to_carrier(
        self,
        *,
        carrier: str,
        awb:     str,
        reason:  Optional[str] = None,
    ) -> Dict[str, Any]:
        """Operator scanned the package over to the courier.

        Rejects unless current state is exactly ``label_printed``. After
        this transition, ``cancel_shipment`` will be rejected by the
        state engine's "void after handover" rule.
        """
        row = self._require_row(carrier, awb)
        if row["state"] != cse.LABEL_PRINTED:
            raise ValueError(
                f"mark_handed_to_carrier requires state "
                f"{cse.LABEL_PRINTED!r}, got {row['state']!r}"
            )
        cse.transition(cse.LABEL_PRINTED, cse.HANDED_TO_CARRIER)
        return self._apply_transition(
            row=row,
            to_state=cse.HANDED_TO_CARRIER,
            reason=reason or "handed-to-carrier",
            event_code="handed_to_carrier",
        )

    # ── private helpers ────────────────────────────────────────────────────

    def _require_row(self, carrier: str, awb: str) -> Dict[str, Any]:
        row = csdb.get_by_awb(carrier, awb)
        if row is None:
            raise CarrierCoordinatorError(
                f"carrier shipment not found: carrier={carrier!r} "
                f"awb={awb!r}"
            )
        return row

    def _apply_transition(
        self,
        *,
        row:           Dict[str, Any],
        to_state:      str,
        reason:        str,
        event_code:    str,
        extra_message: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist a validated state move + append a manifest message.

        Assumes the caller has already validated legality via
        :func:`carrier_state_engine.transition`. Same-state writes are
        a programming error and would be caught by the state engine.
        """
        from_state = row["state"]
        updated = csdb.upsert_shipment(
            carrier       = row["carrier"],
            awb           = row["awb"],
            state         = to_state,
            batch_id      = row.get("batch_id", ""),
            label_sha256  = row.get("label_sha256", ""),
            manifest_path = row.get("manifest_path", ""),
        )
        transition = csdb.record_transition(
            shipment_id = row["id"],
            from_state  = from_state,
            to_state    = to_state,
            reason      = reason,
            actor       = self._actor,
        )
        msg: Dict[str, Any] = {
            "event_code": event_code,
            "from_state": from_state,
            "to_state":   to_state,
            "actor":      self._actor,
            "reason":     reason,
        }
        if extra_message:
            msg.update(extra_message)
        cls.append_message(row["awb"], msg)
        return {"shipment": updated, "transition": transition}

    # ── DL-E1: post-handover transitions driven by inbound carrier events ──
    #
    # These four methods are called by carrier_event_handler when a webhook
    # event resolves to a state change. State-engine validation lives at the
    # top of each method just like mark_label_printed / mark_handed_to_carrier.
    # No method skips the engine; an illegal current state raises ValueError
    # which the handler catches and turns into outcome="ignored" without a
    # 5xx (DHL retry budget protection).

    def record_in_transit(
        self,
        *,
        carrier: str,
        awb:     str,
        reason:  Optional[str] = None,
    ) -> Dict[str, Any]:
        """Apply ``handed_to_carrier → in_transit`` from a webhook signal.

        Rejects unless current state is exactly ``handed_to_carrier``.
        State engine forbids ``in_transit → in_transit`` so retries
        from the carrier are caught by the legality check.
        """
        row = self._require_row(carrier, awb)
        if row["state"] != cse.HANDED_TO_CARRIER:
            raise ValueError(
                f"record_in_transit requires state "
                f"{cse.HANDED_TO_CARRIER!r}, got {row['state']!r}"
            )
        cse.transition(cse.HANDED_TO_CARRIER, cse.IN_TRANSIT)
        return self._apply_transition(
            row=row,
            to_state=cse.IN_TRANSIT,
            reason=reason or "carrier-event:in_transit",
            event_code="in_transit",
        )

    def record_delivered(
        self,
        *,
        carrier: str,
        awb:     str,
        reason:  Optional[str] = None,
    ) -> Dict[str, Any]:
        """Apply ``→ delivered`` from a webhook signal.

        Accepts the documented "out-of-order delivered from
        handed_to_carrier" case. Rejects from any state where the
        engine forbids the move (delivered/returned/voided terminals,
        or the pre-handover band).
        """
        row = self._require_row(carrier, awb)
        current = row["state"]
        if current not in (cse.HANDED_TO_CARRIER, cse.IN_TRANSIT):
            raise ValueError(
                f"record_delivered requires state "
                f"{cse.HANDED_TO_CARRIER!r} or {cse.IN_TRANSIT!r}, "
                f"got {current!r}"
            )
        cse.transition(current, cse.DELIVERED)
        return self._apply_transition(
            row=row,
            to_state=cse.DELIVERED,
            reason=reason or "carrier-event:delivered",
            event_code="delivered",
        )

    def record_returned(
        self,
        *,
        carrier: str,
        awb:     str,
        reason:  Optional[str] = None,
    ) -> Dict[str, Any]:
        """Apply ``→ returned`` from a webhook signal."""
        row = self._require_row(carrier, awb)
        current = row["state"]
        if current not in (cse.HANDED_TO_CARRIER, cse.IN_TRANSIT):
            raise ValueError(
                f"record_returned requires state "
                f"{cse.HANDED_TO_CARRIER!r} or {cse.IN_TRANSIT!r}, "
                f"got {current!r}"
            )
        cse.transition(current, cse.RETURNED)
        return self._apply_transition(
            row=row,
            to_state=cse.RETURNED,
            reason=reason or "carrier-event:returned",
            event_code="returned",
        )

    def record_exception(
        self,
        *,
        carrier:     str,
        awb:         str,
        reason:      Optional[str] = None,
        status_code: str = "",
        location:    str = "",
        description: str = "",
    ) -> Dict[str, Any]:
        """Append an informational manifest message — NO state change.

        Used for DHL ``exception`` events and for any unknown
        statusCode the translator could not map. The engine is not
        consulted because nothing transitions; the manifest message
        carries the raw fields so the audit trail still names the
        external signal.
        """
        row = self._require_row(carrier, awb)
        cls.append_message(row["awb"], {
            "event_code":   "carrier_exception",
            "from_state":   row["state"],
            "to_state":     row["state"],
            "actor":        self._actor,
            "reason":       reason or "",
            "status_code":  status_code or "",
            "location":     location or "",
            "description":  description or "",
        })
        return {"shipment": row, "transition": None}

    # ── read-through helpers (no state mutation) ───────────────────────────

    def get_shipment(self, *, carrier: str, awb: str) -> Optional[Dict[str, Any]]:
        return csdb.get_by_awb(carrier, awb)

    def list_transitions(self, *, shipment_id: str) -> List[Dict[str, Any]]:
        return csdb.get_transitions(shipment_id)
