"""test_shipment_detail_dhl_customs_tab.py — DHL/Customs tab on shipment-detail.

Source-grep invariants confirming:
  - DETAIL_TABS still includes 'DHL / Customs'
  - There is now a render branch `activeTab === 'DHL / Customs' && ...`
    (root cause of the prior black-screen: missing render block).
  - TabErrorBoundary class exists in shipment-detail.html.
  - The DHL/Customs render branch is wrapped in TabErrorBoundary.
  - Unrelated tabs (Overview, Documents, Warehouse, Sales, PZ / Accounting,
    Timeline, Intelligence, Proposals) are NOT wrapped — scope narrow.
  - Fallback panel test-ids + required text are present.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_DETAIL = (Path(__file__).resolve().parent.parent
           / "app" / "static" / "shipment-detail.html")


@pytest.fixture(scope="module")
def html() -> str:
    return _DETAIL.read_text(encoding="utf-8")


# ── Tab inventory unchanged ──────────────────────────────────────────────────

def test_detail_tabs_still_includes_dhl_customs(html):
    assert "'DHL / Customs'" in html, "DHL / Customs button removed from DETAIL_TABS"


# ── Missing-render-block bug FIXED ──────────────────────────────────────────

def test_dhl_customs_tab_has_render_branch(html):
    """The exact root cause of the black screen: a render branch must
    now exist for activeTab === 'DHL / Customs'."""
    pattern = re.compile(
        r"activeTab\s*===\s*['\"]DHL / Customs['\"]\s*&&"
    )
    assert pattern.search(html), (
        "shipment-detail.html still lacks `{activeTab === 'DHL / Customs' && …}` "
        "render block — that absence is the black-screen root cause"
    )


def test_dhl_customs_render_branch_not_wrapped_during_minimization(html):
    """During structural minimization the TabErrorBoundary wrap is
    INTENTIONALLY removed so we can determine whether the boundary
    itself was the issue (it failed to catch the original crash).
    Once the offending block is identified, the boundary returns and
    this test flips back to the wrap-required form."""
    pattern = re.compile(
        r"activeTab\s*===\s*['\"]DHL / Customs['\"]\s*&&\s*\(\s*<TabErrorBoundary>",
        re.DOTALL,
    )
    assert not pattern.search(html), (
        "DHL / Customs branch must NOT be wrapped in TabErrorBoundary "
        "during the structural minimization diagnostic"
    )


# ── TabErrorBoundary class present + contract ───────────────────────────────

def test_error_boundary_class_defined(html):
    assert "class TabErrorBoundary extends React.Component" in html


def test_error_boundary_implements_required_lifecycle(html):
    assert "getDerivedStateFromError" in html
    assert "componentDidCatch" in html


def test_error_boundary_no_remote_logging_or_retry(html):
    m = re.search(
        r"componentDidCatch\(error, info\) \{(.*?)\}\s*render",
        html, re.DOTALL,
    )
    assert m, "componentDidCatch body not found"
    body = m.group(1)
    assert "console.error" in body
    assert "fetch(" not in body
    assert "apiFetch(" not in body
    assert "setTimeout" not in body


# ── Fallback UI contract ────────────────────────────────────────────────────

def test_fallback_test_ids_present(html):
    assert 'data-testid="tab-error-boundary-fallback"' in html
    assert 'data-testid="tab-error-boundary-message"' in html


def test_fallback_headline_text(html):
    assert "DHL / Customs tab failed to render" in html


def test_fallback_instruction_text(html):
    assert "Refresh the page or contact support with the browser console error." in html


# ── DHL/Customs panel — STRUCTURAL MINIMIZATION (active diagnosis) ──────────
# The full DHL/Customs panel was reduced to a single inert <div> while we
# isolate why the original content white-screened the React subtree
# without firing the TabErrorBoundary fallback.  These tests document
# the current minimal contract; once the binary-search reintroduction
# finds the offending block, the full panel returns and these tests
# are restored to the richer state-set version.

def test_dhl_customs_minimal_panel_test_id_present(html):
    assert 'data-testid="detail-tab-dhl-customs-minimal"' in html


def test_dhl_customs_minimal_panel_renders_inert_marker(html):
    assert "DHL TAB LIVE" in html


def test_dhl_customs_minimal_panel_uses_no_external_components(html):
    """During minimization the branch must reference NO external React
    components — no <Card>, no <SectionHeader>, no <TabErrorBoundary>,
    no IIFE.  This guarantees that if the white screen still happens
    with the minimized branch, the cause is the conditional / parent /
    ancestor — NOT the panel content."""
    # Slice between the conditional opener and its closer
    start = html.find("{activeTab === 'DHL / Customs' && (")
    assert start > 0
    next_branch = html.find("{activeTab === 'Timeline' &&", start)
    assert next_branch > start
    block = html[start:next_branch]
    forbidden = ("<Card", "<SectionHeader", "<TabErrorBoundary", "(() =>", ".map(")
    leaked = [token for token in forbidden if token in block]
    assert not leaked, (
        f"minimal DHL/Customs branch contains external refs: {leaked}"
    )


# ── Scope discipline: other tabs NOT wrapped ────────────────────────────────

UNRELATED_TABS = [
    "Overview", "Documents", "Warehouse", "Sales",
    "PZ / Accounting", "Timeline", "Intelligence", "Proposals",
]


@pytest.mark.parametrize("tab", UNRELATED_TABS)
def test_unrelated_tab_not_wrapped_in_boundary(html, tab):
    """Each unrelated tab must NOT have <TabErrorBoundary> immediately
    after its activeTab === '…' && opening."""
    escaped = re.escape(tab)
    bad = re.compile(
        rf"activeTab\s*===\s*['\"]{escaped}['\"]\s*&&\s*<TabErrorBoundary"
    )
    assert not bad.search(html), (
        f"Tab '{tab}' is wrapped in TabErrorBoundary; scope must be narrow"
    )


# ── No new fetches / backend coupling ───────────────────────────────────────

def test_no_new_apifetch_in_dhl_customs_render_branch(html):
    """The new render branch must NOT add any apiFetch / fetch — it
    surfaces dhlReadiness which is already loaded by an existing
    useEffect."""
    # Slice between the opening marker and the next sibling tab branch.
    start_marker = "{activeTab === 'DHL / Customs' && ("
    start = html.find(start_marker)
    assert start > 0
    end_marker = "{activeTab === 'Timeline' &&"
    end = html.find(end_marker, start)
    assert end > start
    segment = html[start:end]
    assert "apiFetch(" not in segment
    assert "fetch('" not in segment
    assert 'fetch("' not in segment
    # Also no AUTO_* references, no SMTP, no token leaks
    assert "YES_" not in segment
    assert "AUTO_" not in segment


# ── No backend reference for boundary class itself ──────────────────────────

def test_diagnostic_v2_build_marker_present(html):
    """Top-of-page build marker rendered as first child of BatchDetailPage
    render output.  Visible immediately on page load, regardless of tab
    state or scroll position."""
    assert 'data-testid="shipment-detail-build-marker"' in html
    assert "SHIPMENT DETAIL BUILD diagnostic-v2" in html


def test_diagnostic_v2_active_tab_banner_outside_tab_branches(html):
    """Always-visible activeTab diagnostic must be OUTSIDE every
    `activeTab === '…'` conditional — i.e. it renders regardless of
    which tab is active."""
    assert 'data-testid="active-tab-diagnostic-v2"' in html
    assert 'data-testid="active-tab-diagnostic-v2-raw"' in html
    assert 'data-testid="active-tab-diagnostic-v2-json"' in html
    assert 'data-testid="active-tab-diagnostic-v2-match"' in html

    # Verify the v2 banner is OUTSIDE every tab branch (not contained
    # inside any `{activeTab === '…' && …}` block).
    v2_pos = html.find('data-testid="active-tab-diagnostic-v2"')
    assert v2_pos > 0
    # Walk back from v2_pos and find the most recent `activeTab === '`.
    # If it appears AFTER the most recent unmatched `&&` opener that
    # contains v2, the banner would be inside that branch.  Simpler
    # invariant: confirm v2 sits BEFORE the first `{activeTab === '` in
    # the file (so it precedes ALL tab branches).
    first_branch = html.find("{activeTab === '")
    assert 0 < v2_pos < first_branch, (
        "active-tab-diagnostic-v2 must appear BEFORE any tab branch "
        f"(v2_pos={v2_pos}, first_branch={first_branch})"
    )


def test_diagnostic_v2_dhl_customs_branch_marker_replaced_by_minimization(html):
    """The dhl-customs-render-mounted-v2 marker (and the boundary it
    was inside) were removed as part of the structural-minimization
    diagnostic.  The minimal `<div>DHL TAB LIVE</div>` replaces the
    entire subtree.  When the offending block is found, the boundary
    + this marker return and this test flips back."""
    branch_start = html.find("{activeTab === 'DHL / Customs' && (")
    next_branch = html.find("{activeTab === '", branch_start + 5)
    assert 0 < branch_start < next_branch
    block = html[branch_start:next_branch]
    assert 'dhl-customs-render-mounted-v2' not in block, (
        "during minimization the v2 mount marker must not be inside "
        "the DHL/Customs branch (it lived inside the removed full panel)"
    )


def test_diagnostic_v1_active_tab_banner_present(html):
    """Temporary diagnostic — operator-visible activeTab banner under
    the tab strip.  Remove on next deploy unless operator approves
    keeping it."""
    assert 'data-testid="active-tab-diagnostic"' in html
    assert 'data-testid="active-tab-diagnostic-raw"' in html
    assert 'data-testid="active-tab-diagnostic-json"' in html
    assert 'data-testid="active-tab-diagnostic-match"' in html


def test_diagnostic_v1_dhl_customs_mount_marker_replaced_by_minimization(html):
    """The v1/v2 mount marker was inside the now-removed full panel.
    Structural minimization replaces it with the inert
    'DHL TAB LIVE' div.  Same intent (prove branch fired) — different
    test-id family."""
    assert "DHL TAB LIVE" in html
    assert 'data-testid="detail-tab-dhl-customs-minimal"' in html


def test_tab_label_and_render_branch_strings_identical():
    """The exact tab label in DETAIL_TABS and the exact string in the
    render branch conditional MUST be byte-identical.  Strict equality
    fails on any whitespace or unicode variance."""
    src = _DETAIL.read_text(encoding="utf-8")
    # Pull tab label from DETAIL_TABS array
    m1 = re.search(r"DETAIL_TABS\s*=\s*\[(.+?)\];", src, re.DOTALL)
    assert m1, "DETAIL_TABS array not found"
    assert "'DHL / Customs'" in m1.group(1), (
        "DETAIL_TABS label changed; render branch may now mismatch"
    )
    # Pull render branch string
    m2 = re.search(
        r"\{activeTab\s*===\s*'(DHL / Customs)'\s*&&", src
    )
    assert m2, "render branch missing"
    # Strict equality check (no Unicode lookalikes, no extra whitespace)
    label_from_array = "DHL / Customs"
    label_from_branch = m2.group(1)
    assert label_from_array == label_from_branch, (
        f"label mismatch: array={label_from_array!r} vs branch={label_from_branch!r}"
    )


def test_tab_error_boundary_isolated_to_frontend():
    """TabErrorBoundary must remain frontend-only — never appear in a
    backend .py module."""
    backend_root = (Path(__file__).resolve().parent.parent / "app")
    leaks = []
    for p in backend_root.rglob("*.py"):
        try:
            if "TabErrorBoundary" in p.read_text(encoding="utf-8"):
                leaks.append(p.relative_to(backend_root).as_posix())
        except Exception:
            continue
    assert not leaks, f"TabErrorBoundary leaked into backend: {leaks}"
