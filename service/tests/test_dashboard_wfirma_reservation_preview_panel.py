"""
test_dashboard_wfirma_reservation_preview_panel.py — UI exposure tests for
the wFirma Reservation Preview panel inside Batch detail.

Pattern matches test_dashboard_sales_linkage_panel.py: read dashboard.html
source as text and assert specific markers exist. Backend logic is covered
by the wfirma_reservation service tests.

Phase 1 deliverable: confirm the panel exposes every documented field of
the GET /api/v1/wfirma/reservation-preview/{batch_id} response, plus the
required UI states (loading, error, empty).
"""
from __future__ import annotations

from pathlib import Path


DASHBOARD = Path(__file__).resolve().parent.parent / "app" / "static" / "dashboard.html"


def _src() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


# ── Tab registration ─────────────────────────────────────────────────────────

def test_wfirma_tab_registered_in_detail_tabs():
    """The 'PZ / Accounting' tab must appear in DETAIL_TABS (renamed from 'wFirma')."""
    src = _src()
    assert "DETAIL_TABS" in src, "DETAIL_TABS array missing"
    for line in src.splitlines():
        if "const DETAIL_TABS" in line and "[" in line:
            assert "'PZ / Accounting'" in line, (
                "PZ / Accounting tab not registered: " + line
            )
            return
    raise AssertionError("Could not locate DETAIL_TABS definition")


# ── Endpoint wiring ──────────────────────────────────────────────────────────

def test_reservation_preview_endpoint_is_wired():
    """The panel must call GET /api/v1/wfirma/reservation-preview/{batch_id}."""
    src = _src()
    assert "/api/v1/wfirma/reservation-preview/" in src
    assert "loadReservationPreview" in src
    # The fetch must trigger when the PZ / Accounting tab becomes active
    assert "activeTab === 'PZ / Accounting'" in src


def test_reservation_preview_state_hooks_present():
    src = _src()
    assert "reservationPreview" in src
    assert "reservationPreviewLoading" in src
    assert "setReservationPreview" in src
    assert "setReservationPreviewLoading" in src


# ── Master gate fields ───────────────────────────────────────────────────────

def test_panel_renders_ready_to_create_flag():
    src = _src()
    assert "ready_to_create" in src
    # The master gate banner must surface the "Ready to create" / "BLOCKED"
    # text driven by ready_to_create.
    assert "Ready to create reservation" in src
    assert "Reservation BLOCKED" in src


def test_panel_renders_blocking_reasons():
    src = _src()
    assert "blocking_reasons" in src
    # The master gate must render the list when present.
    # (We assert the access pattern; the JSX renders <li> per item.)
    assert "(rp.blocking_reasons || [])" in src


# ── Capability strip ────────────────────────────────────────────────────────

def test_panel_renders_capability_flags():
    """wfirma_configured / audit_clean / reservation_supported all visible."""
    src = _src()
    assert "rp.wfirma_configured" in src
    assert "rp.audit_clean" in src
    assert "rp.reservation_supported" in src
    # Human-readable labels for the chips
    assert "wFirma configured" in src
    assert "Audit clean" in src
    assert "Reservation supported" in src


# ── Summary fields ───────────────────────────────────────────────────────────

def test_panel_renders_summary_counts_and_currency():
    src = _src()
    # Document count + ready/total ratio
    assert "Documents:" in src
    # Currency from invoice_lines
    assert "rp.currency" in src
    assert "Currency:" in src


# ── Per-document fields ──────────────────────────────────────────────────────

def test_panel_renders_per_document_required_fields():
    """Per the response contract, each document has:
      sales_doc_no, client_name, client_ref, customer_ok, customer_match,
      ready, total_value, blocking_reasons.
    All must surface in the UI."""
    src = _src()
    for accessor in (
        "d.sales_doc_no",
        "d.client_name",
        "d.client_ref",
        "d.customer_ok",
        "d.customer_match",
        "d.ready",
        "d.total_value",
        "d.blocking_reasons",
    ):
        assert accessor in src, f"per-document field not surfaced: {accessor}"


# ── Per-row fields ──────────────────────────────────────────────────────────

def test_panel_renders_per_row_required_fields():
    """Per the response contract, each row has:
      product_code, quantity, unit_price, currency,
      stock_ok / stock_status, product_match, design_nos, ready.
    All must surface in the UI."""
    src = _src()
    for accessor in (
        "r.product_code",
        "r.quantity",
        "r.unit_price",
        "r.stock_status",
        "r.product_match",
        "r.design_nos",
        "r.ready",
    ):
        assert accessor in src, f"per-row field not surfaced: {accessor}"


def test_panel_renders_stock_status_badges():
    """stock_status is dispatched | received | missing — all three labels
    must be displayable so the operator sees the right colour/word."""
    src = _src()
    # Look at the STOCK_BADGE map keys
    assert "dispatched:" in src and "Dispatched" in src
    assert "received:" in src   and "Received"   in src
    assert "missing:" in src    and "Missing"    in src


# ── States: loading / error / empty ─────────────────────────────────────────

def test_panel_handles_loading_state():
    src = _src()
    assert "Loading reservation preview" in src


def test_panel_handles_error_state():
    src = _src()
    assert "Reservation preview failed" in src


def test_panel_handles_empty_documents():
    """When the response has no sales documents, an empty-state message must
    render rather than the panel appearing blank."""
    src = _src()
    assert "No sales documents found for this batch" in src


# ── Compile-safety ──────────────────────────────────────────────────────────

def test_dashboard_html_braces_balanced():
    """Coarse compile check: '{' and '}' counts match. Catches truncation."""
    src = _src()
    opens = src.count("{")
    closes = src.count("}")
    assert opens == closes, f"unbalanced braces: {{={opens} }}={closes}"


def test_dashboard_html_has_wfirma_panel_branch():
    src = _src()
    assert "activeTab === 'PZ / Accounting'" in src
    # The visible panel header
    assert "wFirma Reservation Preview" in src
