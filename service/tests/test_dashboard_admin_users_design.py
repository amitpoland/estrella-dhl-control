"""B-MD1 — AdminUsersPage source-grep contracts (MDOC-2026-05).

Pins the architectural rules for the new Admin · Users page mechanically.
The page is separate from MasterDataPage by design — both existing
MasterDataPage security contracts (test_only_allowed_writes_in_master,
test_no_dangerous_destructive_buttons_in_master) stay unchanged.

Approval package: tasks/master-data-users-roles-approval-package.md
Implementation plan: tasks/master-data-users-roles-implementation-plan.md
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[2]
_DASH = _REPO / "service" / "app" / "static" / "dashboard.html"


def _src() -> str:
    if not _DASH.exists():
        pytest.skip("dashboard.html missing")
    return _DASH.read_text(encoding="utf-8")


def _admin_users_block(src: str) -> str:
    """The AdminUsersPage component body up to the next top-level function."""
    start = src.find("function AdminUsersPage(")
    assert start >= 0, "AdminUsersPage function not found in dashboard.html"
    after = src[start:]
    end = len(after)
    for term in ("\nfunction ", "\n// ══"):
        idx = after.find(term, 1)
        if idx >= 0 and idx < end:
            end = idx
    return after[:end]


# ── Existence + routing ─────────────────────────────────────────────────────

def test_admin_users_page_function_present():
    src = _src()
    assert "function AdminUsersPage(" in src, (
        "AdminUsersPage component must be defined in dashboard.html"
    )


def test_admin_users_page_renders_at_route():
    src = _src()
    assert "page === 'admin_users'" in src, (
        "App router must render AdminUsersPage when page === 'admin_users'"
    )
    assert "<AdminUsersPage" in src, (
        "AdminUsersPage component must be referenced in the App routing block"
    )


def test_admin_users_nav_entry_present():
    src = _src()
    # The NAV_TREE entry must include id: 'admin_users' under the Setup group.
    assert "'admin_users'" in src, (
        "NAV_TREE must include 'admin_users' entry under g_setup.children"
    )
    # And the label must mention Users (not bare "Admin")
    block = _admin_users_block(src)
    assert "Admin · Users" in block, (
        "Page must display 'Admin · Users' title for clarity"
    )


# ── Admin gate ──────────────────────────────────────────────────────────────

def test_admin_users_admin_gate_present():
    block = _admin_users_block(_src())
    # The component must check user.role === 'admin' (or equivalent admin check).
    assert "user.role === 'admin'" in block or "isAdmin" in block, (
        "AdminUsersPage must gate render on admin role"
    )
    # Non-admin must hit an Access denied banner.
    assert "admin-users-access-denied" in block, (
        "AdminUsersPage must render an access-denied surface for non-admins"
    )


# ── Endpoint discipline ─────────────────────────────────────────────────────

def test_admin_users_calls_only_allowed_endpoints():
    """Every apiFetch inside the AdminUsersPage block targets ONLY /auth/users."""
    block = _admin_users_block(_src())
    calls = re.findall(r"apiFetch\(([^,)]+)", block)
    assert calls, "Page must call apiFetch at least once (load + writes)"
    for c in calls:
        cl = c.strip()
        # Allow literal '/auth/users' OR concatenated '/auth/users/' + id + '/<action>'.
        ok = (
            "/auth/users" in cl
            and "wfirma" not in cl.lower()
            and "finance" not in cl.lower()
            and "proforma" not in cl.lower()
            and "/api/v1/" not in cl
        )
        assert ok, f"AdminUsersPage called non-auth endpoint: {c!r}"


def test_admin_users_uses_post_for_writes():
    """All 5 write actions use method: 'POST'. No PATCH/DELETE."""
    block = _admin_users_block(_src())
    # Forbidden verbs anywhere in the block.
    for forbidden in ("method: 'PATCH'", "method: 'DELETE'", 'method: "PATCH"', 'method: "DELETE"'):
        assert forbidden not in block, (
            f"AdminUsersPage must not contain {forbidden!r} (writes use POST only)"
        )
    # POST must appear at least once (in the _runAction helper).
    assert "method: 'POST'" in block, (
        "AdminUsersPage must POST for all write actions"
    )


# ── Role allow-list ─────────────────────────────────────────────────────────

def test_admin_users_role_dropdown_pinned_values():
    """Role dropdown allow-list matches backend ROLES exactly."""
    src = _src()
    # Constant declaration outside the component.
    m = re.search(
        r"const\s+ADMIN_USERS_ROLES\s*=\s*\[([^\]]+)\]",
        src,
    )
    assert m is not None, (
        "Frontend must declare ADMIN_USERS_ROLES allow-list constant"
    )
    items = [s.strip().strip("'\"") for s in m.group(1).split(",") if s.strip()]
    assert items == ['admin', 'accounts', 'logistics', 'auditor', 'viewer'], (
        f"ADMIN_USERS_ROLES must match backend ROLES exactly; got {items}"
    )


# ── No create / delete user UI ──────────────────────────────────────────────

def test_admin_users_no_create_or_delete_user_buttons():
    """Strings >Create user<, >Delete user<, >Remove user< MUST NOT appear."""
    block = _admin_users_block(_src())
    for forbidden in (
        ">Create user<", ">Delete user<", ">Remove user<",
        ">Invite user<",  # Invite is allowed only as a disabled chip with explanation
    ):
        assert forbidden not in block, (
            f"AdminUsersPage must not contain {forbidden!r}"
        )
    # The disabled invite chip is allowed and must be testable.
    assert "admin-users-invite-disabled" in block, (
        "AdminUsersPage must surface a disabled invite chip with clear labelling"
    )


# ── Self-lockout guard ──────────────────────────────────────────────────────

def test_admin_users_has_self_lockout_guard():
    block = _admin_users_block(_src())
    # The component computes isSelf and uses it to hide actions.
    assert "isSelf" in block or "u.id === currentUserId" in block, (
        "AdminUsersPage must mark the current admin's own row to prevent self-lockout"
    )
    # And there must be a self-noactions branch in the render.
    assert "admin-users-self-noactions" in block, (
        "AdminUsersPage must render a no-actions cell for the self-row"
    )


# ── Confirmation discipline ─────────────────────────────────────────────────

def test_admin_users_has_confirm_for_writes():
    """All 5 write actions must be gated behind window.confirm."""
    block = _admin_users_block(_src())
    # _runAction is the single chokepoint; it must call window.confirm.
    assert "window.confirm" in block, (
        "AdminUsersPage write helper must invoke window.confirm before each action"
    )
    # All 5 action helpers must specify a confirm message via the _runAction options.
    for label in ('Approve user', 'Reject user', 'Activate user',
                  'Deactivate user', 'Set role'):
        assert label in block, (
            f"AdminUsersPage must surface a confirm message containing {label!r}"
        )


# ── Refresh path ────────────────────────────────────────────────────────────

def test_admin_users_refresh_is_safe_get():
    """Refresh button calls loadUsers, which is a GET /auth/users only."""
    block = _admin_users_block(_src())
    assert "admin-users-refresh" in block
    # loadUsers must exist as an identifier and call GET /auth/users.
    assert "loadUsers" in block, "loadUsers helper must exist"
    assert "apiFetch('/auth/users')" in block, (
        "loadUsers must call GET /auth/users (no body, no method)"
    )
    # The refresh button must wire onClick={loadUsers}.
    assert "onClick={loadUsers}" in block, (
        "Refresh button must call loadUsers via onClick"
    )
    # No POST option may decorate the GET /auth/users call (anchored to that exact string).
    bad = re.search(r"apiFetch\(\s*'/auth/users'\s*,\s*\{[^}]*method", block)
    assert bad is None, (
        f"GET /auth/users must not carry a method option: {bad and bad.group(0)!r}"
    )


# ── Action button testids exist ─────────────────────────────────────────────

def test_admin_users_action_buttons_have_testids():
    block = _admin_users_block(_src())
    for tid in (
        'admin-users-btn-approve',
        'admin-users-btn-reject',
        'admin-users-btn-activate',
        'admin-users-btn-deactivate',
        'admin-users-select-role',
    ):
        assert tid in block, f"Missing testid: {tid}"


# ── Cross-check: MasterDataPage contracts remain green ──────────────────────

def test_master_data_page_does_not_call_auth_users_writes():
    """The existing MasterDataPage must NOT contain any /auth/users POST."""
    src = _src()
    start = src.find("function MasterDataPage(")
    assert start >= 0
    after = src[start:]
    end = len(after)
    for term in ("\nfunction ", "\n// ══"):
        idx = after.find(term, 1)
        if idx >= 0 and idx < end:
            end = idx
    md_block = after[:end]
    # No POST/PATCH/DELETE to /auth/users from MasterDataPage.
    for pat in (
        r"apiFetch\([^,]*/auth/users[^,]*,\s*\{\s*method:\s*'(POST|PATCH|DELETE)'",
        r"apiFetch\([^,]*/auth/users[^,]*,\s*\{\s*method:\s*\"(POST|PATCH|DELETE)\"",
    ):
        m = re.search(pat, md_block)
        assert m is None, (
            f"MasterDataPage must not write to /auth/users (B-MD1 isolation broken): {m and m.group(0)!r}"
        )


def test_admin_users_isolated_from_master_data_writes():
    """AdminUsersPage must not contain any master-data write endpoint."""
    block = _admin_users_block(_src())
    for path in (
        '/api/v1/suppliers', '/api/v1/hs-codes', '/api/v1/units',
        '/api/v1/product-local', '/api/v1/incoterms', '/api/v1/vat-config',
        '/api/v1/fx-rates', '/api/v1/carriers-config', '/api/v1/customer-master',
        '/api/v1/wfirma', '/api/v1/finance', '/api/v1/proforma',
    ):
        assert path not in block, (
            f"AdminUsersPage leaked into master-data territory: {path}"
        )
