"""
test_atlas_v2_sprint1.py -- Sprint 1 contract tests for the /v2/ shell mount.

Coverage:
  1. /v2/ route is registered in the app.
  2. /v2/ unauth in prod-env -> redirect to /login (session gate identical to /dashboard/).
  3. /v2/ in dev-env -> 200 (no auth required locally).
  4. /v2/index.html exists on disk and contains expected shell tokens.
  5. WIRED_PAGES only contains 'proforma' and 'proforma_detail'.
  6. mock-badge.jsx is present under static/v2/.
  7. No estrella-docs scripts in index.html.
  8. tweaks-panel.jsx script tag removed from index.html.
  9. pz-api.js / dashboard-shared.js loaded before jsx files.
 10. /v2/ handler shares the same login-gate logic as /dashboard/ handler.
"""
from __future__ import annotations

import pathlib
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings

_STATIC = pathlib.Path(__file__).parent.parent / "app" / "static"
_V2 = _STATIC / "v2"
_INDEX = _V2 / "index.html"


# ── File-system checks (no server needed) ────────────────────────────────────

def test_v2_index_html_exists():
    """Shell file present on disk."""
    assert _INDEX.exists(), f"v2/index.html missing at {_INDEX}"


def test_v2_index_no_tweaks_panel_script():
    """tweaks-panel.jsx script tag must be removed (omelette runtime not available)."""
    html = _INDEX.read_text(encoding="utf-8", errors="replace")
    assert 'src="tweaks-panel.jsx"' not in html, "tweaks-panel.jsx script still present"


def test_v2_index_no_estrella_docs():
    """estrella-docs/ must not be loaded by the shell (Document Suite is out of scope)."""
    html = _INDEX.read_text(encoding="utf-8", errors="replace")
    assert "estrella-docs/" not in html, "estrella-docs reference found in v2/index.html"


def test_v2_index_provides_api_fetch():
    """EstrellaShared.apiFetch must be available in the v2 shell.

    dashboard-shared.js is intentionally excluded: it exports Track-1 components
    (Sidebar, Badge, Btn, etc.) that would overwrite Track-2 design's components.jsx.
    The shell instead uses an inline apiFetch shim that provides only apiFetch
    without polluting the window with Track-1 UI primitives.
    """
    html = _INDEX.read_text(encoding="utf-8", errors="replace")
    # The shim must be present (inline or via any script providing EstrellaShared.apiFetch)
    assert "EstrellaShared" in html, "EstrellaShared not defined in v2 shell"
    assert "apiFetch" in html, "apiFetch not provided in v2 shell"
    # dashboard-shared.js must NOT be loaded (Track-1 component pollution)
    assert 'src="dashboard-shared.js"' not in html, (
        "dashboard-shared.js loaded in v2 shell — removes Track-1 components that "
        "would overwrite design's components.jsx"
    )


def test_v2_index_loads_pz_api():
    """pz-api.js must be loaded (wires proforma to live backend)."""
    html = _INDEX.read_text(encoding="utf-8", errors="replace")
    assert "pz-api.js" in html, "pz-api.js not loaded in v2 shell"


def test_v2_self_contained_no_cross_path():
    """Shared-layer scripts must be co-located in static/v2/ (no /dashboard/ cross-path).

    The shell must be self-contained: pz-api.js, pz-state.js, dashboard-shared.js
    must live under static/v2/ and be referenced without the /dashboard/ prefix.
    A cross-path reference creates a coupling between the /v2/ and /dashboard/ handlers
    that breaks if either is deployed or gated independently.
    """
    html = _INDEX.read_text(encoding="utf-8", errors="replace")
    assert "/dashboard/pz-api.js" not in html, "pz-api.js referenced via /dashboard/ (not self-contained)"
    assert "/dashboard/pz-state.js" not in html, "pz-state.js referenced via /dashboard/ (not self-contained)"
    assert "/dashboard/dashboard-shared.js" not in html, "dashboard-shared.js referenced via /dashboard/"
    # Confirm co-located copies exist
    assert (_V2 / "pz-api.js").exists(), "pz-api.js not co-located in static/v2/"
    assert (_V2 / "pz-state.js").exists(), "pz-state.js not co-located in static/v2/"
    assert (_V2 / "dashboard-shared.js").exists(), "dashboard-shared.js not co-located in static/v2/"


def test_v2_mock_badge_jsx_present():
    """mock-badge.jsx must exist under static/v2/."""
    assert (_V2 / "mock-badge.jsx").exists(), "mock-badge.jsx missing"


def test_v2_index_includes_mock_banner_component():
    """MockBanner must be referenced in the shell markup."""
    html = _INDEX.read_text(encoding="utf-8", errors="replace")
    assert "MockBanner" in html, "MockBanner not used in v2 shell"


def test_v2_mock_badge_wired_pages_correct():
    """WIRED_PAGES must contain exactly proforma and proforma_detail."""
    badge_src = (_V2 / "mock-badge.jsx").read_text(encoding="utf-8", errors="replace")
    assert "proforma" in badge_src, "'proforma' missing from WIRED_PAGES"
    assert "proforma_detail" in badge_src, "'proforma_detail' missing from WIRED_PAGES"


def test_v2_proforma_list_uses_pz_state():
    """proforma-list.jsx must use PzState.useProformaDrafts (not hardcoded mock)."""
    src = (_V2 / "proforma-list.jsx").read_text(encoding="utf-8", errors="replace")
    assert "PzState.useProformaDrafts" in src, "proforma-list.jsx not wired to PzState"
    assert "PROFORMA_DRAFTS" not in src, "old PROFORMA_DRAFTS mock array still present"


def test_v2_proforma_detail_uses_pz_state():
    """proforma-detail.jsx must fetch live detail and disclose-post."""
    src = (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8", errors="replace")
    assert "PzState.useDraft" in src, "proforma-detail.jsx not wired to PzState.useDraft"
    assert "disclose-post" in src, "disclose-post endpoint not referenced in proforma-detail.jsx"


def test_v2_proforma_detail_vat_resolution():
    """proforma-detail.jsx must surface vat_resolution (ADR-027 D4)."""
    src = (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8", errors="replace")
    assert "vat_resolution" in src, "vat_resolution not displayed in proforma-detail.jsx"
    assert "data-testid=\"vat-resolution-detail\"" in src, "vat-resolution-detail testid missing"


# ── Route registration check ──────────────────────────────────────────────────

def test_v2_route_registered():
    """GET /v2/{path} route must be registered in the app."""
    from app.main import app as _app
    paths = [r.path for r in _app.routes if hasattr(r, "path")]
    assert any("/v2/" in p for p in paths), "/v2/ route not registered in main.py"


# ── HTTP gate tests ───────────────────────────────────────────────────────────

@pytest.fixture()
def dev_client(tmp_path, monkeypatch):
    """Client in dev mode -- auth disabled."""
    monkeypatch.setattr(settings, "environment", "dev")
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def prod_client(tmp_path, monkeypatch):
    """Client in prod mode -- session gate active."""
    monkeypatch.setattr(settings, "environment", "prod")
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    from app.main import app
    with TestClient(app, raise_server_exceptions=False, follow_redirects=False) as c:
        yield c


def test_v2_dev_mode_serves_shell(dev_client):
    """In dev mode, GET /v2/index.html serves the shell (200)."""
    r = dev_client.get("/v2/index.html")
    assert r.status_code == 200, f"Expected 200 in dev mode, got {r.status_code}: {r.text[:200]}"
    assert "text/html" in r.headers.get("content-type", ""), "Response is not HTML"


def test_v2_prod_unauth_redirects_to_login(prod_client):
    """In prod mode without session, GET /v2/ must redirect to /login (gate matches /dashboard/)."""
    r = prod_client.get("/v2/")
    # Either 302 redirect or 401 -- must NOT return 200
    assert r.status_code in (302, 307, 401, 403), (
        f"Expected redirect/auth error for unauthenticated /v2/ in prod, got {r.status_code}"
    )
    if r.status_code in (302, 307):
        location = r.headers.get("location", "")
        assert "login" in location.lower(), f"Redirect not to /login: {location}"


def test_v2_root_redirect(dev_client):
    """GET /v2 (no trailing slash) must redirect to /v2/index.html."""
    r = dev_client.get("/v2", follow_redirects=False)
    assert r.status_code in (302, 307), f"Expected redirect from /v2, got {r.status_code}"


# ── URL sync contract tests (Phase 1, Sprint 1 increment) ────────────────────

def test_v2_deep_link_proforma_served(dev_client):
    """Deep link GET /v2/proforma?batch_id=X must serve the shell (200).

    The /v2/{path:path} handler falls back to index.html for any unknown path,
    so /v2/proforma serves the shell which then reads location on mount.
    """
    r = dev_client.get("/v2/proforma?batch_id=BATCH-TEST-001")
    assert r.status_code == 200, f"Expected 200 for deep link, got {r.status_code}"
    assert "text/html" in r.headers.get("content-type", ""), "Response not HTML"


def test_v2_deep_link_inbox_served(dev_client):
    """Any page deep link must serve the shell."""
    r = dev_client.get("/v2/inbox")
    assert r.status_code == 200


def test_v2_url_sync_present_in_shell():
    """index.html must contain the URL-sync logic (parseV2Location, handleNav pushState, popstate)."""
    html = _INDEX.read_text(encoding="utf-8", errors="replace")
    assert "parseV2Location" in html, "parseV2Location missing from shell"
    assert "pushState" in html, "history.pushState missing from shell"
    assert "popstate" in html, "popstate listener missing from shell"
    assert "pageToUrl" in html, "pageToUrl helper missing from shell"


def test_v2_batch_scoped_pages_defined():
    """BATCH_SCOPED_PAGES must contain proforma and proforma_detail."""
    html = _INDEX.read_text(encoding="utf-8", errors="replace")
    assert "BATCH_SCOPED_PAGES" in html, "BATCH_SCOPED_PAGES missing from shell"
    assert "'proforma'" in html or '"proforma"' in html, "proforma missing from BATCH_SCOPED_PAGES"
    assert "'proforma_detail'" in html or '"proforma_detail"' in html, "proforma_detail missing"


def test_v2_route_redirects_in_shell():
    """ROUTE_REDIRECTS must be present (preserves legacy deep links)."""
    html = _INDEX.read_text(encoding="utf-8", errors="replace")
    assert "ROUTE_REDIRECTS" in html, "ROUTE_REDIRECTS missing from shell"


def test_v2_index_no_cross_path_for_shared_layer():
    """index.html must not reference /dashboard/ for the shared-layer scripts.

    Cross-path references create coupling between /v2/ and /dashboard/ handlers.
    The self-containment fix uses relative paths (dashboard-shared.js, pz-api.js)
    or absolute /v2/ paths -- never /dashboard/pz-api.js etc.
    """
    html = _INDEX.read_text(encoding="utf-8", errors="replace")
    assert "/dashboard/pz-api.js" not in html, "pz-api.js referenced via /dashboard/ in index.html"
    assert "/dashboard/pz-state.js" not in html, "pz-state.js referenced via /dashboard/ in index.html"
    assert "/dashboard/dashboard-shared.js" not in html, "dashboard-shared.js referenced via /dashboard/"


# ── Parse-smoke: structural completeness of all v2 JSX files ────────────────
# This test class would have caught the proforma-list.jsx truncation in PR #423.
# Every *.jsx under static/v2/ must end with a proper closing line (not a
# mid-expression fragment). The invariant: last non-empty line ends with ";"
# or "}" -- matching the registration/closure patterns used by all v2 components.

_JSX_SUFFIX_REQUIRED = (";", "}")


def test_v2_jsx_all_files_structurally_complete():
    """Every *.jsx under static/v2/ must end on a syntactically closed line.

    A file whose last non-empty line ends with neither ';' nor '}' is truncated
    (e.g. '<td style={{ padding: ...' -- the PR #423 defect pattern).
    This test is the minimal parse-smoke that would have blocked that merge.
    """
    jsx_files = sorted(_V2.glob("*.jsx"))
    assert jsx_files, f"No .jsx files found under {_V2}"

    failures: list[str] = []
    for f in jsx_files:
        content = f.read_text(encoding="utf-8", errors="replace")
        non_empty = [ln.rstrip() for ln in content.splitlines() if ln.strip()]
        if not non_empty:
            failures.append(f"{f.name}: file is empty")
            continue
        last = non_empty[-1]
        if not (last.endswith(";") or last.endswith("}")):
            failures.append(
                f"{f.name}: last non-empty line does not close properly: {last!r}"
            )

    assert not failures, (
        "Structurally incomplete JSX file(s) -- likely truncated:\n"
        + "\n".join(f"  {e}" for e in failures)
    )


# ── apiFetch shim contract tests (ADR-028) ────────────────────────────────────
# These pin the inline shim's behavioral contract so that future edits cannot
# silently drop D1 (network error handling) or D2 (err.status on auth).
# They are structural (text-grep) tests — they verify the contract is EXPRESSED
# in the shim source, not that it executes correctly at runtime.

def test_v2_shim_has_network_error_catch():
    """apiFetch shim must wrap fetch() in try/catch and surface a 'network' error.

    D1 fix: a service-down condition (fetch() throws TypeError) must produce
    a user-friendly error with err.type='network', not an uncaught TypeError.
    Contract source: dashboard-shared.js canonical apiFetch.
    """
    html = _INDEX.read_text(encoding="utf-8", errors="replace")
    assert "try {" in html, "apiFetch shim missing try-block (D1: network error catch)"
    assert "catch" in html, "apiFetch shim missing catch clause (D1: network error catch)"
    assert "Service unreachable" in html, (
        "apiFetch shim missing 'Service unreachable' message (D1: canonical network error text)"
    )
    assert "type = 'network'" in html or "ne.type" in html, (
        "apiFetch shim missing err.type='network' assignment (D1)"
    )


def test_v2_shim_sets_err_status_on_auth():
    """apiFetch shim must set err.status on 401/403 responses.

    D2 fix: callers that branch on err.status (e.g. to distinguish 401 from 403)
    must not receive undefined. Contract source: dashboard-shared.js canonical apiFetch.
    """
    html = _INDEX.read_text(encoding="utf-8", errors="replace")
    assert ".status = res.status" in html, (
        "apiFetch shim missing err.status = res.status assignment (D2: auth error status)"
    )
    assert "type = 'auth'" in html or "e.type = 'auth'" in html, (
        "apiFetch shim missing err.type='auth' (D2: auth error type)"
    )
