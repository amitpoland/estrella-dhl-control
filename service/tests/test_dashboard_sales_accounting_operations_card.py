"""tests/test_dashboard_sales_accounting_operations_card.py — UI-3.2a

Source-grep tests for the read-only cross-batch Sales & Accounting
Operations card on DashboardPage. Mirrors the UI-3.1b warehouse card
pattern; reads only fields already present on every list row.

The card MUST:
  - render only in active view mode;
  - derive purely from existing batch-list payload fields
    (salesHint, wfirmaHint, pzStatus, awb, doc_no, id, timestamp);
  - re-use operator-readable label maps under stable anchors;
  - expose stable data-testid landmarks + data-* attributes;
  - introduce no write surface (no apiFetch, no fetch, no form,
    no execute / export action) beyond the existing onViewShipment
    navigation handler which is read-only;
  - introduce no carrier/multi-carrier wording;
  - leave UI-3.1a per-batch lifecycle badge and UI-3.1b warehouse
    operations card untouched.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_HERE     = Path(__file__).resolve()
_SVC_ROOT = _HERE.parent.parent
_DASH     = _SVC_ROOT / "app" / "static" / "dashboard.html"
_DETAIL   = _SVC_ROOT / "app" / "static" / "shipment-detail.html"


def _src() -> str:
    if not _DASH.exists():
        pytest.skip("dashboard.html not found")
    return _DASH.read_text(encoding="utf-8")


def _detail_src() -> str:
    if not _DETAIL.exists():
        pytest.skip("shipment-detail.html not found")
    return _DETAIL.read_text(encoding="utf-8")


_BLOCK_OPEN  = "UI-3.2a: cross-batch sales & accounting operations card"
_BLOCK_CLOSE = "{/* ── Archived view ── */}"


def _card_block(src: str) -> str:
    start = src.find(_BLOCK_OPEN)
    end   = src.find(_BLOCK_CLOSE, start)
    assert start != -1, "UI-3.2a block opener not found"
    assert end   != -1 and end > start, "UI-3.2a block close anchor not found"
    return src[start:end]


# ── Card landmark + placement ─────────────────────────────────────────────

def test_card_testid_present():
    src = _src()
    assert 'data-testid="sales-accounting-operations-card"' in src


def test_card_only_renders_in_active_view():
    src = _src()
    block = _card_block(src)
    assert "viewMode === 'active'" in block, (
        "sales-accounting-operations-card must be gated on active view mode"
    )


def test_card_renders_after_warehouse_operations_card():
    """The accounting card sits below the warehouse card to keep
    operator flow Warehouse → Sales/Accounting → Shipment table."""
    src = _src()
    wh_idx  = src.find('data-testid="warehouse-operations-card"')
    acct_idx = src.find('data-testid="sales-accounting-operations-card"')
    assert wh_idx != -1 and acct_idx != -1
    assert acct_idx > wh_idx, (
        "sales-accounting card must render after the warehouse card"
    )


def test_card_renders_before_active_shipments_table():
    src = _src()
    acct_idx  = src.find('data-testid="sales-accounting-operations-card"')
    table_idx = src.find('{/* ── Active shipments table ── */}')
    assert acct_idx != -1 and table_idx != -1
    assert acct_idx < table_idx, (
        "sales-accounting card must render above the active table"
    )


def test_card_renders_before_archived_view_block():
    src = _src()
    archived_idx = src.find('{/* ── Archived view ── */}')
    acct_idx     = src.find('data-testid="sales-accounting-operations-card"')
    assert archived_idx != -1 and acct_idx != -1
    assert acct_idx < archived_idx, (
        "sales-accounting card must not live inside the archived block"
    )


# ── Bucket grid ────────────────────────────────────────────────────────────

def test_bucket_grid_landmark_present():
    src = _src()
    assert 'data-testid="sales-accounting-operations-buckets"' in src


def test_bucket_tile_uses_keyed_testid_template():
    src = _src()
    block = _card_block(src)
    assert "sales-accounting-operations-bucket-${key}" in block, (
        "bucket tile must use the keyed testid template"
    )


@pytest.mark.parametrize(
    "key",
    [
        "sales_ready",
        "sales_missing",
        "wfirma_preview",
        "wfirma_pending",
        "pz_done",
        "pz_pending",
    ],
)
def test_bucket_grid_iterates_each_bucket_key(key):
    src = _src()
    block = _card_block(src)
    idx = block.find("sales-accounting-operations-buckets")
    assert idx != -1
    snippet = block[idx : idx + 2000]
    assert f"'{key}'" in snippet, (
        f"bucket-grid iteration must include {key!r}"
    )


def test_bucket_tile_exposes_state_data_attribute():
    src = _src()
    block = _card_block(src)
    idx = block.find("sales-accounting-operations-bucket-${key}")
    assert idx != -1
    snippet = block[idx : idx + 600]
    assert "data-bucket-key={key}" in snippet, (
        "bucket tile must expose data-bucket-key={key}"
    )


# ── Label maps + derivations ──────────────────────────────────────────────

def test_bucket_label_map_anchor_present():
    src = _src()
    assert "const acctBucketLabel" in src, (
        "acctBucketLabel map declaration missing"
    )


def test_bucket_tone_map_anchor_present():
    src = _src()
    assert "const acctBucketTone" in src, (
        "acctBucketTone map declaration missing"
    )


def test_sales_label_helper_anchor_present():
    src = _src()
    assert "const acctSalesLabel" in src


def test_wfirma_label_helper_anchor_present():
    src = _src()
    assert "const acctWfirmaLabel" in src


def test_sales_missing_helper_anchor_present():
    src = _src()
    assert "const acctSalesMissing" in src


def test_wfirma_missing_helper_anchor_present():
    src = _src()
    assert "const acctWfirmaMissing" in src


def test_pz_pending_helper_anchor_present():
    src = _src()
    assert "const acctPzPending" in src


def test_needs_attention_helper_anchor_present():
    src = _src()
    assert "const acctNeedsAttention" in src


@pytest.mark.parametrize(
    "label",
    [
        "Sales ready",
        "Sales missing",
        "wFirma preview built",
        "wFirma not prepared",
        "PZ generated/exported",
        "PZ ready/locked",
    ],
)
def test_bucket_operator_label_present(label):
    src = _src()
    block = _card_block(src)
    assert label in block, (
        f"operator-readable bucket label {label!r} missing"
    )


@pytest.mark.parametrize(
    "label",
    ["Linked", "Not linked", "Preview built", "Not prepared", "Unknown"],
)
def test_row_pill_label_present(label):
    """Per-row pill labels rendered by the helpers must appear in source."""
    src = _src()
    block = _card_block(src)
    assert label in block, (
        f"row pill label {label!r} missing from sales-accounting block"
    )


# ── Derivation source discipline ──────────────────────────────────────────

def test_derivations_use_existing_list_payload_fields():
    """Derivations must read only salesHint, wfirmaHint, pzStatus —
    fields already on every list row. No new payload references."""
    src = _src()
    block = _card_block(src)
    for field in ("salesHint", "wfirmaHint", "pzStatus"):
        assert field in block, f"derivation must reference row.{field}"


def test_pz_done_labels_set_anchor_present():
    """UI-3.3a: PZ_DONE_LABELS lives at DashboardPage scope so the
    card counts and OP_PREDICATES.sales_accounting share one source."""
    src = _src()
    assert "PZ_DONE_LABELS" in src, "PZ_DONE_LABELS set must be declared"


def test_pz_pending_labels_set_anchor_present():
    src = _src()
    assert "PZ_PENDING_LABELS" in src, "PZ_PENDING_LABELS set must be declared"


@pytest.mark.parametrize("label", ["Generated", "Exported"])
def test_pz_done_label_string_in_source(label):
    """UI-3.3a: the literal strings live in the shared PZ_DONE_LABELS
    Set at DashboardPage scope, not inside the card IIFE."""
    src = _src()
    assert f"'{label}'" in src, (
        f"PZ done label {label!r} must be enumerated in source"
    )


@pytest.mark.parametrize("label", ["Ready for PZ", "Locked"])
def test_pz_pending_label_string_in_source(label):
    src = _src()
    assert f"'{label}'" in src, (
        f"PZ pending label {label!r} must be enumerated in source"
    )


# ── Attention table ───────────────────────────────────────────────────────

def test_attention_table_landmark_present():
    src = _src()
    assert 'data-testid="sales-accounting-operations-attention-table"' in src


def test_attention_row_landmark_present():
    src = _src()
    assert 'data-testid="sales-accounting-operations-attention-row"' in src


def test_attention_row_exposes_batch_id_and_hints():
    src = _src()
    block = _card_block(src)
    idx = block.find('data-testid="sales-accounting-operations-attention-row"')
    assert idx != -1
    snippet = block[idx : idx + 800]
    for attr in ("data-batch-id=", "data-sales-hint=",
                 "data-wfirma-hint=", "data-pz-status="):
        assert attr in snippet, (
            f"attention row must expose {attr!r} for downstream tooling"
        )


@pytest.mark.parametrize(
    "pill",
    [
        "sales-accounting-operations-attention-sales-pill",
        "sales-accounting-operations-attention-wfirma-pill",
        "sales-accounting-operations-attention-pz-pill",
    ],
)
def test_attention_row_pill_landmarks_present(pill):
    src = _src()
    assert f'data-testid="{pill}"' in src


def test_attention_empty_state_present():
    src = _src()
    assert 'data-testid="sales-accounting-operations-attention-empty"' in src


def test_attention_loading_state_present():
    src = _src()
    assert 'data-testid="sales-accounting-operations-attention-loading"' in src


def test_attention_open_handler_is_existing_navigation():
    src = _src()
    block = _card_block(src)
    idx = block.find('data-testid="sales-accounting-operations-attention-open"')
    assert idx != -1
    snippet = block[max(0, idx - 400) : idx + 400]
    assert "onViewShipment" in snippet, (
        "attention row open button must call onViewShipment"
    )


# ── Read-only discipline ──────────────────────────────────────────────────

def test_card_block_does_not_call_apiFetch():
    src = _src()
    block = _card_block(src)
    assert "apiFetch" not in block, (
        "sales-accounting card must not introduce new apiFetch calls"
    )


def test_card_block_does_not_call_raw_fetch():
    src = _src()
    block = _card_block(src)
    assert "fetch(" not in block


def test_card_block_has_no_form_or_input():
    src = _src()
    block = _card_block(src)
    for forbidden in ("<input", "<form", "<select", "<textarea"):
        assert forbidden not in block, (
            f"sales-accounting card must not contain {forbidden!r}"
        )


def test_card_block_has_no_btn_component():
    src = _src()
    block = _card_block(src)
    assert "<Btn" not in block, (
        "sales-accounting card must not introduce <Btn> actions"
    )


def test_card_block_carries_read_only_disclaimer():
    src = _src()
    block = _card_block(src)
    assert "read-only" in block.lower(), (
        "card must disclose its read-only nature"
    )


def test_card_block_has_no_export_or_create_button_text():
    """No 'Export', 'Create', 'Send', 'Generate', 'Adopt', 'Convert'
    button text inside the card block."""
    src = _src()
    block = _card_block(src)
    for forbidden in (
        ">Export<", ">Create<", ">Send<", ">Generate<",
        ">Adopt<", ">Convert<", ">Issue<",
    ):
        assert forbidden not in block, (
            f"sales-accounting card must not introduce {forbidden!r} "
            "button text"
        )


def test_card_block_does_not_reference_execute_endpoints():
    src = _src()
    block = _card_block(src)
    for forbidden in (
        "/api/v1/wfirma/",
        "/api/v1/pz/process",
        "/api/v1/proforma/",
        "/api/v1/sales/",
        "/execute",
        "/create",
        "/adopt",
    ):
        assert forbidden not in block, (
            f"sales-accounting card must not reference {forbidden!r}"
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
        "sales-accounting card block"
    )


# ── UI-3.1a + UI-3.1b preservation ────────────────────────────────────────

def test_ui_3_1a_per_batch_badge_preserved():
    # The per-batch lifecycle badge/pill moved to shipment-detail.html.
    src = _detail_src()
    assert 'data-testid="warehouse-inventory-lifecycle-badge"' in src
    assert 'data-testid="warehouse-inventory-lifecycle-pill"'  in src
    assert "const lifecycleLabel" in src


def test_ui_3_1b_warehouse_card_preserved():
    src = _src()
    assert 'data-testid="warehouse-operations-card"' in src
    assert 'data-testid="warehouse-operations-buckets"' in src
    assert 'data-testid="warehouse-operations-attention-table"' in src
    assert "const xbatchLifecycleLabel" in src
    assert "const xbatchDeriveLifecycle" in src


# ── Existing dashboard landmarks preserved ────────────────────────────────

@pytest.mark.parametrize(
    "preserved",
    [
        'colSpan={14}',
        '<TH col="warehouseHint">Warehouse</TH>',
        '<TH col="salesHint">Sales</TH>',
        '<TH col="wfirmaHint">wFirma</TH>',
        'Total Shipments',
        'Awaiting DHL',
        'Ready for PZ',
        '⊘ Archived',
        '● Active',
    ],
)
def test_dashboard_landmarks_preserved(preserved):
    src = _src()
    assert preserved in src, (
        f"existing dashboard landmark {preserved!r} removed by UI-3.2a"
    )


# ── Brace balance / file sanity ───────────────────────────────────────────

def test_dashboard_html_braces_balanced():
    src = _src()
    opens = src.count("{")
    closes = src.count("}")
    assert opens == closes, f"unbalanced braces: {{={opens} }}={closes}"
