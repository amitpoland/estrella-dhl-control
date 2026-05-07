"""
import_pz_builder.py — Build wFirma PZRequest directly from PZ app engine output.

This is the clean-architecture path: import PZ calculation → wFirma warehouse PZ.
It replaces the recovery workaround that derived the PZ from a sales proforma.

Input shape
-----------
  BatchRow: one output row from process_batch() / pz_rows.json / XLSX Rows sheet.
  product_map: dict[product_code → wfirma_good_id] — from wfirma_products table.

Output
------
  BatchBuildResult:
    pz_request           — PZRequest ready for create_warehouse_pz() (may be None if unresolved)
    planned_lines        — preview rows (always populated, including unresolved ones)
    unresolved_codes     — product_codes with no entry in product_map
    price_conflicts      — product_codes with conflicting unit_netto_pln across rows
    ready                — True only when unresolved_codes and price_conflicts are both empty

Rules
-----
  - Aggregate by wfirma_good_id (grouped by good_id after resolving product_code mapping)
  - count  = sum(quantity)
  - price  = unit_netto_pln (landed cost per unit: FOB + allocated freight + allocated A00 duty)
  - Price conflict = same product_code → same good_id but different unit_netto_pln across rows
  - description includes batch_id and MRN so the PZ is traceable back to the import event
  - Never calls create_warehouse_pz; pure builder/preview only
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date
from typing import Dict, List, Optional

__all__ = [
    "BatchRow",
    "PlannedLine",
    "BatchBuildResult",
    "build_pz_request_from_batch",
]


@dataclass
class BatchRow:
    """One engine output row as consumed by this builder."""
    product_code:    str
    quantity:        float
    unit_netto_pln:  float
    invoice_no:      str   = ""
    description_en:  str   = ""
    pl_desc:         str   = ""
    item_type:       str   = ""
    unit:            str   = "szt."


@dataclass
class PlannedLine:
    """One line in the preview — includes mapping status."""
    product_code:   str
    good_id:        Optional[str]   # None = unresolved
    count:          float
    price_pln:      float
    description:    str
    resolved:       bool


@dataclass
class BatchBuildResult:
    planned_lines:    List[PlannedLine]
    unresolved_codes: List[str]           # product_codes missing from product_map
    price_conflicts:  List[str]           # product_codes with inconsistent unit_netto_pln
    ready:            bool                # True only when both lists are empty
    pz_request:       object              # PZRequest | None (None when not ready)


def build_pz_request_from_batch(
    rows:           List[BatchRow],
    contractor_id:  str,
    warehouse_id:   str,
    product_map:    Dict[str, str],   # product_code → wfirma_good_id
    batch_id:       str,
    clearance_date: Optional[str] = None,
    mrn:            str = "",
) -> BatchBuildResult:
    """
    Build a PZRequest (and preview) from PZ engine rows.

    Parameters
    ----------
    rows           : engine output rows (product_code, quantity, unit_netto_pln)
    contractor_id  : wFirma import supplier contractor id
    warehouse_id   : wFirma warehouse id (e.g. "347088")
    product_map    : product_code → wfirma_good_id (from wfirma_products table)
    batch_id       : internal batch identifier — included in PZ description
    clearance_date : ISO date string from SAD clearance_date; defaults to today
    mrn            : customs MRN — included in PZ description and used as dedup key

    Returns
    -------
    BatchBuildResult with pz_request=None when not ready.
    """
    from .wfirma_client import PZLine, PZRequest  # deferred to avoid circular import

    doc_date = clearance_date or _date.today().isoformat()

    # ── Pass 1: aggregate by product_code first ───────────────────────────────
    agg_qty:   Dict[str, float] = {}
    agg_price: Dict[str, float] = {}   # must be consistent per product_code
    conflicts: List[str] = []
    name_map:  Dict[str, str] = {}     # product_code → display name

    for row in rows:
        pc = row.product_code
        if not pc:
            continue
        qty   = float(row.quantity)
        price = float(row.unit_netto_pln)

        if pc in agg_price:
            if abs(agg_price[pc] - price) > 1e-4:
                if pc not in conflicts:
                    conflicts.append(pc)
        else:
            agg_price[pc] = price

        agg_qty[pc]  = agg_qty.get(pc, 0.0) + qty
        name_map[pc] = (row.pl_desc or row.description_en or row.item_type or pc).strip()

    # ── Pass 2: resolve product_code → good_id ────────────────────────────────
    unresolved: List[str] = []
    # good_id → aggregated (count, price) — aggregate further if multiple product_codes
    # map to the same good_id (e.g. same physical product from different invoice lines)
    good_agg_qty:   Dict[str, float] = {}
    good_agg_price: Dict[str, float] = {}
    good_name:      Dict[str, str]   = {}

    planned: List[PlannedLine] = []

    for pc, qty in agg_qty.items():
        price  = agg_price[pc]
        gid    = product_map.get(pc)
        name   = name_map[pc]

        if gid is None:
            unresolved.append(pc)
            planned.append(PlannedLine(
                product_code=pc, good_id=None, count=qty,
                price_pln=price, description=name, resolved=False,
            ))
            continue

        # Two product_codes mapping to same good_id — prices must also match
        if gid in good_agg_price and abs(good_agg_price[gid] - price) > 1e-4:
            if pc not in conflicts:
                conflicts.append(pc)
            # Still record as planned (unresolved due to conflict) but mark unresolved
            planned.append(PlannedLine(
                product_code=pc, good_id=gid, count=qty,
                price_pln=price, description=name, resolved=False,
            ))
            continue

        good_agg_qty[gid]   = good_agg_qty.get(gid, 0.0) + qty
        good_agg_price[gid] = price
        good_name[gid]      = name
        planned.append(PlannedLine(
            product_code=pc, good_id=gid, count=qty,
            price_pln=price, description=name, resolved=True,
        ))

    ready = not unresolved and not conflicts

    if not ready:
        return BatchBuildResult(
            planned_lines=planned,
            unresolved_codes=unresolved,
            price_conflicts=conflicts,
            ready=False,
            pz_request=None,
        )

    # ── Build PZRequest ───────────────────────────────────────────────────────
    mrn_part = f" | MRN {mrn}" if mrn else ""
    description = f"batch={batch_id}{mrn_part}"

    lines = [
        PZLine(good_id=gid, count=good_agg_qty[gid], price=good_agg_price[gid])
        for gid in good_agg_qty
    ]

    req = PZRequest(
        contractor_id=contractor_id,
        warehouse_id=warehouse_id,
        date=doc_date,
        description=description,
        lines=lines,
    )

    return BatchBuildResult(
        planned_lines=planned,
        unresolved_codes=[],
        price_conflicts=[],
        ready=True,
        pz_request=req,
    )
