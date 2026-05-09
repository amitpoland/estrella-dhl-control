"""
test_import_pz_builder.py — unit tests for build_pz_request_from_batch.

Covers:
  1. builds PZRequest when all product_codes are mapped
  2. unresolved product_code → ready=False, pz_request=None
  3. duplicate product_code aggregates quantity
  4. conflicting unit_netto_pln → price_conflicts non-empty, ready=False
  5. description contains batch_id and MRN
  6. build does not call create_warehouse_pz (pure builder)
  7. two product_codes mapping to same good_id with matching price → aggregated correctly
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.import_pz_builder import BatchRow, build_pz_request_from_batch
from app.services.wfirma_client import PZLine, PZRequest


# ── Shared helpers ────────────────────────────────────────────────────────────

def _rows(*specs) -> list[BatchRow]:
    """Build BatchRow list from (product_code, qty, price) tuples."""
    return [
        BatchRow(product_code=pc, quantity=qty, unit_netto_pln=price)
        for pc, qty, price in specs
    ]


_MAP = {
    "EJL-013-1": "48611875",
    "EJL-013-2": "48612067",
    "EJL-013-3": "48613001",
}

_BATCH   = "TEST_BATCH_001"
_DATE    = "2026-05-01"
_MRN     = "26PL321000E0123456X7"
_CTRCT   = "38142296"
_WH      = "347088"


# ── Test 1: all mapped → ready=True, valid PZRequest ─────────────────────────

def test_builds_pz_request_when_all_mapped():
    rows = _rows(("EJL-013-1", 3.0, 173.00), ("EJL-013-2", 2.0, 176.50))
    pmap = {"EJL-013-1": "48611875", "EJL-013-2": "48612067"}

    result = build_pz_request_from_batch(
        rows=rows, contractor_id=_CTRCT, warehouse_id=_WH,
        product_map=pmap, batch_id=_BATCH, clearance_date=_DATE, mrn=_MRN,
    )

    assert result.ready is True
    assert result.unresolved_codes == []
    assert result.price_conflicts == []
    assert result.pz_request is not None

    req: PZRequest = result.pz_request
    assert req.contractor_id == _CTRCT
    assert req.warehouse_id  == _WH
    assert req.date          == _DATE

    good_ids = {ln.good_id for ln in req.lines}
    assert good_ids == {"48611875", "48612067"}

    by_gid = {ln.good_id: ln for ln in req.lines}
    assert by_gid["48611875"].count == pytest.approx(3.0)
    assert by_gid["48611875"].price == pytest.approx(173.00)
    assert by_gid["48612067"].count == pytest.approx(2.0)
    assert by_gid["48612067"].price == pytest.approx(176.50)


# ── Test 2: unresolved product_code → ready=False ────────────────────────────

def test_unresolved_product_code_blocks_readiness():
    rows = _rows(("EJL-013-1", 1.0, 100.00), ("EJL-013-UNKNOWN", 2.0, 50.00))
    pmap = {"EJL-013-1": "48611875"}   # EJL-013-UNKNOWN not in map

    result = build_pz_request_from_batch(
        rows=rows, contractor_id=_CTRCT, warehouse_id=_WH,
        product_map=pmap, batch_id=_BATCH, clearance_date=_DATE, mrn=_MRN,
    )

    assert result.ready is False
    assert "EJL-013-UNKNOWN" in result.unresolved_codes
    assert result.pz_request is None

    # planned_lines still populated for operator review
    unres_lines = [pl for pl in result.planned_lines if not pl.resolved]
    assert len(unres_lines) == 1
    assert unres_lines[0].product_code == "EJL-013-UNKNOWN"
    assert unres_lines[0].good_id is None


# ── Test 3: duplicate product_code aggregates quantity ────────────────────────

def test_duplicate_product_code_aggregates_qty():
    # Same product_code appears on two invoice rows (same price)
    rows = _rows(
        ("EJL-013-1", 2.0, 173.00),
        ("EJL-013-1", 3.0, 173.00),  # same code, same price → sum qty
    )
    pmap = {"EJL-013-1": "48611875"}

    result = build_pz_request_from_batch(
        rows=rows, contractor_id=_CTRCT, warehouse_id=_WH,
        product_map=pmap, batch_id=_BATCH, clearance_date=_DATE, mrn=_MRN,
    )

    assert result.ready is True
    assert len(result.pz_request.lines) == 1
    assert result.pz_request.lines[0].count == pytest.approx(5.0)
    assert result.pz_request.lines[0].price == pytest.approx(173.00)


# ── Test 4: conflicting price → price_conflicts, ready=False ─────────────────

def test_price_conflict_blocks_readiness():
    rows = _rows(
        ("EJL-013-1", 1.0, 173.00),
        ("EJL-013-1", 1.0, 174.99),   # same product_code, different price
    )
    pmap = {"EJL-013-1": "48611875"}

    result = build_pz_request_from_batch(
        rows=rows, contractor_id=_CTRCT, warehouse_id=_WH,
        product_map=pmap, batch_id=_BATCH, clearance_date=_DATE, mrn=_MRN,
    )

    assert result.ready is False
    assert "EJL-013-1" in result.price_conflicts
    assert result.pz_request is None


# ── Test 5: description includes batch_id and MRN ────────────────────────────

def test_description_includes_batch_id_and_mrn():
    rows  = _rows(("EJL-013-1", 1.0, 173.00))
    pmap  = {"EJL-013-1": "48611875"}
    batch = "BATCH_XYZ_2026"
    mrn   = "26PL000000TESTMRN0X7"

    result = build_pz_request_from_batch(
        rows=rows, contractor_id=_CTRCT, warehouse_id=_WH,
        product_map=pmap, batch_id=batch, clearance_date=_DATE, mrn=mrn,
    )

    assert result.ready is True
    desc = result.pz_request.description
    assert batch in desc
    assert mrn   in desc


# ── Test 6: builder never calls create_warehouse_pz ──────────────────────────

def test_builder_never_calls_create_warehouse_pz():
    rows = _rows(("EJL-013-1", 1.0, 173.00))
    pmap = {"EJL-013-1": "48611875"}

    with patch("app.services.wfirma_client.create_warehouse_pz") as mock_create:
        result = build_pz_request_from_batch(
            rows=rows, contractor_id=_CTRCT, warehouse_id=_WH,
            product_map=pmap, batch_id=_BATCH, clearance_date=_DATE, mrn=_MRN,
        )
        mock_create.assert_not_called()

    assert result.ready is True


# ── Test 7: two product_codes map to same good_id → aggregated ───────────────

def test_two_codes_same_good_id_aggregated():
    # product_codes EJL-013-1a and EJL-013-1b both map to good_id 48611875
    # (e.g. split invoice lines for same physical item, same price)
    rows  = _rows(("EJL-013-1a", 2.0, 173.00), ("EJL-013-1b", 3.0, 173.00))
    pmap  = {"EJL-013-1a": "48611875", "EJL-013-1b": "48611875"}

    result = build_pz_request_from_batch(
        rows=rows, contractor_id=_CTRCT, warehouse_id=_WH,
        product_map=pmap, batch_id=_BATCH, clearance_date=_DATE, mrn=_MRN,
    )

    assert result.ready is True
    assert len(result.pz_request.lines) == 1
    assert result.pz_request.lines[0].good_id == "48611875"
    assert result.pz_request.lines[0].count   == pytest.approx(5.0)
    assert result.pz_request.lines[0].price   == pytest.approx(173.00)
