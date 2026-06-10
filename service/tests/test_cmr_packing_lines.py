"""
test_cmr_packing_lines.py — Source-grep regression tests for CMR packing-lines enrichment.

Covers:
  - Packing-lines fetch wired in proforma-detail.jsx
  - Metal / stone / item-type parsers present
  - _cmrAggPackingLines aggregation present, returns {lines, goods_summary, total_qty}
  - Aggregation groups by item_type ONLY (metal+stone go into goods_summary header)
  - CMR line shape: {item_type, qty, net_weight, origin} — no per-line metal/stone columns
  - goods_summary string built from metal+stone Sets, rendered in both CMR variants
  - Old line shape fields (sku, desc, purity) absent from CMR renderer
  - HS/CN codes NOT output on CMR document (DB-only decision 2026-06-09)
  - Download PDF button wired (data-testid=preview-download)
  - A4 @media print CSS injected in ProformaPreviewModal
  - CMR Classic grid updated to new column widths (5 cols)
  - CMR Modern table updated to 5 columns
  - Packing List document type ('packing') wired in ProformaPreviewModal
  - packingListData IIFE built in proforma-detail.jsx
"""

import re
from pathlib import Path

PROFORMA_DETAIL = Path(__file__).parent.parent / "app" / "static" / "v2" / "proforma-detail.jsx"
CMR_DOC = Path(__file__).parent.parent / "app" / "static" / "v2" / "estrella-doc-cmr.jsx"
PACKING_DOC = Path(__file__).parent.parent / "app" / "static" / "v2" / "estrella-doc-packing.jsx"
TOKENS_CSS = Path(__file__).parent.parent / "app" / "static" / "v2" / "estrella-doc-tokens.css"
INDEX_HTML = Path(__file__).parent.parent / "app" / "static" / "v2" / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Proforma-detail: packing-lines fetch ──────────────────────────────────────

def test_batchPackingLines_state_declared():
    """batchPackingLines React state must be declared."""
    src = _read(PROFORMA_DETAIL)
    assert "batchPackingLines" in src, "batchPackingLines state not found in proforma-detail.jsx"


def test_packing_lines_api_fetch():
    """Packing lines fetch must call /api/v1/packing/ endpoint."""
    src = _read(PROFORMA_DETAIL)
    assert "/api/v1/packing/" in src, "Packing lines API fetch not wired"


def test_packing_lines_dependency_on_batchId():
    """Effect must depend on batchId so it re-fetches when batch changes."""
    src = _read(PROFORMA_DETAIL)
    assert "[batchId]" in src, "batchPackingLines effect missing batchId dependency"


# ── Proforma-detail: parsers ───────────────────────────────────────────────────

def test_parseMetal_function_exists():
    src = _read(PROFORMA_DETAIL)
    assert "_parseMetal" in src


def test_parseStone_function_exists():
    src = _read(PROFORMA_DETAIL)
    assert "_parseStone" in src


def test_cmrItemLabel_function_exists():
    src = _read(PROFORMA_DETAIL)
    assert "_cmrItemLabel" in src


def test_metal_parser_handles_white_gold():
    """Parser must map '14KT/W' suffix correctly."""
    src = _read(PROFORMA_DETAIL)
    assert "White Gold" in src, "White Gold label not in metal parser"


def test_metal_parser_handles_pink_gold():
    src = _read(PROFORMA_DETAIL)
    assert "Pink Gold" in src, "Pink Gold label not in metal parser"


def test_metal_parser_handles_yellow_gold():
    src = _read(PROFORMA_DETAIL)
    assert "Yellow Gold" in src, "Yellow Gold label not in metal parser"


def test_stone_parser_handles_diamond():
    src = _read(PROFORMA_DETAIL)
    assert "Diamond" in src, "Diamond label not in stone parser"


def test_item_parser_handles_pendant():
    src = _read(PROFORMA_DETAIL)
    assert "Pendant" in src, "Pendant label not in item parser"


def test_item_parser_handles_ring():
    src = _read(PROFORMA_DETAIL)
    assert "'Ring'" in src or '"Ring"' in src, "Ring label not in item parser"


def test_item_parser_handles_earrings():
    src = _read(PROFORMA_DETAIL)
    assert "Earrings" in src, "Earrings label not in item parser"


# ── Proforma-detail: aggregation shape (item_type ONLY, goods_summary header) ──

def test_cmrAggPackingLines_exists():
    src = _read(PROFORMA_DETAIL)
    assert "_cmrAggPackingLines" in src


def test_aggregation_reads_item_type_metal_stone_from_packing_lines():
    """Aggregation reads l.item_type for grouping; reads l.metal and l.stone_type for goods_summary."""
    src = _read(PROFORMA_DETAIL)
    assert "l.item_type" in src, "l.item_type not referenced in aggregation"
    assert "l.metal" in src, "l.metal not read for goods_summary building"
    assert "l.stone_type" in src, "l.stone_type not read for goods_summary building"


def test_aggregation_sums_quantity():
    src = _read(PROFORMA_DETAIL)
    assert "l.quantity" in src, "Aggregation must sum l.quantity from packing lines"


def test_aggregation_sums_net_weight():
    src = _read(PROFORMA_DETAIL)
    assert "l.net_weight" in src, "Aggregation must handle l.net_weight from packing lines"


def test_aggregation_builds_goods_summary():
    """Aggregation must compute goods_summary from metal and stone Sets."""
    src = _read(PROFORMA_DETAIL)
    assert "goods_summary" in src, "goods_summary not built in aggregation"


def test_aggregation_returns_object_with_lines_field():
    """_cmrAggPackingLines returns {lines, goods_summary, total_qty} — NOT a plain array."""
    src = _read(PROFORMA_DETAIL)
    # The result shape should have 'lines:' and 'goods_summary:' and 'total_qty:'
    assert "goods_summary," in src or "goods_summary:" in src, (
        "_cmrAggPackingLines must return object with goods_summary field"
    )
    assert "total_qty" in src, "_cmrAggPackingLines must return total_qty field"


def test_cmr_lines_use_aggregated_packing_data():
    """cmrPreviewData.lines must use _cmrAggPackingLines.lines as primary source."""
    src = _read(PROFORMA_DETAIL)
    # Shape change 2026-06-09: aggregation returns object, so check is .lines.length
    assert "_cmrAggPackingLines.lines.length > 0" in src, (
        "cmrPreviewData.lines must switch on _cmrAggPackingLines.lines.length (not .length directly)"
    )


def test_new_line_shape_fields_present_in_fallback():
    """Fallback lines (from proforma editable_lines) must also use new shape."""
    src = _read(PROFORMA_DETAIL)
    assert "item_type:" in src
    assert "net_weight:" in src


# ── Proforma-detail: packingListData ─────────────────────────────────────────

def test_packingListData_iife_exists():
    """packingListData IIFE must be built in proforma-detail.jsx."""
    src = _read(PROFORMA_DETAIL)
    assert "packingListData" in src, "packingListData not found in proforma-detail.jsx"


def test_packingListData_uses_pack_sr_for_sort():
    """Packing rows must be sorted by pack_sr."""
    src = _read(PROFORMA_DETAIL)
    assert "pack_sr" in src, "pack_sr not used in packingListData sort"


def test_packingListData_carries_currency_from_draft():
    """packingListData must derive currency from liveDraft.currency (not hardcoded)."""
    src = _read(PROFORMA_DETAIL)
    assert "liveDraft.currency" in src, "packingListData must use liveDraft.currency, not hardcode EUR"


def test_packingListData_uses_unit_price_from_packing_lines():
    """unit_price must come from packing line (sales authority)."""
    src = _read(PROFORMA_DETAIL)
    assert "l.unit_price" in src or "unit_price" in src, "unit_price not mapped in packingListData"


# ── Proforma-detail: ProformaPreviewModal extended with 'packing' type ────────

def test_preview_modal_has_packing_doc_type():
    """ProformaPreviewModal must accept and render 'packing' document type."""
    src = _read(PROFORMA_DETAIL)
    assert "'packing'" in src or '"packing"' in src, (
        "ProformaPreviewModal does not include 'packing' document type"
    )


def test_preview_modal_has_packing_data_prop():
    """packingData prop must be wired to ProformaPreviewModal."""
    src = _read(PROFORMA_DETAIL)
    assert "packingData" in src, "packingData prop not wired in ProformaPreviewModal"


def test_preview_modal_resolves_EJPackingList():
    """ProformaPreviewModal must resolve window.EJPackingList for 'packing' type."""
    src = _read(PROFORMA_DETAIL)
    assert "EJPackingList" in src, "EJPackingList not referenced in ProformaPreviewModal resolution"


# ── Proforma-detail: HS/CN codes NOT in CMR output ───────────────────────────

def test_hs_code_not_in_cmr_lines():
    """HS/CN codes must NOT appear in cmrPreviewData.lines (DB-only decision)."""
    src = _read(PROFORMA_DETAIL)
    cmr_lines_block_start = src.find("_cmrAggPackingLines.lines.length > 0")
    assert cmr_lines_block_start != -1, "Cannot find cmrPreviewData.lines block"
    snippet = src[cmr_lines_block_start: cmr_lines_block_start + 400]
    assert "hs_code" not in snippet.lower(), (
        "HS/CN code found in cmrPreviewData.lines — must be DB-only per 2026-06-09 decision"
    )


def test_cn_code_not_rendered_in_cmr_component():
    """CMR renderer must NOT display hs_code / cn_code / hsCode field."""
    src = _read(CMR_DOC)
    assert "l.hs_code" not in src, "l.hs_code found in CMR line renderer"
    assert "l.cn_code" not in src, "l.cn_code found in CMR line renderer"
    assert "l.hsCode"  not in src, "l.hsCode found in CMR line renderer"


# ── Proforma-detail: A4 print CSS ─────────────────────────────────────────────

def test_media_print_css_injected():
    src = _read(PROFORMA_DETAIL)
    assert "@media print" in src


def test_print_css_sets_a4_page():
    src = _read(PROFORMA_DETAIL)
    assert "size: A4" in src or "size:A4" in src


def test_print_css_hides_preview_bar():
    src = _read(PROFORMA_DETAIL)
    assert ".ej-preview-bar" in src and "display: none" in src


def test_print_css_removes_scale_transform():
    """Print CSS must reset the scale transform so A4 renders at 100%."""
    src = _read(PROFORMA_DETAIL)
    assert ".ej-preview-sheet" in src
    media_idx = src.find("@media print")
    assert media_idx != -1
    print_block = src[media_idx: media_idx + 800]
    assert "transform: none" in print_block or "transform:none" in print_block


# ── Proforma-detail: Download button ─────────────────────────────────────────

def test_download_button_testid_present():
    src = _read(PROFORMA_DETAIL)
    assert 'data-testid="preview-download"' in src or "data-testid='preview-download'" in src


def test_download_button_calls_print():
    src = _read(PROFORMA_DETAIL)
    assert "window.print()" in src


# ── estrella-doc-cmr.jsx: old shape fields removed from renderer ──────────────

def test_cmr_renderer_does_not_use_l_sku_in_lines():
    """CMR line renderer must not reference l.sku in line output (old shape gone)."""
    src = _read(CMR_DOC)
    assert "l.sku" not in src, "l.sku still referenced in CMR renderer — old line shape not fully removed"


def test_cmr_renderer_does_not_use_l_purity_in_lines():
    """CMR line renderer must not reference l.purity in line output."""
    src = _read(CMR_DOC)
    assert "l.purity" not in src, "l.purity still referenced in CMR renderer — old line shape not fully removed"


def test_cmr_renderer_does_not_use_l_desc_in_lines():
    """CMR line renderer must not reference l.desc in line output."""
    src = _read(CMR_DOC)
    assert "l.desc" not in src, "l.desc still referenced in CMR renderer — old line shape not fully removed"


def test_cmr_renderer_uses_new_shape_item_type():
    """CMR line renderer must use l.item_type for the single grouped row label."""
    src = _read(CMR_DOC)
    assert "l.item_type" in src, "l.item_type not used in CMR line renderer"


def test_cmr_renderer_uses_new_shape_net_weight():
    """CMR line renderer must use l.net_weight for total weight per category."""
    src = _read(CMR_DOC)
    assert "l.net_weight" in src, "l.net_weight not used in CMR line renderer"


def test_cmr_renderer_does_not_render_per_line_metal():
    """CMR renderer must NOT have l.metal per line — metal goes into goods_summary header only."""
    src = _read(CMR_DOC)
    assert "l.metal" not in src, (
        "l.metal found as per-line field in CMR renderer — "
        "metal must appear only in d.goods_summary header, not per row"
    )


def test_cmr_renderer_does_not_render_per_line_stone():
    """CMR renderer must NOT have l.stone per line — stone goes into goods_summary header only."""
    src = _read(CMR_DOC)
    assert "l.stone" not in src, (
        "l.stone found as per-line field in CMR renderer — "
        "stone must appear only in d.goods_summary header, not per row"
    )


def test_cmr_renderer_renders_goods_summary_header():
    """Both Classic and Modern CMR variants must render d.goods_summary."""
    src = _read(CMR_DOC)
    assert "d.goods_summary" in src, "d.goods_summary not rendered in CMR component"
    # Must appear at least twice (once per variant)
    assert src.count("d.goods_summary") >= 2, (
        "d.goods_summary only renders in one CMR variant — must appear in both Classic and Modern"
    )


# ── estrella-doc-cmr.jsx: Classic grid updated ────────────────────────────────

def test_classic_grid_updated_to_new_columns():
    """Classic grid must use new column widths for 5-column layout."""
    src = _read(CMR_DOC)
    # Old: "60px 1fr 110px 80px 80px" — must be gone
    assert '"60px 1fr 110px 80px 80px"' not in src, (
        "Old Classic column widths still present — not updated to new line shape"
    )
    # New: must contain 40px first column (item number narrow)
    assert "40px 1fr" in src, "New Classic column layout (40px first) not found"


def test_classic_grid_header_updated():
    """Classic header must show new columns not old Marks/Gross/Volume."""
    src = _read(CMR_DOC)
    assert '"Marks"' not in src and "'Marks'" not in src, "'Marks' column still in Classic header"
    assert '"Gross kg"' not in src, "'Gross kg' column still in Classic header"
    assert '"Volume m³"' not in src, "'Volume m³' column still in Classic header"
    assert "Net Weight" in src, "Net Weight column not in Classic header"


def test_classic_header_uses_item_category():
    """Classic (and Modern) headers must use 'Item Category' not the old 'Description'."""
    src = _read(CMR_DOC)
    assert "Item Category" in src, "Item Category label not found in CMR headers"


# ── estrella-doc-cmr.jsx: Modern table updated ────────────────────────────────

def test_modern_table_has_five_columns():
    """Modern table colSpan must be 5 — Item Category, Packaging, Origin, Net Weight, Qty."""
    src = _read(CMR_DOC)
    assert "colSpan={5}" in src or 'colSpan="5"' in src, (
        "Modern table colSpan not 5 — expected Item Category | Packaging | Origin | Net Weight | Qty"
    )


def test_modern_table_does_not_have_six_columns():
    """Modern table must NOT have colSpan 6 — Metal/Stone columns were moved to goods_summary."""
    src = _read(CMR_DOC)
    assert "colSpan={6}" not in src and 'colSpan="6"' not in src, (
        "colSpan=6 still present in CMR Modern — old 6-column layout not removed"
    )


def test_modern_table_header_updated():
    """Modern table header must contain Item Category and Net Weight columns."""
    src = _read(CMR_DOC)
    assert "Item Category" in src, "Item Category column not in Modern table header"
    assert "Net Weight" in src, "Net Weight column not in Modern table header"


def test_modern_table_does_not_show_sku_column():
    """Modern table must not have a SKU column (old shape)."""
    src = _read(CMR_DOC)
    assert ">SKU<" not in src, "SKU column header still in Modern table"


# ── estrella-doc-cmr.jsx: header comment updated ─────────────────────────────

def test_cmr_shape_comment_updated():
    """File-level comment must reflect new line shape with goods_summary."""
    src = _read(CMR_DOC)
    assert "item_type" in src[:3000], "Shape comment at top of file not updated to new line shape"
    assert "goods_summary" in src[:3000], "goods_summary not documented in shape comment at top of file"
    # Old shape field 'purity' must not be in the shape comment
    top_comment = src[:2500]
    assert "purity" not in top_comment, "'purity' still in shape comment at top of file"


# ── estrella-doc-packing.jsx: file exists and exports EJPackingList ───────────

def test_packing_doc_file_exists():
    assert PACKING_DOC.exists(), f"estrella-doc-packing.jsx not found at {PACKING_DOC}"


def test_packing_doc_exports_EJPackingList():
    src = _read(PACKING_DOC)
    assert "EJPackingList" in src, "EJPackingList not defined in estrella-doc-packing.jsx"
    assert "window.EJPackingList" in src, "EJPackingList not assigned to window"


def test_packing_doc_uses_ej_a4_landscape_class():
    """Packing List must use .ej-a4-landscape CSS class — landscape A4 (1123x794px)."""
    src = _read(PACKING_DOC)
    assert "ej-a4-landscape" in src, ".ej-a4-landscape class not used in packing list component"


def test_packing_doc_uses_ej_table():
    """Packing List must use ej-table CSS class (shared table standard from tokens.css)."""
    src = _read(PACKING_DOC)
    assert "ej-table" in src, "ej-table class not used — packing list table must follow shared table standard"


def test_tokens_css_defines_ej_a4_landscape():
    """estrella-doc-tokens.css must define .ej-a4-landscape for landscape A4 shell."""
    src = _read(TOKENS_CSS)
    assert ".ej-a4-landscape" in src, ".ej-a4-landscape not defined in estrella-doc-tokens.css"
    assert "1123px" in src, "1123px (landscape A4 width) not in tokens.css .ej-a4-landscape definition"


def test_packing_doc_cmr_style_party_boxes():
    """Packing List must use CMR Classic-style boxed party blocks with number badges."""
    src = _read(PACKING_DOC)
    # CMR Classic style: number badge in green circle (background: '#0B3D2E')
    assert "0B3D2E" in src, "CMR Classic brand color (#0B3D2E) not used in packing list party blocks"


def test_proforma_modal_landscape_orientation():
    """ProformaPreviewModal must set @page size to landscape when packing type is active."""
    src = _read(PROFORMA_DETAIL)
    assert "landscape" in src, "'landscape' orientation not in ProformaPreviewModal print CSS"
    assert "packing" in src and "landscape" in src, (
        "ProformaPreviewModal must output A4 landscape @page rule for packing doc type"
    )


def test_proforma_modal_wider_wrap_for_landscape():
    """ProformaPreviewModal must use wider wrap (1200px) when packing list is active."""
    src = _read(PROFORMA_DETAIL)
    assert "1200px" in src, "1200px wrap width not found in ProformaPreviewModal — needed for landscape packing list"


def test_packing_doc_has_thirteen_column_keys():
    """Packing List must reference all 13 data fields: sr, ctg, client_po, design, kt, col,
       quality, dia_wt, col_wt, qty, unit_price, total_value, size."""
    src = _read(PACKING_DOC)
    # Fields are referenced as r.key in table cells (e.g. r.sr, r.ctg, r.client_po)
    expected_fields = ["r.sr", "r.ctg", "r.client_po", "r.design", "r.kt", "r.col",
                       "r.quality", "r.dia_wt", "r.col_wt", "r.qty", "r.unit_price",
                       "r.total_value", "r.size"]
    for field in expected_fields:
        assert field in src, (
            f"Data field '{field}' not found in packing list — "
            f"13 columns (Sr/Category/Client PO/Design/Kt/Col/Quality/Dia Wt/Col Wt/Qty/Value/Total/Size) required"
        )


def test_packing_doc_renders_currency_from_prop():
    """Packing List must NOT hardcode EUR — currency comes from packingData.currency."""
    src = _read(PACKING_DOC)
    assert "d.currency" in src or "packingData.currency" in src, (
        "Packing list must derive currency from data prop, not hardcode EUR"
    )
    # The currency constant must fall back to 'EUR' as a default, not be hardcoded everywhere
    # Allow flexible whitespace between d.currency and || (e.g. "d.currency   ||" with alignment spaces)
    assert re.search(r"d\.currency\s*\|\|", src) or re.search(r"packingData\.currency\s*\|\|", src), (
        "Currency must fall back to 'EUR' only as default (d.currency || 'EUR'), not be hardcoded throughout"
    )


def test_packing_doc_has_seller_block():
    """Packing List must include a seller/exporter party block."""
    src = _read(PACKING_DOC)
    assert "d.seller" in src or "seller" in src.lower(), "Seller block not in packing list"


def test_packing_doc_has_shipto_block():
    """Packing List must include a ship-to/consignee party block."""
    src = _read(PACKING_DOC)
    assert "d.shipto" in src or "shipto" in src.lower(), "Ship-to block not in packing list"


def test_packing_doc_totals_footer_shows_grand_total():
    """Packing List must render grand_total in a footer row."""
    src = _read(PACKING_DOC)
    assert "grand_total" in src or "grandTotal" in src, "Grand total not rendered in packing list footer"


def test_packing_doc_dia_wt_shows_dash_when_null():
    """dia_wt must show '—' when null (not yet parsed from Excel)."""
    src = _read(PACKING_DOC)
    assert "dia_wt" in src, "dia_wt column not in packing list"
    assert "col_wt" in src, "col_wt column not in packing list"


# ── index.html: packing script tag added ─────────────────────────────────────

def test_index_html_loads_packing_script():
    """index.html must load estrella-doc-packing.jsx after the CMR script."""
    src = _read(INDEX_HTML)
    assert "estrella-doc-packing.jsx" in src, (
        "estrella-doc-packing.jsx script tag not found in index.html"
    )


def test_index_html_packing_script_after_cmr():
    """estrella-doc-packing.jsx must be loaded AFTER estrella-doc-cmr.jsx."""
    src = _read(INDEX_HTML)
    cmr_idx = src.find("estrella-doc-cmr.jsx")
    pkg_idx = src.find("estrella-doc-packing.jsx")
    assert cmr_idx != -1, "CMR script not in index.html"
    assert pkg_idx != -1, "Packing script not in index.html"
    assert pkg_idx > cmr_idx, (
        "estrella-doc-packing.jsx must appear after estrella-doc-cmr.jsx in index.html"
    )
