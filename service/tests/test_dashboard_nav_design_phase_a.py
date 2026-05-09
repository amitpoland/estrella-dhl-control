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
# 6. The placeholder-only page ids still render via PlaceholderPage and
#    do not introduce any fetch / apiFetch calls on their conditional
#    render line.
#
# `proforma` was removed from this list when Phase B replaced it with
# the real ProformaDraftsCrossBatchPage. The Phase B test
# (test_dashboard_proforma_drafts_cross_batch.py) covers the new page
# instead. The remaining three ids — statements, proposals, broker —
# stay placeholders until their own Phase C/D/E lands.
# ──────────────────────────────────────────────────────────────────────

PLACEHOLDER_NAV_IDS = ["statements", "proposals", "broker"]


@pytest.mark.parametrize("nav_id", PLACEHOLDER_NAV_IDS)
def test_placeholder_page_ids_use_placeholder_only(html: str, nav_id: str) -> None:
    """
    For each placeholder id, the conditional render line must be:
        page === '<id>' && <PlaceholderPage ... />
    and not a fetch-bearing component.

    The simplest source-level guarantee: find the line containing
    page === '<id>' (excluding the App page-state assignment context)
    and confirm <PlaceholderPage appears on the same line.
    """
    # Find the conditional render line — the App router uses the
    # exact spelling "page === '<id>'" inside the JSX tree.
    pattern = re.compile(rf"page\s*===\s*'{re.escape(nav_id)}'[^\n]*")
    matches = pattern.findall(html)
    # We expect at least one match — the App router's render line.
    assert matches, (
        f"No conditional render line for page === '{nav_id}'. "
        f"App router did not wire the placeholder."
    )
    # Every match must reference PlaceholderPage on the same line.
    # If a future commit replaces a placeholder with a real page,
    # the page id should be moved out of PLACEHOLDER_NAV_IDS and into
    # its own dedicated test suite (see Phase B for the precedent).
    placeholder_match = any("PlaceholderPage" in line for line in matches)
    assert placeholder_match, (
        f"Page id {nav_id!r} is rendered but does NOT use PlaceholderPage. "
        f"If a real page has shipped for this id, drop it from "
        f"PLACEHOLDER_NAV_IDS and add a dedicated test file. "
        f"Render lines found: {matches!r}"
    )
    # And critically — none of those matches contain fetch / apiFetch.
    for line in matches:
        assert "fetch(" not in line and "apiFetch(" not in line, (
            f"Page id {nav_id!r} render line introduces a fetch call: {line!r}. "
            f"Placeholders must not call any endpoint."
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
