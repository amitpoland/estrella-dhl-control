"""
wFirma inbound webhook receiver.

Endpoint
--------
  POST /api/v1/webhooks/wfirma
       Receives event push notifications from wFirma.pl.

Security model (applied in order):
  1. Guard   — HTTP 503 if WFIRMA_WEBHOOK_KEY is not configured.
               503 signals "not available" rather than "unauthorised",
               preventing probing from learning the key is unset.
  2. JSON    — HTTP 400 if body is not valid JSON object.
  3. Key     — HTTP 403 if webhook_key field is missing or does not match
               the configured key (constant-time comparison).
  4. Store   — Raw payload (webhook_key stripped) written to DB.
  5. Respond — {"webhook_key": "<echoed key>"} on success.

Deliberately excluded from Phase 1:
  - No business state mutation.
  - No wFirma API calls.
  - No invoice / customer sync.
"""
from __future__ import annotations

import hmac
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from ..services.wfirma_webhook_db import init_db as _init_db
from ..services.wfirma_webhook_db import insert_event as _insert_event

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks-wfirma"])


# ── injectable dependencies ───────────────────────────────────────────────────


def _require_wfirma_webhook_key() -> str:
    """
    FastAPI dependency — returns the configured WFIRMA_WEBHOOK_KEY.

    Raises HTTP 503 if the key is missing or empty.  503 ("not available")
    rather than 403 ("forbidden") so callers cannot distinguish an
    unconfigured endpoint from an auth failure.
    """
    from ..core.config import settings

    key = settings.wfirma_webhook_key
    if not key:
        raise HTTPException(
            status_code=503,
            detail="Webhook endpoint is not configured on this server.",
        )
    return key


def _get_webhook_db_path() -> Path:
    """FastAPI dependency — returns the wFirma webhook event DB path."""
    from ..core.config import settings

    root = Path(settings.storage_root)
    root.mkdir(parents=True, exist_ok=True)
    return root / "wfirma_webhook_events.db"


# ── route ─────────────────────────────────────────────────────────────────────


@router.post("/wfirma", include_in_schema=False)
async def receive_wfirma_webhook(
    request: Request,
    configured_key: str = Depends(_require_wfirma_webhook_key),
    db_path: Path = Depends(_get_webhook_db_path),
) -> JSONResponse:
    """
    Receive and authenticate a wFirma webhook event.

    - Authenticates via constant-time comparison of webhook_key in JSON body.
    - Duplicate event ids (payload["id"]) are acknowledged with HTTP 200 (no reprocessing).
    - webhook_key is never written to storage or emitted in logs.
    """
    raw_body: bytes = await request.body()

    try:
        payload: object = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    provided_key: Optional[str] = payload.get("webhook_key")
    if not provided_key:
        raise HTTPException(status_code=403, detail="Missing or empty webhook_key in payload")

    try:
        key_valid = hmac.compare_digest(
            provided_key.encode("utf-8"),
            configured_key.encode("utf-8"),
        )
    except (TypeError, ValueError):
        key_valid = False

    if not key_valid:
        raise HTTPException(status_code=403, detail="Invalid webhook_key")

    # Strip the secret before storing — it must never land in the DB.
    safe_payload = {k: v for k, v in payload.items() if k != "webhook_key"}

    event_id: str = str(payload.get("id") or uuid.uuid4())
    event_type: Optional[str] = payload.get("event_type") or payload.get("type")
    received_at: str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    _init_db(db_path)
    _insert_event(db_path, event_id, event_type, safe_payload, received_at)

    return JSONResponse({"webhook_key": provided_key})
