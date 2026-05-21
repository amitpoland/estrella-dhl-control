"""
global_jewellery_supplier_profile.py — Permanent supplier profile for
Global Jewellery Pvt. Ltd. shipments.

Authority split:
  - Invoice  → financial totals (FOB / Freight / Insurance / CIF / unit
               counts), already extracted by the engine's parse_invoice
               in the `global_jewellery` invoice_format branch.
  - Packing  → product rows (jewellery type, metal, stones, qty, weight,
               per-line rate, per-line amount, customs description).

This module owns the packing-side extraction + the bilingual PL/EN
description rules engine for Global lines. It is invoked from
``routes_dhl_clearance._synthesize_rows_from_invoice_aggregates`` only
when the supplier is detected as Global Jewellery.

NEVER:
  - touches Estrella supplier logic (no change to invoice_intake_parser,
    customs_description_engine, or product_identity_engine)
  - modifies CIF / customs threshold / SAD/ZC429 gates
  - introduces wFirma / PZ / proforma writes
  - changes DB schema

All Estrella code paths must be invariant under this addition — the
supplier-detector returns False for non-Global invoices and the row
builder is never called for them.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Supplier identification
# ─────────────────────────────────────────────────────────────────────────────

SUPPLIER_NAME       = "GLOBAL JEWELLERY PVT LTD"
INVOICE_FORMAT      = "global_jewellery"   # set by engine.parse_invoice
SUPPLIER_KEY        = "global_jewellery"

# Engine-side marker phrases that uniquely identify a Global invoice
# (also catches edge cases where invoice_format wasn't set).
_GLOBAL_MARKERS = (
    "Global Jewellery Pvt. Ltd.",
    "GLOBAL JEWELLERY PVT",
)


_RE_GLOBAL_INVOICE_NUMBER = re.compile(
    # Global "Exporter's Ref" pattern: NNN/YYYY-YYYY (e.g. 088/2026-2027)
    r"\b(\d{1,4}/\d{4}-\d{4})\b"
)


def extract_invoice_number_from_text(raw_text: str) -> Optional[str]:
    """Find the Global Exporter's Ref invoice number (e.g. 088/2026-2027)
    in the engine's raw_text. Returns None if absent — caller can fall
    back to the engine's invoice_no (filename stem).
    """
    if not raw_text:
        return None
    m = _RE_GLOBAL_INVOICE_NUMBER.search(raw_text)
    return m.group(1) if m else None


def is_global_jewellery_invoice(invoice_dict: Optional[Dict[str, Any]]) -> bool:
    """Return True iff *invoice_dict* (the engine's parse_invoice output)
    represents a Global Jewellery Pvt. Ltd. invoice.

    Detects via either the engine's `invoice_format` field (preferred,
    set deterministically by the engine when it matches its global
    layout) or via raw-text marker phrases (fallback for edge cases).
    """
    if not isinstance(invoice_dict, dict):
        return False
    fmt = str(invoice_dict.get("invoice_format") or "").strip().lower()
    if fmt == INVOICE_FORMAT:
        return True
    raw = str(invoice_dict.get("_raw_text") or "")
    return any(m in raw for m in _GLOBAL_MARKERS)


# ─────────────────────────────────────────────────────────────────────────────
# Jewellery type mapping (operator-locked vocabulary)
# ─────────────────────────────────────────────────────────────────────────────

# Maps the per-row jewellery-type token from the Global invoice (Bracelet,
# Pendant, Ring, etc.) to:
#   - canonical EN type (used by customs_description_engine grouping)
#   - Polish singular form (used in the PL description prefix)
#   - English form for the "EN line"
#
# Engine grouping uses item_type uppercase; keep that contract intact.
_TYPE_TABLE: Dict[str, Dict[str, str]] = {
    "RING":     {"en": "RING",     "pl": "Pierścionek",      "en_label": "RING"},
    "PENDANT":  {"en": "PENDANT",  "pl": "Wisiorek",         "en_label": "PENDANT"},
    "EARRING":  {"en": "EARRINGS", "pl": "Kolczyki",         "en_label": "EARRINGS"},
    "EARRINGS": {"en": "EARRINGS", "pl": "Kolczyki",         "en_label": "EARRINGS"},
    "BRACELET": {"en": "BRACELET", "pl": "Bransoletka",      "en_label": "BRACELET"},
    "BANGLE":   {"en": "BANGLE",   "pl": "Bransoletka sztywna", "en_label": "BANGLE"},
    "NECKLACE": {"en": "NECKLACE", "pl": "Naszyjnik",        "en_label": "NECKLACE"},
    "CHAIN":    {"en": "NECKLACE", "pl": "Łańcuszek",        "en_label": "CHAIN"},
    "CUFFLINK": {"en": "CUFFLINKS","pl": "Spinki do mankietów", "en_label": "CUFFLINKS"},
    "CUFFLINKS":{"en": "CUFFLINKS","pl": "Spinki do mankietów", "en_label": "CUFFLINKS"},
}


def normalize_type(raw: str) -> Optional[str]:
    """Normalise a Global per-row jewellery-type token to the canonical
    upper-case key used by _TYPE_TABLE.

    Returns None when the token isn't recognised — caller decides
    whether to skip or fall back. (We DO NOT emit ``UNKNOWN`` as a
    placeholder per operator spec.)
    """
    if not raw:
        return None
    t = raw.strip().upper()
    # Singular ↔ plural normalisation
    if t in _TYPE_TABLE:
        return t
    if t.endswith("S") and t[:-1] in _TYPE_TABLE:
        return t[:-1]
    if (t + "S") in _TYPE_TABLE:
        return t
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Metal mapping (purity + Polish/English forms)
# ─────────────────────────────────────────────────────────────────────────────
#
# Polish form follows operator's locked vocabulary:
#   925 Silver  → "ze srebra próby 925"
#   14KT Gold   → "ze złota próby 585"
#   09KT Gold   → "ze złota próby 375"
#   18KT Gold   → "ze złota próby 750"
#   22KT Gold   → "ze złota próby 916"
#   PT950       → "z platyny próby 950"
#
# English form mirrors the way Global writes it on the invoice line
# (rule samples: "925 Silver Plain Jewellery RING").
_METAL_TABLE: Tuple[Tuple[str, str, str], ...] = (
    # (canonical_key, polish_phrase, english_label)
    ("925 SILVER", "ze srebra próby 925", "925 Silver"),
    ("14KT GOLD",  "ze złota próby 585",  "14KT Gold"),
    ("09KT GOLD",  "ze złota próby 375",  "09KT Gold"),
    ("9KT GOLD",   "ze złota próby 375",  "09KT Gold"),
    ("18KT GOLD",  "ze złota próby 750",  "18KT Gold"),
    ("22KT GOLD",  "ze złota próby 916",  "22KT Gold"),
    ("PT950",      "z platyny próby 950", "PT950 Platinum"),
    ("PT900",      "z platyny próby 900", "PT900 Platinum"),
)


def normalize_metal(raw: str) -> Optional[Dict[str, str]]:
    """Match the metal token from a Global line/category header.

    Recognises common spellings: "925 Purity Silver" / "925 Silver",
    "09KT Gold" / "9KT Gold", "14KT Gold", etc. Case-insensitive.

    Returns {key, pl, en} on match, None when nothing matches (caller
    must decide; we never emit "metal szlachetny" generic fallback for
    Global lines).
    """
    if not raw:
        return None
    u = raw.upper().replace(",", " ").replace("PURITY ", "")
    u = re.sub(r"\s+", " ", u).strip()
    # KT variants without space e.g. "14KT" ; or with space "14 KT"
    u = re.sub(r"(\d+)\s*KT", r"\1KT", u)
    for key, pl, en in _METAL_TABLE:
        # Key already in canonical form ("925 SILVER", "14KT GOLD" etc)
        if key in u:
            return {"key": key, "pl": pl, "en": en}
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Stone mapping (PL / EN bilingual)
# ─────────────────────────────────────────────────────────────────────────────
#
# Stone vocabulary from operator rules + observed Global invoice tokens.
# Order matters: composite stones (LGD, DIA & CLS) MUST match before
# their components.
#
# Each entry maps to:
#   - PL adornment phrase (e.g. "wysadzany cyrkoniami")
#   - EN qualifier         (e.g. "CZ Stud Jewellery")
#
# Plain (no stone) is the explicit "Plain" or "Plain Jewellery" case.
_STONE_RULES: Tuple[Tuple[str, str, str], ...] = (
    # (regex pattern, polish adornment, english qualifier)
    (r"\bLGD\b",
     "z diamentami laboratoryjnymi",
     "Lab Grown Diamond Jewellery"),
    (r"\bLAB\s*GROWN\s+DIAMOND",
     "z diamentami laboratoryjnymi",
     "Lab Grown Diamond Jewellery"),
    # DIA + CZ combo
    (r"\bDIA\s*&\s*CZ\b|\bDIA.?CZ\b",
     "wysadzany diamentami i cyrkoniami",
     "Diamond & CZ Stud Jewellery"),
    # CZ + Colour Stone combo (operator Rule C)
    (r"\bCZ.{0,3}CLS\b|\bCLS.{0,3}CZ\b",
     "wysadzany cyrkoniami i kamieniami kolorowymi",
     "CZ & Colour Stone Jewellery"),
    (r"\bCZ\b",
     "wysadzany cyrkoniami",
     "CZ Stud Jewellery"),
    (r"\bDIA\b|\bDIAMOND\b",
     "z diamentami",
     "Diamond Jewellery"),
    (r"\bCLS\b|\bCOLOUR\s+STONE\b|\bCOLOR\s+STONE\b",
     "wysadzany kamieniami kolorowymi",
     "Colour Stone Jewellery"),
    # Plain — explicit
    (r"\bPLAIN\b",
     "",   # plain → no adornment phrase
     "Plain Jewellery"),
)


def normalize_stone(raw: str) -> Dict[str, str]:
    """Detect stone vocabulary from a Global category header / row text.

    Returns ``{"pl": <adornment phrase or ''>, "en": <qualifier or 'Plain Jewellery'>}``.

    "Plain" / no-stone case → pl=''  en='Plain Jewellery'. Caller composes.
    """
    if not raw:
        return {"pl": "", "en": "Plain Jewellery"}
    r_up = raw.upper()
    for pat, pl, en in _STONE_RULES:
        if re.search(pat, r_up):
            return {"pl": pl, "en": en}
    # No stone matched — treat as plain (never emit UNKNOWN for stones)
    return {"pl": "", "en": "Plain Jewellery"}


# ─────────────────────────────────────────────────────────────────────────────
# Bilingual description renderer
# ─────────────────────────────────────────────────────────────────────────────


def render_description(jewellery_type: str, metal_raw: str, stone_raw: str
                       ) -> Dict[str, str]:
    """Produce ``{pl, en, item_type, item_type_pl}`` for one Global line.

    Implements operator-locked rules (Rule A–E) plus consistent
    extensions for additional combinations.

    The returned strings are intentionally template-rendered (no LLM, no
    learning) so the customs description is deterministic and reviewable.
    """
    t_key = normalize_type(jewellery_type)
    metal = normalize_metal(metal_raw or "")
    stone = normalize_stone(stone_raw or "")

    if t_key is None or metal is None:
        # Operator spec: never emit UNKNOWN/placeholder. Best-effort
        # English label + Polish "biżuteria" with the metal/stone we DID
        # detect, but flagged so the caller can decide whether to abort
        # extraction and fall back.
        return {
            "pl": "",
            "en": "",
            "item_type":    "",
            "item_type_pl": "",
            "_unmapped":    "1",
        }

    type_info = _TYPE_TABLE[t_key]
    pl_type   = type_info["pl"]
    en_type   = type_info["en_label"]

    # Polish: <pl_type> <metal_pl>[ <stone_pl>]
    pl_parts = [pl_type, metal["pl"]]
    if stone["pl"]:
        pl_parts.append(stone["pl"])
    pl = " ".join(p for p in pl_parts if p).strip()

    # English: "<metal_en> <stone_en> <EN_TYPE>"
    # Convention from operator rules: stone qualifier in English ends in
    # "Jewellery", then the upper-cased type label.
    en_parts = [metal["en"], stone["en"], en_type]
    en = " ".join(p for p in en_parts if p).strip()

    return {
        "pl":           pl,
        "en":           en,
        "item_type":    type_info["en"],   # uppercase canonical, for engine grouping
        "item_type_pl": pl_type,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Per-line extraction from Global invoice PDF text
# ─────────────────────────────────────────────────────────────────────────────

# Pattern for category header lines:
#   "PCS, 925 Purity Silver, Studed Jewellery CZ, CLS"
#   "PRS, 14KT Gold, LGD Gold Stud Jewell"
#   "PCS, 09KT Gold, LGD Gold Stud Jewell"
_RE_CATEGORY = re.compile(
    r"^(?P<unit>PCS|PRS)\s*,\s*(?P<metal>[^,]+?),\s*(?P<description>.+)$",
    re.IGNORECASE,
)

# Pattern for product-row lines:
#   "Bracelet 8.982 9.860 2.0 302.00 604.00 ..."
#   "Ring 33.362 36.220 15.0 7.27 109.00 ..."
# Six numeric tokens after the type word, with the 6th being the amount.
_RE_PRODUCT_ROW = re.compile(
    r"^(?P<type>Bracelet|Pendant|Ring|Bangle|Earring|Earrings|Necklace|Chain|Cufflink|Cufflinks)"
    r"\s+(?P<net_wt>\d+\.\d+)"
    r"\s+(?P<gross_wt>\d+\.\d+)"
    r"\s+(?P<qty>\d+(?:\.\d+)?)"
    r"\s+(?P<rate>\d+(?:\.\d+)?)"
    r"\s+(?P<amount>\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)


def extract_lines_from_text(raw_text: str) -> List[Dict[str, Any]]:
    """Parse Global invoice PDF text into structured product rows.

    Walks line by line, tracking the most-recent ``PCS,``/``PRS,``
    category header and applying it to subsequent product rows until
    a new header appears.

    Returns a list of dicts (one per product row) carrying:
      unit (PCS|PRS), type_raw, type, metal_raw, stone_raw,
      net_wt, gross_wt, quantity, rate_usd, line_total_usd

    Does NOT inject descriptions — call ``build_global_invoice_rows``
    for the full row-shaped output the route layer expects.
    """
    rows: List[Dict[str, Any]] = []
    current_unit:   str = "PCS"
    current_metal:  str = ""
    current_stone:  str = ""

    for ln in raw_text.split("\n"):
        s = ln.strip()
        if not s:
            continue
        # Category header?
        m_cat = _RE_CATEGORY.match(s)
        if m_cat:
            current_unit  = m_cat.group("unit").upper()
            current_metal = m_cat.group("metal").strip()
            # description portion holds stone vocabulary (CZ, LGD, DIA, etc.)
            current_stone = m_cat.group("description").strip()
            continue
        # Product row?
        m_row = _RE_PRODUCT_ROW.match(s)
        if m_row:
            try:
                qty    = float(m_row.group("qty"))
                amount = float(m_row.group("amount"))
            except Exception:
                continue
            if qty <= 0 or amount <= 0:
                continue
            rows.append({
                "unit":          current_unit,
                "type_raw":      m_row.group("type"),
                "type":          (m_row.group("type") or "").upper(),
                "metal_raw":     current_metal,
                "stone_raw":     current_stone,
                "net_wt":        float(m_row.group("net_wt")),
                "gross_wt":      float(m_row.group("gross_wt")),
                "quantity":      qty,
                "rate_usd":      float(m_row.group("rate")),
                "line_total_usd": amount,
            })
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point: build rows for audit["rows"]
# ─────────────────────────────────────────────────────────────────────────────


def build_global_invoice_rows(
    invoice_no:     str,
    raw_text:       str,
    declared_fob:   float,
    tolerance_usd:  float = 1.00,
) -> List[Dict[str, Any]]:
    """Build the customs-description-ready row list from Global invoice
    PDF text.

    Steps:
      1. Extract per-line items from raw_text.
      2. Skip lines whose (type, metal) we cannot map (operator spec:
         never produce UNKNOWN customs rows).
      3. Generate product_code = ``<invoice_no>-<seq>``.
      4. Render bilingual PL/EN description via ``render_description``.
      5. Validate row sum reconciles with declared_fob within tolerance.

    Returns:
      - Non-empty row list if extraction succeeded AND sums reconcile.
      - Empty list otherwise — the caller MUST fall back to its prior
        synthesis path.

    The returned dicts are shaped to be directly assignable to
    ``audit["rows"]`` and consumed by both ``_reconcile_rows_with_audit_totals``
    and the customs_description_engine's per-line grouping.
    """
    extracted = extract_lines_from_text(raw_text)
    if not extracted:
        return []

    out: List[Dict[str, Any]] = []
    total = 0.0
    for seq, x in enumerate(extracted, start=1):
        desc = render_description(x["type_raw"], x["metal_raw"], x["stone_raw"])
        if desc.get("_unmapped") == "1":
            # We refuse to emit a row we cannot describe — operator spec:
            # never produce UNKNOWN rows. Caller falls back.
            return []
        product_code = f"{invoice_no}-{seq}"
        line_total = round(float(x["line_total_usd"]), 2)
        unit_price = round(line_total / x["quantity"], 6) if x["quantity"] else 0.0
        out.append({
            "invoice_number":             invoice_no,
            "line_position":              seq,
            "product_code":               product_code,
            "description":                desc["en"],   # used by engine's text-scan
            "polish_customs_description": desc["pl"],   # used by engine PDF render
            "description_en":             desc["en"],
            "description_pl":             desc["pl"],
            "item_type":                  desc["item_type"],
            "item_type_pl":               desc["item_type_pl"],
            "material":                   "",  # engine derives from description
            "quantity":                   float(x["quantity"]),
            "unit_price":                 unit_price,
            "line_total":                 line_total,
            "line_total_usd":             line_total,
            "hsn_code":                   "",
            "currency":                   "USD",
            "uom":                        x["unit"],   # PCS or PRS
            "net_weight":                 x["net_wt"],
            "gross_weight":               x["gross_wt"],
            "_supplier_profile":          SUPPLIER_KEY,
        })
        total += line_total

    # Reconciliation: row sum MUST match declared FOB within tolerance.
    # If it doesn't, return empty — caller falls back rather than emit
    # rows the reconciler will reject downstream anyway.
    if declared_fob > 0 and abs(round(total, 2) - round(declared_fob, 2)) > tolerance_usd:
        return []
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: extract directly from a PDF file path
# ─────────────────────────────────────────────────────────────────────────────


def build_rows_from_pdf(
    pdf_path:       Path,
    invoice_no:     str,
    declared_fob:   float,
    tolerance_usd:  float = 1.00,
) -> List[Dict[str, Any]]:
    """Open *pdf_path* via pdfplumber, extract raw text, build rows.

    Returns empty list on any failure (file missing, pdfplumber crash,
    no extractable lines, sum doesn't reconcile). Caller falls back.
    """
    try:
        import pdfplumber
    except Exception:
        return []
    try:
        text_parts: List[str] = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                text_parts.append(page.extract_text() or "")
        full_text = "\n".join(text_parts)
    except Exception:
        return []
    return build_global_invoice_rows(invoice_no, full_text, declared_fob, tolerance_usd)
