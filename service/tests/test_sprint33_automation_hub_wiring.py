"""
test_sprint33_automation_hub_wiring.py
=======================================
Sprint 33 regression tests: Automation Hub wired into the V2 shell as a
read-only observer surface (AiBridgePage, route `page === 'automation'`).

Source-grep tests pinning the wiring contract:
  - 'automation' added to WIRED_PAGES (no MOCK banner); all 6 prior wired pages intact
  - AiBridgePage uses window.EstrellaShared.apiFetch
  - Exactly the 3 allowed ai-bridge endpoints; no write endpoints
  - No write HTTP methods in pages-v2.jsx AiBridgePage region
  - No forbidden affordance strings (Retry / Edit / Save & Activate / Test /
    Diff vs v2) in the live implementation
  - Mock data retired (tasks[] array, capabilities[] array, mock task IDs T-88xx)
  - automation-hub-root + required testids present; read-only disclaimer present
  - index.html automation route still renders <AiBridgePage />
  - NAV_TREE 'automation' entry preserved (P2 reachability)

References:
  .claude/campaigns/atlas-v2/sprint-33-automation-endpoints.md
  service/app/static/v2/pages-v2.jsx     (AiBridgePage + helper components)
  service/app/static/v2/mock-badge.jsx   (WIRED_PAGES)
  service/app/static/v2/index.html       (automation route block)
  service/app/static/v2/components.jsx   (NAV_TREE)
"""
from __future__ import annotations

import re
from pathlib import Path

_V2         = Path(__file__).parent.parent / "app" / "static" / "v2"
_PAGES_V2   = _V2 / "pages-v2.jsx"
_MOCK_BADGE = _V2 / "mock-badge.jsx"
_INDEX_HTML = _V2 / "index.html"
_COMPONENTS = _V2 / "components.jsx"


def _src() -> str:
    return _PAGES_V2.read_text(encoding="utf-8")


def _code_only(src: str) -> str:
    """Strip `//` single-line comments so prose in the header/disclaimer comments
    never trips a forbidden-token scan. Block comments are not used here."""
    out = []
    for line in src.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("//"):
            continue
        if "//" in line and "http" not in line:
            line = line[: line.index("//")]
        out.append(line)
    return "\n".join(out)


def _automation_route_block(src: str) -> str:
    """The JSX automation route block in index.html, anchored by
    `page === 'automation' && (`."""
    idx = src.index("page === 'automation' && (")
    end = src.find("page === '", idx + 30)
    return src[idx:end] if end > idx else src[idx:idx + 1500]


# ══════════════════════════════════════════════════════════════════════════════
# A. mock-badge.jsx — 'automation' in WIRED_PAGES
# ══════════════════════════════════════════════════════════════════════════════

def test_automation_in_wired_pages():
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    assert "'automation'" in src, "mock-badge.jsx WIRED_PAGES must include 'automation'"


def test_wired_pages_array_contains_automation():
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    idx = src.index("WIRED_PAGES")
    arr_body = src[src.index("[", idx):src.index("]", idx)]
    assert "automation" in arr_body, "'automation' must be inside the WIRED_PAGES array literal"


def test_existing_wired_pages_preserved():
    """Regression: all 6 previously-wired domains remain wired."""
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    idx = src.index("WIRED_PAGES")
    arr_body = src[src.index("[", idx):src.index("]", idx)]
    # proforma_detail intentionally removed Sprint 36 Phase 0 (2026-06-06) — authority violation
    for page in ("proforma", "inbox", "inventory", "dhl", "shipments"):
        assert page in arr_body, f"{page!r} must remain in WIRED_PAGES"


# ══════════════════════════════════════════════════════════════════════════════
# B. AiBridgePage — live wiring, testids, export
# ══════════════════════════════════════════════════════════════════════════════

def test_automation_page_uses_estrella_shared_api_fetch():
    src = _src()
    assert "window.EstrellaShared.apiFetch" in src or "EstrellaShared.apiFetch" in src, (
        "AiBridgePage must use window.EstrellaShared.apiFetch (auth-aware shim)"
    )


def test_automation_hub_root_testid_present():
    assert 'data-testid="automation-hub-root"' in _src(), (
        "AiBridgePage must carry data-testid='automation-hub-root'"
    )


def test_ai_bridge_page_exported_on_window():
    src = _src()
    assert "AiBridgePage" in src, "AiBridgePage must exist in pages-v2.jsx"
    assert "Object.assign(window" in src and "AiBridgePage" in src, (
        "AiBridgePage must be exported on window for the shell to render it"
    )


# ══════════════════════════════════════════════════════════════════════════════
# C. Endpoint contract — exactly the 3 allowed ai-bridge endpoints; no writes
# ══════════════════════════════════════════════════════════════════════════════

ALLOWED_ENDPOINTS = [
    "/api/v1/ai-bridge/tasks",
    "/api/v1/ai-bridge/errors",
    "/api/v1/ai-bridge/templates",
]

FORBIDDEN_WRITE_ENDPOINTS = [
    "/ai-bridge/tasks/{",
    "/ai-bridge/results/{",
    "ai-bridge/tasks/{batch_id}",
    "ai-bridge/results/{task_id}",
]


def test_all_allowed_endpoints_referenced():
    src = _src()
    for ep in ALLOWED_ENDPOINTS:
        assert ep in src, f"AiBridgePage must reference the allowed endpoint: {ep}"


def test_no_forbidden_write_endpoints():
    code = _code_only(_src())
    present = [ep for ep in FORBIDDEN_WRITE_ENDPOINTS if ep in code]
    assert not present, (
        f"pages-v2.jsx must NOT reference forbidden write ai-bridge endpoints: {present}"
    )


def test_no_unknown_ai_bridge_endpoints():
    """Any /api/v1/ai-bridge/* string in code must be on the allowed list."""
    code = _code_only(_src())
    refs = set(re.findall(r"/api/v1/ai-bridge/[a-zA-Z0-9_\-/{}?=&]+", code))
    # strip query params for comparison
    base_refs = {r.split("?")[0] for r in refs}
    unknown = base_refs - set(ALLOWED_ENDPOINTS)
    assert not unknown, (
        f"pages-v2.jsx references ai-bridge endpoints outside the allowed list: {sorted(unknown)}"
    )


def test_no_ai_advisory_endpoints():
    """Must not accidentally call /api/v1/ai/* (routes_ai_advisory, NOT ai-bridge)."""
    code = _code_only(_src())
    # /api/v1/ai/ paths that are NOT /api/v1/ai-bridge/
    refs = re.findall(r"/api/v1/ai/[a-zA-Z0-9_\-/]+", code)
    assert not refs, (
        f"AiBridgePage must NOT reference /api/v1/ai/* advisory endpoints: {refs}"
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
        f"pages-v2.jsx must contain NO write HTTP methods in AiBridgePage region: {present}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# E. NO forbidden affordance controls — visibility-only invariant
# ══════════════════════════════════════════════════════════════════════════════

# These were the write-action buttons in the old mock AiBridgePage.
# Checked against comment-stripped code.
FORBIDDEN_AFFORDANCES_LOWER = [
    "save & activate",
    "diff vs v2",
]


def test_no_forbidden_affordance_controls():
    code = _code_only(_src()).lower()
    present = [s for s in FORBIDDEN_AFFORDANCES_LOWER if s in code]
    assert not present, (
        f"AiBridgePage must contain none of these affordance strings: {present}"
    )


def test_no_retry_button_for_error_rows():
    """The mock error-row `{t.status === 'error' && <Btn...>Retry</Btn>}` pattern
    must be gone. The uniquely identifying condition was the inline JSX expression
    `t.status === 'error' && <Btn` inside AiBridgePage's task table rows.
    Note: a Retry button in EmailQueuePage (q.status) is unrelated and allowed."""
    code = _code_only(_src())
    # This exact expression only existed in the mock AiBridgePage task loop.
    assert "t.status === 'error' && <Btn" not in code, (
        "Error-conditional Retry affordance pattern must be removed from AiBridgePage"
    )


def test_no_edit_button_for_capabilities():
    """The mock capabilities-tab `<Btn small variant='outline'>Edit</Btn>` must be gone.
    The removal is confirmed transitively: the capabilities array is gone
    (test_mock_capabilities_array_retired) and the capabilities tab is gone
    (test_no_capabilities_tab). This test pins the specific Btn pattern."""
    code = _code_only(_src())
    # The old capabilities-map Edit button was always next to a capabilities.map call
    assert "capabilities.map" not in code, (
        "capabilities.map iterator must be removed (capabilities tab retired)"
    )


def test_no_capabilities_tab():
    """The Capabilities tab (no live endpoint) must be removed."""
    code = _code_only(_src())
    # The tab id must not appear in the tabs array
    assert "id: 'capabilities'" not in code, "Capabilities tab must be removed (no live endpoint)"
    assert 'id: "capabilities"' not in code, "Capabilities tab must be removed (no live endpoint)"


# ══════════════════════════════════════════════════════════════════════════════
# F. Mock data retired
# ══════════════════════════════════════════════════════════════════════════════

def test_mock_tasks_array_retired():
    """The hardcoded `const tasks = [` array with mock task objects must be gone."""
    code = _code_only(_src())
    assert "const tasks = [" not in code, "hardcoded tasks array must be retired"


def test_mock_capabilities_array_retired():
    """The hardcoded `const capabilities = [` array must be gone."""
    code = _code_only(_src())
    assert "const capabilities = [" not in code, "hardcoded capabilities array must be retired"


def test_mock_task_ids_retired():
    """Specific mock task IDs from the old array must not survive."""
    src = _code_only(_src())
    for mock_id in ("T-8835", "T-8836", "T-8837", "T-8838", "T-8839", "T-8840", "T-8841", "T-8842"):
        assert mock_id not in src, f"mock task ID must be retired: {mock_id}"


def test_static_stat_tiles_retired():
    """Hardcoded stat tile values like '284' (tasks today) and '$4.82' must be gone."""
    code = _code_only(_src())
    assert '"284"' not in code, 'hardcoded "284 tasks today" stat must be retired'
    assert "'284'" not in code, "hardcoded tasks-today stat must be retired"
    assert '"$4.82"' not in code, "hardcoded token spend stat must be retired"
    assert "'$4.82'" not in code, "hardcoded token spend stat must be retired"


# ══════════════════════════════════════════════════════════════════════════════
# G. index.html — automation route renders AiBridgePage
# ══════════════════════════════════════════════════════════════════════════════

def test_index_html_automation_route_renders_ai_bridge_page():
    block = _automation_route_block(_INDEX_HTML.read_text(encoding="utf-8"))
    assert "AiBridgePage" in block, (
        "index.html automation route must render <AiBridgePage />"
    )


def test_automation_route_block_present():
    src = _INDEX_HTML.read_text(encoding="utf-8")
    assert "page === 'automation' && (" in src, (
        "index.html must have the automation page conditional (P1 route)"
    )


# ══════════════════════════════════════════════════════════════════════════════
# H. Required testids + read-only disclaimer
# ══════════════════════════════════════════════════════════════════════════════

ELEMENT_TESTIDS = [
    "automation-hub-root",
    "automation-hub-reload",
    "automation-hub-summary",
    "automation-hub-tasks-table",
    "automation-hub-results-table",
    "automation-hub-errors-table",
    "automation-hub-templates",
]


def test_required_testids_present():
    src = _src()
    # Accept either the literal `data-testid="..."` attribute (root/button/div elements)
    # or the `testid="..."` prop pass-through form (helper components apply it internally).
    missing = [
        t for t in ELEMENT_TESTIDS
        if f'data-testid="{t}"' not in src and f'testid="{t}"' not in src
    ]
    assert not missing, f"AiBridgePage missing testids: {missing}"


def test_read_only_disclaimer_present():
    src = _src().lower()
    assert "observer only" in src or "read-only" in src, (
        "AiBridgePage must declare a read-only / observer-only disclaimer"
    )


def test_reload_button_is_passive():
    """The Reload control must not carry a server-side trigger label."""
    code = _code_only(_src()).lower()
    assert "automation-hub-reload" in code, "Reload control testid must exist"
    pre = code.split("automation-hub-reload")[0][-200:]
    for bad in ("reprocess", "recheck", "trigger", "regenerate", "resend", "execute"):
        assert bad not in pre, f"Reload control vicinity must not mention {bad!r}"


# ══════════════════════════════════════════════════════════════════════════════
# I. NAV_TREE — Automation discoverability (P2)
# ══════════════════════════════════════════════════════════════════════════════

def test_automation_in_nav_tree():
    src = _COMPONENTS.read_text(encoding="utf-8")
    nav_body = src[src.index("NAV_TREE = ["):src.index("];", src.index("NAV_TREE = ["))]
    assert "id: 'automation'" in nav_body, (
        "components.jsx NAV_TREE must include id: 'automation' (P2 reachability)"
    )


def test_existing_nav_entries_preserved():
    src = _COMPONENTS.read_text(encoding="utf-8")
    nav_body = src[src.index("NAV_TREE = ["):src.index("];", src.index("NAV_TREE = ["))]
    for page_id in ("dashboard", "inbox", "shipments", "proforma",
                    "documents", "accounting", "inventory", "reports", "dhl", "automation"):
        assert f"id: '{page_id}'" in nav_body, (
            f"top-level NAV_TREE entry '{page_id}' must remain"
        )


# ══════════════════════════════════════════════════════════════════════════════
# J. No dead Automation header buttons (Sprint 33 hardening — post-audit fix)
# ══════════════════════════════════════════════════════════════════════════════

def test_no_system_status_button_in_automation_header():
    """'System Status' dead button must be absent from the Automation route block."""
    block = _automation_route_block(_INDEX_HTML.read_text(encoding="utf-8"))
    assert "System Status" not in block, (
        "Automation route header must not contain dead 'System Status' button"
    )


def test_no_export_logs_button_in_automation_header():
    """'Export Logs' dead button must be absent from the Automation route block."""
    block = _automation_route_block(_INDEX_HTML.read_text(encoding="utf-8"))
    assert "Export Logs" not in block, (
        "Automation route header must not contain dead '↓ Export Logs' button"
    )


def test_automation_page_header_has_no_actions_prop():
    """Automation PageHeader must not carry an 'actions=' prop (no dead action buttons)."""
    block = _automation_route_block(_INDEX_HTML.read_text(encoding="utf-8"))
    # Split on <AiBridgePage to get only the header region
    header_region = block.split("<AiBridgePage")[0]
    assert "actions=" not in header_region, (
        "Automation PageHeader must not have an 'actions=' prop — dead buttons removed"
    )


def test_automation_route_still_renders_ai_bridge_page_after_hardening():
    """Regression: removing header buttons must not break <AiBridgePage /> render."""
    block = _automation_route_block(_INDEX_HTML.read_text(encoding="utf-8"))
    assert "<AiBridgePage />" in block or "AiBridgePage" in block, (
        "Automation route must still render <AiBridgePage /> after header hardening"
    )
