"""tests/test_dashboard_warehouse_operations_card.py — UI-3.1b

Source-grep tests for the read-only cross-batch warehouse operations
card on DashboardPage. The card aggregates batch-list warehouse hints
into operator-readable lifecycle buckets and surfaces a "needs
attention" subset.

UI-3.1a's per-batch 7-state badge is preserved unchanged; this is the
cross-batch (5-state subset) complementary surface.

The card MUST:
  - render only in active view mode (no archive coupling);
  - derive purely from existing batch-list payload fields
    (warehouseHint, pzStatus, wfirmaHint, salesHint, awb, timestamp,
    doc_no, id) — no new endpoint, no allowlist change;
  - re-use the same label-map discipline as UI-3.1a;
  - expose stable data-testid landmarks + data-lifecycle-state keys;
  - introduce no write surface (no apiFetch, no fetch, no form,
    no execute action) beyond the existing onViewShipment navigation
    handler which is read-only;
  - introduce no carrier/multi-carrier wording.
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


_BLOCK_OPEN  = "UI-3.1b: cross-batch warehouse operations card"
_BLOCK_CLOSE = "{/* ── Archived view ── */}"


def _card_block(src: str) -> str:
    """Return the full UI-3.1b card block — from the section comment
    opener through to the next sibling section (archived view).
    This captures the const-declarations, the JSX, and nothing else."""
    start = src.find(_BLOCK_OPEN)
    end   = src.find(_BLOCK_CLOSE, start)
    assert start != -1, "UI-3.1b block opener not found"
    assert end   != -1 and end > start, "UI-3.1b block close anchor not found"
    return src[start:end]


# ── Card landmark + placement ─────────────────────────────────────────────

def test_card_testid_present():
    src = _src()
    assert 'data-testid="warehouse-operations-card"' in src


def test_card_only_renders_in_active_view():
    """The card must be conditionally guarded behind viewMode === 'active'
    so it doesn't pollute the archived view."""
    src = _src()
    block = _card_block(src)
    assert "viewMode === 'active'" in block, (
        "warehouse-operations-card must be gated on active view mode"
    )


def test_card_renders_before_active_shipments_table():
    """The card belongs above the active shipments table."""
    src = _src()
    card_idx  = src.find('data-testid="warehouse-operations-card"')
    table_idx = src.find('{/* ── Active shipments table ── */}')
    assert card_idx != -1 and table_idx != -1
    assert card_idx < table_idx, (
        "warehouse-operations-card must render above the active table"
    )


def test_card_renders_after_archived_view_block():
    """The card must NOT live inside the archived view block."""
    src = _src()
    archived_idx = src.find('{/* ── Archived view ── */}')
    card_idx     = src.find('data-testid="warehouse-operations-card"')
    assert archived_idx != -1 and card_idx != -1
    assert card_idx < archived_idx, (
        "warehouse-operations-card should sit before the archived block, "
        "not after it"
    )


# ── Bucket grid ────────────────────────────────────────────────────────────

def test_bucket_grid_landmark_present():
    src = _src()
    assert 'data-testid="warehouse-operations-buckets"' in src


def test_bucket_tile_uses_keyed_testid_template():
    """The bucket grid emits one tile per lifecycle key via a template
    testid pattern. The literal expanded form is runtime, but the
    template pattern must appear in source."""
    src = _src()
    block = _card_block(src)
    assert "warehouse-operations-bucket-${key}" in block, (
        "bucket tile must use the keyed testid template"
    )


@pytest.mark.parametrize(
    "key",
    ["awaiting", "partial_received", "in_warehouse", "reserved", "unknown"],
)
def test_bucket_grid_iterates_each_lifecycle_key(key):
    """The bucket-grid map iteration must include every lifecycle key
    so a tile gets emitted for every state."""
    src = _src()
    block = _card_block(src)
    # Find the bucket grid iteration anchor and confirm the key string
    # appears inside it.
    idx = block.find("warehouse-operations-buckets")
    assert idx != -1
    snippet = block[idx : idx + 1500]
    assert f"'{key}'" in snippet, (
        f"bucket-grid iteration array must include {key!r}"
    )


def test_bucket_tile_exposes_state_data_attribute():
    """Each bucket tile carries data-lifecycle-state for filter/test infra."""
    src = _src()
    block = _card_block(src)
    # The template is rendered once per key.
    idx = block.find("warehouse-operations-bucket-${key}")
    assert idx != -1
    snippet = block[idx : idx + 600]
    assert "data-lifecycle-state={key}" in snippet, (
        "bucket tile must expose data-lifecycle-state={key}"
    )


# ── Lifecycle label map — UI-3.1a discipline reused ───────────────────────

def test_lifecycle_label_map_anchor_present():
    src = _src()
    assert "const xbatchLifecycleLabel" in src, (
        "cross-batch lifecycle label map declaration missing"
    )


def test_lifecycle_tone_map_anchor_present():
    src = _src()
    assert "const xbatchLifecycleTone" in src, (
        "cross-batch lifecycle tone map declaration missing"
    )


def test_lifecycle_derivation_anchor_present():
    src = _src()
    assert "const xbatchDeriveLifecycle" in src, (
        "cross-batch lifecycle derivation function missing"
    )


@pytest.mark.parametrize(
    "key",
    ["unknown", "awaiting", "partial_received", "in_warehouse", "reserved"],
)
def test_lifecycle_state_key_declared(key):
    """All five technical cross-batch lifecycle keys must appear."""
    src = _src()
    block = _card_block(src)
    assert f"{key}:" in block or f"'{key}'" in block or f'"{key}"' in block, (
        f"cross-batch lifecycle key {key!r} missing"
    )


@pytest.mark.parametrize(
    "label",
    [
        "No packing list",
        "Awaiting receipt",
        "Partially received",
        "In warehouse",
        "Reserved (PZ created)",
    ],
)
def test_lifecycle_operator_label_present(label):
    """Operator-readable labels must appear in source — strings live
    in the label map so reviewers can grep them."""
    src = _src()
    block = _card_block(src)
    assert label in block, (
        f"operator-readable cross-batch lifecycle label {label!r} missing"
    )


def test_lifecycle_label_map_matches_ui_3_1a_for_shared_keys():
    """The five cross-batch labels must match UI-3.1a verbatim for the
    keys both maps share. Drift between the two surfaces would confuse
    operators."""
    src = _src()
    # UI-3.1a per-batch map (the original) is also in this file.
    assert "const lifecycleLabel" in src
    # Just confirm both source strings are present — UI-3.1a tests
    # already pin them at exact equality. If either changes, both
    # test files fail in unison.
    for label in (
        "No packing list",
        "Awaiting receipt",
        "Partially received",
        "In warehouse",
        "Reserved (PZ created)",
    ):
        # Each must appear at least twice — once in UI-3.1a map, once
        # in UI-3.1b map.
        assert src.count(label) >= 2, (
            f"label {label!r} must be shared verbatim between UI-3.1a "
            f"and UI-3.1b label maps (found {src.count(label)} occurrences)"
        )


def test_lifecycle_derivation_uses_existing_list_payload_fields():
    """Derivation must read only from row.warehouseHint + row.pzStatus
    — the two fields already present on every list row.

    UI-3.3a: the per-card xbatchDeriveLifecycle anchor is now a thin
    alias to the DashboardPage-scope `deriveWarehouseLifecycle` which
    consults OP_PREDICATES.warehouse. Both must reference the two
    payload fields somewhere in source."""
    src = _src()
    # Per-card alias anchor still exists.
    assert "const xbatchDeriveLifecycle" in src
    # Shared derivation anchor exists.
    assert "const deriveWarehouseLifecycle" in src
    # OP_PREDICATES.warehouse predicates reference both fields.
    idx = src.find("const OP_PREDICATES")
    assert idx != -1
    pred_body = src[idx : idx + 2000]
    for field in ("warehouseHint", "pzStatus"):
        assert field in pred_body, (
            f"OP_PREDICATES.warehouse must reference row.{field}"
        )


def test_lifecycle_derivation_does_not_invent_dispatch_states():
    """Cross-batch payload doesn't carry dispatched_items, so the
    derivation must NOT emit 'dispatched' or 'partial_dispatch'."""
    src = _src()
    idx = src.find("const xbatchDeriveLifecycle")
    body = src[idx : idx + 800]
    for forbidden in ("'dispatched'", "'partial_dispatch'",
                      '"dispatched"', '"partial_dispatch"'):
        assert forbidden not in body, (
            f"cross-batch derivation must NOT emit {forbidden} "
            "without dispatched_items in the list payload"
        )


# ── Attention list ─────────────────────────────────────────────────────────

def test_attention_table_landmark_present():
    src = _src()
    assert 'data-testid="warehouse-operations-attention-table"' in src


def test_attention_row_landmark_present():
    src = _src()
    assert 'data-testid="warehouse-operations-attention-row"' in src


def test_attention_row_exposes_batch_id_and_state():
    src = _src()
    block = _card_block(src)
    idx = block.find('data-testid="warehouse-operations-attention-row"')
    assert idx != -1
    snippet = block[idx : idx + 600]
    assert "data-batch-id=" in snippet, (
        "attention row must expose data-batch-id for downstream tooling"
    )
    assert "data-lifecycle-state=" in snippet, (
        "attention row must expose data-lifecycle-state"
    )


def test_attention_row_pill_landmark_present():
    src = _src()
    assert 'data-testid="warehouse-operations-attention-lifecycle-pill"' in src


def test_attention_empty_state_present():
    src = _src()
    assert 'data-testid="warehouse-operations-attention-empty"' in src


def test_attention_loading_state_present():
    src = _src()
    assert 'data-testid="warehouse-operations-attention-loading"' in src


def test_attention_open_handler_is_existing_navigation():
    """Opening a row must go through onViewShipment (existing
    read-only navigation), not a new write endpoint."""
    src = _src()
    block = _card_block(src)
    idx = block.find('data-testid="warehouse-operations-attention-open"')
    assert idx != -1
    # 600 chars window before+after the testid landmark must contain
    # the existing onViewShipment call.
    snippet = block[max(0, idx - 400) : idx + 400]
    assert "onViewShipment" in snippet, (
        "attention row open button must call onViewShipment, not "
        "introduce a new endpoint"
    )


# ── Read-only discipline ──────────────────────────────────────────────────

def test_card_block_does_not_call_apiFetch():
    """No new API calls inside the card block."""
    src = _src()
    block = _card_block(src)
    assert "apiFetch" not in block, (
        "warehouse-operations card must not introduce new apiFetch calls"
    )


def test_card_block_does_not_call_raw_fetch():
    src = _src()
    block = _card_block(src)
    assert "fetch(" not in block, (
        "warehouse-operations card must not introduce raw fetch() calls"
    )


def test_card_block_has_no_form_or_input():
    src = _src()
    block = _card_block(src)
    for forbidden in ("<input", "<form", "<select", "<textarea"):
        assert forbidden not in block, (
            f"warehouse-operations card must not contain {forbidden!r}"
        )


def test_card_block_has_no_btn_component():
    """No <Btn> primary actions — the only interactive element is the
    plain navigation button delegating to onViewShipment."""
    src = _src()
    block = _card_block(src)
    assert "<Btn" not in block, (
        "warehouse-operations card must not introduce <Btn> actions"
    )


def test_card_block_carries_read_only_disclaimer():
    """Operator-visible copy must declare the card is read-only and
    derived from existing payload."""
    src = _src()
    block = _card_block(src)
    assert "read-only" in block.lower(), (
        "card must disclose its read-only nature"
    )


def test_card_block_does_not_reference_execute_endpoints():
    """No carrier or warehouse execute endpoints may appear inside
    the card block."""
    src = _src()
    block = _card_block(src)
    for forbidden in (
        "/api/v1/carrier/actions/",
        "/api/v1/warehouse/scan",
        "/api/v1/warehouse/dispatch",
        "/execute",
    ):
        assert forbidden not in block, (
            f"warehouse-operations card must not reference {forbidden!r}"
        )


# ── Scope discipline — no multi-carrier leakage ───────────────────────────

@pytest.mark.parametrize(
    "forbidden",
    ["FedEx IP", "FedEx Priority", "UPS Worldwide", "Estrella Atlas",
     "Shipping Operations"],
)
def test_card_block_no_out_of_scope_carriers(forbidden):
    src = _src()
    block = _card_block(src)
    assert forbidden not in block, (
        f"out-of-scope copy {forbidden!r} leaked into "
        "warehouse-operations card block"
    )


# ── UI-3.1a preservation ──────────────────────────────────────────────────

def test_ui_3_1a_per_batch_badge_preserved():
    """UI-3.1a's per-batch lifecycle badge must remain intact."""
    src = _src()
    assert 'data-testid="warehouse-inventory-lifecycle-badge"' in src
    assert 'data-testid="warehouse-inventory-lifecycle-pill"'  in src
    assert "const lifecycleLabel" in src
    assert "const lifecycleState" in src


# ── Existing dashboard landmarks preserved ────────────────────────────────

@pytest.mark.parametrize(
    "preserved",
    [
        # Active shipment table
        'colSpan={14}',
        # Existing warehouse hint column header
        '<TH col="warehouseHint">Warehouse</TH>',
        # Existing summary cards
        'Total Shipments',
        'Awaiting DHL',
        'Awaiting SAD',
        'Ready for PZ',
        # Existing view mode toggle
        '⊘ Archived',
        '● Active',
    ],
)
def test_dashboard_landmarks_preserved(preserved):
    src = _src()
    assert preserved in src, (
        f"existing dashboard landmark {preserved!r} removed by UI-3.1b"
    )


# ── Brace balance / file sanity ───────────────────────────────────────────

def test_dashboard_html_braces_balanced():
    src = _src()
    opens = src.count("{")
    closes = src.count("}")
    assert opens == closes, f"unbalanced braces: {{={opens} }}={closes}"
