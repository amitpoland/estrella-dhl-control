"""
auth/service.py — User CRUD, password hashing, JWT creation, rate limiting.
"""
from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import bcrypt as _bcrypt
import jwt

from .database import get_db
from ..core.config import settings

ROLES = ("admin", "accounts", "logistics", "auditor", "viewer")


# ── Password helpers (direct bcrypt — avoids passlib startup compatibility issue) ─

def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── JWT helpers ───────────────────────────────────────────────────────────────

def create_token(user_id: str, role: str, remember: bool = False) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        days=30 if remember else 1
    )
    payload = {
        "sub": user_id,
        "role": role,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.auth_secret_key, algorithm="HS256")


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.auth_secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


# ── User queries ──────────────────────────────────────────────────────────────

def count_users() -> int:
    with get_db() as con:
        row = con.execute("SELECT COUNT(*) FROM users").fetchone()
        return row[0]


def get_user_by_email(email: str) -> Optional[dict]:
    with get_db() as con:
        row = con.execute(
            "SELECT * FROM users WHERE email=? COLLATE NOCASE", (email,)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: str) -> Optional[dict]:
    with get_db() as con:
        row = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None


def list_users() -> list[dict]:
    with get_db() as con:
        rows = con.execute(
            "SELECT * FROM users ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def create_user(
    full_name: str,
    company_name: str,
    email: str,
    password: str,
    role: str,
    is_approved: bool,
    email_verified: bool = False,
) -> dict:
    uid             = str(uuid.uuid4())
    now             = datetime.now(timezone.utc).isoformat()
    ph              = hash_password(password)
    approval_status = "approved" if is_approved else "pending"
    # Only set is_active=1 when the account is approved
    is_active       = 1 if is_approved else 0
    with get_db() as con:
        con.execute(
            """INSERT INTO users
               (id, full_name, company_name, email, password_hash, role,
                is_active, is_approved, email_verified, approval_status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (uid, full_name, company_name, email.lower().strip(),
             ph, role, is_active, 1 if is_approved else 0,
             1 if email_verified else 0, approval_status, now),
        )
    return get_user_by_id(uid)


def update_last_login(user_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as con:
        con.execute(
            "UPDATE users SET last_login=? WHERE id=?", (now, user_id)
        )


def approve_user(user_id: str) -> None:
    with get_db() as con:
        con.execute(
            "UPDATE users SET is_approved=1, is_active=1, approval_status='approved' WHERE id=?",
            (user_id,),
        )


def reject_user(user_id: str) -> None:
    with get_db() as con:
        con.execute(
            "UPDATE users SET is_approved=0, is_active=0, approval_status='rejected' WHERE id=?",
            (user_id,),
        )


def set_user_role(user_id: str, role: str) -> None:
    if role not in ROLES:
        raise ValueError(f"Invalid role: {role}")
    with get_db() as con:
        con.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))


def set_user_active(user_id: str, active: bool) -> None:
    with get_db() as con:
        con.execute(
            "UPDATE users SET is_active=? WHERE id=?", (1 if active else 0, user_id)
        )


# ── Rate limiting ─────────────────────────────────────────────────────────────

MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def check_rate_limit(email: str) -> tuple[bool, str]:
    """Return (allowed, message). Updates attempt counter."""
    now = datetime.now(timezone.utc)
    with get_db() as con:
        row = con.execute(
            "SELECT attempts, locked_until FROM login_attempts WHERE email=?",
            (email.lower(),),
        ).fetchone()

        if row:
            locked_until_str = row["locked_until"]
            if locked_until_str:
                locked_until = datetime.fromisoformat(locked_until_str)
                if locked_until > now:
                    remaining = int((locked_until - now).total_seconds() / 60) + 1
                    return False, f"Too many failed attempts. Try again in {remaining} min."
                # Lock expired — reset
                con.execute(
                    "UPDATE login_attempts SET attempts=0, locked_until=NULL WHERE email=?",
                    (email.lower(),),
                )
    return True, ""


def record_failed_attempt(email: str) -> None:
    now = datetime.now(timezone.utc)
    with get_db() as con:
        row = con.execute(
            "SELECT attempts FROM login_attempts WHERE email=?", (email.lower(),)
        ).fetchone()
        attempts = (row["attempts"] + 1) if row else 1
        locked_until = None
        if attempts >= MAX_ATTEMPTS:
            locked_until = (now + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
        con.execute(
            """INSERT INTO login_attempts (email, attempts, locked_until)
               VALUES (?,?,?)
               ON CONFLICT(email) DO UPDATE SET attempts=?, locked_until=?""",
            (email.lower(), attempts, locked_until, attempts, locked_until),
        )


def clear_attempts(email: str) -> None:
    with get_db() as con:
        con.execute("DELETE FROM login_attempts WHERE email=?", (email.lower(),))


# ── Password reset ────────────────────────────────────────────────────────────

def create_reset_token(user_id: str) -> str:
    """Generate a 6-digit code valid for 30 minutes."""
    code = "".join(random.choices(string.digits, k=6))
    expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    with get_db() as con:
        # Invalidate old tokens for this user
        con.execute("DELETE FROM reset_tokens WHERE user_id=?", (user_id,))
        con.execute(
            "INSERT INTO reset_tokens (token, user_id, expires_at) VALUES (?,?,?)",
            (code, user_id, expires),
        )
    return code


def verify_reset_token(code: str) -> Optional[str]:
    """Return user_id if the code is valid and unused, else None."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as con:
        row = con.execute(
            "SELECT user_id FROM reset_tokens WHERE token=? AND used=0 AND expires_at>?",
            (code, now),
        ).fetchone()
        return row["user_id"] if row else None


def consume_reset_token(code: str, new_password: str) -> bool:
    """Mark token as used and update password. Returns True on success."""
    user_id = verify_reset_token(code)
    if not user_id:
        return False
    ph = hash_password(new_password)
    with get_db() as con:
        con.execute("UPDATE users SET password_hash=? WHERE id=?", (ph, user_id))
        con.execute("UPDATE reset_tokens SET used=1 WHERE token=?", (code,))
    return True
