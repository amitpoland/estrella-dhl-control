"""tests/test_dashboard_pipeline_summary_navigation.py — UI-3.5

Source-grep tests for the clickable navigation behaviour added to the
Per-Batch Pipeline Summary pills. Each pill becomes a <button> that
calls the existing setActiveTab setter on BatchDetailPage to jump to
the relevant existing tab.

The implementation MUST:
  - turn every pill in the Pipeline Summary panel into a <button>
    element with type="button";
  - bind onClick to setActiveTab('<existing-tab-name>') where the
    target tab matches one of the existing DETAIL_TABS entries;
  - expose data-nav-target=<TabName> on each pill so tests + downstream
    tooling can verify the wiring without parsing onClick handlers;
  - carry an aria-label that mentions the target tab for screen readers;
  - keep all UI-3.4 testid landmarks intact;
  - introduce no new endpoints, no apiFetch, no write/execute/send/
    reply/export-direct actions;
  - introduce no new tab name; every target must be one of DETAIL_TABS.
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


# ── DETAIL_TABS — the only allowed navigation targets ────────────────────

EXISTING_TABS = {
    'Overview', 'Documents', 'DHL / Customs', 'Warehouse', 'Sales',
    'PZ / Accounting', 'Timeline', 'Intelligence', 'Proposals', 'DHL Express',
}


def test_detail_tabs_constant_unchanged():
    """UI-3.5 must NOT introduce a new tab name. The existing
    DETAIL_TABS literal must remain byte-identical."""
    src = _src()
    expected = (
        "const DETAIL_TABS = ['Overview', 'Documents', 'DHL / Customs', "
        "'Warehouse', 'Sales', 'PZ / Accounting', 'Timeline', 'Intelligence', "
        "'Proposals'];"
    )
    assert expected in src, (
        "DETAIL_TABS must remain unchanged; UI-3.5 must not introduce a new tab"
    )


# ── Each pill is a clickable button ──────────────────────────────────────

PILL_TARGETS = [
    # (testid, expected target tab)
    ("pipeline-summary-warehouse-lifecycle-pill",      "Warehouse"),
    ("pipeline-summary-warehouse-readiness-pill",      "Warehouse"),
    ("pipeline-summary-warehouse-packing-list-pill",   "Warehouse"),
    ("pipeline-summary-warehouse-attention",           "Warehouse"),
    ("pipeline-summary-sales-pill",                    "Sales"),
    ("pipeline-summary-wfirma-pill",                   "PZ / Accounting"),
    ("pipeline-summary-pz-pill",                       "PZ / Accounting"),
    ("pipeline-summary-sales-attention",               "Sales"),
    ("pipeline-summary-dhl-status-pill",               "DHL / Customs"),
    ("pipeline-summary-sad-pill",                      "DHL / Customs"),
    ("pipeline-summary-mrn-pill",                      "DHL / Customs"),
    ("pipeline-summary-tracking-pill",                 "DHL / Customs"),
    ("pipeline-summary-dhl-attention",                 "DHL / Customs"),
]


@pytest.mark.parametrize("testid, target_tab", PILL_TARGETS)
def test_pill_is_button(testid, target_tab):
    src = _src()
    idx = src.find(f'data-testid="{testid}"')
    assert idx != -1, f"pill testid {testid!r} missing"
    # The element opening lives ABOVE the testid; walk back ≤ 200 chars
    # and confirm it's a <button.
    head = src[max(0, idx - 200) : idx]
    assert "<button" in head, (
        f"pill {testid!r} must be a <button> element"
    )
    assert 'type="button"' in head, (
        f"pill {testid!r} must declare type=\"button\""
    )


@pytest.mark.parametrize("testid, target_tab", PILL_TARGETS)
def test_pill_target_via_data_attr(testid, target_tab):
    """Each pill exposes data-nav-target=<TabName> so the wiring is
    introspectable without parsing onClick."""
    src = _src()
    idx = src.find(f'data-testid="{testid}"')
    assert idx != -1
    # Forward window covers the rest of the open tag.
    snippet = src[idx : idx + 800]
    assert f'data-nav-target="{target_tab}"' in snippet, (
        f"pill {testid!r} must expose data-nav-target=\"{target_tab}\""
    )


@pytest.mark.parametrize("testid, target_tab", PILL_TARGETS)
def test_pill_onClick_calls_setActiveTab_with_target(testid, target_tab):
    """The onClick handler must call setActiveTab('<target>')."""
    src = _src()
    idx = src.find(f'data-testid="{testid}"')
    assert idx != -1
    snippet = src[idx : idx + 800]
    needle = f"setActiveTab('{target_tab}')"
    assert needle in snippet, (
        f"pill {testid!r} must call {needle}"
    )


@pytest.mark.parametrize("testid, target_tab", PILL_TARGETS)
def test_pill_aria_label_mentions_target(testid, target_tab):
    """Accessible label must mention the target tab so screen-reader
    users know where they'll land."""
    src = _src()
    idx = src.find(f'data-testid="{testid}"')
    assert idx != -1
    snippet = src[idx : idx + 800]
    assert "aria-label=" in snippet, (
        f"pill {testid!r} must carry aria-label"
    )
    assert f"open {target_tab} tab" in snippet, (
        f"pill {testid!r} aria-label must mention {target_tab!r}"
    )


@pytest.mark.parametrize("testid, target_tab", PILL_TARGETS)
def test_pill_title_mentions_target(testid, target_tab):
    """Hover hint also points at the target tab."""
    src = _src()
    idx = src.find(f'data-testid="{testid}"')
    snippet = src[idx : idx + 800]
    assert f'title="Open {target_tab} tab"' in snippet, (
        f"pill {testid!r} must carry hover title for {target_tab!r}"
    )


@pytest.mark.parametrize("_testid, target_tab", PILL_TARGETS)
def test_pill_target_is_an_existing_tab(_testid, target_tab):
    """Sanity invariant — every navigation target must be one of
    DETAIL_TABS. Catches typos like 'PZ/wFirma' (missing spaces)."""
    assert target_tab in EXISTING_TABS, (
        f"target tab {target_tab!r} is not in DETAIL_TABS — "
        "UI-3.5 must not invent new tabs"
    )


# ── No span pills remain inside the Pipeline Summary panel ───────────────

@pytest.mark.parametrize("testid, _target", PILL_TARGETS)
def test_no_span_with_pill_testid_remains(testid, _target):
    """The conversion from <span> to <button> must be complete.
    A leftover <span data-testid="..."> would indicate a stale pill
    that isn't navigable."""
    src = _src()
    assert f'<span data-testid="{testid}"' not in src, (
        f"stale <span> with pill testid {testid!r} still present — "
        "pill conversion incomplete"
    )


# ── setActiveTab is the ONLY navigation mechanism used in the panel ──────

def test_panel_uses_setactivetab_only():
    """Navigation must go through the existing setActiveTab setter —
    no window.location, no history.push, no router calls."""
    src = _src()
    block = _panel_block(src)
    assert "setActiveTab(" in block, (
        "panel must use setActiveTab for navigation"
    )
    for forbidden in (
        "window.location", "history.push", "history.replaceState",
        "navigate(", "useNavigate", "Link to=",
    ):
        assert forbidden not in block, (
            f"panel must not use {forbidden!r} — only setActiveTab"
        )


# ── Read-only discipline (re-verified post-conversion) ───────────────────

def test_panel_block_does_not_call_apifetch():
    src = _src()
    block = _panel_block(src)
    assert "apiFetch" not in block, (
        "Pipeline Summary panel must not introduce apiFetch"
    )


def test_panel_block_does_not_call_raw_fetch():
    src = _src()
    block = _panel_block(src)
    assert "fetch(" not in block


def test_panel_block_has_no_form_or_input():
    src = _src()
    block = _panel_block(src)
    for forbidden in ("<input", "<form", "<select", "<textarea"):
        assert forbidden not in block


def test_panel_block_has_no_btn_component():
    """The React <Btn> primitive (capital-B) is for write/execute
    actions. Plain <button> tags are used for navigation, which is
    safe."""
    src = _src()
    block = _panel_block(src)
    assert "<Btn" not in block, (
        "panel must not introduce <Btn> primary actions"
    )


def test_panel_block_has_no_write_action_button_text():
    src = _src()
    block = _panel_block(src)
    for forbidden in (
        ">Reply<", ">Send<", ">Forward<", ">Resolve<",
        ">Export<", ">Create<", ">Adopt<", ">Generate<",
        ">Re-send<", ">Execute<", ">Submit<",
    ):
        assert forbidden not in block, (
            f"panel must not introduce {forbidden!r}"
        )


def test_panel_block_does_not_reference_execute_endpoints():
    src = _src()
    block = _panel_block(src)
    for forbidden in (
        "/api/v1/dhl/", "/api/v1/customs/", "/api/v1/agency/",
        "/api/v1/carrier/actions/", "/api/v1/wfirma/",
        "/api/v1/pz/process", "/api/v1/proforma/",
        "/execute", "/send-reply", "/send-initial",
        "/proactive-dispatch", "/adopt-issued",
    ):
        assert forbidden not in block, (
            f"panel must not reference {forbidden!r}"
        )


# ── UI-3.4 testid landmarks all preserved ────────────────────────────────

@pytest.mark.parametrize(
    "preserved_testid",
    [
        "pipeline-summary-panel",
        "pipeline-summary-warehouse",
        "pipeline-summary-sales-accounting",
        "pipeline-summary-dhl-customs",
        # All 13 pill testids must still exist (now on <button> elements)
        "pipeline-summary-warehouse-lifecycle-pill",
        "pipeline-summary-warehouse-readiness-pill",
        "pipeline-summary-warehouse-packing-list-pill",
        "pipeline-summary-warehouse-attention",
        "pipeline-summary-sales-pill",
        "pipeline-summary-wfirma-pill",
        "pipeline-summary-pz-pill",
        "pipeline-summary-sales-attention",
        "pipeline-summary-dhl-status-pill",
        "pipeline-summary-sad-pill",
        "pipeline-summary-mrn-pill",
        "pipeline-summary-tracking-pill",
        "pipeline-summary-dhl-attention",
    ],
)
def test_ui_3_4_pill_testids_preserved(preserved_testid):
    src = _src()
    assert f'data-testid="{preserved_testid}"' in src, (
        f"UI-3.4 pill testid {preserved_testid!r} removed by UI-3.5"
    )


# ── UI-3.4 data attributes all preserved ─────────────────────────────────

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
        ("pipeline-summary-tracking-pill",            "data-tracking-key="),
        ("pipeline-summary-warehouse-readiness-pill", "data-readiness-status="),
    ],
)
def test_ui_3_4_data_attributes_preserved(section_anchor, data_attr):
    src = _src()
    idx = src.find(f'data-testid="{section_anchor}"')
    assert idx != -1
    snippet = src[idx : idx + 800]
    assert data_attr in snippet, (
        f"UI-3.4 data attribute {data_attr!r} removed from {section_anchor!r}"
    )


# ── Scope discipline ─────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "forbidden",
    ["FedEx IP", "FedEx Priority", "UPS Worldwide", "Estrella Atlas"],
)
def test_panel_block_no_out_of_scope_carriers(forbidden):
    src = _src()
    block = _panel_block(src)
    assert forbidden not in block, (
        f"out-of-scope carrier copy {forbidden!r} leaked into panel"
    )


# ── Earlier UI-3 surface preservation ────────────────────────────────────

def test_ui_3_1b_warehouse_card_preserved():
    src = _src()
    assert 'data-testid="warehouse-operations-card"' in src


def test_ui_3_2a_sales_accounting_card_preserved():
    src = _src()
    assert 'data-testid="sales-accounting-operations-card"' in src


def test_ui_3_2b_dhl_customs_card_preserved():
    src = _src()
    assert 'data-testid="dhl-customs-operations-card"' in src


def test_ui_3_3_active_filter_chip_preserved():
    src = _src()
    assert 'data-testid="op-filter-active-chip"' in src


# ── Brace balance / file sanity ──────────────────────────────────────────

def test_dashboard_html_braces_balanced():
    src = _src()
    opens = src.count("{")
    closes = src.count("}")
    assert opens == closes, f"unbalanced braces: {{={opens} }}={closes}"
