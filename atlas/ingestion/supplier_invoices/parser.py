"""
parser.py — Supplier invoice line extraction for Estrella-format invoices.

Extracts structured fields from invoice description strings and batch dicts.
Read-only: no DB writes, no external API calls, no wFirma / PZ / proforma paths.

Supported invoice format:
    Estrella Jewels LLP — "PCS, <PURITY> <MATERIAL>,<STYLE> <PRODUCT_TYPE>"
    e.g. "PCS, 14KT Gold,LGD Gold Stud Jewell RING"
         "PCS, PT950 Platinum,Plain Jewel RING"
         "PCS, 18KT Gold,Plain Jewellery PENDANT"

InvoiceLine fields:
    description     str   — raw description from invoice
    material        str   — e.g. "Gold", "Platinum", "Silver"
    purity_code     str   — e.g. "14KT", "18KT", "PT950", "925"
    product_type    str   — canonical type via last-noun authority (classifier.py)
    uom             str   — "PCS" or "PRS"
    quantity        int
    gross_weight    float — may be 0.0 if not in description
    net_weight      float — may be 0.0 if not in description
    rate            float — unit price (USD)
    amount          float — line total (USD)
    hsn_code        str
    stones          list[str] — e.g. ["LGD", "DIA", "CLS"]
    invoice_number  str
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .classifier import classify_product_type

# ── Material / purity lookup ──────────────────────────────────────────────────

_PURITY_MATERIAL: Dict[str, tuple] = {
    # Gold — karat system
    "9KT":   ("Gold",     "375"),
    "10KT":  ("Gold",     "417"),
    "14KT":  ("Gold",     "585"),
    "18KT":  ("Gold",     "750"),
    "22KT":  ("Gold",     "916"),
    "24KT":  ("Gold",     "999"),
    # Platinum — PT system
    "PT850": ("Platinum", "850"),
    "PT900": ("Platinum", "900"),
    "PT950": ("Platinum", "950"),
    # Silver — direct hallmark
    "925":   ("Silver",   "925"),
    "SL925": ("Silver",   "925"),
    "935":   ("Silver",   "935"),
    "999":   ("Silver",   "999"),
}

_PURITY_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _PURITY_MATERIAL) + r")\b",
    re.IGNORECASE,
)

# ── Stone abbreviation lookup ─────────────────────────────────────────────────

_STONE_PATTERNS: List[tuple] = [
    ("LGD",      re.compile(r"\bLGD\b", re.IGNORECASE)),          # lab-grown diamonds
    ("DIA",      re.compile(r"\bDIAM?\b", re.IGNORECASE)),         # diamonds or Diam abbreviation
    ("CLS",      re.compile(r"\bCLS\b", re.IGNORECASE)),           # coloured gems
    ("RUBY",     re.compile(r"\bRUBY\b", re.IGNORECASE)),
    ("EMERALD",  re.compile(r"\bEMERALD\b", re.IGNORECASE)),
    ("SAPPHIRE", re.compile(r"\bSAPPHIRE\b", re.IGNORECASE)),
]

# ── UOM ───────────────────────────────────────────────────────────────────────
_UOM_RE = re.compile(r"\b(PCS|PRS|NOS|GMS)\b", re.IGNORECASE)


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class InvoiceLine:
    description:    str
    invoice_number: str       = ""
    material:       str       = ""
    purity_code:    str       = ""
    product_type:   str       = "UNKNOWN"
    uom:            str       = "PCS"
    quantity:       int       = 0
    gross_weight:   float     = 0.0
    net_weight:     float     = 0.0
    rate:           float     = 0.0
    amount:         float     = 0.0
    hsn_code:       str       = ""
    stones:         List[str] = field(default_factory=list)


@dataclass
class InvoiceBatch:
    """Collection of parsed lines from one or more invoices in a shipment."""
    awb:         str
    lines:       List[InvoiceLine]
    fob_usd:     float = 0.0
    freight_usd: float = 0.0
    insurance_usd: float = 0.0
    cif_usd:     float = 0.0

    @property
    def total_quantity(self) -> int:
        return sum(l.quantity for l in self.lines)

    @property
    def quantity_by_type(self) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for l in self.lines:
            result[l.product_type] = result.get(l.product_type, 0) + l.quantity
        return result

    @property
    def computed_fob_usd(self) -> float:
        """Sum of all line amounts — cross-check against stated FOB."""
        return round(sum(l.amount for l in self.lines), 2)

    @property
    def computed_cif_usd(self) -> float:
        return round(self.computed_fob_usd + self.freight_usd + self.insurance_usd, 2)


# ── Public API ────────────────────────────────────────────────────────────────

def parse_invoice_line(description: str,
                       *,
                       invoice_number: str = "",
                       quantity: int = 0,
                       rate: float = 0.0,
                       amount: float = 0.0,
                       gross_weight: float = 0.0,
                       net_weight: float = 0.0,
                       hsn_code: str = "",
                       uom: str = "") -> InvoiceLine:
    """Parse a single Estrella-format invoice description into an InvoiceLine.

    Description examples::

        "PCS, 14KT Gold,LGD Gold Stud Jewell RING"
        "PCS, PT950 Platinum,Plain Jewel RING"
        "PCS, 18KT Gold,Plain Jewellery PENDANT"

    The *quantity*, *rate*, *amount*, *hsn_code* keyword arguments allow callers
    to supply numeric fields not present in the description string itself.
    """
    line = InvoiceLine(description=description, invoice_number=invoice_number)

    # ── UOM from description if not supplied ─────────────────────────────────
    uom_m = _UOM_RE.search(description)
    line.uom = (uom or (uom_m.group(1).upper() if uom_m else "PCS"))

    # ── Material + purity ─────────────────────────────────────────────────────
    purity_m = _PURITY_RE.search(description)
    if purity_m:
        code = purity_m.group(1).upper()
        mat, _ = _PURITY_MATERIAL.get(code, ("", ""))
        line.purity_code = code
        line.material    = mat

    # ── Product type (last-noun authority) ────────────────────────────────────
    line.product_type = classify_product_type(description)

    # ── Stones ────────────────────────────────────────────────────────────────
    for stone_code, pattern in _STONE_PATTERNS:
        if pattern.search(description):
            line.stones.append(stone_code)

    # ── Numeric fields from kwargs ────────────────────────────────────────────
    line.quantity     = quantity
    line.rate         = rate
    line.amount       = amount
    line.gross_weight = gross_weight
    line.net_weight   = net_weight
    line.hsn_code     = hsn_code

    return line


def parse_invoice_batch(batch_dict: Dict[str, Any], *, awb: str = "") -> InvoiceBatch:
    """Parse a structured invoice batch dict into an InvoiceBatch.

    Expected shape (matches the fixture format used in tests)::

        {
            "awb": "8400636576",          # optional; overridden by kwarg
            "invoices": [
                {
                    "invoice_number": "EJL/26-27/233",
                    "items": [
                        {
                            "description": "PCS, 14KT Gold,...",
                            "quantity": 1,
                            "unit_price": 279.0,
                            "line_total": 279.0,
                            "hsn_code": "71131914",
                        },
                        ...
                    ],
                },
                ...
            ],
            "freight_usd": 95.0,
            "insurance_usd": 55.0,
            "invoice_totals": {"total_cif_usd": 12427.0},
        }
    """
    awb_val    = awb or batch_dict.get("awb", "")
    freight    = float(batch_dict.get("freight_usd", 0.0))
    insurance  = float(batch_dict.get("insurance_usd", 0.0))

    totals     = batch_dict.get("invoice_totals") or {}
    cif        = float(totals.get("total_cif_usd", 0.0))

    lines: List[InvoiceLine] = []
    for inv in batch_dict.get("invoices", []):
        inv_no = inv.get("invoice_number", "")
        for item in inv.get("items", []):
            desc   = item.get("description", "")
            qty    = int(item.get("quantity", 0))
            rate   = float(item.get("unit_price", 0.0))
            amount = float(item.get("line_total", 0.0))
            hsn    = item.get("hsn_code", "")
            lines.append(parse_invoice_line(
                desc,
                invoice_number=inv_no,
                quantity=qty,
                rate=rate,
                amount=amount,
                hsn_code=hsn,
            ))

    fob = round(sum(l.amount for l in lines), 2)

    return InvoiceBatch(
        awb=awb_val,
        lines=lines,
        fob_usd=fob,
        freight_usd=freight,
        insurance_usd=insurance,
        cif_usd=cif,
    )
