"""
test_cmr_packing_lines.py — CMR / Packing List authority after single-canonical cutover.

Canonical projection + presentation live in Python:
  - commercial_cmr._aggregate_lines / build_cmr_document
  - commercial_packing_list.build_commercial_packing_document
  - commercial_*_html + Chrome PDF

Browser Preview/Logistics consume packing-list.html / cmr.html / cmr.json —
they must NOT rebuild packingListData / cmrPreviewData locally.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.commercial_cmr import _aggregate_lines, _item_category_label

PROFORMA_DETAIL = Path(__file__).parent.parent / "app" / "static" / "v2" / "proforma-detail.jsx"
CMR_DOC = Path(__file__).parent.parent / "app" / "static" / "v2" / "estrella-doc-cmr.jsx"
PACKING_DOC = Path(__file__).parent.parent / "app" / "static" / "v2" / "estrella-doc-packing.jsx"
CMR_PY = Path(__file__).parent.parent / "app" / "services" / "commercial_cmr.py"
PACKING_PY = Path(__file__).parent.parent / "app" / "services" / "commercial_packing_list.py"
PACKING_HTML = Path(__file__).parent.parent / "app" / "services" / "commercial_packing_list_html.py"
CMR_HTML = Path(__file__).parent.parent / "app" / "services" / "commercial_cmr_html.py"
TOKENS_CSS = Path(__file__).parent.parent / "app" / "static" / "v2" / "estrella-doc-tokens.css"
INDEX_HTML = Path(__file__).parent.parent / "app" / "static" / "v2" / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Frontend: packing-lines fetch (still used for warehouse / enrichment UI) ──

def test_batchPackingLines_state_declared():
    src = _read(PROFORMA_DETAIL)
    assert "batchPackingLines" in src, "batchPackingLines state not found in proforma-detail.jsx"


def test_packing_lines_api_fetch():
    src = _read(PROFORMA_DETAIL)
    assert "/api/v1/packing/" in src, "Packing lines API fetch not wired"


def test_packing_lines_dependency_on_batchId():
    src = _read(PROFORMA_DETAIL)
    assert "[batchId]" in src, "batchPackingLines effect missing batchId dependency"


# ── Canonical CMR aggregation (Python — sole authority) ───────────────────────

def test_item_category_label_maps_common_types():
    assert _item_category_label("PND") == "Pendant" or "Pendant" in _item_category_label("PENDANT")
    assert "Ring" in _item_category_label("RNG") or _item_category_label("RING") == "Ring"
    assert "Earring" in _item_category_label("EAR") or "Earring" in _item_category_label("EARRING")


def test_aggregate_lines_groups_by_item_type_only():
    lines, summary = _aggregate_lines([
        {"item_type": "RNG", "qty": 2, "net_weight": 1.5, "origin": "IN",
         "metal": "14KT White Gold", "stone_type": "Diamond"},
        {"item_type": "RNG", "qty": 1, "net_weight": 0.5, "origin": "IN",
         "metal": "14KT Pink Gold", "stone_type": "Diamond"},
        {"item_type": "PND", "qty": 3, "net_weight": 2.0, "origin": "IN",
         "metal": "14KT Yellow Gold", "stone_type": "Ruby"},
    ])
    assert len(lines) == 2
    by_type = {r["item_type"]: r for r in lines}
    assert by_type["Ring"]["qty"] == 3
    assert by_type["Ring"]["net_weight"] == pytest.approx(2.0)
    assert by_type["Pendant"]["qty"] == 3
    assert "Diamond" in summary
    assert "White Gold" in summary or "Pink Gold" in summary
    assert "hs_code" not in by_type["Ring"]
    assert "cn_code" not in by_type["Ring"]


def test_aggregate_lines_uses_draft_qty_not_batch_invention():
    lines, _ = _aggregate_lines([{"item_type": "EAR", "qty": 4, "quantity": 99}])
    assert lines[0]["qty"] == 4


def test_cmr_py_is_sole_aggregation_authority():
    detail = _read(PROFORMA_DETAIL)
    cmr_py = _read(CMR_PY)
    assert "def _aggregate_lines" in cmr_py
    assert "goods_summary" in cmr_py
    assert "const _cmrAggPackingLines" not in detail
    assert "const cmrPreviewData" not in detail
    assert "_parseMetal" not in detail
    assert "_parseStone" not in detail


def test_frontend_consumes_canonical_cmr_projection():
    detail = _read(PROFORMA_DETAIL)
    assert "getCmrDocument" in detail
    assert "getCmrHtml" in detail
    assert "canonicalCmr" in detail
    assert "cmrData={cmrPreviewData}" not in detail


# ── Canonical Packing List (Python — sole authority) ──────────────────────────

def test_packing_list_local_projection_retired():
    detail = _read(PROFORMA_DETAIL)
    assert "const packingListData" not in detail
    assert "packingData={packingListData}" not in detail
    assert "getPackingListHtml" in detail
    assert "getPackingListDocument" in detail


def test_packing_py_carries_currency_and_unit_price():
    src = _read(PACKING_PY)
    assert '"currency"' in src or "'currency'" in src
    assert "unit_price" in src
    assert "authority" in src and "commercial_packing_list" in src


def test_packing_py_sr_is_sequential_not_pack_sr():
    src = _read(PACKING_PY)
    assert '"sr": i' in src or '"sr": i,' in src
    assert "pack_sr" not in src.split("rows.append")[1][:800]


def test_preview_modal_has_packing_doc_type():
    src = _read(PROFORMA_DETAIL)
    assert "'packing'" in src or '"packing"' in src


def test_preview_modal_uses_canonical_html_not_ej_packing():
    modal = _read(PROFORMA_DETAIL).split("function ProformaPreviewModal")[1].split(
        "function CancelDraftModal"
    )[0]
    assert "getPackingListHtml" in modal
    assert "DocVariant = window.EJPackingList" not in modal
    assert "packingData=" not in modal
    assert "srcDoc={canonHtml}" in modal or "srcDoc={canonHtml}" in modal.replace(" ", "")


def test_hs_code_not_in_canonical_cmr_lines():
    src = _read(CMR_PY)
    agg = src.split("def _aggregate_lines")[1].split("def _draft_has_insurance")[0]
    assert "hs_code" not in agg.lower()
    assert "cn_code" not in agg.lower()


def test_cn_code_not_rendered_in_cmr_html():
    src = _read(CMR_HTML)
    assert "hs_code" not in src.lower()
    assert "cn_code" not in src.lower()


# ── Print / download chrome ───────────────────────────────────────────────────

def test_media_print_css_injected():
    src = _read(PROFORMA_DETAIL)
    assert "@media print" in src


def test_print_css_sets_a4_page():
    src = _read(PROFORMA_DETAIL)
    assert "size: A4" in src or "size:A4" in src


def test_print_css_hides_preview_bar():
    src = _read(PROFORMA_DETAIL)
    assert ".ej-preview-bar" in src and "display: none" in src


def test_download_button_testid_present():
    src = _read(PROFORMA_DETAIL)
    assert 'data-testid="preview-download"' in src or "data-testid='preview-download'" in src


def test_download_packing_calls_server_pdf():
    src = _read(PROFORMA_DETAIL)
    assert "downloadPackingListPdf" in src
    assert "downloadCmrPdf" in src


# ── Historical JSX files retained but retired from Preview ────────────────────

def test_cmr_jsx_retired_from_preview_wiring():
    detail = _read(PROFORMA_DETAIL)
    assert "RETIRED" in _read(CMR_DOC)[:400]
    modal = detail.split("function ProformaPreviewModal")[1].split("function CancelDraftModal")[0]
    assert "EJCMRClassic" not in modal
    assert "EJCMRModern" not in modal


def test_packing_jsx_retired_from_preview_wiring():
    assert "RETIRED" in _read(PACKING_DOC)[:400]
    modal = _read(PROFORMA_DETAIL).split("function ProformaPreviewModal")[1].split(
        "function CancelDraftModal"
    )[0]
    assert "EJPackingList" not in modal


def test_cmr_html_is_sole_presentation():
    src = _read(CMR_HTML)
    assert "sole" in src.lower()
    assert "mirrors EJ" not in src


def test_packing_html_is_sole_presentation():
    src = _read(PACKING_HTML)
    assert "sole" in src.lower()
    assert "mirrors EJ" not in src
    assert "Item Category" in src or "ctg" in src
    assert "grand_total" in src or "Grand Total" in src


def test_packing_html_has_seller_and_shipto():
    src = _read(PACKING_HTML)
    assert "seller" in src.lower()
    assert "shipto" in src.lower() or "ship-to" in src.lower() or "Ship To" in src


def test_tokens_css_defines_ej_a4_landscape():
    src = _read(TOKENS_CSS)
    assert ".ej-a4-landscape" in src
    assert "1123px" in src


def test_proforma_modal_landscape_orientation():
    src = _read(PROFORMA_DETAIL)
    assert "landscape" in src
    assert "packing" in src and "landscape" in src


def test_proforma_modal_wider_wrap_for_landscape():
    src = _read(PROFORMA_DETAIL)
    assert "1200px" in src


def test_index_html_loads_packing_script():
    src = _read(INDEX_HTML)
    assert "estrella-doc-packing.jsx" in src


def test_index_html_packing_script_after_cmr():
    src = _read(INDEX_HTML)
    cmr_idx = src.find("estrella-doc-cmr.jsx")
    pkg_idx = src.find("estrella-doc-packing.jsx")
    assert cmr_idx != -1 and pkg_idx != -1
    assert pkg_idx > cmr_idx


# Keep historical JSX shape comments honest for archive readers
def test_cmr_shape_comment_updated():
    src = _read(CMR_DOC)
    assert "item_type" in src[:3000]
    assert "goods_summary" in src[:3000]


def test_packing_doc_file_exists():
    assert PACKING_DOC.exists()


def test_packing_doc_still_defines_ej_packing_for_archive():
    """File may still export the symbol, but Preview must not mount it."""
    src = _read(PACKING_DOC)
    assert "EJPackingList" in src
