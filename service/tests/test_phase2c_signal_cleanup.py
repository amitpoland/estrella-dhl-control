"""test_phase2c_signal_cleanup.py — Phase 2C operational-signal
cleanup inside shipment-detail.html.

Source-grep assertions only.  Phase 2C is pure visibility cleanup —
no behaviour changes, no new endpoints.
"""
from __future__ import annotations

import re
from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
SDET   = STATIC / "shipment-detail.html"
DASH   = STATIC / "dashboard.html"
SHARED = STATIC / "dashboard-shared.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ── Edit 1: detailed readiness collapsed ────────────────────────────────

def test_overview_detailed_readiness_details_exists():
    assert 'data-testid="overview-detailed-readiness"' in _read(SDET)


def test_overall_readiness_card_inside_detailed_block():
    """OverallReadinessCard must render inside the new <details> wrap,
    not at top-level of the Overview tab."""
    src = _read(SDET)
    idx_details = src.index('data-testid="overview-detailed-readiness"')
    idx_orc     = src.index("<OverallReadinessCard")
    assert idx_orc > idx_details, (
        "<OverallReadinessCard> must be inside <details "
        "data-testid='overview-detailed-readiness'>"
    )


def test_batch_control_center_still_rendered_on_overview():
    """BatchControlCenter remains the canonical readiness surface."""
    src = _read(SDET)
    assert "<BatchControlCenter" in src


def test_missing_functions_matrix_only_inside_detailed_block():
    """MissingFunctionsMatrix must be moved inside the
    overview-detailed-readiness <details>; the prior top-level
    rendering on Overview is removed (deduped with the detailed
    block)."""
    src = _read(SDET)
    idx_details = src.index('data-testid="overview-detailed-readiness"')
    hits = list(re.finditer(r"<MissingFunctionsMatrix\b", src))
    assert hits, "MissingFunctionsMatrix render not found"
    for h in hits:
        assert h.start() > idx_details, (
            "MissingFunctionsMatrix render must be inside the "
            "overview-detailed-readiness <details>"
        )
    # Exactly one render — no duplicate at top-level.
    assert len(hits) == 1, (
        f"expected exactly 1 MissingFunctionsMatrix render, found {len(hits)}"
    )


# ── Edit 2: DHL Section 1 Shipment Info collapsed (not removed) ─────────

def test_dhl_shipment_metadata_collapsed_details_exists():
    assert 'data-testid="dhl-shipment-metadata-collapsed"' in _read(SDET)


def test_dhl_shipment_metadata_inforows_inside_details():
    """The 5 duplicate InfoRow labels must live inside the new
    <details> block, not at top-level of Section 1."""
    src = _read(SDET)
    idx_details = src.index('data-testid="dhl-shipment-metadata-collapsed"')
    # Locate the end of that <details> — naive: next </details>.
    idx_details_end = src.index('</details>', idx_details)
    section_block = src[idx_details:idx_details_end]
    for label in ('label="AWB / Tracking"', 'label="Carrier"',
                  'label="Batch ID"', 'label="Invoice Files"',
                  'label="AWB PDF"'):
        assert label in section_block, (
            f"{label} must be inside dhl-shipment-metadata-collapsed details"
        )


# ── Edit 3: Live Tracking no-credentials hide guard ─────────────────────

def test_live_tracking_has_no_credentials_hide_guard():
    """Live Tracking Status block must return null when carrier API is
    unconfigured AND operator has not manually set tracking."""
    src = _read(SDET)
    # Tolerate variable naming (_isManualGuard / isManual).
    pattern = re.compile(
        r"isNoCreds\s*&&\s*!\s*_?isManual\w*\)\s*return\s+null",
        re.MULTILINE,
    )
    assert pattern.search(src), (
        "Live Tracking block missing no-credentials hide guard "
        "(`if (isNoCreds && !isManual) return null;`)"
    )


# ── Edit 4: Sales Lane empty state ──────────────────────────────────────

def test_sales_lane_empty_state_rendered():
    src = _read(SDET)
    assert 'data-testid="lane-readiness-sales-empty"' in src
    # Honest-empty wording — canary text.
    assert "Sales drafts: 0" in src
    assert "run Reparse all" in src


def test_sales_lane_populated_banner_still_exists():
    """The non-zero banner testid must still be there (rendered when
    drafts_total > 0)."""
    assert 'data-testid="lane-readiness-sales"' in _read(SDET)


# ── Edit 5: Inventory empty state collapsed ─────────────────────────────

def test_inventory_empty_state_collapsed_under_details():
    src = _read(SDET)
    assert 'data-testid="inventory-batch-state-collapsed"' in src
    assert 'data-testid="inventory-batch-state-empty"' in src


def test_inventory_strip_still_exists_for_non_empty_case():
    """The populated branch keeps its testid (rendered when total > 0)."""
    assert 'data-testid="inventory-batch-state-strip"' in _read(SDET)


# ── Edit 6: Cache freshness banner gating regression guard ──────────────

def test_cache_freshness_banner_still_gated_on_stale_flag():
    """Banner must remain gated on audit.cache_freshness.stale — not
    removed, not re-enabled unconditionally."""
    src = _read(SDET)
    assert re.search(
        r"audit\.cache_freshness\s*&&\s*audit\.cache_freshness\.stale",
        src,
    ), "Cache-freshness banner gate must remain on cache_freshness.stale"


# ── Boundaries: nothing else moved ──────────────────────────────────────

def test_all_nine_tabs_present():
    src = _read(SDET)
    for tab in ("Overview", "Documents", "DHL / Customs", "Warehouse",
                "Sales", "PZ / Accounting", "Timeline",
                "Intelligence", "Proposals"):
        assert f"'{tab}'" in src, f"tab {tab!r} missing"


def test_critical_components_still_present():
    src = _read(SDET)
    for sym in ("BatchDetailPage", "ShipmentDetailApp",
                "AddDocumentModal", "WorkflowStrip",
                "BatchControlCenter", "ContractorResolutionPanel",
                "ProformaDraftPanel", "DhlActionCard",
                "OperatorWorkflowCard", "ExecutePZGate",
                "ProformaReadinessCard"):
        assert re.search(rf"^function\s+{sym}\s*\(", src, re.MULTILINE), \
            f"{sym!r} missing after Phase 2C"


def test_dashboard_and_shared_untouched_by_phase_2c():
    dash = _read(DASH)
    assert "function buildShipmentDetailUrl(" in dash
    assert "/dashboard/shipment-detail.html?id=" in dash
    shared = _read(SHARED)
    for sym in ("Sidebar", "EstrellaMark", "SubTabStrip",
                "apiFetch", "fmtPLN", "Badge", "Card", "Btn",
                "Sel", "Toast", "SessionBanner"):
        assert sym in shared, f"{sym!r} missing from dashboard-shared.js"
