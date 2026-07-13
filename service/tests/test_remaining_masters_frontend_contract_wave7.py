"""
test_remaining_masters_frontend_contract_wave7.py — EJ Dashboard Wave 7.

Source-contract pins for the remaining-master tabs. The V2 master page must
render from the server capability contract (not hardcoded prose), consume the
REAL roles enum (not the stale STATIC_ROLES), wire the existing CRUD + user-admin
actions, and keep the FX/VAT honesty disclaimers + the honest-unavailable states.
"""
from __future__ import annotations

from pathlib import Path

import pytest

V2 = Path(__file__).parents[1] / "app" / "static" / "v2"
MASTER = V2 / "master-page.jsx"
MRE = V2 / "master-record-edit.jsx"
PZAPI = V2 / "pz-api.js"


def _read(p: Path) -> str:
    if not p.exists():
        pytest.skip(f"{p.name} missing")
    return p.read_text(encoding="utf-8")


# ── Capability contract is the source of truth ───────────────────────────────

def test_master_page_consumes_capability_contract():
    src = _read(MASTER)
    assert "getMasterCapabilities" in src, "must fetch the capability contract"
    assert "capForEntity" in src, "must derive per-entity capability from the contract"


def test_crud_tabs_gated_on_capability_available():
    src = _read(MASTER)
    # New/Edit/Delete for the six CRUD domains gate on capForEntity.available
    assert "capForEntity && capForEntity.available" in src
    # delete only when the domain exposes a delete_route
    assert "capForEntity.delete_route" in src


# ── Roles: real enum from the contract, no fabricated matrix ─────────────────

def test_roles_render_from_contract_not_static_permission_matrix():
    src = _read(MASTER)
    # roles rows come from the contract values
    assert "roles.values" in src, "roles must render from the contract enum"
    # the fabricated admin/manager/operator matrix must NOT be the roles authority:
    # the honest roles columns are role + source (Authority), no create/edit/delete flags
    assert "'System-defined" in src or '"System-defined' in src
    # no invented 'manager'/'operator' role rows reintroduced as authority
    assert "Daily operations, limited master edits" not in src
    assert "Can edit master data, no deletions" not in src


# ── Honest disclaimers (FX reference-only / VAT not-overridden) ───────────────

def test_fx_and_vat_disclaimers_present():
    src = _read(MASTER)
    assert "NEVER read by the calculation engine" in src
    assert "not overridden" in src


# ── User admin actions wired; no edit/delete-user or role CRUD ────────────────

def test_user_admin_actions_wired():
    src = _read(MASTER)
    for w in ("approveUser", "rejectUser", "setUserRole", "activateUser", "deactivateUser"):
        assert w in src, f"user admin action {w} must be wired"


def test_set_role_goes_through_confirm():
    src = _read(MASTER)
    # role change must route through the shared confirm dialog action, not fire raw
    assert "set_role" in src, "setUserRole must route through the userActionConfirm 'set_role' path"


def test_no_user_edit_delete_or_role_crud():
    src = _read(MASTER)
    assert "editUser" not in src and "deleteUser" not in src
    assert "createRole" not in src and "deleteRole" not in src and "saveRole" not in src


# ── Generic edit modal uses domain wrappers only (no direct fetch) ───────────

def test_master_record_edit_uses_domain_wrappers():
    src = _read(MRE)
    for w in ("saveHsCode", "saveUnit", "saveIncoterm", "saveCarrierConfig",
              "createVatConfig", "saveVatConfig", "createFxRate", "saveFxRate"):
        assert w in src, f"edit modal must route {w}"
    assert "fetch(" not in src, "edit modal must not call fetch directly"
    # carrier credential fields never rendered as form-field keys (the words may
    # appear only inside the exclusion comment, never as a `key:` value)
    for banned in ("api_key", "api_secret", "password", "token"):
        assert f"'{banned}'" not in src and f'"{banned}"' not in src, \
            f"credential field {banned} must never be a rendered field key"


def test_capability_and_crud_wrappers_exist():
    src = _read(PZAPI)
    for m in ("getMasterCapabilities", "saveHsCode", "deleteHsCode",
              "createVatConfig", "createFxRate", "saveCarrierConfig",
              "approveUser", "setUserRole", "deactivateUser"):
        assert m in src, f"pz-api must expose {m}"
