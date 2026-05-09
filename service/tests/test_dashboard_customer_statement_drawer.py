"""
test_dashboard_customer_statement_drawer.py — Phase 10D dashboard wiring.

Source-grep contract pins for the read-only Customer Statement drawer
that lives inside the wFirma Customer Mapping table (in
``WfirmaExportPage``). The drawer wires to the existing Phase 10B/10C
endpoints; no new backend surface.

Each test pins one rule from the Phase 10D task spec.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

DASHBOARD = (
    Path(__file__).resolve().parent.parent
    / "app" / "static" / "dashboard.html"
)


@pytest.fixture(scope="module")
def html() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


# ── 1. Customer Mapping row carries the Statement button ──────────────────

def test_customer_mapping_row_contains_statement_button(html):
    # Per-row testid uses ${c.client_name} interpolation. We grep for the
    # template literal pattern + the visible button label.
    assert 'data-testid={`btn-customer-statement-${c.client_name}`}' in html, (
        "Each Customer Mapping row must carry a per-row Statement "
        "button with data-testid='btn-customer-statement-<client>'"
    )
    # Visible label "Statement" exists inside the button block.
    idx = html.find('data-testid={`btn-customer-statement-${c.client_name}`}')
    assert idx > 0
    window = html[idx:idx + 800]
    # The Btn child is "Statement" (allowing any whitespace/indentation
    # between the > and the word).
    assert re.search(r">\s*Statement\s*<", window), (
        "Statement label must appear inside the button block"
    )


def test_statement_button_only_in_customer_mapping_card(html):
    """The button must live inside the Customer Mapping row block.
    Confirms it's not duplicated elsewhere (e.g., on a Proforma
    Draft panel — that's deferred to Phase 10D.1)."""
    occurrences = html.count(
        'data-testid={`btn-customer-statement-${c.client_name}`}'
    )
    assert occurrences == 1, (
        f"Statement button must appear exactly once "
        f"(found {occurrences})"
    )


# ── 2. Drawer component wired ─────────────────────────────────────────────

def test_drawer_is_rendered_via_customerForStatement_state(html):
    assert "customerForStatement" in html
    assert "setCustomerForStatement" in html
    # The drawer mounts when customerForStatement is non-null.
    assert "{customerForStatement && (" in html
    assert "<CustomerStatementDrawer" in html


def test_drawer_root_carries_testid(html):
    assert 'data-testid="customer-statement-drawer"' in html


def test_drawer_component_definition_exists(html):
    assert "function CustomerStatementDrawer(" in html


# ── 3. JSON fetch URL ──────────────────────────────────────────────────────

def test_drawer_fetches_statement_json_url(html):
    assert "/api/v1/ledgers/clients/" in html
    assert "/statement.json" in html
    # Both segments must appear within ~400 chars of each other inside
    # the drawer's onRefresh handler — look for the template literal.
    pattern = re.compile(
        r"`/api/v1/ledgers/clients/\$\{encodeURIComponent\(cid\)\}`?"
        r"\s*\+\s*`/statement\.json`",
    )
    assert pattern.search(html), (
        "JSON fetch URL must use the encoded contractor id template "
        "literal pattern"
    )


# ── 4. PDF link ───────────────────────────────────────────────────────────

def test_pdf_link_present(html):
    assert 'data-testid="customer-statement-pdf-link"' in html


def test_pdf_link_uses_statement_pdf_path(html):
    idx = html.find('data-testid="customer-statement-pdf-link"')
    assert idx > 0
    window = html[max(0, idx - 1200):idx + 400]
    # PDF URL is built once and stored in `pdfHref`. Confirm both the
    # variable definition and the path.
    assert "/statement.pdf" in window or "/statement.pdf" in html


def test_pdf_link_uses_encodeURIComponent(html):
    """The contractor id must be URL-encoded before being placed in
    the PDF href to prevent path-injection on operator-supplied ids."""
    pattern = re.compile(
        r"/api/v1/ledgers/clients/\$\{encodeURIComponent\(cid\)\}"
        r"`?\s*\+\s*`?/statement\.pdf",
    )
    assert pattern.search(html), (
        "PDF href must encodeURIComponent(cid) before /statement.pdf"
    )


def test_pdf_link_query_string_includes_pickers(html):
    """The PDF link must mirror the live picker values (from / to /
    as_of) so the downloaded PDF matches what's on screen."""
    idx = html.find('data-testid="customer-statement-pdf-link"')
    assert idx > 0
    # pdfHref is computed earlier; locate the const.
    href_def = html.find("const pdfHref = (")
    assert href_def > 0
    window = html[href_def:href_def + 800]
    assert "encodeURIComponent(from_)" in window
    assert "encodeURIComponent(to)"    in window
    assert "encodeURIComponent(asOf)"  in window
    assert "?from="   in window
    assert "&to="     in window
    assert "&as_of="  in window


# ── 5. Date inputs ────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", [
    "customer-statement-from",
    "customer-statement-to",
    "customer-statement-as-of",
])
def test_date_inputs_present(html, tid):
    assert f'data-testid="{tid}"' in html


def test_date_inputs_use_type_date(html):
    """All three date pickers must use <input type="date"> for the
    browser-native picker. We grep three occurrences within the
    drawer."""
    idx = html.find("function CustomerStatementDrawer(")
    end = html.find("\nfunction ", idx + 1)
    block = html[idx:end] if end > idx else html[idx:]
    assert block.count('type="date"') >= 3


# ── 6. Refresh button ──────────────────────────────────────────────────────

def test_refresh_button_exists(html):
    assert 'data-testid="btn-customer-statement-refresh"' in html


def test_refresh_button_invokes_onRefresh(html):
    """Refresh button must call ``onRefresh`` (the only function in
    the drawer that fires a /statement.json fetch). This pin guards
    against accidentally wiring an auto-refresh elsewhere."""
    idx = html.find('data-testid="btn-customer-statement-refresh"')
    assert idx > 0
    window = html[max(0, idx - 200):idx + 400]
    assert "onClick={onRefresh}" in window


# ── 7. Aging method label — "Invoice age" present, "Due date" absent ─────

def test_invoice_age_label_present(html):
    """The literal 'Invoice age' must appear in the drawer source."""
    idx = html.find("function CustomerStatementDrawer(")
    end = html.find("\nfunction ", idx + 1)
    block = html[idx:end] if end > idx else html[idx:]
    assert "Invoice age" in block


def test_due_date_label_not_used_anywhere(html):
    """Phase 10A.5 real-id probe must verify <paymentdate> before
    due-date aging is allowed. The literal 'Due date' must not appear
    anywhere in dashboard source."""
    # Tolerate punctuation variants.
    for forbidden in ("Due date", "Due-date", "DueDate"):
        assert forbidden not in html, (
            f"Forbidden aging-method label {forbidden!r} found in "
            "dashboard. Phase 10A.5 real-id probe must verify "
            "<paymentdate> before due-date aging is enabled."
        )


# ── 8. No fake / unsafe buttons ──────────────────────────────────────────

@pytest.mark.parametrize("forbidden_substring", [
    "Email Statement",
    "Send Statement",
    "Export to XLSX",
    "Export Statement",
    "Mark as paid",
    "payments/add",
    "payments/edit",
    "payments/delete",
    "Record Payment",
])
def test_no_fake_buttons_in_drawer(html, forbidden_substring):
    """Phase 10D rule: no email / send / export / payment-write
    surface. Backend has no such endpoints today; surfacing them
    would be a fake-button violation."""
    idx = html.find("function CustomerStatementDrawer(")
    end = html.find("\nfunction ", idx + 1)
    block = html[idx:end] if end > idx else html[idx:]
    assert forbidden_substring not in block, (
        f"Forbidden surface {forbidden_substring!r} appears inside "
        "CustomerStatementDrawer — remove it"
    )


def test_no_invoice_ledger_button_in_drawer(html):
    """Phase 10D scope: Statement is the operator's primary surface;
    invoice-ledger.json is API-consumer-only and must not be
    surfaced as a button."""
    idx = html.find("function CustomerStatementDrawer(")
    end = html.find("\nfunction ", idx + 1)
    block = html[idx:end] if end > idx else html[idx:]
    assert "/invoice-ledger.json" not in block, (
        "invoice-ledger.json must not be surfaced from the Statement "
        "drawer in Phase 10D"
    )


# ── 9. Conditional unmatched payments + warnings blocks ──────────────────

def test_unmatched_block_renders_conditionally(html):
    """The unmatched-payments mini-table must be guarded by
    `unmatched.length > 0` (or equivalent). It must NOT render a
    permanently-visible empty block."""
    idx = html.find("function CustomerStatementDrawer(")
    end = html.find("\nfunction ", idx + 1)
    block = html[idx:end] if end > idx else html[idx:]
    assert "unmatched.length > 0 && (" in block, (
        "Unmatched payments block must be conditional on "
        "unmatched.length > 0"
    )
    # And the block must carry a per-currency testid.
    assert "data-testid={`customer-statement-unmatched-${ccy}`}" in block


def test_warnings_block_renders_conditionally(html):
    idx = html.find("function CustomerStatementDrawer(")
    end = html.find("\nfunction ", idx + 1)
    block = html[idx:end] if end > idx else html[idx:]
    assert "(statement.warnings || []).length > 0 && (" in block, (
        "Warnings block must be conditional on warnings.length > 0"
    )
    assert 'data-testid="customer-statement-warnings"' in block


# ── 10. Multi-currency separation ────────────────────────────────────────

def test_per_currency_section_uses_currencies_array(html):
    """The drawer must iterate `statement.currencies` — never assume
    a single currency."""
    idx = html.find("function CustomerStatementDrawer(")
    end = html.find("\nfunction ", idx + 1)
    block = html[idx:end] if end > idx else html[idx:]
    assert "(statement.currencies || []).map(ccy => {" in block
    # Per-currency section testid present.
    assert "data-testid={`customer-statement-currency-${ccy}`}" in block


# ── 11. No automatic statement fetch on dashboard mount ───────────────────

def test_no_auto_fetch_on_mount(html):
    """Confirm there is NO ``useEffect`` that fires
    /api/v1/ledgers/clients/...statement.json on dashboard mount.
    The fetch URL must only appear inside ``onRefresh`` (which is an
    operator-explicit click handler)."""
    # Locate the drawer block.
    idx = html.find("function CustomerStatementDrawer(")
    end = html.find("\nfunction ", idx + 1)
    block = html[idx:end] if end > idx else html[idx:]
    # The /statement.json URL must appear inside the onRefresh
    # function body. Confirm the fetch lives ONLY there.
    refresh_idx = block.find("onRefresh = React.useCallback(async ()")
    assert refresh_idx > 0
    refresh_end = block.index("}, [", refresh_idx)
    refresh_block = block[refresh_idx:refresh_end]
    assert "/statement.json" in refresh_block

    # OUTSIDE the onRefresh helper, /statement.json must NOT appear
    # in any apiFetch call site.
    outside = block[:refresh_idx] + block[refresh_end:]
    # The URL string itself can survive only inside the PDF href
    # (which uses /statement.pdf, not .json) — search for .json.
    suspicious = re.findall(r"apiFetch\([^)]*statement\.json", outside)
    assert not suspicious, (
        "Auto-fetch of /statement.json detected outside onRefresh — "
        "operator must explicitly click Refresh"
    )


def test_drawer_does_not_use_react_useEffect_on_mount(html):
    """Belt-and-braces: the drawer must not declare a useEffect that
    runs on mount (which would auto-fetch). We allow no useEffect at
    all in the drawer scope."""
    idx = html.find("function CustomerStatementDrawer(")
    end = html.find("\nfunction ", idx + 1)
    block = html[idx:end] if end > idx else html[idx:]
    assert "React.useEffect" not in block, (
        "CustomerStatementDrawer must not declare useEffect — "
        "operator-explicit Refresh is the only fetch path"
    )


# ── 12. Empty / loading / error states ──────────────────────────────────

def test_empty_state_present(html):
    idx = html.find("function CustomerStatementDrawer(")
    end = html.find("\nfunction ", idx + 1)
    block = html[idx:end] if end > idx else html[idx:]
    assert 'data-testid="customer-statement-empty"' in block


def test_loading_state_visible(html):
    idx = html.find("function CustomerStatementDrawer(")
    end = html.find("\nfunction ", idx + 1)
    block = html[idx:end] if end > idx else html[idx:]
    # The Refresh button shows "Loading…" while the fetch is in flight.
    assert "Loading…" in block


def test_error_state_uses_red_badge(html):
    """An error state must visually surface (not silently swallow)."""
    idx = html.find("function CustomerStatementDrawer(")
    end = html.find("\nfunction ", idx + 1)
    block = html[idx:end] if end > idx else html[idx:]
    assert "var(--badge-red-bg)" in block
    assert "var(--badge-red-text)" in block


# ── 13. Existing JSON / PDF endpoints unchanged (regression) ──────────────

def test_routes_ledgers_still_has_three_endpoints():
    """Phase 10D is dashboard-only — routes_ledgers.py must keep all
    three Phase 10A/B/C endpoints unchanged."""
    routes_path = (
        Path(__file__).resolve().parent.parent
        / "app" / "api" / "routes_ledgers.py"
    )
    src = routes_path.read_text(encoding="utf-8")
    assert "/clients/{contractor_id}/invoice-ledger.json" in src
    assert "/clients/{contractor_id}/statement.json"      in src
    assert "/clients/{contractor_id}/statement.pdf"       in src


# ── 14. Aging-method testid pinned ────────────────────────────────────────

def test_aging_method_label_carries_testid(html):
    assert 'data-testid="customer-statement-aging-method"' in html


# ── 15. Drawer is mounted (not just defined) ──────────────────────────────

def test_drawer_is_actually_mounted_in_wfirma_export_page(html):
    """The component must be rendered when customerForStatement is
    non-null. We grep the WfirmaExportPage closing block."""
    # Find the conditional render of the drawer
    assert "customerForStatement && (" in html
    # And confirm CustomerStatementDrawer is the rendered component.
    idx = html.find("customerForStatement && (")
    assert idx > 0
    window = html[idx:idx + 400]
    assert "<CustomerStatementDrawer" in window
    assert "customer={customerForStatement}" in window
