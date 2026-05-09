"""
test_dashboard_broker_followups_cross_batch.py

Phase E of the dashboard design refresh — verify the new read-only
Broker Follow-ups cross-batch page has landed correctly:

  * BrokerFollowupsCrossBatchPage component is defined.
  * The page exposes data-testid="broker-followups-cross-batch".
  * The Refresh button is wired with data-testid="btn-broker-followups-refresh".
  * The page consumes only the existing aggregated endpoint:
      GET /dashboard/broker-followups
    (no per-batch fan-out — the endpoint already aggregates).
  * The page does NOT reference the per-batch send endpoint
    /dashboard/broker-followups/{batch_id}/send. Transmission lives
    in the existing per-batch BrokerFollowupPanel.
  * The component body contains no write-action labels (Send,
    Resend, Queue, Execute).
  * The page has an "Open batch" action wired through the existing
    App-level `viewShipment` function (passed as the onViewBatch
    prop in the App router).
  * The page does NOT contain any of the design-bundle invented
    endpoints.
  * The App router replaces the `broker` PlaceholderPage with the
    real component.
  * Phase B/C/D routes for proforma / statements / proposals
    continue to render their real pages — the design-refresh
    migration is complete.
  * The existing per-batch broker-followup-panel data-testid
    remains present.

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
    Slice the source between `function BrokerFollowupsCrossBatchPage(`
    and the next top-level `function ` declaration. Returns "" if not
    found.
    """
    start_match = re.search(
        r"function\s+BrokerFollowupsCrossBatchPage\s*\(", html
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
    pattern = re.compile(r"function\s+BrokerFollowupsCrossBatchPage\s*\(")
    assert pattern.search(html), (
        "BrokerFollowupsCrossBatchPage component declaration not found in "
        "dashboard.html. Phase E did not land."
    )


# ──────────────────────────────────────────────────────────────────────
# 2. Root testid is present
# ──────────────────────────────────────────────────────────────────────

def test_root_testid_present(html: str) -> None:
    assert 'data-testid="broker-followups-cross-batch"' in html, (
        "Required root testid `broker-followups-cross-batch` missing."
    )


# ──────────────────────────────────────────────────────────────────────
# 3. Refresh button testid is present
# ──────────────────────────────────────────────────────────────────────

def test_refresh_button_testid_present(html: str) -> None:
    assert 'data-testid="btn-broker-followups-refresh"' in html, (
        "Refresh button testid `btn-broker-followups-refresh` missing."
    )


# ──────────────────────────────────────────────────────────────────────
# 4. Uses /dashboard/broker-followups
# ──────────────────────────────────────────────────────────────────────

def test_uses_broker_followups_endpoint(html: str) -> None:
    body = _component_body(html)
    assert body, "Could not slice BrokerFollowupsCrossBatchPage component body."
    assert "/dashboard/broker-followups" in body, (
        "Component does not call /dashboard/broker-followups. Phase E "
        "must consume the aggregated endpoint."
    )


# ──────────────────────────────────────────────────────────────────────
# 5. Component does NOT reference the per-batch send endpoint
# ──────────────────────────────────────────────────────────────────────

FORBIDDEN_WRITE_FRAGMENTS = [
    "/dashboard/broker-followups/${batch_id}/send",
    "/dashboard/broker-followups/{batch_id}/send",
    "/send",
]


@pytest.mark.parametrize("frag", FORBIDDEN_WRITE_FRAGMENTS)
def test_no_send_endpoint_in_component(html: str, frag: str) -> None:
    body = _component_body(html)
    assert body, "Could not slice component body."
    assert frag not in body, (
        f"Forbidden write-endpoint fragment {frag!r} appears inside "
        f"BrokerFollowupsCrossBatchPage. The cross-batch list must be "
        f"read-only — transmission lives in the per-batch "
        f"BrokerFollowupPanel inside BatchDetailPage."
    )


# ──────────────────────────────────────────────────────────────────────
# 6. Component does NOT contain write-action labels
# ──────────────────────────────────────────────────────────────────────

WRITE_BUTTON_LABELS = ["Send", "Resend", "Queue", "Execute"]


@pytest.mark.parametrize("label", WRITE_BUTTON_LABELS)
def test_no_write_action_labels(html: str, label: str) -> None:
    body = _component_body(html)
    assert body, "Could not slice component body."
    assert label not in body, (
        f"Write-button label {label!r} appears inside the cross-batch "
        f"page. The page must be read-only — transmission lives in the "
        f"per-batch BrokerFollowupPanel."
    )


# ──────────────────────────────────────────────────────────────────────
# 7. "Open batch" action exists
# ──────────────────────────────────────────────────────────────────────

def test_open_batch_action_present(html: str) -> None:
    body = _component_body(html)
    assert body, "Could not slice component body."
    assert "Open batch" in body, (
        "Component is missing the `Open batch` action. Operators need a "
        "navigation link from the cross-batch list to the per-batch panel."
    )
    assert "btn-broker-followups-open-batch" in body, (
        "data-testid `btn-broker-followups-open-batch` missing on the "
        "per-row navigation button."
    )


# ──────────────────────────────────────────────────────────────────────
# 8. Page is wired to existing `viewShipment` via App router
# ──────────────────────────────────────────────────────────────────────

def test_uses_existing_view_shipment(html: str) -> None:
    pattern = re.compile(
        r"<\s*BrokerFollowupsCrossBatchPage\b[^>]*onViewBatch\s*=\s*\{\s*viewShipment\s*\}"
    )
    assert pattern.search(html), (
        "App router does not wire BrokerFollowupsCrossBatchPage with "
        "onViewBatch={viewShipment}. Phase E must reuse the existing "
        "viewShipment function."
    )


# ──────────────────────────────────────────────────────────────────────
# 9. No design-bundle invented endpoints anywhere in the dashboard
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
        f"Backend does not implement that path; Phase E must not surface it."
    )


# ──────────────────────────────────────────────────────────────────────
# 10. App router renders BrokerFollowupsCrossBatchPage for `broker`,
#     not PlaceholderPage
# ──────────────────────────────────────────────────────────────────────

def test_app_router_uses_real_page(html: str) -> None:
    pattern = re.compile(r"page\s*===\s*'broker'[^\n]*")
    matches = pattern.findall(html)
    assert matches, "No conditional render line for page === 'broker'."
    real_match = any("BrokerFollowupsCrossBatchPage" in line for line in matches)
    assert real_match, (
        f"page === 'broker' is not wired to "
        f"BrokerFollowupsCrossBatchPage. Render lines: {matches!r}"
    )
    placeholder_match = any("PlaceholderPage" in line for line in matches)
    assert not placeholder_match, (
        f"page === 'broker' is still wired to PlaceholderPage somewhere. "
        f"Phase E should have replaced the final placeholder. "
        f"Render lines: {matches!r}"
    )


# ──────────────────────────────────────────────────────────────────────
# 11. All four design-refresh routes are real (Phase E closes migration)
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
        f"Page id {page_id!r} is wired to PlaceholderPage — Phase E was "
        f"supposed to close the migration. All four design-refresh "
        f"routes must render real components."
    )


# ──────────────────────────────────────────────────────────────────────
# 12. Existing per-batch broker-followup-panel substring remains present
# ──────────────────────────────────────────────────────────────────────

def test_existing_per_batch_panel_substring_unchanged(html: str) -> None:
    """The per-batch BrokerFollowupPanel inside BatchDetailPage must still mount."""
    assert "broker-followup-panel" in html, (
        "data-testid `broker-followup-panel` disappeared from dashboard.html. "
        "Phase E is supposed to be additive only — the existing per-batch "
        "panel must remain wired."
    )
    assert re.search(r"function\s+BrokerFollowupPanel\s*\(", html), (
        "BrokerFollowupPanel function declaration disappeared from "
        "dashboard.html. Phase E must not modify it."
    )
