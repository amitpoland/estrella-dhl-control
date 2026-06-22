"""
test_pz_quantity_validator.py — Permanent regression guards for PZ quantity normalization.

Origin: AWB 9158478722 (SHIPMENT_9158478722_2026-06_924c4e59, Draft #38).
Product EJL/26-27/299-11 had quantity=20.5 for unit "PRS". wFirma's
warehouse_document_p_z/add returned a bare ERROR status (no description,
~525ms response = immediate validation rejection) because fractional unit
counts are invalid for physical-goods units.

Operator authorised round_half_up normalization (20.5 → 21) as the
production fix. This module prevents recurrence — any future fractional
quantity on an integer-only unit will be normalised automatically before
XML generation.

Coverage:
  1. Integer quantity → PASS unchanged, no event, no advisory
  2. Decimal + integer-only unit → round_half_up
     a. 20.5 → 21 (canonical AWB 9158478722 case, unit=PRS)
     b. 10.4 → 10 (below .5 boundary)
     c. 0.9  → 1
     d. 0.5  → 1 (not banker's rounding — .5 always rounds up)
  3. Decimal + decimal-safe unit (kg, g) → PASS unchanged
  4. Line total preserved: unit_netto_pln recalculated after normalization
  5. Audit event trail: one NormalizationEvent per normalised row
  6. Advisory message present when events exist; None when no events
  7. round_half_up table correctness
  8. Empty input → empty result
"""
from __future__ import annotations

import sys
import math
from pathlib import Path

import pytest

_svc = Path(__file__).resolve().parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))

from app.services.import_pz_builder import BatchRow
from app.services.pz_quantity_validator import (
    validate_pz_quantities,
    NormalizationEvent,
    QuantityValidationResult,
    DECIMAL_UNITS,
    _round_half_up,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _row(
    product_code:   str   = "TEST-001",
    quantity:       float = 10.0,
    unit_netto_pln: float = 100.0,
    unit:           str   = "szt.",
) -> BatchRow:
    return BatchRow(
        product_code   = product_code,
        quantity       = quantity,
        unit_netto_pln = unit_netto_pln,
        invoice_no     = "INV/001",
        description_en = "Test product",
        pl_desc        = "produkt testowy",
        item_type      = "EARRINGS",
        unit           = unit,
    )


# ── 1: Integer quantities pass unchanged ─────────────────────────────────────

def test_integer_quantity_passes_unchanged():
    row    = _row(quantity=20.0, unit="szt.")
    result = validate_pz_quantities([row])
    assert result.rows[0].quantity == 20.0
    assert result.events           == []
    assert result.advisory         is None


def test_integer_large_value_passes():
    row    = _row(quantity=100.0, unit="kpl.")
    result = validate_pz_quantities([row])
    assert result.rows[0].quantity == 100.0
    assert not result.events


# ── 2a: canonical AWB 9158478722 case ────────────────────────────────────────

def test_canonical_20_5_prs_normalises_to_21():
    """
    Exact production case: EJL/26-27/299-11, qty=20.5, unit=PRS.
    wFirma rejected this with a bare ERROR status.  Must normalise to 21.
    """
    row = _row(
        product_code   = "EJL/26-27/299-11",
        quantity       = 20.5,
        unit_netto_pln = 419.0028362979221,
        unit           = "PRS",
    )
    result = validate_pz_quantities([row])

    assert len(result.rows) == 1
    assert result.rows[0].quantity     == 21.0
    assert result.rows[0].product_code == "EJL/26-27/299-11"
    assert len(result.events)          == 1
    assert result.events[0].original_quantity   == 20.5
    assert result.events[0].normalized_quantity == 21.0


# ── 2b–2d: other decimal + integer-only cases ────────────────────────────────

def test_10_4_normalises_to_10():
    row    = _row(quantity=10.4, unit="szt.")
    result = validate_pz_quantities([row])
    assert result.rows[0].quantity == 10.0


def test_0_9_normalises_to_1():
    row    = _row(quantity=0.9, unit="pcs")
    result = validate_pz_quantities([row])
    assert result.rows[0].quantity == 1.0


def test_0_5_rounds_up_not_bankers():
    """0.5 must round to 1 (round_half_up), not to 0 (banker's rounding)."""
    row    = _row(quantity=0.5, unit="szt.")
    result = validate_pz_quantities([row])
    assert result.rows[0].quantity == 1.0


# ── 3: Decimal + decimal-safe unit → pass unchanged ──────────────────────────

def test_decimal_kg_passes_unchanged():
    row    = _row(quantity=1.5, unit="kg")
    result = validate_pz_quantities([row])
    assert result.rows[0].quantity == 1.5
    assert not result.events


def test_decimal_gram_passes_unchanged():
    row    = _row(quantity=250.75, unit="g")
    result = validate_pz_quantities([row])
    assert result.rows[0].quantity == 250.75
    assert not result.events


# ── 4: Line total preserved ───────────────────────────────────────────────────

def test_line_total_preserved_after_normalization():
    """unit_netto_pln × quantity must be invariant through normalization."""
    qty        = 20.5
    unit_price = 419.0028362979221
    line_total = qty * unit_price

    row    = _row(quantity=qty, unit_netto_pln=unit_price, unit="PRS")
    result = validate_pz_quantities([row])

    new_row   = result.rows[0]
    new_total = new_row.quantity * new_row.unit_netto_pln

    assert abs(new_total - line_total) < 1e-6, (
        f"Line total changed: was {line_total:.8f}, now {new_total:.8f}"
    )


def test_line_total_preserved_10_4_case():
    qty        = 10.4
    unit_price = 250.0
    line_total = qty * unit_price

    row    = _row(quantity=qty, unit_netto_pln=unit_price, unit="szt.")
    result = validate_pz_quantities([row])

    new_total = result.rows[0].quantity * result.rows[0].unit_netto_pln
    assert abs(new_total - line_total) < 1e-6


# ── 5: Audit event trail ──────────────────────────────────────────────────────

def test_one_event_per_normalised_row():
    rows = [
        _row("A", quantity=1.5, unit="szt."),   # normalised
        _row("B", quantity=2.0, unit="szt."),   # integer — unchanged
        _row("C", quantity=3.7, unit="kpl."),   # normalised
    ]
    result = validate_pz_quantities(rows)
    assert len(result.events) == 2
    codes = {e.product_code for e in result.events}
    assert codes == {"A", "C"}


def test_event_fields_correct():
    row    = _row("EJL-TEST", quantity=20.5, unit="PRS")
    result = validate_pz_quantities([row])
    evt    = result.events[0]

    assert evt.product_code        == "EJL-TEST"
    assert evt.original_quantity   == 20.5
    assert evt.normalized_quantity == 21.0
    assert evt.unit                == "PRS"
    assert "round_half_up"         in evt.reason


def test_no_events_when_all_pass():
    rows = [
        _row("X", quantity=5.0,   unit="szt."),
        _row("Y", quantity=10.0,  unit="kpl."),
        _row("Z", quantity=1.5,   unit="kg"),
    ]
    result = validate_pz_quantities(rows)
    assert result.events == []


# ── 6: Advisory message ───────────────────────────────────────────────────────

def test_advisory_contains_product_code_when_normalised():
    row    = _row("EJL/26-27/299-11", quantity=20.5, unit="PRS")
    result = validate_pz_quantities([row])
    assert result.advisory is not None
    assert "EJL/26-27/299-11" in result.advisory


def test_advisory_none_when_no_normalisation():
    row    = _row("CLEAN", quantity=5.0, unit="szt.")
    result = validate_pz_quantities([row])
    assert result.advisory is None


# ── 7: round_half_up correctness ─────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    (0.4,  0),
    (0.5,  1),   # .5 rounds UP (not banker's rounding)
    (1.5,  2),
    (2.5,  3),
    (10.4, 10),
    (20.5, 21),
    (99.9, 100),
])
def test_round_half_up_table(value, expected):
    assert _round_half_up(value) == expected


# ── 8: Empty input ────────────────────────────────────────────────────────────

def test_empty_input_returns_empty_result():
    result = validate_pz_quantities([])
    assert result.rows    == []
    assert result.events  == []
    assert result.advisory is None


# ── 9: unit=None fallback ─────────────────────────────────────────────────────

def test_unit_none_falls_back_to_szt_and_normalises():
    """unit=None defaults to 'szt.' (integer-only), so fractional qty must normalise."""
    row = _row("NULL-UNIT", quantity=5.7, unit_netto_pln=100.0, unit="szt.")
    row_with_none = BatchRow(
        product_code   = "NULL-UNIT",
        quantity       = 5.7,
        unit_netto_pln = 100.0,
        invoice_no     = "INV/001",
        description_en = "Test product",
        pl_desc        = "produkt testowy",
        item_type      = "EARRINGS",
        unit           = None,
    )
    result = validate_pz_quantities([row_with_none])
    # unit=None → fallback "szt." → integer-only → rounds 5.7 → 6
    assert result.rows[0].quantity == 6.0
    assert len(result.events) == 1
    assert result.events[0].unit == "szt."


# ── 10: qty rounds to zero guard ─────────────────────────────────────────────

def test_qty_rounds_to_zero_passes_unchanged():
    """qty=0.4 rounds to 0 via round_half_up — guard must pass row unchanged, not send count=0."""
    row    = _row("ZERO-GUARD", quantity=0.4, unit_netto_pln=500.0, unit="szt.")
    result = validate_pz_quantities([row])
    # Row returned unchanged (original qty preserved); no event emitted.
    assert result.rows[0].quantity == 0.4
    assert result.events == []
    assert result.advisory is None


# ── 11: NaN / non-finite guard ────────────────────────────────────────────────

def test_nan_quantity_passes_unchanged_without_raising():
    """NaN row must not raise — returned unchanged with no event."""
    import math
    row = BatchRow(
        product_code   = "NAN-TEST",
        quantity       = float("nan"),
        unit_netto_pln = 100.0,
        invoice_no     = "INV/001",
        description_en = "Test product",
        pl_desc        = "produkt testowy",
        item_type      = "EARRINGS",
        unit           = "szt.",
    )
    result = validate_pz_quantities([row])
    assert len(result.rows) == 1
    assert math.isnan(result.rows[0].quantity)
    assert result.events == []
    assert result.advisory is None


def test_inf_quantity_passes_unchanged_without_raising():
    """inf row must not raise — returned unchanged with no event."""
    row = BatchRow(
        product_code   = "INF-TEST",
        quantity       = float("inf"),
        unit_netto_pln = 100.0,
        invoice_no     = "INV/001",
        description_en = "Test product",
        pl_desc        = "produkt testowy",
        item_type      = "EARRINGS",
        unit           = "szt.",
    )
    result = validate_pz_quantities([row])
    assert len(result.rows) == 1
    assert result.events == []
