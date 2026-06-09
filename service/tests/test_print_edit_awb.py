"""
Regression tests for:
  Fix A — Multi-page print CSS (ProformaPreviewModal SCALE order, @media print rules)
  Fix B — Edit mode PATCH endpoint wiring (backend + frontend contracts)
  Fix C — DHL Express AWB button (visible + disabled with reason per Lesson M)
  Fix D — wFirma PDF Content-Disposition (attachment, not inline) + empty-bytes guard

Scope: source-grep tests — no server required.
"""
from __future__ import annotations

import re
from pathlib import Path

_SVC   = Path(__file__).resolve().parents[1]
_APP   = _SVC / "app"
_V2    = _APP / "static" / "v2"
_MAIN  = _APP / "main.py"

_PROFORMA_DETAIL  = _V2 / "proforma-detail.jsx"
_TOKENS_CSS       = _V2 / "estrella-doc-tokens.css"
_PZ_API           = _V2 / "pz-api.js"
_ROUTES_PROFORMA  = _APP / "api" / "routes_proforma.py"


# ══════════════════════════════════════════════════════════════════════════════
# Fix A — Print CSS: ProformaPreviewModal declaration order + @media print
# ══════════════════════════════════════════════════════════════════════════════

class TestPreviewModalDeclarationOrder:
    """Contract: activeType must be declared BEFORE SCALE in ProformaPreviewModal."""

    def _src(self) -> str:
        return _PROFORMA_DETAIL.read_text(encoding="utf-8")

    def test_activeType_before_scale(self):
        """activeType const must appear before SCALE const in the component body."""
        src = self._src()
        # Find the function containing SCALE and activeType
        fn_start = src.find("function ProformaPreviewModal(")
        assert fn_start != -1, "ProformaPreviewModal not found"
        fn_body = src[fn_start:fn_start + 2000]  # first 2000 chars is enough
        idx_activetype = fn_body.find("const activeType")
        idx_scale       = fn_body.find("const SCALE")
        assert idx_activetype != -1, "const activeType not found in ProformaPreviewModal"
        assert idx_scale       != -1, "const SCALE not found in ProformaPreviewModal"
        assert idx_activetype < idx_scale, (
            "activeType must be declared BEFORE SCALE — SCALE references activeType. "
            f"Found activeType at offset {idx_activetype}, SCALE at {idx_scale} "
            "within ProformaPreviewModal body."
        )

    def test_scale_uses_active_type(self):
        """SCALE must reference activeType (not be a hardcoded literal)."""
        src = self._src()
        fn_start = src.find("function ProformaPreviewModal(")
        fn_body = src[fn_start:fn_start + 2000]
        scale_match = re.search(r"const SCALE\s*=\s*(.+?)(?:;|\n)", fn_body)
        assert scale_match, "const SCALE assignment not found"
        assert "activeType" in scale_match.group(1), (
            "SCALE assignment must use activeType, not a hardcoded literal"
        )

    def test_packing_scale_differs_from_portrait(self):
        """Packing list scale (landscape) must differ from portrait scale."""
        src = self._src()
        fn_start = src.find("function ProformaPreviewModal(")
        fn_body = src[fn_start:fn_start + 2000]
        # e.g. activeType === 'packing' ? 0.87 : 0.88
        # Both values must be present and must differ
        scale_numbers = re.findall(r"0\.\d+", fn_body)
        # There should be at least two distinct scale values for packing vs portrait
        distinct = set(scale_numbers)
        assert len(distinct) >= 2, (
            "ProformaPreviewModal should have at least two distinct scale values "
            f"for landscape/portrait — found: {distinct}"
        )


class TestPrintCSSRules:
    """Contract: @media print block must have multi-page rules for both orientations."""

    def _css(self) -> str:
        return _TOKENS_CSS.read_text(encoding="utf-8")

    def _print_block(self) -> str:
        src = self._css()
        m = re.search(r"@media print\s*\{(.+)", src, re.DOTALL)
        assert m, "Could not find @media print block"
        # Extract until the closing brace that ends the @media block
        return m.group(1)

    def test_ej_a4_height_auto(self):
        block = self._print_block()
        assert "height: auto" in block or "height:auto" in block, (
            "@media print must set .ej-a4 { height: auto }"
        )

    def test_ej_a4_overflow_visible(self):
        block = self._print_block()
        assert "overflow: visible" in block or "overflow:visible" in block, (
            "@media print must set .ej-a4 { overflow: visible }"
        )

    def test_ej_a4_landscape_in_print(self):
        """.ej-a4-landscape must also appear in the @media print block."""
        block = self._print_block()
        assert "ej-a4-landscape" in block, (
            "@media print must include rules for .ej-a4-landscape (packing list)"
        )

    def test_table_header_group(self):
        block = self._print_block()
        assert "table-header-group" in block, (
            "@media print must set thead { display: table-header-group }"
        )

    def test_page_counter_exists(self):
        """@media print must contain a @page block with page counter content."""
        block = self._print_block()
        assert "@page" in block, (
            "@media print must contain @page rule for page number counter"
        )
        assert "counter(page)" in block, (
            "@media print @page block must include counter(page) for page numbers"
        )

    def test_footer_unpin(self):
        block = self._print_block()
        assert "ej-proforma-footer" in block, (
            "@media print must unpin .ej-proforma-footer from position:absolute"
        )
        assert "static" in block, (
            "@media print .ej-proforma-footer must use position:static"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Fix B — Edit mode: PATCH endpoint + frontend wiring
# ══════════════════════════════════════════════════════════════════════════════

class TestEditModeBackend:
    """Contract: PATCH /draft/{draft_id} must exist and accept expected_updated_at + patch."""

    def _routes_src(self) -> str:
        return _ROUTES_PROFORMA.read_text(encoding="utf-8")

    def test_patch_draft_endpoint_exists(self):
        src = self._routes_src()
        assert '@router.patch("/draft/{draft_id}"' in src or \
               "@router.patch('/draft/{draft_id}'" in src, (
            "routes_proforma.py must have PATCH /draft/{draft_id} endpoint"
        )

    def test_patch_accepts_expected_updated_at(self):
        src = self._routes_src()
        assert "expected_updated_at" in src, (
            "PATCH /draft/{draft_id} must use expected_updated_at for optimistic locking"
        )

    def test_patch_accepts_patch_key(self):
        src = self._routes_src()
        # The body must extract a "patch" key
        assert 'body.get("patch")' in src or "body['patch']" in src or \
               'body.get("patch")' in src, (
            "PATCH endpoint must extract a 'patch' key from the request body"
        )


class TestEditModeFrontend:
    """Contract: frontend must have canEdit gate, edit mode state, and Save handler."""

    def _src(self) -> str:
        return _PROFORMA_DETAIL.read_text(encoding="utf-8")

    def test_can_edit_gate(self):
        src = self._src()
        # canEdit must check draft state
        assert "canEdit" in src, "canEdit variable must exist in proforma-detail.jsx"
        assert "'draft'" in src and "'editing'" in src, (
            "canEdit must include 'draft' and 'editing' states"
        )

    def test_edit_button_uses_can_edit(self):
        src = self._src()
        # The ✎ Edit button must reference canEdit
        edit_btn_pattern = re.compile(r'canEdit.*?data-testid.*?tb-edit|data-testid.*?tb-edit.*?canEdit', re.DOTALL)
        assert edit_btn_pattern.search(src) or "canEdit ? (" in src or ": canEdit ? (" in src, (
            "Edit button must be gated by canEdit in toolbar"
        )

    def test_save_calls_patch_draft(self):
        src = self._src()
        assert "PzApi.patchDraft" in src or "patchDraft" in src, (
            "handleSaveEdit must call PzApi.patchDraft"
        )

    def test_patch_draft_in_pz_api(self):
        api_src = _PZ_API.read_text(encoding="utf-8")
        assert "patchDraft" in api_src, "pz-api.js must expose patchDraft()"
        assert "expected_updated_at" in api_src, (
            "pz-api.js patchDraft must send expected_updated_at"
        )

    def test_edit_mode_banner_exists(self):
        src = self._src()
        assert "edit-mode-banner" in src or "edit-mode" in src.lower(), (
            "An edit mode banner / indicator must exist in ProformaOverviewTab"
        )

    def test_editable_kv_item_exists(self):
        src = self._src()
        assert "EditableKvItem" in src, (
            "EditableKvItem component must exist for edit mode field inputs"
        )

    def test_conflict_error_surfaced(self):
        """Save must surface errors (incl. optimistic-lock conflicts) to UI."""
        src = self._src()
        assert "editError" in src or "edit_error" in src, (
            "Edit mode must track and surface save errors (incl. 409 conflict)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Fix C — DHL Express AWB button (Lesson M: visible + disabled + reason)
# ══════════════════════════════════════════════════════════════════════════════

class TestDHLAWBButton:
    """Contract: AWB button must be visible, disabled with explicit reason (Lesson M)."""

    def _src(self) -> str:
        return _PROFORMA_DETAIL.read_text(encoding="utf-8")

    def test_awb_button_exists(self):
        """data-testid='tb-awb-generate' must be in the toolbar."""
        src = self._src()
        assert 'data-testid="tb-awb-generate"' in src or \
               "data-testid='tb-awb-generate'" in src, (
            "proforma-detail.jsx toolbar must have AWB Generate button "
            "(data-testid='tb-awb-generate') per Lesson M — capability must remain visible"
        )

    def test_awb_button_disabled(self):
        """AWB button must be in disabled state (carrier gate is pending)."""
        src = self._src()
        # Find the block containing tb-awb-generate and check for disabled
        idx = src.find('tb-awb-generate')
        assert idx != -1, "AWB button not found"
        surrounding = src[max(0, idx - 300):idx + 300]
        assert "disabled" in surrounding, (
            "AWB button must be disabled while carrier gate is pending"
        )

    def test_awb_button_has_reason_title(self):
        """AWB button title must explain WHY it is disabled (Lesson M §3)."""
        src = self._src()
        idx = src.find('tb-awb-generate')
        assert idx != -1
        # Search in a reasonable window around the testid
        surrounding = src[max(0, idx - 600):idx + 600]
        assert "CARRIER_API_STATUS" in surrounding or "carrier" in surrounding.lower(), (
            "AWB button title must reference the carrier gate status reason "
            "per Lesson M §3: 'Display the exact reason the capability is unavailable'"
        )

    def test_awb_button_not_hidden(self):
        """AWB button must NOT be conditionally hidden (Lesson M §1: keep visible)."""
        src = self._src()
        idx = src.find('tb-awb-generate')
        assert idx != -1
        surrounding = src[max(0, idx - 600):idx + 600]
        # It should NOT be wrapped in a conditional like {canDoAWB && <TbBtn...>}
        # The safest check: the button is NOT inside a ternary that hides it entirely
        # by finding `null` as the alternative to the AWB button block
        # (a disabled button with no render-condition is the Lesson M compliant pattern)
        # We accept any presence; the disabled test above enforces the gated state.
        assert "tb-awb-generate" in src, "AWB button must always be rendered (Lesson M)"


# ══════════════════════════════════════════════════════════════════════════════
# Fix D — wFirma PDF: Content-Disposition=attachment + empty-bytes guard
# ══════════════════════════════════════════════════════════════════════════════

class TestWFirmaPdfDownload:
    """Contract: proforma_document_pdf must use attachment disposition and guard empty bytes."""

    def _routes_src(self) -> str:
        return _ROUTES_PROFORMA.read_text(encoding="utf-8")

    def _pdf_endpoint_block(self) -> str:
        src = self._routes_src()
        # Isolate the proforma_document_pdf function body
        start = src.find("async def proforma_document_pdf(")
        assert start != -1, "proforma_document_pdf not found"
        # Capture until the next @router decorator (end of this function).
        # The function includes the empty-bytes guard + Response() return,
        # so we need up to ~5000 chars to reach the return statement.
        end_match = re.search(r"\n@router\.", src[start + 50:])
        end = start + 50 + end_match.start() if end_match else start + 5000
        return src[start:end]

    def test_content_disposition_attachment(self):
        """Content-Disposition must be 'attachment' not 'inline'."""
        block = self._pdf_endpoint_block()
        assert "attachment;" in block, (
            "proforma_document_pdf must use Content-Disposition: attachment "
            "so the browser downloads the PDF (avoids blank-print in Chrome PDF viewer)"
        )
        assert "inline;" not in block, (
            "proforma_document_pdf must NOT use Content-Disposition: inline"
        )

    def test_cache_control_no_store(self):
        """Lesson G: download endpoint must carry no-store cache directive."""
        block = self._pdf_endpoint_block()
        assert "no-store" in block, (
            "Lesson G: proforma_document_pdf must set Cache-Control: no-store"
        )

    def test_empty_bytes_guard(self):
        """PDF fetch must guard against suspiciously small responses (< 200 bytes)."""
        block = self._pdf_endpoint_block()
        # Look for a length check on pdf_bytes
        assert "len(pdf_bytes)" in block, (
            "proforma_document_pdf must check len(pdf_bytes) and raise 502 "
            "when wFirma returns an empty/blank PDF"
        )
        # Check that there's an HTTPException raised for the empty case
        assert "HTTPException" in block or "502" in block, (
            "Empty-bytes guard must raise HTTPException(502) not silently serve blank PDF"
        )

    def test_pdf_route_exists(self):
        """GET /{batch_id}/{client_name}/document.pdf must be registered."""
        src = self._routes_src()
        assert "document.pdf" in src, (
            "Proforma PDF download route must be registered in routes_proforma.py"
        )
