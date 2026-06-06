"""
test_sprint34_intelligence_hub_wiring.py
==========================================
Sprint 34 regression tests: Intelligence Hub wired into the V2 shell as a
read-only observer surface (IntelligencePage, route `page === 'intelligence'`).

Source-grep tests pinning the wiring contract:
  - 'intelligence' added to WIRED_PAGES (no MOCK banner); all 7 prior wired pages intact
  - IntelligencePage uses window.EstrellaShared.apiFetch
  - Exactly the 4 allowed endpoints; no write endpoints
  - No write HTTP methods in pages-v2.jsx IntelligencePage region
  - No forbidden affordance strings (mock parser, random MRN, file upload alerts)
  - Mock/static data retired (setTimeout fake parser, Math.random MRN, hardcoded rates)
  - intelligence-hub-root + required testids present; read-only disclaimer present
  - index.html intelligence route renders <IntelligencePage /> not <LearningParserPage />
  - NAV_TREE 'intelligence' entry preserved (P2 reachability)
  - No backend files changed

References:
  service/app/static/v2/pages-v2.jsx     (IntelligencePage + helper components)
  service/app/static/v2/mock-badge.jsx   (WIRED_PAGES)
  service/app/static/v2/index.html       (intelligence route block)
  service/app/static/v2/components.jsx   (NAV_TREE)
  service/app/api/routes_intelligence.py (allowed GET endpoints)
  service/app/api/routes_learning.py     (allowed GET endpoint)
"""
from __future__ import annotations

import re
from pathlib import Path

_V2         = Path(__file__).parent.parent / "app" / "static" / "v2"
_PAGES_V2   = _V2 / "pages-v2.jsx"
_MOCK_BADGE = _V2 / "mock-badge.jsx"
_INDEX_HTML = _V2 / "index.html"
_COMPONENTS = _V2 / "components.jsx"

_BACKEND    = Path(__file__).parent.parent / "app" / "api"


def _src() -> str:
    return _PAGES_V2.read_text(encoding="utf-8")


def _code_only(src: str) -> str:
    """Strip `//` single-line comments so prose in header/disclaimer comments
    never trips a forbidden-token scan."""
    out = []
    for line in src.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("//"):
            continue
        if "//" in line and "http" not in line:
            line = line[: line.index("//")]
        out.append(line)
    return "\n".join(out)


def _intelligence_route_block(src: str) -> str:
    """The JSX intelligence route block in index.html, anchored by
    `page === 'intelligence' && (`."""
    idx = src.index("page === 'intelligence' && (")
    end = src.find("page === '", idx + 30)
    return src[idx:end] if end > idx else src[idx:idx + 1500]


# ══════════════════════════════════════════════════════════════════════════════
# A. mock-badge.jsx — 'intelligence' in WIRED_PAGES
# ══════════════════════════════════════════════════════════════════════════════

def test_intelligence_in_wired_pages():
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    assert "'intelligence'" in src, "mock-badge.jsx WIRED_PAGES must include 'intelligence'"


def test_wired_pages_array_contains_intelligence():
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    idx = src.index("WIRED_PAGES")
    arr_body = src[src.index("[", idx):src.index("]", idx)]
    assert "intelligence" in arr_body, "'intelligence' must be inside the WIRED_PAGES array literal"


def test_existing_wired_pages_preserved():
    """Regression: all 7 previously-wired domains remain wired."""
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    idx = src.index("WIRED_PAGES")
    arr_body = src[src.index("[", idx):src.index("]", idx)]
    # proforma_detail intentionally removed Sprint 36 Phase 0 (2026-06-06) — authority violation
    for page in ("proforma", "inbox", "inventory", "dhl", "shipments", "automation"):
        assert page in arr_body, f"{page!r} must remain in WIRED_PAGES"


# ══════════════════════════════════════════════════════════════════════════════
# B. IntelligencePage — live wiring, testids, export
# ══════════════════════════════════════════════════════════════════════════════

def test_intelligence_page_uses_estrella_shared_api_fetch():
    src = _src()
    assert "window.EstrellaShared.apiFetch" in src or "EstrellaShared.apiFetch" in src, (
        "IntelligencePage must use window.EstrellaShared.apiFetch (auth-aware shim)"
    )


def test_intelligence_hub_root_testid_present():
    assert 'data-testid="intelligence-hub-root"' in _src(), (
        "IntelligencePage must carry data-testid='intelligence-hub-root'"
    )


def test_intelligence_page_exported_on_window():
    src = _src()
    assert "IntelligencePage" in src, "IntelligencePage must exist in pages-v2.jsx"
    assert "Object.assign(window" in src and "IntelligencePage" in src, (
        "IntelligencePage must be exported on window for the shell to render it"
    )


# ══════════════════════════════════════════════════════════════════════════════
# C. Endpoint contract — exactly the 4 allowed endpoints; no writes
# ══════════════════════════════════════════════════════════════════════════════

ALLOWED_ENDPOINTS = [
    "/api/v1/intelligence/status",
    "/api/v1/intelligence/suggestions",
    "/api/v1/intelligence/config",
    "/api/v1/invoice-learning/summary",
]

FORBIDDEN_WRITE_ENDPOINTS = [
    "/api/v1/intelligence/refresh",
    "/api/v1/intelligence/build",
    "/api/v1/intelligence/classify",
    "/api/v1/invoice-learning/feedback",
]


def test_all_allowed_endpoints_referenced():
    src = _src()
    for ep in ALLOWED_ENDPOINTS:
        assert ep in src, f"IntelligencePage must reference the allowed endpoint: {ep}"


def test_no_forbidden_write_endpoints():
    code = _code_only(_src())
    present = [ep for ep in FORBIDDEN_WRITE_ENDPOINTS if ep in code]
    assert not present, (
        f"pages-v2.jsx must NOT reference forbidden write intelligence endpoints: {present}"
    )


def test_no_unknown_intelligence_endpoints():
    """Any /api/v1/intelligence/* string in code must be on the allowed list."""
    code = _code_only(_src())
    refs = set(re.findall(r"/api/v1/intelligence/[a-zA-Z0-9_\-/{}?=&]+", code))
    base_refs = {r.split("?")[0] for r in refs}
    unknown = base_refs - set(ALLOWED_ENDPOINTS)
    assert not unknown, (
        f"pages-v2.jsx references intelligence endpoints outside the allowed list: {sorted(unknown)}"
    )


def test_no_unknown_invoice_learning_endpoints():
    """Any /api/v1/invoice-learning/* string in code must be on the allowed list."""
    code = _code_only(_src())
    refs = set(re.findall(r"/api/v1/invoice-learning/[a-zA-Z0-9_\-/{}?=&]+", code))
    base_refs = {r.split("?")[0] for r in refs}
    unknown = base_refs - set(ALLOWED_ENDPOINTS)
    assert not unknown, (
        f"pages-v2.jsx references invoice-learning endpoints outside the allowed list: {sorted(unknown)}"
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
        f"pages-v2.jsx must contain NO write HTTP methods: {present}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# E. NO forbidden affordance controls — visibility-only invariant
# ══════════════════════════════════════════════════════════════════════════════

def test_no_run_parser_button():
    """The mock '▶ Run Parser' button from LearningParserPage must be gone."""
    code = _code_only(_src())
    assert "Run Parser" not in code, (
        "IntelligencePage must not contain 'Run Parser' mock button"
    )


def test_no_file_upload_input_in_intelligence():
    """The mock invoice PDF upload <input type='file'> must be gone."""
    code = _code_only(_src())
    # Check for the specific file-upload pattern that was in LearningParserPage.
    # A general type="file" elsewhere is acceptable; we check within IntelligencePage context.
    # The old pattern was: accept=".pdf" ... onChange={() => alert(
    assert "onChange={() => alert(" not in code, (
        "IntelligencePage must not contain fake file-upload alert() pattern"
    )


def test_no_parser_textarea_mock():
    """The mock SAD parser textarea pattern must be gone from IntelligencePage."""
    code = _code_only(_src()).lower()
    assert "paste sad" not in code, (
        "IntelligencePage must not contain 'Paste SAD' mock textarea prompt"
    )


# ══════════════════════════════════════════════════════════════════════════════
# F. Mock/static parser data retired
# ══════════════════════════════════════════════════════════════════════════════

def test_mock_parser_settimeout_retired():
    """The fake parser setTimeout(...) simulation must be gone from IntelligencePage."""
    code = _code_only(_src())
    # The old LearningParserPage used setTimeout to fake a parser result.
    # Check that the specific fake-result object is not present.
    assert "clearanceDate: '27 Apr 2024'" not in code, (
        "Hardcoded fake clearanceDate from mock parser must be retired"
    )


def test_mock_random_mrn_retired():
    """The fake random MRN generator (Math.random + padStart) must be gone."""
    code = _code_only(_src())
    # The mock used: 'PL' + Math.floor(Math.random() * 99999999999999)
    assert "99999999999999" not in code, (
        "Mock random MRN generator must be retired from IntelligencePage"
    )


def test_mock_hardcoded_exchange_rate_retired():
    """Hardcoded fake exchange rate '4.2650' from mock parser must be gone."""
    code = _code_only(_src())
    assert "'4.2650'" not in code and '"4.2650"' not in code, (
        "Hardcoded fake exchange rate from mock parser must be retired"
    )


def test_mock_parser_agent_retired():
    """Hardcoded 'Agencja Celna Sp. z o.o.' from mock parser must be gone."""
    code = _code_only(_src())
    assert "Agencja Celna Sp. z o.o." not in code, (
        "Hardcoded mock clearance agent string must be retired from IntelligencePage"
    )


# ══════════════════════════════════════════════════════════════════════════════
# G. index.html — intelligence route renders IntelligencePage
# ══════════════════════════════════════════════════════════════════════════════

def test_index_html_intelligence_route_renders_intelligence_page():
    block = _intelligence_route_block(_INDEX_HTML.read_text(encoding="utf-8"))
    assert "IntelligencePage" in block, (
        "index.html intelligence route must render <IntelligencePage />"
    )


def test_index_html_intelligence_route_does_not_use_learning_parser_page():
    """The old V1 mock component must be replaced in the intelligence route."""
    block = _intelligence_route_block(_INDEX_HTML.read_text(encoding="utf-8"))
    assert "LearningParserPage" not in block, (
        "index.html intelligence route must not use <LearningParserPage /> (V1 mock)"
    )


def test_intelligence_route_block_present():
    src = _INDEX_HTML.read_text(encoding="utf-8")
    assert "page === 'intelligence' && (" in src, (
        "index.html must have the intelligence page conditional (P1 route)"
    )


# ══════════════════════════════════════════════════════════════════════════════
# H. Required testids + read-only disclaimer
# ══════════════════════════════════════════════════════════════════════════════

ELEMENT_TESTIDS = [
    "intelligence-hub-root",
    "intelligence-hub-reload",
    "intelligence-hub-summary",
    "intelligence-hub-status-panel",
    "intelligence-hub-suggestions-panel",
    "intelligence-hub-config-panel",
    "intelligence-hub-learning-panel",
]


def test_required_testids_present():
    src = _src()
    missing = [
        t for t in ELEMENT_TESTIDS
        if f'data-testid="{t}"' not in src and f'testid="{t}"' not in src
    ]
    assert not missing, f"IntelligencePage missing testids: {missing}"


def test_read_only_disclaimer_present():
    src = _src().lower()
    assert "observer only" in src or "read-only" in src, (
        "IntelligencePage must declare a read-only / observer-only disclaimer"
    )


def test_reload_button_is_passive():
    """The Reload control must not carry a server-side trigger label."""
    code = _code_only(_src()).lower()
    assert "intelligence-hub-reload" in code, "Reload control testid must exist"
    pre = code.split("intelligence-hub-reload")[0][-200:]
    for bad in ("reprocess", "recheck", "trigger", "regenerate", "resend", "execute"):
        assert bad not in pre, f"Reload control vicinity must not mention {bad!r}"


# ══════════════════════════════════════════════════════════════════════════════
# I. NAV_TREE — Intelligence discoverability (P2)
# ══════════════════════════════════════════════════════════════════════════════

def test_intelligence_in_nav_tree():
    src = _COMPONENTS.read_text(encoding="utf-8")
    nav_body = src[src.index("NAV_TREE = ["):src.index("];", src.index("NAV_TREE = ["))]
    assert "id: 'intelligence'" in nav_body, (
        "components.jsx NAV_TREE must include id: 'intelligence' (P2 reachability)"
    )
    assert "label: 'Intelligence Hub'" in nav_body, (
        "intelligence NAV_TREE entry must use label 'Intelligence Hub' (matches page header; Sprint 34c cleanup)"
    )


def test_existing_nav_entries_preserved():
    src = _COMPONENTS.read_text(encoding="utf-8")
    nav_body = src[src.index("NAV_TREE = ["):src.index("];", src.index("NAV_TREE = ["))]
    for page_id in ("dashboard", "inbox", "shipments", "proforma",
                    "documents", "accounting", "inventory", "reports",
                    "dhl", "automation", "intelligence"):
        assert f"id: '{page_id}'" in nav_body, (
            f"top-level NAV_TREE entry '{page_id}' must remain"
        )


# ══════════════════════════════════════════════════════════════════════════════
# J. Backend files not changed — read-only implementation guard
# ══════════════════════════════════════════════════════════════════════════════

def test_routes_intelligence_not_modified_by_sprint34():
    """Sprint 34 must NOT add IntelligencePage logic to the backend route file.
    The route file already has the correct GET endpoints; no Sprint 34 changes
    should appear in it."""
    src = (_BACKEND / "routes_intelligence.py").read_text(encoding="utf-8")
    assert "Sprint 34" not in src, (
        "routes_intelligence.py must not be modified by Sprint 34 — backend-only, not touched"
    )


def test_routes_learning_not_modified_by_sprint34():
    src = (_BACKEND / "routes_learning.py").read_text(encoding="utf-8")
    assert "Sprint 34" not in src, (
        "routes_learning.py must not be modified by Sprint 34 — backend-only, not touched"
    )
