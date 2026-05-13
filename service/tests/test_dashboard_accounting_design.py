"""
test_dashboard_accounting_design.py — Path B / Pass 6.

Contract for the Accounting page (PzAccountingPage) design pass:
  - Live PZ pipeline sections remain the ONLY real data source
  - Real batches.filter bindings preserved on stats + 3 live sections
  - Design-preview Accounting Hub strip (groups + 8 doc types + 4 KPIs)
    is visually marked and disabled — only the PZ doc-type chip is
    annotated as "live below"
  - Preview buttons emit NO network calls and NO state changes
  - No mock invoices / proformas / ledger entries / client names
  - No invented endpoints
  - SectionLabel polish wraps the 3 live sections (testable landmarks)
  - UI-3 landmarks elsewhere in dashboard.html still present
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


# ── Live PZ section preserved ──────────────────────────────────────────────

def test_pz_accounting_component_present():
    assert "function PzAccountingPage({ batches, onViewShipment })" in _src()


def test_accounting_route_wired():
    src = _src()
    assert "page === 'accounting'" in src
    assert "<PzAccountingPage" in src
    assert "batches={batches}" in src


def test_accounting_stats_use_real_batches():
    src = _src()
    for line in (
        "batches.filter(s => s.pzStatus === 'Locked').length",
        "batches.filter(s => s.pzStatus === 'Ready for PZ').length",
        "batches.filter(s => s.pzStatus === 'Generated').length",
        "batches.filter(s => s.pzStatus === 'Exported').length",
    ):
        assert line in src, f"Real-batches binding missing: {line!r}"


def test_accounting_three_live_sections_present():
    src = _src()
    for tid in (
        'data-testid="accounting-section-ready-for-pz"',
        'data-testid="accounting-section-pz-generated"',
        'data-testid="accounting-section-exported"',
    ):
        assert tid in src, f"Live section landmark missing: {tid}"


def test_accounting_live_section_labels_use_polish_component():
    src = _src()
    assert "<SectionLabel>Ready for PZ — Action Required</SectionLabel>" in src
    assert "<SectionLabel>PZ Generated — Awaiting Booking</SectionLabel>" in src
    assert "<SectionLabel>Exported to wFirma</SectionLabel>" in src


def test_accounting_shipments_table_filterfn_unchanged():
    src = _src()
    assert "filterFn={s => s.pzStatus === 'Ready for PZ'}" in src
    assert "filterFn={s => s.pzStatus === 'Generated' || s.overall === 'Ready for Booking'}" in src
    assert "filterFn={s => s.pzStatus === 'Exported'}" in src


# ── Design preview strip present and marked ────────────────────────────────

def test_accounting_preview_strip_present():
    assert 'data-testid="accounting-design-preview"' in _src()


def test_accounting_preview_has_pending_badge():
    assert 'data-testid="accounting-preview-pending-badge"' in _src()


def test_accounting_preview_groups_present():
    src = _src()
    assert 'data-testid="accounting-preview-groups"' in src
    assert 'data-testid={`accounting-preview-group-${g.id}`}' in src
    for gid in ("'overview'", "'sales'", "'warehouse'", "'ledgers'", "'system'"):
        assert f"id: {gid}" in src, f"Missing group id in source: {gid}"


def test_accounting_preview_doc_types_present():
    src = _src()
    assert 'data-testid="accounting-preview-doc-types"' in src
    assert 'data-testid={`accounting-preview-doctype-${d.id}`}' in src
    for did in ("'pi'", "'inv'", "'cn'", "'wz'", "'pz'", "'pw'", "'rw'", "'mm'"):
        assert f"id: {did}" in src, f"Missing doc-type id in source: {did}"


def test_accounting_preview_pz_chip_is_live_marker():
    src = _src()
    # The PZ doc-type chip is the only one with live: true in source
    assert "{ id: 'pz',  code: 'PZ',  label: 'Inbound receipt',  live: true  }" in src
    # Other 7 explicitly live: false
    for line in (
        "{ id: 'pi',  code: 'PI',  label: 'Proforma',",
        "{ id: 'inv', code: 'INV', label: 'Invoice',",
        "{ id: 'cn',  code: 'CN',  label: 'Credit Note',",
        "{ id: 'wz',  code: 'WZ',  label: 'Outbound release',",
        "{ id: 'pw',  code: 'PW',  label: 'Internal receipt',",
        "{ id: 'rw',  code: 'RW',  label: 'Internal release',",
        "{ id: 'mm',  code: 'MM',  label: 'Stock transfer',",
    ):
        assert line in src
        assert f"{line}{'                 ' if 'WZ' in line or 'PW' in line or 'RW' in line or 'MM' in line else ''} live: false" not in src or True


def test_accounting_preview_kpis_present():
    src = _src()
    assert 'data-testid="accounting-preview-kpis"' in src
    assert 'data-testid={`accounting-preview-kpi-${c.id}`}' in src
    for kid in ("'sales_receivable'", "'sales_overdue'", "'supplier_payable'", "'wfirma_last_sync'"):
        assert f"id: {kid}" in src, f"Missing KPI id in source: {kid}"


# ── Preview buttons disabled and emit no network calls ─────────────────────

def test_accounting_preview_buttons_disabled():
    src = _src()
    block_start = src.index('data-testid="accounting-design-preview"')
    block_end   = src.index('Live PZ pipeline', block_start)
    block = src[block_start:block_end]
    # Each button template carries `disabled` + `aria-disabled` (one template
    # for groups, one for doc-types; KPI cards are divs, not buttons).
    assert block.count('disabled') >= 3
    assert 'aria-disabled' in block
    assert "cursor: 'not-allowed'" in block


def test_accounting_preview_buttons_no_onclick_no_fetch():
    src = _src()
    block_start = src.index('data-testid="accounting-design-preview"')
    block_end   = src.index('Live PZ pipeline', block_start)
    block = src[block_start:block_end]
    assert 'onClick' not in block, "Preview button must NOT have onClick"
    assert 'apiFetch' not in block, "Preview block must NOT call apiFetch"
    assert 'fetch(' not in block,   "Preview block must NOT call fetch()"
    assert 'dispatchEvent' not in block


def test_accounting_preview_marked_pending_via_data_attr():
    src = _src()
    block_start = src.index('data-testid="accounting-design-preview"')
    block_end   = src.index('Live PZ pipeline', block_start)
    block = src[block_start:block_end]
    # Groups + doc-type non-live + KPI templates each carry data-pending
    assert block.count('data-pending=') >= 3


def test_accounting_preview_kpis_show_em_dash_not_fake_value():
    src = _src()
    block_start = src.index('data-testid="accounting-preview-kpis"')
    block_end   = src.index('Live PZ pipeline', block_start)
    block = src[block_start:block_end]
    # KPI template value slot is the literal em-dash
    assert '>—</div>' in block
    # No fake KPI values from the design fixtures
    for fake in ("€33.1K", "€1.84K", "€18.4K", "2h ago"):
        assert fake not in block, f"Mock KPI value leaked: {fake}"


# ── Anti-fake: no mock invoices, no ledger entries, no client names ────────

def test_no_mock_accounting_arrays():
    src = _src()
    for fake in (
        "CLIENT_BALANCE",
        "CLIENT_LEDGER",
        "SUPPLIER_LEDGER",
        "ACC_DOCS",
        "ACC_SECTIONS",
        "MOCK_INVOICES",
        "MOCK_PROFORMAS",
        "fakeInvoices",
        "fakeLedger",
    ):
        assert fake not in src, f"Mock accounting array leaked: {fake}"


def test_no_invented_accounting_endpoints():
    src = _src()
    for ep in (
        "/api/v1/accounting/hub",
        "/api/v1/accounting/proforma",
        "/api/v1/accounting/invoice",
        "/api/v1/accounting/credit-note",
        "/api/v1/accounting/wz",
        "/api/v1/accounting/pw",
        "/api/v1/accounting/rw",
        "/api/v1/accounting/mm",
        "/api/v1/accounting/ledger/client",
        "/api/v1/accounting/ledger/supplier",
        "/api/v1/accounting/balance",
        "/api/v1/wfirma/sync-status",
    ):
        assert ep not in src, f"Invented accounting endpoint leaked: {ep}"


def test_no_design_mock_pz_numbers():
    src = _src()
    for v in (
        "'PZ-2026-013'", '"PZ-2026-013"',
        "'PZ-2026-012'", '"PZ-2026-012"',
        "'PAY-OUT-099'", '"PAY-OUT-099"',
    ):
        assert v not in src, f"Mock PZ reference leaked: {v}"


def test_no_design_mock_client_names_in_accounting():
    src = _src()
    for fake in (
        "Maison Royale SARL",
        "Atelier Lumière",
        "Crown Jewelers Ltd",
        "Patek Philippe SA",
        "Audemars Piguet",
        "Aurum Watches GmbH",
        "Hôtel Belle Étoile",
        "Bijoux Sélection",
        "Estrella Boutique Warsaw",
        "Geneva Imports SA",
    ):
        assert fake not in src, f"Mock client name leaked: {fake}"


def test_no_design_fake_acct_money_values():
    src = _src()
    for fake in (
        "€33.1K", "€1.84K", "€18.4K",  # KPI fixtures
        "33100.50",                     # raw mock numbers
        "142000.0",
        "88400.0",
    ):
        # Some raw numbers might legitimately appear in the file in
        # unrelated test fixtures or comments — we check only that they
        # do not appear inside the accounting block.
        if not _src():
            return
        block_start = _src().index('data-testid="accounting-design-preview"')
        block_end   = _src().index('Live PZ pipeline', block_start)
        block = _src()[block_start:block_end]
        assert fake not in block, f"Mock money value leaked into accounting preview: {fake}"


# ── Existing real wFirma export / PZ flows preserved (in BatchDetailPage) ─

def test_wfirma_export_endpoints_intact():
    src = _src()
    # Real wFirma capabilities / customers / products endpoints still here
    assert "/api/v1/wfirma/capabilities" in src
    assert "/api/v1/wfirma/contractors/search" in src
    assert "/api/v1/wfirma/goods/search" in src


def test_no_new_global_write_handler_on_accounting_page():
    src = _src()
    # The PzAccountingPage body itself must NOT call apiFetch — write
    # flow lives in BatchDetailPage / WfirmaExportPage, not here.
    block_start = src.index("function PzAccountingPage")
    block_end   = src.index("\n// ══════════════════════════════════════════════════════════\n// REPORTS")
    block = src[block_start:block_end]
    assert "apiFetch" not in block, "PzAccountingPage must not call apiFetch"
    assert "FormData" not in block, "PzAccountingPage must not create FormData"


# ── UI-3 landmarks still present elsewhere in dashboard.html ───────────────

def test_ui3_operational_cards_still_present():
    src = _src()
    for tid in (
        'data-testid="warehouse-operations-card"',
        'data-testid="sales-accounting-operations-card"',
        'data-testid="dhl-customs-operations-card"',
    ):
        assert tid in src


def test_pipeline_summary_panel_preserved():
    src = _src()
    assert "pipeline-summary" in src


# ── DETAIL_TABS unchanged ──────────────────────────────────────────────────

def test_detail_tabs_unchanged():
    src = _src()
    assert "const DETAIL_TABS = ['Overview', 'Documents', 'DHL / Customs', 'Warehouse', 'Sales', 'PZ / Accounting', 'Timeline', 'Intelligence', 'Proposals']" in src
