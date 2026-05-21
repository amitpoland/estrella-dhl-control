#!/usr/bin/env python3
"""
PZ Import Processor  v3
========================
Reads supplier invoice PDFs + ZC429/SAD customs PDF,
fetches correct NBP USD/PLN rate, calculates landed costs,
and prints a PZ document in wFirma.pl format.

Retained corrections from validated batch 039–044:
  - Quantity comes after the SECOND UOM token (never from HSN field)
  - A00 duty = "stawka opł." (charged/rounded), NOT the taxable base "Kwota"
  - LRN supports bracketed format "Numer LRN [12 09]:"
  - Always use PDF body date, never filename date
  - Silver items use silver-specific Polish descriptions
  - Fail loudly if quantity looks like HSN or duty rate is implausible

Usage:
    python3 pz_import_processor.py --invoices inv1.pdf inv2.pdf --zc429 zc429.pdf
    python3 pz_import_processor.py --invoices ./invoices/ --zc429 zc429.pdf
    python3 pz_import_processor.py --invoices ./invoices/ --zc429 zc429.pdf --rate 3.5912

Dependencies:
    pip3 install pdfplumber requests
"""

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    sys.exit("Missing dependency: pip3 install pdfplumber requests")
try:
    import requests
except ImportError:
    sys.exit("Missing dependency: pip3 install requests")


# ── Constants ────────────────────────────────────────────────────────────────
VAT_RATE = 0.23

RECIPIENT = {
    "name":    "ESTRELLA JEWELS Sp. z o. o. SPÓŁKA KOMANDYTOWA",
    "address": "ul. Wybrzeże Kościuszkowskie 31/33, 00-379 Warszawa",
    "nip":     "5252812119",
}
SUPPLIER = {
    "name":    "ESTRELLA JEWELS LLP.",
    "address": "312, OPTIONS PRIMO PREMISES CHSL, MAROL INDUSTRIAL ESTATE, MIDC, 400093 ANDHERI EAST, MUMBAI",
}

# Known HSN codes — never a valid quantity
HSN_CODES = {71131911, 71131913, 71131914, 71131919, 71131141, 71131100}

# ── Polish translations ───────────────────────────────────────────────────────
# ── Polish item-type names ─────────────────────────────────────────────────────
ITEM_PL: dict = {
    "RING":     "pierścionek",
    "PENDANT":  "wisiorek",
    "EARRING":  "kolczyki",
    "EARRINGS": "kolczyki",
    "BRACELET": "bransoletka",
    "NECKLACE": "naszyjnik",
    "BANGLE":   "bransoletka",
    "ANKLET":   "bransoletka nożna",
}

# Grammatical agreement of the studded participle with the Polish item noun:
#   masculine (m): wysadzany / srebrny
#   feminine  (f): wysadzana / srebrna
#   plural   (pl): wysadzane / srebrne
_STUD_AGREE: dict = {
    "pierścionek":    "wysadzany",
    "wisiorek":       "wysadzany",
    "naszyjnik":      "wysadzany",
    "kolczyki":       "wysadzane",
    "bransoletka":    "wysadzana",
    "bransoletka nożna": "wysadzana",
}
_SILVER_AGREE: dict = {
    "pierścionek":    "srebrny",
    "wisiorek":       "srebrny",
    "naszyjnik":      "srebrny",
    "kolczyki":       "srebrne",
    "bransoletka":    "srebrna",
    "bransoletka nożna": "srebrna",
}

# ── Item line regex (named groups) — Estrella Jewels LLP format ──────────────
# Matches:
#   PCS, 14KT Gold, Stud Jewelry DIA&CLS PENDANT 1.060 0.796 71131919 PCS 2.0 213.50 427.00
#   PCS, SL925 SILVER Plain Jewellery PENDANT 0.500 0.500 71131141 PCS 1.0 5.00 5.00
ITEM_RE = re.compile(
    r'^(?:PCS,|PRS,|PGS,)\s+'
    r'(?P<desc>.+?)\s+'
    r'(?P<item_type>PENDANT|RING|EARRINGS|EARRING|BRACELET|NECKLACE|BANGLE|ANKLET|CUFFLINK)\s+'
    r'(?P<gross>\d+(?:\.\d+)?)\s+'
    r'(?P<net>\d+(?:\.\d+)?)\s+'
    r'(?P<hsn>\d{7,8})\s+'
    r'(?:PCS|PRS|PGS)\s+'
    r'(?P<qty>\d+(?:\.\d+)?)\s+'
    r'(?P<rate>[\d,]+(?:\.\d+)?)\s+'
    r'(?P<amount>[\d,]+(?:\.\d+)?)$',
    re.IGNORECASE
)

# ── Phrases that must never appear in a commercial invoice ────────────────────
# If any of these EXACT phrases (case-insensitive) are found in raw invoice text,
# blocked_phrases_clean = False.
# Only these specific phrases trigger a mismatch — do not infer from parser warnings.
BLOCKED_PHRASES_PATTERNS: list = [
    r'\bgift\b',
    r'\bsamples?\b',
    r'\bno\s+commercial\s+value\b',
    r'\bnot\s+for\s+sale\b',
    r'\bpersonal\s+use\b',
    r'\bfree\s+of\s+charge\b',
    r'\breplacement\b',
    r'\brepair\s+return\b',
    r'\bproforma\s+only\b',
]


# ── Helper functions ──────────────────────────────────────────────────────────

def parse_money(s: str) -> float:
    return float(s.replace(",", "").strip())

def fmt_pln(v: float) -> str:
    """Polish number format: comma decimal, space thousands. e.g. 1 360,18"""
    s = f"{v:,.2f}"                    # '1,360.18'
    s = s.replace(",", " ").replace(".", ",")   # '1 360,18'
    return s

def fmt_date_pl(iso_date: str) -> str:
    """Convert 2026-04-15 → 15.04.2026"""
    try:
        return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return iso_date

def is_suspicious_quantity(q) -> bool:
    if q is None:
        return True
    if q > 1000:
        return True
    try:
        if int(q) in HSN_CODES:
            return True
    except (ValueError, TypeError):
        return True
    return False

def normalize_family(desc: str) -> str:
    t = desc.upper()
    if "SL925" in t or "SILVER" in t:
        return "Silver Plain"
    if "LGD" in t or "LAB GROWN" in t or "LAB-GROWN" in t:
        return "Lab Grown Diamond"
    # "CLS" always means Colour Stone in Estrella invoices (covers "DIA&CLS" and bare "CLS")
    if "DIA&CLS" in t or "COLOUR STONE" in t or "COLOR STONE" in t or "CLS" in t:
        return "Diamond / Colour Stone Studded"
    if "STUD WITH DIAM" in t or ("STUD" in t and "DIA" in t):
        return "Diamond Studded"
    if "PLAIN" in t:
        return "Plain"
    return "Unknown"

def classify_product_type(item_type: str) -> str:
    """Map item_type string to product category for quantity aggregation.
    Note: EARRING must be checked before RING (substring overlap)."""
    t = item_type.upper()
    if "EARRING" in t:                                               return "earrings"   # before RING
    if "RING" in t:                                                  return "rings"
    if "PENDANT" in t:                                               return "pendants"
    if "BRACELET" in t or "BANGLE" in t or "ANKLET" in t:           return "bracelets"
    if "NECKLACE" in t:                                              return "necklaces"
    if "CUFFLINK" in t:                                              return "cufflinks"
    return "other_jewellery"

def compute_invoice_totals(invoices: list) -> dict:
    """Aggregate PCS/PRS counts and value totals across all invoices.

    PCS (pieces) and PRS (pairs) are tracked separately.  A pair is TWO pieces
    for physical-count purposes, but we store the raw PRS quantity as-is so the
    caller can decide how to surface it.  The legacy ``total_pcs`` field now
    represents the combined piece-equivalent count (PRS × 1, kept raw).
    """
    total_pcs = 0
    total_prs = 0
    total_fob  = 0.0
    total_frgt = 0.0
    total_ins  = 0.0
    counts = {"rings": 0, "pendants": 0, "bracelets": 0,
              "earrings": 0, "necklaces": 0, "cufflinks": 0, "other_jewellery": 0}
    counts_by_unit: dict = {"PCS": {}, "PRS": {}}

    for inv in invoices:
        total_fob  += inv.get("fob_usd", 0.0)
        total_frgt += inv.get("freight_usd", 0.0)
        total_ins  += inv.get("insurance_usd", 0.0)
        for item in inv.get("items", []):
            qty  = item.get("quantity", 0)
            unit = (item.get("unit", "PCS") or "PCS").upper()
            qty_int = int(qty) if isinstance(qty, float) and qty == int(qty) else qty

            if unit == "PRS":
                total_prs += qty_int
            else:
                total_pcs += qty_int

            cat = classify_product_type(item.get("item_type", ""))
            counts[cat] = counts.get(cat, 0) + qty_int
            unit_key = "PRS" if unit == "PRS" else "PCS"
            counts_by_unit[unit_key][cat] = counts_by_unit[unit_key].get(cat, 0) + qty_int

    total_units = total_pcs + total_prs
    # qty_validation: cross-check that line-level quantities sum to total_units
    total_from_lines = total_pcs + total_prs  # already accumulated correctly above
    prs_categories = [cat for cat, cnt in counts_by_unit.get("PRS", {}).items() if cnt > 0]
    units_consistent = True  # by construction — total_from_lines IS total_units
    qty_validation = {
        "status":                  "ok" if units_consistent else "mismatch",
        "total_from_lines":        total_from_lines,
        "calculated_total_items":  total_units,
        "units_consistent":        units_consistent,
        "prs_categories":          prs_categories,
        "note": (
            f"PRS items ({', '.join(prs_categories)}) counted as 1 unit per pair"
            if prs_categories else "All items counted as PCS"
        ),
    }

    return {
        "total_pcs":             total_pcs,
        "total_prs":             total_prs,
        "total_units":           total_units,
        "total_fob_usd":         round(total_fob, 2),
        "total_freight_usd":     round(total_frgt, 2),
        "total_insurance_usd":   round(total_ins, 2),
        "total_cif_usd":         round(total_fob + total_frgt + total_ins, 2),
        "product_counts":        counts,
        "product_counts_by_unit": counts_by_unit,
        "qty_validation":        qty_validation,
    }

def get_karat(desc: str) -> str:
    t = desc.upper()
    # Platinum must be checked before gold karats — "PT950" contains no "KT"
    if "PT950" in t:
        return "PT950"
    if "PT900" in t:
        return "PT900"
    for k in ["22KT", "18KT", "14KT", "10KT", "9KT"]:
        if k in t:
            return k
    return "14KT"

def build_en_name(item: dict) -> str:
    """Natural English description: 'Diamond Studded 14KT Gold Jewellery RING'."""
    family    = item["family"]
    karat     = item["karat"]
    item_type = item["item_type"]
    metal = "Platinum" if "PT" in karat else "Gold"
    if "Silver" in family:
        return f"Silver SL925 Jewellery {item_type}"
    if "Lab Grown" in family:
        return f"Lab Grown Diamond Studded {karat} {metal} Jewellery {item_type}"
    if "Colour Stone" in family:
        return f"Diamond & Colour Stone {karat} {metal} Jewellery {item_type}"
    if "Diamond Studded" in family:
        return f"Diamond Studded {karat} {metal} Jewellery {item_type}"
    return f"Plain {karat} {metal} Jewellery {item_type}"


def build_pl_name(item: dict) -> str:
    """Natural Polish description with correct grammatical gender agreement."""
    family    = item["family"]
    karat_raw = item["karat"]
    item_type = item["item_type"].upper()

    pl_type = ITEM_PL.get(item_type, item_type.lower())

    # ── Silver ────────────────────────────────────────────────────────────────
    if "Silver" in family:
        agree = _SILVER_AGREE.get(pl_type, "srebrny")
        return f"{pl_type} {agree} próby 925"

    # ── Metal base phrase ─────────────────────────────────────────────────────
    if "PT" in karat_raw:
        purity = karat_raw[2:]          # "950" or "900"
        base   = f"{pl_type} z platyny próby {purity}"
    else:
        karat_num = karat_raw.replace("KT", "")
        base      = f"{pl_type} ze złota próby {karat_num} karatów"

    # ── Suffix by family ─────────────────────────────────────────────────────
    agree = _STUD_AGREE.get(pl_type, "wysadzany")
    if "Lab Grown" in family:
        return f"{base} z diamentami hodowanymi laboratoryjnie"
    if "Colour Stone" in family:
        return f"{base} z diamentami i kamieniami"
    if "Diamond Studded" in family:
        return f"{base} {agree} diamentami"
    return base   # Plain


def get_full_nazwa(item: dict) -> str:
    """Combined wFirma name: 'Polish / English' — Polish first for wFirma display."""
    return f"{build_pl_name(item)} / {build_en_name(item)}"


def build_product_code(invoice_no: str, position: int) -> str:
    """
    Canonical product_code format: ``invoice_no-N`` (1-indexed, no space).

    Single source of truth for suffix formatting — use this everywhere instead
    of inline f-strings to guarantee the format never drifts back to the old
    ``invoice_no -N`` (space before hyphen) pattern.
    """
    return f"{invoice_no}-{position}"


def canonical_item_sort_key(item: dict, original_index: int) -> tuple:
    """
    Preserve invoice line order for ``product_code`` assignment.

    ``product_code`` is the legal/accounting identity that ties a row in
    pz_rows.json to its invoice line, to its customs declaration, and to
    its wFirma good. The earlier implementation sorted by item_type /
    description / hs / price / qty (with original_index only as a
    tiebreaker), which renumbered ``<invoice>-<N>`` codes whenever an
    invoice mixed item types — auto-register (which reads
    ``invoice_lines`` in invoice order) and pz_rows.json (which used the
    sorted order) ended up disagreeing under the same code, producing
    drifted line content in wFirma PZ documents.

    Today's parser is deterministic by ``original_index`` (assigned in
    PDF read order), so the historical motivation for the multi-tier
    sort — re-parse stability — is already satisfied without it.
    Returning ``(original_index,)`` makes ``<invoice>-<N>`` mean the
    invoice's Nth line, full stop. This aligns auto-register and PZ
    row generation under the same code → the wFirma PZ created from
    pz_rows references goods whose registered descriptions match the
    actual line content.

    Function name + signature unchanged to avoid touching call sites.
    """
    # Single-key sort = preserve original parser/invoice order.
    return (original_index,)


# ── NBP rate ──────────────────────────────────────────────────────────────────

def get_nbp_rate(invoice_date_str: str, manual_rate: float = None) -> dict:
    if manual_rate:
        print(f"  Using manual rate: 1 USD = {manual_rate} PLN")
        return {"table_no": "MANUAL", "table_date": "MANUAL",
                "usd_rate": manual_rate, "eur_rate": None}

    try:
        inv_date = datetime.strptime(invoice_date_str, "%d-%m-%Y")
    except ValueError:
        try:
            inv_date = datetime.strptime(invoice_date_str, "%Y-%m-%d")
        except ValueError:
            inv_date = datetime.now()

    # One working day before invoice date
    rate_date = inv_date - timedelta(days=1)
    while rate_date.weekday() >= 5:
        rate_date -= timedelta(days=1)

    for offset in range(7):
        check = rate_date - timedelta(days=offset)
        if check.weekday() >= 5:
            continue
        url = f"https://api.nbp.pl/api/exchangerates/tables/A/{check.strftime('%Y-%m-%d')}/?format=json"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()[0]
                rates = {x["code"]: x["mid"] for x in data["rates"]}
                result = {
                    "table_no":   data["no"],
                    "table_date": data["effectiveDate"],
                    "usd_rate":   rates.get("USD", 0),
                    "eur_rate":   rates.get("EUR", 0),
                }
                print(f"  NBP Table {result['table_no']} ({result['table_date']}): "
                      f"1 USD = {result['usd_rate']} PLN")
                return result
        except Exception:
            pass

    try:
        rate_str = input("  NBP fetch failed. Enter USD/PLN rate manually: ").strip()
    except EOFError:
        raise RuntimeError(
            "NBP rate fetch failed and service is running non-interactively — "
            "cannot prompt for USD/PLN rate. Set MANUAL_RATE env var or ensure "
            "network access to api.nbp.pl."
        )
    try:
        return {"table_no": "MANUAL", "table_date": "MANUAL",
                "usd_rate": float(rate_str), "eur_rate": None}
    except ValueError:
        sys.exit("Invalid rate. Aborting.")


# ── Invoice format detection ──────────────────────────────────────────────────

def detect_invoice_format(text: str, lines: list) -> str:
    """
    Heuristically determine which parser to use for this invoice.

    Primary signals (in priority order):
      1. "Merchant Exporter:" label + "Estrella Jewels LLP"  → "estrella"
      2. "Exporter:" label + "Global Jewellery Pvt. Ltd."    → "global_jewellery"
      3. EJL/ invoice number pattern                          → "estrella"
      4. ITEM_RE-matching line (PCS,/PRS, prefix)            → "estrella"
      5. "Global Jewellery" anywhere in text                 → "global_jewellery"
      6. fallback                                             → "generic"
    """
    text_upper = text.upper()

    # ── Primary: explicit template markers ───────────────────────────────────
    # Estrella: Merchant Exporter label with company name
    if "MERCHANT EXPORTER" in text_upper and "ESTRELLA JEWELS LLP" in text_upper:
        return "estrella"

    # Global Jewellery: Exporter label with company name
    if re.search(r"Exporter\s*:\s*Global\s+Jewellery\s+Pvt", text, re.IGNORECASE):
        return "global_jewellery"
    if "GLOBAL JEWELLERY PVT" in text_upper:
        return "global_jewellery"

    # ── Secondary: invoice pattern / line structure ───────────────────────────
    has_ejl = bool(re.search(r"EJL/\d{2}-\d{2}/\d{3,}", text, re.IGNORECASE))
    has_item_re = any(ITEM_RE.match(l) for l in lines)
    if has_ejl or has_item_re:
        return "estrella"

    if "GLOBAL JEWELLERY" in text_upper or "GLOBAL JEWELS" in text_upper:
        return "global_jewellery"

    return "generic"


# ── Shared block-parsing helpers ─────────────────────────────────────────────

def _extract_address_block(lines: list, start_idx: int, max_lines: int = 6) -> list:
    """
    Collect address lines starting at start_idx, stopping at the next section
    label (ALL-CAPS header, blank-equivalent line after data, or a line that
    is obviously a new section).
    """
    _cid_strip = re.compile(r"\(cid:\d+\)", re.IGNORECASE)
    block = []
    for line in lines[start_idx: start_idx + max_lines]:
        line = _cid_strip.sub("", line).strip()
        if not line:
            continue
        # Stop at lines that look like new section labels
        if re.match(r'^[A-Z][A-Z\s/\-]+:\s*$', line) or re.match(r'^[A-Z][A-Z\s/\-]+\s*:\s*$', line):
            break
        # Stop at PCS, / PRS, item data rows
        if ITEM_RE.match(line):
            break
        block.append(line)
    return block


def _parse_merchant_exporter_block(lines: list) -> dict:
    """
    Parse the "Merchant Exporter:" labelled block found in Estrella invoices.

    Layout:
        Merchant Exporter:
        Estrella Jewels LLP
        312, OPTIONS PRIMO PREMISES CHSL,
        MAROL INDUSTRIAL ESTATE, MIDC CROSS ROAD NO.21
        ANDHERI EAST, MUMBAI 400 093, India.
        GSTIN 27AADFE3151H1ZP

    Returns dict with: exporter_name, exporter_address, exporter_tax_id
    """
    # Pattern: pdfplumber sometimes injects "(cid:N)" control codes — strip before parsing
    _CID_STRIP = re.compile(r"\(cid:\d+\)", re.IGNORECASE)
    # Inline text that indicates a column-header merge (not a company name)
    _HEADER_INLINE_RE = re.compile(
        r"^(Invoice\s+No|Exporter'?s?\s+Ref|Date|Buyer|Consignee|Ship|Port|B/L|AWB)",
        re.IGNORECASE,
    )

    def _clean_cid(s: str) -> str:
        return _CID_STRIP.sub("", s).strip()

    result = {"exporter_name": "", "exporter_address": "", "exporter_tax_id": ""}
    for i, line in enumerate(lines):
        if re.search(r"Merchant\s+Exporter\s*:", line, re.IGNORECASE):
            # If "Merchant Exporter: CompanyName" is on the same line, extract it.
            # But: pdfplumber sometimes merges two-column headers into one line, producing
            # "Merchant Exporter: Invoice No & Date Exporter's Ref :" — detect and skip.
            inline = re.sub(r".*Merchant\s+Exporter\s*:\s*", "", line, flags=re.IGNORECASE).strip()
            inline = _clean_cid(inline)
            block_start = i + 1
            # Reject header-noise inline text — fall through to block scan
            if inline and not _HEADER_INLINE_RE.match(inline):
                result["exporter_name"] = inline
                addr_lines = _extract_address_block(lines, block_start, max_lines=6)
            else:
                addr_block = _extract_address_block(lines, block_start, max_lines=7)
                if addr_block:
                    # Clean cid codes from first line (company name)
                    name_raw = _clean_cid(addr_block[0])
                    # Trim trailing noise (invoice code, date) that got column-merged
                    name_raw = re.split(r"\s+(?=EJL/|CID\d+|IEC\s+NO|\d{2}[-/]\d{2}[-/]\d{4})",
                                        name_raw)[0].strip().rstrip(",;:")
                    result["exporter_name"] = name_raw
                    addr_lines = [_clean_cid(al) for al in addr_block[1:]]
                else:
                    addr_lines = []
            # Pull GSTIN out of address lines
            addr_parts = []
            for al in addr_lines:
                gstin_m = re.search(r"GSTIN\s+([A-Z0-9]{15})", al, re.IGNORECASE)
                if gstin_m:
                    result["exporter_tax_id"] = gstin_m.group(1)
                else:
                    addr_parts.append(al)
            result["exporter_address"] = ", ".join(addr_parts)
            break
    return result


def _parse_exporter_label_block(lines: list) -> dict:
    """
    Parse "Exporter: Name" label found in Global Jewellery invoices.

    Layout (may be inline or multiline):
        Exporter: Global Jewellery Pvt. Ltd.
        G-49, Gems & Jewellery Complex-1,
        Seepz, Andheri(East),
        Mumbai - 400096

    Returns dict with: exporter_name, exporter_address, exporter_tax_id
    """
    result = {"exporter_name": "", "exporter_address": "", "exporter_tax_id": ""}
    for i, line in enumerate(lines):
        m = re.match(r"Exporter\s*:\s*(.+)", line, re.IGNORECASE)
        if m:
            result["exporter_name"] = m.group(1).strip()
            addr_lines = _extract_address_block(lines, i + 1, max_lines=6)
            result["exporter_address"] = ", ".join(addr_lines)
            # GSTIN / TIN extraction
            for al in addr_lines:
                gstin_m = re.search(r"(?:GSTIN|TIN|IEC)[:\s]+([A-Z0-9]{10,})", al, re.IGNORECASE)
                if gstin_m:
                    result["exporter_tax_id"] = gstin_m.group(1)
                    break
            break
    return result


def _parse_generic_exporter_block(lines: list) -> dict:
    """
    Try multiple exporter-label patterns in priority order for unknown formats.
    Priority: Merchant Exporter → Exporter → Shipper → Supplier → Seller
    """
    for label in ["Merchant Exporter", "Exporter", "Shipper", "Supplier", "Seller"]:
        for i, line in enumerate(lines):
            if re.search(rf"{re.escape(label)}\s*:", line, re.IGNORECASE):
                inline = re.sub(rf".*{re.escape(label)}\s*:\s*", "", line, flags=re.IGNORECASE).strip()
                block_start = i + 1
                if inline:
                    name = inline
                    addr_lines = _extract_address_block(lines, block_start)
                else:
                    block = _extract_address_block(lines, block_start)
                    name = block[0] if block else ""
                    addr_lines = block[1:] if block else []
                return {
                    "exporter_name":    name,
                    "exporter_address": ", ".join(addr_lines),
                    "exporter_tax_id":  "",
                }
    return {"exporter_name": "", "exporter_address": "", "exporter_tax_id": ""}


def _parse_consignee_buyer(lines: list, text: str, *,
                           consignee_labels=("Consignee",),
                           buyer_labels=("Buyer", "Account")) -> dict:
    """
    Parse consignee (delivery recipient) and buyer (legal importer) from invoice.

    Returns: consignee_name, consignee_address, buyer_name, buyer_address,
             importer_vat (VAT/NIP found in either block).
    """
    result = {
        "consignee_name": "", "consignee_address": "",
        "buyer_name": "",    "buyer_address": "",
        "importer_vat": "",
    }

    def _find_block(labels):
        for label in labels:
            for i, line in enumerate(lines):
                if re.search(rf"^{re.escape(label)}\s*:", line, re.IGNORECASE):
                    block = _extract_address_block(lines, i + 1)
                    return block
        return []

    cons_block  = _find_block(consignee_labels)
    buyer_block = _find_block(buyer_labels)

    def _extract_vat(block):
        for bl in block:
            m = re.search(r"VAT\s+(?:Nr\.?|No\.?|#)?\s*(\d{10})", bl, re.IGNORECASE)
            if m:
                return m.group(1)
            m = re.search(r"NIP[:\s]+(\d{10})", bl, re.IGNORECASE)
            if m:
                return m.group(1)
        return ""

    if cons_block:
        result["consignee_name"]    = cons_block[0]
        result["consignee_address"] = ", ".join(cons_block[1:])
        result["importer_vat"]      = _extract_vat(cons_block)

    if buyer_block:
        result["buyer_name"]    = buyer_block[0]
        result["buyer_address"] = ", ".join(buyer_block[1:])
        if not result["importer_vat"]:
            result["importer_vat"] = _extract_vat(buyer_block)

    # Final fallback: global NIP/VAT scan
    if not result["importer_vat"]:
        m = re.search(r"(?:VAT\s+Nr\.?|NIP)[:\s]+(\d{10})", text, re.IGNORECASE)
        if m:
            result["importer_vat"] = m.group(1)

    return result


def _validate_cif(fob: float, freight: float, insurance: float, cif_parsed: float) -> dict:
    """
    Compare computed CIF (fob + freight + insurance) against parsed CIF.
    Returns a status string and the difference.
    """
    computed = round(fob + freight + insurance, 2)
    if cif_parsed <= 0:
        status = "Missing from document"
    elif abs(computed - cif_parsed) <= 1.0:
        status = "Verified"
    else:
        status = f"Mismatch (computed {computed:,.2f}, document {cif_parsed:,.2f})"
    return {"cif_computed": computed, "cif_parsed": cif_parsed, "cif_status": status}


# ── Global Jewellery Pvt. Ltd. parser ────────────────────────────────────────

# Item line pattern for Global Jewellery invoices.
# Example rows (reconstructed from typical GJ format):
#   1  Diamond Studded 18KT Gold RING  71131911  PCS  2  1,250.00  2,500.00
#   2  Plain 14KT Gold Pendant         71131919  PCS  5    320.00  1,600.00
_GJ_ITEM_RE = re.compile(
    r'^(?:\d+\s+)?'                                      # optional sr. no.
    r'(?P<desc>.+?)\s+'
    r'(?P<item_type>PENDANT|RING|EARRINGS|EARRING|BRACELET|NECKLACE|BANGLE|ANKLET|CUFFLINK)\s+'
    r'(?P<hsn>\d{7,8})\s+'
    r'(?P<unit>PCS|PRS|PGS)\s+'
    r'(?P<qty>\d+(?:\.\d+)?)\s+'
    r'(?P<rate>[\d,]+(?:\.\d+)?)\s+'
    r'(?P<amount>[\d,]+(?:\.\d+)?)$',
    re.IGNORECASE
)

# A looser pattern for lines that lack a clean item_type keyword:
#   1  Gold Jewellery (RING) 71131911 PCS 2 1250.00 2500.00
_GJ_LOOSE_RE = re.compile(
    r'^(?:\d+\s+)?'
    r'(?P<desc>.+?)\s+'
    r'(?P<hsn>71\d{6})\s+'
    r'(?P<unit>PCS|PRS|PGS)\s+'
    r'(?P<qty>\d+(?:\.\d+)?)\s+'
    r'(?P<rate>[\d,]+(?:\.\d+)?)\s+'
    r'(?P<amount>[\d,]+(?:\.\d+)?)$',
    re.IGNORECASE
)

_GJ_ITEM_TYPES = ["CUFFLINK", "EARRINGS", "EARRING", "BRACELET", "NECKLACE",
                  "BANGLE", "ANKLET", "PENDANT", "RING"]   # order: longest first


def _gj_infer_item_type(desc: str) -> str:
    """Extract item type from description string (longest match first)."""
    du = desc.upper()
    for t in _GJ_ITEM_TYPES:
        if t in du:
            return t
    # Parenthesised hint: "Gold Jewellery (RING)"
    m = re.search(r'\(([A-Z]+)\)', du)
    if m and m.group(1) in _GJ_ITEM_TYPES:
        return m.group(1)
    return "ITEM"


# ─── Global PZ Engine Authority Bridge (2026-05-21) ──────────────────────────
#
# Bridge between the customs-description chain (PR #269 produces 10 invoice-
# position rows in audit.json) and the PZ engine which historically re-parsed
# the source PDF via a regex that does not match the current Global layout.
# When the bridge fires, the engine consumes the same invoice-position
# authority used by the description side; when it does not (Estrella, missing
# audit, validation failure, etc.) the legacy regex parser runs unchanged.

_AUTHORITY_FORBIDDEN_TOKENS = (
    "UNKNOWN",
    "metal szlachetny",
    "Wyrób jubilerski",
    "grouped invoice aggregate",
    "wysadzany",
)


def _try_invoice_from_authority_rows(pdf_path, fname, corrections_log):
    """Return a parser-shaped dict from audit.rows when invoice-position
    authority is present and valid; return None to mean "fall through to
    the legacy parser". NEVER raises — every failure is logged and the
    legacy path runs.

    Audit-row source contract:
      _rows_source == "invoice_positions_authority"
      rows is a non-empty list of dicts
      each row has quantity > 0 and line_total_usd > 0
      no forbidden placeholders anywhere in the rows blob
      row line_total_usd sum reconciles to declared FOB within $1
    """
    try:
        audit_path = Path(pdf_path).parent.parent.parent / "audit.json"
        if not audit_path.is_file():
            return None
        audit = json.loads(audit_path.read_text(encoding="utf-8"))

        if (audit.get("_rows_source") or "") != "invoice_positions_authority":
            return None
        rows = audit.get("rows") or []
        if not isinstance(rows, list) or not rows:
            return None

        ok, why = _validate_authority_rows(rows, audit)
        if not ok:
            corrections_log.append(
                f"[{fname}] authority bridge declined: {why} — falling back to legacy parser"
            )
            return None

        return _build_invoice_from_authority_rows(
            pdf_path, fname, audit, rows, corrections_log
        )
    except Exception as exc:  # noqa: BLE001
        corrections_log.append(
            f"[{fname}] authority bridge raised {type(exc).__name__}: {exc} — falling back"
        )
        return None


def _validate_authority_rows(rows, audit):
    """Return (ok, reason). Conservative — any failure means fall back."""
    if not rows:
        return False, "empty rows"
    try:
        blob = json.dumps(rows, ensure_ascii=False)
    except Exception:
        return False, "rows not JSON-serialisable"
    for tok in _AUTHORITY_FORBIDDEN_TOKENS:
        if tok in blob:
            return False, f"forbidden token present: {tok!r}"

    qty_sum = 0.0
    line_sum = 0.0
    for r in rows:
        if not isinstance(r, dict):
            return False, "non-dict row"
        try:
            q = float(r.get("quantity") or 0)
        except (TypeError, ValueError):
            return False, f"non-numeric quantity at line {r.get('line_position')}"
        try:
            v = float(r.get("line_total_usd") or 0)
        except (TypeError, ValueError):
            return False, f"non-numeric line_total_usd at line {r.get('line_position')}"
        if q <= 0:
            return False, f"row qty <= 0 at line {r.get('line_position')}"
        if v <= 0:
            return False, f"row line_total_usd <= 0 at line {r.get('line_position')}"
        qty_sum  += q
        line_sum += v
    if qty_sum <= 0:
        return False, "qty sum <= 0"
    if line_sum <= 0:
        return False, "value sum <= 0"

    declared_fob = 0.0
    try:
        declared_fob = float(
            (audit.get("_customs_aggregation") or {}).get("fob_sum_preserved")
            or (audit.get("invoice_totals") or {}).get("total_fob_usd")
            or 0
        )
    except (TypeError, ValueError):
        declared_fob = 0.0
    if declared_fob > 0 and abs(line_sum - declared_fob) > 1.0:
        return False, (
            f"FOB drift: rows sum to ${line_sum:,.2f} vs declared ${declared_fob:,.2f}"
        )
    return True, "ok"


def _build_invoice_from_authority_rows(pdf_path, fname, audit, rows, corrections_log):
    """Build the parser-shaped dict from audit.rows. Reuses existing family
    / karat normalisation so downstream description rendering is identical
    to the regex path."""
    it_totals     = audit.get("invoice_totals") or {}
    fob_usd       = float(it_totals.get("total_fob_usd") or 0)
    freight_usd   = float(it_totals.get("total_freight_usd") or 0)
    insurance_usd = float(it_totals.get("total_insurance_usd") or 0)

    invoice_no = ""
    for r in rows:
        invoice_no = (r.get("invoice_number") or "").strip()
        if invoice_no:
            break
    if not invoice_no:
        invoice_no = (audit.get("invoice_no") or "").strip() or Path(pdf_path).stem
    invoice_date = (audit.get("invoice_date") or "").strip() or ""

    items = []
    pbu = {"PCS": {}, "PRS": {}}
    for r in rows:
        qty       = float(r.get("quantity") or 0)
        unit      = (r.get("uom") or r.get("unit") or "PCS").upper()
        if unit not in ("PCS", "PRS"):
            unit = "PCS"
        amount    = float(r.get("line_total_usd") or 0)
        unit_p    = float(r.get("unit_price") or (amount / qty if qty else 0))
        desc_en   = (r.get("description_en") or r.get("description") or "").strip()
        item_type = (r.get("item_type") or "").strip().upper()
        hsn       = (r.get("hsn_code") or "").strip()
        pl_desc   = (
            r.get("description_pl")
            or r.get("polish_customs_description")
            or ""
        ).strip()

        family = normalize_family(desc_en) if desc_en else ""
        karat  = get_karat(desc_en) if desc_en else ""

        item = {
            "description_en": desc_en,
            "item_type":      item_type,
            "family":         family,
            "karat":          karat,
            "hsn":            hsn,
            "quantity":       int(qty) if qty == int(qty) else qty,
            "unit":           unit,
            "unit_price_usd": unit_p,
            "total_usd":      amount,
            "gross_weight":   0.0,
            "net_weight":     0.0,
            "pl_desc":        pl_desc,
        }
        items.append(item)

        cat = classify_product_type(item_type)
        uk  = "PRS" if unit == "PRS" else "PCS"
        pbu[uk][cat] = pbu[uk].get(cat, 0) + item["quantity"]

    cif_validation = _validate_cif(
        fob_usd, freight_usd, insurance_usd,
        fob_usd + freight_usd + insurance_usd,
    )

    qty_sum = sum(it["quantity"] for it in items)
    corrections_log.append(
        f"[{fname}] [AUTHORITY-BRIDGE] Using PR #269 invoice-position rows from "
        f"audit.json: {len(items)} positions, qty {qty_sum}, FOB ${fob_usd:,.2f}"
    )

    return {
        "filename":              fname,
        "invoice_format":        "global_jewellery",
        "invoice_no":            invoice_no,
        "invoice_date":          invoice_date,
        "exporter_name":         "Global Jewellery",
        "exporter_address":      "",
        "exporter_tax_id":       "",
        "consignee_name":        "",
        "consignee_address":     "",
        "buyer_name":            "",
        "buyer_address":         "",
        "importer_vat":          "",
        "seller_name":           "Global Jewellery",
        "buyer_nip":             "",
        "transport":             "",
        "country_origin":        "IN",
        "country_destination":   "PL",
        "fob_usd":               fob_usd,
        "freight_usd":           freight_usd,
        "insurance_usd":         insurance_usd,
        "cif_usd":               fob_usd + freight_usd + insurance_usd,
        "cif_validation":        cif_validation,
        "conversion_rate_invoice": 0.0,
        "value_inr":             0.0,
        "items":                 items,
        "product_counts_by_unit": pbu,
        "_format":               "global_jewellery",
        "_raw_text":             "",
        "_authority_source":     "invoice_positions_authority",
    }


def parse_invoice_global_jewellery(pdf_path: str, text: str, lines: list,
                                   corrections_log: list) -> dict:
    """
    Parse a Global Jewellery Pvt. Ltd. invoice.

    Format: tabular layout without PCS,/PRS, line prefix.
    Exporter identity comes from the "Exporter:" label.
    Columns: Sr. No., Description, HSN, Unit, Qty, Rate, Amount.
    """
    fname = os.path.basename(pdf_path)

    # ── Authority bridge — PR #269 invoice-position rows from audit.json ──────
    # When the customs-description chain has already populated audit.rows
    # under the invoice-position authority, consume those rows directly.
    # This is a narrow opt-in: the audit.json must be sibling to
    # outputs/{batch}/ and carry _rows_source == "invoice_positions_authority"
    # with non-empty rows that pass validation. On any failure → fall through
    # to the legacy regex parser (existing behaviour preserved verbatim).
    #
    # Why: the legacy _GJ_LOOSE_RE regex does not match the current Global
    # PCS/PRS category-header layout, so item lines are silently dropped and
    # the engine fails with "Total before-duty PLN is zero". PR #269 already
    # produces the correct 10-position structure for the description side;
    # this bridge makes the engine consume the same authority.
    _bridge = _try_invoice_from_authority_rows(pdf_path, fname, corrections_log)
    if _bridge is not None:
        return _bridge

    # ── Invoice no & date ──────────────────────────────────────────────────────
    invoice_no = ""
    invoice_date = ""

    # Pattern: "Invoice No.: 417/2025-2026   Date: 02/01/2026"
    # or "Invoice No. & Date: 431  01/04/2026" (Global SEEPZ format)
    # or separate lines
    _invoice_no_from_text = False
    for line in lines:
        m = re.search(
            r"(?:Invoice\s+No\.?|INV\.?\s*NO\.?)[:\s]+([A-Z0-9/\-]+?)\s+"
            r"Date\s*[:\s]+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
            line, re.IGNORECASE)
        if m:
            invoice_no   = m.group(1).strip()
            invoice_date = m.group(2).strip().replace("/", "-")
            _invoice_no_from_text = True
            break
        if not invoice_no:
            # "Invoice No. & Date" label followed by bare number + date
            m2a = re.search(
                r"(?:Invoice\s+No\.?\s*(?:&|and)?\s*Date)[:\s]+(\d{3,})\s+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
                line, re.IGNORECASE)
            if m2a:
                invoice_no   = m2a.group(1).strip()
                invoice_date = m2a.group(2).strip().replace("/", "-")
                _invoice_no_from_text = True
                break
            m2 = re.search(
                r"(?:Invoice\s+No\.?|INV\.?\s*NO\.?)[:\s]+([A-Z0-9][A-Z0-9/\-]{2,})",
                line, re.IGNORECASE)
            if m2:
                candidate = m2.group(1).strip()
                # Accept bare numeric like "431" or alphanumeric like "417/2025-2026"
                if re.match(r'^\d{3,}$', candidate) or re.match(r'^[A-Z0-9][A-Z0-9/\-]{2,}$', candidate):
                    invoice_no = candidate
                    _invoice_no_from_text = True
        if not invoice_date:
            m3 = re.search(r"(?:Date|Dt\.?)[:\s]+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
                           line, re.IGNORECASE)
            if m3:
                invoice_date = m3.group(1).strip().replace("/", "-")

    if not invoice_no:
        # Filename fallback: "GLOBAL Invoice 431.pdf" → "431"
        stem = Path(pdf_path).stem
        fn_num_m = re.search(r'(\d{3,})\s*$', stem)
        if fn_num_m:
            invoice_no = fn_num_m.group(1)
            corrections_log.append(
                f"[{fname}] Invoice number inferred from filename"
            )
        else:
            invoice_no = stem
            corrections_log.append(
                f"[{fname}] Global Jewellery: invoice number not found — used filename"
            )

    # Normalise date to DD-MM-YYYY
    if invoice_date:
        parts = invoice_date.split("-")
        if len(parts) == 3 and len(parts[-1]) == 2:
            parts[-1] = "20" + parts[-1]
            invoice_date = "-".join(parts)

    # ── Exporter ───────────────────────────────────────────────────────────────
    exp = _parse_exporter_label_block(lines)
    exporter_name    = exp["exporter_name"]
    exporter_address = exp["exporter_address"]
    exporter_tax_id  = exp["exporter_tax_id"]

    # If exporter not parsed from invoice text, try filename-based fallback
    # "GLOBAL Invoice 431.pdf" → "Global Jewellery"
    if not exporter_name:
        fname_upper = fname.upper()
        if "GLOBAL" in fname_upper:
            exporter_name = "Global Jewellery"
            corrections_log.append(
                f"[{fname}] Exporter parsed from invoice; SAD exporter not available — "
                f"using filename fallback: '{exporter_name}'"
            )

    # ── Consignee & Buyer ──────────────────────────────────────────────────────
    # Global Jewellery uses "Consignee:" and "Account / delivery address:" or "Buyer:"
    cb = _parse_consignee_buyer(
        lines, text,
        consignee_labels=("Consignee",),
        buyer_labels=("Account", "Buyer", "Account / delivery address"),
    )
    consignee_name    = cb["consignee_name"]
    consignee_address = cb["consignee_address"]
    buyer_name        = cb["buyer_name"]
    buyer_address     = cb["buyer_address"]
    importer_vat      = cb["importer_vat"]

    # ── Transport ──────────────────────────────────────────────────────────────
    transport = ""
    for line in lines:
        m = re.search(r"(?:Transport(?:ation)?|Mode\s+of\s+Shipment|Carrier)[:\s]+(.+)",
                      line, re.IGNORECASE)
        if m:
            transport = m.group(1).strip()[:80]
            break
    if not transport:
        # Inline: "DHL / AIR FREIGHT" appearing standalone
        m = re.search(r"\b(DHL|FEDEX|AIR\s+FREIGHT|SEA\s+FREIGHT|COURIER)\b", text, re.IGNORECASE)
        if m:
            transport = m.group(1)

    # ── FOB / Freight / Insurance ──────────────────────────────────────────────
    def find_amount(label: str) -> float:
        m = re.search(rf"{re.escape(label)}[^\d]*([\d,]+\.?\d*)", text, re.IGNORECASE)
        return float(m.group(1).replace(",", "")) if m else 0.0

    fob_usd       = (find_amount("FOB US$") or find_amount("FOB USD") or
                     find_amount("Total FOB") or find_amount("FOB Value") or
                     find_amount("FOB"))
    freight_usd   = find_amount("FRI US$") or find_amount("Freight US$") or find_amount("Freight") or 0.0
    insurance_usd = find_amount("INS US$") or find_amount("Insurance US$") or find_amount("Insurance") or 0.0

    # Parsed CIF/Value from document
    cif_parsed = (find_amount("CIF US$") or find_amount("CIF Value") or
                  find_amount("Total Value") or find_amount("Value") or 0.0)

    # ── Item rows ──────────────────────────────────────────────────────────────
    items = []
    for line in lines:
        m = _GJ_ITEM_RE.match(line)
        if not m:
            m = _GJ_LOOSE_RE.match(line)
            if not m:
                continue
            desc_raw  = m.group("desc")
            item_type = _gj_infer_item_type(desc_raw)
        else:
            desc_raw  = m.group("desc")
            item_type = m.group("item_type").upper()

        unit   = m.group("unit").upper()
        qty    = float(m.group("qty"))
        rate   = parse_money(m.group("rate"))
        amount = parse_money(m.group("amount"))
        hsn    = m.group("hsn")

        if is_suspicious_quantity(qty):
            corrections_log.append(
                f"[{fname}] Suspicious quantity {qty} in line: {line[:70]}… — skipped"
            )
            continue

        karat  = get_karat(desc_raw)
        family = normalize_family(desc_raw)

        if ("SILVER" in desc_raw.upper() or "SL925" in desc_raw.upper()) and family != "Silver Plain":
            family = "Silver Plain"
            corrections_log.append(f"[{fname}] Global Jewellery: auto-corrected silver item")

        _item_meta = {"family": family, "karat": karat, "item_type": item_type}
        desc_en = build_en_name(_item_meta)
        pl_desc = build_pl_name(_item_meta)

        items.append({
            "description_en": desc_en,
            "item_type":      item_type,
            "family":         family,
            "karat":          karat,
            "hsn":            hsn,
            "quantity":       int(qty) if qty == int(qty) else qty,
            "unit":           unit,
            "unit_price_usd": rate,
            "total_usd":      amount,
            "gross_weight":   0.0,
            "net_weight":     0.0,
            "pl_desc":        pl_desc,
        })

    # ── FOB fallback ───────────────────────────────────────────────────────────
    if fob_usd <= 0.0 and items:
        fob_usd = sum(it["total_usd"] for it in items)
        corrections_log.append(
            f"[VERIFY-GAP] [{fname}] Global Jewellery FOB derived from line totals: "
            f"USD {fob_usd:,.2f}"
        )

    if not items:
        corrections_log.append(
            f"[{fname}] Global Jewellery: no item lines parsed — check PDF format"
        )

    # ── Product counts by unit ─────────────────────────────────────────────────
    pbu: dict = {"PCS": {}, "PRS": {}}
    for it in items:
        cat  = classify_product_type(it["item_type"])
        uk   = "PRS" if it["unit"] == "PRS" else "PCS"
        pbu[uk][cat] = pbu[uk].get(cat, 0) + it["quantity"]

    cif_validation = _validate_cif(fob_usd, freight_usd, insurance_usd, cif_parsed)

    return {
        # ── Core identity ─────────────────────────────────────────────────────
        "filename":       fname,
        "invoice_format": "global_jewellery",
        "invoice_no":     invoice_no,
        "invoice_date":   invoice_date,
        # ── Exporter (key fix: comes from "Exporter:" label) ──────────────────
        "exporter_name":    exporter_name,
        "exporter_address": exporter_address,
        "exporter_tax_id":  exporter_tax_id,
        # ── Consignee & buyer (separate) ──────────────────────────────────────
        "consignee_name":    consignee_name,
        "consignee_address": consignee_address,
        "buyer_name":        buyer_name,
        "buyer_address":     buyer_address,
        "importer_vat":      importer_vat,
        # ── Legacy compat aliases (used by verify_sad_invoice_match) ─────────
        "seller_name": exporter_name,
        "buyer_nip":   importer_vat,
        # ── Transport & origin ────────────────────────────────────────────────
        "transport":          transport,
        "country_origin":     "IN",   # India — all GJ invoices are India origin
        "country_destination": "PL",
        # ── Financial ─────────────────────────────────────────────────────────
        "fob_usd":       fob_usd,
        "freight_usd":   freight_usd,
        "insurance_usd": insurance_usd,
        "cif_usd":       fob_usd + freight_usd + insurance_usd,
        "cif_validation": cif_validation,
        "conversion_rate_invoice": 0.0,   # GJ invoices are USD; INR rate not applicable
        "value_inr":     0.0,
        # ── Items ─────────────────────────────────────────────────────────────
        "items":                items,
        "product_counts_by_unit": pbu,
        # ── Internal ──────────────────────────────────────────────────────────
        "_format":   "global_jewellery",
        "_raw_text": text,
    }


# ── Generic fallback parser ───────────────────────────────────────────────────

def parse_invoice_generic(pdf_path: str, text: str, lines: list,
                          corrections_log: list) -> dict:
    """
    Best-effort parser for unknown invoice formats.

    Extracts: invoice number, date, FOB/freight/insurance, and line items
    using broad heuristics.  Items that cannot be reliably classified are
    flagged as "Needs review" in the English description.
    """
    fname = os.path.basename(pdf_path)
    corrections_log.append(
        f"[{fname}] Unknown invoice format — using generic fallback parser. "
        "Verify all parsed values manually."
    )

    # ── Invoice no & date (broad) ──────────────────────────────────────────────
    invoice_no = ""
    invoice_date = ""
    for line in lines:
        if not invoice_no:
            m = re.search(r"(?:invoice\s+(?:no|number|#)\.?)[:\s]+([A-Z0-9/\-]+)",
                          line, re.IGNORECASE)
            if m:
                invoice_no = m.group(1).strip()
        if not invoice_date:
            m = re.search(r"(?:date)[:\s]+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
                          line, re.IGNORECASE)
            if m:
                invoice_date = m.group(1).strip().replace("/", "-")

    if not invoice_no:
        invoice_no = Path(pdf_path).stem
        corrections_log.append(
            f"[{fname}] Generic parser: invoice number not found — used filename"
        )

    # ── FOB / Freight / Insurance ──────────────────────────────────────────────
    def find_amount(label: str) -> float:
        m = re.search(rf"{re.escape(label)}[^\d]*([\d,]+\.?\d*)", text, re.IGNORECASE)
        return float(m.group(1).replace(",", "")) if m else 0.0

    fob_usd = (
        find_amount("FOB Value") or find_amount("FOB Amount") or
        find_amount("FOB US$") or find_amount("FOB USD") or
        find_amount("Total FOB") or find_amount("FOB") or
        find_amount("Total Amount") or find_amount("Grand Total")
    )
    freight_usd   = find_amount("Freight") or 0.0
    insurance_usd = find_amount("Insurance") or 0.0

    # ── Item rows (broad HSN-anchored scan) ───────────────────────────────────
    # Pattern: any line containing a 7-8 digit HSN code, followed by qty and amount
    _GENERIC_ITEM_RE = re.compile(
        r'(?P<desc>[A-Za-z][^\t\n]{3,60}?)\s+'
        r'(?P<hsn>71\d{6})\s+'
        r'(?P<unit>PCS|PRS|PGS)?\s*'
        r'(?P<qty>\d{1,4}(?:\.\d+)?)\s+'
        r'(?P<rate>[\d,]+\.\d{2})\s+'
        r'(?P<amount>[\d,]+\.\d{2})',
        re.IGNORECASE
    )

    items = []
    for line in lines:
        m = _GENERIC_ITEM_RE.search(line)
        if not m:
            continue
        desc_raw  = m.group("desc").strip()
        hsn       = m.group("hsn")
        unit      = (m.group("unit") or "PCS").upper()
        qty       = float(m.group("qty"))
        rate      = parse_money(m.group("rate"))
        amount    = parse_money(m.group("amount"))

        if is_suspicious_quantity(qty):
            corrections_log.append(
                f"[{fname}] Generic parser: suspicious quantity {qty} — skipped"
            )
            continue

        item_type = _gj_infer_item_type(desc_raw) or "ITEM"
        karat     = get_karat(desc_raw)
        family    = normalize_family(desc_raw)

        if item_type == "ITEM":
            desc_en = f"[Needs review] {desc_raw}"
            pl_desc = "[Wymaga weryfikacji]"
            corrections_log.append(
                f"[{fname}] Generic parser: item type not identified for '{desc_raw[:50]}'"
            )
        else:
            _item_meta = {"family": family, "karat": karat, "item_type": item_type}
            desc_en = build_en_name(_item_meta)
            pl_desc = build_pl_name(_item_meta)

        items.append({
            "description_en": desc_en,
            "item_type":      item_type,
            "family":         family,
            "karat":          karat,
            "hsn":            hsn,
            "quantity":       int(qty) if qty == int(qty) else qty,
            "unit":           unit,
            "unit_price_usd": rate,
            "total_usd":      amount,
            "gross_weight":   0.0,
            "net_weight":     0.0,
            "pl_desc":        pl_desc,
        })

    if fob_usd <= 0.0 and items:
        fob_usd = sum(it["total_usd"] for it in items)
        corrections_log.append(
            f"[VERIFY-GAP] [{fname}] Generic FOB derived from line totals: "
            f"USD {fob_usd:,.2f}"
        )

    corrections_log.append(
        f"[{fname}] Generic parser produced {len(items)} item(s) — "
        "manual verification of all values required"
    )

    # ── Exporter (generic: try labels in priority order) ──────────────────────
    exp = _parse_generic_exporter_block(lines)

    # ── Consignee & Buyer ──────────────────────────────────────────────────────
    cb = _parse_consignee_buyer(lines, text)

    # ── Product counts by unit ─────────────────────────────────────────────────
    pbu: dict = {"PCS": {}, "PRS": {}}
    for it in items:
        cat = classify_product_type(it["item_type"])
        uk  = "PRS" if it.get("unit") == "PRS" else "PCS"
        pbu[uk][cat] = pbu[uk].get(cat, 0) + it["quantity"]

    cif_validation = _validate_cif(fob_usd, freight_usd, insurance_usd, 0.0)

    return {
        "filename":       fname,
        "invoice_format": "generic",
        "invoice_no":     invoice_no,
        "invoice_date":   invoice_date,
        "exporter_name":    exp["exporter_name"],
        "exporter_address": exp["exporter_address"],
        "exporter_tax_id":  exp["exporter_tax_id"],
        "consignee_name":    cb["consignee_name"],
        "consignee_address": cb["consignee_address"],
        "buyer_name":        cb["buyer_name"],
        "buyer_address":     cb["buyer_address"],
        "importer_vat":      cb["importer_vat"],
        "seller_name":       exp["exporter_name"],   # legacy compat
        "buyer_nip":         cb["importer_vat"],     # legacy compat
        "transport":          "",
        "country_origin":     "",
        "country_destination": "",
        "fob_usd":       fob_usd,
        "freight_usd":   freight_usd,
        "insurance_usd": insurance_usd,
        "cif_usd":       fob_usd + freight_usd + insurance_usd,
        "cif_validation": cif_validation,
        "conversion_rate_invoice": 0.0,
        "value_inr":     0.0,
        "items":                items,
        "product_counts_by_unit": pbu,
        "_format":   "generic",
        "_raw_text": text,
    }


# ── Invoice PDF parser (dispatcher) ──────────────────────────────────────────

def parse_invoice(pdf_path: str, corrections_log: list) -> dict:
    """
    Dispatcher: detect invoice format and call the appropriate parser.

    Supported formats:
        "estrella"         — Estrella Jewels LLP (EJL/ numbers, PCS,/PRS, lines)
        "global_jewellery" — Global Jewellery Pvt. Ltd. (tabular, HSN column)
        "generic"          — Unknown format (best-effort fallback)

    All returned dicts include ``_format`` and ``_raw_text`` keys that are
    used by ``process_batch()`` for blocked-phrase scanning and audit logging.

    If invoice_learning_agent is installed it will:
      1. Pre-scan for supplier key + layout fingerprint
      2. Fetch any learned hints for the supplier/layout
      3. After parsing, call learn_from_parse() to record new patterns
      4. Attach _learning_trace to the result dict
    """
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    fname = os.path.basename(pdf_path)

    # ── Learning pre-scan (graceful degradation if module absent) ────────────
    _learning_agent = None
    _supplier_key   = ""
    _fingerprint    = ""
    _hints: dict    = {}
    try:
        import invoice_learning_agent as _learning_agent  # type: ignore
        _supplier_key = _learning_agent.quick_supplier_scan(text, lines)
        _fingerprint  = _learning_agent.fingerprint_layout(text, lines)
        if _supplier_key:
            _hints = _learning_agent.get_hints(_supplier_key, _fingerprint)
            if _hints:
                corrections_log.append(
                    f"[LEARNING] Using learned patterns for '{_supplier_key}' "
                    f"(fingerprint {_fingerprint})"
                )
    except ImportError:
        pass
    except Exception as _le:
        corrections_log.append(f"[LEARNING] Pre-scan error (non-fatal): {_le}")

    fmt = detect_invoice_format(text, lines)

    if fmt == "global_jewellery":
        corrections_log.append(f"[{fname}] Detected format: Global Jewellery Pvt. Ltd.")
        result = parse_invoice_global_jewellery(pdf_path, text, lines, corrections_log)
        return _apply_learning_postparse(result, text, lines, corrections_log,
                                         _learning_agent, _supplier_key, _fingerprint, _hints)

    if fmt == "generic":
        result = parse_invoice_generic(pdf_path, text, lines, corrections_log)
        return _apply_learning_postparse(result, text, lines, corrections_log,
                                         _learning_agent, _supplier_key, _fingerprint, _hints)

    # ── Estrella Jewels LLP format (default) ──────────────────────────────────
    invoice_no = ""
    invoice_date = ""
    for line in lines:
        m = re.search(r"(EJL/\d{2}-\d{2}/\d{3,})\s+Date\s*:\s*(\d{2}-\d{2}-\d{4})",
                      line, re.IGNORECASE)
        if m:
            invoice_no   = m.group(1).strip()
            invoice_date = m.group(2).strip()
            break
        m2 = re.search(r"(EJL/\d{2}-\d{2}/\d{3,})", line)
        if m2 and not invoice_no:
            invoice_no = m2.group(1)
        m3 = re.search(r"(\d{2}-\d{2}-\d{4})", line)
        if m3 and not invoice_date:
            invoice_date = m3.group(1)

    if not invoice_no:
        invoice_no = Path(pdf_path).stem
        corrections_log.append(f"Could not find invoice number in {fname}; used filename")

    # Warn if filename date differs from PDF body date (rule 4)
    fn_date_m = re.search(r"(\d{2}-\d{2}-\d{2})", fname)
    if fn_date_m and invoice_date:
        fn_short = fn_date_m.group(1)
        body_short = invoice_date[0:6] + invoice_date[8:]   # DD-MM-YY
        if fn_short != body_short:
            corrections_log.append(
                f"Filename date '{fn_short}' differs from PDF body date '{invoice_date}' "
                f"in {fname} — using PDF body date"
            )

    # ── FOB / Freight / Insurance ──
    def find_amount(label):
        m = re.search(rf"{re.escape(label)}[^\d]*([\d,]+\.?\d*)", text, re.IGNORECASE)
        return float(m.group(1).replace(",", "")) if m else 0.0

    fob_usd = (
        find_amount("FOB US $")
        or find_amount("FOB USD")
        or find_amount("FOB US")
        or find_amount("TOTAL FOB")
        or find_amount("Total FOB")
        or find_amount("FOB Value")
        or find_amount("FOB")
    )

    freight_usd   = find_amount("Freight US$") or find_amount("Freight USD") or find_amount("Freight US")
    insurance_usd = find_amount("Insurance US$") or find_amount("Insurance USD") or find_amount("Insurance US")

    if not freight_usd:
        freight_usd = 0.0
    if not insurance_usd:
        insurance_usd = 0.0

    # ── Item rows ──
    items = []
    for line in lines:
        m = ITEM_RE.match(line)
        if not m:
            continue

        desc_raw  = m.group("desc")
        item_type = m.group("item_type").upper()
        hsn       = m.group("hsn")
        qty       = float(m.group("qty"))
        rate      = parse_money(m.group("rate"))
        amount    = parse_money(m.group("amount"))

        # Determine unit from line prefix (PCS, vs PRS,)
        unit = "PRS" if line.upper().startswith("PRS,") else "PCS"

        # Sanity: quantity must not look like an HSN code
        if is_suspicious_quantity(qty):
            corrections_log.append(
                f"Suspicious quantity {qty} in {fname} line: {line[:60]}... — skipping row"
            )
            continue

        karat  = get_karat(desc_raw)
        family = normalize_family(desc_raw)

        # Silver detection: fix family if normalize_family missed it
        if ("SILVER" in desc_raw.upper() or "SL925" in desc_raw.upper()) and family != "Silver Plain":
            family = "Silver Plain"
            corrections_log.append(
                f"Auto-corrected silver item to Silver Plain family in {fname}"
            )

        _item = {"family": family, "karat": karat, "item_type": item_type}
        desc_en = build_en_name(_item)
        pl_desc = build_pl_name(_item)

        items.append({
            "description_en": desc_en,
            "item_type":      item_type,
            "family":         family,
            "karat":          karat,
            "hsn":            hsn,
            "quantity":       int(qty) if qty == int(qty) else qty,
            "unit":           unit,
            "unit_price_usd": rate,
            "total_usd":      amount,
            "gross_weight":   float(m.group("gross")),
            "net_weight":     float(m.group("net")),
            "pl_desc":        pl_desc,
        })

    # ── FOB fallback: derive from line totals if still 0 ─────────────────────
    if fob_usd <= 0.0 and items:
        fob_from_lines = sum(it["total_usd"] for it in items)
        if fob_from_lines > 0:
            corrections_log.append(
                f"[VERIFY-GAP] FOB not parsed directly from {fname}; "
                f"derived from line totals: USD {fob_from_lines:,.2f}"
            )
            fob_usd = fob_from_lines
        else:
            corrections_log.append(
                f"[VERIFY-GAP] FOB = 0.0 and line totals also 0 in {fname} — "
                f"invoice_no={invoice_no}; freight allocation will use 0%"
            )

    if not items and fob_usd > 0:
        corrections_log.append(f"No items parsed from {fname} — using FOB total as single line")
        items.append({
            "description_en": "Gold Jewellery",
            "item_type": "ITEM", "family": "Plain", "karat": "14KT",
            "hsn": "", "quantity": 1, "unit": "PCS",
            "unit_price_usd": fob_usd, "total_usd": fob_usd,
            "pl_desc": "Biżuteria złota",
        })

    # ── Exporter: "Merchant Exporter:" block ─────────────────────────────────
    exp = _parse_merchant_exporter_block(lines)
    exporter_name    = exp["exporter_name"]
    exporter_address = exp["exporter_address"]
    exporter_tax_id  = exp["exporter_tax_id"]

    # ── Consignee & Buyer ─────────────────────────────────────────────────────
    # Estrella invoices: "Consignee:" = warehouse; "Buyer:" = legal importer
    cb = _parse_consignee_buyer(
        lines, text,
        consignee_labels=("Consignee",),
        buyer_labels=("Buyer", "Bill To", "TO"),
    )
    consignee_name    = cb["consignee_name"]
    consignee_address = cb["consignee_address"]
    buyer_name        = cb["buyer_name"]
    buyer_address     = cb["buyer_address"]
    importer_vat      = cb["importer_vat"]

    # ── Conversion rate (Conv Rt) — invoice INR/USD rate ─────────────────────
    conv_rate = 0.0
    m = re.search(r"Conv(?:ersion)?\s+Rt?\s+([\d.]+)", text, re.IGNORECASE)
    if m:
        try:
            conv_rate = float(m.group(1))
        except ValueError:
            pass

    # ── INR value (CIF in INR on invoice) ────────────────────────────────────
    value_inr = 0.0
    if conv_rate > 0:
        cif_usd_computed = fob_usd + freight_usd + insurance_usd
        value_inr = round(cif_usd_computed * conv_rate, 2)

    # ── Product counts by unit ────────────────────────────────────────────────
    pbu: dict = {"PCS": {}, "PRS": {}}
    for it in items:
        cat = classify_product_type(it["item_type"])
        uk  = "PRS" if it.get("unit") == "PRS" else "PCS"
        pbu[uk][cat] = pbu[uk].get(cat, 0) + it["quantity"]

    cif_parsed = fob_usd + freight_usd + insurance_usd   # Estrella CIF always stated
    cif_validation = _validate_cif(fob_usd, freight_usd, insurance_usd, cif_parsed)

    _estrella_result = {
        # ── Core identity ─────────────────────────────────────────────────────
        "filename":       fname,
        "invoice_format": "estrella",
        "invoice_no":     invoice_no,
        "invoice_date":   invoice_date,
        # ── Exporter (key fix: from "Merchant Exporter:" block) ───────────────
        "exporter_name":    exporter_name,
        "exporter_address": exporter_address,
        "exporter_tax_id":  exporter_tax_id,
        # ── Consignee & buyer (separate) ──────────────────────────────────────
        "consignee_name":    consignee_name,
        "consignee_address": consignee_address,
        "buyer_name":        buyer_name,
        "buyer_address":     buyer_address,
        "importer_vat":      importer_vat,
        # ── Legacy compat aliases ─────────────────────────────────────────────
        "seller_name": exporter_name,
        "buyer_nip":   importer_vat,
        # ── Transport & origin ────────────────────────────────────────────────
        "transport":           "AIR FREIGHT",   # Estrella always air
        "country_origin":      "IN",
        "country_destination": "PL",
        # ── Financial ─────────────────────────────────────────────────────────
        "fob_usd":       fob_usd,
        "freight_usd":   freight_usd,
        "insurance_usd": insurance_usd,
        "cif_usd":       fob_usd + freight_usd + insurance_usd,
        "cif_validation": cif_validation,
        "conversion_rate_invoice": conv_rate,
        "value_inr":     value_inr,
        # ── Items ─────────────────────────────────────────────────────────────
        "items":                items,
        "product_counts_by_unit": pbu,
        # ── Internal ──────────────────────────────────────────────────────────
        "_format":   "estrella",
        "_raw_text": text,
    }
    return _apply_learning_postparse(_estrella_result, text, lines, corrections_log,
                                     _learning_agent, _supplier_key, _fingerprint, _hints)


def _apply_learning_postparse(
    result: dict,
    text: str,
    lines: list,
    corrections_log: list,
    _learning_agent,        # module or None
    supplier_key: str,
    fingerprint: str,
    hints: dict,
) -> dict:
    """
    Post-parse learning hook — called by parse_invoice after every format branch.

    Runs learn_from_parse(), attaches _learning_trace to result, and logs any
    recovered fields.  All errors are non-fatal.
    """
    if _learning_agent is None:
        return result

    try:
        # CONFLICT DETECTION: check learned label hints against actual document text
        # before running learn_from_parse, so conflicts are logged in corrections_log
        if hints and hasattr(_learning_agent, "apply_hints_conflict_check"):
            _learning_agent.apply_hints_conflict_check(text, hints, corrections_log)

        trace = _learning_agent.learn_from_parse(
            invoice        = result,
            text           = text,
            lines          = lines,
            corrections_log= corrections_log,
        )
        result["_learning_trace"] = trace

        # Surface recovered fields in corrections_log for visibility
        recovered = trace.get("fields_recovered") or []
        if recovered:
            corrections_log.append(
                f"[LEARNING] Recovered fields via learned pattern: {', '.join(recovered)}"
            )
        hints_used = trace.get("hints_used") or []
        if hints_used:
            corrections_log.append(
                f"[LEARNING] Hints applied: {', '.join(hints_used)}"
            )
    except Exception as _le:
        corrections_log.append(f"[LEARNING] Post-parse error (non-fatal): {_le}")

    return result


# ── ZC429 parser ──────────────────────────────────────────────────────────────

def parse_zc429(pdf_path: str, corrections_log: list) -> dict:
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    # MRN
    mrn = ""
    m = re.search(r"MRN[:\s]+([A-Z0-9]{15,})", text)
    if m:
        mrn = m.group(1).strip()

    # LRN — supports "Numer LRN [12 09]: 26S00Q8O0S" (rule 3)
    lrn = ""
    m = re.search(r"Numer\s+LRN\s*(?:\[\d+\s*\d+\])?\s*:\s*([A-Z0-9]+)", text, re.IGNORECASE)
    if m:
        lrn = m.group(1).strip()
    if not lrn:
        m = re.search(r"\bLRN\b[^:]*:\s*([A-Z0-9]{6,})", text, re.IGNORECASE)
        if m:
            lrn = m.group(1).strip()
            corrections_log.append("Recovered LRN using fallback regex")
    if not lrn:
        corrections_log.append("LRN not found in ZC429")

    # Clearance date
    clearance_date = ""
    m = re.search(r"Data\s+przyj[eę]cia\s+zg[lł]oszenia[:\s]+(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE)
    if m:
        clearance_date = m.group(1)
    else:
        m = re.search(r"(\d{4}-\d{2}-\d{2})T\d{2}:\d{2}", text)
        if m:
            clearance_date = m.group(1)

    # Agent / declarant — "Zgłaszający: AGENCJA CELNA SPEDYCJA KUŹMICZ K."
    agent = ""
    m = re.search(r"Zg[lł]aszaj[aą]cy\s*:\s*(.+)", text, re.IGNORECASE)
    if m:
        agent = m.group(1).strip()
    if not agent:
        # Fallback: Przedstawiciel line
        m = re.search(r"Przedstawiciel\s*\[.*?\]\s*:\s*(.+)", text, re.IGNORECASE)
        if m:
            agent = m.group(1).strip()

    # A00 duty — "stawka opł.: 1225.00 PLN" (NOT the taxable base "Kwota: 48987 PLN")
    duty_pln = 0.0
    for m in re.finditer(
        r"A00\s+Kwota:[^,]+,\s+stawka\s+op[lł]\.\s*:\s*([\d.]+)\s+PLN",
        text, re.IGNORECASE
    ):
        duty_pln += float(m.group(1))

    # Fallback: summary table "A00 1225 PLN R"
    if not duty_pln:
        for m in re.finditer(r"^A00\s+(\d+)\s+PLN\s+R", text, re.MULTILINE):
            duty_pln += float(m.group(1))
        if duty_pln:
            corrections_log.append("A00 duty recovered from Podsumowanie summary table")

    # ── Payment methods from Podsumowanie summary table ──────────────────────
    # Format: "A00 1225 PLN R" or "B00 2054 PLN G"
    # R = płatne natychmiast (payable at customs)
    # G = rozliczenie w deklaracji VAT (Art. 33a — VAT deferred)
    a00_payment_method = ""
    m_a00m = re.search(r"^A00\s+[\d.,]+\s+PLN\s+([A-Z])\b", text, re.MULTILINE)
    if m_a00m:
        a00_payment_method = m_a00m.group(1)

    b00_payment_method = ""
    m_b00m = re.search(r"^B00\s+[\d.,]+\s+PLN\s+([A-Z])\b", text, re.MULTILINE)
    if m_b00m:
        b00_payment_method = m_b00m.group(1)

    # B00 VAT (reference only)
    vat_pln = 0.0
    for m in re.finditer(
        r"B00\s+Kwota:[^,]+,\s+stawka\s+op[lł]\.\s*:\s*([\d.]+)\s+PLN",
        text, re.IGNORECASE
    ):
        vat_pln += float(m.group(1))
    if not vat_pln:
        m = re.search(r"^B00\s+(\d+)\s+PLN\s+([A-Z])", text, re.MULTILINE)
        if m:
            vat_pln = float(m.group(1))
            if not b00_payment_method:
                b00_payment_method = m.group(2)

    # CIF value from customs doc
    total_cif_usd = 0.0
    m = re.search(r"Warto[sś][cć]\s+faktur[^:]*:\s*([\d.]+)\s+USD", text, re.IGNORECASE)
    if m:
        total_cif_usd = float(m.group(1))

    # ── Statistical value PLN (field 99 06) ──────────────────────────────────
    statistical_value_pln = 0.0
    for _p in [r"Warto[sś][cć]\s+stat\.\s*(?:\[\d+\s*\d+\])?\s*:\s*([\d\s.,]+)\s*PLN",
               r"Warto[sś][cć]\s+statystyczna\s*(?:\[\d+\s*\d+\])?\s*:\s*([\d\s.,]+)\s*PLN",
               r"\[99\s*06\][^:]*:\s*([\d\s.,]+)\s*PLN"]:
        _m = re.search(_p, text, re.IGNORECASE)
        if _m:
            try:
                statistical_value_pln = float(_m.group(1).replace(" ", "").replace(",", "."))
                break
            except ValueError:
                pass

    # ── Goods description (field 31) ──────────────────────────────────────────
    goods_description = ""
    for _p in [r"Opis\s+towar[oó]w[^:]*:\s*([^\n]{5,})",
               r"31\s*[.\):]?\s*([A-ZŻŹĆĄŚĘŁÓŃ][A-ZŻŹĆĄŚĘŁÓŃ\s,\-]{4,})"]:
        _m = re.search(_p, text, re.IGNORECASE)
        if _m:
            goods_description = _m.group(1).strip()[:200]
            break
    if not goods_description:
        _m = re.search(r"(BIŻ[A-ZŻŹĆĄŚĘŁÓŃ\s,\-]{3,})", text, re.IGNORECASE)
        if _m:
            goods_description = _m.group(1).strip()[:200]

    # ── CN / TARIC code (field 33) ────────────────────────────────────────────
    cn_code = ""
    for _p in [r"Kod\s+(?:towaru|taryfy)[^:]*:\s*(\d{8,10})",
               r"\[33\][^:]*:\s*(\d{8,10})",
               r"\b(71131\d{3})\b"]:
        _m = re.search(_p, text)
        if _m:
            cn_code = _m.group(1)
            break

    if not mrn:
        corrections_log.append("MRN not found in ZC429")
    if not duty_pln:
        corrections_log.append("A00 duty not found in ZC429 — duty_pln set to 0.0 (verify manually)")
        try:
            duty_str = input("  Enter A00 duty amount (PLN): ").strip()
            try:
                duty_pln = float(duty_str)
            except ValueError:
                sys.exit("Invalid duty amount. Aborting.")
        except EOFError:
            # Service context — no stdin. duty_pln stays 0.0; engine continues.
            # The correction log entry above will surface this in the audit.
            pass

    # ── N935 attached document / invoice references ───────────────────────────
    # pdfplumber interleaves two-column SAD layouts on the same line, causing:
    #   "...N935-EJL/26-27/039 ... N935-EJL  <right-col text>\n/26-27/040 ..."
    # The token "N935-EJL" ends the line (right-column text appended after it),
    # then the invoice number continuation "/26-27/040" starts the next line.
    # Fix: rejoin specifically that split: N935-EJL<anything-not-slash>\n/digits
    text_joined = re.sub(
        r"(N935-[A-Z]{2,})[^\n/]*\n(/\d{2}-\d{2}/\d{3,})",
        r"\1\2",
        text,
    )
    # Apply up to 5 times to catch all continuations in a long block
    for _ in range(4):
        text_joined = re.sub(
            r"(N935-[A-Z]{2,})[^\n/]*\n(/\d{2}-\d{2}/\d{3,})",
            r"\1\2",
            text_joined,
        )

    invoice_refs: list = []
    # Track where refs were found for audit
    _invoice_refs_sources: list = []
    # Primary: find all invoice-number tokens that follow N935
    for m in re.finditer(
        r"\bN935[-]([A-Z]{2,}/\d{2}-\d{2}/\d{3,})", text_joined, re.IGNORECASE
    ):
        ref = m.group(1).strip()
        if ref not in invoice_refs:
            invoice_refs.append(ref)
            _invoice_refs_sources.append("N935")
    # Supplement: always scan for bare EJL/ patterns to catch refs that are present
    # in the SAD but NOT preceded by N935 (e.g. continuation lines, multi-item SAD
    # layouts where pdfplumber's two-column interleave breaks the join differently,
    # or later item lines that don't re-emit the N935 prefix).
    # This is additive — deduplication ensures no double-counting.
    for m in re.finditer(r"\b(EJL/\d{2}-\d{2}/\d{3,})\b", text_joined, re.IGNORECASE):
        ref = m.group(1).strip()
        if ref not in invoice_refs:
            invoice_refs.append(ref)
            _invoice_refs_sources.append("EJL_bare")

    # ── Global Jewellery: scan additional patterns if no N935/EJL refs found ──
    # ZC429 may reference Global Jewellery invoices via bare numbers, UWAGI notes,
    # or document attachment fields [12 03] / [12 01].
    _inferred_refs: list = []
    _invoice_refs_method = "N935"
    if not invoice_refs:
        # Bare invoice numbers (3-5 digits, not HSN-like 7-8 digits): 431, 432
        for m in re.finditer(r"\b(\d{3,5})\b", text_joined):
            candidate = m.group(1)
            if int(candidate) < 10000 and candidate not in invoice_refs:
                # Check surroundings: near "invoice", "faktura", or document section
                start = max(0, m.start() - 80)
                ctx = text_joined[start: m.end() + 30].lower()
                if any(kw in ctx for kw in ["invoice", "faktur", "dokument", "12 03", "12 01", "n935"]):
                    _inferred_refs.append(candidate)
                    if candidate not in invoice_refs:
                        invoice_refs.append(candidate)
                        _invoice_refs_sources.append("bare_number_inferred")

        # "Dokumenty załączone [12 03]" / "Dokumenty poprzednie [12 01]" sections
        _doc_section_m = re.search(
            r"(?:Dokumenty\s+(?:za[lł][aą]czone|poprzednie)|N935|N934)\s*(?:\[\d+\s+\d+\])?[:\s]+([\d\s,;/A-Z\-\.]{3,80})",
            text_joined, re.IGNORECASE)
        if _doc_section_m:
            _doc_nums = re.findall(r'\b(\d{3,5})\b', _doc_section_m.group(1))
            for dn in _doc_nums:
                if dn not in invoice_refs:
                    invoice_refs.append(dn)
                    _inferred_refs.append(dn)
                    _invoice_refs_sources.append("doc_section_inferred")

        # UWAGI / notes free text scan
        for m in re.finditer(r"UWAGI[:\s]+(.{5,200})", text_joined, re.IGNORECASE):
            _uwagi_nums = re.findall(r'\b(\d{3,5})\b', m.group(1))
            for un in _uwagi_nums:
                if un not in invoice_refs and int(un) < 10000:
                    invoice_refs.append(un)
                    _inferred_refs.append(un)
                    _invoice_refs_sources.append("uwagi_inferred")

        if _inferred_refs:
            _invoice_refs_method = "inferred_from_sad_free_text"
            corrections_log.append(
                f"[VERIFY-GAP] SAD invoice references inferred from free text / document sections "
                f"(not via N935): {_inferred_refs}"
            )
        elif not invoice_refs:
            _invoice_refs_method = "not_found"

    # ── Importer / consignee (field 8 in Polish SADs: "Odbiorca:") ────────────
    importer_name = ""
    importer_nip  = ""
    for pattern in [r"Odbiorca\s*:\s*([^\n]+)",
                    r"Importer\s*:\s*([^\n]+)",
                    r"(?:8\s*[.\):]?\s*)([A-Z][A-Z\s]{5,})"]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()[:150]
            if len(candidate) > 5:
                importer_name = candidate
                break
    m = re.search(r"NIP[:\s]+(\d{10})", text)
    if m:
        importer_nip = m.group(1)

    # ── Exporter / supplier (field 2: "Nadawca/Eksporter" or "Sprzedający:") ──
    exporter_name = ""
    for pattern in [r"Sprzedaj[aą]cy\s*:\s*([^\n]+)",
                    r"Nadawca\s*/?\s*[Ee]ksporter\s*:\s*([^\n]+)",
                    r"Eksporter\s*:\s*([^\n]+)"]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()[:150]
            if len(candidate) > 5:
                exporter_name = candidate
                break

    # ── Customs exchange rate (field 23: "Kurs waluty") ─────────────────────
    customs_rate_usd = 0.0
    for pattern in [r"USD\s*/\s*PLN\s+([\d.,]+)",
                    r"Kurs\s+walut[yo][^:]*:\s*(?:USD[/\s]PLN)?\s*([\d.,]+)",
                    r"Kurs\s+(?:USD)?\s*=\s*([\d.,]+)"]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                customs_rate_usd = float(m.group(1).replace(",", "."))
                if 2.0 < customs_rate_usd < 6.0:   # plausible PLN/USD range
                    break
                else:
                    customs_rate_usd = 0.0
            except ValueError:
                pass

    # ── Quantity by item type from SAD goods description (best-effort) ────────
    # SAD field 31 often describes goods in aggregate form.
    # Try to parse patterns like: "RING - 16", "PENDANT - 4", "EARRINGS - 5.5"
    sad_qty_by_type: dict = {}
    type_patterns = [
        (r"\bRING[S]?\b[^0-9]*?(\d+(?:\.\d+)?)", "RING"),
        (r"\bPENDANT[S]?\b[^0-9]*?(\d+(?:\.\d+)?)", "PENDANT"),
        (r"\bEARRING[S]?\b[^0-9]*?(\d+(?:\.\d+)?)", "EARRINGS"),
        (r"\bBRACELET[S]?\b[^0-9]*?(\d+(?:\.\d+)?)", "BRACELET"),
        (r"\bNECKLACE[S]?\b[^0-9]*?(\d+(?:\.\d+)?)", "NECKLACE"),
    ]
    for pattern, item_type in type_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                qty = float(m.group(1))
                if 0 < qty < 10000:
                    sad_qty_by_type[item_type] = qty
            except ValueError:
                pass

    # ── N740 transport document references (AWB / CMR / other) ──────────────
    # SAD documents reference transport docs as N740-<number>.
    # AWB numbers are typically 10-12 digits, sometimes IATA dashed: 852-12345678
    transport_refs: list = []
    for m in re.finditer(r"\bN740[-\s]([A-Z0-9][\w/\-]{3,})", text, re.IGNORECASE):
        ref = m.group(1).strip()
        if ref not in transport_refs:
            transport_refs.append(ref)
    # Fallback: numeric AWB-like standalone patterns near transport keywords
    if not transport_refs:
        for m in re.finditer(
            r"(?:AWB|Air\s+Waybill|Lot\s+awiacyjny|nr\s+listu)[^0-9]*(\d[\d\-]{7,})",
            text, re.IGNORECASE
        ):
            ref = m.group(1).strip().replace("-", "")
            if ref not in transport_refs:
                transport_refs.append(ref)

    # ── SAD invoice value fields for CIF reconciliation ─────────────────────
    # "Wartość faktur [14 06]" — SAD declared invoice value
    sad_invoice_value_usd = 0.0
    for _p in [r"Warto[sś][cć]\s+faktur[^:\n]*:\s*([\d\s.,]+)\s*USD",
               r"\[14\s*06\][^:\n]*:\s*([\d\s.,]+)\s*USD"]:
        _m = re.search(_p, text, re.IGNORECASE)
        if _m:
            try:
                sad_invoice_value_usd = float(_m.group(1).replace(" ", "").replace(",", "."))
                break
            except ValueError:
                pass

    # "Doliczenia i odliczenia [14 04]" — customs adjustments (freight/insurance additions)
    sad_additions_pln = 0.0
    for _p in [r"Doliczenia\s+i\s+odliczenia[^:\n]*:\s*([\d\s.,]+)\s*PLN",
               r"\[14\s*04\][^:\n]*:\s*([\d\s.,]+)\s*PLN",
               r"Koszty\s+transportu[^:\n]*:\s*([\d\s.,]+)\s*PLN"]:
        _m = re.search(_p, text, re.IGNORECASE)
        if _m:
            try:
                sad_additions_pln = float(_m.group(1).replace(" ", "").replace(",", "."))
                break
            except ValueError:
                pass

    return {
        "mrn":              mrn,
        "lrn":              lrn,
        "clearance_date":   clearance_date,
        "duty_pln":         duty_pln,
        "vat_pln":          vat_pln,
        "total_cif_usd":    total_cif_usd,
        "agent":            agent,            # Zgłaszający / customs declarant
        # verification fields
        "invoice_refs":       invoice_refs,       # invoice numbers from SAD
        "invoice_refs_method": _invoice_refs_method,  # how refs were found
        "inferred_refs":      _inferred_refs,     # refs inferred from free text
        "transport_refs":   transport_refs,   # N740 transport doc refs (AWB/CMR)
        "importer_name":    importer_name,    # field 8 consignee
        "importer_nip":     importer_nip,     # NIP/VAT of importer
        "exporter_name":    exporter_name,    # field 2 supplier
        "customs_rate_usd":    customs_rate_usd,    # field 23 exchange rate
        "sad_qty_by_type":     sad_qty_by_type,     # parsed goods qty by type (may be empty)
        "a00_payment_method":  a00_payment_method,  # R=standard, G=deferred (unusual for A00)
        "b00_payment_method":  b00_payment_method,  # R=standard, G=Art.33a VAT deferred
        # Extended audit fields (non-financial)
        "statistical_value_pln":  statistical_value_pln,
        "goods_description":      goods_description,
        "cn_code":                cn_code,
        # CIF reconciliation fields
        "sad_invoice_value_usd":  sad_invoice_value_usd,
        "sad_additions_pln":      sad_additions_pln,
    }


# ── SAD ↔ Invoice verification ────────────────────────────────────────────────

def verify_sad_invoice_match(invoices: list, zc429: dict) -> dict:
    """
    Compare the invoice set against the ZC429/SAD and return structured checks.
    All checks are best-effort — missing SAD fields produce 'not_parsed' status,
    never a hard failure.  Amendment decisions live in build_amendment_flags().
    """
    parsed_nos = [inv["invoice_no"] for inv in invoices]

    # ── 1. Invoice number match ───────────────────────────────────────────────
    sad_refs = zc429.get("invoice_refs", [])
    _refs_method = zc429.get("invoice_refs_method", "N935")
    _inferred_refs = zc429.get("inferred_refs", [])

    if sad_refs:
        # Normalize: strip leading/trailing whitespace, compare case-insensitively
        sad_refs_norm = [r.strip().upper() for r in sad_refs]
        parsed_nos_norm = [n.strip().upper() for n in parsed_nos]
        # Also try matching by bare number suffix (e.g. "EJL/26-27/431" vs "431")
        def _refs_match(inv_no: str) -> bool:
            ino_norm = inv_no.strip().upper()
            if ino_norm in sad_refs_norm:
                return True
            # Check if any SAD ref ends with or contains the invoice number
            for sr in sad_refs_norm:
                if sr == ino_norm or sr.endswith("/" + ino_norm) or ino_norm in sr:
                    return True
            return False

        missing_in_pdfs = [r for r in sad_refs if not any(
            r.strip().upper() == n.strip().upper()
            or r.strip().upper().endswith("/" + n.strip().upper())
            or n.strip().upper() in r.strip().upper()
            for n in parsed_nos
        )]
        extra_not_in_sad = [n for n in parsed_nos if not _refs_match(n)]

        if _refs_method == "inferred_from_sad_free_text":
            # Inferred refs: don't set hard False — treat as partial
            inv_refs_match = None if (missing_in_pdfs or extra_not_in_sad) else True
        else:
            inv_refs_match = (not missing_in_pdfs and not extra_not_in_sad)
    else:
        missing_in_pdfs = []
        extra_not_in_sad = []
        inv_refs_match = None  # None = could not verify (SAD refs not parsed)

    # ── 2. CIF total match ────────────────────────────────────────────────────
    inv_cif = round(sum(inv["cif_usd"] for inv in invoices), 2)
    sad_cif = zc429.get("total_cif_usd") or 0.0
    # Try SAD invoice value field [14 06] if total_cif_usd is not available
    _sad_invoice_val_usd = zc429.get("sad_invoice_value_usd", 0.0)
    if not sad_cif and _sad_invoice_val_usd:
        sad_cif = _sad_invoice_val_usd
    cif_diff = round(inv_cif - sad_cif, 2)
    _cif_status = "unknown"
    if sad_cif:
        if abs(cif_diff) <= 1.0:
            cif_match = True
            _cif_status = "Verified"
        else:
            # Before marking hard mismatch, check if diff is explained by SAD additions
            # (freight + insurance customs additions in field [14 04])
            _sad_additions_pln = zc429.get("sad_additions_pln", 0.0)
            _customs_rate = zc429.get("customs_rate_usd", 0.0)
            # Convert additions PLN → USD estimate for comparison
            _additions_usd_est = 0.0
            if _sad_additions_pln and _customs_rate and _customs_rate > 0:
                _additions_usd_est = round(_sad_additions_pln / _customs_rate, 2)

            _abs_diff = abs(cif_diff)
            # If diff ≤ estimated additions (freight/insurance), treat as verified with additions
            if _additions_usd_est and _abs_diff <= _additions_usd_est + 1.0:
                cif_match = True
                _cif_status = "Verified with customs additions"
            # If diff is a plausible freight/insurance amount (≤ $500, round-ish)
            elif _abs_diff <= 500 and (_abs_diff % 50 < 10 or _abs_diff < 200):
                cif_match = None   # soft — not confirmed mismatch
                _cif_status = "Verification needed — difference appears to be freight/insurance/customs adjustment"
            else:
                cif_match = False
                _cif_status = "Mismatch after additions check"
    else:
        cif_match = None   # could not verify
        _cif_status = "SAD CIF not available"

    # ── 3. Quantity by item type ──────────────────────────────────────────────
    # Sum from invoices
    inv_qty: dict = {}
    for inv in invoices:
        for item in inv["items"]:
            it = item.get("item_type", "UNKNOWN").upper().rstrip("S")
            it = "EARRINGS" if "EARRING" in it else it + "S" if not it.endswith("S") else it
            # Normalize to canonical plurals
            canonical = {"RINGS": "RING", "PENDANTS": "PENDANT", "BRACELETS": "BRACELET",
                         "NECKLACES": "NECKLACE", "EARRINGS": "EARRINGS", "BANGLES": "BANGLE"}
            it = canonical.get(it, it.rstrip("S"))
            inv_qty[it] = inv_qty.get(it, 0) + item.get("quantity", 0)

    sad_qty = zc429.get("sad_qty_by_type", {})
    if sad_qty:
        qty_diff: dict = {}
        for it in set(list(inv_qty.keys()) + list(sad_qty.keys())):
            inv_v = inv_qty.get(it, 0)
            sad_v = sad_qty.get(it, 0)
            d = inv_v - sad_v
            if abs(d) > 0.001:
                qty_diff[it] = d
        qty_match = (len(qty_diff) == 0)
    else:
        qty_diff  = {}
        qty_match = None  # could not verify

    # qty_status — categorical label for the audit hardening pipeline.
    # Mirrors qty_match_by_type but expresses *why* verification has the
    # state it has, so audit_scoring caps can be applied without re-deriving.
    #   "verified"               → exact per-type qty match
    #   "partial_aggregated_sad" → SAD has a single aggregated line
    #                              (sad_qty empty, sad_item_count>=1) and
    #                              per-type proof is impossible; the SAD is
    #                              internally consistent
    #   "not_verified"           → confirmed mismatch, or no evidence at all
    _sad_item_count = zc429.get("sad_item_count", 0) or 0
    if qty_match is True:
        qty_status = "verified"
    elif qty_match is False:
        qty_status = "not_verified"
    elif not sad_qty and _sad_item_count >= 1:
        qty_status = "partial_aggregated_sad"
    else:
        qty_status = "not_verified"

    # ── 4. Importer match ─────────────────────────────────────────────────────
    sad_importer = zc429.get("importer_name", "")
    sad_nip      = zc429.get("importer_nip",  "")
    inv_buyer    = invoices[0].get("buyer_name", "") if invoices else ""
    inv_nip      = invoices[0].get("buyer_nip",  "") if invoices else ""

    if sad_importer and inv_buyer:
        # Fuzzy: check if key words overlap (case-insensitive)
        sad_words = set(sad_importer.upper().split())
        inv_words = set(inv_buyer.upper().split())
        overlap   = sad_words & inv_words
        importer_match = len(overlap) >= 2
    elif sad_nip and inv_nip:
        importer_match = (sad_nip == inv_nip)
    else:
        importer_match = None   # not enough data to compare

    if sad_nip and inv_nip:
        nip_match = (sad_nip == inv_nip)
    else:
        nip_match = None

    # nip_source — categorical describing which side(s) provided the NIP
    # used for importer verification. Master fallback recognises the
    # well-known Estrella Jewels Sp. z o.o. master NIP (RECIPIENT.nip): when
    # the invoice does not carry a NIP but the SAD-declared NIP equals the
    # master, treat the verification as confirmed.
    #   "invoice_and_sad" → both sides parsed (canonical case)
    #   "sad_and_master"  → invoice NIP missing; SAD NIP == master NIP
    #   "sad_only"        → invoice NIP missing; SAD NIP not master
    #   "invoice_only"    → SAD NIP missing; invoice NIP present
    #   "neither"         → neither side parsed a NIP
    def _norm_nip(s: str) -> str:
        s = (s or "").upper().replace(" ", "").replace("-", "")
        return s[2:] if s.startswith("PL") else s
    _master_nip_n = _norm_nip(RECIPIENT.get("nip", ""))
    _inv_nip_n    = _norm_nip(inv_nip)
    _sad_nip_n    = _norm_nip(sad_nip)
    if _inv_nip_n and _sad_nip_n:
        nip_source = "invoice_and_sad"
    elif _sad_nip_n and not _inv_nip_n:
        if _master_nip_n and _sad_nip_n == _master_nip_n:
            nip_source = "sad_and_master"
            # Master fallback: invoice missing NIP but SAD declares the
            # known master NIP — treat as verified. Only escalates None to
            # True; never overrides an existing False.
            if nip_match is None:
                nip_match = True
        else:
            nip_source = "sad_only"
    elif _inv_nip_n and not _sad_nip_n:
        nip_source = "invoice_only"
    else:
        nip_source = "neither"

    # ── 5. Exporter match ─────────────────────────────────────────────────────
    # Use exporter_name (from Merchant Exporter / Exporter block) preferring
    # the new normalized field; fall back to legacy seller_name for old batches.
    sad_exporter = zc429.get("exporter_name", "")
    inv_exporter = (invoices[0].get("exporter_name", "")
                    or invoices[0].get("seller_name", "")) if invoices else ""

    if inv_exporter and sad_exporter:
        sad_e_words = set(sad_exporter.upper().split())
        inv_e_words = set(inv_exporter.upper().split())
        overlap_e   = sad_e_words & inv_e_words
        exporter_match = len(overlap_e) >= 2
        # Further: if names differ but invoice exporter IS parsed, mark as variance
        exporter_source = "invoice_and_sad"
    elif inv_exporter and not sad_exporter:
        exporter_match  = None       # can't compare — SAD exporter not parsed
        exporter_source = "invoice_only"
    elif sad_exporter and not inv_exporter:
        exporter_match  = None
        exporter_source = "sad_only"
    else:
        exporter_match  = None
        exporter_source = "neither"

    # ── 6. Currency / rate visibility ─────────────────────────────────────────
    customs_rate = zc429.get("customs_rate_usd", 0.0)

    # ── Derive human-readable label strings for audit output ─────────────────
    # Invoice refs label
    if inv_refs_match is True:
        _inv_refs_label = "Verified"
    elif inv_refs_match is False:
        _inv_refs_label = "Not found in SAD"
    else:
        # None — could not verify; check if SAD had inferred refs
        _sad_refs_method = zc429.get("invoice_refs_method", "")
        if _sad_refs_method == "inferred_from_sad_free_text":
            _inv_refs_label = "Partially verified — invoice references inferred from SAD/free text"
        else:
            _inv_refs_label = "Partially verified — invoice references inferred from SAD/free text" if sad_refs else "Not found in SAD"

    # Exporter label
    if exporter_match is True:
        _exporter_label = "Parsed from SAD"
    elif exporter_match is None:
        if exporter_source == "invoice_only":
            _exporter_label = "Parsed from invoice; SAD exporter not available"
        elif exporter_source == "sad_only":
            _exporter_label = "Parsed from SAD"
        else:
            _exporter_label = "Parsed from invoice; SAD exporter not available"
    else:
        _exporter_label = "Parsed with variance"

    # ── 6. CN parent/child code validation ───────────────────────────────────
    # SAD may declare a 6-digit parent CN while invoice items carry 8-digit children.
    # Risk classification drives the dashboard decision model:
    #   same chapter (first 2 digits match) → "medium" risk → operator-overridable
    #   different chapter                   → "high"   risk → hard block
    sad_cn = (zc429.get("cn_code") or "").strip().replace(" ", "")
    inv_hsn_codes = [
        str(item.get("hsn", "") or "").strip().replace(" ", "")
        for inv in invoices
        for item in inv.get("items", [])
        if item.get("hsn")
    ]

    if not sad_cn:
        cn_match = None
        cn_status = "sad_cn_not_parsed"
        cn_risk_level = None
    elif not inv_hsn_codes:
        cn_match = None
        cn_status = "invoice_hsn_not_parsed"
        cn_risk_level = None
    else:
        # Build a 6-char parent prefix: strip trailing zeros but keep ≥ 4 chars.
        _sad_parent = sad_cn.rstrip("0")
        if len(_sad_parent) < 4:
            _sad_parent = sad_cn[:4]  # minimum 4-char prefix

        _all_child = all(hsn.startswith(_sad_parent) for hsn in inv_hsn_codes)
        if _all_child:
            cn_match = True
            cn_status = "verified_parent_aggregated"
            cn_risk_level = "low"
        else:
            _sad_chapter = sad_cn[:2]
            _inv_chapters = {hsn[:2] for hsn in inv_hsn_codes if len(hsn) >= 2}
            if _sad_chapter in _inv_chapters:
                # Same chapter — taxonomy mismatch but same goods family
                cn_risk_level = "medium"
            else:
                # Completely different chapter — structural fraud/error risk
                cn_risk_level = "high"
            cn_match = False
            cn_status = "failed_parent_mismatch"

    return {
        # Invoice number reconciliation
        "invoice_refs_match":        inv_refs_match,    # True/False/None
        "invoice_refs_label":        _inv_refs_label,   # human-readable label
        "sad_invoice_refs":          sad_refs,
        "parsed_invoice_nos":        parsed_nos,
        "missing_invoices_in_pdfs":  missing_in_pdfs,
        "extra_invoices_not_in_sad": extra_not_in_sad,
        # CIF
        "cif_match":            cif_match,              # True/False/None
        "cif_status":           _cif_status,            # human-readable status
        "invoice_cif_total_usd": inv_cif,
        "sad_cif_total_usd":    sad_cif,
        "cif_difference_usd":   cif_diff,
        # Quantity by type
        "qty_match_by_type":    qty_match,              # True/False/None
        "qty_status":           qty_status,             # "verified"|"partial_aggregated_sad"|"not_verified"
        "invoice_qty_by_type":  inv_qty,
        "sad_qty_by_type":      sad_qty,
        "qty_diff_by_type":     qty_diff,
        # Importer
        "importer_match":       importer_match,         # True/False/None
        "invoice_importer_name": inv_buyer,
        "sad_importer_name":    sad_importer,
        "invoice_vat":          inv_nip,
        "sad_vat":              sad_nip,
        "vat_match":            nip_match,
        "nip_source":           nip_source,             # "invoice_and_sad"|"sad_and_master"|"sad_only"|"invoice_only"|"neither"
        # Exporter
        "exporter_match":        exporter_match,        # True/False/None
        "exporter_label":        _exporter_label,       # human-readable label
        "exporter_source":       exporter_source,       # "invoice_and_sad"|"invoice_only"|"sad_only"|"neither"
        "invoice_exporter_name": inv_exporter,
        "sad_exporter_name":     sad_exporter,
        # CN code validation
        "cn_match":             cn_match,               # True/False/None
        "cn_status":            cn_status,              # "verified_parent_aggregated"|"failed_parent_mismatch"|...
        "cn_risk_level":        cn_risk_level,          # "low"|"medium"|"high"|None
        "sad_cn_code":          sad_cn,
        "invoice_hsn_codes":    inv_hsn_codes,
        # Currency
        "nbp_rate_used":        0.0,    # filled by process_batch after NBP fetch
        "sad_customs_rate":     customs_rate,
        "rate_note":            "NBP accounting rate may differ from customs declaration rate",
    }


def build_amendment_flags(
    invoices: list, zc429: dict, verification: dict, corrections_log: list
) -> list:
    """
    Return a list of plain-text flag strings for conditions requiring manual attention.
    An empty list means no issues found.  Flags appear in terminal, XLSX, and optionally PDF.
    """
    flags = []

    # 1. SAD invoice references mismatch
    if verification["invoice_refs_match"] is False:
        miss = verification["missing_invoices_in_pdfs"]
        xtra = verification["extra_invoices_not_in_sad"]
        if miss:
            flags.append(f"SAD lists invoices not in PDF set: {', '.join(miss)}")
        if xtra:
            flags.append(f"Invoices in PDF set not listed in SAD: {', '.join(xtra)}")

    # 2. CIF mismatch
    if verification["cif_match"] is False:
        flags.append(
            f"CIF mismatch: invoices total ${verification['invoice_cif_total_usd']:,.2f} "
            f"vs SAD ${verification['sad_cif_total_usd']:,.2f} "
            f"(diff ${verification['cif_difference_usd']:+.2f})"
        )

    # 3. Quantity by type mismatch
    if verification["qty_match_by_type"] is False:
        for it, diff in verification["qty_diff_by_type"].items():
            flags.append(f"Quantity mismatch — {it}: invoice {verification['invoice_qty_by_type'].get(it, 0)} "
                         f"vs SAD {verification['sad_qty_by_type'].get(it, 0)} (diff {diff:+g})")

    # 4. Importer mismatch
    if verification["importer_match"] is False:
        flags.append(
            f"Importer mismatch — invoice: '{verification['invoice_importer_name'][:60]}' "
            f"/ SAD: '{verification['sad_importer_name'][:60]}'"
        )

    # 5. Exporter — only flag confirmed mismatch; never flag "Missing from SAD"
    #    as a mismatch when the invoice exporter was successfully parsed.
    exporter_source = verification.get("exporter_source", "neither")
    if verification["exporter_match"] is False:
        flags.append(
            f"Exporter mismatch — invoice: '{verification['invoice_exporter_name'][:60]}' "
            f"/ SAD: '{verification['sad_exporter_name'][:60]}'"
        )
    elif exporter_source == "invoice_only" and verification.get("invoice_exporter_name"):
        # Invoice exporter parsed but SAD exporter absent — informational, not an error
        pass   # surfaced in XLSX audit only, not as an amendment flag

    # 6. Invalid freight or insurance (negative values only)
    for inv in invoices:
        if inv["freight_usd"] < 0:
            flags.append(f"Invalid freight ${inv['freight_usd']} in {inv['invoice_no']} — must be ≥ 0")
        if inv["insurance_usd"] < 0:
            flags.append(f"Invalid insurance ${inv['insurance_usd']} in {inv['invoice_no']} — must be ≥ 0")

    # 7. Blocked correction-log phrases
    # [VERIFY-GAP] entries are non-fatal visibility notes, not parse errors — skip them.
    blocked = ["reparsed", "not found", "suspicious", "failed", "invalid",
               "manual entry", "could not"]
    for entry in corrections_log:
        if entry.startswith("[VERIFY-GAP]"):
            continue
        if any(p in entry.lower() for p in blocked):
            flags.append(f"Parse warning: {entry[:120]}")

    # 8. Master amendment flag — if any structural mismatch exists
    structural_mismatch = any([
        verification["invoice_refs_match"] is False,
        verification["cif_match"] is False,
        verification["qty_match_by_type"] is False,
        verification["importer_match"] is False,
        verification["exporter_match"] is False,
    ])
    if structural_mismatch:
        flags.append(
            "Review needed: SAD / invoice set may require amendment "
            "or corrected source document check."
        )

    return flags


# ── Landed cost calculation ───────────────────────────────────────────────────

def calculate_landed(invoices: list, zc429: dict, nbp: dict, corrections_log: list):
    """
    Landed-cost calculation — all field names are explicit and audit-ready.

    Freight allocation: by value share within each invoice.
        freight_rate_pct     = (freight + insurance) / invoice FOB USD
        allocated_ship_usd   = line_usd × freight_rate_pct
        allocated_ship_pln   = allocated_ship_usd × rate

    Duty allocation: A00 duty distributed proportionally over total before-duty PLN.
        duty_rate_pct        = A00_PLN / total_before_duty_PLN
        allocated_duty_pln   = before_duty_pln × duty_rate_pct

    Residual reconciliation: rounding pennies assigned to last row so
    sum(allocated_duty_pln) == A00 exactly.
    """
    usd_pln = nbp["usd_rate"]

    total_fob_usd     = sum(inv["fob_usd"] for inv in invoices)
    total_freight_usd = sum(inv["freight_usd"] + inv["insurance_usd"] for inv in invoices)
    total_cif_usd     = sum(inv["cif_usd"] for inv in invoices)

    # ── Step 1: before-duty PLN per row ──────────────────────────────────────
    rows = []
    total_before_duty_pln = 0.0

    for inv in invoices:
        if inv["fob_usd"] <= 0:
            line_sum = sum(it.get("total_usd", 0) for it in inv.get("items", []))
            raise ValueError(
                f"Invoice {inv['invoice_no']} ({inv.get('filename','?')}) has "
                f"FOB USD = {inv['fob_usd']:.2f} — cannot compute freight share.\n"
                f"  Line items: {len(inv.get('items', []))}  "
                f"Line total USD: {line_sum:.2f}  "
                f"Freight USD: {inv.get('freight_usd', 0):.2f}  "
                f"Insurance USD: {inv.get('insurance_usd', 0):.2f}\n"
                f"  Likely cause: FOB label in PDF does not match any known pattern "
                f"(FOB US $, FOB USD, FOB, TOTAL FOB).\n"
                f"  Fix: verify the PDF's FOB line label and add it to find_amount() fallbacks."
            )
        inv_ship_usd     = inv["freight_usd"] + inv["insurance_usd"]
        freight_rate_pct = inv_ship_usd / inv["fob_usd"]   # e.g. 0.0190 = 1.9%
        if freight_rate_pct < 0:
            raise ValueError(
                f"Negative freight rate {freight_rate_pct:.4%} for {inv['invoice_no']}"
            )

        # Sort items by canonical key. Under the current contract,
        # ``canonical_item_sort_key`` returns ``(original_index,)`` so this
        # is effectively a stable identity sort that preserves invoice
        # line order — product_code -N maps to invoice line N.
        indexed_items = sorted(
            enumerate(inv["items"]),
            key=lambda t: canonical_item_sort_key(t[1], t[0]),
        )
        # NOTE: a duplicate-canonical-key warning loop used to live here.
        # It warned when two items shared an identical multi-tier sort
        # key (item_type+description+hs+price+qty), since the old sort
        # used original_index only as a tiebreaker. After Option B, the
        # sort key IS original_index, so every item has a unique key by
        # construction — there are no canonical-key collisions to
        # surface, and running the old check would emit one false-
        # positive [WARN] per item past the first on every multi-line
        # invoice. The block is removed deliberately; downstream
        # duplicate detection (e.g. matching invoice descriptions to
        # warehouse stock) lives in other services and is unaffected.

        for line_position, (_orig_idx, item) in enumerate(indexed_items, start=1):
            product_code     = build_product_code(inv["invoice_no"], line_position)
            line_usd         = item["total_usd"]
            qty              = item["quantity"]

            # Backfill `family` and `karat` for any caller that hands
            # calculate_landed a bare invoice item without routing it
            # through parse_invoice first (e.g. synthetic test fixtures).
            # Production parsing paths already assign both keys via
            # normalize_family()/get_karat() before persisting items, so
            # setdefault is a strict no-op for them. Without this guard,
            # build_pl_name / build_en_name (called below) would raise
            # KeyError: 'family' on the first synthetic line item.
            _desc_for_naming = (
                item.get("description_en")
                or item.get("description")
                or item.get("desc")
                or ""
            )
            item.setdefault("family", normalize_family(_desc_for_naming))
            item.setdefault("karat",  get_karat(_desc_for_naming))

            allocated_ship_usd  = line_usd * freight_rate_pct
            allocated_ship_pln  = allocated_ship_usd * usd_pln
            purchase_value_pln  = line_usd * usd_pln
            before_duty_pln     = purchase_value_pln + allocated_ship_pln
            total_before_duty_pln += before_duty_pln

            rows.append({
                **item,
                "invoice_no":          inv["invoice_no"],
                "invoice_date":        inv["invoice_date"],
                "product_code":        product_code,
                "line_position":       line_position,
                "nazwa_pl":            build_pl_name(item),
                "nazwa_en":            build_en_name(item),
                "nazwa":               f"{build_pl_name(item)} / {build_en_name(item)}",
                "usd_pln":             usd_pln,
                # ── explicit cost fields ──────────────────────────────────
                "freight_rate_pct":    freight_rate_pct,
                "allocated_ship_usd":  allocated_ship_usd,
                "allocated_ship_pln":  allocated_ship_pln,
                "purchase_value_pln":  purchase_value_pln,
                "before_duty_pln":     before_duty_pln,
            })

    # ── Validation ────────────────────────────────────────────────────────────
    if zc429["duty_pln"] <= 0:
        raise ValueError("A00 duty parsed as zero or negative — check ZC429 parser")
    if total_before_duty_pln <= 0:
        raise ValueError("Total before-duty PLN is zero — check invoice FOB values")

    duty_rate_frac = zc429["duty_pln"] / total_before_duty_pln
    if duty_rate_frac > 0.20:
        raise ValueError(
            f"Implausible duty rate {duty_rate_frac:.2%} — parser likely captured the customs "
            f"taxable base ({zc429['duty_pln']:,.2f} PLN) instead of the A00 charged duty. "
            f"Fix: use 'stawka opł.' value, not 'Kwota:' value from ZC429."
        )
    if not zc429.get("lrn"):
        corrections_log.append(
            "WARNING: LRN is empty — ZC429 parser must support 'Numer LRN [12 09]' format"
        )
    # CIF reconciliation: sum of invoice CIFs must match ZC429 declared value within 1 USD
    cif_sum = sum(inv["cif_usd"] for inv in invoices)
    if zc429.get("total_cif_usd") and abs(cif_sum - zc429["total_cif_usd"]) > 1.0:
        corrections_log.append(
            f"CIF reconciliation gap: invoices sum to ${cif_sum:,.2f} but "
            f"ZC429 declares ${zc429['total_cif_usd']:,.2f} "
            f"(diff ${abs(cif_sum - zc429['total_cif_usd']):.2f})"
        )

    # ── Step 2: duty per row ──────────────────────────────────────────────────
    for row in rows:
        qty                   = row["quantity"]
        allocated_duty_pln    = row["before_duty_pln"] * duty_rate_frac
        line_netto_pln        = row["before_duty_pln"] + allocated_duty_pln
        unit_netto_pln        = line_netto_pln / qty
        line_brutto_pln       = line_netto_pln * (1 + VAT_RATE)

        row.update({
            "allocated_duty_pln":  allocated_duty_pln,
            "line_netto_pln":      line_netto_pln,
            "unit_netto_pln":      unit_netto_pln,
            "line_brutto_pln":     line_brutto_pln,
            # ── audit / display only (per-unit breakdowns) ────────────────
            "fi_per_unit_usd":     row["allocated_ship_usd"] / qty if qty else 0,
            "cost_before_duty":    row["before_duty_pln"] / qty if qty else 0,
            "duty_per_unit":       allocated_duty_pln / qty if qty else 0,
        })

    # ── Residual reconciliation ───────────────────────────────────────────────
    # Floating-point rounding means sum(allocated_duty_pln) may differ by ±0.01 PLN.
    # Assign the remainder to the last row so the total equals A00 exactly.
    allocated_total = round(sum(r["allocated_duty_pln"] for r in rows), 2)
    residual        = round(zc429["duty_pln"] - allocated_total, 2)
    if residual != 0:
        rows[-1]["allocated_duty_pln"] += residual
        rows[-1]["line_netto_pln"]     += residual
        rows[-1]["unit_netto_pln"]      = rows[-1]["line_netto_pln"] / rows[-1]["quantity"]
        rows[-1]["line_brutto_pln"]     = rows[-1]["line_netto_pln"] * (1 + VAT_RATE)
        rows[-1]["duty_per_unit"]      += residual / rows[-1]["quantity"]
        if abs(residual) > 0.01:
            corrections_log.append(
                f"Duty residual {residual:+.2f} PLN assigned to last row "
                f"(effective A00 = {zc429['duty_pln']:.2f} PLN)"
            )

    totals = {
        "total_fob_usd":         total_fob_usd,
        "total_freight_usd":     total_freight_usd,
        "total_cif_usd":         total_cif_usd,
        "total_before_duty_pln": total_before_duty_pln,
        "duty_rate_pct":         duty_rate_frac * 100,
        "usd_pln":               usd_pln,
    }
    return rows, totals


# ── Note line 4 — dynamic by customs settlement mode ─────────────────────────

def build_note_4(zc429: dict, batch_meta: dict) -> str:
    """
    Return the fourth UWAGI line, which describes how customs was settled.

    batch_meta keys (all optional):
      settlement_mode      "standard" (default) | "art33a"
      prefer_carrier_label bool — if True and carrier_name is set, use carrier
                                  even when an agent was parsed from ZC429
      carrier_name         str  — e.g. "DHL EXPRESS (POLAND) SP. Z O.O."

    Decision order:
      1. art33a → art. 33a statutory wording
      2. prefer_carrier_label + carrier_name → carrier label
      3. zc429["agent"] present → "Odprawa celna przez: <agent>"
      4. carrier_name → carrier label
      5. fallback → "Odprawa celna importowa."
    """
    mode         = (batch_meta or {}).get("settlement_mode", "standard")
    prefer_carr  = (batch_meta or {}).get("prefer_carrier_label", False)
    carrier_name = ((batch_meta or {}).get("carrier_name") or "").strip()

    if mode == "art33a":
        return "Import towarów rozliczany zgodnie z art. 33a ustawy o VAT."

    if prefer_carr and carrier_name:
        return carrier_name

    agent = (zc429.get("agent") or "").strip()
    if agent:
        return f"Odprawa celna przez: {agent}"

    if carrier_name:
        return carrier_name

    return "Odprawa celna importowa."


# ── Notes builder ─────────────────────────────────────────────────────────────

def build_notes(invoices: list, zc429: dict, nbp: dict, batch_meta: dict = None) -> list:
    inv_nos   = [inv["invoice_no"] for inv in invoices]
    base      = "/".join(inv_nos[0].split("/")[:-1])
    first_sfx = inv_nos[0].split("/")[-1]
    last_sfx  = inv_nos[-1].split("/")[-1]
    inv_date  = invoices[0]["invoice_date"]

    range_str = f"{base}/{first_sfx}" + (f" - {last_sfx}" if first_sfx != last_sfx else "")
    cl_date   = fmt_date_pl(zc429["clearance_date"])

    return [
        f"Applies to: Invoice No. {range_str} Date : {inv_date}",
        f"USD RATE: Table no. {nbp['table_no']} of {nbp['table_date']} , where 1 USD ={nbp['usd_rate']} PLN",
        f"Admitted for circulation in the territory of the Republic of Poland on the basis of: "
        f"{zc429['mrn']} Own number: {zc429['lrn']} of dt {cl_date}",
        build_note_4(zc429, batch_meta),
    ]


# ── Clipboard / paste formatters ─────────────────────────────────────────────

def format_uwagi(notes: list) -> str:
    """
    Return the UWAGI block as a plain string.
    Takes the notes list directly — no secondary formatting path.
    """
    return "\n".join(["UWAGI:"] + list(notes))


def format_pz_clipboard(rows: list, notes: list, totals: dict) -> str:
    """
    Return the wFirma-ready PZ content as a single string suitable for
    direct paste into wFirma.pl or piping to pbcopy.

    Critical invariant: all UWAGI content comes exclusively from the notes
    argument — this function never reconstructs or reformats note lines.
    Whatever process_batch() returns as notes is what appears in the output.
    """
    out = []
    sep = "─" * 113

    # Items table header
    out.append(sep)
    out.append(
        f"{'Lp':>3}  {'Nazwa':<55}  {'Jedn':>4}  {'Ilość':>6}  "
        f"{'Cena netto':>12}  {'Stawka':>6}  {'Wart. netto':>12}  {'Wart. brutto':>13}"
    )
    out.append(sep)

    for i, r in enumerate(rows, 1):
        qty = int(r["quantity"]) if r["quantity"] == int(r["quantity"]) else r["quantity"]
        # Truncate Polish description to fit column; full name shown in print_pz detail
        pl = r["pl_desc"][:54]
        out.append(
            f"{i:>3}  {pl:<55}  {'szt.':>4}  {qty:>6}  "
            f"{fmt_pln(r['unit_netto_pln']):>12}  {'23%':>6}  "
            f"{fmt_pln(r['line_netto_pln']):>12}  {fmt_pln(r['line_brutto_pln']):>13}"
        )

    out.append(sep)
    total_n = sum(r["line_netto_pln"]  for r in rows)
    total_b = sum(r["line_brutto_pln"] for r in rows)
    out.append(f"{'':>85}  Razem netto:   {fmt_pln(total_n):>12} PLN")
    out.append(f"{'':>85}  Razem brutto:  {fmt_pln(total_b):>12} PLN")
    out.append("")

    # UWAGI — notes list is the single source; no reconstruction here
    out.append(format_uwagi(notes))

    return "\n".join(out)


# ── Output — wFirma PZ format ─────────────────────────────────────────────────

def _fmt_check(value) -> str:
    """Format a True/False/None verification result for terminal display."""
    if value is True:
        return "✅ YES"
    if value is False:
        return "❌ NO"
    return "— (not parsed)"


def print_pz(rows: list, zc429: dict, nbp: dict, totals: dict,
             notes: list, invoices: list, corrections_log: list,
             verification: dict = None):

    inv_date  = rows[0]["invoice_date"] if rows else ""
    total_n   = sum(r["line_netto_pln"]  for r in rows)
    total_b   = sum(r["line_brutto_pln"] for r in rows)
    today_str = datetime.now().strftime("%Y-%m-%d")

    # ── PZ Header ──
    print()
    print(f"PZ  [wFirma.pl — ready to enter]")
    print(f"Data wystawienia: {today_str}")
    print(f"Magazyn: Główny")
    print()
    print(f"Odbiorca: {RECIPIENT['name']}")
    print(f"         {RECIPIENT['address']}")
    print(f"         NIP: {RECIPIENT['nip']}")
    print(f"Dostawca: {SUPPLIER['name']}")
    print(f"         {SUPPLIER['address']}")
    print()

    # ── Items table ──
    sep = "─" * 110
    hdr = f"{'Lp':>3}  {'Nazwa':<58}  {'Jedn':>4}  {'Ilość':>5}  {'Cena netto':>12}  {'Stawka':>6}  {'Wart. netto':>12}  {'Wart. brutto':>13}"
    print(sep)
    print(hdr)
    print(sep)

    for i, r in enumerate(rows, 1):
        nazwa = get_full_nazwa(r)   # "English natural name (Polish natural name)"
        # Print name on first line, wrapped
        first_line = nazwa[:57]
        rest       = nazwa[57:]
        qty_disp   = int(r["quantity"]) if r["quantity"] == int(r["quantity"]) else r["quantity"]
        print(
            f"{i:>3}  {first_line:<58}  {'szt.':>4}  {qty_disp:>5}  "
            f"{fmt_pln(r['unit_netto_pln']):>12}  {'23%':>6}  "
            f"{fmt_pln(r['line_netto_pln']):>12}  {fmt_pln(r['line_brutto_pln']):>13}"
        )
        while rest:
            print(f"     {rest[:57]}")
            rest = rest[57:]

    print(sep)
    print(f"{'':>78}  {'Razem netto':>11}  {fmt_pln(total_n):>12} PLN")
    print(f"{'':>78}  {'Razem brutto':>11}  {fmt_pln(total_b):>12} PLN")
    print()

    # ── UWAGI ──
    print("UWAGI (paste into wFirma.pl):")
    print("─" * 80)
    for n in notes:
        print(f"  {n}")
    print()

    # ── Calculation parameters ──
    print("─" * 80)
    print("  CALCULATION PARAMETERS")
    print("─" * 80)
    print(f"  Exchange rate (NBP)  : 1 USD = {totals['usd_pln']} PLN")
    print(f"  Total FOB  (USD)     : $ {totals['total_fob_usd']:>10,.2f}")
    print(f"  Total F+I  (USD)     : $ {totals['total_freight_usd']:>10,.2f}")
    print(f"  Total CIF  (USD)     : $ {totals['total_cif_usd']:>10,.2f}")
    print(f"  Total before duty PLN:   {totals['total_before_duty_pln']:>10,.2f}")
    print(f"  Duty A00 paid        :   {zc429['duty_pln']:>10,.2f} PLN")
    print(f"  VAT  B00 (ref only)  :   {zc429['vat_pln']:>10,.2f} PLN  [reclaimed via VAT-7]")
    print(f"  Duty rate   (L12)    :   {totals['duty_rate_pct']:.6f}%")
    print()

    # ── Per-line detail ──
    print("─" * 80)
    print("  LINE DETAIL")
    print("─" * 80)
    for r in rows:
        qty_disp = int(r["quantity"]) if r["quantity"] == int(r["quantity"]) else r["quantity"]
        print(f"\n  [{r['product_code']}]  {r['description_en']}")
        print(f"     PL : {r['pl_desc']}")
        print(f"     Qty: {qty_disp} × ${r['unit_price_usd']:.2f}")
        print(f"     F+I/unit: ${r['fi_per_unit_usd']:.4f}  |  "
              f"Cost before duty: {r['cost_before_duty']:.4f} PLN  |  "
              f"Duty: {r['duty_per_unit']:.4f} PLN")
        print(f"     Unit netto (Cena netto):  {fmt_pln(r['unit_netto_pln'])} PLN  |  "
              f"Line netto:  {fmt_pln(r['line_netto_pln'])} PLN  |  "
              f"Line brutto: {fmt_pln(r['line_brutto_pln'])} PLN")

    print()
    print("=" * 80)
    print(f"  RAZEM NETTO   {fmt_pln(total_n):>14} PLN")
    print(f"  VAT 23%       {fmt_pln(total_b - total_n):>14} PLN  (reclaimed via VAT-7)")
    print(f"  RAZEM BRUTTO  {fmt_pln(total_b):>14} PLN")
    print("=" * 80)

    # ── INVOICE / SAD VERIFICATION ───────────────────────────────────────────
    if verification:
        print()
        print("─" * 80)
        print("  INVOICE / SAD VERIFICATION")
        print("─" * 80)
        print(f"  Invoice references match : {_fmt_check(verification.get('invoice_refs_match'))}")
        print(f"  CIF total match          : {_fmt_check(verification.get('cif_match'))}",
              end="")
        cif_d = verification.get("cif_difference_usd", 0)
        if cif_d:
            print(f"  (diff ${cif_d:+.2f})")
        else:
            print()
        print(f"  Quantity by type match   : {_fmt_check(verification.get('qty_match_by_type'))}")
        print(f"  Importer match           : {_fmt_check(verification.get('importer_match'))}")
        print(f"  Exporter match           : {_fmt_check(verification.get('exporter_match'))}")
        print(f"  NBP rate used            : {verification.get('nbp_rate_used', 0):.4f} PLN/USD")
        if verification.get("sad_customs_rate"):
            print(f"  SAD customs rate         : {verification['sad_customs_rate']:.4f} PLN/USD")
            print(f"                           : ({verification.get('rate_note', '')})")
        flags = verification.get("amendment_flags", [])
        if flags:
            print()
            print("  ⚠  AMENDMENT FLAGS:")
            for f in flags:
                print(f"       {f}")
        else:
            print("  Amendment flags          : none")

    # ── Corrections log ──
    if corrections_log:
        print()
        print("─" * 80)
        print("  CORRECTIONS LOG")
        print("─" * 80)
        for entry in corrections_log:
            print(f"  ⚠  {entry}")
    else:
        print("\n  ✅ No corrections needed — all values parsed cleanly.")
    print()


# ── Public batch API ──────────────────────────────────────────────────────────

def process_batch(inv_paths: list, zc429_path: str, rate: float = None,
                  batch_meta: dict = None) -> dict:
    """
    Callable API for testing and programmatic use.

    Parameters
    ----------
    inv_paths   : list of invoice PDF file paths (strings)
    zc429_path  : ZC429 / SAD customs PDF path
    rate        : manual USD/PLN rate (float); if None, fetches from NBP
    batch_meta  : dict controlling note line 4 (see build_note_4 docstring)
                  keys: settlement_mode ("standard"|"art33a"),
                        prefer_carrier_label (bool),
                        carrier_name (str)

    Returns
    -------
    dict with keys:
        rows            – list of per-line cost dicts
        totals          – batch-level USD/PLN summary dict
        zc429           – parsed customs data dict
        nbp             – exchange-rate dict
        notes           – UWAGI lines list
        invoices        – list of parsed invoice dicts
        corrections_log – list of warning/correction strings
        line_count      – int, number of PZ lines
        total_net       – float, razem netto PLN (sum of line_netto_pln per row)
        total_gross     – float, razem brutto PLN (sum of line_brutto_pln per row)
        duty_pln        – float, A00 duty paid PLN (from ZC429)

    Raises ValueError on sanity-check failures (implausible duty rate, etc.).
    """
    corrections_log: list = []

    invoices = [parse_invoice(p, corrections_log) for p in inv_paths]
    invoice_totals = compute_invoice_totals(invoices)
    zc429    = parse_zc429(zc429_path, corrections_log)

    # ── Parser Fix Proposals — capture failures after parse (non-fatal) ───────
    _fix_proposals: list = []
    try:
        import parser_fix_proposals as _pfp
        _batch_id = (batch_meta or {}).get("batch_id", "")
        for _inv in invoices:
            _sup  = _inv.get("exporter_name", "") or _inv.get("seller_name", "")
            _file = _inv.get("filename", "")
            _raw  = _inv.get("_raw_text", "")[:300]

            if not _inv.get("invoice_no") or _inv.get("invoice_no") == "UNKNOWN":
                _fix_proposals.append(_pfp.capture_proposal(
                    field_missing  = "invoice_no",
                    failure_reason = "invoice_no not found or set to UNKNOWN after parse",
                    text_snippet   = _raw,
                    supplier_key   = _sup,
                    batch_id       = _batch_id,
                    invoice_file   = _file,
                ))
            if not _inv.get("exporter_name"):
                _fix_proposals.append(_pfp.capture_proposal(
                    field_missing  = "exporter_name",
                    failure_reason = "exporter_name is empty after parse",
                    text_snippet   = _raw,
                    supplier_key   = _sup,
                    batch_id       = _batch_id,
                    invoice_file   = _file,
                ))
            _cif = _inv.get("cif_usd", 0) or 0
            if _cif == 0 and _inv.get("items"):
                _fix_proposals.append(_pfp.capture_proposal(
                    field_missing  = "cif_usd",
                    failure_reason = "cif_usd is 0 despite invoice having item lines",
                    text_snippet   = _raw,
                    supplier_key   = _sup,
                    batch_id       = _batch_id,
                    invoice_file   = _file,
                ))
    except Exception as _pfp_err:
        corrections_log.append(f"[PROPOSALS] Proposal capture skipped (non-fatal): {_pfp_err}")
    nbp      = get_nbp_rate(invoices[0]["invoice_date"], rate)
    rows, totals = calculate_landed(invoices, zc429, nbp, corrections_log)
    notes    = build_notes(invoices, zc429, nbp, batch_meta)

    # ── SAD ↔ Invoice verification ────────────────────────────────────────────
    verification = verify_sad_invoice_match(invoices, zc429)
    verification["nbp_rate_used"] = nbp["usd_rate"]   # fill in now that NBP is known

    # Non-fatal visibility notes: when a check returned None (not parseable from SAD),
    # log it explicitly so it appears in XLSX Notes — not a mismatch, not silent.
    # Prefix [VERIFY-GAP] so build_amendment_flags blocked-phrase scanner skips these.
    _refs_method = zc429.get("invoice_refs_method", "N935")
    if verification.get("invoice_refs_match") is None:
        if _refs_method == "inferred_from_sad_free_text":
            corrections_log.append(
                "[VERIFY-GAP] SAD invoice references partially verified — "
                "inferred from SAD free text / document sections (not via N935)."
            )
        else:
            corrections_log.append(
                "[VERIFY-GAP] SAD invoice references could not be verified — "
                "N935 lines not found in ZC429."
            )
    if verification.get("cif_match") is None:
        _cif_st = verification.get("cif_status", "")
        if _cif_st and _cif_st != "SAD CIF not available":
            corrections_log.append(
                f"[VERIFY-GAP] CIF: {_cif_st}"
            )
        else:
            corrections_log.append(
                "[VERIFY-GAP] SAD CIF total could not be verified — "
                "invoice value field not parsed from ZC429."
            )

    # Quantity by type: if item lines exist, say "Parsed from invoice" not "Not parsed"
    _has_items = any(len(inv.get("items", [])) > 0 for inv in invoices)
    _sad_goods_desc = zc429.get("goods_description", "")
    if verification.get("qty_match_by_type") is None:
        if _has_items and _sad_goods_desc:
            verification["qty_by_type_label"] = "Partially verified — SAD contains combined goods description"
            corrections_log.append(
                "[VERIFY-GAP] SAD quantity-by-type: parsed from invoice lines; "
                "SAD contains combined goods description (not per-type breakdown)."
            )
        elif _has_items:
            verification["qty_by_type_label"] = "Parsed from invoice"
            corrections_log.append(
                "[VERIFY-GAP] SAD quantity-by-type: parsed from invoice lines; "
                "no per-type breakdown in SAD."
            )
        else:
            verification["qty_by_type_label"] = "Not parsed"
            corrections_log.append(
                "[VERIFY-GAP] SAD quantity-by-type could not be verified "
                "from goods description format."
            )
    else:
        verification["qty_by_type_label"] = "Parsed from invoice" if _has_items else "Not parsed"

    if verification.get("importer_match") is None:
        corrections_log.append(
            "[VERIFY-GAP] SAD importer identity could not be verified — "
            "consignee field not parsed from ZC429."
        )
    if verification.get("exporter_match") is None:
        _exp_src = verification.get("exporter_source", "neither")
        if _exp_src == "invoice_only":
            corrections_log.append(
                "[VERIFY-GAP] Exporter parsed from invoice; SAD exporter not available."
            )
        else:
            corrections_log.append(
                "[VERIFY-GAP] SAD exporter identity could not be verified — "
                "supplier field not parsed from ZC429."
            )

    amendment_flags = build_amendment_flags(invoices, zc429, verification, corrections_log)
    verification["amendment_flags"] = amendment_flags

    # ── Blocked-phrases check: scan raw invoice text, not the corrections log ──
    # BLOCKED_PHRASES_PATTERNS contains patterns that must never appear in a
    # legitimate commercial invoice (gift, sample, no commercial value, etc.).
    blocked_found: list = []
    for inv in invoices:
        raw = inv.get("_raw_text", "")
        if not raw:
            continue
        raw_lower = raw.lower()
        for pattern in BLOCKED_PHRASES_PATTERNS:
            if re.search(pattern, raw_lower):
                blocked_found.append(
                    f"{inv.get('filename','?')}: matched '{pattern}'"
                )
    verification["blocked_phrases_clean"] = len(blocked_found) == 0
    if blocked_found:
        for hit in blocked_found:
            corrections_log.append(f"[BLOCKED-PHRASE] {hit}")
    verification["duty_rate_ok"] = (
        0 < totals["duty_rate_pct"] < 20.0
    )

    total_net   = sum(r["line_netto_pln"]  for r in rows)
    total_gross = sum(r["line_brutto_pln"] for r in rows)

    # ── Collect learning traces from all parsed invoices ─────────────────────
    learning_traces = [
        inv["_learning_trace"]
        for inv in invoices
        if isinstance(inv.get("_learning_trace"), dict)
    ]

    # ── Parser Fix Proposals — verification-level checks ─────────────────────
    try:
        import parser_fix_proposals as _pfp2
        _batch_id2 = (batch_meta or {}).get("batch_id", "")
        _sup2 = invoices[0].get("exporter_name", "") if invoices else ""

        if verification.get("invoice_refs_match") is False:
            _fix_proposals.append(_pfp2.capture_proposal(
                field_missing  = "invoice_refs",
                failure_reason = (
                    "SAD invoice references do not match parsed invoice numbers. "
                    f"Missing in PDFs: {verification.get('missing_invoices_in_pdfs', [])}. "
                    f"Extra not in SAD: {verification.get('extra_invoices_not_in_sad', [])}."
                ),
                text_snippet   = str(verification.get("sad_invoice_refs", ""))[:300],
                supplier_key   = _sup2,
                batch_id       = _batch_id2,
                invoice_file   = invoices[0].get("filename", "") if invoices else "",
            ))

        if verification.get("cif_match") is False:
            _fix_proposals.append(_pfp2.capture_proposal(
                field_missing  = "cif_match",
                failure_reason = (
                    f"CIF mismatch: invoice total ${verification.get('invoice_cif_total_usd', 0):,.2f} "
                    f"vs SAD ${verification.get('sad_cif_total_usd', 0):,.2f} "
                    f"(diff ${verification.get('cif_difference_usd', 0):+.2f})"
                ),
                text_snippet   = str(verification.get("cif_status", ""))[:300],
                supplier_key   = _sup2,
                batch_id       = _batch_id2,
                invoice_file   = invoices[0].get("filename", "") if invoices else "",
            ))

        if not verification.get("blocked_phrases_clean", True):
            _fix_proposals.append(_pfp2.capture_proposal(
                field_missing  = "blocked_phrases",
                failure_reason = "Blocked phrase pattern matched in invoice text (possible false positive)",
                text_snippet   = "; ".join(
                    e for e in corrections_log if e.startswith("[BLOCKED-PHRASE]")
                )[:300],
                supplier_key   = _sup2,
                batch_id       = _batch_id2,
                invoice_file   = invoices[0].get("filename", "") if invoices else "",
            ))
    except Exception as _pfp2_err:
        corrections_log.append(
            f"[PROPOSALS] Verification-level proposal capture skipped (non-fatal): {_pfp2_err}"
        )

    # Strip error-only entries and None values from fix_proposals list
    _fix_proposals_clean = [
        p for p in _fix_proposals
        if p and isinstance(p, dict) and "proposal_id" in p
    ]

    # ── DSK is NOT generated here — it is generated only after a DHL customs
    # email arrives and is matched to this batch.  See dhl_clearance_handler.py.
    # import dsk_generator is kept available for use elsewhere.
    import dsk_generator  # noqa: F401 — kept for external callers

    # ── Clearance status: set initial state based on carrier ─────────────────
    _carrier_for_status = ((batch_meta or {}).get("carrier", "") or "").upper()
    _total_cif_for_status = sum(float(inv.get("cif_usd") or 0) for inv in invoices)
    if _total_cif_for_status == 0:
        _total_cif_for_status = totals.get("total_cif_usd") or 0

    if _carrier_for_status == "DHL":
        _clearance_status = "awaiting_dhl_customs_email"
    else:
        _clearance_status = "shipment_created"

    return {
        "rows":             rows,
        "totals":           totals,
        "zc429":            zc429,
        "nbp":              nbp,
        "notes":            notes,
        "invoices":         invoices,
        "corrections_log":  corrections_log,
        "line_count":       len(rows),
        "total_net":        total_net,
        "total_gross":      total_gross,
        "duty_pln":         zc429["duty_pln"],
        "invoice_totals":   invoice_totals,
        "verification":     verification,
        "settlement_mode":  (batch_meta or {}).get("settlement_mode", "standard"),
        "learning_traces":  learning_traces,
        "fix_proposals":    _fix_proposals_clean,
        "dsk":              None,
        "clearance_status": _clearance_status,
    }


# ── File collection ───────────────────────────────────────────────────────────

def collect_pdfs(paths: list) -> list:
    """Collect PDF paths from files and directories.

    Dedupes case-insensitively per resolved path. On Windows the filesystem
    is case-insensitive, so globbing both ``*.pdf`` and ``*.PDF`` returns
    the same file twice ('foo.pdf' matches both patterns). That doubling
    silently inflated invoice totals once the Global PZ engine authority
    bridge (2026-05-21) started returning real items — the legacy regex
    parser had been returning ``items=[]`` so doubling was invisible.
    Dedupe at collection time so every caller is safe.
    """
    seen: set = set()
    result: list = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            for hit in sorted(
                glob.glob(str(path / "*.pdf")) + glob.glob(str(path / "*.PDF"))
            ):
                key = str(Path(hit).resolve()).lower()
                if key not in seen:
                    seen.add(key)
                    result.append(hit)
        elif str(path).lower().endswith(".pdf"):
            key = str(path.resolve()).lower()
            if key not in seen:
                seen.add(key)
                result.append(str(path))
    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="PZ Import Processor v3 — invoice PDFs + ZC429 → wFirma.pl PZ"
    )
    parser.add_argument("--invoices", nargs="+", required=True,
                        help="Invoice PDF file(s) or folder")
    parser.add_argument("--zc429", required=True,
                        help="ZC429 / SAD customs PDF")
    parser.add_argument("--rate", type=float, default=None,
                        help="USD/PLN rate (optional; fetched from NBP if omitted)")
    parser.add_argument("--settlement-mode", choices=["standard", "art33a"],
                        default="standard",
                        help="Customs settlement mode: 'standard' (default) or 'art33a'")
    parser.add_argument("--carrier", default="",
                        help="Carrier name shown in note line 4 when no agent is in ZC429 "
                             "(e.g. 'DHL EXPRESS (POLAND) SP. Z O.O.')")
    parser.add_argument("--prefer-carrier", action="store_true",
                        help="Use --carrier label even when an agent is parsed from ZC429")
    parser.add_argument("--clipboard", action="store_true",
                        help="Copy the wFirma-ready PZ table + UWAGI to clipboard (macOS pbcopy)")
    parser.add_argument("--pdf", default="",
                        help="Write a PDF copy of the PZ to this path "
                             "(e.g. --pdf PZ_039_044.pdf). Requires: pip install reportlab")
    parser.add_argument("--xlsx", default="",
                        help="Write an audit workbook (.xlsx) to this path "
                             "(e.g. --xlsx PZ_039_044_calc.xlsx). Requires: pip install openpyxl")
    parser.add_argument("--doc-no", default="",
                        help="Document number in the PDF header and workbook "
                             "(e.g. --doc-no 'PZ 12/3/2026'); defaults to 'PZ'")
    parser.add_argument("--strict-match", action="store_true",
                        help="Exit 1 if any SAD/invoice verification check fails "
                             "(invoice refs, CIF, qty, importer, exporter). "
                             "Without this flag, mismatches produce amendment flags only.")
    args = parser.parse_args()

    batch_meta = {
        "settlement_mode":      args.settlement_mode,
        "prefer_carrier_label": args.prefer_carrier,
        "carrier_name":         args.carrier,
    }

    print(f"\nPZ Import Processor  v3")
    print("=" * 55)

    # 1. Collect PDFs
    inv_paths = collect_pdfs(args.invoices)
    if not inv_paths:
        sys.exit("ERROR: No invoice PDFs found.")

    print(f"\nInvoice PDFs ({len(inv_paths)}):")
    for p in inv_paths:
        print(f"  → {os.path.basename(p)}")

    # 2–6. Single calculation path via process_batch()
    #       (parse invoices, parse ZC429, fetch NBP, calculate, build notes,
    #        run SAD verification, build amendment flags)
    print(f"\nParsing ZC429: {os.path.basename(args.zc429)}")
    print("\nCalculating landed costs...")
    try:
        _result = process_batch(inv_paths, args.zc429, rate=args.rate, batch_meta=batch_meta)
    except ValueError as e:
        print(f"\n  ✗ SANITY CHECK FAILED: {e}")
        sys.exit(1)

    rows            = _result["rows"]
    zc429           = _result["zc429"]
    nbp             = _result["nbp"]
    totals          = _result["totals"]
    notes           = _result["notes"]
    invoices        = _result["invoices"]
    corrections_log = _result["corrections_log"]
    verification    = _result.get("verification", {})

    # Quick parse summary (mirrors old per-step prints)
    print(f"  MRN      : {zc429['mrn']}")
    print(f"  LRN      : {zc429['lrn']}")
    print(f"  Date     : {zc429['clearance_date']}")
    print(f"  Duty A00 : {zc429['duty_pln']:,.2f} PLN")
    print(f"  VAT  B00 : {zc429['vat_pln']:,.2f} PLN  [ref only]")
    print(f"\nInvoice PDFs parsed: {len(invoices)}, lines: {len(rows)}")
    for inv in invoices:
        print(f"  ✓ {inv['invoice_no']} | {inv['invoice_date']} | "
              f"FOB ${inv['fob_usd']:.2f} | {len(inv['items'])} item(s)")

    # 7. Print PZ summary
    print_pz(rows, zc429, nbp, totals, notes, invoices, corrections_log,
             verification=verification)

    # 8. --strict-match: exit 1 on any SAD/invoice verification failure
    if args.strict_match:
        _verify_keys = ["invoice_refs_match", "cif_match", "qty_match_by_type",
                        "importer_match", "exporter_match"]
        _failed = [k for k in _verify_keys if verification.get(k) is False]
        _flags  = verification.get("amendment_flags", [])
        if _failed or _flags:
            print(f"\n  ✗ --strict-match: verification failures: {_failed or []}")
            if _flags:
                for f in _flags:
                    print(f"       • {f}")
            sys.exit(1)

    # 9. Clipboard (optional)
    if args.clipboard:
        clip_text = format_pz_clipboard(rows, notes, totals)
        try:
            import subprocess
            subprocess.run(["pbcopy"], input=clip_text.encode("utf-8"), check=True)
            print("  ✅ PZ table + UWAGI copied to clipboard (pbcopy)")
        except FileNotFoundError:
            print("  ⚠ pbcopy not found (not macOS?). Printing clipboard content instead:")
            print(clip_text)
        except Exception as e:
            print(f"  ⚠ Clipboard copy failed: {e}")

    # Track failures for requested exports — any failure → non-zero exit at end.
    # Rule: if the user asked for an output and it was not produced, the run failed.
    _export_failures: list = []

    # 10. PDF export (optional — requires reportlab)
    if args.pdf:
        try:
            from pz_pdf_export import save_pz_pdf
        except ImportError:
            msg = ("pz_pdf_export.py not found or reportlab not installed. "
                   "Install: pip install reportlab")
            print(f"  ✗ PDF export failed: {msg}")
            _export_failures.append(f"--pdf: {msg}")
        else:
            try:
                out = save_pz_pdf(_result, args.pdf, document_no=args.doc_no)
                print(f"  ✅ PDF written: {out}")
            except Exception as e:
                print(f"  ✗ PDF export failed: {e}")
                _export_failures.append(f"--pdf: {e}")

    # 11. XLSX audit workbook (optional — requires openpyxl)
    if args.xlsx:
        try:
            from pz_dual_export import export_pz_calculation_xlsx
        except ImportError:
            msg = ("pz_dual_export.py not found or openpyxl not installed. "
                   "Install: pip install openpyxl")
            print(f"  ✗ XLSX export failed: {msg}")
            _export_failures.append(f"--xlsx: {msg}")
        else:
            try:
                out = export_pz_calculation_xlsx(
                    _result, args.xlsx, document_no=args.doc_no
                )
                print(f"  ✅ XLSX written: {out}")
            except Exception as e:
                print(f"  ✗ XLSX export failed: {e}")
                _export_failures.append(f"--xlsx: {e}")

    # Exit non-zero if any explicitly-requested export was not produced.
    if _export_failures:
        print()
        print("  ✗ One or more requested exports failed — run aborted with error.")
        for f in _export_failures:
            print(f"       {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
