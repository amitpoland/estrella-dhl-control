"""
global_packing_parser.py — Parse Global Jewellery Pvt. Ltd. packing lists.

Global packing lists are 245-row Excel files where each row is one item.
The packing list is the authority for item-level data; the commercial
invoice only provides aggregate totals.

Row format (typical column order):
  Sr / Type / Style No. / Metal / Qty / Gross Wt / Net Wt / FOB Value

Product code convention (mirrors invoice_packing_extractor.py):
  ``{invoice_no}-{serial_number}``
  e.g. ``088/2026-2027-1``, ``088/2026-2027-2``

Public API
----------
``parse_global_packing_excel(path, invoice_no=None)``
    → ``(rows, parser_name, parser_version, diag)``

``_safe_float(val)``
    → ``float``   (exported so routes_packing.py can import it for crash safety)

Safety
------
- Never raises — returns empty rows list on failure.
- Never writes to DB.
- All numeric coercions use ``_safe_float``.
- Rows where the serial column contains non-integer text (e.g. "ite 1",
  "Total", header echo) are skipped silently.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

_PARSER_NAME    = "global_packing_v1"
_PARSER_VERSION = "1.0"

# ── Column alias map ──────────────────────────────────────────────────────────

def _normalise_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "_", (h or "").strip().lower()).strip("_")


_FIELD_ALIASES: Dict[str, str] = {
    # serial / row number
    "sr":          "serial_no",
    "sr_no":       "serial_no",
    "srno":        "serial_no",
    "s_no":        "serial_no",
    "sno":         "serial_no",
    "item":        "serial_no",
    "item_no":     "serial_no",
    "no":          "serial_no",
    # item type / category
    "type":        "item_type",
    "category":    "item_type",
    "item_type":   "item_type",
    "description": "item_type",
    "particulars": "item_type",
    # style / design number
    "style":       "design_no",
    "style_no":    "design_no",
    "styleno":     "design_no",
    "design":      "design_no",
    "design_no":   "design_no",
    "designno":    "design_no",
    "model":       "design_no",
    "article":     "design_no",
    "article_no":  "design_no",
    # metal / material
    "metal":       "metal",
    "material":    "metal",
    "kt":          "metal",
    "purity":      "metal",
    "fineness":    "metal",
    # quantity
    "qty":         "quantity",
    "quantity":    "quantity",
    "pcs":         "quantity",
    "pcs_qty":     "quantity",
    "nos":         "quantity",
    # weights
    "gross_wt":    "gross_weight",
    "grosswt":     "gross_weight",
    "g_wt":        "gross_weight",
    "gwt":         "gross_weight",
    "gross_weight":"gross_weight",
    "net_wt":      "net_weight",
    "netwt":       "net_weight",
    "n_wt":        "net_weight",
    "nwt":         "net_weight",
    "net_weight":  "net_weight",
    # value / FOB price
    "fob":         "unit_price",
    "fob_value":   "unit_price",
    "fobvalue":    "unit_price",
    "value":       "unit_price",
    "amount":      "unit_price",
    "rate":        "unit_price",
    "unit_price":  "unit_price",
    "price":       "unit_price",
    # remarks
    "remarks":     "remarks",
    "notes":       "remarks",
}

# Tokens that indicate a row is noise (totals, headers, labels)
_SKIP_SERIAL_RE = re.compile(
    r"^(?:ite|item|total|grand|sub|sr\.?\s*no|s\.?\s*no|#|n/a|na|nil|"
    r"packing|list|invoice|note|description|particulars|remarks).*",
    re.IGNORECASE,
)

# Invoice number pattern inside Excel preamble
_INV_NO_RE = re.compile(r"\b(\d{3}/\d{4}-\d{4})\b")


# ── Safe float ────────────────────────────────────────────────────────────────

def _safe_float(val: Any) -> float:
    """Convert any value to float. Returns 0.0 on error — never raises."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


# ── Header detection ──────────────────────────────────────────────────────────

def _find_global_header_row(rows: List[List[Any]]) -> int:
    """Scan first 30 rows for the Global packing list header.

    Requires ALL THREE of:
      - a type/style column   (item identity)
      - a qty column          (quantity)
      - a weight column       (gross or net weight)
    """
    def _has_type(norm: List[str]) -> bool:
        return any(
            h in ("type", "item_type", "description", "category", "particulars", "style", "style_no", "styleno")
            for h in norm
        )

    def _has_qty(norm: List[str]) -> bool:
        return any(h in ("qty", "quantity", "pcs", "pcs_qty", "nos") for h in norm)

    def _has_weight(norm: List[str]) -> bool:
        return any(
            h in ("gross_wt", "grosswt", "g_wt", "gwt", "gross_weight",
                   "net_wt", "netwt", "n_wt", "nwt", "net_weight")
            for h in norm
        )

    for idx, row in enumerate(rows[:30]):
        norm = [_normalise_header(str(c) if c is not None else "") for c in row]
        if _has_type(norm) and _has_qty(norm) and _has_weight(norm):
            return idx
    return -1


def _map_headers(raw_headers: List[Any]) -> Dict[int, str]:
    """Return {col_index: canonical_field_name}."""
    mapping: Dict[int, str] = {}
    for i, h in enumerate(raw_headers):
        key = _normalise_header(str(h) if h is not None else "")
        if key in _FIELD_ALIASES:
            mapping[i] = _FIELD_ALIASES[key]
    return mapping


def _row_to_dict(cells: List[Any], col_map: Dict[int, str]) -> Dict[str, Any]:
    row: Dict[str, Any] = {}
    for idx, field in col_map.items():
        if idx < len(cells):
            val = cells[idx]
            row[field] = "" if val is None else val
    return row


# ── Row validation ────────────────────────────────────────────────────────────

def _is_valid_row(row: Dict[str, Any]) -> bool:
    """Return True for data rows; False for noise (totals, blanks, echoed headers)."""
    serial = str(row.get("serial_no", "") or "").strip()
    item_type = str(row.get("item_type", "") or "").strip()
    design_no = str(row.get("design_no", "") or "").strip()

    # Must have at least item_type or design_no
    if not item_type and not design_no:
        return False

    # Skip if serial looks like noise text
    if serial and _SKIP_SERIAL_RE.match(serial):
        return False

    # Skip header echo rows (item_type matches a known header alias)
    item_norm = _normalise_header(item_type)
    if item_norm in _FIELD_ALIASES or item_norm in ("type", "item_type", "description"):
        return False

    return True


# ── Preamble invoice_no detection ─────────────────────────────────────────────

def _find_invoice_no_in_preamble(rows: List[List[Any]], header_idx: int) -> str:
    """Scan preamble rows (above header) for an invoice number."""
    for row in rows[:max(header_idx, 0)]:
        for cell in row:
            if cell is None:
                continue
            m = _INV_NO_RE.search(str(cell))
            if m:
                return m.group(1)
    return ""


# ── Diagnostic ────────────────────────────────────────────────────────────────

def _new_diag() -> Dict[str, Any]:
    return {
        "supplier":        "global_jewellery",
        "parser":          _PARSER_NAME,
        "parser_version":  _PARSER_VERSION,
        "rows_extracted":  0,
        "rows_skipped":    0,
        "total_qty":       0.0,
        "total_fob_usd":   0.0,
        "total_gross_wt":  0.0,
        "total_net_wt":    0.0,
        "header_row_idx":  -1,
        "invoice_no":      "",
        "failure_reason":  None,
    }


# ── Main parser ───────────────────────────────────────────────────────────────

def parse_global_packing_excel(
    path: Path,
    invoice_no: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], str, str, Dict[str, Any]]:
    """Parse a Global Jewellery packing list Excel file.

    Parameters
    ----------
    path:
        Path to the ``.xlsx`` or ``.xls`` file.
    invoice_no:
        Invoice number to stamp on each row's ``product_code``.
        If ``None``, the parser attempts to read it from the Excel
        preamble rows.

    Returns
    -------
    ``(rows, parser_name, parser_version, diag)`` — same shape as
    ``invoice_packing_extractor.extract_packing()``.
    """
    diag = _new_diag()
    rows: List[Dict[str, Any]] = []

    try:
        raw = _read_excel_rows(path)
    except Exception as exc:
        log.warning("global_packing_parser: cannot open %s: %s", path, exc)
        diag["failure_reason"] = "file_open_error"
        return rows, _PARSER_NAME, _PARSER_VERSION, diag

    if not raw:
        diag["failure_reason"] = "empty_sheet"
        return rows, _PARSER_NAME, _PARSER_VERSION, diag

    header_idx = _find_global_header_row(raw)
    if header_idx < 0:
        diag["failure_reason"] = "header_not_detected"
        return rows, _PARSER_NAME, _PARSER_VERSION, diag

    diag["header_row_idx"] = header_idx

    # Resolve invoice_no: caller > preamble > ""
    if not invoice_no:
        invoice_no = _find_invoice_no_in_preamble(raw, header_idx)
    diag["invoice_no"] = invoice_no or ""

    col_map = _map_headers(raw[header_idx])

    # Assign serial counter for rows without a serial column
    auto_serial = 0

    for raw_row in raw[header_idx + 1 :]:
        # Skip entirely blank rows
        if all(c is None or str(c).strip() == "" for c in raw_row):
            continue

        rd = _row_to_dict(raw_row, col_map)

        if not _is_valid_row(rd):
            diag["rows_skipped"] += 1
            continue

        # Serial number — prefer explicit, fallback to auto-increment
        serial_raw = str(rd.get("serial_no", "") or "").strip()
        if serial_raw and serial_raw.isdigit():
            serial = int(serial_raw)
        else:
            auto_serial += 1
            serial = auto_serial

        # Safe numeric coercions
        qty        = _safe_float(rd.get("quantity"))
        gross_wt   = _safe_float(rd.get("gross_weight"))
        net_wt     = _safe_float(rd.get("net_weight"))
        unit_price = _safe_float(rd.get("unit_price"))

        # Product code: invoice_no-serial
        inv = invoice_no or "GLOBAL"
        pc  = f"{inv}-{serial}"

        rows.append({
            "serial_no":              serial,
            "product_code":           pc,
            "invoice_no":             inv,
            "invoice_line_position":  serial,
            "item_type":              str(rd.get("item_type", "") or "").strip(),
            "design_no":              str(rd.get("design_no", "") or "").strip(),
            "metal":                  str(rd.get("metal", "") or "").strip(),
            "quantity":               qty,
            "gross_weight":           gross_wt,
            "net_weight":             net_wt,
            "unit_price":             unit_price,
            "total_value":            unit_price,  # 1 qty per row typically
            "remarks":                str(rd.get("remarks", "") or "").strip(),
            "extracted_confidence":   1.0,
            "requires_manual_review": False,
            # Packing-specific fields
            "supplier":               "global_jewellery",
        })

        diag["total_qty"]      += qty
        diag["total_fob_usd"]  += unit_price
        diag["total_gross_wt"] += gross_wt
        diag["total_net_wt"]   += net_wt

    diag["rows_extracted"] = len(rows)

    if not rows:
        diag["failure_reason"] = "no_valid_rows"

    # Round totals
    diag["total_qty"]      = round(diag["total_qty"], 3)
    diag["total_fob_usd"]  = round(diag["total_fob_usd"], 2)
    diag["total_gross_wt"] = round(diag["total_gross_wt"], 3)
    diag["total_net_wt"]   = round(diag["total_net_wt"], 3)

    return rows, _PARSER_NAME, _PARSER_VERSION, diag


# ── Excel reader ──────────────────────────────────────────────────────────────

def _read_excel_rows(path: Path) -> List[List[Any]]:
    """Read all rows from the active sheet. Returns list of lists."""
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(str(path), data_only=True)
        ws = wb.active
        return [list(r) for r in ws.iter_rows(values_only=True)]
    elif suffix == ".xls":
        import xlrd
        wb = xlrd.open_workbook(str(path))
        ws = wb.sheet_by_index(0)
        return [ws.row_values(i) for i in range(ws.nrows)]
    else:
        raise ValueError(f"Unsupported extension for global packing parser: {suffix}")
