"""test_phase1_dashboard_shared.py — Phase 1 lifts 8 shared utilities
into dashboard-shared.js without behaviour change."""
from __future__ import annotations

import re
from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
SHARED = STATIC / "dashboard-shared.js"
DASH   = STATIC / "dashboard.html"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


SYMBOLS = ("apiFetch", "fmtPLN", "Badge", "Card", "Btn", "Sel",
           "Toast", "SessionBanner")


# ── Shared module ────────────────────────────────────────────────────────

def test_dashboard_shared_js_exists():
    assert SHARED.exists(), "service/app/static/dashboard-shared.js must exist"


def test_shared_module_defines_eight_symbols():
    src = _read(SHARED)
    for sym in SYMBOLS:
        assert re.search(rf"\bfunction\s+{sym}\b", src), \
            f"{sym!r} missing in dashboard-shared.js"


def test_shared_module_exports_on_window():
    src = _read(SHARED)
    assert "window.EstrellaShared" in src
    # All 8 symbols must appear in the export block.
    export_block = src.split("window.EstrellaShared")[-1]
    for sym in SYMBOLS:
        assert sym in export_block, \
            f"{sym!r} not in EstrellaShared export"


def test_shared_module_makes_no_api_calls():
    """Shared utilities are presentational + the HTTP helper. No
    backend URL constants live here."""
    src = _read(SHARED)
    assert "/api/v1/" not in src
    assert "/auth/me" not in src


def test_shared_module_uses_iife_wrapper():
    """Shared module is IIFE-wrapped so it does not pollute the
    Babel block's lexical scope."""
    src = _read(SHARED)
    assert "(function ()" in src or "(function()" in src
    assert "})();" in src


# ── dashboard.html ───────────────────────────────────────────────────────

def test_dashboard_html_references_shared_js_before_main_block():
    src = _read(DASH)
    shared_idx = src.find('src="/dashboard/dashboard-shared.js"')
    assert shared_idx > 0, "shared.js script tag missing"
    # The destructure call must come after the shared script tag.
    destruct_idx = src.find("} = window.EstrellaShared")
    assert destruct_idx > shared_idx, \
        "destructure must come after shared.js script tag"


def test_dashboard_html_destructures_eight_symbols():
    src = _read(DASH)
    end = src.find("} = window.EstrellaShared")
    assert end > 0, "destructure line missing"
    block = src[end - 400:end + 40]
    for sym in SYMBOLS:
        assert sym in block, f"{sym!r} missing from destructure"


def test_dashboard_html_no_duplicate_definitions():
    """Each of the 8 symbols must NOT appear as a function declaration
    in dashboard.html (they live in shared.js now)."""
    src = _read(DASH)
    for sym in SYMBOLS:
        hits = re.findall(rf"\bfunction\s+{sym}\b\s*\(", src)
        assert len(hits) == 0, (
            f"duplicate definition of {sym!r} in dashboard.html "
            f"({len(hits)} hits) — must be removed in Phase 1"
        )


# ── Boundaries: nothing else moved ──────────────────────────────────────

def test_sidebar_moved_to_shared_after_phase_1b():
    """Phase 1B lifted Sidebar into dashboard-shared.js. The Phase 1
    boundary that asserted Sidebar must remain in dashboard.html no
    longer applies — see test_phase1b_sidebar_shared.py."""
    hits = re.findall(r"\bfunction\s+Sidebar\b\s*\(", _read(DASH))
    assert len(hits) == 0, "Sidebar must be removed from dashboard.html in Phase 1B"


def test_batch_detail_page_moved_to_shipment_detail():
    """Phase 2 moved BatchDetailPage out of dashboard.html into
    shipment-detail.html.  This test was a Phase-1 boundary; updated
    in Phase 2 to reflect the legitimate move."""
    assert "function BatchDetailPage(" not in _read(DASH)
    sdet = STATIC / "shipment-detail.html"
    assert sdet.exists()
    assert "function BatchDetailPage(" in sdet.read_text(encoding="utf-8")


def test_app_root_still_in_dashboard():
    assert re.search(r"\bfunction\s+App\b\s*\(", _read(DASH))


def test_route_helper_unchanged():
    """Phase 0 helper survives Phase 1."""
    src = _read(DASH)
    assert "function buildShipmentDetailUrl(" in src
    assert "window.EstrellaRoutes" in src


def test_transform_batch_still_in_dashboard():
    """transformBatch is App-only — must stay in dashboard.html."""
    assert "function transformBatch(" in _read(DASH)


def test_shipment_detail_html_exists_after_phase_2():
    """Phase 2 lifted the Phase-1 boundary — file now exists."""
    assert (STATIC / "shipment-detail.html").exists()


def test_all_nine_detail_tabs_present():
    src = _read(DASH)
    for tab in ("Overview", "Documents", "DHL / Customs", "Warehouse",
                "Sales", "PZ / Accounting", "Timeline",
                "Intelligence", "Proposals"):
        assert f"'{tab}'" in src, f"tab {tab!r} missing from dashboard.html"


def test_status_map_still_in_dashboard():
    """STATUS_MAP is referenced outside Badge (line ~10237) so it stays
    in dashboard.html. The shared module carries its own private copy."""
    assert "const STATUS_MAP = {" in _read(DASH)
