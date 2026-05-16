"""B-MD3 — Master Data UI cleanup + disabled-state polish contracts.

Pins the cleanup invariants delivered by B-MD3 (MDOC-2026-05). These tests
guard against regressions:

1. The legacy `PendingPanel` reusable component is GONE from MasterDataPage.
2. No `<PendingPanel` usages anywhere in dashboard.html.
3. The hidden `master-pending-grid` testid anchor remains for back-compat
   tests but its contents are empty.
4. Every disabled <button> inside MasterDataPage carries a visible `title`
   attribute giving the operator a reason.
5. The "Backend pending" string count inside MasterDataPage is bounded to
   zero (no creep).
6. Live sidebar entities (Designs / HS / Units / Suppliers / FX / Carriers /
   Incoterms / VAT / Product-local / Clients / Customer Master / Users /
   Products) all carry `live: true`; Roles is `live: false` BY DESIGN
   (read-only explainer).
7. Designs form labels say "(soft)" / "(soft ref)" on cross-referenced fields.
8. Roles panel explicitly states the no-enforcement-engine state.
9. The disabled Invite-user chip in AdminUsersPage carries a clear reason.
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


def _master_block(src: str) -> str:
    start = src.find("function MasterDataPage(")
    assert start >= 0
    after = src[start:]
    end = len(after)
    for term in ("\nfunction ", "\n// ══"):
        idx = after.find(term, 1)
        if idx >= 0 and idx < end:
            end = idx
    return after[:end]


def _admin_users_block(src: str) -> str:
    start = src.find("function AdminUsersPage(")
    assert start >= 0
    after = src[start:]
    end = len(after)
    for term in ("\nfunction ", "\n// ══"):
        idx = after.find(term, 1)
        if idx >= 0 and idx < end:
            end = idx
    return after[:end]


# ── Orphan removal ──────────────────────────────────────────────────────────

def test_legacy_pendingpanel_component_is_removed():
    """The old reusable PendingPanel component was orphaned in B-MD2 (no
    callers remained). B-MD3 removes the dead definition entirely."""
    src = _src()
    md = _master_block(src)
    assert "const PendingPanel = ({" not in md, (
        "Legacy PendingPanel component must be removed from MasterDataPage"
    )
    # No JSX usage anywhere in the file either.
    assert "<PendingPanel " not in src and "<PendingPanel/>" not in src, (
        "No <PendingPanel> JSX usages should remain anywhere"
    )


def test_pending_grid_anchor_remains_empty():
    """The hidden test-compat anchors remain for back-compat tests, but
    the pending grid is empty by design after B-MD3."""
    src = _src()
    assert 'data-testid="master-pending-panel"' in src
    assert 'data-testid="master-pending-grid"' in src
    # Locate the master-pending-grid block and assert no children.
    idx = src.index('data-testid="master-pending-grid"')
    block = src[idx: idx + 600]
    # No data-pending="true" tiles should appear inside the grid.
    assert 'data-pending="true"' not in block, (
        "After B-MD3, the pending grid must be empty — all entities are live "
        "or explicitly read-only"
    )


# ── Disabled-state polish ───────────────────────────────────────────────────

def test_every_disabled_button_in_master_has_title_or_state_disabler():
    """Every <button ... disabled ...> inside MasterDataPage must carry a
    visible `title` attribute OR be a state-driven disabler (disabled={var}).
    Operators need an explanation when a button is greyed out.
    """
    md = _master_block(_src())
    # Find every <button ... disabled ...> block (capture the whole opening tag).
    # Use a non-greedy regex up to the closing '>' of the tag.
    pattern = re.compile(r"<button\b[^>]*\bdisabled[^>]*>", re.IGNORECASE)
    for m in pattern.finditer(md):
        tag = m.group(0)
        has_title = bool(re.search(r'\btitle\s*=', tag))
        # State-driven disabler pattern: disabled={someVar}
        is_state_disabler = bool(re.search(r"disabled\s*=\s*\{", tag))
        assert has_title or is_state_disabler, (
            f"Disabled button without title or state-disabler: {tag[:200]!r}"
        )


def test_no_backend_pending_strings_in_master_block():
    """B-MD3 removes every stale 'Backend pending' string from MasterDataPage.
    All entities are live or explicitly read-only.
    """
    md = _master_block(_src())
    assert "Backend pending" not in md, (
        "MasterDataPage must contain zero 'Backend pending' strings after B-MD3 — "
        "all entities are live or explicitly read-only (Roles)."
    )
    assert "backend pending" not in md.lower().replace("backend-pending", ""), (
        "Case-insensitive 'backend pending' must not appear in MasterDataPage"
    )


# ── Live entity count consistency ───────────────────────────────────────────

LIVE_ENTITIES = (
    "'clients'", "'users'", "'products'", "'customer_master'",
    "'designs'", "'fx_rates'", "'suppliers'", "'hs_codes'",
    "'units'", "'product_local'", "'carriers_config'", "'incoterms'",
    "'vat_config'",
)
EXPLAINER_ONLY_ENTITIES = ("'roles'",)


def test_live_entities_carry_live_true():
    """Each live entity sidebar entry inside the ENTITIES block has
    `live: true` within ~260 chars of its `id:` declaration.
    """
    src = _src()
    # Scope to the ENTITIES = [ ... ] block to disambiguate from the
    # error-rows config which also uses `id: 'users'` etc.
    entities_start = src.find("const ENTITIES = [")
    assert entities_start >= 0, "ENTITIES sidebar array must exist"
    entities_end = src.find("];", entities_start)
    entities_block = src[entities_start: entities_end + 2]
    for entity_id in LIVE_ENTITIES:
        m = entities_block.find(f"id: {entity_id}")
        assert m >= 0, f"Missing live entity id in ENTITIES block: {entity_id}"
        snippet = entities_block[m: m + 260]
        assert "live: true" in snippet, (
            f"{entity_id} must carry live: true in the ENTITIES sidebar entry"
        )


def test_roles_remains_live_false_by_design():
    """Roles is intentionally live: false — it has no list/count; the panel
    is a read-only explainer."""
    src = _src()
    m = src.find("id: 'roles'")
    assert m >= 0
    snippet = src[m: m + 140]
    assert "live: false" in snippet, (
        "Roles entity remains live: false (read-only explainer; not a list)"
    )


# ── Designs form labels (soft references) ──────────────────────────────────

def test_designs_form_labels_mark_soft_refs():
    """The Designs form must explicitly label product_ref / hs_code / unit
    as soft references so operators don't expect SQL FK behaviour."""
    md = _master_block(_src())
    # Find the designs form block.
    assert 'data-testid="master-designs-form"' in md
    form_start = md.index('data-testid="master-designs-form"')
    form = md[form_start: form_start + 7000]
    assert "(soft)" in form or "soft ref" in form.lower(), (
        "Designs form must label product_ref / hs_code / unit as soft references"
    )


# ── Roles explainer must state no-enforcement-engine ───────────────────────

def test_roles_explainer_states_no_enforcement_engine():
    """The Roles read-only panel must state explicitly that there is no
    permission enforcement engine today."""
    md = _master_block(_src())
    assert 'data-testid="master-roles-explainer"' in md
    idx = md.index('data-testid="master-roles-explainer"')
    block = md[idx: idx + 4000]
    # Must contain at least one explicit deferral / not-enforced phrase.
    block_lower = block.lower()
    enforcement_signal = (
        "deferred" in block_lower
        or "not yet" in block_lower
        or "not enforced" in block_lower
        or "do not yet have" in block_lower
    )
    assert enforcement_signal, (
        "Roles explainer must explicitly state the no-enforcement-engine state"
    )


def test_roles_explainer_matrix_lists_5_roles():
    md = _master_block(_src())
    idx = md.index('data-testid="master-roles-enforcement-matrix"')
    block = md[idx: idx + 4000]
    for role in ("admin", "accounts", "logistics", "auditor", "viewer"):
        assert f"'{role}'" in block, f"Roles matrix must list {role!r}"


# ── AdminUsersPage Invite-user disabled chip ───────────────────────────────

def test_admin_users_invite_disabled_chip_has_reason():
    """The disabled Invite-user chip on AdminUsersPage must carry visible
    explanation text covering its disabled state."""
    block = _admin_users_block(_src())
    assert 'data-testid="admin-users-invite-disabled"' in block
    idx = block.index('admin-users-invite-disabled')
    snippet = block[idx: idx + 1500]
    # Must include a `title` or visible reason text.
    has_title = "title=" in snippet
    has_visible_reason = ("Backend pending" in snippet
                          or "out of scope" in snippet.lower()
                          or "/auth/signup" in snippet)
    assert has_title or has_visible_reason, (
        "Invite-user disabled chip must carry a visible reason (title= or "
        "visible explanatory text)"
    )


# ── Stable testid hygiene for B-MD4 browser smoke ──────────────────────────

REQUIRED_TESTIDS_FOR_B_MD4 = (
    # Master Data shell
    "master-search",
    "master-refresh",
    # Live entities (write surface or read surface)
    "master-suppliers-panel",
    "master-hs-codes-panel",
    "master-units-panel",
    "master-product-local-panel",
    "master-incoterms-panel",
    "master-vat-config-panel",
    "master-fx-rates-panel",
    "master-carriers-config-panel",
    "master-designs-panel",
    "master-roles-panel",
    "master-roles-explainer",
    "master-roles-enforcement-matrix",
    "master-roles-btn-open-admin-users",
    "master-designs-btn-new",
    "master-designs-btn-save",
    "master-designs-btn-cancel",
    # Admin · Users
    "admin-users-page",
    "admin-users-refresh",
    "admin-users-search",
    "admin-users-invite-disabled",
)


def test_b_md4_required_testids_present():
    """B-MD4 (browser smoke) depends on a stable testid surface. This test
    pins every testid B-MD4 will reference."""
    src = _src()
    missing = [tid for tid in REQUIRED_TESTIDS_FOR_B_MD4
               if f'data-testid="{tid}"' not in src]
    assert missing == [], (
        f"B-MD4 browser smoke requires these testids to exist: {missing}"
    )


# ── No new write affordances ────────────────────────────────────────────────

def test_no_new_write_endpoints_in_master_data_page():
    """B-MD3 is UI cleanup only. No new write endpoints may appear in
    MasterDataPage. The existing allow-list (suppliers / hs-codes / units /
    product-local / incoterms / vat-config / fx-rates / carriers-config /
    designs / customer-master) is the complete set.
    """
    md = _master_block(_src())
    allowed_writes = (
        '/api/v1/suppliers', '/api/v1/hs-codes', '/api/v1/units',
        '/api/v1/product-local', '/api/v1/incoterms', '/api/v1/vat-config',
        '/api/v1/fx-rates', '/api/v1/carriers-config', '/api/v1/designs',
        '/api/v1/customer-master',
    )
    # Find every POST/PUT/DELETE write helper invocation.
    posts = re.findall(r"apiFetch\(([^,]+),\s*\{\s*method:\s*'(POST|PUT|DELETE|PATCH)'", md)
    helper_calls = re.findall(r"b5(?:Save|Delete)\('([^']+)'", md)
    for ep, _verb in posts:
        ep_str = ep.strip()
        if "basePath" in ep_str:
            continue
        assert any(a in ep_str for a in allowed_writes), (
            f"B-MD3 introduced a write to a non-allow-listed endpoint: {ep_str!r}"
        )
    for call_path in helper_calls:
        assert any(a in call_path for a in allowed_writes), (
            f"B-MD3 introduced a b5 helper call to non-allow-listed path: {call_path}"
        )


def test_no_auth_writes_inside_master_data_page():
    """MasterDataPage must never contain /auth/users writes (admin actions
    live in AdminUsersPage only)."""
    md = _master_block(_src())
    bad = re.search(
        r"apiFetch\([^,]*/auth/users[^,]*,\s*\{\s*method:\s*'(POST|PUT|PATCH|DELETE)'",
        md,
    )
    assert bad is None, (
        f"MasterDataPage must not write to /auth/users: {bad and bad.group(0)!r}"
    )
