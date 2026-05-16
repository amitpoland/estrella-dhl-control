"""B-MD1 — backend route contracts for /auth/users admin writes (MDOC-2026-05).

Source-grep guarantees that the 5 admin write routes in routes_auth.py
remain behind require_admin, that role validation pins the allow-list,
and that self-target guards exist on reject + deactivate.

These contracts are mechanical proofs of the security envelope that
B-MD1 relies on. The new AdminUsersPage frontend is only safe because
the backend already enforces these invariants.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[2]
_ROUTE = _REPO / "service" / "app" / "api" / "routes_auth.py"
_AUTH_SERVICE = _REPO / "service" / "app" / "auth" / "service.py"


def _route_src() -> str:
    if not _ROUTE.exists():
        pytest.skip("routes_auth.py missing")
    return _ROUTE.read_text(encoding="utf-8")


def _auth_service_src() -> str:
    if not _AUTH_SERVICE.exists():
        pytest.skip("auth/service.py missing")
    return _AUTH_SERVICE.read_text(encoding="utf-8")


WRITE_ROUTES = ("approve", "reject", "role", "deactivate", "activate")


def test_all_admin_writes_have_require_admin():
    """Each of the 5 admin write routes declares Depends(require_admin)."""
    src = _route_src()
    for action in WRITE_ROUTES:
        # Locate decorator line position; require_admin must appear in the
        # def signature that immediately follows (within ~200 chars).
        dec_pat = rf'@router\.post\("/users/\{{user_id\}}/{action}"\)'
        m = re.search(dec_pat, src)
        assert m is not None, (
            f"Could not locate POST /users/{{user_id}}/{action} route decorator"
        )
        # Take the next 300 chars after the decorator (covers the def signature
        # even when default args span the line).
        after = src[m.end(): m.end() + 300]
        assert "require_admin" in after, (
            f"/users/{{user_id}}/{action} signature must use Depends(require_admin); "
            f"signature start: {after[:200]!r}"
        )


def test_set_role_validates_role_value():
    """SetRoleRequest.role_valid enforces the ROLES allow-list."""
    src = _route_src()
    # Locate the SetRoleRequest class.
    m = re.search(r"class\s+SetRoleRequest\(BaseModel\):[\s\S]+?(?=\nclass\s|\Z)", src)
    assert m is not None, "SetRoleRequest model must be defined"
    body = m.group(0)
    assert "role_valid" in body or "field_validator" in body, (
        "SetRoleRequest must declare a role validator"
    )
    assert "ROLES" in body, (
        "SetRoleRequest validator must check membership against ROLES allow-list"
    )


def test_role_allowlist_pinned():
    """ROLES tuple has exactly 5 canonical values."""
    src = _auth_service_src()
    m = re.search(r"^ROLES\s*=\s*\(([^)]+)\)", src, re.MULTILINE)
    assert m is not None, "ROLES tuple must be defined in auth/service.py"
    items = [s.strip().strip("'\"") for s in m.group(1).split(",") if s.strip()]
    expected = ["admin", "accounts", "logistics", "auditor", "viewer"]
    assert items == expected, (
        f"ROLES drifted: expected {expected}, got {items}. "
        "Frontend ADMIN_USERS_ROLES depends on this list — update both together."
    )


def test_reject_self_route_protection():
    """The /users/{id}/reject route refuses to reject the caller's own id."""
    src = _route_src()
    # Locate the admin_reject_user function body.
    m = re.search(
        r'@router\.post\("/users/\{user_id\}/reject"\)\s*\n'
        r'async def admin_reject_user\([\s\S]+?(?=\n@router\.|\Z)',
        src,
    )
    assert m is not None, "admin_reject_user function not found"
    body = m.group(0)
    # Must contain a self-target guard that returns/raises 400.
    assert 'target["id"] == user["id"]' in body or 'target["id"] == user.get("id")' in body, (
        "admin_reject_user must compare target id against current user id"
    )
    assert "400" in body, (
        "admin_reject_user must raise HTTPException 400 on self-reject"
    )


def test_deactivate_self_route_protection():
    """The /users/{id}/deactivate route refuses to deactivate the caller's own id."""
    src = _route_src()
    m = re.search(
        r'@router\.post\("/users/\{user_id\}/deactivate"\)\s*\n'
        r'async def admin_deactivate_user\([\s\S]+?(?=\n@router\.|\Z)',
        src,
    )
    assert m is not None, "admin_deactivate_user function not found"
    body = m.group(0)
    assert 'target["id"] == user["id"]' in body or 'target["id"] == user.get("id")' in body, (
        "admin_deactivate_user must compare target id against current user id"
    )
    assert "400" in body, (
        "admin_deactivate_user must raise HTTPException 400 on self-deactivate"
    )


def test_admin_writes_use_post_only():
    """No PATCH/PUT/DELETE decorators on /users/{user_id}/* admin actions."""
    src = _route_src()
    for action in WRITE_ROUTES:
        # Forbid non-POST decorators on this exact path.
        for bad_verb in ("get", "put", "patch", "delete"):
            pat = rf'@router\.{bad_verb}\("/users/\{{user_id\}}/{action}"\)'
            assert re.search(pat, src) is None, (
                f"/users/{{user_id}}/{action} must use POST only; "
                f"found @router.{bad_verb}"
            )
