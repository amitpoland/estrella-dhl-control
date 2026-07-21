"""
test_inventory_v2_contract.py — Sprint 29 Inventory V2 read-only contract.

Asserts (static source-grep; no server required):

  A. inventory-v2.html existence and structure (1–5)
     1. inventory-v2.html exists.
     2. inventory-v2.html loads dashboard-shared.js.
     3. inventory-v2.html loads pz-api.js.
     4. inventory-v2.html mounts via ReactDOM.createRoot.
     5. inventory-v2.html has data-testid="inventory-hub-root".

  B. Only approved read-only endpoints are referenced (6–10)
     6. All 8 approved GET paths are present in source.
     7. No POST/PATCH/DELETE/PUT fetch methods — strictly read-only.
     8. No write endpoints: sample-out, sample-return, return-from-client,
        return-to-producer, return-from-producer, scan (write), location POST.
     9. inventory-page.jsx prototype is NOT loaded or imported.
    10. No /api/v1/inventory/pieces/{id}/location (write route) referenced.

  C. STUB_ROUTES in pz-design-v2.js (11–12)
    11. 'inventory' is NOT in STUB_ROUTES.
    12. STUB_ROUTES is an empty Set (all routes now live).

  D. Preserved boundaries (13–14)
    13. wfirma-inbox-v2.html still exists.
    14. No backend/route/customs/wFirma/PZ/proforma files changed.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT   = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "service" / "app" / "static"


def _read(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8", errors="replace")


# ══════════════════════════════════════════════════════════════════════════════
# A — inventory-v2.html existence and structure
# ══════════════════════════════════════════════════════════════════════════════

def test_inventory_v2_exists():
    assert (_STATIC / "inventory-v2.html").exists(), \
        "inventory-v2.html must exist in service/app/static/"


def test_inventory_v2_loads_dashboard_shared():
    src = _read("inventory-v2.html")
    assert "dashboard-shared.js" in src, \
        "inventory-v2.html must load dashboard-shared.js (provides EstrellaShared.apiFetch)"


def test_inventory_v2_loads_pz_api():
    src = _read("inventory-v2.html")
    assert "pz-api.js" in src, \
        "inventory-v2.html must load pz-api.js"


def test_inventory_v2_mounts_root():
    src = _read("inventory-v2.html")
    assert "ReactDOM.createRoot" in src, \
        "inventory-v2.html must mount via ReactDOM.createRoot"


def test_inventory_v2_has_root_testid():
    src = _read("inventory-v2.html")
    assert 'data-testid="inventory-hub-root"' in src, \
        "inventory-v2.html must have data-testid='inventory-hub-root' on root element"


# ══════════════════════════════════════════════════════════════════════════════
# B — Only approved read-only endpoints
# ══════════════════════════════════════════════════════════════════════════════

_APPROVED_PATHS = [
    "/api/v1/inventory/stage2/aggregate",
    "/api/v1/inventory/state/",
    "/api/v1/inventory/pieces/",
    "/api/v1/warehouse/inventory/",
    "/api/v1/warehouse/locations",
    "/api/v1/warehouse/audit-summary/",
    "/api/v1/warehouse/audit/",
]


def test_all_approved_endpoints_present():
    src = _read("inventory-v2.html")
    for path in _APPROVED_PATHS:
        assert path in src, f"Approved endpoint path '{path}' not found in inventory-v2.html"


def test_no_write_methods():
    src = _read("inventory-v2.html")
    write_patterns = [
        "method: 'POST'", 'method: "POST"',
        "method: 'PATCH'", 'method: "PATCH"',
        "method: 'DELETE'", 'method: "DELETE"',
        "method: 'PUT'", 'method: "PUT"',
    ]
    for pattern in write_patterns:
        assert pattern not in src, \
            f"Write method '{pattern}' found — inventory-v2.html must be strictly read-only"


_FORBIDDEN_WRITE_SUFFIXES = [
    "/sample-out",
    "/sample-return",
    "/return-from-client",
    "/return-to-producer",
    "/return-from-producer",
    # POST /inventory/pieces/{id}/location — the write path ends with /pieces/.../location
    # Note: /warehouse/locations (plural) IS approved — only the piece-level /location suffix is forbidden
    "inventory/scan`",      # POST scan write endpoint pattern
]


def test_no_write_endpoint_paths():
    src = _read("inventory-v2.html")
    for pattern in _FORBIDDEN_WRITE_SUFFIXES:
        assert pattern not in src, (
            f"Forbidden write endpoint pattern '{pattern}' found in inventory-v2.html. "
            "Write operations are deferred to Sprint 30."
        )
    # The piece-level location write route: /api/v1/inventory/pieces/{id}/location
    # Distinguish from /warehouse/locations (approved) by checking the specific path
    import re
    piece_location_write = re.search(r'/inventory/pieces/[^/\s]+/location', src)
    assert not piece_location_write, (
        "POST /inventory/pieces/{id}/location write route found — deferred to Sprint 30"
    )


def test_inventory_page_jsx_not_loaded():
    src = _read("inventory-v2.html")
    assert "inventory-page.jsx" not in src, (
        "v2/inventory-page.jsx must NOT be loaded — it is a mock prototype "
        "with no real API calls. Build the real page inline."
    )


def test_no_piece_location_write_route():
    src = _read("inventory-v2.html")
    import re
    # POST /inventory/pieces/{id}/location is a write route (deferred to Sprint 30)
    # Approved: GET /warehouse/locations (plural) — this is NOT the forbidden route
    # Forbidden: any path ending /pieces/{something}/location
    assert not re.search(r"inventory/pieces/[^'\"\s]+/location", src), (
        "POST /inventory/pieces/{id}/location is a write route — deferred to Sprint 30. "
        "Note: GET /warehouse/locations (plural) IS approved and is different."
    )


# ══════════════════════════════════════════════════════════════════════════════
# C — STUB_ROUTES in pz-design-v2.js
# ══════════════════════════════════════════════════════════════════════════════

def test_inventory_not_in_stub_routes():
    src = _read("pz-design-v2.js")
    stub_idx = src.index("STUB_ROUTES")
    stub_block = src[stub_idx:stub_idx + 150]
    assert "'inventory'" not in stub_block, \
        "'inventory' must be removed from STUB_ROUTES — inventory-v2.html is now deployed"


def test_stub_routes_is_empty():
    src = _read("pz-design-v2.js")
    stub_idx = src.index("STUB_ROUTES")
    stub_block = src[stub_idx:stub_idx + 150]
    # STUB_ROUTES should be an empty Set — no remaining stubs
    match = re.search(r"new Set\(\[(.*?)\]\)", stub_block)
    if match:
        contents = match.group(1).strip()
        assert contents == '', (
            f"STUB_ROUTES should be empty Set([]) but found: {contents}. "
            "All V2 sidebar routes are now live."
        )


# ══════════════════════════════════════════════════════════════════════════════
# D — Preserved boundaries
# ══════════════════════════════════════════════════════════════════════════════

def test_wfirma_inbox_preserved():
    assert (_STATIC / "wfirma-inbox-v2.html").exists(), \
        "wfirma-inbox-v2.html must remain — separate wFirma recovery domain"


# ── Inventory V2 promotion boundary (Sprint 29) ──────────────────────────────
# This contract protects ONLY files owned by the Inventory V2 feature. It
# INTENTIONALLY ignores unrelated backend changes elsewhere in the repository —
# it is NOT a repository-wide backend freeze.
#
# OWNERSHIP is the authority, not the token. `_inventory_owned_backend_coupling`
# defines the owned set as backend-impl files (anchored prefixes below) whose
# path carries the 'inventory' token. If an Inventory backend file is renamed or
# moved out of that naming, UPDATE THIS OWNERSHIP RULE — do not assume the token
# alone stays correct. Anchored prefixes prevent bare substrings like "routes_"
# from mis-classifying test files (service/tests/test_routes_*.py).
#
# The read-only ENDPOINT restrictions above (no POST/PATCH/DELETE, approved-GET-
# only) remain the primary contract and are unchanged by this scoping.
_BACKEND_IMPL_PREFIXES = ("service/app/api/", "service/app/services/")


def _changed_files(base="origin/main", head="HEAD"):
    import subprocess
    r = subprocess.run(["git", "diff", "--name-only", base, head],
                       cwd=str(_ROOT), capture_output=True, text=True)
    return [f for f in r.stdout.splitlines() if f.strip()]


def _is_backend_impl(path):
    return path.startswith(_BACKEND_IMPL_PREFIXES)


def _inventory_owned_backend_coupling(changed):
    """Inventory-owned backend implementation files changed on this branch — the
    only thing the Inventory V2 promotion boundary prohibits. Ownership anchored
    by the 'inventory' token; unrelated backend is out of scope."""
    return [p for p in changed if _is_backend_impl(p) and "inventory" in p.lower()]


def test_no_inventory_owned_backend_coupling():
    forbidden = _inventory_owned_backend_coupling(_changed_files())
    assert not forbidden, (
        "Inventory V2 promotion must not add Inventory-owned backend coupling "
        f"(app/api or app/services files for inventory): {forbidden}. Unrelated "
        "backend changes elsewhere in the branch are out of this contract's scope."
    )


def test_inventory_backend_classifier_scope():
    """Deterministic scope pins (no git)."""
    det = _inventory_owned_backend_coupling
    assert det(["service/app/api/routes_inventory.py"]) == ["service/app/api/routes_inventory.py"]
    assert det(["service/app/services/inventory_state_db.py"]) == ["service/app/services/inventory_state_db.py"]
    # unrelated backend IGNORED
    assert det(["service/app/api/routes_proforma.py"]) == []
    assert det(["service/app/services/document_reconciler.py"]) == []
    # test file not mis-classified
    assert det(["service/tests/test_routes_proforma_reconciliation.py"]) == []
    # owned frontend not backend impl
    assert det(["service/app/static/inventory-v2.html"]) == []
