"""
RBAC Slice 1 — login / V2 nav / direct URL consume /auth/me authority.

No Tier-0 fiscal API tightening. Master ROLE_MATRIX left in place.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.auth.permissions import (
    PAGE_ALIASES,
    PAGE_VIEW_PERMISSION,
    ROLE_LANDING,
    VALID_PAGES,
    allowed_pages_for_permissions,
    build_authority_fields,
    landing_url_for_user,
    page_is_allowed,
    permissions_for_role,
)
from app.auth.service import ROLES

_REPO = Path(__file__).resolve().parents[2]
_APP = _REPO / "service" / "app"
_STATIC = _APP / "static"


@pytest.fixture()
def auth_db(monkeypatch, tmp_path):
    from app.core.config import settings

    db_path = tmp_path / "users.db"
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "auth_db_path", str(db_path))
    from app.auth.database import init_db

    init_db(db_path)
    return db_path


# ── Page binder / landing (backend sole authority) ─────────────────────────────

def test_page_view_permission_covers_all_valid_pages():
    assert set(PAGE_VIEW_PERMISSION) == set(VALID_PAGES)
    for page, perm in PAGE_VIEW_PERMISSION.items():
        assert "." in perm


def test_allowed_pages_for_crm_hides_fiscal_and_inventory():
    allowed = set(allowed_pages_for_permissions(permissions_for_role("crm")))
    assert "inbox" in allowed
    assert "shipments" in allowed
    assert "accounting" not in allowed
    assert "inventory" not in allowed
    assert "dhl" not in allowed
    assert "admin" not in allowed


def test_allowed_pages_for_master_viewer_is_master_only():
    allowed = set(allowed_pages_for_permissions(permissions_for_role("master_viewer")))
    assert allowed == {"master"}


def test_role_landing_urls_consume_surface_and_page_separately():
    assert landing_url_for_user({"role": "logistics"}) == "/v2/shipments"
    assert landing_url_for_user({"role": "accounts"}) == "/v2/accounting"
    assert landing_url_for_user({"role": "crm"}) == "/v2/inbox"
    assert landing_url_for_user({"role": "master_admin"}) == "/v2/master"
    assert landing_url_for_user({
        "role": "logistics",
        "default_surface": "v1",
        "default_page": "shipments",
    }) == "/dashboard/dashboard.html"


def test_default_page_falls_back_when_stored_page_not_allowed():
    """Stored landing outside permissions → resolve to an allowed page."""
    auth = build_authority_fields({
        "role": "crm",
        "default_surface": "v2",
        "default_page": "accounting",  # CRM has no accounting.view
    })
    assert auth["default_page"] != "accounting"
    assert auth["default_page"] in auth["allowed_pages"]
    assert "inbox" in auth["allowed_pages"]


def test_build_authority_includes_allowed_pages():
    auth = build_authority_fields({"role": "viewer"})
    assert "allowed_pages" in auth
    assert "permissions" in auth
    assert auth["default_surface"] == "v2"
    assert auth["default_page"] == "dashboard"
    assert set(auth["allowed_pages"]) <= set(VALID_PAGES)


def test_page_aliases_share_parent_permission():
    assert PAGE_ALIASES["detail"] == "shipments"
    assert PAGE_ALIASES["proforma_detail"] == "proforma"
    allowed = allowed_pages_for_permissions(permissions_for_role("logistics"))
    assert page_is_allowed("detail", allowed)
    assert page_is_allowed("proforma_detail", allowed)
    crm_allowed = allowed_pages_for_permissions(permissions_for_role("crm"))
    assert not page_is_allowed("detail", crm_allowed) or "shipments" in crm_allowed
    # CRM has shipments.view → detail allowed
    assert page_is_allowed("detail", crm_allowed)


# ── Login / main.py consumers ────────────────────────────────────────────────

def test_login_html_uses_authority_landing_not_hard_dashboard():
    src = (_STATIC / "login.html").read_text(encoding="utf-8")
    assert "default_surface" in src
    assert "default_page" in src
    assert "/v2/" in src
    # Must not be the sole hard redirect anymore
    assert not re.search(
        r"window\.location\.href\s*=\s*['\"]/dashboard['\"]\s*;",
        src,
    )


def test_main_py_landing_redirect_helper_present():
    src = (_APP / "main.py").read_text(encoding="utf-8")
    assert "landing_url_for_user" in src
    assert "_landing_redirect" in src
    assert 'RedirectResponse(url="/dashboard/dashboard.html")' not in src or "v1" in src


def test_v2_shell_fetches_auth_me_and_filters_nav():
    idx = (_STATIC / "v2" / "index.html").read_text(encoding="utf-8")
    assert "authority-consumer.js" in idx
    assert "AuthorityConsumer" in idx
    assert "allowed_pages" in idx or "allowedPages" in idx
    assert "applyAuthorityGate" in idx
    comps = (_STATIC / "v2" / "components.jsx").read_text(encoding="utf-8")
    assert "filterNavTreeByAllowedPages" in comps
    assert "allowedPages" in comps
    ac = (_STATIC / "v2" / "authority-consumer.js").read_text(encoding="utf-8")
    assert "fetchAuthMe" in ac
    assert "pageIsAllowed" in ac
    assert "ROLE_PERMISSIONS" not in ac
    assert "PERMISSION_CATALOGUE" not in ac


def test_master_role_matrix_preserved():
    src = (_STATIC / "v2" / "master-page.jsx").read_text(encoding="utf-8")
    assert "const ROLE_MATRIX" in src
    assert "admin/manager/operator/viewer" in src or "ROLE_MATRIX" in src


def test_no_frontend_role_permission_catalogue():
    """FE must not redefine ROLE_PERMISSIONS / PERMISSION_CATALOGUE."""
    for path in _STATIC.rglob("*"):
        if path.suffix not in {".js", ".jsx", ".html"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "ROLE_PERMISSIONS" not in text, path
        assert "PERMISSION_CATALOGUE" not in text, path


# ── HTTP: landing + /auth/me + direct URL gate support ───────────────────────

def test_login_landing_and_auth_me_for_logistics():
    from fastapi.testclient import TestClient
    from app.auth.service import create_user
    from app.main import app

    with TestClient(app) as client:
        create_user(
            full_name="Logistics S1",
            company_name="EJ",
            email="logistics_s1@example.com",
            password="TestPass123!",
            role="logistics",
            is_approved=True,
            email_verified=True,
        )
        login = client.post(
            "/auth/login",
            json={"email": "logistics_s1@example.com", "password": "TestPass123!", "remember": False},
        )
        assert login.status_code == 200, login.text
        body = login.json()
        assert body["user"]["default_page"] == "shipments"
        assert body["user"]["default_surface"] == "v2"
        assert "shipments" in body["user"]["allowed_pages"]
        assert "accounting" in body["user"]["allowed_pages"]

        me = client.get("/auth/me")
        assert me.status_code == 200
        me_body = me.json()
        assert me_body["default_page"] == "shipments"
        assert "allowed_pages" in me_body
        assert set(me_body["allowed_pages"]) == set(
            allowed_pages_for_permissions(permissions_for_role("logistics"))
        )

        bounced = client.get("/login", follow_redirects=False)
        assert bounced.status_code in (302, 303)
        assert bounced.headers["location"] == "/v2/shipments"

        dash = client.get("/dashboard", follow_redirects=False)
        assert dash.status_code in (302, 303)
        assert dash.headers["location"] == "/v2/shipments"


def test_crm_auth_me_hides_accounting_page():
    from fastapi.testclient import TestClient
    from app.auth.service import create_user
    from app.main import app

    with TestClient(app) as client:
        create_user(
            full_name="CRM S1",
            company_name="EJ",
            email="crm_s1@example.com",
            password="TestPass123!",
            role="crm",
            is_approved=True,
            email_verified=True,
        )
        assert client.post(
            "/auth/login",
            json={"email": "crm_s1@example.com", "password": "TestPass123!", "remember": False},
        ).status_code == 200
        me = client.get("/auth/me").json()
        assert me["default_page"] == "inbox"
        assert "accounting" not in me["allowed_pages"]
        assert "inventory" not in me["allowed_pages"]
        assert "inbox" in me["allowed_pages"]


def test_malformed_authority_resolve_safe_fallback():
    """Empty / unknown role → deny pages; landing falls back without crashing."""
    auth = build_authority_fields({"role": "", "default_surface": "x", "default_page": "y"})
    assert auth["permissions"] == []
    assert auth["allowed_pages"] == []
    assert auth["default_surface"] in ("v1", "v2")
    assert auth["default_page"] in VALID_PAGES
    url = landing_url_for_user({"role": "nope"})
    assert url.startswith("/v2/")


def test_authority_consumer_malformed_fail_closed_source():
    """V2 consumer must fail closed on malformed /auth/me (no protected render)."""
    ac = (_STATIC / "v2" / "authority-consumer.js").read_text(encoding="utf-8")
    idx = (_STATIC / "v2" / "index.html").read_text(encoding="utf-8")
    assert "malformed" in ac
    assert "failClosedToLogin" in ac
    assert "/auth/logout" in ac
    assert "Fail closed" in ac or "fail closed" in ac.lower() or "empty allow-list" in ac
    assert "auth.malformed" in idx or "malformed" in idx
    assert "failClosedToLogin" in idx
    assert "/login" in idx


# ── Fail-closed shell (regression pins) ──────────────────────────────────────
# These pin a proven bypass: with authority-consumer.js blocked, a logged-in CRM
# user rendered the Accounting page. The shell degraded *open* in two ways — an
# inline `return true` gate, and a `page` seeded from the URL before any gate ran.


def _v2_index() -> str:
    return (_STATIC / "v2" / "index.html").read_text(encoding="utf-8")


def test_v2_shell_never_default_allows_when_consumer_missing():
    """Losing the consumer must make the shell less capable, never more."""
    idx = _v2_index()
    # The exact pre-repair defect.
    assert not re.search(r"pageIsAllowed\s*\|\|\s*function", idx)
    # Any inline predicate that answers "allowed" without consulting authority.
    assert not re.search(r"function\s*\(\s*\)\s*\{\s*return\s+true\s*;?\s*\}", idx)
    assert "AC_READY" in idx
    assert re.search(
        r"AC_READY\s*\?\s*AC\.pageIsAllowed\s*:\s*function\s*\(\s*\)\s*\{\s*return\s+false",
        idx,
    ), "missing consumer must deny every page"


def test_v2_shell_missing_consumer_denies_then_bounces():
    """Deny the render first; the logout redirect is cleanup, not the gate."""
    idx = _v2_index()
    assert "if (!AC_READY) {" in idx
    block = idx.split("if (!AC_READY) {", 1)[1][:800]
    assert "setPage('')" in block, "must deny the page before redirecting"
    assert "/auth/logout" in block
    assert "/login" in block


def test_v2_shell_does_not_boot_a_page_from_the_url():
    """No page may be derived from the URL before authority resolves.

    Seeding `page` from location rendered the requested protected page for one
    frame ahead of every gate. applyAuthorityGate re-reads the location itself.
    """
    idx = _v2_index()
    assert "_bootPage" not in idx
    assert "const [page, setPage] = React.useState('');" in idx
    assert "const [activeNav, setActiveNav] = React.useState('dashboard');" in idx
    assert "parseV2Location()" in idx.split("function applyAuthorityGate", 1)[1][:1200]


def test_v2_shell_non_ready_authority_denies_navigation():
    """`fallback` and `loading` are deny states, not allow states."""
    idx = _v2_index()
    assert not re.search(r"authorityStatus\s*===\s*'fallback'", idx), (
        "a branch named fail-closed must not be the one that allows"
    )
    # popstate + handleNav both gate on ready authority.
    assert len(re.findall(r"!authority \|\| authorityStatus !== 'ready'", idx)) >= 2


def test_v2_shell_fallback_landing_must_itself_be_allowed():
    """An unauthorized Dashboard is not a safe place to land."""
    idx = _v2_index()
    assert "return gate(d) ? d : '';" in idx
    assert "pageIsAllowed(d, authority.allowed_pages) ? d : ''" in idx


def test_v2_shell_page_deny_state_renders_no_content_block():
    """`page: ''` is only a deny state if every content region is page-gated.

    A region rendered on anything looser than `page === '<name>'` would survive
    the empty deny page. MockBanner is the one allowed exception: it carries no
    authority-bearing data, only a 'not wired yet' notice.
    """
    idx = _v2_index()
    ungated = [
        ln.strip()
        for ln in idx.splitlines()
        if "{!viewerDoc &&" in ln and "page === '" not in ln
    ]
    assert ungated == ["{!viewerDoc && <MockBanner page={page} />}"], ungated
    assert re.findall(r"page === '([a-z0-9_]+)'", idx)


def test_every_role_landing_in_allowed_pages_when_possible():
    for role in ROLES:
        auth = build_authority_fields({"role": role})
        if auth["allowed_pages"]:
            assert auth["default_page"] in auth["allowed_pages"], role
        else:
            # should not happen for current 9 roles
            assert False, f"{role} has empty allowed_pages"


def test_source_grep_no_require_permission_fiscal_tighten():
    """Slice 1 must not introduce require_permission fiscal enforcement."""
    hits = []
    for path in _APP.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "def require_permission" in text or "require_permission(" in text:
            hits.append(path.as_posix())
    assert not hits, f"require_permission must not land in Slice 1: {hits}"
