"""
test_proforma_wireframe_s5_line_ops.py — PFW-S5: Items tab line operations.

Source-grep pins for the edit-mode line operations wired to the EXISTING
draft-line authority (POST/PATCH/DELETE /draft/{id}/lines). No new endpoints,
no new authority — the pins assert the wiring uses the sanctioned transport
methods, respects the EDITABLE_LINE_FIELDS whitelist (qty/unit_price only —
variant identity stays reset-refreshed), and keeps the honest guards.
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "app" / "static" / "v2"
JSX = STATIC / "proforma-detail.jsx"
API = STATIC / "pz-api.js"


def _src() -> str:
    return JSX.read_text(encoding="utf-8")


def test_line_ops_use_existing_transport():
    src = _src()
    for call in ("PzApi.addDraftLine(", "PzApi.patchDraftLine(", "PzApi.deleteDraftLine("):
        assert call.replace("PzApi.", "window.PzApi.") in src, \
            f"Items tab must call the existing transport method {call}"
    # No raw fetch to the lines endpoints from the page (transport-only rule).
    assert not re.search(r"apiFetch\([^)]*'/draft/\$\{[^}]+\}/lines", src), \
        "line ops must go through PzApi, not raw apiFetch"


def test_delete_transport_carries_occ_token():
    api = API.read_text(encoding="utf-8")
    m = re.search(r"deleteDraftLine:\s*\(draftId, lineId, updatedAt, force\)", api)
    assert m, "deleteDraftLine must accept (draftId, lineId, updatedAt, force)"
    assert "expected_updated_at=" in api, \
        "deleteDraftLine must pass expected_updated_at as a query param"


def test_line_ops_edit_mode_gated():
    src = _src()
    assert "const lineOpsEnabled = !!(editMode && draftId)" in src, \
        "line ops must be gated on editMode + draftId"
    # The call site gates on canEdit too (posted/locked drafts stay read-only).
    assert re.search(r"ProformaLinesTab[\s\S]{0,500}?editMode=\{editMode && canEdit\}", src), \
        "call site must pass editMode={editMode && canEdit}"


def test_line_ops_whitelist_respected():
    """Only qty + unit_price are patchable inline; variant identity fields must
    NOT gain inline inputs (EDITABLE_LINE_FIELDS pin + ADR)."""
    src = _src()
    block = src[src.index("function ProformaLinesTab("):]
    block = block[:block.index("\n// ── Customer Mapping tab")] if "\n// ── Customer Mapping tab" in block else block
    for allowed in ("patch.qty = ", "patch.unit_price = "):
        assert allowed in block, f"inline patch must support {allowed.strip()}"
    for forbidden in ("patch.karat", "patch.metal_color", "patch.quality_string",
                      "patch.size", "patch.diamond_weight", "patch.stone_type"):
        assert forbidden not in block, \
            f"{forbidden} is not whitelisted — variant identity is reset-refreshed, never inline-patched"


def test_delete_never_forces_last_line():
    src = _src()
    assert re.search(r"deleteDraftLine\(draftId, line\.lineId, expectedUpdatedAt, false\)", src), \
        "row delete must pass force=false — removing the last line errors honestly"


def test_add_line_uses_product_options_picker():
    src = _src()
    assert "window.PzApi.getProductOptions()" in src, \
        "add-line picker must read the existing product-options authority"
    for tid in ("pf-add-line-row", "pf-add-line-product", "pf-add-line-qty",
                "pf-add-line-price", "pf-add-line-submit"):
        assert f'"{tid}"' in src, f"add-line testid {tid} missing"


def test_row_op_testids_present():
    src = _src()
    for tid in ("pf-line-qty-${i}", "pf-line-price-${i}", "pf-line-save-${i}",
                "pf-line-delete-${i}", "pf-line-err-${i}"):
        assert tid in src, f"row-op dynamic testid {tid} missing"


def test_every_op_reloads_draft():
    """OCC discipline: each successful op calls onChanged() so the next op
    carries the server's fresh expected_updated_at."""
    src = _src()
    block = src[src.index("function ProformaLinesTab("):]
    assert block.count("onChanged && onChanged()") >= 3, \
        "add, save, and delete must each reload the draft on success"
