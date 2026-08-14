"""Source-grep pins for Atlas V2 mobile / tablet shell behaviour.

Guards the regression: fixed sidebar crushing Dashboard on narrow viewports,
MOCK banner covering the nav drawer, and TopBar painting over the System strip.
"""
from __future__ import annotations

import pathlib

_V2 = pathlib.Path(__file__).parent.parent / "app" / "static" / "v2"
_INDEX = _V2 / "index.html"
_COMPONENTS = _V2 / "components.jsx"
_KANBAN = _V2 / "dashboard-kanban.jsx"
_PZ_DESIGN = pathlib.Path(__file__).parent.parent / "app" / "static" / "pz-design-v2.js"


def test_v2_index_uses_js_narrow_breakpoint():
    html = _INDEX.read_text(encoding="utf-8", errors="replace")
    assert "matchMedia('(max-width: 900px)')" in html
    assert "!isNarrow" in html
    assert "onOpenMenu={isNarrow" in html or "onOpenMobileNav={isNarrow" in html


def test_v2_index_hides_desktop_sidebar_in_css():
    html = _INDEX.read_text(encoding="utf-8", errors="replace")
    assert ".sidebar-desktop { display: none !important; }" in html
    assert ".mobile-hamburger { display: flex !important; }" in html


def test_v2_index_mobile_drawer_left_side():
    html = _INDEX.read_text(encoding="utf-8", errors="replace")
    assert 'data-testid="mobile-nav-drawer"' in html
    assert 'data-testid="mobile-nav-backdrop"' in html
    drawer_i = html.index('data-testid="mobile-nav-drawer"')
    backdrop_i = html.index('data-testid="mobile-nav-backdrop"')
    assert drawer_i < backdrop_i


def test_topbar_exposes_mobile_menu_button():
    src = _COMPONENTS.read_text(encoding="utf-8", errors="replace")
    assert "onOpenMenu" in src or "onOpenMobileNav" in src
    assert 'data-testid="mobile-menu-btn"' in src
    assert 'className="mobile-hamburger"' in src


def test_kanban_uses_responsive_layout_classes():
    src = _KANBAN.read_text(encoding="utf-8", errors="replace")
    assert "quick-flow-grid" in src
    assert "kpi-strip-grid" in src
    assert "atlas-content-pad" in src
    assert 'className="kanban-board"' in src


def test_appshell_unmounts_sidebar_on_narrow():
    src = _PZ_DESIGN.read_text(encoding="utf-8", errors="replace")
    assert "ensureAppShellResponsiveCss" in src
    assert "!isNarrow && (" in src
    assert 'data-testid="mobile-nav-drawer"' in src
    assert 'data-testid="sidebar-desktop"' in src
    assert 'aside data-testid="sidebar" className="sidebar-desktop"' not in src


def test_topbar_clips_overflow_so_it_cannot_paint_over_ops_strip():
    src = _COMPONENTS.read_text(encoding="utf-8", errors="replace")
    assert "overflow: 'hidden'" in src or 'overflow: "hidden"' in src
    assert "maxHeight: 56" in src
    assert "topbar-actions" in src


def test_mock_banner_zindex_below_drawer():
    banner = (_V2 / "mock-badge.jsx").read_text(encoding="utf-8", errors="replace")
    html = _INDEX.read_text(encoding="utf-8", errors="replace")
    assert "zIndex: 30" in banner
    assert "zIndex: 900" not in banner
    assert "zIndex: 1100" in html
    assert "--z-drawer: 1100" in html


def test_ops_status_strip_is_nonwrapping_scroll_row():
    src = (_V2 / "wireframe-update.jsx").read_text(encoding="utf-8", errors="replace")
    assert 'className="ops-status-strip"' in src
    assert "ops-status-items" in src
    assert "flexWrap: 'nowrap'" in src


def test_index_html_slug_resolves_to_dashboard():
    """/v2/index.html must not stick as page 'index.html' (empty MOCK shell)."""
    html = _INDEX.read_text(encoding="utf-8", errors="replace")
    assert "slug === 'index.html'" in html
    # Current main clears the slug (bare → default_page after /auth/me);
    # either clearing or rewriting to 'dashboard' is acceptable.
    assert "slug = ''" in html or "slug = 'dashboard'" in html
