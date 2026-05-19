"""test_dashboard_dhl_customs_error_boundary.py — UI resilience invariant.

Source-grep tests for the narrow ErrorBoundary applied around the
DHL Clearance and Customs Documents tabs in dashboard.html.

Pure file-level assertions; no JSX rendering needed.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
_DASHBOARD = _STATIC / "dashboard.html"
_DETAIL    = _STATIC / "shipment-detail.html"


@pytest.fixture(scope="module")
def dashboard_html() -> str:
    return _DASHBOARD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def detail_html() -> str:
    return _DETAIL.read_text(encoding="utf-8")


# ── ErrorBoundary component exists ───────────────────────────────────────────

def test_error_boundary_class_defined(dashboard_html):
    """A class-based React ErrorBoundary must exist in dashboard.html."""
    assert "class TabErrorBoundary extends React.Component" in dashboard_html


def test_error_boundary_implements_required_lifecycle(dashboard_html):
    """ErrorBoundary must implement BOTH getDerivedStateFromError (renders
    fallback) AND componentDidCatch (logs to console)."""
    assert "getDerivedStateFromError" in dashboard_html
    assert "componentDidCatch" in dashboard_html


def test_error_boundary_logs_to_console_not_remote(dashboard_html):
    """componentDidCatch must use console.error — no remote logging,
    no fetch, no mutation, no auto-retry."""
    # Find componentDidCatch body
    m = re.search(r"componentDidCatch\(error, info\) \{(.*?)\}\s*render", dashboard_html, re.DOTALL)
    assert m, "componentDidCatch body not found"
    body = m.group(1)
    assert "console.error" in body
    assert "fetch(" not in body
    assert "apiFetch(" not in body
    assert "setTimeout" not in body  # no auto-retry timer


# ── Fallback UI contract ─────────────────────────────────────────────────────

def test_fallback_test_id_present(dashboard_html):
    assert 'data-testid="tab-error-boundary-fallback"' in dashboard_html


def test_fallback_message_test_id_present(dashboard_html):
    assert 'data-testid="tab-error-boundary-message"' in dashboard_html


def test_fallback_headline_text(dashboard_html):
    assert "DHL / Customs tab failed to render" in dashboard_html


def test_fallback_instruction_text(dashboard_html):
    assert "Refresh the page or contact support with the browser console error." in dashboard_html


def test_fallback_no_auto_retry_button(dashboard_html):
    """Fallback must NOT contain any retry button / link / onClick that
    would re-trigger the crashing render."""
    # The fallback block starts at the data-testid and is bounded by
    # the closing of the conditional render.  Search a generous window.
    start = dashboard_html.find('data-testid="tab-error-boundary-fallback"')
    assert start > 0
    block = dashboard_html[start:start + 2000]
    assert "onClick" not in block, "fallback must not contain onClick"
    assert "<Btn" not in block,    "fallback must not contain action button"


# ── Wrapping invariants ──────────────────────────────────────────────────────

def test_dhl_clearance_page_wrapped(dashboard_html):
    """page==='dhl' must instantiate DhlClearancePage inside TabErrorBoundary."""
    pattern = re.compile(
        r"page\s*===\s*['\"]dhl['\"]\s*&&\s*<TabErrorBoundary>\s*<DhlClearancePage"
    )
    assert pattern.search(dashboard_html), (
        "DhlClearancePage must be wrapped: "
        "page === 'dhl' && <TabErrorBoundary><DhlClearancePage ...>"
    )


def test_customs_documents_page_wrapped(dashboard_html):
    """page==='documents' must instantiate CustomsDocumentsPage inside TabErrorBoundary."""
    pattern = re.compile(
        r"page\s*===\s*['\"]documents['\"]\s*&&\s*<TabErrorBoundary>\s*<CustomsDocumentsPage"
    )
    assert pattern.search(dashboard_html), (
        "CustomsDocumentsPage must be wrapped: "
        "page === 'documents' && <TabErrorBoundary><CustomsDocumentsPage ...>"
    )


# ── NEGATIVE invariants — unrelated tabs must NOT be wrapped ─────────────────

UNRELATED_TABS = {
    "dashboard":   "DashboardKanban",
    "shipments":   "DashboardPage",
    "accounting":  "PzAccountingPage",
    "wfirma_setup":"WfirmaExportPage",
    "reports":     "ReportsPage",
    "inventory":   "InventoryPage",
    "admin":       "AdminPage",
    "carriers":    "CarriersPage",
    "master":      "MasterDataPage",
}


@pytest.mark.parametrize("page_key,component", list(UNRELATED_TABS.items()))
def test_unrelated_tab_not_wrapped(dashboard_html, page_key, component):
    """Sales / PZ / Warehouse / Dashboard / Overview tab render sites
    must NOT be wrapped in TabErrorBoundary — scope is narrow."""
    # Pattern: page === '<key>' ... && <Component (no TabErrorBoundary between)
    pattern = re.compile(
        rf"page\s*===\s*['\"]{re.escape(page_key)}['\"]\s*&&\s*<TabErrorBoundary"
    )
    assert not pattern.search(dashboard_html), (
        f"Unrelated tab '{page_key}' (component {component}) must NOT "
        "be wrapped in TabErrorBoundary; scope is intentionally narrow"
    )


# ── Detail-page audit (no DHL/Customs container expected) ────────────────────

def test_shipment_detail_has_no_dhl_customs_page_component(detail_html):
    """shipment-detail.html does NOT have a top-level DHL/Customs page
    component (DhlClearancePage / CustomsDocumentsPage) — those live
    only in dashboard.html.  This test documents the current topology;
    if a future patch introduces such a component to shipment-detail,
    this test fails and prompts an explicit decision to wrap it."""
    assert "<DhlClearancePage" not in detail_html
    assert "<CustomsDocumentsPage" not in detail_html


# ── Backend untouched ────────────────────────────────────────────────────────

def test_no_backend_references_added():
    """The fix must be UI-only.  Confirm no new backend service / route
    files were modified or added as part of this patch."""
    # Source-grep: TabErrorBoundary must not appear in any .py file
    backend_root = Path(__file__).resolve().parent.parent / "app"
    leaks = []
    for p in backend_root.rglob("*.py"):
        try:
            if "TabErrorBoundary" in p.read_text(encoding="utf-8"):
                leaks.append(p.relative_to(backend_root).as_posix())
        except Exception:
            continue
    assert not leaks, f"TabErrorBoundary leaked into backend: {leaks}"
