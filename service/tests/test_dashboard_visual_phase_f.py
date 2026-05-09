"""
test_dashboard_visual_phase_f.py

Phase F of the dashboard design refresh — verify the visual-only
PageHeader consistency + responsive breakpoint polish has landed:

  * The PageHeader function/component is defined.
  * PageHeader's signature accepts title and subtitle props (and an
    actions slot for caller-supplied right-aligned buttons).
  * All 14 listed top-level pages are wired through the centralised
    PAGE_TITLES map so they share PageHeader chrome.
  * BatchDetailPage is NOT in PAGE_TITLES — Phase F deliberately did
    not touch it (operationally sensitive, large component).
  * The CSS contains responsive @media breakpoints at 1100 / 900 /
    600 px.
  * Critical existing testids remain present so the underlying
    panels still mount.
  * No design-bundle invented endpoints.
  * No TweaksPanel or ApiChecklistModal introduced.

Pure source-level grep. No browser, no React rendering.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_DASHBOARD = (
    Path(__file__).resolve().parents[1] / "app" / "static" / "dashboard.html"
)


@pytest.fixture(scope="module")
def html() -> str:
    return _DASHBOARD.read_text(encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────
# 1. PageHeader function/component is defined
# ──────────────────────────────────────────────────────────────────────

def test_page_header_defined(html: str) -> None:
    pattern_fn    = re.compile(r"function\s+PageHeader\s*\(")
    pattern_const = re.compile(r"const\s+PageHeader\s*=")
    assert pattern_fn.search(html) or pattern_const.search(html), (
        "PageHeader function/component declaration not found in "
        "dashboard.html. Phase F requires a reusable PageHeader."
    )


# ──────────────────────────────────────────────────────────────────────
# 2. PageHeader accepts title and subtitle props
# ──────────────────────────────────────────────────────────────────────

def test_page_header_accepts_title_and_subtitle(html: str) -> None:
    """The signature must destructure title + subtitle (the spec's two
    required props). actions is optional but commonly present."""
    pattern = re.compile(
        r"function\s+PageHeader\s*\(\s*\{[^}]*\btitle\b[^}]*\bsubtitle\b[^}]*\}\s*\)",
        re.DOTALL,
    )
    pattern_alt = re.compile(
        r"const\s+PageHeader\s*=\s*\(?\s*\{[^}]*\btitle\b[^}]*\bsubtitle\b[^}]*\}\s*\)?\s*=>",
        re.DOTALL,
    )
    assert pattern.search(html) or pattern_alt.search(html), (
        "PageHeader signature does not destructure both `title` and "
        "`subtitle` props."
    )


# ──────────────────────────────────────────────────────────────────────
# 3. All 14 listed pages are covered by PageHeader (via PAGE_TITLES)
# ──────────────────────────────────────────────────────────────────────
#
# Every covered page id appears as an entry in PAGE_TITLES with both
# `title:` and `subtitle:` fields. App's centralised render at
# `page !== 'detail' && currentTitle && <PageHeader ... />` then mounts
# PageHeader for that page.
#
# We assert against the page id (the route key in PAGE_TITLES), not the
# component name, because the centralisation indirects through the map.

PAGE_IDS_WITH_HEADER = [
    "dashboard",     # DashboardPage
    "shipments",     # DashboardPage (filtered)
    "dhl",           # DhlClearancePage
    "customs",       # CustomsDocumentsPage
    "wfirma",        # WfirmaExportPage
    "pz",            # PzAccountingPage
    "reports",       # ReportsPage
    "intelligence",  # IntelligencePage
    "learning",      # LearningPage
    "ai_bridge",     # AiBridgePage
    "admin",         # AdminPage
    "proforma",      # ProformaDraftsCrossBatchPage   (Phase B)
    "statements",    # CustomerStatementsPickerPage   (Phase C)
    "proposals",     # ActionProposalsCrossBatchPage  (Phase D)
    "broker",        # BrokerFollowupsCrossBatchPage  (Phase E)
]


def _slice_page_titles(html: str) -> str:
    """Slice the source between `const PAGE_TITLES = {` and the matching
    closing `};` so subsequent tests grep within that map only."""
    start_match = re.search(r"const\s+PAGE_TITLES\s*=\s*\{", html)
    if not start_match:
        return ""
    start = start_match.end()
    # Walk balanced braces from start.
    depth = 1
    i = start
    while i < len(html) and depth > 0:
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
        i += 1
    return html[start:i]


@pytest.mark.parametrize("page_id", PAGE_IDS_WITH_HEADER)
def test_page_id_in_page_titles_map(html: str, page_id: str) -> None:
    body = _slice_page_titles(html)
    assert body, "PAGE_TITLES map not found in dashboard.html."
    pattern = re.compile(
        rf"\b{re.escape(page_id)}\s*:\s*\{{[^}}]*\btitle\b[^}}]*\bsubtitle\b[^}}]*\}}",
        re.DOTALL,
    )
    assert pattern.search(body), (
        f"PAGE_TITLES['{page_id}'] entry is missing or does not have both "
        f"`title` and `subtitle` keys. Phase F requires PageHeader to "
        f"cover this page id."
    )


# ──────────────────────────────────────────────────────────────────────
# 4. BatchDetailPage is NOT refactored to PageHeader in this phase
# ──────────────────────────────────────────────────────────────────────

def test_batch_detail_page_not_in_page_titles(html: str) -> None:
    """The 'detail' route must NOT have a PAGE_TITLES entry, and App's
    central PageHeader render uses `page !== 'detail'` to skip it.
    Phase F deliberately does not touch BatchDetailPage."""
    body = _slice_page_titles(html)
    assert body, "PAGE_TITLES map not found."
    # No `detail:` key in the map.
    assert not re.search(r"\bdetail\s*:\s*\{", body), (
        "PAGE_TITLES contains a `detail:` entry. Phase F was supposed to "
        "leave BatchDetailPage untouched — no centralised PageHeader."
    )
    # And the App's PageHeader render still gates with page !== 'detail'.
    assert re.search(r"page\s*!==\s*'detail'", html), (
        "App's central PageHeader render no longer guards against "
        "`page === 'detail'`. BatchDetailPage must keep its own header."
    )


# ──────────────────────────────────────────────────────────────────────
# 5–7. Responsive breakpoints exist
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("px", [1100, 900, 600])
def test_responsive_breakpoint_present(html: str, px: int) -> None:
    pattern = re.compile(rf"@media\s*\(\s*max-width:\s*{px}px\s*\)")
    assert pattern.search(html), (
        f"@media (max-width: {px}px) breakpoint missing from dashboard "
        f"<style> block. Phase F requires three responsive breakpoints "
        f"at 1100px / 900px / 600px."
    )


# ──────────────────────────────────────────────────────────────────────
# 8. Critical existing testids / panel substrings remain present
# ──────────────────────────────────────────────────────────────────────

CRITICAL_SUBSTRINGS = [
    "proforma-drafts-cross-batch",   # Phase B root testid
    "customer-statements-picker",    # Phase C root testid
    "action-proposals-cross-batch",  # Phase D root testid
    "broker-followups-cross-batch",  # Phase E root testid
    "proforma-draft-panel",          # ProformaDraftPanel
    "customer-statement-drawer",     # CustomerStatementDrawer
    "broker-followup-panel",         # BrokerFollowupPanel
    "workflow-card",                 # OperatorWorkflowCard
]


@pytest.mark.parametrize("token", CRITICAL_SUBSTRINGS)
def test_critical_substrings_unchanged(html: str, token: str) -> None:
    assert token in html, (
        f"Critical testid / panel substring {token!r} disappeared from "
        f"dashboard.html. Phase F is supposed to be visual-only — "
        f"existing operator panels and cross-batch pages must remain "
        f"wired."
    )


# ──────────────────────────────────────────────────────────────────────
# 9. No design-bundle invented endpoints
# ──────────────────────────────────────────────────────────────────────

INVENTED_ENDPOINTS = [
    "/api/v1/shipments",
    "/api/v1/pz/generate",
    "/api/v1/wfirma/export",
    "/api/v1/ai/classify",
]


@pytest.mark.parametrize("endpoint", INVENTED_ENDPOINTS)
def test_no_invented_endpoints(html: str, endpoint: str) -> None:
    assert endpoint not in html, (
        f"Design-bundle invented endpoint {endpoint!r} found in "
        f"dashboard.html. Phase F must not surface any new endpoint, "
        f"least of all one that does not exist in the backend."
    )


# ──────────────────────────────────────────────────────────────────────
# 10. No TweaksPanel or ApiChecklistModal introduced
# ──────────────────────────────────────────────────────────────────────

FORBIDDEN_DESIGN_COMPONENTS = ["TweaksPanel", "ApiChecklistModal"]


@pytest.mark.parametrize("component_name", FORBIDDEN_DESIGN_COMPONENTS)
def test_no_design_only_components(html: str, component_name: str) -> None:
    """The Claude Design bundle had a TweaksPanel and an ApiChecklistModal.
    Both are explicitly out-of-scope for Phase F (and for the production
    dashboard generally — TweaksPanel exposes dev-only toggles in the
    operator UI, ApiChecklistModal in the bundle had wrong endpoint
    paths). Neither must appear in dashboard.html."""
    assert component_name not in html, (
        f"Design-bundle component {component_name!r} found in "
        f"dashboard.html. Phase F must not introduce design-only "
        f"components — they were excluded for documented reasons."
    )
