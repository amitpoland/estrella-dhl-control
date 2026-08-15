"""
test_v2_packing_list_sr_origin.py — Packing List SR + commercial authority pins.

Authority after single-canonical cutover (2026-08-15):
  - SR / origin / commercial fields owned by commercial_packing_list.py
  - Preview consumes packing-list.html / .json (no local packingListData)
"""
from __future__ import annotations

from pathlib import Path

import pytest

_DETAIL = (Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
           / "proforma-detail.jsx")
_PACKING_PY = (Path(__file__).resolve().parents[1] / "app" / "services"
               / "commercial_packing_list.py")
_PACKING_HTML = (Path(__file__).resolve().parents[1] / "app" / "services"
                 / "commercial_packing_list_html.py")


@pytest.fixture(scope="module")
def detail():
    return _DETAIL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def packing_py():
    return _PACKING_PY.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def packing_html():
    return _PACKING_HTML.read_text(encoding="utf-8")


def test_frontend_does_not_rebuild_packing_list(detail):
    assert "const packingListData" not in detail
    assert "getPackingListHtml" in detail
    assert "getPackingListDocument" in detail


def test_packing_list_sr_is_sequential_not_pack_sr(packing_py):
    assert '"sr": i' in packing_py or '"sr": i,' in packing_py
    rows = packing_py.split("rows.append")[1][:1200]
    assert "pack_sr" not in rows


def test_origin_from_product_master_authority_not_hardcoded(packing_py, detail):
    assert "normalize_origin_country" in packing_py
    assert "liveDraft.origin_country" not in detail
    assert "|| pk.origin || 'India'," not in packing_py
    assert '"origin": str(ln.get("origin")' in packing_py


def test_hsn_removed_from_commercial_packing_list(packing_py, packing_html):
    assert "hsn:" not in packing_py.split("rows.append")[1][:1500]
    assert ">HSN<" not in packing_html
    assert "r.hsn" not in packing_html


def test_commercial_fields_from_sales_packing_draft_line(packing_py):
    assert 'ln.get("quality_string")' in packing_py
    assert 'ln.get("karat")' in packing_py or "karat" in packing_py
    assert 'ln.get("metal_color")' in packing_py or "metal_color" in packing_py
    assert 'ln.get("diamond_weight")' in packing_py
    assert 'ln.get("color_weight")' in packing_py
    assert 'ln.get("size")' in packing_py
    assert 'ln.get("client_po")' in packing_py
    assert "pk.unit_price_eur" not in packing_py
    assert "pk.quality_string" not in packing_py


def test_physical_weights_prefer_draft_line(packing_py):
    assert 'ln.get("gross_weight")' in packing_py
    assert 'ln.get("net_weight")' in packing_py
