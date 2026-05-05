"""
pz_batch_schema.py — single-source-of-truth shape for a "1 AWB → 1 PZ" batch.

Rule:    one shipment (AWB/SAD)  →  one PZ document  →  one truth.

This module defines the dataclasses returned by build_pz_batch and consumed
by validate_pz_batch + the UI autofill payload.

NEVER hold floats for money — all numeric fields are Decimal so totals
match wFirma's accounting rounding to the grosz.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from decimal import Decimal
from typing import Any, Dict, List, Optional


# Constants pinned from the live wFirma account (verified via probes 2026-05-03)
DEFAULT_WAREHOUSE_ID    = "347088"      # Główny
DEFAULT_VAT_CODE_ID     = "222"         # VAT 23%
DEFAULT_UNIT_ID         = "17456790"    # szt.
DEFAULT_PZ_SERIES_ID    = "15827163"    # PZ numbering series in this account
DEFAULT_CURRENCY        = "PLN"
DEFAULT_PRICE_TYPE      = "netto"


@dataclass
class Supplier:
    """Supplier (kontrahent / dostawca) — must be the same for all lines."""
    wfirma_id:  str
    name:       str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PZBatchLine:
    """One PZ line. product_code is the bridge key; wfirma_good_id is the wFirma binding."""
    product_code:    str
    wfirma_good_id:  str
    name:            str             # bilingual "Polish / English"
    qty:             Decimal
    price_net_pln:   Decimal
    invoice_no:      str             # source invoice (e.g. "EJL/26-27/015")
    vat_code_id:     str = DEFAULT_VAT_CODE_ID
    unit_id:         str = DEFAULT_UNIT_ID

    def line_net(self) -> Decimal:
        return (self.qty * self.price_net_pln).quantize(Decimal("0.01"))

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Decimals → strings (preserves precision through JSON)
        d["qty"]            = str(self.qty)
        d["price_net_pln"]  = str(self.price_net_pln)
        d["line_net_pln"]   = str(self.line_net())
        return d


@dataclass
class PZBatch:
    """One PZ document covering the entire shipment (1 AWB = 1 PZ)."""
    batch_id:       str               # e.g. "AWB_6876258325"
    awb:            str
    sad_number:     str               # may be empty during import-pending
    supplier:       Supplier
    warehouse_id:   str
    document_date:  str               # ISO YYYY-MM-DD
    currency:       str
    price_type:     str
    series_id:      str
    lines:          List[PZBatchLine] = field(default_factory=list)
    invoices:       List[str]         = field(default_factory=list)   # source invoice numbers
    notes:          str               = ""

    def total_net(self) -> Decimal:
        if not self.lines:
            return Decimal("0.00")
        return sum((l.line_net() for l in self.lines), Decimal("0.00")).quantize(Decimal("0.01"))

    def total_brutto(self, vat_rate: Decimal = Decimal("0.23")) -> Decimal:
        return (self.total_net() * (Decimal("1") + vat_rate)).quantize(Decimal("0.01"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_id":       self.batch_id,
            "awb":            self.awb,
            "sad_number":     self.sad_number,
            "supplier":       self.supplier.to_dict(),
            "warehouse_id":   self.warehouse_id,
            "document_date":  self.document_date,
            "currency":       self.currency,
            "price_type":     self.price_type,
            "series_id":      self.series_id,
            "invoices":       list(self.invoices),
            "notes":          self.notes,
            "lines":          [l.to_dict() for l in self.lines],
            "total_net_pln":  str(self.total_net()),
        }
