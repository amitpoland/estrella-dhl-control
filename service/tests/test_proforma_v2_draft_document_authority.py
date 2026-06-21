"""
test_proforma_v2_draft_document_authority.py — Draft #38 class (frontend).

Static-contract pins for the V2 proforma-detail document + readiness authority:

  A. Documents (Packing List, CMR) render only THIS draft's billed editable_lines,
     enriched by the batch packing row by design_no/product_code — never the
     full-shipment batch packing (which spans all clients on the batch).
  B. The Reservation tab, the Overview banners, and the What's-Blocking panel
     read the canonical backend readiness (readinessPost), not the stale preview
     blocking_reasons.
  C. The Packing List carries the full required column set.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_V2 = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
_DETAIL = _V2 / "proforma-detail.jsx"
_PACKING = _V2 / "estrella-doc-packing.jsx"


@pytest.fixture(scope="module")
def detail():
    return _DETAIL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def packing():
    return _PACKING.read_text(encoding="utf-8")


# ── A. documents iterate the DRAFT's lines, enriched by packing (never batch) ──

def test_packing_list_iterates_editable_lines_not_batch(detail):
    # the row loop drives off editable_lines, not the full batch packing
    assert "const rows = _editableLines.map((ln, i) =>" in detail
    # the old batch-driven loop is gone
    assert "const rows = sortedLines.map" not in detail
    assert "[...batchPackingLines].sort" not in detail


def test_cmr_aggregates_editable_lines_not_batch(detail):
    # CMR aggregation iterates the draft's editable_lines
    assert "for (const ln of _el)" in detail
    # the old batch-wide aggregation is gone
    assert "for (const l of batchPackingLines)" not in detail


def test_enrichment_is_by_design_or_product_code_only(detail):
    # batch packing rows enrich a draft line by design_no then product_code —
    # they are never iterated to ADD document rows.
    assert "_enrichPacking" in detail
    assert "_packingByDesign" in detail and "_packingByCode" in detail
    assert "const pk        = _enrichPacking(ln);" in detail or \
           "const pk = _enrichPacking(ln);" in detail


def test_qty_and_total_come_from_draft_line(detail):
    # qty + sales price are the draft line's (billing authority); total = qty*price
    assert "const qty       = Number(ln.qty) || 0;" in detail
    assert "total_value:  unitPrice * qty," in detail


# ── B. readiness consumers use the canonical backend readiness ────────────────

def test_blocking_reasons_source_is_canonical_readiness(detail):
    # the Reservation tab / Overview banners read readinessPost.blockers, NOT the
    # stale preview.blocking_reasons.
    assert "const blockingReasons = ((readinessPost && readinessPost.blockers) || []).map(b => b.reason);" in detail
    assert "const blockingReasons = (preview && preview.blocking_reasons) || [];" not in detail
    # the export blocker list is no longer sourced from the stale preview
    assert "const exportBlockers  = (preview && preview.export_blockers)  || [];" not in detail


def test_whats_blocking_panel_drops_stale_rows(detail):
    # the panel no longer adds the stale Reservation / Export-PDF rows; the
    # canonical Post/Convert + Approve rows already carry everything.
    assert "blockingReasons.forEach(r => add(r, null, 'Reservation'));" not in detail
    assert "exportBlockers.forEach(r => add(r, null, 'Export / PDF'));" not in detail
    assert "postBlockers.forEach(b => add(b.reason, b.repair_action, 'Post / Convert'));" in detail


# ── C. Packing List required columns present ──────────────────────────────────

def test_packing_list_has_required_columns(packing):
    for header in ("Product Code", "Gross Wt", "Net Wt", "HSN", "Origin",
                   "Category", "Client PO", "Design", "Quality", "Size"):
        assert f">{header}<" in packing or f"{header}</th>" in packing or header in packing, header


def test_packing_row_renders_new_fields(packing):
    for field in ("r.product_code", "r.gross_wt", "r.net_wt", "r.hsn", "r.origin"):
        assert field in packing, field


def test_packing_builder_emits_new_fields(detail):
    for field in ("product_code:", "gross_wt:", "net_wt:", "hsn:", "origin:"):
        assert field in detail, field
