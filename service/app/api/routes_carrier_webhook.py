"""
routes_carrier_webhook.py — Inbound DHL webhook ingestion.

DL-E1 scope
-----------
Two POST endpoints under ``/api/v1/carrier/webhook``:
  * ``/dhl/activate`` — one-time subscription confirmation handshake
  * ``/dhl/events``   — steady-state event sink

Hard rules (also enforced by source-grep tests)
-----------------------------------------------
* POST-only.
* No HTTP client imports (no live DHL calls from the route layer).
* No live-DHL transport invocation — the live adapter is parse-only.
* Both endpoints return HTTP 503 when ``settings.carrier_dhl_webhook_enabled``
  is False. The router is mounted regardless so endpoints are
  discoverable, but they remain inert.
* The events endpoint always replies 2xx for accepted-but-ignored
  cases (dedupe / no_shipment / illegal-transition / unknown code).
  DHL's retry budget (1h, 6h, deactivation at 10k consecutive
  failures) is NOT spent on outcomes we deliberately skip.

Security
--------
* DHL does NOT document a per-event HMAC signature, so this layer
  validates:
    - the master flag
    - the ``DHL-API-Key`` header (when ``settings.api_key`` is set)
    - source IP allow-list (when ``carrier_dhl_webhook_ip_allowlist``
      is set)
* The activation handshake compares the secret in the request header
  against the secret in the request body and persists only the
  sha256 hash, never the raw secret.
"""
from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request

from ..core import timeline as tl
from ..core.config import settings
from ..services.carrier import carrier_event_db as ced
from ..services.carrier.adapters.base import CarrierResponseError

router = APIRouter(prefix="/api/v1/carrier/webhook", tags=["carrier"])


# Secret header name. DHL's docs use a "secret" value duplicated in
# header and body; the exact header name is not strictly specified
# in public docs, so we accept the common ``DHL-Hook-Secret`` form.
_HEADER_SECRET = "DHL-Hook-Secret"
_HEADER_API_KEY = "DHL-API-Key"


# ── Helpers ─────────────────────────────────────────────────────────────────

def _carrier_db_path() -> Path:
    return Path(settings.storage_root) / "carrier_shipments.db"


def _label_root() -> Path:
    return Path(settings.storage_root) / "carrier_labels"


def _event_db_path() -> Path:
    return Path(settings.storage_root) / "carrier_events.db"


def _audit_path_for(batch_id: str) -> Path:
    return Path(settings.storage_root) / "outputs" / (batch_id or "") / "audit.json"


def _client_ip(request: Request) -> str:
    """Best-effort source IP. Falls back to empty string when the
    transport doesn't expose a client (uncommon in practice)."""
    if request.client and request.client.host:
        return request.client.host
    return ""


def _ip_in_allowlist(client_ip: str, allowlist_csv: str) -> bool:
    """True iff *client_ip* falls inside any CIDR in the comma-separated
    allow-list. Empty allow-list means "no IP check applies"."""
    if not allowlist_csv.strip():
        return True
    try:
        ip_obj = ipaddress.ip_address(client_ip)
    except (ValueError, TypeError):
        return False
    for raw in allowlist_csv.split(","):
        cidr = raw.strip()
        if not cidr:
            continue
        try:
            net = ipaddress.ip_network(cidr, strict=False)
        except (ValueError, TypeError):
            continue
        if ip_obj in net:
            return True
    return False


def _enabled_or_503() -> None:
    if not settings.carrier_dhl_webhook_enabled:
        raise HTTPException(status_code=503, detail={
            "code":  "webhook_disabled",
            "error": "carrier_dhl_webhook_enabled is False; endpoint is inert",
        })


def _check_api_key(request: Request) -> None:
    """Reject when ``settings.api_key`` is configured and the header
    is missing or wrong. Open in dev (api_key empty)."""
    expected = settings.api_key
    if not expected:
        return
    received = request.headers.get(_HEADER_API_KEY) or ""
    if received != expected:
        raise HTTPException(status_code=401, detail={
            "code":  "unauthorized",
            "error": f"missing or invalid {_HEADER_API_KEY} header",
        })


def _check_ip_allowlist(request: Request) -> None:
    allowlist = settings.carrier_dhl_webhook_ip_allowlist or ""
    if not allowlist.strip():
        return
    client_ip = _client_ip(request)
    if not _ip_in_allowlist(client_ip, allowlist):
        raise HTTPException(status_code=403, detail={
            "code":  "forbidden",
            "error": f"source IP {client_ip!r} not in allowlist",
        })


async def _read_json_object(request: Request) -> Tuple[bytes, Dict[str, Any]]:
    """Read raw body bytes and decode to a dict. 400 on parse failure."""
    raw = await request.body()
    if not raw:
        raise HTTPException(status_code=400, detail={
            "code":  "empty_body",
            "error": "request body is empty",
        })
    try:
        decoded = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail={
            "code":  "invalid_body",
            "error": f"request body is not valid JSON: {exc}",
        })
    if not isinstance(decoded, dict):
        raise HTTPException(status_code=400, detail={
            "code":  "invalid_body",
            "error": "request body must be a JSON object",
        })
    return raw, decoded


def _log_rejection(*, code: str, reason: str, batch_id: str = "") -> None:
    try:
        tl.log_event(
            _audit_path_for(batch_id),
            tl.EV_CARRIER_WEBHOOK_REJECTED,
            "system:carrier_webhook",
            actor="system:carrier_webhook",
            detail={"code": code, "reason": reason},
        )
    except Exception:
        pass


def _log_outcome(outcome: str, *, batch_id: str, detail: Dict[str, Any]) -> None:
    """Log the per-event outcome to the parent batch's timeline.

    ``applied`` → EV_CARRIER_WEBHOOK_ACCEPTED
    everything else (deduped / ignored / no_shipment) → EV_CARRIER_WEBHOOK_IGNORED
    """
    try:
        if outcome == "applied":
            ev = tl.EV_CARRIER_WEBHOOK_ACCEPTED
        else:
            ev = tl.EV_CARRIER_WEBHOOK_IGNORED
        tl.log_event(
            _audit_path_for(batch_id),
            ev,
            "system:carrier_webhook",
            actor="system:carrier_webhook",
            detail=detail,
        )
    except Exception:
        pass


# ── 1. POST /dhl/activate ───────────────────────────────────────────────────

@router.post("/dhl/activate")
async def activate_dhl_subscription(request: Request) -> Dict[str, Any]:
    """One-time subscription confirmation.

    DHL sends the secret in BOTH a request header and the body. We
    verify equality, persist only the sha256 hash, and echo the
    secret back so DHL marks the subscription as activated.
    """
    _enabled_or_503()
    _check_ip_allowlist(request)

    _, body = await _read_json_object(request)
    body_secret = (body.get("secret") or "").strip()
    header_secret = (request.headers.get(_HEADER_SECRET) or "").strip()
    if not header_secret or not body_secret:
        _log_rejection(code="secret_missing", reason="header or body secret missing")
        raise HTTPException(status_code=400, detail={
            "code":  "secret_missing",
            "error": (
                f"both request header {_HEADER_SECRET} and body 'secret' "
                "must be present"
            ),
        })
    if header_secret != body_secret:
        _log_rejection(code="secret_mismatch", reason="header/body secret mismatch")
        raise HTTPException(status_code=400, detail={
            "code":  "secret_mismatch",
            "error": "request header secret does not match body secret",
        })

    subscription_id = (
        body.get("subscription_id") or body.get("self") or "default"
    )

    # Persist hash only — never the raw secret.
    ced.init_db(_event_db_path())  # idempotent
    secret_hash = ced.hash_secret(header_secret)
    ced.upsert_subscription(
        subscription_id=str(subscription_id),
        secret_hash=secret_hash,
    )
    ced.confirm_subscription(
        subscription_id=str(subscription_id),
        secret_hash=secret_hash,
    )

    # Echo the secret back so DHL marks the subscription active.
    return {
        "secret":          header_secret,
        "subscription_id": str(subscription_id),
        "confirmed":       True,
    }


# ── 2. POST /dhl/events ─────────────────────────────────────────────────────

@router.post("/dhl/events")
async def receive_dhl_events(request: Request) -> Dict[str, Any]:
    """Steady-state event sink.

    Validates the master flag, header API key, IP allow-list, and
    body shape. For each shipment in ``shipments[]`` we parse via
    the live adapter and dispatch through ``CarrierEventHandler``.
    Per-shipment results are returned in the response body; we
    never raise 5xx for accepted-but-ignored events.
    """
    _enabled_or_503()
    _check_api_key(request)
    _check_ip_allowlist(request)

    raw_body, body = await _read_json_object(request)

    shipments = body.get("shipments")
    if not isinstance(shipments, list):
        _log_rejection(code="missing_shipments", reason="shipments[] not a list")
        raise HTTPException(status_code=400, detail={
            "code":  "missing_shipments",
            "error": "request body must carry a 'shipments' array",
        })

    max_per = settings.carrier_dhl_webhook_max_shipments_per_push
    if len(shipments) > max_per:
        _log_rejection(
            code="too_many_shipments",
            reason=f"got={len(shipments)} max={max_per}",
        )
        raise HTTPException(status_code=400, detail={
            "code":  "too_many_shipments",
            "error": (
                f"shipments array length {len(shipments)} exceeds "
                f"max {max_per}"
            ),
            "max":   max_per,
        })

    # Parse the envelope. Importing the live adapter inside the
    # function keeps the route module's source-grep proof intact
    # ("no live-adapter import at module scope").
    from ..services.carrier.adapters.dhl_express_live import (
        DHLExpressLiveAdapter,
    )
    adapter = DHLExpressLiveAdapter()
    try:
        events, dropped = adapter.parse_push_payload(raw_body, request.headers)
    except CarrierResponseError as exc:
        _log_rejection(code="invalid_body", reason=str(exc))
        raise HTTPException(status_code=400, detail={
            "code":  "invalid_body",
            "error": str(exc),
        })

    # Construct handler. Importing the coordinator + stub adapter
    # inside the function preserves the route layer's source-grep
    # contract for adapter-isolation.
    from ..services.carrier.carrier_coordinator import CarrierCoordinator
    from ..services.carrier.adapters.dhl_express_stub import (
        DHLExpressStubAdapter,
    )
    from ..services.carrier.carrier_event_handler import CarrierEventHandler

    coord = CarrierCoordinator(
        db_path          = _carrier_db_path(),
        label_store_root = _label_root(),
        adapter          = DHLExpressStubAdapter(),
        actor            = "system:carrier_webhook",
    )
    handler = CarrierEventHandler(
        coordinator = coord,
        db_path     = _event_db_path(),
    )

    results = []
    for ev in events:
        try:
            outcome = handler.handle_event(ev)
        except Exception as exc:
            # Genuine internal failure — return 5xx so DHL retries.
            _log_rejection(
                code="ingest_failed",
                reason=f"{type(exc).__name__}: {exc}",
            )
            raise HTTPException(status_code=500, detail={
                "code":  "ingest_failed",
                "error": str(exc),
            }) from exc

        # Emit per-event timeline
        from ..services.carrier import carrier_shipment_db as csdb
        row = csdb.get_by_awb(ev.carrier, ev.awb) if ev.awb else None
        batch_id = (row or {}).get("batch_id", "")
        _log_outcome(
            outcome["outcome"],
            batch_id=batch_id,
            detail={
                "event_id":   outcome["event_id"],
                "carrier":    ev.carrier,
                "awb":        ev.awb,
                "event_code": ev.event_code,
                "outcome":    outcome["outcome"],
                "reason":     outcome.get("reason"),
            },
        )
        results.append(outcome)

    return {
        "shipments_received":  len(shipments),
        "shipments_processed": len(events),
        "shipments_dropped":   dropped,
        "results":             results,
    }
