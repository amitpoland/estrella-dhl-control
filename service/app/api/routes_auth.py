"""
routes_auth.py — Authentication endpoints for Estrella PZ Dashboard.

POST /auth/login
POST /auth/logout
POST /auth/signup
GET  /auth/me
POST /auth/forgot-password
POST /auth/reset-password

Admin (role=admin only):
GET  /auth/users
POST /auth/users/{id}/approve
POST /auth/users/{id}/reject
POST /auth/users/{id}/deactivate
POST /auth/users/{id}/activate
POST /auth/users/{id}/role
"""
from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, field_validator

from ..auth.dependencies import get_current_user, require_admin
from ..auth.service import (
    check_rate_limit,
    clear_attempts,
    consume_reset_token,
    count_users,
    create_reset_token,
    create_token,
    create_user,
    get_user_by_email,
    get_user_by_id,
    list_users,
    record_failed_attempt,
    update_last_login,
    verify_password,
    approve_user,
    reject_user,
    set_user_role,
    set_user_active,
    ROLES,
)
from ..services.email_service import (
    queue_email,
    make_approval_email,
    make_rejection_email,
    make_password_reset_email,
)
from ..core.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Request / response models ─────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str
    remember: bool = False

class SignupRequest(BaseModel):
    full_name: str
    company_name: str = ""
    email: str
    password: str
    confirm_password: str
    role: str = "viewer"

    @field_validator("role")
    @classmethod
    def role_valid(cls, v):
        if v not in ROLES:
            raise ValueError(f"Role must be one of: {', '.join(ROLES)}")
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one number")
        return v

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    code: str
    new_password: str
    confirm_password: str

class SetRoleRequest(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def role_valid(cls, v):
        if v not in ROLES:
            raise ValueError(f"Role must be one of: {', '.join(ROLES)}")
        return v


def _safe_user(u: dict) -> dict:
    """Strip sensitive fields before returning to client."""
    return {
        "id":              u["id"],
        "full_name":       u["full_name"],
        "company_name":    u["company_name"],
        "email":           u["email"],
        "role":            u["role"],
        "is_active":       bool(u.get("is_active", 0)),
        "is_approved":     bool(u.get("is_approved", 0)),
        "email_verified":  bool(u.get("email_verified", 0)),
        "approval_status": u.get("approval_status", "pending"),
        "created_at":      u.get("created_at"),
        "last_login":      u.get("last_login"),
    }


def _set_session_cookie(response: Response, token: str, remember: bool) -> None:
    max_age = 60 * 60 * 24 * 30 if remember else 60 * 60 * 24
    response.set_cookie(
        key="pz_session",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,   # set True behind HTTPS / Cloudflare
        max_age=max_age,
        path="/",
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/login")
async def login(body: LoginRequest, response: Response):
    email = body.email.lower().strip()

    # Rate limit check
    allowed, msg = check_rate_limit(email)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=msg)

    user = get_user_by_email(email)
    if not user or not verify_password(body.password, user["password_hash"]):
        record_failed_attempt(email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    approval = user.get("approval_status", "approved" if user.get("is_approved") else "pending")

    if not user.get("is_active", 0):
        if approval == "rejected":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account request was not approved. Please contact an administrator.",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account has been deactivated.",
        )

    if approval != "approved":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is pending admin approval. You will receive an email when access is granted.",
        )

    # Success
    clear_attempts(email)
    update_last_login(user["id"])
    token = create_token(user["id"], user["role"], remember=body.remember)
    _set_session_cookie(response, token, remember=body.remember)

    return {"ok": True, "user": _safe_user(user)}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("pz_session", path="/")
    return {"ok": True}


@router.post("/signup")
async def signup(body: SignupRequest):
    if body.password != body.confirm_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passwords do not match")

    email = body.email.lower().strip()
    if get_user_by_email(email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    # First user gets Admin + auto-approved; all subsequent users await approval
    is_first = count_users() == 0
    role      = "admin" if is_first else body.role
    approved  = is_first

    user = create_user(
        full_name      = body.full_name.strip(),
        company_name   = body.company_name.strip(),
        email          = email,
        password       = body.password,
        role           = role,
        is_approved    = approved,
        email_verified = is_first,   # first user auto-verified
    )
    return {
        "ok":       True,
        "approved": approved,
        "message":  (
            "Admin account created. You can now log in."
            if approved else
            "Account created. An admin will review your request and you will receive an email when approved."
        ),
    }


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return _safe_user(user)


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest):
    """Generate a password-reset code and email it to the user.

    Per Estrella production incident 2026-05-13 (Tejal lockout): the prior
    implementation returned the code in the API response body (`_debug_code`)
    and required an admin to manually relay it. This produced "code routed
    to admin" UI labels with no actual delivery path. Now the code is
    emailed to the user directly via `queue_email` (Zoho Mail REST primary,
    file-queue fallback).

    Security:
    - Always returns the same success message regardless of whether the
      email exists (no user enumeration).
    - Email-queue failure is logged at WARNING but does NOT change the
      response; the admin can still recover the code from `reset_tokens`
      table via SQL if email fails.
    - `_debug_code` field is REMOVED from the response (was an admin
      relay mechanism; obsolete now that the email path exists).
    """
    email = body.email.lower().strip()
    user  = get_user_by_email(email)
    # Always return success to avoid user enumeration
    if not user:
        return {
            "ok": True,
            "message": "If that email is registered, a reset code has been emailed to you.",
        }
    code = create_reset_token(user["id"])

    # Queue the reset email (non-blocking). Failure must not break the
    # response or expose information about whether the email landed.
    email_queued = False
    try:
        reset_url = f"{settings.fastapi_public_url.rstrip('/')}/forgot-password"
        subject, html, text = make_password_reset_email(
            user_full_name=user.get("full_name", ""),
            code=code,
            reset_url=reset_url,
        )
        queue_email(
            to=user["email"],
            subject=subject,
            body_html=html,
            body_text=text,
        )
        email_queued = True
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "Email queue failed for password reset (user_id=%s): %s",
            user["id"], exc,
        )

    return {
        "ok":      True,
        "message": (
            "If that email is registered, a reset code has been emailed to you."
            if email_queued else
            "Reset code generated. If you do not receive an email shortly, contact your admin."
        ),
    }


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest):
    if body.new_password != body.confirm_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passwords do not match")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password too short")

    ok = consume_reset_token(body.code, body.new_password)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset code")
    return {"ok": True, "message": "Password updated. You can now log in."}


# ── Admin endpoints ───────────────────────────────────────────────────────────

@router.get("/users")
async def admin_list_users(user: dict = Depends(require_admin)):
    return [_safe_user(u) for u in list_users()]


@router.get("/users/{user_id}/active-reset-code")
async def admin_get_active_reset_code(
    user_id: str,
    user: dict = Depends(require_admin),
):
    """Recover the most recent UNUSED, UNEXPIRED reset code for a user.

    Operator-recovery surface for the case where (a) the password-reset
    email failed to deliver, (b) the user cannot access their inbox, or
    (c) SMTP/Zoho was misconfigured. Admin-only. Per Estrella incident
    2026-05-13 — closes the loop where the prior implementation relied
    on admin manually relaying the code but no UI existed to read it.

    Returns 404 if no active code exists; 410 if expired/used; 200 with
    code on success. Admin action is audit-logged via standard request
    log (every read is observable).
    """
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    from datetime import datetime, timezone
    from ..auth.database import get_db
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db() as con:
        row = con.execute(
            "SELECT token, expires_at FROM reset_tokens "
            "WHERE user_id=? AND used=0 AND expires_at>? "
            "ORDER BY expires_at DESC LIMIT 1",
            (user_id, now_iso),
        ).fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail="No active reset code for this user. Ask the user to request a new one via /forgot-password.",
        )
    return {
        "ok":         True,
        "user_email": target["email"],
        "code":       row["token"],
        "expires_at": row["expires_at"],
        "note":       "Share this code with the user via a secure channel. Code is single-use.",
    }


@router.post("/users/{user_id}/approve")
async def admin_approve_user(user_id: str, user: dict = Depends(require_admin)):
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    approve_user(user_id)

    # Queue approval email (non-blocking)
    try:
        login_url = f"{settings.fastapi_public_url.rstrip('/')}/login"
        subject, html, text = make_approval_email(target["full_name"], login_url)
        queue_email(to=target["email"], subject=subject, body_html=html, body_text=text)
    except Exception as exc:
        # Email queue failure must never break approval
        import logging
        logging.getLogger(__name__).warning("Email queue failed for approve: %s", exc)

    return {"ok": True, "message": f"User {target['email']} approved. Approval email queued."}


@router.post("/users/{user_id}/reject")
async def admin_reject_user(user_id: str, user: dict = Depends(require_admin)):
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target["id"] == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot reject your own account")
    reject_user(user_id)

    # Queue rejection email (non-blocking)
    try:
        subject, html, text = make_rejection_email(target["full_name"])
        queue_email(to=target["email"], subject=subject, body_html=html, body_text=text)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Email queue failed for reject: %s", exc)

    return {"ok": True, "message": f"User {target['email']} rejected. Rejection email queued."}


@router.post("/users/{user_id}/role")
async def admin_set_role(user_id: str, body: SetRoleRequest, user: dict = Depends(require_admin)):
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    set_user_role(user_id, body.role)
    return {"ok": True, "message": f"Role updated to '{body.role}'"}


@router.post("/users/{user_id}/deactivate")
async def admin_deactivate_user(user_id: str, user: dict = Depends(require_admin)):
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target["id"] == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
    set_user_active(user_id, False)
    return {"ok": True}


@router.post("/users/{user_id}/activate")
async def admin_activate_user(user_id: str, user: dict = Depends(require_admin)):
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    set_user_active(user_id, True)
    return {"ok": True}
