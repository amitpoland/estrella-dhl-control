"""
test_dashboard_batch_list_status_columns.py — UI exposure tests for the
batch-list status columns (Phase 1, Change 5).

Pattern matches test_dashboard_sales_linkage_panel.py and
test_dashboard_wfirma_reservation_preview_panel.py: read dashboard.html as
text and assert specific markers exist. Backend logic (the hint computation
in routes_dashboard.py) is unchanged and untested here.
"""
from __future__ import annotations

from pathlib import Path


DASHBOARD = (
    Path(__file__).resolve().parent.parent / "app" / "static" / "dashboard.html"
)


SHIPMENT_DETAIL = (
    Path(__file__).resolve().parent.parent / "app" / "static" / "shipment-detail.html"
)


def _src() -> str:
    if not DASHBOARD.exists():
        import pytest
        pytest.skip(f"dashboard.html not found at {DASHBOARD}")
    return DASHBOARD.read_text(encoding="utf-8")


def _detail_src() -> str:
    if not SHIPMENT_DETAIL.exists():
        import pytest
        pytest.skip(f"shipment-detail.html not found at {SHIPMENT_DETAIL}")
    return SHIPMENT_DETAIL.read_text(encoding="utf-8")


# ── Endpoint wiring (must remain) ────────────────────────────────────────────

def test_batch_list_endpoint_remains_wired():
    src = _src()
    assert "/dashboard/batches?all=1" in src
    assert "loadBatches" in src
    assert "transformBatch" in src


def test_transform_batch_extracts_existing_status_hints():
    """transformBatch must surface the hint fields the backend already
    returns; we don't add new fields, only rely on existing ones."""
    src = _src()
    assert "warehouse_status_hint" in src
    assert "sales_status_hint" in src
    assert "wfirma_status_hint" in src


# ── Column headers added ─────────────────────────────────────────────────────

def test_batch_list_has_status_column_headers():
    """The four new columns must appear in the table header row, in addition
    to the original AWB / Carrier / Overall / Net / Gross / Duty A00 / Actions."""
    src = _src()
    # Find the table header literal
    assert (
        "['AWB / Tracking', 'Carrier', 'Warehouse', 'Sales', 'wFirma', 'DHL', "
        "'Overall', 'Net', 'Gross', 'Duty A00', 'Actions']"
    ) in src, "ShipmentsTable header row does not contain the new status columns"


# ── Per-row data wiring ──────────────────────────────────────────────────────

def test_warehouse_chip_uses_existing_warehouse_hint():
    src = _src()
    assert "row.warehouseHint" in src
    assert 'testId="shipments-cell-warehouse"' in src


def test_sales_chip_uses_existing_sales_hint():
    src = _src()
    assert "row.salesHint" in src
    assert 'testId="shipments-cell-sales"' in src


def test_wfirma_chip_uses_existing_wfirma_hint():
    src = _src()
    assert "row.wfirmaHint" in src
    assert 'testId="shipments-cell-wfirma"' in src


def test_dhl_cell_uses_existing_dhl_status():
    """DHL status is already mapped from b.dhl_status; the column shows it
    with a 'Not checked' fallback when the row has no value."""
    src = _src()
    assert 'data-testid="shipments-cell-dhl"' in src
    assert "row.dhlStatus" in src


def test_overall_cell_remains_present_as_blocked_ready_indicator():
    """The Overall column was already there as the readiness indicator;
    the new layout must keep it AND give it a stable test id."""
    src = _src()
    assert 'data-testid="shipments-cell-overall"' in src
    # Badge is bound to row.overall with the `small` variant. A `title`
    # tooltip prop (action_reason) was later added after `small`, so match
    # the stable prefix rather than the exact self-closing form.
    assert "<Badge status={row.overall} small" in src


# ── Missing-value handling ───────────────────────────────────────────────────

def test_status_chip_renders_safe_fallback_for_missing_values():
    """When a hint is null/missing/'n/a', the chip must show a neutral
    'Not checked' label rather than blank or crash."""
    src = _src()
    # The STATUS_HINT_MAP includes the 'n/a' fallback…
    assert "'n/a':" in src or '"n/a":' in src
    assert "'Not checked'" in src or '"Not checked"' in src
    # And the StatusChip helper coerces null/empty to 'n/a'
    assert "value == null || value === ''" in src


def test_dhl_cell_falls_back_to_not_checked():
    """The DHL cell uses 'Not checked' when row.dhlStatus is empty."""
    src = _src()
    # The cell uses {row.dhlStatus || 'Not checked'}
    assert "row.dhlStatus || 'Not checked'" in src


# ── Status chip palette covers the documented hint values ───────────────────

def test_status_chip_covers_warehouse_hint_values():
    """Backend yields warehouse_status_hint ∈ {clean, partial, empty, n/a}.
    All four must have a label in STATUS_HINT_MAP."""
    src = _src()
    for v in ("clean:", "partial:", "empty:", "'n/a':"):
        assert v in src, f"warehouse hint value {v!r} missing from STATUS_HINT_MAP"


def test_status_chip_covers_sales_hint_values():
    """Backend yields sales_status_hint ∈ {present, none, n/a}."""
    src = _src()
    for v in ("present:", "none:", "'n/a':"):
        assert v in src, f"sales hint value {v!r} missing from STATUS_HINT_MAP"


def test_status_chip_covers_wfirma_hint_values():
    """Backend yields wfirma_status_hint ∈ {preview_built, none, n/a}."""
    src = _src()
    for v in ("preview_built:", "none:", "'n/a':"):
        assert v in src, f"wfirma hint value {v!r} missing from STATUS_HINT_MAP"


# ── Compile-safety ──────────────────────────────────────────────────────────

def test_dashboard_html_braces_balanced():
    """Coarse compile-safety check after the edit."""
    src = _src()
    opens = src.count("{")
    closes = src.count("}")
    assert opens == closes, f"unbalanced braces: {{={opens} }}={closes}"


def test_dashboard_has_status_chip_helper_and_table_marker():
    src = _src()
    # The new helper component
    assert "function StatusChip(" in src
    # The data-testid on the table itself
    assert 'data-testid="shipments-table"' in src
    assert 'data-testid="shipments-row"' in src


def test_no_unrelated_endpoints_changed():
    """Sanity: the endpoints we depend on are still referenced (not deleted).
    Under Atlas-V2 the per-shipment sales-linkage and wFirma reservation-preview
    calls migrated from dashboard.html to shipment-detail.html; the batch-list
    fetch stays on dashboard.html."""
    src = _src()
    detail = _detail_src()
    # Sales linkage (moved to the shipment-detail page)
    assert "/api/v1/sales/linkage/" in detail
    # wFirma reservation preview (moved to the shipment-detail page)
    assert "/api/v1/wfirma/reservation-preview/" in detail
    # Batch list (still the dashboard's own fetch)
    assert "/dashboard/batches?all=1" in src
