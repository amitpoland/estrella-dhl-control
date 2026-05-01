"""
auth/dependencies.py — FastAPI dependencies for authentication and RBAC.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from .service import decode_token, get_user_by_id

# Role hierarchy: higher index = broader access
_ROLE_RANK = {
    "viewer":    0,
    "auditor":   1,
    "logistics": 2,
    "accounts":  3,
    "admin":     4,
}


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
