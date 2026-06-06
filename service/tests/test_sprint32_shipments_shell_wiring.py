"""
test_sprint32_shipments_shell_wiring.py
=======================================
Sprint 32 regression tests: Shipments Hub wired into the V2 shell as a
read-only observer surface (DashboardPage, route `page === 'shipments'`).

Source-grep tests pinning the wiring contract:
  - 'shipments' added to WIRED_PAGES (no MOCK banner); prior wired pages intact
  - DashboardPage uses window.EstrellaShared.apiFetch
  - Exactly the 1 allowed endpoint (/api/v1/dashboard/batches); no deferred sub-endpoints
  - No write HTTP methods in dashboard-page.jsx
  - No forbidden affordance strings (Reprocess / Regenerate / Recheck / Archive /
    Delete / Resend / Operator-override / CN-decision / Edit Draft) as controls
  - P3: MOCK_SHIPMENTS + static SUMMARY_CARDS retired; mock AWB literals gone;
    Prev/Next pagination removed
  - shipments-hub-root + required testids present; read-only disclaimer present
  - index.html shipments route still renders <DashboardPage />
  - NAV_TREE 'shipments' entry preserved (P2 reachability)

References:
  .claude/campaigns/atlas-v2/sprint-32-shipments-hub.md
  service/app/static/v2/dashboard-page.jsx   (DashboardPage)
  service/app/static/v2/mock-badge.jsx       (WIRED_PAGES)
  service/app/static/v2/index.html           (shipments route block)
  service/app/static/v2/components.jsx        (NAV_TREE)
"""
from __future__ import annotations

import re
from pathlib import Path

_V2         = Path(__file__).parent.parent / "app" / "static" / "v2"
_DASH_PAGE  = _V2 / "dashboard-page.jsx"
_MOCK_BADGE = _V2 / "mock-badge.jsx"
_INDEX_HTML = _V2 / "index.html"
_COMPONENTS = _V2 / "components.jsx"


def _src() -> str:
    return _DASH_PAGE.read_text(encoding="utf-8")


def _code_only(src: str) -> str:
    """Strip `//` single-line comments so prose in the header/disclaimer comments
    never trips a forbidden-token scan. Block comments are not used here."""
    out = []
    for line in src.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("//"):
            continue
        # strip trailing inline // comments (no URLs with // in this file's code)
        if "//" in line and "http" not in line:
            line = line[: line.index("//")]
        out.append(line)
    return "\n".join(out)


def _shipments_route_block(src: str) -> str:
    """The JSX shipments route block in index.html, anchored by the unique
    conditional `page === 'shipments' && (`."""
    idx = src.index("page === 'shipments' && (")
    end = src.find("page === 'dhl'", idx)
    if end < 0:
        end = src.find("page === 'detail'", idx)
    return src[idx:end] if end > idx else src[idx:idx + 1500]


# ══════════════════════════════════════════════════════════════════════════════
# A. mock-badge.jsx — 'shipments' in WIRED_PAGES
# ══════════════════════════════════════════════════════════════════════════════

def test_shipments_in_wired_pages():
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    assert "'shipments'" in src, "mock-badge.jsx WIRED_PAGES must include 'shipments'"


def test_wired_pages_array_contains_shipments():
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    idx = src.index("WIRED_PAGES")
    arr_body = src[src.index("[", idx):src.index("]", idx)]
    assert "shipments" in arr_body, "'shipments' must be inside the WIRED_PAGES array literal"


def test_existing_wired_pages_preserved():
    """Regression: the 5 previously-wired domains remain wired."""
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    idx = src.index("WIRED_PAGES")
    arr_body = src[src.index("[", idx):src.index("]", idx)]
    # proforma_detail intentionally removed Sprint 36 Phase 0 (2026-06-06) — authority violation
    for page in ("proforma", "inbox", "inventory", "dhl"):
        assert page in arr_body, f"{page!r} must remain in WIRED_PAGES"


# ══════════════════════════════════════════════════════════════════════════════
# B. DashboardPage — live wiring, export, testids
# ══════════════════════════════════════════════════════════════════════════════

def test_dashboard_page_uses_estrella_shared_api_fetch():
    src = _src()
    assert "window.EstrellaShared.apiFetch" in src or "EstrellaShared.apiFetch" in src, (
        "DashboardPage must use window.EstrellaShared.apiFetch (auth-aware shim)"
    )


def test_shipments_hub_root_testid_present():
    assert 'data-testid="shipments-hub-root"' in _src(), (
        "DashboardPage must carry data-testid='shipments-hub-root'"
    )


def test_dashboard_page_exported_on_window():
    assert "DashboardPage" in _src()
    assert "window" in _src() and "DashboardPage" in _src(), (
        "DashboardPage must be exported on window for the shell to render it"
    )


# ══════════════════════════════════════════════════════════════════════════════
# C. Endpoint contract — exactly the 1 allowed; no deferred sub-endpoints
# ══════════════════════════════════════════════════════════════════════════════

ALLOWED_ENDPOINT = "/api/v1/dashboard/batches"

# Deferred batch sub-endpoints that must NOT appear in this read-only list page.
DEFERRED_BATCH_ENDPOINTS = [
    "/dashboard/batches/{",
    "/batches/{batch_id}",
    "/dashboard/broker-followups",
    "/dashboard/archive",
    "/action-diagnostics",
    "/email-evidence",
    "/proforma-readiness",
    "/zc429-lineage",
    "/cn-hsn-classification",
    "/dhl-action-state",
    "/cn-decision",
    "/operator-override",
    "/regenerate",
    "/recheck",
    "/resend",
]


def test_allowed_endpoint_referenced():
    assert ALLOWED_ENDPOINT in _src(), (
        f"DashboardPage must reference the allowed endpoint: {ALLOWED_ENDPOINT}"
    )


def test_no_deferred_batch_endpoints():
    code = _code_only(_src())
    present = [ep for ep in DEFERRED_BATCH_ENDPOINTS if ep in code]
    assert not present, (
        f"DashboardPage must NOT reference deferred/write batch sub-endpoints: {present}"
    )


def test_no_unknown_dashboard_endpoints():
    """Any /api/v1/dashboard/* string must be exactly the allowed list endpoint."""
    code = _code_only(_src())
    refs = set(re.findall(r"/api/v1/dashboard/[a-zA-Z0-9_\-/{}]+", code))
    unknown = refs - {ALLOWED_ENDPOINT}
    assert not unknown, (
        f"DashboardPage references dashboard endpoints outside the 1 allowed: {sorted(unknown)}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# D. NO write HTTP methods
# ══════════════════════════════════════════════════════════════════════════════

FORBIDDEN_WRITE_METHOD_TOKENS = [
    "method: 'POST'",   'method: "POST"',   "method:'POST'",
    "method: 'PUT'",    'method: "PUT"',    "method:'PUT'",
    "method: 'PATCH'",  'method: "PATCH"',  "method:'PATCH'",
    "method: 'DELETE'", 'method: "DELETE"', "method:'DELETE'",
]


def test_no_write_http_methods():
    code = _code_only(_src())
    present = [tok for tok in FORBIDDEN_WRITE_METHOD_TOKENS if tok in code]
    assert not present, (
        f"dashboard-page.jsx must contain NO write HTTP methods: {present}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# E. NO forbidden affordance controls — visibility-only invariant (brief §4)
# ══════════════════════════════════════════════════════════════════════════════

# Checked against comment-stripped code (prose in // comments is allowed to
# explain what was removed). These are the mock action-menu labels + write verbs.
FORBIDDEN_AFFORDANCES_LOWER = [
    "edit draft",
    "reprocess",
    "regenerate",
    "recheck",
    "operator-override",
    "accept-sad",
    "escalate-agent",
    "correct-internal",
    "← prev",
    "next →",
]


def test_no_forbidden_affordance_controls():
    code = _code_only(_src()).lower()
    present = [s for s in FORBIDDEN_AFFORDANCES_LOWER if s in code]
    assert not present, (
        f"DashboardPage must contain none of these affordance strings (code region): {present}"
    )


def test_no_action_menu_array():
    """The mock `['Edit Draft', 'Reprocess', 'Archive', 'Delete']` action menu must be gone."""
    code = _code_only(_src())
    assert "'Reprocess'" not in code and '"Reprocess"' not in code, "action menu must be retired"
    assert "'Archive'" not in code and '"Archive"' not in code, "action menu must be retired"
    assert "setActionMenu" not in code, "action-menu state handler must be removed"


def test_no_button_with_write_verb_child():
    """No JSX button/element whose visible text is a write verb."""
    code = _code_only(_src())
    for verb in ("Reprocess", "Regenerate", "Recheck", "Archive", "Resend"):
        assert f">{verb}<" not in code, f"no element may render '{verb}' as a control label"


def test_tracking_url_scheme_guarded():
    """The AWB external link must only render http(s) URLs (no javascript:/data: href).

    Defence in depth: the href must be a scheme-validated value, not the raw field.
    """
    code = _code_only(_src())
    assert "_safeHttpUrl" in code, "tracking_url must pass through an http(s) scheme guard"
    assert "^https?:" in code or "https?:" in code, "scheme guard must restrict to http(s)"
    # The raw field must NOT be assigned directly to href.
    assert "href={row.tracking_url}" not in code, (
        "AWB href must use the scheme-guarded value, not row.tracking_url directly"
    )


# ══════════════════════════════════════════════════════════════════════════════
# F. P3 — mock data retired
# ══════════════════════════════════════════════════════════════════════════════

def test_mock_shipments_constant_retired():
    """The hardcoded MOCK_SHIPMENTS array must be gone (no `const MOCK_SHIPMENTS = [`)."""
    code = _code_only(_src())
    assert "const MOCK_SHIPMENTS = [" not in code, "MOCK_SHIPMENTS array must be retired"
    assert "window.MOCK_SHIPMENTS" not in code, "MOCK_SHIPMENTS must not be exported"


def test_static_summary_cards_constant_retired():
    """The static SUMMARY_CARDS array (hardcoded values) must be gone — derived from live rows now."""
    code = _code_only(_src())
    assert "const SUMMARY_CARDS = [" not in code, "static SUMMARY_CARDS must be retired (derive from live data)"


def test_mock_awb_literals_retired():
    """Specific mock AWB/MRN literals from the old MOCK_SHIPMENTS must not survive."""
    code = _code_only(_src())
    for lit in ("DHL-1234567890", "DHL-9876543210", "FDX-0011223344",
                "PL12345678901234A", "SHP-001", "SHP-007"):
        assert lit not in code, f"mock literal must be retired: {lit}"


def test_no_pagination_controls():
    """Prev/Next pagination (no API pagination exists) must be removed."""
    code = _code_only(_src())
    assert "Prev" not in code, "Prev pagination control must be removed"
    assert "Next" not in code, "Next pagination control must be removed"


# ══════════════════════════════════════════════════════════════════════════════
# G. index.html — shipments route renders DashboardPage
# ══════════════════════════════════════════════════════════════════════════════

def test_index_html_shipments_route_renders_dashboard_page():
    block = _shipments_route_block(_INDEX_HTML.read_text(encoding="utf-8"))
    assert "DashboardPage" in block, (
        "index.html shipments route must render <DashboardPage />"
    )


def test_shipments_header_no_misleading_drill_promise():
    """The header must not promise an internal detail drill that no longer exists."""
    block = _shipments_route_block(_INDEX_HTML.read_text(encoding="utf-8")).lower()
    assert "click any awb to open detail" not in block, (
        "shipments header must not promise a detail drill (deferred this sprint)"
    )


def test_shipments_header_no_dead_export_button():
    """The dead '↓ Export CSV' button (no handler) must be removed from the header."""
    block = _shipments_route_block(_INDEX_HTML.read_text(encoding="utf-8"))
    assert "Export CSV" not in block, (
        "shipments header must not carry the unwired Export CSV button"
    )


def test_shipments_header_declares_read_only():
    block = _shipments_route_block(_INDEX_HTML.read_text(encoding="utf-8")).lower()
    assert "read-only" in block or "no write actions" in block, (
        "shipments header subtitle must declare the page is read-only"
    )


# ══════════════════════════════════════════════════════════════════════════════
# H. Required testids + read-only disclaimer
# ══════════════════════════════════════════════════════════════════════════════

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


def test_read_only_disclaimer_present():
    src = _src().lower()
    assert "observer only" in src or "read-only" in src, (
        "DashboardPage must declare a read-only / observer-only disclaimer"
    )


def test_reload_button_is_passive_label():
    """The Reload control must not carry a server-trigger label."""
    code = _code_only(_src()).lower()
    assert "shipments-hub-reload" in code, "Reload control testid must exist"
    # vicinity check: 200 chars before the reload testid must not mention a trigger verb
    pre = code.split("shipments-hub-reload")[0][-200:]
    for bad in ("reprocess", "recheck", "trigger", "regenerate", "resend"):
        assert bad not in pre, f"Reload control vicinity must not mention {bad!r}"


# ══════════════════════════════════════════════════════════════════════════════
# I. NAV_TREE — Shipments discoverability (P2)
# ══════════════════════════════════════════════════════════════════════════════

def test_shipments_in_nav_tree():
    src = _COMPONENTS.read_text(encoding="utf-8")
    nav_body = src[src.index("NAV_TREE = ["):src.index("];", src.index("NAV_TREE = ["))]
    assert "id: 'shipments'" in nav_body, (
        "components.jsx NAV_TREE must include id: 'shipments' (P2 reachability)"
    )


def test_existing_nav_entries_preserved():
    src = _COMPONENTS.read_text(encoding="utf-8")
    nav_body = src[src.index("NAV_TREE = ["):src.index("];", src.index("NAV_TREE = ["))]
    for page_id in ("dashboard", "inbox", "shipments", "proforma",
                    "documents", "accounting", "inventory", "reports", "dhl"):
        assert f"id: '{page_id}'" in nav_body, (
            f"top-level NAV_TREE entry '{page_id}' must remain"
        )
