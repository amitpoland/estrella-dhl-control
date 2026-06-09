"""
Regression tests for packing list field mapping and print CSS contracts.

Four contracts:
  A. Size comes from `size` field, never from `scan_code`.
  B. Quality / Dia Wt / Col Wt are present in packing API response and
     reach the packingListData passed to the packing list renderer.
  C. /v2/* static handler returns no-cache headers for .jsx AND .css.
  D. Print CSS: .ej-a4 must not have overflow:hidden in @media print context
     (i.e., the @media print block must set height:auto and overflow:visible).

Origin: 2026-06-09 packing field mapping fix (SHA 066a8ac).
  - size was incorrectly using scan_code (barcode key)
  - diamond_weight, color_weight, quality_string were silently dropped
  - print pagination broke because .ej-a4 had height:1123px; overflow:hidden
  - CSS was cached for 1 hour (max-age=3600); fixed to no-store for /v2/*.css
"""
from __future__ import annotations

import re
from pathlib import Path

# ── paths ──────────────────────────────────────────────────────────────────────
_SVC  = Path(__file__).resolve().parents[1]
_APP  = _SVC / "app"
_V2   = _APP / "static" / "v2"
_MAIN = _APP / "main.py"

_PROFORMA_DETAIL = _V2 / "proforma-detail.jsx"
_TOKENS_CSS      = _V2 / "estrella-doc-tokens.css"
_PROFORMA_DOC    = _V2 / "estrella-doc-proforma.jsx"


# ══════════════════════════════════════════════════════════════════════════════
# A — Size field: must NOT use scan_code, MUST use l.size
# ══════════════════════════════════════════════════════════════════════════════

class TestSizeFieldMapping:
    """Contract A: size must come from the 'size' DB column, never scan_code."""

    def _src(self) -> str:
        return _PROFORMA_DETAIL.read_text(encoding="utf-8")

    def test_size_uses_size_field(self):
        """size property must be mapped to l.size (or l['size'])."""
        src = self._src()
        # Must contain l.size assignment (not scan_code)
        assert "l.size" in src or "l['size']" in src or 'l["size"]' in src, (
            "proforma-detail.jsx: size mapping must read from l.size, not scan_code"
        )

    def test_size_does_not_use_scan_code(self):
        """size: must NOT be assigned from scan_code anywhere in the packingListData builder."""
        src = self._src()
        # Find the packing row builder block — look for size: assignment with scan_code value
        # Pattern: size: ... scan_code
        bad_pattern = re.compile(r"size\s*:\s*[^\n,]*scan_code", re.IGNORECASE)
        assert not bad_pattern.search(src), (
            "proforma-detail.jsx: size field must not be sourced from scan_code"
        )

    def test_scan_code_not_used_for_display(self):
        """scan_code must not be the value supplied to a display field called 'size'."""
        src = self._src()
        # Any line that says: size: l.scan_code  or  size: ... scan_code (as value)
        lines = src.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("size:") and "scan_code" in stripped:
                raise AssertionError(
                    f"proforma-detail.jsx line {i+1}: 'size' field sourced from scan_code: {stripped!r}"
                )


# ══════════════════════════════════════════════════════════════════════════════
# B — Quality / Dia Wt / Col Wt field wiring
# ══════════════════════════════════════════════════════════════════════════════

class TestPackingDisplayFields:
    """Contract B: diamond_weight, color_weight, quality_string must be wired
    from the DB field names through to the renderer."""

    def _src(self) -> str:
        return _PROFORMA_DETAIL.read_text(encoding="utf-8")

    def test_diamond_weight_mapped(self):
        src = self._src()
        assert "diamond_weight" in src, (
            "proforma-detail.jsx: diamond_weight field must be referenced in packing renderer"
        )

    def test_color_weight_mapped(self):
        src = self._src()
        assert "color_weight" in src, (
            "proforma-detail.jsx: color_weight field must be referenced in packing renderer"
        )

    def test_quality_string_mapped(self):
        src = self._src()
        assert "quality_string" in src, (
            "proforma-detail.jsx: quality_string must be referenced in packing renderer"
        )

    def test_dia_wt_reads_from_diamond_weight(self):
        """dia_wt display field must source from l.diamond_weight."""
        src = self._src()
        # Look for: dia_wt: ... diamond_weight
        assert re.search(r"dia_wt\s*:.*diamond_weight", src), (
            "proforma-detail.jsx: dia_wt display field must read from l.diamond_weight"
        )

    def test_col_wt_reads_from_color_weight(self):
        """col_wt display field must source from l.color_weight."""
        src = self._src()
        assert re.search(r"col_wt\s*:.*color_weight", src), (
            "proforma-detail.jsx: col_wt display field must read from l.color_weight"
        )

    def test_quality_not_null_null(self):
        """Quality must not be hardcoded to null — that was the broken state."""
        src = self._src()
        # Broken pattern: dia_wt: null (literal null assignment, not conditional)
        broken = re.compile(r"(dia_wt|col_wt)\s*:\s*null\s*,\s*//.*not parsed")
        assert not broken.search(src), (
            "proforma-detail.jsx: dia_wt/col_wt must not be hardcoded to null with 'not parsed' comment"
        )


# ══════════════════════════════════════════════════════════════════════════════
# C — Static cache headers for /v2/* JSX and CSS
# ══════════════════════════════════════════════════════════════════════════════

class TestV2StaticCacheHeaders:
    """Contract C: /v2/* handler must serve .jsx AND .css with no-cache headers."""

    def _main_src(self) -> str:
        return _MAIN.read_text(encoding="utf-8")

    def test_v2_handler_nocache_includes_css(self):
        """The /v2/* handler must include .css in its no-cache suffix list."""
        src = self._main_src()
        # Find the v2 handler block — look for the suffix tuple that includes .jsx
        # The fix adds ".css" to the tuple alongside ".html", ".js", ".jsx"
        v2_block_match = re.search(
            r'serve_v2_static.*?return Response\(',
            src, re.DOTALL
        )
        assert v2_block_match, "Could not find serve_v2_static handler in main.py"
        v2_block = v2_block_match.group(0)
        assert '".css"' in v2_block or "'.css'" in v2_block, (
            "main.py serve_v2_static: .css must be in the no-cache suffix list. "
            "estrella-doc-tokens.css carries print CSS and must never be cached."
        )

    def test_v2_handler_nocache_includes_jsx(self):
        """The /v2/* handler must keep .jsx in its no-cache suffix list."""
        src = self._main_src()
        v2_block_match = re.search(
            r'serve_v2_static.*?return Response\(',
            src, re.DOTALL
        )
        assert v2_block_match, "Could not find serve_v2_static handler in main.py"
        v2_block = v2_block_match.group(0)
        assert '".jsx"' in v2_block or "'.jsx'" in v2_block, (
            "main.py serve_v2_static: .jsx must remain in the no-cache suffix list."
        )

    def test_v2_handler_no_store_directive(self):
        """The /v2/* no-cache response must include 'no-store'."""
        src = self._main_src()
        v2_block_match = re.search(
            r'serve_v2_static.*?return Response\(',
            src, re.DOTALL
        )
        assert v2_block_match
        v2_block = v2_block_match.group(0)
        assert "no-store" in v2_block, (
            "main.py serve_v2_static: Cache-Control header must include no-store"
        )


# ══════════════════════════════════════════════════════════════════════════════
# D — Print CSS: no overflow:hidden in @media print
# ══════════════════════════════════════════════════════════════════════════════

class TestPrintCSS:
    """Contract D: @media print block must fix the A4 page container for multi-page output."""

    def _css(self) -> str:
        return _TOKENS_CSS.read_text(encoding="utf-8")

    def test_print_block_exists(self):
        src = self._css()
        assert "@media print" in src, (
            "estrella-doc-tokens.css: @media print block is missing"
        )

    def _print_block(self) -> str:
        src = self._css()
        m = re.search(r"@media print\s*\{(.+?)(?=\n\})", src, re.DOTALL)
        assert m, "Could not extract @media print block from estrella-doc-tokens.css"
        return m.group(1)

    def test_ej_a4_height_auto_in_print(self):
        """@media print must override .ej-a4 height to auto (removes 1123px clip)."""
        block = self._print_block()
        assert "height: auto" in block or "height:auto" in block, (
            "@media print block must set .ej-a4 { height: auto } to allow multi-page flow"
        )

    def test_ej_a4_overflow_visible_in_print(self):
        """@media print must set overflow:visible on .ej-a4 (removes hidden clip)."""
        block = self._print_block()
        assert "overflow: visible" in block or "overflow:visible" in block, (
            "@media print block must set .ej-a4 { overflow: visible } — overflow:hidden clips page 2+"
        )

    def test_table_header_group_in_print(self):
        """@media print must use display:table-header-group to repeat <thead> on every page."""
        block = self._print_block()
        assert "table-header-group" in block, (
            "@media print must set thead { display: table-header-group } for column header repeat"
        )

    def test_ej_a4_no_overflow_hidden_in_base(self):
        """Base .ej-a4 rule must have overflow:hidden (the print block overrides it)."""
        src = self._css()
        # Outside @media print the base rule should have overflow:hidden
        base_match = re.search(r"\.ej-a4\s*\{([^}]+)\}", src)
        assert base_match, "Could not find base .ej-a4 rule"
        base_block = base_match.group(1)
        # The BASE should have overflow:hidden — the @media print overrides it
        assert "overflow: hidden" in base_block or "overflow:hidden" in base_block, (
            "Base .ej-a4 should have overflow:hidden (the @media print block overrides it to visible)"
        )

    def test_proforma_footer_class_present(self):
        """estrella-doc-proforma.jsx must apply ej-proforma-footer class for print unpinning."""
        src = _PROFORMA_DOC.read_text(encoding="utf-8")
        assert "ej-proforma-footer" in src, (
            "estrella-doc-proforma.jsx: ej-proforma-footer class must be present on the seller footer div "
            "so @media print can unpin it from position:absolute"
        )

    def test_footer_unpin_in_print_css(self):
        """@media print must unpin .ej-proforma-footer from absolute positioning."""
        block = self._print_block()
        assert "ej-proforma-footer" in block, (
            "@media print block must include .ej-proforma-footer { position: static } rule"
        )
        assert "static" in block, (
            "@media print .ej-proforma-footer must set position:static to unpin from page 1"
        )
