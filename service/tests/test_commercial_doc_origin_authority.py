"""Shared commercial-document origin authority (Proforma / Packing / CMR / visibility).

Product Master ``product_local.origin_country`` is the sole goods-origin writer.
Documents consume the ISO code (India → IN). Absent SKUs stay blank — never invent.
"""
from __future__ import annotations

from pathlib import Path

from app.services.master_data_db import normalize_origin_country

_ROUTES = Path(__file__).resolve().parents[1] / "app" / "api" / "routes_proforma.py"
_DETAIL = (
    Path(__file__).resolve().parents[1]
    / "app" / "static" / "v2" / "proforma-detail.jsx"
)


def test_normalize_origin_country_iso_and_india():
    assert normalize_origin_country("IN") == "IN"
    assert normalize_origin_country("in") == "IN"
    assert normalize_origin_country("India") == "IN"
    assert normalize_origin_country("  india  ") == "IN"
    assert normalize_origin_country("") is None
    assert normalize_origin_country(None) is None
    assert normalize_origin_country("PL") == "PL"


def test_draft_get_does_not_invent_blank_origin_as_in():
    src = _ROUTES.read_text(encoding="utf-8")
    # Old inventing patterns must stay gone from the shared enrich index.
    assert '(_r["origin_country"] or "").strip() or "IN"' not in src
    assert 'origin_country = "IN"' not in src
    assert "normalize_origin_country" in src


def test_visibility_does_not_default_every_line_to_in():
    src = _ROUTES.read_text(encoding="utf-8")
    # Visibility projection used to start every line at IN before lookup.
    assert 'origin_country = "IN"' not in src
    assert "pl_row.origin_country or \"IN\"" not in src
    assert "pl_row.origin_country or 'IN'" not in src


def test_frontend_docs_share_ln_origin_only():
    text = _DETAIL.read_text(encoding="utf-8")
    assert "liveDraft.origin_country" not in text
    # CMR aggregate must not fall back to purchase packing origin
    cmr = text.split("const _cmrAggPackingLines")[1].split(
        "const packingListData"
    )[0]
    assert "pk.origin" not in cmr
    assert "(ln.origin || '').trim() || null" in cmr
