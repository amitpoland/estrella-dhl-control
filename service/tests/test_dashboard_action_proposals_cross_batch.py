"""
test_dashboard_action_proposals_cross_batch.py

Phase D of the dashboard design refresh — verify the new read-only
Action Proposals cross-batch page has landed correctly:

  * ActionProposalsCrossBatchPage component is defined.
  * The page exposes data-testid="action-proposals-cross-batch".
  * The Refresh button is wired with data-testid="btn-action-proposals-refresh".
  * The page consumes only existing endpoints:
      GET /dashboard/batches?all=1
      GET /api/v1/action-proposals/{batch_id}
  * The page does NOT call any per-proposal write endpoint
    (/approve, /reject, /queue) inside the component body.
  * The page does NOT contain the labels Approve / Reject / Queue /
    Execute inside the component body. Operators take action by
    clicking "Open batch" and using the per-batch panel.
  * The page exposes a "Open batch" action wired through the
    existing App-level `viewShipment` function (passed as the
    onViewBatch prop in the App router).
  * The page does NOT contain any of the design-bundle invented
    endpoints.
  * The App router replaces the `proposals` PlaceholderPage with
    the real component.
  * Phase B/C routes for `proforma` / `statements` continue to
    render their real pages.
  * The remaining `broker` route still renders PlaceholderPage.
  * The existing per-batch proposal-* substrings remain present.

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


def _component_body(html: str) -> str:
    """
    Slice the source between `function ActionProposalsCrossBatchPage(`
    and the next top-level `function ` declaration. Returns "" if not
    found.
    """
    start_match = re.search(
        r"function\s+ActionProposalsCrossBatchPage\s*\(", html
    )
    if not start_match:
        return ""
    start = start_match.start()
    next_match = re.search(
        r"\nfunction\s+[A-Z][A-Za-z0-9_]*\s*\(", html[start + 50:]
    )
    end = (start + 50 + next_match.start()) if next_match else len(html)
    return html[start:end]


# ──────────────────────────────────────────────────────────────────────
# 1. Component is defined
# ──────────────────────────────────────────────────────────────────────

def test_component_defined(html: str) -> None:
    pattern = re.compile(r"function\s+ActionProposalsCrossBatchPage\s*\(")
    assert pattern.search(html), (
        "ActionProposalsCrossBatchPage component declaration not found in "
        "dashboard.html. Phase D did not land."
    )


# ──────────────────────────────────────────────────────────────────────
# 2. Root testid is present
# ──────────────────────────────────────────────────────────────────────

def test_root_testid_present(html: str) -> None:
    assert 'data-testid="action-proposals-cross-batch"' in html, (
        "Required root testid `action-proposals-cross-batch` missing."
    )


# ──────────────────────────────────────────────────────────────────────
# 3. Refresh button testid is present
# ──────────────────────────────────────────────────────────────────────

def test_refresh_button_testid_present(html: str) -> None:
    assert 'data-testid="btn-action-proposals-refresh"' in html, (
        "Refresh button testid `btn-action-proposals-refresh` missing."
    )


# ──────────────────────────────────────────────────────────────────────
# 4. Uses /dashboard/batches?all=1
# ──────────────────────────────────────────────────────────────────────

def test_uses_dashboard_batches_endpoint(html: str) -> None:
    body = _component_body(html)
    assert body, "Could not slice ActionProposalsCrossBatchPage component body."
    assert "/dashboard/batches?all=1" in body, (
        "Cross-batch page does not call /dashboard/batches?all=1. The page "
        "must fan out from the canonical batch list."
    )


# ──────────────────────────────────────────────────────────────────────
# 5. Uses /api/v1/action-proposals/
# ──────────────────────────────────────────────────────────────────────

def test_uses_action_proposals_endpoint(html: str) -> None:
    body = _component_body(html)
    assert body, "Could not slice component body."
    assert "/api/v1/action-proposals/" in body, (
        "Component does not call /api/v1/action-proposals/. Phase D must "
        "consume this per-batch listing endpoint."
    )


# ──────────────────────────────────────────────────────────────────────
# 6. Component body does NOT contain proposal write endpoints
# ──────────────────────────────────────────────────────────────────────

WRITE_ENDPOINT_FRAGMENTS = ["/approve", "/reject", "/queue"]


@pytest.mark.parametrize("frag", WRITE_ENDPOINT_FRAGMENTS)
def test_no_write_endpoints_in_component(html: str, frag: str) -> None:
    body = _component_body(html)
    assert body, "Could not slice component body."
    assert frag not in body, (
        f"Write-endpoint fragment {frag!r} appears inside "
        f"ActionProposalsCrossBatchPage. The cross-batch list must be "
        f"read-only — proposal status transitions live in the per-batch "
        f"panel inside BatchDetailPage."
    )


# ──────────────────────────────────────────────────────────────────────
# 7. Component body does NOT contain write-action button labels
# ──────────────────────────────────────────────────────────────────────

WRITE_BUTTON_LABELS = ["Approve", "Reject", "Queue", "Execute"]


@pytest.mark.parametrize("label", WRITE_BUTTON_LABELS)
def test_no_write_action_labels(html: str, label: str) -> None:
    body = _component_body(html)
    assert body, "Could not slice component body."
    assert label not in body, (
        f"Write-button label {label!r} appears inside the cross-batch "
        f"page. Approve / Reject / Queue / Execute actions must not be "
        f"surfaced on the read-only list — they live in the per-batch "
        f"panel."
    )


# ──────────────────────────────────────────────────────────────────────
# 8. "Open batch" action exists
# ──────────────────────────────────────────────────────────────────────

def test_open_batch_action_present(html: str) -> None:
    body = _component_body(html)
    assert body, "Could not slice component body."
    assert "Open batch" in body, (
        "Component is missing the `Open batch` action. Operators need a "
        "navigation link from the cross-batch list to the per-batch panel."
    )
    # Stable per-row testid for the Open-batch button.
    assert "btn-action-proposals-open-batch" in body, (
        "data-testid `btn-action-proposals-open-batch` missing on the "
        "per-row navigation button."
    )


# ──────────────────────────────────────────────────────────────────────
# 9. Page is wired to existing `viewShipment` via App router
# ──────────────────────────────────────────────────────────────────────

def test_uses_existing_view_shipment(html: str) -> None:
    """
    The App router instantiates ActionProposalsCrossBatchPage with
    onViewBatch={viewShipment}. This guarantees the page reuses the
    existing batch-detail navigation rather than introducing a new
    handler.
    """
    pattern = re.compile(
        r"<\s*ActionProposalsCrossBatchPage\b[^>]*onViewBatch\s*=\s*\{\s*viewShipment\s*\}"
    )
    assert pattern.search(html), (
        "App router does not wire ActionProposalsCrossBatchPage with "
        "onViewBatch={viewShipment}. Phase D must reuse the existing "
        "viewShipment function rather than introducing a new handler."
    )


# ──────────────────────────────────────────────────────────────────────
# 10. No design-bundle invented endpoints anywhere in the dashboard
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
        f"Backend does not implement that path; Phase D must not surface it."
    )


# ──────────────────────────────────────────────────────────────────────
# 11. App router renders ActionProposalsCrossBatchPage for `proposals`,
#     not PlaceholderPage
# ──────────────────────────────────────────────────────────────────────

def test_app_router_uses_real_page(html: str) -> None:
    pattern = re.compile(r"page\s*===\s*'proposals'[^\n]*")
    matches = pattern.findall(html)
    assert matches, "No conditional render line for page === 'proposals'."
    real_match = any("ActionProposalsCrossBatchPage" in line for line in matches)
    assert real_match, (
        f"page === 'proposals' is not wired to "
        f"ActionProposalsCrossBatchPage. Render lines: {matches!r}"
    )
    placeholder_match = any("PlaceholderPage" in line for line in matches)
    assert not placeholder_match, (
        f"page === 'proposals' is still wired to PlaceholderPage somewhere. "
        f"Phase D should have replaced it. Render lines: {matches!r}"
    )


# ──────────────────────────────────────────────────────────────────────
# 12. Phase B/C routes remain real (no regression)
# ──────────────────────────────────────────────────────────────────────

PHASE_B_C_PAGES = [
    ("proforma",   "ProformaDraftsCrossBatchPage"),
    ("statements", "CustomerStatementsPickerPage"),
]


@pytest.mark.parametrize("page_id,component", PHASE_B_C_PAGES)
def test_earlier_phase_pages_unchanged(html: str, page_id: str, component: str) -> None:
    pattern = re.compile(rf"page\s*===\s*'{re.escape(page_id)}'[^\n]*")
    matches = pattern.findall(html)
    assert matches, f"No conditional render line for page === '{page_id}'."
    real_match = any(component in line for line in matches)
    assert real_match, (
        f"page === '{page_id}' is no longer wired to {component!r}. "
        f"Phase D must not regress earlier phases. Render lines: {matches!r}"
    )


# ──────────────────────────────────────────────────────────────────────
# 13. All four design-refresh nav entries now render real pages.
#
# Migration history: see test_dashboard_nav_design_phase_a.py header
# for the full Phase A → Phase E timeline. Phase E (broker →
# BrokerFollowupsCrossBatchPage) closed the migration; no design-
# refresh placeholders remain.
#
# This file's earlier `test_broker_remains_placeholder` standalone
# assertion was replaced with the same positive parametrised "all
# four are real" sentinel that lives in every phase test file.
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
    pattern = re.compile(rf"page\s*===\s*'{re.escape(page_id)}'[^\n]*")
    matches = pattern.findall(html)
    assert matches, f"No conditional render line for page === '{page_id}'."
    real_match = any(component in line for line in matches)
    assert real_match, (
        f"Page id {page_id!r} is not wired to {component!r}. "
        f"Render lines: {matches!r}"
    )
    placeholder_match = any("PlaceholderPage" in line for line in matches)
    assert not placeholder_match, (
        f"Page id {page_id!r} is wired to PlaceholderPage somewhere — "
        f"design-refresh migration is supposed to be complete."
    )


# ──────────────────────────────────────────────────────────────────────
# 14. Existing per-batch proposal-* substrings remain present
# ──────────────────────────────────────────────────────────────────────

EXISTING_PER_BATCH_PROPOSAL_SUBSTRINGS = [
    "proposal-approve-btn",            # per-batch approve button data-testid
    "proposal-approve-disabled-reason", # per-batch disabled-reason note
]


@pytest.mark.parametrize("token", EXISTING_PER_BATCH_PROPOSAL_SUBSTRINGS)
def test_existing_per_batch_proposal_substrings(html: str, token: str) -> None:
    assert token in html, (
        f"Existing per-batch proposal substring {token!r} disappeared from "
        f"dashboard.html. Phase D is supposed to be additive only — the "
        f"existing per-batch proposal panel must remain wired."
    )
