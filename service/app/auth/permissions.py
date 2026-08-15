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

Consumers: /auth/me (routes_auth._safe_user), Slice 1 shell landing/nav/URL gates,
future require_permission helpers. Frontend must NOT invent a second catalogue —
it consumes permissions / allowed_pages / default_surface / default_page only.
"""
from __future__ import annotations

from typing import FrozenSet, Iterable, List, Mapping, Optional, Tuple

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

# Shell page id → catalogue *view* permission that unlocks nav + direct URL.
# Binder only — every value MUST be in PERMISSION_CATALOGUE (asserted below).
# Not a second catalogue; not a role matrix. Frontend must not re-encode this.
PAGE_VIEW_PERMISSION: Mapping[str, str] = {
    "dashboard": "dashboard.view",
    "inbox": "inbox.view",
    "shipments": "shipments.view",
    "dhl": "dhl.view",
    "proforma": "proforma.view",
    "documents": "documents.view",
    "accounting": "accounting.view",
    "supplier_invoice_review": "supplier_invoices.view",
    "inventory": "inventory.view",
    "reports": "reports.view",
    "admin": "system.settings.view",
    "admin_users": "users.view",
    "master": "master.view",
    "carriers": "carriers.view",
    "wfirma_setup": "wfirma.view",
    "api_status": "system.api_status.view",
    "diagnostics": "system.diagnostics.view",
    "automation": "system.automation.view",
    "intelligence": "intelligence.view",
    "coverage": "coverage.view",
    "shipping_ops": "shipping_ops.view",
}

# In-shell aliases that share a parent page's view permission.
PAGE_ALIASES: Mapping[str, str] = {
    "detail": "shipments",
    "proforma_detail": "proforma",
    # Cross-batch Prior Proforma Search (Screen C) — same module as Pro Forma list.
    "proforma_search": "proforma",
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
    # Credential mutation — admin-only (Carrier Master secret authority).
    # logistics has carriers.edit for non-secret config; NEVER grant these to logistics.
    "carriers.credentials.view",
    "carriers.credentials.write",
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


def allowed_pages_for_permissions(perms: Iterable[str]) -> List[str]:
    """Pages whose view permission is present — deny-by-default for unknown pages."""
    have = set(perms)
    return sorted(
        page for page, need in PAGE_VIEW_PERMISSION.items() if need in have
    )


def canonicalize_page_id(page: Optional[str]) -> str:
    """Map in-shell aliases to the page id used for access checks."""
    raw = (page or "").strip()
    if not raw:
        return ""
    return PAGE_ALIASES.get(raw, raw)


def page_is_allowed(page: Optional[str], allowed_pages: Iterable[str]) -> bool:
    canon = canonicalize_page_id(page)
    if not canon:
        return False
    return canon in set(allowed_pages)


def resolve_default_page(user: Mapping, allowed: Iterable[str]) -> str:
    """
    Prefer stored/role default_page when allowed; otherwise first allowed page.
    Safe fallback when landing is malformed or permissions exclude the default.
    """
    allowed_set = set(allowed)
    role = str(user.get("role") or "")
    _, page_default = landing_defaults_for_role(role)
    page = (user.get("default_page") or "").strip() or page_default
    if page not in VALID_PAGES:
        page = page_default
    if page in allowed_set:
        return page
    if page_default in allowed_set:
        return page_default
    if allowed_set:
        # Stable order: prefer ROLE_LANDING order via sorted allowed list
        return sorted(allowed_set)[0]
    return "dashboard"


def landing_url_for_user(user: Mapping) -> str:
    """
    Absolute path for post-login / already-logged-in redirects.
    default_surface and default_page stay separate; both drive the URL.
    """
    auth = build_authority_fields(user)
    surface = auth["default_surface"]
    page = auth["default_page"]
    if surface == "v1":
        # V1 shell entry remains the classic dashboard HTML (V1 frozen).
        return "/dashboard/dashboard.html"
    return f"/v2/{page}"


def build_authority_fields(user: Mapping) -> dict:
    """
    Canonical authority projection for /auth/me (and login user payload).

    Uses stored default_surface / default_page when present and valid;
    otherwise role landing defaults. Permissions always derived from role
    (Slice 0: no per-user permission overrides table).
    allowed_pages is derived from permissions via PAGE_VIEW_PERMISSION binder.
    """
    role = str(user.get("role") or "")
    perms = sorted(permissions_for_role(role))
    allowed = allowed_pages_for_permissions(perms)
    surf_default, page_default = landing_defaults_for_role(role)

    surface = (user.get("default_surface") or "").strip() or surf_default
    if surface not in VALID_SURFACES:
        surface = surf_default

    page = resolve_default_page(user, allowed)
    # Keep page_default as secondary signal when allowed empty (deny shell).
    if not allowed:
        page = page_default if page_default in VALID_PAGES else "dashboard"

    return {
        "permissions": perms,
        "allowed_pages": allowed,
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
assert not (_LOGISTICS & frozenset({
    "carriers.credentials.write",
    "carriers.credentials.view",
})), "Logistics must not receive carrier credential permissions"
assert not (_CRM & FISCAL_FINALIZE_PERMISSIONS), (
    "CRM must not receive fiscal finalize permissions"
)
assert not (_CRM & frozenset({
    "pz.prepare", "pz.create_draft", "pz.process",
    "dhl.execute", "inventory.execute", "users.admin",
    "system.settings.admin", "accounting.execute", "accounting.post",
})), "CRM bundle must stay narrow"
assert set(PAGE_VIEW_PERMISSION) == set(VALID_PAGES), (
    "PAGE_VIEW_PERMISSION keys must equal VALID_PAGES"
)
assert_permissions_subset_of_catalogue(PAGE_VIEW_PERMISSION.values())
for _alias_target in PAGE_ALIASES.values():
    assert _alias_target in PAGE_VIEW_PERMISSION, (
        f"PAGE_ALIASES target missing from PAGE_VIEW_PERMISSION: {_alias_target}"
    )
