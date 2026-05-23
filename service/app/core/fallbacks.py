"""
fallbacks.py — Graceful degradation responses when external services are unavailable.

Each fallback returns a safe, structured value that the caller can handle
without crashing. All fallbacks log a WARNING so operators see them in logs.

These are used by circuit breaker wrappers in service modules:
    cliq_service.py       → cliq_post_fallback
    workdrive_uploader.py → workdrive_upload_fallback
    wfirma_client.py      → wfirma_request_fallback
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .logging import get_logger

log = get_logger(__name__)


def cliq_post_fallback(text: str = "", **_kwargs: Any) -> bool:
    """Fallback for Cliq channel/webhook posting.

    Logs the message that would have been sent so operators can resend manually.
    Always returns False so callers know the post did not reach Cliq.
    """
    preview = text[:200] if text else "(no text)"
    log.warning(
        "CLIQ FALLBACK: circuit open — message not delivered. Preview: %r", preview
    )
    return False


def workdrive_upload_fallback(
    batch_id: str = "",
    **_kwargs: Any,
) -> Dict[str, Any]:
    """Fallback for WorkDrive batch uploads.

    Returns a structured result identical in shape to workdrive_uploader.upload_pz_outputs()
    so callers don't need special-case handling. Resource IDs are None, success=False.
    Local files are always safe — the service retry queue will pick them up.
    """
    log.warning(
        "WORKDRIVE FALLBACK: circuit open — upload skipped for batch %r. "
        "Local files are safe; retry queue will handle upload.",
        batch_id,
    )
    return {
        "success":           False,
        "pdf_resource_id":   None,
        "xlsx_resource_id":  None,
        "batch_folder_id":   None,
        "error":             "workdrive_circuit_breaker_open",
    }


def wfirma_request_fallback(
    method: str = "",
    module: str = "",
    action: str = "",
    **_kwargs: Any,
) -> tuple[int, str]:
    """Fallback for wFirma HTTP requests.

    Returns HTTP 503 with a machine-readable body so callers that check
    the status code (e.g. probe_endpoint) behave correctly.
    """
    log.warning(
        "WFIRMA FALLBACK: circuit open — request skipped (%s %s/%s)",
        method, module, action,
    )
    return 503, "circuit_breaker_open"


def dhl_tracking_fallback(awb: str = "", **_kwargs: Any) -> Dict[str, Optional[str]]:
    """Fallback for DHL tracking API calls.

    Returns a structured dict so callers can display a 'tracking unavailable'
    status instead of crashing or showing a blank field.
    """
    log.warning("DHL FALLBACK: circuit open — tracking unavailable for AWB %r", awb)
    return {
        "status":      "tracking_unavailable",
        "last_event":  "External tracking system temporarily unavailable",
        "location":    None,
        "event_time":  None,
    }
