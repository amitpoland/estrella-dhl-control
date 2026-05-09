"""
test_dashboard_nav_design_phase_a.py

Phase A of the dashboard design refresh — verify the smallest safe
nav change has landed correctly:

  * existing 12 NAV_ITEMS ids are still present
  * 4 new placeholder NAV_ITEMS ids added (proforma, statements,
    proposals, broker)
  * sidebar visual group dividers added with the explanatory comment
  * the 4 new pages are wired to PlaceholderPage (no fetch / apiFetch
    associated with them)
  * dashboard.html does NOT contain any of the design bundle's
    invented endpoint paths
  * critical existing testid / panel substrings remain present so the
    underlying operator panels still render

This is purely a source-level grep. No browser, no React rendering.
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
    """Read dashboard.html once for every test in the module."""
    return _DASHBOARD.read_text(encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────
# 1. Existing NAV_ITEMS ids are still present
# ──────────────────────────────────────────────────────────────────────

EXISTING_NAV_IDS = [
    "dashboard",
    "shipments",
    "dhl",
    "customs",
    "warehouse_scanner",
    "pz",
    "wfirma",
    "reports",
    "intelligence",
    "ai_bridge",
    "learning",
    "admin",
]


@pytest.mark.parametrize("nav_id", EXISTING_NAV_IDS)
def test_existing_nav_ids_present(html: str, nav_id: str) -> None:
    # Each existing id must still appear as a NAV_ITEMS entry. Match
    # the canonical "id: '<id>'," shape so prose mentions don't pass.
    pattern = re.compile(rf"id:\s*'{re.escape(nav_id)}'")
    assert pattern.search(html), (
        f"Existing NAV_ITEMS id {nav_id!r} disappeared from dashboard.html"
    )


# ──────────────────────────────────────────────────────────────────────
# 2. New ids are present
# ──────────────────────────────────────────────────────────────────────

NEW_NAV_IDS = ["proforma", "statements", "proposals", "broker"]


@pytest.mark.parametrize("nav_id", NEW_NAV_IDS)
def test_new_nav_ids_present(html: str, nav_id: str) -> None:
    pattern = re.compile(rf"id:\s*'{re.escape(nav_id)}'")
    assert pattern.search(html), (
        f"New NAV_ITEMS id {nav_id!r} not found in dashboard.html"
    )


# ──────────────────────────────────────────────────────────────────────
# 3. New labels are present
# ──────────────────────────────────────────────────────────────────────

NEW_NAV_LABELS = [
    "Proforma Drafts",
    "Customer Statements",
    "Action Proposals",
    "Broker Follow-ups",
]


@pytest.mark.parametrize("label", NEW_NAV_LABELS)
def test_new_nav_labels_present(html: str, label: str) -> None:
    assert label in html, (
        f"New NAV_ITEMS label {label!r} not found in dashboard.html"
    )


# ──────────────────────────────────────────────────────────────────────
# 4. The placeholder explanatory comment is present
# ──────────────────────────────────────────────────────────────────────

PLACEHOLDER_COMMENT = (
    "Design refresh placeholders. Backend verified; UI pages deferred."
)


def test_placeholder_comment_present(html: str) -> None:
    assert PLACEHOLDER_COMMENT in html, (
        f"Phase A explanatory comment missing: {PLACEHOLDER_COMMENT!r}"
    )


# ──────────────────────────────────────────────────────────────────────
# 5. None of the design bundle's invented endpoints leaked into the dashboard
# ──────────────────────────────────────────────────────────────────────

INVENTED_ENDPOINTS = [
    "/api/v1/shipments",
    "/api/v1/pz/generate",
    "/api/v1/wfirma/export",
    "/api/v1/ai/classify",
]


@pytest.mark.parametrize("endpoint", INVENTED_ENDPOINTS)
def test_no_invented_endpoints(html: str, endpoint: str) -> None:
    # Match the literal endpoint path. We allow it as a substring of
    # a longer path (e.g. /api/v1/shipments-something) to fail too —
    # the design bundle's path namespace does not exist in the
    # backend at all and must not appear verbatim in the dashboard.
    assert endpoint not in html, (
        f"Design-bundle invented endpoint {endpoint!r} found in dashboard.html. "
        f"Backend does not implement that path; do not surface it in the UI."
    )


# ──────────────────────────────────────────────────────────────────────
# 6. All four design-refresh nav entries now render real pages.
#
# Migration history of the parametrised list that used to live here:
#   Phase A (commit 90289a5): NEW_NAV_IDS = [proforma, statements,
#                                            proposals, broker]
#                              all 4 are placeholders.
#   Phase B (commit 6ec303e): proforma → ProformaDraftsCrossBatchPage
#                              dropped from PLACEHOLDER_NAV_IDS.
#   Phase C (commit 6164050): statements → CustomerStatementsPickerPage
#                              dropped from PLACEHOLDER_NAV_IDS.
#   Phase D (commit c91423c): proposals → ActionProposalsCrossBatchPage
#                              dropped from PLACEHOLDER_NAV_IDS.
#   Phase E (this commit):    broker → BrokerFollowupsCrossBatchPage
#                              dropped from PLACEHOLDER_NAV_IDS.
#
# All four ids now have dedicated phase test files asserting their real
# page renders. The list-of-placeholders is empty by construction. We
# replace the parametrised "still placeholders" sentinel with a positive
# parametrised "all four are real" sentinel — same shape, opposite
# polarity. Future regressions that revert any one page back to
# PlaceholderPage will fail this test.
# ──────────────────────────────────────────────────────────────────────

DESIGN_REFRESH_REAL_PAGES = [
    ("proforma",   "ProformaDraftsCrossBatchPage"),
    ("statements", "CustomerStatementsPickerPage"),
    ("proposals",  "ActionProposalsCrossBatchPage"),
    ("broker",     "BrokerFollowupsCrossBatchPage"),
]


@pytest.mark.parametrize("page_id,component", DESIGN_REFRESH_REAL_PAGES)
def test_design_refresh_pages_are_real(
    html: str, page_id: str, component: str
) -> None:
    """
    Every design-refresh nav id must render its real component (not
    PlaceholderPage). This is the post-Phase-E sentinel that catches
    any regression that re-introduces a placeholder for these ids.
    """
    pattern = re.compile(rf"page\s*===\s*'{re.escape(page_id)}'[^\n]*")
    matches = pattern.findall(html)
    assert matches, (
        f"No conditional render line for page === '{page_id}'. "
        f"App router is missing this design-refresh nav id."
    )
    real_match = any(component in line for line in matches)
    assert real_match, (
        f"Page id {page_id!r} is not wired to {component!r}. "
        f"Render lines found: {matches!r}"
    )
    placeholder_match = any("PlaceholderPage" in line for line in matches)
    assert not placeholder_match, (
        f"Page id {page_id!r} is wired to PlaceholderPage somewhere — the "
        f"design-refresh migration is supposed to be complete. "
        f"Render lines found: {matches!r}"
    )


# ──────────────────────────────────────────────────────────────────────
# 7. Critical existing testid / panel substrings remain present
# ──────────────────────────────────────────────────────────────────────

CRITICAL_PANEL_SUBSTRINGS = [
    "proforma-draft-panel",       # ProformaDraftPanel data-testid
    "customer-statement-drawer",  # CustomerStatementDrawer data-testid
    "zc429-lineage",              # /zc429-lineage endpoint URL substring
    "broker-followup-panel",      # BrokerFollowupPanel data-testid
    "workflow-card",              # OperatorWorkflowCard's testid
                                  # (canonical spelling in current source)
]


@pytest.mark.parametrize("token", CRITICAL_PANEL_SUBSTRINGS)
def test_critical_panel_substrings_remain(html: str, token: str) -> None:
    assert token in html, (
        f"Critical panel substring {token!r} disappeared from dashboard.html. "
        f"Phase A is supposed to be additive only — existing operator "
        f"panels must remain wired."
    )
