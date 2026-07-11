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
    assert "{ limit: 100 }" in src, (
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
    "ldg-suppliers-pending",    # supplier tab: honest backend-pending panel
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


def test_supplier_tab_visible_but_honest():
    """Lesson M: the Suppliers tab STAYS (no capability suppression) but states
    its real status — no supplier ledger route exists in routes_ledgers.py."""
    src = _src()
    assert "SupplierLedgerView" in src, (
        "Suppliers tab must remain visible (Lesson M — no silent removal)"
    )
    assert "backend pending" in src.lower(), (
        "Missing capabilities must be declared 'backend pending', not faked"
    )
    # The old synthetic supplier statement components are gone.
    for gone in ("SupplierHeaderCard", "SupplierStatementTable"):
        assert gone not in src, (
            f"{gone} (synthetic supplier mock) must not return without a real "
            "supplier ledger authority behind it"
        )


def test_backend_matches_no_supplier_routes_assumption():
    """The supplier panel's honesty claim is only valid while routes_ledgers.py
    really has no supplier route. If one is added, the panel must be wired
    instead — this test forces that reconciliation."""
    routes = (Path(__file__).resolve().parent.parent / "app" / "api"
              / "routes_ledgers.py").read_text(encoding="utf-8", errors="replace")
    assert "/suppliers" not in routes, (
        "routes_ledgers.py now serves a supplier route — wire the Suppliers "
        "tab to it and retire the backend-pending panel (update LDG pin)"
    )


# ── D. Page stays mounted (no duplicate page / renderer) ─────────────────

def test_still_exports_window_ledgers_page():
    src = _src()
    assert "Object.assign(window, { LedgersPage })" in src or \
           "window.LedgersPage = LedgersPage" in src, (
        "ledgers-page.jsx must keep exporting window.LedgersPage — the "
        "Accounting hub mounts it (census AC-5)"
    )
