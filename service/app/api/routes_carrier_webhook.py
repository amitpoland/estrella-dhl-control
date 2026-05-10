"""
DHL Express carrier webhook endpoint.

Security model (applied in order):
  1. Guard    — HTTP 503 if DHL_WEBHOOK_SECRET is not configured.
                503 signals "not available" rather than "unauthorised",
                preventing probing from learning the secret is unset.
  2. Header   — HTTP 401 if DHL-Signature header is absent.
  3. HMAC     — HTTP 401 if HMAC-SHA256(secret, raw_body) does not match
                the supplied signature. Uses hmac.compare_digest to avoid
                timing attacks.
  4. Dedup    — Duplicate event_id returns 200 without reprocessing
                (INSERT OR IGNORE in event_db).
  5. Store    — Log-safe payload written to carrier_events.db.

Deliberately excluded from this phase:
  - No business state mutation.
  - No coordinator / adapter calls.
  - No audit DB writes.
  - No DHL API calls.
  - Raw payload is never echoed in responses or emitted to logs.
  - Credentials/secrets are never logged.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from ..services.carrier.models.webhook import DhlWebhookPayload, make_log_safe
from ..services.carrier.persistence.event_db import init_db as _init_event_db
from ..services.carrier.persistence.event_db import insert_event as _insert_event

router = APIRouter(prefix="/api/v1/carrier/webhook", tags=["carrier-webhook"])


# ── injectable dependencies ───────────────────────────────────────────────────


def _require_webhook_secret() -> str:
    """
    FastAPI dependency — returns the configured DHL webhook HMAC secret.

    Raises HTTP 503 if the secret is missing or empty.  503 ("not available")
    rather than 401 ("unauthorised") so that callers cannot distinguish an
    unconfigured endpoint from a signing failure.
    """
    from ..core.config import settings

    secret = settings.dhl_webhook_secret
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Webhook endpoint is not configured on this server.",
        )
    return secret


def _get_event_db_path() -> Path:
    """FastAPI dependency — returns the carrier event DB path."""
    from ..core.config import settings

    root = settings.carrier_storage_root or (settings.storage_root / "carrier")
    root.mkdir(parents=True, exist_ok=True)
    return root / "carrier_events.db"


# ── route ─────────────────────────────────────────────────────────────────────


@router.post("/dhl", include_in_schema=False)
async def receive_dhl_webhook(
    request: Request,
    dhl_signature: Optional[str] = Header(None, alias="DHL-Signature"),
    secret: str = Depends(_require_webhook_secret),
    db_path: Path = Depends(_get_event_db_path),
) -> JSONResponse:
    """
    Receive and authenticate a DHL Express webhook event.

    - Authenticates via HMAC-SHA256 over the raw request body.
    - Duplicate event_ids are acknowledged with HTTP 200 (no reprocessing).
    - Response never echoes the raw payload or any credential.
    """
    if not dhl_signature:
        raise HTTPException(status_code=401, detail="Missing DHL-Signature header")

    raw_body: bytes = await request.body()

    expected_sig = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    try:
        sig_valid = hmac.compare_digest(expected_sig, dhl_signature)
    except (TypeError, ValueError):
        sig_valid = False

    if not sig_valid:
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        raw_dict = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if not isinstance(raw_dict, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    payload = DhlWebhookPayload.model_validate(raw_dict)
    event_id = payload.extract_event_id()
    if not event_id:
        raise HTTPException(status_code=400, detail="Missing event identifier in payload")

    event_type = payload.extract_event_type()
    batch_id = payload.extract_batch_id()

    _init_event_db(db_path)
    # Strip tracking identifiers before persistence.
    safe_payload = make_log_safe(raw_dict)
    is_new = _insert_event(db_path, event_id, batch_id, event_type, safe_payload)

    return JSONResponse({"status": "ok", "accepted": is_new})
