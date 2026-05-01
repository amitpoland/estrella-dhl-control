"""
zoho_auth.py — Zoho Mail OAuth2 token management with auto-refresh.

Reads credentials from `.env` via app.core.config.settings. Holds the access
token in memory only (never written back to disk). Automatically refreshes
when expired using the long-lived refresh token.

Public API:
    get_valid_access_token() -> str
        Returns a non-expired access token. Refreshes via the Zoho accounts
        endpoint if the cached token is expired or missing.

    has_zoho_credentials() -> bool
        True iff enough credentials are configured to make API calls.

    invalidate_cached_token() -> None
        Drops the cached token (for testing or after a 401).

Security:
    - Tokens are NEVER logged. Only `_mask()` outputs (first 4 chars + "****").
    - Refresh token is read from settings.zoho_mail_refresh_token only;
      it is never written or echoed.
    - On refresh failure, raises ZohoAuthError with a generic message.

Zoho OAuth Token Management Rules (canonical for all Zoho services):
    1. In-memory only — never persist refreshed access tokens to disk or .env.
    2. Thread-safe cache — protect shared token state with threading.Lock (sync)
       or asyncio.Lock (async). Hold the lock only for cache reads/writes,
       never across network calls.
    3. Masked logging — use _mask(token) (first 4 chars + "****") in all log
       output. Never log full tokens or full API error response bodies (they
       may echo tokens).
    4. Safety margin — refresh at least _REFRESH_SAFETY_SECONDS (60 s) before
       expiry to avoid race windows.
    5. Credentials via settings — read secrets from app.core.config.settings,
       never hard-code or accept from request parameters.

    These rules apply to zoho_auth.py, cliq_bot_service.py,
    cliq_service.py, and workdrive_uploader.py.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import httpx

from ..core.config import settings

log = logging.getLogger(__name__)


# ── Errors ────────────────────────────────────────────────────────────────────

class ZohoAuthError(RuntimeError):
    """Raised when token cannot be obtained or refreshed."""


# ── In-memory cache (process-local, thread-safe) ──────────────────────────────

_cache_lock = threading.Lock()
_cached_token: Optional[str] = None
_cached_expires_at: float = 0.0   # epoch seconds; 0 = not cached
# Refresh slightly before actual expiry to avoid edge-case 401s
_REFRESH_SAFETY_SECONDS = 60


def _mask(value: Optional[str]) -> str:
    """Mask a credential for safe logging — show first 4 chars + ****."""
    if not value:
        return "<not set>"
    return value[:4] + "****"


# ── Public API ────────────────────────────────────────────────────────────────

def has_zoho_credentials() -> bool:
    """
    True iff at least one viable auth path is configured:
      - refresh-token flow: client_id + client_secret + refresh_token
      - bootstrap flow:     ZOHO_MAIL_API_TOKEN (short-lived, no refresh)
    """
    refresh_ok = bool(
        settings.zoho_client_id
        and settings.zoho_client_secret
        and settings.zoho_mail_refresh_token
    )
    bootstrap_ok = bool(settings.zoho_mail_api_token)
    return refresh_ok or bootstrap_ok


def invalidate_cached_token() -> None:
    """Drop the cached access token. Next call will refresh."""
    global _cached_token, _cached_expires_at
    with _cache_lock:
        _cached_token = None
        _cached_expires_at = 0.0


def get_valid_access_token() -> str:
    """
    Return a valid (non-expired) Zoho Mail access token.

    Order of preference:
      1. Cached token if still valid.
      2. Refresh via refresh_token if client_id + client_secret + refresh_token
         are configured.
      3. Static ZOHO_MAIL_API_TOKEN as last-resort bootstrap (no refresh).

    Raises:
        ZohoAuthError if no valid token can be obtained.
    """
    global _cached_token, _cached_expires_at
    now = time.time()

    with _cache_lock:
        if _cached_token and now < (_cached_expires_at - _REFRESH_SAFETY_SECONDS):
            return _cached_token

    # Try refresh-token flow first (production path)
    if (
        settings.zoho_client_id
        and settings.zoho_client_secret
        and settings.zoho_mail_refresh_token
    ):
        token, expires_in = _refresh_via_oauth()
        with _cache_lock:
            _cached_token = token
            _cached_expires_at = time.time() + expires_in
        return token

    # Fall back to static bootstrap token (will fail in 1 hour with no recovery)
    if settings.zoho_mail_api_token:
        log.warning(
            "[zoho_auth] using static ZOHO_MAIL_API_TOKEN — no refresh path. "
            "Configure ZOHO_CLIENT_ID/SECRET/REFRESH_TOKEN for production."
        )
        return settings.zoho_mail_api_token

    raise ZohoAuthError(
        "Zoho token expired or invalid: no credentials configured. "
        "Set ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_MAIL_REFRESH_TOKEN in .env."
    )


# ── Refresh implementation ────────────────────────────────────────────────────

def _refresh_via_oauth() -> tuple[str, int]:
    """
    Exchange the refresh token for a new access token.

    Returns: (access_token, expires_in_seconds).
    Raises:  ZohoAuthError on any failure.
    """
    url = f"{settings.zoho_accounts_base.rstrip('/')}/oauth/v2/token"
    log.info(
        "[zoho_auth] refreshing access token (client=%s)",
        _mask(settings.zoho_client_id),
    )
    try:
        with httpx.Client(timeout=12) as client:
            resp = client.post(
                url,
                data={
                    "grant_type":    "refresh_token",
                    "client_id":     settings.zoho_client_id or "",
                    "client_secret": settings.zoho_client_secret or "",
                    "refresh_token": settings.zoho_mail_refresh_token or "",
                },
            )
        if resp.status_code != 200:
            # Don't echo the response body — may contain partial tokens
            raise ZohoAuthError(
                f"Zoho token refresh failed (HTTP {resp.status_code}). "
                "Verify client_id, client_secret, and refresh_token in .env."
            )
        payload = resp.json()
    except httpx.HTTPError as exc:
        raise ZohoAuthError(f"Zoho token refresh network error: {type(exc).__name__}") from exc
    except ValueError as exc:
        raise ZohoAuthError("Zoho token refresh: invalid JSON response") from exc

    access_token = payload.get("access_token")
    if not access_token:
        # Log error field only (no secrets) for diagnostics
        log.warning(
            "[zoho_auth] refresh failed: error=%s",
            payload.get("error", "unknown"),
        )
        raise ZohoAuthError(
            "Zoho token expired or invalid: refresh did not return an access_token. "
            "Refresh token may have been revoked — re-authorise via Zoho API Console."
        )

    expires_in = int(payload.get("expires_in", 3600))
    log.info("[zoho_auth] access token refreshed; expires_in=%ds", expires_in)
    return access_token, expires_in
