"""
routes_carrier_actions.py — Gated carrier execution surface.

DL-D5 scope
-----------
This is the only carrier route file that mutates state. Lives separate
from routes_carrier.py and routes_carrier_proposals.py so their
read-only source-grep proofs hold. Every endpoint is a POST gated by:

  1. Router-level API-key dependency.
  2. Per-resource proposal_write_lock (batch_id for create, awb for
     per-shipment actions).
  3. Re-derived proposal_id check — the deterministic id from
     carrier_proposal_builder must match the body's submitted id.
     A state change between proposal-list-time and execute-time
     invalidates the id and the request is rejected as stale.
  4. Idempotent-replay short-circuit when the shipment is already in
     the target state.
  5. Coordinator-only writes — routes never call the adapter or the
     DB write helpers directly. The coordinator validates each move
     against the carrier_state_engine.

Endpoints (all POST under /api/v1/carrier/actions)
--------------------------------------------------
* /create-shipment/execute
* /mark-label-printed/execute
* /mark-handed-to-carrier/execute
* /cancel-shipment/execute

Response envelope
-----------------
{
  "executed":            bool,
  "proposal_id":         str,
  "idempotent_replay":   bool,
  "result":              dict,
  "error":               Optional[str],
  "code":                Optional[str],
}

Auth
----
Router-level dependency = require_api_key. Same convention as
routes_action_proposals.py.

Auto-actor sentinel reject
--------------------------
``actor`` body field must be non-empty and must NOT begin with the
prefixes ``auto:`` or ``system:`` — operator-supplied values cannot
masquerade as automated sentinels (mirrors the G9 spirit of
routes_action_proposals.py without coupling to its sentinel set).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core import timeline as tl
from ..core.config import settings
from ..core.security import require_api_key
from ..services.carrier import carrier_proposal_builder as pb
from ..services.carrier import carrier_shipment_db as csdb
from ..services.carrier import carrier_state_engine as cse
from ..services.carrier.base import (
    CARRIER_DHL,
    CarrierAddress,
    CarrierShipmentRequest,
    PackageSpec,
)
from ..services.carrier.carrier_coordinator import (
    CarrierCoordinator,
    CarrierCoordinatorError,
)
from ..utils.proposal_lock import proposal_write_lock


# Router-level auth — every endpoint is protected. Mirrors the pattern
# used by routes_action_proposals (the canonical write-surface in this
# codebase).
_auth = Depends(require_api_key)
router = APIRouter(
    prefix       = "/api/v1/carrier/actions",
    tags         = ["carrier"],
    dependencies = [_auth],
)


# ── Auto-actor sentinel guard ───────────────────────────────────────────────

#: Prefixes that mean "this actor is an automated sentinel".
#: Operator-supplied actor values matching these prefixes are rejected.
_AUTO_ACTOR_PREFIXES = ("auto:", "system:")


def _validate_actor(actor: str) -> str:
    """Reject empty / sentinel actors per rules 15+16."""
    cleaned = (actor or "").strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail={
            "code":  "actor_required",
            "error": "actor must be a non-empty string",
        })
    for prefix in _AUTO_ACTOR_PREFIXES:
        if cleaned.lower().startswith(prefix):
            raise HTTPException(status_code=422, detail={
                "code":  "auto_actor_sentinel_reserved",
                "error": (
                    f"actor {cleaned!r} matches an automated-sentinel prefix; "
                    f"operator-supplied actors must not begin with "
                    f"{_AUTO_ACTOR_PREFIXES!r}."
                ),
            })
    return cleaned


# ── Coordinator factory (stub adapter only for this phase) ──────────────────

def _carrier_db_path() -> Path:
    """Same path that main.py initialises in lifespan and that the
    read-only carrier route layer reads through the singleton."""
    return Path(settings.storage_root) / "carrier_shipments.db"


def _carrier_label_root() -> Path:
    return Path(settings.storage_root) / "carrier_labels"


# DHL MyDHL API base URLs. Constants — never read from environment.
# Selection between sandbox and production is driven by
# settings.dhl_express_api_status, gated by carrier_dhl_live_enabled.
_DHL_SANDBOX_URL:    str = "https://express.api.dhl.com/mydhlapi/test"
_DHL_PRODUCTION_URL: str = "https://express.api.dhl.com/mydhlapi"


def _select_carrier_adapter(actor: str):
    """Pick the carrier adapter for this request.

    DL-F1/F2 selection rules — falls back to the DHL Express stub for
    any condition that fails live-eligibility checks. NEVER raises;
    the worst case is "stub when you wanted live", which the
    dashboard surfaces. Order:

      1. carrier_dhl_live_enabled is False                  → stub
      2. dhl_express_api_status == "pending"                → stub
      3. username / password / account_number empty         → stub
      4. unknown status                                     → stub
      5. live constructor raises (defensive)                → stub
      6. carrier_dhl_shadow_mode is True (and 1-5 passed)   → SHADOW(stub, live)
      7. status == "sandbox"  (shadow off)                  → live (sandbox URL)
      8. status == "production" (shadow off)                → live (prod URL)
      9. shadow constructor raises (defensive)              → stub

    Imports are local so the route module's source-grep contract
    ("no adapter base import at module scope") holds.
    """
    from ..services.carrier.adapters.dhl_express_stub import (
        DHLExpressStubAdapter,
    )

    if not settings.carrier_dhl_live_enabled:
        return DHLExpressStubAdapter()

    status = (settings.dhl_express_api_status or "pending").lower().strip()
    if status == "pending":
        return DHLExpressStubAdapter()

    username       = (settings.dhl_express_api_username   or "").strip()
    password       = (settings.dhl_express_api_password   or "").strip()
    account_number = (settings.dhl_express_account_number or "").strip()
    if not username or not password or not account_number:
        return DHLExpressStubAdapter()

    if status == "sandbox":
        base_url = _DHL_SANDBOX_URL
    elif status == "production":
        base_url = _DHL_PRODUCTION_URL
    else:
        return DHLExpressStubAdapter()

    from ..services.carrier.adapters.dhl_express_live import (
        DHLExpressLiveAdapter,
    )
    try:
        live = DHLExpressLiveAdapter(
            base_url       = base_url,
            username       = username,
            password       = password,
            account_number = account_number,
            # DL-F3 — Paperless Trade is forwarded into the adapter's
            # constructor so the adapter never reads settings directly.
            paperless_trade_enabled = bool(
                settings.carrier_dhl_paperless_trade_enabled
            ),
            # DL-F3.5c — PLT path containment. The validator rejects
            # any operator-supplied customs_invoice_pdf_path that
            # escapes the project's storage tree. Closes the
            # arbitrary-file-read primitive identified by Security
            # Reviewer as P0.
            paperless_trade_allowed_root = str(settings.storage_root),
        )
    except Exception:
        # Defensive: live constructor rejected the inputs (empty after
        # strip, malformed URL, etc.). Fall back to the stub rather
        # than crash the action endpoint.
        return DHLExpressStubAdapter()

    # Shadow-mode wrap (DL-F2) — only when the operator has explicitly
    # enabled it AND the live adapter is fully configured. The wrapper
    # routes the operator-facing return value through the stub while
    # observing the live adapter for diff review.
    if settings.carrier_dhl_shadow_mode:
        try:
            from ..services.carrier.adapters.dhl_express_shadow import (
                DHLExpressShadowAdapter,
            )
            return DHLExpressShadowAdapter(
                stub  = DHLExpressStubAdapter(),
                live  = live,
                actor = (actor or "system:shadow"),
            )
        except Exception:
            # Defensive: any wrapping failure falls back to the stub
            # so the operator action never crashes. The live adapter
            # constructed above is dropped on the floor; the next
            # request rebuilds.
            return DHLExpressStubAdapter()

    return live


def _make_coordinator(actor: str) -> CarrierCoordinator:
    """Construct a per-request coordinator wired to the selected
    adapter (stub by default; live DHL behind feature flag).

    The adapter import is local to keep the module-scope source-grep
    proof intact (rule 7 of DL-D5 forbids "import or call any adapter
    directly" at module scope).
    """
    return CarrierCoordinator(
        db_path          = _carrier_db_path(),
        label_store_root = _carrier_label_root(),
        adapter          = _select_carrier_adapter(actor),
        actor            = actor,
    )


# ── Audit-path resolver for timeline events ─────────────────────────────────

def _audit_path_for(batch_id: str) -> Path:
    """Resolve the parent batch's audit.json path.

    ``tl.log_event`` is non-fatal: if the audit file is absent (e.g.,
    an outbound carrier shipment that has no inbound PZ batch yet),
    the call swallows the error and logs a warning. We still emit the
    event so the audit timeline carries the carrier action when the
    file does exist.
    """
    return Path(settings.storage_root) / "outputs" / (batch_id or "") / "audit.json"


# ── Request models ──────────────────────────────────────────────────────────

class _PackagePayload(BaseModel):
    weight_kg:          float
    length_cm:          float
    width_cm:           float
    height_cm:          float
    declared_value:     float = 0.0
    declared_currency:  str   = "USD"
    description:        str   = ""


class _AddressPayload(BaseModel):
    name:        str
    company:     str = ""
    street_1:    str = ""
    street_2:    str = ""
    city:        str = ""
    postal_code: str = ""
    country:     str = ""
    phone:       str = ""
    email:       str = ""


class _ShipmentRequestPayload(BaseModel):
    batch_id:     str
    ship_from:    _AddressPayload
    ship_to:      _AddressPayload
    packages:     list[_PackagePayload]
    service_code: str = ""
    reference:    str = ""
    metadata:     Optional[Dict[str, Any]] = None
    # DL-F3 — optional Paperless Trade fields. The live adapter only
    # honours these when carrier_dhl_paperless_trade_enabled is True
    # AND the file passes validate_paperless_trade_pdf. Stub adapters
    # ignore both fields entirely.
    customs_invoice_pdf_path:  str = ""
    customs_invoice_metadata:  Optional[Dict[str, Any]] = None


class CreateShipmentBody(BaseModel):
    batch_id:    str
    request:     _ShipmentRequestPayload
    proposal_id: str
    actor:       str
    reason:      Optional[str] = None
    carrier:     str = CARRIER_DHL


class _ShipmentActionBody(BaseModel):
    carrier:     str
    awb:         str
    proposal_id: str
    actor:       str
    reason:      Optional[str] = None


class MarkLabelPrintedBody(_ShipmentActionBody):
    pass


class MarkHandedToCarrierBody(_ShipmentActionBody):
    pass


class CancelShipmentBody(_ShipmentActionBody):
    pass


# ── Helpers ─────────────────────────────────────────────────────────────────

def _payload_to_request(p: _ShipmentRequestPayload) -> CarrierShipmentRequest:
    return CarrierShipmentRequest(
        batch_id     = p.batch_id,
        ship_from    = CarrierAddress(**p.ship_from.model_dump()),
        ship_to      = CarrierAddress(**p.ship_to.model_dump()),
        packages     = tuple(PackageSpec(**pkg.model_dump()) for pkg in p.packages),
        service_code = p.service_code,
        reference    = p.reference,
        metadata     = dict(p.metadata or {}),
        customs_invoice_pdf_path = p.customs_invoice_pdf_path or "",
        customs_invoice_metadata = dict(p.customs_invoice_metadata or {}),
    )


def _envelope(
    *,
    executed:           bool,
    proposal_id:        str,
    result:             Dict[str, Any],
    idempotent_replay:  bool = False,
    error:              Optional[str] = None,
    code:               Optional[str] = None,
) -> Dict[str, Any]:
    """Stable response shape — matches the spec's envelope exactly."""
    return {
        "executed":          executed,
        "proposal_id":       proposal_id,
        "idempotent_replay": idempotent_replay,
        "result":            result,
        "error":             error,
        "code":              code,
    }


def _log_rejection(
    *,
    batch_id: str,
    actor:    str,
    proposal_id: str,
    action:   str,
    code:     str,
    detail:   str,
) -> None:
    """Emit EV_CARRIER_EXECUTE_REJECTED to the parent batch timeline.

    Best-effort: tl.log_event is non-fatal and silently no-ops when
    the audit file is absent.
    """
    try:
        tl.log_event(
            _audit_path_for(batch_id),
            tl.EV_CARRIER_EXECUTE_REJECTED,
            "admin",
            actor=actor or "system",
            detail={
                "action":      action,
                "proposal_id": proposal_id,
                "code":        code,
                "reason":      detail,
            },
        )
    except Exception:
        pass


# ── 1. POST /create-shipment/execute ────────────────────────────────────────

@router.post("/create-shipment/execute")
def execute_create_shipment(body: CreateShipmentBody) -> Dict[str, Any]:
    actor = _validate_actor(body.actor)
    batch_id = (body.batch_id or "").strip()
    if not batch_id:
        raise HTTPException(status_code=422, detail={
            "code":  "batch_id_required",
            "error": "batch_id must be a non-empty string",
        })

    lock_key = f"carrier:batch:{batch_id}"
    with proposal_write_lock(lock_key):
        # Re-load existing shipments + re-derive the create proposal.
        # This is the source of truth for whether the action is legal
        # right now and for the canonical proposal_id.
        csdb.init_db(_carrier_db_path())  # idempotent

        # DL-F3.5a — idempotency pre-check. Must run BEFORE the
        # proposal-blocked gate, because that gate would otherwise
        # 409 every legitimate retry as "active_shipment_exists".
        # Same (batch_id, reference) retried after a transient
        # failure returns the existing shipment with
        # idempotent_replay=True instead of a duplicate AWB.
        # Empty reference returns None → no idempotency claim;
        # request proceeds to the normal gate stack.
        request = _payload_to_request(body.request)
        existing_idem = csdb.get_by_batch_and_reference(
            batch_id=batch_id,
            reference=(request.reference or ""),
        )
        if existing_idem is not None:
            outcome = {
                "shipment":          dict(existing_idem),
                "label_sha256":      str(existing_idem.get("label_sha256") or ""),
                "manifest_path":     str(existing_idem.get("manifest_path") or ""),
                "transitions":       [],
                "raw_response":      {},
                "idempotent_replay": True,
            }
            tl.log_event(
                _audit_path_for(batch_id),
                tl.EV_CARRIER_SHIPMENT_CREATED,
                "admin",
                actor=actor,
                detail={
                    "action":       "create_shipment",
                    "proposal_id":  body.proposal_id,
                    "carrier":      existing_idem.get("carrier", ""),
                    "awb":          existing_idem.get("awb", ""),
                    "label_sha256": existing_idem.get("label_sha256", ""),
                    "replay":       True,
                },
            )
            return _envelope(
                executed          = False,
                proposal_id       = body.proposal_id,
                result            = outcome,
                idempotent_replay = True,
            )

        existing = csdb.get_by_batch(batch_id)
        proposal = pb.build_create_shipment_proposal(
            batch_id, existing_shipments=existing, carrier=body.carrier,
        )

        if not proposal["enabled"]:
            _log_rejection(
                batch_id=batch_id, actor=actor,
                proposal_id=body.proposal_id,
                action="create_shipment",
                code="active_shipment_exists",
                detail="; ".join(proposal["blocking_reasons"]),
            )
            raise HTTPException(status_code=409, detail={
                "code":              "active_shipment_exists",
                "error":             "create-shipment is blocked while an active shipment exists for this batch",
                "blocking_reasons":  proposal["blocking_reasons"],
                "expected_id":       proposal["proposal_id"],
            })

        if proposal["proposal_id"] != body.proposal_id:
            _log_rejection(
                batch_id=batch_id, actor=actor,
                proposal_id=body.proposal_id,
                action="create_shipment",
                code="stale_proposal",
                detail=f"expected={proposal['proposal_id']!r}",
            )
            raise HTTPException(status_code=409, detail={
                "code":         "stale_proposal",
                "error":        "submitted proposal_id does not match current proposal id",
                "expected_id":  proposal["proposal_id"],
                "received_id":  body.proposal_id,
            })

        # Coordinator does the actual work. Adapter is the stub.
        # `request` was already built above for the idempotency check;
        # reuse it here.
        coord = _make_coordinator(actor=actor)
        try:
            outcome = coord.create_shipment(
                batch_id = batch_id,
                request  = request,
                reason   = body.reason,
            )
        except (ValueError, CarrierCoordinatorError) as exc:
            _log_rejection(
                batch_id=batch_id, actor=actor,
                proposal_id=body.proposal_id,
                action="create_shipment",
                code="coordinator_rejected",
                detail=str(exc),
            )
            raise HTTPException(status_code=409, detail={
                "code":  "coordinator_rejected",
                "error": str(exc),
            })

    # DL-F3.5a — idempotent replay returns 200 with executed=False
    # and the existing shipment row. The adapter was NOT called and
    # no new transitions were appended. The timeline still emits
    # EV_CARRIER_SHIPMENT_CREATED with a replay=True marker so an
    # operator scanning the audit can see the retry happened.
    is_replay = bool(outcome.get("idempotent_replay"))

    tl.log_event(
        _audit_path_for(batch_id),
        tl.EV_CARRIER_SHIPMENT_CREATED,
        "admin",
        actor=actor,
        detail={
            "action":       "create_shipment",
            "proposal_id":  body.proposal_id,
            "carrier":      outcome["shipment"]["carrier"],
            "awb":          outcome["shipment"]["awb"],
            "label_sha256": outcome["label_sha256"],
            "replay":       is_replay,
        },
    )
    return _envelope(
        executed          = (not is_replay),
        proposal_id       = body.proposal_id,
        result            = outcome,
        idempotent_replay = is_replay,
    )


# ── 2. POST /mark-label-printed/execute ─────────────────────────────────────

@router.post("/mark-label-printed/execute")
def execute_mark_label_printed(body: MarkLabelPrintedBody) -> Dict[str, Any]:
    return _execute_per_shipment(
        body              = body,
        action            = "mark_label_printed",
        target_state      = cse.LABEL_PRINTED,
        required_state    = cse.LABEL_CREATED,
        proposal_builder  = pb.build_mark_label_printed_proposal,
        coordinator_method= "mark_label_printed",
        success_event     = tl.EV_CARRIER_LABEL_PRINTED,
    )


# ── 3. POST /mark-handed-to-carrier/execute ─────────────────────────────────

@router.post("/mark-handed-to-carrier/execute")
def execute_mark_handed_to_carrier(body: MarkHandedToCarrierBody) -> Dict[str, Any]:
    return _execute_per_shipment(
        body              = body,
        action            = "mark_handed_to_carrier",
        target_state      = cse.HANDED_TO_CARRIER,
        required_state    = cse.LABEL_PRINTED,
        proposal_builder  = pb.build_mark_handed_to_carrier_proposal,
        coordinator_method= "mark_handed_to_carrier",
        success_event     = tl.EV_CARRIER_HANDED_TO_CARRIER,
    )


# ── 4. POST /cancel-shipment/execute ────────────────────────────────────────

@router.post("/cancel-shipment/execute")
def execute_cancel_shipment(body: CancelShipmentBody) -> Dict[str, Any]:
    return _execute_per_shipment(
        body              = body,
        action            = "cancel_shipment",
        target_state      = cse.VOIDED,
        required_state    = None,                     # any pre-handover state
        proposal_builder  = pb.build_cancel_shipment_proposal,
        coordinator_method= "cancel_shipment",
        success_event     = tl.EV_CARRIER_SHIPMENT_VOIDED,
    )


# ── Shared per-shipment executor ────────────────────────────────────────────

def _execute_per_shipment(
    *,
    body,
    action:             str,
    target_state:       str,
    required_state:     Optional[str],
    proposal_builder,
    coordinator_method: str,
    success_event:      str,
) -> Dict[str, Any]:
    """Common path for mark-printed / mark-handed / cancel.

    All three have the same shape: load row → idempotent-replay short-
    circuit → re-derive proposal → match id → coordinator call → log.
    """
    actor = _validate_actor(body.actor)
    awb = (body.awb or "").strip()
    carrier = (body.carrier or "").strip()
    if not awb or not carrier:
        raise HTTPException(status_code=422, detail={
            "code":  "carrier_and_awb_required",
            "error": "carrier and awb must both be non-empty",
        })

    lock_key = f"carrier:awb:{carrier}:{awb}"
    with proposal_write_lock(lock_key):
        csdb.init_db(_carrier_db_path())  # idempotent
        row = csdb.get_by_awb(carrier, awb)
        if row is None:
            _log_rejection(
                batch_id=body.proposal_id, actor=actor,
                proposal_id=body.proposal_id,
                action=action,
                code="shipment_not_found",
                detail=f"carrier={carrier!r} awb={awb!r}",
            )
            raise HTTPException(status_code=404, detail={
                "code":  "shipment_not_found",
                "error": f"no carrier shipment for carrier={carrier!r} awb={awb!r}",
            })

        # Idempotent-replay short-circuit: if the row is already at
        # the target state, return without mutating. No new transition
        # row, no coordinator call, no timeline event.
        if row["state"] == target_state:
            return _envelope(
                executed          = False,
                proposal_id       = body.proposal_id,
                result            = row,
                idempotent_replay = True,
            )

        # Re-derive the proposal. The builder will return enabled=False
        # for any state that does not satisfy the action's pre-check.
        proposal = proposal_builder(row)
        if not proposal["enabled"]:
            _log_rejection(
                batch_id=row.get("batch_id", ""), actor=actor,
                proposal_id=body.proposal_id,
                action=action,
                code="invalid_state",
                detail="; ".join(proposal["blocking_reasons"]),
            )
            raise HTTPException(status_code=409, detail={
                "code":              "invalid_state",
                "error":             f"action {action!r} not available from current state {row['state']!r}",
                "blocking_reasons":  proposal["blocking_reasons"],
                "current_state":     row["state"],
                "expected_state":    required_state,
            })

        if proposal["proposal_id"] != body.proposal_id:
            _log_rejection(
                batch_id=row.get("batch_id", ""), actor=actor,
                proposal_id=body.proposal_id,
                action=action,
                code="stale_proposal",
                detail=f"expected={proposal['proposal_id']!r}",
            )
            raise HTTPException(status_code=409, detail={
                "code":         "stale_proposal",
                "error":        "submitted proposal_id does not match current proposal id",
                "expected_id":  proposal["proposal_id"],
                "received_id":  body.proposal_id,
            })

        coord = _make_coordinator(actor=actor)
        method = getattr(coord, coordinator_method)
        try:
            outcome = method(carrier=carrier, awb=awb, reason=body.reason)
        except (ValueError, CarrierCoordinatorError) as exc:
            _log_rejection(
                batch_id=row.get("batch_id", ""), actor=actor,
                proposal_id=body.proposal_id,
                action=action,
                code="coordinator_rejected",
                detail=str(exc),
            )
            raise HTTPException(status_code=409, detail={
                "code":  "coordinator_rejected",
                "error": str(exc),
            })

    # Successful execute — log and return.
    tl.log_event(
        _audit_path_for(row.get("batch_id", "")),
        success_event,
        "admin",
        actor=actor,
        detail={
            "action":       action,
            "proposal_id":  body.proposal_id,
            "carrier":      carrier,
            "awb":          awb,
            "from_state":   row["state"],
            "to_state":     target_state,
        },
    )
    return _envelope(
        executed    = True,
        proposal_id = body.proposal_id,
        result      = outcome,
    )
