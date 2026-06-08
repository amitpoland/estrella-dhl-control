from __future__ import annotations

import hmac
from typing import Optional

from fastapi import Cookie, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from .config import settings

_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(
    key: Optional[str] = Security(_header),
    pz_session: Optional[str] = Cookie(default=None),
) -> None:
    if not settings.api_key:
        if settings.environment == "prod":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Server misconfiguration: API_KEY is not configured.",
            )
        return  # dev only — auth disabled

    if key is not None and hmac.compare_digest(key, settings.api_key):
        return

    if pz_session:
        from ..auth.dependencies import get_current_user_optional  # noqa: PLC0415
        user = get_current_user_optional(pz_session=pz_session)
        if user is not None:
            return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


def require_api_key_or_admin(
    key: Optional[str] = Security(_header),
    pz_session: Optional[str] = Cookie(default=None),
) -> None:
    """Like require_api_key, but session-cookie auth requires admin role.

    API-key path is unchanged (machine-to-machine callers are trusted).
    Session-cookie path rejects non-admin roles with 403 so that viewer/
    auditor/logistics/accounts sessions cannot reach admin-class endpoints.
    """
    if not settings.api_key:
        if settings.environment == "prod":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Server misconfiguration: API_KEY is not configured.",
            )
        return  # dev only — auth disabled

    if key is not None and hmac.compare_digest(key, settings.api_key):
        return  # direct API key accepted

    if pz_session:
        from ..auth.dependencies import get_current_user_optional  # noqa: PLC0415
        user = get_current_user_optional(pz_session=pz_session)
        if user is not None:
            if user.get("role") == "admin":
                return
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin role required for this endpoint",
            )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )
