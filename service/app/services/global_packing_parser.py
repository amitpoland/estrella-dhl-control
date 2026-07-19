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

from .excel_reader import read_excel_rows as _read_excel_rows

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
    """Convert any value to float. Returns 0.0 on error — never raises.

    Delegates to the canonical packing normaliser so both parsers agree on
    comma handling; this module previously stripped every comma, turning the
    decimal-comma form "1234,56" into 123456.0 (a silent 100x overstatement).
    """
    from .invoice_packing_extractor import _safe_float as _canonical  # noqa: PLC0415

    return _canonical(val)


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


# ─────────────────────────────────────────────────────────────────────────────
# PDF packing-list parser
# ─────────────────────────────────────────────────────────────────────────────
#
# Global supplier sometimes ships the packing list as a PDF whose table is
# rendered via text positioning (not native PDF tables). pdfplumber's
# extract_tables() returns nothing for this layout — but extract_text()
# returns a clean line-per-row stream.
#
# Row pattern (sr.no anchored):
#
#   <sr.no> <Type> <Style+Metal> <qty> <grs_wt> <net_wt> <stone metadata…> <FOB> <FOB>
#
# - Sr.no is a small integer (1..N)
# - Type ∈ {Bracelet, Pendant, Ring, Bangle, Earrings/Earring, Necklace, Chain}
# - Style + Metal: one or two tokens. Metal suffixes: 925SL, 9, 14, 18, 22, PT950.
#   Sometimes concatenated when the supplier omits a space (e.g. "CAO0233EH-1.50925SL")
# - qty is a small int (almost always 1)
# - grs_wt / net_wt are floats with 3 decimals
# - FOB appears twice at end as `<f>.00 <f>.00` (two equal floats)
#
# Continuation lines (no sr.no anchor) carry additional stone metadata for
# the previous item — they are aggregated as stone-detail metadata into the
# anchor row but do NOT add a new row.
#
# Pure read of the PDF text. NEVER touches CIF formula, customs threshold,
# wFirma/PZ writes, DB schema, or Estrella code paths.


_PDF_PARSER_NAME = "global_packing_pdf_v1"
_PDF_PARSER_VERSION = "1.0"


_TYPE_WORDS = (
    "Bracelet", "Pendant", "Ring", "Bangle",
    "Earrings", "Earring", "Necklace", "Chain", "Cufflinks", "Cufflink",
)
_TYPE_WORDS_RE = r"(?:" + "|".join(_TYPE_WORDS) + r")"

# Metal suffix tokens that may be glued to the end of the style code.
# Ordered longest-first so 925SL is preferred over standalone "9".
_METAL_SUFFIX_TOKENS = (
    "925SL",
    "PT950", "PT900",
    "22KT", "18KT", "14KT", "9KT",
    "925",
    "22", "18", "14", "9",  # bare KT numbers (the PDF table uses these)
)

# A product-row anchor pattern. Captures up through net_wt; everything from
# net_wt forward is stone-detail (optional) until the trailing
# "<FOB> <FOB>" pair. Some rows carry no stone metadata at all — the
# regex makes ``rest`` optional so those still match.
_RE_PDF_PRODUCT_ROW = re.compile(
    rf"^(?P<srno>\d+)\s+"
    rf"(?P<type>{_TYPE_WORDS_RE})\s+"
    rf"(?P<style_metal_qty>.+?)\s+"
    rf"(?P<grs>\d+\.\d{{3}})\s+"
    rf"(?P<net>\d+\.\d{{3}})"
    rf"(?:\s+(?P<rest>.+?))?\s+"
    rf"(?P<fob_a>\d+\.\d{{2}})\s+(?P<fob_b>\d+\.\d{{2}})\s*$"
)


def _split_style_metal_qty(blob: str) -> Tuple[str, str, int]:
    """Split the messy blob between Type and gross_wt into (style, metal, qty).

    Layouts:
      "JBR00377 9 1"                  → style=JBR00377, metal=9,    qty=1
      "J3609P0119 925SL 1"            → style=J3609P0119, metal=925SL, qty=1
      "CAO0233EH-1.50925SL 1"         → style=CAO0233EH-1.50, metal=925SL, qty=1
        (supplier omitted the space — split on the trailing metal suffix)
      "JR08296 925SL/ 14KT CO 1M"     → style=JR08296, metal=925SL, qty=1
        (multi-metal alloy: prefer the first listed; tolerate qty
         OCR garbage like "1M")
      "CSTR04794-J-HA9F25SL 1"        → style=CSTR04794-J-HA9F, metal=925SL, qty=1
        (OCR slipped "9" off "925SL"; trailing "25SL" → treat as 925SL)

    Returns ("", "", 1) on failure so caller can still record the row
    via the fallback (FOB still extracts via the outer regex).
    """
    parts = blob.strip().split()
    if not parts:
        return ("", "", 1)
    # Last token is qty — be tolerant of OCR-trailing-letter garbage
    # like "1M" / "1 M" / "1." Strip any trailing non-digit chars first.
    qty_raw = re.sub(r"[^\d]+$", "", parts[-1])
    try:
        qty = int(qty_raw) if qty_raw else 1
    except ValueError:
        qty = 1
    rest = parts[:-1]
    if not rest:
        return ("", "", qty)

    # Multi-metal alloy designations: "925SL/" or "925SL/ 14KT CO" — take
    # the first metal-shaped token from the front of rest and treat the
    # rest of the alloy descriptor as style annotation.
    for i, tok in enumerate(rest):
        # Strip alloy markers and combo separators
        clean = tok.rstrip("/").rstrip()
        if clean in _METAL_SUFFIX_TOKENS:
            # Style = everything before this metal token
            style = " ".join(rest[:i]) if i > 0 else " ".join(rest[:-1] or rest)
            return (style, clean, qty)

    # Common case: rest = [style, metal]
    if len(rest) >= 2:
        last = rest[-1]
        if last in _METAL_SUFFIX_TOKENS:
            style = " ".join(rest[:-1])
            return (style, last, qty)

    # Single token in rest — try to split off a trailing metal suffix
    blob_no_qty = " ".join(rest)
    for ms in _METAL_SUFFIX_TOKENS:
        if blob_no_qty.endswith(ms) and len(blob_no_qty) > len(ms):
            style = blob_no_qty[: -len(ms)].rstrip()
            return (style, ms, qty)

    # OCR-quirky fallbacks: trailing "25SL" almost certainly means 925SL
    # (the supplier's metal column is 925SL; OCR dropped the leading 9).
    if blob_no_qty.endswith("25SL") and len(blob_no_qty) > 4:
        style = blob_no_qty[:-4].rstrip()
        return (style, "925SL", qty)

    # Couldn't separate — return blob as style, blank metal so caller
    # can record the row even if vocabulary rendering is incomplete.
    return (blob_no_qty, "", qty)


_METAL_KEY_NORMALISE = {
    "925SL": "925 SILVER",
    "925":   "925 SILVER",
    "9":     "9KT GOLD",
    "9KT":   "9KT GOLD",
    "14":    "14KT GOLD",
    "14KT":  "14KT GOLD",
    "18":    "18KT GOLD",
    "18KT":  "18KT GOLD",
    "22":    "22KT GOLD",
    "22KT":  "22KT GOLD",
    "PT950": "PT950",
    "PT900": "PT900",
}


def _normalise_metal_token(metal_raw: str) -> str:
    """Map the cryptic Global packing metal column (`925SL`, `9`, `14`, etc.)
    to a canonical key downstream description engines understand."""
    return _METAL_KEY_NORMALISE.get(metal_raw.strip().upper(), metal_raw.strip())


_RE_PDF_INVOICE_NO = re.compile(r"Inv\s*Exp\s*No\s*:\s*(\S+)", re.IGNORECASE)


def parse_global_packing_pdf(
    path: Path,
    invoice_no: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], str, str, Dict[str, Any]]:
    """Parse a Global Jewellery packing-list **PDF** file.

    Pure read of pdfplumber text output. Walks every line; matches sr.no
    anchored product rows; ignores continuation lines (additional stone
    metadata for the preceding item).

    Returns ``(rows, parser_name, parser_version, diag)`` — same shape
    as the Excel parser, so the dispatcher in
    ``invoice_packing_extractor.extract_packing`` can use either.

    Never raises on malformed fragments like ``"ite 1"`` or ``"######"``;
    such lines simply fail the row-regex and are skipped.
    """
    diag = _new_diag()
    rows: List[Dict[str, Any]] = []

    try:
        import pdfplumber
    except ImportError:
        diag["failure_reason"] = "pdfplumber_not_installed"
        return rows, _PDF_PARSER_NAME, _PDF_PARSER_VERSION, diag

    text_lines: List[str] = []
    try:
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                for ln in t.split("\n"):
                    text_lines.append(ln)
    except Exception as exc:
        log.warning("global_packing_pdf: cannot read %s: %s", path, exc)
        diag["failure_reason"] = "file_open_error"
        return rows, _PDF_PARSER_NAME, _PDF_PARSER_VERSION, diag

    # Try to recover invoice_no from header lines if not provided
    if not invoice_no:
        for ln in text_lines[:30]:
            m = _RE_PDF_INVOICE_NO.search(ln)
            if m:
                invoice_no = m.group(1).strip()
                break

    diag["invoice_no"] = invoice_no or ""

    # Walk lines; for each anchored product row, emit one packing-line dict.
    # Continuation lines (no sr.no.) carry extra stone metadata which we
    # append to the previous row's stone_detail aggregate.
    last_row_idx: int = -1
    for ln in text_lines:
        if not ln or not ln.strip():
            continue
        m = _RE_PDF_PRODUCT_ROW.match(ln.strip())
        if not m:
            # Continuation row? Append to previous if it looks like stone meta.
            if last_row_idx >= 0:
                rows[last_row_idx]["stone_detail"] = (
                    (rows[last_row_idx].get("stone_detail") or "") + " | " + ln.strip()
                ).strip(" |")
            continue

        try:
            srno = int(m.group("srno"))
        except ValueError:
            continue

        style, metal_raw, qty = _split_style_metal_qty(m.group("style_metal_qty"))
        grs_wt = _safe_float(m.group("grs"))
        net_wt = _safe_float(m.group("net"))
        try:
            fob = _safe_float(m.group("fob_b"))
        except Exception:
            fob = 0.0

        # The first FOB value SHOULD equal the second (rate × qty when qty=1).
        # We use fob_b as authoritative because it's the rightmost extended
        # amount column on the packing layout.

        # Stone detail captured from the optional "rest" middle (between
        # net_wt and FOB). Plain-jewellery rows have no rest section.
        stone_detail = (m.group("rest") or "").strip() if m.group("rest") else ""

        inv = invoice_no or "GLOBAL"
        product_code = f"{inv}-{srno}"

        row_dict = {
            "serial_no":              srno,
            "product_code":           product_code,
            "invoice_no":             inv,
            "invoice_line_position":  srno,
            "item_type":              m.group("type"),
            "design_no":              style,
            "metal":                  _normalise_metal_token(metal_raw),
            "metal_raw":              metal_raw,
            "stone_detail":           stone_detail,
            # Alias for packing_db.upsert_packing_lines schema (stone_type col)
            "stone_type":             stone_detail,
            "quantity":               float(qty),
            "gross_weight":           grs_wt,
            "net_weight":             net_wt,
            "unit_price":             fob,    # qty=1 per row in this format
            "total_value":            fob,
            "remarks":                "",
            "extracted_confidence":   1.0,
            "requires_manual_review": False,
            "supplier":               "global_jewellery",
        }
        rows.append(row_dict)
        last_row_idx = len(rows) - 1

        diag["total_qty"]      += float(qty)
        diag["total_fob_usd"]  += fob
        diag["total_gross_wt"] += grs_wt
        diag["total_net_wt"]   += net_wt

    diag["rows_extracted"] = len(rows)
    if not rows:
        diag["failure_reason"] = "no_valid_rows"

    diag["total_qty"]      = round(diag["total_qty"], 3)
    diag["total_fob_usd"]  = round(diag["total_fob_usd"], 2)
    diag["total_gross_wt"] = round(diag["total_gross_wt"], 3)
    diag["total_net_wt"]   = round(diag["total_net_wt"], 3)

    return rows, _PDF_PARSER_NAME, _PDF_PARSER_VERSION, diag
