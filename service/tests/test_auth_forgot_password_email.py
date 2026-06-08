"""
test_auth_forgot_password_email.py — Production incident 2026-05-13 (Tejal
lockout): the prior forgot-password endpoint generated a reset code
but returned it in the response body as `_debug_code` instead of emailing
the user. The UI label "code routed to admin" was honest about the missing
delivery path. This test suite covers the fix:

1. forgot-password now queues an email with the reset code to the user
2. The response no longer exposes `_debug_code`
3. User-enumeration resistance preserved (same message for unknown email)
4. Admin can recover an active reset code via /auth/users/{id}/active-reset-code
5. Email template carries the code, expiry note, and reset URL
"""
from __future__ import annotations

import json as _json
import re as _re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.core.config import settings  # noqa: E402


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """Fresh users.db + email queue per test. Re-init the auth DB to a
    tmp_path so we don't pollute the worktree's storage."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "auth_db_path", str(tmp_path / "users.db"))
    monkeypatch.setattr(settings, "fastapi_public_url", "https://pz.estrellajewels.eu")

    from app.auth.database import init_db
    init_db(tmp_path / "users.db")

    from app.main import app
    yield TestClient(app)


def _signup(client, email: str = "tejal@estrellajewels.com", password: str = "Test1234!"):
    """First signup auto-approves as admin per existing signup logic."""
    r = client.post("/auth/signup", json={
        "full_name":        "Tejal Test",
        "email":            email,
        "password":         password,
        "confirm_password": password,
        "role":             "admin",
    })
    assert r.status_code == 200, r.text
    return r.json()


def _login(client, email: str, password: str):
    return client.post("/auth/login", json={
        "email": email, "password": password, "remember": False,
    })


# Reset codes are now secrets.token_hex(4) → exactly 8 lowercase hex chars
# (PR #488 H-A2: replaced the old 6-digit numeric code).
_HEX8 = _re.compile(r"^[0-9a-f]{8}$")


def _extract_reset_code(body_text: str):
    """Return the 8-hex reset code embedded in an email body, or None."""
    for part in body_text.replace("\n", " ").split():
        if _HEX8.match(part):
            return part
    return None


# ── forgot-password emails the code ──────────────────────────────────────────

def test_forgot_password_queues_email_with_code(client, tmp_path):
    _signup(client)
    r = client.post("/auth/forgot-password", json={"email": "tejal@estrellajewels.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    # Response no longer exposes the code
    assert "_debug_code" not in body
    # Email queued to the user
    queue_file = tmp_path / "email_queue.json"
    assert queue_file.exists()
    entries = _json.loads(queue_file.read_text())
    assert len(entries) == 1
    entry = entries[0]
    assert entry["to"] == "tejal@estrellajewels.com"
    assert "reset" in entry["subject"].lower()
    # The 8-hex code must appear in the text body
    assert _extract_reset_code(entry["body_text"]) is not None, \
        f"8-hex reset code not present in body_text: {entry['body_text'][:200]}"
    assert "estrellajewels.eu/forgot-password" in entry["body_html"]


def test_forgot_password_does_not_enumerate_unknown_email(client, tmp_path):
    _signup(client)
    r = client.post("/auth/forgot-password", json={"email": "stranger@example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    # Same success message shape; no information leak about whether the
    # email is registered.
    assert "emailed" in body["message"].lower() or "registered" in body["message"].lower()
    # No email queued for the unknown user
    queue_file = tmp_path / "email_queue.json"
    if queue_file.exists():
        entries = _json.loads(queue_file.read_text())
        assert all(e["to"] != "stranger@example.com" for e in entries)


def test_forgot_password_response_omits_debug_code(client):
    _signup(client)
    r = client.post("/auth/forgot-password", json={"email": "tejal@estrellajewels.com"})
    body = r.json()
    # Explicit: prior implementation leaked the code as `_debug_code`.
    # The fix MUST remove it from the response.
    assert "_debug_code" not in body
    assert "code" not in body  # no raw code in any shape


def test_forgot_password_reset_token_persisted(client, tmp_path):
    """The code emailed must match what's in reset_tokens table (used by
    /auth/reset-password to verify)."""
    _signup(client)
    client.post("/auth/forgot-password", json={"email": "tejal@estrellajewels.com"})

    # Recover code from queue
    entries = _json.loads((tmp_path / "email_queue.json").read_text())
    code_from_email = _extract_reset_code(entries[0]["body_text"])
    assert code_from_email is not None

    # The same code resets the password
    r = client.post("/auth/reset-password", json={
        "code":             code_from_email,
        "new_password":     "NewPass123!",
        "confirm_password": "NewPass123!",
    })
    assert r.status_code == 200

    # New password works for login
    r = _login(client, "tejal@estrellajewels.com", "NewPass123!")
    assert r.status_code == 200


# ── Admin reset-code recovery endpoint ───────────────────────────────────────

def test_admin_can_recover_active_reset_code(client):
    """Admin can confirm an active reset code EXISTS (presence + expiry only).
    H-A4 (PR #488): the plaintext code is no longer returned in the response —
    admins re-email it via /auth/forgot-password instead."""
    signup_body = _signup(client)
    # Log in to get session cookie
    login_resp = _login(client, "tejal@estrellajewels.com", "Test1234!")
    assert login_resp.status_code == 200
    cookies = login_resp.cookies

    # Issue a reset code
    client.post("/auth/forgot-password", json={"email": "tejal@estrellajewels.com"})

    # Admin reads the active code
    user_id = signup_body.get("user_id") or _admin_find_user_id(client, cookies, "tejal@estrellajewels.com")
    r = client.get(f"/auth/users/{user_id}/active-reset-code", cookies=cookies)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["user_email"] == "tejal@estrellajewels.com"
    # H-A4: plaintext code must NOT be exposed; only presence + expiry.
    assert "code" not in body
    assert body["has_active_code"] is True
    assert "expires_at" in body


def test_admin_reset_code_recovery_404_when_no_active_code(client):
    signup_body = _signup(client)
    cookies = _login(client, "tejal@estrellajewels.com", "Test1234!").cookies
    user_id = signup_body.get("user_id") or _admin_find_user_id(client, cookies, "tejal@estrellajewels.com")
    # No forgot-password called → no token exists
    r = client.get(f"/auth/users/{user_id}/active-reset-code", cookies=cookies)
    assert r.status_code == 404


def test_admin_reset_code_recovery_requires_auth(client):
    _signup(client)
    # No cookies / not logged in
    r = client.get("/auth/users/some-user-id/active-reset-code")
    assert r.status_code in (401, 403)


# ── Email template ───────────────────────────────────────────────────────────

def test_make_password_reset_email_contains_code_and_link():
    from app.services.email_service import make_password_reset_email
    subject, html, text = make_password_reset_email(
        user_full_name="Tejal",
        code="123456",
        reset_url="https://pz.estrellajewels.eu/forgot-password",
        expires_minutes=30,
    )
    assert "reset" in subject.lower()
    assert "123456" in html
    assert "123456" in text
    assert "30 minutes" in text
    assert "pz.estrellajewels.eu/forgot-password" in html
    # No exception-message leak; Estrella branding present
    assert "Estrella" in html


def test_make_password_reset_email_handles_empty_name():
    from app.services.email_service import make_password_reset_email
    subject, html, text = make_password_reset_email(
        user_full_name="",
        code="654321",
    )
    # No bare 'Hello ,' formatting
    assert "Hello ," not in text
    assert "654321" in text


# ── Helpers ──────────────────────────────────────────────────────────────────

def _admin_find_user_id(client, cookies, email: str) -> str:
    r = client.get("/auth/users", cookies=cookies)
    assert r.status_code == 200, r.text
    for u in r.json():
        if u["email"] == email:
            return u["id"]
    raise AssertionError(f"User {email!r} not found in /auth/users")
