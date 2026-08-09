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
    # The roster read is now routed through the shared PzApi transport authority
    # (pz-api.js: listClientBalancesShared → GET /api/v1/ledgers/clients?limit=100)
    # so Accounting Overview and this page share ONE live read per navigation. The
    # canonical URL now lives in pz-api.js (pinned by test_ledgers_shared_read.py);
    # this page consumes it via the shared method.
    assert "listClientBalancesShared" in src, (
        "Client roster must read via the shared PzApi.listClientBalancesShared "
        "authority (single live /ledgers/clients read shared with Accounting Overview)"
    )
    assert "limit: 100" in src, (
        "Client roster read must request limit=100 (route maximum), matching the "
        "Accounting Overview read so both share one cache entry"
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
    "ldg-filter-search",        # search input is WIRED (was a dead input)
    "ldg-filter-no-match",      # honest zero-match state for the search
    "ldg-clients-truncated",    # honest note when the roster hits limit=100
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


def test_accounting_hub_supplier_rail_uses_ledgers_page():
    """AccSupplierLedger must mount LedgersPage — no deferred P0 placeholder."""
    hub = (_V2 / "accounting-hub.jsx").read_text(encoding="utf-8", errors="replace")
    assert "function AccSupplierLedger" in hub
    assert 'initialTab="suppliers"' in hub or "initialTab: 'suppliers'" in hub or "initialTab=\"suppliers\"" in hub
    assert "acc-supplier-ledger-p0-note" not in hub
    assert "Supplier payable aging remains deferred" not in hub
    src = _src()
    assert "initialTab" in src
