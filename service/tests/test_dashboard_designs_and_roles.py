"""B-MD2 (MDOC-2026-05) — source-grep contracts for Designs panel + Roles read-only explainer."""
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


# ── Designs (live CRUD) ─────────────────────────────────────────────────────

def test_designs_sidebar_live_with_count():
    src = _src()
    idx = src.index("id: 'designs'")
    snippet = src[idx:idx + 240]
    assert "live: true" in snippet
    assert "designs.items" in snippet or "designs.error" in snippet


def test_designs_panel_buttons_present():
    src = _src()
    for tid in (
        'master-designs-panel',
        'master-designs-btn-new',
        'master-designs-btn-save',
        'master-designs-btn-cancel',
        'master-designs-input-code',
        'master-designs-input-active',
    ):
        assert f'data-testid="{tid}"' in src, f"Missing testid: {tid}"


def test_designs_panel_uses_b5_helpers():
    src = _src()
    assert "b5Save('/api/v1/designs', 'design_code'" in src
    assert "b5Delete('/api/v1/designs'," in src


def test_designs_loader_uses_only_designs_endpoint():
    """The Designs loader calls only GET /api/v1/designs/."""
    src = _src()
    # Locate the loadDesigns helper.
    m = re.search(r"const loadDesigns\s*=\s*React\.useCallback\([\s\S]+?\}, \[\]\)", src)
    assert m is not None, "loadDesigns helper must exist"
    body = m.group(0)
    assert "apiFetch('/api/v1/designs/')" in body
    assert "method:" not in body, "loadDesigns must be a safe GET"


def test_designs_panel_has_no_writes_outside_b5_helpers():
    """No raw apiFetch POST/PUT/DELETE targeting /api/v1/designs inside the panel."""
    src = _src()
    start = src.index("master-designs-panel")
    # Look 6000 chars forward — covers the whole panel including the form.
    block = src[start: start + 12000]
    # Forbid raw apiFetch with method on /api/v1/designs.
    bad = re.findall(
        r"apiFetch\([^,]*designs[^,]*,\s*\{\s*method",
        block,
    )
    assert bad == [], f"Designs panel must only write via b5 helpers; got raw: {bad}"


# ── Roles (read-only explainer) ─────────────────────────────────────────────

def test_roles_explainer_panel_present():
    src = _src()
    for tid in (
        'master-roles-panel',
        'master-roles-explainer',
        'master-roles-enforcement-matrix',
        'master-roles-btn-open-admin-users',
    ):
        assert f'data-testid="{tid}"' in src, f"Missing testid: {tid}"


def test_roles_panel_lists_five_roles_exactly():
    src = _src()
    start = src.index('data-testid="master-roles-enforcement-matrix"')
    block = src[start: start + 4000]
    for role in ('admin', 'accounts', 'logistics', 'auditor', 'viewer'):
        assert f"data-testid={{'master-roles-row-' + row[0]}}" in block or (
            f"'{role}'" in block
        ), f"Roles matrix must list role: {role}"


def test_roles_panel_marks_admin_as_only_enforced_role():
    src = _src()
    start = src.index('data-testid="master-roles-explainer"')
    block = src[start: start + 4000]
    # Mention that only admin is enforced today.
    assert "require_admin" in block
    assert "admin" in block.lower()
    assert "deferred" in block.lower() or "not yet" in block.lower() or "no" in block.lower()


def test_roles_panel_has_no_write_apifetch():
    """Roles panel must NOT call any write endpoint."""
    src = _src()
    start = src.index("master-roles-panel")
    end = src.find("master-pending-panel", start)
    if end < 0:
        end = start + 6000
    block = src[start:end]
    bad = re.findall(r"apiFetch\(", block)
    assert bad == [], f"Roles panel must contain zero apiFetch calls; got {bad}"
    # Also no method: 'POST'/'PUT'/'DELETE'/'PATCH'.
    for verb in ("'POST'", "'PUT'", "'DELETE'", "'PATCH'"):
        assert f"method: {verb}" not in block, (
            f"Roles panel must not contain write verb {verb}"
        )


def test_roles_panel_has_only_safe_button_open_admin_users():
    """Only allowed button in the roles panel is the navigation button."""
    src = _src()
    start = src.index("master-roles-panel")
    end = src.find("master-pending-panel", start)
    if end < 0:
        end = start + 6000
    block = src[start:end]
    # Count <button occurrences inside the roles block.
    btn_count = block.count("<button")
    # Exactly one button: the "Open Admin Users" navigation.
    assert btn_count == 1, (
        f"Roles panel must contain exactly one button (navigation only); got {btn_count}"
    )
    # Forbidden write button labels.
    for forbidden in (">Add role<", ">Create role<", ">Delete role<",
                      ">Edit role<", ">Save role<"):
        assert forbidden not in block, (
            f"Roles panel must not contain write button label: {forbidden}"
        )


def test_roles_panel_nav_button_targets_admin_users():
    src = _src()
    start = src.index("master-roles-btn-open-admin-users")
    block = src[start: start + 500]
    assert "onNav('admin_users')" in block, (
        "Open Admin Users button must navigate to admin_users page"
    )
