"""
pz_quantity_validator.py — Pre-PZ quantity normalization.

wFirma warehouse_document_p_z/add rejects fractional unit counts for
physical-goods unit types (szt., kpl., PRS, pcs., prs., kpl., etc.),
returning a bare ERROR status with no description (~525ms response time —
immediate validation rejection, not a transient network issue).

Origin: AWB 9158478722, product EJL/26-27/299-11, quantity=20.5, unit=PRS.
Permanent fix: normalize at the wFirma layer before XML generation.

This module:
  1. Inspects every BatchRow quantity.
  2. Integer quantities → PASS unchanged.
  3. Decimal quantity + decimal-safe unit (kg, g, l, m, …) → PASS unchanged.
  4. Decimal quantity + integer-only unit → round_half_up; recalculate
     unit_netto_pln to preserve line total (qty × unit_netto_pln).
  5. Returns normalised rows + events for audit.json and advisory responses.

Never raises — on any unexpected error the input rows are returned unchanged.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

from .import_pz_builder import BatchRow

# ── Unit type sets ────────────────────────────────────────────────────────────

# wFirma accepts fractional quantities for continuous-measure units.
# All other unit strings are treated as integer-only.
DECIMAL_UNITS: frozenset[str] = frozenset({
    "g", "kg", "t",        # mass
    "ml", "l",              # volume
    "m", "cm", "mm",        # length
    "m2", "m²",            # area
    "h", "min",             # time
})


# ── Public types ──────────────────────────────────────────────────────────────

@dataclass
class NormalizationEvent:
    product_code:        str
    original_quantity:   float
    normalized_quantity: float
    unit:                str
    reason:              str


@dataclass
class QuantityValidationResult:
    rows:     List[BatchRow]           # possibly normalised rows
    events:   List[NormalizationEvent] # one per normalised row
    advisory: Optional[str]           # human-readable summary; None if no events


# ── Implementation ────────────────────────────────────────────────────────────

def _round_half_up(value: float) -> int:
    """Round to nearest integer, .5 always rounds up (avoids banker's rounding)."""
    return math.floor(value + 0.5)


def _unit_is_decimal_safe(unit: str) -> bool:
    return unit.strip().lower().rstrip(".") in DECIMAL_UNITS


def validate_pz_quantities(rows: List[BatchRow]) -> QuantityValidationResult:
    """
    Validate and normalise PZ row quantities for wFirma compatibility.

    Rules:
      - Integer quantity                        → PASS unchanged.
      - Decimal quantity + decimal-safe unit    → PASS unchanged.
      - Decimal quantity + integer-only unit    → round_half_up; recalculate
        unit_netto_pln so line total is preserved.

    Returns QuantityValidationResult. Never raises.
    """
    normalised_rows: List[BatchRow]           = []
    events:          List[NormalizationEvent] = []

    for row in rows:
        qty  = row.quantity
        unit = row.unit or "szt."

        # Integer quantities are always valid for wFirma.
        if qty == math.floor(qty):
            normalised_rows.append(row)
            continue

        # Decimal quantity on a continuous-measure unit — leave unchanged.
        if _unit_is_decimal_safe(unit):
            normalised_rows.append(row)
            continue

        # Decimal quantity + integer-only unit → normalise.
        new_qty    = float(_round_half_up(qty))
        line_total = row.unit_netto_pln * qty

        # Preserve line total: new_unit_price × new_qty ≈ line_total.
        new_unit_price = (line_total / new_qty) if new_qty > 0 else row.unit_netto_pln

        event = NormalizationEvent(
            product_code        = row.product_code,
            original_quantity   = qty,
            normalized_quantity = new_qty,
            unit                = unit,
            reason              = (
                f"wFirma integer-only unit '{unit}': "
                f"{qty} → {new_qty} (round_half_up, line total preserved)"
            ),
        )
        events.append(event)

        normalised_row = BatchRow(
            product_code   = row.product_code,
            quantity       = new_qty,
            unit_netto_pln = new_unit_price,
            invoice_no     = row.invoice_no,
            description_en = row.description_en,
            pl_desc        = row.pl_desc,
            item_type      = row.item_type,
            unit           = row.unit,
        )
        normalised_rows.append(normalised_row)

    advisory: Optional[str] = None
    if events:
        codes    = ", ".join(e.product_code for e in events)
        advisory = f"Quantity normalised for wFirma compatibility: {codes}"

    return QuantityValidationResult(
        rows     = normalised_rows,
        events   = events,
        advisory = advisory,
    )
