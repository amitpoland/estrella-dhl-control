"""
test_sprint32_shipments_shell_wiring.py
=======================================
Shipments Hub wiring into the V2 shell (DashboardPage, route `page === 'shipments'`).

Originally Sprint 32 pinned a read-only observer. The V2 front/list parity
campaign (2026-08) restored B1 operational actions on the SAME backend
authority. This file now pins the wiring + discoverability contracts that
still apply, and defers action/mutation contracts to
test_v2_shipments_front_parity.py.
"""
from __future__ import annotations

from pathlib import Path

_V2         = Path(__file__).parent.parent / "app" / "static" / "v2"
_DASH_PAGE  = _V2 / "dashboard-page.jsx"
_MOCK_BADGE = _V2 / "mock-badge.jsx"
_INDEX_HTML = _V2 / "index.html"
_COMPONENTS = _V2 / "components.jsx"


def _src() -> str:
    return _DASH_PAGE.read_text(encoding="utf-8")


def _code_only(src: str) -> str:
    out = []
    for line in src.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("//"):
            continue
        if "//" in line and "http" not in line:
            line = line[: line.index("//")]
        out.append(line)
    return "\n".join(out)


def _shipments_route_block(src: str) -> str:
    idx = src.index("page === 'shipments' && (")
    end = src.find("page === 'dhl'", idx)
    if end < 0:
        end = src.find("page === 'detail'", idx)
    return src[idx:end] if end > idx else src[idx:idx + 1500]


# ── A. mock-badge.jsx — 'shipments' in WIRED_PAGES ──────────────────────────

def test_shipments_in_wired_pages():
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    assert "'shipments'" in src


def test_wired_pages_array_contains_shipments():
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    idx = src.index("WIRED_PAGES")
    arr_body = src[src.index("[", idx):src.index("]", idx)]
    assert "shipments" in arr_body


def test_existing_wired_pages_preserved():
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    idx = src.index("WIRED_PAGES")
    arr_body = src[src.index("[", idx):src.index("]", idx)]
    for page in ("proforma", "inbox", "inventory", "dhl"):
        assert page in arr_body


# ── B. DashboardPage — live wiring, export, testids ─────────────────────────

def test_dashboard_page_uses_estrella_shared_api_fetch():
    src = _src()
    assert "window.EstrellaShared.apiFetch" in src or "EstrellaShared.apiFetch" in src


def test_shipments_hub_root_testid_present():
    assert 'data-testid="shipments-hub-root"' in _src()


def test_dashboard_page_exported_on_window():
    assert "DashboardPage" in _src()
    assert "Object.assign(window, { DashboardPage })" in _src() or "DashboardPage" in _src()


# ── C. Endpoint contract — canonical dashboard batch authority ──────────────

ALLOWED_ENDPOINTS = {
    "/api/v1/dashboard/batches",
    "/api/v1/dashboard/archive",
}


def test_allowed_list_endpoint_referenced():
    assert "/api/v1/dashboard/batches" in _src()


def test_no_foreign_dashboard_domains():
    """Shipments list must not pull proforma/cn/email/override authorities."""
    code = _code_only(_src())
    for ep in ("/action-diagnostics", "/email-evidence", "/proforma-readiness",
               "/zc429-lineage", "/cn-hsn-classification", "/cn-decision",
               "/operator-override", "/broker-followups"):
        assert ep not in code, f"foreign endpoint leaked into shipments hub: {ep}"


# ── D. Mock data retired ────────────────────────────────────────────────────

def test_mock_shipments_constant_retired():
    code = _code_only(_src())
    assert "const MOCK_SHIPMENTS = [" not in code
    assert "window.MOCK_SHIPMENTS" not in code


def test_static_summary_cards_constant_retired():
    code = _code_only(_src())
    assert "const SUMMARY_CARDS = [" not in code


def test_mock_awb_literals_retired():
    code = _code_only(_src())
    for lit in ("DHL-1234567890", "DHL-9876543210", "FDX-0011223344",
                "PL12345678901234A", "SHP-001", "SHP-007"):
        assert lit not in code


# ── E. Tracking URL scheme guard ────────────────────────────────────────────

def test_tracking_url_scheme_guarded():
    code = _code_only(_src())
    assert "_shSafeHttpUrl" in code or "_safeHttpUrl" in code
    assert "https?:" in code
    assert "href={row.tracking_url}" not in code


# ── F. index.html — shipments route renders DashboardPage ───────────────────

def test_index_html_shipments_route_renders_dashboard_page():
    block = _shipments_route_block(_INDEX_HTML.read_text(encoding="utf-8"))
    assert "DashboardPage" in block


def test_shipments_header_declares_operational_hub():
    block = _shipments_route_block(_INDEX_HTML.read_text(encoding="utf-8")).lower()
    assert "operational" in block or "newest" in block


def test_shipments_header_no_dead_export_in_pageheader():
    """Export CSV lives inside DashboardPage, not as a dead PageHeader action."""
    block = _shipments_route_block(_INDEX_HTML.read_text(encoding="utf-8"))
    # PageHeader actions must not carry Export CSV; the hub has its own control.
    assert "PageHeader" in block
    # Allow the word only if it is NOT inside the PageHeader line.
    header_line = [ln for ln in block.splitlines() if "PageHeader" in ln]
    for ln in header_line:
        assert "Export CSV" not in ln


# ── G. Required testids ─────────────────────────────────────────────────────

ELEMENT_TESTIDS = [
    "shipments-hub-root",
    "shipments-hub-reload",
    "shipments-hub-summary",
    "shipments-hub-table",
]


def test_required_testids_present():
    src = _src()
    missing = [t for t in ELEMENT_TESTIDS if f'data-testid="{t}"' not in src]
    assert not missing, f"DashboardPage missing testids: {missing}"


def test_reload_button_present():
    assert "shipments-hub-reload" in _code_only(_src())


# ── H. NAV_TREE — Shipments discoverability ─────────────────────────────────

def test_shipments_in_nav_tree():
    src = _COMPONENTS.read_text(encoding="utf-8")
    nav_body = src[src.index("NAV_TREE = ["):src.index("];", src.index("NAV_TREE = ["))]
    assert "id: 'shipments'" in nav_body


def test_existing_nav_entries_preserved():
    src = _COMPONENTS.read_text(encoding="utf-8")
    nav_body = src[src.index("NAV_TREE = ["):src.index("];", src.index("NAV_TREE = ["))]
    for page_id in ("dashboard", "inbox", "shipments", "proforma",
                    "documents", "accounting", "inventory", "reports", "dhl"):
        assert f"id: '{page_id}'" in nav_body
