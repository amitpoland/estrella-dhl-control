"""test_phase1b_sidebar_shared.py — Phase 1B lifts Sidebar +
EstrellaMark + SubTabStrip into dashboard-shared.js. Sidebar becomes
prop-driven (navTree). NAV_TREE / ROUTE_REDIRECTS / NAV_INDEX /
navGroupOf stay in dashboard.html as app-owned config."""
from __future__ import annotations

import re
from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
SHARED = STATIC / "dashboard-shared.js"
DASH   = STATIC / "dashboard.html"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ── Shared module has Sidebar + helpers ─────────────────────────────────

def test_sidebar_in_shared_js():
    src = _read(SHARED)
    assert re.search(r"\bfunction\s+Sidebar\b\s*\(", src), \
        "Sidebar must be declared in dashboard-shared.js"


def test_estrella_mark_in_shared_js():
    src = _read(SHARED)
    assert re.search(r"\bfunction\s+EstrellaMark\b\s*\(", src)


def test_sub_tab_strip_in_shared_js():
    src = _read(SHARED)
    assert re.search(r"\bfunction\s+SubTabStrip\b\s*\(", src)


def test_shared_export_lists_sidebar_estrella_subtab():
    src = _read(SHARED)
    export_block = src.split("window.EstrellaShared")[-1]
    for sym in ("Sidebar", "EstrellaMark", "SubTabStrip"):
        assert sym in export_block, \
            f"{sym!r} missing from EstrellaShared export"


def test_sidebar_is_prop_driven_for_nav_tree():
    """Shared Sidebar must read its tree from a navTree prop, not from
    a closed-over NAV_TREE constant (which lives in dashboard.html and
    is not visible from inside the shared IIFE)."""
    src = _read(SHARED)
    fn_start = src.index("function Sidebar(")
    fn_body  = src[fn_start:fn_start + 8000]
    assert "navTree" in fn_body, "Sidebar must accept navTree prop"
    assert "NAV_TREE" not in fn_body, (
        "Sidebar body must not reference NAV_TREE — that constant "
        "lives in dashboard.html and is not reachable here"
    )


def test_shared_sidebar_has_no_app_specific_constants():
    src = _read(SHARED)
    fn_start = src.index("function Sidebar(")
    fn_body  = src[fn_start:fn_start + 8000]
    for forbidden in ("NAV_TREE", "NAV_INDEX", "ROUTE_REDIRECTS",
                      "navGroupOf("):
        assert forbidden not in fn_body, (
            f"Sidebar body must not reference {forbidden!r}"
        )


# ── dashboard.html stops declaring Sidebar / EstrellaMark / SubTabStrip ──

def test_sidebar_not_redeclared_in_dashboard():
    src = _read(DASH)
    hits = re.findall(r"\bfunction\s+Sidebar\b\s*\(", src)
    assert len(hits) == 0, (
        f"duplicate Sidebar declaration in dashboard.html "
        f"({len(hits)} hits) — must be removed in Phase 1B"
    )


def test_estrella_mark_not_redeclared_in_dashboard():
    src = _read(DASH)
    hits = re.findall(r"\bfunction\s+EstrellaMark\b\s*\(", src)
    assert len(hits) == 0


def test_sub_tab_strip_not_redeclared_in_dashboard():
    src = _read(DASH)
    hits = re.findall(r"\bfunction\s+SubTabStrip\b\s*\(", src)
    assert len(hits) == 0


# ── App-owned config stays in dashboard.html ────────────────────────────

def test_nav_tree_still_in_dashboard():
    assert "const NAV_TREE = [" in _read(DASH)


def test_route_redirects_still_in_dashboard():
    assert "const ROUTE_REDIRECTS = {" in _read(DASH)


def test_nav_group_of_still_in_dashboard():
    """navGroupOf is used by App at the SubTabStrip render site
    (~line 25981). It stays in dashboard.html."""
    assert re.search(r"\bfunction\s+navGroupOf\b\s*\(", _read(DASH))


def test_sidebar_callsite_passes_nav_tree_prop():
    """App must pass navTree={NAV_TREE} when rendering shared Sidebar."""
    src = _read(DASH)
    # `[\s\S]*?` matches any char including '>' (so onToggle={() => ...}
    # arrow functions don't terminate the match), non-greedy up to the
    # navTree prop.
    assert re.search(r"<Sidebar\s[\s\S]*?navTree=\{NAV_TREE\}", src), (
        "App must pass navTree={NAV_TREE} as a prop to <Sidebar>"
    )


# ── Destructure includes the three new shared symbols ──────────────────

def test_destructure_includes_sidebar_estrella_subtab():
    src = _read(DASH)
    end = src.index("} = window.EstrellaShared")
    block = src[end - 800:end + 40]
    for sym in ("Sidebar", "EstrellaMark", "SubTabStrip"):
        assert sym in block, f"{sym!r} missing from destructure"


# ── Boundaries: nothing else moved ──────────────────────────────────────

def test_batch_detail_page_moved_to_shipment_detail():
    """Phase 2 moved BatchDetailPage into shipment-detail.html.
    This was a Phase-1B boundary; updated in Phase 2."""
    assert "function BatchDetailPage(" not in _read(DASH)
    sdet = STATIC / "shipment-detail.html"
    assert sdet.exists()
    assert "function BatchDetailPage(" in sdet.read_text(encoding="utf-8")


def test_shipment_detail_html_exists_after_phase_2():
    assert (STATIC / "shipment-detail.html").exists()


def test_app_root_still_in_dashboard():
    assert re.search(r"\bfunction\s+App\b\s*\(", _read(DASH))


def test_route_helper_unchanged():
    """Phase 0 helper survives."""
    src = _read(DASH)
    assert "function buildShipmentDetailUrl(" in src
    assert "window.EstrellaRoutes" in src


def test_all_nine_detail_tabs_present():
    src = _read(DASH)
    for tab in ("Overview", "Documents", "DHL / Customs", "Warehouse",
                "Sales", "PZ / Accounting", "Timeline",
                "Intelligence", "Proposals"):
        assert f"'{tab}'" in src, f"tab {tab!r} missing"


def test_shared_module_makes_no_api_calls():
    """No backend URLs added to shared module by Sidebar lift."""
    src = _read(SHARED)
    assert "/api/v1/" not in src
    assert "/auth/me" not in src
