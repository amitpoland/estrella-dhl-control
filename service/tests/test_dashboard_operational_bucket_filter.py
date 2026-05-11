"""tests/test_dashboard_operational_bucket_filter.py — UI-3.3

Source-grep tests for the clickable operational bucket filter that
binds the three UI-3.x cross-batch cards (warehouse, sales+accounting,
DHL+customs) to the active shipments table.

The implementation MUST:
  - hold the active operational filter in component state
    (`opFilter = null | { card, key, label }`);
  - apply both the existing status `filter` AND the operational
    predicate to the shipments table (AND semantics);
  - turn every bucket tile in every card into a <button> that
    toggles its (card, key) state on/off;
  - surface an active-filter chip with a clear control while a
    bucket is selected;
  - expose visual active marking via data-op-active="true|false"
    and aria-pressed on bucket buttons;
  - update the active-table empty state when an op filter is active;
  - introduce no new API calls, no write/execute actions, no
    multi-carrier wording.

Behaviour is documented in UI copy and pinned here via source-grep.
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


# ── opFilter state + predicate map ────────────────────────────────────────

def test_opfilter_state_declared():
    src = _src()
    assert "const [opFilter, setOpFilter]" in src, (
        "opFilter useState hook must be declared"
    )


def test_toggle_op_filter_handler_declared():
    src = _src()
    assert "const toggleOpFilter" in src


def test_clear_op_filter_handler_declared():
    src = _src()
    assert "const clearOpFilter" in src


def test_is_op_active_helper_declared():
    src = _src()
    assert "const isOpActive" in src


def test_op_predicates_map_declared():
    src = _src()
    assert "const OP_PREDICATES" in src


@pytest.mark.parametrize(
    "card", ["warehouse", "sales_accounting", "dhl_customs"],
)
def test_op_predicates_map_has_each_card(card):
    src = _src()
    # Map keys appear as `<card>:` followed by an object literal.
    assert f"{card}:" in src, (
        f"OP_PREDICATES must expose predicates for {card!r}"
    )


@pytest.mark.parametrize(
    "key",
    ["unknown", "awaiting", "partial_received", "in_warehouse", "reserved"],
)
def test_warehouse_predicate_key_present(key):
    src = _src()
    idx = src.find("warehouse:")
    sub = src[idx : idx + 1500]
    assert f"{key}:" in sub, (
        f"warehouse predicate key {key!r} missing from OP_PREDICATES"
    )


@pytest.mark.parametrize(
    "key",
    ["sales_ready", "sales_missing", "wfirma_preview",
     "wfirma_pending", "pz_done", "pz_pending"],
)
def test_sales_accounting_predicate_key_present(key):
    src = _src()
    idx = src.find("sales_accounting:")
    sub = src[idx : idx + 1500]
    assert f"{key}:" in sub, (
        f"sales_accounting predicate key {key!r} missing from OP_PREDICATES"
    )


@pytest.mark.parametrize(
    "key",
    ["awaiting_customs_docs", "sad_present", "sad_missing",
     "customs_cleared", "dhl_in_transit", "dhl_delivered"],
)
def test_dhl_customs_predicate_key_present(key):
    src = _src()
    idx = src.find("dhl_customs:")
    sub = src[idx : idx + 2500]
    assert f"{key}:" in sub, (
        f"dhl_customs predicate key {key!r} missing from OP_PREDICATES"
    )


# ── Filter application ────────────────────────────────────────────────────

def test_base_filtered_anchor_present():
    src = _src()
    assert "const baseFiltered" in src, (
        "filter chain must split into baseFiltered (status) + filtered (op)"
    )


def test_filtered_applies_op_predicate():
    src = _src()
    assert "baseFiltered.filter(opPredicate)" in src, (
        "filtered must compose baseFiltered with opPredicate"
    )


def test_existing_status_filter_logic_preserved():
    """The original `filter === 'all' ? batches : batches.filter` flow
    must still exist (as the baseFiltered source)."""
    src = _src()
    assert "filter === 'all' ? batches : batches.filter(s => s.overall === filter)" in src


# ── Bucket tiles are clickable buttons ────────────────────────────────────

@pytest.mark.parametrize(
    "testid_template, card_name",
    [
        ("warehouse-operations-bucket-${key}",        "warehouse"),
        ("sales-accounting-operations-bucket-${key}", "sales_accounting"),
        ("dhl-customs-operations-bucket-${key}",      "dhl_customs"),
    ],
)
def test_bucket_tile_is_button(testid_template, card_name):
    src = _src()
    idx = src.find(testid_template)
    assert idx != -1, (
        f"bucket testid template {testid_template!r} missing"
    )
    # Walk backwards to find the element opening — must be `<button`.
    head = src[max(0, idx - 400) : idx]
    assert "<button" in head, (
        f"{card_name} bucket tile must be a <button> element"
    )


@pytest.mark.parametrize(
    "testid_template",
    [
        "warehouse-operations-bucket-${key}",
        "sales-accounting-operations-bucket-${key}",
        "dhl-customs-operations-bucket-${key}",
    ],
)
def test_bucket_tile_binds_toggle_handler(testid_template):
    src = _src()
    idx = src.find(testid_template)
    assert idx != -1
    snippet = src[idx : idx + 1200]
    assert "toggleOpFilter(" in snippet, (
        f"bucket tile {testid_template!r} must call toggleOpFilter()"
    )


@pytest.mark.parametrize(
    "testid_template, card_arg",
    [
        ("warehouse-operations-bucket-${key}",        "'warehouse'"),
        ("sales-accounting-operations-bucket-${key}", "'sales_accounting'"),
        ("dhl-customs-operations-bucket-${key}",      "'dhl_customs'"),
    ],
)
def test_bucket_tile_passes_correct_card_to_toggle(testid_template, card_arg):
    src = _src()
    idx = src.find(testid_template)
    snippet = src[idx : idx + 1200]
    assert f"toggleOpFilter({card_arg}, key," in snippet, (
        f"bucket tile {testid_template!r} must call "
        f"toggleOpFilter({card_arg}, key, …)"
    )


@pytest.mark.parametrize(
    "testid_template",
    [
        "warehouse-operations-bucket-${key}",
        "sales-accounting-operations-bucket-${key}",
        "dhl-customs-operations-bucket-${key}",
    ],
)
def test_bucket_tile_exposes_active_data_attribute(testid_template):
    src = _src()
    idx = src.find(testid_template)
    snippet = src[idx : idx + 1200]
    assert "data-op-active=" in snippet, (
        f"bucket tile {testid_template!r} must expose data-op-active"
    )


@pytest.mark.parametrize(
    "testid_template",
    [
        "warehouse-operations-bucket-${key}",
        "sales-accounting-operations-bucket-${key}",
        "dhl-customs-operations-bucket-${key}",
    ],
)
def test_bucket_tile_exposes_aria_pressed(testid_template):
    src = _src()
    idx = src.find(testid_template)
    snippet = src[idx : idx + 1200]
    assert "aria-pressed={active}" in snippet, (
        f"bucket tile {testid_template!r} must expose aria-pressed"
    )


# ── Active-filter chip + clear control ────────────────────────────────────

def test_active_chip_testid_present():
    src = _src()
    assert 'data-testid="op-filter-active-chip"' in src


def test_active_chip_label_testid_present():
    src = _src()
    assert 'data-testid="op-filter-active-label"' in src


def test_clear_btn_testid_present():
    src = _src()
    assert 'data-testid="op-filter-clear-btn"' in src


def test_active_chip_only_renders_when_op_filter_set():
    """The active chip must be conditional on `opFilter` being truthy."""
    src = _src()
    idx = src.find('data-testid="op-filter-active-chip"')
    assert idx != -1
    head = src[max(0, idx - 400) : idx]
    assert "opFilter" in head, (
        "active chip must be guarded by an opFilter conditional"
    )


def test_active_chip_documents_and_semantics():
    """UI copy must explain AND semantics so operators aren't surprised."""
    src = _src()
    idx = src.find('data-testid="op-filter-active-chip"')
    snippet = src[idx : idx + 1500]
    assert "combined AND with the status filter above" in snippet, (
        "active chip must state AND-combination with the status filter"
    )


def test_clear_btn_invokes_clear_op_filter():
    src = _src()
    idx = src.find('data-testid="op-filter-clear-btn"')
    assert idx != -1
    snippet = src[idx : idx + 600]
    assert "onClick={clearOpFilter}" in snippet, (
        "clear control must invoke clearOpFilter"
    )


def test_active_chip_carries_card_and_key_data_attrs():
    src = _src()
    idx = src.find('data-testid="op-filter-active-chip"')
    snippet = src[idx : idx + 800]
    assert "data-op-card={opFilter.card}" in snippet
    assert "data-op-key={opFilter.key}" in snippet


# ── Empty state in active shipments table ─────────────────────────────────

def test_active_table_empty_state_testid_present():
    src = _src()
    assert 'data-testid="active-table-empty-state"' in src


def test_active_table_empty_state_mentions_op_filter_when_active():
    src = _src()
    assert 'data-testid="active-table-empty-op-filter-note"' in src


def test_active_table_empty_state_has_inline_clear_link():
    """Operators stuck in an empty result set must have a one-click
    clear pathway from inside the empty state."""
    src = _src()
    idx = src.find('data-testid="active-table-empty-op-filter-note"')
    assert idx != -1
    snippet = src[idx : idx + 800]
    assert "onClick={clearOpFilter}" in snippet, (
        "empty-state op-filter note must offer a clear-filter link"
    )


# ── Read-only / no-write discipline ───────────────────────────────────────

def test_no_new_apifetch_in_op_filter_regions():
    """UI-3.3 must NOT introduce apiFetch in the new handler region,
    predicate map, active chip, or empty-state additions."""
    src = _src()
    for anchor, span in (
        # UI-3.4: OP_PREDICATES lifted to module scope; narrow window
        # to the predicate map itself (declaration through closing brace).
        ("const OP_PREDICATES",            2800),
        ("const toggleOpFilter",            600),
        ("const clearOpFilter",             400),
        ("const isOpActive",                400),
        ('data-testid="op-filter-active-chip"', 1500),
        ('data-testid="active-table-empty-op-filter-note"', 800),
    ):
        idx = src.find(anchor)
        assert idx != -1, f"anchor {anchor!r} missing"
        snippet = src[idx : idx + span]
        assert "apiFetch" not in snippet, (
            f"apiFetch leaked into UI-3.3 region near {anchor!r}"
        )
        assert "fetch(" not in snippet, (
            f"raw fetch() leaked into UI-3.3 region near {anchor!r}"
        )


def test_existing_archive_apifetch_preserved():
    """Pre-existing archive load remains."""
    src = _src()
    assert "apiFetch('/dashboard/archive')" in src


def test_handlers_do_not_call_fetch_or_apifetch():
    """toggleOpFilter / clearOpFilter / isOpActive must be pure
    client-state mutators."""
    src = _src()
    for handler in ("const toggleOpFilter", "const clearOpFilter",
                    "const isOpActive"):
        idx = src.find(handler)
        assert idx != -1
        snippet = src[idx : idx + 600]
        assert "apiFetch" not in snippet
        assert "fetch(" not in snippet


@pytest.mark.parametrize(
    "forbidden_text",
    [">Reply<", ">Send<", ">Forward<", ">Resolve<",
     ">Customs<", ">Execute<", ">Mark printed<"],
)
def test_no_write_action_text_added_near_bucket_buttons(forbidden_text):
    """Bucket buttons must remain pure filter toggles, not action
    handles."""
    src = _src()
    for needle in (
        "warehouse-operations-bucket-${key}",
        "sales-accounting-operations-bucket-${key}",
        "dhl-customs-operations-bucket-${key}",
    ):
        idx = src.find(needle)
        assert idx != -1
        snippet = src[idx : idx + 1500]
        assert forbidden_text not in snippet, (
            f"bucket tile near {needle!r} must not introduce {forbidden_text!r}"
        )


# ── Triptych preservation ─────────────────────────────────────────────────

def test_ui_3_1b_warehouse_card_preserved():
    src = _src()
    assert 'data-testid="warehouse-operations-card"' in src
    assert "const xbatchLifecycleLabel" in src


def test_ui_3_2a_sales_accounting_card_preserved():
    src = _src()
    assert 'data-testid="sales-accounting-operations-card"' in src
    assert "const acctBucketLabel" in src


def test_ui_3_2b_dhl_customs_card_preserved():
    src = _src()
    assert 'data-testid="dhl-customs-operations-card"' in src
    assert "const dcBucketLabel" in src


def test_ui_3_1a_per_batch_badge_preserved():
    src = _src()
    assert 'data-testid="warehouse-inventory-lifecycle-badge"' in src
    assert "const lifecycleLabel" in src


# ── Existing dashboard primitives preserved ───────────────────────────────

@pytest.mark.parametrize(
    "preserved",
    [
        # Status filter row still present.
        "const filters = ['all', 'Ready for PZ', 'Awaiting DHL',",
        # Sort logic preserved.
        "const sorted = [...filtered].sort(",
        # View mode toggle preserved.
        '⊘ Archived',
        '● Active',
        # Active shipments table block opener preserved.
        '{/* ── Active shipments table ── */}',
    ],
)
def test_dashboard_primitives_preserved(preserved):
    src = _src()
    assert preserved in src, (
        f"existing dashboard primitive {preserved!r} removed by UI-3.3"
    )


# ── Scope discipline ──────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "forbidden",
    ["FedEx IP", "FedEx Priority", "UPS Worldwide", "Estrella Atlas"],
)
def test_no_out_of_scope_carrier_wording_added(forbidden):
    """Whole-file: introducing multi-carrier wording is a regression."""
    src = _src()
    # Allow the pre-existing baseline. Tests in prior UI-3.x phases
    # already pinned the per-block absence; this test confirms that
    # UI-3.3 did not introduce these terms into the new chip / handler
    # blocks. We constrain to the new code regions.
    chip_idx     = src.find('data-testid="op-filter-active-chip"')
    handlers_idx = src.find("const toggleOpFilter")
    pred_idx     = src.find("const OP_PREDICATES")
    for anchor in (chip_idx, handlers_idx, pred_idx):
        assert anchor != -1
        snippet = src[anchor : anchor + 4000]
        assert forbidden not in snippet, (
            f"forbidden term {forbidden!r} leaked into UI-3.3 region"
        )


# ── Brace balance / file sanity ───────────────────────────────────────────

def test_dashboard_html_braces_balanced():
    src = _src()
    opens = src.count("{")
    closes = src.count("}")
    assert opens == closes, f"unbalanced braces: {{={opens} }}={closes}"
