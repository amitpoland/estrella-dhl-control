"""
test_phase_b_fold_retirement.py — Phase B FOLD retirement pins
(PROJECT_STATE DECISIONS "Phase B FOLD", 2026-07-03).

Replaces the former test_move_location_promotion.py. The standalone Move
Location page is RETIRED — its capability folded into the Inventory page as
the Move Stock modal (Lesson M relocation). These pins assert the retirement
is complete AND the modal is reachable via the Inventory action:
  - the page file is gone; window global gone; script tag gone; render block gone
  - move_location slug removed from nav + WIRED_PAGES; redirects to inventory
  - the Move Stock modal lives on the Inventory page, reachable via the action
  - net page count DECREASED (no new page/route)

String-level assertions against the static shell files (no server, no browser).
"""
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_V2 = _HERE.parent / "app" / "static" / "v2"

_INDEX      = _V2 / "index.html"
_COMPONENTS = _V2 / "components.jsx"
_MOCK_BADGE = _V2 / "mock-badge.jsx"
_INV_PAGE   = _V2 / "inventory-page.jsx"
_PZ_API     = _V2 / "pz-api.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


# ── 1. The standalone page is fully retired ──────────────────────────────────

def test_move_location_page_file_deleted():
    assert not (_V2 / "move-location-page.jsx").exists(), \
        "move-location-page.jsx must be deleted (Phase B FOLD)"


def test_no_script_tag_or_render_block_or_global():
    idx = _read(_INDEX)
    assert 'src="move-location-page.jsx"' not in idx, "script tag must be gone"
    assert "page === 'move_location'" not in idx, "render conditional must be gone"
    assert "<MoveLocationPage" not in idx, "render block must be gone"
    assert "MoveLocationPage" not in idx, "window global reference must be gone from the shell"


def test_move_location_removed_from_nav():
    body = _read(_COMPONENTS)
    i = body.index("NAV_TREE = [")
    j = body.index("];", i)
    nav = body[i:j]
    assert "id: 'move_location'" not in nav, "move_location nav child must be gone"
    assert "id: 'g_inventory'" not in nav, "g_inventory group collapsed to a flat Inventory entry"
    assert "id: 'inventory'" in nav, "a flat Inventory nav entry must remain"


def test_move_location_removed_from_wired_pages():
    src = _read(_MOCK_BADGE)
    start = src.index("const WIRED_PAGES")
    end = src.index("];", start)
    body = src[start:end]
    assert "'move_location'" not in body, "move_location must be out of WIRED_PAGES"
    assert "'inventory'" in body, "inventory must remain wired"


# ── 2. Stale-URL insurance: the slug redirects to inventory ──────────────────

def _redirect_body() -> str:
    src = _read(_INDEX)
    i = src.index("ROUTE_REDIRECTS = {")
    j = src.index("};", i)
    return src[i:j]


def test_move_location_redirects_to_inventory():
    body = _redirect_body()
    assert "move_location: 'inventory'" in body, \
        "retired /v2/move_location must redirect to inventory (stale-URL insurance)"
    assert "move_stock:" in body, "move_stock stays redirected (reserved for B×7-1b)"


# ── 3. The Move Stock modal is folded into the Inventory page ────────────────

def test_move_stock_modal_folded_into_inventory_page():
    src = _read(_INV_PAGE)
    assert "function MoveStockModal(" in src, "the Move Stock modal must live on the Inventory page"
    assert 'data-testid="btn-open-move-stock"' in src, "the Inventory hub must host the action"
    assert "<MoveStockModal onClose=" in src, "the hub must mount the modal"
    assert "MoveLocationPage" not in src, "no standalone move page component may remain"


def test_modal_wired_to_existing_transports_no_paste():
    src = _read(_INV_PAGE)
    for m in ("getWarehouseLocations", "getLocationInventory", "movePieceLocation"):
        assert f"window.PzApi.{m}" in src, f"modal must use PzApi.{m}"
    import re as _re
    k = src.index("function MoveStockModal(")
    end = src.index("function InventoryPage(", k)
    for tag in _re.findall(r"<input\b[^>]*>", src[k:end]):
        assert 'type="checkbox"' in tag, f"no paste input allowed in the modal: {tag}"


def test_pz_api_retains_move_transport():
    api = _read(_PZ_API)
    assert "movePieceLocation:" in api, "the move transport must remain (used by the modal)"
    assert "/inventory/pieces/${encodeURIComponent(pieceId)}/location" in api


# ── 4. Net page count decreased (Lesson M relocation, not addition) ──────────

def test_inventory_still_wired_and_flat():
    idx = _read(_INDEX)
    assert "<InventoryPage" in idx, "InventoryPage must still render"
    assert "page === 'inventory'" in idx
