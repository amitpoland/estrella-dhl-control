"""
test_accounting_hub_v2_contract.py — Sprint 28 Accounting Hub V2 contract.

Asserts (static source-grep; no server required):

  A. accounting-hub-v2.html existence and structure (1–5)
     1. accounting-hub-v2.html exists.
     2. accounting-hub-v2.html loads dashboard-shared.js.
     3. accounting-hub-v2.html loads pz-api.js.
     4. accounting-hub-v2.html mounts a root component (ReactDOM.createRoot).
     5. accounting-hub-v2.html has data-testid="accounting-hub-root".

  B. Only approved endpoints are referenced (6–8)
     6. No forbidden endpoint patterns present:
        /api/v1/accounting/, /api/v1/ledger/clients, /api/v1/wfirma/sync/.
     7. All referenced /api/v1/ paths are from the approved list.
     8. No POST/PATCH/DELETE/PUT fetch methods — page is strictly read-only.

  C. Atlas stub retired (9)
     9. atlas/accounting-v2.html does NOT exist.

  D. NAV_ROUTES and STUB_ROUTES (10–12)
    10. NAV_ROUTES['accounting'] points to /dashboard/accounting-hub-v2.html.
    11. 'accounting' is NOT in STUB_ROUTES.
    12. STUB_ROUTES is empty (inventory promoted in Sprint 29).

  E. Preserved boundaries (13–14)
    13. wfirma-inbox-v2.html still exists.
    14. No backend files changed.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT   = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "service" / "app" / "static"


def _read(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8", errors="replace")


# ══════════════════════════════════════════════════════════════════════════════
# A — accounting-hub-v2.html existence and structure
# ══════════════════════════════════════════════════════════════════════════════

def test_accounting_hub_exists():
    assert (_STATIC / "accounting-hub-v2.html").exists(), \
        "accounting-hub-v2.html must exist in service/app/static/"


def test_accounting_hub_loads_dashboard_shared():
    src = _read("accounting-hub-v2.html")
    assert "dashboard-shared.js" in src, \
        "accounting-hub-v2.html must load dashboard-shared.js (provides EstrellaShared.apiFetch)"


def test_accounting_hub_loads_pz_api():
    src = _read("accounting-hub-v2.html")
    assert "pz-api.js" in src, \
        "accounting-hub-v2.html must load pz-api.js"


def test_accounting_hub_mounts_root():
    src = _read("accounting-hub-v2.html")
    assert "ReactDOM.createRoot" in src, \
        "accounting-hub-v2.html must mount via ReactDOM.createRoot"


def test_accounting_hub_has_root_testid():
    src = _read("accounting-hub-v2.html")
    assert 'data-testid="accounting-hub-root"' in src, \
        "accounting-hub-v2.html must have data-testid='accounting-hub-root' on root element"


# ══════════════════════════════════════════════════════════════════════════════
# B — Only approved endpoints referenced
# ══════════════════════════════════════════════════════════════════════════════

_FORBIDDEN_PATTERNS = [
    "/api/v1/accounting/",
    "/api/v1/ledger/clients",      # wrong path — real path is /ledgers/clients/
    "/api/v1/wfirma/sync/",
]

_APPROVED_API_PATHS = [
    "/api/v1/proforma/draft/",         # covers invoice-link, to-invoice-preview, disclose-convert
    "/api/v1/proforma/pipeline/",
    "/api/v1/proforma/",               # covers /{batch_id}/{client}/dual-valuation
    "/api/v1/ledgers/clients/",
]


def test_no_forbidden_endpoints():
    src = _read("accounting-hub-v2.html")
    for pattern in _FORBIDDEN_PATTERNS:
        assert pattern not in src, (
            f"Forbidden endpoint pattern '{pattern}' found in accounting-hub-v2.html. "
            "Only pre-approved routes from the authority audit may be used."
        )


def test_all_api_paths_are_approved():
    src = _read("accounting-hub-v2.html")
    # Extract all /api/v1/... path strings from the source
    found = re.findall(r"/api/v1/[a-zA-Z0-9/_{}.*-]+", src)
    for path in set(found):
        matched = any(path.startswith(approved) or approved in path
                      for approved in _APPROVED_API_PATHS)
        assert matched, (
            f"Unapproved API path '{path}' found in accounting-hub-v2.html. "
            f"Approved prefixes: {_APPROVED_API_PATHS}"
        )


def test_no_write_methods():
    src = _read("accounting-hub-v2.html")
    write_patterns = [
        "method: 'POST'", 'method: "POST"',
        "method: 'PATCH'", 'method: "PATCH"',
        "method: 'DELETE'", 'method: "DELETE"',
        "method: 'PUT'", 'method: "PUT"',
    ]
    for pattern in write_patterns:
        assert pattern not in src, (
            f"Write method '{pattern}' found — accounting-hub-v2.html must be strictly read-only"
        )


# ══════════════════════════════════════════════════════════════════════════════
# C — Atlas stub retired
# ══════════════════════════════════════════════════════════════════════════════

def test_atlas_accounting_stub_removed():
    assert not (_STATIC / "atlas" / "accounting-v2.html").exists(), (
        "atlas/accounting-v2.html must be deleted — stale static mock. "
        "Production authority is service/app/static/accounting-hub-v2.html."
    )


# ══════════════════════════════════════════════════════════════════════════════
# D — NAV_ROUTES and STUB_ROUTES
# ══════════════════════════════════════════════════════════════════════════════

def test_nav_routes_accounting_target():
    src = _read("pz-design-v2.js")
    match = re.search(r"'accounting'\s*:\s*'[^']*accounting-hub-v2\.html'", src)
    assert match is not None, \
        "NAV_ROUTES must map 'accounting' to '/dashboard/accounting-hub-v2.html'"


def test_accounting_not_in_stub_routes():
    src = _read("pz-design-v2.js")
    stub_idx = src.index("STUB_ROUTES")
    stub_block = src[stub_idx:stub_idx + 100]
    assert "'accounting'" not in stub_block, \
        "'accounting' must be removed from STUB_ROUTES — accounting-hub-v2.html is now deployed"


def test_stub_routes_now_empty():
    # Sprint 29 promoted inventory-v2.html. STUB_ROUTES should be empty.
    import re as _re
    src = _read("pz-design-v2.js")
    stub_idx = src.index("STUB_ROUTES")
    stub_block = src[stub_idx:stub_idx + 150]
    match = _re.search(r"new Set\(\[(.*?)\]\)", stub_block)
    if match:
        assert match.group(1).strip() == '', \
            "STUB_ROUTES should be empty Set([]) — all V2 routes now live"


# ══════════════════════════════════════════════════════════════════════════════
# E — Preserved boundaries
# ══════════════════════════════════════════════════════════════════════════════

def test_wfirma_inbox_preserved():
    assert (_STATIC / "wfirma-inbox-v2.html").exists(), \
        "wfirma-inbox-v2.html must remain — it is the separate wFirma recovery domain"


def test_no_backend_files_changed():
    import subprocess
    result = subprocess.run(
        ["git", "diff", "--name-only", "origin/main", "HEAD"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    changed = result.stdout.splitlines()
    forbidden = [
        f for f in changed if any(pat in f for pat in [
            "app/api/", "app/services/", "routes_", "customs", "wfirma",
            "pz_import", "engine/", ".env",
        ])
    ]
    assert not forbidden, f"Forbidden backend files found in diff: {forbidden}"
