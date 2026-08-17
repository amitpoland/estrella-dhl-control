"""LDG-1 — Client Ledger live wiring pin (ledgers-page.jsx).

Before this slice, ledgers-page.jsx was a fully synthetic mockup mounted LIVE
inside the Accounting hub (accounting-hub.jsx → window.LedgersPage): four
hardcoded clients, invented statement rows, a fabricated "Synced 4 min ago"
chip, fake credit/KUKE utilisation bars and a drawer minting "WF-DOC-" ids —
fake figures on an accounting surface.

This suite pins the repair:
  * the page reads ONLY the canonical ledger read authority
    (routes_ledgers.py: GET /ledgers/clients + /clients/{id}/statement.json)
    through the shared apiFetch transport;
  * every synthetic dataset and the fake sync chip are gone and cannot return;
  * missing capabilities are stated honestly (Lesson M five-state model), not
    faked and not hidden: supplier ledger, credit/KUKE utilisation, last-30d,
    entry cross-links are all "backend pending";
  * honest load/error/empty states carry stable data-testids.
"""
from __future__ import annotations

from pathlib import Path

_V2 = Path(__file__).resolve().parent.parent / "app" / "static" / "v2"


def _src() -> str:
    return (_V2 / "ledgers-page.jsx").read_text(encoding="utf-8", errors="replace")


# ── A. Live authority wiring ──────────────────────────────────────────────

def test_reads_client_balance_authority():
    src = _src()
    # The roster read is routed through the shared PzApi transport authority
    # (pz-api.js: listClientBalancesShared → GET /api/v1/ledgers/clients)
    # with server-side 10-row paging (bulk AR; per_customer_wfirma_calls=0).
    assert "listClientBalancesShared" in src, (
        "Client roster must read via the shared PzApi.listClientBalancesShared "
        "authority (single live /ledgers/clients read shared with Accounting Overview)"
    )
    # Operator decision: compact 20/page rosters (Accounting + Client Balance).
    assert "LDG_LIST_LIMIT = 20" in src, (
        "Client roster must request limit=20 (shared register paging contract)"
    )
    assert "limit: 100" not in src, (
        "Client roster must not request limit=100 (former N+1 timeout path)"
    )


def test_reads_statement_authority():
    src = _src()
    assert "/statement.json" in src, (
        "Statement table must read GET /ledgers/clients/{id}/statement.json "
        "(same authority the statement PDF uses)"
    )
    assert "/statement.pdf" in src, (
        "Statement PDF download must link the existing /statement.pdf route"
    )


def test_uses_shared_transport_only():
    src = _src()
    assert "window.EstrellaShared.apiFetch" in src, (
        "Ledger reads must go through the shared apiFetch transport"
    )
    # No direct wFirma calls, no wrong route prefix (singular /ledger/).
    for forbidden in ("/api/v1/wfirma/", "api2.wfirma.pl", "/api/v1/ledger/clients"):
        assert forbidden not in src, (
            f"Forbidden endpoint '{forbidden}' in ledgers-page.jsx — business "
            "modules consume the ledger authority, never wFirma directly"
        )


# ── B. Synthetic data is gone and cannot return ───────────────────────────

_FORBIDDEN_MOCK_MARKERS = [
    "Synced 4 min ago",     # fabricated sync chip
    "Juliany EOOD",         # hardcoded mock clients
    "Verhoeven Antwerp",
    "Atelier Bonacchi",
    "Estrella Jewels LLP",  # hardcoded mock suppliers
    "Bangkok Gem Co",
    "INV 2026/01",          # invented statement rows
    "PAY-2604-",
    "WF-CT-10",             # minted wFirma contractor ids
    "WF-VN-20",
    "AUD-2604-2148",        # fabricated drawer audit event
    "SHP-2026-0142",        # fabricated drawer shipment link
    "'WF-DOC-' +",          # minted doc ids in the drawer
    "184 KB",               # fake document preview metadata
    # Independent-review HIGH: overdue_invoice_age = aging total − current,
    # which INCLUDES 1–30-day invoices. A "30 days" claim on that figure is
    # factually wrong and triggers premature collection calls.
    "older than 30 days",
]


def test_no_synthetic_data_markers():
    src = _src()
    for marker in _FORBIDDEN_MOCK_MARKERS:
        assert marker not in src, (
            f"Synthetic-data marker '{marker}' found in ledgers-page.jsx — "
            "LDG-1 removed all fabricated ledger data; it must not return"
        )


# ── C. Honest states (Lesson M five-state model) ──────────────────────────

_REQUIRED_TESTIDS = [
    "ldg-load-status",          # header: live read status chip
    "ldg-refresh",              # header: real Refresh action
    "ldg-clients-loading",
    "ldg-clients-error",
    "ldg-clients-empty",
    "ldg-client-unavailable",   # per-row balance_available:false state
    "ldg-statement-pdf",
    "ldg-stmt-loading",
    "ldg-stmt-error",
    "ldg-stmt-empty",
    "ldg-stmt-pdf",
    "ldg-stmt-warnings",
    "ldg-credit-kuke-pending",  # credit/KUKE + exposure: backend pending note
    "ldg-suppliers-loading",    # supplier tab: live AP portfolio loading
    "ldg-suppliers-root",       # supplier tab: live Supplier Ledger
    "ldg-entry-drawer",
    "ldg-entry-links-pending",  # drawer cross-links: backend pending
    "ldg-clients-root",         # full-width client balance table (no permanent rail)
    "ldg-client-tabs",          # Statement / Invoices / Payments / Aging / Info
    "ldg-suppliers-balance-table",
    "ldg-supplier-detail",
    "ldg-filter-search",
    "ldg-clients-pager",
]


def test_honest_state_testids_present():
    src = _src()
    for tid in _REQUIRED_TESTIDS:
        assert f'"{tid}"' in src or f"'{tid}'" in src or f"`{tid}" in src, (
            f"data-testid '{tid}' missing from ledgers-page.jsx — every honest "
            "load/error/empty/pending state must stay addressable"
        )


def test_supplier_tab_wired_to_ap_authority():
    """Lesson M: Suppliers tab stays visible and now consumes live AP routes."""
    src = _src()
    assert "SupplierLedgerView" in src, (
        "Suppliers tab must remain visible (Lesson M — no silent removal)"
    )
    assert "getPayablesAnalysis" in src or "getSupplierStatement" in src
    assert "ldg-suppliers-root" in src or "ldg-suppliers-loading" in src
    # The old synthetic supplier statement components stay gone.
    for gone in ("SupplierHeaderCard", "SupplierStatementTable"):
        assert gone not in src, (
            f"{gone} (synthetic supplier mock) must not return"
        )


def test_backend_has_supplier_ap_routes():
    """Supplier Ledger UI is backed by payables + statement routes."""
    routes = (Path(__file__).resolve().parent.parent / "app" / "api"
              / "routes_ledgers.py").read_text(encoding="utf-8", errors="replace")
    assert "/payables-analysis.json" in routes
    assert "/suppliers/{contractor_id}/statement.json" in routes
    assert "build_payables_analysis" in routes
    assert "aggregate_supplier_statement" in routes


# ── D. Page stays mounted (no duplicate page / renderer) ─────────────────

def test_still_exports_window_ledgers_page():
    src = _src()
    assert "Object.assign(window, { LedgersPage })" in src or \
           "window.LedgersPage = LedgersPage" in src, (
        "ledgers-page.jsx must keep exporting window.LedgersPage — the "
        "Accounting hub mounts it (census AC-5)"
    )


def test_client_statement_lazy_not_per_roster_row():
    """Statement JSON is fetched only when the detail panel is open."""
    src = _src()
    assert "Lazy statement" in src or "only when detail panel open" in src
    assert "detailId" in src
    assert "if (!detailId)" in src


def test_accounting_hub_reaches_supplier_ledger_through_one_mount():
    """The supplier ledger is reachable, and reachable exactly once.

    This pin used to require ``function AccSupplierLedger`` in the hub. That
    component mounted a SECOND whole LedgersPage with its own period state, so
    Management Analysis (and its AP Status filter) existed twice, unsynchronised
    — the "duplicate filter" operators reported. It is deleted. The supplier
    ledger now lives where it always rendered: the LedgersPage tab strip.
    """
    hub = (_V2 / "accounting-hub.jsx").read_text(encoding="utf-8", errors="replace")
    assert "function AccSupplierLedger" not in hub, "no second LedgersPage mount (PR-005)"
    assert hub.count("<LedgersPage") == 1, "LedgersPage must be mounted exactly once"
    assert "acc-supplier-ledger-p0-note" not in hub
    assert "Supplier payable aging remains deferred" not in hub
    src = _src()
    assert "'suppliers'" in src, "LedgersPage must still render the Supplier Ledger tab"
