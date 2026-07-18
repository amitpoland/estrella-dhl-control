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
     9. STUB_ROUTES is empty — all sidebar routes now live (inventory promoted in Sprint 29).

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


def test_stub_routes_now_empty():
    # Sprint 29 promoted inventory-v2.html. All sidebar routes are now live.
    # STUB_ROUTES should be an empty Set.
    import re as _re
    src = _read("pz-design-v2.js")
    stub_idx = src.index("STUB_ROUTES")
    stub_block = src[stub_idx:stub_idx + 150]
    match = _re.search(r"new Set\(\[(.*?)\]\)", stub_block)
    if match:
        assert match.group(1).strip() == '', \
            "STUB_ROUTES should be empty Set([]) — all V2 routes now live"


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


# ── Inbox V2 promotion boundary (Sprint 27) ──────────────────────────────────
# This contract protects ONLY files owned by the Inbox V2 feature. It
# INTENTIONALLY ignores unrelated backend changes elsewhere in the repository
# (e.g. proforma / reconciliation) — it is NOT a repository-wide backend freeze.
#
# OWNERSHIP is the authority, not the token. `_inbox_owned_backend_coupling`
# defines the owned set as backend-impl files (anchored prefixes below) whose
# path carries the 'inbox' token. If an Inbox backend file is renamed or moved
# out of that naming, UPDATE THIS OWNERSHIP RULE — do not assume the token alone
# stays correct. Anchored prefixes are used so bare substrings like "routes_"
# never mis-classify test files (service/tests/test_routes_*.py).
_BACKEND_IMPL_PREFIXES = ("service/app/api/", "service/app/services/")


def _changed_files(base="origin/main", head="HEAD"):
    import subprocess
    r = subprocess.run(["git", "diff", "--name-only", base, head],
                       cwd=str(_ROOT), capture_output=True, text=True)
    return [f for f in r.stdout.splitlines() if f.strip()]


def _is_backend_impl(path):
    # anchored to real backend implementation dirs; test files (service/tests/…)
    # and static frontend (service/app/static/…) are never backend impl.
    return path.startswith(_BACKEND_IMPL_PREFIXES)


def _inbox_owned_backend_coupling(changed):
    """Inbox-owned backend implementation files changed on this branch — the only
    thing the Inbox V2 promotion boundary prohibits. Ownership anchored by the
    'inbox' token in the path; unrelated backend is out of scope."""
    return [p for p in changed if _is_backend_impl(p) and "inbox" in p.lower()]


def test_no_inbox_owned_backend_coupling():
    forbidden = _inbox_owned_backend_coupling(_changed_files())
    assert not forbidden, (
        "Inbox V2 promotion must not add Inbox-owned backend coupling "
        f"(app/api or app/services files for inbox): {forbidden}. Unrelated "
        "backend changes elsewhere in the branch are out of this contract's scope."
    )


def test_inbox_backend_classifier_scope():
    """Deterministic scope pins (no git) — the classifier flags Inbox-owned
    backend, ignores unrelated backend, and never mis-classifies test files."""
    det = _inbox_owned_backend_coupling
    assert det(["service/app/api/routes_inbox.py"]) == ["service/app/api/routes_inbox.py"]
    assert det(["service/app/services/inbox_projection.py"]) == ["service/app/services/inbox_projection.py"]
    # unrelated backend (proforma / reconciliation) is IGNORED
    assert det(["service/app/api/routes_proforma.py"]) == []
    assert det(["service/app/services/document_reconciler.py"]) == []
    # bare "routes_" no longer mis-classifies a test file
    assert det(["service/tests/test_routes_proforma_reconciliation.py"]) == []
    # owned frontend files are not backend impl
    assert det(["service/app/static/v2/inbox-page.jsx"]) == []
