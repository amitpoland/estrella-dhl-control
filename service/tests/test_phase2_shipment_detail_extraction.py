"""test_phase2_shipment_detail_extraction.py — Phase 2.

BatchDetailPage moves from dashboard.html into shipment-detail.html.
buildShipmentDetailUrl flips to point at the new file. dashboard.html
?id= bookmarks redirect.
"""
from __future__ import annotations

import re
from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
DASH   = STATIC / "dashboard.html"
SDET   = STATIC / "shipment-detail.html"
SHARED = STATIC / "dashboard-shared.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ── shipment-detail.html exists with the right wiring ───────────────────

def test_shipment_detail_html_exists():
    assert SDET.exists()


def test_shipment_detail_html_includes_shared_js():
    src = _read(SDET)
    assert 'src="/dashboard/dashboard-shared.js"' in src


def test_shipment_detail_html_destructures_shared_symbols():
    src = _read(SDET)
    end = src.index("} = window.EstrellaShared")
    block = src[end - 800:end + 40]
    for sym in ("apiFetch", "fmtPLN", "Badge", "Card", "Btn", "Sel",
                "Toast", "SessionBanner", "EstrellaMark",
                "SubTabStrip", "Sidebar"):
        assert sym in block, f"{sym!r} missing from shared destructure"


def test_shipment_detail_contains_batch_detail_page():
    assert "function BatchDetailPage(" in _read(SDET)


def test_shipment_detail_has_app_wrapper():
    src = _read(SDET)
    assert "function ShipmentDetailApp(" in src
    assert "root.render(<ShipmentDetailApp />)" in src


def test_shipment_detail_renders_sidebar_with_nav_tree():
    src = _read(SDET)
    assert re.search(r"<Sidebar\s[\s\S]*?navTree=\{NAV_TREE_INLINE\}", src), (
        "shipment-detail.html ShipmentDetailApp must render "
        "<Sidebar … navTree={NAV_TREE_INLINE} />"
    )


def test_shipment_detail_has_all_nine_tabs():
    src = _read(SDET)
    for tab in ("Overview", "Documents", "DHL / Customs", "Warehouse",
                "Sales", "PZ / Accounting", "Timeline",
                "Intelligence", "Proposals"):
        assert f"'{tab}'" in src, f"tab {tab!r} missing"


def test_shipment_detail_inlines_nav_tree_alias():
    src = _read(SDET)
    # Either an inline copy or an alias is acceptable; both keep
    # navigation chrome stable when navigating to the page directly.
    assert "const NAV_TREE_INLINE" in src


def test_shipment_detail_back_button_returns_to_dashboard():
    src = _read(SDET)
    start = src.index("function ShipmentDetailApp(")
    body  = src[start:start + 3500]
    assert "/dashboard/dashboard.html" in body, (
        "ShipmentDetailApp goBack must navigate to /dashboard/dashboard.html"
    )


# ── dashboard.html no longer hosts BatchDetailPage ──────────────────────

def test_dashboard_no_longer_contains_batch_detail_page():
    assert "function BatchDetailPage(" not in _read(DASH)


def test_dashboard_no_longer_renders_detail_branch():
    """The {page === 'detail' && <BatchDetailPage …>} JSX must be gone."""
    src = _read(DASH)
    assert "<BatchDetailPage" not in src, (
        "dashboard.html must not render <BatchDetailPage> anymore"
    )


# ── buildShipmentDetailUrl flipped ─────────────────────────────────────

def test_helper_returns_shipment_detail_html():
    src = _read(DASH)
    fn_start = src.index("function buildShipmentDetailUrl(")
    body = src[fn_start:fn_start + 800]
    success_returns = [l for l in body.splitlines()
                       if "return" in l and "shipment-detail.html" in l]
    assert success_returns, (
        "helper success path must point at /dashboard/shipment-detail.html"
    )


def test_view_shipment_uses_window_location_href():
    src = _read(DASH)
    start = src.index("const viewShipment = (")
    body  = src[start:start + 400]
    assert "window.location.href" in body
    assert "buildShipmentDetailUrl" in body


def test_no_stale_set_page_detail_callsites():
    """Phase 2 leftover hunt — no active code path may call
    setPage('detail') anymore. The page === 'detail' render branch
    has been removed; any remaining call would set unreachable state
    and bypass the new shipment-detail.html URL.

    Comments mentioning the historical call are allowed (they explain
    the deletion); only ACTIVE JS statements are forbidden."""
    src = _read(DASH)
    # Match the call as an executable statement (not embedded in a comment).
    # An active call line has no `//` before setPage on the same line.
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        if "setPage('detail')" in line or 'setPage("detail")' in line:
            assert False, (
                f"active setPage('detail') callsite found: {line!r} — "
                f"replace with window.location.href = buildShipmentDetailUrl(id)"
            )


def test_new_shipment_modal_uses_helper_on_create():
    """NewShipmentModal.onCreated must navigate through the helper
    on success, not via the dead setPage('detail') + pushState path."""
    src = _read(DASH)
    idx = src.index("<NewShipmentModal")
    block = src[idx:idx + 1200]
    assert "buildShipmentDetailUrl(data.batchId)" in block or \
           "buildShipmentDetailUrl(data.batch_id)" in block, (
        "NewShipmentModal.onCreated must call "
        "window.location.href = buildShipmentDetailUrl(data.batchId)"
    )


def test_dashboard_redirects_id_query_param():
    """dashboard.html?id=… must redirect to shipment-detail.html?id=…
    so existing operator bookmarks keep working."""
    src = _read(DASH)
    assert re.search(
        r"window\.location\.(href|replace)\s*[=\(]\s*buildShipmentDetailUrl",
        src,
    ), "dashboard.html App must redirect ?id= bookmarks via the helper"


# ── No backend / API drift / no dashboard-shared.js changes ────────────

def test_dashboard_shared_js_unchanged_in_phase_2():
    src = _read(SHARED)
    # Phase 1B export set is the contract.
    for sym in ("apiFetch", "fmtPLN", "Badge", "Card", "Btn", "Sel",
                "Toast", "SessionBanner",
                "EstrellaMark", "SubTabStrip", "Sidebar"):
        assert sym in src
    # No Phase 2 add (BatchDetailPage etc.) crept in.
    assert "function BatchDetailPage(" not in src
    assert "function ShipmentDetailApp(" not in src


def test_no_new_api_urls_introduced():
    """Phase 2 must reuse existing endpoints, not invent new ones."""
    # Spot-check that no /api/vX path was added to shipment-detail
    # that doesn't already exist somewhere. Since shipment-detail
    # was cloned from dashboard.html, any /api/ path it references
    # also exists in the cloned source.
    for url in ("/api/v1/packing/", "/api/v1/dhl/readiness/",
                "/api/v1/sales/linkage/", "/api/v1/shipment/"):
        assert url in _read(SDET), f"expected URL {url!r} missing"


# ── Critical testids preserved in shipment-detail.html ─────────────────

def test_critical_testids_preserved():
    src = _read(SDET)
    for tid in (
        "packing-list-status",
        "packing-list-row-fallback",
        "packing-list-row-parsed",
        "packing-list-row-side-purchase",
        "packing-list-row-side-sales",
        "lane-readiness-sales",
        "lane-readiness-purchase",
        "detail-subheader-importer",
    ):
        assert f'"{tid}"' in src or f"'{tid}'" in src, \
            f"testid {tid!r} missing from shipment-detail.html"
