"""
test_cmr_packing_lines.py — Source-grep regression tests for CMR packing-lines enrichment.

Covers:
  - Packing-lines fetch wired in proforma-detail.jsx
  - Metal / stone / item-type parsers present
  - _cmrAggPackingLines aggregation present with correct field names
  - CMR line shape: {item_type, metal, stone, qty, net_weight, origin}
  - Old line shape fields (sku, desc, purity) absent from CMR renderer
  - HS/CN codes NOT output on CMR document (DB-only decision 2026-06-09)
  - Download PDF button wired (data-testid=preview-download)
  - A4 @media print CSS injected in ProformaPreviewModal
  - CMR Classic grid updated to new column widths
  - CMR Modern table updated to 6 columns (was 5)
"""

import re
from pathlib import Path

PROFORMA_DETAIL = Path(__file__).parent.parent / "app" / "static" / "v2" / "proforma-detail.jsx"
CMR_DOC = Path(__file__).parent.parent / "app" / "static" / "v2" / "estrella-doc-cmr.jsx"


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


# ── Proforma-detail: aggregation ──────────────────────────────────────────────

def test_cmrAggPackingLines_exists():
    src = _read(PROFORMA_DETAIL)
    assert "_cmrAggPackingLines" in src


def test_aggregation_groups_by_item_type_metal_stone():
    """Aggregation key must include item_type, metal (field), and stone_type."""
    src = _read(PROFORMA_DETAIL)
    assert "l.item_type" in src and "l.metal" in src and "l.stone_type" in src


def test_aggregation_sums_quantity():
    src = _read(PROFORMA_DETAIL)
    assert "l.quantity" in src, "Aggregation must sum l.quantity from packing lines"


def test_aggregation_sums_net_weight():
    src = _read(PROFORMA_DETAIL)
    assert "l.net_weight" in src, "Aggregation must handle l.net_weight from packing lines"


def test_cmr_lines_use_aggregated_packing_data():
    """cmrPreviewData.lines must use _cmrAggPackingLines as primary source."""
    src = _read(PROFORMA_DETAIL)
    # The aggregated lines must appear in cmrPreviewData assignment
    assert "_cmrAggPackingLines.length > 0" in src, (
        "cmrPreviewData.lines must switch on _cmrAggPackingLines.length"
    )


def test_new_line_shape_fields_present_in_fallback():
    """Fallback lines (from proforma editable_lines) must also use new shape."""
    src = _read(PROFORMA_DETAIL)
    assert "item_type:" in src
    assert "net_weight:" in src


# ── Proforma-detail: HS/CN codes NOT in CMR output ───────────────────────────

def test_hs_code_not_in_cmr_lines():
    """HS/CN codes must NOT appear in cmrPreviewData.lines (DB-only decision)."""
    src = _read(PROFORMA_DETAIL)
    # Find the lines: block in cmrPreviewData; it should NOT contain hs_code
    # The lines mapping block is between "lines: _cmrAggPackingLines" and the closing }
    cmr_lines_block_start = src.find("lines: _cmrAggPackingLines")
    assert cmr_lines_block_start != -1, "Cannot find cmrPreviewData.lines block"
    # In the 300 chars after this point there should be no hs_code
    snippet = src[cmr_lines_block_start: cmr_lines_block_start + 400]
    assert "hs_code" not in snippet.lower(), (
        "HS/CN code found in cmrPreviewData.lines — must be DB-only per 2026-06-09 decision"
    )


def test_cn_code_not_rendered_in_cmr_component():
    """CMR renderer must NOT display hs_code / cn_code / hsCode field."""
    src = _read(CMR_DOC)
    # The renderer should not reference any hs_code or cn_code field in its line rendering
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
    # transform: none must appear in the print block
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
    # l.sku should not appear in line iteration — it's not in the new shape
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
    src = _read(CMR_DOC)
    assert "l.item_type" in src


def test_cmr_renderer_uses_new_shape_metal():
    src = _read(CMR_DOC)
    assert "l.metal" in src


def test_cmr_renderer_uses_new_shape_stone():
    src = _read(CMR_DOC)
    assert "l.stone" in src


def test_cmr_renderer_uses_new_shape_net_weight():
    src = _read(CMR_DOC)
    assert "l.net_weight" in src


# ── estrella-doc-cmr.jsx: Classic grid updated ────────────────────────────────

def test_classic_grid_updated_to_new_columns():
    """Classic grid must use new column widths for 5-column layout."""
    src = _read(CMR_DOC)
    # Old: "60px 1fr 110px 80px 80px" — must be gone
    assert '"60px 1fr 110px 80px 80px"' not in src, (
        "Old Classic column widths still present — not updated to new line shape"
    )
    # New: must contain 40px first column
    assert "40px 1fr" in src, "New Classic column layout (40px first) not found"


def test_classic_grid_header_updated():
    """Classic header must show new columns not old Marks/Gross/Volume."""
    src = _read(CMR_DOC)
    assert '"Marks"' not in src and "'Marks'" not in src, "'Marks' column still in Classic header"
    assert '"Gross kg"' not in src, "'Gross kg' column still in Classic header"
    assert '"Volume m³"' not in src, "'Volume m³' column still in Classic header"
    assert "Net Weight" in src, "Net Weight column not in Classic header"


# ── estrella-doc-cmr.jsx: Modern table updated ────────────────────────────────

def test_modern_table_has_six_columns():
    """Modern table colSpan must be 6 (was 5 — added Net Weight column)."""
    src = _read(CMR_DOC)
    assert "colSpan={6}" in src or 'colSpan="6"' in src, (
        "Modern table colSpan not updated to 6 after adding Net Weight column"
    )


def test_modern_table_header_updated():
    """Modern table header must contain Item Type, Metal, Stone, Net Weight columns."""
    src = _read(CMR_DOC)
    assert "Item Type" in src
    assert "Net Weight" in src


def test_modern_table_does_not_show_sku_column():
    """Modern table must not have a SKU column (old shape)."""
    src = _read(CMR_DOC)
    # SKU as table header should be gone; check the th content
    # The old header was: <th style={{ width: 90 }}>SKU</th>
    assert ">SKU<" not in src, "SKU column header still in Modern table"


# ── estrella-doc-cmr.jsx: header comment updated ─────────────────────────────

def test_cmr_shape_comment_updated():
    """File-level comment must reflect new line shape."""
    src = _read(CMR_DOC)
    assert "item_type" in src[:3000], "Shape comment at top of file not updated to new line shape"
    # Old shape field 'purity' must not be in the shape comment
    # (It may appear elsewhere in the file — just check the top comment area)
    top_comment = src[:2500]
    assert "purity" not in top_comment, "'purity' still in shape comment at top of file"
