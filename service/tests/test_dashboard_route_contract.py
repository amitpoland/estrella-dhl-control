"""test_dashboard_route_contract.py — Phase 0 route helper.

Locks in the navigation contract so Phase 1 (shipment-detail.html
extraction) is a one-line swap inside buildShipmentDetailUrl.
"""
from __future__ import annotations

import re
from pathlib import Path


DASH = (Path(__file__).resolve().parents[1] / "app" / "static"
        / "dashboard.html").read_text(encoding="utf-8")
STATIC_DIR = (Path(__file__).resolve().parents[1] / "app" / "static")


# ── Helper presence ──────────────────────────────────────────────────────

def test_build_shipment_detail_url_helper_exists():
    assert "function buildShipmentDetailUrl(" in DASH
    # Exposed on window for future cross-file consumption.
    assert "window.EstrellaRoutes" in DASH


def test_helper_currently_returns_dashboard_html():
    """Phase 0 lock — helper still points at dashboard.html. When
    Phase 1 lands, this test must FAIL and be updated in the same PR."""
    snippet = DASH[DASH.index("function buildShipmentDetailUrl("):
                   DASH.index("function buildShipmentDetailUrl(") + 500]
    assert "/dashboard/dashboard.html" in snippet
    assert "/dashboard/shipment-detail.html" not in snippet


def test_helper_uses_encode_uri_component():
    snippet = DASH[DASH.index("function buildShipmentDetailUrl("):
                   DASH.index("function buildShipmentDetailUrl(") + 500]
    assert "encodeURIComponent" in snippet


# ── Caller threading ────────────────────────────────────────────────────

def test_viewShipment_calls_buildShipmentDetailUrl():
    """viewShipment inside App() must route through the helper, not
    construct the query string inline."""
    start = DASH.index("const viewShipment = (")
    body  = DASH[start:start + 700]
    assert "buildShipmentDetailUrl" in body, (
        "viewShipment must use buildShipmentDetailUrl, not inline string concat"
    )


def test_no_other_hardcoded_detail_query_strings():
    """No other code may construct '?id=' detail URLs by hand.
    Allowed: the helper itself + viewShipment's slicing of helper output.
    Any future caller must go through buildShipmentDetailUrl."""
    patterns_disallowed = [
        r"`\?id=\$\{",       # template literal building ?id=...
        r"'\?id='\s*\+",     # plain string concat '?id=' + ...
        r'"\?id="\s*\+',
    ]
    for pat in patterns_disallowed:
        hits = re.findall(pat, DASH)
        # Phase 0 expects exactly one template-literal hit inside the
        # helper itself. Cap at 2 to allow that and any single
        # transitional artefact; tighten once shipment-detail is split.
        assert len(hits) <= 2, (
            f"too many hardcoded ?id= constructions ({len(hits)}) "
            f"for pattern {pat!r} — all detail URLs must go through "
            f"buildShipmentDetailUrl"
        )


# ── Boundary: nothing else extracted yet ────────────────────────────────

def test_shipment_detail_html_does_not_exist_yet():
    """Phase 0 must NOT create the new file — only the helper."""
    assert not (STATIC_DIR / "shipment-detail.html").exists(), (
        "shipment-detail.html must not exist until Phase 1"
    )


def test_dashboard_shared_js_exists_after_phase_1():
    """Phase 1 lifted the original Phase-0 'must-not-exist' boundary.
    The file now exists and houses the 8 shared utilities. See
    test_phase1_dashboard_shared.py for the full contract."""
    assert (STATIC_DIR / "dashboard-shared.js").exists()


def test_batch_detail_page_still_in_dashboard():
    """BatchDetailPage stays in dashboard.html in Phase 0."""
    assert "function BatchDetailPage(" in DASH


def test_existing_id_query_param_still_handled():
    """The ?id= URL param must continue to drive batch selection."""
    assert "params.get('id')" in DASH or 'params.get("id")' in DASH


# ── Tabs untouched ──────────────────────────────────────────────────────

def test_detail_tabs_unchanged():
    """All 9 detail tabs must still be present."""
    assert "const DETAIL_TABS" in DASH
    for tab in ("Overview", "Documents", "DHL / Customs", "Warehouse",
                "Sales", "PZ / Accounting", "Timeline",
                "Intelligence", "Proposals"):
        assert f"'{tab}'" in DASH, f"tab {tab!r} must remain in DETAIL_TABS"


# ── No backend URL drift ────────────────────────────────────────────────

def test_no_backend_url_changes():
    """The helper must not introduce any /api/v1/... URL changes."""
    snippet = DASH[DASH.index("function buildShipmentDetailUrl("):
                   DASH.index("function buildShipmentDetailUrl(") + 500]
    assert "/api/" not in snippet, (
        "route helper must not reference backend URLs"
    )
