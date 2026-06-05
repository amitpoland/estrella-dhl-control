"""
test_sprint30_inventory_shell_wiring.py
========================================
Sprint 30 regression tests: Inventory V2 wired into the main V2 shell.

These are source-grep tests — they verify the JSX source files contain the
correct wiring, exports, testids, and API endpoint references, and that NO
write-capable patterns appear in the inventory page.

References:
  service/app/static/v2/mock-badge.jsx    — WIRED_PAGES list
  service/app/static/v2/inventory-page.jsx — live hub exports + endpoints
"""
from __future__ import annotations

from pathlib import Path

_MOCK_BADGE  = Path(__file__).parent.parent / "app" / "static" / "v2" / "mock-badge.jsx"
_INV_PAGE    = Path(__file__).parent.parent / "app" / "static" / "v2" / "inventory-page.jsx"


# ══════════════════════════════════════════════════════════════════════════════
# A. mock-badge.jsx — 'inventory' in WIRED_PAGES
# ══════════════════════════════════════════════════════════════════════════════

def test_inventory_in_wired_pages():
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    assert "'inventory'" in src, (
        "mock-badge.jsx WIRED_PAGES must include 'inventory'"
    )


def test_wired_pages_array_contains_inventory():
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    # Must be inside the array literal, not just a comment
    idx = src.index("WIRED_PAGES")
    arr_start = src.index("[", idx)
    arr_end   = src.index("]", arr_start)
    arr_body  = src[arr_start:arr_end]
    assert "inventory" in arr_body, (
        "'inventory' must be inside the WIRED_PAGES array literal"
    )


def test_proforma_and_inbox_still_wired():
    """Regression: existing wired pages must remain wired."""
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    idx = src.index("WIRED_PAGES")
    arr_start = src.index("[", idx)
    arr_end   = src.index("]", arr_start)
    arr_body  = src[arr_start:arr_end]
    assert "proforma" in arr_body, "proforma must remain in WIRED_PAGES"
    assert "inbox"    in arr_body, "inbox must remain in WIRED_PAGES"


# ══════════════════════════════════════════════════════════════════════════════
# B. inventory-page.jsx — exports and structure
# ══════════════════════════════════════════════════════════════════════════════

def test_inventory_page_exports_window_inventory_page():
    src = _INV_PAGE.read_text(encoding="utf-8")
    assert "window.InventoryPage" in src, (
        "inventory-page.jsx must export window.InventoryPage"
    )


def test_inventory_page_exports_window_document_viewer():
    src = _INV_PAGE.read_text(encoding="utf-8")
    assert "window.DocumentViewerPage" in src, (
        "inventory-page.jsx must export window.DocumentViewerPage (shell-global)"
    )


def test_inventory_hub_root_testid_present():
    src = _INV_PAGE.read_text(encoding="utf-8")
    assert 'data-testid="inventory-hub-root"' in src, (
        "InventoryPage must have data-testid='inventory-hub-root'"
    )


def test_uses_estrella_shared_api_fetch():
    src = _INV_PAGE.read_text(encoding="utf-8")
    assert "window.EstrellaShared.apiFetch" in src or \
           "EstrellaShared.apiFetch" in src, (
        "inventory-page.jsx must use window.EstrellaShared.apiFetch"
    )


# ══════════════════════════════════════════════════════════════════════════════
# C. inventory-page.jsx — all 8 read-only endpoints present
# ══════════════════════════════════════════════════════════════════════════════

ENDPOINTS = [
    "/api/v1/inventory/stage2/aggregate",
    "/api/v1/inventory/state/",
    "/api/v1/inventory/pieces/",
    "/api/v1/warehouse/inventory/",
    "/api/v1/warehouse/locations",
    "/api/v1/warehouse/audit-summary/",
    "/api/v1/warehouse/audit/",
]


def test_all_read_only_endpoints_present():
    src = _INV_PAGE.read_text(encoding="utf-8")
    for ep in ENDPOINTS:
        assert ep in src, (
            f"inventory-page.jsx must reference endpoint: {ep}"
        )


def test_location_detail_endpoint_present():
    src = _INV_PAGE.read_text(encoding="utf-8")
    assert "/inventory" in src and "/inventory" in src, (
        "location detail endpoint /warehouse/locations/{code}/inventory must be present"
    )
    # More specific check for the locations/{code}/inventory pattern
    assert "locations/" in src and "/inventory`" in src, (
        "locations/{code}/inventory endpoint must be present (with template literal)"
    )


# ══════════════════════════════════════════════════════════════════════════════
# D. inventory-page.jsx — NO write-capable patterns
# ══════════════════════════════════════════════════════════════════════════════

FORBIDDEN_WRITE_PATTERNS = [
    "method: 'POST'",
    'method: "POST"',
    "method: 'PUT'",
    'method: "PUT"',
    "method: 'DELETE'",
    'method: "DELETE"',
    "method: 'PATCH'",
    'method: "PATCH"',
    "/api/v1/inventory/adjust",
    "/api/v1/inventory/move",
    "/api/v1/inventory/write",
    "/api/v1/warehouse/write",
    "/api/v1/warehouse/scan",   # scan-in is a write — not allowed here
]


def test_no_write_http_methods_in_inventory_hub():
    src = _INV_PAGE.read_text(encoding="utf-8")
    # Only check the InventoryPage IIFE section (after DocumentViewerPage)
    # DocumentViewerPage is a UI component with no network calls; check the IIFE
    iife_start = src.index("(function ()")
    iife_src = src[iife_start:]
    for pattern in FORBIDDEN_WRITE_PATTERNS:
        assert pattern not in iife_src, (
            f"inventory-page.jsx IIFE must not contain write pattern: {pattern!r}"
        )


def test_read_only_disclaimer_present():
    """Each live panel must declare it makes no write calls."""
    src = _INV_PAGE.read_text(encoding="utf-8")
    assert "Read-only. No write calls are made from this panel." in src, (
        "At least one panel must carry the read-only disclaimer"
    )
    count = src.count("Read-only. No write calls are made from this panel.")
    assert count >= 4, (
        f"Expected ≥4 panels with read-only disclaimer, found {count}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# E. inventory-page.jsx — data-testids for key interactive elements
# ══════════════════════════════════════════════════════════════════════════════

# Panel testids are passed as `testid=` prop to InvPanel (which renders data-testid={testid}).
# Button/input testids are set directly as data-testid="...".
PANEL_TESTIDS = [
    "panel-stage2",
    "panel-batch",
    "panel-piece",
    "panel-locations",
    "panel-audit",
]

ELEMENT_TESTIDS = [
    "btn-refresh-stage2",
    "input-batch-id",
    "btn-batch-state",
    "input-piece-id",
    "btn-lookup-piece",
    "input-scan-code",
    "btn-lookup-scan",
    "input-audit-batch-id",
    "btn-audit-summary",
    "btn-audit-full",
]


def test_required_testids_present():
    src = _INV_PAGE.read_text(encoding="utf-8")
    # Panels: passed as testid="xxx" prop to InvPanel
    missing_panels = [t for t in PANEL_TESTIDS if f'testid="{t}"' not in src]
    # Interactive elements: set as data-testid="xxx" directly
    missing_elements = [t for t in ELEMENT_TESTIDS if f'data-testid="{t}"' not in src]
    missing = missing_panels + missing_elements
    assert not missing, (
        f"inventory-page.jsx is missing testids: {missing}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# F. index.html still renders InventoryPage (not accidentally removed)
# ══════════════════════════════════════════════════════════════════════════════

_INDEX_HTML = Path(__file__).parent.parent / "app" / "static" / "v2" / "index.html"


def test_index_html_renders_inventory_page():
    src = _INDEX_HTML.read_text(encoding="utf-8")
    assert "InventoryPage" in src, (
        "index.html must still render <InventoryPage> for the inventory route"
    )


def test_index_html_loads_inventory_page_jsx():
    src = _INDEX_HTML.read_text(encoding="utf-8")
    assert "inventory-page.jsx" in src, (
        "index.html must load inventory-page.jsx via a script tag"
    )


def test_mock_banner_not_shown_for_inventory():
    """Verify WIRED_PAGES contains inventory so mock-banner is suppressed."""
    badge_src = _MOCK_BADGE.read_text(encoding="utf-8")
    idx = badge_src.index("WIRED_PAGES")
    arr_start = badge_src.index("[", idx)
    arr_end   = badge_src.index("]", arr_start)
    wired = badge_src[arr_start:arr_end]
    assert "inventory" in wired, (
        "inventory must be in WIRED_PAGES so mock-banner is suppressed"
    )
