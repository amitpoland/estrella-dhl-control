"""
test_dashboard_customer_statements_picker.py

Phase C of the dashboard design refresh — verify the new read-only
Customer Statements picker page has landed correctly:

  * CustomerStatementsPickerPage component is defined.
  * The page exposes data-testid="customer-statements-picker".
  * The Refresh button is wired with data-testid="btn-customer-statements-refresh".
  * The search input is wired with data-testid="customer-statements-search".
  * The page consumes only one existing endpoint:
      GET /api/v1/wfirma/customers
  * The page does NOT call /statement.json or /statement.pdf directly.
    Statement loads stay inside CustomerStatementDrawer (the existing
    Phase 10D component).
  * The picker opens CustomerStatementDrawer when a row is selected.
  * The picker component body contains no write-button labels:
      Create, Edit, Delete, Sync, Export, Send.
  * The picker contains none of the design-bundle invented endpoints.
  * The App router replaces the placeholder for `statements` and
    renders the new component.
  * The remaining Phase A placeholders (proposals, broker) stay
    placeholders.
  * Phase B's `proforma` route remains wired to
    ProformaDraftsCrossBatchPage.

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
    Slice the source between `function CustomerStatementsPickerPage(`
    and the next top-level `function ` declaration. Returns "" if not
    found.
    """
    start_match = re.search(
        r"function\s+CustomerStatementsPickerPage\s*\(", html
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
    pattern = re.compile(r"function\s+CustomerStatementsPickerPage\s*\(")
    assert pattern.search(html), (
        "CustomerStatementsPickerPage component declaration not found in "
        "dashboard.html. Phase C did not land."
    )


# ──────────────────────────────────────────────────────────────────────
# 2. Root testid is present
# ──────────────────────────────────────────────────────────────────────

def test_root_testid_present(html: str) -> None:
    assert 'data-testid="customer-statements-picker"' in html, (
        "Required root testid `customer-statements-picker` missing."
    )


# ──────────────────────────────────────────────────────────────────────
# 3. Refresh button testid is present
# ──────────────────────────────────────────────────────────────────────

def test_refresh_button_testid_present(html: str) -> None:
    assert 'data-testid="btn-customer-statements-refresh"' in html, (
        "Refresh button testid `btn-customer-statements-refresh` missing."
    )


# ──────────────────────────────────────────────────────────────────────
# 4. Search input testid is present
# ──────────────────────────────────────────────────────────────────────

def test_search_input_testid_present(html: str) -> None:
    assert 'data-testid="customer-statements-search"' in html, (
        "Search input testid `customer-statements-search` missing."
    )


# ──────────────────────────────────────────────────────────────────────
# 5. Uses /api/v1/wfirma/customers
# ──────────────────────────────────────────────────────────────────────

def test_uses_wfirma_customers_endpoint(html: str) -> None:
    body = _component_body(html)
    assert body, "Could not slice CustomerStatementsPickerPage component body."
    assert "/api/v1/wfirma/customers" in body, (
        "Picker component does not call /api/v1/wfirma/customers. "
        "Phase C requires this single endpoint for the customer list."
    )


# ──────────────────────────────────────────────────────────────────────
# 6. Picker page does NOT directly call /statement.json
# ──────────────────────────────────────────────────────────────────────

def test_no_direct_statement_json_call(html: str) -> None:
    body = _component_body(html)
    assert body, "Could not slice picker component body."
    assert "/statement.json" not in body, (
        "Picker component contains /statement.json. The picker must NOT "
        "fetch statement data directly — that work lives in "
        "CustomerStatementDrawer."
    )


# ──────────────────────────────────────────────────────────────────────
# 7. Picker page does NOT directly call /statement.pdf
# ──────────────────────────────────────────────────────────────────────

def test_no_direct_statement_pdf_call(html: str) -> None:
    body = _component_body(html)
    assert body, "Could not slice picker component body."
    assert "/statement.pdf" not in body, (
        "Picker component contains /statement.pdf. The picker must NOT "
        "fetch the PDF directly — the drawer handles PDF retrieval."
    )


# ──────────────────────────────────────────────────────────────────────
# 8. Existing CustomerStatementDrawer still exists
# ──────────────────────────────────────────────────────────────────────

def test_drawer_component_unchanged(html: str) -> None:
    """The Phase 10D drawer must still be defined in the file."""
    assert re.search(r"function\s+CustomerStatementDrawer\s*\(", html), (
        "CustomerStatementDrawer function disappeared from dashboard.html. "
        "Phase C must not modify it."
    )
    assert "customer-statement-drawer" in html, (
        "data-testid `customer-statement-drawer` disappeared. The existing "
        "drawer must remain intact."
    )


# ──────────────────────────────────────────────────────────────────────
# 9. Picker opens CustomerStatementDrawer
# ──────────────────────────────────────────────────────────────────────

def test_picker_opens_drawer(html: str) -> None:
    body = _component_body(html)
    assert body, "Could not slice picker component body."
    # The picker should render <CustomerStatementDrawer ... /> conditionally.
    # We accept either single or no whitespace between the angle and name.
    assert re.search(r"<\s*CustomerStatementDrawer\b", body), (
        "Picker component does not render CustomerStatementDrawer. "
        "Phase C requires the picker to open the existing drawer for the "
        "selected customer."
    )


# ──────────────────────────────────────────────────────────────────────
# 10. Picker component body contains no write-button labels
# ──────────────────────────────────────────────────────────────────────

WRITE_BUTTON_LABELS = ["Create", "Edit", "Delete", "Sync", "Export", "Send"]


@pytest.mark.parametrize("label", WRITE_BUTTON_LABELS)
def test_no_write_button_labels(html: str, label: str) -> None:
    body = _component_body(html)
    assert body, "Could not slice picker component body."
    assert label not in body, (
        f"Write-button label {label!r} appears inside the picker component. "
        f"The picker is read-only — no Create / Edit / Delete / Sync / "
        f"Export / Send actions are allowed."
    )


# ──────────────────────────────────────────────────────────────────────
# 11. Picker contains none of the design-bundle invented endpoints
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
        f"Backend does not implement that path; Phase C must not surface it."
    )


# ──────────────────────────────────────────────────────────────────────
# 12. App router renders CustomerStatementsPickerPage for `statements`,
#     not PlaceholderPage
# ──────────────────────────────────────────────────────────────────────

def test_app_router_uses_real_page(html: str) -> None:
    pattern = re.compile(r"page\s*===\s*'statements'[^\n]*")
    matches = pattern.findall(html)
    assert matches, "No conditional render line for page === 'statements'."
    real_match = any("CustomerStatementsPickerPage" in line for line in matches)
    assert real_match, (
        f"page === 'statements' is not wired to CustomerStatementsPickerPage. "
        f"Render lines found: {matches!r}"
    )
    placeholder_match = any("PlaceholderPage" in line for line in matches)
    assert not placeholder_match, (
        f"page === 'statements' is still wired to PlaceholderPage somewhere. "
        f"Phase C should have replaced it. Render lines: {matches!r}"
    )


# ──────────────────────────────────────────────────────────────────────
# 13. The remaining nav placeholders stay placeholders
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
        f"Phase C was supposed to only replace the statements placeholder. "
        f"Render lines found: {matches!r}"
    )


# ──────────────────────────────────────────────────────────────────────
# 14. Phase B `proforma` route remains ProformaDraftsCrossBatchPage
# ──────────────────────────────────────────────────────────────────────

def test_phase_b_proforma_unchanged(html: str) -> None:
    pattern = re.compile(r"page\s*===\s*'proforma'[^\n]*")
    matches = pattern.findall(html)
    assert matches, "No conditional render line for page === 'proforma'."
    real_match = any("ProformaDraftsCrossBatchPage" in line for line in matches)
    assert real_match, (
        f"page === 'proforma' is no longer wired to "
        f"ProformaDraftsCrossBatchPage. Phase C must not regress Phase B. "
        f"Render lines: {matches!r}"
    )
