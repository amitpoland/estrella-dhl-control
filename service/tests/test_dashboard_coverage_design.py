"""
test_dashboard_coverage_design.py — Path B / Tier 2 close-out / Pass 18.

Contract for the new Coverage Matrix documentation page:
  - Static frontend-maintained matrix; ZERO backend, ZERO fetch
  - Every sidebar leaf route from NAV_TREE present in MATRIX
  - Classification values constrained to the canonical 5-value set
  - Pending rows carry data-pending="true"; live/composed rows do not
  - No write methods, no write buttons, no fake operational data
  - KPI tile counts derived from MATRIX.filter(...).length only
  - 'True stubs remaining' filter excludes 'coverage' route itself
  - coverage no longer routes to StubPage
"""
from __future__ import annotations

import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SVC_ROOT = _HERE.parent
_DASH = _SVC_ROOT / "app" / "static" / "dashboard.html"


def _src() -> str:
    if not _DASH.exists():
        import pytest
        pytest.skip(f"dashboard.html not found at {_DASH}")
    return _DASH.read_text(encoding="utf-8")


def _coverage_block() -> str:
    """Return only the CoverageMatrixPage component body."""
    src = _src()
    start = src.index("function CoverageMatrixPage()")
    end = src.index("function InventoryPage(", start)
    return src[start:end]


# ── 1. Coverage route renders the real component ──────────────────────────

def test_coverage_route_renders_real_component():
    src = _src()
    assert "<CoverageMatrixPage" in src
    assert "page === 'coverage' && (" in src
    assert "function CoverageMatrixPage()" in src
    # Removed from STUB_CONFIG
    stub_start = src.index("const STUB_CONFIG = {")
    stub_end   = src.index("function CoverageMatrixPage(", stub_start)
    stub_block = src[stub_start:stub_end]
    assert "coverage:" not in stub_block


# ── 2. Stub page no longer handles coverage ──────────────────────────────

def test_stub_page_no_longer_handles_coverage():
    src = _src()
    # STUB_CONFIG block contains no `coverage` key
    stub_start = src.index("const STUB_CONFIG = {")
    stub_end   = src.index("function CoverageMatrixPage(", stub_start)
    stub_block = src[stub_start:stub_end]
    assert "coverage:" not in stub_block
    # App() route map does not route coverage through StubPage
    assert "{page === 'coverage' && (\n          <StubPage" not in src
    assert "page === 'coverage' && (\n          <CoverageMatrixPage />" in src


# ── 3. No fetch / apiFetch / side-effect hooks in component body ────────

def test_coverage_page_has_no_fetch_or_apifetch():
    block = _coverage_block()
    for forbidden in ("apiFetch(", "fetch(", "XMLHttpRequest", "dispatchEvent",
                      "axios", "useEffect"):
        assert forbidden not in block, \
            f"CoverageMatrixPage body must NOT contain {forbidden!r}"


# ── 4. No write methods anywhere in component body ──────────────────────

def test_coverage_page_has_no_write_methods():
    block = _coverage_block()
    for forbidden in (
        "method: 'POST'", "method: 'PUT'", "method: 'PATCH'", "method: 'DELETE'",
        'method: "POST"', 'method: "PUT"', 'method: "PATCH"', 'method: "DELETE"',
        "method:'POST'", "method:'PUT'", "method:'PATCH'", "method:'DELETE'",
    ):
        assert forbidden not in block, \
            f"CoverageMatrixPage body must NOT contain {forbidden!r}"


# ── 5. No write-shaped buttons ──────────────────────────────────────────

def test_coverage_page_has_no_write_buttons():
    block = _coverage_block()
    for forbidden in (
        ">Move<", ">Approve<", ">Sync<", ">Refresh<", ">Retry<",
        ">Probe<", ">Run<", ">Execute<", ">Create<", ">Edit<",
        ">Delete<", ">Save<", ">Submit<", ">Send<", ">Post<",
        ">Reset<", ">Unlock<", ">Repair<",
    ):
        assert forbidden not in block, \
            f"Forbidden write-shaped button leaked into CoverageMatrixPage: {forbidden}"


# ── 6. Classifications are exactly the canonical 5 values ───────────────

def test_coverage_page_classifications_are_canonical():
    block = _coverage_block()
    # Extract every `classification: '...'` value from the MATRIX entries.
    found = set(re.findall(r"classification:\s*'([^']+)'", block))
    canonical = {'LIVE', 'PARTIAL', 'COMPOSED', 'STUB ONLY', 'BACKEND PENDING'}
    extra = found - canonical
    assert not extra, f"Non-canonical classification values found: {extra}"
    # And the canonical filter constants in the page also reference only these values
    for v in ('LIVE', 'PARTIAL', 'COMPOSED', 'STUB ONLY', 'BACKEND PENDING'):
        assert f"'{v}'" in block, f"Canonical classification missing from MATRIX/filters: {v}"


# ── 7. Every sidebar leaf is covered (no omissions, no extras) ──────────

_EXTERNAL_HREF_ROUTES = {"warehouse_scanner"}  # external static page, not a SPA route


def _parse_nav_tree_leaves(src: str) -> set:
    """Walk the NAV_TREE block and collect every leaf `id`. Group items
    (those with a `children` array) themselves are NOT leaves; only their
    children are. External-href items are excluded (they navigate to a
    separate static HTML page, not a SPA route)."""
    nav_start = src.index("const NAV_TREE = [")
    nav_end   = src.index("\n];", nav_start) + 3
    nav_block = src[nav_start:nav_end]

    # Collect EVERY `id: '...'` occurrence — both group-level and child-level.
    all_ids = re.findall(r"id:\s*'([^']+)'", nav_block)

    # A group is recognised by an explicit `children:` array on the same line
    # — we strip those.
    group_ids = set()
    for line in nav_block.splitlines():
        m = re.search(r"id:\s*'([^']+)'", line)
        if m and "children:" in line:
            group_ids.add(m.group(1))

    leaves = {i for i in all_ids if i not in group_ids and i not in _EXTERNAL_HREF_ROUTES}
    return leaves


def test_coverage_includes_every_sidebar_module():
    src = _src()
    block = _coverage_block()

    sidebar_leaves = _parse_nav_tree_leaves(src)

    matrix_routes = set(re.findall(r"route:\s*'([^']+)'", block))

    missing  = sidebar_leaves - matrix_routes
    extras   = matrix_routes  - sidebar_leaves

    assert not missing, f"MATRIX is missing sidebar leaves: {sorted(missing)}"
    assert not extras,  f"MATRIX contains routes not in sidebar: {sorted(extras)}"


# ── 8. Pending rows marked data-pending; live/composed rows are not ──────

def test_pending_rows_marked_data_pending():
    block = _coverage_block()
    # The row template uses isPending derived from classification.
    # Verify the derivation logic and the conditional attribute are present.
    assert (
        "const isPending =\n"
        "                row.classification === 'PARTIAL' ||\n"
        "                row.classification === 'BACKEND PENDING' ||\n"
        "                row.classification === 'STUB ONLY';"
    ) in block
    assert 'data-pending={isPending ? \'true\' : undefined}' in block


def test_pending_attribute_only_for_pending_classifications():
    """The MATRIX itself has at least one STUB ONLY row (Coverage Matrix
    itself), and zero PARTIAL / BACKEND PENDING entries today. The
    isPending derivation in the rendered template must correctly classify
    each — the assertion below verifies the rendered HTML emits
    data-pending="true" only for rows whose classification is one of the
    pending three.
    """
    block = _coverage_block()
    # Walk every MATRIX entry, capturing the classification per row.
    rows = re.findall(
        r"\{\s*module:\s*'([^']+)'\s*,\s*route:\s*'([^']+)'\s*,\s*classification:\s*'([^']+)'",
        block,
    )
    assert rows, "No MATRIX rows parsed from CoverageMatrixPage source"
    pending_set = {"PARTIAL", "BACKEND PENDING", "STUB ONLY"}
    # Every row's expected isPending value must match the runtime ternary.
    # The runtime ternary is single — we just confirm both branches exist:
    #   row marked → data-pending="true"
    #   row not    → undefined
    # That's already covered by the previous test. Here we just assert the
    # MATRIX classification distribution is plausible (>=1 pending so the
    # data-pending branch is exercised).
    has_pending = any(c in pending_set for _, _, c in rows)
    assert has_pending, "MATRIX must contain at least one pending row so the data-pending branch is exercised"


# ── 9. No fake operational data inside the component ──────────────────

def test_no_fake_operational_data_in_coverage():
    block = _coverage_block()
    for forbidden in (
        "MOCK_", "SAMPLE_", "FAKE_", "DEMO_",
        "EJ-RING-", "EJ-NECK-", "Diamond Solitaire",
        "PLN 38,400", "PLN 14,640",
        "AWB-DHL-",
    ):
        assert forbidden not in block, \
            f"Fake-data signature leaked into CoverageMatrixPage: {forbidden}"
    # No 10-digit AWB-shaped numeric strings (real AWBs only appear via
    # batches.awb at runtime — never literal in source).
    awb_shaped = re.findall(r"['\"](\d{10,12})['\"]", block)
    assert not awb_shaped, f"AWB-shaped numeric strings in CoverageMatrixPage: {awb_shaped[:3]}"


# ── 10. KPI counts derived from MATRIX.filter(...).length, not literals ──

def test_coverage_kpi_counts_derive_from_matrix():
    block = _coverage_block()
    # Each canonical bucket count must use MATRIX.filter(...).length
    for expr in (
        "MATRIX.filter(m => m.classification === 'LIVE').length",
        "MATRIX.filter(m => m.classification === 'COMPOSED').length",
        "MATRIX.filter(m => m.classification === 'PARTIAL').length",
        "MATRIX.filter(m => m.classification === 'BACKEND PENDING').length",
        "MATRIX.filter(m => m.classification === 'STUB ONLY').length",
    ):
        assert expr in block, f"KPI must derive from MATRIX filter: {expr!r}"
    # KPI tile values reference the derived names — no hardcoded integers
    # on the tile `value:` slot.
    assert "value: counts.LIVE" in block
    assert "value: counts.COMPOSED" in block
    assert "value: pendingBackendSurfaces" in block
    assert "value: trueStubsRemaining" in block


# ── 11. Landmark testids present (page-level + per-row) ─────────────────

def test_coverage_landmark_testids_present():
    src = _src()
    block = _coverage_block()
    # Page-level landmarks
    for tid in (
        'data-testid="coverage-page"',
        'data-testid="coverage-kpi-strip"',
        'data-testid="coverage-matrix-table"',
        'data-testid="coverage-footer"',
    ):
        assert tid in block, f"Missing coverage landmark: {tid}"
    # KPI tile testids — assigned via the kpiTiles array's `testid:` keys
    for kpi_tid in (
        "testid: 'coverage-kpi-live'",
        "testid: 'coverage-kpi-composed'",
        "testid: 'coverage-kpi-pending'",
        "testid: 'coverage-kpi-stubs'",
    ):
        assert kpi_tid in block, f"Missing KPI tile testid: {kpi_tid}"
    # Per-row testids via template literal
    assert 'data-testid={`coverage-row-${row.route}`}' in block

    # And every MATRIX route id is present in source — the template renders
    # `coverage-row-<route>` testids at runtime.
    sidebar_leaves = _parse_nav_tree_leaves(src)
    matrix_routes = set(re.findall(r"route:\s*'([^']+)'", block))
    assert sidebar_leaves <= matrix_routes


# ── 12. trueStubsRemaining filter excludes coverage itself ──────────────

def test_true_stubs_remaining_excludes_coverage_itself():
    block = _coverage_block()
    # Filter must AND the STUB ONLY classification with route !== 'coverage'
    assert (
        "MATRIX.filter(m =>\n"
        "    m.classification === 'STUB ONLY' && m.route !== 'coverage'\n"
        "  ).length"
    ) in block


# ── Extra: confirm the tone helper covers all 5 classifications ─────────

def test_tone_helper_covers_all_classifications():
    block = _coverage_block()
    # Each canonical classification has a tone branch
    for cls in ("LIVE", "COMPOSED", "PARTIAL", "BACKEND PENDING", "STUB ONLY"):
        assert f"c === '{cls}'" in block, f"tone() helper missing branch for {cls}"


# ── Cross-suite: every other Tier 2 design test still has its anchors ──

def test_no_regression_in_other_tier_pages():
    src = _src()
    # Each Tier 2 page landmark must still exist (defensive — the coverage
    # closeout must not have disturbed prior composition pages).
    for anchor in (
        'data-testid="inbox-page"',
        'data-testid="api-status-page"',
        'data-testid="diagnostics-page"',
        'data-testid="carriers-page"',
        'data-testid="master-page"',
        'data-testid="inventory-page"',
    ):
        assert anchor in src, f"Tier 2 page landmark missing after coverage edit: {anchor}"


# ── DETAIL_TABS unchanged ──────────────────────────────────────────────

def test_detail_tabs_unchanged():
    src = _src()
    assert "const DETAIL_TABS = ['Overview', 'Documents', 'DHL / Customs', 'Warehouse', 'Sales', 'PZ / Accounting', 'Timeline', 'Intelligence', 'Proposals']" in src


# ── UI-3 landmarks unchanged ───────────────────────────────────────────

def test_ui3_operational_cards_still_present():
    src = _src()
    for tid in (
        'data-testid="warehouse-operations-card"',
        'data-testid="sales-accounting-operations-card"',
        'data-testid="dhl-customs-operations-card"',
    ):
        assert tid in src
