"""
test_v2_packing_list_sr_origin.py — Packing List SR + commercial authority pins.

Authority (2026-08-08, extends PR #1128 commercial-document contract):
  - SR = sequential draft row number (never colliding pack_sr)
  - Origin = shared Product Master ISO on ln.origin (never hardcoded India,
    never purchase-packing origin, never phantom liveDraft.origin_country)
  - Commercial fields (client_po, quality, kt/col, size, dia/col wt, price)
    = Sales Packing via draft editable_lines
  - Gross/net g = Purchase Packing physical only
  - HSN removed from the printed commercial packing list
"""
from __future__ import annotations

from pathlib import Path

import pytest

_DETAIL = (Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
           / "proforma-detail.jsx")
_PACKING = (Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
            / "estrella-doc-packing.jsx")


@pytest.fixture(scope="module")
def detail():
    return _DETAIL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def packing_doc():
    return _PACKING.read_text(encoding="utf-8")


def test_packing_list_sr_is_sequential_not_pack_sr(detail):
    assert "const lines = (liveDraft.editable_lines || []).map((ln, i) => ({" in detail
    assert "seq:      i + 1," in detail
    assert "sr:           line.seq," in detail
    assert "sr:           pk.pack_sr" not in detail
    assert "sr: pk.pack_sr" not in detail


def test_sr_collision_rationale_documented(detail):
    i = detail.index("sr:           line.seq,")
    blk = detail[i - 400:i]
    assert "pack_sr collides" in blk or "collides" in blk
    assert "sequential" in blk.lower()


def test_origin_from_product_master_authority_not_hardcoded(detail):
    # Shared Product Master ISO on ln.origin — same as Proforma/CMR.
    assert "origin:       (ln.origin || '').trim() || '—'," in detail
    assert "liveDraft.origin_country" not in detail
    assert "|| pk.origin || 'India'," not in detail
    assert "pk.origin" not in detail.split("const packingListData")[1][:3500]


def test_hsn_removed_from_commercial_packing_list(detail, packing_doc):
    # Builder must not emit hsn; renderer must not print HSN column.
    pack_builder = detail.split("const packingListData")[1].split(
        "const draftState"
    )[0]
    assert "hsn:" not in pack_builder
    assert ">HSN<" not in packing_doc
    assert "r.hsn" not in packing_doc
    assert "colSpan={18}" in packing_doc


def test_commercial_fields_from_sales_packing_draft_line(detail):
    pack_builder = detail.split("const packingListData")[1].split(
        "const draftState"
    )[0]
    assert "ln.quality_string" in pack_builder
    assert "ln.karat" in pack_builder
    assert "ln.metal_color" in pack_builder
    assert "ln.diamond_weight" in pack_builder
    assert "ln.color_weight" in pack_builder
    assert "ln.size" in pack_builder
    assert "client_po:    (ln.client_po || '').trim()," in pack_builder
    # No purchase-packing commercial price fallback
    assert "pk.unit_price_eur" not in pack_builder
    assert "pk.quality_string" not in pack_builder


def test_physical_weights_prefer_draft_line_then_purchase_packing(detail):
    pack_builder = detail.split("const packingListData")[1].split(
        "const draftState"
    )[0]
    assert "Number(ln.gross_weight)" in pack_builder
    assert "Number(ln.net_weight)" in pack_builder
    assert "Number(pk.gross_weight)" in pack_builder
    assert "Number(pk.net_weight)" in pack_builder
