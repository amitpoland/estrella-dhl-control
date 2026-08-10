"""
Canonical RBAC permission catalogue + role → permission map (Slice 0).

Authority rules (frozen charter RBAC Authority Consolidation):
- ONE catalogue lives here. Do not duplicate in frontend or a second module.
- Roles are named in auth.service.ROLES; this module maps each role to explicit
  module.action permissions (never a literal "Full" token).
- master_* stays isolated: only master.* (and related master client) grants.
- API-key is machine authentication elsewhere — not modeled as a human role here.
- Logistics must NOT receive fiscal finalize / export / approve / convert.
- CRM is narrow (customer/docs/inbox oriented).

Consumers: /auth/me (routes_auth._safe_user), future require_permission helpers,
Admin Users UI (role dropdown only — no second permission admin page in Slice 0).
"""
from __future__ import annotations

from typing import FrozenSet, Iterable, Mapping, Optional, Tuple

# ── Surfaces / pages (landing authority) ─────────────────────────────────────

VALID_SURFACES: FrozenSet[str] = frozenset({"v1", "v2"})

# Page ids that may appear as default_page (V1/V2 shell slugs).
VALID_PAGES: FrozenSet[str] = frozenset({
    "dashboard",
    "inbox",
    "shipments",
    "dhl",
    "proforma",
    "documents",
    "accounting",
    "supplier_invoice_review",
    "inventory",
    "reports",
    "admin",
    "admin_users",
    "master",
    "carriers",
    "wfirma_setup",
    "api_status",
    "diagnostics",
    "automation",
    "intelligence",
    "coverage",
    "shipping_ops",
})

# role → (default_surface, default_page)
ROLE_LANDING: Mapping[str, Tuple[str, str]] = {
    "admin": ("v2", "dashboard"),
    "accounts": ("v2", "accounting"),
    "logistics": ("v2", "shipments"),
    "crm": ("v2", "inbox"),
    "auditor": ("v2", "dashboard"),
    "viewer": ("v2", "dashboard"),
    "master_admin": ("v2", "master"),
    "master_editor": ("v2", "master"),
    "master_viewer": ("v2", "master"),
}

# ── Explicit permission catalogue (module.action) ────────────────────────────
# Append-only for Slice 0+. Renames require charter amendment.

PERMISSION_CATALOGUE: FrozenSet[str] = frozenset({
    # Shell / system
    "dashboard.view",
    "inbox.view",
    "inbox.act",
    "inbox.act_crm",
    "system.settings.view",
    "system.settings.admin",
    "system.diagnostics.view",
    "system.api_status.view",
    "system.automation.view",
    "system.automation.execute",
    "users.view",
    "users.admin",
    "reports.view",
    "reports.financial",
    "reports.logistics",
    "reports.crm",
    "intelligence.view",
    "coverage.view",
    "shipping_ops.view",
    # Shipments / DHL / AWB
    "shipments.view",
    "shipments.create",
    "shipments.edit",
    "dhl.view",
    "dhl.execute",
    "dhl.resolve",
    "awb.create",
    "awb.label",
    "awb.docs_fetch",
    # Documents
    "documents.view",
    "documents.create",
    "documents.edit",
    "documents.upload",
    "documents.download",
    "documents.execute",
    "documents.approve",
    "documents.delete",
    "documents.admin",
    # Proforma (C2 split)
    "proforma.view",
    "proforma.prepare",
    "proforma.create",
    "proforma.edit",
    "proforma.approve",
    "proforma.convert",
    "proforma.delete",
    # PZ (C2 split)
    "pz.view",
    "pz.prepare",
    "pz.create_draft",
    "pz.finalize",
    "pz.export_wfirma",
    "pz.process",
    # Accounting / wFirma
    "accounting.view",
    "accounting.execute",
    "accounting.post",
    "wfirma.view",
    "wfirma.goods.write",
    "wfirma.customers.write",
    "wfirma.reservation.create",
    "supplier_invoices.view",
    "supplier_invoices.upload",
    "supplier_invoices.edit",
    # Inventory / warehouse
    "inventory.view",
    "inventory.execute",
    "inventory.correct",
    "warehouse.scan",
    "warehouse.receipt.confirm",
    # Master / carriers
    "master.view",
    "master.edit",
    "master.admin",
    "master.clients.view",
    "master.clients.edit",
    "carriers.view",
    "carriers.edit",
})

# Fiscal finalization verbs — Logistics must never receive these by default (C2).
FISCAL_FINALIZE_PERMISSIONS: FrozenSet[str] = frozenset({
    "pz.finalize",
    "pz.export_wfirma",
    "proforma.approve",
    "proforma.convert",
    "wfirma.goods.write",
    "wfirma.customers.write",
    "wfirma.reservation.create",
    "accounting.post",
})

# ── Role → permission bundles (deny-by-default) ──────────────────────────────

_ADMIN: FrozenSet[str] = frozenset(PERMISSION_CATALOGUE)  # explicit expansion of every verb

_ACCOUNTS: FrozenSet[str] = frozenset({
    "dashboard.view",
    "inbox.view",
    "inbox.act",
    "shipments.view",
    "dhl.view",
    "documents.view",
    "documents.download",
    "proforma.view",
    "proforma.prepare",
    "proforma.create",
    "proforma.edit",
    "proforma.approve",
    "proforma.convert",
    "pz.view",
    "pz.prepare",
    "pz.create_draft",
    "pz.finalize",
    "pz.export_wfirma",
    "pz.process",
    "accounting.view",
    "accounting.execute",
    "accounting.post",
    "wfirma.view",
    "wfirma.goods.write",
    "wfirma.customers.write",
    "wfirma.reservation.create",
    "supplier_invoices.view",
    "supplier_invoices.upload",
    "supplier_invoices.edit",
    "inventory.view",
    "reports.view",
    "reports.financial",
    "master.view",
    "master.clients.view",
    "master.clients.edit",
    "carriers.view",
    "system.automation.view",
    "intelligence.view",
})

_LOGISTICS: FrozenSet[str] = frozenset({
    "dashboard.view",
    "inbox.view",
    "inbox.act",
    "shipments.view",
    "shipments.create",
    "shipments.edit",
    "dhl.view",
    "dhl.execute",
    "awb.create",
    "awb.label",
    "awb.docs_fetch",
    "documents.view",
    "documents.upload",
    "documents.download",
    "documents.execute",
    "proforma.view",
    "proforma.prepare",
    "proforma.create",
    "proforma.edit",
    # NO proforma.approve / proforma.convert (C2)
    "pz.view",
    "pz.prepare",
    "pz.create_draft",
    "pz.process",
    # NO pz.finalize / pz.export_wfirma (C2)
    "accounting.view",  # limited view only — no execute/post
    "wfirma.view",
    "supplier_invoices.view",
    "supplier_invoices.upload",
    "inventory.view",
    "inventory.execute",
    # NO inventory.correct
    "warehouse.scan",
    "warehouse.receipt.confirm",
    "reports.view",
    "reports.logistics",
    "master.view",
    "master.clients.view",
    "carriers.view",
    "carriers.edit",
    "system.api_status.view",
    "system.automation.view",
    "system.automation.execute",
    "intelligence.view",
    "coverage.view",
    "shipping_ops.view",
})

_CRM: FrozenSet[str] = frozenset({
    "dashboard.view",
    "inbox.view",
    "inbox.act_crm",
    "shipments.view",
    "documents.view",
    "documents.download",
    # documents.upload intentionally OFF by default
    "proforma.view",
    "reports.view",
    "reports.crm",
    "master.view",
    "master.clients.view",
    # master.clients.edit OFF by default (opt-in)
})

_AUDITOR: FrozenSet[str] = frozenset({
    "dashboard.view",
    "inbox.view",
    "shipments.view",
    "dhl.view",
    "documents.view",
    "documents.download",
    "proforma.view",
    "pz.view",
    "accounting.view",
    "wfirma.view",
    "supplier_invoices.view",
    "inventory.view",
    "reports.view",
    "reports.financial",
    "reports.logistics",
    "reports.crm",
    "master.view",
    "master.clients.view",
    "carriers.view",
    "system.diagnostics.view",
    "system.api_status.view",
    "system.automation.view",
    "intelligence.view",
    "coverage.view",
    "shipping_ops.view",
})

_VIEWER: FrozenSet[str] = frozenset({
    "dashboard.view",
    "inbox.view",
    "shipments.view",
    "dhl.view",
    "documents.view",
    "proforma.view",
    "pz.view",
    "inventory.view",
    "reports.view",
})

_MASTER_ADMIN: FrozenSet[str] = frozenset({
    "master.view",
    "master.edit",
    "master.admin",
    "master.clients.view",
    "master.clients.edit",
})

_MASTER_EDITOR: FrozenSet[str] = frozenset({
    "master.view",
    "master.edit",
    "master.clients.view",
    "master.clients.edit",
})

_MASTER_VIEWER: FrozenSet[str] = frozenset({
    "master.view",
    "master.clients.view",
})

# THE single role→permission map. Architecture tests pin uniqueness.
ROLE_PERMISSIONS: Mapping[str, FrozenSet[str]] = {
    "admin": _ADMIN,
    "accounts": _ACCOUNTS,
    "logistics": _LOGISTICS,
    "crm": _CRM,
    "auditor": _AUDITOR,
    "viewer": _VIEWER,
    "master_admin": _MASTER_ADMIN,
    "master_editor": _MASTER_EDITOR,
    "master_viewer": _MASTER_VIEWER,
}


def permissions_for_role(role: Optional[str]) -> FrozenSet[str]:
    """Deny-by-default: unknown / empty role → empty set."""
    if not role:
        return frozenset()
    return ROLE_PERMISSIONS.get(str(role), frozenset())


def landing_defaults_for_role(role: Optional[str]) -> Tuple[str, str]:
    """Return (default_surface, default_page) for a role; safe fallback for unknown."""
    if role and role in ROLE_LANDING:
        return ROLE_LANDING[role]
    return ("v2", "dashboard")


def has_permission(role: Optional[str], permission: str) -> bool:
    return permission in permissions_for_role(role)


def assert_permissions_subset_of_catalogue(
    perms: Iterable[str],
) -> None:
    unknown = set(perms) - PERMISSION_CATALOGUE
    if unknown:
        raise ValueError(f"Permissions not in catalogue: {sorted(unknown)}")


def build_authority_fields(user: Mapping) -> dict:
    """
    Canonical authority projection for /auth/me (and login user payload).

    Uses stored default_surface / default_page when present and valid;
    otherwise role landing defaults. Permissions always derived from role
    (Slice 0: no per-user permission overrides table).
    """
    role = str(user.get("role") or "")
    perms = sorted(permissions_for_role(role))
    surf_default, page_default = landing_defaults_for_role(role)

    surface = (user.get("default_surface") or "").strip() or surf_default
    if surface not in VALID_SURFACES:
        surface = surf_default

    page = (user.get("default_page") or "").strip() or page_default
    if page not in VALID_PAGES:
        page = page_default

    return {
        "permissions": perms,
        "default_surface": surface,
        "default_page": page,
    }


# Validate bundles at import time (fail fast on catalogue drift).
for _role, _bundle in ROLE_PERMISSIONS.items():
    assert_permissions_subset_of_catalogue(_bundle)
assert FISCAL_FINALIZE_PERMISSIONS <= PERMISSION_CATALOGUE
assert not (_LOGISTICS & FISCAL_FINALIZE_PERMISSIONS), (
    "Logistics must not receive fiscal finalize permissions"
)
assert not (_CRM & FISCAL_FINALIZE_PERMISSIONS), (
    "CRM must not receive fiscal finalize permissions"
)
assert not (_CRM & frozenset({
    "pz.prepare", "pz.create_draft", "pz.process",
    "dhl.execute", "inventory.execute", "users.admin",
    "system.settings.admin", "accounting.execute", "accounting.post",
})), "CRM bundle must stay narrow"
