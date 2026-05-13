"""
test_dashboard_automation_design.py — Path B / Pass 7.

Contract for the Automation page (AiBridgePage) design pass:
  - Live AI-bridge task / result / error / template surfaces remain the
    ONLY real data source
  - Real /api/v1/ai-bridge endpoints preserved
  - Live KPI strip derives counts from real task arrays (no fake counts)
  - Design-preview strip (Avg-latency KPI, Token-spend KPI, Capabilities
    tab, Prompt Templates editor tab) is visually marked and disabled
  - Preview controls emit NO network calls and NO state changes
  - No mock task ids, no mock task types/inputs/models, no mock template
    names introduced
  - No invented /api/v1/ai-bridge endpoints
  - Existing create-task + import-result + view-json + tab handlers
    unchanged and still call the real endpoints
"""
from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SVC_ROOT = _HERE.parent
_DASH = _SVC_ROOT / "app" / "static" / "dashboard.html"


def _src() -> str:
    if not _DASH.exists():
        import pytest
        pytest.skip(f"dashboard.html not found at {_DASH}")
    return _DASH.read_text(encoding="utf-8")


# ── Live AI-bridge endpoints preserved ─────────────────────────────────────

def test_aibridge_component_present():
    assert "function AiBridgePage({ onToast })" in _src()


def test_automation_route_wired():
    src = _src()
    assert "page === 'automation'" in src
    assert "<AiBridgePage" in src


def test_aibridge_load_endpoints_intact():
    src = _src()
    # Parallel load of pending / processed / templates / errors
    assert "apiFetch('/api/v1/ai-bridge/tasks?status=pending')" in src
    assert "apiFetch('/api/v1/ai-bridge/tasks?status=processed')" in src
    assert "apiFetch('/api/v1/ai-bridge/templates')" in src
    assert "apiFetch('/api/v1/ai-bridge/errors')" in src


def test_aibridge_create_endpoint_intact():
    src = _src()
    # Create task is POST /api/v1/ai-bridge/tasks/{batch_id}
    assert "/api/v1/ai-bridge/tasks/${encodeURIComponent(newBatch.trim())}" in src
    # Wrapped in createTask handler with confirm-free but state-guarded body
    assert "const createTask = async () =>" in src


def test_aibridge_import_result_endpoint_intact():
    src = _src()
    # POST /api/v1/ai-bridge/results/{task_id}
    assert "/api/v1/ai-bridge/results/${encodeURIComponent(task.task_id)}" in src
    assert "const importResult = async (task) =>" in src


def test_aibridge_view_result_json_endpoint_intact():
    src = _src()
    # GET /api/v1/ai-bridge/results/{task_id}
    assert "/api/v1/ai-bridge/results/${encodeURIComponent(tid)}" in src


# ── Live KPI strip uses real task arrays ──────────────────────────────────

def test_live_stats_strip_present():
    src = _src()
    assert 'data-testid="automation-live-stats"' in src
    for sid in ("pending", "processed", "rejected", "types"):
        assert f'data-testid={{`automation-stat-${{s.id}}`}}' in src or \
               f'data-testid="automation-stat-{sid}"' in src
    # Ids referenced in source array
    for sid in ("'pending'", "'processed'", "'rejected'", "'types'"):
        assert f"id: {sid}" in src, f"Missing live stat id in source: {sid}"


def test_live_stats_derive_from_real_arrays():
    src = _src()
    # Counts come from the real state arrays, not literal numbers
    assert "pending:   tasks.length" in src
    assert "processed: processed.length" in src
    assert "rejected:  errors.length" in src
    assert "types:     Object.keys(templates).length" in src


def test_live_stats_loading_state():
    src = _src()
    # The number slot renders "…" while loading, the real value when loaded
    assert "{loading ? '…' : s.value}" in src


# ── Design preview strip present and marked ────────────────────────────────

def test_automation_preview_strip_present():
    assert 'data-testid="automation-design-preview"' in _src()


def test_automation_preview_has_pending_badge():
    assert 'data-testid="automation-preview-pending-badge"' in _src()


def test_automation_preview_kpis_present():
    src = _src()
    assert 'data-testid="automation-preview-kpis"' in src
    assert 'data-testid={`automation-preview-kpi-${c.id}`}' in src
    for kid in ("'avg_latency'", "'token_spend'"):
        assert f"id: {kid}" in src, f"Missing preview KPI id: {kid}"


def test_automation_preview_tabs_present():
    src = _src()
    assert 'data-testid="automation-preview-tabs"' in src
    assert 'data-testid={`automation-preview-tab-${t.id}`}' in src
    for tid in ("'capabilities'", "'templates'"):
        assert f"id: {tid}" in src, f"Missing preview tab id: {tid}"


# ── Preview controls disabled / non-executable ─────────────────────────────

def test_preview_buttons_disabled():
    src = _src()
    block_start = src.index('data-testid="automation-design-preview"')
    block_end   = src.index('Create task panel', block_start)
    block = src[block_start:block_end]
    assert block.count('disabled') >= 2
    assert 'aria-disabled="true"' in block
    assert "cursor: 'not-allowed'" in block


def test_preview_buttons_no_onclick_no_fetch():
    src = _src()
    block_start = src.index('data-testid="automation-design-preview"')
    block_end   = src.index('Create task panel', block_start)
    block = src[block_start:block_end]
    assert 'onClick' not in block, "Preview button must NOT have onClick"
    assert 'apiFetch' not in block, "Preview block must NOT call apiFetch"
    assert 'fetch(' not in block,   "Preview block must NOT call fetch()"
    assert 'dispatchEvent' not in block


def test_preview_marked_pending_via_data_attr():
    src = _src()
    block_start = src.index('data-testid="automation-design-preview"')
    block_end   = src.index('Create task panel', block_start)
    block = src[block_start:block_end]
    # KPI cards + tab buttons each carry data-pending="true"
    assert block.count('data-pending="true"') >= 2


def test_preview_kpis_show_em_dash_not_fake_number():
    src = _src()
    block_start = src.index('data-testid="automation-preview-kpis"')
    block_end   = src.index('Create task panel', block_start)
    block = src[block_start:block_end]
    assert '>—</div>' in block


# ── Anti-fake: no mock task / result / template data ───────────────────────

def test_no_mock_task_ids():
    src = _src()
    # Design fixture task IDs from pages-v2.jsx
    for fake in ("T-8842", "T-8841", "T-8840", "T-8839", "T-8838",
                 "T-8837", "T-8836", "T-8835"):
        assert fake not in src, f"Mock task id leaked: {fake}"


def test_no_mock_task_inputs_or_models():
    src = _src()
    # Design mock fixtures
    for fake in (
        "em-872",
        "DHL-7733991122",
        "DHL-2244668800",
        "inv-2294 · 12 lines",
        "sad-pdf-447.pdf",
        "PZ/2024/000891",
        "batch:DHL-april",
        "inv-2293.pdf",
        "MRN regex match failed; needs human review",
        "haiku-4-5",
        "sonnet-4-5",
    ):
        assert fake not in src, f"Mock task input/model leaked: {fake}"


def test_no_mock_capability_definitions():
    src = _src()
    # Design fixture capability ids that don't exist in our backend
    for fake in (
        "classify_email", "generate_dsk", "translate_pl",
        "parse_sad",     "reconcile_pz", "classify_invoice",
        "propose_action", "verify_carnet",
    ):
        # These specific strings are part of the design mock surface for
        # the Capabilities tab. None should land in dashboard.html.
        assert fake not in src, f"Mock capability id leaked: {fake}"


def test_no_mock_template_names():
    src = _src()
    # Design template version names — none should land
    for fake in (
        "classify_email.v3", "generate_dsk.v2", "translate_pl.v4",
        "parse_sad.v2", "reconcile_pz.v1", "propose_action.v1",
    ):
        assert fake not in src, f"Mock template name leaked: {fake}"


def test_no_fake_latency_or_spend_values():
    src = _src()
    block_start = src.index('data-testid="automation-design-preview"')
    block_end   = src.index('Create task panel', block_start)
    block = src[block_start:block_end]
    for fake in ("2.4s", "p95 6.8s", "$4.82", "$20/day", "271 success", "8 errors"):
        assert fake not in block, f"Mock telemetry value leaked: {fake}"


# ── Anti-fake: no invented endpoints ───────────────────────────────────────

def test_no_invented_aibridge_endpoints():
    src = _src()
    for ep in (
        "/api/v1/ai-bridge/capabilities",
        "/api/v1/ai-bridge/templates/edit",
        "/api/v1/ai-bridge/metrics/latency",
        "/api/v1/ai-bridge/metrics/spend",
        "/api/v1/ai-bridge/metrics/today",
        "/api/v1/ai-bridge/retry",
    ):
        assert ep not in src, f"Invented AI Bridge endpoint leaked: {ep}"


# ── Existing handlers + guards preserved ───────────────────────────────────

def test_create_task_handler_intact():
    src = _src()
    # Create button is disabled while creating OR when batch field empty
    assert "disabled={creating || !newBatch.trim()}" in src
    # Real validation guard
    assert "if (!newBatch.trim()) { onToast('Batch ID is required', 'error'); return; }" in src


def test_import_result_handler_intact():
    src = _src()
    # Import result still prompts operator for status / event / location
    assert "Enter tracking status" in src
    # And POSTs to the real endpoint
    assert "/api/v1/ai-bridge/results/${encodeURIComponent(task.task_id)}" in src


def test_view_result_json_handler_intact():
    src = _src()
    # View JSON expand still calls real GET endpoint and caches in jsonData
    assert "setJsonData(p => ({ ...p, [tid]: d }))" in src


def test_safety_note_preserved():
    src = _src()
    # The "AI Bridge results may only update non-financial audit fields"
    # safety footer must remain — it's a real audit-integrity invariant.
    assert "AI Bridge results may only update non-financial audit fields" in src
    assert "clearance_decision" in src
    assert "duty, vat, invoice_totals" in src


# ── SectionLabel polish + page landmarks ───────────────────────────────────

def test_page_landmark_present():
    src = _src()
    assert 'data-testid="automation-page"' in src


def test_create_panel_landmark_present():
    src = _src()
    assert 'data-testid="automation-create-panel"' in src


def test_tabs_landmark_present():
    src = _src()
    assert 'data-testid="automation-tabs"' in src


def test_section_label_polish_applied():
    src = _src()
    # SectionLabel components wrap the two main sections of the live page
    assert "<SectionLabel>Create new task</SectionLabel>" in src
    assert "<SectionLabel>Task queue</SectionLabel>" in src


# ── UI-3 landmarks unchanged ───────────────────────────────────────────────

def test_ui3_operational_cards_still_present():
    src = _src()
    for tid in (
        'data-testid="warehouse-operations-card"',
        'data-testid="sales-accounting-operations-card"',
        'data-testid="dhl-customs-operations-card"',
    ):
        assert tid in src


def test_detail_tabs_unchanged():
    src = _src()
    assert "const DETAIL_TABS = ['Overview', 'Documents', 'DHL / Customs', 'Warehouse', 'Sales', 'PZ / Accounting', 'Timeline', 'Intelligence', 'Proposals']" in src
