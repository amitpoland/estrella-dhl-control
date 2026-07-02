"""slice B×7-1 — Move Location promotion pins (reworked per operator decision (i)).

Pins the first inventory-family promotion per the dhl/Sprint-31 playbook:
wire live -> NAV_TREE -> remove redirect -> WIRED_PAGES -> pin with test.
Built as "Move Stock", RENAMED move_stock -> move_location: the page is a
physical location (shelf/zone) metadata helper and does NOT change inventory
state. The 'move_stock' slug returns to ROUTE_REDIRECTS and is reserved for
the document-event-driven business stage promotion (slice B×7-1b).
Cites PROJECT_STATE DECISIONS "slice B×7-1" + "B×7-1 rework" (2026-07-02).

String-level assertions against the static shell files (same technique as
test_sprint31_dhl_shell_wiring.py) — no server, no browser.
"""
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_V2 = _HERE.parent / "app" / "static" / "v2"

_INDEX      = _V2 / "index.html"
_COMPONENTS = _V2 / "components.jsx"
_MOCK_BADGE = _V2 / "mock-badge.jsx"
_PAGE       = _V2 / "move-location-page.jsx"
_PZ_API     = _V2 / "pz-api.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


# ── 1. WIRED_PAGES ───────────────────────────────────────────────────────────

def test_move_location_in_wired_pages():
    src = _read(_MOCK_BADGE)
    start = src.index("const WIRED_PAGES")
    end = src.index("];", start)
    body = src[start:end]
    assert "'move_location'" in body, "move_location must be in WIRED_PAGES (live, no MOCK badge)"
    assert "'move_stock'" not in body, (
        "move_stock must NOT be in WIRED_PAGES — the name is reserved for the "
        "B×7-1b business promotion (operator decision (i))"
    )


def test_existing_wired_pages_preserved():
    src = _read(_MOCK_BADGE)
    start = src.index("const WIRED_PAGES")
    end = src.index("];", start)
    body = src[start:end]
    for page in ("proforma", "proforma_search", "inbox", "inventory", "dhl",
                 "shipments", "automation", "intelligence", "documents",
                 "proforma_detail", "wfirma_setup", "master", "carriers",
                 "dashboard", "api_status", "diagnostics", "coverage", "detail"):
        assert f"'{page}'" in body, f"WIRED_PAGES entry '{page}' must remain"


# ── 2. ROUTE_REDIRECTS ───────────────────────────────────────────────────────

def _redirect_body() -> str:
    src = _read(_INDEX)
    i = src.index("ROUTE_REDIRECTS = {")
    j = src.index("};", i)
    return src[i:j]


def test_move_stock_redirect_restored():
    """Operator decision (i): move_stock returns to the redirect map — it is
    the ACTIVE-PLANNED business promotion (B×7-1b), not this location helper."""
    body = _redirect_body()
    assert "move_stock:" in body, (
        "move_stock redirect must be RESTORED (reserved for the B×7-1b business promotion)"
    )


def test_twelve_redirects_preserved():
    body = _redirect_body()
    for slug in ("actions", "proposals", "email_queue", "reservation", "shipping",
                 "scanner", "identity", "sample_out", "sample_return",
                 "goods_return", "return_prod", "move_stock"):
        assert f"{slug}:" in body, f"redirect entry '{slug}' must be retained (stale-URL insurance)"


def test_move_location_not_redirected():
    """The promoted slug must route to its own page, not be swallowed by a redirect."""
    body = _redirect_body()
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("/*"):
            continue
        assert not stripped.startswith("move_location"), (
            f"move_location must not appear in ROUTE_REDIRECTS — found: {stripped!r}"
        )


def test_dhl_redirect_still_absent():
    body = _redirect_body()
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("/*"):
            continue
        assert not stripped.startswith("dhl"), "dhl redirect must not resurface"


# ── 3. Render block + script tag + file on disk ──────────────────────────────

def test_index_html_renders_move_location_page():
    src = _read(_INDEX)
    assert "page === 'move_location'" in src, "move_location render conditional missing"
    assert "<MoveLocationPage />" in src, "render block must mount MoveLocationPage"


def test_index_html_loads_move_location_jsx():
    src = _read(_INDEX)
    assert 'src="move-location-page.jsx"' in src, "script tag for move-location-page.jsx missing"


def test_move_location_page_file_exists():
    assert _PAGE.exists(), "move-location-page.jsx must exist on disk"
    assert "window.MoveLocationPage = MoveLocationPage" in _read(_PAGE), \
        "MoveLocationPage must be exported as a window global"


def test_render_block_declares_metadata_only_and_sequential():
    src = _read(_INDEX)
    k = src.index("{!viewerDoc && page === 'move_location'")
    block = src[k - 600: k + 900]
    assert "sequential" in block.lower(), (
        "the move_location route block must declare the sequential per-piece "
        "mechanics (no atomic-batch claim)"
    )
    assert "does NOT change inventory state" in block, (
        "the Move Location subtitle must declare metadata-only semantics "
        "(operator decision (i))"
    )


# ── 4. NAV_TREE ──────────────────────────────────────────────────────────────

def _nav_body() -> str:
    src = _read(_COMPONENTS)
    i = src.index("NAV_TREE = [")
    j = src.index("];", i)
    return src[i:j]


def test_g_inventory_group_with_move_location_child():
    body = _nav_body()
    assert "id: 'g_inventory'" in body, "g_inventory NAV_TREE group missing"
    assert "defaultId: 'inventory'" in body, "g_inventory must default to the inventory hub"
    assert "id: 'move_location'" in body, "move_location NAV_TREE child missing"
    assert "'Move Location'" in body, "nav label must read 'Move Location'"


def test_move_stock_not_in_nav_tree():
    """The reserved business-promotion slug must not surface in nav until B×7-1b ships."""
    body = _nav_body()
    assert "id: 'move_stock'" not in body, (
        "move_stock must not be a NAV_TREE entry — reserved for B×7-1b"
    )


def test_inventory_still_in_nav_tree():
    body = _nav_body()
    assert "id: 'inventory'" in body, "id: 'inventory' must remain (nav-pin preservation)"


def test_other_top_level_nav_entries_preserved():
    body = _nav_body()
    for page_id in ("dashboard", "inbox", "shipments", "dhl", "proforma",
                    "documents", "accounting", "reports", "g_setup"):
        assert f"id: '{page_id}'" in body, f"NAV_TREE entry '{page_id}' must remain"


# ── 5. Endpoint whitelist ────────────────────────────────────────────────────

def test_page_uses_only_pzapi_transport():
    src = _read(_PAGE)
    assert "fetch(" not in src, "page must not call fetch directly — PzApi only"
    assert "window.PzApi.getInventoryState" in src, "page must read via PzApi.getInventoryState"
    assert "window.PzApi.movePieceLocation" in src, "page must write via PzApi.movePieceLocation"


def test_pz_api_has_exactly_the_two_endpoints():
    src = _read(_PZ_API)
    assert "/inventory/state/${encodeURIComponent(batchId)}" in src, \
        "getInventoryState must target /api/v1/inventory/state/{batch_id}"
    assert "/inventory/pieces/${encodeURIComponent(pieceId)}/location" in src, \
        "movePieceLocation must target /api/v1/inventory/pieces/{id}/location"


def test_move_transport_refuses_blank_operator():
    src = _read(_PZ_API)
    k = src.index("movePieceLocation:")
    block = src[k:k + 1200]
    assert "_resolveOperator()" in block, "movePieceLocation must resolve the operator"
    assert "Operator name required" in block, "blank operator must refuse to POST"


# ── 6. Idempotency + sequential-loop mechanics ───────────────────────────────

def test_per_piece_idempotency_key():
    src = _read(_PAGE)
    assert "crypto.randomUUID()" in src, "each move must carry its own idempotency key"
    api = _read(_PZ_API)
    assert "idempotency_key" in api, "transport must send idempotency_key in the body"


def test_sequential_single_piece_loop():
    src = _read(_PAGE)
    assert "for (const" in src, "submit must loop pieces sequentially"
    assert "await window.PzApi.movePieceLocation" in src, \
        "each iteration must await its own single-piece move"


def test_honest_batch_banner():
    src = _read(_PAGE)
    assert "Batch = sequential single-piece moves (backend is per-piece)" in src, \
        "the honest-mechanics banner text must be present verbatim"


# ── 7. Error-state + synthetic + testids ─────────────────────────────────────

def test_all_five_error_codes_rendered_distinctly():
    src = _read(_PAGE)
    for code in ("INVALID_INPUT", "PIECE_NOT_FOUND", "WRONG_STATE",
                 "DB_UNAVAILABLE", "MIGRATION_PENDING"):
        assert code in src, f"error code {code} must have distinct rendering"
    assert "20260512_002516_idempotency_key" in src, \
        "MIGRATION_PENDING rendering must name the migration (renamed applied form)"
    assert "WAREHOUSE_STOCK" in src, \
        "WRONG_STATE rendering must explain the WAREHOUSE_STOCK requirement"


def test_migration_file_renamed_to_applied_form():
    """The draft was applied to the verify-tree warehouse.db and renamed in the
    same commit as this rework (PROJECT_STATE DECISIONS 'B×7-1 rework')."""
    mig_dir = _HERE.parent / "app" / "db" / "migrations"
    assert (mig_dir / "20260512_002516_idempotency_key.py").exists(), \
        "applied migration 20260512_002516_idempotency_key.py must exist"
    assert not (mig_dir / "draft_20260512_002516_idempotency_key.py.draft").exists(), \
        "draft form must be gone (renamed, not duplicated)"


def test_synthetic_rows_selection_disabled():
    src = _read(_PAGE)
    assert "synthetic" in src, "page must recognise synthetic (C13A projection) rows"
    k = src.index("p.synthetic")
    block = src[k - 200: k + 900]
    assert "disabled" in block, "synthetic rows must have their checkbox disabled"
    assert "not movable" in block, "synthetic disable must carry a reason"


def test_empty_state_is_honest():
    src = _read(_PAGE)
    assert "ms-empty" in src, "empty-state testid missing"
    assert "No pieces in this batch" in src, "honest empty-state text missing"


def test_required_testids_present():
    src = _read(_PAGE)
    for tid in ("move-location-root", "ms-batch-input", "ms-load", "ms-table",
                "ms-filter", "ms-destination", "ms-note", "ms-submit",
                "ms-result-row", "ms-banner", "ms-empty", "ms-row-checkbox"):
        assert f'data-testid="{tid}"' in src, f"data-testid '{tid}' missing"


def test_wireframe_stub_retired_no_name_collision():
    """B×7-1 defect fix: wireframe-update.jsx loads AFTER the page script, so a
    surviving stub silently overwrites the live page on window (last-write-wins
    — the slice-03 ReportsPage defect class). The retired MoveStockPage stub
    must stay deleted, and MoveLocationPage must have exactly one owner."""
    wf = _read(_V2 / "wireframe-update.jsx")
    assert "function MoveStockPage(" not in wf, \
        "wireframe-update.jsx must not define MoveStockPage (stub retired in B×7-1)"
    assert "function MoveLocationPage(" not in wf, \
        "wireframe-update.jsx must not define MoveLocationPage (single-owner rule)"
    # the export list must not re-export either name (comments are fine)
    exports = wf[wf.index("Object.assign(window,"):]
    live_lines = [l for l in exports.split("\n") if not l.strip().startswith("//")]
    assert not any("MoveStockPage" in l for l in live_lines), \
        "wireframe-update.jsx export list must not carry MoveStockPage"
    assert not any("MoveLocationPage" in l for l in live_lines), \
        "wireframe-update.jsx export list must not carry MoveLocationPage"
    # exactly one definition across the v2 tree owns the name
    page = _read(_PAGE)
    assert "function MoveLocationPage(" in page and "window.MoveLocationPage = MoveLocationPage" in page


def test_no_mandatory_scan_language():
    """The operator UX rule: scanner optional, NEVER required."""
    src = _read(_PAGE).lower()
    assert "scan is ever required" in src or "never required" in src, \
        "page must state that scanning is optional"
    for forbidden in ("scan required", "must scan", "scan first"):
        assert forbidden not in src, f"forbidden mandatory-scan phrasing: {forbidden!r}"
