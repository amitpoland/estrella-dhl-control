"""
test_sprint31_dhl_shell_wiring.py
==================================
Sprint 31 regression tests: DHL Hub wired into the V2 shell as a read-only
observer surface.

These are source-grep tests pinning the wiring contract:
  - 'dhl' added to WIRED_PAGES (no MOCK banner)
  - DhlCustomsPage uses window.EstrellaShared.apiFetch
  - Exactly the 4 allowed GET endpoints referenced; no deferred per-batch endpoints
  - No write HTTP methods in the DHL Hub region
  - No forbidden affordance strings (Send Now / Retry Parse / Scan / Lane / Force / etc.)
  - Mock components retired (P3): DhlClearancePipeline, DhlEmailInbox,
    EmailDetailModal, SadDocsTable
  - Inline mock arrays (`emails`, `sadDocs`) removed
  - Existing live cards composed: window.DhlScanStatus, window.DhlDailySummary
  - dhl-hub-root testid present
  - index.html dhl route has no write-implying actions / "Two-stage"-style stale subtitle

References:
  .claude/campaigns/atlas-v2/sprint-31-dhl-hub.md
  service/app/static/v2/pages-v2.jsx       (DhlCustomsPage region)
  service/app/static/v2/mock-badge.jsx     (WIRED_PAGES)
  service/app/static/v2/index.html         (dhl route block)
  service/app/static/v2/dhl-scan-status.jsx
  service/app/static/v2/dhl-daily-summary.jsx
"""
from __future__ import annotations

from pathlib import Path

_PAGES_V2   = Path(__file__).parent.parent / "app" / "static" / "v2" / "pages-v2.jsx"
_MOCK_BADGE = Path(__file__).parent.parent / "app" / "static" / "v2" / "mock-badge.jsx"
_INDEX_HTML = Path(__file__).parent.parent / "app" / "static" / "v2" / "index.html"
_COMPONENTS = Path(__file__).parent.parent / "app" / "static" / "v2" / "components.jsx"
_SCAN_CARD  = Path(__file__).parent.parent / "app" / "static" / "v2" / "dhl-scan-status.jsx"
_SUM_CARD   = Path(__file__).parent.parent / "app" / "static" / "v2" / "dhl-daily-summary.jsx"


def _dhl_hub_region(src: str) -> str:
    """The DhlCustomsPage block + its private primitives — between the DHL Hub banner and the next domain banner."""
    start = src.index("// DHL Hub")
    end = src.index("// Accounting")
    return src[start:end]


def _dhl_route_block(src: str) -> str:
    """The actual JSX dhl route block in index.html (not the comment/redirect mentions).

    The route block is uniquely anchored by `page === 'dhl' && (` which only
    appears inside the conditional JSX, never inside comments or the redirect map.
    """
    idx = src.index("page === 'dhl' && (")
    end = src.find("page === 'accounting'", idx)
    if end < 0:
        end = src.find("page === 'inventory'", idx)
    return src[idx:end] if end > idx else src[idx:idx + 1500]


# ══════════════════════════════════════════════════════════════════════════════
# A. mock-badge.jsx — 'dhl' in WIRED_PAGES
# ══════════════════════════════════════════════════════════════════════════════

def test_dhl_in_wired_pages():
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    assert "'dhl'" in src, "mock-badge.jsx WIRED_PAGES must include 'dhl'"


def test_wired_pages_array_contains_dhl():
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    idx = src.index("WIRED_PAGES")
    arr_start = src.index("[", idx)
    arr_end = src.index("]", arr_start)
    arr_body = src[arr_start:arr_end]
    assert "dhl" in arr_body, "'dhl' must be inside the WIRED_PAGES array literal"


def test_existing_wired_pages_preserved():
    """Regression: proforma / inbox / inventory remain wired.

    NOTE: 'proforma_detail' was intentionally removed from WIRED_PAGES in Sprint 36
    Phase 0 (2026-06-06) — authority violation containment. It will be re-added after
    Sprint 36 full authority recovery.
    """
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    idx = src.index("WIRED_PAGES")
    arr_body = src[src.index("[", idx):src.index("]", idx)]
    for page in ("proforma", "inbox", "inventory"):
        assert page in arr_body, f"{page!r} must remain in WIRED_PAGES"


# ══════════════════════════════════════════════════════════════════════════════
# B. DhlCustomsPage — live wiring, exports, testids
# ══════════════════════════════════════════════════════════════════════════════

def test_dhl_hub_uses_estrella_shared_api_fetch():
    block = _dhl_hub_region(_PAGES_V2.read_text(encoding="utf-8"))
    assert "window.EstrellaShared.apiFetch" in block or "EstrellaShared.apiFetch" in block, (
        "DhlCustomsPage must use window.EstrellaShared.apiFetch (auth-aware shim)"
    )


def test_dhl_hub_root_testid_present():
    block = _dhl_hub_region(_PAGES_V2.read_text(encoding="utf-8"))
    assert 'data-testid="dhl-hub-root"' in block, (
        "DhlCustomsPage must carry data-testid='dhl-hub-root'"
    )


def test_dhl_hub_composes_existing_live_cards():
    block = _dhl_hub_region(_PAGES_V2.read_text(encoding="utf-8"))
    assert "window.DhlScanStatus" in block, (
        "DhlCustomsPage must compose the existing window.DhlScanStatus card"
    )
    assert "window.DhlDailySummary" in block, (
        "DhlCustomsPage must compose the existing window.DhlDailySummary card"
    )


def test_index_html_loads_dhl_card_jsx_files():
    """The composed cards (window.DhlScanStatus / window.DhlDailySummary) must
    be loaded by index.html's script chain — otherwise they are undefined at
    runtime and the Hub falls back to the 'card unavailable' placeholder."""
    src = _INDEX_HTML.read_text(encoding="utf-8")
    assert 'src="dhl-scan-status.jsx"' in src, (
        "index.html must <script src='dhl-scan-status.jsx'> so window.DhlScanStatus is defined"
    )
    assert 'src="dhl-daily-summary.jsx"' in src, (
        "index.html must <script src='dhl-daily-summary.jsx'> so window.DhlDailySummary is defined"
    )


def test_referenced_live_cards_exist_on_disk():
    """Defence in depth: the cards we compose must actually exist."""
    assert _SCAN_CARD.exists(), f"missing live card: {_SCAN_CARD}"
    assert _SUM_CARD.exists(),  f"missing live card: {_SUM_CARD}"
    assert "window.DhlScanStatus"    in _SCAN_CARD.read_text(encoding="utf-8")
    assert "window.DhlDailySummary"  in _SUM_CARD.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# C. Endpoint contract — exactly the 4 allowed; no deferred / no forbidden
# ══════════════════════════════════════════════════════════════════════════════

# Sprint 31 ALLOWED authority endpoints — the actual registered router paths.
# The brief originally listed `/api/v1/dhl/status` and `/api/v1/dhl/shipments`
# but the verified router prefix is `/api/v1/dhl/followup-automation` (see
# routes_dhl_followup_status.py:31). Authority owner unchanged
# (dhl_followup_status_projector); only the URL path was corrected.
ALLOWED_DHL_ENDPOINTS = {
    "/api/v1/dhl/followup-automation/status",
    "/api/v1/dhl/followup-automation/shipments",
    "/api/v1/dhl/auto-scan-status",
    "/api/v1/dhl/daily-summary",
}

DEFERRED_DHL_ENDPOINTS = [
    "/dhl/clearance-status/",
    "/dhl/reply-status/",
    "/dhl/sad-ready/",
    "/dhl/readiness/",
    "/dhl/{batch_id}/mode",
    "/dhl/{batch_id}/auto/preview",
]

FORBIDDEN_BACKEND_TRIGGERS = [
    "/dhl/scheduled-inbox-check",
    "/dhl/scheduled-followup-check",
    "/dhl/scan-inbox",
]


def test_all_allowed_endpoints_referenced_in_dhl_hub():
    block = _dhl_hub_region(_PAGES_V2.read_text(encoding="utf-8"))
    for ep in ALLOWED_DHL_ENDPOINTS:
        assert ep in block, f"DhlCustomsPage must reference allowed endpoint: {ep}"


def test_no_deferred_per_batch_endpoints():
    block = _dhl_hub_region(_PAGES_V2.read_text(encoding="utf-8"))
    present = [ep for ep in DEFERRED_DHL_ENDPOINTS if ep in block]
    assert not present, (
        f"DhlCustomsPage must NOT reference deferred per-batch endpoints: {present}"
    )


def test_no_forbidden_backend_triggers():
    block = _dhl_hub_region(_PAGES_V2.read_text(encoding="utf-8"))
    present = [ep for ep in FORBIDDEN_BACKEND_TRIGGERS if ep in block]
    assert not present, (
        f"DhlCustomsPage must NOT reference scan/followup trigger endpoints: {present}"
    )


def test_no_unknown_dhl_endpoints_in_hub():
    """Any /api/v1/dhl/* string that appears must be in ALLOWED_DHL_ENDPOINTS."""
    import re
    block = _dhl_hub_region(_PAGES_V2.read_text(encoding="utf-8"))
    refs = set(re.findall(r"/api/v1/dhl/[a-zA-Z0-9_\-/{}]+", block))
    unknown = refs - ALLOWED_DHL_ENDPOINTS
    assert not unknown, (
        f"DhlCustomsPage references DHL endpoints outside the 4 allowed: {sorted(unknown)}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# D. NO write HTTP methods in the DHL Hub region
# ══════════════════════════════════════════════════════════════════════════════

FORBIDDEN_WRITE_METHOD_TOKENS = [
    "method: 'POST'",   "method: \"POST\"",   "method:'POST'",
    "method: 'PUT'",    "method: \"PUT\"",    "method:'PUT'",
    "method: 'PATCH'",  "method: \"PATCH\"",  "method:'PATCH'",
    "method: 'DELETE'", "method: \"DELETE\"", "method:'DELETE'",
]


def test_no_write_http_methods_in_dhl_hub():
    block = _dhl_hub_region(_PAGES_V2.read_text(encoding="utf-8"))
    present = [tok for tok in FORBIDDEN_WRITE_METHOD_TOKENS if tok in block]
    assert not present, (
        f"DhlCustomsPage region must contain NO write HTTP methods: {present}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# E. NO forbidden affordance strings — visibility-only invariant (brief §4)
# ══════════════════════════════════════════════════════════════════════════════

# Lowercase, substring-matched against block.lower(). Covers button labels,
# event names, and old mock-renderer markers.
FORBIDDEN_AFFORDANCES_LOWER = [
    "send now",
    "retry parse",
    "retry send",
    "send dsk",
    "send reply",
    "requeue",
    "retry failed",
    "trigger scan",
    "scan now",
    "scan dhl inbox",
    "run lane",
    "run inbox",
    "force status",
    "force update",
    "mark received",
    "re-probe",
    "refresh status",
    "refresh-status",
]


def test_no_forbidden_affordance_strings_in_dhl_hub():
    block = _dhl_hub_region(_PAGES_V2.read_text(encoding="utf-8")).lower()
    present = [s for s in FORBIDDEN_AFFORDANCES_LOWER if s in block]
    assert not present, (
        f"DhlCustomsPage region must contain none of these affordance strings: {present}"
    )


def test_no_forbidden_affordances_in_index_html_dhl_route():
    """The shell's dhl route header must not expose write-implying actions either."""
    block = _dhl_route_block(_INDEX_HTML.read_text(encoding="utf-8")).lower()
    present = [s for s in FORBIDDEN_AFFORDANCES_LOWER if s in block]
    assert not present, (
        f"index.html dhl route must contain none of these affordance strings: {present}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# F. P3 — mock helpers and inline mock arrays retired
# ══════════════════════════════════════════════════════════════════════════════

RETIRED_MOCK_HELPERS = [
    "function DhlClearancePipeline",
    "function DhlEmailInbox",
    "function EmailDetailModal",
    "function SadDocsTable",
]

RETIRED_MOCK_LITERALS_IN_HUB = [
    "DHL-7733991122",
    "DHL-9988776655",
    "DHL-8825441199",
    "DHL-2244668800",
    "DHL-5566778899",
    "ZC429/2024/000847",
    "ZC429/2024/000845",
    "ZC429/2024/000844",
    "AI Bridge result",   # mock email-detail panel header
    "Inbox new",          # mock stat tile
    "SAD pending",        # mock stat tile
    "Cleared today",      # mock stat tile
]


def test_mock_renderer_functions_retired():
    """Sprint 31 P3: the 4 mock components owned by DhlCustomsPage are gone."""
    src = _PAGES_V2.read_text(encoding="utf-8")
    present = [h for h in RETIRED_MOCK_HELPERS if h in src]
    assert not present, (
        f"P3 (Mock Retired) violated — these mock renderers must be deleted: {present}"
    )


def test_inline_mock_arrays_retired_in_dhl_hub():
    """The hardcoded mock email + SAD arrays must not exist inside the DHL Hub region."""
    block = _dhl_hub_region(_PAGES_V2.read_text(encoding="utf-8"))
    present = [lit for lit in RETIRED_MOCK_LITERALS_IN_HUB if lit in block]
    assert not present, (
        f"DhlCustomsPage region must contain no mock literals: {present}"
    )


def test_dhl_hub_region_does_not_construct_mock_email_arrays():
    """No `const emails = [` / `const sadDocs = [` style mock arrays inside DhlCustomsPage."""
    block = _dhl_hub_region(_PAGES_V2.read_text(encoding="utf-8"))
    assert "const emails = [" not in block, "Mock emails array must be retired"
    assert "const sadDocs = [" not in block, "Mock sadDocs array must be retired"


# ══════════════════════════════════════════════════════════════════════════════
# G. index.html — dhl route renders DhlCustomsPage and shows read-only descriptor
# ══════════════════════════════════════════════════════════════════════════════

def test_index_html_dhl_route_renders_dhl_customs_page():
    block = _dhl_route_block(_INDEX_HTML.read_text(encoding="utf-8"))
    assert "DhlCustomsPage" in block, (
        "index.html dhl route must render <DhlCustomsPage />"
    )


def test_index_html_dhl_route_declares_read_only_subtitle():
    block = _dhl_route_block(_INDEX_HTML.read_text(encoding="utf-8"))
    assert "Read-only" in block or "read-only" in block or "No write actions" in block, (
        "index.html dhl route subtitle must declare the page is read-only"
    )


def test_index_html_route_redirects_does_not_alias_dhl():
    """Sprint 31: the legacy `dhl: 'shipments'` redirect must be removed,
    or every visit to /v2/dhl silently lands on Shipments and the DHL Hub
    is unreachable — P2 fails vacuously."""
    src = _INDEX_HTML.read_text(encoding="utf-8")
    redir_start = src.index("ROUTE_REDIRECTS = {")
    redir_end   = src.index("};", redir_start)
    redir_body  = src[redir_start:redir_end]
    # Match a `dhl:` key assignment (with optional whitespace) — but not in a
    # comment line.
    import re
    for line in redir_body.split("\n"):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("/*"):
            continue
        assert not re.match(r"^dhl\s*:", stripped), (
            f"ROUTE_REDIRECTS must not redirect 'dhl' anywhere — found: {stripped!r}"
        )


def test_index_html_dhl_route_has_no_actions_props_with_write_verbs():
    """If actions={...} exists on the dhl PageHeader, it must not contain write-verb labels."""
    block = _dhl_route_block(_INDEX_HTML.read_text(encoding="utf-8")).lower()
    # If the actions prop is absent, nothing to check
    if "actions=" not in block:
        return
    for forbidden in ("scan now", "retry", "send", "requeue", "trigger", "force"):
        assert forbidden not in block, (
            f"index.html dhl route actions must not contain {forbidden!r}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# H. Defence in depth — required panel testids and Reload control
# ══════════════════════════════════════════════════════════════════════════════

# Element-level testids: rendered directly as data-testid="..."
ELEMENT_TESTIDS = [
    "dhl-hub-root",
    "dhl-hub-reload",
    "dhl-hub-scan-card",
    "dhl-hub-summary-card",
]
# Panel testids: passed as the `testid` prop to <DhlPanel testid="..." />,
# which renders data-testid={testid}. Same idiom as Sprint 30 InvPanel.
PANEL_TESTIDS = [
    "dhl-hub-status-panel",
    "dhl-hub-shipments-panel",
]


def test_required_dhl_hub_testids_present():
    block = _dhl_hub_region(_PAGES_V2.read_text(encoding="utf-8"))
    missing_elements = [t for t in ELEMENT_TESTIDS if f'data-testid="{t}"' not in block]
    missing_panels   = [t for t in PANEL_TESTIDS   if f'testid="{t}"'      not in block]
    missing = missing_elements + missing_panels
    assert not missing, f"DhlCustomsPage missing testids: {missing}"


# ══════════════════════════════════════════════════════════════════════════════
# I. NAV_TREE — DHL Hub discoverability (P2: operator can observe truth)
# ══════════════════════════════════════════════════════════════════════════════

def test_dhl_in_nav_tree():
    """Sprint 31 P2: an operator must be able to reach the DHL Hub from the
    V2 shell sidebar. Without a NAV_TREE entry, P2 is vacuously false."""
    src = _COMPONENTS.read_text(encoding="utf-8")
    nav_start = src.index("NAV_TREE = [")
    nav_end   = src.index("];", nav_start)
    nav_body  = src[nav_start:nav_end]
    assert "id: 'dhl'" in nav_body, (
        "components.jsx NAV_TREE must include an entry with id: 'dhl' so "
        "the DHL Hub is reachable from the V2 sidebar"
    )


def test_existing_nav_entries_preserved():
    """Regression: the other 8 top-level nav entries remain intact."""
    src = _COMPONENTS.read_text(encoding="utf-8")
    nav_start = src.index("NAV_TREE = [")
    nav_end   = src.index("];", nav_start)
    nav_body  = src[nav_start:nav_end]
    for page_id in ("dashboard", "inbox", "shipments", "proforma",
                    "documents", "accounting", "inventory", "reports"):
        assert f"id: '{page_id}'" in nav_body, (
            f"top-level NAV_TREE entry '{page_id}' must remain"
        )


def test_reload_button_is_passive_label():
    """The single Reload button must not carry a server-trigger label."""
    block = _dhl_hub_region(_PAGES_V2.read_text(encoding="utf-8")).lower()
    # Ensure the reload control exists by its testid
    assert 'dhl-hub-reload' in block, "Reload control testid must exist"
    # And that any label string near it is benign
    for bad in ("scan", "trigger", "force", "lane a", "lane b", "send", "retry"):
        # only fail if the bad word appears AS A BUTTON LABEL near the reload testid;
        # we already enforce no forbidden affordance strings anywhere in the region.
        # This test is redundant but cheap insurance.
        assert bad not in block.split("dhl-hub-reload")[0][-200:], (
            f"Reload control vicinity must not mention {bad!r}"
        )
