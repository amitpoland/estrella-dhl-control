"""
global_invoice_parser.py — Parse Global Jewellery Pvt. Ltd. commercial invoices.

Global invoices are aggregate-summary documents:
  - One invoice covers all items in the shipment
  - Line items are NOT individually listed (only totals: FOB, freight, insurance, CIF)
  - Quantity is given as PCS + PRS totals

The parser produces exactly ONE aggregate ``invoice_line`` so the invoice
authority record is stored in the DB without polluting ``invoice_lines``
with per-item rows (those come from the packing list).

Public API
----------
``parse_global_invoice_pdf(pdf_path, file_name)`` → dict

Returned dict shape::

    {
        "supplier":        "global_jewellery",
        "invoice_no":      "088/2026-2027",
        "invoice_date":    "2026-...",          # ISO string or "" if not found
        "fob_usd":         3172.00,
        "freight_usd":     125.00,
        "insurance_usd":   25.00,
        "cif_usd":         3322.00,
        "total_qty_pcs":   183,
        "total_qty_prs":   62,
        "currency":        "USD",
        "extraction_method": "regex",           # "regex" | "fallback" | "failed"
        "header": {...},                        # alias for top-level fields
        "lines": [
            {
                "invoice_no":      "088/2026-2027",
                "line_position":   1,
                "product_code":    "088/2026-2027-AGG",
                "description":     "Global Jewellery Pvt. Ltd. — aggregate lot",
                "quantity":        245,
                "unit_price":      0.0,
                "total_value":     3172.00,
                "currency":        "USD",
                "hs_code":         "",
                "gross_weight":    0.0,
                "net_weight":      0.0,
            }
        ],
        "error": None,   # non-None on parse failure
    }

Safety
------
- Never raises — returns ``error`` field on failure.
- Never writes to DB or external services.
- Never modifies CIF / customs routing.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

# ── Regex patterns ────────────────────────────────────────────────────────────

# Invoice number: "088/2026-2027"
_INV_NO_RE = re.compile(r"\b(\d{3}/\d{4}-\d{4})\b")

# Monetary values — strip commas, handle both "3,172.00" and "3172.00"
_MONEY_RE = re.compile(r"([\d,]+\.\d{1,2})")

# FOB (may appear as "FOB Value", "F.O.B.", "FOB Total")
# Pattern order: label → optional qualifier → optional colon → optional currency → number
_FOB_RE = re.compile(
    r"(?:FOB|F\.O\.B\.)\s*(?:Value|Total|Amount)?\s*[:=]?\s*(?:USD|US\$|\$)?\s*([\d,]+\.?\d*)",
    re.IGNORECASE,
)

# Freight
_FREIGHT_RE = re.compile(
    r"[Ff]reight\s*(?:Charges?|Cost|Amount)?\s*[:=]?\s*(?:USD|US\$|\$)?\s*([\d,]+\.?\d*)",
    re.IGNORECASE,
)

# Insurance
_INS_RE = re.compile(
    r"[Ii]nsurance\s*(?:Charges?|Cost|Amount)?\s*[:=]?\s*(?:USD|US\$|\$)?\s*([\d,]+\.?\d*)",
    re.IGNORECASE,
)

# CIF total
_CIF_RE = re.compile(
    r"CIF\s*(?:Value|Total|Amount)?\s*[:=]?\s*(?:USD|US\$|\$)?\s*([\d,]+\.?\d*)",
    re.IGNORECASE,
)

# Quantity PCS / PRS
_PCS_RE = re.compile(r"(\d+)\s*PCS", re.IGNORECASE)
_PRS_RE = re.compile(r"(\d+)\s*PRS", re.IGNORECASE)

# Date patterns: "12/05/2026", "05 January 2026", "2026-01-05"
_DATE_RE = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+\w+\s+\d{4})\b"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_float(s: Optional[str]) -> float:
    """Convert comma-formatted number string to float. Returns 0.0 on error."""
    if not s:
        return 0.0
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _read_pdf_text(pdf_path: Path) -> str:
    """Extract all text from PDF using pdfplumber. Returns '' on failure."""
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            parts = []
            for page in pdf.pages:
                t = page.extract_text() or ""
                parts.append(t)
                if len("".join(parts)) > 4000:
                    break  # enough context
            return "\n".join(parts)
    except Exception as exc:
        log.warning("global_invoice_parser: PDF text extraction failed: %s", exc)
        return ""


# ── Main parser ───────────────────────────────────────────────────────────────

def parse_global_invoice_pdf(
    pdf_path: Path,
    file_name: str = "",
) -> Dict[str, Any]:
    """Parse a Global Jewellery commercial invoice PDF.

    Returns the structured result dict. Never raises.
    """
    result: Dict[str, Any] = {
        "supplier":          "global_jewellery",
        "invoice_no":        "",
        "invoice_date":      "",
        "fob_usd":           0.0,
        "freight_usd":       0.0,
        "insurance_usd":     0.0,
        "cif_usd":           0.0,
        "total_qty_pcs":     0,
        "total_qty_prs":     0,
        "currency":          "USD",
        "extraction_method": "failed",
        "header":            {},
        "lines":             [],
        "error":             None,
    }

    try:
        text = _read_pdf_text(Path(pdf_path))
        if not text:
            result["error"] = "pdf_text_empty"
            return result

        # Invoice number
        m = _INV_NO_RE.search(text)
        if m:
            result["invoice_no"] = m.group(1)

        # Invoice date (first date-like token in text)
        m_date = _DATE_RE.search(text)
        if m_date:
            result["invoice_date"] = m_date.group(1)

        # FOB
        m_fob = _FOB_RE.search(text)
        result["fob_usd"] = _to_float(m_fob.group(1)) if m_fob else 0.0

        # Freight
        m_fr = _FREIGHT_RE.search(text)
        result["freight_usd"] = _to_float(m_fr.group(1)) if m_fr else 0.0

        # Insurance
        m_ins = _INS_RE.search(text)
        result["insurance_usd"] = _to_float(m_ins.group(1)) if m_ins else 0.0

        # CIF
        m_cif = _CIF_RE.search(text)
        result["cif_usd"] = _to_float(m_cif.group(1)) if m_cif else 0.0

        # If CIF not found but we have FOB + freight + insurance, calculate
        if result["cif_usd"] == 0.0 and result["fob_usd"] > 0:
            calc_cif = result["fob_usd"] + result["freight_usd"] + result["insurance_usd"]
            if calc_cif > 0:
                result["cif_usd"] = round(calc_cif, 2)

        # Quantities
        pcs_matches = _PCS_RE.findall(text)
        prs_matches = _PRS_RE.findall(text)
        if pcs_matches:
            result["total_qty_pcs"] = int(pcs_matches[-1])  # last occurrence = total
        if prs_matches:
            result["total_qty_prs"] = int(prs_matches[-1])

        total_qty = result["total_qty_pcs"] + result["total_qty_prs"]
        method = "regex" if result["invoice_no"] else "fallback"
        result["extraction_method"] = method

        # Build header mirror
        result["header"] = {
            "invoice_no":    result["invoice_no"],
            "invoice_date":  result["invoice_date"],
            "fob_usd":       result["fob_usd"],
            "freight_usd":   result["freight_usd"],
            "insurance_usd": result["insurance_usd"],
            "cif_usd":       result["cif_usd"],
            "total_qty_pcs": result["total_qty_pcs"],
            "total_qty_prs": result["total_qty_prs"],
            "currency":      "USD",
        }

        # One aggregate invoice line — authority record for CIF totals
        inv_no = result["invoice_no"] or (Path(file_name).stem if file_name else "GLOBAL-AGG")
        result["lines"] = [
            {
                "invoice_no":    inv_no,
                "line_position": 1,
                "product_code":  f"{inv_no}-AGG",
                "description":   "Global Jewellery Pvt. Ltd. — aggregate lot",
                "quantity":      float(total_qty),
                "unit_price":    0.0,
                "total_value":   result["fob_usd"],
                "currency":      "USD",
                "hs_code":       "",
                "gross_weight":  0.0,
                "net_weight":    0.0,
            }
        ]

    except Exception as exc:
        log.exception("global_invoice_parser: unexpected error on %s", pdf_path)
        result["error"] = str(exc)
        result["extraction_method"] = "failed"

    return result
