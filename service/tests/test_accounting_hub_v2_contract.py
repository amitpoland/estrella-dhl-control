"""
test_accounting_hub_v2_contract.py — Wave-3 Accounting Hub V2 contract.

SUPERSEDED: Sprint-28 contract targeted accounting-hub-v2.html (standalone HTML,
V1 shell era). V2 era uses accounting-hub.jsx in the Atlas Babel-JSX shell.
This contract reflects the V2 architecture.

Asserts (static source-grep; no server required):

  A. accounting-hub.jsx existence and structure in V2 static (1–3)
     1. service/app/static/v2/accounting-hub.jsx exists.
     2. accounting-hub.jsx has data-testid="accounting-hub-root".
     3. accounting-hub.jsx exports window.AccountingHub.

  B. WIRED_PAGES includes 'accounting' (mock-badge.jsx) (4)
     4. 'accounting' is in WIRED_PAGES in mock-badge.jsx.

  C. index.html routes 'accounting' slug to AccountingHub (5–6)
     5. index.html loads accounting-hub.jsx as Babel script.
     6. index.html routes page==='accounting' to AccountingHub.

  D. Only approved pz-api.js methods used; no forbidden endpoints (7–8)
     7. Wave-3 API additions present in pz-api.js:
        getWfirmaContractorScanStatus.
     8. No forbidden endpoint strings in accounting-hub.jsx *call sites*:
        /api/v1/accounting/, /api/v1/ledger/clients, /api/v1/wfirma/sync/.
        Display-only helper text (note=/label= label strings) and JS comments
        that DOCUMENT a backend-pending endpoint are exempt — the guard targets
        real request call sites (fetch/apiFetch/PzApi-bypass), not honest
        "Backend Pending · GET /api/v1/accounting/{type}" placeholders. All live
        reads in the hub already go through window.PzApi.* transport wrappers.

  E. Wave-4 gated tabs kept visible (9)
     9. accounting-hub.jsx contains Wave-4 gated tab IDs (wz/pz/pw/rw/mm).

  F. No mock arrays remain in accounting-hub.jsx (10)
    10. accounting-hub.jsx must NOT contain ACC_DOCS, CLIENT_BALANCE,
        CLIENT_LEDGER, SUPPLIER_LEDGER (old mock data arrays).

  G. LedgersPage embed present (11)
    11. accounting-hub.jsx references window.LedgersPage for the Client
        Ledger tab.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT     = Path(__file__).resolve().parents[2]
_V2       = _ROOT / "service" / "app" / "static" / "v2"
_STATIC   = _ROOT / "service" / "app" / "static"


def _read_v2(name: str) -> str:
    return (_V2 / name).read_text(encoding="utf-8", errors="replace")


# ══════════════════════════════════════════════════════════════════════════════
# A — accounting-hub.jsx existence and structure
# ══════════════════════════════════════════════════════════════════════════════

def test_accounting_hub_jsx_exists():
    assert (_V2 / "accounting-hub.jsx").exists(), \
        "service/app/static/v2/accounting-hub.jsx must exist (Wave-3 V2 authority)"


def test_accounting_hub_has_root_testid():
    src = _read_v2("accounting-hub.jsx")
    assert 'data-testid="accounting-hub-root"' in src, (
        "accounting-hub.jsx must have data-testid='accounting-hub-root' on the "
        "AccountingHub root element"
    )


def test_accounting_hub_exports_window():
    src = _read_v2("accounting-hub.jsx")
    assert "window.AccountingHub" in src, (
        "accounting-hub.jsx must expose window.AccountingHub for the Atlas shell"
    )


# ══════════════════════════════════════════════════════════════════════════════
# B — WIRED_PAGES includes 'accounting'
# ══════════════════════════════════════════════════════════════════════════════

def test_accounting_in_wired_pages():
    src = _read_v2("mock-badge.jsx")
    assert "'accounting'" in src, (
        "'accounting' must be added to WIRED_PAGES in mock-badge.jsx. "
        "Absence means the MOCK banner still renders on the live page."
    )


# ══════════════════════════════════════════════════════════════════════════════
# C — index.html routes 'accounting' slug to AccountingHub
# ══════════════════════════════════════════════════════════════════════════════

def test_index_html_loads_accounting_hub_jsx():
    src = (_V2 / "index.html").read_text(encoding="utf-8", errors="replace")
    assert "accounting-hub.jsx" in src, (
        "index.html must load accounting-hub.jsx as a Babel script"
    )


def test_index_html_routes_accounting_slug():
    src = (_V2 / "index.html").read_text(encoding="utf-8", errors="replace")
    assert "page === 'accounting'" in src or "page==='accounting'" in src, (
        "index.html must route page==='accounting' to AccountingHub"
    )


# ══════════════════════════════════════════════════════════════════════════════
# D — Approved pz-api.js methods; no forbidden endpoints
# ══════════════════════════════════════════════════════════════════════════════

def test_pz_api_has_wfirma_contractor_scan_status():
    src = _read_v2("pz-api.js")
    assert "getWfirmaContractorScanStatus" in src, (
        "pz-api.js must define getWfirmaContractorScanStatus "
        "(Wave-3 transport wrapper for GET /api/v1/wfirma/contractors/scan/status)"
    )


_FORBIDDEN_ENDPOINTS = [
    "/api/v1/accounting/",
    "/api/v1/ledger/clients",    # wrong path (real: /ledgers/clients/)
    "/api/v1/wfirma/sync/",
]

# Display-only string values on a note=/label= prop (JSX attr or object key).
# accounting-hub renders honest "Backend Pending · GET /api/v1/accounting/{type}"
# placeholders (Lesson M honest UI) via <_AccPendingTable note="…" />; that text
# DOCUMENTS the backend-pending endpoint — it is not a request call site. This
# guard targets real call sites, so those label strings must not trip it.
_DISPLAY_PROP_STR = re.compile(r"""\b(?:note|label)\s*[=:]\s*(["'`])(?:(?!\1).)*\1""")


def _code_only(src: str) -> str:
    """Return the executable code of a JSX source with the two documentation-only
    contexts stripped: full-line JS comments and note=/label= display string
    values. Anything left is real code — a genuine fetch/apiFetch to a forbidden
    endpoint (or any non-display occurrence) still survives and trips the guard."""
    lines = [
        ln for ln in src.splitlines()
        if not ln.lstrip().startswith("//") and not ln.lstrip().startswith("*")
    ]
    return _DISPLAY_PROP_STR.sub('note=""', "\n".join(lines))


def test_no_forbidden_endpoints_in_hub():
    # Grep the CALL-SITE code only. Display-only note=/label docs and comments
    # that name a backend-pending endpoint are honest UI text, not a direct
    # call, and must not trip this guard (all live reads go through PzApi.*).
    src = _code_only(_read_v2("accounting-hub.jsx"))
    for pattern in _FORBIDDEN_ENDPOINTS:
        assert pattern not in src, (
            f"Forbidden endpoint '{pattern}' found in an accounting-hub.jsx call "
            "site. Use only PzApi transport wrappers for approved EXISTING "
            "endpoints (display-only note=/label docs + comments are exempt)."
        )


# ══════════════════════════════════════════════════════════════════════════════
# E — Wave-4 gated tabs visible
# ══════════════════════════════════════════════════════════════════════════════

def test_wave4_gated_tabs_present():
    src = _read_v2("accounting-hub.jsx")
    for tab_id in ("'wz'", "'pz'", "'pw'", "'rw'", "'mm'"):
        assert tab_id in src, (
            f"Wave-4 gated tab id {tab_id} must remain visible in accounting-hub.jsx "
            "(R-Q3 honest UI — gated, not hidden)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# F — No mock arrays remain
# ══════════════════════════════════════════════════════════════════════════════

def test_no_mock_arrays():
    src = _read_v2("accounting-hub.jsx")
    forbidden_names = ["ACC_DOCS", "CLIENT_BALANCE", "CLIENT_LEDGER", "SUPPLIER_LEDGER"]
    for name in forbidden_names:
        assert name not in src, (
            f"Mock array '{name}' found in accounting-hub.jsx — "
            "all hardcoded mock data must be removed (Wave-3 live wiring)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# G — LedgersPage embed
# ══════════════════════════════════════════════════════════════════════════════

def test_ledgers_page_embedded():
    src = _read_v2("accounting-hub.jsx")
    assert "window.LedgersPage" in src, (
        "accounting-hub.jsx must reference window.LedgersPage for the Client Ledger tab "
        "(census AC-5: ledgers-page.jsx loaded but not mounted under accounting)"
    )
