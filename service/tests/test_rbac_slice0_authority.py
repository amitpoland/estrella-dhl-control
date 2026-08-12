"""
RBAC Slice 0 — catalogue, role map, /auth/me authority, architecture uniqueness.

No Tier-0 route tightening in this suite — fiscal GAPs remain documented debt.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.auth.permissions import (
    FISCAL_FINALIZE_PERMISSIONS,
    PERMISSION_CATALOGUE,
    ROLE_LANDING,
    ROLE_PERMISSIONS,
    build_authority_fields,
    has_permission,
    landing_defaults_for_role,
    permissions_for_role,
)
from app.auth.service import ROLES

_REPO = Path(__file__).resolve().parents[2]
_APP = _REPO / "service" / "app"
_AUTH = _APP / "auth"
_STATIC = _APP / "static"


@pytest.fixture()
def auth_db(monkeypatch, tmp_path):
    """Isolated users.db for migration / role-change safety proofs."""
    from app.core.config import settings

    db_path = tmp_path / "users.db"
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "auth_db_path", str(db_path))
    from app.auth.database import init_db
    init_db(db_path)
    return db_path


# ── Matrix / catalogue ───────────────────────────────────────────────────────

def test_roles_nine_including_crm_and_master_isolation_order():
    assert ROLES == (
        "admin",
        "accounts",
        "logistics",
        "crm",
        "auditor",
        "viewer",
        "master_admin",
        "master_editor",
        "master_viewer",
    )


def test_every_role_has_permission_bundle_and_landing():
    for role in ROLES:
        assert role in ROLE_PERMISSIONS, f"missing ROLE_PERMISSIONS[{role}]"
        assert role in ROLE_LANDING, f"missing ROLE_LANDING[{role}]"
        assert permissions_for_role(role) <= PERMISSION_CATALOGUE


def test_unknown_role_deny_by_default():
    assert permissions_for_role("no_such_role") == frozenset()
    assert permissions_for_role(None) == frozenset()
    assert permissions_for_role("") == frozenset()
    assert not has_permission("ghost", "dashboard.view")


def test_logistics_has_no_fiscal_finalize_permissions():
    logistics = permissions_for_role("logistics")
    leaked = logistics & FISCAL_FINALIZE_PERMISSIONS
    assert not leaked, f"Logistics must not get fiscal finalize perms: {sorted(leaked)}"
    for p in (
        "pz.finalize",
        "pz.export_wfirma",
        "proforma.approve",
        "proforma.convert",
        "wfirma.goods.write",
        "accounting.post",
    ):
        assert p not in logistics


def test_crm_bundle_is_narrow():
    crm = permissions_for_role("crm")
    assert "inbox.act_crm" in crm
    assert "documents.download" in crm
    assert "proforma.view" in crm
    assert "master.clients.view" in crm
    forbidden = {
        "pz.prepare",
        "pz.create_draft",
        "pz.process",
        "pz.finalize",
        "pz.export_wfirma",
        "dhl.execute",
        "awb.create",
        "inventory.execute",
        "wfirma.goods.write",
        "accounting.post",
        "users.admin",
        "system.settings.admin",
        "documents.upload",  # opt-in only
        "master.clients.edit",  # opt-in only
    }
    assert not (crm & forbidden), f"CRM too wide: {sorted(crm & forbidden)}"


def test_master_roles_isolated_from_legacy_ops():
    legacy_ops = frozenset({
        "shipments.create",
        "dhl.execute",
        "awb.create",
        "pz.export_wfirma",
        "proforma.convert",
        "accounting.post",
        "inventory.execute",
        "users.admin",
    })
    for role in ("master_admin", "master_editor", "master_viewer"):
        leaked = permissions_for_role(role) & legacy_ops
        assert not leaked, f"{role} leaked legacy ops: {sorted(leaked)}"
        assert "master.view" in permissions_for_role(role)


def test_landing_defaults_separate_surface_and_page():
    assert landing_defaults_for_role("logistics") == ("v2", "shipments")
    assert landing_defaults_for_role("accounts") == ("v2", "accounting")
    assert landing_defaults_for_role("crm") == ("v2", "inbox")
    assert landing_defaults_for_role("admin") == ("v2", "dashboard")
    assert landing_defaults_for_role("master_admin") == ("v2", "master")


def test_build_authority_fields_uses_stored_landing_when_valid():
    payload = build_authority_fields({
        "role": "logistics",
        "default_surface": "v1",
        "default_page": "inbox",
    })
    assert payload["default_surface"] == "v1"
    assert payload["default_page"] == "inbox"
    assert "shipments.view" in payload["permissions"]
    assert "pz.export_wfirma" not in payload["permissions"]


def test_build_authority_fields_falls_back_on_invalid_landing():
    payload = build_authority_fields({
        "role": "accounts",
        "default_surface": "mobile",
        "default_page": "not-a-page",
    })
    assert payload["default_surface"] == "v2"
    assert payload["default_page"] == "accounting"


# ── Architecture uniqueness ─────────────────────────────────────────────────

def test_single_canonical_role_permission_map():
    """ROLE_PERMISSIONS must be defined only in auth/permissions.py."""
    hits = []
    for path in _APP.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "ROLE_PERMISSIONS" in text:
            hits.append(path.relative_to(_REPO).as_posix())
    assert hits, "ROLE_PERMISSIONS missing"
    # Definition assignment only in permissions.py; others may import the name.
    defs = []
    for path in _AUTH.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"^ROLE_PERMISSIONS\s*[:=]", text, re.MULTILINE):
            defs.append(path.name)
    assert defs == ["permissions.py"], f"ROLE_PERMISSIONS defined in {defs}"


def test_auth_me_consumes_build_authority_fields():
    src = (_APP / "api" / "routes_auth.py").read_text(encoding="utf-8")
    assert "build_authority_fields" in src
    assert "from ..auth.permissions import build_authority_fields" in src
    assert "out.update(build_authority_fields(u))" in src
    # /auth/me still returns _safe_user
    assert re.search(r'async def me\([\s\S]*?return _safe_user\(user\)', src)


def test_frontend_does_not_define_fiscal_permission_matrix():
    """No second fiscal permission catalogue in JS/JSX/HTML."""
    forbidden_patterns = (
        r"ROLE_PERMISSIONS\s*=",
        r"FISCAL_FINALIZE_PERMISSIONS\s*=",
        r"pz\.export_wfirma",
        r"proforma\.convert",
    )
    offenders = []
    for path in list(_STATIC.rglob("*.jsx")) + list(_STATIC.rglob("*.js")) + list(_STATIC.rglob("*.html")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for pat in forbidden_patterns:
            if re.search(pat, text):
                offenders.append(f"{path.relative_to(_REPO).as_posix()}: {pat}")
    assert not offenders, "Frontend must not own fiscal permission matrix:\n" + "\n".join(offenders)


def test_no_new_duplicate_users_or_rbac_admin_page():
    """Slice 0 must not introduce a parallel Users/RBAC administration page."""
    banned_names = (
        "rbac-admin.html",
        "rbac-users.html",
        "users-rbac.html",
        "permission-admin.html",
        "v2/rbac-page.jsx",
        "v2/users-admin-page.jsx",
    )
    for name in banned_names:
        assert not (_STATIC / name).exists(), f"Forbidden duplicate page created: {name}"
    # Canonical surfaces still present
    assert (_STATIC / "dashboard.html").exists()
    assert (_STATIC / "admin-users.html").exists()
    assert (_STATIC / "v2" / "master-page.jsx").exists()


def test_master_page_remains_presentation_surface():
    src = (_STATIC / "v2" / "master-page.jsx").read_text(encoding="utf-8")
    assert "STATIC_ROLES_NAMES" in src
    assert "'crm'" in src or '"crm"' in src
    # Fake ROLE_MATRIX may still exist as LEGACY simulator — must not be the
    # fiscal catalogue (architecture test above). Master Users write still disabled.
    assert "USERS_WRITE_DISABLED_REASON" in src


def test_admin_users_roles_dropdown_matches_backend_roles():
    src = (_STATIC / "dashboard.html").read_text(encoding="utf-8")
    m = re.search(r"const\s+ADMIN_USERS_ROLES\s*=\s*\[([^\]]+)\]", src)
    assert m
    items = [s.strip().strip("'\"") for s in m.group(1).split(",") if s.strip()]
    assert items == list(ROLES)


def test_slice0_does_not_tighten_tier0_pz_export_gate():
    """Historical Slice 0 pin — superseded by Slice 2d Gate 3.

    ``pz_create`` must now stack ``pz.export_wfirma`` (logistics denied).
    """
    src = (_APP / "api" / "routes_wfirma.py").read_text(encoding="utf-8")
    assert "pz_create" in src
    assert 'require_permission("pz.export_wfirma")' in src
    assert "require_api_key" in src[:2500]


def test_slice0_catalogue_anticipates_require_permission_helper():
    """Slice 0 deferred the helper; Phase 2 owns ``require_permission``.

    Keep the catalogue/docs pin: permissions.py still names the future helper
    contract. The implementation lives in auth.dependencies (Phase 2).
    """
    perms = (_AUTH / "permissions.py").read_text(encoding="utf-8")
    assert "future require_permission helpers" in perms
    deps = (_AUTH / "dependencies.py").read_text(encoding="utf-8")
    assert "def require_permission" in deps
    assert "has_permission" in deps


# ── Migration / backfill safety ──────────────────────────────────────────────

def test_existing_user_keeps_role_and_gets_deterministic_landing(auth_db):
    """
    Existing users retain their role. Landing defaults are filled from the role
    map only — permissions are derived from role and never exceed that bundle.
    """
    from app.auth.database import get_db, init_db
    from app.auth.service import create_user, get_user_by_id

    user = create_user(
        full_name="Logistics Op",
        company_name="EJ",
        email="logistics.op@example.com",
        password="Test1234!",
        role="logistics",
        is_approved=True,
    )
    assert user["role"] == "logistics"
    assert user["default_surface"] == "v2"
    assert user["default_page"] == "shipments"

    # Simulate pre-Slice-0 row: wipe landing, re-run init/backfill, role must stay.
    with get_db() as con:
        con.execute(
            "UPDATE users SET default_surface='', default_page='' WHERE id=?",
            (user["id"],),
        )
    init_db(auth_db)
    refreshed = get_user_by_id(user["id"])
    assert refreshed["role"] == "logistics"
    assert refreshed["email"] == "logistics.op@example.com"
    assert refreshed["full_name"] == "Logistics Op"
    assert refreshed["default_surface"] == "v2"
    assert refreshed["default_page"] == "shipments"

    # Permissions equal the logistics bundle — no silent widen.
    auth = build_authority_fields(refreshed)
    assert set(auth["permissions"]) == set(permissions_for_role("logistics"))
    assert "pz.export_wfirma" not in auth["permissions"]
    assert "proforma.convert" not in auth["permissions"]


def test_role_change_updates_landing_without_rewriting_unrelated_state(auth_db):
    """set_user_role updates role + landing defaults only — not identity/approval."""
    from app.auth.service import create_user, get_user_by_id, set_user_role

    user = create_user(
        full_name="Keep My Name",
        company_name="Keep Co",
        email="keep.state@example.com",
        password="Test1234!",
        role="viewer",
        is_approved=True,
        email_verified=True,
    )
    before = get_user_by_id(user["id"])
    assert before["default_page"] == "dashboard"

    set_user_role(user["id"], "accounts")
    after = get_user_by_id(user["id"])

    assert after["role"] == "accounts"
    assert after["default_surface"] == "v2"
    assert after["default_page"] == "accounting"
    # Unrelated state preserved
    assert after["full_name"] == "Keep My Name"
    assert after["company_name"] == "Keep Co"
    assert after["email"] == "keep.state@example.com"
    assert after["password_hash"] == before["password_hash"]
    assert bool(after["is_approved"]) is True
    assert bool(after["is_active"]) is True
    assert bool(after["email_verified"]) is True
    assert after["approval_status"] == before["approval_status"]
    assert after["created_at"] == before["created_at"]

    auth = build_authority_fields(after)
    assert set(auth["permissions"]) == set(permissions_for_role("accounts"))
    assert "pz.export_wfirma" in auth["permissions"]  # accounts may finalize
    assert "users.admin" not in auth["permissions"]
