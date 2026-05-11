"""tests/test_dashboard_pipeline_summary_panel.py — UI-3.4

Source-grep tests for the read-only Per-Batch Pipeline Summary panel
on BatchDetailPage overview tab. The panel mirrors the cross-batch
operational triptych (warehouse / sales+accounting / DHL+customs) at
single-batch scope.

The panel MUST:
  - render only on the Overview tab;
  - derive purely from existing per-batch data (audit.*,
    warehouseAudit.summary.*, batchReadiness.*) already loaded by
    BatchDetailPage — no new endpoint;
  - consume the shared module-scope helpers from UI-3.3a (OP_PREDICATES,
    ATTENTION_PREDICATES, deriveWarehouseLifecycle,
    WAREHOUSE_LIFECYCLE_LABEL) — no duplicate predicate logic;
  - expose stable data-testid landmarks for panel, three sections,
    and per-pill landmarks;
  - introduce no write surface (no apiFetch, no fetch, no <Btn>,
    no <form>, no execute / send / reply / export action);
  - introduce no FedEx / UPS / multi-carrier wording;
  - preserve all UI-3 cross-batch cards (UI-3.1a, UI-3.1b, UI-3.2a,
    UI-3.2b, UI-3.3 filter chip).
"""
from __future__ import annotations

from pathlib import Path

import pytest

_HERE     = Path(__file__).resolve()
_SVC_ROOT = _HERE.parent.parent
_DASH     = _SVC_ROOT / "app" / "static" / "dashboard.html"


def _src() -> str:
    if not _DASH.exists():
        pytest.skip("dashboard.html not found")
    return _DASH.read_text(encoding="utf-8")


_BLOCK_OPEN  = "UI-3.4: Per-Batch Pipeline Summary"
_BLOCK_CLOSE = "<MissingFunctionsMatrix />"


def _panel_block(src: str) -> str:
    start = src.find(_BLOCK_OPEN)
    end   = src.find(_BLOCK_CLOSE, start)
    assert start != -1, "UI-3.4 panel block opener not found"
    assert end != -1 and end > start, "UI-3.4 panel block close anchor not found"
    return src[start:end]


# ── Module-scope shared helpers exist and reachable ───────────────────────

def test_op_predicates_at_module_scope():
    """UI-3.4: OP_PREDICATES must be declared at module scope so
    BatchDetailPage can consume it without a re-declaration."""
    src = _src()
    # Find the declaration; must appear BEFORE function DashboardPage
    op_idx = src.find("const OP_PREDICATES")
    dp_idx = src.find("function DashboardPage(")
    bd_idx = src.find("function BatchDetailPage(")
    assert op_idx != -1
    assert dp_idx != -1
    assert bd_idx != -1
    assert op_idx < dp_idx, (
        "OP_PREDICATES must be declared at module scope ABOVE "
        "function DashboardPage so BatchDetailPage can reach it"
    )
    assert op_idx < bd_idx


def test_op_predicates_declared_exactly_once():
    """No drift via duplicate declaration."""
    src = _src()
    assert src.count("const OP_PREDICATES") == 1


def test_attention_predicates_declared_exactly_once():
    src = _src()
    assert src.count("const ATTENTION_PREDICATES") == 1


def test_derive_warehouse_lifecycle_declared_exactly_once():
    src = _src()
    assert src.count("const deriveWarehouseLifecycle") == 1


def test_warehouse_lifecycle_label_shared_declared():
    src = _src()
    assert "const WAREHOUSE_LIFECYCLE_LABEL" in src


# ── Panel landmark + placement ────────────────────────────────────────────

def test_panel_testid_present():
    src = _src()
    assert 'data-testid="pipeline-summary-panel"' in src


def test_panel_rendered_in_overview_tab():
    """Panel must live inside the Overview-tab JSX block."""
    src = _src()
    panel_idx = src.find('data-testid="pipeline-summary-panel"')
    assert panel_idx != -1
    # Walk back; the most recent `activeTab === 'Overview'` must precede.
    head = src[: panel_idx]
    overview_idx = head.rfind("activeTab === 'Overview'")
    assert overview_idx != -1, (
        "panel must be guarded by an activeTab === 'Overview' conditional"
    )


def test_panel_renders_between_readiness_card_and_matrix():
    src = _src()
    readiness_idx = src.find("<OverallReadinessCard")
    panel_idx     = src.find('data-testid="pipeline-summary-panel"')
    matrix_idx    = src.find("<MissingFunctionsMatrix />")
    assert readiness_idx != -1 and panel_idx != -1 and matrix_idx != -1
    assert readiness_idx < panel_idx < matrix_idx, (
        "panel must render between OverallReadinessCard and MissingFunctionsMatrix"
    )


# ── Three section landmarks ──────────────────────────────────────────────

@pytest.mark.parametrize(
    "section_testid",
    [
        "pipeline-summary-warehouse",
        "pipeline-summary-sales-accounting",
        "pipeline-summary-dhl-customs",
    ],
)
def test_section_testid_present(section_testid):
    src = _src()
    assert f'data-testid="{section_testid}"' in src


# ── Section pill landmarks ────────────────────────────────────────────────

@pytest.mark.parametrize(
    "pill_testid",
    [
        # Warehouse
        "pipeline-summary-warehouse-lifecycle-pill",
        "pipeline-summary-warehouse-packing-list-pill",
        # Sales + Accounting
        "pipeline-summary-sales-pill",
        "pipeline-summary-wfirma-pill",
        "pipeline-summary-pz-pill",
        # DHL + Customs
        "pipeline-summary-dhl-status-pill",
        "pipeline-summary-sad-pill",
    ],
)
def test_pill_testid_present(pill_testid):
    src = _src()
    assert f'data-testid="{pill_testid}"' in src


def test_panel_exposes_warehouse_readiness_pill_conditionally():
    """Readiness pill is conditional on batchReadiness.warehouse —
    the testid must still appear in source so tests can assert it
    when present."""
    src = _src()
    assert 'data-testid="pipeline-summary-warehouse-readiness-pill"' in src


def test_panel_exposes_mrn_pill_conditionally():
    src = _src()
    assert 'data-testid="pipeline-summary-mrn-pill"' in src


def test_panel_exposes_tracking_pill_conditionally():
    src = _src()
    assert 'data-testid="pipeline-summary-tracking-pill"' in src


# ── Attention pills wired to shared ATTENTION_PREDICATES ─────────────────

@pytest.mark.parametrize(
    "attention_testid, card_key",
    [
        ("pipeline-summary-warehouse-attention",        "warehouse"),
        ("pipeline-summary-sales-attention",            "sales_accounting"),
        ("pipeline-summary-dhl-attention",              "dhl_customs"),
    ],
)
def test_attention_pill_present_and_wired_to_shared_predicate(attention_testid, card_key):
    """Each attention pill must:
    (a) carry its data-testid;
    (b) be rendered under a guard that calls ATTENTION_PREDICATES.<card>."""
    src = _src()
    block = _panel_block(src)
    assert f'data-testid="{attention_testid}"' in block, (
        f"attention pill testid {attention_testid!r} missing"
    )
    # The guard variable assignment must reference ATTENTION_PREDICATES.<card_key>
    assert f"ATTENTION_PREDICATES.{card_key}" in block, (
        f"attention condition must call ATTENTION_PREDICATES.{card_key}"
    )


# ── Shared helper consumption ────────────────────────────────────────────

def test_panel_uses_shared_derive_warehouse_lifecycle():
    src = _src()
    block = _panel_block(src)
    assert "deriveWarehouseLifecycle(pipelineRow)" in block, (
        "panel must call shared deriveWarehouseLifecycle"
    )


def test_panel_uses_shared_warehouse_lifecycle_label():
    src = _src()
    block = _panel_block(src)
    assert "WAREHOUSE_LIFECYCLE_LABEL[" in block, (
        "panel must look up shared WAREHOUSE_LIFECYCLE_LABEL"
    )


def test_panel_uses_shared_pz_done_labels_set():
    """The PZ pill colour decision must consult shared PZ_DONE_LABELS,
    not a local re-statement."""
    src = _src()
    block = _panel_block(src)
    assert "PZ_DONE_LABELS.has(" in block


def test_panel_uses_shared_track_attention_set():
    src = _src()
    block = _panel_block(src)
    assert "TRACK_ATTENTION.has(" in block


def test_panel_reuses_existing_status_mappers():
    """Existing mapPzStatus / mapDhlStatus / mapSadStatus are reused —
    no new mapper invented."""
    src = _src()
    block = _panel_block(src)
    assert "mapPzStatus("  in block
    assert "mapDhlStatus(" in block
    assert "mapSadStatus(" in block


# ── No duplicate predicate logic ─────────────────────────────────────────

@pytest.mark.parametrize(
    "duplicate_anchor",
    [
        # If anyone re-declares OP_PREDICATES near the panel.
        "const OP_PREDICATES = {",
        # If anyone re-declares ATTENTION_PREDICATES near the panel.
        "const ATTENTION_PREDICATES = {",
        # If anyone re-declares the warehouse lifecycle key list.
        "const WAREHOUSE_LIFECYCLE_KEYS = [",
        # If anyone inlines the shared sets near the panel.
        "new Set(['Generated', 'Exported'])",
        "new Set(['uploaded_parsed'",
        "new Set(['exception', 'customs'])",
        "new Set(['dhl_email_received'",
    ],
)
def test_no_duplicate_predicate_logic_in_panel_block(duplicate_anchor):
    src = _src()
    block = _panel_block(src)
    assert duplicate_anchor not in block, (
        f"duplicate predicate logic {duplicate_anchor!r} inside panel block — "
        "must reuse shared module-scope helpers, not re-declare"
    )


# ── Read-only discipline ─────────────────────────────────────────────────

def test_panel_block_does_not_call_apifetch():
    src = _src()
    block = _panel_block(src)
    assert "apiFetch" not in block, (
        "Pipeline Summary panel must not introduce new apiFetch calls"
    )


def test_panel_block_does_not_call_raw_fetch():
    src = _src()
    block = _panel_block(src)
    assert "fetch(" not in block


def test_panel_block_has_no_btn_component():
    src = _src()
    block = _panel_block(src)
    assert "<Btn" not in block, (
        "Pipeline Summary panel must not introduce <Btn> actions"
    )


def test_panel_block_has_no_form_or_input():
    src = _src()
    block = _panel_block(src)
    for forbidden in ("<input", "<form", "<select", "<textarea"):
        assert forbidden not in block, (
            f"Pipeline Summary panel must not contain {forbidden!r}"
        )


def test_panel_block_has_no_write_action_button_text():
    src = _src()
    block = _panel_block(src)
    for forbidden in (
        ">Reply<", ">Send<", ">Forward<", ">Resolve<",
        ">Export<", ">Create<", ">Adopt<", ">Generate<",
        ">Re-send<",
    ):
        assert forbidden not in block, (
            f"Pipeline Summary panel must not introduce {forbidden!r}"
        )


def test_panel_block_does_not_reference_execute_endpoints():
    src = _src()
    block = _panel_block(src)
    for forbidden in (
        "/api/v1/dhl/",
        "/api/v1/customs/",
        "/api/v1/agency/",
        "/api/v1/carrier/actions/",
        "/api/v1/wfirma/",
        "/api/v1/pz/process",
        "/api/v1/proforma/",
        "/execute", "/send-reply", "/send-initial",
        "/proactive-dispatch", "/adopt-issued",
    ):
        assert forbidden not in block, (
            f"Pipeline Summary panel must not reference {forbidden!r}"
        )


def test_panel_block_carries_read_only_disclaimer():
    src = _src()
    block = _panel_block(src)
    assert "Read-only" in block, (
        "panel must disclose its read-only nature"
    )


# ── Scope discipline — DHL Express only, no multi-carrier leakage ────────

@pytest.mark.parametrize(
    "forbidden",
    ["FedEx IP", "FedEx Priority", "UPS Worldwide", "Estrella Atlas",
     "Shipping Operations"],
)
def test_panel_block_no_out_of_scope_carriers(forbidden):
    src = _src()
    block = _panel_block(src)
    assert forbidden not in block, (
        f"out-of-scope carrier copy {forbidden!r} leaked into "
        "Pipeline Summary panel"
    )


# ── data-* attributes for downstream tooling ─────────────────────────────

@pytest.mark.parametrize(
    "section_anchor, data_attr",
    [
        ("pipeline-summary-warehouse-lifecycle-pill", "data-lifecycle-state="),
        ("pipeline-summary-sales-pill",               "data-sales-hint="),
        ("pipeline-summary-wfirma-pill",              "data-wfirma-hint="),
        ("pipeline-summary-pz-pill",                  "data-pz-status="),
        ("pipeline-summary-dhl-status-pill",          "data-dhl-status="),
        ("pipeline-summary-sad-pill",                 "data-sad-status="),
        ("pipeline-summary-sad-pill",                 "data-has-sad="),
    ],
)
def test_pill_exposes_data_attribute(section_anchor, data_attr):
    src = _src()
    idx = src.find(f'data-testid="{section_anchor}"')
    assert idx != -1, f"pill {section_anchor!r} missing"
    # Forward window covers the open <span> attributes.
    snippet = src[idx : idx + 600]
    assert data_attr in snippet, (
        f"pill {section_anchor!r} must expose {data_attr!r}"
    )


# ── UI-3 preservation ────────────────────────────────────────────────────

def test_ui_3_1a_per_batch_badge_preserved():
    src = _src()
    assert 'data-testid="warehouse-inventory-lifecycle-badge"' in src
    assert "const lifecycleLabel" in src


def test_ui_3_1b_warehouse_card_preserved():
    src = _src()
    assert 'data-testid="warehouse-operations-card"' in src
    assert 'data-testid="warehouse-operations-buckets"' in src
    assert "const xbatchLifecycleLabel" in src


def test_ui_3_2a_sales_accounting_card_preserved():
    src = _src()
    assert 'data-testid="sales-accounting-operations-card"' in src
    assert "const acctBucketLabel" in src


def test_ui_3_2b_dhl_customs_card_preserved():
    src = _src()
    assert 'data-testid="dhl-customs-operations-card"' in src
    assert "const dcBucketLabel" in src


def test_ui_3_3_active_filter_chip_preserved():
    src = _src()
    assert 'data-testid="op-filter-active-chip"' in src
    assert 'data-testid="op-filter-clear-btn"' in src


# ── Existing BatchDetailPage primitives preserved ────────────────────────

@pytest.mark.parametrize(
    "preserved",
    [
        "const DETAIL_TABS",
        "<BatchControlCenter",
        "<OverallReadinessCard",
        "<MissingFunctionsMatrix />",
        "<EmailEvidenceTimeline",
        "loadWarehouseAudit",
    ],
)
def test_batch_detail_landmarks_preserved(preserved):
    src = _src()
    assert preserved in src, (
        f"existing BatchDetailPage landmark {preserved!r} removed by UI-3.4"
    )


# ── Brace balance / file sanity ──────────────────────────────────────────

def test_dashboard_html_braces_balanced():
    src = _src()
    opens = src.count("{")
    closes = src.count("}")
    assert opens == closes, f"unbalanced braces: {{={opens} }}={closes}"
