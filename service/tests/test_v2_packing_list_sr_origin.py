"""
test_v2_packing_list_sr_origin.py — Packing List SR numbering + Origin default.

Operator-reported (Draft #34): the Packing List showed duplicate/colliding SR
numbers (e.g. JR04929 → SR 9 three times, JR05671 → SR 10 twice) with gaps and
out-of-order rows, and an empty Origin column.

Root causes:
  - SR used the matched packing row's `pack_sr`, which collides when several
    billed lines map to the same design (mixed lots). A packing list must number
    its own rows sequentially (1..N from the draft's editable_lines).
  - Origin had no source (packing_lines has no origin column) → "—". Default to
    India (the goods' manufacturing origin) — the same default the CMR uses.

HSN stays "—" for EU shipments by design (operator decision 2026-06-09: HS codes
shown outside Europe only). Weights/quality/size stay "—" when the packing source
lacks them (re-upload needed) — never fabricated.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_DETAIL = (Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
           / "proforma-detail.jsx")


@pytest.fixture(scope="module")
def detail():
    return _DETAIL.read_text(encoding="utf-8")


def test_packing_list_sr_is_sequential_not_pack_sr(detail):
    # SR is the row index (i+1), NOT the colliding packing serial.
    assert "sr:           i + 1," in detail
    assert "sr:           pk.pack_sr" not in detail
    assert "sr: pk.pack_sr" not in detail


def test_sr_collision_rationale_documented(detail):
    # the comment explains why pack_sr is not used (prevents regression)
    i = detail.index("sr:           i + 1,")
    blk = detail[i - 400:i]
    assert "pack_sr collides" in blk or "collides" in blk
    assert "sequential" in blk.lower()


def test_origin_from_product_master_authority_not_hardcoded(detail):
    # 2026-07-16 authority repair: origin comes from the Product Master authority
    # (per-line ln.origin → draft-level liveDraft.origin_country, the same chain
    # the CMR goods block uses), with honest '—' when the authority has none.
    # The hardcoded UI default 'India' is removed.
    assert "origin:       ln.origin || liveDraft.origin_country || '—'," in detail
    assert "|| pk.origin || 'India'," not in detail


def test_hsn_not_fabricated_for_eu(detail):
    # HSN keeps the no-fabricate fallback ('' → renders "—"); the operator's
    # outside-Europe-only decision is documented next to it.
    assert "hsn:          ln.hs_code || pk.hs_code || ''," in detail
    hi = detail.index("hsn:          ln.hs_code")
    assert "outside Europe only" in detail[hi - 200:hi]


def test_weights_still_render_dash_when_absent(detail):
    # the >0 guards keep "—" for absent weights (no fabrication) — unchanged
    assert "Number(pk.diamond_weight) > 0 ? Number(pk.diamond_weight) : null" in detail
    assert "Number(pk.net_weight)     > 0 ? Number(pk.net_weight)     : null" in detail
