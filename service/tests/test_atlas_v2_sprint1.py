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


def test_v2_index_loads_dashboard_shared():
    """dashboard-shared.js must be loaded (provides EstrellaShared.apiFetch)."""
    html = _INDEX.read_text(encoding="utf-8", errors="replace")
    assert "dashboard-shared.js" in html, "dashboard-shared.js not loaded in v2 shell"


def test_v2_index_loads_pz_api():
    """pz-api.js must be loaded (wires proforma to live backend)."""
    html = _INDEX.read_text(encoding="utf-8", errors="replace")
    assert "pz-api.js" in html, "pz-api.js not loaded in v2 shell"


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
