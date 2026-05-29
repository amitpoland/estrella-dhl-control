"""
test_dashboard_documents_design.py — Path B / Pass 5.

Contract for the Documents page (CustomsDocumentsPage) design pass:
  - Live SAD / ZC429 sections remain the ONLY real data source
  - Real batches.filter bindings preserved on stats + 3 sections
  - Design-preview Documents Hub strip (Proforma / PZ-Inbound / Other +
    Draft/Approved/Posted/Cancelled lanes + upload/new-doc actions) is
    visually marked and disabled
  - Preview buttons emit NO network calls and NO state changes
  - No mock document arrays, no SAMPLE_FLOW, no /api/v1/pi or /api/v1/pz
    hub endpoints invented
  - SectionLabel polish wraps the 3 live sections (testable landmarks)
  - UI-3 landmarks elsewhere in dashboard.html still present
"""
from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SVC_ROOT = _HERE.parent
_DASH = _SVC_ROOT / "app" / "static" / "dashboard.html"
_DETAIL = _SVC_ROOT / "app" / "static" / "shipment-detail.html"


def _src() -> str:
    if not _DASH.exists():
        import pytest
        pytest.skip(f"dashboard.html not found at {_DASH}")
    return _DASH.read_text(encoding="utf-8")


def _detail_src() -> str:
    if not _DETAIL.exists():
        import pytest
        pytest.skip(f"shipment-detail.html not found at {_DETAIL}")
    return _DETAIL.read_text(encoding="utf-8")


# ── Live customs section preserved ─────────────────────────────────────────

def test_customs_documents_component_present():
    src = _src()
    assert "function CustomsDocumentsPage({ batches, onViewShipment })" in src


def test_documents_route_wired():
    src = _src()
    assert "page === 'documents'" in src
    assert "<CustomsDocumentsPage" in src
    assert "batches={batches}" in src


def test_documents_stats_use_real_batches():
    src = _src()
    for line in (
        "batches.filter(s => s.sadStatus === 'SAD Pending').length",
        "batches.filter(s => s.sadStatus === 'SAD Uploaded').length",
        "batches.filter(s => s.sadStatus === 'Customs Verified').length",
        "batches.filter(s => s.sadStatus === 'Verification Needed').length",
    ):
        assert line in src, f"Real-batches binding missing: {line!r}"


def test_documents_three_live_sections_present():
    src = _src()
    # Each live section wraps its ShipmentsTable in a testid container with
    # a SectionLabel
    for tid in (
        'data-testid="documents-section-verification-needed"',
        'data-testid="documents-section-sad-pending"',
        'data-testid="documents-section-parsed-verified"',
    ):
        assert tid in src, f"Live section landmark missing: {tid}"


def test_documents_live_section_labels_use_polish_component():
    src = _src()
    # SectionLabel polish: each live section uses <SectionLabel>...
    assert "<SectionLabel>Verification Needed — Action Required</SectionLabel>" in src
    assert "<SectionLabel>SAD Pending Upload</SectionLabel>" in src
    assert "<SectionLabel>Customs Parsed / Verified</SectionLabel>" in src


def test_documents_shipments_table_filterfn_unchanged():
    src = _src()
    # Verification-needed filter still calls real ShipmentsTable filter prop
    assert "filterFn={s => s.sadStatus === 'Verification Needed'}" in src
    assert "filterFn={s => s.sadStatus === 'SAD Pending'}" in src
    assert "filterFn={s => s.sadStatus === 'Customs Parsed' || s.sadStatus === 'Customs Verified'}" in src


# ── Design preview strip present and marked ────────────────────────────────

def test_documents_preview_strip_present():
    src = _src()
    assert 'data-testid="documents-design-preview"' in src


def test_documents_preview_has_pending_badge():
    src = _src()
    assert 'data-testid="documents-preview-pending-badge"' in src


def test_documents_preview_subtabs_present():
    src = _src()
    assert 'data-testid="documents-preview-subtabs"' in src
    # The template-literal testid form is in the source
    assert 'data-testid={`documents-preview-subtab-${t.id}`}' in src
    # And each sub-tab id appears
    for tid in ("'pi'", "'pz'", "'other'"):
        assert f"id: {tid}" in src, f"Missing sub-tab id in source: {tid}"


def test_documents_preview_lanes_present():
    src = _src()
    assert 'data-testid="documents-preview-lanes"' in src
    assert 'data-testid={`documents-preview-lane-${l.id}`}' in src
    for lid in ("'draft'", "'approved'", "'posted'", "'cancelled'"):
        assert f"id: {lid}" in src, f"Missing lane id in source: {lid}"


def test_documents_preview_actions_present():
    src = _src()
    assert 'data-testid={`documents-preview-action-${b.id}`}' in src
    for aid in ("'upload_packing'", "'new_doc'"):
        assert f"id: {aid}" in src, f"Missing preview action id in source: {aid}"


# ── Preview buttons disabled and emit no network calls ─────────────────────

def test_documents_preview_buttons_disabled():
    src = _src()
    # Locate the preview block bounds and confirm guards present
    block_start = src.index('data-testid="documents-design-preview"')
    block_end   = src.index('Live customs documents', block_start)
    block = src[block_start:block_end]
    # Multiple disabled occurrences across the sub-tab + action templates
    assert block.count('disabled') >= 2
    assert 'aria-disabled="true"' in block
    assert "cursor: 'not-allowed'" in block


def test_documents_preview_buttons_no_onclick_no_fetch():
    src = _src()
    block_start = src.index('data-testid="documents-design-preview"')
    block_end   = src.index('Live customs documents', block_start)
    block = src[block_start:block_end]
    assert 'onClick' not in block, "Preview button must NOT have onClick"
    assert 'apiFetch' not in block, "Preview block must NOT call apiFetch"
    assert 'fetch(' not in block,   "Preview block must NOT call fetch()"
    assert 'dispatchEvent' not in block


def test_documents_preview_marked_pending_via_data_attr():
    src = _src()
    block_start = src.index('data-testid="documents-design-preview"')
    block_end   = src.index('Live customs documents', block_start)
    block = src[block_start:block_end]
    # Sub-tabs + actions + lanes templates each carry data-pending="true"
    assert block.count('data-pending="true"') >= 3


def test_documents_preview_lanes_show_em_dash_not_fake_count():
    src = _src()
    block_start = src.index('data-testid="documents-preview-lanes"')
    block_end   = src.index('Live customs documents', block_start)
    block = src[block_start:block_end]
    # Lane "value" slot is the literal em-dash, not a number
    assert ">—</div>" in block
    # No fake counts hardcoded in the lane template
    assert 'fontFamily: \'"DM Serif Display", serif\', lineHeight: 1 }}>5' not in block
    assert 'fontFamily: \'"DM Serif Display", serif\', lineHeight: 1 }}>12' not in block


# ── Anti-fake: no mock arrays, no invented endpoints ───────────────────────

def test_no_mock_document_arrays():
    src = _src()
    for fake in ("SAMPLE_FLOW", "MOCK_DOCS", "MOCK_FLOW", "OTHER_DOCS",
                 "fakeDocs", "FAKE_DOCS"):
        assert fake not in src, f"Mock document array leaked: {fake}"


def test_no_invented_documents_endpoints():
    src = _src()
    for ep in (
        "/api/v1/pi/upload-packing-list",
        "/api/v1/pi/",
        "/api/v1/pz/upload-packing-list",
        "/api/v1/pz/hub",
        "/api/v1/documents/hub",
        "/api/v1/documents/proforma",
        "/api/v1/documents/other",
    ):
        assert ep not in src, f"Invented Documents-Hub endpoint leaked: {ep}"


def test_no_design_mock_pz_numbers():
    src = _src()
    # Design fixtures from documents-hub.jsx used these PZ numbers
    for v in ("'PZ/2024/001234'", '"PZ/2024/001234"', "PZ/2024/000891"):
        assert v not in src, f"Mock PZ number leaked: {v}"


def test_no_design_mock_client_names():
    src = _src()
    for fake in (
        "Maison Royale SARL",
        "Atelier Lumière",
        "Crown Jewelers Ltd",
        "Patek Philippe SA",
        "Audemars Piguet",
    ):
        assert fake not in src


# ── Existing real upload flows preserved (BatchDetailPage) ─────────────────

def test_batch_detail_upload_handlers_intact():
    # BatchDetailPage's per-batch SAD upload flow now lives in
    # shipment-detail.html (moved out of dashboard.html). Verify the
    # well-known upload refs survived the move by sampling them there.
    src = _detail_src()
    assert "sadRef" in src
    assert "dhlDocsRef" in src
    assert "agencyDocsRef" in src
    assert "svcInvoiceRef" in src


def test_no_new_global_upload_handler_on_documents_page():
    src = _src()
    # The Documents page (CustomsDocumentsPage body) must NOT add a global
    # upload handler — uploads remain per-batch in BatchDetailPage
    block_start = src.index("function CustomsDocumentsPage")
    block_end   = src.index("function WfirmaExportPage")
    block = src[block_start:block_end]
    assert "apiFetch" not in block, "CustomsDocumentsPage must not call apiFetch"
    assert "FormData" not in block, "CustomsDocumentsPage must not create FormData"


# ── UI-3 landmarks still present elsewhere in dashboard.html ───────────────

def test_ui3_operational_cards_still_present():
    src = _src()
    for tid in (
        'data-testid="warehouse-operations-card"',
        'data-testid="sales-accounting-operations-card"',
        'data-testid="dhl-customs-operations-card"',
    ):
        assert tid in src


# ── DETAIL_TABS unchanged ──────────────────────────────────────────────────

def test_detail_tabs_unchanged():
    src = _src()
    assert "const DETAIL_TABS = ['Overview', 'Documents', 'DHL / Customs', 'Warehouse', 'Sales', 'PZ / Accounting', 'Timeline', 'Intelligence', 'Proposals']" in src
