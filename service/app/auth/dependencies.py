"""
auth/dependencies.py — FastAPI dependencies for authentication and RBAC.
"""
from __future__ import annotations

import hmac
from typing import Callable, Optional

from fastapi import Cookie, Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from ..core.config import settings
from .permissions import PERMISSION_CATALOGUE, has_permission
from .service import decode_token, get_user_by_id

# Role hierarchy: higher index = broader access
_ROLE_RANK = {
    "viewer":    0,
    "auditor":   1,
    "logistics": 2,
    "accounts":  3,
    "admin":     4,
}

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _get_token(pz_session: Optional[str] = Cookie(default=None)) -> Optional[str]:
    return pz_session


def get_current_user(
    pz_session: Optional[str] = Cookie(default=None),
) -> dict:
    """Dependency: returns current user dict or raises 401."""
    if not pz_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(pz_session)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")
    user = get_user_by_id(payload["sub"])
    if not user or not user["is_active"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account inactive")
    if not user["is_approved"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account pending approval")
    return user


def get_current_user_optional(
    pz_session: Optional[str] = Cookie(default=None),
) -> Optional[dict]:
    """Returns user or None (does not raise)."""
    if not pz_session:
        return None
    payload = decode_token(pz_session)
    if not payload:
        return None
    user = get_user_by_id(payload["sub"])
    if not user or not user["is_active"] or not user["is_approved"]:
        return None
    return user


def require_role(*roles: str):
    """Dependency factory: require user to have one of the given roles."""
    def _dep(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user['role']}' is not permitted for this action.",
            )
        return user
    return _dep


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


def require_permission(permission: str) -> Callable:
    """Dependency factory: require a catalogue permission (human RBAC).

    Authority: ``permissions.has_permission`` / ``ROLE_PERMISSIONS`` only —
    never a hardcoded role list in the caller.

    Machine-identity ruling (explicit, not an undocumented bypass):
    A valid ``X-API-Key`` is machine authentication and is admin-equivalent,
    matching ``require_api_key_privileged`` / permissions.py ("API-key is
    machine authentication elsewhere — not modeled as a human role").
    Session (human) callers must hold ``permission`` via the role bundle.
    """
    if permission not in PERMISSION_CATALOGUE:
        raise ValueError(
            f"require_permission({permission!r}): not in PERMISSION_CATALOGUE"
        )

    def _dep(
        key: Optional[str] = Security(_api_key_header),
        pz_session: Optional[str] = Cookie(default=None),
    ) -> Optional[dict]:
        if not settings.api_key:
            if settings.environment == "prod":
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Server misconfiguration: API_KEY is not configured.",
                )
            # Dev-only: auth disabled (parity with require_api_key).
            return None

        # Trusted automation — machine identity, admin-equivalent.
        if key is not None and hmac.compare_digest(
            key.encode("utf-8"), settings.api_key.encode("utf-8")
        ):
            return {"auth": "api_key", "role": "admin"}

        if not pz_session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        # Full session validation (inactive / unapproved) before permission check.
        user = get_current_user(pz_session=pz_session)
        if not has_permission(user.get("role"), permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Permission '{permission}' is required "
                    f"(role '{user.get('role')}' lacks it)."
                ),
            )
        return user

    return _dep


def require_users_admin(
    user: dict = Depends(require_admin),
    _permission: Optional[dict] = Depends(require_permission("users.admin")),
) -> dict:
    """Slice 2b — session admin + catalogue ``users.admin``.

    Keeps ``require_admin`` so a bare X-API-Key cannot widen into user-admin
    writes (``require_permission`` alone treats a valid key as machine-admin).
    """
    return user


def require_system_settings_admin(
    user: dict = Depends(require_admin),
    _permission: Optional[dict] = Depends(require_permission("system.settings.admin")),
) -> dict:
    """Slice 2b — session admin + catalogue ``system.settings.admin``.

    Same no-widen composition as ``require_users_admin``.
    """
    return user


def check_session_or_redirect(request: Request) -> Optional[dict]:
    """
    For HTML page routes: return user if authenticated,
    or return None (caller must redirect to /login).
    """
    pz_session = request.cookies.get("pz_session")
    if not pz_session:
        return None
    payload = decode_token(pz_session)
    if not payload:
        return None
    user = get_user_by_id(payload["sub"])
    if not user or not user["is_active"] or not user["is_approved"]:
        return None
    return user
