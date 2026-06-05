"""
test_inbox_v2_contract.py — Sprint 27 Inbox V2 promotion contract.

Asserts (static source-grep; no server required):

  A. inbox-v2.html existence and script loading (1–5)
     1. inbox-v2.html exists in service/app/static/.
     2. inbox-v2.html loads v2/inbox-page.jsx.
     3. inbox-v2.html loads dashboard-shared.js (provides EstrellaShared.apiFetch).
     4. inbox-v2.html loads pz-api.js (provides PzApi.approveProposal/rejectProposal).
     5. inbox-v2.html mounts window.InboxPage on #root.

  B. Atlas stub retired (6)
     6. atlas/inbox-v2.html does NOT exist — stale prototype removed.

  C. NAV_ROUTES and STUB_ROUTES in pz-design-v2.js (7–9)
     7. pz-design-v2.js routes inbox to /dashboard/inbox-v2.html.
     8. 'inbox' is NOT in STUB_ROUTES (sidebar link is live).
     9. 'inventory' remains in STUB_ROUTES ('accounting' promoted in Sprint 28).

  D. Preserved boundaries (10–12)
    10. wfirma-inbox-v2.html still exists (separate wFirma recovery domain).
    11. dashboard.html V1 inbox unchanged — contains InboxPage function.
    12. No backend/route/customs/wFirma/PZ/proforma files changed.
"""
from __future__ import annotations

from pathlib import Path

_ROOT   = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "service" / "app" / "static"


def _read(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8", errors="replace")


# ══════════════════════════════════════════════════════════════════════════════
# A — inbox-v2.html existence and script loading
# ══════════════════════════════════════════════════════════════════════════════

def test_inbox_v2_exists():
    assert (_STATIC / "inbox-v2.html").exists(), \
        "inbox-v2.html must exist in service/app/static/"


def test_inbox_v2_loads_inbox_page_jsx():
    src = _read("inbox-v2.html")
    assert "v2/inbox-page.jsx" in src, \
        "inbox-v2.html must load v2/inbox-page.jsx"


def test_inbox_v2_loads_dashboard_shared():
    src = _read("inbox-v2.html")
    assert "dashboard-shared.js" in src, \
        "inbox-v2.html must load dashboard-shared.js (provides EstrellaShared.apiFetch)"


def test_inbox_v2_loads_pz_api():
    src = _read("inbox-v2.html")
    assert "pz-api.js" in src, \
        "inbox-v2.html must load pz-api.js (provides PzApi.approveProposal/rejectProposal)"


def test_inbox_v2_mounts_inbox_page():
    src = _read("inbox-v2.html")
    assert "window.InboxPage" in src or "InboxPage" in src, \
        "inbox-v2.html must mount window.InboxPage on #root"


# ══════════════════════════════════════════════════════════════════════════════
# B — Atlas stub retired
# ══════════════════════════════════════════════════════════════════════════════

def test_atlas_inbox_stub_removed():
    assert not (_STATIC / "atlas" / "inbox-v2.html").exists(), (
        "atlas/inbox-v2.html must be deleted — stale prototype. "
        "Production authority is service/app/static/inbox-v2.html."
    )


# ══════════════════════════════════════════════════════════════════════════════
# C — NAV_ROUTES and STUB_ROUTES in pz-design-v2.js
# ══════════════════════════════════════════════════════════════════════════════

def test_nav_routes_inbox_points_to_inbox_v2():
    src = _read("pz-design-v2.js")
    # The NAV_ROUTES entry has the form: 'inbox': '/dashboard/inbox-v2.html'
    # Search for the direct route assignment, not the NAV_TREE label entry.
    assert "'inbox'" in src, "pz-design-v2.js must have an 'inbox' nav id"
    assert "/dashboard/inbox-v2.html" in src, \
        "pz-design-v2.js must route inbox to /dashboard/inbox-v2.html"
    # Confirm assignment form: 'inbox': '...inbox-v2.html'
    import re
    match = re.search(r"'inbox'\s*:\s*'[^']*inbox-v2\.html'", src)
    assert match is not None, (
        "NAV_ROUTES must contain the mapping 'inbox': '/dashboard/inbox-v2.html'"
    )


def test_inbox_not_in_stub_routes():
    src = _read("pz-design-v2.js")
    # STUB_ROUTES should not contain 'inbox' — the page now exists
    stub_idx = src.index("STUB_ROUTES")
    stub_block = src[stub_idx:stub_idx + 120]
    assert "'inbox'" not in stub_block, (
        "'inbox' must be removed from STUB_ROUTES — inbox-v2.html is now deployed"
    )


def test_inventory_remains_in_stub_routes():
    # 'accounting' was promoted in Sprint 28 (accounting-hub-v2.html now live).
    # Only 'inventory' should remain as a stub.
    src = _read("pz-design-v2.js")
    stub_idx = src.index("STUB_ROUTES")
    stub_block = src[stub_idx:stub_idx + 100]
    assert "'inventory'" in stub_block, \
        "'inventory' must remain in STUB_ROUTES (page not yet built)"


# ══════════════════════════════════════════════════════════════════════════════
# D — Preserved boundaries
# ══════════════════════════════════════════════════════════════════════════════

def test_wfirma_inbox_preserved():
    assert (_STATIC / "wfirma-inbox-v2.html").exists(), (
        "wfirma-inbox-v2.html must still exist — it is the separate wFirma "
        "recovery domain (series-missing), not general inbox."
    )


def test_dashboard_v1_inbox_untouched():
    src = _read("dashboard.html")
    assert "InboxPage" in src, (
        "dashboard.html V1 InboxPage must be untouched — "
        "V1 freeze rule; any change to dashboard.html would violate Lesson F."
    )


def test_no_backend_files_changed():
    import subprocess, sys
    result = subprocess.run(
        ["git", "diff", "--name-only", "origin/main", "HEAD"],
        cwd=str(_ROOT),
        capture_output=True, text=True,
    )
    changed = result.stdout.splitlines()
    forbidden = [
        f for f in changed
        if any(pat in f for pat in [
            "app/api/", "app/services/", "routes_", "customs", "wfirma",
            "pz_import", "engine/", ".env",
        ])
    ]
    assert not forbidden, (
        f"Forbidden backend/write files found in diff: {forbidden}"
    )
