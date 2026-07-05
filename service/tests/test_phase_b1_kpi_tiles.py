"""
test_phase_b1_kpi_tiles.py — Phase B B1 KPI tile polish
(PROJECT_STATE DECISIONS "Phase B B1", 2026-07-03).

The Stage-2 overview tiles are restyled to the wireframe InvStatTile design
(design/inventory-page.design.jsx :28-43). Real numbers from
/inventory/stage2/aggregate ONLY; Consignment is a clean BACKEND-PENDING ·
PHASE C tile (never a fake number); the raw diagnostic limitations paragraph
is removed from the UI.
"""
from pathlib import Path

_V2 = Path(__file__).resolve().parent.parent / "app" / "static" / "v2"


def _inv() -> str:
    return (_V2 / "inventory-page.jsx").read_text(encoding="utf-8", errors="replace")


def _design() -> str:
    p = Path(__file__).resolve().parent.parent.parent / "docs" / "design" / "inventory-page.design.jsx"
    return p.read_text(encoding="utf-8", errors="replace")


def test_invstattile_component_present():
    src = _inv()
    assert "function InvStatTile(" in src, "the wireframe InvStatTile must be ported"


def test_four_stage2_tiles_with_testids():
    # InvStatTile takes a `testid` prop and renders data-testid={testid};
    # the source therefore carries the `testid="…"` form.
    src = _inv()
    for tid in ("tile-final-stock", "tile-samples-out", "tile-returns", "tile-consignment"):
        assert f'testid="{tid}"' in src, f"tile {tid} missing"


def test_tiles_use_real_aggregate_feed_only():
    """Values come from the stage2 aggregate response — no hardcoded numbers."""
    src = _inv()
    k = src.index('testid="tile-final-stock"')
    row = src[k:k + 700]
    assert "s2.final_stock" in row, "final-stock tile must read the real aggregate field"
    assert "s2.samples" in row, "samples tile must read the real aggregate field"
    assert "s2.returns" in row, "returns tile must read the real aggregate field"
    # no fabricated wireframe demo numbers leaked in (e.g. 412 / 1,847 / 2.41M)
    for fake in ("2.41M", "1,847", "PLN 2."):
        assert fake not in src, f"wireframe demo number leaked into live UI: {fake}"


def test_consignment_tile_is_pending_not_fake():
    src = _inv()
    k = src.index('testid="tile-consignment"')
    tile = src[k:k + 200]
    assert "pending" in tile, "consignment tile must be pending (aggregate has no data)"
    # the pending badge text lives in InvStatTile
    assert "BACKEND-PENDING" in src and "PHASE C" in src


def test_diagnostic_paragraph_removed_from_ui():
    src = _inv()
    # the old raw limitations dump must be gone from the render
    assert "data.limitations.join(' · ')" not in src, \
        "the raw diagnostic limitations paragraph must be removed from the UI"


def test_tile_style_matches_wireframe_invstattile():
    """Spec-by-reference: the ported tile carries the wireframe's signature
    tile styling (label uppercase 0.10em; value fontSize 22)."""
    src = _inv()
    k = src.index("function InvStatTile(")
    block = src[k:k + 1200]
    assert "letterSpacing: '0.10em'" in block, "label tracking must match the wireframe tile"
    assert "fontSize: 22" in block, "value size must match the wireframe tile"
    # the design authority uses the same signature
    d = _design()
    assert "letterSpacing: '0.10em'" in d and "fontSize: 22" in d
