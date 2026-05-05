"""
test_dashboard_sales_linkage_panel.py — UI exposure tests for the Sales
Linkage panel inside Batch detail.

Pattern matches test_agency_preclearance.py: read dashboard.html source as
text and assert specific substrings/markers exist. We do NOT execute JSX;
the test just confirms the panel is wired correctly so the bundle compiles
and renders the expected fields.

Backend logic / endpoint behaviour is covered by test_sales_linkage.py.
"""
from __future__ import annotations

from pathlib import Path


DASHBOARD = Path(
    "/Users/amitgupta/Downloads/CLI/service/app/static/dashboard.html"
)


def _src() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


# ── Tab registration ─────────────────────────────────────────────────────────

def test_sales_linkage_tab_registered_in_detail_tabs():
    """The 'Sales' tab must appear in the DETAIL_TABS list so users can open
    the Sales Linkage panel from Batch detail."""
    src = _src()
    # Locate the DETAIL_TABS array and assert 'Sales' appears in it.
    assert "DETAIL_TABS" in src, "DETAIL_TABS array missing"
    # Pull the line that defines DETAIL_TABS and confirm 'Sales' in that line
    for line in src.splitlines():
        if "const DETAIL_TABS" in line and "[" in line:
            assert "'Sales'" in line, (
                "Sales tab is not registered in DETAIL_TABS: " + line
            )
            return
    raise AssertionError("Could not locate DETAIL_TABS array definition")


# ── Endpoint wiring ──────────────────────────────────────────────────────────

def test_sales_linkage_endpoint_is_wired():
    """The panel must call GET /api/v1/sales/linkage/{batch_id}."""
    src = _src()
    # The fetch call uses an interpolated batch id — match the literal path.
    assert "/api/v1/sales/linkage/" in src
    # And the loadSalesLinkage callback must exist
    assert "loadSalesLinkage" in src
    # The fetch must be triggered when the Sales tab becomes active
    assert "activeTab === 'Sales'" in src


def test_sales_linkage_state_hooks_present():
    """React state for the linkage response and loading flag must exist."""
    src = _src()
    assert "salesLinkage" in src
    assert "salesLinkageLoading" in src
    assert "setSalesLinkage" in src
    assert "setSalesLinkageLoading" in src


# ── Required fields rendered ─────────────────────────────────────────────────

def test_panel_renders_ready_for_invoice_flag():
    src = _src()
    assert "ready_for_invoice" in src
    assert "sales-linkage-ready-flag" in src


def test_panel_renders_blocked_flag():
    """The explicit `blocked` boolean from the linkage response must surface."""
    src = _src()
    assert "sales-linkage-blocked-flag" in src
    assert "blocked: " in src or "blocked:" in src


def test_panel_renders_blocking_reasons():
    """blocking_reasons from the response must be displayed (with audit_warnings
    as fallback when blocking_reasons is empty in preview mode)."""
    src = _src()
    assert "sales-linkage-blocking-reasons" in src
    assert "blocking_reasons" in src
    assert "Blocking reasons" in src
    # Audit warnings fallback label is the alternate header
    assert "Audit warnings" in src


# ── Summary counts ──────────────────────────────────────────────────────────

def test_panel_renders_summary_counts():
    """summary.total / ready / pending_dispatch / not_ready / missing_scan must
    all be exposed in the UI."""
    src = _src()
    # Locate the linkage summary card and confirm all 5 counter keys appear
    for key in ("summary.total", "summary.ready", "summary.pending_dispatch",
                "summary.not_ready", "summary.missing_scan"):
        # The code uses `summary.X ?? 0` — match by substring
        assert key in src, f"summary key not surfaced: {key}"


def test_panel_shows_total_label():
    src = _src()
    # The text label "Total:" appears in the summary header strip
    assert "Total:" in src


# ── Per-row fields ──────────────────────────────────────────────────────────

def test_panel_renders_per_row_required_fields():
    """Each row must show product_code, design_no, scan code(s), warehouse_status,
    current_location."""
    src = _src()
    # Field accessors on each item:
    assert "r.product_code" in src
    assert "r.design_no" in src
    assert "r.matched_scan_codes" in src        # scan_code grouping
    assert "r.warehouse_status" in src
    assert "r.current_location" in src


def test_panel_groups_rows_by_client():
    """Rows must be grouped by client_name + client_ref."""
    src = _src()
    assert "client_name" in src
    assert "client_ref" in src
    # A grouping container (one card per client) is built
    assert "groups[key]" in src or "groupList" in src


# ── Empty state handling ────────────────────────────────────────────────────

def test_panel_handles_empty_sales_rows():
    """When no sales packing lines exist, the panel must show an empty-state
    message rather than rendering nothing or crashing."""
    src = _src()
    # Either of these strings indicates the empty branch is wired
    assert "No sales packing lines found" in src


def test_panel_handles_loading_state():
    """A loading state must exist so the panel doesn't show stale or empty
    data while the fetch is in flight."""
    src = _src()
    assert "Loading linkage" in src or "salesLinkageLoading" in src


def test_panel_handles_error_state():
    """If the endpoint fails, the panel must display the error rather than
    appearing empty."""
    src = _src()
    assert "Sales linkage failed" in src


# ── Compile-safety: dashboard reads as UTF-8 ────────────────────────────────

def test_dashboard_html_is_readable_and_nonempty():
    """Smoke check that the file exists and parses as UTF-8 — catches
    accidental binary corruption from edits."""
    src = _src()
    assert len(src) > 1000, "dashboard.html unexpectedly small"
    # The Sales panel branch must exist
    assert "activeTab === 'Sales'" in src


def test_dashboard_html_braces_balanced():
    """A coarse compile-safety check: '{' and '}' counts match. Catches
    most JSX truncation bugs introduced by edits to this large file."""
    src = _src()
    opens = src.count("{")
    closes = src.count("}")
    assert opens == closes, f"unbalanced braces: {{={opens} }}={closes}"
