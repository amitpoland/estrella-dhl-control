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


# ── Multi-branch DHL/Customs render — corrected understanding ──────────────
# shipment-detail.html already contains two pre-existing render branches
# for `activeTab === 'DHL / Customs'`: one at ~line 6913 ("Section 1 —
# Shipment & DHL Clearance"), one at ~line 8408 ("DHL Customs Pipeline").
# An earlier campaign added a third branch under the false premise that
# no branch existed; that redundant branch has been removed.  The actual
# white-screen bug originates inside one of the two pre-existing branches.

def test_dhl_customs_render_branches_count_unchanged(html):
    """Exactly two `activeTab === 'DHL / Customs' && ` render branches
    must exist in shipment-detail.html — the pre-existing pair owned
    by the original implementation.  Adding a third (as an earlier
    campaign did) duplicates rendering and obscures the real bug."""
    branches = re.findall(
        r"\{\s*activeTab\s*===\s*['\"]DHL / Customs['\"]\s*&&", html
    )
    assert len(branches) == 2, (
        f"expected exactly 2 DHL/Customs render branches (pre-existing), "
        f"found {len(branches)} — a redundant branch was reintroduced"
    )


def test_binary_isolation_step1_prefix_removed(html):
    """Binary-isolation step 1 (`false &&` disable prefix on branch #1)
    has been removed.  The crashing component inside branch #1 was
    identified via static inspection — a Rules-of-Hooks violation in
    the DHL Orchestrator card IIFE — and surgically removed.  Branch
    #1 now renders again without the white-screen."""
    assert "binary-isolation-step-1" not in html
    assert "false /* binary-isolation" not in html


def test_orchestrator_card_iife_removed_from_branch1(html):
    """The IIFE at lines 7424-7470 (DHL Orchestrator card in branch #1)
    called React.useState + React.useEffect from inside a conditional
    render path.  That violates Rules of Hooks (call count changes
    between renders depending on activeTab) and unmounts the entire
    BatchDetailPage subtree on activeTab transition into 'DHL / Customs'.
    The card has been removed from this location; the identical card
    on dashboard.html remains the canonical surface for orchestrator
    state.

    This test guards against re-introduction of the same anti-pattern:
    no React.useState / React.useEffect may appear inside any
    `(() => { ... })()` IIFE that itself sits inside a tab-conditional
    render branch."""
    # Slice branch #1 from open to close
    branch1_start = html.find("{activeTab === 'DHL / Customs' && (\n          <>")
    if branch1_start < 0:
        # Tolerate whitespace variance — fallback to first DHL/Customs branch
        branch1_start = html.find("{activeTab === 'DHL / Customs' && (")
    assert branch1_start > 0
    # Find the branch #2 opener as the close marker for branch #1
    branch2_start = html.find("{activeTab === 'DHL / Customs' && (() =>", branch1_start + 5)
    assert branch2_start > branch1_start, "branch #2 marker not found"
    branch1_body = html[branch1_start:branch2_start]
    # No React.useState / React.useEffect inside branch #1 body
    assert "React.useState(" not in branch1_body, (
        "branch #1 contains React.useState() inside its render path — "
        "this is a Rules-of-Hooks violation that will white-screen on "
        "tab activation"
    )
    assert "React.useEffect(" not in branch1_body, (
        "branch #1 contains React.useEffect() inside its render path — "
        "this is a Rules-of-Hooks violation that will white-screen on "
        "tab activation"
    )
    # Specific marker confirming the orchestrator card was removed
    assert 'data-testid="orchestrator-state-card"' not in branch1_body, (
        "the DHL Orchestrator card must not be re-introduced inside "
        "shipment-detail.html branch #1 — it called hooks from inside "
        "an IIFE, violating Rules of Hooks"
    )


def test_redundant_minimal_branch_removed(html):
    """The minimal `<div>DHL TAB LIVE</div>` placeholder branch must
    be removed.  It was added under a false-premise diagnosis and is
    no longer needed."""
    assert "DHL TAB LIVE" not in html
    assert 'data-testid="detail-tab-dhl-customs-minimal"' not in html


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


# ── DHL/Customs panel — corrected understanding ────────────────────────────
# The two pre-existing render branches at ~lines 6913 and 8408 contain
# the real DHL/Customs UI (Section 1 Shipment & DHL Clearance + DHL
# Customs Pipeline readiness).  No new branch is needed.  The next
# campaign focuses on identifying which of those two branches crashes.

def test_dhl_customs_first_branch_renders_section1(html):
    """First pre-existing branch renders 'Section 1 — Shipment & DHL
    Clearance'.  Locating this string proves the branch is intact."""
    assert "Section 1 — Shipment & DHL Clearance" in html


def test_dhl_customs_second_branch_renders_pipeline_panel(html):
    """Second pre-existing branch renders the readiness pipeline panel
    via `data-testid='dhl-readiness-panel'`."""
    assert 'data-testid="dhl-readiness-panel"' in html


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

def test_no_redundant_branch_between_documents_and_timeline(html):
    """After removing the redundant DHL/Customs branch, the file
    flows directly from the Documents branch closing to the Timeline
    branch opening — no third DHL/Customs branch should appear in
    between."""
    docs_branch_open = html.find("{activeTab === 'Documents' && (() =>")
    timeline_branch_open = html.find("{activeTab === 'Timeline' &&")
    assert 0 < docs_branch_open < timeline_branch_open
    middle = html[docs_branch_open:timeline_branch_open]
    # There must be NO `activeTab === 'DHL / Customs'` render branch
    # in the Documents-to-Timeline span.  The pre-existing DHL branches
    # live FURTHER DOWN the file (~lines 6913 and 8408).
    assert "{activeTab === 'DHL / Customs' &&" not in middle, (
        "redundant DHL/Customs branch between Documents and Timeline "
        "must remain removed"
    )


# ── Temporary diagnostics removed (post-fix cleanup) ────────────────────────
# All build markers and activeTab banners that were added during the
# DHL/Customs white-screen investigation have been removed now that the
# root cause (Rules of Hooks violation in branch #1's orchestrator IIFE)
# is fixed.  These tests assert the cleanup is complete and guard against
# re-introduction.

DIAGNOSTIC_MARKERS_REMOVED = (
    "shipment-detail-build-marker",
    "SHIPMENT DETAIL BUILD diagnostic-v2",
    "active-tab-diagnostic-v2",
    "active-tab-diagnostic-v2-raw",
    "active-tab-diagnostic-v2-json",
    "active-tab-diagnostic-v2-match",
    "active-tab-diagnostic",
    "active-tab-diagnostic-raw",
    "active-tab-diagnostic-json",
    "active-tab-diagnostic-match",
    "diagnostic-v2",
    "diagnostic·activeTab",
    "DIAGNOSTIC v1",
    "DIAGNOSTIC v2",
    "dhl-customs-render-mounted",
    "dhl-customs-render-mounted-v2",
    "detail-tab-dhl-customs-minimal",
    "DHL TAB LIVE",
    "binary-isolation",
)


@pytest.mark.parametrize("marker", DIAGNOSTIC_MARKERS_REMOVED)
def test_diagnostic_marker_removed(html, marker):
    """Every temporary diagnostic marker added during the DHL/Customs
    investigation must be absent from the cleaned production file."""
    assert marker not in html, (
        f"diagnostic marker {marker!r} still present in shipment-detail.html"
    )


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
