"""
invoice_intake_parser.py — Extract real EJL invoice line tables at intake time.

Pipeline:
  1. pdfplumber.extract_tables()  — preferred, robust against layout shifts
  2. regex on extract_text()      — fallback for templates where the table
                                    structure isn't detected as a grid

EJL invoice table layout (English INVOICE / Polish FAKTURA share the same shape):

    Description                            Gross   Net    HSN       UOM  Qty  Rate     Amount
    PCS, 18KT Gold, Plain Jewellery PEND.  1.300   1.300  71131911  PCS  5.0  23.20    116.00
    PCS, 18KT Gold, Plain Jewellery RING   3.960   3.960  71131911  PCS  1.0  570.00   570.00
    PCS, PT950 Platinum, Stud With Diam    3.290   3.166  71131923  PCS  1.0  486.00   486.00

Polish locale: rate / amount may use comma as decimal separator (570,00).

Output (one dict per line):
  {
    invoice_no, line_position, product_code,
    description, hsn_code, quantity,
    gross_weight, net_weight, rate_usd, amount_usd,
    currency,            # always "USD" for EJL exports
  }

If the parser cannot extract real lines (text-extract failure, format change),
it falls back to a SINGLE placeholder line so the packing-list matcher has
something to fuzzy-match against — this preserves backward compatibility but
the placeholder is clearly marked.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.logging import get_logger

log = get_logger(__name__)

# ── Patterns ──────────────────────────────────────────────────────────────────

# EJL invoice number: EJL/26-27/013, EJL-26-27-013, EJL-26/27-013, etc.
_RE_INVOICE_NO = re.compile(
    r"\b(EJL[\s/\-]\s*\d{2}[\s/\-]\d{2}[\s/\-]\s*\d{2,4})\b",
    re.IGNORECASE,
)

# Currency mention
_RE_CURRENCY = re.compile(r"\b(USD|EUR|PLN|INR)\b")

# Real EJL line pattern:
#   <description>  <gross.dec>  <net.dec>  <8-digit HSN>  <UOM>  <qty>  <rate>  <amount>
# Both gross and net REQUIRE a decimal (e.g. 1.300, 3.166) so we don't
# accidentally swallow plain integers from header / footer text.
# Rate and amount may use comma as decimal separator (Polish locale).
_RE_INVOICE_LINE = re.compile(
    r"^(?P<desc>.+?)"
    r"\s+(?P<gross>\d+\.\d{1,3})"
    r"\s+(?P<net>\d+\.\d{1,3})"
    r"\s+(?P<hsn>\d{8})"
    r"\s+(?P<uom>\w+)"
    r"\s+(?P<qty>\d+(?:\.\d+)?)"
    r"\s+(?P<rate>[\d,\.]+)"
    r"\s+(?P<amount>[\d,\.]+)\s*$"
)


def _norm_invoice_no(raw: str) -> str:
    """Normalise EJL invoice number → 'EJL/<yy>-<yy>/<seq>'."""
    s = re.sub(r"\s+", "", raw)
    s = s.replace("-", "/")  # convert dashes to slashes
    # Re-collapse 26/27 (range portion stays single token)
    parts = s.split("/")
    if len(parts) == 4 and parts[0].upper() == "EJL":
        return f"EJL/{parts[1]}-{parts[2]}/{parts[3]}"
    return s


def _to_float(s: str) -> float:
    """Parse number that may use ',' as decimal separator (Polish)."""
    if not s:
        return 0.0
    cleaned = s.strip()
    # If both ',' and '.' are present, ',' is thousands → strip it.
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        # Polish decimal comma → swap to dot
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _extract_invoice_no(file_name: str, text: str) -> str:
    m = _RE_INVOICE_NO.search(file_name)
    if m:
        return _norm_invoice_no(m.group(1))
    m = _RE_INVOICE_NO.search(text)
    if m:
        return _norm_invoice_no(m.group(1))
    return Path(file_name).stem


def _extract_currency(text: str) -> str:
    m = _RE_CURRENCY.search(text)
    return m.group(1) if m else ""


def _make_product_code(invoice_no: str, position: int) -> str:
    return f"{invoice_no}-{position}"


def _extract_lines_from_text(text: str, invoice_no: str, currency: str) -> List[Dict[str, Any]]:
    """
    Regex-based extraction. Walks each line of the PDF text and matches the
    EJL invoice line pattern. Returns canonical-shape line dicts.
    """
    lines: List[Dict[str, Any]] = []
    for raw in text.split("\n"):
        line = " ".join(raw.split())  # collapse whitespace runs (handles ZWSP/extra spaces)
        m = _RE_INVOICE_LINE.match(line)
        if not m:
            continue
        d = m.groupdict()
        try:
            qty    = _to_float(d["qty"])
            rate   = _to_float(d["rate"])
            amount = _to_float(d["amount"])
            gross  = _to_float(d["gross"])
            net    = _to_float(d["net"])
        except Exception:
            continue
        # Sanity: amount ~= qty * rate (tolerate 5% rounding drift)
        if rate > 0 and qty > 0:
            expected = qty * rate
            if expected > 0 and abs(amount - expected) / expected > 0.05:
                # Probably matched a footer total; skip
                continue

        pos = len(lines) + 1
        lines.append({
            "invoice_no":    invoice_no,
            "line_position": pos,
            "product_code":  _make_product_code(invoice_no, pos),
            "description":   d["desc"].strip()[:300],
            "hsn_code":      d["hsn"],
            "quantity":      qty,
            "gross_weight":  gross,
            "net_weight":    net,
            "rate_usd":      rate,
            "amount_usd":    amount,
            "currency":      currency or "USD",
            # legacy compatibility
            "unit_price":    rate,
            "total_value":   amount,
            "hs_code":       d["hsn"],
        })
    return lines


def _extract_lines_from_tables(tables: List[List[List[Optional[str]]]],
                                invoice_no: str,
                                currency: str) -> List[Dict[str, Any]]:
    """
    Fallback table-based extraction. Looks for rows shaped like
    [desc, gross, net, hsn, uom, qty, rate, amount] in any detected table.
    """
    lines: List[Dict[str, Any]] = []
    for table in tables or []:
        for row in table:
            if not row or len(row) < 8:
                continue
            cells = [(c or "").strip() for c in row]
            # Look for an 8-digit HSN cell anywhere in the row
            hsn_idx = next((i for i, c in enumerate(cells)
                             if re.fullmatch(r"\d{8}", c)), None)
            if hsn_idx is None or hsn_idx < 3:
                continue
            try:
                desc   = " ".join(cells[:hsn_idx - 2])[:300]
                gross  = _to_float(cells[hsn_idx - 2])
                net    = _to_float(cells[hsn_idx - 1])
                hsn    = cells[hsn_idx]
                uom    = cells[hsn_idx + 1] if hsn_idx + 1 < len(cells) else ""
                qty    = _to_float(cells[hsn_idx + 2]) if hsn_idx + 2 < len(cells) else 0.0
                rate   = _to_float(cells[hsn_idx + 3]) if hsn_idx + 3 < len(cells) else 0.0
                amount = _to_float(cells[hsn_idx + 4]) if hsn_idx + 4 < len(cells) else 0.0
            except Exception:
                continue
            if qty <= 0 or rate <= 0:
                continue
            pos = len(lines) + 1
            lines.append({
                "invoice_no":    invoice_no,
                "line_position": pos,
                "product_code":  _make_product_code(invoice_no, pos),
                "description":   desc,
                "hsn_code":      hsn,
                "quantity":      qty,
                "gross_weight":  gross,
                "net_weight":    net,
                "rate_usd":      rate,
                "amount_usd":    amount,
                "currency":      currency or "USD",
                "unit_price":    rate,
                "total_value":   amount,
                "hs_code":       hsn,
            })
    return lines


def parse_invoice_pdf(pdf_path: Path, file_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Extract real invoice lines from an EJL purchase invoice PDF.

    Returns:
      {
        invoice_no, currency, lines: [...], extraction_method, line_count
      }

    On failure, returns a placeholder line (1 row) so packing-list fuzzy
    matching can still proceed.
    """
    fname  = file_name or pdf_path.name
    result = {
        "invoice_no":         "",
        "currency":           "",
        "lines":              [],
        "extraction_method":  "filename_only",
        "line_count":         0,
    }

    text     = ""
    tables: List[List[List[Optional[str]]]] = []
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages[:5]:
                t = page.extract_text() or ""
                text += t + "\n"
                try:
                    tables.extend(page.extract_tables() or [])
                except Exception:
                    pass
    except Exception as exc:
        log.warning("Invoice PDF open failed (%s): %s", pdf_path, exc)

    invoice_no = _extract_invoice_no(fname, text)
    currency   = _extract_currency(text) or "USD"
    result["invoice_no"] = invoice_no
    result["currency"]   = currency

    # Priority 1: regex on text (works for the EJL template — both EN & PL)
    lines = _extract_lines_from_text(text, invoice_no, currency)
    method = "regex_text"

    # Priority 2: pdfplumber tables (only if text path fails)
    if not lines:
        lines  = _extract_lines_from_tables(tables, invoice_no, currency)
        method = "pdfplumber_tables"

    # Fallback: single placeholder row
    if not lines:
        method = "filename_only"
        lines = [{
            "invoice_no":    invoice_no,
            "line_position": 1,
            "product_code":  _make_product_code(invoice_no, 1),
            "description":   "(placeholder — PZ engine will populate)",
            "hsn_code":      "",
            "quantity":      0.0,
            "gross_weight":  0.0,
            "net_weight":    0.0,
            "rate_usd":      0.0,
            "amount_usd":    0.0,
            "currency":      currency,
            "unit_price":    0.0,
            "total_value":   0.0,
            "hs_code":       "",
        }]

    result["lines"]             = lines
    result["extraction_method"] = method
    result["line_count"]        = len(lines)

    log.info("Invoice parsed: %s — %d lines (%s)", invoice_no, len(lines), method)
    return result
