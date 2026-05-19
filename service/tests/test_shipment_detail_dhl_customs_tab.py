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


def test_dhl_customs_render_branch_wrapped_in_boundary(html):
    """The new DHL/Customs branch must be wrapped in TabErrorBoundary
    so any future render crash inside it stays contained."""
    pattern = re.compile(
        r"activeTab\s*===\s*['\"]DHL / Customs['\"]\s*&&\s*\(\s*<TabErrorBoundary>",
        re.DOTALL,
    )
    assert pattern.search(html), (
        "DHL / Customs render branch must open with <TabErrorBoundary>"
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


# ── New DHL/Customs panel content + test-ids ────────────────────────────────

def test_dhl_customs_panel_test_id_present(html):
    assert 'data-testid="detail-tab-dhl-customs"' in html


def test_dhl_customs_panel_states_present(html):
    """Loading / error / empty / data states each carry a distinct test-id
    so smoke tests can assert which branch rendered."""
    for tid in (
        "detail-dhl-customs-loading",
        "detail-dhl-customs-error",
        "detail-dhl-customs-empty",
        "detail-dhl-customs-readiness",
    ):
        assert f'data-testid="{tid}"' in html, f"missing test-id {tid!r}"


def test_dhl_customs_panel_has_navigation_hint(html):
    """Operator should be told where the actionable surfaces live (the
    main dashboard's DHL/Customs and Documents pages) — this panel is
    read-only."""
    assert 'data-testid="detail-dhl-customs-nav-hint"' in html


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


def test_diagnostic_v2_dhl_customs_branch_marker_present(html):
    """Inside the DHL/Customs render branch, an always-rendered marker
    (not gated by loading/error/data state) confirms the conditional
    fired and the subtree mounted."""
    assert 'data-testid="dhl-customs-render-mounted-v2"' in html
    assert "DHL CUSTOMS BRANCH IS ACTIVE — diagnostic-v2" in html
    # Marker must sit inside the DHL/Customs && ( ... ) block.
    branch_start = html.find("{activeTab === 'DHL / Customs' && (")
    marker_pos = html.find('data-testid="dhl-customs-render-mounted-v2"')
    next_branch = html.find("{activeTab === '", branch_start + 5)
    assert branch_start > 0 < marker_pos
    assert branch_start < marker_pos < next_branch, (
        "DHL/Customs marker must be INSIDE the DHL/Customs render branch"
    )


def test_diagnostic_v1_active_tab_banner_present(html):
    """Temporary diagnostic — operator-visible activeTab banner under
    the tab strip.  Remove on next deploy unless operator approves
    keeping it."""
    assert 'data-testid="active-tab-diagnostic"' in html
    assert 'data-testid="active-tab-diagnostic-raw"' in html
    assert 'data-testid="active-tab-diagnostic-json"' in html
    assert 'data-testid="active-tab-diagnostic-match"' in html


def test_diagnostic_v1_dhl_customs_mount_marker_present(html):
    """Temporary diagnostic — always-rendered marker inside the
    DHL/Customs render branch (not gated by data states) so operator
    can confirm the conditional fires.  Upgraded to v2 wording —
    same test-id family, new label."""
    assert 'data-testid="dhl-customs-render-mounted-v2"' in html


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
