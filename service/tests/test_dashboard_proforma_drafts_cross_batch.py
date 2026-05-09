"""
test_dashboard_proforma_drafts_cross_batch.py

Phase B of the dashboard design refresh — verify the new read-only
Proforma Drafts cross-batch page has landed correctly:

  * ProformaDraftsCrossBatchPage component is defined.
  * The page exposes data-testid="proforma-drafts-cross-batch".
  * The Refresh button is wired with data-testid="btn-proforma-drafts-refresh".
  * The page consumes only existing endpoints:
      GET /dashboard/batches  (already used by App)
      GET /api/v1/proforma/drafts/{batch_id}
  * The page does NOT introduce any write endpoint from routes_proforma:
      /approve, /post, /send, /create,
      /cancel-issued-for-reissue, /adopt-issued
  * The page does NOT contain any of the design-bundle invented endpoints.
  * The App router replaces the placeholder for `proforma` and renders
    the new component.
  * Existing critical operator-panel substrings remain present so the
    underlying batch-detail panels still mount.
  * The remaining Phase A placeholders (statements, proposals, broker)
    are still placeholders.

This is a pure source-level grep. No browser, no React rendering.
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
# 1. Component is defined
# ──────────────────────────────────────────────────────────────────────

def test_component_defined(html: str) -> None:
    """The ProformaDraftsCrossBatchPage function component is declared."""
    pattern = re.compile(r"function\s+ProformaDraftsCrossBatchPage\s*\(")
    assert pattern.search(html), (
        "ProformaDraftsCrossBatchPage component declaration not found in "
        "dashboard.html. Phase B did not land."
    )


# ──────────────────────────────────────────────────────────────────────
# 2. Root testid is present
# ──────────────────────────────────────────────────────────────────────

def test_root_testid_present(html: str) -> None:
    assert 'data-testid="proforma-drafts-cross-batch"' in html, (
        "Required root testid `proforma-drafts-cross-batch` missing."
    )


# ──────────────────────────────────────────────────────────────────────
# 3. Refresh button testid is present
# ──────────────────────────────────────────────────────────────────────

def test_refresh_button_testid_present(html: str) -> None:
    assert 'data-testid="btn-proforma-drafts-refresh"' in html, (
        "Refresh button testid `btn-proforma-drafts-refresh` missing."
    )


# ──────────────────────────────────────────────────────────────────────
# 4. Uses /dashboard/batches
# ──────────────────────────────────────────────────────────────────────

def test_uses_dashboard_batches_endpoint(html: str) -> None:
    """
    The /dashboard/batches endpoint substring is present in dashboard.html.
    The App's existing loadBatches already calls it; the new page consumes
    that data via apiFetch as well.
    """
    assert "/dashboard/batches" in html, (
        "Expected /dashboard/batches endpoint substring not found."
    )


# ──────────────────────────────────────────────────────────────────────
# 5. Uses /api/v1/proforma/drafts/
# ──────────────────────────────────────────────────────────────────────

def test_uses_proforma_drafts_endpoint(html: str) -> None:
    """The new component must call /api/v1/proforma/drafts/."""
    assert "/api/v1/proforma/drafts/" in html, (
        "Expected /api/v1/proforma/drafts/ endpoint substring not found. "
        "ProformaDraftsCrossBatchPage must consume the per-batch drafts "
        "listing endpoint."
    )


# ──────────────────────────────────────────────────────────────────────
# 6. Cross-batch page does NOT contain any write endpoint
# ──────────────────────────────────────────────────────────────────────
#
# The page is read-only. None of the proforma write actions should
# appear inside the ProformaDraftsCrossBatchPage component body. We
# extract the component's source range and grep within it.
#
# (We test substring presence within the component body specifically,
# rather than against the whole file, because the file also contains
# ProformaDraftPanel which legitimately uses these endpoints.)
# ──────────────────────────────────────────────────────────────────────

WRITE_ENDPOINT_FRAGMENTS = [
    "/approve",
    "/post",
    "/send",
    "/create",
    "/cancel-issued-for-reissue",
    "/adopt-issued",
]


def _component_body(html: str) -> str:
    """
    Slice the source between `function ProformaDraftsCrossBatchPage(`
    and the next top-level `function ` declaration. Returns "" if not
    found.
    """
    start_match = re.search(
        r"function\s+ProformaDraftsCrossBatchPage\s*\(", html
    )
    if not start_match:
        return ""
    start = start_match.start()
    # Find the next top-level function declaration after start
    next_match = re.search(
        r"\nfunction\s+[A-Z][A-Za-z0-9_]*\s*\(", html[start + 50:]
    )
    end = (start + 50 + next_match.start()) if next_match else len(html)
    return html[start:end]


@pytest.mark.parametrize("frag", WRITE_ENDPOINT_FRAGMENTS)
def test_no_write_endpoints_in_component(html: str, frag: str) -> None:
    body = _component_body(html)
    assert body, "Could not slice ProformaDraftsCrossBatchPage component body."
    assert frag not in body, (
        f"Write-endpoint fragment {frag!r} appears inside "
        f"ProformaDraftsCrossBatchPage. The page must be read-only — "
        f"approve/post/send/create/cancel-issued/adopt-issued live in "
        f"ProformaDraftPanel inside BatchDetailPage instead."
    )


# ──────────────────────────────────────────────────────────────────────
# 7. No design-bundle invented endpoints anywhere in the dashboard
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
        f"Design-bundle invented endpoint {endpoint!r} found in dashboard.html. "
        f"Backend does not implement that path; Phase B must not surface it."
    )


# ──────────────────────────────────────────────────────────────────────
# 8. App router renders ProformaDraftsCrossBatchPage for `proforma`,
#    not PlaceholderPage
# ──────────────────────────────────────────────────────────────────────

def test_app_router_uses_real_page(html: str) -> None:
    """
    Find the conditional render line for page === 'proforma' in the App
    router and confirm it references ProformaDraftsCrossBatchPage rather
    than PlaceholderPage.
    """
    pattern = re.compile(r"page\s*===\s*'proforma'[^\n]*")
    matches = pattern.findall(html)
    assert matches, "No conditional render line for page === 'proforma'."
    # At least one match must wire the real component.
    real_match = any("ProformaDraftsCrossBatchPage" in line for line in matches)
    assert real_match, (
        f"page === 'proforma' is no longer wired to "
        f"ProformaDraftsCrossBatchPage. Render lines found: {matches!r}"
    )
    # And no placeholder match for proforma should remain.
    placeholder_match = any("PlaceholderPage" in line for line in matches)
    assert not placeholder_match, (
        f"page === 'proforma' is still wired to PlaceholderPage somewhere. "
        f"Phase B should have replaced it. Render lines: {matches!r}"
    )


# ──────────────────────────────────────────────────────────────────────
# 9. Existing ProformaDraftPanel substring still exists
# ──────────────────────────────────────────────────────────────────────

def test_proforma_draft_panel_unchanged(html: str) -> None:
    """ProformaDraftPanel inside BatchDetailPage must still mount."""
    assert "ProformaDraftPanel" in html, (
        "ProformaDraftPanel function name disappeared from dashboard.html. "
        "Phase B was supposed to be additive — the existing per-batch "
        "panel must remain intact."
    )
    assert "proforma-draft-panel" in html, (
        "data-testid `proforma-draft-panel` disappeared. Phase B is "
        "additive; existing panel testids must remain."
    )


# ──────────────────────────────────────────────────────────────────────
# 10. The remaining nav placeholders stay placeholders
#
# `statements` was removed from this list when Phase C replaced it with
# the real CustomerStatementsPickerPage. The Phase C test
# (test_dashboard_customer_statements_picker.py) asserts `statements`
# now renders the real page.
#
# `proposals` was removed from this list when Phase D replaced it with
# the real ActionProposalsCrossBatchPage. The Phase D test
# (test_dashboard_action_proposals_cross_batch.py) covers the new
# page instead. Only `broker` remains a placeholder, awaiting Phase E.
# ──────────────────────────────────────────────────────────────────────

REMAINING_PLACEHOLDERS = ["broker"]


@pytest.mark.parametrize("nav_id", REMAINING_PLACEHOLDERS)
def test_remaining_placeholders_unchanged(html: str, nav_id: str) -> None:
    pattern = re.compile(rf"page\s*===\s*'{re.escape(nav_id)}'[^\n]*")
    matches = pattern.findall(html)
    assert matches, f"No conditional render line for page === '{nav_id}'."
    placeholder_match = any("PlaceholderPage" in line for line in matches)
    assert placeholder_match, (
        f"Page id {nav_id!r} is no longer rendering PlaceholderPage. "
        f"If a real page has shipped for this id, drop it from "
        f"REMAINING_PLACEHOLDERS and add a dedicated test file. "
        f"Render lines found: {matches!r}"
    )
