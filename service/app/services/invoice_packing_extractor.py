"""
invoice_packing_extractor.py — Extract invoice lines and packing list rows.

Invoice lines come from pz_rows.json (engine output — not re-parsed).
Packing list rows are extracted from an uploaded PDF or XLSX file.

product_code convention:
  invoice_no + "-" + str(invoice_line_position)
  e.g. EJL/26-27/100-1, EJL/26-27/100-2

Matching strategy (in priority order):
  1. Direct: packing row has explicit invoice_no + line_position
  2. Fuzzy: same invoice_no + item_type + metal/karat + quantity match
  3. No match: product_code=None, requires_manual_review=True
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

_PARSER_NAME    = "invoice_packing_extractor"
_PARSER_VERSION = "1.0"


# ── Invoice lines: DB-first with pz_rows.json fallback ───────────────────────

def load_invoice_lines(
    batch_output_dir: Path,
    batch_id:         Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Resolve invoice lines using the priority chain:
      1. document_db.invoice_lines    (canonical — source = "db_invoice_lines")
      2. pz_rows.json                 (legacy fallback — source = "legacy_pz_rows")
      3. []                           (no invoice context)

    The DB path is the modern source: invoice_lines are populated at intake time,
    long before PZ is generated. pz_rows.json is retained only for legacy batches
    that pre-date the intake pipeline.

    Returns list of dicts with:
      invoice_no, invoice_line_position, product_code,
      description_en, item_type, quantity, unit,
      unit_netto_pln, line_netto_pln, _source
    """
    # ── Priority 1: DB ────────────────────────────────────────────────────────
    if batch_id:
        try:
            from . import document_db as ddb
            db_rows = ddb.get_invoice_lines_for_batch(batch_id)
            if db_rows:
                result: List[Dict[str, Any]] = []
                for r in db_rows:
                    desc = r.get("description", "")
                    result.append({
                        "invoice_no":            r.get("invoice_no", ""),
                        "invoice_line_position": int(r.get("line_position") or 0),
                        "product_code":          r.get("product_code", ""),
                        "description":           desc,           # canonical
                        "description_en":        desc,           # legacy alias
                        # item_type isn't a separate column in invoice_lines;
                        # the matcher derives it from description if blank.
                        "item_type":             "",
                        "quantity":              float(r.get("quantity", 0) or 0),
                        "unit":                  "",
                        "rate_usd":              float(r.get("rate_usd",   r.get("unit_price",  0)) or 0),
                        "amount_usd":            float(r.get("amount_usd", r.get("total_value", 0)) or 0),
                        "unit_price":            float(r.get("rate_usd",   r.get("unit_price",  0)) or 0),
                        "total_value":           float(r.get("amount_usd", r.get("total_value", 0)) or 0),
                        "unit_netto_pln":        float(r.get("rate_usd",   r.get("unit_price",  0)) or 0),
                        "line_netto_pln":        float(r.get("amount_usd", r.get("total_value", 0)) or 0),
                        "gross_weight":          float(r.get("gross_weight", 0) or 0),
                        "net_weight":            float(r.get("net_weight",   0) or 0),
                        "hsn_code":              r.get("hsn_code", "") or r.get("hs_code", ""),
                        "_source":               "db_invoice_lines",
                    })
                log.info("[%s] invoice_lines loaded from DB (%d rows)",
                         batch_id, len(result))
                return result
        except Exception as exc:
            log.warning("[%s] DB invoice_lines lookup failed (falling back to pz_rows): %s",
                        batch_id, exc)

    # ── Priority 2: pz_rows.json (legacy) ─────────────────────────────────────
    pz_rows_path = batch_output_dir / "pz_rows.json"
    if not pz_rows_path.exists():
        log.warning("Neither DB invoice_lines nor pz_rows.json found for %s",
                    batch_id or batch_output_dir)
        return []

    import json
    raw: List[Dict[str, Any]] = json.loads(pz_rows_path.read_text(encoding="utf-8"))

    by_invoice: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in raw:
        inv = row.get("invoice_no", "")
        by_invoice[inv].append(row)

    result: List[Dict[str, Any]] = []
    for inv_no, rows in sorted(by_invoice.items()):
        for pos, row in enumerate(rows, start=1):
            product_code = f"{inv_no}-{pos}"
            result.append({
                "invoice_no":            inv_no,
                "invoice_line_position": pos,
                "product_code":          product_code,
                "description_en":        row.get("description_en", ""),
                "item_type":             row.get("item_type", "").upper(),
                "quantity":              float(row.get("quantity", 0) or 0),
                "unit":                  row.get("unit", ""),
                "unit_netto_pln":        float(row.get("unit_netto_pln", 0) or 0),
                "line_netto_pln":        float(row.get("line_netto_pln", 0) or 0),
                "_source":               "legacy_pz_rows",
            })
    log.info("[%s] invoice_lines loaded from pz_rows.json (%d rows)",
             batch_id or "?", len(result))
    return result


# ── Packing list extraction ───────────────────────────────────────────────────

def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _new_diagnostic(file_type: str) -> Dict[str, Any]:
    """Build an empty parser_diagnostic skeleton."""
    return {
        "parser_name":          _PARSER_NAME,
        "parser_version":       _PARSER_VERSION,
        "file_type":            file_type,
        "workbook_sheet_names": [],
        "sheet_count":          0,
        "sheets_scanned":       [],
        "candidate_header_rows": [],
        "chosen_header":        None,
        "mapped_columns":       [],
        "unmatched_columns":    [],
        "alias_hits":           0,
        "row_count":            0,
        "failure_reason":       None,
        "exception_class":      None,
        "exception_message":    None,
    }


def _collect_excel_diagnostic(path: Path, engine: str, diag: Dict[str, Any]) -> None:
    """Populate the diagnostic dict by re-reading the workbook for
    observability (sheet names, candidate header rows, chosen header,
    column mapping). Non-fatal — exceptions are swallowed and the
    diagnostic stays as far as it got.

    This NEVER changes parsing behaviour — it only inspects.
    """
    try:
        if engine == "openpyxl":
            import openpyxl as _opx
            wb = _opx.load_workbook(str(path), data_only=True, read_only=True)
            diag["workbook_sheet_names"] = list(wb.sheetnames)
            diag["sheet_count"] = len(wb.sheetnames)
            ws = wb.active
            diag["sheets_scanned"] = [ws.title] if ws is not None else []
            sheet_name = ws.title if ws is not None else "<active>"
        elif engine == "xlrd":
            import xlrd as _xlrd
            wb = _xlrd.open_workbook(str(path))
            diag["workbook_sheet_names"] = list(wb.sheet_names())
            diag["sheet_count"] = wb.nsheets
            diag["sheets_scanned"] = [wb.sheet_names()[0]] if wb.nsheets else []
            sheet_name = wb.sheet_names()[0] if wb.nsheets else "<sheet0>"
        else:
            return
    except Exception as exc:
        # Workbook unreadable in diagnostic pass — caller's failure_reason
        # already set; just leave the diag thin.
        log.debug("packing diagnostic workbook open failed: %s", exc)
        return

    # Re-read rows for header scoring (we don't trust the closed workbook
    # state; use the same path the parser uses).
    try:
        rows_raw = _read_excel_rows(path, engine)
    except Exception as exc:
        log.debug("packing diagnostic _read_excel_rows failed: %s", exc)
        return

    # Score each of the top 25 rows for alias hits.
    candidates: List[Dict[str, Any]] = []
    best_idx, best_hits = -1, 0
    best_raw: List[str] = []
    best_col_map: Dict[int, str] = {}
    for idx, row in enumerate(rows_raw[:25]):
        raw_cells = [str(c) if c is not None else "" for c in row]
        if not any(c.strip() for c in raw_cells):
            continue
        col_map = _map_headers(raw_cells)
        hits = len(col_map)
        if hits > 0:
            candidates.append({
                "sheet":            sheet_name,
                "row_index":        idx,
                "raw_cells_sample": raw_cells[:20],
                "alias_hits":       hits,
            })
        # _find_header_row uses a stricter rule (qty AND design); we record
        # the row that production parser would pick — re-derive via
        # _find_header_row over the same data.
        if hits > best_hits:
            best_hits, best_idx, best_raw, best_col_map = hits, idx, raw_cells, col_map

    diag["candidate_header_rows"] = candidates
    diag["alias_hits"] = best_hits

    hdr_idx = _find_header_row(rows_raw)
    if hdr_idx >= 0:
        hdr_cells = [str(c) if c is not None else "" for c in rows_raw[hdr_idx]]
        col_map = _map_headers(hdr_cells)
        diag["chosen_header"] = {
            "sheet":     sheet_name,
            "row_index": hdr_idx,
            "raw_cells": hdr_cells[:40],
        }
        diag["mapped_columns"] = [
            {"raw": hdr_cells[i] if i < len(hdr_cells) else "",
             "normalised": _normalise_header(hdr_cells[i]) if i < len(hdr_cells) else "",
             "canonical_field": fld}
            for i, fld in sorted(col_map.items())
        ]
        diag["unmatched_columns"] = [
            hdr_cells[i] for i in range(len(hdr_cells))
            if i not in col_map and hdr_cells[i].strip()
        ]
    elif best_idx >= 0:
        # Best-effort: surface the best-scoring candidate even when the
        # stricter _find_header_row rejected it. Helps the operator see
        # which row the parser ALMOST picked.
        diag["mapped_columns"] = [
            {"raw": best_raw[i] if i < len(best_raw) else "",
             "normalised": _normalise_header(best_raw[i]) if i < len(best_raw) else "",
             "canonical_field": fld}
            for i, fld in sorted(best_col_map.items())
        ]
        diag["unmatched_columns"] = [
            best_raw[i] for i in range(len(best_raw))
            if i not in best_col_map and best_raw[i].strip()
        ]


def _collect_pdf_diagnostic(path: Path, diag: Dict[str, Any]) -> None:
    """Best-effort observability for PDF packing lists. Captures page count
    and the first table-like row when present."""
    try:
        import pdfplumber as _pp  # type: ignore
        with _pp.open(str(path)) as pdf:
            page_count = len(pdf.pages)
            diag["sheet_count"] = page_count
            diag["workbook_sheet_names"] = [f"page_{i+1}" for i in range(page_count)]
            diag["sheets_scanned"] = diag["workbook_sheet_names"][:1]
            if pdf.pages:
                tables = pdf.pages[0].extract_tables() or []
                if tables and tables[0]:
                    first = [str(c) if c is not None else "" for c in tables[0][0]]
                    diag["candidate_header_rows"] = [{
                        "sheet":            "page_1",
                        "row_index":        0,
                        "raw_cells_sample": first[:20],
                        "alias_hits":       len(_map_headers(first)),
                    }]
    except Exception as exc:
        log.debug("packing diagnostic pdf open failed: %s", exc)


def extract_packing(
    path: Path,
) -> Tuple[List[Dict[str, Any]], str, str, Dict[str, Any]]:
    """
    Dispatch to PDF or Excel extractor based on file extension.

    Returns (rows, parser_name, parser_version, parser_diagnostic).
    Each row is a raw dict of all extracted fields. The diagnostic dict
    carries observability data — see _new_diagnostic for the schema and
    docs/packing_diagnostics.md for the canonical contract. The
    diagnostic is ALWAYS returned (never None) so callers can record
    parser state regardless of success or failure.

    Supports:
      - .xlsx via openpyxl
      - .xls  via xlrd (legacy binary Excel)
      - .pdf  via pdfplumber

    Parser LOGIC is unchanged from prior versions — this wrapper only
    adds observability. The internal helpers (_extract_packing_excel,
    _extract_packing_pdf, _find_header_row, _map_headers) are untouched.
    """
    suffix = path.suffix.lower()
    diag = _new_diagnostic(file_type=suffix)
    rows: List[Dict[str, Any]] = []

    try:
        if suffix == ".xlsx":
            rows = _extract_packing_excel(path, engine="openpyxl")
            _collect_excel_diagnostic(path, "openpyxl", diag)
        elif suffix == ".xls":
            rows = _extract_packing_excel(path, engine="xlrd")
            _collect_excel_diagnostic(path, "xlrd", diag)
        elif suffix == ".pdf":
            rows = _extract_packing_pdf(path)
            _collect_pdf_diagnostic(path, diag)
        else:
            diag["failure_reason"] = "unsupported_extension"
            diag["file_type"] = suffix or "<none>"
            raise ValueError(f"Unsupported packing list format: {suffix}")
    except ValueError:
        # Re-raise the explicit "unsupported_extension" case so existing
        # callers continue to receive ValueError.
        if diag["failure_reason"] == "unsupported_extension":
            raise
        diag["failure_reason"] = "parser_exception"
        diag["exception_class"] = "ValueError"
    except Exception as exc:
        diag["failure_reason"] = "parser_exception"
        diag["exception_class"] = type(exc).__name__
        diag["exception_message"] = str(exc)[:500]
        log.warning("extract_packing exception on %s: %s", path.name, exc)
        # Still attempt diagnostic collection (workbook may be partially
        # readable) for the file types where it makes sense.
        try:
            if suffix == ".xlsx":
                _collect_excel_diagnostic(path, "openpyxl", diag)
            elif suffix == ".xls":
                _collect_excel_diagnostic(path, "xlrd", diag)
            elif suffix == ".pdf":
                _collect_pdf_diagnostic(path, diag)
        except Exception:
            pass

    # ── Post-pass classification ─────────────────────────────────────────
    diag["row_count"] = len(rows)
    if diag["failure_reason"] is None:
        if not rows:
            # Distinguish header_not_detected from empty_sheet using the
            # diagnostic state.
            if diag["chosen_header"] is None and diag["candidate_header_rows"]:
                diag["failure_reason"] = "header_not_detected"
            elif diag["sheet_count"] == 0 and diag["file_type"] in (".xlsx", ".xls"):
                # File couldn't be opened as a workbook OR has zero sheets.
                diag["failure_reason"] = "file_corrupt"
            elif diag["chosen_header"] is None:
                diag["failure_reason"] = "header_not_detected"
            else:
                diag["failure_reason"] = "empty_sheet"

    return rows, _PARSER_NAME, _PARSER_VERSION, diag


def _normalise_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "_", (h or "").strip().lower()).strip("_")


_FIELD_ALIASES: Dict[str, str] = {
    # design / product
    "design_no": "design_no",  "design": "design_no",  "style": "design_no",
    "model":     "design_no",  "designno":  "design_no",
    # batch
    "batch_no": "batch_no",   "batch": "batch_no",    "lot": "batch_no",
    "lot_no":   "batch_no",
    # bag / tray
    "bag_id":  "bag_id",   "bag":  "bag_id",   "bag_no":  "bag_id",
    "tray_id": "tray_id",  "tray": "tray_id",  "tray_no": "tray_id",
    # item type / category
    "item_type":  "item_type",  "type":     "item_type",  "category": "item_type",
    "description":"item_type",  "ctg":      "item_type",
    "pksr":       "line_position",   # EJL "PkSr" packing serial
    # uom
    "uom": "uom",  "unit": "uom",
    # quantities / weights
    "quantity":     "quantity",      "qty":      "quantity",   "pcs": "quantity",
    "pcs_qty":      "quantity",      "qty_pcs":  "quantity",
    "gross_weight": "gross_weight",  "gross_wt": "gross_weight","gw":  "gross_weight",
    "net_weight":   "net_weight",    "net_wt":   "net_weight",  "nw":  "net_weight",
    "dia_wt":       "diamond_weight","col_wt":   "color_weight",
    "qualtity":     "quality_string",  # observed typo in Pkg3806Rpt template
    # metal / karat / colour
    # EJL packing variants: "Kt/Color" combined OR "Kt"+"Col" separate cells.
    "metal":  "metal",  "material": "metal",  "kt_color": "metal",  "kt": "metal",
    "kt_col": "metal",   # observed: "Kt/Col" abbreviated header
    "col":    "metal_color",         # secondary (W/Y/RG indicator)
    "color":  "metal_color",
    "karat":  "karat",  "purity": "karat",  "fineness": "karat",
    # quality / stone — canonical field is quality_string
    "quality":    "quality_string",
    "stone_type": "stone_type", "stone": "stone_type",  "gemstone": "stone_type",
    # value (EJL packing list — used for fuzzy matching to invoice rate/amount)
    "value":       "unit_price",
    "total_value": "total_value",
    "size":        "size",
    "client_po":   "client_po",      # sales-side PO reference
    "order_no":    "client_po",
    # invoice link (purchase + export references)
    "invoice_no":   "invoice_no",  "invoice": "invoice_no",  "inv_no": "invoice_no",
    "invoice_":     "invoice_no",
    "export_no":    "invoice_no",     # EJL sales packing uses "Export No"
    "invoice_line": "invoice_line_position",
    "line_position":"invoice_line_position",
    "line_no":      "invoice_line_position",
    "sr":           "line_position",  # generic Serial column
    # misc
    "remarks": "remarks",  "notes": "remarks",  "comment": "remarks",
    # Per-line currency (sales packing lists may carry one)
    "currency": "currency",  "ccy": "currency",
}


_CURRENCY_TOKEN_RE = re.compile(
    r"\b(EUR|USD|PLN|GBP|CHF|JPY)\b", re.IGNORECASE,
)

# Symbol → ISO. Match longest-first so multi-char tokens win over '$'.
# 'zł' is the only common Polish symbol; CHF/JPY rarely appear as symbols.
_CURRENCY_SYMBOL_TO_ISO: List[tuple] = [
    ("zł",  "PLN"),
    ("CHF", "CHF"),
    ("EUR", "EUR"),
    ("USD", "USD"),
    ("PLN", "PLN"),
    ("GBP", "GBP"),
    ("JPY", "JPY"),
    ("€",   "EUR"),
    ("£",   "GBP"),
    ("¥",   "JPY"),
    ("$",   "USD"),
]


def _currency_from_format_string(fmt: str) -> str:
    """Parse an Excel ``cell.number_format`` string and return an ISO
    currency code, or "" if no recognised marker is present.

    Examples
    --------
    ``'[$-10409]"€"\\ 0;\\("€"\\ 0\\)'``    → ``"EUR"``
    ``'[$-10409]"$"\\ 0;\\("$"\\ 0\\)'``    → ``"USD"``
    ``'#,##0.00 "zł"'``                       → ``"PLN"``
    ``'General'``                              → ``""``
    """
    if not fmt:
        return ""
    s = str(fmt)
    # Excel locale prefixes like "[$-10409]" must NOT be confused with the
    # literal "$" symbol — strip them out before scanning.
    s_clean = re.sub(r"\[\$-[0-9A-Fa-f]+\]", "", s)
    for sym, iso in _CURRENCY_SYMBOL_TO_ISO:
        if sym in s_clean:
            return iso
    return ""


def _detect_packing_currency(rows: list, header_idx: int, headers: list) -> str:
    """
    Sales packing lists rarely carry a per-row currency cell. Detect from:
      1. Header text on Value/Total Value columns: "Value (EUR)", "Total USD"
      2. Sheet preamble cells (top 12 rows): "Currency: EUR", "USD"
    Returns the upper-case ISO code, or "" if nothing matched.
    """
    # 1. Header-level
    for h in headers or []:
        s = str(h or "")
        m = _CURRENCY_TOKEN_RE.search(s)
        if m:
            return m.group(1).upper()
    # 2. Preamble scan (rows above the header row)
    for r in (rows or [])[:max(header_idx, 0)]:
        for cell in r or []:
            s = str(cell or "")
            if not s:
                continue
            low = s.lower()
            if "currency" in low or "ccy" in low:
                m = _CURRENCY_TOKEN_RE.search(s)
                if m:
                    return m.group(1).upper()
            # Bare currency token in preamble (e.g. "All values in EUR")
            m = _CURRENCY_TOKEN_RE.search(s)
            if m and ("value" in low or "total" in low or "all " in low
                      or low.strip() in ("eur", "usd", "pln", "gbp",
                                           "chf", "jpy")):
                return m.group(1).upper()
    return ""


def _map_headers(raw_headers: List[str]) -> Dict[int, str]:
    """Return {col_index: canonical_field_name} for known headers.

    Tolerant of currency-annotated headers like ``Value (EUR)`` /
    ``Total USD``: a parenthetical or trailing currency token is stripped
    before alias lookup so ``value_eur`` resolves to the same canonical
    field as ``value``.
    """
    mapping: Dict[int, str] = {}
    for i, h in enumerate(raw_headers):
        raw = (h or "").strip()
        # Strip "(EUR)" / "(USD)" annotations from header text.
        cleaned = re.sub(r"\s*\(\s*(?:EUR|USD|PLN|GBP|CHF|JPY)\s*\)\s*",
                          "", raw, flags=re.IGNORECASE)
        # Strip trailing bare currency tokens: "Total USD" → "Total"
        cleaned = re.sub(r"\b(?:EUR|USD|PLN|GBP|CHF|JPY)\b\s*$",
                          "", cleaned, flags=re.IGNORECASE).strip()
        key = _normalise_header(cleaned)
        if key in _FIELD_ALIASES:
            mapping[i] = _FIELD_ALIASES[key]
    return mapping


def _row_to_dict(cells: List[Any], col_map: Dict[int, str]) -> Dict[str, Any]:
    row: Dict[str, Any] = {}
    for idx, field in col_map.items():
        if idx < len(cells):
            val = cells[idx]
            if val is None:
                val = ""
            row[field] = val
    return row


def _read_excel_rows(path: Path, engine: str) -> List[List[Any]]:
    """Read every cell of the active sheet. Returns list of rows (list of cell values)."""
    if engine == "openpyxl":
        import openpyxl
        wb = openpyxl.load_workbook(str(path), data_only=True)
        ws = wb.active
        return [list(r) for r in ws.iter_rows(values_only=True)]

    if engine == "xlrd":
        import xlrd
        wb = xlrd.open_workbook(str(path))
        sh = wb.sheet_by_index(0)
        out: List[List[Any]] = []
        for r in range(sh.nrows):
            row: List[Any] = []
            for c in range(sh.ncols):
                v = sh.cell_value(r, c)
                # xlrd represents empty cells as ''. Keep None → '' equivalence.
                row.append(v if v != "" else None)
            out.append(row)
        return out

    raise ValueError(f"Unknown excel engine: {engine}")


def _find_header_row(rows: List[List[Any]]) -> int:
    """
    Locate the header row by scanning for a row that contains BOTH a quantity
    cell (qty/quantity/pcs/pcs_qty) AND a design/category cell. Tolerant of
    minor template variations: header text may contain extra words.
    Returns -1 if no header row is found.
    """
    def _is_qty_header(h: str) -> bool:
        return h in ("qty", "quantity", "pcs") or "qty" in h or "pcs_qty" == h
    def _is_design_header(h: str) -> bool:
        return h in ("designno", "design", "design_no", "style", "ctg", "category") or "design" in h

    for idx, row in enumerate(rows[:25]):  # only scan top 25 rows
        norm = [_normalise_header(str(c) if c is not None else "") for c in row]
        if any(_is_qty_header(h) for h in norm) and any(_is_design_header(h) for h in norm):
            return idx
    return -1


def _is_numeric_cell(v: Any) -> bool:
    """Return True if v parses as a finite number."""
    if v is None or v == "":
        return False
    if isinstance(v, (int, float)):
        return True
    s = str(v).strip().replace(",", ".")
    try:
        float(s)
        return True
    except ValueError:
        return False


def _is_subtotal_row(cells: List[Any], col_map: Dict[int, str]) -> bool:
    """Detect Total / Grand Total / sub-total rows so they don't pollute output."""
    for i, v in enumerate(cells):
        s = str(v or "").strip().lower()
        if not s:
            continue
        if "total" in s and i in col_map and col_map[i] == "design_no":
            return True
        if s.startswith(("grand total", "subtotal", "sub total", "total ")):
            return True
    return False


def _extract_packing_excel(path: Path, engine: str = "openpyxl") -> List[Dict[str, Any]]:
    """
    Read an EJL packing list (XLSX via openpyxl, XLS via xlrd).

    The EJL template puts:
      - "Invoice #" / "EJL/26-27/013" in a stray cell pair near rows 3-5
      - The actual line table headers on row 9 (PkSr, Ctg, DesignNo, Kt/Color,
        Quality, Dia Wt, Col Wt, Qty, Value, Total Value, Size)
      - Real data rows starting at row 10
      - Sub-total rows ("Total PND-18KT", "Grand Total") interleaved

    This function locates the header row dynamically and drops sub-totals.
    """
    rows = _read_excel_rows(path, engine)
    if not rows:
        return []

    # ── Pull invoice_no from the sheet preamble ──────────────────────────────
    # Two formats observed in EJL templates:
    #   A. label + value in adjacent cells:    ["Invoice #", "EJL/26-27/013"]
    #   B. label + value concatenated in one:  ["Export No : EJL/26-27/015"]
    invoice_no_from_sheet = ""
    _LABELS_A = ("invoice", "invoice #", "invoice no", "export no", "export no.")
    _LABEL_PATTERN_B = re.compile(
        r"^(?:invoice\s*(?:no|#)?|export\s*no\.?)\s*[:#]?\s*(.+)$",
        re.IGNORECASE,
    )
    _IS_INVOICE_LIKE = re.compile(r"^\s*(EJL|PROF|INV)[\s/\-]", re.IGNORECASE)

    for r in rows[:12]:
        for i, cell in enumerate(r):
            raw = str(cell or "").strip()
            if not raw:
                continue
            # Form A — label only
            tag = raw.lower().rstrip("#:.").strip()
            if tag in _LABELS_A:
                for v in r[i + 1:]:
                    sv = str(v or "").strip()
                    if sv:
                        invoice_no_from_sheet = sv
                        break
                break
            # Form B — label and value in same cell
            m = _LABEL_PATTERN_B.match(raw)
            if m:
                cand = m.group(1).strip()
                if _IS_INVOICE_LIKE.match(cand):
                    invoice_no_from_sheet = cand
                    break
        if invoice_no_from_sheet:
            break

    # ── Locate the header row ─────────────────────────────────────────────
    hdr_idx = _find_header_row(rows)
    if hdr_idx < 0:
        log.warning("No recognisable column headers found in %s", path.name)
        return []

    headers = [str(c) if c is not None else "" for c in rows[hdr_idx]]
    col_map = _map_headers(headers)
    if not col_map:
        log.warning("Header row %d had no aliasable cells: %s", hdr_idx, headers)
        return []

    # Sheet-level currency (header text or preamble). Stamped onto every
    # row that doesn't already carry a per-row currency cell.
    sheet_currency = _detect_packing_currency(rows, hdr_idx, headers)

    # ── Cell-format currency (highest-priority source) ──────────────────
    # Excel encodes currency on the Value / Total Value cells via
    # ``number_format`` (e.g. ``[$-10409]"€" 0``). This is the AUTHORITATIVE
    # signal — it survives copy/paste and renders the symbol in the source
    # file the operator sees. Read once per workbook (engine=openpyxl only;
    # xlrd does not expose per-cell number_format reliably).
    cell_format_currencies: List[str] = []
    if engine == "openpyxl":
        try:
            import openpyxl as _opx  # type: ignore
            wb_fmt = _opx.load_workbook(str(path), data_only=False)
            ws_fmt = wb_fmt.active
            # Value-bearing columns: any column mapped to unit_price /
            # total_value. We scan ALL data rows (not just header) so a
            # mid-sheet currency switch is detectable.
            value_cols = [i + 1 for i, fld in col_map.items()
                          if fld in ("unit_price", "total_value")]
            for ri in range(hdr_idx + 2, ws_fmt.max_row + 1):
                for ci in value_cols:
                    cell = ws_fmt.cell(row=ri, column=ci)
                    iso = _currency_from_format_string(cell.number_format or "")
                    if iso:
                        cell_format_currencies.append(iso)
        except Exception as _exc:
            log.warning("number_format currency scan failed for %s: %s",
                         path.name, _exc)
    # Sheet-level cell-format currency: use the most common one. Mixed
    # → keep the most common but record the conflict for the caller via a
    # special marker on the parsed rows so intake can warn.
    sheet_cell_format_currency = ""
    sheet_cell_format_conflict = False
    if cell_format_currencies:
        from collections import Counter as _Counter
        counts = _Counter(cell_format_currencies)
        sheet_cell_format_currency = counts.most_common(1)[0][0]
        sheet_cell_format_conflict = len(counts) > 1

    result: List[Dict[str, Any]] = []
    for raw in rows[hdr_idx + 1:]:
        cells = list(raw)
        # Skip fully empty rows
        if all(c is None or str(c).strip() == "" for c in cells):
            continue
        if _is_subtotal_row(cells, col_map):
            continue
        d = _row_to_dict(cells, col_map)

        # Real data rows ALWAYS have a numeric quantity. This is the strongest
        # signal — drops "Total ..." subtotals, "frt"/"insu" footer rows,
        # client-address rows, etc. that may appear interleaved.
        if not _is_numeric_cell(d.get("quantity")):
            continue
        # And must have a design / category cell
        design_present = bool(str(d.get("design_no", "") or "").strip())
        item_type      = bool(str(d.get("item_type", "") or "").strip())
        if not design_present and not item_type:
            continue

        # ── Metal / color split handling ─────────────────────────────────────
        # Three template variants produce different raw row shapes:
        #   Variant A (separate Kt + Col cells):
        #     col_map assigns metal="14KT", metal_color="W" (two distinct cells)
        #   Variant B (combined "14KT/Y" in one Kt/Color or Kt/Col cell):
        #     col_map assigns metal="14KT/Y", metal_color="" (combined cell)
        #   Variant C (separate Karat + Color):
        #     same as variant A
        #
        # Goal: after this block, `metal` holds the full combined string (e.g.
        # "14KT/W") AND `metal_color` holds the standalone color code (e.g. "W").
        if d.get("metal_color") and d.get("metal"):
            # Variant A / C: separate cells — merge karat + color into metal,
            # metal_color already populated (left unchanged for DB storage).
            d["metal"] = f"{d['metal']}/{d['metal_color']}"
        elif not d.get("metal_color") and d.get("metal"):
            # Variant B: combined cell like "14KT/Y" — extract the color suffix.
            # Color codes are short (1–4 chars): W, Y, R, RG, WY, RW, etc.
            # A dash or hyphen ("-") means no color / neutral — leave empty.
            combined = str(d["metal"]).strip()
            if "/" in combined:
                _, _, color_part = combined.partition("/")
                color_part = color_part.strip().rstrip("-").strip()
                if color_part and len(color_part) <= 4:
                    d["metal_color"] = color_part

        # Stamp invoice_no from sheet header if not already on the row
        if invoice_no_from_sheet and not d.get("invoice_no"):
            d["invoice_no"] = invoice_no_from_sheet

        # Currency priority on the row:
        #   1. cell number_format on Value/Total columns (authoritative)
        #   2. per-row currency cell (if present)
        #   3. sheet header / preamble token
        if not str(d.get("currency", "") or "").strip():
            if sheet_cell_format_currency:
                d["currency"]        = sheet_cell_format_currency
                d["currency_source"] = "excel_symbol"
            elif sheet_currency:
                d["currency"]        = sheet_currency
                d["currency_source"] = "excel_token"
        else:
            d.setdefault("currency_source", "excel_row")

        # Surface the multi-currency conflict so intake can warn.
        if sheet_cell_format_conflict:
            d["currency_conflict"] = True

        result.append(d)
    log.info("Packing extracted %d rows from %s (engine=%s, header_row=%d)",
             len(result), path.name, engine, hdr_idx)
    return result


# Backward-compatible alias (retained so any external caller still works)
def _extract_packing_xlsx(path: Path) -> List[Dict[str, Any]]:
    return _extract_packing_excel(path, engine="openpyxl")


def _extract_packing_pdf(path: Path) -> List[Dict[str, Any]]:
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber is required for PDF packing list extraction")

    result: List[Dict[str, Any]] = []
    col_map: Optional[Dict[int, str]] = None

    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table:
                    continue
                # First non-empty row with text is treated as the header row
                for row_idx, row in enumerate(table):
                    if row is None:
                        continue
                    cells = [str(c).strip() if c is not None else "" for c in row]
                    if col_map is None:
                        # Try to detect header row
                        candidate = _map_headers(cells)
                        if candidate:
                            col_map = candidate
                            continue
                        # If first row has no matches, treat it as header anyway
                        col_map = _map_headers(cells) or {}
                        continue
                    if all(c == "" for c in cells):
                        continue
                    result.append(_row_to_dict(cells, col_map))

    return result


# ── Matching ──────────────────────────────────────────────────────────────────

def _normalise_item_type(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


# EJL packing-list category tokens ↔ invoice description keywords.
# The packing list uses 3-4 letter codes ("PND", "RNG"); the invoice description
# spells them out ("PENDANT", "RING"). Map both onto a canonical key.
_EJL_TOKEN_MAP = {
    "pnd":      "pendant",  "pend":     "pendant", "pendant":  "pendant",
    "rng":      "ring",     "ring":     "ring",
    "erg":      "earring",  "er":       "earring", "earring":  "earring",
    "ear":      "earring",  "ears":     "earring", "earrings": "earring",
    "prs":      "earring",  # EJL packing list "PRS" (pairs) for earrings
    "brc":      "bracelet", "br":       "bracelet","bracelet": "bracelet",
    "nck":      "necklace", "nk":       "necklace","necklace": "necklace",
    "bng":      "bangle",   "bangle":   "bangle",
    "cfl":      "cufflink", "cufflink": "cufflink",
    "chn":      "chain",    "chain":    "chain",
}


def _canonical_item_type(s: str) -> str:
    """
    Normalise either an EJL packing 'Ctg' code (PND/RNG/ERG…) or an invoice
    description (containing PENDANT/RING/EARRING…) to a single canonical key.

    Iterates tokens LONGEST FIRST to prevent shorter substrings from winning
    (e.g. "ring" inside "earring", or "ring" inside "earrings").
    """
    norm = _normalise_item_type(s)
    if not norm:
        return ""
    # 1. Direct hit on the abbreviation
    if norm in _EJL_TOKEN_MAP:
        return _EJL_TOKEN_MAP[norm]
    # 2. Word inside a longer string — check longest tokens first
    for tok, canon in sorted(_EJL_TOKEN_MAP.items(), key=lambda x: -len(x[0])):
        if len(tok) >= 4 and tok in norm:
            return canon
    return norm


# ── Metal / material code normalisation ──────────────────────────────────────
# Recognises the metal token written in either the invoice description
# ("18KT Gold", "PT950 Platinum") or the packing list "Kt/Color" column
# ("18KT/W", "PT950/-", "925/-", "14KT/Y").
#
# Returns canonical token: "18KT", "14KT", "22KT", "24KT", "PT950", "PT900",
# "PT850", "925", "999", or "" if unrecognised.
_METAL_PATTERNS = [
    (re.compile(r"\b(\d{3})\s*PT\b",      re.IGNORECASE),              lambda m: "PT" + m.group(1)),  # "950 PT"
    (re.compile(r"\bPT\s*(\d{3})\b",      re.IGNORECASE),              lambda m: "PT" + m.group(1)),  # "PT950"
    (re.compile(r"\b(\d{2})\s*KT?\b",     re.IGNORECASE),              lambda m: m.group(1) + "KT"),  # "18KT", "14K"
    # Silver: 925 / 999 with optional letter prefix (S, SL, SS, SLV, SILVER).
    # Negative lookbehind for digits prevents false hits like "1925" (year).
    # Negative lookahead prevents false hits like "9255".
    (re.compile(r"(?<![0-9])(925|999)(?![0-9])"),                       lambda m: m.group(1)),
]


def _canonical_metal(*texts: str) -> str:
    """First metal token found across one or more text fragments."""
    for raw in texts:
        if not raw:
            continue
        s = str(raw)
        for pat, fmt in _METAL_PATTERNS:
            m = pat.search(s)
            if m:
                return fmt(m).upper()
    return ""


def _approx(a: float, b: float, tol_abs: float = 0.01, tol_rel: float = 0.02) -> bool:
    """True if two floats agree within tol_abs OR tol_rel of the larger value."""
    if abs(a - b) <= tol_abs:
        return True
    base = max(abs(a), abs(b))
    return base > 0 and abs(a - b) / base <= tol_rel


def match_packing_to_invoice(
    packing_rows: List[Dict[str, Any]],
    invoice_lines: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Match packing rows → invoice lines using a layered strategy:

      1. Direct  — explicit (invoice_no, invoice_line_position)
      2. Strong  — (invoice_no, item_type_canon, qty, rate) — rate breaks ties
      3. Fuzzy   — (invoice_no, item_type_canon, qty)
      4. Fuzzy² — (invoice_no, qty, rate) — for packing lists that lack a Ctg col
      5. Unmatched → requires_manual_review=True

    A given invoice line is consumed by the first packing row that matches it
    so two packing rows can't both claim the same invoice position.
    """
    # ── Build maps ────────────────────────────────────────────────────────────
    direct_map: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for il in invoice_lines:
        inv_no = il.get("invoice_no", "")
        pos    = il.get("invoice_line_position")
        if inv_no and pos:
            try:
                direct_map[(inv_no, int(pos))] = il
            except (ValueError, TypeError):
                pass

    # Available pool — invoice lines yet to be claimed
    available: List[Dict[str, Any]] = list(invoice_lines)

    def _claim(line: Dict[str, Any]) -> None:
        try:
            available.remove(line)
        except ValueError:
            pass

    matched: List[Dict[str, Any]] = []
    for row in packing_rows:
        r = dict(row)
        inv_no = str(r.get("invoice_no", "")).strip()
        item_canon = _canonical_item_type(str(r.get("item_type", "")))
        qty   = float(r.get("quantity",   0) or 0)
        rate  = float(r.get("unit_price", 0) or 0)  # EJL packing "Value" column
        # Metal/material — packing list has "metal" and "karat" columns
        # (mapped from "Kt/Color"). Combine them so "18KT/W" → "18KT" and
        # "PT950/-" → "PT950".
        pack_metal = _canonical_metal(r.get("metal", ""), r.get("karat", ""))

        chosen: Optional[Dict[str, Any]] = None
        confidence = 0.0
        strategy   = ""

        # Strategy 1 — direct
        raw_pos = r.get("invoice_line_position")
        if inv_no and raw_pos:
            try:
                pos = int(raw_pos)
                il  = direct_map.get((inv_no, pos))
                if il and il in available:
                    chosen = il; confidence = 1.0; strategy = "direct"
            except (ValueError, TypeError):
                pass

        # Strategy 2 — invoice + item_type + qty + rate
        # Only applied when BOTH sides actually carry a rate; otherwise fall
        # through to strategy 3 (type+qty+metal) so confidence isn't inflated.
        if chosen is None and inv_no and item_canon and rate > 0:
            for il in available:
                if il.get("invoice_no") != inv_no: continue
                if _canonical_item_type(il.get("item_type", "") or il.get("description", "")) != item_canon: continue
                if not _approx(float(il.get("quantity", 0) or 0), qty): continue
                il_rate = float(il.get("rate_usd", il.get("unit_netto_pln", il.get("unit_price", 0))) or 0)
                if il_rate <= 0: continue   # invoice line has no rate → skip
                if not _approx(il_rate, rate, tol_abs=0.05, tol_rel=0.05): continue
                # Metal sanity check: when both sides have a metal token, they
                # must agree. Prevents 18KT ↔ PT950 swap if rates ever collide.
                il_metal = _canonical_metal(il.get("description", ""), il.get("item_type", ""))
                if pack_metal and il_metal and pack_metal != il_metal:
                    continue
                chosen = il; confidence = 0.95; strategy = "type+qty+rate+metal"
                break

        # Strategy 3 — invoice + item_type + qty + metal (rate missing)
        # Distinguishes 18KT vs PT950 vs 925 silver vs 999 even with no rate.
        if chosen is None and inv_no and item_canon and pack_metal:
            for il in available:
                if il.get("invoice_no") != inv_no: continue
                if _canonical_item_type(il.get("item_type", "") or il.get("description", "")) != item_canon: continue
                if not _approx(float(il.get("quantity", 0) or 0), qty): continue
                il_metal = _canonical_metal(il.get("description", ""), il.get("item_type", ""))
                if il_metal != pack_metal: continue
                chosen = il; confidence = 0.85; strategy = "type+qty+metal"
                break

        # Strategy 4 — invoice + item_type + qty (no rate, no metal)
        if chosen is None and inv_no and item_canon:
            for il in available:
                if il.get("invoice_no") != inv_no: continue
                if _canonical_item_type(il.get("item_type", "") or il.get("description", "")) != item_canon: continue
                if not _approx(float(il.get("quantity", 0) or 0), qty): continue
                chosen = il; confidence = 0.8; strategy = "type+qty"
                break

        # Strategy 5 — invoice + qty + rate (when packing list has no Ctg column)
        if chosen is None and inv_no and rate > 0:
            for il in available:
                if il.get("invoice_no") != inv_no: continue
                if not _approx(float(il.get("quantity", 0) or 0), qty): continue
                il_rate = float(il.get("rate_usd", il.get("unit_netto_pln", il.get("unit_price", 0))) or 0)
                if not _approx(il_rate, rate, tol_abs=0.05, tol_rel=0.05): continue
                chosen = il; confidence = 0.7; strategy = "qty+rate"
                break

        # Strategy 6 — N:1 loose match for AGGREGATED invoice lines.
        # Used when an invoice groups many packing rows under one summary line
        # (e.g. invoice line "21 RINGs @ $371.10" ↔ 21 detailed packing rows).
        # Looks at INVOICE LINES (full pool, not 'available') because multiple
        # packing rows are expected to point to the same invoice line.
        if chosen is None and inv_no and item_canon:
            for il in invoice_lines:
                if il.get("invoice_no") != inv_no: continue
                if _canonical_item_type(il.get("item_type", "") or il.get("description", "")) != item_canon: continue
                il_metal = _canonical_metal(il.get("description", ""), il.get("item_type", ""))
                if pack_metal and il_metal and pack_metal != il_metal: continue
                # Invoice line must be aggregated (qty > 1) for loose match
                if float(il.get("quantity", 0) or 0) <= 1.0: continue
                chosen = il; confidence = 0.6; strategy = "type+metal_aggregate"
                break  # do NOT _claim() — N:1 reuse

        if chosen is not None:
            # Aggregate strategy is N:1 — don't consume the invoice line so
            # subsequent packing rows can map to it too.
            if strategy != "type+metal_aggregate":
                _claim(chosen)
            r["invoice_line_position"] = chosen.get("invoice_line_position")
            r["product_code"]          = chosen.get("product_code")
            r["invoice_no"]            = chosen.get("invoice_no") or inv_no
            r["requires_manual_review"] = False
            r["extracted_confidence"]  = confidence
            r["match_strategy"]        = strategy
        else:
            r["invoice_line_position"] = None
            r["product_code"]          = None
            r["requires_manual_review"] = True
            r["extracted_confidence"]  = 0.0
            r["match_strategy"]        = "unmatched"
        matched.append(r)

    return matched


# ── Full pipeline ─────────────────────────────────────────────────────────────

def process_packing_upload(
    batch_id: str,
    batch_output_dir: Path,
    packing_file_path: Path,
    force_reextract: bool = False,
) -> Dict[str, Any]:
    """
    Full pipeline: extract invoice lines from pz_rows.json, extract packing rows
    from the uploaded file, match them, and return structured result ready for DB insert.

    Returns:
      {
        "invoice_lines": [...],
        "packing_rows": [...],          # enriched with product_code
        "document": {...},              # packing_document fields
        "matched_count": int,
        "unmatched_count": int,
        "total_rows": int,
      }
    """
    invoice_lines = load_invoice_lines(batch_output_dir, batch_id=batch_id)
    inv_source = invoice_lines[0].get("_source", "unknown") if invoice_lines else "none"

    raw_rows, parser_name, parser_version, parser_diagnostic = extract_packing(packing_file_path)
    enriched = match_packing_to_invoice(raw_rows, invoice_lines)

    # Detect invoice_no from packing rows (majority vote)
    inv_nos = [r.get("invoice_no", "") for r in enriched if r.get("invoice_no")]
    if inv_nos:
        from collections import Counter
        doc_invoice_no = Counter(inv_nos).most_common(1)[0][0]
    else:
        doc_invoice_no = ""

    matched   = sum(1 for r in enriched if not r.get("requires_manual_review"))
    unmatched = len(enriched) - matched

    return {
        "invoice_lines":         invoice_lines,
        "invoice_lines_source":  inv_source,
        "packing_rows":          enriched,
        "parser_diagnostic":     parser_diagnostic,
        "document": {
            "batch_id":         batch_id,
            "invoice_no":       doc_invoice_no,
            "source_file_path": str(packing_file_path),
            "source_file_hash": file_sha256(packing_file_path),
            "parser_name":      parser_name,
            "parser_version":   parser_version,
            "extraction_status": "complete" if enriched else "empty",
            "parser_diagnostic": parser_diagnostic,
        },
        "matched_count":   matched,
        "unmatched_count": unmatched,
        "total_rows":      len(enriched),
    }
