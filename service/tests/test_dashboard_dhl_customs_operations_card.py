"""tests/test_dashboard_dhl_customs_operations_card.py — UI-3.2b

Source-grep tests for the read-only cross-batch DHL & Customs
Operations card on DashboardPage. Third sibling in the UI-3.x
operational-card triptych (after UI-3.1b warehouse and UI-3.2a
sales+accounting).

The card MUST:
  - render only in active view mode;
  - derive purely from existing batch-list payload fields that have
    been verified to exist (dhl_status, sad_status, has_sad, mrn,
    tracking_status_key, tracking_status, awb, doc_no, id, timestamp)
    — must NOT invent customs_status or agency_status;
  - re-use operator-readable label maps under stable anchors;
  - expose stable data-testid landmarks + data-* attributes;
  - introduce no write surface (no apiFetch, no fetch, no form, no
    reply/send/customs execute action) beyond existing onViewShipment
    navigation;
  - introduce no FedEx / UPS / multi-carrier wording;
  - preserve UI-3.1a per-batch badge, UI-3.1b warehouse card, and
    UI-3.2a sales+accounting card landmarks.
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


_BLOCK_OPEN  = "UI-3.2b: cross-batch DHL & customs operations card"
_BLOCK_CLOSE = "{/* ── Archived view ── */}"


def _card_block(src: str) -> str:
    start = src.find(_BLOCK_OPEN)
    end   = src.find(_BLOCK_CLOSE, start)
    assert start != -1, "UI-3.2b block opener not found"
    assert end   != -1 and end > start, "UI-3.2b block close anchor not found"
    return src[start:end]


# ── Card landmark + placement ─────────────────────────────────────────────

def test_card_testid_present():
    src = _src()
    assert 'data-testid="dhl-customs-operations-card"' in src


def test_card_only_renders_in_active_view():
    src = _src()
    block = _card_block(src)
    assert "viewMode === 'active'" in block


def test_card_renders_after_warehouse_card():
    src = _src()
    wh_idx = src.find('data-testid="warehouse-operations-card"')
    dc_idx = src.find('data-testid="dhl-customs-operations-card"')
    assert wh_idx != -1 and dc_idx != -1
    assert dc_idx > wh_idx, "DHL/customs card must render after warehouse card"


def test_card_renders_after_sales_accounting_card():
    src = _src()
    sa_idx = src.find('data-testid="sales-accounting-operations-card"')
    dc_idx = src.find('data-testid="dhl-customs-operations-card"')
    assert sa_idx != -1 and dc_idx != -1
    assert dc_idx > sa_idx, "DHL/customs card must render after sales card"


def test_card_renders_before_active_shipments_table():
    src = _src()
    dc_idx    = src.find('data-testid="dhl-customs-operations-card"')
    table_idx = src.find('{/* ── Active shipments table ── */}')
    assert dc_idx != -1 and table_idx != -1
    assert dc_idx < table_idx


def test_card_renders_before_archived_block():
    src = _src()
    arch_idx = src.find('{/* ── Archived view ── */}')
    dc_idx   = src.find('data-testid="dhl-customs-operations-card"')
    assert arch_idx != -1 and dc_idx != -1
    assert dc_idx < arch_idx


# ── Bucket grid ───────────────────────────────────────────────────────────

def test_bucket_grid_landmark_present():
    src = _src()
    assert 'data-testid="dhl-customs-operations-buckets"' in src


def test_bucket_tile_uses_keyed_testid_template():
    src = _src()
    block = _card_block(src)
    assert "dhl-customs-operations-bucket-${key}" in block


@pytest.mark.parametrize(
    "key",
    [
        "awaiting_customs_docs",
        "sad_present",
        "sad_missing",
        "customs_cleared",
        "dhl_in_transit",
        "dhl_delivered",
    ],
)
def test_bucket_grid_iterates_each_bucket_key(key):
    src = _src()
    block = _card_block(src)
    idx = block.find("dhl-customs-operations-buckets")
    assert idx != -1
    snippet = block[idx : idx + 2000]
    assert f"'{key}'" in snippet, (
        f"bucket-grid iteration must include {key!r}"
    )


def test_bucket_tile_exposes_state_data_attribute():
    src = _src()
    block = _card_block(src)
    idx = block.find("dhl-customs-operations-bucket-${key}")
    assert idx != -1
    snippet = block[idx : idx + 600]
    assert "data-bucket-key={key}" in snippet


# ── Label maps + derivations ──────────────────────────────────────────────

def test_bucket_label_map_anchor_present():
    src = _src()
    assert "const dcBucketLabel" in src


def test_bucket_tone_map_anchor_present():
    src = _src()
    assert "const dcBucketTone" in src


def test_sad_cleared_keys_set_anchor_present():
    """UI-3.3a: SAD_CLEARED_KEYS lives at DashboardPage scope so the
    card counts + OP_PREDICATES + ATTENTION_PREDICATES share one source."""
    src = _src()
    assert "SAD_CLEARED_KEYS" in src


def test_track_attention_set_anchor_present():
    src = _src()
    assert "TRACK_ATTENTION" in src


def test_dhl_flow_live_keys_set_anchor_present():
    src = _src()
    assert "DHL_FLOW_LIVE_KEYS" in src


@pytest.mark.parametrize(
    "label",
    [
        "Awaiting customs docs",
        "SAD present",
        "SAD missing",
        "Customs cleared",
        "DHL in transit",
        "DHL delivered",
    ],
)
def test_bucket_operator_label_present(label):
    src = _src()
    block = _card_block(src)
    assert label in block


@pytest.mark.parametrize(
    "key",
    ["uploaded_parsed", "customs_parsed", "customs_verified"],
)
def test_sad_cleared_key_enumerated(key):
    """UI-3.3a: enumerated in SAD_CLEARED_KEYS at DashboardPage scope."""
    src = _src()
    assert f"'{key}'" in src


@pytest.mark.parametrize("key", ["exception", "customs"])
def test_track_attention_key_enumerated(key):
    src = _src()
    assert f"'{key}'" in src


@pytest.mark.parametrize(
    "key",
    [
        "dhl_email_received",
        "reply_queued",
        "reply_sent",
        "reply_package_prepared",
        "pre_check_pending",
        "pre_check_completed",
    ],
)
def test_dhl_flow_live_key_enumerated(key):
    src = _src()
    assert f"'{key}'" in src


@pytest.mark.parametrize("key", ["in_transit", "delivered"])
def test_tracking_status_key_in_bucket_filter(key):
    src = _src()
    assert f"'{key}'" in src


# ── Derivation source discipline ──────────────────────────────────────────

def test_derivations_use_existing_list_payload_fields():
    src = _src()
    block = _card_block(src)
    for field in ("dhl_status", "sad_status", "has_sad",
                  "tracking_status_key"):
        assert field in block, (
            f"derivation must reference verified payload field {field!r}"
        )


def test_derivation_does_not_invent_customs_status():
    """Pre-check rejected customs_status as a payload field."""
    src = _src()
    block = _card_block(src)
    assert "customs_status" not in block, (
        "card must NOT reference customs_status — field not in payload"
    )


def test_derivation_does_not_invent_agency_status():
    src = _src()
    block = _card_block(src)
    assert "agency_status" not in block, (
        "card must NOT reference agency_status — field not in payload"
    )


# ── Attention table ───────────────────────────────────────────────────────

def test_attention_table_landmark_present():
    src = _src()
    assert 'data-testid="dhl-customs-operations-attention-table"' in src


def test_attention_row_landmark_present():
    src = _src()
    assert 'data-testid="dhl-customs-operations-attention-row"' in src


def test_attention_row_exposes_required_data_attrs():
    src = _src()
    block = _card_block(src)
    idx = block.find('data-testid="dhl-customs-operations-attention-row"')
    assert idx != -1
    snippet = block[idx : idx + 1000]
    for attr in ("data-batch-id=", "data-dhl-status=",
                 "data-sad-status=", "data-has-sad=",
                 "data-tracking-key="):
        assert attr in snippet, (
            f"attention row must expose {attr!r} for downstream tooling"
        )


@pytest.mark.parametrize(
    "pill",
    [
        "dhl-customs-operations-attention-dhl-pill",
        "dhl-customs-operations-attention-sad-pill",
        "dhl-customs-operations-attention-tracking-pill",
    ],
)
def test_attention_row_pill_landmarks_present(pill):
    src = _src()
    assert f'data-testid="{pill}"' in src


def test_attention_empty_state_present():
    src = _src()
    assert 'data-testid="dhl-customs-operations-attention-empty"' in src


def test_attention_loading_state_present():
    src = _src()
    assert 'data-testid="dhl-customs-operations-attention-loading"' in src


def test_attention_open_handler_is_existing_navigation():
    src = _src()
    block = _card_block(src)
    idx = block.find('data-testid="dhl-customs-operations-attention-open"')
    assert idx != -1
    snippet = block[max(0, idx - 400) : idx + 400]
    assert "onViewShipment" in snippet


def test_attention_table_has_mrn_column_header():
    """MRN must be a visible column header (operator visibility
    of customs reference)."""
    src = _src()
    block = _card_block(src)
    # The column header strings are emitted via the ['Shipment', ...]
    # array literal.
    idx = block.find('data-testid="dhl-customs-operations-attention-table"')
    snippet = block[idx : idx + 1500]
    assert "'MRN'" in snippet, "attention table must include MRN column"


# ── Read-only discipline ──────────────────────────────────────────────────

def test_card_block_does_not_call_apiFetch():
    src = _src()
    block = _card_block(src)
    assert "apiFetch" not in block


def test_card_block_does_not_call_raw_fetch():
    src = _src()
    block = _card_block(src)
    assert "fetch(" not in block


def test_card_block_has_no_form_or_input():
    src = _src()
    block = _card_block(src)
    for forbidden in ("<input", "<form", "<select", "<textarea"):
        assert forbidden not in block


def test_card_block_has_no_btn_component():
    src = _src()
    block = _card_block(src)
    assert "<Btn" not in block


def test_card_block_carries_read_only_disclaimer():
    src = _src()
    block = _card_block(src)
    assert "read-only" in block.lower()


def test_card_block_has_no_reply_or_send_button_text():
    src = _src()
    block = _card_block(src)
    for forbidden in (
        ">Reply<", ">Send<", ">Forward<", ">Clear<",
        ">Resolve<", ">Re-send<", ">Customs<",
    ):
        assert forbidden not in block, (
            f"DHL/customs card must not introduce {forbidden!r} button text"
        )


def test_card_block_does_not_reference_execute_endpoints():
    src = _src()
    block = _card_block(src)
    for forbidden in (
        "/api/v1/dhl/",
        "/api/v1/customs/",
        "/api/v1/agency/",
        "/api/v1/carrier/actions/",
        "/execute",
        "/send-reply",
        "/send-initial",
        "/proactive-dispatch",
    ):
        assert forbidden not in block, (
            f"DHL/customs card must not reference {forbidden!r}"
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
    assert forbidden not in block


def test_card_block_keeps_dhl_express_wording_in_title_area():
    """Card title / subtitle area must remain DHL-scope, not generic
    'carrier'."""
    src = _src()
    block = _card_block(src)
    assert "DHL" in block, "card scope must remain DHL"


# ── Prior UI-3.x surface preservation ─────────────────────────────────────

def test_ui_3_1a_per_batch_badge_preserved():
    # The per-batch lifecycle badge moved to shipment-detail.html.
    src = _detail_src()
    assert 'data-testid="warehouse-inventory-lifecycle-badge"' in src
    assert "const lifecycleLabel" in src


def test_ui_3_1b_warehouse_card_preserved():
    src = _src()
    assert 'data-testid="warehouse-operations-card"' in src
    assert 'data-testid="warehouse-operations-buckets"' in src
    assert 'data-testid="warehouse-operations-attention-table"' in src
    assert "const xbatchLifecycleLabel" in src


def test_ui_3_2a_sales_accounting_card_preserved():
    src = _src()
    assert 'data-testid="sales-accounting-operations-card"' in src
    assert 'data-testid="sales-accounting-operations-buckets"' in src
    assert 'data-testid="sales-accounting-operations-attention-table"' in src
    assert "const acctBucketLabel" in src


# ── Existing dashboard landmarks preserved ────────────────────────────────

@pytest.mark.parametrize(
    "preserved",
    [
        'colSpan={14}',
        '<TH col="warehouseHint">Warehouse</TH>',
        '<TH col="salesHint">Sales</TH>',
        '<TH col="wfirmaHint">wFirma</TH>',
        '<TH col="dhlStatus">DHL Status</TH>',
        '<TH col="sadStatus">SAD Status</TH>',
        '<TH col="mrn">MRN</TH>',
        'Total Shipments',
        'Awaiting DHL',
        '⊘ Archived',
        '● Active',
    ],
)
def test_dashboard_landmarks_preserved(preserved):
    src = _src()
    assert preserved in src, (
        f"existing dashboard landmark {preserved!r} removed by UI-3.2b"
    )


# ── Brace balance / file sanity ───────────────────────────────────────────

def test_dashboard_html_braces_balanced():
    src = _src()
    opens = src.count("{")
    closes = src.count("}")
    assert opens == closes, f"unbalanced braces: {{={opens} }}={closes}"
